from __future__ import annotations

import zipfile
from io import BytesIO

from attachments.config import AttachmentProfile
from attachments.models import MESSAGES, AttachmentRejected


def check_zip(data: bytes, profile: AttachmentProfile) -> None:
    """Reject zip containers that are unsafe to expand (count, size, ratio)."""
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError):
        raise AttachmentRejected("unreadable_file", MESSAGES["unreadable_file"]) from None

    if len(infos) > profile.zip_max_entries:
        raise AttachmentRejected("zip_unsafe", MESSAGES["zip_unsafe"])

    total_uncompressed = sum(info.file_size for info in infos)
    total_compressed = sum(info.compress_size for info in infos)
    if total_uncompressed > profile.zip_max_uncompressed_bytes:
        raise AttachmentRejected("zip_unsafe", MESSAGES["zip_unsafe"])
    if total_uncompressed / max(1, total_compressed) > profile.zip_max_ratio:
        raise AttachmentRejected("zip_unsafe", MESSAGES["zip_unsafe"])
    for info in infos:
        if info.file_size / max(1, info.compress_size) > profile.zip_max_ratio:
            raise AttachmentRejected("zip_unsafe", MESSAGES["zip_unsafe"])
