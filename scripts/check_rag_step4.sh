#!/usr/bin/env bash
# Step 4 RAG checks: documents 06, 07, 08 and the whole corpus.
# Usage: bash scripts/check_rag_step4.sh
set -u
cd "$(dirname "$0")/.."

python3 - <<'PY'
import os
import re
import sys
import glob
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
    "rag/docs/06_loans.md": ("Loan Products and Requirements", "06"),
    "rag/docs/07_fraud_and_security.md": ("Fraud and Security", "07"),
    "rag/docs/08_general_faq.md": ("General FAQ", "08"),
}

with open("rag/facts.yaml") as f:
    facts = yaml.safe_load(f)
with open("config/settings.yaml") as f:
    settings = yaml.safe_load(f)
db_path = settings["bank_api"]["db_path"]


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


def norm(s):
    return s.replace(" ", "").lower()


def eligibility_tokens(elig):
    tokens = []
    for key, value in elig.items():
        if "naira" in key and isinstance(value, (int, float)):
            tokens.append((key, f"₦{value:,}"))
        elif isinstance(value, list):
            for item in value:
                tokens.append((key, item))
        else:
            tokens.append((key, str(value)))
    return tokens


# --- 1. files exist ---
missing_files = [p for p in DOCS if not os.path.isfile(p)]
check("the 3 documents exist with exact names", not missing_files, "missing: " + ", ".join(missing_files))

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

# --- 5. doc 06 eligibility section covers every eligibility value ---
doc06 = texts.get("rag/docs/06_loans.md", "")
elig = settings["bank_api"]["eligibility"]
elig_sec = section_containing(sections_by_doc.get("rag/docs/06_loans.md", []), "Eligibility")
elig_body = elig_sec["body"] if elig_sec else ""
missing_elig = [f"{k} -> {t}" for k, t in eligibility_tokens(elig) if norm(t) not in norm(elig_body)]
check("doc 06 eligibility section covers every eligibility value", not missing_elig,
      "missing: " + ", ".join(missing_elig))

# --- 6. doc 06 required figures and no rogue interest figure ---
needed06 = ["₦2,000", "₦1,000", "1%", "0.5%", "3 to 12 months", "30 days"]
missing06 = [t for t in needed06 if t not in doc06]
loan_cols = []
if os.path.isfile(db_path):
    conn = sqlite3.connect(db_path)
    loan_cols = [r[1] for r in conn.execute("PRAGMA table_info(loans)").fetchall()]
    conn.close()
interest_cols = [c for c in loan_cols if "interest" in c.lower()]
percents = set(re.findall(r"\d+(?:\.\d+)?%", doc06))
if not interest_cols:
    fee_percents = {"1%", "0.5%"}
    rogue = percents - fee_percents
    if missing06 or rogue:
        check("doc 06 fees and no invented interest figure", False,
              "missing: " + ", ".join(missing06) + ("; rogue %: " + ", ".join(sorted(rogue)) if rogue else ""))
    else:
        check("doc 06 fees and no invented interest figure", True)
else:
    check("doc 06 fees and no invented interest figure", not missing06,
          "DB stores an interest column; confirm the rate is quoted. missing: " + ", ".join(missing06))

# --- 7. doc 06 last section sources ---
last06 = sections_by_doc.get("rag/docs/06_loans.md", [{}])[-1].get("body", "")
cbn_guide_url = "https://www.cbn.gov.ng/FinInc/FinLit/How_Lodge_Complaints.pdf"
src06 = []
if cbn_guide_url not in last06:
    src06.append("CBN guide URL")
if "2026-10-27" not in last06:
    src06.append("2026-10-27")
if "may be out of date" not in last06:
    src06.append("'may be out of date'")
check("doc 06 Sources cites the CBN guide and dates", not src06, "missing: " + ", ".join(src06))

# --- 8. doc 07 never-ask section covers every item ---
doc07 = texts.get("rag/docs/07_fraud_and_security.md", "")
never_ask = facts["fictional_bank"]["never_ask"]
na_sec = section_containing(sections_by_doc.get("rag/docs/07_fraud_and_security.md", []), "never ask")
na_body = norm(na_sec["body"]) if na_sec else ""
missing_na = [item for item in never_ask if norm(item) not in na_body]
check("doc 07 never-ask section covers every item", not missing_na, "missing: " + ", ".join(missing_na))

