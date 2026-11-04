"""Route wiring: /chats create/delete, JSON messages, health and dev-otp."""
from __future__ import annotations

import asyncio
import secrets
import time

from fastapi import APIRouter, HTTPException, Request

from .models import ChatResponse, MessageBody, MessageResponse, OtpResponse
from .panel import _record_panel_result
from .transcript import record_reply, record_user

router = APIRouter()


def _cfg(request: Request):
    return request.app.state.cfg


def _store(request: Request):
    return request.app.state.chat_store


def _get_llm(app, cfg):
    if app.state.shared_llm is None:
        from core.factories import create_llm
        app.state.shared_llm = create_llm(cfg)
    return app.state.shared_llm


def _read_otp_line(otp_path: str) -> str:
    try:
        from pathlib import Path
        lines = [line for line in Path(otp_path).read_text().splitlines() if line.strip()]
        return lines[-1] if lines else ""
    except Exception:
        return ""


@router.get("/health")
async def health(request: Request):
    return {"status": "ok", "active_chats": _store(request).active_chats()}


@router.post("/chats", response_model=ChatResponse)
async def create_chat(request: Request):
    cfg = _cfg(request)
    store = _store(request)
    if store.cap_reached():
        raise HTTPException(status_code=503, detail="max_sessions")
    chat_id = secrets.token_urlsafe(32)
    start = time.time()
    llm = _get_llm(request.app, cfg)
    from adapters import web_chat
    runner = web_chat.create_agent_runner(cfg, llm=llm)
    duration = time.time() - start
    print(f"[web] runner created for {chat_id} in {duration:.3f}s")
    store.create(chat_id, runner)
    return ChatResponse(chat_id=chat_id)


@router.post("/chats/{chat_id}/messages", response_model=MessageResponse)
async def send_message(chat_id: str, body: MessageBody, request: Request):
    cfg = _cfg(request)
    store = _store(request)
    web_cfg = cfg.settings.adapters.web
    entry = store.get(chat_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="chat_expired")

    text = body.message
    if text is None or not str(text).strip():
        raise HTTPException(status_code=400, detail="empty_message")
    if len(str(text)) > web_cfg.max_message_chars:
        raise HTTPException(status_code=400, detail="message_too_long")

    runner = entry["runner"]
    lock = entry["lock"]

    async with lock:
        def result_observer(tool_name: str, status: str, args: dict, envelope: dict) -> None:
            _record_panel_result(cfg, store, entry, tool_name, status, args, envelope)

        runner.tool_result_observer = result_observer
        record_user(entry, text, cfg, store)
        try:
            try:
                reply_text = await asyncio.to_thread(runner.handle_message, text)
                record_reply(entry, reply_text, status="done", cfg=cfg, store=store)
                return MessageResponse(reply=reply_text, error=False)
            except Exception as exc:
                import sys
                print(f"[web] message error in {chat_id}: {exc}", file=sys.stderr)
                record_reply(entry, web_cfg.error_message, status="error", cfg=cfg, store=store)
                return MessageResponse(reply=web_cfg.error_message, error=True)
        finally:
            runner.tool_result_observer = None


@router.get("/chats/{chat_id}/dev-otp", response_model=OtpResponse)
async def get_otp(chat_id: str, request: Request):
    cfg = _cfg(request)
    store = _store(request)
    web_cfg = cfg.settings.adapters.web
    if not web_cfg.allow_dev_otp:
        raise HTTPException(status_code=404, detail="dev_otp_disabled")
    entry = store.get(chat_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="chat_expired")
    otp_line = _read_otp_line(web_cfg.otp_log_path)
    if not otp_line:
        raise HTTPException(status_code=404, detail="no_otp_line")
    token = getattr(getattr(entry.get("runner"), "session", None), "token", None)
    if token and isinstance(token, str) and token in otp_line:
        otp_line = otp_line.replace(token, "***")
    return OtpResponse(otp_line=otp_line)


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str, request: Request):
    store = _store(request)
    entry = store.get(chat_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="chat_expired")
    store.delete(chat_id)
    return None
