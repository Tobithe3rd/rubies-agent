#!/usr/bin/env bash
# Step 12b: phone validation and honest request-otp wording.
# Usage: bash scripts/checks/check_web_step12b.sh          (pytest only)
#        LIVE=1 bash scripts/checks/check_web_step12b.sh  (also curl the bank API)
set -u
cd "$(dirname "$0")/../.."

LIVE="${LIVE:-0}"
PORT="${BANK_API_PORT:-8001}"
BASE="${BANK_API_URL:-http://127.0.0.1:${PORT}}"
passes=0
fails=0
STARTED=0
API_PID=""
KNOWN="+2348031234567"
UNKNOWN="+2349999999999"

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

cleanup() {
  if [ "$STARTED" = "1" ] && [ -n "$API_PID" ]; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# ---------------------------------------------------------------- pytest
python3 -m pytest -q >/tmp/check_web_step12b_pytest.log 2>&1
pytest_rc=$?
check "full pytest -q" "$([ "$pytest_rc" -eq 0 ] && echo 1 || echo 0)" \
  "rc=${pytest_rc}; see /tmp/check_web_step12b_pytest.log"

if [ "$LIVE" != "1" ]; then
  echo "SKIP: LIVE=0, not curling the bank API"
  echo "RESULT: ${passes} passed, ${fails} failed"
  [ "$fails" -eq 0 ]
  exit $?
fi

# ---------------------------------------------------------------- live curl
if ! python3 -m bank_api.seed >/tmp/check_web_step12b_seed.log 2>&1; then
  check "seed bank data" 0 "see /tmp/check_web_step12b_seed.log"
fi

http_code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health" 2>/dev/null || true)
if [ "$http_code" != "200" ]; then
  python3 -m uvicorn bank_api.main:create_app --factory --host 127.0.0.1 --port "$PORT" \
    >/tmp/check_web_step12b_api.log 2>&1 &
  API_PID=$!
  STARTED=1
  http_code=""
  for _ in $(seq 1 40); do
    http_code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health" 2>/dev/null || true)
    if [ "$http_code" = "200" ]; then break; fi
    sleep 0.5
  done
fi
check "bank API is up on $BASE" "$([ "$http_code" = "200" ] && echo 1 || echo 0)" \
  "health=${http_code:-none}; see /tmp/check_web_step12b_api.log"

malformed_code=$(curl -s -o /tmp/check_web_step12b_malformed.json -w '%{http_code}' \
  -X POST -H 'Content-Type: application/json' \
  -d '{"phone":"abc"}' "$BASE/auth/request-otp" 2>/dev/null)
malformed_body=$(cat /tmp/check_web_step12b_malformed.json 2>/dev/null || true)
if [ "$malformed_code" = "422" ] && printf '%s' "$malformed_body" | grep -q 'invalid_phone_format'; then
  check "malformed phone gives 422 invalid_phone_format" 1
else
  check "malformed phone gives 422 invalid_phone_format" 0 \
    "got ${malformed_code:-none}: ${malformed_body}"
fi

known_code=$(curl -s -o /tmp/check_web_step12b_known.json -w '%{http_code}' \
  -X POST -H 'Content-Type: application/json' \
  -d "{\"phone\":\"$KNOWN\"}" "$BASE/auth/request-otp" 2>/dev/null)
unknown_code=$(curl -s -o /tmp/check_web_step12b_unknown.json -w '%{http_code}' \
  -X POST -H 'Content-Type: application/json' \
  -d "{\"phone\":\"$UNKNOWN\"}" "$BASE/auth/request-otp" 2>/dev/null)
if [ "$known_code" = "200" ] && [ "$unknown_code" = "200" ] \
  && cmp -s /tmp/check_web_step12b_known.json /tmp/check_web_step12b_unknown.json; then
  check "known and unknown well-formed numbers give identical bodies" 1
else
  check "known and unknown well-formed numbers give identical bodies" 0 \
    "known=${known_code}:$(cat /tmp/check_web_step12b_known.json 2>/dev/null) unknown=${unknown_code}:$(cat /tmp/check_web_step12b_unknown.json 2>/dev/null)"
fi

echo "RESULT: ${passes} passed, ${fails} failed"
[ "$fails" -eq 0 ]
