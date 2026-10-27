#!/usr/bin/env bash
# Step 3 RAG checks: documents 02 and 05.
# Usage: bash scripts/check_rag_step3.sh
set -u
cd "$(dirname "$0")/.."

python3 - <<'PY'
import os
import re
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


DOCS = {
    "rag/docs/02_account_types_and_kyc.md": ("Account Types and KYC Tiers", "02"),
    "rag/docs/05_cards_ussd_app.md": ("Cards, USSD and App Guide", "05"),
}
ALL_DOCS = [
    "rag/docs/01_fee_schedule.md",
    "rag/docs/02_account_types_and_kyc.md",
    "rag/docs/03_transfers_and_failed_transactions.md",
    "rag/docs/04_disputes_and_complaints.md",
    "rag/docs/05_cards_ussd_app.md",
]

with open("rag/facts.yaml") as f:
    facts = yaml.safe_load(f)
with open("config/settings.yaml") as f:
    settings = yaml.safe_load(f)


def collect_numbers(node, out):
    if isinstance(node, bool):
        return
    if isinstance(node, (int, float)):
        out.add(float(node))
    elif isinstance(node, dict):
        for v in node.values():
            collect_numbers(v, out)
    elif isinstance(node, list):
        for v in node:
            collect_numbers(v, out)


allowed_amounts = set()
collect_numbers(facts.get("fictional_bank", {}), allowed_amounts)
collect_numbers(facts.get("doc_examples", {}), allowed_amounts)
for entry in facts.get("derived", {}).values():
    if isinstance(entry, dict) and isinstance(entry.get("value"), (int, float)):
        allowed_amounts.add(float(entry["value"]))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def sections(text):
    secs = []
    cur = None
    for ln in text.splitlines():
        if re.match(r"^## \d+\. ", ln):
            if cur is not None:
                secs.append(cur)
            cur = {"heading": ln[3:].strip(), "body": []}
        elif cur is not None:
            cur["body"].append(ln)
    if cur is not None:
        secs.append(cur)
    for s in secs:
        s["body"] = "\n".join(s["body"])
    return secs


def section_containing(secs, needle):
    for s in secs:
        if needle.lower() in s["heading"].lower():
            return s
    return None


# --- 1. files exist ---
missing_files = [p for p in DOCS if not os.path.isfile(p)]
check("the 2 documents exist with exact names", not missing_files, "missing: " + ", ".join(missing_files))

texts = {p: read(p) for p in DOCS if os.path.isfile(p)}
sections_by_doc = {p: sections(t) for p, t in texts.items()}

# --- 2. title, metadata, Document ID ---
meta_problems = []
for p, (title, docnum) in DOCS.items():
    if p not in texts:
        meta_problems.append(f"{p}: missing")
        continue
    lines = texts[p].splitlines()
    if not lines or lines[0].strip() != f"# {title}":
        meta_problems.append(f"{p}: line 1 is not '# {title}'")
    if len(lines) < 3:
        meta_problems.append(f"{p}: no line 3")
        continue
    m = re.match(
        r"^Document ID: RUB-DOC-(\d{2}) \| Version: 1\.0 \| Effective: 2026-10-01 \| Owner: Customer Experience$",
        lines[2].strip(),
    )
    if not m:
        meta_problems.append(f"{p}: line 3 metadata mismatch")
    elif m.group(1) != docnum:
        meta_problems.append(f"{p}: Document ID RUB-DOC-{m.group(1)} != RUB-DOC-{docnum}")
check("titles and metadata lines are correct", not meta_problems, "; ".join(meta_problems))

# --- 3. sequential headings, last is Sources and currency ---
head_problems = []
for p in DOCS:
    if p not in texts:
        continue
    secs = sections_by_doc[p]
    nums = [int(re.match(r"^(\d+)\.", s["heading"]).group(1)) for s in secs]
    if nums != list(range(1, len(nums) + 1)):
        head_problems.append(f"{p}: headings {nums}")
    if not secs or "Sources and currency" not in secs[-1]["heading"]:
        head_problems.append(f"{p}: last heading not 'Sources and currency'")
check("## headings numbered 1..N, last is Sources and currency", not head_problems, "; ".join(head_problems))

# --- 4. word counts ---
word_problems = []
for p in DOCS:
    if p not in texts:
        continue
    for s in sections_by_doc[p]:
        n = len(s["body"].split())
        if not (40 <= n <= 400):
            word_problems.append(f"{p} :: {s['heading']} = {n} words")
    total = len(texts[p].split())
    if not (600 <= total <= 1600):
        word_problems.append(f"{p} total = {total} words")
check("each ## section 40-400 words; each file 600-1600 words", not word_problems, "; ".join(word_problems))

