import pytest

from attachments.extract import extract_document
from attachments.extractors.base import NeedsVision
from attachments.extractors.pdf import PdfExtractor
from attachments.models import AttachmentRejected
from tests.attachments.extract_fixtures import (
    blank_pdf_bytes,
    encrypted_pdf_bytes,
    text_pdf_bytes,
)
from tests.attachments.profiles import make_config, make_file

CONFIG = make_config()
PROFILE = CONFIG.profile("chat_attachment")
TEXT = "Rubies MFB fictional statement text for customer Adaeze Nwachukwu, amount NGN 20,000.00."


class TestPdfExtractor:
    def test_text_pages_with_page_numbers(self):
        doc = PdfExtractor().extract(make_file("pdf", text_pdf_bytes([TEXT, TEXT])), PROFILE)
        assert doc.page_count == 2
        assert [(b.type, b.page) for b in doc.blocks] == [("paragraph", 1), ("paragraph", 2)]
        assert TEXT in doc.blocks[0].text
        assert doc.method == "library"

    def test_blank_pages_need_vision(self):
        doc = make_file("pdf", blank_pdf_bytes(2))
        with pytest.raises(NeedsVision) as info:
            PdfExtractor().extract(doc, PROFILE)
        assert "no_text_layer" in str(info.value)

    def test_encrypted_pdf_is_rejected_without_decrypting(self):
        with pytest.raises(AttachmentRejected) as info:
            PdfExtractor().extract(make_file("pdf", encrypted_pdf_bytes()), PROFILE)
        assert info.value.code == "encrypted_file"

    def test_page_cap_sets_truncated(self):
        doc = PdfExtractor().extract(
            make_file("pdf", text_pdf_bytes([TEXT, TEXT, TEXT])),
            make_config(max_pdf_pages=2).profile("chat_attachment"),
        )
        assert doc.page_count == 3
        assert doc.truncated is True
        assert "page limit reached" in doc.warnings
        assert len(doc.blocks) == 2

    def test_corrupt_pdf_is_unreadable(self):
        marker = "ZzSecretMarker"
        with pytest.raises(AttachmentRejected) as info:
            PdfExtractor().extract(make_file("pdf", b"%PDF-1.4\n" + marker.encode()), PROFILE)
        assert info.value.code == "unreadable_file"
        assert marker not in str(info.value)


class TestDispatch:
    def test_needs_vision_goes_to_vision(self):
        from attachments.vision.mock import MockVisionExtractor
        extractor = MockVisionExtractor(CONFIG.vision, text="Scanned text.")
        doc = extract_document(make_file("pdf", blank_pdf_bytes()), "chat_attachment",
                               CONFIG, extractor)
        assert doc.method == "vision"
        assert doc.blocks[0].text == "Scanned text."
