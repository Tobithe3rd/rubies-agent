from __future__ import annotations

import sys
import argparse

from core.config import load_config
from core.factories import create_embedder, create_vectorstore
from rag.chunker import chunk_documents, write_chunks


def ingest(config_dir: str = "config") -> int:
    try:
        cfg = load_config(config_dir=config_dir)
        chunks = chunk_documents(cfg)
        write_chunks(chunks, cfg.settings.rag.chunks_path)

        embedder = create_embedder(cfg)
        store = create_vectorstore(cfg, embedder)

        store.reset()
        embeddings = embedder.embed_documents([c.text for c in chunks])
        store.add(chunks, embeddings)

        provider = getattr(embedder, "provider", "unknown")
        model = getattr(embedder, "model_id", "") or "n/a"
        print(
            f"{len(chunks)} chunks ingested into {cfg.settings.vectorstore.collection} "
            f"at {cfg.settings.vectorstore.path} using {provider}/{model}"
        )
        return 0
    except Exception as exc:
        print(f"Ingest failed: {exc}", file=sys.stderr, flush=True)
        return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Chunk and embed the policy docs into the vector store.")
    parser.add_argument("--config", default="config", help="config directory (default: config)")
    args = parser.parse_args(argv)
    return ingest(config_dir=args.config)


if __name__ == "__main__":
    sys.exit(main())
