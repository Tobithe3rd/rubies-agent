import json
from datetime import datetime
from types import SimpleNamespace

from agent.tool_logger import JsonlToolLogger
from core.clock import Clock


def make_cfg(tmp_path, debug=False):
    return SimpleNamespace(
        settings=SimpleNamespace(
            timezone="Africa/Lagos",
            logging=SimpleNamespace(
                tool_log_path=str(tmp_path / "tool_calls.jsonl"),
                debug=debug,
                redact_keys=["otp", "token", "session_token", "authorization"],
                mask_phone_keep_last=4,
                pending_token_prefix_chars=4,
            ),
        )
    )


def frozen_clock():
    return Clock("Africa/Lagos", now_source=lambda: datetime(2026, 1, 1, 0, 0))


class TestRedaction:
    def test_redact_keys_at_any_depth(self, tmp_path):
        logger = JsonlToolLogger(make_cfg(tmp_path), clock=frozen_clock())
        redacted = logger.redact(
            {
                "token": "SECRET",
                "nested": {"otp": "123456", "safe": "ok"},
                "items": [{"session_token": "T"}, {"authorization": "Bearer X"}],
            }
        )
        assert redacted["token"] == "***"
        assert redacted["nested"]["otp"] == "***"
        assert redacted["nested"]["safe"] == "ok"
        assert redacted["items"][0]["session_token"] == "***"
        assert redacted["items"][1]["authorization"] == "***"

    def test_phone_keeps_last_digits_and_pending_token_prefix(self, tmp_path):
        logger = JsonlToolLogger(make_cfg(tmp_path), clock=frozen_clock())
        redacted = logger.redact(
            {
                "phone": "+2348031234567",
                "local_phone": "08031234567",
                "pending_token": "abcdefgh",
            }
        )
        assert redacted["phone"].endswith("4567")
        assert redacted["phone"].startswith("*")
        assert "234803" not in redacted["phone"]
        assert redacted["local_phone"] == "*******4567"
        assert redacted["pending_token"] == "abcd..."


class TestLogFile:
    def test_writes_one_json_line_with_redacted_inputs(self, tmp_path):
        logger = JsonlToolLogger(make_cfg(tmp_path), clock=frozen_clock())
        logger.log(
            session_id="session-1",
            tool="verify_customer",
            inputs={"phone": "08031234567", "otp": "123456"},
            ok=False,
            error={"code": "verification_failed", "message": "bad code"},
            duration_ms=3,
        )
        lines = (tmp_path / "tool_calls.jsonl").read_text().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert set(payload) >= {"time", "session_id", "tool", "inputs", "ok", "duration_ms"}
        assert payload["time"].endswith("+01:00")
        assert payload["ok"] is False
        assert payload["inputs"]["phone"] == "*******4567"
        assert payload["inputs"]["otp"] == "***"
        assert payload["error"]["code"] == "verification_failed"
        assert "result" not in payload
        assert "123456" not in lines[0]

    def test_writes_result_only_when_ok_and_masks_pending(self, tmp_path):
        logger = JsonlToolLogger(make_cfg(tmp_path), clock=frozen_clock())
        logger.log(
            session_id="s",
            tool="open_dispute",
            inputs={"reference": "RUB-DB-002"},
            ok=True,
            result={"token": "SECRET", "pending_token": "abcdefgh", "summary": "Open"},
            duration_ms=1,
        )
        raw = (tmp_path / "tool_calls.jsonl").read_text()
        payload = json.loads(raw)
        assert payload["result"]["token"] == "***"
        assert payload["result"]["pending_token"] == "abcd..."
        assert "SECRET" not in raw
        assert "abcdefgh" not in raw

    def test_write_failure_is_swallowed_and_warns(self, tmp_path, capsys):
        bad_path = tmp_path / "a_directory"
        bad_path.mkdir()
        cfg = make_cfg(tmp_path)
        cfg.settings.logging.tool_log_path = str(bad_path)
        logger = JsonlToolLogger(cfg, clock=frozen_clock())
        logger.log(
            session_id="s", tool="get_balance", inputs={}, ok=False,
            error={"code": "not_verified", "message": "x"},
        )
        captured = capsys.readouterr()
        assert "warning" in captured.err.lower()

    def test_time_uses_injected_clock(self, tmp_path):
        logger = JsonlToolLogger(make_cfg(tmp_path), clock=frozen_clock())
        logger.log(session_id="s", tool="get_balance", inputs={}, ok=True, result={})
        payload = json.loads((tmp_path / "tool_calls.jsonl").read_text())
        assert payload["time"] == "2026-01-01T00:00:00+01:00"
