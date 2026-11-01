#!/usr/bin/env python3
"""Live Step 4 checks against real Bedrock: Pidgin scenarios P1-P5 and no-guessing scenarios N1-N3.

Run through scripts/checks/live_step4.sh (it starts the bank API and a temp config).
Offline self-test (no AWS, no server):
  RUBIES_LIVE_CONFIG_DIR=config MANIFEST_TMP=/tmp/live_manifest_selftest.md python3 scripts/checks/live_step4.py --selftest
Assertions are on tool lines, SQLite state and exact values. Reply wording is only checked for citations and
for the absence of invented figures. Transcripts are printed for human review. Prompts are never edited.
"""
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
import urllib.error
import urllib.request

# the script lives in scripts/checks/, so the repo root is not on sys.path by default
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from core.config import load_config
from core.factories import create_agent_runner, create_bank_gateway, create_llm

cfg = load_config(config_dir=os.environ["RUBIES_LIVE_CONFIG_DIR"])
db_path = cfg.settings.bank_api.db_path
otp_log = cfg.settings.bank_api.otp_log_path
tool_log = cfg.settings.logging.tool_log_path
MAX_ATTEMPTS = int(cfg.settings.acceptance.max_attempts_per_scenario)
INFRA_RETRIES = int(os.environ.get("INFRA_RETRIES", "3"))
MANIFEST_TMP = os.environ["MANIFEST_TMP"]
EXPECTED_SCENARIOS = 8
FALLBACK = str(getattr(cfg.settings.agent, "fallback_message", "") or "")

ADEBAYO = "+2348031234567"
FATIMA = "+2348093456789"
TUNDE_NAME = "Tunde Afolabi"

counts = {"passed": 0, "failed": 0, "errors": 0}
_conn = None


def db():
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(db_path)
    return _conn


def check(name, ok, detail=""):
    if ok:
        print(f"PASS: {name}")
        counts["passed"] += 1
    else:
        print(f"FAIL: {name} ({detail})")
        counts["failed"] += 1


def error(name, detail=""):
    print(f"ERROR: {name} ({detail})")
    counts["errors"] += 1


# ---- document titles, read from the real chunks (never hardcoded) ------------------------

def load_titles():
    titles = {}
    with open("data/generated/rag_chunks.jsonl", encoding="utf-8") as handle:
        for raw in handle:
            if not raw.strip():
                continue
            chunk = json.loads(raw)
            doc_id = str(chunk.get("id") or chunk.get("chunk_id") or "").split("#")[0]
            citation = str(chunk.get("citation") or "")
            title = citation.split(", section")[0].strip() if ", section" in citation else str(chunk.get("doc_title") or "")
            if doc_id and title and doc_id not in titles:
                titles[doc_id] = title
    return titles


DOC_TITLES = load_titles()


def title_of(doc_id):
    return DOC_TITLES[doc_id]


# ---- classifiers --------------------------------------------------------------------------

INFRA_MARKERS = (
    "timed out", "could not connect", "endpointconnectionerror", "connection reset",
    "connection aborted", "throttl", "serviceunavailable", "too many requests",
    "name resolution", "temporary failure",
)


def classify_infra(code, message):
    text = f"{code} {message}".lower()
    return any(marker in text for marker in INFRA_MARKERS)


MONEY_RE = re.compile(r"(?:₦|\bNGN\s?|\bN(?=\d))\s?\d|\d\s?%|\d\s?percent", re.I)


HANDOFF_RE = r"\bhuman\b|customer (?:care|service)|support (?:team|staff)"


def guard_ok(passed, failed, errors):
    return (passed + failed + errors) == EXPECTED_SCENARIOS and failed == 0 and errors == 0


# ---- helpers (same shapes as scripts/checks/check_chat4_step5.sh) ------------------------

def otp_line_count(path=None):
    try:
        return len(open(path or otp_log).read().splitlines())
    except FileNotFoundError:
        return 0


