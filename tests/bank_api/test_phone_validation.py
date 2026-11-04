import sqlite3

import pytest
from fastapi.testclient import TestClient

from core.config import BankAPIConfig, load_config
from pydantic import ValidationError
from providers.datastore.sqlite import SQLiteDataStore
from bank_api.auth import INVALID_PHONE_MESSAGE, AuthService, normalise_phone
from bank_api.main import create_app


KNOWN = "+2348030000001"
UNKNOWN = "+2349999999999"
MALFORMED = [
    "abc",
    "0803",
    "080300000011",
    "+15551234567",
    "",
    "08030000001 2",
    "0803000000",
]


def tiny_dataset():
    return {
        "customers": [
            {"id": 1, "full_name": "Alice Test", "phone": KNOWN, "created_at": "2026-01-01"},
        ],
        "accounts": [
            {"id": 1, "customer_id": 1, "account_number": "1000000001", "account_type": "savings",
             "kyc_tier": "tier1", "balance_kobo": 1000000, "status": "active", "opened_at": "2026-01-01"},
        ],
        "transactions": [], "cards": [], "loans": [], "disputes": [], "otps": [], "sessions": [],
    }


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    c = load_config()
    c.settings.bank_api.db_path = str(tmp_path / "bank.db")
    c.settings.bank_api.otp_log_path = str(tmp_path / "otp.log")
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


def db(cfg):
    conn = sqlite3.connect(cfg.settings.bank_api.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def otp_count(cfg, phone):
    conn = db(cfg)
    count = conn.execute("SELECT COUNT(*) FROM otps WHERE phone = ?", (phone,)).fetchone()[0]
    conn.close()
    return count


def audit_count(cfg):
    conn = db(cfg)
    count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    conn.close()
    return count


def otp_log(cfg):
    try:
        return open(cfg.settings.bank_api.otp_log_path).read()
    except FileNotFoundError:
        return ""


class TestNormalisation:
    @pytest.mark.parametrize("raw", [
        "08030000001",
        "0803 000 0001",
        "0803-000-0001",
        "(0803) 000 0001",
        "+2348030000001",
        "+234 (803) 000-0001",
        "2348030000001",
    ])
    def test_accepted_forms_normalise_to_e164(self, raw):
        assert normalise_phone(raw) == KNOWN

    def test_letters_are_not_stripped(self):
        assert normalise_phone("abc08030000001") != KNOWN


class TestInvalidFormat:
    @pytest.mark.parametrize("phone", MALFORMED)
    def test_request_otp_rejects_with_422_and_no_side_effects(self, cfg, datastore, phone):
        sender = FakeSender()
        svc = AuthService(datastore, cfg, cfg.env, otp_sender=sender)
        result = svc.request_otp(phone)
        assert result["error"] == "invalid_phone_format"
        assert result["status"] == 422
        assert result["message"] == INVALID_PHONE_MESSAGE
        assert sender.sent == []
        assert otp_count(cfg, KNOWN) == 0
        assert audit_count(cfg) == 0

    @pytest.mark.parametrize("phone", MALFORMED)
    def test_api_request_otp_returns_422_and_no_otp_row_or_log(self, cfg, datastore, phone):
        with TestClient(create_app()) as client:
            r = client.post("/auth/request-otp", json={"phone": phone})
        assert r.status_code == 422
        assert r.json() == {"error": "invalid_phone_format", "message": INVALID_PHONE_MESSAGE}
        assert otp_count(cfg, KNOWN) == 0
        assert otp_log(cfg) == ""
        assert audit_count(cfg) == 0

    @pytest.mark.parametrize("phone", MALFORMED)
    def test_api_verify_returns_422_and_no_side_effects(self, cfg, datastore, phone):
        with TestClient(create_app()) as client:
            r = client.post("/auth/verify", json={"phone": phone, "code": "123456"})
        assert r.status_code == 422
        assert r.json() == {"error": "invalid_phone_format", "message": INVALID_PHONE_MESSAGE}
        assert otp_count(cfg, KNOWN) == 0
        assert audit_count(cfg) == 0

    def test_service_verify_rejects_invalid_format_without_audit(self, cfg, datastore):
        svc = AuthService(datastore, cfg, cfg.env, otp_sender=FakeSender())
        result = svc.verify_otp("not-a-phone", "123456")
        assert result["error"] == "invalid_phone_format"
        assert audit_count(cfg) == 0


class TestKnownCustomer:
    @pytest.mark.parametrize("raw", [
        "08030000001",
        "0803 000 0001",
        "0803-000-0001",
        "+2348030000001",
        "2348030000001",
    ])
    def test_accepted_form_reaches_seeded_customer(self, cfg, datastore, raw):
        sender = FakeSender()
        svc = AuthService(datastore, cfg, cfg.env, otp_sender=sender)
        result = svc.request_otp(raw)
        assert result == {
            "status": "ok",
            "message": "If that number is registered with Rubies, a code is on its way.",
        }
        assert otp_count(cfg, KNOWN) == 1
        assert sender.sent and sender.sent[-1][0] == KNOWN


class TestNoEnumeration:
    def test_known_and_unknown_api_responses_are_identical(self, cfg, datastore):
        with TestClient(create_app()) as client:
            known = client.post("/auth/request-otp", json={"phone": KNOWN})
            unknown = client.post("/auth/request-otp", json={"phone": UNKNOWN})
        assert known.status_code == unknown.status_code == 200
        assert known.json() == unknown.json()
        assert otp_count(cfg, KNOWN) == 1
        assert otp_count(cfg, UNKNOWN) == 0

    def test_unknown_verify_is_indistinguishable_from_known_without_otp(self, cfg, datastore):
        with TestClient(create_app()) as client:
            known = client.post("/auth/verify", json={"phone": KNOWN, "code": "123456"})
            unknown = client.post("/auth/verify", json={"phone": UNKNOWN, "code": "123456"})
        assert known.status_code == unknown.status_code == 401
        assert known.json() == unknown.json() == {"error": "invalid_or_expired"}

    @pytest.mark.parametrize("phone", [KNOWN, UNKNOWN, "not-a-phone"])
    def test_error_bodies_do_not_reveal_registration(self, cfg, datastore, phone):
        with TestClient(create_app()) as client:
            r = client.post("/auth/request-otp", json={"phone": phone})
        body = r.text.lower()
        for word in ("not_registered", "unknown_phone", "number_not_found", "no_customer"):
            assert word not in body


class TestStartupValidation:
    def test_invalid_phone_pattern_fails_at_startup(self):
        c = load_config()
        with pytest.raises(ValidationError):
            BankAPIConfig.model_validate(
                {**c.settings.bank_api.model_dump(), "phone_pattern": "["}
            )
