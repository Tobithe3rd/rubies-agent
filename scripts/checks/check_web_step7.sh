#!/usr/bin/env bash
# Web stream (step 7): SSE tests, then an optional live curl of the stream route.
# Usage: bash scripts/checks/check_web_step7.sh          (LIVE=0: tests only)
#        LIVE=1 bash scripts/checks/check_web_step7.sh  (also curl a running adapter)
set -u
cd "$(dirname "$0")/../.."

LIVE="${LIVE:-0}"
HOST="${WEB_HOST:-http://localhost:8002}"
OUT=/tmp/check_web_step7_stream.txt
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

# ---------------------------------------------------------------- pytest
python3 -m pytest tests/adapters/test_web_stream.py -q >/tmp/check_web_step7_pytest.log 2>&1
pytest_rc=$?
if [ "$pytest_rc" -eq 0 ]; then
  check "pytest tests/adapters/test_web_stream.py" 1
else
  check "pytest tests/adapters/test_web_stream.py" 0 "rc=${pytest_rc}; see /tmp/check_web_step7_pytest.log"
fi

if [ "$LIVE" != "1" ]; then
  echo "SKIP: LIVE=0, not curling the stream route"
  echo "RESULT: ${passes} passed, ${fails} failed"
  [ "$fails" -eq 0 ]
  exit $?
fi

# ---------------------------------------------------------------- live curl
CHAT_ID=$(curl -sf -X POST "$HOST/chats" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("chat_id",""))' 2>/dev/null)
if [ -z "${CHAT_ID:-}" ]; then
  check "create chat" 0 "POST $HOST/chats failed"
  echo "RESULT: ${passes} passed, ${fails} failed"
  exit 1
fi
check "create chat" 1

curl -sN --max-time 90 -X POST -H "Content-Type: application/json" \
  -d '{"message":"What are the fees for transfers?"}' \
  "$HOST/chats/$CHAT_ID/messages/stream" > "$OUT" 2>/dev/null

grep -q '^event: step' "$OUT"
step_rc=$?
check "step event present" "$([ "$step_rc" -eq 0 ] && echo 1 || echo 0)"

text_count=$(grep -c '^event: text' "$OUT" || true)
[ "${text_count:-0}" -ge 2 ]
text_rc=$?
check "at least 2 text events (got ${text_count:-0})" "$([ "$text_rc" -eq 0 ] && echo 1 || echo 0)"

grep -q '^event: done' "$OUT"
done_rc=$?
check "done event present" "$([ "$done_rc" -eq 0 ] && echo 1 || echo 0)"

if grep -Eq 'verify_customer|get_balance|get_mini_statement|get_transaction_status|open_dispute|block_card|check_loan_eligibility|get_loan_status|handoff_to_human|search_policy|confirm_action|\[using tool' "$OUT"; then
  check "no tool names in the output" 0 "found in $OUT"
else
  check "no tool names in the output" 1
fi

echo "RESULT: ${passes} passed, ${fails} failed"
[ "$fails" -eq 0 ]
