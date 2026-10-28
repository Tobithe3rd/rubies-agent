#!/usr/bin/env bash
# Chat 4 step 3 checks: validated, logged tool runtime over the real bank API.
# Usage: LIVE=0 bash scripts/check_chat4_step3.sh   (or LIVE=1)
#
# LIVE=0: every check is local except l (real search_policy), which needs AWS
# and is printed as SKIP. The older scripts reached through
# check_chat4_step2.sh handle their own LIVE gating.
set -u
cd "$(dirname "$0")/.."

LIVE="${LIVE:-1}"
export LIVE
PORT="${BANK_API_PORT:-8001}"
BASE="http://127.0.0.1:${PORT}"
STARTED=0
API_PID=""
passes=0
fails=0
TMPCFG=$(mktemp -d)
TOOLLOG="$TMPCFG/tool_calls.jsonl"

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
skip() { echo "SKIP: $1"; }

# --- temp config copy with a fresh tool log path (never edit settings.yaml) ---
cp config/settings.yaml "$TMPCFG/settings.yaml"
cp config/tools.yaml "$TMPCFG/tools.yaml"
python3 - "$TMPCFG/settings.yaml" "$TOOLLOG" <<'PY'
import sys
import yaml

path, log_path = sys.argv[1], sys.argv[2]
with open(path) as handle:
    data = yaml.safe_load(handle)
data["logging"]["tool_log_path"] = log_path
with open(path, "w") as handle:
    yaml.safe_dump(data, handle, sort_keys=False)
PY
echo "INFO: tool log at $TOOLLOG"

# --- fresh reset + seed (works while the API is running) ---
if ! python3 -m bank_api.seed >/tmp/seed_step3.log 2>&1; then
  echo "FAIL: seed fresh data (see /tmp/seed_step3.log)"
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
    >/tmp/bank_api_step3.log 2>&1 &
  API_PID=$!
  STARTED=1
  code=""
  for _ in $(seq 1 40); do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/health" 2>/dev/null || true)
    if [ "$code" = "200" ]; then break; fi
    sleep 0.5
  done
  if [ "$code" != "200" ]; then
    echo "FAIL: bank API did not start on $BASE (see /tmp/bank_api_step3.log)"
    fails=$((fails + 1))
    echo "RESULT: $passes passed, $fails failed"
    exit 1
  fi
  echo "INFO: started bank API on $BASE"
fi

