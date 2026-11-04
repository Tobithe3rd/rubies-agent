from __future__ import annotations

import asyncio
import sys
import time
from typing import Any

from agent.prompts import load_system_prompt
from agent.strands_tools import build_strands_tools

# Fixed reply for empty/whitespace input: no model call, no turn started.
EMPTY_MESSAGE_REPLY = "Please type a message so I can help."

# Network failures where a retry is worth it (botocore names, possibly wrapped).
RETRYABLE_ERROR_NAMES = {
    "EndpointConnectionError",
    "ConnectTimeoutError",
    "ReadTimeoutError",
    "ConnectionError",
    "ConnectionClosedError",
    "ProxyConnectionError",
}


def is_retryable_error(exc: BaseException) -> bool:
    """True for connection/timeout errors, checking wrapped causes too."""
    seen = set()
    while exc is not None and id(exc) not in seen:
        seen.add(id(exc))
        if type(exc).__name__ in RETRYABLE_ERROR_NAMES:
            return True
        exc = exc.__cause__ or exc.__context__
    return False


class AgentRunner:
    """Runs the Strands agent for one conversation session.

    The model never sees the session token or customer_id: tools call the
    validated ToolRuntime, which injects the token from SessionState.
    """

    def __init__(self, config, runtime, llm, system_prompt: str | None = None, query_rewriter=None,
                 tool_observer=None, tool_result_observer=None):
        from strands import Agent
        from strands.agent.conversation_manager import SlidingWindowConversationManager

        self.config = config
        self.runtime = runtime
        self.session = runtime.session
        self.llm = llm
        self.logger = runtime.logger
        self.system_prompt = system_prompt or load_system_prompt(config)

        from agent.strands_tools import _default_query_rewriter

        self.query_rewriter = query_rewriter or _default_query_rewriter(config, llm)
        self.tool_observer = tool_observer
        self.tool_result_observer = tool_result_observer
        self.tools, self.counter = build_strands_tools(
            config, runtime, self.logger, query_rewriter=self.query_rewriter,
            observer=self._notify_tool, result_observer=self._notify_tool_result,
        )
        model = llm.get_model() if hasattr(llm, "get_model") else llm
        self.agent = Agent(
            model=model,
            tools=self.tools,
            system_prompt=self.system_prompt,
            conversation_manager=SlidingWindowConversationManager(
                window_size=int(config.settings.agent.max_history_messages)
            ),
            callback_handler=None,
            name="rubies-support-agent",
        )

    def _notify_tool(self, tool_name: str, status: str, is_proposal: bool) -> None:
        """Forward to the optional per-runner observer.

        strands_tools owns the safety boundary: it logs and swallows observer
        errors, so a broken observer can never change a tool result or a turn.
        """
        observer = getattr(self, "tool_observer", None)
        if observer is not None:
            observer(tool_name, status, is_proposal)

    def _notify_tool_result(self, tool_name: str, status: str, args: dict, envelope: dict) -> None:
        observer = getattr(self, "tool_result_observer", None)
        if observer is not None:
            observer(tool_name, status, args, envelope)

    def _setup_turn(self, text: str, has_attachments: bool = False) -> bool:
        # Pre-turn setup: once per non-empty message. Returns False for empty.
        if text is None or not str(text).strip():
            return False
        self.session.start_turn(has_attachments=has_attachments)
        self.counter.reset()
        return True

    def handle_message(self, text: str, has_attachments: bool = False) -> str:
        if not self._setup_turn(text, has_attachments=has_attachments):
            return EMPTY_MESSAGE_REPLY
        attempts = self._attempts()
        for attempt in range(1, attempts + 1):
            try:
                result = self.agent(text)
                return self._final_text(result)
            except Exception as exc:
                if attempt < attempts and is_retryable_error(exc):
                    self._log_agent_error(exc, tool="agent_retry")
                    time.sleep(self._backoff())
                    continue
                self._log_agent_error(exc)
                return self._error_reply(exc)

    async def stream_events(self, text, has_attachments: bool = False):
        if not self._setup_turn(text, has_attachments=has_attachments):
            # Empty message: yield nothing (same behavior as handle_message returning empty reply)
            return
        attempts = self._attempts()
        for attempt in range(1, attempts + 1):
            yielded = False
            try:
                async for event in self.agent.stream_async(text):
                    # SDK lifecycle events (init/start) are not model output:
                    # only real output makes a retry unsafe.
                    if any(key in event for key in ("data", "message", "current_tool_use")):
                        yielded = True
                    yield event
                return
            except Exception as exc:
                # Only retry when nothing was streamed yet: the customer must
                # never see the same answer twice.
                if not yielded and attempt < attempts and is_retryable_error(exc):
                    self._log_agent_error(exc, tool="agent_retry")
                    await asyncio.sleep(self._backoff())
                    continue
                self._log_agent_error(exc)
                # On model/SDK error, yield a single event with fallback text so the CLI
                # can display it the same way it handles other events.
                yield {"data": self._error_reply(exc)}
                return

    def _attempts(self) -> int:
        return 1 + int(getattr(self.config.settings.agent, "model_retries", 0))

    def _backoff(self) -> float:
        return float(getattr(self.config.settings.agent, "retry_backoff_seconds", 0.0))

    def _error_reply(self, exc: Exception) -> str:
        agent_cfg = self.config.settings.agent
        if is_retryable_error(exc):
            return getattr(agent_cfg, "network_error_message", None) or agent_cfg.fallback_message
        return agent_cfg.fallback_message

    def _final_text(self, result: Any) -> str:
        message = getattr(result, "message", None) or {}
        parts = [
            block.get("text", "")
            for block in message.get("content", [])
            if isinstance(block, dict) and block.get("text")
        ]
        return "\n".join(parts).strip()

    def _log_agent_error(self, exc: Exception, tool: str = "agent_error") -> None:
        detail = self._scrub(str(exc))
        try:
            self.logger.log(
                session_id=self.session.session_id,
                tool=tool,
                inputs={},
                ok=False,
                error={"code": type(exc).__name__, "message": detail},
                duration_ms=0,
            )
        except Exception as log_exc:  # logging must never raise out of the runner
            print(f"warning: could not log agent error: {log_exc}", file=sys.stderr)

    def _scrub(self, text: str) -> str:
        for secret in [self.session.token] + list(self.session.pending):
            if secret and isinstance(secret, str):
                text = text.replace(secret, "***")
        return text
