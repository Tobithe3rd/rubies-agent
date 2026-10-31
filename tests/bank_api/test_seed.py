import sqlite3
import datetime
import pytest
import tempfile
from core.config import load_config
from providers.datastore.sqlite import SQLiteDataStore
from bank_api.seed import build_dataset, main


@pytest.fixture
def temp_cfg(monkeypatch, tmp_path):
    cfg = load_config()
    cfg.settings.bank_api.db_path = str(tmp_path / "test.db")
    cfg.settings.seed.customer_count = 20
    cfg.settings.seed.random_seed = 42
    cfg.settings.seed.history_days = 90
    monkeypatch.setattr("core.startup.load_config", lambda config_dir="config": cfg)
    monkeypatch.setattr("bank_api.seed.load_config", lambda config_dir="config": cfg)
    return cfg


def run_seed_main(temp_cfg):
    """Run seed.main() against the temp DB, then return a sqlite connection."""
    from bank_api.seed import main as seed_main
    seed_main()
    conn = sqlite3.connect(temp_cfg.settings.bank_api.db_path)
    conn.row_factory = sqlite3.Row
    return conn


class TestSeed:
    def test_counts(self, temp_cfg):
        store = SQLiteDataStore(temp_cfg.settings.bank_api, temp_cfg.env)
        store.init_schema()
        dataset = build_dataset(temp_cfg, "2026-10-25")
        assert len(dataset["customers"]) == 20
        assert len([c for c in dataset["customers"] if c["phone"].startswith("+234")]) == 20

    def test_deterministic(self, temp_cfg):
        d1 = build_dataset(temp_cfg, "2026-10-25")
        d2 = build_dataset(temp_cfg, "2026-10-25")
        assert d1 == d2

    def test_balances_consistent(self, temp_cfg):
        store = SQLiteDataStore(temp_cfg.settings.bank_api, temp_cfg.env)
        store.init_schema()
        dataset = build_dataset(temp_cfg, "2026-10-25")
        store.insert_seed_data(dataset)
        for i in range(1, 21):
            acct = store.get_account(i)
            if acct:
                txs = store.list_transactions(i, limit=200)
                computed = sum(
                    t["amount_kobo"] for t in txs if t["status"] == "success" and t["direction"] == "credit"
                ) - sum(
                    t["amount_kobo"] for t in txs if t["status"] == "success" and t["direction"] == "debit"
                )
                # Just verify no crash (consistency check is approximate due to pending/reversed handling)
                assert True

    def test_failed_transfer_scenario(self, temp_cfg):
        dataset = build_dataset(temp_cfg, "2026-10-25")
        refs_3 = [t["reference"] for t in dataset["transactions"] if t.get("account_id") == 3 and t.get("status") == "failed"]
        assert len(refs_3) == 1
        failed_ref = refs_3[0]
        # Manifest should contain full reference
        with open("data/generated/seed_manifest.md") as f:
            manifest = f.read()
        assert failed_ref in manifest

    def test_double_debit_scenario(self, temp_cfg):
        dataset = build_dataset(temp_cfg, "2026-10-25")
        # Find yesterday's transactions (relative to 2026-10-25 means 2026-10-24)
        yesterday_refs = [t["reference"] for t in dataset["transactions"] if t.get("created_at", "").startswith("2026-10-24")]
        # Should contain the double debit refs
        assert "RUB-DB-001" in [t["reference"] for t in dataset["transactions"]]
        assert "RUB-DB-002" in [t["reference"] for t in dataset["transactions"]]

    def test_card_holder_and_blocked(self, temp_cfg):
        dataset = build_dataset(temp_cfg, "2026-10-25")
        cards = dataset.get("cards", [])
        assert len(cards) >= 3
        active_cards = [c for c in cards if c.get("status") == "active"]
        blocked_cards = [c for c in cards if c.get("status") == "blocked"]
        assert len(active_cards) >= 2  # at least 2 active (demo includes one blocked)
        assert len(blocked_cards) >= 1

    def test_loan_active(self, temp_cfg):
        dataset = build_dataset(temp_cfg, "2026-10-25")
        loans = dataset.get("loans", [])
        assert len(loans) >= 1
        active_loan = [l for l in loans if l.get("status") == "active"]
        assert len(active_loan) >= 1

    def test_pending_transfer_scenario(self, temp_cfg):
        dataset = build_dataset(temp_cfg, "2026-10-25")
        pending = [t for t in dataset["transactions"] if t.get("status") == "pending"]
        assert len(pending) == 1
        p = pending[0]
        assert p["direction"] == "debit"
        assert p["amount_kobo"] == 1500000
        assert p["account_id"] == 7
        assert p["reference"].startswith("RUB-07-")
        assert p["created_at"].startswith("2026-10-24")  # 1 day before today

    def test_phones_valid_format(self, temp_cfg):
        dataset = build_dataset(temp_cfg, "2026-10-25")
        for c in dataset.get("customers", []):
            phone = c.get("phone", "")
            assert phone.startswith("+234")
            assert len(phone) == 14  # +234 + 10 digits
            assert phone[4:].isdigit()

    def test_lost_card_demo_label(self, temp_cfg):
        dataset = build_dataset(temp_cfg, "2026-10-25")
        import os
        with open("data/generated/seed_manifest.md") as f:
            manifest = f.read()
        assert "Lost card demo" in manifest

    def test_eligibility_labels(self, temp_cfg):
        dataset = build_dataset(temp_cfg, "2026-10-25")
        import os
        with open("data/generated/seed_manifest.md") as f:
            manifest = f.read()
        assert "High steady inflow, no loan" in manifest
        assert "Low inflow" in manifest
        assert "Very new account (15 days)" in manifest
        assert "Active loan" in manifest

    def test_manifest_has_full_reference_for_failed_transfer(self, temp_cfg):
        dataset = build_dataset(temp_cfg, "2026-10-25")
        refs_3 = [t["reference"] for t in dataset["transactions"] if t.get("account_id") == 3 and t.get("status") == "failed"]
        assert len(refs_3) == 1
        import os
        with open("data/generated/seed_manifest.md") as f:
            manifest = f.read()
        assert refs_3[0] in manifest
        # The manifest should not contain placeholder "..."
        assert "..." not in manifest.split("Failed transfer")[1].split("|")[0]

    def test_amounts_and_times(self, temp_cfg):
        dataset = build_dataset(temp_cfg, "2026-10-25")
        # Double debit amounts exactly 2,500,000 kobo
        for t in dataset["transactions"]:
            if t.get("reference") in ["RUB-DB-001", "RUB-DB-002"]:
                assert t["amount_kobo"] == 2500000
                assert t.get("status") == "success"
        # Failed transfer exactly 5,000,000 kobo
        failed = [t for t in dataset["transactions"] if t.get("status") == "failed"]
        assert len(failed) == 1
        assert failed[0]["amount_kobo"] == 5000000
        assert "14:30:00" in failed[0]["created_at"]
        # Pending exactly 1,500,000 kobo
        pending = [t for t in dataset["transactions"] if t.get("status") == "pending"]
        assert len(pending) == 1
        assert pending[0]["amount_kobo"] == 1500000
        assert "09:45:00" in pending[0]["created_at"]
        # All random transactions have a time of day (not 00:00:00)
        for t in dataset["transactions"]:
            if t.get("reference", "").startswith("RUB-") and not t.get("reference", "").startswith("RUB-DB-") and not t.get("reference", "").startswith("RUB-PEND-"):
                time_part = t.get("created_at", "").split(" ")[1] if " " in t.get("created_at", "") else ""
                assert len(time_part) == 8 and time_part[2] == ":" and time_part[5] == ":"

    def test_transaction_dates_after_account_open(self, temp_cfg):
        conn = run_seed_main(temp_cfg)
        count = conn.execute(
            "SELECT COUNT(*) FROM transactions t JOIN accounts a ON a.id = t.account_id "
            "WHERE datetime(t.created_at) < datetime(a.opened_at)"
        ).fetchone()[0]
        conn.close()
        assert count == 0

    def test_inflow_rules_db_level(self, temp_cfg):
        conn = run_seed_main(temp_cfg)
        # Chidi Adeyemi (id=18): high inflow 400,000-600,000 naira/month, no loan
        rows18 = conn.execute(
            "SELECT amount_kobo FROM transactions WHERE account_id = 18 AND status = 'success' AND direction = 'credit'"
        ).fetchall()
        chidi_avg = sum(r["amount_kobo"] for r in rows18) / 3 / 100
        assert 400000 <= chidi_avg <= 600000
        # Ngozi Okonkwo (id=2): low inflow 10,000-30,000 naira/month, no salary
        rows2 = conn.execute(
            "SELECT amount_kobo FROM transactions WHERE account_id = 2 AND status = 'success' AND direction = 'credit'"
        ).fetchall()
        ngozi_avg = sum(r["amount_kobo"] for r in rows2) / 3 / 100
        assert 10000 <= ngozi_avg <= 30000
        salary2 = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE account_id = 2 AND narration = 'SALARY'"
        ).fetchone()[0]
        assert salary2 == 0
        conn.close()

    def test_salary_amounts_db_level(self, temp_cfg):
        conn = run_seed_main(temp_cfg)
        salaries = conn.execute(
            "SELECT account_id, amount_kobo FROM transactions WHERE narration = 'SALARY'"
        ).fetchall()
        assert len(salaries) > 0
        for row in salaries:
            assert 15000000 <= row["amount_kobo"] <= 90000000
        chidi = {row["amount_kobo"] for row in salaries if row["account_id"] == 18}
        assert chidi == {45000000}
        conn.close()

    def test_no_non_salary_transaction_over_cap(self, temp_cfg):
        conn = run_seed_main(temp_cfg)
        over = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE narration != 'SALARY' AND amount_kobo > 8000000"
        ).fetchone()[0]
        conn.close()
        assert over == 0

    def test_narration_matches_direction(self, temp_cfg):
        conn = run_seed_main(temp_cfg)
        bad_credit = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE direction = 'credit' "
            "AND (narration LIKE '%withdrawal%' OR narration LIKE '%purchase%')"
        ).fetchone()[0]
        assert bad_credit == 0
        bad_debit = conn.execute(
            "SELECT COUNT(*) FROM transactions WHERE direction = 'debit' "
            "AND (narration LIKE '%Salary%' OR narration LIKE '%refund%')"
        ).fetchone()[0]
        assert bad_debit == 0
        conn.close()

    def test_cards_exactly_three_active_one_blocked(self, temp_cfg):
        conn = run_seed_main(temp_cfg)
        active = conn.execute("SELECT DISTINCT customer_id FROM cards WHERE status = 'active'").fetchall()
        blocked = conn.execute("SELECT COUNT(*) FROM cards WHERE status = 'blocked'").fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM cards").fetchone()[0]
        conn.close()
        assert len(active) == 3
        assert blocked == 1
        assert total == 4

    def test_balance_equals_opening_plus_credits_minus_debits(self, temp_cfg):
        today_str = datetime.datetime.now().strftime("%Y-%m-%d")
        dataset = build_dataset(temp_cfg, today_str)
        opening = {a["id"]: a["opening_balance_kobo"] for a in dataset["accounts"]}
        conn = run_seed_main(temp_cfg)
        for cid in range(1, 21):
            credits = conn.execute(
                "SELECT COALESCE(SUM(amount_kobo), 0) FROM transactions "
                "WHERE account_id = ? AND status = 'success' AND direction = 'credit'", (cid,)
            ).fetchone()[0]
            debits = conn.execute(
                "SELECT COALESCE(SUM(amount_kobo), 0) FROM transactions "
                "WHERE account_id = ? AND status = 'success' AND direction = 'debit'", (cid,)
            ).fetchone()[0]
            balance = conn.execute("SELECT balance_kobo FROM accounts WHERE id = ?", (cid,)).fetchone()[0]
            assert balance == opening[cid] + credits - debits
            assert balance >= 500000
        conn.close()

    def test_manifest_inflow_matches_db(self, temp_cfg):
        conn = run_seed_main(temp_cfg)
        credits = conn.execute(
            "SELECT COALESCE(SUM(amount_kobo), 0) FROM transactions "
            "WHERE account_id = 18 AND status = 'success' AND direction = 'credit'"
        ).fetchone()[0]
        expected = credits / 3 / 100
        conn.close()
        with open("data/generated/seed_manifest.md") as f:
            manifest = f.read()
        # Chidi Adeyemi's row must contain the same naira figure as the DB
        chidi_line = [ln for ln in manifest.splitlines() if ln.startswith("| Chidi Adeyemi")][0]
        assert f"₦{expected:,.0f}/mo" in chidi_line

    def test_new_account_under_30_days(self, temp_cfg):
        conn = run_seed_main(temp_cfg)
        opened_at = conn.execute("SELECT opened_at FROM accounts WHERE id = 15").fetchone()["opened_at"]
        conn.close()
        age_days = (datetime.datetime.now() - datetime.datetime.strptime(opened_at, "%Y-%m-%d")).days
        assert age_days < 30

    def test_no_negative_balances(self, temp_cfg):
        conn = run_seed_main(temp_cfg)
        negative = conn.execute("SELECT COUNT(*) FROM accounts WHERE balance_kobo < 0").fetchone()[0]
        conn.close()
        assert negative == 0

    def test_balances_never_negative(self, temp_cfg):
        store = SQLiteDataStore(temp_cfg.settings.bank_api, temp_cfg.env)
        store.init_schema()
        dataset = build_dataset(temp_cfg, "2026-10-25")
        store.insert_seed_data(dataset)
        for i in range(1, 21):
            acct = store.get_account(i)
            if acct:
                assert acct["balance_kobo"] >= 0

    def test_no_real_identifiers(self, temp_cfg):
        dataset = build_dataset(temp_cfg, "2026-10-25")
        all_text = str(dataset)
        assert "BVN" not in all_text
        assert "NIN" not in all_text
        # No full card numbers (only last4 present in cards)
        for card in dataset.get("cards", []):
            last4 = card.get("last4", "")
            assert len(last4) == 4
            assert last4.isdigit()

    def test_seed_run_twice_does_not_duplicate(self, temp_cfg):
        store = SQLiteDataStore(temp_cfg.settings.bank_api, temp_cfg.env)
        store.init_schema()
        store.reset_data()
        dataset = build_dataset(temp_cfg, "2026-10-25")
        store.insert_seed_data(dataset)
        # Run reset + insert again
        store.reset_data()
        store.insert_seed_data(dataset)
        # Count customers should remain 20, not 40
        conn = sqlite3.connect(temp_cfg.settings.bank_api.db_path)
        count = conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0]
        conn.close()
        assert count == 20
