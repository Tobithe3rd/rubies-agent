from __future__ import annotations

import sys
from typing import Any

from agent.prompts import load_system_prompt
from agent.strands_tools import build_strands_tools

# Fixed reply for empty/whitespace input: no model call, no turn started.
EMPTY_MESSAGE_REPLY = "Please type a message so I can help."


class AgentRunner:
    """Runs the Strands agent for one conversation session.

    The model never sees the session token or customer_id: tools call the
    validated ToolRuntime, which injects the token from SessionState.
    """

    def __init__(self, config, runtime, llm, system_prompt: str | None = None, query_rewriter=None):
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
        self.tools, self.counter = build_strands_tools(
            config, runtime, self.logger, query_rewriter=self.query_rewriter
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

    def _setup_turn(self, text: str) -> bool:
        # Pre-turn setup: once per non-empty message. Returns False for empty.
        if text is None or not str(text).strip():
            return False
        self.session.start_turn()
        self.counter.reset()
        return True

    def handle_message(self, text: str) -> str:
        if not self._setup_turn(text):
            return EMPTY_MESSAGE_REPLY
        try:
            result = self.agent(text)
        except Exception as exc:
            self._log_agent_error(exc)
            return self.config.settings.agent.fallback_message
        return self._final_text(result)

    async def stream_events(self, text):
        if not self._setup_turn(text):
            # Empty message: yield nothing (same behavior as handle_message returning empty reply)
            return
        try:
            async for event in self.agent.stream_async(text):
                yield event
        except Exception as exc:
            self._log_agent_error(exc)
            # On model/SDK error, yield a single event with fallback text so the CLI
            # can display it the same way it handles other events.
            yield {"data": self.config.settings.agent.fallback_message}

    def _final_text(self, result: Any) -> str:
        message = getattr(result, "message", None) or {}
        parts = [
            block.get("text", "")
            for block in message.get("content", [])
            if isinstance(block, dict) and block.get("text")
        ]
        return "\n".join(parts).strip()

    def _log_agent_error(self, exc: Exception) -> None:
        detail = self._scrub(str(exc))
        try:
            self.logger.log(
                session_id=self.session.session_id,
                tool="agent_error",
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
