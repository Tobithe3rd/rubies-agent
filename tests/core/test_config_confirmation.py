import shutil

import pytest
import yaml
from pydantic import ValidationError

from attachments.config import load_attachments_config
from core.config import ConfirmationConfig, ConfigError, load_config


def _set_env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
    monkeypatch.setenv("OTP_HASH_SECRET", "test-secret-at-least-16-chars")


def _real_config(monkeypatch):
    _set_env(monkeypatch)
    return load_config(config_dir="config")


def _confirmation_data():
    data = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
    return data["confirmation"]


def test_real_confirmation_lists_are_safe(monkeypatch):
    _set_env(monkeypatch)
    cfg = load_config(config_dir="config")
    confirmation = cfg.settings.confirmation
    assert confirmation.max_turns == 2
    assert confirmation.max_tokens == 8
    assert confirmation.reject_digits is True
    for word in ("no", "not", "dont", "cancel", "wait"):
        assert word in confirmation.negative_words
    for word in ("ok", "okay", "thanks"):
        assert word not in confirmation.affirmative_words
        assert word not in confirmation.affirmative_phrases


def test_confirm_action_is_the_only_tool_that_requires_affirmation(monkeypatch):
    _set_env(monkeypatch)
    cfg = load_config(config_dir="config")
    requires = {name for name, tool in cfg.tools.items() if tool.requires_affirmation}
    assert requires == {"confirm_action"}


def test_overlapping_affirmative_and_negative_entries_fail_fast():
    data = _confirmation_data()
    data["negative_words"] = list(data["negative_words"]) + ["YES"]
    with pytest.raises(ValidationError) as exc:
        ConfirmationConfig(**data)
    message = str(exc.value)
    assert "affirmative_words" in message
    assert "negative_words" in message
    assert "'yes'" in message


def test_overlap_through_load_config_names_both_entries(tmp_path, monkeypatch):
    _set_env(monkeypatch)
    cfg_dir = tmp_path / "config"
    shutil.copytree("config", cfg_dir)
    path = cfg_dir / "settings.yaml"
    data = yaml.safe_load(path.read_text())
    data["confirmation"]["negative_phrases"].append("Go Ahead")
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    with pytest.raises(ConfigError) as exc:
        load_config(config_dir=str(cfg_dir))
    message = str(exc.value)
    assert "affirmative_phrases" in message
    assert "negative_phrases" in message
    assert "'go ahead'" in message


def test_confirm_action_has_all_guards(monkeypatch):
    tool = _real_config(monkeypatch).tools["confirm_action"]
    assert tool.blocked_on_attachment_turns is True, (
        "tools.confirm_action.blocked_on_attachment_turns must be true"
    )
    assert tool.requires_affirmation is True, (
        "tools.confirm_action.requires_affirmation must be true"
    )
    assert tool.requires_verified_session is True, (
        "tools.confirm_action.requires_verified_session must be true"
    )


def test_only_confirm_action_is_blocked_on_attachment_turns(monkeypatch):
    tools = _real_config(monkeypatch).tools
    blocked = {name for name, tool in tools.items() if tool.blocked_on_attachment_turns}
    assert blocked == {"confirm_action"}, (
        "only tools.confirm_action.blocked_on_attachment_turns may be true; "
        f"got {sorted(blocked)}"
    )


def test_propose_tools_stay_confirmation_gated(monkeypatch):
    tools = _real_config(monkeypatch).tools
    for name in ("open_dispute", "block_card"):
        assert tools[name].requires_confirmation is True, (
            f"tools.{name}.requires_confirmation must stay true "
            "(the propose step must remain confirmation-gated)"
        )


def test_confirmation_limits_are_safe(monkeypatch):
    confirmation = _real_config(monkeypatch).settings.confirmation
    assert 1 <= confirmation.max_turns <= 3, (
        "settings.confirmation.max_turns must be between 1 and 3 inclusive"
    )
    assert confirmation.reject_digits is True, (
        "settings.confirmation.reject_digits must be true"
    )
    assert confirmation.max_tokens <= 10, (
        "settings.confirmation.max_tokens must be at most 10"
    )


def test_confirmation_word_lists_reject_ambiguous_yes(monkeypatch):
    confirmation = _real_config(monkeypatch).settings.confirmation
    affirmatives = set(confirmation.affirmative_words) | set(confirmation.affirmative_phrases)
    for word in ("ok", "okay", "thanks", "alright", "go on"):
        assert word not in affirmatives, (
            f"confirmation affirmative lists must not contain {word!r}"
        )
    for word in ("no", "not", "dont", "stop", "cancel", "wait", "but", "if"):
        assert word in confirmation.negative_words, (
            f"settings.confirmation.negative_words must contain {word!r}"
        )


def test_committed_web_config_never_enables_dev_otp(monkeypatch):
    web = _real_config(monkeypatch).settings.adapters.web
    assert web.allow_dev_otp is False, (
        "settings.adapters.web.allow_dev_otp must be false: "
        "a committed config must never enable the dev OTP route"
    )


def test_committed_uploads_stay_disabled():
    config = load_attachments_config(config_dir="config")
    assert config.enabled is False, (
        "attachments.enabled must be false: "
        "uploads stay disabled until the live acceptance run passes"
    )
