#!/usr/bin/env bash
# Step 8 RAG checks: search_policy, threshold, dev set.
# Usage: bash scripts/checks/check_rag_step8.sh   (LIVE=0 to skip the live block)
set -u
cd "$(dirname "$0")/../.."

python3 - <<'PY'
import os
import re
import sys
import json
import shutil
import tempfile
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


def live_check(name, fn):
    if not LIVE:
        print(f"SKIP: {name}")
        return
    ok, reason = fn()
    check(name, ok, reason)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def py(code, stdin=None):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, input=stdin)


def settings():
    return yaml.safe_load(read("config/settings.yaml"))


def chunks():
    return {json.loads(l)["id"]: json.loads(l) for l in read("data/generated/rag_chunks.jsonl").splitlines() if l.strip()}


def _replace_line(text, key, value):
    out = []
    for line in text.splitlines():
        if line.strip().startswith(key + ":"):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f"{indent}{key}: {value}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def make_config(base, chroma_path, provider="mock", edits=None):
    cfg_dir = os.path.join(base, "config")
    os.makedirs(cfg_dir, exist_ok=True)
    text = read("config/settings.yaml")
    text = text.replace("provider: titan", f"provider: {provider}")
    text = text.replace(f"path: {settings()['vectorstore']['path']}", f"path: {chroma_path}")
    for key, value in (edits or {}).items():
        text = _replace_line(text, key, value)
    with open(os.path.join(cfg_dir, "settings.yaml"), "w", encoding="utf-8") as f:
        f.write(text)
    shutil.copy("config/tools.yaml", os.path.join(cfg_dir, "tools.yaml"))
    return cfg_dir


def ingest(cfg_dir):
    return subprocess.run([sys.executable, "-m", "rag.ingest", "--config", cfg_dir],
                          capture_output=True, text=True)


# =====================================================================
# Offline block
# =====================================================================
tmp = tempfile.mkdtemp()
mock_cfg = make_config(tmp, os.path.join(tmp, "chroma"), provider="mock")
ing = ingest(mock_cfg)
if ing.returncode != 0:
    check("O0 offline ingest of the real chunks", False, ing.stderr[:200])
else:
    print("PASS: O0 offline ingest of the real chunks")
    results.append(True)

PRE = (
    "import json,sys;"
    "from core.config import load_config;"
    "from core.factories import create_embedder, create_vectorstore;"
    "from rag.search import build_search_policy;"
    f"cfg=load_config({mock_cfg!r});"
    "e=create_embedder(cfg);s=create_vectorstore(cfg,e);"
    "search=build_search_policy(cfg,e,s);"
    "chunks={json.loads(l)['id']:json.loads(l) for l in open('data/generated/rag_chunks.jsonl',encoding='utf-8') if l.strip()};"
)

# --- O1 ---
r = py(PRE + "r=search(chunks['RUB-DOC-03#6']['text']);"
            "print(r.status, r.results[0]['chunk_id'] if r.results else '-', "
            "round(r.results[0]['score'],4) if r.results else 0)")
f = r.stdout.split()
check("O1 own chunk text returns ok with that chunk first (>=0.999)",
      len(f) == 3 and f[0] == "ok" and f[1] == "RUB-DOC-03#6" and float(f[2]) >= 0.999,
      (r.stdout or r.stderr).strip()[:120])

# --- O2 ---
r = py(PRE + "r=search(chunks['RUB-DOC-01#2']['text']);"
            "h=[x for x in r.results if x['chunk_id']=='RUB-DOC-01#2'];print(h[0]['citation'] if h else '-')")
check("O2 citation of RUB-DOC-01#2 is exact",
      r.stdout.strip() == "Fee Schedule, section 2 (Transfer fees)", r.stdout.strip()[:80])

# --- O3 ---
r = py(PRE + "r=search('zzzz qqqq');"
            "print(r.status, len(r.results), r.message==cfg.settings.rag.no_result_message)")
