#!/usr/bin/env bash
# Chat 5 step 4: prompt rules (Pidgin register, no-guessing, answer-from-text),
# plus live verification of the 5 Pidgin scenarios and 3 no-guessing cases.
# Usage: LIVE=0 bash scripts/checks/check_chat5_step4.sh   (or LIVE=1)
#
# LIVE=0: pytest, Chat 5 step 3 re-run, protected paths, threshold/top_k,
#         tuning-set checks, and live sections print SKIP.
# LIVE=1: everything runs against real Bedrock; live agent scenarios use the
#         Chat 4 harness (real SQLite + JSONL log) with up to
#         acceptance.max_attempts_per_scenario attempts per scenario.
# The script asserts on tool/state structure and exact values, never on
# reply wording. If a live scenario fails on model behaviour, it prints the
# full transcript and JSONL lines and reports FAIL, without editing prompts.
set -u
source scripts/checks/lib_manifest.sh
source scripts/checks/lib_protected.sh
cd "$(dirname "$0")/../.."

LIVE="${LIVE:-1}"
export LIVE
passes=0
fails=0

check() {
  local name="$1" ok="$2" detail="${3:-}"
  if [ "$ok" = "1" ]; then
    echo "PASS: $name"
    passes=$((passes + 1))
  else
    echo "FAIL: $name ($detail)"
    fails=$((fails + 1))
  fi
}
skip() { echo "SKIP: $1"; }

# ---------------------------------------------------------------- a. pytest
python3 -m pytest -q >/tmp/pytest_chat5_step4.log 2>&1
pytest_rc=$?
count=$(grep -oE '[0-9]+ passed' /tmp/pytest_chat5_step4.log | head -1 | awk '{print $1}')
count="${count:-0}"
if [ "$pytest_rc" -eq 0 ] && [ "$count" -gt 250 ]; then a_ok=1; else a_ok=0; fi
check "a. Full pytest passes with ${count} tests (> 250)" "$a_ok" "pytest rc=${pytest_rc}, count=${count}"

# --------------------------------------------- b. Chat 5 step 3 (all earlier)
LIVE="$LIVE" bash scripts/checks/check_chat5_step3.sh >/tmp/check_chat5_step3_step4.log 2>&1
b_rc=$?
if [ "$b_rc" -eq 0 ]; then b_ok=1; else b_ok=0; fi
check "b. scripts/checks/check_chat5_step3.sh passes" "$b_ok" "rc=${b_rc}; see /tmp/check_chat5_step3_step4.log"

# --------------------------------- c/d. protected agent files vs both bases
PROT_FILES=(agent/session.py agent/bank_client.py agent/errors.py agent/tool_runtime.py)
if git rev-parse -q --verify chat4-done >/dev/null 2>&1; then
  c_mod=""
  for f in "${PROT_FILES[@]}"; do
    [ -n "$(git diff --name-only chat4-done -- "$f" 2>/dev/null)" ] || continue
    if { [ "$f" = agent/session.py ] || [ "$f" = agent/tool_runtime.py ]; } && _reviewed_exempt "$f"; then continue; fi
    c_mod="$c_mod$f "
  done
  if [ -z "$c_mod" ]; then c_ok=1; else c_ok=0; fi
  check "c. identity/confirmation files unchanged since chat4-done" "$c_ok" \
    "modified: $c_mod"
else
  skip "c. identity/confirmation files unchanged since chat4-done (no tag)"
fi

base3="chat3-done"
if ! git rev-parse -q --verify "$base3" >/dev/null 2>&1; then
  base3=$(git log --format=%H --grep='^Chat 3 done' -1 2>/dev/null || true)
fi
if [ -z "${base3:-}" ]; then
  skip "d. identity/confirmation files unmodified since chat3-done (no base ref)"
else
  d_mod=""
  for f in "${PROT_FILES[@]}"; do
    [ -n "$(git diff --name-only --diff-filter=MD "$base3" -- "$f" 2>/dev/null)" ] || continue
    if { [ "$f" = agent/session.py ] || [ "$f" = agent/tool_runtime.py ]; } && _reviewed_exempt "$f"; then continue; fi
    d_mod="$d_mod$f "
  done
  if [ -z "$d_mod" ]; then d_ok=1; else d_ok=0; fi
  check "d. identity/confirmation files unmodified since ${base3}" "$d_ok" \
    "modified: $d_mod"
