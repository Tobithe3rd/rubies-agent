from types import SimpleNamespace

import pytest

from agent.prompts import load_system_prompt
from core.config import ConfigError


def make_cfg(tmp_path, path):
    return SimpleNamespace(
        settings=SimpleNamespace(
            agent=SimpleNamespace(
                system_prompt_path=str(path),
                pidgin_examples_path="prompts/pidgin_examples.md",
            )
        )
    )


def test_missing_prompt_names_the_key(tmp_path):
    cfg = make_cfg(tmp_path, tmp_path / "nope.md")
    with pytest.raises(ConfigError) as exc:
        load_system_prompt(cfg)
    assert "agent.system_prompt_path" in str(exc.value)


def test_empty_prompt_names_the_key(tmp_path):
    path = tmp_path / "empty.md"
    path.write_text("   \n")
    cfg = make_cfg(tmp_path, path)
    with pytest.raises(ConfigError) as exc:
        load_system_prompt(cfg)
    assert "agent.system_prompt_path" in str(exc.value)


def test_prompt_is_read_unchanged(tmp_path):
    path = tmp_path / "prompt.md"
    text = "# hello\n\nbody text\n"
    path.write_text(text, encoding="utf-8")
    cfg = make_cfg(tmp_path, path)
    # With pidgin examples appended, the result includes both texts
    full = load_system_prompt(cfg)
    assert text in full
