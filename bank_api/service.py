from __future__ import annotations

import hashlib
import json
import secrets
import datetime
from typing import Callable, Optional

from core.interfaces import DataStore


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _naira(kobo: int) -> float:
    return kobo / 100


class BankService:
    """Read and protected-action operations for one verified customer.

    Every method takes customer_id first and only ever reads/writes rows for
    that customer. All calls write an audit row with no token or code in params.
    """

    def __init__(self, datastore: DataStore, cfg,
                 clock: Optional[Callable[[], datetime.datetime]] = None):
        self.ds = datastore
        self.cfg = cfg
        bank = cfg.settings.bank_api
        self.pending_ttl_seconds = bank.pending_action_ttl_seconds
        self.mini_max = bank.mini_statement_max_n
        self.mini_default = bank.mini_statement_default_n
        self.elig = bank.eligibility
        self._clock = clock or datetime.datetime.now

    def _now(self) -> datetime.datetime:
        return self._clock()

    def _audit(self, customer_id: Optional[int], action: str, params: dict, outcome: str) -> None:
        self.ds.write_audit(None, customer_id, action, json.dumps(params), outcome)

    @staticmethod
    def _session_ref(session_token: Optional[str]) -> Optional[str]:
        if not session_token:
            return None
        return _sha256_hex(session_token)[:8]

    # --- reads ---

    def get_balance(self, customer_id: int) -> dict:
        account = self.ds.get_account(customer_id)
        if account is None:
            self._audit(customer_id, "get_balance", {}, "no_account")
            return {"error": "not_found"}
        self._audit(customer_id, "get_balance", {}, "ok")
        return {
            "balance_kobo": account["balance_kobo"],
            "balance_naira": _naira(account["balance_kobo"]),
            "account_number": account["account_number"],
            "account_type": account["account_type"],
            "kyc_tier": account["kyc_tier"],
            "status": account["status"],
        }

    def get_mini_statement(self, customer_id: int, n: Optional[int] = None) -> dict:
        if n is None:
            n = self.mini_default
        n = max(1, min(int(n), self.mini_max))
        rows = self.ds.list_transactions(customer_id, limit=n)
        self._audit(customer_id, "get_mini_statement", {"n": n}, "ok")
        return {
            "n": n,
            "transactions": [
                {
                    "reference": r["reference"],
                    "direction": r["direction"],
                    "amount_kobo": r["amount_kobo"],
                    "amount_naira": _naira(r["amount_kobo"]),
                    "status": r["status"],
                    "narration": r["narration"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ],
        }

    def get_transaction_status(self, customer_id: int, reference: str) -> dict:
        txn = self.ds.get_transaction_by_reference(customer_id, reference)
        if txn is None:
            # Generic: never reveal whether another customer's reference exists.
            self._audit(customer_id, "get_transaction_status", {"reference": reference}, "not_found")
            return {"error": "not_found"}
        self._audit(customer_id, "get_transaction_status", {"reference": reference}, "ok")
        return {
            "reference": txn["reference"],
            "direction": txn["direction"],
            "amount_kobo": txn["amount_kobo"],
            "amount_naira": _naira(txn["amount_kobo"]),
            "status": txn["status"],
            "narration": txn["narration"],
            "failure_reason": txn["failure_reason"],
            "created_at": txn["created_at"],
        }

    # --- protected actions (two-step) ---

    def propose_dispute(self, customer_id: int, session_token: str, reference: str, reason: str) -> dict:
        txn = self.ds.get_transaction_by_reference(customer_id, reference)
        if txn is None:
            self._audit(customer_id, "propose_dispute", {"reference": reference}, "not_found")
            return {"error": "not_found"}
        existing = self.ds.get_open_dispute_for_transaction(customer_id, txn["id"])
        if existing is not None:
            self._audit(customer_id, "propose_dispute", {"reference": reference}, "duplicate_dispute")
            return {"error": "duplicate_dispute"}
        token = secrets.token_urlsafe(32)
        expires = self._now() + datetime.timedelta(seconds=self.pending_ttl_seconds)
        payload = {"transaction_id": txn["id"], "reference": txn["reference"], "reason": reason}
        self.ds.create_pending_action(
            customer_id, _sha256_hex(token), self._session_ref(session_token), "dispute",
            json.dumps(payload), expires.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._audit(customer_id, "propose_dispute", {"reference": reference}, "proposed")
        return {
            "pending_token": token,
            "expires_at": expires.strftime("%Y-%m-%d %H:%M:%S"),
            "summary": (
                f"Open a dispute for {txn['reference']} "
                f"(₦{_naira(txn['amount_kobo']):,.0f}). "
                "Confirm to proceed; nothing has changed yet."
            ),
        }

    def propose_block_card(self, customer_id: int, session_token: str, last4: str) -> dict:
        card = self.ds.get_card(customer_id, last4)
        if card is None:
            self._audit(customer_id, "propose_block_card", {"last4": last4}, "not_found")
            return {"error": "not_found"}
        if card["status"] == "blocked":
            self._audit(customer_id, "propose_block_card", {"last4": last4}, "already_blocked")
            return {"status": "already_blocked", "last4": last4}
        token = secrets.token_urlsafe(32)
        expires = self._now() + datetime.timedelta(seconds=self.pending_ttl_seconds)
        payload = {"last4": last4}
        self.ds.create_pending_action(
            customer_id, _sha256_hex(token), self._session_ref(session_token), "block_card",
            json.dumps(payload), expires.strftime("%Y-%m-%d %H:%M:%S"),
        )
        self._audit(customer_id, "propose_block_card", {"last4": last4}, "proposed")
        return {
            "pending_token": token,
            "expires_at": expires.strftime("%Y-%m-%d %H:%M:%S"),
            "summary": f"Block card ending {last4}. Confirm to proceed; nothing has changed yet.",
        }

    def confirm_action(self, customer_id: int, session_token: str, token: str) -> dict:
        generic_error = {"error": "invalid_or_expired"}
        if not token:
            self._audit(customer_id, "confirm_action", {}, "invalid")
            return generic_error
        token_hash = _sha256_hex(token)
        pending = self.ds.get_pending_action_by_token_hash(customer_id, token_hash)
        if pending is None:
            self._audit(customer_id, "confirm_action", {}, "invalid")
            return generic_error
        if pending.get("session_ref") is not None and pending["session_ref"] != self._session_ref(session_token):
            self._audit(customer_id, "confirm_action", {}, "invalid")
            return generic_error
        if pending["used"]:
            self._audit(customer_id, "confirm_action", {"action_type": pending["action_type"]}, "used")
            return generic_error
        expires_at = datetime.datetime.strptime(pending["expires_at"], "%Y-%m-%d %H:%M:%S")
        if self._now() > expires_at:
            self._audit(customer_id, "confirm_action", {"action_type": pending["action_type"]}, "expired")
            return generic_error

        payload = json.loads(pending["payload_json"])
        if pending["action_type"] == "dispute":
            dispute = self.ds.create_dispute(customer_id, payload["transaction_id"], payload["reason"])
            self.ds.mark_pending_action_used(customer_id, pending["id"])
            self._audit(customer_id, "confirm_action", {"action_type": "dispute"}, "executed")
            return {"status": "dispute_opened", "dispute_id": dispute["id"],
                    "reference": payload["reference"]}
        if pending["action_type"] == "block_card":
            card = self.ds.block_card(customer_id, payload["last4"])
            self.ds.mark_pending_action_used(customer_id, pending["id"])
            self._audit(customer_id, "confirm_action", {"action_type": "block_card"}, "executed")
            return {"status": "card_blocked", "last4": payload["last4"],
                    "card_status": card.get("status")}
        self._audit(customer_id, "confirm_action", {}, "invalid")
        return generic_error

    # --- loans ---

    def check_loan_eligibility(self, customer_id: int, requested_amount_naira: int) -> dict:
        inputs = self.ds.get_loan_inputs(customer_id)
        reasons: list[str] = []
        rules: list[dict] = []

        if not inputs:
            self._audit(customer_id, "check_loan_eligibility", {}, "no_account")
            return {"decision": "not_eligible", "reasons": ["No account found for this customer."], "rules": []}

        age_days = inputs.get("account_age_days", 0)
        avg_inflow_kobo = inputs.get("avg_monthly_inflow_kobo", 0)
        existing_loan = inputs.get("existing_loan", False)
        kyc_tier = inputs.get("kyc_tier", "tier1")
        avg_inflow_naira = _naira(avg_inflow_kobo)

        def rule(name, passed, ok_reason, fail_reason):
            rules.append({"rule": name, "passed": passed})
            reasons.append(ok_reason if passed else fail_reason)
            return passed

        not_eligible = False
        needs_review = False

        if existing_loan:
            not_eligible = True
            rules.append({"rule": "no_existing_loan", "passed": False})
            reasons.append("You already have an active loan, so a new loan is not available.")
        else:
            rules.append({"rule": "no_existing_loan", "passed": True})

        if age_days < self.elig.min_account_age_days:
            not_eligible = True
            rules.append({"rule": "min_account_age", "passed": False})
            reasons.append(
                f"Your account is {age_days} days old; at least "
                f"{self.elig.min_account_age_days} days is required."
            )
        else:
            rules.append({"rule": "min_account_age", "passed": True})

        if avg_inflow_naira < self.elig.min_avg_monthly_inflow_naira:
            not_eligible = True
            rules.append({"rule": "min_avg_monthly_inflow", "passed": False})
            reasons.append(
                f"Your average monthly inflow (₦{avg_inflow_naira:,.0f}) is below the "
                f"required ₦{self.elig.min_avg_monthly_inflow_naira:,.0f}."
            )
        else:
            rules.append({"rule": "min_avg_monthly_inflow", "passed": True})

        if requested_amount_naira > self.elig.requested_amount_max_naira:
            not_eligible = True
            rules.append({"rule": "requested_amount_max", "passed": False})
            reasons.append(
                f"The requested amount exceeds the maximum of "
                f"₦{self.elig.requested_amount_max_naira:,.0f}."
            )
        else:
            rules.append({"rule": "requested_amount_max", "passed": True})

        if kyc_tier not in self.elig.kyc_tiers_allowed:
            needs_review = True
            rules.append({"rule": "kyc_tier", "passed": False})
            reasons.append(f"Your KYC tier ({kyc_tier}) needs review before a loan.")
        else:
            rules.append({"rule": "kyc_tier", "passed": True})

        max_by_inflow = avg_inflow_naira * self.elig.max_loan_to_inflow_multiple
        if requested_amount_naira > max_by_inflow:
            needs_review = True
            rules.append({"rule": "loan_to_inflow_multiple", "passed": False})
            reasons.append(
                f"The requested amount is high relative to your inflow; a review is needed."
            )
        else:
            rules.append({"rule": "loan_to_inflow_multiple", "passed": True})

        if not_eligible:
            decision = "not_eligible"
        elif needs_review:
            decision = "needs_review"
        else:
            decision = "eligible"
            reasons.append("You meet the eligibility requirements.")

        self._audit(customer_id, "check_loan_eligibility",
                    {"requested_amount_naira": requested_amount_naira}, decision)
        return {"decision": decision, "reasons": reasons, "rules": rules}

    def get_loan_status(self, customer_id: int) -> dict:
        loan = self.ds.get_active_loan(customer_id)
        if loan is None:
            self._audit(customer_id, "get_loan_status", {}, "no_active_loan")
            return {"status": "no_active_loan"}
        self._audit(customer_id, "get_loan_status", {}, "ok")
        return {
            "status": loan["status"],
            "outstanding_kobo": loan["outstanding_kobo"],
            "outstanding_naira": _naira(loan["outstanding_kobo"]),
            "next_repayment_date": loan["next_repayment_date"],
            "next_repayment_kobo": loan["next_repayment_kobo"],
            "next_repayment_naira": _naira(loan["next_repayment_kobo"]),
        }
