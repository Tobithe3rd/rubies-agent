#!/usr/bin/env bash
# Step 7 RAG checks: ChromaDB vector store + ingest + calibration.
# Usage: bash scripts/checks/check_rag_step7.sh   (LIVE=0 to skip the live block)
set -u
cd "$(dirname "$0")/../.."

python3 - <<'PY'
import os
import re
import sys
import glob
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


def make_config(base, chroma_path, provider="mock", replace=None):
    cfg_dir = os.path.join(base, "config")
    os.makedirs(cfg_dir, exist_ok=True)
    text = read("config/settings.yaml")
    text = text.replace("provider: titan", f"provider: {provider}")
    text = text.replace(f"path: {settings()['vectorstore']['path']}", f"path: {chroma_path}")
    if replace:
        for old, new in replace.items():
            text = text.replace(old, new)
    with open(os.path.join(cfg_dir, "settings.yaml"), "w", encoding="utf-8") as f:
        f.write(text)
    shutil.copy("config/tools.yaml", os.path.join(cfg_dir, "tools.yaml"))
    return cfg_dir


def ingest(cfg_dir):
    return subprocess.run([sys.executable, "-m", "rag.ingest", "--config", cfg_dir],
                          capture_output=True, text=True)


def chunk_ids():
    return {json.loads(l)["id"] for l in read("data/generated/rag_chunks.jsonl").splitlines() if l.strip()}


# =====================================================================
# Offline block (mock embedder, temp store)
# =====================================================================
tmp = tempfile.mkdtemp()
mock_cfg = make_config(tmp, os.path.join(tmp, "chroma"), provider="mock")
collection = settings()["vectorstore"]["collection"]
chroma_path = os.path.join(tmp, "chroma")

# --- O1 ---
r = ingest(mock_cfg)
check("O1 ingest exits 0 and prints '75 chunks ingested'",
      r.returncode == 0 and "75 chunks ingested" in r.stdout, (r.stderr or r.stdout)[:160])

# --- O2 ---
o2_code = (
    "import json,sys,chromadb;"
    "from chromadb.config import Settings;"
    f"client=chromadb.PersistentClient(path={chroma_path!r}, settings=Settings(anonymized_telemetry=False));"
    f"coll=client.get_collection({collection!r});"
    "data=coll.get(include=['documents','metadatas','embeddings']);"
    "chunks={json.loads(l)['id']:json.loads(l) for l in open('data/generated/rag_chunks.jsonl',encoding='utf-8') if l.strip()};"
    "ids=data['ids'];docs=data['documents'];metas=data['metadatas'];embs=data['embeddings'];"
    "assert coll.count()==75, coll.count();"
    "assert set(ids)==set(chunks), 'ids differ';"
    "fields=['doc_id','doc_title','file','section_number','section_heading','citation','word_count'];"
    "assert all(docs[i]==chunks[c]['text'] for i,c in enumerate(ids)), 'text differs';"
    "assert all(all(m.get(f) not in (None,'') for f in fields) for m in metas), 'metadata missing';"
    "assert all(len(e)==1024 for e in embs), 'embedding length';"
    "print('OK')"
)
o2 = py(o2_code)
check("O2 reopened store: count, ids, texts, embeddings, metadata",
      "OK" in o2.stdout, (o2.stderr or o2.stdout)[:200])

# --- O3 ---
o3_code = (
    "import chromadb;"
    "from chromadb.config import Settings;"
    f"client=chromadb.PersistentClient(path={chroma_path!r}, settings=Settings(anonymized_telemetry=False));"
    f"coll=client.get_collection({collection!r});"
    "m=coll.get(ids=['RUB-DOC-01#2'], include=['metadatas'])['metadatas'][0];"
    "print(m.get('citation'))"
)
o3 = py(o3_code)
check("O3 stored citation of RUB-DOC-01#2 is exact",
      o3.stdout.strip() == "Fee Schedule, section 2 (Transfer fees)", o3.stdout.strip()[:80])

# --- O4 ---
sqlite = os.path.join(chroma_path, "chroma.sqlite3")
check("O4 temp store has chroma.sqlite3 > 0 bytes",
      os.path.isfile(sqlite) and os.path.getsize(sqlite) > 0, "missing or empty")

# --- O5 ---
assert ingest(mock_cfg).returncode == 0
o5 = py(
    "import json,chromadb;"
    "from chromadb.config import Settings;"
    f"client=chromadb.PersistentClient(path={chroma_path!r}, settings=Settings(anonymized_telemetry=False));"
    f"coll=client.get_collection({collection!r});"
    "ids=coll.get()['ids'];"
    "print(coll.count(), len(set(ids)))"
)
parts = o5.stdout.split()
check("O5 re-ingest keeps count 75 and unique ids",
      len(parts) == 2 and parts[0] == "75" and parts[1] == "75", o5.stdout.strip()[:60])

