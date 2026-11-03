#!/usr/bin/env bash
# Web transcript history (step 12): pytest, then optional live curl checks.
# Usage: bash scripts/checks/check_web_step12.sh          (LIVE=0: tests only)
#        LIVE=1 bash scripts/checks/check_web_step12.sh  (also curl a running adapter)
set -u
cd "$(dirname "$0")/../.."

LIVE="${LIVE:-0}"
HOST="${WEB_HOST:-http://localhost:8002}"
HISTORY=/tmp/check_web_step12_history.json
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
python3 -m pytest tests/adapters/test_web_history.py -q >/tmp/check_web_step12_pytest.log 2>&1
pytest_rc=$?
if [ "$pytest_rc" -eq 0 ]; then
  check "pytest tests/adapters/test_web_history.py" 1
else
  check "pytest tests/adapters/test_web_history.py" 0 "rc=${pytest_rc}; see /tmp/check_web_step12_pytest.log"
fi

if [ "$LIVE" != "1" ]; then
  echo "SKIP: LIVE=0, not curling the transcript history route"
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

curl -sf --max-time 120 -X POST -H "Content-Type: application/json" \
  -d '{"message":"What are your transfer fees?"}' \
  "$HOST/chats/${CHAT_ID}/messages" >/tmp/check_web_step12_reply.json 2>/dev/null
reply_rc=$?
check "send a message" "$([ "$reply_rc" -eq 0 ] && echo 1 || echo 0)" "see /tmp/check_web_step12_reply.json"

curl -sf "$HOST/chats/${CHAT_ID}/history" > "$HISTORY" 2>/dev/null
hist_rc=$?
if [ "$hist_rc" -ne 0 ]; then
  check "GET /history" 0 "see $HISTORY"
  echo "RESULT: ${passes} passed, ${fails} failed"
  exit 1
fi
check "GET /history" 1

user_ok=$(python3 - "$HISTORY" <<'PY'
import json, sys
data = json.load(open(sys.argv[1]))
messages = data.get("messages") or []
first = messages[0] if messages else {}
agent = messages[1] if len(messages) > 1 else {}
ok = first.get("role") == "user" and bool(first.get("text")) \
    and agent.get("role") == "agent" and bool(agent.get("events")) \
    and "panel" in data
print("1" if ok else "0")
PY
)
check "history has user and agent items plus panel" "$user_ok"

if grep -Eq 'verify_customer|get_balance|get_mini_statement|get_transaction_status|open_dispute|block_card|check_loan_eligibility|get_loan_status|handoff_to_human|search_policy|confirm_action' "$HISTORY"; then
  check "history has no tool names" 0 "see $HISTORY"
else
  check "history has no tool names" 1
fi

if grep -Eiq 'token|bearer|session_secret' "$HISTORY"; then
  check "history has no token strings" 0 "see $HISTORY"
else
  check "history has no token strings" 1
fi

curl -sf -X DELETE "$HOST/chats/${CHAT_ID}" >/dev/null 2>&1
delete_rc=$?
check "DELETE chat" "$([ "$delete_rc" -eq 0 ] && echo 1 || echo 0)"

after=$(curl -s -o /dev/null -w '%{http_code}' "$HOST/chats/${CHAT_ID}/history" 2>/dev/null)
check "history is 404 after DELETE" "$([ "$after" = "404" ] && echo 1 || echo 0)" "got ${after}"

echo "RESULT: ${passes} passed, ${fails} failed"
[ "$fails" -eq 0 ]