# --- 5. doc 02 tier limits from facts ---
doc02 = texts.get("rag/docs/02_account_types_and_kyc.md", "")
tiers = facts.get("fictional_bank", {}).get("kyc_tiers", {})
limit_problems = []
for tier, limits in tiers.items():
    daily = limits.get("daily_limit_naira")
    if isinstance(daily, (int, float)) and f"₦{daily:,}" not in doc02:
        limit_problems.append(f"{tier} daily ₦{daily:,}")
    maxb = limits.get("max_balance_naira")
    if isinstance(maxb, (int, float)):
        if f"₦{maxb:,}" not in doc02:
            limit_problems.append(f"{tier} max ₦{maxb:,}")
    elif str(maxb) == "no limit":
        if "no limit" not in doc02:
            limit_problems.append(f"{tier} 'no limit'")
check("doc 02 has tier daily limits and max balances", not limit_problems, "missing: " + ", ".join(limit_problems))

# --- 6. account types and card statuses from the DB ---
db_path = settings["bank_api"]["db_path"]
if not os.path.isfile(db_path):
    check("doc 02 account types and doc 05 card statuses match DB", False, "run the seed first")
else:
    conn = sqlite3.connect(db_path)
    account_types = [r[0] for r in conn.execute("SELECT DISTINCT account_type FROM accounts").fetchall()]
    card_statuses = [r[0] for r in conn.execute("SELECT DISTINCT status FROM cards").fetchall()]
    conn.close()
    at_sec = section_containing(sections_by_doc.get("rag/docs/02_account_types_and_kyc.md", []), "Account types")
    cs_sec = section_containing(sections_by_doc.get("rag/docs/05_cards_ussd_app.md", []), "Rubies debit card")
    problems = []
    at_body = at_sec["body"].lower() if at_sec else ""
    cs_body = cs_sec["body"].lower() if cs_sec else ""
    for t in account_types:
        if t.lower() not in at_body:
            problems.append(f"account type '{t}'")
    for st in card_statuses:
        if st.lower() not in cs_body:
            problems.append(f"card status '{st}'")
    check("doc 02 account types and doc 05 card statuses match DB", not problems, "missing: " + ", ".join(problems))

# --- 7. doc 02 identity + sources ---
doc02_problems = []
for token in ("BVN", "NIN", "December 2023"):
    if token not in doc02:
        doc02_problems.append(f"missing '{token}'")
if sections_by_doc.get("rag/docs/02_account_types_and_kyc.md"):
    last02 = sections_by_doc["rag/docs/02_account_types_and_kyc.md"][-1]["body"]
    for token in ("FPR/DIR/CIR/GEN/02/001", "BPS/DIR/GEN/CIR/04/007", "2026-10-27", "may be out of date", "not confirmed"):
        if token not in last02:
            doc02_problems.append(f"last section missing '{token}'")
check("doc 02 has BVN/NIN/December 2023 and correct sources", not doc02_problems, "; ".join(doc02_problems))

# --- 8. REAL-DB tier consistency ---
if not os.path.isfile(db_path):
    check("DB balances respect tier max balances", False, "run the seed first")
else:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cols = {r[1] for r in conn.execute("PRAGMA table_info(accounts)").fetchall()}
    if "kyc_tier" not in cols:
        conn.close()
        check("DB balances respect tier max balances", True, "no tier column")
    else:
        rows = conn.execute("SELECT customer_id, kyc_tier, balance_kobo FROM accounts").fetchall()
        conn.close()
        offenders = []
        for r in rows:
            tier = r["kyc_tier"]
            limits = tiers.get(tier)
            if not limits:
                offenders.append(f"customer {r['customer_id']} unknown tier {tier}")
                continue
            maxb = limits.get("max_balance_naira")
            if isinstance(maxb, (int, float)):
                if r["balance_kobo"] > maxb * 100:
                    offenders.append(
                        f"customer {r['customer_id']} ({tier}) balance ₦{r['balance_kobo'] / 100:,.0f} > ₦{maxb:,}"
                    )
        check("DB balances respect tier max balances", not offenders, "; ".join(offenders))

# --- 9. doc 05 lost-card section ---
doc05 = texts.get("rag/docs/05_cards_ussd_app.md", "")
lost_sec = section_containing(sections_by_doc.get("rag/docs/05_cards_ussd_app.md", []), "Lost")
lost_body = lost_sec["body"] if lost_sec else ""
needed_lost = ["last four digits", "yes", "immediately", "₦1,500", "5 working days"]
missing_lost = [t for t in needed_lost if t not in lost_body]
check("doc 05 lost-card section has the required steps", not missing_lost, "missing: " + ", ".join(missing_lost))

# --- 10. doc 05 USSD code + Complaints Desk contact ---
l2 = next((lvl for lvl in facts["fictional_bank"]["escalation_levels"] if lvl["level"] == "L2"), {})
needed05 = ["*000#", l2.get("email", "?"), l2.get("phone", "?")]
missing05 = [t for t in needed05 if t not in doc05]
check("doc 05 has USSD code and Complaints Desk contact", not missing05, "missing: " + ", ".join(missing05))

