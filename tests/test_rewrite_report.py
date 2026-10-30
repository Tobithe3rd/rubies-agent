import json

from core.config import load_config
from core.interfaces import HealthStatus, QueryRewriter, RewriteResult
from providers.llm.mock import MockLLM
from rag.query_rewrite import LLMQueryRewriter
import rag.threshold_report as tr


def _set_env(monkeypatch):
    monkeypatch.setenv("AWS_REGION", "us-east-1")
    monkeypatch.setenv("BANK_API_URL", "http://localhost:8001")
    monkeypatch.setenv("OTP_HASH_SECRET", "test-secret-at-least-16-chars")


class TextEmbedder:
    """embed_query returns the text, so the fake store can key on it."""

    def describe(self):
        return "text"

    def healthcheck(self):
        return HealthStatus("text", True, "ok")

    @property
    def dimensions(self):
        return 8

    def embed_documents(self, texts):
        return [list(t) for t in texts]

    def embed_query(self, text):
        return text


class FakeStore:
    def __init__(self, rows_by_text):
        self.rows_by_text = rows_by_text

    def query(self, embedding, top_k):
        return self.rows_by_text.get(embedding, [])[:top_k]


def row(chunk_id, score):
    return {
        "id": chunk_id,
        "score": score,
        "citation": f"doc, section ({chunk_id})",
        "doc_title": "doc",
        "section_heading": "head",
        "text": "body",
    }


class CountingRewriter(QueryRewriter):
    def __init__(self, mapping=None):
        self.calls = []
        self.mapping = mapping or {}

    def describe(self):
        return "counting"

    def healthcheck(self):
        return HealthStatus("counting", True, "ok")

    def rewrite(self, query):
        self.calls.append(query)
        text = self.mapping.get(query, query)
        return RewriteResult(
            rewritten=text, applied=True, ok=True, duration_ms=0,
            original_len=len(query), rewritten_len=len(text),
        )


class BoomRewriter(CountingRewriter):
    def rewrite(self, query):
        self.calls.append(query)
        raise AssertionError("rewriter must not be called when rewriting is off")


QUESTIONS = [
    {"question": "q1", "group": "in_scope", "expected_chunk_id": "A#1"},
    {"question": "q2", "group": "in_scope", "expected_chunk_id": "A#1"},
    {"question": "q3", "group": "in_scope", "expected_chunk_id": "B#5"},
    {"question": "off", "group": "out_of_scope", "kind": "off_topic"},
    {"question": "unans", "group": "out_of_scope", "kind": "in_domain_unanswerable"},
]

ROWS = {
    "q1": [row("A#1", 0.80), row("Z#1", 0.20)],
    "q2": [row("C#1", 0.50)],
    "q3": [row("D#1", 0.20), row("B#5", 0.19)],
    "off": [row("X#1", 0.10)],
    "unans": [row("RUB-DOC-08#1", 0.52)],
}


class TestSummaryMaths:
    def test_summary_numbers_from_tiny_fixture(self):
        per = tr.score_query_set(QUESTIONS, TextEmbedder(), FakeStore(ROWS), 4)
        summary = tr.summarise(per, 0.35)
        assert summary["in_scope_total"] == 3
        assert summary["in_scope_refused"] == 1        # only q3 below threshold
        assert summary["off_topic_total"] == 1
        assert summary["off_topic_answered"] == 0
        assert summary["unanswerable_total"] == 1
        assert summary["unanswerable_answered"] == 1   # known 0.52 case
        assert summary["recall_at_top_k"] == 2         # q1 rank 1, q3 rank 2
        assert summary["top1_accuracy"] == 1
        assert summary["lowest_in_scope_top1"] == 0.20
        assert summary["highest_off_topic_top1"] == 0.10

    def test_status_at_threshold(self):
        assert tr.status_at(0.40, 0.35) == "ok"
        assert tr.status_at(0.20, 0.35) == "no_relevant_result"
        assert tr.status_at(None, 0.35) == "no_relevant_result"

    def test_sweep_values_from_config_not_hardcoded(self):
        assert tr.sweep_values(0.30, 0.34, 0.02) == [0.30, 0.32, 0.34]