# --- O6 ---
top_k = settings()["rag"]["top_k"]
o6_code = (
    "import json;"
    "from core.config import load_config;"
    "from core.factories import create_embedder, create_vectorstore;"
    f"cfg=load_config({mock_cfg!r});"
    "e=create_embedder(cfg);s=create_vectorstore(cfg,e);"
    "chunks={json.loads(l)['id']:json.loads(l) for l in open('data/generated/rag_chunks.jsonl',encoding='utf-8') if l.strip()};"
    "res=s.query(e.embed_query(chunks['RUB-DOC-03#6']['text']), cfg.settings.rag.top_k);"
    "scores=[r['score'] for r in res];"
    "print(res[0]['id'], round(res[0]['score'],4), len(res), scores==sorted(scores,reverse=True))"
)
o6 = py(o6_code)
fields = o6.stdout.split()
o6_ok = (len(fields) == 4 and fields[0] == "RUB-DOC-03#6" and float(fields[1]) >= 0.999
         and int(fields[2]) == top_k and fields[3] == "True")
check("O6 self-query returns itself first, sorted, top_k results", o6_ok, o6.stdout.strip()[:100])

# --- O7 ---
titan_cfg = make_config(os.path.join(tmp, "titan"), chroma_path, provider="titan")
o7 = py(
    "from core.config import load_config;"
    "from core.factories import create_embedder, create_vectorstore;"
    f"cfg=load_config({titan_cfg!r});"
    "e=create_embedder(cfg);s=create_vectorstore(cfg,e);"
    "\ntry:\n s.count()\n print('NO_ERROR')\nexcept Exception as exc:\n print('ERR:', exc)"
)
low = o7.stdout.lower()
check("O7 opening a mock store with titan fails on embedder mismatch",
      "embedder" in low and "mismatch" in low, o7.stdout.strip()[:120])

# --- O8 ---
bogus_cfg = make_config(os.path.join(tmp, "bogus"), os.path.join(tmp, "chroma2"),
                        provider="mock", replace={"type: chroma": "type: bogus"})
o8 = py(f"from core.config import load_config; load_config({bogus_cfg!r})")
check("O8 unknown vector_store.type fails naming 'vector_store.type'",
      o8.returncode != 0 and "vector_store.type" in (o8.stdout + o8.stderr),
      f"rc={o8.returncode}")

# --- O9 ---
chroma_import_bad, forbidden_literal = [], []
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in (".venv", ".git", "__pycache__", ".pytest_cache")]
    for name in files:
        if not name.endswith(".py"):
            continue
        path = os.path.join(root, name)
        text = read(path)
        if ("import chromadb" in text or "from chromadb" in text) and not path.startswith("./providers/vectorstore/"):
            chroma_import_bad.append(path)
        # Tests legitimately embed a settings blob, so scope the literal scan to code.
        if not path.startswith("./tests/") and ("data/runtime/chroma" in text or "rubies_policy" in text):
            forbidden_literal.append(path)
provider_text = read("providers/vectorstore/chroma.py")
telemetry_ok = "anonymized_telemetry" in provider_text and "False" in provider_text
gitignore_ok = "data/runtime/chroma" in read(".gitignore")
check("O9 chromadb only in providers/vectorstore; no hardcoded path/collection; telemetry off; gitignore",
      not chroma_import_bad and not forbidden_literal and telemetry_ok and gitignore_ok,
      f"chromadb:{chroma_import_bad[:2]} literals:{forbidden_literal[:2]} telemetry:{telemetry_ok} gitignore:{gitignore_ok}")

shutil.rmtree(tmp, ignore_errors=True)


# =====================================================================
# Live block (titan, real path)
# =====================================================================
def _live_ingest():
    r = ingest("config")
    ok = r.returncode == 0 and "75 chunks ingested" in r.stdout and "amazon.titan-embed-text-v2:0" in r.stdout
    return ok, (r.stderr or r.stdout)[:160]


live_check("L1 live ingest exits 0 and prints 75 chunks + model id", _live_ingest)


def _live_reopen():
    real_path = settings()["vectorstore"]["path"]
    code = (
        "import json,chromadb;"
        "from chromadb.config import Settings;"
        f"client=chromadb.PersistentClient(path={real_path!r}, settings=Settings(anonymized_telemetry=False));"
        f"coll=client.get_collection({collection!r});"
        "meta=coll.metadata or {};"
        "chunks={json.loads(l)['id'] for l in open('data/generated/rag_chunks.jsonl',encoding='utf-8') if l.strip()};"
        "ids=set(coll.get()['ids']);"
        "ok=coll.count()==75 and ids==chunks and meta.get('embedder_model')=='amazon.titan-embed-text-v2:0' and meta.get('embedder_dimensions')==1024;"
        "print('OK' if ok else 'BAD '+str(meta)+' count='+str(coll.count()))"
    )
    r = py(code)
    return ("OK" in r.stdout), (r.stdout.strip() or r.stderr)[:200]


