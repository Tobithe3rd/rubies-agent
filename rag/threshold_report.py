from __future__ import annotations

import os
import sys
import json
import argparse

import yaml

from core.config import load_config
from core.factories import create_embedder, create_vectorstore


DEV_SET_PATH = "eval/rag_dev_set.yaml"
OUTPUT_PATH = "data/rag_threshold_report.json"
GRID = [round(0.20 + 0.05 * i, 2) for i in range(9)]  # 0.20 .. 0.60


def threshold_report(config_dir: str = "config") -> int:
    try:
        cfg = load_config(config_dir=config_dir)
        top_k = cfg.settings.rag.top_k
        configured = cfg.settings.rag.similarity_threshold
        embedder = create_embedder(cfg)
        store = create_vectorstore(cfg, embedder)

        with open(DEV_SET_PATH, encoding="utf-8") as f:
            dev = yaml.safe_load(f)

        questions = []
        for entry in dev["in_scope"]:
            questions.append({
                "question": entry["question"],
                "group": "in_scope",
                "expected_chunk_id": entry["expected_chunk_id"],
                "expected_heading_contains": entry.get("expected_heading_contains"),
            })
        for entry in dev["out_of_scope"]:
            questions.append({
                "question": entry["question"],
                "group": "out_of_scope",
                "kind": entry["kind"],
            })

        per_question = []
        for q in questions:
            rows = store.query(embedder.embed_query(q["question"]), top_k)
            top_results = [{"id": r["id"], "score": round(float(r["score"]), 4)} for r in rows]
            top1 = top_results[0] if top_results else {"id": None, "score": None}
            rank = None
            if q["group"] == "in_scope":
                for i, r in enumerate(top_results):
                    if r["id"] == q["expected_chunk_id"]:
                        rank = i + 1
                        break
            per_question.append({
                **q,
                "top_results": top_results,
                "top1_id": top1["id"],
                "top1_score": top1["score"],
                "expected_rank": rank,
            })

        in_scope = [p for p in per_question if p["group"] == "in_scope"]
        off_topic = [p for p in per_question if p["group"] == "out_of_scope" and p["kind"] == "off_topic"]
        in_domain = [p for p in per_question if p["group"] == "out_of_scope" and p["kind"] == "in_domain_unanswerable"]

        def answered(pool, threshold):
            return sum(1 for p in pool if (p["top1_score"] or 0.0) >= threshold)

        table = [{
            "threshold": t,
            "in_scope_answered": answered(in_scope, t),
            "off_topic_answered": answered(off_topic, t),
            "in_domain_unanswerable_answered": answered(in_domain, t),
        } for t in GRID]

        recall_hits = sum(1 for p in in_scope if p["expected_rank"] is not None)
        top1_hits = sum(1 for p in in_scope if p["expected_rank"] == 1)

        report = {
            "questions": per_question,
            "thresholds": table,
            "recall_at_top_k": {"hits": recall_hits, "total": len(in_scope)},
            "top1_accuracy": {"hits": top1_hits, "total": len(in_scope)},
            "configured_threshold": configured,
            "configured": {
                "in_scope_refused": len(in_scope) - answered(in_scope, configured),
                "off_topic_answered": answered(off_topic, configured),
                "in_domain_unanswerable_answered": answered(in_domain, configured),
            },
        }

        directory = os.path.dirname(OUTPUT_PATH)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print("threshold table (in_scope_answered / off_topic_answered / in_domain_unanswerable_answered):")
        for row in table:
            print(f"  {row['threshold']:.2f}  {row['in_scope_answered']}/20  "
                  f"{row['off_topic_answered']}/3  {row['in_domain_unanswerable_answered']}/3")
        print(f"recall@top_k: {recall_hits}/{len(in_scope)}")
        print(f"top-1 accuracy: {top1_hits}/{len(in_scope)}")
        print(
            f"configured threshold {configured}: in-scope refused "
            f"{report['configured']['in_scope_refused']}/{len(in_scope)}, off_topic answered "
            f"{report['configured']['off_topic_answered']}/{len(off_topic)}, "
            f"in_domain_unanswerable answered "
            f"{report['configured']['in_domain_unanswerable_answered']}/{len(in_domain)}"
        )
        print(f"wrote {OUTPUT_PATH} covering {len(per_question)} questions")
        return 0
    except Exception as exc:
        print(f"Threshold report failed: {exc}", file=sys.stderr, flush=True)
        return 1


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Report retrieval scores across candidate thresholds.")
    parser.add_argument("--config", default="config", help="config directory (default: config)")
    args = parser.parse_args(argv)
    return threshold_report(config_dir=args.config)


if __name__ == "__main__":
    sys.exit(main())
