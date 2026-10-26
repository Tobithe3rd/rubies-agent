from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Any, Callable, Optional


@dataclass
class HealthStatus:
    name: str
    ok: bool
    detail: str
    # detail must never contain secrets (enforced by caller convention)


@dataclass
class Chunk:
    id: str
    text: str
    metadata: dict
    # metadata must contain at least doc and section keys when used with RAG


@dataclass
class SearchResult:
    chunk: Chunk
    score: float
    # score is higher-is-better, normalised to 0-1.
    # The similarity_threshold in settings.yaml means the same thing
    # regardless of which vector store produces the score.


# --- interfaces ---

class LLMProvider(abc.ABC):
    @abc.abstractmethod
    def describe(self) -> str:
        ...

    @abc.abstractmethod
    def healthcheck(self) -> HealthStatus:
        ...

    @abc.abstractmethod
    def get_model(self) -> Any:
        """Return the framework model object the agent will use.

        Intentionally untyped so the agent layer can use Strands
        now and a different framework later without changing this interface.
        """
        ...

    @abc.abstractmethod
    def complete(self, prompt: str, system: Optional[str] = None) -> str:
        ...


class Embedder(abc.ABC):
    @abc.abstractmethod
    def describe(self) -> str:
        ...

    @abc.abstractmethod
    def healthcheck(self) -> HealthStatus:
        ...

    @property
    @abc.abstractmethod
    def dimensions(self) -> int:
        ...

    @abc.abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        ...

    @abc.abstractmethod
    def embed_query(self, text: str) -> list[float]:
        ...


class VectorStore(abc.ABC):
    @abc.abstractmethod
    def describe(self) -> str:
        ...

    @abc.abstractmethod
    def healthcheck(self) -> HealthStatus:
        ...

    @abc.abstractmethod
    def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        ...

    @abc.abstractmethod
    def search(self, query_embedding: list[float], top_k: int) -> list[SearchResult]:
        ...

    @abc.abstractmethod
    def count(self) -> int:
        ...

    @abc.abstractmethod
    def reset(self) -> None:
        ...


class DataStore(abc.ABC):
    @abc.abstractmethod
    def describe(self) -> str:
        ...

    @abc.abstractmethod
    def healthcheck(self) -> HealthStatus:
        ...

    @abc.abstractmethod
    def connect(self) -> None:
        ...

    @abc.abstractmethod
    def close(self) -> None:
        ...


ChatHandler = Callable[[str, str], str]
"""Handler signature: (session_id: str, message: str) -> str."""


class InterfaceAdapter(abc.ABC):
    @abc.abstractmethod
    def describe(self) -> str:
        ...

    @abc.abstractmethod
    def healthcheck(self) -> HealthStatus:
        ...

    @abc.abstractmethod
    def start(self, handler: ChatHandler) -> None:
        ...

    @abc.abstractmethod
    def stop(self) -> None:
        ...