# --- 9. doc 07 OTP values, USSD, contact, no disclosure instruction ---
otp_length = settings["bank_api"]["otp_length"]
otp_ttl = settings["bank_api"]["otp_ttl_seconds"]
otp_attempts = settings["bank_api"]["otp_max_attempts"]
session_expiry = settings["session"]["expiry_minutes"]
l2 = next((lvl for lvl in facts["fictional_bank"]["escalation_levels"] if lvl["level"] == "L2"), {})
needed07 = [f"{otp_length}-digit", f"{otp_ttl} seconds", f"{otp_attempts} attempts",
            f"{session_expiry} minutes", "*000#", l2.get("email", "?"), l2.get("phone", "?")]
missing07 = [t for t in needed07 if t not in doc07]
forbidden = [
    "send your pin", "send your otp", "send your cvv", "send your password",
    "send us your pin", "send us your otp", "reply with your pin",
    "share your pin with us", "tell us your pin", "give us your pin",
]
present = [f for f in forbidden if f in doc07.lower()]
if missing07 or present:
    check("doc 07 OTP values, channels and no disclosure ask", False,
          "missing: " + ", ".join(missing07) + ("; disclosure: " + ", ".join(present) if present else ""))
else:
    check("doc 07 OTP values, channels and no disclosure ask", True)

# --- 10. doc 08 sections and Q&A counts ---
doc08 = texts.get("rag/docs/08_general_faq.md", "")
secs08 = sections_by_doc.get("rag/docs/08_general_faq.md", [])
qa_problems = []
if len(secs08) != 10:
    qa_problems.append(f"doc 08 has {len(secs08)} sections")
for s in secs08[1:9]:
    qcount = len(re.findall(r"\*\*Q:", s["body"]))
    if not (3 <= qcount <= 5):
        qa_problems.append(f"{s['heading']} has {qcount} Q items")
check("doc 08 has 10 sections; Q&A sections have 3-5 questions", not qa_problems, "; ".join(qa_problems))

# --- 11. doc 08 required strings ---
needed08 = ["₦53.75", "24 hours", "5 working days", "30 days", "*000#", "never", "fictional",
            l2.get("email", "?")]
missing08 = [t for t in needed08 if t not in doc08]
check("doc 08 has the required figures and contacts", not missing08, "missing: " + ", ".join(missing08))

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
l2_phone = l2.get("phone", "")
safety = []
for p in DOCS:
    if p not in texts:
        continue
    text = texts[p]
    if re.search(r"\b\d{11}\b", text):
        safety.append(f"{p}: 11-digit number")
    for m in re.finditer(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]*[A-Za-z0-9])", text):
        domain = m.group(1).lower()
        if not (domain.endswith(".example") or domain == "cbn.gov.ng"):
            safety.append(f"{p}: email domain {domain}")
    for nm in names:
        if nm and nm in text:
            safety.append(f"{p}: customer name '{nm}'")
    scan_text = text.replace(l2_phone, " ") if l2_phone else text
    for l4 in last4s:
        if l4 and l4 in scan_text:
            safety.append(f"{p}: card last4 '{l4}'")
check("no 11-digit numbers, bad domains, names or card last4s", not safety, "; ".join(safety))

# --- 14. corpus: exactly 8 files, unique titles/ids, sequential prefixes ---
corpus_files = sorted(f for f in glob.glob("rag/docs/*.md")
                      if not os.path.basename(f).startswith("_"))
corpus_problems = []
if len(corpus_files) != 8:
    corpus_problems.append(f"{len(corpus_files)} files, expected 8")
prefixes = sorted(os.path.basename(f)[:2] for f in corpus_files)
expected_prefixes = [f"{i:02d}" for i in range(1, 9)]
if prefixes != expected_prefixes:
    corpus_problems.append(f"prefixes {prefixes}")
