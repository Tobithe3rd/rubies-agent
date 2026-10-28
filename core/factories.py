from __future__ import annotations

import importlib
from typing import Any

from core.config import AppConfig, ConfigError
from core.interfaces import (
    BankGateway,
    DataStore,
    Embedder,
    InterfaceAdapter,
    LLMProvider,
    OTPSender,
    VectorStore,
)

# ------------------------------------------------------------------
# Registry: clearly marked import map and decorator
# ------------------------------------------------------------------

# Lazy-import map: (kind, registered_name) -> module_path
# When a factory asks for a name, this module is imported; the module
# is expected to call register(kind, name) on its implementations.
_IMPORT_MAP: dict[tuple[str, str], str] = {
    ("llm", "bedrock"): "providers.llm.bedrock",
    ("embedder", "titan"): "providers.embeddings.titan",
    ("embedder", "mock"): "providers.embeddings.mock",
    ("vectorstore", "chroma"): "providers.vectorstore.chroma",
    ("datastore", "sqlite"): "providers.datastore.sqlite",
    ("adapter", "http_chat"): "adapters.http_chat",
    ("otp_sender", "mock"): "providers.otp.mock",
    ("bank_gateway", "http"): "agent.bank_client",
}

_REGISTRY: dict[str, dict[str, Any]] = {
    "llm": {},
    "embedder": {},
    "vectorstore": {},
    "datastore": {},
    "adapter": {},
    "otp_sender": {},
    "bank_gateway": {},
}


def register(kind: str, name: str):
    """Decorator used by provider implementations to register themselves."""
    def decorator(cls):
        if kind not in _REGISTRY:
            raise ConfigError(f"Unknown kind for registry: {kind}")
        _REGISTRY[kind][name] = cls
        return cls
    return decorator


def _import_module(kind: str, name: str) -> None:
    key = (kind, name)
    if key not in _IMPORT_MAP:
        available = list(_REGISTRY.get(kind, {}).keys())
        if available:
            available_str = ", ".join(available)
        else:
            available_str = "(none registered yet)"
        raise ConfigError(
            f"Unknown {kind} name '{name}'. "
            f"Available: {available_str}. "
            f"Built-in import map keys for {kind}: "
            f"{[k for k in _IMPORT_MAP if k[0] == kind]}"
        )
    module_path = _IMPORT_MAP[key]
    try:
        importlib.import_module(module_path)
    except ModuleNotFoundError:
        raise ConfigError(
            f"Implementation '{name}' for kind '{kind}' is not built yet "
            f"(module '{module_path}' not found)."
        )


def _get_class(kind: str, name: str) -> Any:
    # Check registry first (allows tests to register without import map entries)
    if kind in _REGISTRY and name in _REGISTRY[kind]:
        return _REGISTRY[kind][name]
    # Otherwise try to import module that registers itself
    _import_module(kind, name)
    if kind not in _REGISTRY:
        raise ConfigError(f"Unknown kind for registry: {kind}")
    if name not in _REGISTRY[kind]:
        available = ", ".join(sorted(_REGISTRY[kind].keys()))
        raise ConfigError(
            f"Unknown {kind} name '{name}' after importing module. "
            f"Registered names: {available or '(none)'}"
        )
    return _REGISTRY[kind][name]


# --- factory functions ---

def create_llm(cfg: AppConfig) -> LLMProvider:
    name = cfg.settings.llm.provider
    cls = _get_class("llm", name)
    return cls(cfg.settings.llm, cfg.env)


def create_embedder(cfg: AppConfig) -> Embedder:
    name = cfg.settings.embeddings.provider
    cls = _get_class("embedder", name)
    return cls(cfg.settings.embeddings, cfg.env)


def create_vectorstore(cfg: AppConfig, embedder: Embedder) -> VectorStore:
    name = cfg.settings.vectorstore.type
    cls = _get_class("vectorstore", name)
    return cls(cfg.settings.vectorstore, embedder, cfg.env)


def create_datastore(cfg: AppConfig) -> DataStore:
    name = cfg.settings.bank_api.store_type
    cls = _get_class("datastore", name)
    return cls(cfg.settings.bank_api, cfg.env)


def create_adapter(cfg: AppConfig) -> InterfaceAdapter:
    name = cfg.settings.adapter.type
    cls = _get_class("adapter", name)
    return cls(cfg.settings.adapter, cfg.env)


def create_otp_sender(cfg: AppConfig) -> OTPSender:
    name = cfg.settings.bank_api.otp_delivery
    cls = _get_class("otp_sender", name)
    return cls(cfg.settings.bank_api, cfg.env)


def create_bank_gateway(cfg: AppConfig) -> BankGateway:
    name = cfg.settings.bank_api.gateway
    cls = _get_class("bank_gateway", name)
    return cls(cfg, cfg.env)


# --- build_components ---

def build_components(cfg: AppConfig) -> dict[str, Any]:
    llm = create_llm(cfg)
    embedder = create_embedder(cfg)
    vectorstore = create_vectorstore(cfg, embedder)
    datastore = create_datastore(cfg)
    adapter = create_adapter(cfg)
    bank_gateway = create_bank_gateway(cfg)
    return {
        "llm": llm,
        "embedder": embedder,
        "vectorstore": vectorstore,
        "datastore": datastore,
        "adapter": adapter,
        "bank_gateway": bank_gateway,
    }
