"""Shared route checks used by the JSON and upload stream routes."""
from __future__ import annotations

from fastapi import HTTPException


def get_entry(store, chat_id: str) -> dict:
    entry = store.get(chat_id)
    if entry is None:
        raise HTTPException(status_code=404, detail="chat_expired")
    return entry


def validate_message(text, max_chars: int, status_code: int) -> str:
    value = "" if text is None else str(text)
    if not value.strip():
        raise HTTPException(status_code=status_code, detail="empty_message")
    if len(value) > max_chars:
        raise HTTPException(status_code=status_code, detail="message_too_long")
    return value


def is_verified(entry: dict) -> bool:
    panel = entry.get("panel") or {}
    if panel.get("verified"):
        return True
    session = getattr(entry.get("runner"), "session", None)
    return bool(getattr(session, "verified", False))