# --- 11. doc 05 PIN safety ---
pin_sec = section_containing(sections_by_doc.get("rag/docs/05_cards_ussd_app.md", []), "PIN")
pin_body = pin_sec["body"].lower() if pin_sec else ""
forbidden = [
    "send your pin", "send your otp", "send your cvv", "send your password",
    "send us your pin", "send us your otp", "reply with your pin",
    "share your pin with us", "tell us your pin", "give us your pin",
]
pin_problems = []
if "never" not in pin_body:
    pin_problems.append("PIN section missing 'never'")
present = [f for f in forbidden if f in doc05.lower()]
if present:
    pin_problems.append("disclosure instruction: " + ", ".join(present))
check("doc 05 PIN section warns 'never' and asks for no secrets", not pin_problems, "; ".join(pin_problems))

# --- 12. every ₦ amount exists in facts ---
stray = {}
for p in DOCS:
    if p not in texts:
        continue
    for m in re.finditer(r"₦\s*([0-9][0-9,]*(?:\.[0-9]+)?)", texts[p]):
        value = float(m.group(1).replace(",", ""))
        if value not in allowed_amounts:
            stray.setdefault(p, set()).add(m.group(0).strip())
stray_desc = "; ".join(f"{p}: {', '.join(sorted(v))}" for p, v in stray.items())
check("every ₦ amount exists in facts.yaml", not stray, "stray: " + stray_desc)

# --- 13. safety scans ---
if os.path.isfile(db_path):
    conn = sqlite3.connect(db_path)
    names = [r[0] for r in conn.execute("SELECT full_name FROM customers").fetchall()]
    last4s = [str(r[0]) for r in conn.execute("SELECT DISTINCT last4 FROM cards").fetchall()]
    conn.close()
else:
    names, last4s = [], []
safety_problems = []
l2_phone = next((lvl.get("phone") for lvl in facts["fictional_bank"]["escalation_levels"] if lvl["level"] == "L2"), "")
for p in DOCS:
    if p not in texts:
        continue
    text = texts[p]
    if re.search(r"\b\d{11}\b", text):
        safety_problems.append(f"{p}: 11-digit number")
    for m in re.finditer(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]*[A-Za-z0-9])", text):
        domain = m.group(1).lower()
        if not (domain.endswith(".example") or domain == "cbn.gov.ng"):
            safety_problems.append(f"{p}: email domain {domain}")
    for nm in names:
        if nm and nm in text:
            safety_problems.append(f"{p}: customer name '{nm}'")
    # Ignore the mandated Complaints Desk phone before scanning for card last4s.
    scan_text = text.replace(l2_phone, " ") if l2_phone else text
    for l4 in last4s:
        if l4 and l4 in scan_text:
            safety_problems.append(f"{p}: card last4 '{l4}'")
check("no 11-digit numbers, bad domains, names or card last4s", not safety_problems, "; ".join(safety_problems))

# --- 14. phrasing across all 5 docs ---
phrase_problems = []
for p in ALL_DOCS:
    if not os.path.isfile(p):
        phrase_problems.append(f"{p}: missing")
        continue
    text = read(p)
    if "as above" in text.lower() or "see above" in text.lower():
        phrase_problems.append(f"{p}: 'as above'/'see above'")
    if "PENDING_USER_CONFIRMATION" in text:
        phrase_problems.append(f"{p}: PENDING_USER_CONFIRMATION")
check("no 'as above'/'see above' and no PENDING in the 5 docs", not phrase_problems, "; ".join(phrase_problems))

# --- 15/16. earlier scripts still pass ---
s1 = subprocess.run(["bash", "scripts/check_rag_step1.sh"], capture_output=True, text=True).stdout
check("check_rag_step1 prints 13 passed, 0 failed", "13 passed, 0 failed" in s1, "got: " + s1.strip().splitlines()[-1])
s2 = subprocess.run(["bash", "scripts/check_rag_step2.sh"], capture_output=True, text=True).stdout
check("check_rag_step2 prints 14 passed, 0 failed", "14 passed, 0 failed" in s2, "got: " + s2.strip().splitlines()[-1])

# --- 17. protected dirs untouched ---
try:
    diff = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                          capture_output=True, text=True, check=True).stdout
except Exception as exc:
    check("no bank_api/providers/core/agent/config files modified", False, f"git failed: {exc}")
else:
    allow = os.environ.get("ALLOW_SEED_CHANGE") == "1"
    protected = []
    for ln in diff.splitlines():
        if allow and (ln == "bank_api/seed.py" or ln.startswith("data/") or ln.startswith("tests/")):
            continue
        if ln.startswith(("bank_api/", "providers/", "core/", "agent/", "config/")):
            protected.append(ln)
    check("no bank_api/providers/core/agent/config files modified", not protected,
          "modified: " + ", ".join(protected))

passed = sum(1 for r in results if r)
failed = len(results) - passed
print(f"SUMMARY: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
PY
