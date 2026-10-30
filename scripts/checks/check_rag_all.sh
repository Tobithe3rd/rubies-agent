#!/usr/bin/env bash
# Full RAG acceptance run: files, safety, end-to-end behaviour, regression.
# Usage: bash scripts/checks/check_rag_all.sh   (LIVE=0 for the offline path)
set -u
cd "$(dirname "$0")/../.."

python3 - <<'PY'
import os
import re
import sys
import json
import glob
import subprocess

from dotenv import load_dotenv
load_dotenv(".env")

try:
    import yaml
except Exception as exc:  # pragma: no cover
    print(f"FAIL: pyyaml importable - {exc}")
    print("SUMMARY: 0 passed, 1 failed")
    sys.exit(1)

os.environ["ALLOW_RAG_CHANGE"] = "1"

LIVE = os.environ.get("LIVE", "1") == "1"
results = []


def check(name, ok, reason=""):
    if ok:
        print(f"PASS: {name}")
    else:
        print(f"FAIL: {name} - {reason}")
    results.append(bool(ok))


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def py(code, stdin=None):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, input=stdin)


def settings():
    return yaml.safe_load(read("config/settings.yaml"))


def chunks():
    return [json.loads(l) for l in read("data/generated/rag_chunks.jsonl").splitlines() if l.strip()]


def norm(s):
    return str(s).replace(" ", "").lower()


REQUIRED_FILES = [
    "rag/facts.yaml", "rag/sources.md", "rag/chunker.py", "rag/ingest.py",
    "rag/calibrate.py", "rag/search.py", "rag/threshold_report.py",
    "rag/analyze_dev_set.py", "rag/README.md", "eval/datasets/rag_dev_set.yaml",
    "providers/embeddings/titan.py", "providers/embeddings/mock.py",
    "providers/vectorstore/chroma.py", "data/generated/rag_chunks.jsonl",
    "eval/reports/rag_calibration.json", "eval/reports/rag_threshold_report.json",
]

# =====================================================================
# Files and docs
# =====================================================================
doc_files = sorted(glob.glob("rag/docs/*.md"))
prefixes = sorted(os.path.basename(f)[:2] for f in doc_files)
missing = [f for f in REQUIRED_FILES if not os.path.isfile(f) or os.path.getsize(f) == 0]
check("F1 inventory: 8 docs + required non-empty files",
      len(doc_files) == 8 and prefixes == [f"{i:02d}" for i in range(1, 9)] and not missing,
      f"docs={len(doc_files)} prefixes={prefixes} missing/empty={missing[:4]}")

f2 = py("from rag.search import search_policy, build_search_policy; print(callable(search_policy), callable(build_search_policy))")
check("F2 rag.search exposes search_policy and build_search_policy", f2.stdout.strip() == "True True", f2.stdout.strip()[:60])

readme = read("rag/README.md")
expected_sections = ["Overview", "Documents", "Pipeline", "Configuration", "Running it",
                     "Citations and no-guessing", "Known limitations", "Sources and currency", "Checks"]
found_sections = [m.group(1).strip() for m in re.finditer(r"^## (.+)$", readme, re.M)]
commands = ["python -m rag.chunker", "python -m rag.ingest", "python -m rag.calibrate",
            "python -m rag.threshold_report", "python -m rag.analyze_dev_set",
            "bash scripts/checks/check_rag_all.sh"]
f3_problems = []
if found_sections != expected_sections:
    f3_problems.append(f"sections={found_sections}")
if "known limitation" not in readme.lower():
    f3_problems.append("missing 'known limitation'")
for cmd in commands:
    if cmd not in readme:
        f3_problems.append(f"missing cmd '{cmd}'")
rag = settings()["rag"]
if str(rag["similarity_threshold"]) not in readme or str(rag["top_k"]) not in readme:
    f3_problems.append("missing configured threshold/top_k values")
check("F3 README sections, phrase, commands and config values", not f3_problems, "; ".join(f3_problems[:4]))

docs = {}
for c in chunks():
    docs.setdefault(c["doc_id"], c["doc_title"])
f4_missing = [f"{cid} {title}" for cid, title in docs.items() if cid not in readme or title not in readme]
check("F4 README documents table lists all 8 ids and titles", not f4_missing, "missing: " + "; ".join(f4_missing[:3]))

f5 = subprocess.run([sys.executable, "-m", "rag.analyze_dev_set"], capture_output=True, text=True)
for line in f5.stdout.splitlines():
    print("INFO " + line)
check("F5 analyze_dev_set runs on the real report", f5.returncode == 0 and "in-scope questions:" in f5.stdout,
      (f5.stderr or f5.stdout).strip()[:120])

# =====================================================================
# Safety and hygiene
# =====================================================================
real_path = settings()["vectorstore"]["path"]
collection = settings()["vectorstore"]["collection"]
_l2_phone = next(l for l in yaml.safe_load(read("rag/facts.yaml"))["fictional_bank"]["escalation_levels"]
                if l["level"] == "L2")["phone"]
