"""Shared fixtures for web adapter tests."""
import pytest

from core.config import load_config
from tests.adapters.helpers import set_env


@pytest.fixture
def cfg(monkeypatch):
    set_env(monkeypatch)
    config = load_config(config_dir="config")
    config.settings.llm.provider = "mock"
    return config
