from __future__ import annotations

import sys
import logging
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from contextlib import asynccontextmanager
from core.config import ConfigError
from core.startup import run_startup, StartupResult


def create_app(config_dir: str = "config", startup_result: Optional[StartupResult] = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        result = startup_result
        if result is None:
            # Let ConfigError propagate so app fails to start
            result = run_startup(config_dir=config_dir)
        app.state.startup_result = result
        yield
        # Shutdown: clean up loaded components, ignore errors
        if result is not None:
            for kind, instance in result.components.items():
                try:
                    if hasattr(instance, "stop"):
                        instance.stop()
                except Exception:
                    pass
                try:
                    if hasattr(instance, "close"):
                        instance.close()
                except Exception:
                    pass

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    def health():
        if app.state.startup_result is None:
            return JSONResponse(
                status_code=503,
                content={"status": "error", "message": "Startup not completed"},
            )
        res: StartupResult = app.state.startup_result
        reports = []
        for r in res.reports:
            # Re-run healthchecks of loaded components
            healthy = r.healthy
            detail = r.detail
            if r.status == "loaded" and r.kind in res.components:
                try:
                    health = res.components[r.kind].healthcheck()
                    healthy = health.ok
                    detail = health.detail
                except Exception as exc:
                    healthy = False
                    detail = str(exc)
            reports.append({
                "kind": r.kind,
                "implementation": r.implementation,
                "status": r.status,
                "description": r.description,
                "healthy": healthy,
                "detail": detail,
            })
        overall = res.overall
        code = 200 if overall in ("ok", "degraded") else 503
        return JSONResponse(
            status_code=code,
            content={
                "status": overall,
                "components": reports,
                "debug": res.config.settings.logging.debug,
            },
        )

    return app


def main():
    try:
        from core.config import load_config
        cfg = load_config()
        startup_result = run_startup()
        import uvicorn
        def app_factory(config_dir="config", startup_result=startup_result):
            return create_app(config_dir=config_dir, startup_result=startup_result)
        uvicorn.run(
            app_factory,
            host=cfg.settings.adapter.host,
            port=cfg.settings.adapter.port,
            factory=True,
        )
    except ConfigError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
