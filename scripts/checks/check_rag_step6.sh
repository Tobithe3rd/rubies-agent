#!/usr/bin/env bash
# Step 6 RAG checks: Titan v2 embedder + mock embedder.
# Usage: bash scripts/checks/check_rag_step6.sh   (LIVE=0 to skip the live AWS checks)
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

# Let step 1-5 tolerate this step's sanctioned core/ and config/ changes.
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


def py(code):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)


def settings():
    return yaml.safe_load(read("config/settings.yaml"))


def temp_config(**overrides):
    """Copy settings.yaml/tools.yaml to a temp dir and apply string overrides."""
    tmpdir = tempfile.mkdtemp()
    text = read("config/settings.yaml")
    for old, new in overrides.items():
        text = text.replace(old, new)
    with open(os.path.join(tmpdir, "settings.yaml"), "w", encoding="utf-8") as f:
        f.write(text)
    shutil.copy("config/tools.yaml", os.path.join(tmpdir, "tools.yaml"))
    return tmpdir


# --- 1. config loads; startup names titan + model id ---
model_id = settings()["embeddings"]["model_id"]
s = py("from core.startup import run_startup; run_startup()")
out = s.stdout + s.stderr
check("startup names embedder 'titan' and the model id",
      "kind=embedder" in out and "titan" in out and model_id in out,
      "embedder line missing")

# --- 2. provider mock via temp config ---
mock_dir = temp_config(**{"provider: titan": "provider: mock"})
s = py(f"from core.startup import run_startup; run_startup({mock_dir!r})")
check("temp config with provider mock makes startup print 'mock'",
      "kind=embedder impl=mock" in (s.stdout + s.stderr), "no mock embedder line")
shutil.rmtree(mock_dir, ignore_errors=True)

# --- 3. provider bogus fails naming embedding.provider ---
bogus_dir = temp_config(**{"provider: titan": "provider: bogus"})
bad = py(f"from core.config import load_config; load_config({bogus_dir!r})")
check("provider bogus fails naming 'embedding.provider'",
      bad.returncode != 0 and "embedding.provider" in (bad.stdout + bad.stderr),
      f"rc={bad.returncode}")
shutil.rmtree(bogus_dir, ignore_errors=True)

# --- 4. mock embeds all 75 chunks: length, norm, no NaN, deterministic ---
mock_code = (
    "import json,math,hashlib,sys;"
    "from core.config import load_config;"
    "from providers.embeddings.mock import MockEmbedder;"
    "cfg=load_config();"
    "e=MockEmbedder(cfg.settings.embeddings,cfg.env);"
    "recs=[json.loads(l) for l in open('data/generated/rag_chunks.jsonl',encoding='utf-8') if l.strip()];"
    "v=e.embed_documents([r['text'] for r in recs]);"
    "assert len(v)==75, len(v);"
    "assert all(len(x)==cfg.settings.embeddings.dimensions for x in v);"
    "assert all(abs(math.sqrt(sum(y*y for y in x))-1.0)<1e-6 for x in v);"
    "assert all(math.isfinite(y) for x in v for y in x);"
    "print(hashlib.sha256(json.dumps(v).encode()).hexdigest())"
)
first = py(mock_code)
second = py(mock_code)
check("mock embeds 75 chunks (length/norm/NaN) deterministically",
      first.returncode == 0 and first.stdout == second.stdout,
      (first.stderr or "hashes differ")[:120])

# --- 5. mock rejects empty text ---
empty_code = (
    "from core.config import load_config;"
    "from providers.embeddings.mock import MockEmbedder;"
    "cfg=load_config();"
    "e=MockEmbedder(cfg.settings.embeddings,cfg.env);"
    "\ntry:\n e.embed_query('')\n print('NO_ERROR')\nexcept ValueError:\n print('VALUE_ERROR')"
)
empty = py(empty_code)
check("mock rejects empty text", "VALUE_ERROR" in empty.stdout, empty.stdout.strip()[:60])

