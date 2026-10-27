from __future__ import annotations

import os
import sys
import json
import argparse


DEFAULT_REPORT = "data/rag_threshold_report.json"


def analyze(report_path: str = DEFAULT_REPORT) -> int:
    if not os.path.isfile(report_path):
        print(f"Dev-set analysis failed: report file not found: {report_path}", file=sys.stderr, flush=True)
        return 1
    try:
        with open(report_path, encoding="utf-8") as f:
            report = json.load(f)
        questions = report["questions"]
        if not isinstance(questions, list):
            raise ValueError("'questions' is not a list")
    except Exception as exc:
        print(f"Dev-set analysis failed: malformed report {report_path}: {exc}", file=sys.stderr, flush=True)
        return 1

    in_scope = [q for q in questions if q.get("group") == "in_scope"]
    rank1 = ranks_2_4 = outside = faq_top1 = 0

    for q in in_scope:
        rank = q.get("expected_rank")
        if rank == 1:
            rank1 += 1
            continue

        top1_id = q.get("top1_id")
        top1_score = q.get("top1_score")
        is_faq = str(top1_id).startswith("RUB-DOC-08")

        if rank is None:
            outside += 1
            rank_text = "outside top_k"
        else:
            ranks_2_4 += 1
            rank_text = str(rank)

        if is_faq:
            faq_top1 += 1

        print(f"{q.get('question')}")
        print(f"  expected {q.get('expected_chunk_id')} at rank {rank_text}; "
              f"top-1 {top1_id} (score {top1_score}); top-1 from RUB-DOC-08: {is_faq}")

    print(
        f"in-scope questions: {len(in_scope)}, expected at rank 1: {rank1}, "
        f"ranks 2-4: {ranks_2_4}, outside top_k: {outside}, "
        f"rank-1 chunk from RUB-DOC-08 when expected was not rank 1: {faq_top1}"
    )
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Explain dev-set misses from the threshold report.")
    parser.add_argument("--report", default=DEFAULT_REPORT, help=f"report path (default: {DEFAULT_REPORT})")
    args = parser.parse_args(argv)
    return analyze(args.report)


if __name__ == "__main__":
    sys.exit(main())
