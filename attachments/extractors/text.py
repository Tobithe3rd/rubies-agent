from __future__ import annotations

import re

from attachments.config import AttachmentProfile
from attachments.extractors.base import Extractor, finalize, register_extractor
from attachments.models import MESSAGES, AttachmentRejected, Block, ExtractedDocument, ValidatedFile


@register_extractor("txt")
class TextExtractor(Extractor):
    def extract(self, file: ValidatedFile, profile: AttachmentProfile) -> ExtractedDocument:
        try:
            text = file.data.decode(profile.text_must_decode)
        except (UnicodeDecodeError, LookupError):
            raise AttachmentRejected("not_text", MESSAGES["not_text"]) from None

        blocks = [
            Block("paragraph", part.strip())
            for part in re.split(r"\n\s*\n", text)
            if part.strip()
        ]
        document = ExtractedDocument(
            name=file.display_name, kind=file.kind, blocks=blocks,
            page_count=None, method="native_text",
        )
        return finalize(document, profile)
