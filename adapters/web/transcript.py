"""Transcript recording, coalescing, trimming, history serialisation."""
from __future__ import annotations

import uuid

from zoneinfo import ZoneInfo
from datetime import datetime

from core.config import AppConfig
from .store import ChatSessionStore
from .scrub import _history_text, _mask_phone


def _iso_time(value, timezone: str) -> str:
    tz = ZoneInfo(timezone)
    moment = value if isinstance(value, datetime) else datetime.fromtimestamp(value, tz=tz)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    return moment.astimezone(tz).isoformat(timespec="seconds")


def record_user(entry: dict, text: str, cfg: AppConfig, store: ChatSessionStore) -> None:
    entry["history"].append({
        "role": "user",
        "text": str(text),
        "at": _iso_time(store._now(), cfg.settings.timezone),
    })
    _trim(entry, store)


def start_agent(entry: dict, cfg: AppConfig, store: ChatSessionStore) -> dict:
    record = {
        "role": "agent",
        "events": [],
        "status": "streaming",
        "at": _iso_time(store._now(), cfg.settings.timezone),
    }
    entry["history"].append(record)
    return record


def record_agent_event(entry: dict, record: dict, event: dict, store: ChatSessionStore) -> None:
    events = record["events"]
    if event.get("type") == "text" and events and events[-1].get("type") == "text":
        events[-1]["text"] += event["text"]
    else:
        events.append(dict(event))
    _trim(entry, store)


def finish_agent(entry: dict, record: dict, status: str, cfg: AppConfig, store: ChatSessionStore) -> None:
    record["status"] = status
    record["at"] = _iso_time(store._now(), cfg.settings.timezone)
    _trim(entry, store)


def record_reply(entry: dict, text: str, status: str, cfg: AppConfig, store: ChatSessionStore) -> None:
    record = start_agent(entry, cfg, store)
    record_agent_event(entry, record, {"type": "text", "text": str(text)}, store)
    finish_agent(entry, record, status, cfg, store)


def _trim(entry: dict, store: ChatSessionStore) -> None:
    history = entry["history"]
    def count() -> int:
        return sum(1 if message["role"] == "user" else len(message["events"]) for message in history)
    while len(history) > 1 and count() > store.history_max_events:
        history.pop(0)


def history_messages(cfg: AppConfig, entry: dict) -> list[dict]:
    messages: list[dict] = []
    for message in entry["history"]:
        if message["role"] == "user":
            messages.append({
                "role": "user",
                "text": _history_text(cfg, entry, message["text"]),
                "at": message["at"],
            })
            continue
        events = []
        for event in message["events"]:
            clean = dict(event)
            if clean.get("type") in ("text", "error"):
                if "text" in clean:
                    clean["text"] = _history_text(cfg, entry, clean["text"])
                if "message" in clean:
                    clean["message"] = _history_text(cfg, entry, clean["message"])
            events.append(clean)
        messages.append({
            "role": "agent",
            "events": events,
            "status": message["status"],
            "at": message["at"],
        })
    return messages
