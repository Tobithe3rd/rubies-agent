from datetime import datetime, timedelta, timezone

from core.clock import Clock, create_clock
from core.config import load_config


def _set_env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
    monkeypatch.setenv("OTP_HASH_SECRET", "test-secret-at-least-16-chars")


def test_fixed_source_is_converted_to_configured_timezone():
    c = Clock("Africa/Lagos", now_source=lambda: datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
    assert c.now().utcoffset() == timedelta(hours=1)
    assert c.now().hour == 13


def test_iso_now_carries_the_offset():
    c = Clock("Africa/Lagos", now_source=lambda: datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
    assert c.iso_now().endswith("+01:00")


def test_naive_local_now_has_no_tzinfo_and_same_wall_time():
    c = Clock("Africa/Lagos", now_source=lambda: datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc))
    naive = c.naive_local_now()
    assert naive.tzinfo is None
    assert naive.hour == 13


def test_timezone_is_not_hardcoded():
    c = Clock("UTC", now_source=lambda: datetime(2026, 1, 1, 12, 0))
    assert c.iso_now().endswith("+00:00")


def test_timezone_read_from_real_config(monkeypatch):
    _set_env(monkeypatch)
    c = create_clock(load_config(config_dir="config"))
    assert c.iso_now().endswith("+01:00")
