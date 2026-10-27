#!/bin/bash
B=localhost:8001
DB=data/bank.db
q() { sqlite3 -batch -list -noheader "$DB" "$1"; }
ok=0; bad=0
check() { if [ "$2" = "$3" ]; then echo "PASS  $1"; ok=$((ok+1)); else echo "FAIL  $1 (expected '$3', got '$2')"; bad=$((bad+1)); fi; }
rej() { case "$1" in 400|422) echo reject;; *) echo "$1";; esac; }
post() { curl -s -o /tmp/resp.json -w '%{http_code}' -X POST $B/handoff -H 'content-type: application/json' "${@:2}" -d "$1"; }

echo "== pytest"; pytest -q 2>&1 | tail -2

[ "$(curl -s -o /dev/null -w '%{http_code}' $B/health)" = "200" ] || { echo "API not running on $B"; exit 1; }

# log in as Bola (customer 5)
PHONE="+2348115678901"
curl -s -X POST $B/auth/request-otp -H 'content-type: application/json' -d "{\"phone\":\"$PHONE\"}" > /dev/null
CODE=$(grep -F "$PHONE" logs/otp.log | tail -1 | cut -d, -f2 | tr -d ' ')
TOKEN=$(curl -s -X POST $B/auth/verify -H 'content-type: application/json' -d "{\"phone\":\"$PHONE\",\"code\":\"$CODE\"}" | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

SUM='Customer is angry and wants a manager about a double debit of ₦25,000. Code 482915.'

echo "== no session"
code=$(post "{\"summary\":\"$SUM\",\"reason\":\"upset_user\"}")
check "returns 200" "$code" 200
ID=$(python3 -c "import json;print(json.load(open('/tmp/resp.json'))['ticket_id'])")
check "customer_id is NULL" "$(q "select coalesce(customer_id,'NULL') from handoff_tickets where id=$ID")" NULL
check "6-digit code redacted" "$(q "select instr(summary,'482915') from handoff_tickets where id=$ID")" 0
check "naira amount intact" "$(q "select instr(summary,'25,000')>0 from handoff_tickets where id=$ID")" 1
check "reason stored" "$(q "select reason from handoff_tickets where id=$ID")" upset_user

echo "== valid session (Bola = customer 5)"
code=$(post "{\"summary\":\"Customer asked for a human agent.\",\"reason\":\"user_requested\"}" -H "Authorization: Bearer $TOKEN")
check "returns 200" "$code" 200
ID=$(python3 -c "import json;print(json.load(open('/tmp/resp.json'))['ticket_id'])")
check "customer_id from session" "$(q "select customer_id from handoff_tickets where id=$ID")" 5

echo "== garbage token"
code=$(post "{\"summary\":\"Verification failed three times.\",\"reason\":\"failed_verification\"}" -H "Authorization: Bearer not-a-real-token")
check "still returns 200" "$code" 200
ID=$(python3 -c "import json;print(json.load(open('/tmp/resp.json'))['ticket_id'])")
check "customer_id is NULL" "$(q "select coalesce(customer_id,'NULL') from handoff_tickets where id=$ID")" NULL

echo "== rejected inputs (expect 4xx)"
code=$(post '{"summary":"x","reason":"banana"}'); check "unknown reason" "$(rej $code)" reject
code=$(post '{"summary":"x","reason":"other","customer_id":1}'); check "customer_id in body" "$(rej $code)" reject
code=$(post '{"summary":"   ","reason":"other"}'); check "empty summary" "$(rej $code)" reject

echo "== audit"
check "audit rows exist" "$(q "select count(*)>0 from audit_log where action like '%handoff%'")" 1

echo; echo "RESULT: $ok passed, $bad failed"
