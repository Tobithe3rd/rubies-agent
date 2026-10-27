from __future__ import annotations

import time
import logging
from dataclasses import dataclass
from typing import Callable, Optional

from core.config import AppConfig, load_config
from core.factories import create_embedder, create_vectorstore


logger = logging.getLogger("rubies.search")

INVALID_QUERY_MESSAGE = (
    "I could not use that query. Please ask the customer to rephrase it in a short question."
)


@dataclass
class PolicySearchResult:
    status: str  # "ok" | "no_relevant_result" | "invalid_query"
    query: str
    results: list[dict]
    top_score: Optional[float]
    threshold: float
    message: str

    def to_dict(self) -> dict:
        return {
            "status": self.status,
            "query": self.query,
            "results": self.results,
            "top_score": self.top_score,
            "threshold": self.threshold,
            "message": self.message,
        }


def build_search_policy(
    config: AppConfig,
    embedder=None,
    store=None,
) -> Callable[[str], PolicySearchResult]:
    """Build a search_policy(query) callable bound to one config/embedder/store.

    embedder and store may be injected (tests); otherwise they are built from
    config via the factories, once, lazily.
    """
    rag = config.settings.rag
    threshold = rag.similarity_threshold
    top_k = rag.top_k
    max_query_chars = rag.max_query_chars
    no_result_message = rag.no_result_message
    debug = config.settings.logging.debug

    state: dict = {"embedder": embedder, "store": store}

    def _embedder():
        if state["embedder"] is None:
            state["embedder"] = create_embedder(config)
        return state["embedder"]

    def _store():
        if state["store"] is None:
            state["store"] = create_vectorstore(config, _embedder())
        return state["store"]

    def search_policy(query: str) -> PolicySearchResult:
        start = time.monotonic()
        text = query if isinstance(query, str) else ""

        if not text.strip() or len(text) > max_query_chars:
            result = PolicySearchResult(
                status="invalid_query",
                query=text,
                results=[],
                top_score=None,
                threshold=threshold,
                message=INVALID_QUERY_MESSAGE,
            )
            _log(debug, result, start)
            return result

        embedding = _embedder().embed_query(text)
        rows = _store().query(embedding, top_k)
        top_score = float(rows[0]["score"]) if rows else None
        kept = [r for r in rows if float(r["score"]) >= threshold]
        results = [
            {
                "chunk_id": r["id"],
                "citation": r["citation"],
                "doc_title": r["doc_title"],
                "section_heading": r["section_heading"],
                "text": r["text"],
                "score": round(float(r["score"]), 4),
            }
            for r in kept
        ]
        results.sort(key=lambda r: r["score"], reverse=True)

        if results:
            result = PolicySearchResult("ok", text, results, top_score, threshold, "")
        else:
            result = PolicySearchResult(
                "no_relevant_result", text, [], top_score, threshold, no_result_message
            )
        _log(debug, result, start)
        return result

    return search_policy


def _log(debug: bool, result: PolicySearchResult, start: float) -> None:
    if debug:
        # Status, top score and elapsed time only; never the query text.
        logger.debug(
            "search_policy status=%s top_score=%s elapsed=%.3fs",
            result.status, result.top_score, time.monotonic() - start,
        )


_default_search: Optional[Callable[[str], PolicySearchResult]] = None


def search_policy(query: str) -> PolicySearchResult:
    """Convenience entry point: builds from the real config once, then delegates."""
    global _default_search
    if _default_search is None:
        _default_search = build_search_policy(load_config())
    return _default_search(query)
