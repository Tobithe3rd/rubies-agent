"""Transcript history tests: server-side restore, expiry and privacy.

No network: ScriptedLLM drives the real agent loop, a fake runtime/gateway stands
in for the bank and RAG.
"""
import asyncio
import json
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

import httpx
from fastapi.testclient import TestClient

import adapters.web_chat as web_chat
from adapters.web_chat import create_app
from agent.runner import AgentRunner
from agent.session import SessionState
from core.config import load_config
from providers.llm.mock import ScriptedLLM

PHONE = "+2348031234567"
TOKEN = "BANK-SECRET-TOKEN"
OTP = "123456"


def set_env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
    monkeypatch.setenv("OTP_HASH_SECRET", "test-secret-at-least-16-chars")


@pytest.fixture
def cfg(monkeypatch):
    set_env(monkeypatch)
    config = load_config(config_dir="config")
    config.settings.llm.provider = "mock"
    return config


class FakeClock:
    def __init__(self):
        self.t = 1000.0

    def now(self):
        return self.t

    def advance(self, seconds):
        self.t += seconds


class RecordingLogger:
    def __init__(self):
        self.lines = []

    def log(self, **kwargs):
        self.lines.append(kwargs)


class FakeRuntime:
    def __init__(self, responses=None, session=None):
        self.session = session or SessionState()
        self.logger = RecordingLogger()
        self.calls = []
        self.responses = responses or {}

    def call(self, name, **args):
        self.calls.append((name, args))
        response = self.responses.get(name, {"ok": True, "tool": name, "data": {}})
        if callable(response):
            response = response(args)
        return response


def make_runner(cfg, scripts, runtime=None):
    runtime = runtime or FakeRuntime()
    return AgentRunner(cfg, runtime, ScriptedLLM(scripts=scripts)), runtime


def verify_runtime():
    return FakeRuntime({
        "verify_customer": lambda args: {
            "ok": True,
            "tool": "verify_customer",
            "data": {"verified": True, "phone": args.get("phone"), "token": TOKEN},
        },
    })


class ChunkRunner:
    """Yields the stream events a tool turn with split text would produce."""

    def __init__(self):
        self.session = SimpleNamespace(token=None, pending={})

    async def stream_events(self, text):
        yield {
            "type": "tool_use_stream",
            "current_tool_use": {"toolUseId": "tool-1", "name": "search_policy"},
        }
        if self.tool_observer is not None:
            self.tool_observer("search_policy", "success", False)
        await asyncio.sleep(0)
        yield {
            "message": {
                "role": "user",
                "content": [{
                    "toolResult": {
                        "content": [{
                            "json": {
                                "tool": "search_policy",
                                "data": {"results": [{
                                    "doc_title": "Fee Schedule",
                                    "section_heading": "Transfer fees",
                                }]},
                            },
                        }],
                    },
                }],
            }
        }
        yield {"data": "Your fee is "}
        yield {"data": "₦25."}


class SlowRunner:
    def __init__(self, delay=0.3):
        self.session = SimpleNamespace(token=None, pending={})
        self.delay = delay
        self.finished = False

    async def stream_events(self, text):
        yield {"data": "first "}
        await asyncio.sleep(self.delay)
        yield {"data": "second"}
        self.finished = True


def client_with_runners(monkeypatch, cfg, runners, clock=None):
    queue = list(runners)

    def factory(*args, **kwargs):
        return queue.pop(0)

    monkeypatch.setattr(web_chat, "create_agent_runner", factory)
    return TestClient(create_app(cfg, clock=clock))


def open_chat(client):
    response = client.post("/chats")
    assert response.status_code == 200
    return response.json()["chat_id"]


def get_history(client, chat_id):
    return client.get(f"/chats/{chat_id}/history")


def post_stream(client, chat_id, message):
    response = client.post(f"/chats/{chat_id}/messages/stream", json={"message": message})
    assert response.status_code == 200
    return response.text


