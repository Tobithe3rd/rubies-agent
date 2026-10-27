#!/usr/bin/env bash
# Step 1 RAG checks: facts single source of truth + sources register.
# Usage: bash scripts/check_rag_step1.sh
set -u
cd "$(dirname "$0")/.."

python3 - <<'PY'
import os
import sys
import subprocess
import sqlite3

try:
    import yaml
except Exception as exc:  # pragma: no cover
    print(f"FAIL: pyyaml importable - {exc}")
    print("SUMMARY: 0 passed, 1 failed")
    sys.exit(1)

results = []


def check(name, ok, reason=""):
    if ok:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} - {reason}")
    results.append(bool(ok))


# --- 1. facts.yaml exists and parses ---
facts = None
facts_path = "rag/facts.yaml"
if os.path.isfile(facts_path):
    try:
        with open(facts_path) as f:
            facts = yaml.safe_load(f)
        check("rag/facts.yaml parses as YAML", isinstance(facts, dict), "top level is not a mapping")
    except Exception as exc:
        check("rag/facts.yaml parses as YAML", False, str(exc))
else:
    check("rag/facts.yaml exists", False, "file missing")

if not isinstance(facts, dict):
    print("SUMMARY: 0 passed, 1 failed")
    sys.exit(1)

# --- 2. required sections present ---
required_sections = ["derived", "scenarios", "fictional_bank", "real_rules"]
missing = [s for s in required_sections if s not in facts]
check("required sections present", not missing, "missing: " + ", ".join(missing))

# --- 3. every config-sourced derived value equals the live config ---
with open("config/settings.yaml") as f:
    settings = yaml.safe_load(f)


def walk(node, path):
    cur = node
    for part in path:
        cur = cur[part]
    return cur


mismatch = []
for name, entry in facts.get("derived", {}).items():
    source = entry.get("source", "")
    if not source.startswith("config:"):
        continue
    path = source[len("config:"):].split(".")
    try:
        live = walk(settings, path)
    except Exception:
        mismatch.append(f"{name}: path '{source}' not found in settings.yaml")
        continue
    if live != entry.get("value"):
        mismatch.append(f"{name}: facts={entry.get('value')!r} config={live!r}")
check("derived values match config/settings.yaml", not mismatch, "; ".join(mismatch))

# --- 4. scenarios match the seeded DB ---
db_path = walk(settings, ["bank_api", "db_path"])
if not os.path.isfile(db_path):
    check("scenarios match the seeded DB", False, "run the seed first")
else:
    sc = facts.get("scenarios", {})
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    problems = []

    def tx(ref):
        return conn.execute("SELECT * FROM transactions WHERE reference = ?", (ref,)).fetchone()

    double_amount = sc.get("double_debit", {}).get("amount_naira", 0) * 100
    for ref in ("RUB-DB-001", "RUB-DB-002"):
        row = tx(ref)
        if row is None or row["amount_kobo"] != double_amount:
            problems.append(ref)

    failed = tx("RUB-03-000037")
    failed_amount = sc.get("failed_transfer", {}).get("amount_naira", 0) * 100
    if failed is None or failed["amount_kobo"] != failed_amount or failed["status"] != "failed":
        problems.append("RUB-03-000037")

    pending = tx("RUB-07-000026")
    pending_amount = sc.get("pending_transfer", {}).get("amount_naira", 0) * 100
    if pending is None or pending["amount_kobo"] != pending_amount or pending["status"] != "pending":
        problems.append("RUB-07-000026")

    for last4 in ("0001", "9999"):
        if conn.execute("SELECT 1 FROM cards WHERE last4 = ?", (last4,)).fetchone() is None:
            problems.append("card " + last4)
    conn.close()
    check("scenarios match the seeded DB", not problems, "bad: " + ", ".join(problems))

# --- 5. transfer fee bands and VAT ---
fees = facts.get("fictional_bank", {}).get("transfer_fees_nip", {})
fee_problems = []
if fees.get("up_to_5000_fee_naira") != 10:
    fee_problems.append("up_to_5000")
if fees.get("from_5001_to_50000_fee_naira") != 25:
    fee_problems.append("5001_to_50000")
if fees.get("above_50000_fee_naira") != 50:
    fee_problems.append("above_50000")
if fees.get("above_50000_fee_with_vat_naira") != 53.75:
    fee_problems.append("above_50000_with_vat")
