from __future__ import annotations

from pathlib import Path

from core.config import AppConfig, ConfigError


def load_system_prompt(config: AppConfig) -> str:
    """Read agent.system_prompt_path, failing fast and naming the key."""
    key = "agent.system_prompt_path"
    configured = config.settings.agent.system_prompt_path
    path = Path(configured)
    if not path.is_file():
        raise ConfigError(f"{key} not found: {configured}")
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ConfigError(f"{key} is empty: {configured}")
    return text