def post_json(client, chat_id, message):
    response = client.post(f"/chats/{chat_id}/messages", json={"message": message})
    assert response.status_code == 200
    return response.json()


def verify_script():
    return [("tool", "verify_customer", {"phone": PHONE, "otp": OTP}), ("text", "Verified.")]


# --- config ---

def test_config_defaults(cfg):
    web = cfg.settings.adapters.web
    assert web.session_idle_seconds == 900
    assert web.session_max_age_seconds == 3600
    assert web.history_max_events == 400
    assert web.history_wait_seconds == 30
    assert web.clear_transcript_on_verification_expiry is True


# --- recording ---

def test_history_returns_steps_and_coalesced_text_in_order(monkeypatch, cfg):
    with client_with_runners(monkeypatch, cfg, [ChunkRunner()]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "what is the fee?")
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
    # The stream contract is unchanged.
    assert [line for line in body.splitlines() if line.startswith("event:")] == [
        "event: step", "event: step", "event: text", "event: text", "event: done"
    ]


def test_history_calls_are_stable(monkeypatch, cfg):
    runner, _ = make_runner(cfg, [[("text", "Hello there.")]])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_json(client, chat_id, "hi")
        first = get_history(client, chat_id).json()
        second = get_history(client, chat_id).json()

    assert first == second


def test_json_route_records_user_and_agent_text(monkeypatch, cfg):
    runner, _ = make_runner(cfg, [[("text", "Hello there.")]])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        reply = post_json(client, chat_id, "hi")
        messages = get_history(client, chat_id).json()["messages"]

    assert set(reply) == {"reply", "error"}
    assert reply["reply"] == "Hello there."
    assert messages[0]["role"] == "user"
    assert messages[1]["role"] == "agent"
    assert messages[1]["events"] == [{"type": "text", "text": "Hello there."}]
    assert messages[1]["status"] == "done"


def test_history_includes_panel(monkeypatch, cfg):
    runner, _ = make_runner(cfg, [verify_script()], verify_runtime())
    with client_with_runners(monkeypatch, cfg, [runner], clock=FakeClock()) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        history = get_history(client, chat_id).json()
        panel = client.get(f"/chats/{chat_id}/session").json()

    assert history["panel"] == panel
    assert panel["verified"] is True
    assert panel["phone_masked"] == "+234 ••• ••• 4567"


def test_history_waits_for_in_flight_turn(monkeypatch, cfg):
    cfg.settings.adapters.web.history_wait_seconds = 5
    runner = SlowRunner(delay=0.3)
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
    cfg.settings.adapters.web.history_max_events = 3
    runner, _ = make_runner(cfg, [[("text", "A")], [("text", "B")]])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_json(client, chat_id, "one")
        post_json(client, chat_id, "two")
        messages = get_history(client, chat_id).json()["messages"]

    assert len(messages) == 3
    assert messages[0]["role"] == "agent"
    assert messages[0]["events"] == [{"type": "text", "text": "A"}]
    assert [m["role"] for m in messages[1:]] == ["user", "agent"]
    total = sum(1 if m["role"] == "user" else len(m["events"]) for m in messages)
    assert total <= 3


def test_chats_are_isolated(monkeypatch, cfg):
    runner_a, _ = make_runner(cfg, [[("text", "Answer for A")]])
    runner_b, _ = make_runner(cfg, [[("text", "Answer for B")]])
    with client_with_runners(monkeypatch, cfg, [runner_a, runner_b]) as client:
        chat_a = open_chat(client)
        chat_b = open_chat(client)
        post_json(client, chat_a, "a")
        post_json(client, chat_b, "b")
        history_a = get_history(client, chat_a).json()
        history_b = get_history(client, chat_b).json()

    assert history_a["messages"][0]["text"] == "a"
    assert history_b["messages"][0]["text"] == "b"
    assert "Answer for B" not in json.dumps(history_a)
    assert "Answer for A" not in json.dumps(history_b)


