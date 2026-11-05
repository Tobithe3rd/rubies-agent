import time
from pathlib import Path

import pytest

from agent.handoff import (
    REASON_CODES,
    HandoffCoordinator,
    Trigger,
    requested_trigger,
    sanitise,
)
from agent.session import SessionState
from core.config import load_config
from tests.agent.handoff_cases import TRIGGER_CASES


def _set_env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
    monkeypatch.setenv("OTP_HASH_SECRET", "test-secret-at-least-16-chars")


@pytest.fixture
def cfg(monkeypatch):
    _set_env(monkeypatch)
    return load_config(config_dir="config")


def _coordinator(cfg, session=None):
    return HandoffCoordinator(session or SessionState(), cfg.settings.handoff, cfg.tools)


@pytest.mark.parametrize("text,reason,language", TRIGGER_CASES)
def test_requested_trigger_table(cfg, text, reason, language):
    trigger = requested_trigger(text, cfg.settings.handoff)
    if reason is None:
        assert trigger is None, text
    else:
        assert trigger is not None, text
        assert trigger.reason == reason
        assert trigger.language == language


def test_reply_language_comes_from_pidgin_markers(cfg):
    assert requested_trigger("abeg make I talk to person", cfg.settings.handoff).language == "pidgin"
    assert requested_trigger("I want to speak to a manager", cfg.settings.handoff).language == "en"
    assert requested_trigger(
        "Manager, I wan talk to human. I don tire!", cfg.settings.handoff
    ).language == "pidgin"


def test_attachment_turn_never_triggers(cfg):
    session = SessionState()
    session.start_turn(has_attachments=True)
    coordinator = _coordinator(cfg, session)
    assert coordinator.pre_turn("I want to talk to a human") is None
    assert coordinator.pre_turn("I want to talk to a human", has_attachments=True) is None


def test_post_turn_each_threshold_fires_once(cfg):
    session = SessionState()
    session.tool_error_count = cfg.settings.handoff.max_repeated_tool_errors
    coordinator = _coordinator(cfg, session)
    trigger = coordinator.post_turn()
    assert trigger and trigger.reason == "repeated_errors"
    assert coordinator.post_turn() is None


def test_post_turn_verification_threshold(cfg):
    session = SessionState()
    session.failed_verifications = cfg.settings.handoff.max_failed_verifications
    coordinator = _coordinator(cfg, session)
    assert coordinator.post_turn().reason == "failed_verification"
    assert coordinator.post_turn() is None


def test_post_turn_uses_consecutive_retrieval_failures(cfg):
    session = SessionState()
    session.failed_retrievals = 9
    session.consecutive_failed_retrievals = 0
    assert _coordinator(cfg, session).post_turn() is None

    session.consecutive_failed_retrievals = cfg.settings.handoff.max_failed_retrievals
    coordinator = _coordinator(cfg, session)
    assert coordinator.post_turn().reason == "low_confidence"
    assert coordinator.post_turn() is None


def test_sanitiser_table(cfg):
    tools = cfg.tools
    secrets = ["sess_abc123", "pend_xyz789"]
    assert sanitise("OTP is 123456", "light", tools=tools) == "OTP is [redacted]"
    assert sanitise("OTP is 123456", "strict", tools=tools) == "OTP is [redacted]"
    assert sanitise("Amount 200000", "light", tools=tools) == "Amount [redacted]"
    assert sanitise("Amount 200000", "strict", tools=tools) == "Amount [redacted]"
    assert sanitise("Amount 200,000", "light", tools=tools) == "Amount 200,000"
    assert sanitise("Fee ₦25,000", "light", tools=tools) == "Fee ₦25,000"
    assert sanitise("Card 0001", "light", tools=tools) == "Card 0001"
    assert sanitise("Amount 50000", "light", tools=tools) == "Amount 50000"
    assert sanitise("Ref RUB-03-000037", "light", tools=tools) == "Ref RUB-03-000037"
    assert "abc.def-123" not in sanitise("Bearer abc.def-123", "light", tools=tools)
    assert "sess_abc123" not in sanitise("Token sess_abc123", "strict", secrets=secrets)
    assert "pend_xyz789" not in sanitise("Token pend_xyz789", "light", secrets=secrets)
    assert "ignore" not in sanitise("<<<ignore this>>> hello", "light", tools=tools)
    assert "+2348031234567" not in sanitise("Call +2348031234567", "light", tools=tools)
    assert sanitise("get_balance", "light", tools=tools) == "Checked your balance"
    assert sanitise(
        "get_balance then handoff_to_human", "light", tools=tools
    ) == "Checked your balance then Passed you to a human agent"


