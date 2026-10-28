from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional

from core.config import AppConfig, ConfigError, masked_summary, load_config
from core import interfaces
from core import factories


@dataclass
class ComponentReport:
    kind: str
    implementation: str
    status: str  # "loaded" | "not_built" | "error"
    description: str  # from describe(), never secrets
    healthy: Optional[bool]
    detail: str  # never contains secrets


@dataclass
class StartupResult:
    config: AppConfig
    components: dict[str, Any]
    reports: list[ComponentReport]

    @property
    def overall(self) -> str:
        statuses = [r.status for r in self.reports]
        if any(s == "error" for s in statuses) or any(
            r.healthy is False for r in self.reports
        ):
            return "error"
        if any(s == "not_built" for s in statuses):
            return "degraded"
        if all(s == "loaded" for s in statuses) and all(
            r.healthy is True for r in self.reports if r.healthy is not None
        ):
            return "ok"
        return "error"


def run_startup(config_dir: str = "config") -> StartupResult:
    cfg = load_config(config_dir=config_dir)

    # b. Configure dedicated rubies logger (visible under uvicorn)
    level = logging.DEBUG if cfg.settings.logging.debug else logging.INFO
    rubies_logger = logging.getLogger("rubies")
    rubies_logger.setLevel(level)
    rubies_logger.propagate = False
    if not rubies_logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        rubies_logger.addHandler(handler)
    logger = logging.getLogger("rubies.startup")

    reports: list[ComponentReport] = []
    components: dict[str, Any] = {}

    build_order = [
        ("embedder", factories.create_embedder, [cfg]),
        ("vectorstore", factories.create_vectorstore, [cfg, None]),  # embedder filled later
        ("llm", factories.create_llm, [cfg]),
        ("datastore", factories.create_datastore, [cfg]),
        ("adapter", factories.create_adapter, [cfg]),
    ]

    loaded_embedder = None

    for idx, (kind, factory_fn, args_factory) in enumerate(build_order):
        # Resolve args: vectorstore needs embedder instance if loaded
        if kind == "vectorstore":
            args = [cfg, loaded_embedder if loaded_embedder is not None else None]
        else:
            args = [cfg] if kind != "vectorstore" else args_factory
            # Actually handle generically
            args = args_factory.copy()
            if kind == "vectorstore" and loaded_embedder is not None:
                args[1] = loaded_embedder

        # Re-derive args cleanly
        args = [cfg]
        if kind == "vectorstore":
            args.append(loaded_embedder)

        implementation = ""
        try:
            if kind == "embedder":
                implementation = cfg.settings.embeddings.provider
            elif kind == "vectorstore":
                implementation = cfg.settings.vectorstore.type
            elif kind == "llm":
                implementation = cfg.settings.llm.provider
            elif kind == "datastore":
                implementation = cfg.settings.bank_api.store_type
            elif kind == "adapter":
                implementation = cfg.settings.adapter.type
        except Exception:
            implementation = "unknown"

        try:
            if kind == "embedder":
                instance = factories.create_embedder(cfg)
                loaded_embedder = instance
            elif kind == "vectorstore":
                if loaded_embedder is None:
                    instance = None
                    status = "not_built"
                    detail = "depends on embedder"
                    description = ""
                    healthy = None
                    reports.append(
                        ComponentReport(
                            kind=kind,
                            implementation=implementation,
                            status=status,
                            description=description,
                            healthy=healthy,
                            detail=detail,
                        )
                    )
                    continue
                else:
                    instance = factories.create_vectorstore(cfg, loaded_embedder)
            elif kind == "llm":
                instance = factories.create_llm(cfg)
            elif kind == "datastore":
                instance = factories.create_datastore(cfg)
            elif kind == "adapter":
                instance = factories.create_adapter(cfg)
            else:
                instance = None

            # Healthcheck
            try:
                health = instance.healthcheck()
                description = health.name  # use describe if available; fall back
                try:
                    description = instance.describe()
                except Exception:
                    description = health.name
                reports.append(
                    ComponentReport(
                        kind=kind,
                        implementation=implementation,
                        status="loaded",
                        description=description,
                        healthy=health.ok,
                        detail=health.detail,
                    )
                )
                components[kind] = instance
            except Exception as exc:
                reports.append(
                    ComponentReport(
                        kind=kind,
                        implementation=implementation,
                        status="error",
                        description="",
                        healthy=False,
                        detail=str(exc),
                    )
                )
        except ConfigError as exc:
            msg = str(exc)
            if "not built yet" in msg or "Unknown" in msg:
                status = "not_built"
                detail = msg
            else:
                status = "error"
                detail = msg
            # Try describe from registered class if loaded; else empty
            description = ""
            try:
                description = implementation
            except Exception:
                pass
            reports.append(
                ComponentReport(
                    kind=kind,
                    implementation=implementation,
                    status=status,
                    description=description,
                    healthy=None if status == "not_built" else False,
                    detail=detail,
                )
            )
        except Exception as exc:
            reports.append(
                ComponentReport(
                    kind=kind,
                    implementation=implementation,
                    status="error",
                    description="",
                    healthy=False,
                    detail=str(exc),
                )
            )

    # e. If require_components true and any not_built or error, raise ConfigError
    if cfg.settings.startup.require_components:
        bad = [r for r in reports if r.status in ("not_built", "error")]
        if bad:
            names = ", ".join(f"{r.kind}({r.implementation})" for r in bad)
            raise ConfigError(
                f"required components not available: {names}"
            )

    # f. Print startup banner
    for r in reports:
        status_icon = "✓" if r.status == "loaded" else ("✗" if r.status == "not_built" else "!")
        logger.info(
            f"component: kind={r.kind} impl={r.implementation} status={r.status} "
            f"description={r.description} healthy={r.healthy} detail={r.detail}"
        )
    logger.info(f"startup overall: {StartupResult(cfg, components, reports).overall}")
    logger.info(f"debug: {cfg.settings.logging.debug}")
    logger.info(f"timezone: {cfg.settings.timezone}")
    logger.info(f"rag chunking mode: {cfg.settings.rag.chunking.mode}")

    if cfg.settings.logging.debug:
        summary = masked_summary(cfg)
        logger.debug(f"masked config summary: {summary}")

    return StartupResult(config=cfg, components=components, reports=reports)
