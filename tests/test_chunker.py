import hashlib
import json
import os
import shutil
import subprocess
import sys

import pytest

from core.config import ConfigError, load_config

DOCS_DIR = "rag/docs"


def _count_sections_independently() -> int:
    total = 0
    for name in sorted(os.listdir(DOCS_DIR)):
        if not name.endswith(".md") or name.startswith("_"):
            continue
        with open(os.path.join(DOCS_DIR, name), encoding="utf-8") as f:
            total += sum(1 for line in f if line.startswith("## "))
    return total


def _run_chunker() -> str:
    subprocess.run([sys.executable, "-m", "rag.chunker"], check=True, capture_output=True, text=True)
    path = load_config().settings.rag.chunks_path
    return path


def _read_records(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_chunk_count_matches_sections():
    path = _run_chunker()
    records = _read_records(path)
    assert len(records) == _count_sections_independently()


def test_ids_are_unique():
    path = _run_chunker()
    records = _read_records(path)
    ids = [r["id"] for r in records]
    assert len(ids) == len(set(ids))


def test_citation_for_rubdoc01_section2():
    path = _run_chunker()
    records = {r["id"]: r for r in _read_records(path)}
    assert records["RUB-DOC-01#2"]["citation"] == "Fee Schedule, section 2 (Transfer fees)"
    assert records["RUB-DOC-01#2"]["text"].startswith("Fee Schedule > 2. ")


def test_bogus_chunking_mode_raises(tmp_path):
    shutil.copy("config/settings.yaml", tmp_path / "settings.yaml")
    shutil.copy("config/tools.yaml", tmp_path / "tools.yaml")
    settings = (tmp_path / "settings.yaml").read_text(encoding="utf-8")
    settings = settings.replace("    mode: heading", "    mode: bogus")
    (tmp_path / "settings.yaml").write_text(settings, encoding="utf-8")
    with pytest.raises(ConfigError) as exc:
        load_config(config_dir=str(tmp_path))
    assert "chunking.mode" in str(exc.value)


def test_two_runs_are_identical():
    path = _run_chunker()
    first = hashlib.sha256(open(path, "rb").read()).hexdigest()
    _run_chunker()
    second = hashlib.sha256(open(path, "rb").read()).hexdigest()
    assert first == second
