import io
import shutil
import uuid
from types import SimpleNamespace

import pytest

from adapters.cli_chat import CliAdapter
from core.config import ConfigError, load_config


def _set_env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
    monkeypatch.setenv("OTP_HASH_SECRET", "test-secret-at-least-16-chars")


class FakeRunner:
    """Scripted runner: records messages, no AWS and no agent."""

    def __init__(self):
        self.session = SimpleNamespace(session_id=str(uuid.uuid4()), token=None)
        self.calls = []

    def handle_message(self, text):
        self.calls.append(text)
        return f"reply to {text}"


def run_cli(cfg, runner, text, runner_factory=None):
    out = io.StringIO()
    adapter = CliAdapter(
        cfg,
        cfg.env,
        runner,
        input_stream=io.StringIO(text),
        output_stream=out,
        runner_factory=runner_factory,
    )
    rc = adapter.run()
    return rc, out.getvalue(), adapter


@pytest.fixture
def cfg(monkeypatch):
    _set_env(monkeypatch)
    return load_config(config_dir="config")


class TestCliCommands:
    def test_commands_do_not_reach_the_runner(self, cfg):
        runner = FakeRunner()
        rc, out, _ = run_cli(cfg, runner, "hello\n/help\n/otp\n/quit\n")
        assert rc == 0
        assert runner.calls == ["hello"]
        assert "Commands" in out  # /help printed
        assert "/otp" in out

    def test_empty_line_makes_no_runner_call(self, cfg):
        runner = FakeRunner()
        rc, out, _ = run_cli(cfg, runner, "\n   \n/quit\n")
        assert rc == 0
        assert runner.calls == []
        assert "reply to" not in out

    def test_eof_exits_cleanly(self, cfg):
        runner = FakeRunner()
        rc, out, _ = run_cli(cfg, runner, "hello\n")
        assert rc == 0
        assert runner.calls == ["hello"]
        assert "reply to hello" in out

    def test_new_starts_a_new_session(self, cfg):
        first = FakeRunner()
        made = []

        def factory():
            runner = FakeRunner()
            made.append(runner)
            return runner

        rc, out, adapter = run_cli(cfg, first, "hi\n/new\n/quit\n", runner_factory=factory)
        assert rc == 0
        assert len(made) == 1
        assert adapter.runner is made[0]
        assert adapter.runner.session.session_id != first.session.session_id
        assert first.calls == ["hi"]
        assert made[0].calls == []  # /new and /quit never reach the model
        assert "new session" in out.lower()


class TestCliOtp:
    def test_otp_disabled_by_config(self, cfg):
        cfg.settings.adapters.cli.allow_otp_command = False
        runner = FakeRunner()
        rc, out, _ = run_cli(cfg, runner, "/otp\n/quit\n")
        assert rc == 0
        assert "disabled" in out.lower()
        assert "DEV ONLY" not in out
        assert runner.calls == []

    def test_otp_enabled_prints_dev_only_line(self, cfg, tmp_path):
        cfg.settings.adapters.cli.allow_otp_command = True
        otp_path = tmp_path / "otp.log"
        otp_path.write_text("+2348115678901, 123456, 2026-01-01T00:00:00\n")
        cfg.settings.bank_api.otp_log_path = str(otp_path)
        runner = FakeRunner()
        rc, out, _ = run_cli(cfg, runner, "/otp\n/quit\n")
        assert rc == 0
        assert "DEV ONLY" in out
        assert "123456" in out
        assert runner.calls == []

    def test_token_is_never_printed(self, cfg):
        runner = FakeRunner()
        runner.session.token = "SUPER-SECRET-TOKEN"
        rc, out, _ = run_cli(cfg, runner, "hello\n/quit\n")
        assert rc == 0
        assert "SUPER-SECRET-TOKEN" not in out


class TestCliConfigFailFast:
    def _config_copy(self, tmp_path):
        dest = tmp_path / "config"
        shutil.copytree("config", dest)
        return dest

    def _edit(self, path, old, new):
        text = path.read_text()
        assert old in text, f"{old!r} not found in {path}"
        path.write_text(text.replace(old, new, 1))

    def test_non_bool_allow_otp_command_names_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = self._config_copy(tmp_path)
        self._edit(
            cfg_dir / "settings.yaml",
            "allow_otp_command: true",
            'allow_otp_command: "yes"',
        )
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "allow_otp_command" in str(exc.value)

    def test_zero_max_attempts_names_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = self._config_copy(tmp_path)
        self._edit(
            cfg_dir / "settings.yaml",
            "max_attempts_per_scenario: 2",
            "max_attempts_per_scenario: 0",
        )
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "max_attempts_per_scenario" in str(exc.value)

    def test_empty_prompt_text_names_the_key(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg_dir = self._config_copy(tmp_path)
        self._edit(
            cfg_dir / "settings.yaml",
            'prompt_text: "You: "',
            'prompt_text: ""',
        )
        with pytest.raises(ConfigError) as exc:
            load_config(config_dir=str(cfg_dir))
        assert "prompt_text" in str(exc.value)