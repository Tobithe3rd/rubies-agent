import json
from datetime import datetime
from types import SimpleNamespace

from agent.errors import (
    BankNotFound,
    BankRejected,
    BankUnauthorized,
    BankUnavailable,
)
from agent.session import SessionState
from agent.tool_logger import JsonlToolLogger
from agent.tool_runtime import ToolRuntime
from agent.tool_specs import TOOL_SPECS
from core.clock import Clock


class FakeGateway:
    def __init__(self):
        self.calls = []
        self.responses = {}
        self.errors = {}

    def _call(self, name, *args, **kwargs):
        self.calls.append((name, args, kwargs))
        if name in self.errors:
            raise self.errors[name]
        return self.responses.get(name, {})

    def verify_start(self, phone):
        return self._call("verify_start", phone)

    def verify_complete(self, phone, otp):
        return self._call("verify_complete", phone, otp)

    def get_balance(self, token):
        return self._call("get_balance", token)

    def get_mini_statement(self, token, limit=None):
        return self._call("get_mini_statement", token, limit)

    def get_transaction_status(self, token, reference):
        return self._call("get_transaction_status", token, reference)

    def propose_dispute(self, token, reference, reason):
        return self._call("propose_dispute", token, reference, reason)

    def propose_card_block(self, token, last4):
        return self._call("propose_card_block", token, last4)

    def confirm_action(self, token, pending_token):
        return self._call("confirm_action", token, pending_token)

    def check_loan_eligibility(self, token, amount):
        return self._call("check_loan_eligibility", token, amount)

    def get_loan_status(self, token):
        return self._call("get_loan_status", token)

    def create_handoff(self, summary, token=None, reason=None):
        return self._call("create_handoff", summary, token, reason)


def make_cfg(tmp_path, debug=False):
    return SimpleNamespace(
        settings=SimpleNamespace(
            timezone="Africa/Lagos",
            logging=SimpleNamespace(
                tool_log_path=str(tmp_path / "tool_calls.jsonl"),
                debug=debug,
                redact_keys=["otp", "token", "session_token", "authorization"],
                mask_phone_keep_last=4,
                pending_token_prefix_chars=4,
            ),
            bank_api=SimpleNamespace(handoff_summary_max_chars=1000),
        )
    )


def make_tools():
    return {
        name: SimpleNamespace(
            enabled=True,
            requires_confirmation=name in {"open_dispute", "block_card"},
            requires_verified_session=name
            not in {"verify_customer", "handoff_to_human", "search_policy"},
        )
        for name in TOOL_SPECS
    }


def frozen_clock():
    return Clock("Africa/Lagos", now_source=lambda: datetime(2026, 1, 1, 0, 0))


def make_runtime(tmp_path, session=None, gateway=None, search=None, debug=False, tools=None):
    cfg = make_cfg(tmp_path, debug)
    logger = JsonlToolLogger(cfg, clock=frozen_clock())
    session = session or SessionState()
    gateway = gateway or FakeGateway()
    search = search or (lambda query: SimpleNamespace(
        status="ok", message="", results=[], top_score=None, threshold=0.35,
    ))
    tools = tools or make_tools()
    runtime = ToolRuntime(cfg, tools, session, gateway, search, logger)
    return runtime, session, gateway, logger


def log_lines(logger):
    path = logger.path
    if not path.exists():
        return []
    return path.read_text().splitlines()


class TestRejections:
    def test_unknown_tool_is_rejected_and_logged(self, tmp_path):
        runtime, _, gateway, logger = make_runtime(tmp_path)
        result = runtime.call("not_a_tool")
        assert result["error"] == "unknown_tool"
        assert gateway.calls == []
        assert len(log_lines(logger)) == 1

    def test_disabled_tool_is_rejected(self, tmp_path):
        tools = make_tools()
        tools["get_balance"].enabled = False
        runtime, _, gateway, _ = make_runtime(tmp_path, tools=tools)
        result = runtime.call("get_balance")
        assert result["error"] == "tool_disabled"
        assert gateway.calls == []

    def test_customer_id_and_token_are_unexpected_arguments(self, tmp_path):
        runtime, session, gateway, _ = make_runtime(tmp_path)
        session.set_verified("TOKEN", "A")
        for kwargs in (
            {"customer_id": "1"},
            {"token": "abc"},
            {"phone": "+2348031234567"},
        ):
            result = runtime.call("get_balance", **kwargs)
            assert result["error"] == "unexpected_argument"
        assert gateway.calls == []

    def test_missing_and_wrong_type_arguments(self, tmp_path):
        runtime, session, gateway, _ = make_runtime(tmp_path)
        session.set_verified("TOKEN", "A")
        assert runtime.call("get_transaction_status")["error"] == "missing_argument"
        assert runtime.call("get_mini_statement", limit="x")["error"] == "invalid_argument"
        assert runtime.call("check_loan_eligibility", amount=True)["error"] == "invalid_argument"
        assert gateway.calls == []

    def test_not_verified_is_rejected_without_bank_call(self, tmp_path):
        runtime, _, gateway, _ = make_runtime(tmp_path)
        result = runtime.call("get_balance")
        assert result["error"] == "not_verified"
        assert gateway.calls == []

    def test_one_log_line_for_each_rejected_path(self, tmp_path):
        tools = make_tools()
        runtime, _, gateway, logger = make_runtime(tmp_path, tools=tools)
        runtime.call("not_a_tool")
        tools["get_balance"].enabled = False
        runtime.call("get_balance")
        tools["get_balance"].enabled = True
        runtime.call("get_balance")
        assert gateway.calls == []
        assert len(log_lines(logger)) == 3


