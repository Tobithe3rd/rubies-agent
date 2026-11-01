#!/usr/bin/env python3
"""Retrieval gates against real Bedrock (the query rewriter and the embeddings).

Run through scripts/checks/live_retrieval_gates.sh. Self-test, no AWS:
  python3 scripts/checks/live_retrieval_gates.py --selftest
The gates read the report written by rag.threshold_report into /tmp; nothing here edits config, prompts or tracked files.
"""
import copy
import json
import os
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
QUERIES = "eval/datasets/pidgin_tuning_set.yaml"
OUTPUT_MD = "/tmp/retrieval_gates_report.md"
OUTPUT_JSON = "/tmp/retrieval_gates_report.json"

# Baselines from Chat 5 step 3 (Pidgin tuning set and plain-English dev set, rewriter on). Change them only deliberately.
PIDGIN_TOTALS = {"in_scope_total": 14, "off_topic_total": 3, "unanswerable_total": 2}
DEV_TOTALS = {"in_scope_total": 20, "off_topic_total": 3, "unanswerable_total": 3}
MIN_PIDGIN_RECALL = 13
MIN_DEV_RECALL = 19
MIN_MARGIN = 0.05  # lowest in-scope top-1 minus threshold; below this the threshold is getting tight (INFO only)
EXPECTED_CHECKS = 12


def evaluate(on):
    """Return a list of (name, ok, detail). Never raises on missing keys."""
    out = []
    sets = (
        ("Pidgin set", on.get("summary") or {}, PIDGIN_TOTALS, MIN_PIDGIN_RECALL),
        ("plain-English dev set", on.get("dev_summary") or {}, DEV_TOTALS, MIN_DEV_RECALL),
    )
    for label, s, totals, min_recall in sets:
        for key, want in totals.items():
            out.append((f"{label}: {key} == {want} (the report covers every question)", s.get(key) == want, f"got {s.get(key)}"))
        out.append((
            f"{label}: no in-scope question refused (rewrite on)",
            s.get("in_scope_refused") == 0,
            f"refused {s.get('in_scope_refused')} of {s.get('in_scope_total')}",
        ))
        out.append((
            f"{label}: no off-topic question answered (rewrite on)",
            s.get("off_topic_answered") == 0,
            f"answered {s.get('off_topic_answered')} of {s.get('off_topic_total')}; highest off-topic top-1 {s.get('highest_off_topic_top1')}",
        ))
        out.append((
            f"{label}: recall@top_k >= {min_recall}",
            (s.get("recall_at_top_k") or 0) >= min_recall,
            f"got {s.get('recall_at_top_k')}",
        ))
    return out


def info_lines(on):
    lines = []
    p, d = on.get("summary") or {}, on.get("dev_summary") or {}
    thr = on.get("threshold", p.get("threshold"))
    lines.append(f"threshold {thr}, top_k {on.get('top_k')}")
    for label, s in (("Pidgin set", p), ("plain-English dev set", d)):
        low = s.get("lowest_in_scope_top1")
        if isinstance(low, (int, float)) and isinstance(thr, (int, float)):
            margin = low - thr
            flag = "" if margin >= MIN_MARGIN else f" (below {MIN_MARGIN}: the threshold is getting tight)"
            lines.append(f"{label}: lowest in-scope top-1 {low}, margin over the threshold {margin:.4f}{flag}")
        lines.append(
            f"{label}: highest off-topic top-1 {s.get('highest_off_topic_top1')}, top-1 accuracy {s.get('top1_accuracy')}, recall@k {s.get('recall_at_top_k')}"
        )
    for item in on.get("unanswerable") or []:
        lines.append(f"known limitation (not a gate): {item.get('question')!r} -> {item.get('top1_id')} {item.get('top1_score')}")
    return lines


