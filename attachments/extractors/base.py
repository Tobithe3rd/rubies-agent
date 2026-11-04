from __future__ import annotations

import importlib
import unicodedata
from typing import Protocol

from attachments.config import AttachmentProfile
from attachments.models import ExtractedDocument, ValidatedFile


class NeedsVision(Exception):
    """The file cannot be read as text and needs the (not yet built) vision path."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class Extractor(Protocol):
    def extract(self, file: ValidatedFile, profile: AttachmentProfile) -> ExtractedDocument:
        ...


_REGISTRY: dict[str, Extractor] = {}
_IMPORT_MAP = {
    "txt": "attachments.extractors.text",
    "csv": "attachments.extractors.csv",
    "docx": "attachments.extractors.docx",
    "xlsx": "attachments.extractors.xlsx",
    "pdf": "attachments.extractors.pdf",
}


def register_extractor(kind: str):
    def decorator(cls):
        _REGISTRY[kind] = cls()
        return cls
    return decorator


def get_extractor(kind: str) -> Extractor:
    if kind not in _IMPORT_MAP:
        raise ValueError(f"no text extractor for kind: {kind!r}")
    if kind not in _REGISTRY:
        importlib.import_module(_IMPORT_MAP[kind])
    return _REGISTRY[kind]


def strip_control(text: str) -> str:
    """Remove NUL and other control characters, keeping tab/newline/CR."""
    return "".join(
        ch for ch in text
        if ch in "\t\n\r" or unicodedata.category(ch) != "Cc"
    )


def finalize(document: ExtractedDocument, profile: AttachmentProfile) -> ExtractedDocument:
    """Clean text and apply the shared per-document character cap."""
    for block in document.blocks:
        block.text = strip_control(block.text)

    kept = []
    used = 0
    capped = False
    for block in document.blocks:
        remaining = profile.max_chars_per_document - used
        if remaining <= 0:
            capped = True
            break
        if len(block.text) > remaining:
            block.text = block.text[:remaining]
            kept.append(block)
            capped = True
            break
        kept.append(block)
        used += len(block.text)
    document.blocks = kept

    if capped:
        document.truncated = True
        if "text truncated at the document limit" not in document.warnings:
            document.warnings.append("text truncated at the document limit")
    return document
