"""Real-DB checks for the seeded KYC tiers.

These read the REAL seeded SQLite file (data/bank.db) and rag/facts.yaml.
They skip when the real database has not been seeded.
"""
import os
import sqlite3

import pytest
import yaml

DB_PATH = "data/bank.db"
FACTS_PATH = "rag/facts.yaml"

# The customers whose tier the seed had to raise, and the tier they moved to.
EXPECTED_CHANGED = {
    3: "tier3", 6: "tier3", 8: "tier3", 16: "tier3", 19: "tier3",   # tier1 -> tier3
    4: "tier3", 9: "tier3", 14: "tier3", 20: "tier3",              # tier2 -> tier3
    5: "tier2", 12: "tier2", 13: "tier2",                          # tier1 -> tier2
}
RANK = {"tier1": 1, "tier2": 2, "tier3": 3}


def _real_rows():
    if not os.path.isfile(DB_PATH):
        pytest.skip("real seeded DB not present; run python -m bank_api.seed")
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT customer_id, kyc_tier, balance_kobo FROM accounts").fetchall()
    conn.close()
    return rows


def _facts():
    with open(FACTS_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


def test_no_balance_exceeds_tier_max():
    caps = _facts()["fictional_bank"]["kyc_tiers"]
    offenders = []
    for r in _real_rows():
        cap = caps[r["kyc_tier"]]["max_balance_naira"]
        if cap == "no limit":
            continue
        if r["balance_kobo"] > int(cap) * 100:
            offenders.append((r["customer_id"], r["kyc_tier"], r["balance_kobo"]))
    assert offenders == []


def test_changed_customers_match_expected():
    # facts.yaml still holds the pre-fix tiers; use it as the baseline.
    baseline = _facts()["derived"]["kyc_tiers_by_customer"]["value"]
    changed = {}
    for r in _real_rows():
        cid = r["customer_id"]
        if r["kyc_tier"] != baseline[cid]:
            changed[cid] = r["kyc_tier"]
        # a tier is never lowered
        assert RANK[r["kyc_tier"]] >= RANK[baseline[cid]], f"customer {cid} tier was lowered"
    assert changed == EXPECTED_CHANGED
