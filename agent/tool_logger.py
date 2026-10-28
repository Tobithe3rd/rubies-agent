from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Optional

from core.clock import Clock, create_clock
from core.config import AppConfig

# Nigerian mobile formats used by the synthetic data: +234XXXXXXXXXX or 0XXXXXXXXXX.
_PHONE_RE = re.compile(r"^(?:\+?234|0)\d{10}$")


class JsonlToolLogger:
    """Append one redacted JSON object per tool call to logging.tool_log_path."""

    def __init__(self, config: AppConfig, clock: Optional[Clock] = None):
        logging_cfg = config.settings.logging
        self.path = Path(logging_cfg.tool_log_path)
        self.redact_keys = set(logging_cfg.redact_keys)
        self.mask_phone_keep_last = logging_cfg.mask_phone_keep_last
        self.pending_token_prefix_chars = logging_cfg.pending_token_prefix_chars
        self.debug = logging_cfg.debug
        self.clock = clock or create_clock(config)
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            # A write failure is handled (and swallowed) in log(); startup must not crash.
            pass

    def _mask_phone(self, value: str) -> str:
        keep = self.mask_phone_keep_last
        return "*" * max(0, len(value) - keep) + value[-keep:]

    def redact(self, value: Any, key: Optional[str] = None) -> Any:
        if key in self.redact_keys:
            return "***"
        if key == "pending_token" and isinstance(value, str):
            return value[: self.pending_token_prefix_chars] + "..."
        if isinstance(value, dict):
            return {k: self.redact(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [self.redact(v, key) for v in value]
        if isinstance(value, str) and (key == "phone" or _PHONE_RE.match(value)):
            return self._mask_phone(value)
        return value

    def log(
        self,
        *,
        session_id: str,
        tool: str,
        inputs: dict,
        ok: bool,
        result: Any = None,
        error: Any = None,
        duration_ms: int = 0,
    ) -> None:
        payload: dict[str, Any] = {
            "time": self.clock.iso_now(),
            "session_id": session_id,
            "tool": tool,
            "inputs": self.redact(inputs),
            "ok": bool(ok),
            "duration_ms": int(duration_ms),
        }
        if ok:
            payload["result"] = self.redact(result)
        else:
            payload["error"] = self.redact(error)

        try:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, default=str) + "\n")
                handle.flush()
        except Exception as exc:
            # Logging must never break a tool call.
            print(f"warning: could not write tool log {self.path}: {exc}", file=sys.stderr)
