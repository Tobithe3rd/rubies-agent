from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from core.config import load_config
from core.factories import create_datastore, create_otp_sender
from bank_api.auth import AuthService
from bank_api.service import BankService


class RequestOTPBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Format is validated after normalisation in AuthService so spaced and
    # hyphenated input is accepted without weakening the phone pattern.
    phone: str


class VerifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str
    code: str = Field(min_length=4, max_length=10, pattern=r"^[0-9]+$")


class ProposeDisputeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reference: str = Field(min_length=1, max_length=64)
    reason: str = Field(min_length=1, max_length=500)


class BlockCardBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    last4: str = Field(pattern=r"^[0-9]{4}$")


class ConfirmBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=256)


class EligibilityBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    requested_amount_naira: int = Field(ge=1)


class HandoffBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(max_length=10000)
    reason: str = Field(min_length=1, max_length=64)


def create_app(config_dir: str = "config") -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = load_config(config_dir=config_dir)
        datastore = create_datastore(cfg)
        datastore.init_schema()
        otp_sender = create_otp_sender(cfg)
        app.state.cfg = cfg
        app.state.datastore = datastore
        app.state.auth = AuthService(datastore, cfg, cfg.env, otp_sender=otp_sender)
        app.state.bank = BankService(datastore, cfg)
        yield
        try:
            datastore.close()
        except Exception:
            pass

    app = FastAPI(lifespan=lifespan)

    def _bearer(authorization: Optional[str]) -> Optional[str]:
        if not authorization or not authorization.lower().startswith("bearer "):
            return None
        return authorization.split(" ", 1)[1].strip()

    def require_session(authorization: Optional[str] = Header(default=None)) -> int:
        token = _bearer(authorization)
        customer_id = app.state.auth.resolve_session(token) if token else None
        if customer_id is None:
            raise HTTPException(status_code=401, detail="invalid_session")
        return customer_id

    def require_session_ctx(authorization: Optional[str] = Header(default=None)) -> dict:
        token = _bearer(authorization)
        customer_id = app.state.auth.resolve_session(token) if token else None
        if customer_id is None:
            raise HTTPException(status_code=401, detail="invalid_session")
        return {"customer_id": customer_id, "token": token}

    @app.get("/health")
    def health():
        return {"status": "ok"}

    # --- auth ---

    def phone_error(result: dict):
        return JSONResponse(
            status_code=422,
            content={"error": result["error"], "message": result["message"]},
        )

    @app.post("/auth/request-otp")
    def request_otp(body: RequestOTPBody):
        result = app.state.auth.request_otp(body.phone)
        if result.get("error") == "invalid_phone_format":
            return phone_error(result)
        return result

    @app.post("/auth/verify")
    def verify(body: VerifyBody):
        result = app.state.auth.verify_otp(body.phone, body.code)
        if result.get("error") == "invalid_phone_format":
            return phone_error(result)
        if result.get("ok"):
            return {"token": result["token"], "expires_at": result["expires_at"]}
        if result.get("error") == "otp_locked":
            return JSONResponse(status_code=429, content={"error": "otp_locked"})
        return JSONResponse(status_code=401, content={"error": "invalid_or_expired"})

    @app.post("/auth/logout")
    def logout(authorization: Optional[str] = Header(default=None),
               customer_id: int = Depends(require_session)):
        token = _bearer(authorization)
        app.state.auth.logout(token)
        return {"status": "ok"}

    @app.get("/me")
    def me(customer_id: int = Depends(require_session)):
        customer = app.state.datastore.get_customer(customer_id)
        if customer is None:
            raise HTTPException(status_code=401, detail="invalid_session")
        return {"customer_id": customer["id"], "full_name": customer["full_name"]}

    # --- account reads ---

    @app.get("/account/balance")
    def balance(customer_id: int = Depends(require_session)):
        result = app.state.bank.get_balance(customer_id)
        if result.get("error") == "not_found":
            return JSONResponse(status_code=404, content={"error": "not_found"})
        return result

    @app.get("/account/statement")
    def statement(n: Optional[int] = Query(default=None, ge=1),
                  customer_id: int = Depends(require_session)):
        return app.state.bank.get_mini_statement(customer_id, n)

    @app.get("/transactions/{reference}")
    def transaction_status(reference: str, customer_id: int = Depends(require_session)):
        result = app.state.bank.get_transaction_status(customer_id, reference)
        if result.get("error") == "not_found":
            return JSONResponse(status_code=404, content={"error": "not_found"})
        return result

    # --- protected actions ---

    @app.post("/disputes/propose")
    def propose_dispute(body: ProposeDisputeBody, ctx: dict = Depends(require_session_ctx)):
        result = app.state.bank.propose_dispute(ctx["customer_id"], ctx["token"], body.reference, body.reason)
        if result.get("error") == "not_found":
            return JSONResponse(status_code=404, content={"error": "not_found"})
        if result.get("error") == "duplicate_dispute":
            return JSONResponse(status_code=409, content={"error": "duplicate_dispute"})
        return result

    @app.post("/cards/block/propose")
    def propose_block_card(body: BlockCardBody, ctx: dict = Depends(require_session_ctx)):
        result = app.state.bank.propose_block_card(ctx["customer_id"], ctx["token"], body.last4)
        if result.get("error") == "not_found":
            return JSONResponse(status_code=404, content={"error": "not_found"})
        return result

    @app.post("/actions/confirm")
    def confirm_action(body: ConfirmBody, ctx: dict = Depends(require_session_ctx)):
        result = app.state.bank.confirm_action(ctx["customer_id"], ctx["token"], body.token)
        if result.get("error") == "invalid_or_expired":
            return JSONResponse(status_code=400, content={"error": "invalid_or_expired"})
        return result

    # --- loans ---

    @app.post("/loans/eligibility")
    def loan_eligibility(body: EligibilityBody, customer_id: int = Depends(require_session)):
        return app.state.bank.check_loan_eligibility(customer_id, body.requested_amount_naira)

    @app.get("/loans/status")
    def loan_status(customer_id: int = Depends(require_session)):
        return app.state.bank.get_loan_status(customer_id)

    # --- handoff (optional auth) ---

    @app.post("/handoff")
    def handoff(body: HandoffBody, authorization: Optional[str] = Header(default=None)):
        token = _bearer(authorization)
        customer_id = app.state.auth.resolve_session(token) if token else None
        result = app.state.bank.create_handoff(customer_id, body.summary, body.reason)
        if result.get("error") == "invalid_reason":
            return JSONResponse(status_code=400, content={"error": "invalid_reason"})
        if result.get("error") == "empty_summary":
            return JSONResponse(status_code=400, content={"error": "empty_summary"})
        return result

    return app
