import asyncio
import json
import re
from types import SimpleNamespace

from agent.strands_tools import ToolCallCounter, build_input_schema, build_strands_tools
from agent.tool_specs import TOOL_SPECS

# Word-boundary match so the legitimate "pending_token" is not flagged.
FORBIDDEN = re.compile(r"\b(customer_id|token|session_token)\b")


class RecordingLogger:
    def __init__(self):
        self.lines = []

    def log(self, **kwargs):
        self.lines.append(kwargs)


class FakeRuntime:
    def __init__(self):
        self.calls = []
        self.logger = RecordingLogger()
        self.session = SimpleNamespace(session_id="s1")

    def call(self, name, **args):
        self.calls.append((name, args))
        return {"ok": True, "tool": name, "data": {"ok": True}}


def make_cfg(tools, limit=8):
    return SimpleNamespace(
        tools={
            name: SimpleNamespace(enabled=True, description=f"desc {name}")
            for name in tools
        },
        settings=SimpleNamespace(agent=SimpleNamespace(max_tool_calls_per_turn=limit)),
    )


def run_tool(tool, tool_use_id="1", **args):
    tool_use = {"toolUseId": tool_use_id, "name": tool.tool_name, "input": args}

    async def run():
        return [event async for event in tool.stream(tool_use, {})]

    return asyncio.run(run())


def result_of(events):
    return events[-1].tool_result


def test_schema_has_only_allowed_arguments():
    for name in TOOL_SPECS:
        schema = build_input_schema(name)
        assert set(schema["properties"]) == set(TOOL_SPECS[name]["allowed"])
        assert sorted(TOOL_SPECS[name]["required"]) == schema["required"]


def test_builds_only_enabled_tools_and_no_forbidden_strings():
    cfg = make_cfg(["get_balance", "open_dispute", "confirm_action"])
    cfg.tools["get_balance"].enabled = False
    runtime = FakeRuntime()
    tools, counter = build_strands_tools(cfg, runtime, runtime.logger)
    names = [tool.tool_name for tool in tools]
    assert names == ["open_dispute", "confirm_action"]
    serialized = json.dumps([tool.tool_spec for tool in tools])
    assert not FORBIDDEN.search(serialized)
    for tool in tools:
        assert not (set(tool.tool_spec["inputSchema"]["json"]["properties"]) & {
            "customer_id", "token", "session_token"
        })
    assert counter.limit == 8


def test_per_turn_cap_stops_calls_and_logs_them():
    cfg = make_cfg(["get_balance"], limit=3)
    runtime = FakeRuntime()
    (tool,), counter = build_strands_tools(cfg, runtime, runtime.logger)

    envelopes = []
    for i in range(5):
        events = run_tool(tool, tool_use_id=str(i))
        envelopes.append(result_of(events)["content"][0]["json"])

    assert [call[0] for call in runtime.calls] == ["get_balance"] * 3
    assert [e["error"] for e in envelopes[3:]] == ["too_many_tool_calls"] * 2
    assert envelopes[0]["ok"] is True
    assert len(runtime.logger.lines) == 2
    assert all(line["ok"] is False for line in runtime.logger.lines)
    assert all(line["tool"] == "get_balance" for line in runtime.logger.lines)


def test_counter_reset_allows_calls_again():
    cfg = make_cfg(["get_balance"], limit=1)
    runtime = FakeRuntime()
    (tool,), counter = build_strands_tools(cfg, runtime, runtime.logger)
    run_tool(tool)
    run_tool(tool)
    assert len(runtime.calls) == 1
    counter.reset()
    run_tool(tool)
    assert len(runtime.calls) == 2


def test_tool_result_carries_the_runtime_envelope():
    cfg = make_cfg(["confirm_action"], limit=8)
    runtime = FakeRuntime()
    (tool,), _ = build_strands_tools(cfg, runtime, runtime.logger)
    events = run_tool(tool, pending_token="PT")
    result = result_of(events)
    assert result["status"] == "success"
    assert result["content"][0]["json"] == {"ok": True, "tool": "confirm_action", "data": {"ok": True}}
    assert runtime.calls == [("confirm_action", {"pending_token": "PT"})]


def test_observer_exception_is_logged_and_result_unchanged():
    cfg = make_cfg(["block_card"])
    runtime = FakeRuntime()
    seen = []

    def boom(tool_name, status, is_proposal):
        seen.append((tool_name, status, is_proposal))
        raise RuntimeError("observer boom")

    (tool,), _ = build_strands_tools(cfg, runtime, runtime.logger, observer=boom)
    events = run_tool(tool, last4="0001")

    assert result_of(events)["content"][0]["json"] == {
        "ok": True, "tool": "block_card", "data": {"ok": True}
    }
    assert seen == [("block_card", "success", False)]
    assert runtime.logger.lines[-1]["tool"] == "tool_observer_error"
    assert runtime.logger.lines[-1]["error"]["message"] == "observer boom"
