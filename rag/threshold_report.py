from __future__ import annotations

import os
import sys
import json
import argparse

import yaml

from core.config import load_config
from core.factories import (
    create_embedder,
    create_llm,
    create_query_rewriter,
    create_vectorstore,
)


DEV_SET_PATH = "eval/rag_dev_set.yaml"
OUTPUT_PATH = "data/rag_threshold_report.json"
MARKDOWN_PATH = "data/pidgin_threshold_report.md"
GRID = [round(0.20 + 0.05 * i, 2) for i in range(9)]  # 0.20 .. 0.60


# ---------------------------------------------------------------------------
# Legacy report (unchanged behaviour): the plain-English dev set, no rewriting.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Rewrite comparison report (query set + rewrite off/on).
# ---------------------------------------------------------------------------

def load_query_set(path: str) -> list[dict]:
    """Load a dev-set-shaped YAML into a flat question list."""
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    questions: list[dict] = []
    for entry in raw.get("in_scope") or []:
        questions.append({
            "question": entry["question"],
            "group": "in_scope",
            "expected_chunk_id": entry["expected_chunk_id"],
            "expected_heading_contains": entry.get("expected_heading_contains"),
            "source_dev_question": entry.get("source_dev_question"),
        })
    for entry in raw.get("out_of_scope") or []:
        kind = entry.get("kind")
        expected = entry.get("expected")
        if expected is None:
            expected = "no_relevant_result" if kind == "off_topic" else "unanswerable_in_domain"
        questions.append({
            "question": entry["question"],
            "group": "out_of_scope",
            "kind": kind,
            "expected": expected,
        })
    return questions


def score_query_set(questions, embedder, store, top_k, rewriter=None) -> list[dict]:
    per_question = []
    for q in questions:
        original = q["question"]
        rewritten = original
        applied = False
        if rewriter is not None:
            result = rewriter.rewrite(original)
            rewritten = result.rewritten
            applied = result.applied
        rows = store.query(embedder.embed_query(rewritten), top_k)
        top_results = [{"id": r["id"], "score": round(float(r["score"]), 4)} for r in rows]
        top1 = top_results[0] if top_results else {"id": None, "score": None}
        rank = None
        if q.get("expected_chunk_id"):
            for i, r in enumerate(top_results):
                if r["id"] == q["expected_chunk_id"]:
                    rank = i + 1
                    break
        per_question.append({
            **q,
            "original": original,
            "rewritten": rewritten,
            "rewrite_applied": applied,
            "top_results": top_results,
            "top1_id": top1["id"],
            "top1_score": top1["score"],
            "expected_rank": rank,
        })
    return per_question


def status_at(score, threshold) -> str:
    if score is not None and score >= threshold:
        return "ok"
    return "no_relevant_result"


def summarise(per_question, threshold) -> dict:
    in_scope = [p for p in per_question if p["group"] == "in_scope"]
    off_topic = [p for p in per_question if p["group"] == "out_of_scope" and p["kind"] == "off_topic"]
    unanswerable = [
        p for p in per_question
        if p["group"] == "out_of_scope" and p["kind"] == "in_domain_unanswerable"
    ]

    def answered(pool):
        return sum(1 for p in pool if (p["top1_score"] or 0.0) >= threshold)

    in_scores = [p["top1_score"] for p in in_scope if p["top1_score"] is not None]
    off_scores = [p["top1_score"] for p in off_topic if p["top1_score"] is not None]
    return {
        "threshold": threshold,
        "in_scope_total": len(in_scope),
        "in_scope_refused": len(in_scope) - answered(in_scope),
        "off_topic_total": len(off_topic),
        "off_topic_answered": answered(off_topic),
        "unanswerable_total": len(unanswerable),
        "unanswerable_answered": answered(unanswerable),
        "recall_at_top_k": sum(1 for p in in_scope if p["expected_rank"] is not None),
        "top1_accuracy": sum(1 for p in in_scope if p["expected_rank"] == 1),
        "lowest_in_scope_top1": min(in_scores) if in_scores else None,
        "highest_off_topic_top1": max(off_scores) if off_scores else None,
    }


def sweep_values(start: float, stop: float, step: float) -> list[float]:
    values = []
    current = start
    while current <= stop + 1e-9:
        values.append(round(current, 4))
        current += step
    return values


