#!/usr/bin/env bash
# Chat 5 step 3 checks: measure how query rewriting changes retrieval on Pidgin.
# Measurement only: nothing here changes the threshold, top_k, prompts or docs.
# Usage: LIVE=0 bash scripts/checks/check_chat5_step3.sh   (or LIVE=1)
#
# LIVE=0: pytest, the Chat 5 step 2 run, protected paths, and the offline tuning
# set checks run locally; the rewrite off/on report prints SKIP.
set -u
source scripts/checks/lib_manifest.sh
source scripts/checks/lib_protected.sh
cd "$(dirname "$0")/../.."

LIVE="${LIVE:-1}"
export LIVE
passes=0
fails=0
QUERIES="eval/datasets/pidgin_tuning_set.yaml"
MD="eval/reports/pidgin_threshold_report.md"
REPORT_JSON="eval/reports/pidgin_threshold_report.json"

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
python3 -m pytest -q >/tmp/pytest_chat5_step3.log 2>&1
pytest_rc=$?
count=$(grep -oE '[0-9]+ passed' /tmp/pytest_chat5_step3.log | head -1 | awk '{print $1}')
count="${count:-0}"
if [ "$pytest_rc" -eq 0 ] && [ "$count" -gt 250 ]; then a_ok=1; else a_ok=0; fi
check "a. Full pytest passes with ${count} tests (> 250)" "$a_ok" "pytest rc=${pytest_rc}, count=${count}"

# --------------------------------------------- b. Chat 5 step 2 (all earlier)
LIVE="$LIVE" bash scripts/checks/check_chat5_step2.sh >/tmp/check_chat5_step2_step3.log 2>&1
b_rc=$?
if [ "$b_rc" -eq 0 ]; then b_ok=1; else b_ok=0; fi
check "b. scripts/checks/check_chat5_step2.sh passes" "$b_ok" "rc=${b_rc}; see /tmp/check_chat5_step2_step3.log"

# --------------------------------- c/d. protected agent files vs both bases
PROT_FILES=(agent/session.py agent/bank_client.py agent/errors.py agent/tool_runtime.py)
if git rev-parse -q --verify chat4-done >/dev/null 2>&1; then
  if git diff --quiet chat4-done -- "${PROT_FILES[@]}" 2>/dev/null; then c_ok=1; else c_ok=0; fi
  check "c. identity/confirmation files unchanged since chat4-done" "$c_ok" \
    "modified: $(git diff --name-only chat4-done -- "${PROT_FILES[@]}" 2>/dev/null | tr '\n' ' ')"
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
  if git diff --quiet --diff-filter=MD "$base3" -- "${PROT_FILES[@]}" 2>/dev/null; then d_ok=1; else d_ok=0; fi
  check "d. identity/confirmation files unmodified since ${base3}" "$d_ok" \
    "modified: $(git diff --name-only --diff-filter=MD "$base3" -- "${PROT_FILES[@]}" 2>/dev/null | tr '\n' ' ')"
fi

# ------------------------------------------------ e. manifest drift (shared lib)
manifest_check "e. manifest drift is only date/tier drift" chat3-done

# ------------------------------------- f. threshold and top_k unchanged
f_out=$(python3 - <<'PY' 2>&1
import subprocess
import yaml

cur = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
head = yaml.safe_load(
    subprocess.run(["git", "show", "HEAD:config/settings.yaml"],
                   capture_output=True, text=True).stdout
)
current = (cur["rag"]["similarity_threshold"], cur["rag"]["top_k"])
baseline = (head["rag"]["similarity_threshold"], head["rag"]["top_k"])
print("SAME" if current == baseline else f"DIFF {current} vs {baseline}")
PY
)
case "$f_out" in
  SAME*) f_ok=1 ;;
  *) f_ok=0 ;;
esac
check "f. rag.similarity_threshold and rag.top_k unchanged since Step 2" "$f_ok" "$f_out"

