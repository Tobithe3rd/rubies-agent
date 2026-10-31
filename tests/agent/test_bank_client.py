import inspect
from types import SimpleNamespace

import httpx
import pytest

from core.interfaces import BankGateway
from agent.bank_client import HttpBankGateway
from agent.errors import (
    BankAPIError,
    BankNotFound,
    BankRejected,
    BankUnauthorized,
    BankUnavailable,
)


def fake_cfg(timeout=2):
    return SimpleNamespace(
        settings=SimpleNamespace(
            agent=SimpleNamespace(bank_api_timeout_seconds=timeout),
        ),
        env=SimpleNamespace(BANK_API_URL="http://bank.test"),
    )


def make_gateway(handler, cfg=None):
    cfg = cfg or fake_cfg()
    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        base_url="http://bank.test",
        timeout=2,
    )
    return HttpBankGateway(cfg, cfg.env, client=client), client


class TestSuccessAndHeaders:
    def test_success_returns_json_unchanged(self):
        gw, client = make_gateway(
            lambda request: httpx.Response(200, json={"balance_kobo": 123})
        )
        try:
            assert gw.get_balance("TOKEN123") == {"balance_kobo": 123}
        finally:
            client.close()

    def test_session_token_uses_bearer_header(self):
        seen = {}

        def handler(request):
            seen["authorization"] = request.headers.get("authorization")
            return httpx.Response(200, json={"ok": True})

        gw, client = make_gateway(handler)
        try:
            gw.get_balance("TOKEN123")
        finally:
            client.close()
        assert seen["authorization"] == "Bearer TOKEN123"

    def test_verify_start_has_no_authorization(self):
        seen = {}

        def handler(request):
            seen["authorization"] = request.headers.get("authorization")
            return httpx.Response(200, json={"status": "ok"})

        gw, client = make_gateway(handler)
        try:
            gw.verify_start("+2348031234567")
        finally:
            client.close()
        assert seen["authorization"] is None

    def test_mini_statement_limit_is_sent_as_n(self):
        seen = []

        def handler(request):
            seen.append(dict(request.url.params))
            return httpx.Response(200, json={"transactions": []})

        gw, client = make_gateway(handler)
        try:
            gw.get_mini_statement("TOKEN123", limit=7)
            gw.get_mini_statement("TOKEN123")
        finally:
            client.close()
        assert seen[0] == {"n": "7"}
        assert seen[1] == {}


class TestErrorMapping:
    def test_401_raises_bank_unauthorized(self):
        gw, client = make_gateway(
            lambda request: httpx.Response(401, json={"detail": "invalid_session"})
        )
        try:
            with pytest.raises(BankUnauthorized) as exc:
                gw.get_balance("SECRET123")
        finally:
            client.close()
        assert exc.value.status_code == 401
        assert exc.value.code == "invalid_session"
        assert "SECRET123" not in str(exc.value)
        assert "SECRET123" not in repr(exc.value)

    def test_404_raises_bank_not_found_without_amount(self):
        gw, client = make_gateway(
            lambda request: httpx.Response(404, json={"error": "not_found"})
        )
        try:
            with pytest.raises(BankNotFound) as exc:
                gw.get_transaction_status("SECRET123", "RUB-03-000037")
        finally:
            client.close()
        assert exc.value.status_code == 404
        text = (str(exc.value) + repr(exc.value)).lower()
        assert "amount" not in text
        assert "50000" not in text

    def test_422_raises_bank_rejected_and_redacts_tokens(self):
        gw, client = make_gateway(
            lambda request: httpx.Response(
                422,
                json={"detail": [{"loc": ["body", "token"], "msg": "bad",
                                  "input": "PENDING123"}]},
            )
        )
        try:
            with pytest.raises(BankRejected) as exc:
                gw.confirm_action("SECRET123", "PENDING123")
        finally:
            client.close()
        assert exc.value.status_code == 422
        text = str(exc.value) + repr(exc.value)
        assert "SECRET123" not in text
        assert "PENDING123" not in text

    def test_400_raises_bank_rejected(self):
        gw, client = make_gateway(
            lambda request: httpx.Response(400, json={"error": "invalid_or_expired"})
        )
        try:
            with pytest.raises(BankRejected) as exc:
                gw.confirm_action("SECRET123", "PENDING123")
        finally:
            client.close()
        assert exc.value.status_code == 400
        assert "SECRET123" not in str(exc.value)

    def test_500_raises_bank_unavailable(self):
        gw, client = make_gateway(
            lambda request: httpx.Response(500, json={"error": "boom"})
        )
        try:
            with pytest.raises(BankUnavailable) as exc:
                gw.get_balance("SECRET123")
        finally:
            client.close()
        assert exc.value.status_code == 500
        assert "SECRET123" not in str(exc.value)

    def test_timeout_raises_bank_unavailable(self):
        def handler(request):
            raise httpx.ReadTimeout("slow", request=request)

        gw, client = make_gateway(handler)
        try:
            with pytest.raises(BankUnavailable):
                gw.get_balance("SECRET123")
        finally:
            client.close()

    def test_connection_error_raises_bank_unavailable(self):
        def handler(request):
            raise httpx.ConnectError("refused", request=request)

        gw, client = make_gateway(handler)
        try:
            with pytest.raises(BankUnavailable):
                gw.get_balance("SECRET123")
        finally:
            client.close()


