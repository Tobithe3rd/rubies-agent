from __future__ import annotations

import re
import unicodedata

_PUNCTUATION = re.compile(r"[^\w\s]", re.UNICODE)


def _tokens(value: object) -> list[str]:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.replace("'", "").replace("’", "")
    return _PUNCTUATION.sub(" ", text.lower()).split()


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


def is_affirmation(text: str, cfg) -> bool:
    """True only for a short, unambiguous yes in the customer's own message."""
    if not isinstance(text, str) or not text.strip():
        return False
    if getattr(cfg, "reject_digits", False) and any(ch.isdigit() for ch in text):
        return False
    if "?" in text or "？" in text:
        return False

    fillers = {token for entry in cfg.filler_words for token in _tokens(entry)}
    tokens = [token for token in _tokens(text) if token not in fillers]
    if not tokens or len(tokens) > cfg.max_tokens:
        return False
    if _contains(tokens, cfg.negative_words) or _contains(tokens, cfg.negative_phrases):
        return False
    return (
        _contains(tokens, cfg.affirmative_words)
        or _contains(tokens, cfg.affirmative_phrases)
    )