# --- 6. mock cosine: identical 1.0, different < 1.0 ---
cos_code = (
    "from core.config import load_config;"
    "from providers.embeddings.mock import MockEmbedder;"
    "cfg=load_config();"
    "e=MockEmbedder(cfg.settings.embeddings,cfg.env);"
    "a=e.embed_query('transfer fee above fifty thousand');"
    "b=e.embed_query('transfer fee above fifty thousand');"
    "c=e.embed_query('lost card block replacement');"
    "cos=lambda p,q: sum(x*y for x,y in zip(p,q));"
    "print(cos(a,b), cos(a,c))"
)
cos = py(cos_code)
try:
    same, diff = [float(x) for x in cos.stdout.split()]
    cos_ok = abs(same - 1.0) < 1e-9 and diff < 1.0
except Exception:
    same, diff, cos_ok = 0.0, 1.0, False
check("mock cosine identical=1.0, different<1.0", cos_ok, f"same={same} diff={diff}")

# --- 7. boto3 only in providers/embeddings; no 'amazon.titan' in .py ---
boto3_bad, titan_bad = [], []
for root, dirs, files in os.walk("."):
    dirs[:] = [d for d in dirs if d not in (".venv", ".git", "__pycache__", ".pytest_cache")]
    for name in files:
        if not name.endswith(".py"):
            continue
        path = os.path.join(root, name)
        text = read(path)
        if ("import boto3" in text or "from boto3" in text) and not path.startswith("./providers/embeddings/"):
            boto3_bad.append(path)
        if "amazon.titan" in text:
            titan_bad.append(path)
check("boto3 only in providers/embeddings and no hardcoded model id",
      not boto3_bad and not titan_bad,
      f"boto3: {boto3_bad[:3]} model-id: {titan_bad[:3]}")

# --- 8. LIVE: env var names present ---
def _env_names():
    missing = [n for n in ("AWS_REGION", "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY") if not os.environ.get(n)]
    return (not missing, "missing: " + ", ".join(missing))
live_check("AWS_REGION/AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY are set", _env_names)


# --- LIVE helpers ---
def titan_embed(code):
    return py(
        "from core.config import load_config;"
        "from core.factories import create_embedder;"
        "cfg=load_config();"
        "e=create_embedder(cfg);"
        + code
    )


live_check("Titan returns a vector of length 1024", lambda: (
    (lambda r: (r.returncode == 0 and r.stdout.strip().endswith("1024"), (r.stderr or r.stdout)[:120]))(
        titan_embed("v=e.embed_query('hello world');print(len(v))")
    )
))

live_check("Titan vector norm within 0.001 of 1", lambda: (
    (lambda r: (r.returncode == 0 and r.stdout.strip() == "OK", (r.stderr or r.stdout)[:120]))(
        titan_embed(
            "import math;"
            "v=e.embed_query('hello world');"
            "print('OK' if abs(math.sqrt(sum(x*x for x in v))-1.0)<0.001 else 'BAD')"
        )
    )
))

live_check("Titan same text twice has cosine >= 0.999", lambda: (
    (lambda r: (r.returncode == 0 and r.stdout.strip() == "OK", (r.stderr or r.stdout)[:120]))(
        titan_embed(
            "a=e.embed_query('what is the transfer fee');"
            "b=e.embed_query('what is the transfer fee');"
            "c=sum(x*y for x,y in zip(a,b));"
            "print('OK' if c>=0.999 else 'BAD '+str(c))"
        )
    )
))


# --- 12. LIVE: ranking over 6 chunks ---
def _ranking():
    recs = {json.loads(l)["id"]: json.loads(l) for l in read("data/generated/rag_chunks.jsonl").splitlines() if l.strip()}
    ids = ["RUB-DOC-01#2", "RUB-DOC-03#6", "RUB-DOC-04#6", "RUB-DOC-05#3", "RUB-DOC-06#7", "RUB-DOC-07#1"]
    missing = [i for i in ids if i not in recs]
    if missing:
        return False, "missing chunk ids: " + ", ".join(missing)
    questions = [
        ("What is the fee for transfers above ₦50,000?", "RUB-DOC-01#2"),
        ("I was debited twice, what happens and how long does a reversal take?", "RUB-DOC-03#6"),
        ("My card is lost, what should I do?", "RUB-DOC-05#3"),
        ("Can I get a ₦200,000 loan and what are the requirements?", "RUB-DOC-06#7"),
        ("What will Rubies never ask me for?", "RUB-DOC-07#1"),
        ("How do I escalate my complaint?", "RUB-DOC-04#6"),
    ]
    payload = {"ids": ids, "texts": [recs[i]["text"] for i in ids], "questions": questions}
    code = (
        "import json,sys;"
        "from core.config import load_config;"
        "from core.factories import create_embedder;"
        "p=json.loads(sys.stdin.read());"
        "cfg=load_config();e=create_embedder(cfg);"
        "cv=[e.embed_query(t) for t in p['texts']];"
        "cos=lambda a,b: sum(x*y for x,y in zip(a,b));"
        "ok=True;"
        "\nfor q,exp in p['questions']:\n qv=e.embed_query(q)\n scores=[(cos(qv,cv[i]),p['ids'][i]) for i in range(len(p['ids']))]\n print(q)\n [print('  %.4f %s' % (s,i)) for s,i in scores]\n top=max(scores)[1]\n print('  top=%s expected=%s %s' % (top,exp,'OK' if top==exp else 'MISS'))\n ok = ok and top==exp\n"
        "print('RANK_OK' if ok else 'RANK_BAD')"
    )
    r = subprocess.run([sys.executable, "-c", code], input=json.dumps(payload),
                       capture_output=True, text=True)
    print(r.stdout)
    return ("RANK_OK" in r.stdout), (r.stderr[:200] if r.returncode else "a question ranked wrong")


