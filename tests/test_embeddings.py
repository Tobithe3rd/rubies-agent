import os
import sys
import json
import math
import shutil
import hashlib
import subprocess

import pytest

from core.config import ConfigError, load_config
from providers.embeddings.mock import MockEmbedder

CHUNKS_PATH = "data/generated/rag_chunks.jsonl"


def _chunks() -> list[dict]:
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _mock() -> tuple[MockEmbedder, int]:
    cfg = load_config()
    return MockEmbedder(cfg.settings.embeddings, cfg.env), cfg.settings.embeddings.dimensions


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def test_mock_embeds_all_real_chunks():
    embedder, _ = _mock()
    vectors = embedder.embed_documents([c["text"] for c in _chunks()])
    assert len(vectors) == 75


def test_mock_vector_length_is_dimensions():
    embedder, dims = _mock()
    vectors = embedder.embed_documents([c["text"] for c in _chunks()])
    assert all(len(v) == dims for v in vectors)


def test_mock_vectors_are_l2_normalised():
    embedder, _ = _mock()
    vectors = embedder.embed_documents([c["text"] for c in _chunks()])
    for v in vectors:
        assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-6


def test_mock_vectors_have_no_nan():
    embedder, _ = _mock()
    vectors = embedder.embed_documents([c["text"] for c in _chunks()])
    assert all(math.isfinite(x) for v in vectors for x in v)


def test_mock_is_deterministic_across_processes():
    code = (
        "import json,hashlib;"
        "from core.config import load_config;"
        "from providers.embeddings.mock import MockEmbedder;"
        "cfg=load_config();"
        "e=MockEmbedder(cfg.settings.embeddings,cfg.env);"
        "recs=[json.loads(l) for l in open('data/generated/rag_chunks.jsonl',encoding='utf-8') if l.strip()];"
        "v=e.embed_documents([r['text'] for r in recs]);"
        "print(hashlib.sha256(json.dumps(v).encode()).hexdigest())"
    )
    first = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    second = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    assert first.stdout == second.stdout


def test_mock_empty_text_raises():
    embedder, _ = _mock()
    with pytest.raises(ValueError):
        embedder.embed_query("")
    with pytest.raises(ValueError):
        embedder.embed_query("   ")


def test_mock_cosine_identical_and_different():
    embedder, _ = _mock()
    a = embedder.embed_query("transfer fee above fifty thousand naira")
    b = embedder.embed_query("transfer fee above fifty thousand naira")
    c = embedder.embed_query("lost card block replacement pickup")
    assert abs(_cosine(a, b) - 1.0) < 1e-9
    assert _cosine(a, c) < 1.0


def test_unknown_provider_raises_config_error(tmp_path):
    shutil.copy("config/settings.yaml", tmp_path / "settings.yaml")
    shutil.copy("config/tools.yaml", tmp_path / "tools.yaml")
    text = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
    text = text.replace("provider: titan", "provider: bogus")
    (tmp_path / "settings.yaml").write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_dir=str(tmp_path))
    assert "embedding.provider" in str(exc.value)


def test_titan_build_makes_no_network_call(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("boto3.client called at build time")

    monkeypatch.setattr("boto3.client", boom)
    from providers.embeddings.titan import TitanEmbedder

    cfg = load_config()
    embedder = TitanEmbedder(cfg.settings.embeddings, cfg.env)
    assert embedder.dimensions == cfg.settings.embeddings.dimensions
    assert embedder.model_id == cfg.settings.embeddings.model_id


def test_titan_access_denied_message(monkeypatch):
    from botocore.exceptions import ClientError

    class FakeClient:
        def invoke_model(self, **kwargs):
            raise ClientError({"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "InvokeModel")

    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: FakeClient())
    from providers.embeddings.titan import TitanEmbedder

    cfg = load_config()
    embedder = TitanEmbedder(cfg.settings.embeddings, cfg.env)
    with pytest.raises(ConfigError) as exc:
        embedder.embed_query("hello world")
    message = str(exc.value)
    assert cfg.settings.embeddings.model_id in message
    assert "model access" in message.lower()
