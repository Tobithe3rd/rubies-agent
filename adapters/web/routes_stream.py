"""Route wiring: stream message endpoint (SSE)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request

from .models import MessageBody
from .routes_common import get_entry, validate_message
from .turn import stream_response

router = APIRouter()


@router.post("/chats/{chat_id}/messages/stream")
async def stream_message(chat_id: str, body: MessageBody, request: Request):
    cfg = request.app.state.cfg
    store = request.app.state.chat_store
    web_cfg = cfg.settings.adapters.web
    entry = get_entry(store, chat_id)

    text = validate_message(body.message, web_cfg.max_message_chars, 400)
    if not web_cfg.stream_enabled:
        raise HTTPException(status_code=404, detail="stream_disabled")

    # Hold the lock for the whole turn, exactly like the JSON route.
    await entry["lock"].acquire()
    return stream_response(request.app, cfg, store, entry, text, chat_id)
