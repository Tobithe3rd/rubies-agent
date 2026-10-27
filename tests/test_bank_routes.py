import sqlite3
import datetime

import pytest
from fastapi.testclient import TestClient

from core.config import load_config
from providers.datastore.sqlite import SQLiteDataStore
from bank_api.seed import build_dataset
from bank_api.main import create_app


PHONES = {
    1: "+2348031234567",   # Adebayo Ogunleye (card 0001 active)
    2: "+2348052345678",   # Ngozi Okonkwo (low inflow)
    3: "+2348093456789",   # Fatima Ibrahim (failed transfer)
    4: "+2348074567890",   # Chidi Nwankwo (card 0004 active, 9999 blocked)
    5: "+2348115678901",   # Bola Adeyemi (double debit)
    10: "+2348210123456",  # Tunde Afolabi (active loan)
    15: "+2348315678901",  # Ngozi Afolabi (very new account)
    18: "+2348378901234",  # Chidi Adeyemi (high inflow)
}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    c = load_config()
    c.settings.bank_api.db_path = str(tmp_path / "bank.db")
    c.settings.bank_api.otp_log_path = str(tmp_path / "otp.log")
    monkeypatch.setattr("bank_api.main.load_config", lambda config_dir="config": c)
    today = datetime.datetime.now().strftime("%Y-%m-%d")
    ds = SQLiteDataStore(c.settings.bank_api, c.env)
    ds.init_schema()
    ds.insert_seed_data(build_dataset(c, today))
    return c


def db(cfg):
    conn = sqlite3.connect(cfg.settings.bank_api.db_path)
    conn.row_factory = sqlite3.Row
    return conn


def last_code(cfg):
    with open(cfg.settings.bank_api.otp_log_path) as f:
        lines = [ln for ln in f.read().splitlines() if ln.strip()]
    return lines[-1].split(", ")[1]


def login(client, cfg, customer_id):
    client.post("/auth/request-otp", json={"phone": PHONES[customer_id]})
    code = last_code(cfg)
    r = client.post("/auth/verify", json={"phone": PHONES[customer_id], "code": code})
    assert r.status_code == 200
    return r.json()["token"]


def auth(token):
    return {"Authorization": f"Bearer {token}"}


class TestReadRoutes:
    def test_balance_and_statement_and_txn(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg, 1)
            r = client.get("/account/balance", headers=auth(token))
            assert r.status_code == 200
            conn = db(cfg)
            expected = conn.execute("SELECT balance_kobo FROM accounts WHERE customer_id = 1").fetchone()[0]
            conn.close()
            assert r.json()["balance_kobo"] == expected

            r = client.get("/account/statement?n=5", headers=auth(token))
            assert r.status_code == 200
            assert len(r.json()["transactions"]) <= 5

    def test_transaction_status_own(self, cfg):
        conn = db(cfg)
        ref = conn.execute("SELECT reference FROM transactions WHERE account_id = 5 LIMIT 1").fetchone()[0]
        conn.close()
        with TestClient(create_app()) as client:
            token = login(client, cfg, 5)
            r = client.get(f"/transactions/{ref}", headers=auth(token))
            assert r.status_code == 200
            assert r.json()["reference"] == ref

    def test_routes_require_session(self, cfg):
        with TestClient(create_app()) as client:
            for method, path in [
                ("get", "/account/balance"),
                ("get", "/account/statement"),
                ("get", "/transactions/RUB-01-000001"),
                ("post", "/disputes/propose"),
                ("post", "/cards/block/propose"),
                ("post", "/actions/confirm"),
                ("post", "/loans/eligibility"),
                ("get", "/loans/status"),
            ]:
                if method == "get":
                    resp = client.get(path)
                else:
                    resp = client.post(path, json={})
                assert resp.status_code == 401, path

    def test_isolation_other_customer_reference(self, cfg):
        conn = db(cfg)
        failed_ref = conn.execute(
            "SELECT reference FROM transactions WHERE account_id = 3 AND status = 'failed'"
        ).fetchone()[0]
        conn.close()
        with TestClient(create_app()) as client:
            token = login(client, cfg, 2)  # Bob/Ngozi, not the owner
            other = client.get(f"/transactions/{failed_ref}", headers=auth(token))
            missing = client.get("/transactions/RUB-DOES-NOT-EXIST", headers=auth(token))
            assert other.status_code == 404
            assert missing.status_code == 404
            assert other.json() == missing.json() == {"error": "not_found"}

    def test_extra_customer_id_rejected_or_ignored(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg, 1)
            # query param ignored: still the caller's own balance
            r = client.get("/account/balance?customer_id=5", headers=auth(token))
            conn = db(cfg)
            expected = conn.execute("SELECT balance_kobo FROM accounts WHERE customer_id = 1").fetchone()[0]
            conn.close()
            assert r.json()["balance_kobo"] == expected
            # extra field in body rejected
            r = client.post("/loans/eligibility", headers=auth(token),
                            json={"requested_amount_naira": 100000, "customer_id": 5})
            assert r.status_code == 422


