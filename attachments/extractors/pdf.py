from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from attachments.config import AttachmentProfile
from attachments.extractors.base import Extractor, NeedsVision, finalize, register_extractor
from attachments.models import MESSAGES, AttachmentRejected, Block, ExtractedDocument, ValidatedFile


@register_extractor("pdf")
class PdfExtractor(Extractor):
    def extract(self, file: ValidatedFile, profile: AttachmentProfile) -> ExtractedDocument:
        try:
            reader = PdfReader(BytesIO(file.data))
            if reader.is_encrypted:
                raise AttachmentRejected("encrypted_file", MESSAGES["encrypted_file"])

            total_pages = len(reader.pages)
            selected = min(total_pages, profile.max_pdf_pages)
            truncated = total_pages > selected
            page_texts = []
            for index in range(selected):
                text = reader.pages[index].extract_text() or ""
                page_texts.append((index + 1, text))
        except (AttachmentRejected, NeedsVision):
            raise
        except Exception:
            raise AttachmentRejected("unreadable_file", MESSAGES["unreadable_file"]) from None

        if selected == 0 or sum(len(t) for _, t in page_texts) / selected < profile.pdf_min_chars_per_page:
            raise NeedsVision("no_text_layer")

        blocks = [Block("paragraph", text, page=page) for page, text in page_texts if text.strip()]
        warnings = ["page limit reached"] if truncated else []
        document = ExtractedDocument(
            name=file.display_name, kind=file.kind, blocks=blocks,
            page_count=total_pages, warnings=warnings, truncated=truncated, method="library",
        )
        return finalize(document, profile)