live_check("Titan top-1 chunk matches for all 6 questions", _ranking)


# --- 13. LIVE: bogus model id ---
def _bogus_model():
    tmpdir = temp_config(**{"model_id: amazon.titan-embed-text-v2:0": "model_id: amazon.titan-embed-text-v2:0-bogus"})
    r = py(
        "from core.config import load_config;"
        "from core.factories import create_embedder;"
        f"cfg=load_config({tmpdir!r});"
        "e=create_embedder(cfg);"
        "\ntry:\n e.embed_query('hello')\n print('NO_ERROR')\nexcept Exception as exc:\n print('ERROR:', exc)"
    )
    shutil.rmtree(tmpdir, ignore_errors=True)
    out = r.stdout + r.stderr
    names_ok = not any(v and v in out for v in (
        os.environ.get("AWS_ACCESS_KEY_ID"),
        os.environ.get("AWS_SECRET_ACCESS_KEY"),
        os.environ.get("AWS_SESSION_TOKEN"),
    ))
    named = "amazon.titan-embed-text-v2:0-bogus" in out
    text_ok = ("model access" in out.lower() or "validation" in out.lower()
               or "foundation model" in out.lower() or "could not resolve" in out.lower())
    return (named and text_ok and names_ok), f"named={named} text={text_ok} no_secrets={names_ok}"


live_check("bogus model id fails naming the model and access/validation", _bogus_model)

# --- 14. earlier scripts still pass ---
for script, expected in [
    ("check_rag_step1.sh", "13 passed, 0 failed"),
    ("check_rag_step2.sh", "14 passed, 0 failed"),
    ("check_rag_step3.sh", "17 passed, 0 failed"),
    ("check_rag_step4.sh", "25 passed, 0 failed"),
    ("check_rag_step5.sh", "19 passed, 0 failed"),
]:
    out = subprocess.run(["bash", f"scripts/checks/{script}"], capture_output=True, text=True).stdout
    last = out.strip().splitlines()[-1] if out.strip() else "(no output)"
    check(f"{script} prints {expected}", expected in out, "got: " + last)

# --- 15. pytest passes with the new tests ---
pt = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True, text=True)
m = re.search(r"(\d+) passed", pt.stdout)
count = int(m.group(1)) if m else 0
check("pytest passes with at least 105 tests", pt.returncode == 0 and count >= 105,
      f"returncode={pt.returncode} passed={count}")

# --- 16. protected paths untouched ---
try:
    diff = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                          capture_output=True, text=True, check=True).stdout
except Exception as exc:
    check("no bank_api/agent/rag/docs/rag.chunker files or rag/facts.yaml modified", False, f"git failed: {exc}")
else:
    protected = [
        ln for ln in diff.splitlines()
        if ln.startswith(("bank_api/", "agent/", "rag/docs/", "providers/")) or ln in ("rag/facts.yaml", "rag/chunker.py")
    ]
    check("no bank_api/agent/rag/docs/rag.chunker files or rag/facts.yaml modified", not protected,
          "modified: " + ", ".join(protected))

passed = sum(1 for r in results if r)
failed = len(results) - passed
print(f"SUMMARY: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
PY
