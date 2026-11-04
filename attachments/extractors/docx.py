from __future__ import annotations

import re
from io import BytesIO

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from attachments.config import AttachmentProfile
from attachments.extractors.base import Extractor, NeedsVision, finalize, register_extractor
from attachments.extractors.zipcheck import check_zip
from attachments.models import MESSAGES, AttachmentRejected, Block, ExtractedDocument, ValidatedFile

HEADING = re.compile(r"^Heading\s+(\d+)$")


def _heading_level(style_name: str) -> int | None:
    if style_name == "Title":
        return 1
    match = HEADING.match(style_name)
    return int(match.group(1)) if match else None


def _blocks(document) -> list[Block]:
    blocks: list[Block] = []
    for child in document.element.body.iterchildren():
        if child.tag.endswith("}p"):
            paragraph = Paragraph(child, document)
            if not paragraph.text.strip():
                continue
            level = _heading_level(paragraph.style.name if paragraph.style else "")
            blocks.append(Block("heading" if level else "paragraph", paragraph.text,
                                level=level))
        elif child.tag.endswith("}tbl"):
            table = Table(child, document)
            rows = [" | ".join(cell.text for cell in row.cells) for row in table.rows]
            if any(row.strip() for row in rows):
                blocks.append(Block("table", "\n".join(rows)))
    return blocks


@register_extractor("docx")
class DocxExtractor(Extractor):
    def extract(self, file: ValidatedFile, profile: AttachmentProfile) -> ExtractedDocument:
        check_zip(file.data, profile)
        try:
            document = Document(BytesIO(file.data))
            blocks = _blocks(document)
            has_images = len(document.inline_shapes) > 0
        except (AttachmentRejected, NeedsVision):
            raise
        except Exception:
            raise AttachmentRejected("unreadable_file", MESSAGES["unreadable_file"]) from None

        warnings = ["inline images were ignored"] if has_images else []
        extracted = ExtractedDocument(
            name=file.display_name, kind=file.kind, blocks=blocks,
            page_count=None, warnings=warnings, method="library",
        )
        return finalize(extracted, profile)
