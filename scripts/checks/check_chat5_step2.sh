#!/usr/bin/env bash
# Chat 5 step 2 checks: query rewriting inside the search_policy path.
# Usage: LIVE=0 bash scripts/checks/check_chat5_step2.sh   (or LIVE=1)
#
# LIVE=0: pytest, the Chat 4 acceptance re-run, startup, and the protected-path
# checks run locally; every real-Bedrock rewriter/retrieval check prints SKIP.
set -u
cd "$(dirname "$0")/../.."

LIVE="${LIVE:-1}"
export LIVE
passes=0
fails=0
TOOLLOG=$(mktemp)

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
python3 -m pytest -q >/tmp/pytest_chat5_step2.log 2>&1
pytest_rc=$?
count=$(grep -oE '[0-9]+ passed' /tmp/pytest_chat5_step2.log | head -1 | awk '{print $1}')
count="${count:-0}"
if [ "$pytest_rc" -eq 0 ] && [ "$count" -gt 240 ]; then a_ok=1; else a_ok=0; fi
check "a. Full pytest passes with ${count} tests (> 240)" "$a_ok" "pytest rc=${pytest_rc}, count=${count}"

# ------------------------------------------- b. Chat 4 acceptance (all earlier)
LIVE="$LIVE" bash scripts/checks/check_chat4_step5.sh >/tmp/check_chat4_step5_step5.log 2>&1
b_rc=$?
if [ "$b_rc" -eq 0 ]; then b_ok=1; else b_ok=0; fi
check "b. scripts/checks/check_chat4_step5.sh passes" "$b_ok" "rc=${b_rc}; see /tmp/check_chat4_step5_step5.log"

# --------------------------------------- c. startup names the QueryRewriter impl
startup_out=$(python3 - <<'PY' 2>&1
from core.startup import run_startup
run_startup()
PY
)
if printf '%s' "$startup_out" | grep -q "kind=query_rewriter" \
  && printf '%s' "$startup_out" | grep -q "query rewriter:"; then
  check "c. startup prints the QueryRewriter implementation" 1
else
  check "c. startup prints the QueryRewriter implementation" 0 "banner missing query_rewriter"
fi

# ------------------------------------------- d/e. protected files (agent layer)
PROT_FILES=(agent/session.py agent/bank_client.py agent/errors.py agent/tool_runtime.py)
# Chat 4 built these files, so vs chat3-done only modifications/deletions count;
# vs chat4-done any change counts. tool_runtime.py is not touched by this step,
# which is stronger than only checking its identity/confirmation functions.
if git rev-parse -q --verify chat4-done >/dev/null 2>&1; then
  if git diff --quiet chat4-done -- "${PROT_FILES[@]}" 2>/dev/null; then d_ok=1; else d_ok=0; fi
  check "d. identity/confirmation files unchanged since chat4-done" "$d_ok" \
    "modified: $(git diff --name-only chat4-done -- "${PROT_FILES[@]}" 2>/dev/null | tr '\n' ' ')"
else
  skip "d. identity/confirmation files unchanged since chat4-done (no tag)"
fi

base3="chat3-done"
if ! git rev-parse -q --verify "$base3" >/dev/null 2>&1; then
  base3=$(git log --format=%H --grep='^Chat 3 done' -1 2>/dev/null || true)
fi
if [ -z "${base3:-}" ]; then
  skip "e. identity/confirmation files unmodified since chat3-done (no base ref)"
else
  if git diff --quiet --diff-filter=MD "$base3" -- "${PROT_FILES[@]}" 2>/dev/null; then e_ok=1; else e_ok=0; fi
  check "e. identity/confirmation files unmodified since ${base3}" "$e_ok" \
    "modified: $(git diff --name-only --diff-filter=MD "$base3" -- "${PROT_FILES[@]}" 2>/dev/null | tr '\n' ' ')"
fi

# ------------------------------------------------ f. manifest drift (date/tier)
if [ -z "${base3:-}" ]; then
  skip "f. manifest drift is only date/tier drift (no base ref)"
