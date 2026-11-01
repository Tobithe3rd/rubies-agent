from __future__ import annotations

from pathlib import Path

from core.config import AppConfig, ConfigError


def load_system_prompt(config: AppConfig) -> str:
    """Read agent.system_prompt_path and agent.pidgin_examples_path, failing fast and naming the key."""
    key_sys = "agent.system_prompt_path"
    configured_sys = config.settings.agent.system_prompt_path
    path_sys = Path(configured_sys)
    if not path_sys.is_file():
        raise ConfigError(f"{key_sys} not found: {configured_sys}")
    text = path_sys.read_text(encoding="utf-8")
    if not text.strip():
        raise ConfigError(f"{key_sys} is empty: {configured_sys}")

    key_pidgin = "agent.pidgin_examples_path"
    configured_pidgin = config.settings.agent.pidgin_examples_path
    path_pidgin = Path(configured_pidgin)
    if not path_pidgin.is_file():
        raise ConfigError(f"{key_pidgin} not found: {configured_pidgin}")
    pidgin_text = path_pidgin.read_text(encoding="utf-8")
    if not pidgin_text.strip():
        raise ConfigError(f"{key_pidgin} is empty: {configured_pidgin}")

    return text + "\n\n## Pidgin rules and examples (loaded from " + configured_pidgin + ")\n" + pidgin_text
