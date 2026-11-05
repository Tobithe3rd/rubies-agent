from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from pathlib import Path
from typing import Any, Callable, Optional

from agent.handoff_sanitise import sanitise
from agent.handoff_triggers import REASON_CODES, Trigger, _language, _tokens, requested_trigger

_FALLBACKS = {
    "user_requested": "Customer asked to speak to a human agent.",
    "upset_user": "Customer is upset and needs a human agent.",
    "low_confidence": "Customer needs help after repeated failed policy searches.",
    "repeated_errors": "Customer needs help after repeated tool errors.",
    "failed_verification": "Customer needs help after repeated failed identity checks.",
    "other": "Customer needs a human agent.",
}


def _done_label(tools: Optional[Any], name: str) -> Optional[str]:
    if tools is None or not hasattr(tools, "get"):
        return None
    tool = tools.get(name)
    return getattr(getattr(tool, "labels", None), "done", None)


class HandoffCoordinator:
    """Pure handoff decisions for one session; no network I/O and no asyncio.

    `pre_turn` returns a user_requested trigger unless the turn carries
    attachments. `post_turn` reads the session counters defensively and returns
    at most one counter trigger per session. Retrieval failures use the
    consecutive counter (reset by a successful search); tool errors and failed
    verifications use their total counters. A trigger is returned once and a
    failed forced handoff is never retried automatically.

    `record_outcome` keeps only the last 12 done labels and ignores
    handoff_to_human. `summary` calls the complete callable under a timeout and
    falls back to a deterministic, customer-text-free summary on any failure.
    Raw customer text is used only for user_requested, and never on a turn that
    carried attachments.
    """

    def __init__(self, session, cfg, tools: Optional[Any] = None):
        self.session = session
        settings = getattr(cfg, "settings", cfg)
        self.cfg = getattr(settings, "handoff", settings)
        self.tools = tools if tools is not None else getattr(cfg, "tools", None)
        self._handed_off = bool(getattr(session, "handed_off", False))
        self._language = "en"
        self._outcomes: list[str] = []
        self._raw_text: Optional[str] = None
        self._raw_had_attachments = False
        self._prompt = self._load_prompt()

    def _load_prompt(self) -> str:
        try:
            path = Path(self.cfg.summary_prompt_path)
            return path.read_text(encoding="utf-8") if path.is_file() else ""
        except OSError:
            return ""

    def _mark_handed_off(self) -> None:
        self._handed_off = True
        try:
            setattr(self.session, "handed_off", True)
        except Exception:
            pass

    def _secrets(self) -> list[str]:
        values = [
            getattr(self.session, "token", None),
            getattr(self.session, "session_token", None),
            getattr(self.session, "pending_token", None),
        ]
        pending = getattr(self.session, "pending", None)
        if isinstance(pending, dict):
            values.extend(pending.keys())
        elif isinstance(pending, (list, tuple, set)):
            values.extend(pending)
        return [value for value in values if isinstance(value, str) and value]

    def pre_turn(self, text: str, has_attachments: Optional[bool] = None) -> Optional[Trigger]:
        if has_attachments is None:
            has_attachments = bool(getattr(self.session, "turn_has_attachments", False))
        if has_attachments:
            self._raw_text = None
            self._raw_had_attachments = True
        else:
            self._raw_text = text if isinstance(text, str) else None
            self._raw_had_attachments = False
        self._language = _language(_tokens(text), self.cfg)
        if self._handed_off or has_attachments:
            return None
        trigger = requested_trigger(text, self.cfg)
        if trigger is not None:
            self._mark_handed_off()
        return trigger

    def post_turn(self) -> Optional[Trigger]:
        if self._handed_off:
            return None
        reason = None
        if getattr(self.session, "tool_error_count", 0) >= self.cfg.max_repeated_tool_errors:
            reason = "repeated_errors"
        elif getattr(self.session, "consecutive_failed_retrievals", 0) >= self.cfg.max_failed_retrievals:
            reason = "low_confidence"
        elif getattr(self.session, "failed_verifications", 0) >= self.cfg.max_failed_verifications:
            reason = "failed_verification"
        if reason is None:
            return None
        self._mark_handed_off()
        return Trigger(reason, self._language, "counter")

    def record_outcome(self, label: str) -> None:
        if not isinstance(label, str) or not label.strip():
            return
        if label == "handoff_to_human":
            return
        if hasattr(self.tools, "get") and self.tools.get(label):
            label = _done_label(self.tools, label) or label
        self._outcomes = (self._outcomes + [label])[-12:]

    @property
    def outcomes(self) -> list[str]:
        return list(self._outcomes)

    def fallback_summary(self, trigger: Trigger) -> str:
        parts = [_FALLBACKS.get(trigger.reason, _FALLBACKS["other"])]
        last4 = getattr(self.session, "phone_last4", None)
        if last4:
            parts.append(f"Phone ending {last4}.")
        if self._outcomes:
            parts.append("Recent steps: " + "; ".join(self._outcomes) + ".")
        return sanitise(
            " ".join(parts), mode="strict", secrets=self._secrets(), tools=self.tools
        )

    def _context(self, trigger: Trigger, text: Optional[str]) -> str:
        parts = [f"Reason: {trigger.reason}"]
        name = getattr(self.session, "customer_name", None)
        if name:
            parts.append(f"Customer name: {name}")
        last4 = getattr(self.session, "phone_last4", None)
        if last4:
            parts.append(f"Phone ending: {last4}")
        if self._outcomes:
            parts.append("Steps already completed: " + "; ".join(self._outcomes))
        if trigger.reason == "user_requested":
            raw = self._raw_text if text is None else text
            attached = self._raw_had_attachments or bool(
                getattr(self.session, "turn_has_attachments", False)
            )
            if raw and not attached:
                safe = sanitise(
                    raw, mode="strict", secrets=self._secrets(), tools=self.tools
                )
                parts.append("Customer's words: " + safe)
        return "\n".join(parts)

    @staticmethod
    def _invoke_complete(complete: Callable[..., Any], prompt: str, system: str,
                         max_tokens: int) -> Any:
        try:
            params = list(inspect.signature(complete).parameters.values())
        except (TypeError, ValueError):
            return complete(prompt, system, 0.2, max_tokens)
        positional = [
            p for p in params
            if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)
        ]
        if any(p.kind == p.VAR_POSITIONAL for p in params) or len(positional) >= 4:
            return complete(prompt, system, 0.2, max_tokens)
        if len(positional) == 3:
            return complete(prompt, system, 0.2)
        if len(positional) == 2:
            return complete(prompt, system)
        if len(positional) == 1:
            return complete(prompt)
        return complete()

    def summary(self, trigger: Trigger, complete: Optional[Callable[..., Any]] = None,
                text: Optional[str] = None) -> str:
        if complete is not None and not callable(complete):
            complete, text = text, complete
        if complete is None or not self._prompt.strip():
            return self.fallback_summary(trigger)
        prompt = self._context(trigger, text)
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(
                self._invoke_complete, complete, prompt, self._prompt,
                self.cfg.summary_max_tokens,
            )
            raw = future.result(timeout=self.cfg.summary_timeout_seconds)
        except (FutureTimeout, Exception):
            return self.fallback_summary(trigger)
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        if not isinstance(raw, str) or not raw.strip():
            return self.fallback_summary(trigger)
        cleaned = sanitise(
            raw, mode="strict", secrets=self._secrets(), tools=self.tools
        )
        return cleaned or self.fallback_summary(trigger)

    def force(self, trigger: Trigger, complete: Optional[Callable[..., Any]],
              call_tool: Callable[..., Any]) -> Any:
        """Run a forced handoff once; failures are swallowed and not retried."""
        if isinstance(trigger, str):
            trigger = Trigger(trigger, self._language, "forced")
        self._mark_handed_off()
        summary = self.summary(trigger, complete)
        try:
            return call_tool(
                "handoff_to_human",
                {"summary": summary, "reason": trigger.reason},
            )
        except Exception:
            return None
