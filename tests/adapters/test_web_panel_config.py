"""Session panel: receipt template configuration safety."""
from pathlib import Path

import pytest

from core.config import ConfigError, load_config
from tests.adapters.helpers import config_copy, edit_yaml, set_env


def test_bad_receipt_template_fails_fast(tmp_path, monkeypatch):
    set_env(monkeypatch)
    config_dir = config_copy(tmp_path)
    path = Path(config_dir) / "tools.yaml"

    def bad_template(data):
        data["handoff_to_human"]["receipt"]["template"] = "Phone {phone}"

    edit_yaml(path, bad_template)

    with pytest.raises(ConfigError) as exc:
        load_config(config_dir=str(config_dir))
    assert "receipt.template" in str(exc.value)
    assert "phone" in str(exc.value)
