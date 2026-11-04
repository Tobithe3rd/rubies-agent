from __future__ import annotations

import warnings
from io import BytesIO
from pathlib import Path
from typing import Optional, Sequence

import filetype
from PIL import Image

from attachments.config import AttachmentProfile, AttachmentsConfig, load_attachments_config
from attachments.models import MESSAGES, AttachmentRejected, ValidatedFile

EXTENSION_KIND = {
    "png": "png",
    "jpg": "jpeg",
    "jpeg": "jpeg",
    "pdf": "pdf",
    "docx": "docx",
    "xlsx": "xlsx",
    "txt": "txt",
    "csv": "csv",
}
TEXT_KINDS = frozenset({"txt", "csv"})
TEXT_MIME = {"txt": "text/plain", "csv": "text/csv"}
IMAGE_KINDS = frozenset({"png", "jpeg"})
ALLOWED_CONTROL_BYTES = frozenset({0x09, 0x0A, 0x0D})

def _reject(code: str) -> None:
    raise AttachmentRejected(code, MESSAGES[code])


def _extension(filename: str) -> str:
    return Path(filename).suffix.lower().lstrip(".")


def _validate_text(data: bytes, encoding: str) -> None:
    try:
        data.decode(encoding)
    except (UnicodeDecodeError, LookupError):
        _reject("not_text")
    for byte in data:
        if byte == 0 or byte == 0x7F or (byte < 0x20 and byte not in ALLOWED_CONTROL_BYTES):
            _reject("not_text")


def _validate_image(data: bytes, profile: AttachmentProfile) -> None:
    # Never rely on Pillow's default bomb threshold; ours comes from config.
    Image.MAX_IMAGE_PIXELS = profile.max_image_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                _check_image_size(image.size, profile)
                image.verify()
            with Image.open(BytesIO(data)) as image:
                _check_image_size(image.size, profile)
    except AttachmentRejected:
        raise
    except Image.DecompressionBombError:
        _reject("image_too_large")
    except Exception:
        _reject("bad_image")


def _check_image_size(size: tuple[int, int], profile: AttachmentProfile) -> None:
    width, height = size
    if width > profile.max_image_side or height > profile.max_image_side:
        _reject("image_too_large")
    if width * height > profile.max_image_pixels:
        _reject("image_too_large")


def _detect(filename: str, data: bytes, profile: AttachmentProfile) -> tuple[str, str]:
    extension = _extension(filename)
    expected = EXTENSION_KIND.get(extension)
    if expected is None:
        _reject("type_not_allowed")

    if expected in TEXT_KINDS:
        if expected not in profile.allowed_types:
            _reject("type_not_allowed")
        _validate_text(data, profile.text_must_decode)
        return expected, TEXT_MIME[expected]

    guess = filetype.guess(data)
    if guess is None:
        _reject("type_mismatch")
    detected = "jpeg" if guess.extension in ("jpg", "jpeg") else guess.extension
    if detected != expected:
        _reject("type_mismatch")
    if detected not in profile.allowed_types:
        _reject("type_not_allowed")
    if detected in IMAGE_KINDS:
        _validate_image(data, profile)
    return detected, guess.mime


def validate_files(
    files: Sequence[tuple[str, bytes]],
    profile_name: str,
    config: Optional[AttachmentsConfig] = None,
) -> list[ValidatedFile]:
    """Validate attachments against a named profile.

    The profile is selected only by `profile_name`; filename and bytes cannot
    choose a profile. Original filenames are used only to read the extension
    and never appear in results, messages or exceptions.
    """
    config = config or load_attachments_config()
    profile = config.profile(profile_name)

    if len(files) > profile.max_files_per_message:
        _reject("too_many_files")
    total = sum(len(data) for _, data in files)
    validated: list[ValidatedFile] = []
    for index, (filename, data) in enumerate(files, start=1):
        if not data:
            _reject("empty_file")
        if len(data) > profile.max_file_bytes:
            _reject("too_large")
        if total > profile.max_total_bytes:
            _reject("total_too_large")
        kind, mime = _detect(filename, data, profile)
        validated.append(ValidatedFile(f"Attachment {index}", kind, mime, len(data), data))
    return validated