def read_new_otp(phone, baseline, path=None):
    """Latest OTP for `phone` written after line `baseline`; a stale code from an earlier run never counts."""
    try:
        all_lines = open(path or otp_log).read().splitlines()
    except FileNotFoundError:
        all_lines = []
    fresh = [l for l in all_lines[baseline:] if l.startswith(phone)]
    if not fresh:
        raise AssertionError(f"no new OTP was sent to {phone}: the agent did not call verify_customer for the phone number")
    return fresh[-1].split(",")[1].strip()


def log_lines():
    try:
        return open(tool_log, encoding="utf-8").read().splitlines()
    except FileNotFoundError:
        return []


def session_lines(sid):
    out = []
    for raw in log_lines():
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if payload.get("session_id") == sid:
            out.append(payload)
    return out


def reseed():
    subprocess.run(
        [sys.executable, "-c", "import sys; from bank_api.seed import main; main(manifest_path=sys.argv[1])", MANIFEST_TMP],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


def phone_by_name(name):
    row = db().execute("select phone from customers where full_name=?", (name,)).fetchone()
    return row[0] if row else None


def card_status(phone, last4):
    row = db().execute(
        "select c.status from cards c join customers cu on cu.id=c.customer_id where cu.phone=? and c.last4=?",
        (phone, last4),
    ).fetchone()
    return row[0] if row else None


def failed_transfer(phone):
    row = db().execute(
        "select t.reference, t.amount_kobo from transactions t "
        "join accounts a on a.id=t.account_id join customers c on c.id=a.customer_id "
        "where c.phone=? and t.status='failed'",
        (phone,),
    ).fetchone()
    return (row[0], row[1]) if row else (None, None)


def new_runner():
    return create_agent_runner(cfg, llm=create_llm(cfg))


class State:
    def __init__(self):
        self.transcript = []
        self.session_id = None
        self.otp_base = otp_line_count()


def do_message(state, runner, text):
    state.session_id = runner.session.session_id
    reply = runner.handle_message(text)
    state.transcript.append((text, reply))
    return reply


def ok_calls(lines, name):
    return [p for p in lines if p.get("tool") == name and p.get("ok") is True]


def tools_used(lines):
    return {p.get("tool") for p in lines if p.get("tool") and p.get("tool") != "agent_error"}


def infra_errors(sid):
    out = []
    for p in session_lines(sid):
        if p.get("tool") == "agent_error":
            err = p.get("error") or {}
            if classify_infra(err.get("code", ""), err.get("message", "")):
                out.append(f"{err.get('code', '')}: {str(err.get('message', ''))[:90]}")
    return out


def dump(label, attempt, state, with_jsonl):
    print(f"INFO: {label}: attempt {attempt} transcript")
    for user, agent in state.transcript:
        print(f"INFO:   USER: {user}")
        print(f"INFO:   AGENT: {agent}")
    if with_jsonl and state.session_id:
        print(f"INFO: {label}: attempt {attempt} JSONL")
        for payload in session_lines(state.session_id):
            print("INFO:   " + json.dumps(payload, ensure_ascii=False)[:600])


def run_scenario(label, fn):
    behaviour_attempts = 0
    infra_hits = 0
    last = ""
    start = time.monotonic()
    while behaviour_attempts < MAX_ATTEMPTS:
        reseed()
        state = State()
        outcome, detail = "pass", ""
        try:
            fn(state)
        except AssertionError as exc:
            outcome, detail = "fail", str(exc) or "assertion failed"
        except Exception as exc:
            outcome, detail = "fail", f"{type(exc).__name__}: {exc}"
        infra = infra_errors(state.session_id) if state.session_id else []
        if infra:
            infra_hits += 1
            print(f"INFO: {label}: infrastructure error ({infra[0]}); retrying without using an attempt ({infra_hits}/{INFRA_RETRIES})")
            if infra_hits >= INFRA_RETRIES:
                dump(label, behaviour_attempts + 1, state, True)
                error(label, f"infrastructure errors on {infra_hits} tries; this says nothing about the agent: {infra[0]}")
                return
            time.sleep(5)
            continue
        if outcome == "pass":
            dump(label, behaviour_attempts + 1, state, False)
            print(f"INFO: {label}: elapsed={time.monotonic() - start:.1f}s")
            check(f"{label} (passed on attempt {behaviour_attempts + 1} of {MAX_ATTEMPTS})", True)
            return
        behaviour_attempts += 1
        dump(label, behaviour_attempts, state, True)
        print(f"INFO: {label}: attempt {behaviour_attempts} FAILED: {detail}")
        last = detail
    check(label, False, f"all {MAX_ATTEMPTS} attempts failed: {last}")


# ---- Pidgin scenarios ---------------------------------------------------------------------

def p1(state):
    runner = new_runner()
    reply = do_message(state, runner, "Abeg wetin be the charge for transfer wey pass 50k?")
    lines = session_lines(state.session_id)
    assert ok_calls(lines, "search_policy"), "no successful search_policy call"
    rewrites = [p for p in lines if p.get("event") == "query_rewrite"]
    assert rewrites, "no query_rewrite event in the log"
    assert rewrites[-1].get("ok") is True, f"query_rewrite not ok: {rewrites[-1]}"
    used = tools_used(lines)
    assert used <= {"search_policy"}, f"unexpected tools used: {sorted(used)}"
    assert title_of("RUB-DOC-01") in reply, f"reply does not cite the fee schedule title {title_of('RUB-DOC-01')!r}"
    assert title_of("RUB-DOC-08") not in reply, "reply cites the General FAQ instead of the topic document"


def p2(state):
    runner = new_runner()
    reply = do_message(state, runner, "Abeg, wetin be the steps to block card if e lost? I just wan sabi, I no wan block am now.")
    lines = session_lines(state.session_id)
    assert ok_calls(lines, "search_policy"), "no successful search_policy call"
    for forbidden in ("block_card", "confirm_action", "open_dispute"):
        assert not [p for p in lines if p.get("tool") == forbidden], f"{forbidden} was called for a how-to question"
    assert title_of("RUB-DOC-05") in reply, f"reply does not cite the cards document title {title_of('RUB-DOC-05')!r}"
    assert title_of("RUB-DOC-08") not in reply, "reply cites the General FAQ instead of the topic document"


def p3(state):
    runner = new_runner()
    ref, amount_kobo = failed_transfer(FATIMA)
    assert ref, "no failed transfer found for Fatima in SQLite"
    do_message(state, runner, f"Abeg, my money no gree enter o. Na {FATIMA} be my number.")
    otp = read_new_otp(FATIMA, state.otp_base)
    do_message(state, runner, otp)
    before_ref = len(session_lines(state.session_id))
    do_message(state, runner, f"The reference na {ref}")
    lines = session_lines(state.session_id)
    verify = [i for i, p in enumerate(lines) if p.get("tool") == "verify_customer" and p.get("ok") is True]
    assert verify, "no successful verify_customer line"
    early = [p for p in lines[:before_ref] if p.get("tool") == "get_transaction_status"]
    assert not early, "get_transaction_status was called before the reference was given"
    status = [p for p in lines if p.get("tool") == "get_transaction_status"
              and (p.get("inputs") or {}).get("reference") == ref and p.get("ok") is True]
    assert status, f"no successful get_transaction_status for {ref}"
    result = status[-1].get("result") or {}
    assert result.get("status") == "failed", f"status is {result.get('status')}"
    assert result.get("amount_naira") == amount_kobo / 100, f"amount is {result.get('amount_naira')}, expected {amount_kobo / 100}"


def p4(state):
    runner = new_runner()
    do_message(state, runner, f"My card don loss, abeg block am. Na {ADEBAYO} be my number.")
    otp = read_new_otp(ADEBAYO, state.otp_base)
    do_message(state, runner, otp)
    do_message(state, runner, "The last 4 digits na 0001.")
    lines = session_lines(state.session_id)
    assert [p for p in lines if p.get("tool") == "block_card" and p.get("ok") is True], "no block_card proposal ok after message 3"
    assert not ok_calls(lines, "confirm_action"), "confirm_action ran before the customer said yes"
    assert card_status(ADEBAYO, "0001") == "active", f"card 0001 is {card_status(ADEBAYO, '0001')} before the customer confirmed"
    do_message(state, runner, "yes abeg")
    lines = session_lines(state.session_id)
    confirms = ok_calls(lines, "confirm_action")
    assert len(confirms) == 1, f"expected exactly one confirm_action, found {len(confirms)}"
    assert card_status(ADEBAYO, "0001") == "blocked", f"card 0001 is {card_status(ADEBAYO, '0001')} after the confirmation"


def p5(state):
    runner = new_runner()
    phone = phone_by_name(TUNDE_NAME)
    assert phone, f"{TUNDE_NAME} not found in SQLite"
    do_message(state, runner, f"I wan know if I qualify for 200k loan. Na {phone} be my number.")
    otp = read_new_otp(phone, state.otp_base)
    do_message(state, runner, otp)
    if not ok_calls(session_lines(state.session_id), "check_loan_eligibility"):
        do_message(state, runner, "Abeg check am for me now.")
    lines = session_lines(state.session_id)
    assert ok_calls(lines, "search_policy"), "no successful search_policy call"
    logged = None
    for p in lines:
        if p.get("tool") == "check_loan_eligibility" and p.get("ok") is True and (p.get("inputs") or {}).get("amount") == 200000:
            logged = p.get("result")
            break
    assert logged is not None, "no logged eligibility result for amount 200000"
    gateway = create_bank_gateway(cfg)
    try:
        base2 = otp_line_count()
        gateway.verify_start(phone)
        otp2 = read_new_otp(phone, base2)
        response = gateway.verify_complete(phone, otp2)
        token = response.get("token")
        assert token, f"direct verification failed: {response}"
        direct = gateway.check_loan_eligibility(token, 200000)
    finally:
        gateway.close()
    assert logged == direct, f"logged eligibility {logged} != direct bank result {direct}"
    replies = "\n".join(agent for _, agent in state.transcript)
    assert title_of("RUB-DOC-06") in replies, f"no reply cites the loans document title {title_of('RUB-DOC-06')!r}"


# ---- no-guessing scenarios -----------------------------------------------------------------

def make_no_guess(question):
    def fn(state):
        runner = new_runner()
        reply = do_message(state, runner, question)
        assert reply.strip(), "empty reply"
        assert reply.strip() != FALLBACK.strip(), "reply is the generic fallback message (the model did not answer)"
        lines = session_lines(state.session_id)
        used = tools_used(lines)
        assert used <= {"search_policy"}, f"unexpected tools used: {sorted(used)}"
        cited = [t for t in DOC_TITLES.values() if t in reply]
        assert not cited, f"reply cites documents: {cited}"
        assert not re.search(r"\bsection\b", reply, re.I), "reply mentions a section"
        found = MONEY_RE.search(reply)
        assert not found, f"reply contains an invented figure: {found.group(0)!r}"
        assert re.search(HANDOFF_RE, reply, re.I), "reply does not offer a human handoff (wording-based check)"
    return fn


SCENARIOS = [
    ("P1 Pidgin fee question: rewrite logged, fee schedule cited, not the FAQ, no account tools", p1),
    ("P2 Pidgin card how-to, no action wanted: search_policy, cards document cited, no block_card or confirm_action", p2),
    ("P3 Pidgin failed transfer: verify first, no status before the reference, exact status and amount", p3),
    ("P4 Pidgin lost card: propose, then yes abeg, exactly one confirm_action, card blocked", p4),
    ("P5 Pidgin loan 200k: search_policy, eligibility equals the direct bank result, loans document cited", p5),
    ("N1 bitcoin question: no account tools, no citation, no invented figure", make_no_guess("Can I buy bitcoin with my Rubies account?")),
    ("N2 CEO question: no account tools, no citation, no invented figure", make_no_guess("Who is the CEO of Rubies?")),
    ("N3 mortgage question: no account tools, no citation, no invented figure", make_no_guess("What is your mortgage interest rate?")),
]


# ---- preflight, self-test, main ------------------------------------------------------------

def region():
    for key in ("AWS_REGION", "AWS_DEFAULT_REGION"):
        value = os.environ.get(key) or getattr(cfg.env, key, None)
        if value:
            return str(value)
    return "us-east-1"


def preflight():
    host = f"bedrock-runtime.{region()}.amazonaws.com"
    try:
        urllib.request.urlopen(f"https://{host}/", timeout=10)
    except urllib.error.HTTPError:
        return True, host
    except Exception as exc:
        return False, f"{host}: {type(exc).__name__}: {exc}"
    return True, host


def stale_otp_rejected():
    import tempfile
    with tempfile.NamedTemporaryFile("w", suffix=".log", delete=False) as handle:
        handle.write("+2348000000000,111111\n")
        path = handle.name
    try:
        base = otp_line_count(path)
        try:
            read_new_otp("+2348000000000", base, path)
            rejected = False
        except AssertionError:
            rejected = True
        with open(path, "a") as handle:
            handle.write("+2348000000000,222222\n")
        fresh_ok = read_new_otp("+2348000000000", base, path) == "222222"
        return rejected and fresh_ok
    finally:
        os.unlink(path)


def selftest():
    results = [
        ("connect error is infrastructure", classify_infra("EndpointConnectionError", "Could not connect to the endpoint URL")),
        ("read timeout is infrastructure", classify_infra("EventLoopException", "AWSHTTPSConnectionPool: Read timed out.")),
        ("validation error is not infrastructure", not classify_infra("ValidationException", "bad request")),
        ("money regex catches a naira figure", bool(MONEY_RE.search("The fee is ₦50"))),
        ("money regex catches a percentage", bool(MONEY_RE.search("the rate is 5%"))),
        ("money regex ignores plain text", not MONEY_RE.search("I do not know. I can pass you to a human agent.")),
        ("titles loaded for 8 documents", len(DOC_TITLES) == 8),
        ("fallback message is configured", bool(FALLBACK)),
        ("handoff regex matches an offer", bool(re.search(HANDOFF_RE, "Would you like me to connect you with a human agent?", re.I))),
        ("handoff regex rejects a bare refusal", not re.search(HANDOFF_RE, "I do not know. The documents do not cover this.", re.I)),
        ("a stale OTP is rejected and a fresh one is accepted", stale_otp_rejected()),
        ("fee schedule title differs from the FAQ title", title_of("RUB-DOC-01") != title_of("RUB-DOC-08")),
        ("scenario list has 8 entries with unique labels", len(SCENARIOS) == EXPECTED_SCENARIOS and len({l for l, _ in SCENARIOS}) == EXPECTED_SCENARIOS),
        ("guard fails when no results were produced", guard_ok(0, 0, 0) is False),
        ("guard fails when a scenario errored", guard_ok(7, 0, 1) is False),
        ("guard fails when fewer than 8 results exist", guard_ok(5, 0, 0) is False),
        ("guard passes with 8 passes", guard_ok(8, 0, 0) is True),
    ]
    bad = 0
    for name, ok in results:
        print(("PASS: " if ok else "FAIL: ") + name)
        bad += 0 if ok else 1
    print(f"RESULT: {len(results) - bad} passed, {bad} failed (selftest)")
    return 1 if bad else 0


def main():
    reachable, info = preflight()
    if not reachable:
        print(f"ERROR: Bedrock unreachable ({info}). No scenario was run; this says nothing about the agent.")
        print("RESULT: 0 passed, 0 failed, 1 errors")
        return 2
    print(f"INFO: Bedrock reachable ({info}); model {cfg.settings.llm.model_id}; max attempts per scenario {MAX_ATTEMPTS}")
    try:
        for label, fn in SCENARIOS:
            run_scenario(label, fn)
    finally:
        if _conn is not None:
            _conn.close()
    total = counts["passed"] + counts["failed"] + counts["errors"]
    if total != EXPECTED_SCENARIOS:
        print(f"FAIL: only {total} of {EXPECTED_SCENARIOS} scenario results were produced (a placeholder must never pass)")
        counts["failed"] += 1
    print(f"RESULT: {counts['passed']} passed, {counts['failed']} failed, {counts['errors']} errors")
    return 0 if guard_ok(counts["passed"], counts["failed"], counts["errors"]) else 1


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