f = r.stdout.split()
check("O3 nonsense query returns no_relevant_result with configured message",
      f == ["no_relevant_result", "0", "True"], (r.stdout or r.stderr).strip()[:120])

# --- O4 ---
spy = (
    "import json,sys;\n"
    "from core.config import load_config;\n"
    "from core.factories import create_embedder, create_vectorstore;\n"
    "from rag.search import build_search_policy;\n"
    f"cfg=load_config({mock_cfg!r});\n"
    "e=create_embedder(cfg);s=create_vectorstore(cfg,e);\n"
    "class Spy:\n"
    "    def __init__(self, inner):\n"
    "        self.inner = inner\n"
    "        self.calls = 0\n"
    "        self.provider = 'mock'\n"
    "    @property\n"
    "    def dimensions(self):\n"
    "        return self.inner.dimensions\n"
    "    def embed_query(self, t):\n"
    "        self.calls += 1\n"
    "        return self.inner.embed_query(t)\n"
    "    def embed_documents(self, ts):\n"
    "        return self.inner.embed_documents(ts)\n"
    "spy = Spy(e);search = build_search_policy(cfg, spy, s);\n"
    "st = [search(q).status for q in ('', '   ', 'x'*1001)];\n"
    "print('|'.join(st), spy.calls)"
)
r = py(spy)
check("O4 invalid queries return invalid_query without embedding",
      r.stdout.strip() == "invalid_query|invalid_query|invalid_query 0",
      (r.stdout or r.stderr).strip()[:140])

# --- O5 ---
r = py(PRE + "r=search('What is the transfer fee?');d=r.to_dict();"
            "print(json.dumps(d) is not None, sorted(d.keys()))")
check("O5 to_dict is JSON-serialisable with the six keys",
      "'message'" in r.stdout and "'results'" in r.stdout and "'status'" in r.stdout
      and "'threshold'" in r.stdout and "'top_score'" in r.stdout and "'query'" in r.stdout
      and r.stdout.startswith("True"),
      (r.stdout or r.stderr).strip()[:140])

# --- O6 ---
r = py(PRE + "r=search('What is the transfer fee?');sc=[x['score'] for x in r.results];"
            "print(sc==sorted(sc,reverse=True), len(r.results)<=cfg.settings.rag.top_k, "
            "all(x>=cfg.settings.rag.similarity_threshold for x in sc))")
check("O6 results sorted, within top_k, above threshold", r.stdout.strip() == "True True True",
      (r.stdout or r.stderr).strip()[:80])

# --- O7 ---
invalid = [
    ({"similarity_threshold": 1.5}, "similarity_threshold"),
    ({"top_k": 0}, "top_k"),
    ({"no_result_message": '""'}, "no_result_message"),
    ({"max_query_chars": 10}, "max_query_chars"),
]
bad = []
for i, (edits, key) in enumerate(invalid):
    cfg_dir = make_config(os.path.join(tmp, f"bad{i}"), os.path.join(tmp, "chroma"), edits=edits)
    r = py(f"from core.config import load_config; load_config({cfg_dir!r})")
    if r.returncode == 0 or key not in (r.stdout + r.stderr):
        bad.append(key)
check("O7 invalid config values fail naming the right key", not bad, "not named: " + ", ".join(bad))

# --- O8 ---
dev = yaml.safe_load(read("eval/datasets/rag_dev_set.yaml"))
chunk_map = chunks()
drift = []
if len(dev["in_scope"]) != 20 or len(dev["out_of_scope"]) != 6:
    drift.append(f"shape {len(dev['in_scope'])}/{len(dev['out_of_scope'])}")
for e in dev["in_scope"]:
    cid = e["expected_chunk_id"]
    if cid not in chunk_map:
        drift.append(f"{cid} missing")
    elif e["expected_heading_contains"].lower() not in chunk_map[cid]["section_heading"].lower():
        drift.append(f"{cid} heading drift")
check("O8 dev set: 20 in-scope, 6 out-of-scope, ids and headings valid",
      not drift, "; ".join(drift[:5]))

