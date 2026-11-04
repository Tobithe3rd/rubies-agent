from __future__ import annotations

import os
import time
from io import BytesIO
from pathlib import Path
from typing import Any, Optional

import boto3
from botocore.config import Config as BotoConfig
from PIL import Image

from attachments.models import MESSAGES, AttachmentRejected
from attachments.vision.base import VisionResult, register_vision
from core.config import ConfigError


@register_vision("bedrock")
class BedrockVisionExtractor:
    """Transcribes images/PDFs with Bedrock Converse (no Strands)."""

    def __init__(self, config, client: Optional[Any] = None) -> None:
        self.config = config
        self.model_id = config.model_id
        self._client = client
        try:
            self.prompt = Path(config.prompt_path).read_text(encoding="utf-8")
        except Exception as exc:
            raise ConfigError(
                f"vision.prompt_path could not be read: {config.prompt_path}"
            ) from exc

    def describe(self) -> str:
        return f"bedrock-vision:{self.model_id}"

    def _region(self) -> str:
        return os.environ.get("AWS_REGION", "")

    def _get_client(self):
        if self._client is None:
            self._client = boto3.client(
                "bedrock-runtime",
                region_name=self._region(),
                config=BotoConfig(
                    connect_timeout=self.config.connect_timeout_seconds,
                    read_timeout=self.config.read_timeout_seconds,
                    retries={"max_attempts": self.config.max_retries, "mode": "standard"},
                ),
            )
        return self._client

    def _image_block(self, data: bytes, kind: str) -> dict:
        with Image.open(BytesIO(data)) as image:
            image.load()
            output = BytesIO()
            if kind == "png":
                image.save(output, "PNG")
                image_format = "png"
            else:
                image.convert("RGB").save(output, "JPEG", quality=90)
                image_format = "jpeg"
        return {
            "image": {
                "format": image_format,
                "source": {"bytes": output.getvalue()},
            }
        }

    def _media_block(self, data: bytes, kind: str) -> dict:
        if kind == "pdf":
            return {
                "document": {
                    "format": "pdf",
                    "name": "Document 1",
                    "source": {"bytes": data},
                }
            }
        return self._image_block(data, kind)

    def transcribe(self, data: bytes, kind: str) -> VisionResult:
        try:
            content = [self._media_block(data, kind), {"text": self.prompt}]
            started = time.monotonic()
            response = self._get_client().converse(
                modelId=self.model_id,
                messages=[{"role": "user", "content": content}],
                inferenceConfig={
                    "temperature": self.config.temperature,
                    "maxTokens": self.config.max_output_tokens,
                },
            )
            latency_ms = int(round((time.monotonic() - started) * 1000))
            text = "".join(
                block.get("text", "")
                for block in response["output"]["message"]["content"]
            )
            usage = response.get("usage") or {}
            return VisionResult(
                text=text or "NO_TEXT",
                input_tokens=usage.get("inputTokens"),
                output_tokens=usage.get("outputTokens"),
                latency_ms=latency_ms,
            )
        except AttachmentRejected:
            raise
        except Exception:
            raise AttachmentRejected(
                "extraction_unavailable", MESSAGES["extraction_unavailable"]
            ) from None