fi

# ------------------------------------------------- f. threshold/top_k unchanged
f_out=$(python3 - <<'PY' 2>&1
import subprocess, yaml
cur = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
head = yaml.safe_load(subprocess.run(["git", "show", "HEAD:config/settings.yaml"], capture_output=True, text=True).stdout)
current = (cur["rag"]["similarity_threshold"], cur["rag"]["top_k"])
baseline = (head["rag"]["similarity_threshold"], head["rag"]["top_k"])
print("SAME" if current == baseline else f"DIFF {current} vs {baseline}")
PY
)
case "$f_out" in
  SAME*) f_ok=1 ;;
  *) f_ok=0 ;;
esac
check "f. rag.similarity_threshold and rag.top_k unchanged" "$f_ok" "$f_out"

# ------------------------------------------------- g. tuning set (offline)
g_out=$(python3 - <<'PY' 2>&1
import json, yaml
data = yaml.safe_load(open("eval/datasets/pidgin_tuning_set.yaml", encoding="utf-8"))
in_scope = data.get("in_scope") or []
out = data.get("out_of_scope") or []
off = [e for e in out if e.get("kind") == "off_topic"]
unans = [e for e in out if e.get("kind") == "in_domain_unanswerable"]
chunks = set()
for line in open("data/generated/rag_chunks.jsonl", encoding="utf-8"):
    if line.strip():
        chunks.add(json.loads(line)["id"])
missing = [e["expected_chunk_id"] for e in in_scope if e["expected_chunk_id"] not in chunks]
ok = len(in_scope) == 14 and len(off) == 3 and len(unans) == 2 and not missing
print("OK" if ok else f"BAD in_scope={len(in_scope)} off={len(off)} unans={len(unans)} missing={missing}")
PY
)
case "$g_out" in
  OK*) g_ok=1 ;;
  *) g_ok=0 ;;
esac
check "g. tuning set: 14 in-scope, 3 off-topic, 2 unanswerable; ids exist" "$g_ok" "$g_out"

# ------------------------------------------------- h-l. live retrieval gates (separate script; SKIP if LIVE=0)
if [ "$LIVE" != "1" ]; then
  skip "live retrieval gates: scripts/checks/live_retrieval_gates.sh (needs AWS; LIVE=0)"
else
  gates_out=$(bash scripts/checks/live_retrieval_gates.sh 2>&1)
  gates_rc=$?
  printf '%s\n' "$gates_out" | grep -E "^(PASS|FAIL|ERROR|INFO|RESULT)"
  if [ "$gates_rc" -eq 0 ]; then gates_ok=1; else gates_ok=0; fi
  check "live retrieval gates pass (scripts/checks/live_retrieval_gates.sh, 12 checks)" "$gates_ok" "rc=${gates_rc}"
fi

# --------------------------------------------- P1-P5 and N1-N3 live scenarios (separate script; SKIP if LIVE=0)
if [ "$LIVE" != "1" ]; then
  skip "live Pidgin and no-guessing scenarios P1-P5, N1-N3: scripts/checks/live_step4.sh (needs AWS; LIVE=0)"
else
  scen_out=$(bash scripts/checks/live_step4.sh 2>&1)
  scen_rc=$?
  printf '%s\n' "$scen_out" | grep -E "^(PASS|FAIL|ERROR|INFO: Bedrock|RESULT)"
  scen_n=$(printf '%s\n' "$scen_out" | grep -c '^PASS: [PN][1-5] ')
  if [ "$scen_rc" -eq 0 ] && [ "$scen_n" -eq 8 ]; then scen_ok=1; else scen_ok=0; fi
  check "live Pidgin and no-guessing scenarios pass (scripts/checks/live_step4.sh, 8 of 8)" "$scen_ok" "rc=${scen_rc}, passed=${scen_n}"
fi

# --- informational transcript / JSONL reminder ---
echo "INFO: with LIVE=1 this script also runs live_step4.sh and live_retrieval_gates.sh; run them directly to see full transcripts."

echo "RESULT: $passes passed, $fails failed"
if [ "$fails" -ne 0 ]; then exit 1; fi
exit 0
