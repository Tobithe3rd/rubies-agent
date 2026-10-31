import sqlite3
import hashlib
import datetime

import pytest
from fastapi.testclient import TestClient

from core.config import ConfigError, load_config
from providers.datastore.sqlite import SQLiteDataStore
from bank_api.auth import AuthService, normalise_phone
from bank_api.main import create_app


def tiny_dataset():
    return {
        "customers": [
            {"id": 1, "full_name": "Alice Test", "phone": "+2348030000001", "created_at": "2026-01-01"},
            {"id": 2, "full_name": "Bob Test", "phone": "+2348030000002", "created_at": "2026-01-01"},
        ],
        "accounts": [
            {"id": 1, "customer_id": 1, "account_number": "1000000001", "account_type": "savings",
             "kyc_tier": "tier1", "balance_kobo": 1000000, "status": "active", "opened_at": "2026-01-01"},
            {"id": 2, "customer_id": 2, "account_number": "1000000002", "account_type": "savings",
             "kyc_tier": "tier1", "balance_kobo": 1000000, "status": "active", "opened_at": "2026-01-01"},
        ],
        "transactions": [], "cards": [], "loans": [], "disputes": [], "otps": [], "sessions": [],
    }


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    c = load_config()
    c.settings.bank_api.db_path = str(tmp_path / "bank.db")
    c.settings.bank_api.otp_log_path = str(tmp_path / "otp.log")
    c.settings.bank_api.otp_max_attempts = 3
    monkeypatch.setattr("bank_api.main.load_config", lambda config_dir="config": c)
    return c


@pytest.fixture
def datastore(cfg):
    ds = SQLiteDataStore(cfg.settings.bank_api, cfg.env)
    ds.init_schema()
    ds.insert_seed_data(tiny_dataset())
    return ds


class FakeSender:
    def __init__(self):
        self.sent = []

    def describe(self):
        return "fake"

    def send(self, phone, code):
        self.sent.append((phone, code))


def make_service(cfg, datastore, clock=None, sender=None):
    return AuthService(datastore, cfg, cfg.env, otp_sender=sender or FakeSender(), clock=clock)


def last_code(sender):
    return sender.sent[-1][1]


def sha256_hex(value):
    return hashlib.sha256(value.encode()).hexdigest()


class TestRequestOTP:
    def test_known_and_unknown_identical_and_no_code(self, cfg, datastore):
        sender = FakeSender()
        svc = make_service(cfg, datastore, sender=sender)
        known = svc.request_otp("+2348030000001")
        unknown = svc.request_otp("+2349999999999")
        assert known == unknown
        code = last_code(sender)
        assert code not in str(known)
        conn = sqlite3.connect(cfg.settings.bank_api.db_path)
        assert conn.execute("SELECT COUNT(*) FROM otps WHERE phone = ?", ("+2348030000001",)).fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM otps WHERE phone = ?", ("+2349999999999",)).fetchone()[0] == 0
        conn.close()

    def test_phone_normalisation(self):
        assert normalise_phone("08030000001") == "+2348030000001"
        assert normalise_phone("2348030000001") == "+2348030000001"
        assert normalise_phone("+2348030000001") == "+2348030000001"


class TestVerifyOTP:
    def test_correct_code_returns_token_and_only_hashes_stored(self, cfg, datastore):
        sender = FakeSender()
        svc = make_service(cfg, datastore, sender=sender)
        svc.request_otp("+2348030000001")
        code = last_code(sender)
        result = svc.verify_otp("+2348030000001", code)
        assert result["ok"] is True
        token = result["token"]
        conn = sqlite3.connect(cfg.settings.bank_api.db_path)
        conn.row_factory = sqlite3.Row
        # token stored only as sha256 hex
        row = conn.execute("SELECT token_hash FROM sessions").fetchone()
        assert row["token_hash"] == sha256_hex(token)
        # raw token and raw code appear nowhere
        for table in ("otps", "sessions", "audit_log"):
            rows = conn.execute(f"SELECT * FROM {table}").fetchall()
            blob = " ".join(str(dict(r)) for r in rows)
            assert token not in blob
            assert code not in blob
        conn.close()

    def test_wrong_code_increments_then_locks(self, cfg, datastore):
        sender = FakeSender()
        svc = make_service(cfg, datastore, sender=sender)
        svc.request_otp("+2348030000001")
        code = last_code(sender)
        for _ in range(cfg.settings.bank_api.otp_max_attempts):
            r = svc.verify_otp("+2348030000001", "000000")
            assert r["error"] == "invalid_or_expired"
        # correct code now locked
        r = svc.verify_otp("+2348030000001", code)
        assert r["error"] == "otp_locked"

    def test_expired_otp_rejected(self, cfg, datastore):
        sender = FakeSender()
        state = {"t": datetime.datetime(2026, 1, 1, 12, 0, 0)}
        svc = make_service(cfg, datastore, sender=sender, clock=lambda: state["t"])
        svc.request_otp("+2348030000001")
        code = last_code(sender)
        state["t"] = state["t"] + datetime.timedelta(seconds=cfg.settings.bank_api.otp_ttl_seconds + 1)
        r = svc.verify_otp("+2348030000001", code)
        assert r["error"] == "invalid_or_expired"

    def test_used_otp_rejected(self, cfg, datastore):
        sender = FakeSender()
        svc = make_service(cfg, datastore, sender=sender)
        svc.request_otp("+2348030000001")
        code = last_code(sender)
        assert svc.verify_otp("+2348030000001", code)["ok"] is True
        r = svc.verify_otp("+2348030000001", code)
        assert r["error"] == "invalid_or_expired"


