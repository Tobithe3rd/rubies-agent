"""SSE event formatting and heartbeat."""
from __future__ import annotations

import json


def _sse(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _extract_citations(message: dict) -> list[dict]:
    if message.get("role") != "user":
        return []
    out: list[dict] = []
    for block in message.get("content", []):
        result = block.get("toolResult") if isinstance(block, dict) else None
        if not isinstance(result, dict):
            continue
        for content in result.get("content") or []:
            envelope = content.get("json") if isinstance(content, dict) else None
            if not isinstance(envelope, dict) or envelope.get("tool") != "search_policy":
                continue
            data = envelope.get("data") or {}
            for row in data.get("results") or []:
                document = row.get("doc_title")
                section = row.get("section_heading")
                if document and section:
                    out.append({"document": document, "section": section})
    return out


def heartbeat_line() -> str:
    return ": ping\n\n"