else
  j2=$(git diff -U0 "$base3" -- data/generated/seed_manifest.md 2>/dev/null | python3 -c '
import sys, re
from collections import defaultdict
raw = [l for l in sys.stdin.read().splitlines() if l[:1] in "+-" and not l.startswith(("+++", "---"))]
removed = [l[1:] for l in raw if l.startswith("-")]
added = [l[1:] for l in raw if l.startswith("+")]
if not removed and not added:
    print("NOCHANGE")
    sys.exit(0)
dr = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
tr = re.compile(r"\btier[0-9]\b")
nd = lambda s: dr.sub("DATE", s)
nt = lambda s: tr.sub("TIER", s)
nb = lambda s: nt(nd(s))
rn = sorted(map(nb, removed))
an = sorted(map(nb, added))
if rn == an:
    gr, ga = defaultdict(list), defaultdict(list)
    for l in removed: gr[nb(l)].append(l)
    for l in added: ga[nb(l)].append(l)
    tier = date = False
    for k in set(gr) | set(ga):
        for r, a in zip(gr[k], ga[k]):
            if r != a:
                if nt(r) == nt(a): tier = True
                elif nd(r) == nd(a): date = True
    if tier: print("INFO: manifest tier drift (KYC tier follows run-day balances)")
    if date: print("INFO: manifest has date-only drift")
    print("PASS")
    sys.exit(0)
for i in range(max(len(rn), len(an))):
    r = rn[i] if i < len(rn) else "<none>"
    a = an[i] if i < len(an) else "<none>"
    if r != a:
        print("FAIL: " + r + "  ->  " + a)
        sys.exit(1)
')
  printf '%s\n' "$j2" | grep '^INFO:' || true
  if printf '%s\n' "$j2" | grep -q '^FAIL:'; then
    check "f. manifest drift is only date/tier drift" 0 "$(printf '%s\n' "$j2" | grep '^FAIL:' | head -1)"
  else
    check "f. manifest drift is only date/tier drift" 1
  fi
fi

# ------------------------------------------------ g-n. live rewriter checks
if [ "$LIVE" != "1" ]; then
  for n in \
    "g. 5 Pidgin queries rewritten: non-empty, one line, short, changed, digits kept" \
    "h. one query_rewrite JSONL line per query with the expected keys" \
    "i. no original or rewritten query text in the info-level JSONL" \
    "j. plain-English query stays one non-empty line" \
    "k. retrieval for the fee question returns RUB-DOC-01#2"; do
    skip "$n (needs AWS; LIVE=0)"
  done
else
  live_out=$(TOOLLOG="$TOOLLOG" python3 - <<'PY' 2>&1
import json
import os
import re
import sys

from agent.tool_logger import JsonlToolLogger
from core.config import load_config
from core.factories import create_llm, create_query_rewriter
from rag.query_rewrite import rewrite_for_search
from rag.search import build_search_policy

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


cfg = load_config(config_dir="config")
tool_log = os.environ["TOOLLOG"]
cfg.settings.logging.tool_log_path = tool_log
qr = cfg.settings.rag.query_rewrite

PIDGIN = [
    "Abeg wetin be the charge for transfer wey pass 50k",
    "My money no gree enter, na 20,000 I send yesterday",
    "How I fit block my card wey I lose?",
    "Wetin be di fee for SMS alert?",
    "I wan know if I qualify for 200k loan",
]
DISTINCTIVE = ["abeg", "gree", "wetin", "qualify", "alert"]

try:
    llm = create_llm(cfg)
    rewriter = create_query_rewriter(cfg, llm)
    logger = JsonlToolLogger(cfg)
except Exception as exc:
    detail = f"{type(exc).__name__}: {exc}"
    for label in (
        "g. 5 Pidgin queries rewritten: non-empty, one line, short, changed, digits kept",
        "h. one query_rewrite JSONL line per query with the expected keys",
        "i. no original or rewritten query text in the info-level JSONL",
        "j. plain-English query stays one non-empty line",
        "k. retrieval for the fee question returns RUB-DOC-01#2",
    ):
        check(label, False, f"setup failed: {detail}")
    print(f"PYTHON: {passed} passed, {failed} failed")
    sys.exit(1)

results = []
problems = []
for query in PIDGIN:
    result = rewrite_for_search(
        query, rewriter=rewriter, logger=logger, session_id="chat5-live", config=cfg
    )
    results.append((query, result))
    if not result.ok:
        problems.append(f"{query!r}: rewrite failed ({result.error})")
        continue
    text = result.rewritten or ""
    if not text.strip():
        problems.append(f"{query!r}: empty")
    if "\n" in text or "\r" in text:
        problems.append(f"{query!r}: more than one line")
    if len(text) > qr.max_output_chars:
        problems.append(f"{query!r}: longer than {qr.max_output_chars}")
    if text.strip() == query.strip():
        problems.append(f"{query!r}: unchanged")
    for digits in re.findall(r"\d+", query):
        if digits not in text:
            problems.append(f"{query!r}: lost digits {digits!r} -> {text!r}")

check(
    "g. 5 Pidgin queries rewritten: non-empty, one line, short, changed, digits kept",
    not problems,
    "; ".join(problems[:4]),
)

try:
    raw = open(tool_log, encoding="utf-8").read().splitlines()
except Exception as exc:
    raw = []
    print(f"INFO: could not read rewrite log: {exc}")

events = []
for line in raw:
    if not line.strip():
        continue
    try:
        payload = json.loads(line)
    except ValueError:
        continue
    if payload.get("event") == "query_rewrite":
        events.append(payload)

required = {
    "time", "event", "session_id", "applied", "ok", "fallback_used",
    "original_len", "rewritten_len", "model_id", "duration_ms", "error",
}
keys_ok = bool(events) and all(required <= set(e) for e in events)
check(
    "h. one query_rewrite JSONL line per query with the expected keys",
    len(events) == len(PIDGIN) and keys_ok,
    f"lines={len(events)} (expected {len(PIDGIN)}) keys_ok={keys_ok}",
)

blob = "\n".join(raw).lower()
leaks = [word for word in DISTINCTIVE if word in blob]
check(
    "i. no original or rewritten query text in the info-level JSONL",
    not leaks,
    f"leaked words: {leaks}",
)

PLAIN = "What is the fee for transfers above ₦50,000?"
plain = rewriter.rewrite(PLAIN)
plain_text = plain.rewritten if plain.ok and plain.rewritten.strip() else PLAIN
check(
    "j. plain-English query stays one non-empty line",
    plain.ok and bool(plain.rewritten.strip()) and "\n" not in plain.rewritten,
    f"ok={plain.ok} rewritten={plain.rewritten!r} error={plain.error}",
)

policy = build_search_policy(cfg)(plain_text)
top = (policy.results[0]["chunk_id"] if policy.results else None)
check(
    "k. retrieval for the fee question returns RUB-DOC-01#2",
    policy.status == "ok" and top == "RUB-DOC-01#2",
    f"status={policy.status} top={top}",
)

for query, result in results:
    print(f"INFO: rewrite {query!r} -> {result.rewritten!r} (applied={result.applied})")
print(f"INFO: expected chunk id comes from the Chat 3 dev set (transfer fee = RUB-DOC-01#2)")

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
    echo "FAIL: live query-rewrite checks crashed (see output above)"
    fails=$((fails + 1))
  fi
fi

echo "RESULT: $passes passed, $fails failed"
if [ "$fails" -ne 0 ]; then exit 1; fi
exit 0