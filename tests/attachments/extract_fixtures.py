"""Fixtures for text-extractor tests. Built in code, never committed."""
import io

from docx import Document
from docx.shared import Pt
from openpyxl import Workbook
from pypdf import PdfWriter

from tests.attachments.fixtures import png_bytes


def _pdf_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def text_pdf_bytes(page_texts=None) -> bytes:
    page_texts = page_texts or [
        "Rubies MFB statement page one. Fictional customer Adaeze Nwachukwu.",
    ]
    count = len(page_texts)
    page_ids = [4 + 2 * i for i in range(count)]
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] "
        f"/Count {count} >>".encode(),
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    for index, text in enumerate(page_texts):
        content = f"BT /F1 12 Tf 72 720 Td ({_pdf_escape(text)}) Tj ET".encode("latin-1")
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_ids[index] + 1} 0 R >>".encode()
        )
        objects.append(
            b"<< /Length " + str(len(content)).encode() + b" >>\nstream\n"
            + content + b"\nendstream"
        )
    out = b"%PDF-1.4\n"
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
    for offset in offsets:
        out += f"{offset:010d} 00000 n \n".encode()
    out += (f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref}\n%%EOF\n").encode()
    return out


def blank_pdf_bytes(pages: int = 1) -> bytes:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def encrypted_pdf_bytes(password: str = "secret") -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.encrypt(password)
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def docx_rich_bytes() -> bytes:
    document = Document()
    document.add_heading("1. Fees", level=1)
    document.add_paragraph("Body one. Fictional customer Adaeze Nwachukwu.")
    document.add_heading("1.1 Account maintenance", level=2)
    document.add_paragraph("Body two. Monthly fee is NGN 250.00.")
    table = document.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "Tier"
    table.cell(0, 1).text = "Fee"
    table.cell(1, 0).text = "Tier 2"
    table.cell(1, 1).text = "NGN 250.00"
    document.add_picture(io.BytesIO(png_bytes((4, 4))), width=Pt(12))
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def xlsx_workbook_bytes() -> bytes:
    workbook = Workbook()
    october = workbook.active
    october.title = "October"
    october.append(["date", "reference", "amount_ngn"])
    october.append(["2026-10-01", "RUB-TX-95000", 20000])
    october.append(["2026-10-02", "RUB-TX-95001", 5000])
    october["A5"] = "=SUM(C2:C3)"
    november = workbook.create_sheet("November")
    november.append(["date", "reference", "amount_ngn"])
    november.append(["2026-11-01", "RUB-TX-96000", 7500])
    buf = io.BytesIO()
    workbook.save(buf)
    return buf.getvalue()


def corrupt_docx_bytes() -> bytes:
    return b"PK\x03\x04" + b"garbage-body-not-a-real-zip" * 10
