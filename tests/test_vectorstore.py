import os
import sys
import json
import shutil
import subprocess

import pytest

from core.config import ConfigError, load_config
from core.factories import create_embedder, create_vectorstore
from providers.vectorstore.chroma import ChromaVectorStore  # noqa: F401  (registers the provider)

CHUNKS_PATH = "data/rag_chunks.jsonl"


def _chunks() -> list[dict]:
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def _write_config(base, chroma_path, provider="mock"):
    cfg_dir = os.path.join(base, "config")
    os.makedirs(cfg_dir, exist_ok=True)
    real_path = load_config().settings.vectorstore.path
    text = open("config/settings.yaml", encoding="utf-8").read()
    text = text.replace("provider: titan", f"provider: {provider}")
    text = text.replace(f"path: {real_path}", f"path: {chroma_path}")
    with open(os.path.join(cfg_dir, "settings.yaml"), "w", encoding="utf-8") as f:
        f.write(text)
    shutil.copy("config/tools.yaml", os.path.join(cfg_dir, "tools.yaml"))
    return cfg_dir


def _ingest(cfg_dir):
    return subprocess.run(
        [sys.executable, "-m", "rag.ingest", "--config", cfg_dir],
        capture_output=True, text=True,
    )


def _open_store(cfg_dir):
    cfg = load_config(config_dir=cfg_dir)
    embedder = create_embedder(cfg)
    store = create_vectorstore(cfg, embedder)
    return cfg, embedder, store


@pytest.fixture
def mock_store(tmp_path):
    cfg_dir = _write_config(str(tmp_path), str(tmp_path / "chroma"), provider="mock")
    result = _ingest(cfg_dir)
    assert result.returncode == 0, result.stderr
    return cfg_dir


def test_ingest_creates_75_and_ids_match(mock_store):
    cfg, embedder, store = _open_store(mock_store)
    assert store.count() == 75
    ids_in_file = {c["id"] for c in _chunks()}
    results = store.query(embedder.embed_query(_chunks()[0]["text"]), 75)
    assert {r["id"] for r in results} == ids_in_file


def test_stored_text_and_metadata(mock_store):
    cfg, embedder, store = _open_store(mock_store)
    by_id = {c["id"]: c for c in _chunks()}
    results = store.query(embedder.embed_query(by_id["RUB-DOC-03#6"]["text"]), 75)
    for r in results:
        assert r["text"] == by_id[r["id"]]["text"]
        for field in ("doc_id", "doc_title", "file", "section_number", "section_heading", "citation", "word_count"):
            assert r[field] not in (None, "")


def test_citation_of_rubdoc01_2(mock_store):
    cfg, embedder, store = _open_store(mock_store)
    results = store.query(embedder.embed_query(_chunks()[0]["text"]), 75)
    by_id = {r["id"]: r for r in results}
    assert by_id["RUB-DOC-01#2"]["citation"] == "Fee Schedule, section 2 (Transfer fees)"


def test_reingest_keeps_count_and_unique_ids(mock_store):
    assert _ingest(mock_store).returncode == 0
    cfg, embedder, store = _open_store(mock_store)
    assert store.count() == 75
    results = store.query(embedder.embed_query(_chunks()[0]["text"]), 75)
    ids = [r["id"] for r in results]
    assert len(ids) == len(set(ids))


def test_self_query_returns_itself_first(mock_store):
    cfg, embedder, store = _open_store(mock_store)
    by_id = {c["id"]: c for c in _chunks()}
    results = store.query(embedder.embed_query(by_id["RUB-DOC-03#6"]["text"]), 4)
    assert results[0]["id"] == "RUB-DOC-03#6"
    assert results[0]["score"] >= 0.999
    scores = [r["score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_embedder_mismatch_raises(tmp_path):
    mock_dir = _write_config(str(tmp_path), str(tmp_path / "chroma"), provider="mock")
    assert _ingest(mock_dir).returncode == 0
    titan_dir = _write_config(str(tmp_path / "titan"), str(tmp_path / "chroma"), provider="titan")
    cfg = load_config(config_dir=titan_dir)
    embedder = create_embedder(cfg)
    store = create_vectorstore(cfg, embedder)
    with pytest.raises(ConfigError) as exc:
        store.count()
    message = str(exc.value).lower()
    assert "embedder" in message and "mismatch" in message


def test_unknown_vector_store_type_raises(tmp_path):
    cfg_dir = _write_config(str(tmp_path), str(tmp_path / "chroma"))
    path = os.path.join(cfg_dir, "settings.yaml")
    text = open(path, encoding="utf-8").read().replace("type: chroma", "type: bogus")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    with pytest.raises(ConfigError) as exc:
        load_config(config_dir=cfg_dir)
    assert "vector_store.type" in str(exc.value)


def test_empty_store_query_raises(tmp_path):
    cfg_dir = _write_config(str(tmp_path), str(tmp_path / "chroma"))
    cfg, embedder, store = _open_store(cfg_dir)
    with pytest.raises(ConfigError):
        store.query(embedder.embed_query("anything at all"), 4)
