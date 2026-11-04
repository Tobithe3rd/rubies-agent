"""Live check for attachment vision. Run manually; not collected by pytest.

    .venv/bin/python scripts/checks/live_attachment_vision.py

Builds synthetic fixtures with Pillow, sends them to Bedrock through
extract_document, and prints block text, warnings, latency and tokens.
Prints no credentials.
"""
from __future__ import annotations

import io
import logging
import os
import sys

# the script lives in scripts/checks/, so the repo root is not on sys.path by default
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from dotenv import load_dotenv
from PIL import Image, ImageDraw, ImageFont

from attachments.config import load_attachments_config
from attachments.extract import extract_document
from attachments.models import ValidatedFile
from attachments.vision.base import get_vision_extractor

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(message)s")

LINES = [
    ("RUBIES MFB", 32),
    ("ATM CASH WITHDRAWAL", 22),
    ("Date: 14/10/2026  Time: 18:42", 18),
    ("Terminal: RMB-ATM-0042", 18),
    ("Card: **** **** **** 4417", 18),
    ("Withdrawal      NGN 20,000.00", 22),
    ("Fee             NGN    100.00", 22),
    ("Balance         NGN 145,320.50", 22),
    ("Ref: RMB20261014X7731", 18),
]
FONT = "/Library/Fonts/Arial Unicode.ttf"


def receipt_image() -> Image.Image:
    image = Image.new("RGB", (620, 900), "white")
    draw = ImageDraw.Draw(image)
    y = 50
    for text, size in LINES:
        draw.text((40, y), text, font=ImageFont.truetype(FONT, size), fill="black")
        y += size + 26
    return image


def main() -> None:
    config = load_attachments_config()
    bedrock = get_vision_extractor(config.vision)

    image = receipt_image()
    png = io.BytesIO()
    image.save(png, "PNG")
    pdf = io.BytesIO()
    image.save(pdf, "PDF", resolution=150.0)
    fixtures = [("receipt.png", "png", png.getvalue()), ("receipt.pdf", "pdf", pdf.getvalue())]

    for index, (name, kind, data) in enumerate(fixtures, start=1):
        class Recording:
            last = None

            def transcribe(self, payload, transport_kind):
                self.last = bedrock.transcribe(payload, transport_kind)
                return self.last

        recorder = Recording()
        file = ValidatedFile(f"Attachment {index}", kind, "application/octet-stream", len(data), data)
        document = extract_document(file, "chat_attachment", config, recorder)
        result = recorder.last
        print(f"\n=== {name} ({kind}) ===")
        for block in document.blocks:
            print(f"[{block.type}] {block.text}")
        print("warnings:", document.warnings)
        print("method:", document.method, "| page_count:", document.page_count,
              "| truncated:", document.truncated)
        if result:
            print("latency_ms:", result.latency_ms, "| input_tokens:", result.input_tokens,
                  "| output_tokens:", result.output_tokens)


if __name__ == "__main__":
    main()
