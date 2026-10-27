import os
import sys
import json
import subprocess

SUMMARY = (
    "in-scope questions: 4, expected at rank 1: 1, ranks 2-4: 2, "
    "outside top_k: 1, rank-1 chunk from RUB-DOC-08 when expected was not rank 1: 1"
)


def _fixture_report():
    return {
        "questions": [
            {"group": "in_scope", "question": "q1 rank one", "expected_chunk_id": "RUB-DOC-01#2",
             "top1_id": "RUB-DOC-01#2", "top1_score": 0.9, "expected_rank": 1},
            {"group": "in_scope", "question": "q2 behind faq", "expected_chunk_id": "RUB-DOC-03#6",
             "top1_id": "RUB-DOC-08#3", "top1_score": 0.8, "expected_rank": 3},
            {"group": "in_scope", "question": "q3 behind non-faq", "expected_chunk_id": "RUB-DOC-04#3",
             "top1_id": "RUB-DOC-04#1", "top1_score": 0.7, "expected_rank": 2},
            {"group": "in_scope", "question": "q4 outside", "expected_chunk_id": "RUB-DOC-06#4",
             "top1_id": "RUB-DOC-06#6", "top1_score": 0.6, "expected_rank": None},
            {"group": "out_of_scope", "question": "off topic", "kind": "off_topic",
             "top1_id": "RUB-DOC-08#1", "top1_score": 0.1, "expected_rank": None},
        ]
    }


def _run(report_path):
    return subprocess.run(
        [sys.executable, "-m", "rag.analyze_dev_set", "--report", str(report_path)],
        capture_output=True, text=True,
    )


def test_summary_line(tmp_path):
    report = tmp_path / "report.json"
    report.write_text(json.dumps(_fixture_report()), encoding="utf-8")
    result = _run(report)
    assert result.returncode == 0, result.stderr
    assert SUMMARY in result.stdout


def test_missing_file_exits_non_zero(tmp_path):
    result = _run(tmp_path / "missing.json")
    assert result.returncode != 0
    assert "not found" in (result.stdout + result.stderr).lower()
