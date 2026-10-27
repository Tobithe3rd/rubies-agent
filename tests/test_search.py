import os
import sys
import json
import shutil
import subprocess

import pytest
import yaml

from core.config import ConfigError, load_config
from core.factories import create_embedder, create_vectorstore
from providers.embeddings.mock import MockEmbedder
from providers.vectorstore.chroma import ChromaVectorStore  # noqa: F401  (registers the provider)
from rag.search import build_search_policy

CHUNKS_PATH = "data/rag_chunks.jsonl"
DEV_SET_PATH = "eval/rag_dev_set.yaml"


def _chunks() -> dict:
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        return {json.loads(l)["id"]: json.loads(l) for l in f if l.strip()}


def _replace_line(text, key, value):
    out = []
    for line in text.splitlines():
        if line.strip().startswith(key + ":"):
            indent = line[: len(line) - len(line.lstrip())]
            out.append(f"{indent}{key}: {value}")
        else:
            out.append(line)
    return "\n".join(out) + "\n"


def _write_config(base, chroma_path, provider="mock", edits=None):
    cfg_dir = os.path.join(base, "config")
    os.makedirs(cfg_dir, exist_ok=True)
    real_path = load_config().settings.vectorstore.path
    text = open("config/settings.yaml", encoding="utf-8").read()
    text = text.replace("provider: titan", f"provider: {provider}")
    text = text.replace(f"path: {real_path}", f"path: {chroma_path}")
    for key, value in (edits or {}).items():
        text = _replace_line(text, key, value)
    with open(os.path.join(cfg_dir, "settings.yaml"), "w", encoding="utf-8") as f:
        f.write(text)
    shutil.copy("config/tools.yaml", os.path.join(cfg_dir, "tools.yaml"))
    return cfg_dir


def _ingest(cfg_dir):
    return subprocess.run([sys.executable, "-m", "rag.ingest", "--config", cfg_dir],
                          capture_output=True, text=True)


class SpyEmbedder:
    def __init__(self, inner):
        self.inner = inner
        self.calls = 0
        self.provider = "mock"

    @property
    def dimensions(self):
        return self.inner.dimensions

    def embed_query(self, text):
        self.calls += 1
        return self.inner.embed_query(text)

    def embed_documents(self, texts):
        return self.inner.embed_documents(texts)


@pytest.fixture
def built(tmp_path):
    cfg_dir = _write_config(str(tmp_path), str(tmp_path / "chroma"))
    assert _ingest(cfg_dir).returncode == 0
    cfg = load_config(config_dir=cfg_dir)
    embedder = create_embedder(cfg)
    store = create_vectorstore(cfg, embedder)
    return cfg, embedder, store


def test_own_text_returns_ok(built):
    cfg, embedder, store = built
    search = build_search_policy(cfg, embedder, store)
    chunk = _chunks()["RUB-DOC-03#6"]
    result = search(chunk["text"])
    assert result.status == "ok"
    assert result.results[0]["chunk_id"] == "RUB-DOC-03#6"
    assert result.results[0]["score"] >= 0.999


def test_citation_of_rubdoc01_2(built):
    cfg, embedder, store = built
    search = build_search_policy(cfg, embedder, store)
    result = search(_chunks()["RUB-DOC-01#2"]["text"])
    hit = next(r for r in result.results if r["chunk_id"] == "RUB-DOC-01#2")
    assert hit["citation"] == "Fee Schedule, section 2 (Transfer fees)"


def test_nonsense_query_no_relevant_result(built):
    cfg, embedder, store = built
    search = build_search_policy(cfg, embedder, store)
    result = search("zzzz qqqq")
    assert result.status == "no_relevant_result"
    assert result.results == []
    assert result.message == cfg.settings.rag.no_result_message


def test_invalid_queries_make_no_embedder_call(built):
    cfg, embedder, store = built
    spy = SpyEmbedder(embedder)
    search = build_search_policy(cfg, spy, store)
    for query in ("", "   ", "x" * 1001):
        result = search(query)
        assert result.status == "invalid_query"
        assert result.results == []
    assert spy.calls == 0


def test_high_threshold_turns_query_into_no_relevant(tmp_path):
    cfg_dir = _write_config(str(tmp_path), str(tmp_path / "chroma"),
                            edits={"similarity_threshold": 0.99999})
    assert _ingest(cfg_dir).returncode == 0
    cfg = load_config(config_dir=cfg_dir)
    embedder = create_embedder(cfg)
    store = create_vectorstore(cfg, embedder)
    search = build_search_policy(cfg, embedder, store)
    result = search("transfer fee")
    assert result.status == "no_relevant_result"


def test_results_sorted_and_within_bounds(built):
    cfg, embedder, store = built
    search = build_search_policy(cfg, embedder, store)
    result = search("What is the transfer fee?")
    scores = [r["score"] for r in result.results]
    assert scores == sorted(scores, reverse=True)
    assert len(result.results) <= cfg.settings.rag.top_k
    assert all(s >= cfg.settings.rag.similarity_threshold for s in scores)


@pytest.mark.parametrize("edits,key", [
    ({"similarity_threshold": 1.5}, "similarity_threshold"),
    ({"top_k": 0}, "top_k"),
    ({"no_result_message": '""'}, "no_result_message"),
    ({"max_query_chars": 10}, "max_query_chars"),
])
def test_invalid_config_values_raise(tmp_path, edits, key):
    cfg_dir = _write_config(str(tmp_path), str(tmp_path / "chroma"), edits=edits)
    with pytest.raises(ConfigError) as exc:
        load_config(config_dir=cfg_dir)
    assert key in str(exc.value)


def test_dev_set_shape_and_ids():
    dev = yaml.safe_load(open(DEV_SET_PATH, encoding="utf-8"))
    assert len(dev["in_scope"]) == 20
    assert len(dev["out_of_scope"]) == 6
    chunks = _chunks()
    for entry in dev["in_scope"]:
        assert entry["expected_chunk_id"] in chunks