class TestConfirmation:
    def test_same_turn_confirmation_is_refused_without_bank_call(self, tmp_path):
        runtime, session, gateway, _ = make_runtime(tmp_path)
        session.set_verified("TOKEN", "A")
        session.register_pending("P1", "open_dispute")
        result = runtime.call("confirm_action", pending_token="P1")
        assert result["error"] == "confirmation_not_allowed"
        assert result["data"]["reason"] == "same_turn"
        assert gateway.calls == []

    def test_unknown_pending_token_is_refused_without_bank_call(self, tmp_path):
        runtime, session, gateway, _ = make_runtime(tmp_path)
        session.set_verified("TOKEN", "A")
        result = runtime.call("confirm_action", pending_token="NOPE")
        assert result["error"] == "confirmation_not_allowed"
        assert result["data"]["reason"] == "unknown_token"
        assert gateway.calls == []

    def test_confirmation_after_new_turn_executes_and_consumes(self, tmp_path):
        runtime, session, gateway, _ = make_runtime(tmp_path)
        session.set_verified("TOKEN", "A")
        session.register_pending("P1", "open_dispute")
        session.start_turn()
        gateway.responses["confirm_action"] = {"status": "dispute_opened"}
        result = runtime.call("confirm_action", pending_token="P1")
        assert result["ok"] is True
        assert result["data"]["status"] == "dispute_opened"
        assert session.pending == {}
        assert len(gateway.calls) == 1

    def test_rejected_confirmation_consumes_pending(self, tmp_path):
        runtime, session, gateway, _ = make_runtime(tmp_path)
        session.set_verified("TOKEN", "A")
        session.register_pending("P1", "open_dispute")
        session.start_turn()
        gateway.errors["confirm_action"] = BankRejected(
            "bank API rejected the request", 400, "invalid_or_expired"
        )
        result = runtime.call("confirm_action", pending_token="P1")
        assert result["error"] == "rejected"
        assert "invalid_or_expired" in result["message"]
        assert session.pending == {}

    def test_unavailable_confirmation_keeps_pending(self, tmp_path):
        runtime, session, gateway, _ = make_runtime(tmp_path)
        session.set_verified("TOKEN", "A")
        session.register_pending("P1", "open_dispute")
        session.start_turn()
        gateway.errors["confirm_action"] = BankUnavailable(
            "bank API unavailable", code="connection_error"
        )
        result = runtime.call("confirm_action", pending_token="P1")
        assert result["error"] == "bank_unavailable"
        assert "P1" in session.pending
        assert session.tool_error_count == 1


class TestVerificationAndErrors:
    def test_verify_flow_omits_session_token_from_result_and_log(self, tmp_path):
        runtime, session, gateway, logger = make_runtime(tmp_path)
        gateway.responses["verify_start"] = {"status": "ok", "message": "sent"}
        gateway.responses["verify_complete"] = {
            "token": "SECRETTOKEN", "expires_at": "2026-01-01 00:15:00",
        }
        first = runtime.call("verify_customer", phone="+2348031234567")
        second = runtime.call(
            "verify_customer", phone="+2348031234567", otp="123456"
        )
        assert first["ok"] and second["ok"]
        assert session.verified is True
        assert session.token == "SECRETTOKEN"
        assert "SECRETTOKEN" not in json.dumps(second)
        assert "123456" not in json.dumps(second)
        raw = logger.path.read_text()
        assert "SECRETTOKEN" not in raw
        assert "123456" not in raw

    def test_invalid_phone_format_code_reaches_the_model(self, tmp_path):
        runtime, session, gateway, _ = make_runtime(tmp_path)
        gateway.errors["verify_start"] = BankRejected(
            "bank API rejected the request", 422, "invalid_phone_format"
        )
        result = runtime.call("verify_customer", phone="not-a-phone")
        assert result["error"] == "verification_failed"
        # The agent-side client exposes the bank's error code as this message;
        # the friendly body text is not forwarded (see report).
        assert "invalid_phone_format" in result["message"]
        assert session.failed_verifications == 1

    def test_wrong_otp_records_failed_verification(self, tmp_path):
        runtime, session, gateway, _ = make_runtime(tmp_path)
        gateway.errors["verify_complete"] = BankUnauthorized(
            "bank API unauthorized", 401, "invalid_or_expired"
        )
        result = runtime.call(
            "verify_customer", phone="+2348031234567", otp="000000"
        )
        assert result["error"] == "verification_failed"
        assert "invalid_or_expired" in result["message"]
        assert session.failed_verifications == 1
        assert session.verified is False

    def test_error_mapping_and_tool_error_counters(self, tmp_path):
        runtime, session, gateway, _ = make_runtime(tmp_path)
        session.set_verified("TOKEN", "A")

        gateway.errors["get_balance"] = BankNotFound(
            "bank API not found", 404, "not_found"
        )
        assert runtime.call("get_balance")["error"] == "not_found"

        gateway.errors["get_balance"] = BankRejected(
            "bank API rejected the request", 400, "duplicate_dispute"
        )
        rejected = runtime.call("get_balance")
        assert rejected["error"] == "rejected"
        assert "duplicate_dispute" in rejected["message"]

        gateway.errors["get_balance"] = BankUnavailable(
            "bank API unavailable", 500, "boom"
        )
        assert runtime.call("get_balance")["error"] == "bank_unavailable"
        assert session.tool_error_count == 1

        gateway.errors["get_balance"] = RuntimeError("bug")
        assert runtime.call("get_balance")["error"] == "tool_error"
        assert session.tool_error_count == 2

        gateway.errors["get_balance"] = BankUnauthorized(
            "bank API unauthorized", 401, "invalid_session"
        )
        assert runtime.call("get_balance")["error"] == "session_expired"
        assert session.verified is False


