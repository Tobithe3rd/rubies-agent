"""Streaming route tests: SSE event order and tool labels."""
from tests.adapters.helpers import (
    FakeRuntime,
    client_with_runners,
    make_runner,
    open_chat as _open_chat,
    post_stream,
    sse_events,
)


def open_chat(client):
    chat_id = _open_chat(client)
    assert chat_id
    return chat_id


def test_tool_turn_event_order(monkeypatch, cfg):
    runner, _ = make_runner(
        cfg, [[("tool", "get_balance", {}), ("text", "Your balance is ₦1,000")]]
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        response = post_stream(client, chat_id, "what is my balance?")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        assert response.headers["x-accel-buffering"] == "no"

    events = sse_events(response.text)
    names = [name for name, _ in events]
    steps = [payload for name, payload in events if name == "step"]
    assert steps[0] == {
        "id": steps[0]["id"],
        "status": "running",
        "label": cfg.tools["get_balance"].labels.running,
    }
    assert steps[1]["id"] == steps[0]["id"]
    assert steps[1]["status"] == "done"
    assert steps[1]["label"] == cfg.tools["get_balance"].labels.done
    assert names.index("step") < names.index("text") < names.index("done")
    assert [p["delta"] for n, p in events if n == "text"] == ["Your balance is ₦1,000"]
    assert events[-1] == ("done", {"citations": []})


def test_failing_tool_gives_step_failed(monkeypatch, cfg):
    runtime = FakeRuntime(
        {"get_balance": {"ok": False, "tool": "get_balance", "error": "bank_unavailable"}}
    )
    runner, _ = make_runner(
        cfg, [[("tool", "get_balance", {}), ("text", "Please try again")]], runtime
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "balance please").text

    steps = [p for n, p in sse_events(body) if n == "step"]
    assert [s["status"] for s in steps] == ["running", "failed"]
    assert steps[-1]["label"] == cfg.tools["get_balance"].labels.failed


def test_block_card_proposal_gives_step_awaiting(monkeypatch, cfg):
    runtime = FakeRuntime(
        {"block_card": {"ok": True, "tool": "block_card", "data": {"pending_token": "PT-1"}}}
    )
    runner, _ = make_runner(
        cfg, [[("tool", "block_card", {"last4": "0001"}), ("text", "Shall I block it?")]],
        runtime,
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "block my card").text

    steps = [p for n, p in sse_events(body) if n == "step"]
    assert [s["status"] for s in steps] == ["running", "awaiting"]
    assert steps[-1]["label"] == cfg.tools["block_card"].labels.awaiting


def test_block_card_already_blocked_gives_no_action(monkeypatch, cfg):
    runtime = FakeRuntime(
        {
            "block_card": {
                "ok": True,
                "tool": "block_card",
                "data": {"status": "already_blocked", "last4": "0001"},
            }
        }
    )
    runner, _ = make_runner(
        cfg, [[("tool", "block_card", {"last4": "0001"}), ("text", "That card is already blocked.")]],
        runtime,
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "block my card").text

    steps = [p for n, p in sse_events(body) if n == "step"]
    assert [s["status"] for s in steps] == ["running", "done"]
    assert steps[-1]["label"] == cfg.tools["block_card"].labels.no_action
    assert steps[-1]["label"] == "Checked your card"
    assert "awaiting" not in [s["status"] for s in steps]


def test_open_dispute_proposal_gives_step_awaiting(monkeypatch, cfg):
    runtime = FakeRuntime(
        {"open_dispute": {"ok": True, "tool": "open_dispute", "data": {"pending_token": "PT-2"}}}
    )
    runner, _ = make_runner(
        cfg,
        [[("tool", "open_dispute", {"reference": "RUB-DB-002", "reason": "double debit"}),
          ("text", "Shall I open the dispute?")]],
        runtime,
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "open a dispute").text

    steps = [p for n, p in sse_events(body) if n == "step"]
    assert [s["status"] for s in steps] == ["running", "awaiting"]
    assert steps[-1]["label"] == cfg.tools["open_dispute"].labels.awaiting


def test_open_dispute_no_proposal_gives_no_action(monkeypatch, cfg):
    runtime = FakeRuntime(
        {
            "open_dispute": {
                "ok": True,
                "tool": "open_dispute",
                "data": {"error": "duplicate_dispute"},
            }
        }
    )
    runner, _ = make_runner(
        cfg,
        [[("tool", "open_dispute", {"reference": "RUB-DB-002", "reason": "double debit"}),
          ("text", "That dispute already exists.")]],
        runtime,
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "open a dispute").text

    steps = [p for n, p in sse_events(body) if n == "step"]
    assert [s["status"] for s in steps] == ["running", "done"]
    assert steps[-1]["label"] == cfg.tools["open_dispute"].labels.no_action
    assert steps[-1]["label"] == "Checked your dispute request"


def test_failing_confirmation_tool_gives_failed(monkeypatch, cfg):
    runtime = FakeRuntime(
        {"block_card": {"ok": False, "tool": "block_card", "error": "bank_unavailable"}}
    )
    runner, _ = make_runner(
        cfg, [[("tool", "block_card", {"last4": "0001"}), ("text", "Please try again.")]],
        runtime,
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "block my card").text

    steps = [p for n, p in sse_events(body) if n == "step"]
    assert [s["status"] for s in steps] == ["running", "failed"]
    assert steps[-1]["label"] == cfg.tools["block_card"].labels.failed
