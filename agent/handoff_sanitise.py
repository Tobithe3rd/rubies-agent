from __future__ import annotations

import re
from typing import Any, Iterable, Mapping, Optional

# OTP-like runs. Boundaries treat nearby letters, digits and hyphens as part of
# the same token, so references such as RUB-03-000037 are left alone.
_DIGITS = re.compile(r"(?<![\w-])\d{6,}(?![\w-])")
_LIGHT_DIGITS = re.compile(r"(?<![\w-])\d{6,10}(?![\w-])")
_PHONE = re.compile(r"(?<!\d)(?:\+234|0)[789]\d{9}(?!\d)")
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]+")
_LONG_TOKEN = re.compile(
    r"\b(?=[A-Za-z0-9_\-]{24,}\b)(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9_\-]{24,}\b"
)
_BLOCK = re.compile(r"<<<.*?>>>", re.DOTALL)
_SPACES = re.compile(r"\s+")


def _label_for(tool_name: str, tools: Optional[Any]) -> Optional[str]:
    if tools is None:
        return None
    tool = tools.get(tool_name) if isinstance(tools, Mapping) else None
    labels = getattr(tool, "labels", None)
    return getattr(labels, "done", None)


def _replace_tools(text: str, tools: Optional[Any]) -> str:
    if not tools:
        return text
    names = [name for name in tools if isinstance(name, str)]
    for name in sorted(names, key=len, reverse=True):
        label = _label_for(name, tools)
        if not label:
            continue
        text = re.sub(
            rf"(?<![\w]){re.escape(name)}(?![\w])", lambda _: label, text
        )
    return text


def sanitise(
    text: str,
    mode: str = "strict",
    secrets: Optional[Iterable[str]] = None,
    tools: Optional[Any] = None,
) -> str:
    """Remove customer secrets from handoff text.

    Both modes remove <<<...>>> blocks, supplied secrets (session and pending
    tokens), bearer tokens, long opaque tokens, full Nigerian phone numbers and
    replace tool names with the done label from config/tools.yaml.

    Light mode also redacts standalone 6 to 10 digit runs (OTP-like), but keeps
    comma-grouped amounts, last-4 digits and references such as RUB-03-000037.
    Strict mode redacts every standalone run of 6 or more digits.
    """
    value = text if isinstance(text, str) else ""
    value = _BLOCK.sub(" ", value)

    for secret in sorted(
        (s for s in (secrets or ()) if isinstance(s, str) and s), key=len, reverse=True
    ):
        value = value.replace(secret, "[redacted]")

    value = _BEARER.sub("[redacted]", value)
    value = _PHONE.sub("[phone]", value)
    value = _LONG_TOKEN.sub("[redacted]", value)
    value = (_LIGHT_DIGITS if mode == "light" else _DIGITS).sub("[redacted]", value)
    value = _replace_tools(value, tools)
    return _SPACES.sub(" ", value).strip()


sanitize = sanitise