# --- a-m: drive the validated ToolRuntime over HTTP ---
py_out=$(RUBIES_CONFIG_DIR="$TMPCFG" BANK_API_URL="$BASE" TOOLLOG="$TOOLLOG" LIVE="$LIVE" \
  python3 - <<'PY' 2>&1
import json
import os
import sqlite3
import sys
from types import SimpleNamespace

from core.config import load_config
from core.factories import create_bank_gateway
from agent.bank_client import HttpBankGateway
from agent.session import SessionState
from agent.tool_logger import JsonlToolLogger
from agent.tool_runtime import ToolRuntime
from agent.tool_specs import TOOL_SPECS
from rag.search import build_search_policy

passed = 0
failed = 0
CALLS = 0


def check(name, ok, detail=""):
    global passed, failed
    if ok:
        print(f"PASS: {name}")
        passed += 1
    else:
        print(f"FAIL: {name} ({detail})")
        failed += 1


def skip(name):
    print(f"SKIP: {name}")


cfg = load_config(config_dir=os.environ["RUBIES_CONFIG_DIR"])
db_path = cfg.settings.bank_api.db_path
otp_log = cfg.settings.bank_api.otp_log_path
tool_log = cfg.settings.logging.tool_log_path
live = os.environ.get("LIVE", "1") == "1"

conn = sqlite3.connect(db_path)
gw = create_bank_gateway(cfg)
logger = JsonlToolLogger(cfg)


def read_otp(phone):
    lines = [l for l in open(otp_log).read().splitlines() if l.startswith(phone)]
    if not lines:
        raise RuntimeError(f"no OTP log line for {phone}")
    return lines[-1].split(",")[1].strip()


def log_lines():
    try:
        return open(tool_log, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return []


def audit_count():
    return conn.execute("select count(*) from audit_log").fetchone()[0]


def dispute_count(reference):
    return conn.execute(
        "select count(*) from disputes d join transactions t on t.id=d.transaction_id "
        "where t.reference=?",
        (reference,),
    ).fetchone()[0]


def card_status(phone, last4):
    row = conn.execute(
        "select c.status from cards c join customers cu on cu.id=c.customer_id "
        "where cu.phone=? and c.last4=?",
        (phone, last4),
    ).fetchone()
    return row[0] if row else None


def call(runtime, name, **args):
    global CALLS
    CALLS += 1
    return runtime.call(name, **args)


def unused_search(query):
    raise RuntimeError("search not used in this check")


def make_runtime(session, gateway=None, search=None):
    return ToolRuntime(cfg, cfg.tools, session, gateway or gw, search or unused_search, logger)


adebayo = "+2348031234567"
bola = "+2348115678901"
fatima = "+2348093456789"

try:
    # a. unverified read is refused and never reaches the bank
    adebayo_session = SessionState()
    adebayo_rt = make_runtime(adebayo_session)
    audit_before = audit_count()
    lines_before = len(log_lines())
    res = call(adebayo_rt, "get_balance")
    audit_after = audit_count()
    lines_after = len(log_lines())
    new_lines = log_lines()[lines_before:lines_after]
    a_ok = (
        res.get("error") == "not_verified"
        and len(new_lines) == 1
        and json.loads(new_lines[-1]).get("ok") is False
        and audit_after == audit_before
    )
    check(
        "a. unverified get_balance refused without a bank call",
        a_ok,
        f"error={res.get('error')} lines={lines_before}->{lines_after} audit={audit_before}->{audit_after}",
    )

    # b. verify Adebayo; token/OTP must not appear in the JSONL or the result
    call(adebayo_rt, "verify_customer", phone=adebayo)
    otp = read_otp(adebayo)
    res_b = call(adebayo_rt, "verify_customer", phone=adebayo, otp=otp)
    token = adebayo_session.token
    raw = open(tool_log, encoding="utf-8").read()
    b_ok = (
        adebayo_session.verified is True
        and res_b.get("ok") is True
        and bool(token)
        and token not in raw
        and otp not in raw
        and token not in json.dumps(res_b)
        and otp not in json.dumps(res_b)
    )
    check("b. verify Adebayo and no session token or OTP in the JSONL", b_ok,
          f"verified={adebayo_session.verified}")

    # c. balance matches the real SQLite file
    expected = conn.execute(
        "select a.balance_kobo from customers c join accounts a on a.customer_id=c.id "
        "where c.phone=?",
        (adebayo,),
    ).fetchone()[0]
    res_c = call(adebayo_rt, "get_balance")
    actual = (res_c.get("data") or {}).get("balance_kobo")
    check("c. get_balance matches SQLite", res_c.get("ok") is True and actual == expected,
          f"expected {expected}, got {actual}")

    # d. customer_id / token injection is rejected before any bank call
    inj_session = SessionState()
    inj_rt = make_runtime(inj_session)
    audit_before = audit_count()
    lines_before = len(log_lines())
    r1 = call(inj_rt, "get_balance", customer_id="1")
    r2 = call(inj_rt, "get_balance", token="abc")
    audit_after = audit_count()
    new_lines = log_lines()[lines_before:len(log_lines())]
    d_ok = (
        r1.get("error") == "unexpected_argument"
        and r2.get("error") == "unexpected_argument"
        and len(new_lines) == 2
        and all(json.loads(l).get("ok") is False for l in new_lines)
        and audit_after == audit_before
    )
    check("d. argument injection rejected without a bank call", d_ok,
          f"r1={r1.get('error')} r2={r2.get('error')} audit={audit_before}->{audit_after}")

    # e. three wrong OTPs on Fatima
    fatima_session = SessionState()
    fatima_rt = make_runtime(fatima_session)
    call(fatima_rt, "verify_customer", phone=fatima)
    fatima_otp = read_otp(fatima)
    wrong = "000000" if fatima_otp != "000000" else "111111"
    errors = []
    for _ in range(3):
        res_e = call(fatima_rt, "verify_customer", phone=fatima, otp=wrong)
        errors.append(res_e.get("error"))
    e_ok = (
        errors == ["verification_failed"] * 3
        and fatima_session.failed_verifications == 3
        and fatima_session.verified is False
    )
    check("e. three wrong OTPs are verification_failed and leave Fatima unverified", e_ok,
          f"errors={errors} failed={fatima_session.failed_verifications} verified={fatima_session.verified}")

    # f. double-debit two-step on Bola
    bola_session = SessionState()
    bola_rt = make_runtime(bola_session)
    call(bola_rt, "verify_customer", phone=bola)
    bola_otp = read_otp(bola)
    call(bola_rt, "verify_customer", phone=bola, otp=bola_otp)
    stmt = call(bola_rt, "get_mini_statement", limit=50)
    by_ref = {t.get("reference"): t for t in (stmt.get("data") or {}).get("transactions", [])}
    has_both = "RUB-DB-001" in by_ref and "RUB-DB-002" in by_ref
    amount_ok = (
        by_ref.get("RUB-DB-001", {}).get("amount_naira") == 25000
        and by_ref.get("RUB-DB-002", {}).get("amount_naira") == 25000
    )
    before = dispute_count("RUB-DB-002")
    prop = call(bola_rt, "open_dispute", reference="RUB-DB-002", reason="double debit")
    pending = (prop.get("data") or {}).get("pending_token")
    after_prop = dispute_count("RUB-DB-002")
    same = call(bola_rt, "confirm_action", pending_token=pending)
    after_same = dispute_count("RUB-DB-002")
    bola_session.start_turn()
    conf = call(bola_rt, "confirm_action", pending_token=pending)
    after_conf = dispute_count("RUB-DB-002")
    again = call(bola_rt, "confirm_action", pending_token=pending)
    after_again = dispute_count("RUB-DB-002")
    f_ok = (
        has_both and amount_ok and bool(pending) and before == 0 and after_prop == 0
        and same.get("error") == "confirmation_not_allowed"
        and (same.get("data") or {}).get("reason") == "same_turn"
        and after_same == 0
        and conf.get("ok") is True and after_conf == 1
        and again.get("error") == "confirmation_not_allowed"
        and (again.get("data") or {}).get("reason") == "unknown_token"
        and after_again == 1
    )
    check("f. double-debit two-step confirmation", f_ok,
          f"refs={has_both} amount={amount_ok} before={before} prop={after_prop} "
          f"same={(same.get('data') or {}).get('reason')} conf={after_conf} "
          f"again={(again.get('data') or {}).get('reason')} final={after_again}")

    # g. lost-card two-step on Adebayo
    g_session = SessionState()
    g_rt = make_runtime(g_session)
    call(g_rt, "verify_customer", phone=adebayo)
    g_otp = read_otp(adebayo)
    call(g_rt, "verify_customer", phone=adebayo, otp=g_otp)
    before = card_status(adebayo, "0001")
    prop_g = call(g_rt, "block_card", last4="0001")
    pending_g = (prop_g.get("data") or {}).get("pending_token")
    after_prop = card_status(adebayo, "0001")
    same_g = call(g_rt, "confirm_action", pending_token=pending_g)
    g_session.start_turn()
    conf_g = call(g_rt, "confirm_action", pending_token=pending_g)
    after_conf = card_status(adebayo, "0001")
    g_ok = (
        before == "active" and bool(pending_g) and after_prop == "active"
        and same_g.get("error") == "confirmation_not_allowed"
        and (same_g.get("data") or {}).get("reason") == "same_turn"
        and conf_g.get("ok") is True and after_conf == "blocked"
    )
    check("g. lost-card two-step confirmation", g_ok,
          f"before={before} prop={after_prop} same={(same_g.get('data') or {}).get('reason')} "
          f"confirmed={conf_g.get('ok')} after={after_conf}")

    # h. made-up pending token
    audit_before = audit_count()
    res_h = call(bola_rt, "confirm_action", pending_token="made-up-token")
    audit_after = audit_count()
    h_ok = (
        res_h.get("error") == "confirmation_not_allowed"
        and (res_h.get("data") or {}).get("reason") == "unknown_token"
        and audit_after == audit_before
    )
    check("h. made-up pending token refused without a bank call", h_ok,
          f"error={res_h.get('error')} reason={(res_h.get('data') or {}).get('reason')} audit={audit_before}->{audit_after}")

    # i. neighbour attack plus identity-leak audit over Adebayo's lines
    res_i = call(g_rt, "get_transaction_status", reference="RUB-03-000037")
    text_i = json.dumps(res_i).lower()
    i_ok = (
        res_i.get("error") == "not_found"
        and "amount" not in text_i
        and "50000" not in text_i
    )
    session_lines = []
    for raw_line in log_lines():
        payload = json.loads(raw_line)
        if payload.get("session_id") == g_session.session_id:
            session_lines.append(payload)
    for payload in session_lines:
        allowed = set(TOOL_SPECS.get(payload.get("tool"), {}).get("allowed", {}))
        inputs = payload.get("inputs", {})
        if set(inputs) - allowed:
            i_ok = False
        raw_inputs = json.dumps(inputs)
        if "customer_id" in raw_inputs:
            i_ok = False
        for other in (fatima, bola):
            if other in raw_inputs:
                i_ok = False
    check("i. neighbour attack refused and no identity leak in Adebayo's lines", i_ok,
          f"error={res_i.get('error')} lines={len(session_lines)} checked")
    print(f"INFO: checked {len(session_lines)} JSONL lines for Adebayo's session")

    # j. bank down
    down_gw = HttpBankGateway(cfg, SimpleNamespace(BANK_API_URL="http://127.0.0.1:1"))
    down_session = SessionState()
    down_rt = make_runtime(down_session, gateway=down_gw)
    res_j = call(down_rt, "verify_customer", phone=adebayo)
    j_ok = res_j.get("error") == "bank_unavailable" and down_session.tool_error_count == 1
    down_gw.close()
    check("j. bank down returns bank_unavailable and counts one tool error", j_ok,
          f"error={res_j.get('error')} tool_errors={down_session.tool_error_count}")

    # k. search failure
    def broken_search(query):
        raise RuntimeError("policy store unavailable")

    search_session = SessionState()
    search_rt = make_runtime(search_session, search=broken_search)
    res_k = call(search_rt, "search_policy", query="anything")
    k_ok = res_k.get("error") == "tool_error" and search_session.tool_error_count == 1
    check("k. search failure is a tool_error without crashing", k_ok,
          f"error={res_k.get('error')} tool_errors={search_session.tool_error_count}")

    # l. real search_policy (LIVE only)
    if live:
        real_search = build_search_policy(cfg)
        rag_session = SessionState()
        rag_rt = make_runtime(rag_session, search=real_search)
        res_l1 = call(rag_rt, "search_policy", query="What is the fee for transfers above ₦50,000?")
        d1 = res_l1.get("data") or {}
        ok1 = (
            res_l1.get("ok") is True
            and d1.get("status") == "ok"
            and d1.get("results")
            and str(d1["results"][0].get("chunk_id", "")).startswith("RUB-DOC-01")
        )
        res_l2 = call(rag_rt, "search_policy", query="What is the capital of France?")
        d2 = res_l2.get("data") or {}
        ok2 = (
            res_l2.get("ok") is True
            and d2.get("status") == "no_relevant_result"
            and rag_session.failed_retrievals == 1
            and rag_session.consecutive_failed_retrievals == 1
        )
        last_raw = log_lines()[-1]
        ok3 = (
            all(k in last_raw for k in ('"status"', '"top_score"', '"threshold"'))
            and "capital of France" not in last_raw
        )
        top_chunk = str((d1.get("results") or [{}])[0].get("chunk_id")) if d1.get("results") else "-"
        check("l. real search_policy citation + no-relevant-result + hidden query",
              ok1 and ok2 and ok3,
              f"q1={d1.get('status')}/{top_chunk} q2={d2.get('status')} "
              f"failed={rag_session.failed_retrievals}")
    else:
        skip("l. real search_policy (needs AWS; LIVE=0)")

    # m. JSONL integrity
    lines = log_lines()
    m_ok = len(lines) == CALLS
    for raw_line in lines:
        try:
            payload = json.loads(raw_line)
        except Exception:
            m_ok = False
            break
        for key in ("time", "session_id", "tool", "inputs", "ok"):
            if key not in payload:
                m_ok = False
        if not str(payload.get("time", "")).endswith("+01:00"):
            m_ok = False
    check(f"m. JSONL integrity ({len(lines)} lines, {CALLS} calls)", m_ok,
          f"lines={len(lines)} calls={CALLS}")
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

# --- n. fail-fast config ---
badcfg=$(mktemp -d)
cp config/settings.yaml "$badcfg/settings.yaml"
cp config/tools.yaml "$badcfg/tools.yaml"
python3 - "$badcfg/settings.yaml" <<'PY'
import sys
import yaml

path = sys.argv[1]
with open(path) as handle:
    data = yaml.safe_load(handle)
data["handoff"]["max_failed_retrievals"] = 0
with open(path, "w") as handle:
    yaml.safe_dump(data, handle, sort_keys=False)
PY
out=$(python3 -c "from core.config import load_config; load_config(config_dir='$badcfg')" 2>&1); rc=$?
if [ "$rc" -ne 0 ] && printf '%s' "$out" | grep -q "max_failed_retrievals"; then n_ok=1; else n_ok=0; fi
check "n. zero handoff.max_failed_retrievals fails and names the key" "$n_ok" "rc=$rc out=$out"
rm -rf "$badcfg"

# --- o. full pytest ---
python3 -m pytest -q >/tmp/pytest_step3.log 2>&1
pytest_rc=$?
count=$(grep -oE '[0-9]+ passed' /tmp/pytest_step3.log | head -1 | awk '{print $1}')
count="${count:-0}"
if [ "$pytest_rc" -eq 0 ] && [ "$count" -gt 166 ]; then o_ok=1; else o_ok=0; fi
check "o. Full pytest passes with ${count} tests (> 166)" "$o_ok" "pytest rc=${pytest_rc}, count=${count}"

# --- p. re-run the step 2 script (it re-runs step 1 and the older ones) ---
LIVE="$LIVE" bash scripts/check_chat4_step2.sh >/tmp/check_chat4_step2_step3.log 2>&1
p_rc=$?
if [ "$p_rc" -eq 0 ]; then p_ok=1; else p_ok=0; fi
check "p. scripts/check_chat4_step2.sh passes" "$p_ok" "rc=${p_rc}; see /tmp/check_chat4_step2_step3.log"

# --- q. protected paths (same j1/j2 as step 1, reused) ---
base="chat3-done"
if ! git rev-parse -q --verify "$base" >/dev/null 2>&1; then
  base=$(git log --format=%H --grep='^Chat 3 done' -1 2>/dev/null || true)
fi
if [ -z "${base:-}" ]; then
  skip "q1. protected paths untouched (no base ref found)"
  skip "q2. manifest drift (no base ref found)"
else
  if git diff --quiet "$base" -- bank_api providers rag eval scripts/check_step5.sh scripts/check_rag_all.sh 2>/dev/null; then
    check "q1. protected paths untouched since ${base}" 1
  else
    changed=$(git diff --name-only "$base" -- bank_api providers rag eval scripts/check_step5.sh scripts/check_rag_all.sh 2>/dev/null | tr '\n' ' ')
    check "q1. protected paths untouched since chat3-done" 0 "modified: $changed"
  fi

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
    check "q2. manifest drift is only date/tier drift since chat3-done" 0 "${first#FAIL: }"
  elif printf '%s\n' "$j2" | grep -q '^NOCHANGE'; then
    check "q2. manifest has no drift since chat3-done" 1
  else
    check "q2. manifest drift is only date/tier drift since chat3-done" 1
  fi
fi

echo "INFO: agent/bank_client.py and agent/errors.py vs HEAD (informational):"
git diff --stat HEAD -- agent/bank_client.py agent/errors.py 2>/dev/null || true
git status --short -- agent/bank_client.py agent/errors.py 2>/dev/null || true

echo "RESULT: $passes passed, $fails failed"
if [ "$fails" -ne 0 ]; then exit 1; fi
exit 0
