import pytest

from attachments.models import AttachmentRejected
from attachments.validate import validate_files
from core.config import ConfigError
from tests.attachments import fixtures as fx
from tests.attachments.profiles import make_config


def run(files, **overrides):
    return validate_files(files, "chat_attachment", make_config(**overrides))


HAPPY = [
    ("receipt.PNG", fx.png_bytes(), "png", "image/png"),
    ("photo.JPG", fx.jpeg_bytes(), "jpeg", "image/jpeg"),
    ("statement.pdf", fx.pdf_bytes(), "pdf", "application/pdf"),
    ("policy.docx", fx.docx_bytes(), "docx",
     "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("data.xlsx", fx.xlsx_bytes(), "xlsx",
     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    ("notes.txt", fx.text_bytes(), "txt", "text/plain"),
    ("data.csv", fx.csv_bytes(), "csv", "text/csv"),
]


class TestHappyPath:
    @pytest.mark.parametrize("filename,data,kind,mime", HAPPY)
    def test_each_allowed_type(self, filename, data, kind, mime):
        [item] = run([(filename, data)])
        assert (item.kind, item.detected_mime) == (kind, mime)
        assert item.size == len(data)
        assert item.data == data

    def test_batch_gets_neutral_numbered_names(self):
        items = run([(name, data) for name, data, _, _ in HAPPY])
        assert [i.display_name for i in items] == [f"Attachment {n}" for n in range(1, 8)]
        assert all(name not in i.display_name for name, *_ in HAPPY for i in items)

    def test_uppercase_extension_accepted(self):
        [item] = run([("SHOUT.PNG", fx.png_bytes())])
        assert item.kind == "png"

    def test_double_extension_uses_last_suffix(self):
        [item] = run([("report.pdf.png", fx.png_bytes())])
        assert item.kind == "png"

    def test_data_excluded_from_repr_and_dict(self):
        [item] = run([("receipt.png", fx.png_bytes())])
        payload = item.data
        assert "data" not in item.to_dict()
        assert str(list(item.to_dict().values())) != str(payload)
        assert repr(payload) not in repr(item)
        assert payload[:8] not in repr(item).encode()


class TestRejections:
    @pytest.mark.parametrize("filename,data,overrides,code", [
        ("secret-many.txt", fx.text_bytes(), {"max_files_per_message": 1}, "too_many_files"),
        ("secret-big.txt", b"a" * 60, {"max_file_bytes": 50}, "too_large"),
        ("secret-type.gif", fx.gif_bytes(), {}, "type_not_allowed"),
        ("secret-spoof.png", fx.text_bytes(), {}, "type_mismatch"),
        ("secret-mismatch.png", fx.pdf_bytes(), {}, "type_mismatch"),
        ("secret-nul.txt", b"hello\x00world", {}, "not_text"),
        ("secret-utf.txt", b"\xff\xfe\xfa", {}, "not_text"),
        ("secret-bad.png", fx.truncated_png_bytes(), {}, "bad_image"),
        ("secret-bomb.png", fx.bomb_png_bytes(), {}, "image_too_large"),
        ("secret-empty.txt", b"", {}, "empty_file"),
    ])
    def test_rejection_code_and_safe_message(self, filename, data, overrides, code):
        extra = [("filler.txt", b"hello")] if code == "too_many_files" else []
        with pytest.raises(AttachmentRejected) as info:
            run([(filename, data)] + extra, **overrides)
        assert info.value.code == code
        assert filename not in str(info.value)
        assert filename not in info.value.message

    def test_too_many_files_counts_before_content(self):
        files = [(f"secret-{n}.txt", b"ok") for n in range(4)]
        with pytest.raises(AttachmentRejected) as info:
            run(files, max_files_per_message=3)
        assert info.value.code == "too_many_files"

    def test_two_files_exceed_total(self):
        files = [("a.txt", b"a" * 60), ("b.txt", b"b" * 60)]
        with pytest.raises(AttachmentRejected) as info:
            run(files, max_file_bytes=100, max_total_bytes=100)
        assert info.value.code == "total_too_large"

    def test_unknown_profile_raises_before_reading_files(self):
        with pytest.raises(ConfigError, match="unknown attachment profile"):
            validate_files([("safe.png", fx.png_bytes())], "other_profile", make_config())
