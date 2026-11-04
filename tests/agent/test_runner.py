from types import SimpleNamespace

from agent.runner import EMPTY_MESSAGE_REPLY, AgentRunner
from agent.session import SessionState
from providers.llm.mock import ScriptedLLM


class RecordingLogger:
    def __init__(self):
        self.lines = []

    def log(self, **kwargs):
        self.lines.append(kwargs)


class FakeRuntime:
    def __init__(self):
        self.session = SessionState()
        self.logger = RecordingLogger()
        self.calls = []

    def call(self, name, **args):
        self.calls.append((name, args))
        return {"ok": True, "tool": name, "data": {}}


def make_cfg(tmp_path, prompt="SYSTEM PROMPT", max_history=40, max_tools=8, fallback="FALLBACK",
             model_retries=0, retry_backoff=0.0, network_message="NETWORK DOWN"):
    prompt_path = tmp_path / "prompt.md"
    prompt_path.write_text(prompt, encoding="utf-8")
    return SimpleNamespace(
        settings=SimpleNamespace(
            agent=SimpleNamespace(
                system_prompt_path=str(prompt_path),
                pidgin_examples_path="prompts/pidgin_examples.md",
                max_history_messages=max_history,
                max_tool_calls_per_turn=max_tools,
                fallback_message=fallback,
                model_retries=model_retries,
                retry_backoff_seconds=retry_backoff,
                network_error_message=network_message,
            )
        ),
        tools={},
    )


def make_runner(tmp_path, scripts, **kwargs):
    cfg = make_cfg(tmp_path, **kwargs)
    runtime = FakeRuntime()
    model = ScriptedLLM(scripts=scripts)
    runner = AgentRunner(cfg, runtime, model)
    return runner, runtime, model


def test_empty_input_is_rejected_without_a_model_call(tmp_path):
    runner, runtime, model = make_runner(tmp_path, [[("text", "hello")]])
    assert runner.handle_message("   ") == EMPTY_MESSAGE_REPLY
    assert runner.handle_message("") == EMPTY_MESSAGE_REPLY
    assert runtime.session.turn == 0
    assert model.call_count == 0


def test_text_reply_is_returned(tmp_path):
    runner, _, _ = make_runner(tmp_path, [[("text", "hello ₦25,000")]])
    assert runner.handle_message("hi") == "hello ₦25,000"
    assert runner.session.turn == 1


def test_model_error_returns_fallback_and_logs_agent_error(tmp_path):
    runner, runtime, _ = make_runner(tmp_path, [])
    reply = runner.handle_message("hi")
    assert reply == "FALLBACK"
    assert runner.session.turn == 1
    assert len(runtime.logger.lines) == 1
    line = runtime.logger.lines[0]
    assert line["tool"] == "agent_error"
    assert line["ok"] is False
    assert line["error"]["code"]
    assert line["error"]["message"]


def test_model_error_message_does_not_leak_the_session_token(tmp_path):
    runner, runtime, _ = make_runner(tmp_path, [])
    runtime.session.set_verified("SUPER-SECRET-TOKEN", "A")

    class Exploding(ScriptedLLM):
        async def stream(self, *args, **kwargs):
            raise RuntimeError("boom SUPER-SECRET-TOKEN")
            yield  # pragma: no cover

    runner.agent.model = Exploding()
    reply = runner.handle_message("hi")
    assert reply == "FALLBACK"
    logged = str(runtime.logger.lines[-1])
    assert "SUPER-SECRET-TOKEN" not in logged


class EndpointConnectionError(Exception):
    """Same class name botocore uses, to exercise the retry classification."""


class FlakyLLM(ScriptedLLM):
    def __init__(self, fail_times, error=EndpointConnectionError, **kwargs):
        super().__init__(**kwargs)
        self.fail_times = fail_times
        self.error = error
        self.stream_calls = 0

    async def stream(self, *args, **kwargs):
        self.stream_calls += 1
        if self.stream_calls <= self.fail_times:
            raise self.error("Could not connect to the endpoint URL")
        async for event in super().stream(*args, **kwargs):
            yield event


def test_connection_error_is_retried_and_the_turn_succeeds(tmp_path):
    cfg = make_cfg(tmp_path, model_retries=2)
    runtime = FakeRuntime()
    model = FlakyLLM(1, scripts=[[("text", "hello")]])
    runner = AgentRunner(cfg, runtime, model)

    assert runner.handle_message("hi") == "hello"
    assert model.stream_calls == 2
    assert [line["tool"] for line in runtime.logger.lines] == ["agent_retry"]