class TestSearchHandoffAndPropose:
    def test_search_failure_counts_and_query_is_hidden(self, tmp_path):
        search = lambda query: SimpleNamespace(
            status="no_relevant_result",
            message="No relevant policy information was found.",
            results=[],
            top_score=0.12,
            threshold=0.35,
        )
        runtime, session, _, logger = make_runtime(tmp_path, search=search)
        result = runtime.call("search_policy", query="capital of France")
        assert result["ok"] is True
        assert result["data"]["status"] == "no_relevant_result"
        assert session.failed_retrievals == 1
        assert session.consecutive_failed_retrievals == 1
        raw = logger.path.read_text()
        assert "capital of France" not in raw
        payload = json.loads(raw.splitlines()[-1])
        assert payload["inputs"] == {}
        assert payload["result"]["status"] == "no_relevant_result"
        assert payload["result"]["top_score"] == 0.12
        assert payload["result"]["threshold"] == 0.35

    def test_search_exception_is_a_tool_error(self, tmp_path):
        def broken(query):
            raise RuntimeError("policy store down")

        runtime, session, _, _ = make_runtime(tmp_path, search=broken)
        result = runtime.call("search_policy", query="anything")
        assert result["error"] == "tool_error"
        assert session.tool_error_count == 1

    def test_handoff_truncates_and_passes_token_when_verified(self, tmp_path):
        runtime, session, gateway, _ = make_runtime(tmp_path)
        session.set_verified("TOKEN", "A")
        gateway.responses["create_handoff"] = {"ticket_id": 1, "status": "open"}
        result = runtime.call(
            "handoff_to_human", summary="x" * 1200, reason="user_requested"
        )
        assert result["ok"] is True
        name, args, kwargs = gateway.calls[0]
        assert name == "create_handoff"
        assert len(args[0]) == 1000
        assert args[1] == "TOKEN"
        assert args[2] == "user_requested"

    def test_handoff_uses_no_token_when_unverified(self, tmp_path):
        runtime, _, gateway, _ = make_runtime(tmp_path)
        gateway.responses["create_handoff"] = {"ticket_id": 2, "status": "open"}
        runtime.call("handoff_to_human", summary="help")
        name, args, _ = gateway.calls[0]
        assert name == "create_handoff"
        assert args[1] is None

    def test_propose_registers_pending_and_masks_it_in_log(self, tmp_path):
        runtime, session, gateway, logger = make_runtime(tmp_path)
        session.set_verified("TOKEN", "A")
        gateway.responses["propose_dispute"] = {
            "pending_token": "abcdefgh",
            "summary": "Open a dispute for RUB-DB-002.",
        }
        result = runtime.call(
            "open_dispute", reference="RUB-DB-002", reason="double debit"
        )
        assert result["ok"] is True
        assert result["data"]["pending_token"] == "abcdefgh"
        assert "abcdefgh" in session.pending
        raw = logger.path.read_text()
        assert "abcdefgh" not in raw
        assert "abcd..." in raw
        assert "Open a dispute" in raw

    def test_get_balance_passes_session_token(self, tmp_path):
        runtime, session, gateway, _ = make_runtime(tmp_path)
        session.set_verified("TOKEN", "A")
        gateway.responses["get_balance"] = {"balance_kobo": 12345}
        result = runtime.call("get_balance")
        assert result["data"] == {"balance_kobo": 12345}
        assert gateway.calls[0][1] == ("TOKEN",)


def test_no_tool_schema_allows_identity_arguments():
    for name, spec in TOOL_SPECS.items():
        allowed = set(spec["allowed"])
        assert "customer_id" not in allowed, name
        assert "token" not in allowed, name
        assert "session_token" not in allowed, name
