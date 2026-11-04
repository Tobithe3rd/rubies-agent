"""App factory wiring: create_app, CORS, router registration."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

try:
    from core.config import AppConfig, load_config
except ImportError:
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from core.config import AppConfig, load_config

from .store import ChatSessionStore
from .routes_chat import router as chat_router
from .routes_session import router as session_router
from .routes_stream import router as stream_router


def create_app(cfg: AppConfig = None, clock=None) -> FastAPI:
    if cfg is None:
        cfg = load_config()

    web_cfg = cfg.settings.adapters.web
    app = FastAPI(title="Rubies Web Adapter")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=web_cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.state.cfg = cfg
    app.state.chat_store = ChatSessionStore(cfg, clock=clock)
    app.state.stream_tasks = set()
    app.state.shared_llm = None

    app.include_router(chat_router)
    app.include_router(stream_router)
    app.include_router(session_router)
    return app


def main():
    cfg = load_config()
    import uvicorn
    uvicorn.run(
        "adapters.web_chat:create_app",
        factory=True,
        host=cfg.settings.adapters.web.host,
        port=cfg.settings.adapters.web.port,
    )
