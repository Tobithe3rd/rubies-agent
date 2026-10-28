from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Optional

from core.config import AppConfig, ConfigError, QueryRewriteConfig
from core.factories import register
from core.interfaces import HealthStatus, LLMProvider, QueryRewriter, RewriteResult

logger = logging.getLogger("rubies.query_rewrite")


def _one_line(text: str) -> str:
    return text.strip().strip("\r\n").strip()


@register("query_rewriter", "passthrough")
class PassthroughQueryRewriter(QueryRewriter):
    """Used when query rewriting is disabled. Returns the query unchanged."""

    def __init__(self, cfg: Optional[QueryRewriteConfig] = None, llm: Any = None):
        self.cfg = cfg
        self.llm = llm

    def describe(self) -> str:
        return "passthrough:disabled"

    def healthcheck(self) -> HealthStatus:
        return HealthStatus(self.describe(), True, "query rewriting disabled")

    def rewrite(self, query: str) -> RewriteResult:
        text = query if isinstance(query, str) else ""
        return RewriteResult(
            rewritten=text,
            applied=False,
            ok=True,
            duration_ms=0,
            model_id=None,
            error=None,
            fallback_used=False,
            original_len=len(text),
            rewritten_len=len(text),
        )


@register("query_rewriter", "llm")
class LLMQueryRewriter(QueryRewriter):
    """Rewrites a customer message with one separate, small LLM call.

    The customer message is only ever passed as data (the user message); the
    role, rules and few-shot examples live in the prompt file. Output is
    validated (non-empty, one line, within max_output_chars) before it is used;
    anything else falls back to the original query. rewrite() never raises.
    """

    def __init__(self, cfg: QueryRewriteConfig, llm: LLMProvider):
        self.cfg = cfg
        self.llm = llm
        if llm is None:
            raise ConfigError(
                "rag.query_rewrite.implementation 'llm' requires the llm component"
            )
        self.model_id = cfg.model_id or getattr(llm, "model_id", None) or None
        self.prompt_text = self._load_prompt(cfg.prompt_path)

    @staticmethod
    def _load_prompt(prompt_path: str) -> str:
        key = "rag.query_rewrite.prompt_path"
        path = Path(prompt_path)
        if not path.is_file():
            raise ConfigError(f"{key} not found: {prompt_path}")
        text = path.read_text(encoding="utf-8")
        if not text.strip():
            raise ConfigError(f"{key} is empty: {prompt_path}")
        return text

    def describe(self) -> str:
        model = self.model_id or "llm-default"
        return f"llm:query_rewrite:model={model}"

    def healthcheck(self) -> HealthStatus:
        try:
            health = self.llm.healthcheck()
        except Exception as exc:  # a broken llm must not crash startup
            return HealthStatus(self.describe(), False, type(exc).__name__)
        detail = "prompt loaded" if health.ok else health.detail
        return HealthStatus(self.describe(), health.ok, detail)

    def _complete(self, user_prompt: str) -> str:
        # complete() has no timeout argument, so bound it here.
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(
                self.llm.complete,
                user_prompt,
                self.prompt_text,
                self.cfg.temperature,
                self.cfg.max_tokens,
            )
            return future.result(timeout=self.cfg.timeout_seconds)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)

    def rewrite(self, query: str) -> RewriteResult:
        start = time.monotonic()
        text = query if isinstance(query, str) else ""
        original_len = len(text)

        def fail(code: str, detail: Optional[str] = None) -> RewriteResult:
            message = code if not detail else f"{code}: {detail}"
            return RewriteResult(
                rewritten=text,
                applied=False,
                ok=False,
                duration_ms=int((time.monotonic() - start) * 1000),
                model_id=self.model_id,
                error=message,
                fallback_used=True,
                original_len=original_len,
                rewritten_len=original_len,
            )

        if not text.strip():
            return fail("empty_query")
        if original_len > self.cfg.max_input_chars:
            return fail("input_too_long")

        try:
            raw = self._complete(f"Input: {text}\nOutput:")
        except FutureTimeout:
            return fail("timeout")
        except Exception as exc:
            detail = str(exc)
            if text and text in detail:
                detail = detail.replace(text, "***")
            return fail(type(exc).__name__, detail)

        candidate = _one_line(raw if isinstance(raw, str) else "")
        if candidate.lower().startswith("output:"):
            candidate = _one_line(candidate[len("output:"):])

        if not candidate:
            return fail("empty_output")
        if "\n" in candidate or "\r" in candidate:
            return fail("multiline_output")
        if len(candidate) > self.cfg.max_output_chars:
            return fail("output_too_long")

        return RewriteResult(
            rewritten=candidate,
            applied=True,
            ok=True,
            duration_ms=int((time.monotonic() - start) * 1000),
            model_id=self.model_id,
            error=None,
            fallback_used=False,
            original_len=original_len,
            rewritten_len=len(candidate),
        )


def rewrite_for_search(
    query: str,
    *,
    rewriter: QueryRewriter,
    logger: Any = None,
    session_id: str = "",
    config: Optional[AppConfig] = None,
) -> RewriteResult:
    """Rewrite one query for search_policy, logging one JSONL event line.

    Never raises; on any problem the original query is returned in
    `rewritten`. Retrieval must never be broken by a rewrite failure.
    """
    try:
        result = rewriter.rewrite(query)
    except Exception as exc:  # defensive: implementations must never raise
        text = query if isinstance(query, str) else ""
        result = RewriteResult(
            rewritten=text,
            applied=False,
            ok=False,
            duration_ms=0,
            model_id=None,
            error=type(exc).__name__,
            fallback_used=True,
            original_len=len(text),
            rewritten_len=len(text),
        )

    if result.fallback_used and not result.ok:
        logger_ = logging.getLogger("rubies.query_rewrite")
        logger_.warning("query_rewrite fallback: %s", result.error)

    _log_event(logger, session_id, result, config, query)
    return result


def _log_event(
    logger: Any,
    session_id: str,
    result: RewriteResult,
    config,
    original: str,
) -> None:
    if logger is None:
        return

    log_text = False
    if config is not None:
        settings = getattr(config, "settings", None)
        rag = getattr(settings, "rag", None)
        qr = getattr(rag, "query_rewrite", None)
        logging_cfg = getattr(settings, "logging", None)
        if qr is not None and logging_cfg is not None:
            log_text = bool(qr.log_text or logging_cfg.debug)

    fields: dict[str, Any] = {
        "applied": result.applied,
        "ok": result.ok,
        "fallback_used": result.fallback_used,
        "original_len": result.original_len,
        "rewritten_len": result.rewritten_len,
        "model_id": result.model_id,
        "error": result.error,
    }
    # Text is only ever written when log_text (or debug) is on; never by default.
    if log_text:
        fields["original_text"] = original
        fields["rewritten_text"] = result.rewritten

    try:
        if hasattr(logger, "log_event"):
            logger.log_event(
                "query_rewrite",
                session_id=session_id,
                duration_ms=result.duration_ms,
                fields=fields,
            )
        else:
            logger.log(
                session_id=session_id,
                tool="query_rewrite",
                inputs={},
                ok=bool(result.ok),
                result=fields,
                duration_ms=result.duration_ms,
            )
    except Exception as exc:
        # Logging must never break retrieval.
        logging.getLogger("rubies.query_rewrite").warning(
            "could not log query rewrite: %s", exc
        )