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


def _lowest_fitting_tier(balance_kobo, caps):
    for name, limits in sorted(caps.items(), key=lambda kv: RANK[kv[0]]):
        cap = limits.get("max_balance_naira")
        if cap == "no limit" or balance_kobo <= int(cap) * 100:
            return name
    return "tier3"


def test_tiers_follow_balance_caps():
    # The seed raises each account to the lowest tier whose max balance fits and
    # never lowers a tier. Balances (and so the set of raised customers) shift
    # with the run day, so assert the rule rather than a frozen snapshot.
    facts = _facts()
    caps = facts["fictional_bank"]["kyc_tiers"]
    baseline = facts["derived"]["kyc_tiers_by_customer"]["value"]
    for r in _real_rows():
        cid = r["customer_id"]
        floor = _lowest_fitting_tier(r["balance_kobo"], caps)
        assert RANK[r["kyc_tier"]] >= RANK[floor], (
            f"customer {cid}: tier {r['kyc_tier']} is below the lowest fitting tier {floor}"
        )
        # a tier is never lowered below the pre-fix baseline
        assert RANK[r["kyc_tier"]] >= RANK[baseline[cid]], f"customer {cid} tier was lowered"
