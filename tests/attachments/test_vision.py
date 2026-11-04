import logging
from io import BytesIO

import pytest
from pypdf import PdfReader

from attachments.extract import extract_document
from attachments.models import AttachmentRejected
from attachments.vision.base import VisionResult
from attachments.vision.mock import MockVisionExtractor
from tests.attachments import fixtures as fx
from tests.attachments.extract_fixtures import blank_pdf_bytes
from tests.attachments.profiles import make_config, make_file, make_vision

CONFIG = make_config()
PROFILE = CONFIG.profile("chat_attachment")


def run_image(text="Hello from the receipt.", config=CONFIG):
    extractor = MockVisionExtractor(config.vision, text=text)
    return extract_document(make_file("png", fx.png_bytes()), "chat_attachment", config, extractor)


class RecordingExtractor:
    def __init__(self, text="Transcribed."):
        self.text = text
        self.calls = []

    def transcribe(self, data, kind):
        pages = len(PdfReader(BytesIO(data)).pages) if kind == "pdf" else None
        self.calls.append((kind, pages))
        return VisionResult(self.text, 10, 5, 3)


class TestVisionGlue:
    def test_image_becomes_vision_document(self):
        doc = run_image()
        assert doc.method == "vision"
        assert [b.type for b in doc.blocks] == ["paragraph"]
        assert doc.blocks[0].text == "Hello from the receipt."
        assert CONFIG.vision.warning_text in doc.warnings

    def test_scanned_pdf_falls_through_to_vision(self):
        extractor = MockVisionExtractor(CONFIG.vision, text="Scanned page text.")
        doc = extract_document(make_file("pdf", blank_pdf_bytes(2)), "chat_attachment",
                               CONFIG, extractor)
        assert doc.method == "vision"
        assert doc.page_count == 2
        assert doc.blocks[0].text == "Scanned page text."

    def test_pdf_trimmed_to_vision_page_limit(self):
        extractor = RecordingExtractor()
        doc = extract_document(make_file("pdf", blank_pdf_bytes(5)), "chat_attachment",
                               CONFIG, extractor)
        assert extractor.calls == [("pdf", 3)]
        assert doc.page_count == 5
        assert doc.truncated is True
        assert "page limit reached" in doc.warnings

    def test_escaped_asterisks_unescaped(self):
        doc = run_image(text=r"Card: \*\*\*\* \*\*\*\* \*\*\*\* 4417")
        assert doc.blocks[0].text == "Card: **** **** **** 4417"

    def test_code_fences_stripped(self):
        doc = run_image(text="```text\nReceipt line\n```")
        assert doc.blocks[0].text == "Receipt line"

    @pytest.mark.parametrize("text", [
        "NO_TEXT", "NO_TEXT.", "`no_text`", "**NO_TEXT**", "No text", "NO-TEXT", "", "   ",
    ])
    def test_no_text_raises(self, text):
        with pytest.raises(AttachmentRejected) as info:
            run_image(text=text)
        assert info.value.code == "no_readable_text"

    def test_no_text_inside_a_sentence_passes_through(self):
        text = "The receipt says there is no text printed below the total."
        doc = run_image(text=text)
        assert doc.blocks[0].text == text

    def test_warning_text_comes_from_config(self):
        config = make_config(vision=make_vision(warning_text="Custom AI warning."))
        doc = run_image(config=config)
        assert "Custom AI warning." in doc.warnings

    def test_one_structured_log_line_without_text(self, caplog):
        with caplog.at_level(logging.INFO, logger="rubies.attachments"):
            run_image(text="UniqueSecretTranscription")
        lines = [r.message for r in caplog.records if r.name == "rubies.attachments"]
        assert len(lines) == 1
        assert "attachment_vision" in lines[0] and '"ok": true' in lines[0]
        assert "UniqueSecretTranscription" not in lines[0]

    def test_failed_call_logs_ok_false(self, caplog):
        with caplog.at_level(logging.INFO, logger="rubies.attachments"):
            with pytest.raises(AttachmentRejected):
                run_image(text="NO_TEXT")
        assert '"ok": false' in caplog.records[-1].message
