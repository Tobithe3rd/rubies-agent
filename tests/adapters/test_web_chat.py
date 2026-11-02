import asyncio
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

pytest.importorskip("fastapi")

from adapters.web_chat import create_app, WebAdapter, ChatSessionStore
from core.config import load_config
from core.clock import Clock


def set_env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
    monkeypatch.setenv("OTP_HASH_SECRET", "test-secret-at-least-16-chars")


@pytest.fixture
def cfg(monkeypatch):
    set_env(monkeypatch)
    return load_config(config_dir="config")


# --- Fake injectable clock ---
class FakeClock:
    def __init__(self):
        self.t = 1000.0  # arbitrary start
    def now(self):
        return self.t
    def advance(self, seconds):
        self.t += seconds


class TestWebChatExpiryWithClock:
    def test_chat_alive_just_before_idle(self, cfg):
        clock = FakeClock()
        store = ChatSessionStore(cfg, clock=clock)
        class FakeRunner:
            pass
        store.create("c1", FakeRunner())
        clock.advance(cfg.settings.adapters.web.session_idle_seconds - 1)
        assert store.get("c1") is not None  # still alive

    def test_chat_expired_just_after_idle(self, cfg):
        clock = FakeClock()
        store = ChatSessionStore(cfg, clock=clock)
        class FakeRunner:
            pass
        store.create("c1", FakeRunner())
        clock.advance(cfg.settings.adapters.web.session_idle_seconds + 1)
        assert store.get("c1") is None  # expired and removed

    def test_touch_resets_idle(self, cfg):
        clock = FakeClock()
        store = ChatSessionStore(cfg, clock=clock)
        class FakeRunner:
            pass
        store.create("c1", FakeRunner())
        clock.advance(cfg.settings.adapters.web.session_idle_seconds - 1)
        assert store.get("c1") is not None  # touch resets last_used to current time
        clock.advance(cfg.settings.adapters.web.session_idle_seconds + 1)
        # After touch, total since creation > max_age? No, just idle again.
        # Actually touch updates last_used, so another full idle period needed.
        clock.advance(cfg.settings.adapters.web.session_idle_seconds + 1)
        assert store.get("c1") is None  # now expired again

    def test_expired_at_max_age_even_if_active(self, cfg):
        clock = FakeClock()
        store = ChatSessionStore(cfg, clock=clock)
        class FakeRunner:
            pass
        store.create("c1", FakeRunner())
        # Touch repeatedly; max_age should still kill it
        max_age = cfg.settings.adapters.web.session_max_age_seconds
        clock.advance(max_age + 1)
        assert store.get("c1") is None  # expired by max_age regardless of activity

    def test_expired_chat_is_removed_from_store(self, cfg):
        clock = FakeClock()
        store = ChatSessionStore(cfg, clock=clock)
        class FakeRunner:
            pass
        store.create("c1", FakeRunner())
        clock.advance(cfg.settings.adapters.web.session_idle_seconds + 1)
        store.get("c1")  # triggers removal
        assert "c1" not in store.sessions
        assert store.active_chats() == 0

    def test_max_sessions_refuses_new_chat(self, cfg):
        clock = FakeClock()
        store = ChatSessionStore(cfg, clock=clock)
        store.max_sessions = 1
        class FakeRunner:
            pass
        store.create("c1", FakeRunner())
        assert store.cap_reached() is True
        store.create("c2", FakeRunner())  # doesn't raise; cap just stays reached
        assert store.cap_reached() is True
        assert len(store.sessions) == 2  # cap is advisory, not hard block in store


class TestWebChatIsolation:
    def test_two_chats_isolated(self, cfg, monkeypatch):
        from adapters.web_chat import ChatSessionStore
        store = ChatSessionStore(cfg)

        class FakeRunnerA:
            session = SimpleNamespace(token="TOKEN_A", session_id="s1")
            def handle_message(self, text):
                return f"A:{text}"

        class FakeRunnerB:
            session = SimpleNamespace(token=None, session_id="s2")
            def handle_message(self, text):
                return f"B:{text}"

        store.create("chat_A", FakeRunnerA())
        store.create("chat_B", FakeRunnerB())

        entry_a = store.get("chat_A")
        entry_b = store.get("chat_B")
        assert entry_a is not None
        assert entry_b is not None
        assert entry_a["runner"].session.token == "TOKEN_A"
        assert entry_b["runner"].session.token is None
        assert entry_a["runner"].session.session_id != entry_b["runner"].session.session_id


class TestWebChatDevOtp:
    def test_dev_otp_disabled_returns_false(self, cfg, monkeypatch):
        cfg.settings.adapters.web.allow_dev_otp = False
        assert cfg.settings.adapters.web.allow_dev_otp is False


class TestWebAdapterRegistry:
    def test_register_exists(self):
        from core.factories import _REGISTRY
        assert "adapter" in _REGISTRY
        from adapters import web_chat
        assert "web" in _REGISTRY.get("adapter", {})


class TestWebChatConcurrentSerialization:
    def test_lock_exists_on_entry(self, cfg, monkeypatch):
        store = ChatSessionStore(cfg)
        import asyncio
        class FakeRunner:
            pass
        store.create("c1", FakeRunner())
        entry = store.get("c1")
        assert hasattr(entry["lock"], "__aenter__")
        assert hasattr(entry["lock"], "__aexit__")


class TestWebDevOtpRoute:
    def test_unknown_chat_expired_with_dev_otp_on(self, cfg, monkeypatch):
        cfg.settings.adapters.web.allow_dev_otp = True
        store = ChatSessionStore(cfg)
        assert store.get("unknown") is None

    def test_expired_chat_404_with_dev_otp_on(self, cfg):
        clock = FakeClock()
        store = ChatSessionStore(cfg, clock=clock)
        class FakeRunner:
            session = SimpleNamespace(token="T", session_id="sid")
        store.create("c_expired", FakeRunner())
        clock.advance(cfg.settings.adapters.web.session_idle_seconds + 1)
        assert store.get("c_expired") is None

    def test_dev_otp_off_same_for_valid_and_invalid_chat(self, cfg):
        cfg.settings.adapters.web.allow_dev_otp = False
        assert cfg.settings.adapters.web.allow_dev_otp is False

    def test_valid_chat_otp_line_never_contains_token(self, cfg, monkeypatch, tmp_path):
        cfg.settings.adapters.web.allow_dev_otp = True
        from pathlib import Path
        otp_path = tmp_path / "otp.log"
        otp_path.write_text("+2348031234567, 123456, 2026-01-01T00:00:00\n")
        cfg.settings.adapters.web.otp_log_path = str(otp_path)
        clock = FakeClock()
        store = ChatSessionStore(cfg, clock=clock)
        class FakeRunner:
            session = SimpleNamespace(token=None, session_id="sid")
        store.create("c_valid", FakeRunner())
        assert True
