import pytest

from attachments.extractors.docx import DocxExtractor
from attachments.extractors.xlsx import XlsxExtractor
from attachments.models import AttachmentRejected
from tests.attachments.extract_fixtures import corrupt_docx_bytes, docx_rich_bytes, xlsx_workbook_bytes
from tests.attachments.profiles import make_config, make_file

CONFIG = make_config()
PROFILE = CONFIG.profile("chat_attachment")


class TestDocx:
    def test_blocks_in_order_with_levels_and_table(self):
        doc = DocxExtractor().extract(make_file("docx", docx_rich_bytes()), PROFILE)
        assert [(b.type, b.level) for b in doc.blocks[:5]] == [
            ("heading", 1), ("paragraph", None), ("heading", 2), ("paragraph", None), ("table", None)]
        assert doc.blocks[0].text == "1. Fees"
        assert doc.blocks[2].text == "1.1 Account maintenance"
        assert "Tier | Fee" in doc.blocks[4].text
        assert doc.method == "library"

    def test_inline_image_warning(self):
        doc = DocxExtractor().extract(make_file("docx", docx_rich_bytes()), PROFILE)
        assert "inline images were ignored" in doc.warnings

    def test_corrupt_zip_is_unreadable(self):
        with pytest.raises(AttachmentRejected) as info:
            DocxExtractor().extract(make_file("docx", corrupt_docx_bytes()), PROFILE)
        assert info.value.code == "unreadable_file"
        assert "garbage-body" not in str(info.value)

    def test_zip_limits_are_unsafe(self):
        with pytest.raises(AttachmentRejected) as info:
            DocxExtractor().extract(
                make_file("docx", docx_rich_bytes()),
                make_config(zip_max_uncompressed_bytes=10).profile("chat_attachment"),
            )
        assert info.value.code == "zip_unsafe"

    def test_entry_count_limit_is_unsafe(self):
        with pytest.raises(AttachmentRejected) as info:
            DocxExtractor().extract(
                make_file("docx", docx_rich_bytes()),
                make_config(zip_max_entries=1).profile("chat_attachment"),
            )
        assert info.value.code == "zip_unsafe"


class TestXlsx:
    def test_sheets_headings_tables_and_formula_warning(self):
        doc = XlsxExtractor().extract(make_file("xlsx", xlsx_workbook_bytes()), PROFILE)
        headings = [b.text for b in doc.blocks if b.type == "heading"]
        assert headings == ["October", "November"]
        assert all(b.level == 2 for b in doc.blocks if b.type == "heading")
        assert doc.blocks[1].type == "table"
        assert "formula without cached value" in doc.warnings
        assert doc.method == "library"

    def test_limits_and_warnings(self):
        doc = XlsxExtractor().extract(
            make_file("xlsx", xlsx_workbook_bytes()),
            make_config(max_sheets=1, max_rows_per_sheet=2, max_cols=2,
                        max_cell_chars=3).profile("chat_attachment"),
        )
        assert doc.truncated is True
        for warning in ("sheet limit reached", "row limit reached", "column limit reached",
                        "cell text truncated"):
            assert warning in doc.warnings
        assert len([b for b in doc.blocks if b.type == "heading"]) == 1

    def test_zip_limit_is_unsafe(self):
        with pytest.raises(AttachmentRejected) as info:
            XlsxExtractor().extract(
                make_file("xlsx", xlsx_workbook_bytes()),
                make_config(zip_max_uncompressed_bytes=10).profile("chat_attachment"),
            )
        assert info.value.code == "zip_unsafe"
