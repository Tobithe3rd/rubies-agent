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
from .routes_upload import router as upload_router
from .upload_guard import UploadGuardMiddleware


def create_app(cfg: AppConfig = None, clock=None, attachments_config=None,
               vision_extractor=None) -> FastAPI:
    if cfg is None:
        cfg = load_config()
    if attachments_config is None:
        from attachments.config import load_attachments_config
        attachments_config = load_attachments_config()
    if vision_extractor is None:
        from attachments.vision.base import get_vision_extractor
        vision_extractor = get_vision_extractor(attachments_config.vision)

    web_cfg = cfg.settings.adapters.web
    app = FastAPI(title="Rubies Web Adapter")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=web_cfg.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    profile = attachments_config.profile("chat_attachment")
    app.add_middleware(UploadGuardMiddleware, max_request_bytes=profile.max_request_bytes)

    app.state.cfg = cfg
    app.state.chat_store = ChatSessionStore(cfg, clock=clock)
    app.state.stream_tasks = set()
    app.state.shared_llm = None
    app.state.attachments_config = attachments_config
    app.state.vision_extractor = vision_extractor

    app.include_router(chat_router)
    app.include_router(stream_router)
    app.include_router(upload_router)
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