def test_connection_error_retries_exhausted_returns_network_message(tmp_path):
    cfg = make_cfg(tmp_path, model_retries=1)
    runtime = FakeRuntime()
    model = FlakyLLM(5, scripts=[[("text", "hello")]])
    runner = AgentRunner(cfg, runtime, model)

    assert runner.handle_message("hi") == "NETWORK DOWN"
    assert model.stream_calls == 2
    assert runtime.logger.lines[-1]["tool"] == "agent_error"


def test_non_connection_error_is_not_retried(tmp_path):
    cfg = make_cfg(tmp_path, model_retries=2)
    runtime = FakeRuntime()
    model = FlakyLLM(5, error=ValueError, scripts=[[("text", "hello")]])
    runner = AgentRunner(cfg, runtime, model)

    assert runner.handle_message("hi") == "FALLBACK"
    assert model.stream_calls == 1


def test_stream_retry_only_before_output_is_sent(tmp_path):
    import asyncio

    cfg = make_cfg(tmp_path, model_retries=2)
    runtime = FakeRuntime()
    model = FlakyLLM(1, scripts=[[("text", "hello")]])
    runner = AgentRunner(cfg, runtime, model)

    async def collect():
        return [event async for event in runner.stream_events("hi")]

    events = asyncio.run(collect())
    assert model.stream_calls == 2
    assert any("hello" in str(event.get("data", "")) for event in events)


def test_prompt_is_passed_to_the_agent_unchanged(tmp_path):
    prompt = "# system\n\nDo not guess.\n"
    runner, _, _ = make_runner(tmp_path, [[("text", "ok")]], prompt=prompt)
    assert prompt in runner.system_prompt
    assert prompt in runner.agent.system_prompt


def test_stream_path_increments_turn_and_allows_confirm_on_next_message(tmp_path):
    import asyncio
    scripts = [[("text", "done")], [("text", "ok")]]
    runner, runtime, model = make_runner(tmp_path, scripts)
    async def consume_first():
        evs = []
        async for event in runner.stream_events("msg 1"):
            evs.append(event)
        return evs
    asyncio.run(consume_first())
    assert runtime.session.turn == 1, f"Expected turn=1 after stream, got {runtime.session.turn}"
    assert model.call_count == 1
    # Empty message must not increment turn
    async def consume_empty():
        evs = []
        async for event in runner.stream_events("   "):
            evs.append(event)
        return evs
    asyncio.run(consume_empty())
    assert runtime.session.turn == 1, f"Empty message should not increment turn, got {runtime.session.turn}"


def test_stream_path_confirm_sequence_works(tmp_path):
    import asyncio
    scripts = [[("text", "pending")], [("text", "confirmed")]]
    runner, runtime, model = make_runner(tmp_path, scripts)
    runtime.session.set_verified("TOK", "Name")
    runtime.session.register_pending("PT_A", "open_dispute")
    # Broken stream would leave turn at 0; fixed stream increments to 1.
    async def consume_first():
        evs = []
        async for event in runner.stream_events("confirm please"):
            evs.append(event)
        return evs
    asyncio.run(consume_first())
    assert runtime.session.turn == 1
    allowed, reason = runtime.session.can_confirm("PT_A")
    assert allowed is True, f"Confirm allowed={allowed} reason={reason}"
    assert reason == "ok"


def test_attachment_flag_is_passed_through_and_reset_on_the_next_turn(tmp_path):
    scripts = [[("text", "read it")], [("text", "done")]]
    runner, runtime, _ = make_runner(tmp_path, scripts)

    assert runner.handle_message("look at this", has_attachments=True) == "read it"
    assert runtime.session.turn == 1
    assert runtime.session.turn_has_attachments is True

    assert runner.handle_message("no file now") == "done"
    assert runtime.session.turn == 2
    assert runtime.session.turn_has_attachments is False


def test_stream_attachment_flag_is_passed_through_and_reset(tmp_path):
    import asyncio
    scripts = [[("text", "read it")], [("text", "done")]]
    runner, runtime, _ = make_runner(tmp_path, scripts)

    async def consume(text, has_attachments=False):
        return [event async for event in runner.stream_events(
            text, has_attachments=has_attachments)]

    asyncio.run(consume("look at this", has_attachments=True))
    assert runtime.session.turn_has_attachments is True
    asyncio.run(consume("no file now"))
    assert runtime.session.turn_has_attachments is False


def test_history_is_capped_by_the_conversation_manager(tmp_path):
    scripts = [[("text", f"reply {i}")] for i in range(10)]
    runner, _, _ = make_runner(tmp_path, scripts, max_history=6)
    max_seen = 0
    for i in range(10):
        runner.handle_message(f"message {i}")
        max_seen = max(max_seen, len(runner.agent.messages))
    assert max_seen <= 6
    assert runner.session.turn == 10
