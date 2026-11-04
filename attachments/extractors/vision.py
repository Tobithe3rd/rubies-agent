from __future__ import annotations

import json
import logging
import re
import string
from io import BytesIO

from pypdf import PdfReader, PdfWriter

from attachments.config import AttachmentProfile, VisionConfig
from attachments.extractors.base import finalize, strip_control
from attachments.models import MESSAGES, AttachmentRejected, Block, ExtractedDocument, ValidatedFile
from attachments.vision.base import VisionExtractor, get_vision_extractor

logger = logging.getLogger("rubies.attachments")

FENCE = re.compile(r"^\s*```[^\n]*\n(.*?)\n```\s*$", re.S)
EDGE_CHARS = string.punctuation + "“”‘’«»… \t\r\n\f\v"
NO_TEXT_FORMS = frozenset({"no_text", "no text", "no-text"})


def _trim_pdf(data: bytes, max_pages: int) -> tuple[bytes, int, bool]:
    reader = PdfReader(BytesIO(data))
    total = len(reader.pages)
    writer = PdfWriter()
    for page in reader.pages[:max_pages]:
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue(), total, total > max_pages


def _clean(text: str) -> str:
    text = strip_control(text.replace("\\*", "*"))
    fenced = FENCE.match(text)
    if fenced:
        text = fenced.group(1)
    return text.strip()


def _is_no_text(text: str) -> bool:
    """True only when the whole reply is NO_TEXT (punctuation/emphasis ignored)."""
    normalized = text.strip(EDGE_CHARS).casefold()
    return normalized in NO_TEXT_FORMS


def _log(config, kind, page_count, result, ok) -> None:
    payload = {
        "event": "attachment_vision",
        "model_id": config.model_id,
        "kind": kind,
        "page_count": page_count,
        "latency_ms": result.latency_ms if result else None,
        "input_tokens": result.input_tokens if result else None,
        "output_tokens": result.output_tokens if result else None,
        "ok": ok,
    }
    logger.info("attachment_vision %s", json.dumps(payload, sort_keys=True))


def extract_with_vision(
    file: ValidatedFile,
    profile: AttachmentProfile,
    vision_config: VisionConfig,
    extractor: VisionExtractor | None = None,
) -> ExtractedDocument:
    extractor = extractor or get_vision_extractor(vision_config)
    result = None
    page_count = None
    dropped = False
    ok = False
    try:
        data = file.data
        if file.kind == "pdf":
            data, page_count, dropped = _trim_pdf(data, profile.max_vision_pdf_pages)
        result = extractor.transcribe(data, file.kind)
        text = _clean(result.text)
        if not text or _is_no_text(text):
            raise AttachmentRejected("no_readable_text", MESSAGES["no_readable_text"])

        blocks = [
            Block("paragraph", part.strip())
            for part in re.split(r"\n\s*\n", text)
            if part.strip()
        ]
        warnings = [vision_config.warning_text]
        if dropped:
            warnings.append("page limit reached")
        document = ExtractedDocument(
            name=file.display_name, kind=file.kind, blocks=blocks,
            page_count=page_count, warnings=warnings, truncated=dropped, method="vision",
        )
        document = finalize(document, profile)
        ok = True
        return document
    finally:
        _log(vision_config, file.kind, page_count, result, ok)