check("transfer fee bands and VAT", not fee_problems, "wrong: " + ", ".join(fee_problems))

# --- 6. dispute timelines ---
timelines = facts.get("fictional_bank", {}).get("dispute_timelines", {})
expected_timelines = {
    "acknowledge_hours": 24,
    "failed_or_double_debit_working_days": 5,
    "auto_reversal_of_failed_transfer_hours": 24,
    "loan_or_fee_days": 30,
    "general_complaint_days": 14,
}
bad_tl = [k for k, v in expected_timelines.items() if timelines.get(k) != v]
check("dispute timelines", not bad_tl, "wrong: " + ", ".join(bad_tl))

# --- 7. escalation levels in order ---
levels = [item.get("level") for item in facts.get("fictional_bank", {}).get("escalation_levels", [])]
check("escalation levels L1,L2,L3,CBN in order", levels == ["L1", "L2", "L3", "CBN"], "got " + str(levels))

# --- 8. never_ask covers sensitive items ---
never_ask = facts.get("fictional_bank", {}).get("never_ask", [])
required_never = ["full PIN", "OTP", "card CVV", "full card number", "password", "BVN", "NIN"]
missing_never = [
    item for item in required_never
    if not any(item.lower() in str(entry).lower() for entry in never_ask)
]
check("never_ask covers sensitive items", not missing_never, "missing: " + ", ".join(missing_never))

# --- 9. sources.md URLs and dates ---
source_urls = [
    "https://www.cbn.gov.ng/FinInc/FinLit/How_Lodge_Complaints.pdf",
    "https://www.cbn.gov.ng/Out/2024/CCD/EXPOSURE%20DRAFT%20REVISED%20CONSUMER%20PROTECTION%20REGULATIONS%202.0.pdf",
    "https://youverify.co/blog/kyc-onboarding-nigeria-fintechs-cbn-guidelines",
]
if os.path.isfile("rag/sources.md"):
    with open("rag/sources.md") as f:
        sources_text = f.read()
    missing_urls = [u for u in source_urls if u not in sources_text]
    check("sources.md has the 3 URLs", not missing_urls, "missing: " + ", ".join(missing_urls))

    bad_dates = []
    for line in sources_text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 4:
            continue
        if cells[0] == "id" or set(cells[3]) <= set("-: "):
            continue  # header or separator row
        if cells[3] != "2026-10-27":
            bad_dates.append(cells[0])
    check("sources.md date_read is 2026-10-27", not bad_dates, "bad rows: " + ", ".join(bad_dates))
else:
    check("rag/sources.md exists", False, "file missing")

# --- 10. real_rules completeness ---
bad_rules = [
    r.get("id") for r in facts.get("real_rules", [])
    if not r.get("source_url") or not r.get("date_read")
]
check("every real_rule has source_url and date_read", not bad_rules, "missing: " + ", ".join(str(x) for x in bad_rules))

# --- 11. kyc tier limits confirmed ---
pending_limits = []
for tier, limits in facts.get("fictional_bank", {}).get("kyc_tiers", {}).items():
    for key, value in limits.items():
        if value == "PENDING_USER_CONFIRMATION":
            pending_limits.append(f"{tier}.{key}")
check("kyc tier limits confirmed", not pending_limits, "confirm tier limits from CBN source")

# --- 12. protected source dirs untouched ---
try:
    diff = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        capture_output=True, text=True, check=True,
    ).stdout
except Exception as exc:
    check("no bank_api/providers/core/agent files modified", False, f"git failed: {exc}")
else:
    allow = os.environ.get("ALLOW_SEED_CHANGE") == "1"
    allow_rag = os.environ.get("ALLOW_RAG_CHANGE") == "1"
    protected = []
    for ln in diff.splitlines():
        if allow and (ln == "bank_api/seed.py" or ln.startswith("data/") or ln.startswith("tests/")):
            continue
        if allow_rag and (ln.startswith("core/") or ln.startswith("config/")):
            continue
        if ln.startswith(("bank_api/", "providers/", "core/", "agent/")):
            protected.append(ln)
    check("no bank_api/providers/core/agent files modified", not protected,
          "modified: " + ", ".join(protected))

# --- summary ---
passed = sum(1 for r in results if r)
failed = len(results) - passed
print(f"SUMMARY: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
PY
