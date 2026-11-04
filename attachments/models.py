from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Optional

BlockType = Literal["heading", "paragraph", "table"]
ExtractionMethod = Literal["native_text", "library", "vision"]

REJECTION_CODES = frozenset({
    "too_many_files",
    "too_large",
    "total_too_large",
    "type_not_allowed",
    "type_mismatch",
    "not_text",
    "bad_image",
    "image_too_large",
    "empty_file",
    "encrypted_file",
    "unreadable_file",
    "zip_unsafe",
    "extraction_unavailable",
    "no_readable_text",
    "too_many_pages",
})

# Generic and customer-safe. Never interpolate file content or a filename.
MESSAGES = {
    "too_many_files": "Too many attachments in one message.",
    "too_large": "Each attachment must be within the size limit.",
    "total_too_large": "The attachments are too large together.",
    "type_not_allowed": "That file type is not supported.",
    "type_mismatch": "The file content does not match its extension.",
    "not_text": "The text file could not be read.",
    "bad_image": "The image could not be read.",
    "image_too_large": "The image dimensions are too large.",
    "empty_file": "One of the attachments is empty.",
    "encrypted_file": "The file is password-protected and cannot be read.",
    "unreadable_file": "The file could not be read.",
    "zip_unsafe": "The file is not safe to open.",
    "extraction_unavailable": "The file could not be processed right now. Please try again.",
    "no_readable_text": "No readable text was found in the file.",
    "too_many_pages": "The document has too many pages.",
}


@dataclass
class Block:
    type: BlockType
    text: str
    level: Optional[int] = None
    page: Optional[int] = None


@dataclass
class ExtractedDocument:
    name: str
    kind: str
    blocks: list[Block]
    page_count: Optional[int]
    warnings: list[str] = field(default_factory=list)
    truncated: bool = False
    method: ExtractionMethod = "library"


class ValidatedFile:
    """A file that passed validation.

    `data` is deliberately not a dataclass field: repr() and to_dict() (the
    only serialisation surface) never expose it. Callers read it via `.data`.
    """

    __slots__ = ("display_name", "kind", "detected_mime", "size", "_data")

    def __init__(self, display_name: str, kind: str, detected_mime: str, size: int, data: bytes) -> None:
        self.display_name = display_name
        self.kind = kind
        self.detected_mime = detected_mime
        self.size = size
        self._data = data

    @property
    def data(self) -> bytes:
        return self._data

    def to_dict(self) -> dict[str, Any]:
        return {
            "display_name": self.display_name,
            "kind": self.kind,
            "detected_mime": self.detected_mime,
            "size": self.size,
        }

    def __repr__(self) -> str:
        return (
            f"ValidatedFile(display_name={self.display_name!r}, kind={self.kind!r}, "
            f"detected_mime={self.detected_mime!r}, size={self.size!r})"
        )


class AttachmentRejected(Exception):
    """Customer-safe rejection. Never carries file content or the filename."""

    def __init__(self, code: str, message: str) -> None:
        if code not in REJECTION_CODES:
            raise ValueError(f"unknown rejection code: {code!r}")
        super().__init__(message)
        self.code = code
        self.message = message