# --- expiry ---

def test_unknown_chat_gives_404(monkeypatch, cfg):
    with client_with_runners(monkeypatch, cfg, []) as client:
        response = get_history(client, "missing")
    assert response.status_code == 404
    assert response.json()["detail"] == "chat_expired"


def test_idle_expiry_at_900_seconds(monkeypatch, cfg):
    clock = FakeClock()
    runner, _ = make_runner(cfg, [[("text", "Hi")]])
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        post_json(client, chat_id, "hi")
        clock.advance(900)
        assert get_history(client, chat_id).status_code == 200
        # That call counts as activity, so a fresh full idle window is needed.
        clock.advance(901)
        response = get_history(client, chat_id)

    assert response.status_code == 404
    assert response.json()["detail"] == "chat_expired"


def test_max_age_expiry_even_with_activity(monkeypatch, cfg):
    clock = FakeClock()
    runner, _ = make_runner(cfg, [[("text", "Hi")]])
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        post_json(client, chat_id, "hi")
        for _ in range(4):
            clock.advance(800)
            assert get_history(client, chat_id).status_code == 200
        clock.advance(500)
        response = get_history(client, chat_id)

    assert response.status_code == 404


def test_verification_expiry_deletes_chat_when_flag_true(monkeypatch, cfg):
    cfg.settings.adapters.web.session_idle_seconds = 5000
    cfg.settings.adapters.web.clear_transcript_on_verification_expiry = True
    clock = FakeClock()
    runner, _ = make_runner(cfg, [verify_script()], verify_runtime())
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        clock.advance(cfg.settings.session.expiry_minutes * 60 + 1)
        response = get_history(client, chat_id)

    assert response.status_code == 404
    assert response.json()["detail"] == "chat_expired"


def test_verification_expiry_keeps_chat_when_flag_false(monkeypatch, cfg):
    cfg.settings.adapters.web.session_idle_seconds = 5000
    cfg.settings.adapters.web.clear_transcript_on_verification_expiry = False
    clock = FakeClock()
    runner, _ = make_runner(cfg, [verify_script()], verify_runtime())
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        clock.advance(cfg.settings.session.expiry_minutes * 60 + 1)
        response = get_history(client, chat_id)

    assert response.status_code == 200
    assert response.json()["panel"]["verified"] is False


def test_delete_removes_transcript(monkeypatch, cfg):
    runner, _ = make_runner(cfg, [[("text", "Hello.")]])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_json(client, chat_id, "hi")
        assert client.delete(f"/chats/{chat_id}").status_code == 200
        response = get_history(client, chat_id)

    assert response.status_code == 404
    assert not client.app.state.chat_store.sessions.get(chat_id)


# --- privacy ---

def test_history_payload_has_no_token_otp_or_full_phone(monkeypatch, cfg):
    runner, runtime = make_runner(
        cfg,
        [
            [
                ("tool", "verify_customer", {"phone": PHONE, "otp": OTP}),
                ("text", "Verified for " + PHONE),
            ]
        ],
        verify_runtime(),
    )
    runtime.session.set_verified(TOKEN, "Alice")
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, f"my number is {PHONE} and code is {OTP}")
        body = get_history(client, chat_id).text

    for forbidden in (PHONE, OTP, TOKEN):
        assert forbidden not in body
    assert "[redacted]" in body


def test_no_transcript_text_in_logs(monkeypatch, cfg, caplog):
    marker = "SECRET-TRANSCRIPT-MARKER"
    runner, _ = make_runner(cfg, [[("text", "Echo " + marker)]])
    with caplog.at_level("DEBUG"):
        with client_with_runners(monkeypatch, cfg, [runner]) as client:
            chat_id = open_chat(client)
            post_json(client, chat_id, marker)
            get_history(client, chat_id)

    assert marker not in caplog.text
