"""Session panel tests: verification, receipts, expiry and privacy.

No network: ScriptedLLM drives the real agent loop, a fake gateway stands in
for the bank API.
"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

import adapters.web_chat as web_chat
from adapters.web_chat import create_app
from agent.errors import BankRejected
from agent.runner import AgentRunner
from agent.session import SessionState
from agent.tool_runtime import ToolRuntime
from core.config import ConfigError, load_config
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
    return load_config(config_dir="config")


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


def make_runner(cfg, scripts, gateway=None):
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


def post_stream(client, chat_id, message):
    response = client.post(f"/chats/{chat_id}/messages/stream", json={"message": message})
    assert response.status_code == 200
    return response.text


def get_panel(client, chat_id):
    response = client.get(f"/chats/{chat_id}/session")
    assert response.status_code == 200
    return response.json()


def post_json_message(client, chat_id, message):
    response = client.post(f"/chats/{chat_id}/messages", json={"message": message})
    assert response.status_code == 200
    return response.json()


def verify_script():
    return [("tool", "verify_customer", {"phone": PHONE, "otp": OTP}), ("text", "Verified.")]


def test_successful_verification_shows_masked_phone_and_expiry(monkeypatch, cfg):
    clock = FakeClock()
    runner, _ = make_runner(cfg, [verify_script()])
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "verify me")
        panel = get_panel(client, chat_id)

    events = sse_events(body)
    names = [name for name, _ in events]
    assert "panel" in names
    assert names.index("panel") < names.index("done")
    assert [payload for name, payload in events if name == "panel"][0] == panel
    assert panel == {
        "verified": True,
        "phone_masked": "+234 ••• ••• 4567",
        "expires_in_seconds": cfg.settings.session.expiry_minutes * 60,
        "receipts": [],
    }
    assert PHONE not in body
    assert TOKEN not in body
    assert OTP not in body


def test_json_messages_route_also_updates_panel(monkeypatch, cfg):
    runner, _ = make_runner(cfg, [verify_script()])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_json_message(client, chat_id, "verify me")
        panel = get_panel(client, chat_id)

    assert panel["verified"] is True
    assert panel["phone_masked"] == "+234 ••• ••• 4567"


def test_sending_a_code_only_does_not_verify(monkeypatch, cfg):
    runner, _ = make_runner(
        cfg, [[("tool", "verify_customer", {"phone": PHONE}), ("text", "Code sent.")]]
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "send me a code")
        panel = get_panel(client, chat_id)

    assert panel["verified"] is False
    assert panel["phone_masked"] is None
    assert "panel" not in [name for name, _ in sse_events(body)]


def test_wrong_otp_never_shows_verified(monkeypatch, cfg):
    runner, _ = make_runner(
        cfg,
        [[("tool", "verify_customer", {"phone": PHONE, "otp": "000000"}), ("text", "No.")]],
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        panel = get_panel(client, chat_id)

    assert panel["verified"] is False
    assert panel["phone_masked"] is None
    assert panel["expires_in_seconds"] is None


def test_failed_reverification_clears_verified(monkeypatch, cfg):
    clock = FakeClock()
    runner, _ = make_runner(
        cfg,
        [
            verify_script(),
            [("tool", "verify_customer", {"phone": PHONE, "otp": "000000"}), ("text", "No.")],
        ],
    )
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        assert get_panel(client, chat_id)["verified"] is True
        post_stream(client, chat_id, "try again")
        panel = get_panel(client, chat_id)

    assert panel["verified"] is False
    assert panel["phone_masked"] is None


def test_proposal_creates_no_receipt(monkeypatch, cfg):
    runner, _ = make_runner(
        cfg,
        [[("tool", "block_card", {"last4": "0001"}), ("text", "Confirm?")]],
    )
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        body = post_stream(client, chat_id, "block my card")
        panel = get_panel(client, chat_id)

    assert panel["receipts"] == []
    assert "panel" not in [name for name, _ in sse_events(body)]


def test_executed_dispute_creates_one_receipt(monkeypatch, cfg):
    runner, _ = make_runner(
        cfg,
        [
            [("tool", "open_dispute", {"reference": "RUB-DB-002", "reason": "double debit"}),
             ("text", "Confirm?")],
            [("tool", "confirm_action", {"pending_token": "PT-D"}), ("text", "Done.")],
        ],
    )
    runner.runtime.session.set_verified(TOKEN, "Alice")
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        first = post_stream(client, chat_id, "open a dispute")
        assert "panel" not in [name for name, _ in sse_events(first)]
        second = post_stream(client, chat_id, "yes")
        panel = get_panel(client, chat_id)

    assert len(panel["receipts"]) == 1
    receipt = panel["receipts"][0]
    assert receipt["kind"] == "dispute"
    assert receipt["reference"] == "RUB-DB-002"
    assert receipt["summary"] == "Dispute opened for RUB-DB-002."
    assert receipt["at"].endswith("+01:00")
    assert "panel" in [name for name, _ in sse_events(second)]


def test_executed_block_creates_one_receipt(monkeypatch, cfg):
    runner, _ = make_runner(
        cfg,
        [
            [("tool", "block_card", {"last4": "0001"}), ("text", "Confirm?")],
            [("tool", "confirm_action", {"pending_token": "PT-C"}), ("text", "Done.")],
        ],
    )
    runner.runtime.session.set_verified(TOKEN, "Alice")
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "block 0001")
        post_stream(client, chat_id, "yes")
        panel = get_panel(client, chat_id)

    assert len(panel["receipts"]) == 1
    receipt = panel["receipts"][0]
    assert receipt["kind"] == "card_block"
    assert receipt["reference"] is None
    assert receipt["summary"] == "Card ending 0001 blocked."


def test_failed_confirm_creates_no_receipt(monkeypatch, cfg):
    gateway = FakeGateway()
    gateway.confirm_fails = True
    runner, _ = make_runner(
        cfg,
        [
            [("tool", "block_card", {"last4": "0001"}), ("text", "Confirm?")],
            [("tool", "confirm_action", {"pending_token": "PT-C"}), ("text", "Try again.")],
        ],
        gateway,
    )
    runner.runtime.session.set_verified(TOKEN, "Alice")
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "block 0001")
        body = post_stream(client, chat_id, "yes")
        panel = get_panel(client, chat_id)

    assert panel["receipts"] == []
    assert "panel" not in [name for name, _ in sse_events(body)]


def test_handoff_receipt_caps_and_scrubs_summary(monkeypatch, cfg):
    clock = FakeClock()
    secret_summary = (
        f"Please call {PHONE} and use code {OTP} with {TOKEN}. "
        "My balance is ₦25,000. " + "x" * 700
    )
    runner, _ = make_runner(
        cfg,
        [
            verify_script(),
            [("tool", "handoff_to_human", {"summary": secret_summary, "reason": "user_requested"}),
             ("text", "Passed over.")],
        ],
    )
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        body = post_stream(client, chat_id, "human please")
        panel = get_panel(client, chat_id)

    receipt = panel["receipts"][0]
    assert receipt["kind"] == "handoff"
    assert receipt["reference"] == "HT-123"
    assert len(receipt["summary"]) <= cfg.settings.adapters.web.panel_summary_max_chars
    assert "Passed to a human agent:" in receipt["summary"]
    serialized = json.dumps(panel) + body
    for forbidden in (
        PHONE, TOKEN, OTP, "25,000", "handoff_to_human", "confirm_action",
        "verify_customer", "open_dispute", "block_card", "pending_token",
    ):
        assert forbidden not in serialized


def test_two_chats_stay_isolated(monkeypatch, cfg):
    runner_a, _ = make_runner(cfg, [verify_script()])
    runner_b, _ = make_runner(cfg, [[("text", "Hello.")]])
    with client_with_runners(monkeypatch, cfg, [runner_a, runner_b]) as client:
        chat_a = open_chat(client)
        chat_b = open_chat(client)
        post_stream(client, chat_a, "verify me")
        post_stream(client, chat_b, "hi")
        panel_a = get_panel(client, chat_a)
        panel_b = get_panel(client, chat_b)

    assert panel_a["verified"] is True
    assert panel_a["phone_masked"] == "+234 ••• ••• 4567"
    assert panel_b["verified"] is False
    assert panel_b["phone_masked"] is None


def test_expiry_flips_verified_to_false(monkeypatch, cfg):
    clock = FakeClock()
    # Keep the chat after verification expiry so the panel can be inspected
    # (with the flag on, the chat itself is deleted; covered in history tests).
    cfg.settings.adapters.web.clear_transcript_on_verification_expiry = False
    cfg.settings.adapters.web.session_idle_seconds = 5000
    runner, _ = make_runner(cfg, [verify_script()])
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        assert get_panel(client, chat_id)["verified"] is True
        clock.advance(cfg.settings.session.expiry_minutes * 60 + 1)
        panel = get_panel(client, chat_id)

    assert panel["verified"] is False
    assert panel["phone_masked"] is None
    assert panel["expires_in_seconds"] is None


def test_delete_removes_panel_state(monkeypatch, cfg):
    runner, _ = make_runner(cfg, [verify_script()])
    with client_with_runners(monkeypatch, cfg, [runner]) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        assert client.delete(f"/chats/{chat_id}").status_code == 200
        response = client.get(f"/chats/{chat_id}/session")

    assert response.status_code == 404
    assert response.json()["detail"] == "chat_expired"


def test_chat_expiry_removes_panel_state(monkeypatch, cfg):
    clock = FakeClock()
    runner, _ = make_runner(cfg, [verify_script()])
    with client_with_runners(monkeypatch, cfg, [runner], clock=clock) as client:
        chat_id = open_chat(client)
        post_stream(client, chat_id, "verify me")
        clock.advance(cfg.settings.adapters.web.session_idle_seconds + 1)
        response = client.get(f"/chats/{chat_id}/session")

    assert response.status_code == 404
    assert response.json()["detail"] == "chat_expired"


def test_bad_receipt_template_fails_fast(tmp_path, monkeypatch):
    import shutil
    import yaml

    set_env(monkeypatch)
    config_dir = tmp_path / "config"
    shutil.copytree("config", config_dir)
    path = Path(config_dir) / "tools.yaml"
    data = yaml.safe_load(path.read_text())
    data["handoff_to_human"]["receipt"]["template"] = "Phone {phone}"
    path.write_text(yaml.safe_dump(data, sort_keys=False))

    with pytest.raises(ConfigError) as exc:
        load_config(config_dir=str(config_dir))
    assert "receipt.template" in str(exc.value)
    assert "phone" in str(exc.value)
