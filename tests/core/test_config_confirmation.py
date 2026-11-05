import shutil

import pytest
import yaml
from pydantic import ValidationError

from core.config import ConfirmationConfig, ConfigError, load_config


def _set_env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
    monkeypatch.setenv("OTP_HASH_SECRET", "test-secret-at-least-16-chars")


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