def good_on():
    return {
        "threshold": 0.35,
        "top_k": 4,
        "summary": {
            "in_scope_total": 14, "in_scope_refused": 0, "off_topic_total": 3, "off_topic_answered": 0,
            "unanswerable_total": 2, "recall_at_top_k": 13, "top1_accuracy": 8,
            "lowest_in_scope_top1": 0.42, "highest_off_topic_top1": 0.1,
        },
        "dev_summary": {
            "in_scope_total": 20, "in_scope_refused": 0, "off_topic_total": 3, "off_topic_answered": 0,
            "unanswerable_total": 3, "recall_at_top_k": 19, "top1_accuracy": 15,
            "lowest_in_scope_top1": 0.46, "highest_off_topic_top1": 0.1,
        },
        "unanswerable": [{"question": "x", "top1_id": "RUB-DOC-08#1", "top1_score": 0.54}],
    }


def selftest():
    good = good_on()
    base = evaluate(good)

    def failing(on):
        return [name for name, ok, _ in evaluate(on) if not ok]

    bad_dev = copy.deepcopy(good)
    bad_dev["dev_summary"]["off_topic_answered"] = 1
    bad_pid = copy.deepcopy(good)
    bad_pid["summary"]["in_scope_refused"] = 1
    low_recall = copy.deepcopy(good)
    low_recall["summary"]["recall_at_top_k"] = 12
    bad_total = copy.deepcopy(good)
    bad_total["summary"]["in_scope_total"] = 13
    tight = copy.deepcopy(good)
    tight["summary"]["lowest_in_scope_top1"] = 0.37
    empty = {"summary": {}, "dev_summary": {}}
    f_dev = failing(bad_dev)
    results = [
        ("good data yields exactly 12 checks", len(base) == EXPECTED_CHECKS),
        ("good data passes every check", all(ok for _, ok, _ in base)),
        ("a dev-set off-topic answer fails only the dev off-topic check", len(f_dev) == 1 and "plain-English dev set" in f_dev[0] and "off-topic" in f_dev[0]),
        ("a refused Pidgin in-scope question fails exactly one check", len(failing(bad_pid)) == 1),
        ("recall below the minimum fails", len(failing(low_recall)) == 1),
        ("a changed question total fails (a truncated report cannot pass)", len(failing(bad_total)) == 1),
        ("empty summaries fail every check without raising", len(failing(empty)) == EXPECTED_CHECKS),
        ("a tight margin is flagged", any("getting tight" in line for line in info_lines(tight))),
        ("a healthy margin is not flagged", not any("getting tight" in line for line in info_lines(good))),
        ("unanswerable items are INFO only", any("known limitation" in line for line in info_lines(good))),
    ]
    bad = 0
    for name, ok in results:
        print(("PASS: " if ok else "FAIL: ") + name)
        bad += 0 if ok else 1
    print(f"RESULT: {len(results) - bad} passed, {bad} failed (selftest)")
    return 1 if bad else 0


def main():
    os.chdir(REPO_ROOT)
    for path in (OUTPUT_MD, OUTPUT_JSON):
        if os.path.exists(path):
            os.remove(path)
    cmd = [sys.executable, "-m", "rag.threshold_report", "--queries", QUERIES, "--rewrite", "on", "--output", OUTPUT_MD]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0 or not os.path.exists(OUTPUT_JSON):
        print("ERROR: rag.threshold_report failed; this says nothing about retrieval quality")
        print((proc.stdout or "")[-600:])
        print((proc.stderr or "")[-600:])
        print("RESULT: 0 passed, 0 failed, 1 errors")
        return 2
    try:
        with open(OUTPUT_JSON, encoding="utf-8") as handle:
            data = json.load(handle)
        on = data["modes"]["on"]
        on["summary"]
        on["dev_summary"]
    except Exception as exc:
        print(f"ERROR: unexpected report layout ({type(exc).__name__}: {exc})")
        print("RESULT: 0 passed, 0 failed, 1 errors")
        return 2
    for line in (proc.stdout or "").splitlines()[-6:]:
        print("INFO: report: " + line)
    for line in info_lines(on):
        print("INFO: " + line)
    results = evaluate(on)
    passed = failed = 0
    for name, ok, detail in results:
        if ok:
            print(f"PASS: {name}")
            passed += 1
        else:
            print(f"FAIL: {name} ({detail})")
            failed += 1
    if len(results) != EXPECTED_CHECKS:
        print(f"FAIL: only {len(results)} of {EXPECTED_CHECKS} gate checks were produced")
        failed += 1
    print(f"RESULT: {passed} passed, {failed} failed, 0 errors")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else main())