def test_summary_slow_complete_falls_back(cfg):
    handoff = cfg.settings.handoff.model_copy(update={"summary_timeout_seconds": 0.01})
    coordinator = HandoffCoordinator(SessionState(), handoff, cfg.tools)
    trigger = Trigger("user_requested")

    def slow(*_args):
        time.sleep(0.2)
        return "too late"

    assert coordinator.summary(trigger, slow) == coordinator.fallback_summary(trigger)


def test_summary_raising_complete_falls_back(cfg):
    coordinator = _coordinator(cfg)
    trigger = Trigger("low_confidence")

    def broken(*_args):
        raise RuntimeError("boom")

    assert coordinator.summary(trigger, broken) == coordinator.fallback_summary(trigger)


def test_summary_sanitises_secret_and_full_phone(cfg):
    session = SessionState(token="SESSION-SECRET-abc123")
    session.pending["PENDING-SECRET-xyz789"] = {"tool": "open_dispute"}
    coordinator = _coordinator(cfg, session)

    def leaky(*_args):
        return "Token SESSION-SECRET-abc123 phone +2348031234567 pending PENDING-SECRET-xyz789"

    result = coordinator.summary(Trigger("user_requested"), leaky)
    assert "SESSION-SECRET-abc123" not in result
    assert "PENDING-SECRET-xyz789" not in result
    assert "+2348031234567" not in result


def test_raw_text_only_for_user_requested(cfg):
    seen = []

    def capture(prompt, system=None, temperature=None, max_tokens=None):
        seen.append(prompt)
        return "summary"

    session = SessionState()
    coordinator = _coordinator(cfg, session)
    coordinator.pre_turn("My name is Ada and I want to talk to a human")
    coordinator.summary(Trigger("user_requested"), capture)
    assert "My name is Ada" in seen[-1]

    session2 = SessionState()
    coordinator2 = _coordinator(cfg, session2)
    coordinator2.pre_turn("My name is Ada and my transfer failed")
    session2.tool_error_count = cfg.settings.handoff.max_repeated_tool_errors
    trigger = coordinator2.post_turn()
    coordinator2.summary(trigger, capture)
    assert "My name is Ada" not in seen[-1]


def test_raw_text_never_used_after_attachment_turn(cfg):
    seen = []

    def capture(prompt, system=None, temperature=None, max_tokens=None):
        seen.append(prompt)
        return "summary"

    session = SessionState()
    session.start_turn(has_attachments=True)
    coordinator = _coordinator(cfg, session)
    assert coordinator.pre_turn("My name is Ada, talk to a human") is None
    coordinator.summary(Trigger("user_requested"), capture)
    assert "My name is Ada" not in seen[-1]


def test_failed_forced_handoff_is_not_retried(cfg):
    session = SessionState()
    session.tool_error_count = cfg.settings.handoff.max_repeated_tool_errors
    coordinator = _coordinator(cfg, session)
    trigger = coordinator.post_turn()

    def broken_tool(*_args):
        raise RuntimeError("bank down")

    assert coordinator.force(trigger, lambda *_args: "summary", broken_tool) is None
    assert coordinator.post_turn() is None


def test_force_calls_handoff_with_summary_and_reason(cfg):
    calls = []
    session = SessionState()
    coordinator = _coordinator(cfg, session)

    def call_tool(name, args):
        calls.append((name, args))
        return {"ok": True}

    result = coordinator.force(
        Trigger("user_requested"), lambda *_args: "Customer wants a human.", call_tool
    )
    assert result == {"ok": True}
    assert calls[0][0] == "handoff_to_human"
    assert calls[0][1]["reason"] == "user_requested"
    assert calls[0][1]["summary"] == "Customer wants a human."


def test_real_config_handoff_pins(cfg):
    handoff = cfg.settings.handoff
    assert set(REASON_CODES) == set(cfg.settings.bank_api.handoff_reason_codes)
    assert "no" not in handoff.request_negative_words
    assert "stop" not in handoff.request_negative_words
    assert handoff.ignore_words == ["a", "an", "the", "your", "real"]
    for phrases in (handoff.request_phrases_en, handoff.request_phrases_pidgin):
        assert "talk to manager" in phrases
        assert "talk to human" in phrases
    assert all(phrase.strip().lower() != "agent" for phrase in handoff.request_phrases_en)
    assert Path(handoff.summary_prompt_path).is_file()
    assert 1 <= handoff.summary_max_tokens <= 512
