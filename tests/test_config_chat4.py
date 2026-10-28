import shutil

import pytest

from core.config import KNOWN_TOOLS, ConfigError, load_config


def _set_env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
    monkeypatch.setenv("OTP_HASH_SECRET", "test-secret-at-least-16-chars")


def _config_copy(tmp_path):
    dest = tmp_path / "config"
    shutil.copytree("config", dest)
    return dest


def _edit(path, old, new):
    text = path.read_text()
    assert old in text, f"{old!r} not found in {path}"
    path.write_text(text.replace(old, new, 1))


class TestAgentAndTimezoneConfig:
    def test_real_config_has_timezone_and_agent(self, monkeypatch):
        _set_env(monkeypatch)
        cfg = load_config(config_dir="config")
        assert cfg.settings.timezone == "Africa/Lagos"
        assert cfg.settings.agent.max_history_messages == 40
        assert cfg.settings.agent.system_prompt_path == "prompts/system_prompt.md"

    def test_bad_timezone_names_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(cfg_dir / "settings.yaml", "timezone: Africa/Lagos", "timezone: Mars/Base")
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "timezone" in str(exc.value)

    def test_zero_max_history_names_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(cfg_dir / "settings.yaml", "max_history_messages: 40", "max_history_messages: 0")
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "max_history_messages" in str(exc.value)

    def test_zero_timeout_names_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(cfg_dir / "settings.yaml", "tool_timeout_seconds: 15", "tool_timeout_seconds: 0")
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "tool_timeout_seconds" in str(exc.value)


class TestToolsSchema:
    def test_real_tools_yaml_is_the_eleven_tool_contract(self, monkeypatch):
        _set_env(monkeypatch)
        cfg = load_config(config_dir="config")
        assert set(cfg.tools) == set(KNOWN_TOOLS)
        assert len(cfg.tools) == 11
        confirm = {name for name, t in cfg.tools.items() if t.requires_confirmation}
        assert confirm == {"open_dispute", "block_card"}
        assert cfg.tools["confirm_action"].requires_confirmation is False
        assert cfg.tools["confirm_action"].requires_verified_session is True

    def test_missing_tool_key_fails(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(
            cfg_dir / "tools.yaml",
            'get_balance:\n  enabled: true\n  requires_confirmation: false\n'
            '  requires_verified_session: true\n'
            '  description: "Return the verified customer\'s current account balance."\n',
            'get_balance:\n  enabled: true\n  requires_confirmation: false\n'
            '  description: "Return the verified customer\'s current account balance."\n',
        )
        with pytest.raises(ConfigError):
            load_config(config_dir=str(cfg_dir))

    def test_unknown_tool_name_fails_and_is_named(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        tools = cfg_dir / "tools.yaml"
        tools.write_text(
            tools.read_text()
            + "\nnot_a_tool:\n  enabled: true\n  requires_confirmation: false\n"
            "  requires_verified_session: false\n  description: x\n"
        )
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "not_a_tool" in str(exc.value)

    def test_empty_description_fails(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(
            cfg_dir / "tools.yaml",
            '  description: "Return the verified customer\'s current account balance."',
            '  description: ""',
        )
        with pytest.raises(ConfigError):
            load_config(config_dir=str(cfg_dir))
