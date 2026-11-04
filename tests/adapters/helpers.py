"""Shared fixtures and builders for the web adapter tests."""
import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

from fastapi.testclient import TestClient

import adapters.web_chat as web_chat
from adapters.web_chat import create_app
from agent.errors import BankRejected
from agent.runner import AgentRunner
from agent.session import SessionState
from agent.tool_runtime import ToolRuntime
from providers.llm.mock import ScriptedLLM

PHONE = "+2348031234567"
TOKEN = "BANK-SECRET-TOKEN"
OTP = "123456"


def set_env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
    monkeypatch.setenv("OTP_HASH_SECRET", "test-secret-at-least-16-chars")


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


class FakeGateway:
    def __init__(self):
        self.confirm_fails = False

    def verify_start(self, phone):
        return {"status": "ok", "message": "A code was sent."}

    def verify_complete(self, phone, otp):
        if otp != OTP:
            raise BankRejected("invalid code", code="invalid_or_expired")
        return {"token": TOKEN, "expires_at": "2030-01-01 00:00:00"}

    def propose_dispute(self, token, reference, reason):
        return {"pending_token": "PT-D", "summary": f"Open a dispute for {reference}."}

    def propose_card_block(self, token, last4):
        return {"pending_token": "PT-C", "summary": f"Block card ending {last4}."}

    def confirm_action(self, token, pending_token):
        if self.confirm_fails:
            raise BankRejected("invalid or expired", code="invalid_or_expired")
        if pending_token == "PT-D":
            return {"status": "dispute_opened", "dispute_id": 7, "reference": "RUB-DB-002"}
        if pending_token == "PT-C":
            return {"status": "card_blocked", "last4": "0001", "card_status": "blocked"}
        raise BankRejected("invalid or expired", code="invalid_or_expired")

    def create_handoff(self, summary, token=None, reason=None):
        return {"ticket_id": "HT-123", "status": "open"}


def make_runner(cfg, scripts, runtime=None):
    runtime = runtime or FakeRuntime()
    return AgentRunner(cfg, runtime, ScriptedLLM(scripts=scripts)), runtime


def make_tool_runner(cfg, scripts, gateway=None):
    runtime = ToolRuntime(
        cfg,
        cfg.tools,
        SessionState(),
        gateway or FakeGateway(),
        lambda query: SimpleNamespace(
            status="ok", message="", results=[], top_score=None, threshold=0.35
        ),
        RecordingLogger(),
    )
    return AgentRunner(cfg, runtime, ScriptedLLM(scripts=scripts)), runtime


def verify_runtime():
    return FakeRuntime({
        "verify_customer": lambda args: {
            "ok": True,
            "tool": "verify_customer",
            "data": {"verified": True, "phone": args.get("phone"), "token": TOKEN},
        },
    })


def verify_script():
    return [("tool", "verify_customer", {"phone": PHONE, "otp": OTP}), ("text", "Verified.")]


def sse_events(body: str):
    events = []
    for block in body.split("\n\n"):
        name = data = None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: "):]
            elif line.startswith("data: "):
                data = line[len("data: "):]
        if name and data is not None:
            events.append((name, json.loads(data)))
    return events


def client_with_runners(monkeypatch, cfg, runners, clock=None,
                        attachments_config=None, vision_extractor=None):
    queue = list(runners)

    def factory(*args, **kwargs):
        return queue.pop(0)

    monkeypatch.setattr(web_chat, "create_agent_runner", factory)
    return TestClient(create_app(
        cfg, clock=clock, attachments_config=attachments_config,
        vision_extractor=vision_extractor))


def open_chat(client):
    response = client.post("/chats")
    assert response.status_code == 200
    return response.json()["chat_id"]


def get_history(client, chat_id):
    return client.get(f"/chats/{chat_id}/history")


def get_panel(client, chat_id):
    response = client.get(f"/chats/{chat_id}/session")
    assert response.status_code == 200
    return response.json()


def post_stream(client, chat_id, message):
    return client.post(f"/chats/{chat_id}/messages/stream", json={"message": message})


def post_json(client, chat_id, message):
    response = client.post(f"/chats/{chat_id}/messages", json={"message": message})
    assert response.status_code == 200
    return response.json()


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
    def __init__(self, delay=0.5):
        self.session = SimpleNamespace(session_id="slow", token=None)
        self.delay = delay
        self.finished = False

    async def stream_events(self, text):
        yield {"data": "first chunk "}
        await asyncio.sleep(self.delay)
        yield {"data": "second chunk"}
        self.finished = True


class FailingRunner:
    def __init__(self):
        self.session = SimpleNamespace(session_id="fail", token=None)

    async def stream_events(self, text):
        raise RuntimeError("model exploded")
        yield  # pragma: no cover


class GuardGateway:
    def __init__(self):
        self.calls = []

    def propose_card_block(self, token, last4):
        self.calls.append(("propose", last4))
        return {"pending_token": "PT-1", "status": "pending"}

    def confirm_action(self, token, pending_token):
        self.calls.append(("confirm", pending_token))
        return {"status": "card_blocked"}


def config_copy(tmp_path) -> Path:
    dest = tmp_path / "config"
    shutil.copytree("config", dest)
    return dest


def edit_yaml(path: Path, mutate):
    import yaml

    data = yaml.safe_load(path.read_text())
    mutate(data)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
