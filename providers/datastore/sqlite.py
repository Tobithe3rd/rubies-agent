from __future__ import annotations

import sqlite3
import json
import datetime
from typing import Optional, Any

from core.config import AppConfig, ConfigError
from core.interfaces import DataStore, HealthStatus
from core.factories import register


@register("datastore", "sqlite")
class SQLiteDataStore(DataStore):
    def __init__(self, cfg, env):
        self.db_path = cfg.db_path
        self.cfg = cfg

    def describe(self) -> str:
        return "sqlite"

    def healthcheck(self) -> HealthStatus:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.execute("SELECT 1")
            conn.close()
            return HealthStatus("sqlite", True, "connected")
        except Exception as exc:
            return HealthStatus("sqlite", False, str(exc))

    def connect(self) -> None:
        pass  # Per-call connections used

    def close(self) -> None:
        pass

    def _connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def init_schema(self) -> None:
        conn = self._connection()
        conn.execute("""
        CREATE TABLE IF NOT EXISTS customers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            full_name TEXT NOT NULL,
            phone TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.execute("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            account_number TEXT UNIQUE NOT NULL,
            account_type TEXT NOT NULL DEFAULT 'savings',
            kyc_tier TEXT NOT NULL DEFAULT 'tier1',
            balance_kobo INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active',
            opened_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_accounts_customer ON accounts(customer_id)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            reference TEXT UNIQUE NOT NULL,
            direction TEXT NOT NULL CHECK(direction IN ('debit', 'credit')),
            amount_kobo INTEGER NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('success', 'failed', 'pending', 'reversed')),
            channel TEXT,
            narration TEXT,
            counterparty_name TEXT,
            counterparty_bank TEXT,
            failure_reason TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_account ON transactions(account_id, created_at DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_reference ON transactions(reference)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            last4 TEXT NOT NULL,
            card_type TEXT NOT NULL DEFAULT 'debit',
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'blocked')),
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            blocked_at TEXT
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_cards_customer ON cards(customer_id)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            principal_kobo INTEGER NOT NULL DEFAULT 0,
            outstanding_kobo INTEGER NOT NULL DEFAULT 0,
            next_repayment_date TEXT,
            next_repayment_kobo INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active', 'completed', 'defaulted'))
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_loans_customer ON loans(customer_id)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS disputes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
            reason TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_disputes_customer ON disputes(customer_id)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            phone TEXT NOT NULL,
            code_hash TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            used INTEGER NOT NULL DEFAULT 0
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_otps_phone ON otps(phone)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            token_hash TEXT UNIQUE NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            revoked INTEGER NOT NULL DEFAULT 0
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT DEFAULT CURRENT_TIMESTAMP,
            session_ref TEXT,
            customer_id INTEGER,
            action TEXT NOT NULL,
            params_json TEXT,
            outcome TEXT NOT NULL
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_audit_customer ON audit_log(customer_id)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS handoff_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
            summary TEXT NOT NULL,
            reason TEXT NOT NULL DEFAULT 'other',
            status TEXT NOT NULL DEFAULT 'open',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """)
        # Migrate an older DB that lacks the reason column.
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(handoff_tickets)").fetchall()}
        if "reason" not in cols:
            conn.execute("ALTER TABLE handoff_tickets ADD COLUMN reason TEXT NOT NULL DEFAULT 'other'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_handoff_customer ON handoff_tickets(customer_id)")
        conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_hash TEXT UNIQUE NOT NULL,
            session_ref TEXT,
            customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
            action_type TEXT NOT NULL CHECK(action_type IN ('dispute', 'block_card')),
            payload_json TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            expires_at TEXT NOT NULL,
            used INTEGER NOT NULL DEFAULT 0
        )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_pending_customer ON pending_actions(customer_id)")
        conn.commit()
        conn.close()

    def get_customer_by_phone(self, phone: str) -> Optional[dict]:
        conn = self._connection()
        row = conn.execute("SELECT * FROM customers WHERE phone = ?", (phone,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_customer(self, customer_id: int) -> Optional[dict]:
        conn = self._connection()
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_account(self, customer_id: int) -> Optional[dict]:
        conn = self._connection()
        row = conn.execute("SELECT * FROM accounts WHERE customer_id = ?", (customer_id,)).fetchone()
        conn.close()
        return dict(row) if row else None

    def list_transactions(self, customer_id: int, limit: int = 10) -> list[dict]:
        conn = self._connection()
        account = conn.execute("SELECT id FROM accounts WHERE customer_id = ?", (customer_id,)).fetchone()
        if not account:
            conn.close()
            return []
        account_id = account["id"]
        rows = conn.execute(
            "SELECT * FROM transactions WHERE account_id = ? ORDER BY created_at DESC LIMIT ?",
            (account_id, limit)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]

    def get_transaction_by_reference(self, customer_id: int, reference: str) -> Optional[dict]:
        conn = self._connection()
        account = conn.execute("SELECT id FROM accounts WHERE customer_id = ?", (customer_id,)).fetchone()
        conn.close()
        if not account:
            return None
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM transactions WHERE reference = ? AND account_id = ?",
            (reference, account["id"])
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def create_dispute(self, customer_id: int, transaction_id: int, reason: str) -> dict:
        conn = self._connection()
        cursor = conn.execute(
            "INSERT INTO disputes (customer_id, transaction_id, reason) VALUES (?, ?, ?)",
            (customer_id, transaction_id, reason)
        )
        conn.commit()
        dispute_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM disputes WHERE id = ?", (dispute_id,)).fetchone()
        conn.close()
        return dict(row)

    def get_open_dispute_for_transaction(self, customer_id: int, transaction_id: int) -> Optional[dict]:
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM disputes WHERE customer_id = ? AND transaction_id = ? AND status = 'open'",
            (customer_id, transaction_id)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_card(self, customer_id: int, last4: str) -> Optional[dict]:
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM cards WHERE customer_id = ? AND last4 = ?", (customer_id, last4)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def block_card(self, customer_id: int, last4: str) -> dict:
        conn = self._connection()
        conn.execute(
            "UPDATE cards SET status = 'blocked', blocked_at = CURRENT_TIMESTAMP WHERE customer_id = ? AND last4 = ? AND status = 'active'",
            (customer_id, last4)
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM cards WHERE customer_id = ? AND last4 = ?", (customer_id, last4)
        ).fetchone()
        conn.close()
        return dict(row) if row else {}

    def get_active_loan(self, customer_id: int) -> Optional[dict]:
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM loans WHERE customer_id = ? AND status = 'active'", (customer_id,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def get_loan_inputs(self, customer_id: int) -> dict:
        account = self.get_account(customer_id)
        if not account:
            return {}
        transactions = self.list_transactions(customer_id, limit=1000)
        credits_kobo = sum(
            t["amount_kobo"] for t in transactions
            if t.get("direction") == "credit" and t.get("status") == "success"
        )
        try:
            opened = datetime.datetime.strptime(account["opened_at"], "%Y-%m-%d")
            age_days = (datetime.datetime.now() - opened).days
        except Exception:
            age_days = 0
        return {
            "account_age_days": age_days,
            "avg_monthly_inflow_kobo": credits_kobo // 3,
            "existing_loan": self.get_active_loan(customer_id) is not None,
            "kyc_tier": account.get("kyc_tier", "tier1"),
        }

    def create_otp(self, phone: str, code_hash: str, expires_at: str) -> dict:
        conn = self._connection()
        cursor = conn.execute(
            "INSERT INTO otps (phone, code_hash, expires_at, attempts, used) VALUES (?, ?, ?, 0, 0)",
            (phone, code_hash, expires_at)
        )
        conn.commit()
        otp_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM otps WHERE id = ?", (otp_id,)).fetchone()
        conn.close()
        return dict(row)

    def get_latest_otp(self, phone: str) -> Optional[dict]:
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM otps WHERE phone = ? ORDER BY id DESC LIMIT 1", (phone,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def increment_otp_attempts(self, otp_id: int) -> None:
        conn = self._connection()
        conn.execute(
            "UPDATE otps SET attempts = attempts + 1 WHERE id = ?", (otp_id,)
        )
        conn.commit()
        conn.close()

    def mark_otp_used(self, otp_id: int) -> None:
        conn = self._connection()
        conn.execute("UPDATE otps SET used = 1 WHERE id = ?", (otp_id,))
        conn.commit()
        conn.close()

    def create_session(self, customer_id: int, token_hash: str, expires_at: str) -> dict:
        conn = self._connection()
        cursor = conn.execute(
            "INSERT INTO sessions (customer_id, token_hash, expires_at, revoked) VALUES (?, ?, ?, 0)",
            (customer_id, token_hash, expires_at)
        )
        conn.commit()
        session_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM sessions WHERE id = ?", (session_id,)).fetchone()
        conn.close()
        return dict(row)

    def get_session_by_token_hash(self, token_hash: str) -> Optional[dict]:
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM sessions WHERE token_hash = ? AND revoked = 0", (token_hash,)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def revoke_session(self, token_hash: str) -> None:
        conn = self._connection()
        conn.execute("UPDATE sessions SET revoked = 1 WHERE token_hash = ?", (token_hash,))
        conn.commit()
        conn.close()

    def write_audit(self, session_ref: Optional[str], customer_id: Optional[int], action: str, params_json: str, outcome: str) -> None:
        conn = self._connection()
        conn.execute(
            "INSERT INTO audit_log (session_ref, customer_id, action, params_json, outcome) VALUES (?, ?, ?, ?, ?)",
            (session_ref, customer_id, action, params_json, outcome)
        )
        conn.commit()
        conn.close()

    def reset_data(self) -> None:
        conn = self._connection()
        tables = [
            "pending_actions", "handoff_tickets", "audit_log", "otps", "sessions",
            "disputes", "loans", "cards", "transactions", "accounts", "customers"
        ]
        for t in tables:
            conn.execute(f"DELETE FROM {t}")
        conn.commit()
        conn.close()

    def create_pending_action(self, customer_id: int, token_hash: str, session_ref: Optional[str],
                              action_type: str, payload_json: str, expires_at: str) -> dict:
        conn = self._connection()
        cursor = conn.execute(
            "INSERT INTO pending_actions (customer_id, token_hash, session_ref, action_type, payload_json, expires_at, used) "
            "VALUES (?, ?, ?, ?, ?, ?, 0)",
            (customer_id, token_hash, session_ref, action_type, payload_json, expires_at)
        )
        conn.commit()
        pending_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM pending_actions WHERE id = ?", (pending_id,)).fetchone()
        conn.close()
        return dict(row)

    def get_pending_action_by_token_hash(self, customer_id: int, token_hash: str) -> Optional[dict]:
        conn = self._connection()
        row = conn.execute(
            "SELECT * FROM pending_actions WHERE customer_id = ? AND token_hash = ?",
            (customer_id, token_hash)
        ).fetchone()
        conn.close()
        return dict(row) if row else None

    def mark_pending_action_used(self, customer_id: int, pending_action_id: int) -> None:
        conn = self._connection()
        conn.execute(
            "UPDATE pending_actions SET used = 1 WHERE id = ? AND customer_id = ?",
            (pending_action_id, customer_id)
        )
        conn.commit()
        conn.close()

    def insert_seed_data(self, dataset: dict) -> None:
        conn = self._connection()
        # Insert customers and accounts
        for cust in dataset.get("customers", []):
            conn.execute(
                "INSERT INTO customers (id, full_name, phone, created_at) VALUES (?, ?, ?, ?)",
                (cust.get("id"), cust.get("full_name"), cust.get("phone"), cust.get("created_at"))
            )
        conn.commit()
        for acct in dataset.get("accounts", []):
            conn.execute(
                "INSERT INTO accounts (id, customer_id, account_number, account_type, kyc_tier, balance_kobo, status, opened_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (acct.get("id"), acct.get("customer_id"), acct.get("account_number"), acct.get("account_type", "savings"),
                 acct.get("kyc_tier", "tier1"), acct.get("balance_kobo", 0), acct.get("status", "active"), acct.get("opened_at"))
            )
        conn.commit()
        for trans in dataset.get("transactions", []):
            conn.execute(
                "INSERT INTO transactions (id, account_id, reference, direction, amount_kobo, status, channel, narration, counterparty_name, counterparty_bank, failure_reason, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (trans.get("id"), trans.get("account_id"), trans.get("reference"), trans.get("direction"),
                 trans.get("amount_kobo"), trans.get("status", "pending"), trans.get("channel"),
                 trans.get("narration"), trans.get("counterparty_name"), trans.get("counterparty_bank"),
                 trans.get("failure_reason"), trans.get("created_at"))
            )
        conn.commit()
        for card in dataset.get("cards", []):
            conn.execute(
                "INSERT INTO cards (id, customer_id, last4, card_type, status, created_at, blocked_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (card.get("id"), card.get("customer_id"), card.get("last4"), card.get("card_type", "debit"),
                 card.get("status", "active"), card.get("created_at"), card.get("blocked_at"))
            )
        conn.commit()
        for loan in dataset.get("loans", []):
            conn.execute(
                "INSERT INTO loans (id, customer_id, principal_kobo, outstanding_kobo, next_repayment_date, next_repayment_kobo, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (loan.get("id"), loan.get("customer_id"), loan.get("principal_kobo", 0), loan.get("outstanding_kobo", 0),
                 loan.get("next_repayment_date"), loan.get("next_repayment_kobo", 0), loan.get("status", "active"))
            )
        conn.commit()
        for dispute in dataset.get("disputes", []):
            conn.execute(
                "INSERT INTO disputes (id, customer_id, transaction_id, reason, status, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (dispute.get("id"), dispute.get("customer_id"), dispute.get("transaction_id"), dispute.get("reason"),
                 dispute.get("status", "open"), dispute.get("created_at"))
            )
        conn.commit()
        conn.close()

    def create_handoff_ticket(self, customer_id_or_none: Optional[int], summary: str, reason: str = "other") -> dict:
        conn = self._connection()
        cursor = conn.execute(
            "INSERT INTO handoff_tickets (customer_id, summary, reason) VALUES (?, ?, ?)",
            (customer_id_or_none, summary, reason)
        )
        conn.commit()
        ticket_id = cursor.lastrowid
        row = conn.execute("SELECT * FROM handoff_tickets WHERE id = ?", (ticket_id,)).fetchone()
        conn.close()
        return dict(row)
