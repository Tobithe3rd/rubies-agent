"""Session store: entries, expiry, injectable clock."""
from __future__ import annotations

import asyncio
import time
from typing import Optional

from core.config import AppConfig


class ChatSessionStore:
    def __init__(self, cfg: AppConfig, clock=None):
        self.cfg = cfg
        self.sessions: dict[str, dict] = {}
        web_cfg = cfg.settings.adapters.web
        self.idle_limit = web_cfg.session_idle_seconds
        self.max_age = web_cfg.session_max_age_seconds
        self.history_max_events = web_cfg.history_max_events
        self.clear_on_verification_expiry = web_cfg.clear_transcript_on_verification_expiry
        self.max_sessions = web_cfg.max_sessions
        self.verification_seconds = cfg.settings.session.expiry_minutes * 60
        # Injectable clock
        if clock is None:
            self._now = time.time
        elif hasattr(clock, 'now') and callable(clock.now):
            self._now = clock.now
        elif callable(clock):
            self._now = clock
        else:
            self._now = time.time

    def create(self, chat_id: str, runner) -> None:
        self.sessions[chat_id] = {
            "runner": runner,
            "lock": asyncio.Lock(),
            "created_at": self._now(),
            "last_used": self._now(),
            "history": [],
            "was_verified_at": None,
            "panel": {
                "verified": False,
                "phone_masked": None,
                "verified_at": None,
                "receipts": [],
            },
        }

    def get(self, chat_id: str) -> Optional[dict]:
        entry = self.sessions.get(chat_id)
        if entry is None:
            return None
        now = self._now()
        if (now - entry["last_used"] > self.idle_limit) or (now - entry["created_at"] > self.max_age):
            self.sessions.pop(chat_id, None)
            return None
        verified_at = entry.get("was_verified_at")
        if (self.clear_on_verification_expiry and verified_at is not None
                and now - verified_at > self.verification_seconds):
            self.sessions.pop(chat_id, None)
            return None
        entry["last_used"] = now
        return entry

    def delete(self, chat_id: str) -> None:
        self.sessions.pop(chat_id, None)

    def active_chats(self) -> int:
        now = self._now()
        expired = [
            cid for cid, entry in self.sessions.items()
            if (now - entry["last_used"] > self.idle_limit)
            or (now - entry["created_at"] > self.max_age)
        ]
        for cid in expired:
            self.sessions.pop(cid, None)
        return len(self.sessions)

    def cap_reached(self) -> bool:
        return len(self.sessions) >= self.max_sessions

    @staticmethod
    def _clear_verification(panel: dict) -> bool:
        changed = panel["verified"] or panel["phone_masked"] is not None
        panel["verified"] = False
        panel["phone_masked"] = None
        panel["verified_at"] = None
        return bool(changed)
