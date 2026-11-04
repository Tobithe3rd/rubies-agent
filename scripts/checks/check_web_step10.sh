#!/usr/bin/env bash
# Web session panel (step 10): pytest, then an optional live verify + /session check.
# Usage: bash scripts/checks/check_web_step10.sh          (LIVE=0: tests only)
#        LIVE=1 bash scripts/checks/check_web_step10.sh  (also curl a running adapter)
set -u
cd "$(dirname "$0")/../.."

LIVE="${LIVE:-0}"
HOST="${WEB_HOST:-http://localhost:8002}"
PHONE="${LIVE_PHONE:-+2348031234567}"
OUT=/tmp/check_web_step10_stream.txt
PANEL=/tmp/check_web_step10_panel.json
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
python3 -m pytest tests/adapters/test_web_panel.py -q >/tmp/check_web_step10_pytest.log 2>&1
pytest_rc=$?
if [ "$pytest_rc" -eq 0 ]; then
  check "pytest tests/adapters/test_web_panel.py" 1
else
  check "pytest tests/adapters/test_web_panel.py" 0 "rc=${pytest_rc}; see /tmp/check_web_step10_pytest.log"
fi

if [ "$LIVE" != "1" ]; then
  echo "SKIP: LIVE=0, not curling the session panel"
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

# Ask the agent to send a code; the dev OTP endpoint reads only the dev log.
curl -sN --max-time 90 -X POST -H "Content-Type: application/json" \
  -d "{\"message\":\"Please verify me. My phone number is ${PHONE} and I need a code.\"}" \
  "$HOST/chats/$CHAT_ID/messages/stream" > "$OUT" 2>/dev/null

OTP_LINE=$(curl -sf "$HOST/chats/$CHAT_ID/dev-otp" 2>/dev/null | python3 -c 'import sys,json; print(json.load(sys.stdin).get("otp_line",""))' 2>/dev/null)
OTP=$(printf '%s' "$OTP_LINE" | awk -F', ' '{print $2}')
if [ -z "${OTP:-}" ]; then
  check "read dev OTP" 0 "no OTP line; is allow_dev_otp enabled?"
  echo "RESULT: ${passes} passed, ${fails} failed"
  exit 1
fi
check "read dev OTP" 1

curl -sN --max-time 90 -X POST -H "Content-Type: application/json" \
  -d "{\"message\":\"The code is ${OTP}.\"}" \
  "$HOST/chats/$CHAT_ID/messages/stream" > "$OUT" 2>/dev/null

grep -q '^event: panel' "$OUT"
panel_event_rc=$?
check "panel event on the verifying turn" "$([ "$panel_event_rc" -eq 0 ] && echo 1 || echo 0)"

curl -sf "$HOST/chats/$CHAT_ID/session" > "$PANEL" 2>/dev/null
panel_rc=$?
check "GET /session" "$([ "$panel_rc" -eq 0 ] && echo 1 || echo 0)" "see $PANEL"
if [ "$panel_rc" -ne 0 ]; then
  echo "RESULT: ${passes} passed, ${fails} failed"
  exit 1
fi

verified=$(python3 -c 'import json,sys; print(str(json.load(open(sys.argv[1])).get("verified")).lower())' "$PANEL")
check "panel verified=true" "$([ "$verified" = "true" ] && echo 1 || echo 0)" "got ${verified}"

masked=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("phone_masked") or "")' "$PANEL")
expected_masked="+234 ••• ••• ${PHONE: -4}"
check "panel masked phone" "$([ "$masked" = "$expected_masked" ] && echo 1 || echo 0)" "got '${masked}'"

if grep -Fq "$PHONE" "$PANEL"; then
  check "panel has no full phone number" 0 "found $PHONE"
else
  check "panel has no full phone number" 1
fi

if grep -Eiq 'token|bearer|session_secret' "$PANEL"; then
  check "panel has no token strings" 0 "see $PANEL"
else
  check "panel has no token strings" 1
fi

if grep -Eq 'verify_customer|get_balance|get_mini_statement|get_transaction_status|open_dispute|block_card|check_loan_eligibility|get_loan_status|handoff_to_human|search_policy|confirm_action' "$PANEL"; then
  check "panel has no tool names" 0 "see $PANEL"
else
  check "panel has no tool names" 1
fi

echo "RESULT: ${passes} passed, ${fails} failed"
[ "$fails" -eq 0 ]
