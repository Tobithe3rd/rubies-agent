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


class TestToolLoggingAndHandoffConfig:
    def test_real_config_has_logging_and_handoff_keys(self, monkeypatch):
        _set_env(monkeypatch)
        cfg = load_config(config_dir="config")
        assert cfg.settings.logging.redact_keys == [
            "otp", "token", "session_token", "authorization",
        ]
        assert cfg.settings.logging.mask_phone_keep_last == 4
        assert cfg.settings.logging.pending_token_prefix_chars == 4
        assert cfg.settings.handoff.max_failed_retrievals == 2
        assert cfg.settings.handoff.max_failed_verifications == 3

    def test_empty_redact_keys_fails_naming_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(
            cfg_dir / "settings.yaml",
            "redact_keys: [otp, token, session_token, authorization]",
            "redact_keys: []",
        )
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "redact_keys" in str(exc.value)

    def test_zero_mask_phone_fails_naming_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(cfg_dir / "settings.yaml", "mask_phone_keep_last: 4", "mask_phone_keep_last: 0")
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "mask_phone_keep_last" in str(exc.value)

    def test_zero_pending_prefix_fails_naming_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(
            cfg_dir / "settings.yaml",
            "pending_token_prefix_chars: 4",
            "pending_token_prefix_chars: 0",
        )
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "pending_token_prefix_chars" in str(exc.value)

    def test_zero_max_failed_retrievals_fails_naming_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(
            cfg_dir / "settings.yaml",
            "  max_failed_retrievals: 2\n  max_failed_verifications: 3",
            "  max_failed_retrievals: 0\n  max_failed_verifications: 3",
        )
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "max_failed_retrievals" in str(exc.value)

    def test_zero_max_failed_verifications_fails_naming_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(
            cfg_dir / "settings.yaml",
            "  max_failed_retrievals: 2\n  max_failed_verifications: 3",
            "  max_failed_retrievals: 2\n  max_failed_verifications: 0",
        )
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "max_failed_verifications" in str(exc.value)

    def test_blank_handoff_phrase_names_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(
            cfg_dir / "settings.yaml",
            '  request_phrases_en:\n    - "talk to human"',
            '  request_phrases_en:\n    - ""',
        )
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "request_phrases_en" in str(exc.value)

    def test_handoff_phrase_empty_after_ignore_words_names_the_key(
        self, tmp_path, monkeypatch
    ):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(
            cfg_dir / "settings.yaml",
            '  request_phrases_en:\n    - "talk to human"',
            '  request_phrases_en:\n    - "the"',
        )
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "request_phrases_en" in str(exc.value)
        assert "ignore_words" in str(exc.value)

    def test_handoff_summary_limits_fail_naming_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        for old, new, key in (
            ("summary_max_tokens: 160", "summary_max_tokens: 0", "summary_max_tokens"),
            ("summary_timeout_seconds: 20", "summary_timeout_seconds: 0", "summary_timeout_seconds"),
        ):
            cfg_dir = tmp_path / key
            shutil.copytree("config", cfg_dir)
            _edit(cfg_dir / "settings.yaml", old, new)
            with pytest.raises(ConfigError) as exc:
                load_config(config_dir=str(cfg_dir))
            assert key in str(exc.value)


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


class TestLLMAndAgentRuntimeConfig:
    def test_real_config_has_runtime_keys(self, monkeypatch):
        _set_env(monkeypatch)
        cfg = load_config(config_dir="config")
        assert cfg.settings.llm.temperature == 0.2
        assert cfg.settings.llm.max_tokens == 1024
        assert cfg.settings.agent.max_tool_calls_per_turn == 8
        assert cfg.settings.agent.fallback_message.strip()

    def test_temperature_above_one_names_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(cfg_dir / "settings.yaml", "temperature: 0.2", "temperature: 5")
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "temperature" in str(exc.value)

    def test_zero_max_tool_calls_per_turn_names_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(
            cfg_dir / "settings.yaml",
            "max_tool_calls_per_turn: 8",
            "max_tool_calls_per_turn: 0",
        )
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "max_tool_calls_per_turn" in str(exc.value)

    def test_empty_fallback_message_names_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        text = (cfg_dir / "settings.yaml").read_text()
        text = text.replace(
            '  fallback_message: "Sorry, something went wrong on my side. Please try again, '
            'or ask for a human agent and I will pass you over."',
            '  fallback_message: ""',
        )
        (cfg_dir / "settings.yaml").write_text(text)
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "fallback_message" in str(exc.value)

    def test_unknown_llm_provider_names_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = _config_copy(tmp_path)
        _edit(cfg_dir / "settings.yaml", "provider: bedrock", "provider: nonsense")
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "llm.provider" in str(exc.value) or "provider" in str(exc.value)
