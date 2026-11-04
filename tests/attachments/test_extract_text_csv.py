import pytest

from attachments.extract import extract_document
from attachments.extractors.text import TextExtractor
from attachments.extractors.csv import CsvExtractor
from attachments.models import AttachmentRejected
from tests.attachments.profiles import make_config, make_file


def cfg(**overrides):
    return make_config(**overrides)


class TestTextExtractor:
    def test_blank_line_separated_paragraphs(self):
        file = make_file("txt", b"First paragraph.\n\nSecond paragraph.")
        doc = TextExtractor().extract(file, cfg().profile("chat_attachment"))
        assert [b.type for b in doc.blocks] == ["paragraph", "paragraph"]
        assert [b.text for b in doc.blocks] == ["First paragraph.", "Second paragraph."]
        assert doc.method == "native_text"

    def test_control_characters_stripped(self):
        file = make_file("txt", b"Hello\x00\x07 world\n\nSecond\tline")
        doc = TextExtractor().extract(file, cfg().profile("chat_attachment"))
        text = "\n".join(b.text for b in doc.blocks)
        assert "\x00" not in text and "\x07" not in text
        assert "Hello world" in text and "\t" in text

    def test_char_cap_truncates_at_block_boundary(self):
        file = make_file("txt", b"A" * 50 + b"\n\n" + b"B" * 50)
        doc = TextExtractor().extract(file, cfg(max_chars_per_document=60).profile("chat_attachment"))
        assert doc.truncated is True
        assert "text truncated at the document limit" in doc.warnings
        assert sum(len(b.text) for b in doc.blocks) == 60
        assert doc.blocks[0].text == "A" * 50
        assert doc.blocks[1].text == "B" * 10

    def test_invalid_encoding_is_not_text(self):
        file = make_file("txt", b"\xff\xfe\xfa")
        with pytest.raises(AttachmentRejected) as info:
            TextExtractor().extract(file, cfg().profile("chat_attachment"))
        assert info.value.code == "not_text"


class TestCsvExtractor:
    def test_one_table_block(self):
        file = make_file("csv", b"date,reference,amount\n2026-10-01,RUB-TX-95000,20000\n")
        doc = CsvExtractor().extract(file, cfg().profile("chat_attachment"))
        assert len(doc.blocks) == 1 and doc.blocks[0].type == "table"
        assert doc.blocks[0].text == "date | reference | amount\n2026-10-01 | RUB-TX-95000 | 20000"
        assert doc.method == "native_text"

    def test_sniffed_semicolon_delimiter(self):
        doc = CsvExtractor().extract(
            make_file("csv", b"a;b;c\n1;2;3\n"), cfg().profile("chat_attachment"))
        assert doc.blocks[0].text == "a | b | c\n1 | 2 | 3"

    def test_row_col_and_cell_caps(self):
        data = b"one,two,three\n1,2,3\n4,5,6\n"
        doc = CsvExtractor().extract(
            make_file("csv", data),
            cfg(max_rows_per_sheet=2, max_cols=2, max_cell_chars=3).profile("chat_attachment"),
        )
        assert doc.truncated is True
        assert "table truncated at the configured limits" in doc.warnings
        assert doc.blocks[0].text == "one | two\n1 | 2"

    def test_no_text_in_warnings(self):
        marker = "ZzSecretMarker"
        doc = CsvExtractor().extract(
            make_file("csv", (marker * 3 + ",x\n").encode()),
            cfg(max_cell_chars=1).profile("chat_attachment"),
        )
        assert all(marker not in warning for warning in doc.warnings)


class TestExtractDispatch:
    def test_txt_and_csv_via_extract_document(self):
        config = cfg()
        txt = extract_document(make_file("txt", b"hello"), "chat_attachment", config)
        csv = extract_document(make_file("csv", b"a,b\n1,2\n"), "chat_attachment", config)
        assert txt.kind == "txt" and csv.kind == "csv"

    @pytest.mark.parametrize("kind", ["png", "jpeg"])
    def test_images_go_to_vision(self, kind):
        from attachments.vision.mock import MockVisionExtractor
        config = cfg()
        doc = extract_document(make_file(kind, b"anything"), "chat_attachment", config,
                               MockVisionExtractor(config.vision))
        assert doc.method == "vision"
