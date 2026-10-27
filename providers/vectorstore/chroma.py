from __future__ import annotations

import os

import chromadb
from chromadb.config import Settings as ChromaClientSettings

from core.config import ConfigError
from core.factories import register
from core.interfaces import Chunk, HealthStatus, SearchResult, VectorStore


_METADATA_FIELDS = (
    "doc_id",
    "doc_title",
    "file",
    "section_number",
    "section_heading",
    "citation",
    "word_count",
)


@register("vectorstore", "chroma")
class ChromaVectorStore(VectorStore):
    """Persistent ChromaDB store. Embeddings are always supplied by our Embedder."""

    def __init__(self, cfg, embedder, env):
        self.cfg = cfg
        self.embedder = embedder
        self.path = cfg.path
        self.collection_name = cfg.collection
        self._client = None
        self._provider = getattr(embedder, "provider", "unknown")
        self._model = getattr(embedder, "model_id", "") or "none"
        self._dimensions = int(embedder.dimensions)

    def describe(self) -> str:
        return f"chroma:{self.collection_name}"

    def _client_or_create(self):
        if self._client is None:
            os.makedirs(self.path, exist_ok=True)
            self._client = chromadb.PersistentClient(
                path=self.path,
                settings=ChromaClientSettings(anonymized_telemetry=False),
            )
        return self._client

    def _signature(self) -> dict:
        return {
            "hnsw:space": "cosine",
            "embedder_provider": self._provider,
            "embedder_model": self._model,
            "embedder_dimensions": self._dimensions,
        }

    def _open(self):
        client = self._client_or_create()
        try:
            collection = client.get_collection(self.collection_name)
        except Exception:
            collection = None
        if collection is None:
            return client.get_or_create_collection(self.collection_name, metadata=self._signature())

        metadata = dict(collection.metadata or {})
        stored_provider = metadata.get("embedder_provider")
        if stored_provider is not None:
            stored = (
                stored_provider,
                metadata.get("embedder_model"),
                metadata.get("embedder_dimensions"),
            )
            current = (self._provider, self._model, self._dimensions)
            if stored != current:
                raise ConfigError(
                    f"Embedder mismatch for collection '{self.collection_name}': built with "
                    f"{stored} but the configured embedder is {current}. Re-run ingest to rebuild."
                )
        return collection

    def healthcheck(self) -> HealthStatus:
        try:
            collection = self._open()
            return HealthStatus(self.describe(), True, f"{collection.count()} chunks")
        except Exception as exc:
            return HealthStatus(self.describe(), False, str(exc))

    def reset(self) -> None:
        client = self._client_or_create()
        try:
            client.delete_collection(self.collection_name)
        except Exception:
            pass
        client.get_or_create_collection(self.collection_name, metadata=self._signature())

    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        if len(chunks) != len(embeddings):
            raise ConfigError(
                f"chunks and embeddings length mismatch: {len(chunks)} vs {len(embeddings)}"
            )
        collection = self._open()
        collection.upsert(
            ids=[c.id for c in chunks],
            embeddings=[list(map(float, e)) for e in embeddings],
            documents=[c.text for c in chunks],
            metadatas=[{f: getattr(c, f) for f in _METADATA_FIELDS} for c in chunks],
        )

    def count(self) -> int:
        return self._open().count()

    def query(self, query_embedding: list[float], top_k: int) -> list[dict]:
        collection = self._open()
        if collection.count() == 0:
            raise ConfigError(
                f"Collection '{self.collection_name}' is empty or missing; run ingest first."
            )
        result = collection.query(
            query_embeddings=[list(map(float, query_embedding))],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        ids = result["ids"][0]
        documents = result["documents"][0]
        metadatas = result["metadatas"][0]
        distances = result["distances"][0]
        rows = []
        for i, chunk_id in enumerate(ids):
            rows.append({
                "id": chunk_id,
                "score": 1.0 - float(distances[i]),
                "text": documents[i],
                **{f: metadatas[i].get(f) for f in _METADATA_FIELDS},
            })
        rows.sort(key=lambda r: r["score"], reverse=True)
        return rows

    def search(self, query_embedding: list[float], top_k: int) -> list[SearchResult]:
        results = []
        for row in self.query(query_embedding, top_k):
            chunk = Chunk(
                id=row["id"],
                text=row["text"],
                metadata={f: row[f] for f in _METADATA_FIELDS},
                doc_id=row["doc_id"],
                doc_title=row["doc_title"],
                file=row["file"],
                section_number=row["section_number"],
                section_heading=row["section_heading"],
                citation=row["citation"],
                word_count=row["word_count"],
            )
            results.append(SearchResult(chunk=chunk, score=row["score"]))
        return results