# --------------------------------- g. offline tuning set shape and ids
g_out=$(python3 - <<'PY' 2>&1
import json
import yaml

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

# ------------------------------------------------- h-l. live comparison
if [ "$LIVE" != "1" ]; then
  for n in \
    "h. report file exists and contains every query" \
    "i. in-scope refused at the current threshold == 0 (rewrite on)" \
    "j. off-topic answered == 0 (rewrite on)" \
    "k. rewrite-on recall@4 >= rewrite-off recall@4"; do
    skip "$n (needs AWS; LIVE=0)"
  done
else
  rm -f "$REPORT_JSON"
  off_out=$(python3 -m rag.threshold_report --queries "$QUERIES" --rewrite off 2>&1)
  off_rc=$?
  printf '%s\n' "$off_out" | sed 's/^/INFO (off): /'
  on_out=$(python3 -m rag.threshold_report --queries "$QUERIES" --rewrite on 2>&1)
  on_rc=$?
  printf '%s\n' "$on_out" | sed 's/^/INFO (on): /'
  if [ "$off_rc" -ne 0 ] || [ "$on_rc" -ne 0 ]; then
    echo "INFO: report generation rc off=${off_rc} on=${on_rc}"
  fi

  live_out=$(QUERIES="$QUERIES" MD="$MD" REPORT_JSON="$REPORT_JSON" python3 - <<'PY' 2>&1
import json
import os
import sys

import yaml

passed = 0
failed = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        print(f"PASS: {name}")
        passed += 1
    else:
        print(f"FAIL: {name} ({detail})")
        failed += 1


md_path = os.environ["MD"]
json_path = os.environ["REPORT_JSON"]
queries = yaml.safe_load(open(os.environ["QUERIES"], encoding="utf-8"))
questions = [e["question"] for e in (queries.get("in_scope") or [])]
questions += [e["question"] for e in (queries.get("out_of_scope") or [])]

try:
    state = json.load(open(json_path, encoding="utf-8"))
    md = open(md_path, encoding="utf-8").read()
except Exception as exc:
    check("h. report file exists and contains every query", False, f"could not read report: {exc}")
    check("i. in-scope refused at the current threshold == 0 (rewrite on)", False, "no report")
    check("j. off-topic answered == 0 (rewrite on)", False, "no report")
    check("k. rewrite-on recall@4 >= rewrite-off recall@4", False, "no report")
    print(f"PYTHON: {passed} passed, {failed} failed")
    sys.exit(1)

missing = [q for q in questions if q not in md]
check("h. report file exists and contains every query", not missing, f"missing {len(missing)}: {missing[:2]}")

modes = state.get("modes", {})
off = modes.get("off", {}).get("summary")
on = modes.get("on", {}).get("summary")
if off and on:
    print(f"INFO: threshold={on['threshold']} top_k={modes['on'].get('top_k')}")
    print(f"INFO: rewrite off: refused {off['in_scope_refused']}/{off['in_scope_total']}, "
          f"off_topic answered {off['off_topic_answered']}/{off['off_topic_total']}, "
          f"recall@4 {off['recall_at_top_k']}/{off['in_scope_total']}, "
          f"top-1 {off['top1_accuracy']}/{off['in_scope_total']}, "
          f"lowest in-scope {off['lowest_in_scope_top1']}, highest off-topic {off['highest_off_topic_top1']}")
    print(f"INFO: rewrite on:  refused {on['in_scope_refused']}/{on['in_scope_total']}, "
          f"off_topic answered {on['off_topic_answered']}/{on['off_topic_total']}, "
          f"recall@4 {on['recall_at_top_k']}/{on['in_scope_total']}, "
          f"top-1 {on['top1_accuracy']}/{on['in_scope_total']}, "
          f"lowest in-scope {on['lowest_in_scope_top1']}, highest off-topic {on['highest_off_topic_top1']}")

refused_ok = bool(on) and on["in_scope_refused"] == 0
if not refused_ok and on:
    print("INFO: rewrite-on in-scope queries refused at the current threshold:")
    threshold = on["threshold"]
    for q in modes["on"]["questions"]:
        if q["group"] == "in_scope" and (q["top1_score"] or 0.0) < threshold:
            print(f"INFO:   original={q['original']!r} rewritten={q['rewritten']!r} "
                  f"top1={q['top1_id']} score={q['top1_score']}")
detail = f"refused={on['in_scope_refused']}/{on['in_scope_total']}" if on else "no on summary"
check("i. in-scope refused at the current threshold == 0 (rewrite on)", refused_ok, detail)

offtopic_ok = bool(on) and on["off_topic_answered"] == 0
if not offtopic_ok and on:
    print("INFO: rewrite-on off-topic queries answered at the current threshold:")
    for q in modes["on"]["questions"]:
        if q.get("kind") == "off_topic" and (q["top1_score"] or 0.0) >= on["threshold"]:
            print(f"INFO:   original={q['original']!r} rewritten={q['rewritten']!r} "
                  f"top1={q['top1_id']} score={q['top1_score']}")
detail = f"answered={on['off_topic_answered']}/{on['off_topic_total']}" if on else "no on summary"
check("j. off-topic answered == 0 (rewrite on)", offtopic_ok, detail)

compare_ok = bool(off and on) and on["recall_at_top_k"] >= off["recall_at_top_k"]
detail = (
    f"on={on['recall_at_top_k']} off={off['recall_at_top_k']}"
    if (off and on) else "missing off or on summary"
)
print(f"INFO: recall@4 on vs off: {detail}; top-1 on vs off: "
      f"{on['top1_accuracy'] if on else '?'} vs {off['top1_accuracy'] if off else '?'}")
check("k. rewrite-on recall@4 >= rewrite-off recall@4", compare_ok, detail)

print(f"PYTHON: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
PY
)
  live_rc=$?
  printf '%s\n' "$live_out"
  live_pass=$(printf '%s\n' "$live_out" | grep -c '^PASS:' || true)
  live_fail=$(printf '%s\n' "$live_out" | grep -c '^FAIL:' || true)
  passes=$((passes + live_pass))
  fails=$((fails + live_fail))
  if [ "$live_rc" -ne 0 ] && [ "$live_fail" -eq 0 ]; then
    echo "FAIL: live rewrite-comparison checks crashed (see output above)"
    fails=$((fails + 1))
  fi
fi

echo "RESULT: $passes passed, $fails failed"
if [ "$fails" -ne 0 ]; then exit 1; fi
exit 0
