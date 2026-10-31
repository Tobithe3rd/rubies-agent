import sqlite3

import pytest
from fastapi.testclient import TestClient

from core.config import load_config
from providers.datastore.sqlite import SQLiteDataStore
from bank_api.main import create_app


PHONE = "+2348030000001"


def tiny_dataset():
    return {
        "customers": [
            {"id": 1, "full_name": "Alice Test", "phone": PHONE, "created_at": "2026-01-01"},
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
    ds = SQLiteDataStore(c.settings.bank_api, c.env)
    ds.init_schema()
    ds.insert_seed_data(tiny_dataset())
    return c


def db(cfg):
    conn = sqlite3.connect(cfg.settings.bank_api.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def login(client, cfg):
    client.post("/auth/request-otp", json={"phone": PHONE})
    with open(cfg.settings.bank_api.otp_log_path) as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    code = lines[-1].split(", ")[1]
    r = client.post("/auth/verify", json={"phone": PHONE, "code": code})
    return r.json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


def last_ticket(cfg):
    conn = db(cfg)
    row = conn.execute("SELECT * FROM handoff_tickets ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return dict(row) if row else None


class TestHandoff:
    def test_valid_session_attaches_customer(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg)
            r = client.post("/handoff", headers=auth(token),
                            json={"summary": "Customer wants a human", "reason": "user_requested"})
            assert r.status_code == 200
            assert r.json()["ticket_id"]
            assert last_ticket(cfg)["customer_id"] == 1

    def test_without_session_still_succeeds(self, cfg):
        with TestClient(create_app()) as client:
            r = client.post("/handoff", json={"summary": "No session here", "reason": "upset_user"})
            assert r.status_code == 200
            assert last_ticket(cfg)["customer_id"] is None

    def test_garbage_token_still_succeeds(self, cfg):
        with TestClient(create_app()) as client:
            r = client.post("/handoff", headers={"Authorization": "Bearer garbage"},
                            json={"summary": "Bad token", "reason": "other"})
            assert r.status_code == 200
            assert last_ticket(cfg)["customer_id"] is None

    def test_customer_id_in_body_rejected(self, cfg):
        with TestClient(create_app()) as client:
            r = client.post("/handoff", json={"summary": "x", "reason": "other", "customer_id": 2})
            assert r.status_code == 422

    def test_empty_summary_rejected(self, cfg):
        with TestClient(create_app()) as client:
            assert client.post("/handoff", json={"summary": "", "reason": "other"}).status_code == 400
            r = client.post("/handoff", json={"summary": "    ", "reason": "other"})
            assert r.status_code == 400
            assert r.json()["error"] == "empty_summary"

    def test_over_long_summary_truncated(self, cfg):
        max_chars = cfg.settings.bank_api.handoff_summary_max_chars
        with TestClient(create_app()) as client:
            r = client.post("/handoff", json={"summary": "a" * (max_chars + 50), "reason": "other"})
            assert r.status_code == 200
            stored = last_ticket(cfg)
            assert len(stored["summary"]) == max_chars

    def test_unknown_reason_rejected(self, cfg):
        with TestClient(create_app()) as client:
            r = client.post("/handoff", json={"summary": "x", "reason": "not_a_code"})
            assert r.status_code == 400
            assert r.json()["error"] == "invalid_reason"

    def test_summary_redaction(self, cfg):
        summary = "OTP 123456 please, token Bearer abcdefghijklmnopqrstuvwxyz123456"
        with TestClient(create_app()) as client:
            r = client.post("/handoff", json={"summary": summary, "reason": "other"})
            assert r.status_code == 200
            stored = last_ticket(cfg)["summary"]
            assert "123456" not in stored
            assert "abcdefghijklmnopqrstuvwxyz123456" not in stored
            assert "[redacted]" in stored

    def test_audit_has_no_summary_text(self, cfg):
        secret_text = "please hand me over to a human now"
        with TestClient(create_app()) as client:
            client.post("/handoff", json={"summary": secret_text, "reason": "user_requested"})
            conn = db(cfg)
            rows = conn.execute("SELECT * FROM audit_log WHERE action = 'create_handoff'").fetchall()
            conn.close()
            assert len(rows) == 1
            params = rows[0]["params_json"]
            assert secret_text not in params
            assert "user_requested" in params
            assert "summary_length" in params


class TestSchemaMigration:
    def test_init_schema_on_old_db_without_reason(self, tmp_path):
        path = tmp_path / "old.db"
        conn = sqlite3.connect(path)
        conn.execute(
            "CREATE TABLE handoff_tickets ("
            "id INTEGER PRIMARY KEY AUTOINCREMENT, customer_id INTEGER, "
            "summary TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'open', "
            "created_at TEXT DEFAULT CURRENT_TIMESTAMP)"
        )
        conn.commit()
        conn.close()

        cfg = load_config()
        cfg.settings.bank_api.db_path = str(path)
        store = SQLiteDataStore(cfg.settings.bank_api, cfg.env)
        store.init_schema()  # should add the missing reason column

        conn = sqlite3.connect(path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(handoff_tickets)").fetchall()}
        conn.close()
        assert "reason" in cols

        ticket = store.create_handoff_ticket(None, "migrated", "other")
        assert ticket["reason"] == "other"