# --- O9 ---
o9 = []
for path in ("rag/search.py", "rag/threshold_report.py"):
    text = read(path)
    for bad_str in ("0.35", "rubies_policy", "data/runtime/chroma"):
        if bad_str in text:
            o9.append(f"{path}:{bad_str}")
    if "import boto3" in text or "from boto3" in text or "import chromadb" in text or "from chromadb" in text:
        o9.append(f"{path}:provider-import")
check("O9 search/report files have no hardcoded values or provider imports", not o9, "; ".join(o9))

shutil.rmtree(tmp, ignore_errors=True)


# =====================================================================
# Live block
# =====================================================================
def _live_ready():
    real = settings()["vectorstore"]["path"]
    coll = settings()["vectorstore"]["collection"]
    r = py("import chromadb;from chromadb.config import Settings;"
           f"c=chromadb.PersistentClient(path={real!r},settings=Settings(anonymized_telemetry=False));"
           f"print(c.get_collection({coll!r}).count())")
    return r.stdout.strip() == "75"


live_ready = _live_ready()


def _need_store():
    return (False, "run python -m rag.ingest") if not live_ready else None


def _live_l1():
    gate = _need_store()
    if gate:
        return gate
    questions = [
        ("What is the fee for transfers above ₦50,000?", "RUB-DOC-01#2"),
        ("I was debited twice, what happens and how long does a reversal take?", "RUB-DOC-03#6"),
        ("My card is lost, what should I do?", "RUB-DOC-05#3"),
        ("Can I get a ₦200,000 loan and what are the requirements?", "RUB-DOC-06#7"),
        ("What will Rubies never ask me for?", "RUB-DOC-07#1"),
        ("How do I escalate my complaint?", "RUB-DOC-04#6"),
    ]
    code = (
        "import json,sys;"
        "from core.config import load_config;"
        "from core.factories import create_embedder, create_vectorstore;"
        "from rag.search import build_search_policy;"
        "p=json.loads(sys.stdin.read());"
        "cfg=load_config();e=create_embedder(cfg);s=create_vectorstore(cfg,e);search=build_search_policy(cfg,e,s);"
        "chunks={json.loads(l)['id']:json.loads(l) for l in open('data/generated/rag_chunks.jsonl',encoding='utf-8') if l.strip()};"
        "ok=True;"
        "\nfor q,exp in p:\n r=search(q)\n ids=[x['chunk_id'] for x in r.results]\n hit=[x for x in r.results if x['chunk_id']==exp]\n good=r.status=='ok' and exp in ids and hit and hit[0]['citation']==chunks[exp]['citation']\n print('  status=%s top=%s (%.4f) expected=%s citation=%s %s' % (r.status, r.results[0]['chunk_id'] if r.results else '-', r.results[0]['score'] if r.results else 0, exp, hit[0]['citation'] if hit else '-', 'OK' if good else 'MISS'))\n ok = ok and good\n"
        "print('L1_OK' if ok else 'L1_BAD')"
    )
    r = subprocess.run([sys.executable, "-c", code], input=json.dumps(questions),
                       capture_output=True, text=True)
    print(r.stdout)
    ok = "L1_OK" in r.stdout
    if ok:
        first = [ln for ln in r.stdout.splitlines() if "citation=" in ln]
        ok = any("citation=Fee Schedule, section 2 (Transfer fees)" in ln for ln in first)
    return ok, (r.stderr[:200] if r.returncode else "a question failed or Q1 citation mismatch")


live_check("L1 six demo questions return ok with the expected chunk and citation", _live_l1)


def _live_l2():
    gate = _need_store()
    if gate:
        return gate
    code = (
        "from core.config import load_config;"
        "from core.factories import create_embedder, create_vectorstore;"
        "from rag.search import build_search_policy;"
        "cfg=load_config();e=create_embedder(cfg);s=create_vectorstore(cfg,e);search=build_search_policy(cfg,e,s);"
        "rs=[search('What is the capital of France?'), search('What is the weather in Lagos today?')];"
        "print(all(r.status=='no_relevant_result' and r.results==[] for r in rs))"
    )
    r = py(code)
    return r.stdout.strip() == "True", (r.stdout or r.stderr).strip()[:120]


