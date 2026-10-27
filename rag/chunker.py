from __future__ import annotations

import glob
import json
import os
import re

from core.config import ConfigError, load_config
from core.interfaces import Chunk


def _split_paragraphs(body: str, budget_words: int) -> list[str]:
    """Split a section body on paragraph boundaries, keeping parts under budget."""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    parts: list[str] = []
    current: list[str] = []
    current_words = 0
    for para in paragraphs:
        words = len(para.split())
        if current and current_words + words > budget_words:
            parts.append("\n\n".join(current))
            current = [para]
            current_words = words
        else:
            current.append(para)
            current_words += words
    if current:
        parts.append("\n\n".join(current))
    return parts or [""]


def _chunk_heading(cfg, files: list[str]) -> list[Chunk]:
    max_words = cfg.settings.rag.chunking.max_words
    chunks: list[Chunk] = []

    for path in files:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()

        title = ""
        doc_id = ""
        for line in lines:
            if not title and line.startswith("# "):
                title = line[2:].strip()
            m = re.match(r"^Document ID:\s*(RUB-DOC-\d{2})", line)
            if m and not doc_id:
                doc_id = m.group(1)

        heading_idxs = [i for i, line in enumerate(lines) if re.match(r"^## \d+\. ", line)]
        for k, start in enumerate(heading_idxs):
            end = heading_idxs[k + 1] if k + 1 < len(heading_idxs) else len(lines)
            m = re.match(r"^## (\d+)\. (.+)$", lines[start])
            number = int(m.group(1))
            heading = m.group(2).strip()
            body = "\n".join(lines[start + 1:end]).strip("\n")

            citation = f"{title}, section {number} ({heading})"
            header = f"{title} > {number}. {heading}"
            base_id = f"{doc_id}#{number}"
            metadata = {"doc": doc_id, "section": number}

            def make(chunk_id: str, text: str) -> Chunk:
                return Chunk(
                    id=chunk_id,
                    text=text,
                    metadata=metadata,
                    doc_id=doc_id,
                    doc_title=title,
                    file=path,
                    section_number=number,
                    section_heading=heading,
                    citation=citation,
                    word_count=len(text.split()),
                )

            full_text = f"{header}\n\n{body}" if body else header
            if len(full_text.split()) <= max_words:
                chunks.append(make(base_id, full_text))
                continue

            # Too long: split on paragraph boundaries; the parts share one citation.
            budget = max_words - len(header.split())
            parts = _split_paragraphs(body, budget)
            for j, part in enumerate(parts):
                suffix = chr(ord("a") + j)
                chunks.append(make(f"{base_id}-{suffix}", f"{header}\n\n{part}"))

    return chunks


CHUNKING_MODES = {
    "heading": _chunk_heading,
}


def chunk_documents(cfg) -> list[Chunk]:
    mode = cfg.settings.rag.chunking.mode
    if mode not in CHUNKING_MODES:
        raise ConfigError(
            f"Unknown chunking.mode '{mode}'. Allowed: {', '.join(sorted(CHUNKING_MODES))}"
        )
    docs_dir = cfg.settings.rag.docs_path
    ignore = tuple(cfg.settings.rag.ignore_prefixes)
    files = sorted(
        p for p in glob.glob(os.path.join(docs_dir, "*.md"))
        if not os.path.basename(p).startswith(ignore)
    )
    return CHUNKING_MODES[mode](cfg, files)


def chunk_to_dict(chunk: Chunk) -> dict:
    return {
        "id": chunk.id,
        "doc_id": chunk.doc_id,
        "doc_title": chunk.doc_title,
        "file": chunk.file,
        "section_number": chunk.section_number,
        "section_heading": chunk.section_heading,
        "citation": chunk.citation,
        "text": chunk.text,
        "word_count": chunk.word_count,
    }


def write_chunks(chunks: list[Chunk], path: str) -> None:
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for chunk in chunks:
            f.write(json.dumps(chunk_to_dict(chunk), ensure_ascii=False) + "\n")


def main() -> None:
    cfg = load_config()
    chunks = chunk_documents(cfg)
    path = cfg.settings.rag.chunks_path
    write_chunks(chunks, path)

    documents = sorted({c.file for c in chunks})
    words = [c.word_count for c in chunks] or [0]
    print(
        f"Chunker: documents={len(documents)} chunks={len(chunks)} "
        f"words_min={min(words)} words_max={max(words)} -> {path}"
    )


if __name__ == "__main__":
    main()
