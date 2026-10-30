#!/usr/bin/env bash
# Chat 4 step 2 checks: agent-side bank client over the real API.
# Usage: LIVE=0 bash scripts/checks/check_chat4_step2.sh   (or LIVE=1)
#
# LIVE=0: no check in this script needs AWS. Checks a-j are local HTTP/SQLite
# checks against the mock bank API. The earlier scripts reached through
# check_chat4_step1.sh handle their own LIVE gating and print their own SKIPs.
set -u
cd "$(dirname "$0")/../.."

LIVE="${LIVE:-1}"
export LIVE

PORT="${BANK_API_PORT:-8001}"
BASE="http://127.0.0.1:${PORT}"
STARTED=0
API_PID=""
passes=0
fails=0

cleanup() {
  if [ "$STARTED" = "1" ] && [ -n "$API_PID" ]; then
    kill "$API_PID" 2>/dev/null || true
    wait "$API_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

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

# --- fresh reset + seed (works while the API is running) ---
if ! python3 -m bank_api.seed >/tmp/seed_step2.log 2>&1; then
  echo "FAIL: seed fresh data (see /tmp/seed_step2.log)"
  fails=$((fails + 1))
  echo "RESULT: $passes passed, $fails failed"
  exit 1
fi
echo "INFO: seeded fresh data"

# --- ensure the real bank API is running ---
http_code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health" 2>/dev/null || true)
if [ "$http_code" = "200" ]; then
  echo "INFO: using running bank API on $BASE"
else
  python3 -m uvicorn bank_api.main:create_app --factory --host 127.0.0.1 --port "$PORT" \
    >/tmp/bank_api_step2.log 2>&1 &
  API_PID=$!
  STARTED=1
  code=""
  for _ in $(seq 1 40); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health" 2>/dev/null || true)
    if [ "$code" = "200" ]; then break; fi
    sleep 0.5
  done
  if [ "$code" != "200" ]; then
    echo "FAIL: bank API did not start on $BASE (see /tmp/bank_api_step2.log)"
    fails=$((fails + 1))
    echo "RESULT: $passes passed, $fails failed"
    exit 1
  fi
  echo "INFO: started bank API on $BASE"
fi

# --- k. full pytest (before the a-j checks, so pytest sees the fresh seed) ---
python3 -m pytest -q >/tmp/pytest_step2.log 2>&1
pytest_rc=$?
count=$(grep -oE '[0-9]+ passed' /tmp/pytest_step2.log | head -1 | awk '{print $1}')
count="${count:-0}"
if [ "$pytest_rc" -eq 0 ] && [ "$count" -gt 148 ]; then k_ok=1; else k_ok=0; fi
check "k. Full pytest passes with ${count} tests (> 148)" "$k_ok" "pytest rc=${pytest_rc}, count=${count}"

# --- a-j: real client checks over HTTP ---
py_out=$(BANK_API_URL="$BASE" python3 - <<'PY' 2>&1
import inspect
import sqlite3
import sys
import time
from types import SimpleNamespace

from core.config import load_config
from core.factories import create_bank_gateway
from agent.bank_client import HttpBankGateway
from agent.errors import BankNotFound, BankRejected, BankUnauthorized, BankUnavailable

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


cfg = load_config()
db_path = cfg.settings.bank_api.db_path
otp_log = cfg.settings.bank_api.otp_log_path
timeout = cfg.settings.agent.bank_api_timeout_seconds

conn = sqlite3.connect(db_path)
gw = create_bank_gateway(cfg)


def read_otp(phone):
    lines = [l for l in open(otp_log).read().splitlines() if l.startswith(phone)]
    if not lines:
        raise RuntimeError(f"no OTP log line for {phone}")
    return lines[-1].split(",")[1].strip()


def verify(phone):
    gw.verify_start(phone)
    return gw.verify_complete(phone, read_otp(phone))["token"]


def dispute_count(reference):
    return conn.execute(
        "select count(*) from disputes d join transactions t on t.id=d.transaction_id "
        "where t.reference=?",
        (reference,),
    ).fetchone()[0]


def pending_count(phone):
    return conn.execute(
        "select count(*) from pending_actions p join customers c on c.id=p.customer_id "
        "where c.phone=? and p.action_type='dispute' and p.used=0",
        (phone,),
    ).fetchone()[0]


def card_status(phone, last4):
    row = conn.execute(
        "select c.status from cards c join customers cu on cu.id=c.customer_id "
        "where cu.phone=? and c.last4=?",
        (phone, last4),
    ).fetchone()
    return row[0] if row else None


adebayo = "+2348031234567"
bola = "+2348115678901"
fatima = "+2348093456789"

try:
    # a. full verify + wrong OTP
    gw.verify_start(adebayo)
    adebayo_otp = read_otp(adebayo)
    wrong = "000000" if adebayo_otp != "000000" else "111111"
    a_ok = False
    a_detail = ""
    try:
        gw.verify_complete(adebayo, wrong)
    except BankUnauthorized as exc:
        a_ok = exc.status_code == 401 and wrong not in str(exc) and wrong not in repr(exc)
        a_detail = f"expected BankUnauthorized(401); got {exc.status_code} {exc.code}"
    except BankRejected as exc:
        a_detail = f"expected BankUnauthorized; got BankRejected({exc.status_code})"
    except Exception as exc:
        a_detail = f"unexpected {type(exc).__name__}: {exc}"
    else:
        a_detail = "wrong OTP did not raise"
    adebayo_token = gw.verify_complete(adebayo, adebayo_otp).get("token")
    check(
        "a. verify full flow and wrong OTP",
        a_ok and bool(adebayo_token),
        a_detail if not a_ok else "missing token",
    )

    # b. balance matches SQLite
    expected_balance = conn.execute(
        "select a.balance_kobo from customers c join accounts a on a.customer_id=c.id "
        "where c.phone=?",
        (adebayo,),
    ).fetchone()[0]
    actual_balance = gw.get_balance(adebayo_token).get("balance_kobo")
    check(
        "b. get_balance matches SQLite",
        actual_balance == expected_balance,
        f"expected {expected_balance}, got {actual_balance}",
    )

    # c. Bola mini statement contains double debit
    bola_token = verify(bola)
    stmt = gw.get_mini_statement(bola_token, limit=50)
    by_ref = {t.get("reference"): t for t in stmt.get("transactions", [])}
    c_ok = (
        "RUB-DB-001" in by_ref
        and "RUB-DB-002" in by_ref
        and by_ref["RUB-DB-001"].get("amount_naira") == 25000.0
        and by_ref["RUB-DB-002"].get("amount_naira") == 25000.0
    )
    check(
        "c. mini statement contains double debit",
        c_ok,
        "missing RUB-DB-001/002 or amount != 25000",
    )

    # d. Fatima failed transfer
    fatima_token = verify(fatima)
    txn = gw.get_transaction_status(fatima_token, "RUB-03-000037")
    check(
        "d. transaction status failed amount",
        txn.get("status") == "failed" and txn.get("amount_naira") == 50000.0,
        f"status={txn.get('status')} amount={txn.get('amount_naira')}",
    )

    # e. cross-customer isolation
    e_ok = False
    e_detail = ""
    try:
        gw.get_transaction_status(adebayo_token, "RUB-03-000037")
    except BankNotFound as exc:
        text = (str(exc) + repr(exc)).lower()
        e_ok = exc.status_code == 404 and "amount" not in text and "50000" not in text
        e_detail = f"expected BankNotFound(404); got {exc.status_code} {exc.code}"
    except Exception as exc:
        e_detail = f"unexpected {type(exc).__name__}: {exc}"
    else:
        e_detail = "cross-customer lookup did not raise"
    try:
        gw.get_balance("not-a-real-token")
    except BankUnauthorized as exc:
        e_ok = e_ok and exc.status_code == 401
        e_detail = e_detail if e_ok else f"made-up token: expected 401, got {exc.status_code}"
    except Exception as exc:
        e_ok = False
        e_detail = f"made-up token: unexpected {type(exc).__name__}"
    else:
        e_ok = False
        e_detail = "made-up token did not raise"
    check("e. cross-customer isolation", e_ok, e_detail)

    # f. dispute two-step on Bola
    before = dispute_count("RUB-DB-002")
    propose = gw.propose_dispute(bola_token, "RUB-DB-002", "double debit")
    pending = propose.get("pending_token")
    pending_rows = pending_count(bola)
    after_propose = dispute_count("RUB-DB-002")
    confirm = gw.confirm_action(bola_token, pending) if pending else {}
    after_confirm = dispute_count("RUB-DB-002")
    used = conn.execute(
        "select p.used from pending_actions p join customers c on c.id=p.customer_id "
        "where c.phone=? and p.action_type='dispute' order by p.id desc limit 1",
        (bola,),
    ).fetchone()
    second_ok = False
    second_detail = ""
    if pending:
        try:
            gw.confirm_action(bola_token, pending)
        except BankRejected as exc:
            second_ok = exc.status_code == 400
            second_detail = f"expected BankRejected(400); got {exc.status_code} {exc.code}"
        except Exception as exc:
            second_detail = f"unexpected {type(exc).__name__}: {exc}"
        else:
            second_detail = "second confirm did not raise"
    after_second = dispute_count("RUB-DB-002")
    f_ok = (
        bool(pending)
        and before == 0
        and pending_rows >= 1
        and after_propose == 0
        and confirm.get("status") == "dispute_opened"
        and after_confirm == 1
        and bool(used) and used[0] == 1
        and second_ok
        and after_second == 1
    )
    f_detail = (
        f"pending={bool(pending)} before={before} pending_rows={pending_rows} "
        f"after_propose={after_propose} confirm={confirm.get('status')} "
        f"after_confirm={after_confirm} used={used[0] if used else None} "
        f"second={second_detail} after_second={after_second}"
    )
    check("f. dispute two-step", f_ok, f_detail)

    # g. pending token bound to session
    propose_g = gw.propose_dispute(bola_token, "RUB-DB-001", "double debit")
    pending_g = propose_g.get("pending_token")
    g_ok = False
    g_detail = ""
    if pending_g:
        try:
            gw.confirm_action(adebayo_token, pending_g)
        except BankRejected as exc:
            g_ok = exc.status_code == 400 and dispute_count("RUB-DB-001") == 0
            g_detail = f"expected BankRejected(400); got {exc.status_code} {exc.code}"
        except Exception as exc:
            g_detail = f"unexpected {type(exc).__name__}: {exc}"
        else:
            g_detail = "cross-session confirm did not raise"
    else:
        g_detail = "propose returned no pending token"
    check("g. pending token bound to session", g_ok, g_detail)

    # h. card block two-step on Adebayo
    status_before = card_status(adebayo, "0001")
    propose_h = gw.propose_card_block(adebayo_token, "0001")
    pending_h = propose_h.get("pending_token")
    status_after_propose = card_status(adebayo, "0001")
    confirm_h = gw.confirm_action(adebayo_token, pending_h) if pending_h else {}
    status_after_confirm = card_status(adebayo, "0001")
    h_ok = (
        bool(pending_h)
        and status_before == "active"
        and status_after_propose == "active"
        and confirm_h.get("status") == "card_blocked"
        and status_after_confirm == "blocked"
    )
    check(
        "h. card block two-step",
        h_ok,
        f"before={status_before} after_propose={status_after_propose} "
        f"confirm={confirm_h.get('status')} after_confirm={status_after_confirm}",
    )

    # i. unavailable API on a closed port
    gw2 = HttpBankGateway(cfg, SimpleNamespace(BANK_API_URL="http://127.0.0.1:1"))
    i_ok = False
    i_detail = ""
    start = time.monotonic()
    try:
        gw2.get_balance("x")
    except BankUnavailable as exc:
        elapsed = time.monotonic() - start
        i_ok = elapsed <= timeout + 2
        i_detail = f"BankUnavailable after {elapsed:.2f}s; limit {timeout + 2}s"
    except Exception as exc:
        i_detail = f"unexpected {type(exc).__name__}: {exc}"
    else:
        i_detail = "closed port did not raise"
    finally:
        gw2.close()
    check("i. unavailable API", i_ok, i_detail)

    # j. signature check
    methods = [
        name for name, fn in inspect.getmembers(HttpBankGateway, predicate=inspect.isfunction)
        if not name.startswith("_")
    ]
    bad = [
        name for name in methods
        if "customer_id" in inspect.signature(getattr(HttpBankGateway, name)).parameters
    ]
    check(
        f"j. signature has no customer_id ({len(methods)} methods)",
        not bad,
        f"methods with customer_id: {bad}",
    )
finally:
    conn.close()
    gw.close()

print(f"PYTHON: {passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
PY
)
py_rc=$?
printf '%s\n' "$py_out"
py_pass=$(printf '%s\n' "$py_out" | grep -c '^PASS:' || true)
py_fail=$(printf '%s\n' "$py_out" | grep -c '^FAIL:' || true)
passes=$((passes + py_pass))
fails=$((fails + py_fail))
if [ "$py_rc" -ne 0 ] && [ "$py_fail" -eq 0 ]; then
  echo "FAIL: python checks crashed (see output above)"
  fails=$((fails + 1))
fi

# --- l. re-run the step 1 script (it already re-runs the older scripts) ---
LIVE="$LIVE" bash scripts/checks/check_chat4_step1.sh >/tmp/check_chat4_step1_step2.log 2>&1
l_rc=$?
if [ "$l_rc" -eq 0 ]; then l_ok=1; else l_ok=0; fi
check "l. scripts/checks/check_chat4_step1.sh passes" "$l_ok" "rc=${l_rc}; see /tmp/check_chat4_step1_step2.log"

# --- m. reuse the step 1 script's j1/j2 result ---
if grep -q "PASS: protected paths untouched" /tmp/check_chat4_step1_step2.log \
  && grep -q "PASS: manifest" /tmp/check_chat4_step1_step2.log; then m_ok=1; else m_ok=0; fi
check "m. protected paths and manifest drift" "$m_ok" "j1/j2 not PASS; see /tmp/check_chat4_step1_step2.log"

echo "RESULT: $passes passed, $fails failed"
if [ "$fails" -ne 0 ]; then exit 1; fi
exit 0
