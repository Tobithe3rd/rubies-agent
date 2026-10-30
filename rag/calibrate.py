from __future__ import annotations

import os
import sys
import json
import argparse

from core.config import load_config
from core.factories import create_embedder, create_vectorstore


IN_SCOPE = [
    "What is the fee for transfers above ₦50,000?",
    "I was debited twice, what happens and how long does a reversal take?",
    "My card is lost, what should I do?",
    "Can I get a ₦200,000 loan and what are the requirements?",
    "What will Rubies never ask me for?",
    "How do I escalate my complaint?",
]

OUT_OF_SCOPE = [
    "What is the capital of France?",
    "Can I buy bitcoin with my Rubies account?",
    "What is your mortgage interest rate?",
    "Who is the CEO of Rubies?",
    "What is the weather in Lagos today?",
]

OUTPUT_PATH = "eval/reports/rag_calibration.json"


def calibrate(config_dir: str = "config") -> int:
    try:
        cfg = load_config(config_dir=config_dir)
        top_k = cfg.settings.rag.top_k
        embedder = create_embedder(cfg)
        store = create_vectorstore(cfg, embedder)

        records = []
        for question in IN_SCOPE + OUT_OF_SCOPE:
            group = "in_scope" if question in IN_SCOPE else "out_of_scope"
            embedding = embedder.embed_query(question)
            results = store.query(embedding, top_k)
            records.append({
                "question": question,
                "group": group,
                "top_results": [{"id": r["id"], "score": r["score"]} for r in results],
            })

        directory = os.path.dirname(OUTPUT_PATH)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        print(f"{len(records)} questions calibrated into {OUTPUT_PATH} (top_k={top_k})")
        return 0
    except Exception as exc:
        print(f"Calibrate failed: {exc}", file=sys.stderr, flush=True)
        return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Record retrieval scores for the calibration questions.")
    parser.add_argument("--config", default="config", help="config directory (default: config)")
    args = parser.parse_args(argv)
    return calibrate(config_dir=args.config)


if __name__ == "__main__":
    sys.exit(main())
