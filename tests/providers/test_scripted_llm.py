import asyncio
import json

import pytest

from providers.llm.mock import ScriptedLLM


def collect(model, messages, **kwargs):
    async def run():
        return [event async for event in model.stream(messages, **kwargs)]

    return asyncio.run(run())


def user(text):
    return {"role": "user", "content": [{"text": text}]}


def tool_result(tool_use_id, envelope):
    return {
        "role": "user",
        "content": [
            {
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "status": "success",
                    "content": [{"json": envelope}],
                }
            }
        ],
    }


def test_text_step_emits_a_final_assistant_message():
    model = ScriptedLLM(scripts=[[("text", "hello ₦25,000")]])
    events = collect(model, [user("hi")])
    assert any(e.get("contentBlockDelta", {}).get("delta", {}).get("text") == "hello ₦25,000" for e in events)
    assert events[-1] == {"messageStop": {"stopReason": "end_turn"}}


def test_tool_step_emits_a_tool_use():
    model = ScriptedLLM(scripts=[[("tool", "get_balance", {"limit": 5})]])
    events = collect(model, [user("balance")])
    start = next(e for e in events if "contentBlockStart" in e)
    assert start["contentBlockStart"]["start"]["toolUse"]["name"] == "get_balance"
    delta = next(e for e in events if "contentBlockDelta" in e)
    assert json.loads(delta["contentBlockDelta"]["delta"]["toolUse"]["input"]) == {"limit": 5}
    assert events[-1] == {"messageStop": {"stopReason": "tool_use"}}


def test_callable_step_reads_the_last_tool_result():
    seen = {}

    def args(ctx):
        seen["pending"] = ctx.data["pending_token"]
        seen["tool"] = ctx.last_tool_result["tool"]
        return {"pending_token": ctx.data["pending_token"]}

    model = ScriptedLLM(
        scripts=[
            [
                ("tool", "open_dispute", {"reference": "R1", "reason": "dup"}),
                ("tool", "confirm_action", args),
            ]
        ]
    )
    collect(model, [user("dispute")])
    history = [
        user("dispute"),
        {"role": "assistant", "content": [{"toolUse": {"toolUseId": "1", "name": "open_dispute", "input": {}}}]},
        tool_result("1", {"ok": True, "tool": "open_dispute", "data": {"pending_token": "PT-9"}}),
    ]
    collect(model, history)
    assert seen == {"pending": "PT-9", "tool": "open_dispute"}


def test_running_out_of_steps_names_the_unmet_step():
    model = ScriptedLLM(scripts=[[("tool", "get_balance", {})]])
    collect(model, [user("a")])  # consumes the only step
    with pytest.raises(RuntimeError) as exc:
        collect(model, [user("a"), tool_result("1", {"ok": True})])
    assert "unmet step" in str(exc.value)


def test_missing_turn_script_names_the_unmet_step():
    model = ScriptedLLM(scripts=[])
    with pytest.raises(RuntimeError) as exc:
        collect(model, [user("a")])
    assert "unmet step" in str(exc.value)


def test_call_count_and_tool_specs_seen():
    model = ScriptedLLM(scripts=[[("text", "ok")]])
    specs = [{"name": "get_balance", "description": "d", "inputSchema": {"json": {}}}]
    collect(model, [user("hi")], tool_specs=specs)
    assert model.call_count == 1
    assert model.last_tool_specs == specs
