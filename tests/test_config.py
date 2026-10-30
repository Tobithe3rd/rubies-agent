import os
import pytest
from pathlib import Path

from core.config import load_config, ConfigError, masked_summary


class TestConfigLoad:
    def test_real_config_files_load(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "test-key")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "test-secret")
        app = load_config(config_dir="config")
        assert app.settings.llm.provider == "bedrock"
        assert app.tools["verify_customer"].enabled is True
        assert app.env.BANK_API_URL == "http://localhost:8001"

    def test_unknown_key_raises_config_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
        bad_settings = tmp_path / "bad_settings.yaml"
        bad_settings.write_text("unknown_key: 1\n")
        # We test via loading a full bad settings by monkeypatching settings file
        # Instead, test validation directly by injecting a bad settings dict
        from core.config import Settings
        with pytest.raises(ConfigError):
            # Using load_config with a fake config dir containing bad settings
            bad_dir = tmp_path / "bad_config"
            bad_dir.mkdir()
            (bad_dir / "settings.yaml").write_text("llm:\n  unknown_key: x\n")
            (bad_dir / "tools.yaml").write_text("verify_customer:\n  enabled: true\n  requires_confirmation: false\n  requires_verified_session: false\n  description: ok\n")
            load_config(config_dir=str(bad_dir))

    def test_out_of_range_value_raises_config_error(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
        bad_dir = tmp_path / "bad_config"
        bad_dir.mkdir()
        (bad_dir / "settings.yaml").write_text("llm:\n  provider: bedrock\n  model_id: x\n  temperature: 5.0\n  max_tokens: 1024\nembeddings:\n  provider: bedrock_titan\n  model_id: x\n  dimensions: 1024\nvectorstore:\n  type: chroma\n  path: data/runtime/chroma\n  collection: rubies_policies\nrag:\n  docs_path: rag/docs\n  chunking_mode: heading\n  top_k: 4\n  similarity_threshold: 0.35\n  max_failed_retrievals: 2\nsession:\n  expiry_minutes: 15\n  max_failed_verifications: 3\nhandoff:\n  max_repeated_tool_errors: 3\nlogging:\n  tool_log_path: logs/tool_calls.jsonl\n  debug: false\nadapter:\n  type: http_chat\n  host: 0.0.0.0\n  port: 8000\nbank_api:\n  db_path: data/runtime/bank.db\n")
        (bad_dir / "tools.yaml").write_text("verify_customer:\n  enabled: true\n  requires_confirmation: false\n  requires_verified_session: false\n  description: ok\n")
        with pytest.raises(ConfigError):
            load_config(config_dir=str(bad_dir))

    def test_missing_required_env_var_raises_config_error(self, monkeypatch, tmp_path):
        monkeypatch.delenv("AWS_REGION", raising=False)
        monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
        # Prevent .env file from restoring AWS_REGION
        monkeypatch.setattr("core.config.load_dotenv", lambda: None)
        with pytest.raises(ConfigError):
            load_config(config_dir="config")

    def test_masked_summary_contains_no_secret_values(self, monkeypatch):
        monkeypatch.setenv("AWS_REGION", "us-east-1")
        monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIASECRET")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "token123")
        app = load_config(config_dir="config")
        summary = masked_summary(app)
        summary_str = str(summary)
        assert "AKIASECRET" not in summary_str
        assert "secret" not in summary_str
        assert "token123" not in summary_str
        assert "***" in summary_str
