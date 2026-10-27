#!/usr/bin/env bash
# Step 2 RAG checks: the three policy documents.
# Usage: bash scripts/check_rag_step2.sh
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
    "rag/docs/01_fee_schedule.md": ("Fee Schedule", "01"),
    "rag/docs/03_transfers_and_failed_transactions.md": ("Transfers and Failed Transactions", "03"),
    "rag/docs/04_disputes_and_complaints.md": ("Disputes and Complaints Procedure", "04"),
}

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


# --- 1. files exist ---
missing_files = [p for p in DOCS if not os.path.isfile(p)]
check("the 3 documents exist with exact names", not missing_files, "missing: " + ", ".join(missing_files))

texts = {}
for p in DOCS:
    if os.path.isfile(p):
        texts[p] = read(p)

# --- 2. title and metadata ---
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
    meta = re.match(
        r"^Document ID: RUB-DOC-(\d{2}) \| Version: 1\.0 \| Effective: 2026-10-01 \| Owner: Customer Experience$",
        lines[2].strip(),
    )
    if not meta:
        meta_problems.append(f"{p}: line 3 metadata mismatch")
    elif meta.group(1) != docnum:
        meta_problems.append(f"{p}: Document ID RUB-DOC-{meta.group(1)} != RUB-DOC-{docnum}")
check("titles and metadata lines are correct", not meta_problems, "; ".join(meta_problems))

# --- 3. sequential ## headings + last is Sources and currency ---
head_problems = []
sections_by_doc = {}
for p in DOCS:
    if p not in texts:
        continue
    secs = sections(texts[p])
    sections_by_doc[p] = secs
    nums = [int(re.match(r"^(\d+)\.", s["heading"]).group(1)) for s in secs]
    if nums != list(range(1, len(nums) + 1)):
        head_problems.append(f"{p}: headings {nums}")
    if not secs or "Sources and currency" not in secs[-1]["heading"]:
        head_problems.append(f"{p}: last heading not 'Sources and currency'")
check("## headings numbered 1..N, last is Sources and currency", not head_problems, "; ".join(head_problems))

# --- 4. section and file word counts ---
word_problems = []
for p in DOCS:
    if p not in texts:
        continue
    for s in sections_by_doc.get(p, []):
        n = len(s["body"].split())
        if not (40 <= n <= 400):
            word_problems.append(f"{p} :: {s['heading']} = {n} words")
    total = len(texts[p].split())
    if not (600 <= total <= 1600):
        word_problems.append(f"{p} total = {total} words")
check("each ## section 40-400 words; each file 600-1600 words", not word_problems, "; ".join(word_problems))

# --- 5. fee doc transfer fee strings ---
fee_doc = texts.get("rag/docs/01_fee_schedule.md", "")
transfer_sec = ""
for s in sections_by_doc.get("rag/docs/01_fee_schedule.md", []):
    if "Transfer fees" in s["heading"]:
        transfer_sec = s["body"]
needed_fee = ["₦10", "₦25", "₦50", "₦53.75", "7.5%"]
missing_fee = [t for t in needed_fee if t not in transfer_sec]
check("fee doc Transfer fees has ₦10/₦25/₦50/₦53.75 and 7.5%", not missing_fee, "missing: " + ", ".join(missing_fee))

# --- 6. every ₦ amount exists in facts ---
stray = {}
for p, text in texts.items():
    for m in re.finditer(r"₦\s*([0-9][0-9,]*(?:\.[0-9]+)?)", text):
        value = float(m.group(1).replace(",", ""))
        if value not in allowed_amounts:
            stray.setdefault(p, set()).add(m.group(0).strip())
stray_desc = "; ".join(f"{p}: {', '.join(sorted(v))}" for p, v in stray.items())
check("every ₦ amount exists in facts.yaml", not stray, "stray: " + stray_desc)

# --- 7. transfers doc timelines + DB statuses ---
transfers_doc = texts.get("rag/docs/03_transfers_and_failed_transactions.md", "")
status_sec = ""
for s in sections_by_doc.get("rag/docs/03_transfers_and_failed_transactions.md", []):
    if "Transfer statuses" in s["heading"]:
        status_sec = s["body"]
tl_ok = "24 hours" in transfers_doc and "5 working days" in transfers_doc
db_path = settings["bank_api"]["db_path"]
if not os.path.isfile(db_path):
    check("transfers doc timelines and DB statuses", False, "run the seed first")
else:
    conn = sqlite3.connect(db_path)
    statuses = [r[0] for r in conn.execute("SELECT DISTINCT status FROM transactions").fetchall()]
    conn.close()
    missing_status = [st for st in statuses if st.lower() not in status_sec.lower()]
    ok = tl_ok and not missing_status
    reason = ""
    if not tl_ok:
        reason = "missing '24 hours' or '5 working days'"
    if missing_status:
        reason = (reason + "; " if reason else "") + "missing statuses: " + ", ".join(missing_status)
    check("transfers doc timelines and DB statuses", ok, reason)