live_check("L2 live store: count 75, ids match, metadata names model id and 1024", _live_reopen)


def _live_rank():
    questions = [
        ("What is the fee for transfers above ₦50,000?", "RUB-DOC-01#2"),
        ("I was debited twice, what happens and how long does a reversal take?", "RUB-DOC-03#6"),
        ("My card is lost, what should I do?", "RUB-DOC-05#3"),
        ("Can I get a ₦200,000 loan and what are the requirements?", "RUB-DOC-06#7"),
        ("What will Rubies never ask me for?", "RUB-DOC-07#1"),
        ("How do I escalate my complaint?", "RUB-DOC-04#6"),
    ]
    payload = {"questions": questions, "top_k": top_k}
    code = (
        "import json,sys;"
        "from core.config import load_config;"
        "from core.factories import create_embedder, create_vectorstore;"
        "p=json.loads(sys.stdin.read());"
        "cfg=load_config();e=create_embedder(cfg);s=create_vectorstore(cfg,e);"
        "ok=True;"
        "\nfor q,exp in p['questions']:\n res=s.query(e.embed_query(q), p['top_k'])\n ids=[r['id'] for r in res]\n rank=ids.index(exp)+1 if exp in ids else -1\n score=res[0]['score']\n print('  rank=%s score=%.4f expected=%s top=%s %s' % (rank, score, exp, ids[0], 'OK' if exp in ids else 'MISS'))\n ok = ok and (exp in ids)\n"
        "print('RANK_OK' if ok else 'RANK_BAD')"
    )
    r = subprocess.run([sys.executable, "-c", code], input=json.dumps(payload),
                       capture_output=True, text=True)
    print(r.stdout)
    return ("RANK_OK" in r.stdout), (r.stderr[:200] if r.returncode else "a question missed top_k")


live_check("L3 each in-scope question finds its chunk in top_k", _live_rank)


def _live_calibrate():
    r = subprocess.run([sys.executable, "-m", "rag.calibrate"], capture_output=True, text=True)
    if r.returncode != 0:
        return False, (r.stderr or r.stdout)[:200]
    data = json.loads(read("eval/reports/rag_calibration.json"))
    in_scope = [d for d in data if d["group"] == "in_scope"]
    out_scope = [d for d in data if d["group"] == "out_of_scope"]
    ok = len(data) == 11 and len(in_scope) == 6 and len(out_scope) == 5 \
        and all(len(d["top_results"]) == top_k for d in data)
    if ok:
        for group in ("in_scope", "out_of_scope"):
            print(f"INFO {group}:")
            for d in data:
                if d["group"] == group:
                    top = d["top_results"][0]
                    print(f"INFO   {d['question']} -> {top['id']} ({top['score']:.4f})")
    return ok, f"entries={len(data)}"


live_check("L4 calibrate writes 11 entries (6 in_scope, 5 out_of_scope)", _live_calibrate)

# =====================================================================
# Regression
# =====================================================================
step6_expected = "20 passed, 0 failed" if LIVE else "14 passed, 0 failed"
for script, expected in [
    ("check_rag_step1.sh", "13 passed, 0 failed"),
    ("check_rag_step2.sh", "14 passed, 0 failed"),
    ("check_rag_step3.sh", "17 passed, 0 failed"),
    ("check_rag_step4.sh", "25 passed, 0 failed"),
    ("check_rag_step5.sh", "19 passed, 0 failed"),
    ("check_rag_step6.sh", step6_expected),
]:
    out = subprocess.run(["bash", f"scripts/checks/{script}"], capture_output=True, text=True).stdout
    last = out.strip().splitlines()[-1] if out.strip() else "(no output)"
    check(f"R1 {script} prints {expected}", expected in out, "got: " + last)

pt = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True, text=True)
m = re.search(r"(\d+) passed", pt.stdout)
count = int(m.group(1)) if m else 0
check("R2 pytest passes with at least 112 tests", pt.returncode == 0 and count >= 112,
      f"returncode={pt.returncode} passed={count}")

try:
    diff = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                          capture_output=True, text=True, check=True).stdout
except Exception as exc:
    check("R3 protected paths untouched", False, f"git failed: {exc}")
else:
    protected = [
        ln for ln in diff.splitlines()
        if ln.startswith(("bank_api/", "agent/", "rag/docs/", "providers/embeddings/"))
        or ln in ("rag/facts.yaml", "rag/chunker.py")
    ]
    check("R3 protected paths untouched", not protected, "modified: " + ", ".join(protected))

passed = sum(1 for r in results if r)
failed = len(results) - passed
print(f"SUMMARY: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
PY
