from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from core.config import load_config
from core.factories import create_datastore, create_otp_sender
from bank_api.auth import AuthService


class RequestOTPBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=10, max_length=16, pattern=r"^\+?[0-9]{10,15}$")


class VerifyBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=10, max_length=16, pattern=r"^\+?[0-9]{10,15}$")
    code: str = Field(min_length=4, max_length=10, pattern=r"^[0-9]+$")


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
        yield
        try:
            datastore.close()
        except Exception:
            pass

    app = FastAPI(lifespan=lifespan)

    def require_session(authorization: Optional[str] = Header(default=None)) -> int:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="invalid_session")
        token = authorization.split(" ", 1)[1].strip()
        customer_id = app.state.auth.resolve_session(token)
        if customer_id is None:
            raise HTTPException(status_code=401, detail="invalid_session")
        return customer_id

    @app.get("/health")
    def health():
        return {"status": "ok"}

    @app.post("/auth/request-otp")
    def request_otp(body: RequestOTPBody):
        return app.state.auth.request_otp(body.phone)

    @app.post("/auth/verify")
    def verify(body: VerifyBody):
        result = app.state.auth.verify_otp(body.phone, body.code)
        if result.get("ok"):
            return {"token": result["token"], "expires_at": result["expires_at"]}
        if result.get("error") == "otp_locked":
            return JSONResponse(status_code=429, content={"error": "otp_locked"})
        return JSONResponse(status_code=401, content={"error": "invalid_or_expired"})

    @app.post("/auth/logout")
    def logout(authorization: Optional[str] = Header(default=None),
               customer_id: int = Depends(require_session)):
        token = authorization.split(" ", 1)[1].strip()
        app.state.auth.logout(token)
        return {"status": "ok"}

    @app.get("/me")
    def me(customer_id: int = Depends(require_session)):
        customer = app.state.datastore.get_customer(customer_id)
        if customer is None:
            raise HTTPException(status_code=401, detail="invalid_session")
        return {"customer_id": customer["id"], "full_name": customer["full_name"]}

    return app
