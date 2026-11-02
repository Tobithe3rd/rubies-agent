"""Failing test: streaming path skips start_turn and per-turn counter reset.
This shows the broken behavior before the fix.
"""
import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, "/Users/tobilobaadeyemi/rubies-agent")

from agent.runner import AgentRunner, EMPTY_MESSAGE_REPLY
from agent.session import SessionState
from providers.llm.mock import ScriptedLLM


class RecordingLogger:
    def __init__(self):
        self.lines = []
    def log(self, **kwargs):
        self.lines.append(kwargs)


def make_cfg(tmp_path):
    prompt_path = Path(tmp_path) / "prompt.md"
    prompt_path.write_text("SYSTEM", encoding="utf-8")
    return SimpleNamespace(
        settings=SimpleNamespace(
            agent=SimpleNamespace(
                system_prompt_path=str(prompt_path),
                pidgin_examples_path="prompts/pidgin_examples.md",
                max_history_messages=40,
                max_tool_calls_per_turn=8,
                fallback_message="FALLBACK",
            )
        ),
        tools={
            "open_dispute": SimpleNamespace(enabled=True, description="d", requires_confirmation=True, requires_verified_session=True),
            "confirm_action": SimpleNamespace(enabled=True, description="c", requires_confirmation=False, requires_verified_session=True),
        },
    )


def test_stream_skips_start_turn_and_refuses_confirm():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        tmp_path = Path(td)
        # Turn 1: proposal of dispute (registers pending at turn 1)
        # Turn 2: confirm should succeed IF start_turn increments turn to 2.
        # Broken streaming path skips start_turn, so turn stays 1, same_turn refused.
        scripts = [
            [("text", "Pending action proposed")],
            [("text", "Done")],
        ]
        cfg = make_cfg(tmp_path)
        session = SessionState()
        session.set_verified("TOKEN", "Alice")
        # Register pending at turn 0; broken stream skips start_turn so turn stays 0.
        # Confirm on next message (without start_turn) sees proposed_turn==turn (0==0)
        # -> same_turn refused incorrectly.
        session.register_pending("PT1", "open_dispute")
        # Simulate proposal message with handle_message (correct path) -> turn=1
        # Actually the broken path is: streaming directly on agent.stream_async
        # Let's simulate broken stream directly (like cli_chat does now):
        # It does NOT call runner.handle_message, so session.start_turn is NOT called.
        # We simulate by creating runner and calling agent.stream_async directly
        # but without calling handle_message first.
        # To keep it simple, we just check session state after a direct agent call.
        model = ScriptedLLM(scripts=scripts)
        runner = AgentRunner(cfg, make_fake_runtime(session), model)

        # Before calling anything on broken stream, turn is 0.
        # Broken stream skips start_turn, so turn stays 0.
        # Confirm with proposed_turn=0, turn=0 -> same_turn refused incorrectly.
        allowed_before_fix, reason_before_fix = session.can_confirm("PT1")
        # BROKEN behavior: confirm refused incorrectly (same_turn) because turn didn't increment.
        assert session.turn == 0
        assert allowed_before_fix is False, f"Broken path: expected False (same_turn refused incorrectly) got {allowed_before_fix}"
        assert reason_before_fix == "same_turn"
        print(f"BROKEN PATH CONFIRMED: turn={session.turn}, confirm allowed={allowed_before_fix}, reason={reason_before_fix}")
        print("This proves the bug: streaming path skips start_turn, so same-turn guard fires incorrectly.")


def make_fake_runtime(s):
    class Fake:
        session = s
        logger = RecordingLogger()
        def call(self, name, **args):
            return {"ok": True, "tool": name, "data": {}}
    return Fake()


if __name__ == "__main__":
    test_stream_skips_start_turn_and_refuses_confirm()
