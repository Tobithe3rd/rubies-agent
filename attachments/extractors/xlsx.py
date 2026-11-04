from __future__ import annotations

from io import BytesIO

from openpyxl import load_workbook

from attachments.config import AttachmentProfile
from attachments.extractors.base import Extractor, NeedsVision, finalize, register_extractor
from attachments.extractors.zipcheck import check_zip
from attachments.models import MESSAGES, AttachmentRejected, Block, ExtractedDocument, ValidatedFile


def _cell_text(value, profile: AttachmentProfile) -> tuple[str, bool]:
    if value is None:
        return "", False
    text = str(value)
    if len(text) > profile.max_cell_chars:
        return text[:profile.max_cell_chars], True
    return text, False


def _sheet_rows(sheet, profile: AttachmentProfile) -> list[tuple]:
    return list(sheet.iter_rows(
        min_row=1, max_row=profile.max_rows_per_sheet,
        max_col=profile.max_cols, values_only=True,
    ))


def _has_uncached_formula(cached, formulas) -> bool:
    for cached_row, formula_row in zip(cached, formulas):
        for cached_value, formula_value in zip(cached_row, formula_row):
            if (cached_value is None and isinstance(formula_value, str)
                    and formula_value.startswith("=")):
                return True
    return False


@register_extractor("xlsx")
class XlsxExtractor(Extractor):
    def extract(self, file: ValidatedFile, profile: AttachmentProfile) -> ExtractedDocument:
        check_zip(file.data, profile)
        try:
            cached_wb = load_workbook(BytesIO(file.data), read_only=True, data_only=True)
            formula_wb = load_workbook(BytesIO(file.data), read_only=True, data_only=False)
            blocks: list[Block] = []
            warnings: list[str] = []
            truncated = False

            sheets = cached_wb.worksheets
            if len(sheets) > profile.max_sheets:
                truncated = True
                warnings.append("sheet limit reached")
            for index, sheet in enumerate(sheets[:profile.max_sheets]):
                blocks.append(Block("heading", sheet.title, level=2))
                cached_rows = _sheet_rows(sheet, profile)
                if _has_uncached_formula(cached_rows, _sheet_rows(formula_wb.worksheets[index], profile)):
                    warnings.append("formula without cached value")
                if (sheet.max_row or 0) > profile.max_rows_per_sheet:
                    truncated = True
                    warnings.append("row limit reached")
                if (sheet.max_column or 0) > profile.max_cols:
                    truncated = True
                    warnings.append("column limit reached")

                rows = []
                for row in cached_rows:
                    cells, cell_cut = [], False
                    for value in row:
                        text, cut = _cell_text(value, profile)
                        cells.append(text)
                        cell_cut = cell_cut or cut
                    if cell_cut:
                        truncated = True
                        warnings.append("cell text truncated")
                    if any(cells):
                        rows.append(" | ".join(cells))
                if rows:
                    blocks.append(Block("table", "\n".join(rows)))
        except (AttachmentRejected, NeedsVision):
            raise
        except Exception:
            raise AttachmentRejected("unreadable_file", MESSAGES["unreadable_file"]) from None
        finally:
            for workbook in locals().get("cached_wb"), locals().get("formula_wb"):
                if workbook is not None:
                    try:
                        workbook.close()
                    except Exception:
                        pass

        extracted = ExtractedDocument(
            name=file.display_name, kind=file.kind, blocks=blocks,
            page_count=None, warnings=warnings, truncated=truncated, method="library",
        )
        return finalize(extracted, profile)
