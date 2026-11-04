from __future__ import annotations

import csv
import io
from itertools import islice

from attachments.config import AttachmentProfile
from attachments.extractors.base import Extractor, finalize, register_extractor
from attachments.models import MESSAGES, AttachmentRejected, Block, ExtractedDocument, ValidatedFile


def _dialect(text: str):
    sample = text[:2048]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        return csv.excel


@register_extractor("csv")
class CsvExtractor(Extractor):
    def extract(self, file: ValidatedFile, profile: AttachmentProfile) -> ExtractedDocument:
        try:
            text = file.data.decode(profile.text_must_decode)
        except (UnicodeDecodeError, LookupError):
            raise AttachmentRejected("not_text", MESSAGES["not_text"]) from None

        reader = csv.reader(io.StringIO(text), _dialect(text))
        rows = []
        truncated = False
        for row in islice(reader, profile.max_rows_per_sheet + 1):
            if len(rows) == profile.max_rows_per_sheet:
                truncated = True
                break
            if len(row) > profile.max_cols:
                truncated = True
                row = row[:profile.max_cols]
            cells = []
            for cell in row:
                if len(cell) > profile.max_cell_chars:
                    truncated = True
                    cell = cell[:profile.max_cell_chars]
                cells.append(cell)
            rows.append(" | ".join(cells))

        warnings = ["table truncated at the configured limits"] if truncated else []
        document = ExtractedDocument(
            name=file.display_name, kind=file.kind,
            blocks=[Block("table", "\n".join(rows))] if rows else [],
            page_count=None, warnings=warnings, truncated=truncated, method="native_text",
        )
        return finalize(document, profile)
