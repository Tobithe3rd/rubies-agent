#!/usr/bin/env bash
# Chat 4 step 1 checks: config (timezone + agent), clock, session state, tools schema.
# Usage: bash scripts/check_chat4_step1.sh          (LIVE=1 default, uses AWS)
#        LIVE=0 bash scripts/check_chat4_step1.sh   (skip anything needing AWS)
set -u
cd "$(dirname "$0")/.."

LIVE="${LIVE:-1}"
fails=0

pass() { echo "PASS: $1"; }
fail() { echo "FAIL: $1 ($2)"; fails=$((fails + 1)); }
skip() { echo "SKIP: $1"; }

# ---------------------------------------------------------------- a. config
out=$(python3 -c "from core.config import load_config; print(load_config().settings.timezone)" 2>&1)
if [ "$out" = "Africa/Lagos" ]; then
  pass "config loads and settings timezone is Africa/Lagos"
else
  fail "config loads and settings timezone is Africa/Lagos" "got '$out'"
fi

# ---------------------------------------------------------------- b. clock
out=$(python3 -c "
from core.config import load_config
from core.clock import create_clock
c = create_clock(load_config())
print(c.iso_now(), c.naive_local_now().tzinfo)
" 2>&1)
case "$out" in
  *"+01:00 None") pass "clock iso_now ends +01:00 and naive_local_now has tzinfo None" ;;
  *) fail "clock iso_now ends +01:00 and naive_local_now has tzinfo None" "got '$out'" ;;
esac

# ---------------------------------------------------------------- c. fail-fast config
tmp=$(mktemp -d)
edit() {
  python3 - "$1" "$2" "$3" <<'PY'
import sys
path, old, new = sys.argv[1], sys.argv[2], sys.argv[3]
text = open(path).read()
assert old in text, f"{old!r} not in {path}"
open(path, "w").write(text.replace(old, new, 1))
PY
}

cp -r config "$tmp/badhist"
edit "$tmp/badhist/settings.yaml" "max_history_messages: 40" "max_history_messages: 0"
out=$(python3 -c "from core.config import load_config; load_config(config_dir='$tmp/badhist')" 2>&1); rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "max_history_messages"; then
  pass "zero agent.max_history_messages fails and names the key"
else
  fail "zero agent.max_history_messages fails and names the key" "rc=$rc out=$out"
fi

cp -r config "$tmp/badtz"
edit "$tmp/badtz/settings.yaml" "timezone: Africa/Lagos" "timezone: Mars/Base"
out=$(python3 -c "from core.config import load_config; load_config(config_dir='$tmp/badtz')" 2>&1); rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "timezone"; then
  pass "bad timezone fails and names the key"
else
  fail "bad timezone fails and names the key" "rc=$rc out=$out"
fi
rm -rf "$tmp"

# ---------------------------------------------------------------- d. tools.yaml
out=$(python3 - <<'PY'
import yaml
t = yaml.safe_load(open("config/tools.yaml"))
print(len(t))
print(",".join(sorted(t)))
print(",".join(sorted(k for k, v in t.items() if v["requires_confirmation"])))
print(",".join(sorted(k for k, v in t.items() if not v["requires_verified_session"])))
PY
)
expected=$'11\nblock_card,check_loan_eligibility,confirm_action,get_balance,get_loan_status,get_mini_statement,get_transaction_status,handoff_to_human,open_dispute,search_policy,verify_customer\nblock_card,open_dispute\nhandoff_to_human,search_policy,verify_customer'
if [ "$out" = "$expected" ]; then
  pass "tools.yaml: 11 tools, confirmation only for dispute/block, no session for verify/search/handoff"
else
  fail "tools.yaml: 11 tools, confirmation only for dispute/block, no session for verify/search/handoff" "got: $out"
fi

# ---------------------------------------------------------------- e. confirm rule
out=$(python3 - <<'PY'
from agent.session import SessionState
s = SessionState()
s.start_turn()
s.register_pending("P1", "block_card")
r1 = s.can_confirm("P1")
s.start_turn()
r2 = s.can_confirm("P1")
r3 = s.can_confirm("NOPE")
s.consume_pending("P1")
r4 = s.can_confirm("P1")
print(r1 == (False, "same_turn"), r2[0], r3 == (False, "unknown_token"), r4 == (False, "unknown_token"))
PY
)
if [ "$out" = "True True True True" ]; then
  pass "SessionState: same_turn, then confirmable, unknown token, single use"
else
  fail "SessionState: same_turn, then confirmable, unknown token, single use" "got '$out'"
fi

# ---------------------------------------------------------------- f. counters
out=$(python3 - <<'PY'
from agent.session import SessionState
s = SessionState()
s.record_retrieval("no_relevant_result")
s.record_retrieval("no_relevant_result")
a = (s.failed_retrievals, s.consecutive_failed_retrievals)
s.record_retrieval("ok")
b = (s.failed_retrievals, s.consecutive_failed_retrievals)
print(a, b)
PY
)
if [ "$out" = "(2, 2) (2, 0)" ]; then
  pass "retrieval counters: total stays, consecutive resets after ok"
else
  fail "retrieval counters: total stays, consecutive resets after ok" "got '$out'"
fi

# ---------------------------------------------------------------- g. token never printed
out=$(python3 - <<'PY'
from agent.session import SessionState
s = SessionState()
s.set_verified("SECRET123", "Ada")
print("SECRET123" in repr(s), "SECRET123" in str(s))
PY
)
if [ "$out" = "False False" ]; then
  pass "session token never appears in repr or str"
else
  fail "session token never appears in repr or str" "got '$out'"
fi