class TestNoRetries:
    def test_propose_dispute_is_not_retried(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"pending_token": "p"})

        gw, client = make_gateway(handler)
        try:
            gw.propose_dispute("SECRET123", "RUB-DB-002", "double debit")
        finally:
            client.close()
        assert len(calls) == 1

    def test_confirm_action_is_not_retried(self):
        calls = []

        def handler(request):
            calls.append(request)
            return httpx.Response(200, json={"status": "dispute_opened"})

        gw, client = make_gateway(handler)
        try:
            gw.confirm_action("SECRET123", "PENDING123")
        finally:
            client.close()
        assert len(calls) == 1


class TestHandoffAndConfig:
    def test_handoff_without_token_has_no_auth_and_defaults_reason(self):
        seen = {}

        def handler(request):
            seen["authorization"] = request.headers.get("authorization")
            seen["body"] = request.content
            return httpx.Response(200, json={"ticket_id": 1, "status": "open"})

        gw, client = make_gateway(handler)
        try:
            gw.create_handoff("please help")
        finally:
            client.close()
        assert seen["authorization"] is None
        assert b'"reason":"other"' in seen["body"]

    def test_handoff_with_token_has_auth(self):
        seen = {}

        def handler(request):
            seen["authorization"] = request.headers.get("authorization")
            return httpx.Response(200, json={"ticket_id": 1})

        gw, client = make_gateway(handler)
        try:
            gw.create_handoff("please help", token="TOKEN123", reason="user_requested")
        finally:
            client.close()
        assert seen["authorization"] == "Bearer TOKEN123"

    def test_base_url_and_timeout_come_from_config(self):
        cfg = fake_cfg(timeout=3)
        gw = HttpBankGateway(cfg, cfg.env)
        try:
            assert gw.base_url == "http://bank.test"
            assert gw.timeout == 3
        finally:
            gw.close()


class TestSignatures:
    def test_no_method_has_customer_id(self):
        methods = {
            name: fn
            for name, fn in inspect.getmembers(BankGateway, predicate=inspect.isfunction)
            if not name.startswith("_")
        }
        assert len(methods) == 11
        for name, fn in methods.items():
            params = inspect.signature(fn).parameters
            assert "customer_id" not in params, f"{name} has customer_id"

    def test_token_is_the_only_session_identity(self):
        verify = {"verify_start", "verify_complete"}
        for name, fn in inspect.getmembers(BankGateway, predicate=inspect.isfunction):
            if name.startswith("_") or name in verify:
                continue
            params = inspect.signature(fn).parameters
            assert "token" in params, f"{name} is missing token"
            assert "phone" not in params, f"{name} unexpectedly takes phone"