live_check("L2 off-topic questions return no_relevant_result", _live_l2)


def _live_l3():
    gate = _need_store()
    if gate:
        return gate
    r = subprocess.run([sys.executable, "-m", "rag.threshold_report"], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        print("INFO " + line)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout)[:200]
    report = json.loads(read("eval/reports/rag_threshold_report.json"))
    ok = len(report["questions"]) == 26
    return ok, f"questions={len(report['questions'])}"


live_check("L3 threshold_report writes 26 questions", _live_l3)


def _live_l4():
    gate = _need_store()
    if gate:
        return gate
    report = json.loads(read("eval/reports/rag_threshold_report.json"))
    recall = report["recall_at_top_k"]["hits"]
    conf = report["configured"]
    print(f"INFO recall@top_k {recall}/{report['recall_at_top_k']['total']}, "
          f"top-1 {report['top1_accuracy']['hits']}/{report['top1_accuracy']['total']}")
    print(f"INFO in_domain_unanswerable answered at configured threshold: "
          f"{conf['in_domain_unanswerable_answered']}/3 (known limitation, not a gate)")
    ok = recall >= 17 and conf["in_scope_refused"] <= 1 and conf["off_topic_answered"] == 0
    return ok, (f"recall={recall} refused={conf['in_scope_refused']} off_topic={conf['off_topic_answered']}")


live_check("L4 report gates: recall>=17, refused<=1, off_topic==0", _live_l4)

# =====================================================================
# Regression
# =====================================================================
for script, expected in [
    ("check_rag_step1.sh", "13 passed, 0 failed"),
    ("check_rag_step2.sh", "14 passed, 0 failed"),
    ("check_rag_step3.sh", "17 passed, 0 failed"),
    ("check_rag_step4.sh", "25 passed, 0 failed"),
    ("check_rag_step5.sh", "19 passed, 0 failed"),
]:
    out = subprocess.run(["bash", f"scripts/checks/{script}"], capture_output=True, text=True).stdout
    last = out.strip().splitlines()[-1] if out.strip() else "(no output)"
    check(f"R1 {script} prints {expected}", expected in out, "got: " + last)

env0 = {**os.environ, "LIVE": "0"}
for script, minimum in [("check_rag_step6.sh", 14), ("check_rag_step7.sh", 17)]:
    out = subprocess.run(["bash", f"scripts/checks/{script}"], capture_output=True, text=True, env=env0).stdout
    m = re.search(r"SUMMARY: (\d+) passed, (\d+) failed", out)
    ok = bool(m) and m.group(2) == "0" and int(m.group(1)) >= minimum
    check(f"R1 {script} (LIVE=0) passes with >= {minimum}", ok,
          "got: " + (out.strip().splitlines()[-1] if out.strip() else "(no output)"))

pt = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True, text=True)
m = re.search(r"(\d+) passed", pt.stdout)
count = int(m.group(1)) if m else 0
check("R2 pytest passes with at least 120 tests", pt.returncode == 0 and count >= 120,
      f"returncode={pt.returncode} passed={count}")

try:
    diff = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                          capture_output=True, text=True, check=True).stdout
except Exception as exc:
    check("R3 protected paths untouched", False, f"git failed: {exc}")
else:
    protected = [
        ln for ln in diff.splitlines()
        if ln.startswith(("bank_api/", "agent/", "rag/docs/", "providers/"))
        or ln in ("rag/facts.yaml", "rag/chunker.py", "rag/ingest.py")
    ]
    check("R3 protected paths untouched", not protected, "modified: " + ", ".join(protected))

passed = sum(1 for r in results if r)
failed = len(results) - passed
print(f"SUMMARY: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
PY
