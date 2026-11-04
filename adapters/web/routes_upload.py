"""Multipart upload SSE route: validate files, extract, then stream the agent turn."""
from __future__ import annotations

import asyncio
import hashlib
import time

from fastapi import APIRouter, HTTPException, Request
from starlette.datastructures import UploadFile
from starlette.responses import JSONResponse, Response, StreamingResponse

from attachments import build_chat_message, extract_document, validate_files
from attachments.models import MESSAGES, AttachmentRejected

from .routes_common import get_entry, is_verified, validate_message
from .sse import _sse
from .turn import stream_response
from .upload_helpers import audit_upload

router = APIRouter()
PROFILE = "chat_attachment"
STREAM_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _upload_files(form) -> list[UploadFile]:
    return [item for item in form.getlist("files") if isinstance(item, UploadFile)]


@router.post("/chats/{chat_id}/messages/stream/files")
async def stream_message_with_files(chat_id: str, request: Request):
    started = time.monotonic()
    cfg = request.app.state.cfg
    store = request.app.state.chat_store
    att_cfg = request.app.state.attachments_config
    if not att_cfg.enabled:
        return Response(status_code=404)

    entry = get_entry(store, chat_id)
    profile = att_cfg.profile(PROFILE)
    if profile.require_verified_session and not is_verified(entry):
        raise HTTPException(status_code=403, detail=att_cfg.web_upload.not_verified_message)

    form = await request.form()
    text = validate_message(
        form.get("message"), cfg.settings.adapters.web.max_message_chars, 422)
    uploads = _upload_files(form)
    if not uploads:
        raise HTTPException(status_code=422, detail="no_files")

    raw = []
    for upload in uploads:
        raw.append((upload.filename or "", await upload.read()))
        await upload.close()
    del uploads
    hashes = [hashlib.sha256(data).hexdigest() for _, data in raw]
    sizes = [len(data) for _, data in raw]

    try:
        validated = validate_files(raw, PROFILE, att_cfg)
    except AttachmentRejected as exc:
        audit_upload(chat_id, [], sizes, hashes, exc.code, started)
        del raw
        return JSONResponse(
            status_code=422, content={"code": exc.code, "message": exc.message})
    del raw

    kinds = [item.kind for item in validated]
    await entry["lock"].acquire()
    vision = request.app.state.vision_extractor

    async def event_stream():
        documents = []
        try:
            yield _sse("step", {
                "id": "attachment-read", "status": "running",
                "label": att_cfg.web_upload.reading_label,
            })
            for item in validated:
                documents.append(await asyncio.to_thread(
                    extract_document, item, PROFILE, att_cfg, vision))
            chat_message = build_chat_message(text, documents, att_cfg)
        except (AttachmentRejected, ValueError) as exc:
            code = getattr(exc, "code", "invalid_message")
            message = getattr(exc, "message", MESSAGES["extraction_unavailable"])
            audit_upload(chat_id, kinds, sizes, hashes, code, started)
            yield _sse("error", {"code": code, "message": message})
            documents.clear()
            validated.clear()
            entry["lock"].release()
            return
        except Exception:
            code = "extraction_unavailable"
            audit_upload(chat_id, kinds, sizes, hashes, code, started)
            yield _sse("error", {"code": code, "message": MESSAGES[code]})
            documents.clear()
            validated.clear()
            entry["lock"].release()
            return

        audit_upload(chat_id, kinds, sizes, hashes, "ok", started)
        model_text = chat_message.model_text
        display_text = chat_message.display_text
        del chat_message
        documents.clear()
        validated.clear()

        inner = stream_response(
            request.app, cfg, store, entry, model_text, chat_id,
            record_text=display_text, has_attachments=True)
        async for chunk in inner.body_iterator:
            yield chunk

    return StreamingResponse(
        event_stream(), media_type="text/event-stream", headers=STREAM_HEADERS)
