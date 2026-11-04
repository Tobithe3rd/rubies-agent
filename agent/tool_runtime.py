from __future__ import annotations

import sys
from typing import Any, Callable, Optional

from core.clock import Clock, create_clock
from core.config import AppConfig
from core.interfaces import BankGateway
from agent.errors import (
    BankAPIError,
    BankNotFound,
    BankRejected,
    BankUnauthorized,
    BankUnavailable,
)
from agent.session import SessionState
from agent.tool_specs import validate_arguments


class ToolRuntime:
    """Validated, logged tool layer between the agent and the bank/RAG.

    The model never supplies the session token or customer_id. Every call goes
    through this class so argument validation, verification checks, error
    mapping and one JSONL log line per call happen in exactly one place.
    """

    def __init__(
        self,
        config: AppConfig,
        tools_cfg: dict,
        session: SessionState,
        gateway: BankGateway,
        search_policy: Callable[[str], Any],
        logger: Any,
        clock: Optional[Clock] = None,
    ):
        self.config = config
        self.tools_cfg = tools_cfg
        self.session = session
        self.gateway = gateway
        self.search_policy = search_policy
        self.logger = logger
        self.clock = clock or getattr(logger, "clock", None) or create_clock(config)
        self.debug = bool(config.settings.logging.debug)
        self.handoff_summary_max_chars = int(
            config.settings.bank_api.handoff_summary_max_chars
        )

    # --- public API ---

    def call(self, tool_name: str, **args) -> dict:
        start = self.clock.now()
        try:
            result = self._run(tool_name, args)
        except Exception as exc:  # defensive: _run should already map errors
            self.session.record_tool_error()
            result = self._error(tool_name, "tool_error", type(exc).__name__)
        duration_ms = int((self.clock.now() - start).total_seconds() * 1000)
        self._log(tool_name, args, result, duration_ms)
        return result

    # --- dispatch ---

    def _run(self, tool_name: str, args: dict) -> dict:
        tool_cfg = self.tools_cfg.get(tool_name)
        if tool_cfg is None:
            return self._error(tool_name, "unknown_tool", f"unknown tool: {tool_name}")
        if not getattr(tool_cfg, "enabled", False):
            return self._error(tool_name, "tool_disabled", f"tool disabled: {tool_name}")

        ok, code, message = validate_arguments(tool_name, args)
        if not ok:
            return self._error(tool_name, code, message)

        if (
            getattr(tool_cfg, "blocked_on_attachment_turns", False)
            and getattr(self.session, "turn_has_attachments", False)
        ):
            return self._error(
                tool_name,
                "confirmation_blocked_by_attachment",
                "Confirmation cannot be completed while the current message includes attachments. "
                "Ask the customer to reply with their confirmation in a new message without attachments.",
            )

        if getattr(tool_cfg, "requires_verified_session", False) and not self.session.verified:
            return self._error(tool_name, "not_verified", "customer is not verified")

        try:
            return self._execute(tool_name, args)
        except BankUnauthorized as exc:
            if tool_name == "verify_customer":
                self.session.record_failed_verification()
                return self._error(
                    tool_name, "verification_failed", self._bank_message(exc),
                    data=self._remaining(exc),
                )
            if getattr(tool_cfg, "requires_verified_session", False):
                self.session.clear_verified()
            return self._error(tool_name, "session_expired", "session expired; verify the customer again")
        except BankNotFound as exc:
            return self._error(tool_name, "not_found", self._bank_message(exc))
        except BankRejected as exc:
            if tool_name == "verify_customer":
                self.session.record_failed_verification()
                return self._error(
                    tool_name, "verification_failed", self._bank_message(exc),
                    data=self._remaining(exc),
                )
            return self._error(tool_name, "rejected", self._bank_message(exc))
        except BankUnavailable as exc:
            self.session.record_tool_error()
            return self._error(tool_name, "bank_unavailable", self._bank_message(exc))
        except Exception as exc:
            self.session.record_tool_error()
            return self._error(tool_name, "tool_error", self._safe(str(exc)) or type(exc).__name__)

    def _execute(self, tool_name: str, args: dict) -> dict:
        if tool_name == "verify_customer":
            return self._verify(args)
        if tool_name == "open_dispute":
            return self._propose(tool_name, "propose_dispute", args)
        if tool_name == "block_card":
            return self._propose(tool_name, "propose_card_block", args)
        if tool_name == "confirm_action":
            return self._confirm(args)
        if tool_name == "search_policy":
            return self._search(args)
        if tool_name == "handoff_to_human":
            return self._handoff(args)
        if tool_name == "get_balance":
            return self._ok(tool_name, self.gateway.get_balance(self.session.token))
        if tool_name == "get_mini_statement":
            return self._ok(
                tool_name,
                self.gateway.get_mini_statement(self.session.token, limit=args.get("limit")),
            )
        if tool_name == "get_transaction_status":
            return self._ok(
                tool_name,
                self.gateway.get_transaction_status(self.session.token, args["reference"]),
            )
        if tool_name == "check_loan_eligibility":
            return self._ok(
                tool_name,
                self.gateway.check_loan_eligibility(self.session.token, args["amount"]),
            )
        if tool_name == "get_loan_status":
            return self._ok(tool_name, self.gateway.get_loan_status(self.session.token))
        return self._error(tool_name, "unknown_tool", f"unknown tool: {tool_name}")

    # --- tool implementations ---

    def _verify(self, args: dict) -> dict:
        phone = args["phone"]
        otp = args.get("otp")
        if otp:
            response = self.gateway.verify_complete(phone, otp)
            token = response.get("token")
            if not token:
                self.session.record_failed_verification()
                return self._error("verify_customer", "verification_failed", "verification did not return a session token")
            name = (
                response.get("customer_first_name")
                or response.get("full_name")
                or response.get("name")
            )
            self.session.set_verified(token, name)
            data = {"verified": True}
            if name:
                data["customer_first_name"] = name
            return self._ok("verify_customer", data)

        response = self.gateway.verify_start(phone)
        return self._ok("verify_customer", response)

    def _propose(self, tool_name: str, gateway_method: str, args: dict) -> dict:
        if gateway_method == "propose_dispute":
            response = self.gateway.propose_dispute(
                self.session.token, args["reference"], args["reason"]
            )
        else:
            response = self.gateway.propose_card_block(self.session.token, args["last4"])

        pending = response.get("pending_token")
        if not pending:
            # e.g. block_card on an already-blocked card: the API's status is the answer.
            return self._ok(tool_name, response)

        self.session.register_pending(pending, tool_name)
        return self._ok(
            tool_name,
            {
                "summary": response.get("summary", ""),
                "pending_token": pending,
                "message": "Nothing has changed yet. Ask the customer to confirm this action.",
            },
        )

    def _confirm(self, args: dict) -> dict:
        pending = args["pending_token"]
        allowed, reason = self.session.can_confirm(pending)
        if not allowed:
            return self._error(
                "confirm_action", "confirmation_not_allowed",
                "confirmation is not allowed", data={"reason": reason},
            )
        try:
            response = self.gateway.confirm_action(self.session.token, pending)
        except BankRejected:
            # The bank says the token is invalid/expired/used: drop our local copy.
            self.session.consume_pending(pending)
            raise
        except BankUnavailable:
            # Leave the pending action so a retry can still use it.
            raise
        self.session.consume_pending(pending)
        return self._ok("confirm_action", response)

    def _search(self, args: dict) -> dict:
        result = self.search_policy(args["query"])
        self.session.record_retrieval(result.status)
        data = {
            "status": result.status,
            "message": result.message,
            "results": result.results,
            "top_score": result.top_score,
            "threshold": result.threshold,
            "result_count": len(result.results),
        }
        return self._ok("search_policy", data)

    def _handoff(self, args: dict) -> dict:
        summary = str(args.get("summary", ""))[: self.handoff_summary_max_chars]
        token = self.session.token if self.session.verified else None
        response = self.gateway.create_handoff(
            summary, token=token, reason=args.get("reason")
        )
        return self._ok("handoff_to_human", response)

    # --- result helpers ---

    @staticmethod
    def _ok(tool_name: str, data: Any) -> dict:
        return {"ok": True, "tool": tool_name, "data": data}

    @staticmethod
    def _error(tool_name: str, code: str, message: str, data: Any = None) -> dict:
        result = {"ok": False, "tool": tool_name, "error": code, "message": message}
        if data:
            result["data"] = data
        return result

    def _safe(self, text: str) -> str:
        for secret in [self.session.token] + list(self.session.pending):
            if secret:
                text = text.replace(secret, "***")
        return text

    @staticmethod
    def _bank_message(exc: BankAPIError) -> str:
        message = str(exc)
        code = getattr(exc, "code", None)
        if code and code not in message:
            message = f"{message} ({code})"
        return message

    @staticmethod
    def _remaining(exc: BankAPIError) -> Optional[dict]:
        remaining = getattr(exc, "remaining_attempts", None)
        if remaining is None:
            return None
        return {"remaining_attempts": remaining}

    # --- logging ---

    def _log(self, tool_name: str, args: dict, result: dict, duration_ms: int) -> None:
        inputs: dict = dict(args)
        result_for_log: Any = result.get("data")
        if tool_name == "search_policy":
            if not self.debug:
                inputs.pop("query", None)
            data = result.get("data") or {}
            result_for_log = {
                "status": data.get("status"),
                "top_score": data.get("top_score"),
                "threshold": data.get("threshold"),
                "result_count": data.get("result_count"),
            }
            # Log the top result (never the query) so acceptance checks can
            # assert the cited chunk and the retrieved figures from the log.
            results = data.get("results") or []
            if results:
                top = results[0]
                result_for_log["top_result"] = {
                    "chunk_id": top.get("chunk_id"),
                    "citation": top.get("citation"),
                    "doc_title": top.get("doc_title"),
                    "section_heading": top.get("section_heading"),
                    "text": top.get("text"),
                    "score": top.get("score"),
                }
        error = None
        if not result.get("ok"):
            error = {"code": result.get("error"), "message": result.get("message")}

        try:
            self.logger.log(
                session_id=self.session.session_id,
                tool=tool_name,
                inputs=inputs,
                ok=bool(result.get("ok")),
                result=result_for_log,
                error=error,
                duration_ms=duration_ms,
            )
        except Exception as exc:
            print(f"warning: tool log failed: {exc}", file=sys.stderr)