titles, ids = [], []
for f in corpus_files:
    lines = read(f).splitlines()
    if lines:
        titles.append(lines[0].strip())
    if len(lines) >= 3:
        m = re.match(r"^Document ID: (RUB-DOC-\d{2}) ", lines[2].strip())
        ids.append(m.group(1) if m else "?")
if len(set(titles)) != len(titles):
    corpus_problems.append("duplicate titles")
if len(set(ids)) != len(ids):
    corpus_problems.append("duplicate Document IDs")
check("corpus has 8 docs RUB-DOC-01..08, unique", not corpus_problems, "; ".join(corpus_problems))

# --- 15. corpus question coverage ---
doc01 = read("rag/docs/01_fee_schedule.md")
doc03 = read("rag/docs/03_transfers_and_failed_transactions.md")
doc04 = read("rag/docs/04_disputes_and_complaints.md")
doc05 = read("rag/docs/05_cards_ussd_app.md")

sec01_transfer = section_containing(sections(doc01), "Transfer fees")
ok_a = bool(sec01_transfer) and "₦53.75" in sec01_transfer["body"] and "above" in sec01_transfer["body"]
check("15a fee above 50,000 (doc 01)", ok_a, "Transfer fees section must have ₦53.75 and 'above'")

ok_b = all(s in doc03 for s in ("double debit", "24 hours", "5 working days"))
check("15b double debit and reversal (doc 03)", ok_b, "missing one of double debit / 24 hours / 5 working days")

sec05_lost = section_containing(sections(doc05), "Lost")
ok_c = bool(sec05_lost) and all(t in sec05_lost["body"] for t in ("last four digits", "yes", "immediately", "₦1,500"))
check("15c lost card (doc 05)", ok_c, "lost-card section missing a required phrase or amount")

ok_d = False
for s in sections_by_doc.get("rag/docs/06_loans.md", []):
    if "₦200,000" in s["body"] and all(norm(t) in norm(s["body"]) for _, t in eligibility_tokens(elig)):
        ok_d = True
        break
check("15d loan NGN 200,000 with eligibility values (doc 06)", ok_d,
      "no section has ₦200,000 together with every eligibility value")

ok_e = bool(na_sec) and all(norm(item) in na_body for item in never_ask)
check("15e never ask (doc 07)", ok_e, "never-ask section missing an item")

sec04_esc = section_containing(sections(doc04), "Escalation")
sec04_cbn = section_containing(sections(doc04), "CBN")
ok_f = (bool(sec04_esc) and l2.get("email", "?") in sec04_esc["body"]
        and "customercare.head@rubiesmfb.example" in sec04_esc["body"]
        and l2.get("phone", "?") in sec04_esc["body"]
        and bool(sec04_cbn) and "cpd@cbn.gov.ng" in sec04_cbn["body"])
check("15f escalate a complaint (doc 04)", ok_f, "escalation/CBN section missing a contact")

# --- 16. corpus phrasing ---
phrase_problems = []
for f in corpus_files:
    text = read(f)
    if "as above" in text.lower() or "see above" in text.lower():
        phrase_problems.append(f"{f}: 'as above'/'see above'")
    if "PENDING_USER_CONFIRMATION" in text:
        phrase_problems.append(f"{f}: PENDING_USER_CONFIRMATION")
check("no 'as above'/'see above' and no PENDING in the corpus", not phrase_problems, "; ".join(phrase_problems))

# --- 17. earlier scripts still pass ---
s1 = subprocess.run(["bash", "scripts/check_rag_step1.sh"], capture_output=True, text=True).stdout
check("check_rag_step1 prints 13 passed, 0 failed", "13 passed, 0 failed" in s1, "got: " + s1.strip().splitlines()[-1])
s2 = subprocess.run(["bash", "scripts/check_rag_step2.sh"], capture_output=True, text=True).stdout
check("check_rag_step2 prints 14 passed, 0 failed", "14 passed, 0 failed" in s2, "got: " + s2.strip().splitlines()[-1])
s3 = subprocess.run(["bash", "scripts/check_rag_step3.sh"], capture_output=True, text=True).stdout
check("check_rag_step3 prints 17 passed, 0 failed", "17 passed, 0 failed" in s3, "got: " + s3.strip().splitlines()[-1])

# --- 18. protected dirs untouched ---
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
