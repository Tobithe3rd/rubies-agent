"""Thin shim: keeps adapters.web_chat imports and adapter registration working."""
from __future__ import annotations

from core.config import AppConfig
from core.factories import create_agent_runner, register
from adapters.web.app import create_app, main
from adapters.web.store import ChatSessionStore


@register("adapter", "web")
class WebAdapter:
    """Registered adapter class (not instantiated directly here)."""

    def __init__(self, cfg: AppConfig, env=None):
        self.cfg = cfg
        self.env = env or cfg.env

    def describe(self) -> str:
        return "web:http"

    def healthcheck(self):
        from core.interfaces import HealthStatus
        return HealthStatus("web", True, "http adapter ready")


__all__ = ["create_app", "main", "WebAdapter", "ChatSessionStore", "create_agent_runner"]


if __name__ == "__main__":
    main()