class TestSessions:
    def test_resolve_and_logout(self, cfg, datastore):
        sender = FakeSender()
        svc = make_service(cfg, datastore, sender=sender)
        svc.request_otp("+2348030000001")
        token = svc.verify_otp("+2348030000001", last_code(sender))["token"]
        assert svc.resolve_session(token) == 1
        svc.logout(token)
        assert svc.resolve_session(token) is None

    def test_garbage_token_is_none(self, cfg, datastore):
        svc = make_service(cfg, datastore)
        assert svc.resolve_session("not-a-real-token") is None


class TestAPI:
    def test_me_flow(self, cfg, datastore):
        sender = FakeSender()
        svc = make_service(cfg, datastore, sender=sender)
        svc.request_otp("+2348030000001")
        token = svc.verify_otp("+2348030000001", last_code(sender))["token"]
        with TestClient(create_app()) as client:
            r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200
            assert r.json()["customer_id"] == 1
            assert r.json()["full_name"] == "Alice Test"
            # no token
            assert client.get("/me").status_code == 401
            # garbage token
            assert client.get("/me", headers={"Authorization": "Bearer garbage"}).status_code == 401

    def test_me_ignores_customer_id_in_query(self, cfg, datastore):
        sender = FakeSender()
        svc = make_service(cfg, datastore, sender=sender)
        svc.request_otp("+2348030000001")
        token = svc.verify_otp("+2348030000001", last_code(sender))["token"]
        with TestClient(create_app()) as client:
            r = client.get("/me?customer_id=2", headers={"Authorization": f"Bearer {token}"})
            assert r.status_code == 200
            assert r.json()["customer_id"] == 1

    def test_revoked_token_fails(self, cfg, datastore):
        sender = FakeSender()
        svc = make_service(cfg, datastore, sender=sender)
        svc.request_otp("+2348030000001")
        token = svc.verify_otp("+2348030000001", last_code(sender))["token"]
        with TestClient(create_app()) as client:
            assert client.post("/auth/logout", headers={"Authorization": f"Bearer {token}"}).status_code == 200
            assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401

    def test_expired_token_fails(self, cfg, datastore):
        sender = FakeSender()
        svc = make_service(cfg, datastore, sender=sender)
        svc.request_otp("+2348030000001")
        token = svc.verify_otp("+2348030000001", last_code(sender))["token"]
        conn = sqlite3.connect(cfg.settings.bank_api.db_path)
        conn.execute("UPDATE sessions SET expires_at = ?", ("2000-01-01 00:00:00",))
        conn.commit()
        conn.close()
        with TestClient(create_app()) as client:
            assert client.get("/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401

    def test_request_otp_and_verify_routes(self, cfg, datastore):
        with TestClient(create_app()) as client:
            r = client.post("/auth/request-otp", json={"phone": "+2348030000001"})
            assert r.status_code == 200
            # extra fields rejected
            assert client.post("/auth/request-otp", json={"phone": "+2348030000001", "x": 1}).status_code == 422
            # bad code shape
            assert client.post("/auth/verify", json={"phone": "+2348030000001", "code": "abc"}).status_code == 422


class TestAudit:
    def test_audit_rows_and_no_secrets(self, cfg, datastore):
        sender = FakeSender()
        svc = make_service(cfg, datastore, sender=sender)
        svc.request_otp("+2348030000001")
        code = last_code(sender)
        svc.verify_otp("+2348030000001", "000000")  # failure
        token = svc.verify_otp("+2348030000001", code)["token"]  # success
        svc.logout(token)
        conn = sqlite3.connect(cfg.settings.bank_api.db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM audit_log").fetchall()
        actions = {r["action"] for r in rows}
        assert "request_otp" in actions
        assert "verify_otp" in actions
        assert "logout" in actions
        blob = " ".join(str(dict(r)) for r in rows)
        assert code not in blob
        assert token not in blob
        conn.close()


class TestStartupFailFast:
    def test_missing_secret_fails(self, monkeypatch):
        monkeypatch.delenv("OTP_HASH_SECRET", raising=False)
        monkeypatch.setattr("core.config.load_dotenv", lambda: None)
        with pytest.raises(ConfigError):
            load_config()

    def test_short_secret_fails(self, monkeypatch):
        monkeypatch.setenv("OTP_HASH_SECRET", "short")
        monkeypatch.setattr("core.config.load_dotenv", lambda: None)
        with pytest.raises(ConfigError):
            load_config()
