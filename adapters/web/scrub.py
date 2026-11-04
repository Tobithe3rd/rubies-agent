"""Sanitising: tokens, OTP-length numbers, phones, tool names."""
from __future__ import annotations

import re

from core.config import AppConfig


def _mask_phone(phone) -> str | None:
    digits = re.sub(r"\D", "", str(phone or ""))
    if len(digits) < 4:
        return None
    if digits.startswith("234"):
        country, national = "+234", digits[3:]
    elif digits.startswith("0"):
        country, national = "+234", digits[1:]
    elif len(digits) > 10:
        country, national = f"+{digits[:-10]}", digits[-10:]
    else:
        country, national = "+234", digits
    return f"{country} ••• ••• {national[-4:]}"


def _scrub_summary(
    text,
    secrets_to_remove,
    tool_names,
    max_chars: int,
    otp_length: int,
) -> str:
    text = str(text or "")
    for secret in secrets_to_remove:
        if secret:
            text = text.replace(str(secret), "[redacted]")
    text = re.sub(
        r"(?<![\d+])(?:\+?234|0)[\d\s\-]{8,14}\d(?!\d)",
        "[redacted]", text,
    )
    text = re.sub(
        r"(?i)(?:₦|\bNGN\b|\bnaira\b)\s*[\d,]+(?:\.\d+)?",
        "[redacted]", text,
    )
    text = re.sub(rf"\b\d{{{otp_length},}}\b", "[redacted]", text)
    for name in tool_names:
        text = text.replace(name, "request")
    return " ".join(text.split())[:max_chars]


def _history_text(cfg: AppConfig, entry: dict, text) -> str:
    session = getattr(entry.get("runner"), "session", None)
    secrets_to_remove = [getattr(session, "token", None)]
    secrets_to_remove.extend((getattr(session, "pending", None) or {}).keys())
    out = str(text or "")
    for secret in secrets_to_remove:
        if secret:
            out = out.replace(str(secret), "[redacted]")
    out = re.sub(
        r"(?<![\d+])(?:\+?234|0)[\d\s\-]{8,14}\d(?!\d)",
        "[redacted]", out,
    )
    out = re.sub(
        rf"\b\d{{{cfg.settings.bank_api.otp_length},}}\b",
        "[redacted]", out,
    )
    for tool_name in cfg.tools:
        out = out.replace(tool_name, "request")
    return out
