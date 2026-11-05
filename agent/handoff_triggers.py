from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

REASON_CODES = (
    "user_requested",
    "upset_user",
    "low_confidence",
    "repeated_errors",
    "failed_verification",
    "other",
)

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)


def _tokens(value: object) -> list[str]:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("'", "").replace("’", "")
    return _PUNCTUATION.sub(" ", text.lower()).split()


@dataclass(frozen=True)
class Trigger:
    reason: str
    language: str = "en"
    source: str = "requested"


def _contains(tokens: list[str], entries: list[str]) -> bool:
    for entry in entries:
        needle = _tokens(entry)
        size = len(needle)
        if size and any(
            tokens[i:i + size] == needle
            for i in range(len(tokens) - size + 1)
        ):
            return True
    return False


def _language(tokens: list[str], cfg) -> str:
    return "pidgin" if _contains(tokens, cfg.pidgin_markers) else "en"


def requested_trigger(text: str, cfg) -> Optional[Trigger]:
    """Return a user_requested trigger, unless the request is negated.

    Both phrase lists are checked together. A match is ignored when one of the
    three normalised tokens immediately before it (or its first token) is a
    negative word or falls inside a negative phrase. Language is pidgin when
    any pidgin marker is present.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    raw_tokens = _tokens(text)
    ignored = set(cfg.ignore_words)
    tokens = [token for token in raw_tokens if token not in ignored]
    negative_words = set(cfg.request_negative_words)
    phrases = list(cfg.request_phrases_en) + list(cfg.request_phrases_pidgin)

    for entry in phrases:
        needle = [t for t in _tokens(entry) if t not in ignored]
        size = len(needle)
        if not size:
            continue
        for start in range(len(tokens) - size + 1):
            if tokens[start:start + size] != needle:
                continue
            # Include the first matched token so a negation such as "no wan"
            # still covers a request verb that starts the phrase ("wan see").
            guard = tokens[max(0, start - 3):start + 1]
            negated = any(token in negative_words for token in guard)
            if not negated:
                negated = _contains(guard, cfg.request_negative_phrases)
            if not negated:
                return Trigger("user_requested", _language(raw_tokens, cfg))
    return None