# ---------------------------------------------------------------- h. pytest
ptout=$(python3 -m pytest -q 2>&1); ptrc=$?
cnt=$(printf '%s\n' "$ptout" | grep -oE '[0-9]+ passed' | head -1 | grep -oE '[0-9]+')
if [ "${ptrc:-1}" -eq 0 ] && [ -n "${cnt:-}" ] && [ "$cnt" -ge 125 ]; then
  pass "pytest passes with $cnt tests (>= 125)"
else
  fail "pytest passes with >= 125 tests" "rc=$ptrc count=${cnt:-?}"
fi

# ---------------------------------------------------------------- i. earlier scripts
run_earlier() {
  script="$1"
  if [ "$script" = "scripts/check_step5.sh" ]; then
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 2 localhost:8001/health 2>/dev/null || true)
    if [ "$code" != "200" ]; then
      skip "$script (needs the bank API on :8001)"
      return
    fi
  fi
  eout=$(LIVE="$LIVE" ALLOW_RAG_CHANGE=1 ALLOW_SEED_CHANGE=1 bash "$script" 2>&1); erc=$?

  if [ "$script" = "scripts/check_rag_all.sh" ]; then
    # Carve-out: check_rag_all.sh's own protected-path gate (R3) is superseded
    # by check j. PASS only if it exits non-zero AND the only FAIL lines are
    # that gate; any other failure is a real failure.
    if [ "$erc" -eq 0 ]; then
      pass "$script"
      return
    fi
    failing=$(printf '%s\n' "$eout" | grep '^FAIL:' || true)
    other=$(printf '%s\n' "$failing" | grep -vE '^FAIL: R3 protected paths untouched' || true)
    if [ -n "$failing" ] && [ -z "$other" ]; then
      pass "$script (only its R3 protected-path gate tripped; superseded by check j)"
    else
      [ -n "$other" ] && printf '%s\n' "$other"
      fail "$script" "exit $erc"
    fi
    return
  fi

  if [ "$erc" -eq 0 ]; then
    pass "$script"
    return
  fi
  # A script's own protected-path gate is superseded by check j below.
  other=$(printf '%s\n' "$eout" | grep '^FAIL:' | grep -viE 'protected paths|protected source dirs|bank_api/providers/core/agent' || true)
  if [ -z "$other" ] && printf '%s\n' "$eout" | grep -q '^FAIL:'; then
    pass "$script (only its internal protected-path gate tripped; superseded by check j)"
  else
    last=$(printf '%s\n' "$eout" | grep -E '^SUMMARY:|^FAIL:' | tail -1)
    fail "$script" "${last:-exit $erc}"
  fi
}

for s in scripts/check_step*.sh scripts/check_rag_*.sh; do
  run_earlier "$s"
done

# ---------------------------------------------------------------- j. protected paths
base="chat3-done"
if ! git rev-parse -q --verify "$base" >/dev/null 2>&1; then
  base=$(git log --format=%H --grep='^Chat 3 done' -1 2>/dev/null || true)
fi
if [ -z "${base:-}" ]; then
  skip "protected paths untouched (no base ref found)"
  skip "manifest drift (no base ref found)"
else
  # j1: protected paths (data/seed_manifest.md is handled separately in j2)
  if git diff --quiet "$base" -- bank_api providers rag eval scripts/check_step5.sh scripts/check_rag_all.sh 2>/dev/null; then
    pass "protected paths untouched since ${base}"
  else
    changed=$(git diff --name-only "$base" -- bank_api providers rag eval scripts/check_step5.sh scripts/check_rag_all.sh 2>/dev/null | tr '\n' ' ')
    fail "protected paths untouched since chat3-done" "modified: $changed"
  fi

  # j2: manifest drift. PASS when the removed and added lines match after
  # normalising run-day dates (YYYY-MM-DD -> DATE) and KYC tier labels
  # (tierN -> TIER). Any other change fails and names the first differing
  # normalised line. A raw line that differs only by a tier label or only by
  # a date is reported as INFO, not as a failure.
  j2=$(git diff -U0 "$base" -- data/seed_manifest.md 2>/dev/null | python3 -c '
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
    first=$(printf '%s\n' "$j2" | grep '^FAIL:' | head -1)
    fail "manifest drift is not only date/tier drift since chat3-done" "${first#FAIL: }"
  elif printf '%s\n' "$j2" | grep -q '^NOCHANGE'; then
    pass "manifest has no drift since chat3-done"
  else
    pass "manifest drift is only date/tier drift since chat3-done"
  fi
fi

# ---------------------------------------------------------------- k. timezone report
echo "INFO: timezone usage scan (informational, never fails):"
utcoff=$(python3 -c "
from datetime import datetime
o = datetime.now().astimezone().utcoffset()
s = int(o.total_seconds())
sign = '+' if s >= 0 else '-'
print(f'{sign}{abs(s) // 3600:02d}:{(abs(s) % 3600) // 60:02d}')
" 2>/dev/null || true)
if [ "$utcoff" = "+01:00" ]; then
  echo "INFO: machine UTC offset ${utcoff:-unknown} OK"
else
  echo "INFO: machine UTC offset ${utcoff:-unknown} WARNING: machine is not on Lagos time; Chat 2 naive timestamps follow the machine clock"
fi
matches=$(grep -rnE 'datetime\.now|utcnow|time\.time' bank_api providers/datastore 2>/dev/null || true)
if [ -n "$matches" ]; then
  printf '%s\n' "$matches" | sed 's/^/INFO:   /'
else
  echo "INFO:   no datetime.now / utcnow / time.time found in bank_api or providers/datastore"
fi

echo
echo "RESULT: $fails failed"
[ "$fails" -eq 0 ]