class TestDisputes:
    def test_propose_then_confirm(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg, 5)
            before = db(cfg).execute("SELECT COUNT(*) FROM disputes").fetchone()[0]
            r = client.post("/disputes/propose", headers=auth(token),
                            json={"reference": "RUB-DB-001", "reason": "double debit"})
            assert r.status_code == 200
            pending = r.json()["pending_token"]
            assert "pending_token" in r.json()
            after_propose = db(cfg).execute("SELECT COUNT(*) FROM disputes").fetchone()[0]
            assert after_propose == before  # nothing created yet

            r = client.post("/actions/confirm", headers=auth(token), json={"token": pending})
            assert r.status_code == 200
            assert r.json()["status"] == "dispute_opened"
            after_confirm = db(cfg).execute("SELECT COUNT(*) FROM disputes").fetchone()[0]
            assert after_confirm == before + 1

    def test_duplicate_dispute_refused(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg, 5)
            r = client.post("/disputes/propose", headers=auth(token),
                            json={"reference": "RUB-DB-002", "reason": "dup"})
            client.post("/actions/confirm", headers=auth(token), json={"token": r.json()["pending_token"]})
            again = client.post("/disputes/propose", headers=auth(token),
                                json={"reference": "RUB-DB-002", "reason": "dup"})
            assert again.status_code == 409
            assert again.json()["error"] == "duplicate_dispute"

    def test_both_double_debit_refs_lookup(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg, 5)
            for ref in ("RUB-DB-001", "RUB-DB-002"):
                r = client.get(f"/transactions/{ref}", headers=auth(token))
                assert r.status_code == 200
                assert r.json()["reference"] == ref


class TestConfirmGuards:
    def test_single_use(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg, 5)
            r = client.post("/disputes/propose", headers=auth(token),
                            json={"reference": "RUB-DB-001", "reason": "x"})
            pending = r.json()["pending_token"]
            assert client.post("/actions/confirm", headers=auth(token), json={"token": pending}).status_code == 200
            second = client.post("/actions/confirm", headers=auth(token), json={"token": pending})
            assert second.status_code == 400
            assert second.json()["error"] == "invalid_or_expired"

    def test_forged_token(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg, 5)
            r = client.post("/actions/confirm", headers=auth(token), json={"token": "forged-token"})
            assert r.status_code == 400
            assert r.json()["error"] == "invalid_or_expired"

    def test_wrong_customer_cannot_confirm(self, cfg):
        with TestClient(create_app()) as client:
            owner = login(client, cfg, 5)
            r = client.post("/disputes/propose", headers=auth(owner),
                            json={"reference": "RUB-DB-001", "reason": "x"})
            pending = r.json()["pending_token"]
            other = login(client, cfg, 2)
            resp = client.post("/actions/confirm", headers=auth(other), json={"token": pending})
            assert resp.status_code == 400
            assert resp.json()["error"] == "invalid_or_expired"

    def test_expired_token(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg, 5)
            r = client.post("/disputes/propose", headers=auth(token),
                            json={"reference": "RUB-DB-001", "reason": "x"})
            pending = r.json()["pending_token"]
            conn = db(cfg)
            conn.execute("UPDATE pending_actions SET expires_at = '2000-01-01 00:00:00'")
            conn.commit()
            conn.close()
            resp = client.post("/actions/confirm", headers=auth(token), json={"token": pending})
            assert resp.status_code == 400
            assert resp.json()["error"] == "invalid_or_expired"


class TestBlockCard:
    def test_propose_then_confirm(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg, 1)
            r = client.post("/cards/block/propose", headers=auth(token), json={"last4": "0001"})
            assert r.status_code == 200
            pending = r.json()["pending_token"]
            conn = db(cfg)
            status = conn.execute("SELECT status FROM cards WHERE customer_id = 1 AND last4 = '0001'").fetchone()[0]
            conn.close()
            assert status == "active"  # unchanged until confirm

            r = client.post("/actions/confirm", headers=auth(token), json={"token": pending})
            assert r.status_code == 200
            assert r.json()["status"] == "card_blocked"
            conn = db(cfg)
            status = conn.execute("SELECT status FROM cards WHERE customer_id = 1 AND last4 = '0001'").fetchone()[0]
            conn.close()
            assert status == "blocked"

    def test_already_blocked(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg, 4)
            r = client.post("/cards/block/propose", headers=auth(token), json={"last4": "9999"})
            assert r.status_code == 200
            assert r.json()["status"] == "already_blocked"


class TestLoans:
    def test_eligibility_outcomes(self, cfg):
        with TestClient(create_app()) as client:
            def decision(cid):
                token = login(client, cfg, cid)
                r = client.post("/loans/eligibility", headers=auth(token),
                                json={"requested_amount_naira": 200000})
                assert r.status_code == 200
                return r.json()["decision"]

            assert decision(18) == "eligible"        # high steady inflow, no loan
            assert decision(2) == "not_eligible"     # low inflow
            assert decision(15) == "not_eligible"    # very new account
            assert decision(10) == "not_eligible"    # active loan

    def test_loan_status(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg, 10)
            r = client.get("/loans/status", headers=auth(token))
            assert r.status_code == 200
            assert r.json()["status"] == "active"
            assert r.json()["outstanding_kobo"] > 0

            token2 = login(client, cfg, 1)
            r2 = client.get("/loans/status", headers=auth(token2))
            assert r2.json()["status"] == "no_active_loan"


class TestAudit:
    def test_audit_rows_have_no_token(self, cfg):
        with TestClient(create_app()) as client:
            token = login(client, cfg, 5)
            client.get("/account/balance", headers=auth(token))
            client.get("/loans/status", headers=auth(token))
            r = client.post("/disputes/propose", headers=auth(token),
                            json={"reference": "RUB-DB-001", "reason": "audit"})
            pending = r.json()["pending_token"]
            client.post("/actions/confirm", headers=auth(token), json={"token": pending})

            conn = db(cfg)
            rows = conn.execute("SELECT * FROM audit_log").fetchall()
            conn.close()
            actions = {row["action"] for row in rows}
            assert "get_balance" in actions
            assert "get_loan_status" in actions
            assert "propose_dispute" in actions
            assert "confirm_action" in actions
            blob = " ".join(str(dict(row)) for row in rows)
            assert pending not in blob
            assert token not in blob
