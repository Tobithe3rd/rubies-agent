from __future__ import annotations

from typing import Optional
from urllib.parse import quote

import httpx

from core.config import AppConfig
from core.factories import register
from core.interfaces import BankGateway, HealthStatus
from agent.errors import (
    BankAPIError,
    BankNotFound,
    BankRejected,
    BankUnauthorized,
    BankUnavailable,
)


@register("bank_gateway", "http")
class HttpBankGateway(BankGateway):
    """HTTP implementation of BankGateway for the real mock bank API.

    The session token travels only in `Authorization: Bearer <token>`.
    base_url comes from BANK_API_URL; timeout from
    settings.agent.bank_api_timeout_seconds. A client/transport can be injected
    for tests. No retries are made on propose/confirm (or any call).
    """

    def __init__(self, cfg: AppConfig, env=None, client: Optional[httpx.Client] = None):
        self.cfg = cfg
        self.env = env or cfg.env
        self.base_url = str(self.env.BANK_API_URL).rstrip("/")
        self.timeout = cfg.settings.agent.bank_api_timeout_seconds
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            timeout=float(self.timeout),
        )

    # --- operational helpers (not part of BankGateway's bank contract) ---

    def describe(self) -> str:
        return f"http bank gateway ({self.base_url})"

    def healthcheck(self) -> HealthStatus:
        try:
            response = self._client.get("/health", timeout=float(self.timeout))
            return HealthStatus(
                "bank_gateway",
                response.status_code == 200,
                f"HTTP {response.status_code}",
            )
        except Exception as exc:
            return HealthStatus("bank_gateway", False, type(exc).__name__)

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    # --- request plumbing ---

    @staticmethod
    def _redact(text: str, secrets: list[str]) -> str:
        for secret in secrets:
            if secret:
                text = text.replace(secret, "[redacted]")
        return text

    @staticmethod
    def _code(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except Exception:
            return "http_error"
        if isinstance(payload, dict):
            code = payload.get("error") or payload.get("detail") or "http_error"
        else:
            code = "http_error"
        if isinstance(code, list):
            return "validation_error"
        return str(code)

    def _request(self, method: str, path: str, token: Optional[str] = None,
                 redact: Optional[list[str]] = None, **kwargs):
        secrets = [s for s in ([token] + (redact or [])) if s]
        headers = dict(kwargs.pop("headers", {}))
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            response = self._client.request(method, path, headers=headers, **kwargs)
        except httpx.TimeoutException:
            raise BankUnavailable("bank API timed out", code="timeout") from None
        except httpx.TransportError:
            raise BankUnavailable("bank API unavailable", code="connection_error") from None

        if response.status_code >= 500:
            code = self._redact(self._code(response), secrets)
            raise BankUnavailable(
                "bank API unavailable",
                status_code=response.status_code,
                code=code,
            )
        if response.status_code == 401:
            code = self._redact(self._code(response), secrets)
            raise BankUnauthorized(
                "bank API unauthorized",
                status_code=401,
                code=code,
            )
        if response.status_code == 404:
            code = self._redact(self._code(response), secrets)
            raise BankNotFound(
                "bank API not found",
                status_code=404,
                code=code,
            )
        if 400 <= response.status_code < 500:
            code = self._redact(self._code(response), secrets)
            raise BankRejected(
                "bank API rejected the request",
                status_code=response.status_code,
                code=code,
            )
        try:
            return response.json()
        except ValueError:
            raise BankUnavailable(
                "bank API returned invalid JSON",
                status_code=response.status_code,
                code="invalid_json",
            ) from None

    # --- verification ---

    def verify_start(self, phone: str) -> dict:
        return self._request("POST", "/auth/request-otp", json={"phone": phone})

    def verify_complete(self, phone: str, otp: str) -> dict:
        return self._request(
            "POST", "/auth/verify",
            json={"phone": phone, "code": otp},
            redact=[otp],
        )

    # --- reads ---

    def get_balance(self, token: str) -> dict:
        return self._request("GET", "/account/balance", token=token)

    def get_mini_statement(self, token: str, limit: Optional[int] = None) -> dict:
        params = {"n": limit} if limit is not None else None
        return self._request("GET", "/account/statement", token=token, params=params)

    def get_transaction_status(self, token: str, reference: str) -> dict:
        return self._request(
            "GET", f"/transactions/{quote(reference, safe='')}", token=token
        )

    # --- state changes (no retries) ---

    def propose_dispute(self, token: str, reference: str, reason: str) -> dict:
        return self._request(
            "POST", "/disputes/propose", token=token,
            json={"reference": reference, "reason": reason},
        )

    def propose_card_block(self, token: str, last4: str) -> dict:
        return self._request(
            "POST", "/cards/block/propose", token=token, json={"last4": last4}
        )

    def confirm_action(self, token: str, pending_token: str) -> dict:
        return self._request(
            "POST", "/actions/confirm", token=token,
            json={"token": pending_token},
            redact=[pending_token],
        )

    # --- loans ---

    def check_loan_eligibility(self, token: str, amount: int) -> dict:
        return self._request(
            "POST", "/loans/eligibility", token=token,
            json={"requested_amount_naira": amount},
        )

    def get_loan_status(self, token: str) -> dict:
        return self._request("GET", "/loans/status", token=token)

    # --- handoff (optional auth) ---

    def create_handoff(self, summary: str, token: Optional[str] = None,
                       reason: Optional[str] = None) -> dict:
        return self._request(
            "POST", "/handoff", token=token,
            json={"summary": summary, "reason": reason or "other"},
        )
