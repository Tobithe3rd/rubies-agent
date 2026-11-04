"""Audit logging for the attachment upload route. Never logs text or filenames."""
from __future__ import annotations

import json
import logging
import time

logger = logging.getLogger(__name__)


def audit_upload(chat_id: str, kinds: list[str], sizes: list[int], hashes: list[str],
                 outcome: str, started: float) -> None:
    payload = {
        "event": "attachment_upload",
        "chat_id": chat_id,
        "file_count": len(hashes),
        "kinds": list(kinds),
        "sizes": list(sizes),
        "sha256": list(hashes),
        "outcome": outcome,
        "duration_ms": int((time.monotonic() - started) * 1000),
    }
    logger.info("attachment_upload %s", json.dumps(payload, sort_keys=True), extra=payload)
