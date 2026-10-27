from __future__ import annotations

import math
import hashlib
import re

from core.factories import register
from core.interfaces import Embedder, HealthStatus


_TOKEN_RE = re.compile(r"[a-z0-9]+")


@register("embedder", "mock")
class MockEmbedder(Embedder):
    """Deterministic, offline embedder.

    Hashes lowercase word tokens into the configured number of dimensions and
    L2-normalises, so texts that share words have a higher cosine than
    unrelated texts. Uses hashlib (not Python's randomised hash) so the output
    is identical across runs and processes.
    """

    def __init__(self, cfg, env):
        self.cfg = cfg
        self.env = env
        self.provider = "mock"
        self._dimensions = cfg.dimensions

    def describe(self) -> str:
        return "mock"

    @property
    def dimensions(self) -> int:
        return self._dimensions

    def healthcheck(self) -> HealthStatus:
        return HealthStatus(self.describe(), True, "ok")

    def _embed_one(self, text: str) -> list[float]:
        if text is None or not text.strip():
            raise ValueError("text must be a non-empty string")

        vector = [0.0] * self._dimensions
        for token in _TOKEN_RE.findall(text.lower()):
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:8], "big") % self._dimensions
            sign = 1.0 if (digest[8] & 1) else -1.0
            vector[bucket] += sign

        norm = math.sqrt(sum(v * v for v in vector))
        if norm == 0.0:
            raise ValueError("text has no usable tokens")
        return [v / norm for v in vector]

    def embed_query(self, text: str) -> list[float]:
        return self._embed_one(text)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]
