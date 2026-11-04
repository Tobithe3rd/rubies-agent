"""In-code attachment fixtures. No binaries are committed."""
import io
import struct
import zipfile
import zlib

from PIL import Image


def png_bytes(size=(8, 8), color=(200, 30, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "PNG")
    return buf.getvalue()


def jpeg_bytes(size=(8, 8), color=(30, 120, 200)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


def pdf_bytes() -> bytes:
    return (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog >>\nendobj\n"
            b"trailer\n<< /Root 1 0 R >>\n%%EOF\n")


def _zip(entries: list[tuple[str, bytes]]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in entries:
            archive.writestr(name, data)
    return buf.getvalue()


CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="xml" ContentType="application/xml"/></Types>'
)


def docx_bytes() -> bytes:
    return _zip([
        ("[Content_Types].xml", CONTENT_TYPES.encode()),
        ("word/document.xml", b'<?xml version="1.0"?><w:document xmlns:w="urn:x"/>'),
    ])


def xlsx_bytes() -> bytes:
    return _zip([
        ("[Content_Types].xml", CONTENT_TYPES.encode()),
        ("xl/workbook.xml", b'<?xml version="1.0"?><workbook/>'),
    ])


def text_bytes() -> bytes:
    return "Rubies MFB statement text, fictional customer Adaeze Nwachukwu.".encode("utf-8")


def csv_bytes() -> bytes:
    return b"date,reference,amount_ngn\n2026-10-01,RUB-TX-95000,20000.00\n"


def gif_bytes() -> bytes:
    return b"GIF89a" + b"\x00" * 20


def truncated_png_bytes() -> bytes:
    return b"\x89PNG\r\n\x1a\n" + b"not-an-image"


def bomb_png_bytes(width: int = 20000, height: int = 2001) -> bytes:
    """Patch a 1x1 PNG's IHDR so it claims huge dimensions cheaply."""
    png = bytearray(png_bytes((1, 1)))
    png[16:20] = struct.pack(">I", width)
    png[20:24] = struct.pack(">I", height)
    png[29:33] = struct.pack(">I", zlib.crc32(bytes(png[12:29])) & 0xFFFFFFFF)
    return bytes(png)