def _mode_payload(questions, dev_questions, embedder, store, top_k, threshold, rewriter, sweep_params):
    per_question = score_query_set(questions, embedder, store, top_k, rewriter)
    dev_per_question = score_query_set(dev_questions, embedder, store, top_k, rewriter)
    summary = summarise(per_question, threshold)
    dev_summary = summarise(dev_per_question, threshold)
    unanswerable = [
        {
            "question": p["original"],
            "rewritten": p["rewritten"],
            "top1_id": p["top1_id"],
            "top1_score": p["top1_score"],
        }
        for p in per_question
        if p["group"] == "out_of_scope" and p["kind"] == "in_domain_unanswerable"
    ]
    sweep = None
    if sweep_params is not None:
        start, stop, step = sweep_params
        sweep = []
        for value in sweep_values(start, stop, step):
            row = summarise(per_question, value)
            sweep.append({
                "threshold": value,
                "in_scope_refused": row["in_scope_refused"],
                "off_topic_answered": row["off_topic_answered"],
            })
    return {
        "questions": per_question,
        "summary": summary,
        "dev_summary": dev_summary,
        "unanswerable": unanswerable,
        "sweep": sweep,
        "threshold": threshold,
        "top_k": top_k,
    }


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def render_markdown(state) -> str:
    modes = [m for m in ("off", "on") if m in state.get("modes", {})]
    lines: list[str] = []
    lines.append("# Pidgin query-rewrite threshold report")
    lines.append("")
    lines.append("Tuning only; this is NOT the held-out Chat 7 evaluation set.")
    lines.append("")
    lines.append(f"Query set: `{state.get('query_set')}`")
    lines.append("")

    # Per-query side-by-side table.
    lines.append("## Per query")
    lines.append("")
    header = "| # | query |"
    sep = "|---|---|"
    for mode in modes:
        header += (f" {mode}: rewritten | {mode}: top-1 | {mode}: score |"
                   f" {mode}: expected in top-k | {mode}: status |")
        sep += "---|---|---|---|---|---|"
    lines.append(header)
    lines.append(sep)
    base = state["modes"][modes[0]]["questions"] if modes else []
    for i, q in enumerate(base, start=1):
        row = f"| {i} | {q['original']} |"
        for mode in modes:
            entry = state["modes"][mode]["questions"][i - 1]
            threshold = state["modes"][mode]["threshold"]
            in_top = "yes" if entry["expected_rank"] is not None else "no"
            if entry["group"] != "in_scope":
                in_top = "n/a"
            row += (f" {entry['rewritten']} | {entry['top1_id']} |"
                    f" {_fmt(entry['top1_score'])} | {in_top} |"
                    f" {status_at(entry['top1_score'], threshold)} |")
        lines.append(row)
    lines.append("")

    # Summary tables (Pidgin set and the plain-English dev set).
    lines.append("## Summary")
    lines.append("")
    for label, key in (("Pidgin tuning set", "summary"), ("Plain-English dev set", "dev_summary")):
        lines.append(f"### {label}")
        lines.append("")
        lines.append("| metric | " + " | ".join(modes) + " |")
        lines.append("|---|" + "---|" * len(modes))
        rows = [
            ("threshold", "threshold", _fmt),
            ("in-scope refused", "in_scope_refused", str),
            ("off-topic answered", "off_topic_answered", str),
            ("recall@top-k hits", "recall_at_top_k", str),
            ("top-1 accuracy", "top1_accuracy", str),
            ("lowest in-scope top-1", "lowest_in_scope_top1", _fmt),
            ("highest off-topic top-1", "highest_off_topic_top1", _fmt),
        ]
        for title, field, formatter in rows:
            cells = []
            for mode in modes:
                section = state["modes"][mode][key]
                if field in ("recall_at_top_k", "top1_accuracy"):
                    value = f"{section[field]}/{section['in_scope_total']}"
                else:
                    value = formatter(section.get(field))
                cells.append(value)
            lines.append(f"| {title} | " + " | ".join(cells) + " |")
        lines.append("")

    # In-domain unanswerable questions, listed separately.
    lines.append("## In-domain unanswerable (not counted as threshold failures)")
    lines.append("")
    lines.append("| query | mode | rewritten | top-1 | score |")
    lines.append("|---|---|---|---|---|")
    for mode in modes:
        for entry in state["modes"][mode]["unanswerable"]:
            lines.append(
                f"| {entry['question']} | {mode} | {entry['rewritten']} |"
                f" {entry['top1_id']} | {_fmt(entry['top1_score'])} |"
            )
    lines.append("")

    # Threshold sweep for rewrite on.
    lines.append("## Threshold sweep (rewrite on)")
    lines.append("")
    if "on" in state["modes"] and state["modes"]["on"].get("sweep"):
        lines.append("| threshold | in-scope refused | off-topic answered |")
        lines.append("|---|---|---|")
        for row in state["modes"]["on"]["sweep"]:
            lines.append(
                f"| {_fmt(row['threshold'])} | {row['in_scope_refused']} |"
                f" {row['off_topic_answered']} |"
            )
    else:
        lines.append("_Run with `--rewrite on` to populate the sweep._")
    lines.append("")
    return "\n".join(lines)


