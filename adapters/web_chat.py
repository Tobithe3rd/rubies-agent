"""Web adapter: FastAPI app hosting chat routes backed by AgentRunner."""
from __future__ import annotations

import secrets
import time
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from starlette.requests import Request

try:
    from core.factories import register, create_agent_runner
    from core.config import AppConfig, load_config
except ImportError:
    # Fallback for direct import when path differs
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from core.factories import register, create_agent_runner
    from core.config import AppConfig, load_config


class MessageBody(BaseModel):
    message: str


class ChatResponse(BaseModel):
    chat_id: str


class MessageResponse(BaseModel):
    reply: str
    error: bool = False


class OtpResponse(BaseModel):
    otp_line: str


# --- adapter registry ---


@register("adapter", "web")
class WebAdapter:
    """Registered adapter class (not instantiated directly here)."""

    def __init__(self, cfg: AppConfig, env=None):
        self.cfg = cfg
        self.env = env or cfg.env

    def describe(self) -> str:
        return "web:http"

    def healthcheck(self):
        from core.interfaces import HealthStatus
        return HealthStatus("web", True, "http adapter ready")


# --- session store ---

class ChatSessionStore:
    def __init__(self, cfg: AppConfig, clock=None):
        self.cfg = cfg
        self.sessions: dict[str, dict] = {}
        web_cfg = cfg.settings.adapters.web
        self.idle_limit = web_cfg.session_idle_seconds
        self.max_age = web_cfg.session_max_age_seconds
        self.max_sessions = web_cfg.max_sessions
        # Injectable clock: if clock has .now() use it; else clock is callable directly
        if clock is None:
            self._now = time.time
        elif hasattr(clock, 'now') and callable(clock.now):
            self._now = clock.now
        elif callable(clock):
            self._now = clock
        else:
            self._now = time.time

    def create(self, chat_id: str, runner) -> None:
        import asyncio
        self.sessions[chat_id] = {
            "runner": runner,
            "lock": asyncio.Lock(),
            "created_at": self._now(),
            "last_used": self._now(),
        }

    def get(self, chat_id: str) -> Optional[dict]:
        entry = self.sessions.get(chat_id)
        if entry is None:
            return None
        now = self._now()
        # Lazy expiry check
        if (now - entry["last_used"] > self.idle_limit) or (now - entry["created_at"] > self.max_age):
            self.sessions.pop(chat_id, None)
            return None
        entry["last_used"] = now
        return entry

    def delete(self, chat_id: str) -> None:
        self.sessions.pop(chat_id, None)

    def active_chats(self) -> int:
        # Lazy clean-up before counting
        now = self._now()
        expired = [
            cid for cid, entry in self.sessions.items()
            if (now - entry["last_used"] > self.idle_limit) or (now - entry["created_at"] > self.max_age)
        ]
        for cid in expired:
            self.sessions.pop(cid, None)
        return len(self.sessions)

    def cap_reached(self) -> bool:
        return len(self.sessions) >= self.max_sessions


# --- app factory ---

def create_app(cfg: AppConfig = None) -> FastAPI:
    if cfg is None:
        cfg = load_config()

    web_cfg = cfg.settings.adapters.web
    app = FastAPI(title="Rubies Web Adapter")

    # CORS
    origins = web_cfg.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    store = ChatSessionStore(cfg)
    _shared_llm = None

    def _get_llm():
        nonlocal _shared_llm
        if _shared_llm is None:
            from core.factories import create_llm
            _shared_llm = create_llm(cfg)
        return _shared_llm

    def _read_otp_line() -> str:
        otp_path = web_cfg.otp_log_path
        try:
            from pathlib import Path
            lines = [line for line in Path(otp_path).read_text().splitlines() if line.strip()]
            return lines[-1] if lines else ""
        except Exception:
            return ""

    @app.get("/health")
    async def health():
        return {"status": "ok", "active_chats": store.active_chats()}

    @app.post("/chats", response_model=ChatResponse)
    async def create_chat():
        if store.cap_reached():
            raise HTTPException(status_code=503, detail="max_sessions")
        chat_id = secrets.token_urlsafe(32)
        # Share LLM across runners
        import time
        start = time.time()
        llm = _get_llm()
        runner = create_agent_runner(cfg, llm=llm)
        duration = time.time() - start
        # Log creation time (to stdout / logs only, never to client)
        print(f"[web] runner created for {chat_id} in {duration:.3f}s")
        store.create(chat_id, runner)
        return ChatResponse(chat_id=chat_id)

    @app.post("/chats/{chat_id}/messages", response_model=MessageResponse)
    async def send_message(chat_id: str, body: MessageBody):
        entry = store.get(chat_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="chat_expired")

        text = body.message
        if text is None or not str(text).strip():
            raise HTTPException(status_code=400, detail="empty_message")
        max_chars = web_cfg.max_message_chars
        if len(str(text)) > max_chars:
            raise HTTPException(status_code=400, detail="message_too_long")

        import asyncio
        runner = entry["runner"]
        lock = entry["lock"]

        async with lock:
            try:
                # Call blocking handle_message in threadpool to avoid blocking event loop
                reply_text = await asyncio.to_thread(runner.handle_message, text)
                return MessageResponse(reply=reply_text, error=False)
            except Exception as exc:
                # Log exception without exposing details to client
                import sys
                print(f"[web] message error in {chat_id}: {exc}", file=sys.stderr)
                return MessageResponse(reply=web_cfg.error_message, error=True)

    @app.get("/chats/{chat_id}/dev-otp", response_model=OtpResponse)
    async def get_otp(chat_id: str):
        # Check allow_dev_otp FIRST (so disabled endpoint reveals nothing about chat ids)
        if not web_cfg.allow_dev_otp:
            raise HTTPException(status_code=404, detail="dev_otp_disabled")
        # Check chat validity the same way messages route does; counts as activity
        entry = store.get(chat_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="chat_expired")
        # Reuse CLI logic for reading OTP line without importing cli_chat
        otp_line = _read_otp_line()
        if not otp_line:
            raise HTTPException(status_code=404, detail="no_otp_line")
        # Scrub session token from line (defensive, same as cli_chat)
        token = getattr(getattr(entry.get("runner"), "session", None), "token", None)
        if token and isinstance(token, str) and token in otp_line:
            otp_line = otp_line.replace(token, "***")
        return OtpResponse(otp_line=otp_line)

    @app.delete("/chats/{chat_id}")
    async def delete_chat(chat_id: str):
        entry = store.get(chat_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="chat_expired")
        store.delete(chat_id)
        return None

    return app


# --- direct uvicorn entry ---

def main():
    cfg = load_config()
    import uvicorn
    uvicorn.run(
        "adapters.web_chat:create_app",
        factory=True,
        host=cfg.settings.adapters.web.host,
        port=cfg.settings.adapters.web.port,
    )


if __name__ == "__main__":
    main()