s1_code = (
    "import json,re,sqlite3,chromadb\n"
    "from chromadb.config import Settings\n"
    f"client=chromadb.PersistentClient(path={real_path!r}, settings=Settings(anonymized_telemetry=False))\n"
    f"coll=client.get_collection({collection!r})\n"
    "docs=coll.get(include=['documents'])['documents']\n"
    "conn=sqlite3.connect('data/runtime/bank.db')\n"
    "names=[r[0] for r in conn.execute('SELECT full_name FROM customers')]\n"
    "phones=[r[0] for r in conn.execute('SELECT phone FROM customers')]\n"
    "last4=[str(r[0]) for r in conn.execute('SELECT DISTINCT last4 FROM cards')]\n"
    "conn.close()\n"
    "blob=' '.join(docs)\n"
    f"blob_no_phone=blob.replace({_l2_phone!r}, ' ')\n"
    "bad=[]\n"
    "bad += [n for n in names if n in blob]\n"
    "bad += [p for p in phones if p in blob]\n"
    "bad += [l for l in last4 if l in blob_no_phone]\n"
    "if re.search(r'\\b\\d{11}\\b', blob): bad.append('11-digit')\n"
    "if re.search(r'AKIA[A-Z0-9]{16}', blob): bad.append('aws-key')\n"
    "print(len(docs), bad[:5])\n"
)
s1 = py(s1_code)
s1_ok = False
s1_reason = (s1.stdout or s1.stderr).strip()[:140]
if s1.returncode == 0:
    parts = s1.stdout.split(" ", 1)
    try:
        count = int(parts[0])
        leaked = parts[1].strip()
        s1_ok = count == 75 and leaked == "[]"
        if count != 75:
            s1_reason = f"store has {count} chunks; run python -m rag.ingest"
        elif leaked != "[]":
            s1_reason = f"leaked: {leaked}"
    except Exception:
        pass
check("S1 stored texts are 75 and leak no customer data or secrets", s1_ok, s1_reason)

gitignore = read(".gitignore")
ls_files = subprocess.run(["git", "ls-files", ".env"], capture_output=True, text=True).stdout.strip()
tracked = subprocess.run(["git", "ls-files"], capture_output=True, text=True).stdout.splitlines()
aws_hits = []
pattern = re.compile(r"AKIA[A-Z0-9]{16}")
for path in tracked:
    if path.startswith((".venv/", "data/runtime/chroma/")):
        continue
    if not os.path.isfile(path):
        continue
    try:
        if pattern.search(read(path)):
            aws_hits.append(path)
    except Exception:
        pass
check("S2 .env ignored and no AWS key in tracked files",
      ".env" in gitignore.split("\n") and ls_files == "" and not aws_hits,
      f"gitignore={'.env' in gitignore} ls-files={ls_files!r} hits={aws_hits[:3]}")

# =====================================================================
# Live block
# =====================================================================
def _live_ready():
    r = py("import chromadb;from chromadb.config import Settings;"
           f"c=chromadb.PersistentClient(path={real_path!r},settings=Settings(anonymized_telemetry=False));"
           f"print(c.get_collection({collection!r}).count())")
    return r.stdout.strip() == "75"


live_ready = _live_ready() if LIVE else False


def _queries():
    return [
        "What is the fee for transfers above ₦50,000?",
        "I was debited twice, what happens and how long does a reversal take?",
        "My card is lost, what should I do?",
        "Can I get a ₦200,000 loan and what are the requirements?",
        "What will Rubies never ask me for?",
        "How do I escalate my complaint?",
        "What is the capital of France?",
    ]