def rewrite_report(
    config_dir: str = "config",
    query_set: str = DEV_SET_PATH,
    rewrite: bool = False,
    output: str = MARKDOWN_PATH,
    embedder=None,
    store=None,
    rewriter=None,
    sweep_start=None,
    sweep_stop=None,
    sweep_step=None,
) -> int:
    try:
        cfg = load_config(config_dir=config_dir)
        threshold = cfg.settings.rag.similarity_threshold
        top_k = cfg.settings.rag.top_k
        if embedder is None:
            embedder = create_embedder(cfg)
        if store is None:
            store = create_vectorstore(cfg, embedder)

        mode_key = "on" if rewrite else "off"
        active_rewriter = None
        if rewrite:
            active_rewriter = rewriter or create_query_rewriter(cfg, create_llm(cfg))

        sweep_params = None
        if rewrite:
            configured = cfg.settings.rag.threshold_report
            sweep_params = (
                configured.sweep_start if sweep_start is None else sweep_start,
                configured.sweep_stop if sweep_stop is None else sweep_stop,
                configured.sweep_step if sweep_step is None else sweep_step,
            )

        questions = load_query_set(query_set)
        dev_questions = questions if os.path.abspath(query_set) == os.path.abspath(DEV_SET_PATH) \
            else load_query_set(DEV_SET_PATH)

        payload = _mode_payload(
            questions, dev_questions, embedder, store, top_k, threshold,
            active_rewriter, sweep_params,
        )

        directory = os.path.dirname(output)
        if directory:
            os.makedirs(directory, exist_ok=True)
        json_path = os.path.splitext(output)[0] + ".json"

        state = {"query_set": query_set, "modes": {}}
        if os.path.isfile(json_path):
            try:
                with open(json_path, encoding="utf-8") as f:
                    existing = json.load(f)
                if existing.get("query_set") == query_set:
                    state = existing
                    state.setdefault("modes", {})
            except Exception:
                state = {"query_set": query_set, "modes": {}}
        state["modes"][mode_key] = payload
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)

        with open(output, "w", encoding="utf-8") as f:
            f.write(render_markdown(state))

        summary = payload["summary"]
        print(f"rewrite {mode_key}: in-scope refused {summary['in_scope_refused']}/"
              f"{summary['in_scope_total']}, off-topic answered "
              f"{summary['off_topic_answered']}/{summary['off_topic_total']}, "
              f"recall@top_k {summary['recall_at_top_k']}/{summary['in_scope_total']}, "
              f"top-1 {summary['top1_accuracy']}/{summary['in_scope_total']}")
        print(f"wrote {output} and {json_path} covering {len(payload['questions'])} questions")
        return 0
    except Exception as exc:
        print(f"Rewrite report failed: {exc}", file=sys.stderr, flush=True)
        return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Report retrieval scores across candidate thresholds."
    )
    parser.add_argument("--config", default="config", help="config directory (default: config)")
    parser.add_argument("--queries", default=None,
                        help=f"query set to score (default: legacy {DEV_SET_PATH})")
    parser.add_argument("--rewrite", choices=["off", "on"], default=None,
                        help="run the configured query rewriter before search")
    parser.add_argument("--output", default=MARKDOWN_PATH,
                        help=f"markdown report path (default: {MARKDOWN_PATH})")
    parser.add_argument("--sweep-start", type=float, default=None)
    parser.add_argument("--sweep-stop", type=float, default=None)
    parser.add_argument("--sweep-step", type=float, default=None)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    # Keep the original CLI behaviour when no query set is given and rewriting
    # is not requested: the plain-English dev set, no rewriter, legacy JSON.
    if args.queries is None and args.rewrite in (None, "off"):
        return threshold_report(config_dir=args.config)

    query_set = args.queries or DEV_SET_PATH
    return rewrite_report(
        config_dir=args.config,
        query_set=query_set,
        rewrite=args.rewrite == "on",
        output=args.output,
        sweep_start=args.sweep_start,
        sweep_stop=args.sweep_stop,
        sweep_step=args.sweep_step,
    )


if __name__ == "__main__":
    sys.exit(main())