# --- 8. disputes doc required strings ---
disputes_doc = texts.get("rag/docs/04_disputes_and_complaints.md", "")
needed_disputes = [
    "complaints@rubiesmfb.example",
    "0700 000 0001",
    "customercare.head@rubiesmfb.example",
    "cpd@cbn.gov.ng",
    "24 hours",
    "5 working days",
    "30 days",
    "14 days",
]
missing_disp = [t for t in needed_disputes if t not in disputes_doc]
check("disputes doc has required contacts and timelines", not missing_disp, "missing: " + ", ".join(missing_disp))

# --- 9. disputes doc OTP/session values equal live config ---
otp_length = settings["bank_api"]["otp_length"]
otp_ttl = settings["bank_api"]["otp_ttl_seconds"]
otp_attempts = settings["bank_api"]["otp_max_attempts"]
session_expiry = settings["session"]["expiry_minutes"]
needed_otp = [
    f"{otp_length}-digit",
    f"{otp_ttl} seconds",
    f"{otp_attempts} attempts",
    f"{session_expiry} minutes",
]
missing_otp = [t for t in needed_otp if t not in disputes_doc]
check("disputes doc OTP/session values match config", not missing_otp, "missing: " + ", ".join(missing_otp))

# --- 10. last section sources; no PENDING; CBN URLs in 04 ---
src_problems = []
for p in DOCS:
    if p not in texts or not sections_by_doc.get(p):
        continue
    last = sections_by_doc[p][-1]["body"]
    if "2026-10-27" not in last:
        src_problems.append(f"{p}: last section missing date")
    if "may be out of date" not in last:
        src_problems.append(f"{p}: last section missing 'may be out of date'")
    if "PENDING_USER_CONFIRMATION" in texts[p]:
        src_problems.append(f"{p}: contains PENDING_USER_CONFIRMATION")
cbn_urls = [
    "https://www.cbn.gov.ng/FinInc/FinLit/How_Lodge_Complaints.pdf",
    "https://www.cbn.gov.ng/Out/2024/CCD/EXPOSURE%20DRAFT%20REVISED%20CONSUMER%20PROTECTION%20REGULATIONS%202.0.pdf",
]
last04 = sections_by_doc.get("rag/docs/04_disputes_and_complaints.md", [{}])[-1].get("body", "")
for url in cbn_urls:
    if url not in last04:
        src_problems.append(f"04: last section missing CBN URL {url[:40]}...")
check("sources sections correct; no PENDING; 04 cites CBN URLs", not src_problems, "; ".join(src_problems))

# --- 11. safety: no 11-digit numbers, email domains, customer names ---
safety_problems = []
conn = None
if os.path.isfile(db_path):
    conn = sqlite3.connect(db_path)
    names = [r[0] for r in conn.execute("SELECT full_name FROM customers").fetchall()]
    conn.close()
else:
    names = []
for p, text in texts.items():
    if re.search(r"\b\d{11}\b", text):
        safety_problems.append(f"{p}: 11-digit number")
    for m in re.finditer(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]*[A-Za-z0-9])", text):
        domain = m.group(1).lower()
        if not (domain.endswith(".example") or domain == "cbn.gov.ng"):
            safety_problems.append(f"{p}: email domain {domain}")
    for nm in names:
        if nm and nm in text:
            safety_problems.append(f"{p}: customer name '{nm}'")
check("no 11-digit numbers, bad email domains or customer names", not safety_problems, "; ".join(safety_problems))

# --- 12. no 'as above' / 'see above' ---
above_problems = [p for p, text in texts.items() if "as above" in text.lower() or "see above" in text.lower()]
check("no section uses 'as above' or 'see above'", not above_problems, ", ".join(above_problems))

# --- 13. step 1 still passes except the kyc tier line ---
step1 = subprocess.run(["bash", "scripts/check_rag_step1.sh"], capture_output=True, text=True)
step1_fails = [ln for ln in step1.stdout.splitlines() if ln.startswith("FAIL:")]
unexpected = [f for f in step1_fails if "kyc tier limits confirmed" not in f]
check("check_rag_step1 still passes (except kyc tier line)", not unexpected,
      "; ".join(unexpected) if unexpected else "step1 had unexpected failures")

# --- 14. protected dirs untouched ---
try:
    diff = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                          capture_output=True, text=True, check=True).stdout
except Exception as exc:
    check("no bank_api/providers/core/agent/config files modified", False, f"git failed: {exc}")
else:
    allow = os.environ.get("ALLOW_SEED_CHANGE") == "1"
    allow_rag = os.environ.get("ALLOW_RAG_CHANGE") == "1"
    protected = []
    for ln in diff.splitlines():
        if allow and (ln == "bank_api/seed.py" or ln.startswith("data/") or ln.startswith("tests/")):
            continue
        if allow_rag and (ln.startswith("core/") or ln.startswith("config/")):
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
