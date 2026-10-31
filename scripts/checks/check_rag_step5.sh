#!/usr/bin/env bash
# Step 5 RAG checks: config + heading chunker.
# Usage: bash scripts/checks/check_rag_step5.sh
set -u
cd "$(dirname "$0")/../.."

python3 - <<'PY'
import os
import re
import sys
import json
import glob
import shutil
import hashlib
import tempfile
import subprocess

try:
    import yaml
except Exception as exc:  # pragma: no cover
    print(f"FAIL: pyyaml importable - {exc}")
    print("SUMMARY: 0 passed, 1 failed")
    sys.exit(1)

# Allow step 1-4 to tolerate this step's sanctioned core/ and config/ changes.
os.environ["ALLOW_RAG_CHANGE"] = "1"

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


def py(code):
    return subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)


def run_chunker():
    subprocess.run([sys.executable, "-m", "rag.chunker"], check=True, capture_output=True, text=True)


# --- 0. fresh chunk file ---
chunks_path = "data/generated/rag_chunks.jsonl"
if os.path.exists(chunks_path):
    os.remove(chunks_path)
run_chunker()


def records():
    with open(chunks_path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


# --- 1. config loads with new rag keys; startup shows chunking mode ---
r = py("from core.config import load_config; c=load_config(); "
       "print(c.settings.rag.chunking.mode, c.settings.rag.chunks_path, c.settings.rag.ignore_prefixes)")
cfg_ok = r.returncode == 0 and r.stdout.strip().startswith("heading")
s = py("from core.startup import run_startup; run_startup()")
startup_ok = "rag chunking mode: heading" in (s.stdout + s.stderr)
check("config loads with new rag keys and startup shows chunking mode",
      cfg_ok and startup_ok, f"cfg={r.stdout.strip()!r} startup_ok={startup_ok}")

# --- 2. bogus chunking.mode fails the loader ---
tmpdir = tempfile.mkdtemp()
shutil.copy("config/settings.yaml", os.path.join(tmpdir, "settings.yaml"))
shutil.copy("config/tools.yaml", os.path.join(tmpdir, "tools.yaml"))
settings_text = read(os.path.join(tmpdir, "settings.yaml"))
if "    mode: heading" not in settings_text:
    check("bogus chunking.mode fails the loader", False, "could not find '    mode: heading' to replace")
else:
    with open(os.path.join(tmpdir, "settings.yaml"), "w", encoding="utf-8") as f:
        f.write(settings_text.replace("    mode: heading", "    mode: bogus"))
    bad = py(f"from core.config import load_config; load_config({tmpdir!r})")
    check("bogus chunking.mode fails the loader",
          bad.returncode != 0 and "chunking.mode" in (bad.stdout + bad.stderr),
          f"rc={bad.returncode} out={(bad.stdout + bad.stderr)[:120]!r}")
shutil.rmtree(tmpdir, ignore_errors=True)

# --- 3. chunk file exists and every line is JSON ---
try:
    recs = records()
    check("data/generated/rag_chunks.jsonl exists and every line is valid JSON", True)
except Exception as exc:
    check("data/generated/rag_chunks.jsonl exists and every line is valid JSON", False, str(exc))
    recs = []

# --- 4. chunk count equals the number of "## " lines ---
expected_sections = 0
for path in sorted(glob.glob("rag/docs/*.md")):
    if os.path.basename(path).startswith("_"):
        continue
    expected_sections += sum(1 for line in read(path).splitlines() if line.startswith("## "))
check(f"chunk count equals section count ({expected_sections})",
      len(recs) == expected_sections, f"chunks={len(recs)} sections={expected_sections}")

# --- 5. ids unique and well-formed ---
ids = [r["id"] for r in recs]
id_re = re.compile(r"^RUB-DOC-0[1-8]#[0-9]+(-[a-z])?$")
bad_ids = [i for i in ids if not id_re.match(i)]
check("chunk ids unique and well-formed",
      len(ids) == len(set(ids)) and not bad_ids,
      f"dupes={len(ids) - len(set(ids))} bad={bad_ids[:5]}")

# --- 6. every chunk has all nine fields, non-empty ---
fields = ["id", "doc_id", "doc_title", "file", "section_number", "section_heading", "citation", "text", "word_count"]
missing = [f"{r.get('id', '?')}:{fld}" for r in recs for fld in fields if not r.get(fld)]
check("every chunk has all nine fields, non-empty", not missing, "missing: " + ", ".join(missing[:5]))


# --- helpers to re-derive from source ---
def parse_doc(path):
    lines = read(path).splitlines()
    title, doc_id = "", ""
    for line in lines:
        if not title and line.startswith("# "):
            title = line[2:].strip()
        m = re.match(r"^Document ID:\s*(RUB-DOC-\d{2})", line)
        if m and not doc_id:
            doc_id = m.group(1)
    sections = {}
    idxs = [i for i, line in enumerate(lines) if re.match(r"^## \d+\. ", line)]
    for k, start in enumerate(idxs):
        end = idxs[k + 1] if k + 1 < len(idxs) else len(lines)
        m = re.match(r"^## (\d+)\. (.+)$", lines[start])
        body_lines = [ln for ln in lines[start + 1:end]]
        last_nonempty = next((ln for ln in reversed(body_lines) if ln.strip()), "")
        sections[int(m.group(1))] = {"heading": m.group(2).strip(), "last": last_nonempty}
    return title, doc_id, sections


docs = {}
for path in sorted(glob.glob("rag/docs/*.md")):
    if not os.path.basename(path).startswith("_"):
        docs[path] = parse_doc(path)

# --- 7. RUB-DOC-01#2 citation and text prefix ---
by_id = {r["id"]: r for r in recs}
rec = by_id.get("RUB-DOC-01#2")
ok7 = bool(rec) and rec["citation"] == "Fee Schedule, section 2 (Transfer fees)" \
    and rec["text"].startswith("Fee Schedule > 2. ")
check("RUB-DOC-01#2 citation and text prefix", ok7,
      f"got citation={rec['citation']!r}" if rec else "chunk missing")

# --- 8. citation matches the source heading ---
bad_cit = []
for r in recs:
    title, doc_id, sections = docs.get(r["file"], ("", "", {}))
    sec = sections.get(r["section_number"])
    expected = f"{title}, section {r['section_number']} ({sec['heading']})" if sec else None
    if r["citation"] != expected:
        bad_cit.append(r["id"])
check("every citation matches the source heading", not bad_cit, "bad: " + ", ".join(bad_cit[:5]))

# --- 9. text ends with the section's last line and has no '## ' line ---
bad_end = []
for r in recs:
    _, _, sections = docs.get(r["file"], ("", "", {}))
    sec = sections.get(r["section_number"])
    if not sec:
        bad_end.append(f"{r['id']}:no-section")
        continue
    lines = [ln for ln in r["text"].splitlines() if ln.strip()]
    if not lines or lines[-1] != sec["last"]:
        bad_end.append(f"{r['id']}:lastline")
    if any(ln.startswith("## ") for ln in r["text"].splitlines()):
        bad_end.append(f"{r['id']}:has-heading")
check("chunk text ends with the section last line and has no '## '", not bad_end,
      "bad: " + ", ".join(bad_end[:5]))

# --- 10. all 8 documents have a Sources and currency chunk ---
have_sources = {r["doc_id"] for r in recs if "Sources and currency" in r["section_heading"]}
expected_docs = {f"RUB-DOC-{i:02d}" for i in range(1, 9)}
check("all 8 documents have a Sources and currency chunk",
      expected_docs <= have_sources, "missing: " + ", ".join(sorted(expected_docs - have_sources)))

# --- 11. no chunk exceeds max_words ---
max_words = yaml.safe_load(read("config/settings.yaml"))["rag"]["chunking"]["max_words"]
over = [r["id"] for r in recs if r["word_count"] > max_words]
check(f"no chunk word_count exceeds max_words ({max_words})", not over, "over: " + ", ".join(over[:5]))

# --- 12. two runs are identical ---
first = hashlib.sha256(open(chunks_path, "rb").read()).hexdigest()
run_chunker()
second = hashlib.sha256(open(chunks_path, "rb").read()).hexdigest()
check("two consecutive runs give identical sha256", first == second, f"{first[:12]} != {second[:12]}")

# --- 13. an ignored-prefix file produces no chunks ---
probe = "rag/docs/_probe.md"
try:
    with open(probe, "w", encoding="utf-8") as f:
        f.write("# Probe\n\nDocument ID: RUB-DOC-99 | Version: 1.0 | Effective: 2026-10-01 | Owner: Customer Experience\n\n## 1. Probe section\n\nThis must not become a chunk.\n")
    run_chunker()
    probe_recs = records()
    leaked = [r["id"] for r in probe_recs if "_probe" in r["file"]]
    check("ignored-prefix file produces no chunks", not leaked, "leaked: " + ", ".join(leaked[:5]))
finally:
    if os.path.exists(probe):
        os.remove(probe)
    run_chunker()  # restore the real chunk file

# --- 14. earlier scripts still pass ---
for script, expected in [
    ("check_rag_step1.sh", "13 passed, 0 failed"),
    ("check_rag_step2.sh", "14 passed, 0 failed"),
    ("check_rag_step3.sh", "17 passed, 0 failed"),
    ("check_rag_step4.sh", "25 passed, 0 failed"),
]:
    out = subprocess.run(["bash", f"scripts/checks/{script}"], capture_output=True, text=True).stdout
    last = out.strip().splitlines()[-1] if out.strip() else "(no output)"
    check(f"{script} prints {expected}", expected in out, "got: " + last)

# --- 15. pytest passes with the new tests ---
pt = subprocess.run([sys.executable, "-m", "pytest", "-q"], capture_output=True, text=True)
m = re.search(r"(\d+) passed", pt.stdout)
count = int(m.group(1)) if m else 0
check("pytest passes with at least 97 tests", pt.returncode == 0 and count >= 97,
      f"returncode={pt.returncode} passed={count}")

# --- 16. protected dirs untouched ---
try:
    diff = subprocess.run(["git", "diff", "--name-only", "HEAD"],
                          capture_output=True, text=True, check=True).stdout
except Exception as exc:
    check("no bank_api/agent/rag/docs/providers files or rag/facts.yaml modified", False, f"git failed: {exc}")
else:
    protected = [
        ln for ln in diff.splitlines()
        if ln.startswith(("bank_api/", "agent/", "rag/docs/", "providers/")) or ln == "rag/facts.yaml"
    ]
    check("no bank_api/agent/rag/docs/providers files or rag/facts.yaml modified", not protected,
          "modified: " + ", ".join(protected))

passed = sum(1 for r in results if r)
failed = len(results) - passed
print(f"SUMMARY: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
PY