class TestRewriteCalls:
    def test_rewrite_off_makes_zero_rewriter_calls(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        rewriter = BoomRewriter()
        rc = tr.rewrite_report(
            query_set="eval/datasets/pidgin_tuning_set.yaml",
            rewrite=False,
            output=str(tmp_path / "report.md"),
            embedder=TextEmbedder(),
            store=FakeStore({}),
            rewriter=rewriter,
        )
        assert rc == 0
        assert rewriter.calls == []
        assert (tmp_path / "report.md").is_file()

    def test_rewrite_on_uses_the_scripted_llm(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        cfg = load_config(config_dir="config")
        llm = MockLLM(cfg.settings.llm, cfg.env)
        calls = len(tr.load_query_set("eval/datasets/pidgin_tuning_set.yaml")) + len(
            tr.load_query_set(tr.DEV_SET_PATH)
        )
        llm.load_complete_responses(["rewritten policy query"] * calls)
        rewriter = LLMQueryRewriter(cfg.settings.rag.query_rewrite, llm)
        rc = tr.rewrite_report(
            query_set="eval/datasets/pidgin_tuning_set.yaml",
            rewrite=True,
            output=str(tmp_path / "report.md"),
            embedder=TextEmbedder(),
            store=FakeStore({}),
            rewriter=rewriter,
        )
        assert rc == 0
        assert llm.complete_responses == []  # every query used the scripted rewriter


class TestReportGeneration:
    def test_report_file_contains_every_query(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        out = tmp_path / "report.md"
        rc = tr.rewrite_report(
            query_set="eval/datasets/pidgin_tuning_set.yaml",
            rewrite=False,
            output=str(out),
            embedder=TextEmbedder(),
            store=FakeStore({}),
        )
        assert rc == 0
        text = out.read_text(encoding="utf-8")
        questions = tr.load_query_set("eval/datasets/pidgin_tuning_set.yaml")
        for q in questions:
            assert q["question"] in text
        assert "NOT the held-out Chat 7 evaluation set" in text
        assert "Plain-English dev set" in text
        assert "In-domain unanswerable" in text

    def test_report_writes_accumulating_json(self, tmp_path, monkeypatch):
        _set_env(monkeypatch)
        out = tmp_path / "report.md"
        for rewrite in (False, True):
            tr.rewrite_report(
                query_set="eval/datasets/pidgin_tuning_set.yaml",
                rewrite=rewrite,
                output=str(out),
                embedder=TextEmbedder(),
                store=FakeStore({}),
                rewriter=None if not rewrite else CountingRewriter(mapping={
                    q["question"]: "rewritten"
                    for q in tr.load_query_set("eval/datasets/pidgin_tuning_set.yaml")
                }),
            )
        data = json.loads((tmp_path / "report.json").read_text(encoding="utf-8"))
        assert data["query_set"] == "eval/datasets/pidgin_tuning_set.yaml"
        assert set(data["modes"]) == {"off", "on"}


class TestCliAndTuningSet:
    def test_cli_flags_parse(self):
        parser = tr.build_parser()
        args = parser.parse_args([
            "--config", "conf", "--queries", "eval/datasets/pidgin_tuning_set.yaml",
            "--rewrite", "on", "--output", "out.md", "--sweep-step", "0.01",
        ])
        assert args.config == "conf"
        assert args.queries == "eval/datasets/pidgin_tuning_set.yaml"
        assert args.rewrite == "on"
        assert args.output == "out.md"
        assert args.sweep_step == 0.01

    def test_tuning_set_shape_and_ids_exist_in_chunks(self):
        questions = tr.load_query_set("eval/datasets/pidgin_tuning_set.yaml")
        in_scope = [q for q in questions if q["group"] == "in_scope"]
        off = [q for q in questions if q.get("kind") == "off_topic"]
        unans = [q for q in questions if q.get("kind") == "in_domain_unanswerable"]
        assert len(in_scope) == 14
        assert len(off) == 3
        assert len(unans) == 2
        assert all(q["expected"] == "no_relevant_result" for q in off)
        assert all(q["expected"] == "unanswerable_in_domain" for q in unans)
        chunk_ids = set()
        for line in open("data/generated/rag_chunks.jsonl", encoding="utf-8"):
            if line.strip():
                chunk_ids.add(json.loads(line)["id"])
        for q in in_scope:
            assert q["expected_chunk_id"] in chunk_ids, q["expected_chunk_id"]

    def test_legacy_dev_set_still_loads_26_questions(self):
        questions = tr.load_query_set(tr.DEV_SET_PATH)
        assert len(questions) == 26