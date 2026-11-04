"""Route wiring: session and history endpoints."""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from .panel import panel_view
from .transcript import history_messages

router = APIRouter()


@router.get("/chats/{chat_id}/history")
async def get_history(chat_id: str, request: Request):
    cfg = request.app.state.cfg
    store = request.app.state.chat_store
    web_cfg = cfg.settings.adapters.web
    entry = store.get(chat_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="chat_expired")
    lock = entry["lock"]
    if lock.locked():
        try:
            await asyncio.wait_for(lock.acquire(), timeout=web_cfg.history_wait_seconds)
        except asyncio.TimeoutError:
            pass
        else:
            lock.release()
    return {
        "messages": history_messages(cfg, entry),
        "panel": panel_view(entry, cfg, store),
    }


@router.get("/chats/{chat_id}/session")
async def get_session(chat_id: str, request: Request):
    cfg = request.app.state.cfg
    store = request.app.state.chat_store
    entry = store.get(chat_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="chat_expired")
    return panel_view(entry, cfg, store)
