import pytest
import tempfile
import os

from providers.datastore.sqlite import SQLiteDataStore
from core.config import AppConfig, ConfigError, load_config


@pytest.fixture
def temp_db_path(monkeypatch, tmp_path):
    db_file = tmp_path / "test_bank.db"
    # Monkeypatch settings to use temp DB
    from core.config import load_config
    cfg = load_config()
    cfg.settings.bank_api.db_path = str(db_file)
    monkeypatch.setattr("core.startup.load_config", lambda config_dir="config": cfg)
    return str(db_file)


class TestDataStoreSchema:
    def test_schema_creates_cleanly(self, temp_db_path):
        from core.config import load_config
        cfg = load_config()
        cfg.settings.bank_api.db_path = temp_db_path
        store = SQLiteDataStore(cfg.settings.bank_api, None)
        store.init_schema()
        # Idempotent: call again without error
        store.init_schema()


class TestIsolation:
    def test_customer_a_cannot_read_customer_b(self, temp_db_path):
        from core.config import load_config
        cfg = load_config()
        cfg.settings.bank_api.db_path = temp_db_path
        store = SQLiteDataStore(cfg.settings.bank_api, None)
        store.init_schema()

        # Create two customers
        conn = store._connection()
        conn.execute(
            "INSERT INTO customers (full_name, phone) VALUES (?, ?)",
            ("Alice", "+2341111111111")
        )
        conn.execute(
            "INSERT INTO customers (full_name, phone) VALUES (?, ?)",
            ("Bob", "+2342222222222")
        )
        conn.commit()
        conn.close()

        # Fetch by reference that doesn't exist for Alice
        result = store.get_transaction_by_reference(1, "TXN-999")
        assert result is None


class TestOTPAndSession:
    def test_otp_round_trip(self, temp_db_path):
        from core.config import load_config
        cfg = load_config()
        cfg.settings.bank_api.db_path = temp_db_path
        store = SQLiteDataStore(cfg.settings.bank_api, None)
        store.init_schema()

        otp = store.create_otp("+2343333333333", "hash123", "2099-01-01 00:00:00")
        assert otp["used"] == 0
        assert otp["attempts"] == 0

        store.increment_otp_attempts(otp["id"])
        latest = store.get_latest_otp("+2343333333333")
        assert latest["attempts"] == 1

        store.mark_otp_used(otp["id"])
        latest_after = store.get_latest_otp("+2343333333333")
        assert latest_after["used"] == 1

    def test_session_round_trip(self, temp_db_path):
        from core.config import load_config
        cfg = load_config()
        cfg.settings.bank_api.db_path = temp_db_path
        store = SQLiteDataStore(cfg.settings.bank_api, None)
        store.init_schema()

        conn = store._connection()
        conn.execute(
            "INSERT INTO customers (full_name, phone) VALUES (?, ?)",
            ("Charlie", "+2344444444444")
        )
        conn.commit()
        conn.close()

        session = store.create_session(1, "tokenhash123", "2099-01-01 00:00:00")
        fetched = store.get_session_by_token_hash("tokenhash123")
        assert fetched is not None
        assert fetched["customer_id"] == 1

        store.revoke_session("tokenhash123")
        revoked = store.get_session_by_token_hash("tokenhash123")
        assert revoked is None


class TestAuditAndHandoff:
    def test_audit_write(self, temp_db_path):
        from core.config import load_config
        cfg = load_config()
        cfg.settings.bank_api.db_path = temp_db_path
        store = SQLiteDataStore(cfg.settings.bank_api, None)
        store.init_schema()
        store.write_audit("sess_1", 1, "verify_customer", "{}", "success")

    def test_handoff_ticket(self, temp_db_path):
        from core.config import load_config
        cfg = load_config()
        cfg.settings.bank_api.db_path = temp_db_path
        store = SQLiteDataStore(cfg.settings.bank_api, None)
        store.init_schema()
        conn = store._connection()
        conn.execute("INSERT INTO customers (full_name, phone) VALUES (?, ?)", ("Alice", "+234111"))
        conn.commit()
        conn.close()
        ticket = store.create_handoff_ticket(1, "Angry customer wants manager")
        assert ticket["summary"] == "Angry customer wants manager"
        assert ticket["status"] == "open"