def _run_queries():
    code = (
        "import json,sys;"
        "from core.config import load_config;"
        "from core.factories import create_embedder, create_vectorstore;"
        "from rag.search import build_search_policy;"
        "qs=json.loads(sys.stdin.read());"
        "cfg=load_config();e=create_embedder(cfg);s=create_vectorstore(cfg,e);search=build_search_policy(cfg,e,s);"
        "out=[];"
        "\nfor q in qs:\n r=search(q)\n out.append({'status':r.status,'message':r.message,'results':[{'chunk_id':x['chunk_id'],'citation':x['citation'],'text':x['text'],'score':x['score']} for x in r.results]})\n"
        "print(json.dumps(out))"
    )
    r = subprocess.run([sys.executable, "-c", code], input=json.dumps(_queries()),
                       capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return json.loads(r.stdout)


def _live_eval():
    if not LIVE:
        return None
    if not live_ready:
        return "NOT_READY"
    return _run_queries()


live_data = _live_eval()


def _gate():
    if not LIVE:
        return (False, "offline")
    if live_data == "NOT_READY":
        return (False, "run python -m rag.ingest")
    return None


def live_check(name, fn):
    if not LIVE:
        print(f"SKIP: {name}")
        return
    gate = _gate()
    if gate:
        check(name, False, gate[1])
        return
    ok, reason = fn()
    check(name, ok, reason)


def _res(i):
    return live_data[i]


def _combined(i):
    return " ".join(x["text"] for x in _res(i)["results"])


def _has_chunk(i, cid):
    return any(x["chunk_id"] == cid for x in _res(i)["results"])


def _chunk_text(i, cid):
    for x in _res(i)["results"]:
        if x["chunk_id"] == cid:
            return x["text"]
    return ""


live_check("E1 transfer fee: ok, exact citation, text has ₦53.75", lambda: (
    (_res(0)["status"] == "ok"
     and _res(0)["results"][0]["citation"] == "Fee Schedule, section 2 (Transfer fees)"
     and "₦53.75" in _res(0)["results"][0]["text"]),
    f"status={_res(0)['status']} top={_res(0)['results'][0]['citation'] if _res(0)['results'] else '-'}"
))

live_check("E2 double debit: RUB-DOC-03#6 in results, 24 hours and 5 working days", lambda: (
    (_has_chunk(1, "RUB-DOC-03#6") and "24 hours" in _combined(1) and "5 working days" in _combined(1)),
    f"chunk={_has_chunk(1, 'RUB-DOC-03#6')}"
))

live_check("E3 lost card: RUB-DOC-05#3 with the block steps", lambda: (
    (_has_chunk(2, "RUB-DOC-05#3")
     and all(t in _chunk_text(2, "RUB-DOC-05#3") for t in ("last four digits", "immediately", "₦1,500"))),
    f"chunk={_has_chunk(2, 'RUB-DOC-05#3')}"
))


def _e4():
    elig = settings()["bank_api"]["eligibility"]
    tokens = ["₦200,000"]
    for key, value in elig.items():
        if "naira" in key and isinstance(value, (int, float)):
            tokens.append(f"₦{value:,}")
        elif isinstance(value, list):
            tokens.extend(value)
        else:
            tokens.append(str(value))
    combined = norm(_combined(3))
    missing = [t for t in tokens if norm(t) not in combined]
    return (_has_chunk(3, "RUB-DOC-06#7") and not missing, f"missing={missing[:4]}")


live_check("E4 loan 200k: RUB-DOC-06#7 and every eligibility value", _e4)


def _e5():
    never = yaml.safe_load(read("rag/facts.yaml"))["fictional_bank"]["never_ask"]
    text = norm(_chunk_text(4, "RUB-DOC-07#1"))
    missing = [item for item in never if norm(item) not in text]
    return (_has_chunk(4, "RUB-DOC-07#1") and not missing, f"missing={missing[:4]}")


live_check("E5 never-ask: RUB-DOC-07#1 with every item", _e5)


def _e6():
    l2 = next(l for l in yaml.safe_load(read("rag/facts.yaml"))["fictional_bank"]["escalation_levels"] if l["level"] == "L2")
    text = _chunk_text(5, "RUB-DOC-04#6")
    needed = ["complaints@rubiesmfb.example", "customercare.head@rubiesmfb.example", l2["phone"]]
    missing = [t for t in needed if t not in text]
    return (_has_chunk(5, "RUB-DOC-04#6") and not missing, f"missing={missing}")


live_check("E6 escalation: RUB-DOC-04#6 with both emails and the phone", _e6)

live_check("E7 off-topic: no_relevant_result with the configured message", lambda: (
    (_res(6)["status"] == "no_relevant_result" and _res(6)["results"] == []
     and _res(6)["message"] == settings()["rag"]["no_result_message"]),
    f"status={_res(6)['status']}"
))

# =====================================================================
# Regression
# =====================================================================
env = {**os.environ, "LIVE": "1" if LIVE else "0"}
steps = [
    ("check_rag_step1.sh", 13), ("check_rag_step2.sh", 14), ("check_rag_step3.sh", 17),
    ("check_rag_step4.sh", 25), ("check_rag_step5.sh", 19),
    ("check_rag_step6.sh", 20 if LIVE else 14),
    ("check_rag_step7.sh", 21 if LIVE else 17),
    ("check_rag_step8.sh", 23 if LIVE else 19),
]
for script, minimum in steps:
    out = subprocess.run(["bash", f"scripts/checks/{script}"], capture_output=True, text=True, env=env).stdout
    m = re.search(r"SUMMARY: (\d+) passed, (\d+) failed", out)
    ok = bool(m) and m.group(2) == "0" and int(m.group(1)) >= minimum
    last = out.strip().splitlines()[-1] if out.strip() else "(no output)"
    check(f"R1 {script} passes with >= {minimum}", ok, "got: " + last)

pt = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True, text=True)
m = re.search(r"(\d+) passed", pt.stdout)
count = int(m.group(1)) if m else 0
check("R2 pytest passes with at least 125 tests", pt.returncode == 0 and count >= 125,
      f"returncode={pt.returncode} passed={count}")

try:
    diff = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                          capture_output=True, text=True, check=True).stdout
except Exception as exc:
    check("R3 protected paths untouched", False, f"git failed: {exc}")
else:
    protected = [
        ln for ln in diff.splitlines()
        if ln.startswith(("bank_api/", "agent/", "rag/docs/", "providers/", "core/", "config/"))
        or ln in ("rag/facts.yaml", "ARCHITECTURE.md")
    ]
    check("R3 protected paths untouched", not protected, "modified: " + ", ".join(protected))

passed = sum(1 for r in results if r)
failed = len(results) - passed
print(f"SUMMARY: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
PY
