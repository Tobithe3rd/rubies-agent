from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import datetime
from typing import Callable, Optional

from core.interfaces import DataStore, OTPSender


def _sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def normalise_phone(phone: str) -> str:
    """Normalise a Nigerian phone number to +234XXXXXXXXXX form."""
    digits = "".join(ch for ch in phone if ch.isdigit())
    if digits.startswith("234"):
        return "+" + digits
    if digits.startswith("0"):
        return "+234" + digits[1:]
    return "+234" + digits


class AuthService:
    def __init__(
        self,
        datastore: DataStore,
        cfg,
        env,
        otp_sender: Optional[OTPSender] = None,
        clock: Optional[Callable[[], datetime.datetime]] = None,
    ):
        self.ds = datastore
        self.cfg = cfg
        self.env = env
        self.otp_sender = otp_sender
        self._clock = clock or datetime.datetime.now
        bank = cfg.settings.bank_api
        self.otp_length = bank.otp_length
        self.otp_ttl_seconds = bank.otp_ttl_seconds
        self.otp_max_attempts = bank.otp_max_attempts
        self.session_expiry_minutes = cfg.settings.session.expiry_minutes
        self.secret = env.OTP_HASH_SECRET

    # --- internals ---

    def _now(self) -> datetime.datetime:
        return self._clock()

    def _code_hash(self, phone: str, code: str) -> str:
        msg = f"{phone}:{code}".encode()
        return hmac.new(self.secret.encode(), msg, hashlib.sha256).hexdigest()

    def _audit(self, session_ref: Optional[str], customer_id: Optional[int],
               action: str, params: dict, outcome: str) -> None:
        # params must never contain a code or a token
        self.ds.write_audit(session_ref, customer_id, action, json.dumps(params), outcome)

    def _generate_code(self) -> str:
        return "".join(str(secrets.randbelow(10)) for _ in range(self.otp_length))

    # --- public API ---

    def request_otp(self, phone: str) -> dict:
        norm = normalise_phone(phone)
        customer = self.ds.get_customer_by_phone(norm)
        if customer is not None:
            code = self._generate_code()
            expires_at = (self._now() + datetime.timedelta(seconds=self.otp_ttl_seconds))
            self.ds.create_otp(norm, self._code_hash(norm, code), expires_at.strftime("%Y-%m-%d %H:%M:%S"))
            if self.otp_sender is not None:
                self.otp_sender.send(norm, code)
            self._audit(None, customer["id"], "request_otp", {"phone": norm}, "requested")
        else:
            self._audit(None, None, "request_otp", {"phone": norm}, "unknown_phone")
        # Always the same generic result; never returns the code.
        return {"status": "ok", "message": "If the number is registered, a code has been sent."}

    def verify_otp(self, phone: str, code: str) -> dict:
        norm = normalise_phone(phone)
        otp = self.ds.get_latest_otp(norm)
        if otp is None:
            self._audit(None, None, "verify_otp", {"phone": norm}, "no_otp")
            return {"ok": False, "error": "invalid_or_expired", "status": 401}
        if otp["used"]:
            self._audit(None, None, "verify_otp", {"phone": norm}, "already_used")
            return {"ok": False, "error": "invalid_or_expired", "status": 401}
        expires_at = datetime.datetime.strptime(otp["expires_at"], "%Y-%m-%d %H:%M:%S")
        if self._now() > expires_at:
            self._audit(None, None, "verify_otp", {"phone": norm}, "expired")
            return {"ok": False, "error": "invalid_or_expired", "status": 401}
        if otp["attempts"] >= self.otp_max_attempts:
            self._audit(None, None, "verify_otp", {"phone": norm}, "otp_locked")
            return {"ok": False, "error": "otp_locked", "status": 429}

        # Count the attempt before comparing.
        self.ds.increment_otp_attempts(otp["id"])

        if hmac.compare_digest(self._code_hash(norm, code), otp["code_hash"]):
            self.ds.mark_otp_used(otp["id"])
            customer = self.ds.get_customer_by_phone(norm)
            if customer is None:
                self._audit(None, None, "verify_otp", {"phone": norm}, "no_customer")
                return {"ok": False, "error": "invalid_or_expired", "status": 401}
            token = secrets.token_urlsafe(32)
            token_hash = _sha256_hex(token)
            expires = self._now() + datetime.timedelta(minutes=self.session_expiry_minutes)
            self.ds.create_session(customer["id"], token_hash, expires.strftime("%Y-%m-%d %H:%M:%S"))
            self._audit(token_hash[:8], customer["id"], "verify_otp", {"phone": norm}, "success")
            return {"ok": True, "token": token, "expires_at": expires.strftime("%Y-%m-%d %H:%M:%S")}

        self._audit(None, None, "verify_otp", {"phone": norm}, "invalid_code")
        return {"ok": False, "error": "invalid_or_expired", "status": 401}

    def resolve_session(self, token: str) -> Optional[int]:
        if not token:
            return None
        token_hash = _sha256_hex(token)
        session = self.ds.get_session_by_token_hash(token_hash)
        if session is None:
            return None
        if session.get("revoked"):
            return None
        expires_at = datetime.datetime.strptime(session["expires_at"], "%Y-%m-%d %H:%M:%S")
        if self._now() > expires_at:
            return None
        return session["customer_id"]

    def logout(self, token: str) -> None:
        if not token:
            return
        token_hash = _sha256_hex(token)
        customer_id = self.resolve_session(token)
        self.ds.revoke_session(token_hash)
        self._audit(token_hash[:8], customer_id, "logout", {}, "ok")
