from __future__ import annotations

import asyncio
import json
from typing import Any

from strands.types.events import ToolResultEvent
from strands.types.tools import AgentTool, ToolSpec

from agent.tool_specs import TOOL_SPECS

_JSON_TYPES = {str: "string", int: "integer"}


class ToolCallCounter:
    """Shared per-turn counter. The runner resets it before each user turn."""

    def __init__(self, limit: int):
        self.limit = int(limit)
        self.count = 0

    def reset(self) -> None:
        self.count = 0


def build_input_schema(tool_name: str) -> dict:
    """JSON schema from tool_specs only: never customer_id or a token."""
    spec = TOOL_SPECS[tool_name]
    properties = {
        name: {"type": _JSON_TYPES[expected]}
        for name, expected in spec["allowed"].items()
    }
    return {
        "type": "object",
        "properties": properties,
        "required": sorted(spec["required"]),
    }


class StrandsRuntimeTool(AgentTool):
    """One Strands tool per enabled tools.yaml entry, backed by ToolRuntime."""

    def __init__(
        self,
        name: str,
        description: str,
        runtime,
        logger,
        counter: ToolCallCounter,
        query_rewriter=None,
        observer=None,
        result_observer=None,
    ):
        super().__init__()
        self._name = name
        self._description = description
        self._runtime = runtime
        self._logger = logger
        self._counter = counter
        self._query_rewriter = query_rewriter
        self._observer = observer
        self._result_observer = result_observer

    @property
    def tool_name(self) -> str:
        return self._name

    @property
    def tool_spec(self) -> ToolSpec:
        return {
            "name": self._name,
            "description": self._description,
            "inputSchema": {"json": build_input_schema(self._name)},
        }

    @property
    def tool_type(self) -> str:
        return "python"

    async def stream(self, tool_use, invocation_state: dict[str, Any], **kwargs: Any):
        args = dict(tool_use.get("input") or {})
        tool_use_id = tool_use.get("toolUseId", "")
        self._counter.count += 1

        if self._counter.count > self._counter.limit:
            envelope = {
                "ok": False,
                "tool": self._name,
                "error": "too_many_tool_calls",
                "message": "too many tool calls in one turn",
            }
            self._log_cap(args, envelope)
        else:
            if self._name == "search_policy":
                args = self._rewrite_query(args)
            envelope = await asyncio.to_thread(self._runtime.call, self._name, **args)

        status = "success" if envelope.get("ok") else "error"
        self._notify(status, envelope)
        self._notify_result(status, args, envelope)
        yield ToolResultEvent(
            {
                "toolUseId": tool_use_id,
                "status": status,
                "content": [{"json": envelope}],
            }
        )

    def _notify(self, status: str, envelope: dict) -> None:
        """Optional per-runner observer. Inputs and results are never passed."""
        if self._observer is None:
            return
        # A real proposal is the only successful result carrying a pending token.
        data = envelope.get("data") if isinstance(envelope.get("data"), dict) else {}
        is_proposal = status == "success" and bool(data.get("pending_token"))
        try:
            self._observer(self._name, status, is_proposal)
        except Exception as exc:
            try:
                self._logger.log(
                    session_id=getattr(self._runtime.session, "session_id", ""),
                    tool="tool_observer_error",
                    inputs={"tool": self._name},
                    ok=False,
                    error={"code": type(exc).__name__, "message": str(exc)},
                    duration_ms=0,
                )
            except Exception:
                pass

    def _notify_result(self, status: str, args: dict, envelope: dict) -> None:
        """Server-side result hook. Raw values never leave this process."""
        if self._result_observer is None:
            return
        try:
            self._result_observer(self._name, status, args, envelope)
        except Exception as exc:
            try:
                self._logger.log(
                    session_id=getattr(self._runtime.session, "session_id", ""),
                    tool="tool_result_observer_error",
                    inputs={"tool": self._name},
                    ok=False,
                    error={"code": type(exc).__name__, "message": str(exc)},
                    duration_ms=0,
                )
            except Exception:
                pass

    def _rewrite_query(self, args: dict) -> dict:
        """Rewrite the search query before retrieval; never break retrieval."""
        query = args.get("query")
        if self._query_rewriter is None or not isinstance(query, str) or not query.strip():
            return args
        try:
            from rag.query_rewrite import rewrite_for_search

            result = rewrite_for_search(
                query,
                rewriter=self._query_rewriter,
                logger=self._logger,
                session_id=getattr(self._runtime.session, "session_id", ""),
                config=getattr(self._runtime, "config", None),
            )
        except Exception:
            return args
        if result.applied and result.ok and str(result.rewritten).strip():
            args["query"] = result.rewritten
        else:
            args["query"] = query
        return args

    def _log_cap(self, args: dict, envelope: dict) -> None:
        try:
            self._logger.log(
                session_id=self._runtime.session.session_id,
                tool=self._name,
                inputs=args,
                ok=False,
                error={"code": envelope["error"], "message": envelope["message"]},
                duration_ms=0,
            )
        except Exception:
            pass


def build_strands_tools(
    cfg,
    runtime,
    logger=None,
    counter: ToolCallCounter | None = None,
    query_rewriter=None,
    observer=None,
    result_observer=None,
):
    """Build AgentTool instances for enabled tools; return (tools, counter)."""
    logger = logger or runtime.logger
    counter = counter or ToolCallCounter(cfg.settings.agent.max_tool_calls_per_turn)
    if query_rewriter is None:
        query_rewriter = _default_query_rewriter(cfg)
    tools: list[AgentTool] = []
    for name, tool_cfg in cfg.tools.items():
        if name not in TOOL_SPECS:
            continue
        if not getattr(tool_cfg, "enabled", False):
            continue
        tools.append(
            StrandsRuntimeTool(
                name,
                tool_cfg.description,
                runtime,
                logger,
                counter,
                query_rewriter,
                observer=observer,
                result_observer=result_observer,
            )
        )
    return tools, counter


def _default_query_rewriter(cfg, llm=None):
    """Passthrough when the config has no query_rewrite block (e.g. tests)."""
    from rag.query_rewrite import PassthroughQueryRewriter

    settings = getattr(cfg, "settings", None)
    rag = getattr(settings, "rag", None)
    if getattr(rag, "query_rewrite", None) is None:
        return PassthroughQueryRewriter()
    from core.factories import create_query_rewriter

    return create_query_rewriter(cfg, llm)
