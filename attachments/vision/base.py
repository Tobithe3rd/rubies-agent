from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Optional, Protocol

from core.config import ConfigError


@dataclass
class VisionResult:
    text: str
    input_tokens: Optional[int]
    output_tokens: Optional[int]
    latency_ms: int


class VisionExtractor(Protocol):
    def transcribe(self, data: bytes, kind: str) -> VisionResult:
        ...


_REGISTRY: dict[str, VisionExtractor] = {}
_IMPORT_MAP = {
    "bedrock": "attachments.vision.bedrock",
    "mock": "attachments.vision.mock",
}


def register_vision(provider: str):
    def decorator(cls):
        _REGISTRY[provider] = cls
        return cls
    return decorator


def get_vision_extractor(config) -> VisionExtractor:
    provider = config.provider
    if provider not in _IMPORT_MAP:
        raise ConfigError(
            f"unknown vision provider: {provider!r}; "
            f"available: {', '.join(sorted(_IMPORT_MAP))}"
        )
    if provider not in _REGISTRY:
        importlib.import_module(_IMPORT_MAP[provider])
    return _REGISTRY[provider](config)
