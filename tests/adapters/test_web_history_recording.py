"""Transcript history: recording and serialisation."""
import asyncio
import json
from types import SimpleNamespace

import httpx

import adapters.web_chat as web_chat
from adapters.web_chat import create_app
from tests.adapters.helpers import (
    ChunkRunner,
    FakeClock,
    get_history,
    make_runner,
    open_chat as _open_chat,
    post_json as _post_json,
    post_stream,
    verify_runtime,
    verify_script,
)


def open_chat(client):
    chat_id = _open_chat(client)
    assert chat_id
    return chat_id


def json_ok(client, chat_id, message):
    reply = _post_json(client, chat_id, message)
    assert reply
    return reply


def stream_ok(client, chat_id, message):
    response = post_stream(client, chat_id, message)
    assert response.status_code == 200
    return response.text


class HistorySlowRunner:
    def __init__(self, delay=0.3):
        self.session = SimpleNamespace(token=None, pending={})
        self.delay = delay
        self.finished = False

    async def stream_events(self, text):
        yield {"data": "first "}
        await asyncio.sleep(self.delay)
        yield {"data": "second"}
        self.finished = True


def test_config_defaults(cfg):
    web = cfg.settings.adapters.web
    assert web.session_idle_seconds == 900
    assert web.session_max_age_seconds == 3600
    assert web.history_max_events == 400
    assert web.history_wait_seconds == 30
    assert web.clear_transcript_on_verification_expiry is True


def test_history_returns_steps_and_coalesced_text_in_order(monkeypatch, cfg):
    from tests.adapters.helpers import client_with_runners
    with client_with_runners(monkeypatch, cfg, [ChunkRunner()]) as client:
        chat_id = open_chat(client)
        body = stream_ok(client, chat_id, "what is the fee?")
        response = get_history(client, chat_id)

    assert response.status_code == 200
    payload = response.json()
    assert [m["role"] for m in payload["messages"]] == ["user", "agent"]
    user, agent = payload["messages"]
    assert user["text"] == "what is the fee?"
    assert agent["status"] == "done"
    assert [e["type"] for e in agent["events"]] == ["step", "step", "text", "done"]
    assert [e["status"] for e in agent["events"][:2]] == ["running", "done"]
    assert agent["events"][2]["text"] == "Your fee is ₦25."
    assert agent["events"][3]["citations"] == [
        {"document": "Fee Schedule", "section": "Transfer fees"}
    ]
    assert [line for line in body.splitlines() if line.startswith("event:")] == [
        "event: step", "event: step", "event: text", "event: text", "event: done"
    ]


def test_history_calls_are_stable(monkeypatch, cfg):
    from tests.adapters.helpers import client_with_runners
    runner, _ = make_runner(cfg, [[("text", "Hello there.")]])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        json_ok(client, chat_id, "hi")
        first = get_history(client, chat_id).json()
        second = get_history(client, chat_id).json()

    assert first == second


def test_json_route_records_user_and_agent_text(monkeypatch, cfg):
    from tests.adapters.helpers import client_with_runners
    runner, _ = make_runner(cfg, [[("text", "Hello there.")]])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        reply = json_ok(client, chat_id, "hi")
        messages = get_history(client, chat_id).json()["messages"]

    assert set(reply) == {"reply", "error"}
    assert reply["reply"] == "Hello there."
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "agent"
    assert messages[1]["events"] == [{"type": "text", "text": "Hello there."}]
    assert messages[1]["status"] == "done"


def test_history_includes_panel(monkeypatch, cfg):
    from tests.adapters.helpers import client_with_runners
    runner, _ = make_runner(cfg, [verify_script()], verify_runtime())
    with client_with_runners(monkeypatch, cfg, [runner], clock=FakeClock()) as client:
        chat_id = open_chat(client)
        stream_ok(client, chat_id, "verify me")
        history = get_history(client, chat_id).json()
        panel = client.get(f"/chats/{chat_id}/session").json()

    assert history["panel"] == panel
    assert panel["verified"] is True
    assert panel["phone_masked"] == "+234 ••• ••• 4567"


def test_history_waits_for_in_flight_turn(monkeypatch, cfg):
    cfg.settings.adapters.web.history_wait_seconds = 5
    runner = HistorySlowRunner(delay=0.3)
    monkeypatch.setattr(web_chat, "create_agent_runner", lambda *a, **k: runner)
    app = create_app(cfg, clock=FakeClock())

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            chat_id = (await client.post("/chats")).json()["chat_id"]
            stream = asyncio.create_task(
                client.post(f"/chats/{chat_id}/messages/stream", json={"message": "hi"})
            )
            entry = app.state.chat_store.sessions[chat_id]
            for _ in range(200):
                if entry["lock"].locked():
                    break
                await asyncio.sleep(0.01)
            history = await client.get(f"/chats/{chat_id}/history")
            await stream
        return history.json()

    payload = asyncio.run(scenario())
    agent = payload["messages"][1]
    assert agent["status"] == "done"
    assert [e for e in agent["events"] if e["type"] == "text"][0]["text"] == "first second"


def test_history_max_events_trims_whole_messages(monkeypatch, cfg):
    from tests.adapters.helpers import client_with_runners
    cfg.settings.adapters.web.history_max_events = 3
    runner, _ = make_runner(cfg, [[("text", "A")], [("text", "B")]])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        json_ok(client, chat_id, "one")
        json_ok(client, chat_id, "two")
        messages = get_history(client, chat_id).json()["messages"]

    assert len(messages) == 3
    assert messages[0]["role"] == "agent"
    assert messages[0]["events"] == [{"type": "text", "text": "A"}]
    assert [m["role"] for m in messages[1:]] == ["user", "agent"]
    total = sum(1 if m["role"] == "user" else len(m["events"]) for m in messages)
    assert total <= 3


def test_chats_are_isolated(monkeypatch, cfg):
    from tests.adapters.helpers import client_with_runners
    runner_a, _ = make_runner(cfg, [[("text", "Answer for A")]])
    runner_b, _ = make_runner(cfg, [[("text", "Answer for B")]])
    with client_with_runners(monkeypatch, cfg, [runner_a, runner_b]) as client:
        chat_a = open_chat(client)
        chat_b = open_chat(client)
        json_ok(client, chat_a, "a")
        json_ok(client, chat_b, "b")
        history_a = get_history(client, chat_a).json()
        history_b = get_history(client, chat_b).json()

    assert history_a["messages"][0]["text"] == "a"
    assert history_b["messages"][0]["text"] == "b"
    assert "Answer for B" not in json.dumps(history_a)
    assert "Answer for A" not in json.dumps(history_b)
