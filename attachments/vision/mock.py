from __future__ import annotations

import time
from typing import Optional

from attachments.vision.base import VisionResult, register_vision


@register_vision("mock")
class MockVisionExtractor:
    """Deterministic offline extractor for tests."""

    def __init__(self, config, text: Optional[str] = None) -> None:
        self.config = config
        self.text = "Mock vision transcription." if text is None else text

    def transcribe(self, data: bytes, kind: str) -> VisionResult:
        return VisionResult(text=self.text, input_tokens=11, output_tokens=7, latency_ms=1)
