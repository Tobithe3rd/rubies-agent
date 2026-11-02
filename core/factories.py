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
    QueryRewriter,
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
    ("llm", "mock"): "providers.llm.mock",
    ("embedder", "titan"): "providers.embeddings.titan",
    ("embedder", "mock"): "providers.embeddings.mock",
    ("vectorstore", "chroma"): "providers.vectorstore.chroma",
    ("datastore", "sqlite"): "providers.datastore.sqlite",
    ("adapter", "cli"): "adapters.cli_chat",
    ("adapter", "http_chat"): "adapters.http_chat",
    ("adapter", "web"): "adapters.web_chat",
    ("otp_sender", "mock"): "providers.otp.mock",
    ("bank_gateway", "http"): "agent.bank_client",
    ("query_rewriter", "llm"): "rag.query_rewrite",
    ("query_rewriter", "passthrough"): "rag.query_rewrite",
}

_REGISTRY: dict[str, dict[str, Any]] = {
    "llm": {},
    "embedder": {},
    "vectorstore": {},
    "datastore": {},
    "adapter": {},
    "otp_sender": {},
    "bank_gateway": {},
    "query_rewriter": {},
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
        module = importlib.import_module(module_path)
    except ModuleNotFoundError:
        raise ConfigError(
            f"Implementation '{name}' for kind '{kind}' is not built yet "
            f"(module '{module_path}' not found)."
        )
    # A test or caller may have reset the registry after the module was first
    # imported; re-execute it so its register() calls run again.
    if name not in _REGISTRY.get(kind, {}):
        importlib.reload(module)


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


def create_adapter(cfg: AppConfig, runner=None) -> InterfaceAdapter:
    name = cfg.settings.adapter.type
    cls = _get_class("adapter", name)
    # Startup builds the adapter with no runner (healthcheck only); the CLI
    # passes one so it can call runner.handle_message. Keeping the no-runner
    # call as two args also keeps older adapters with (cfg, env) constructors.
    if runner is None:
        return cls(cfg, cfg.env)
    return cls(cfg, cfg.env, runner)


def create_otp_sender(cfg: AppConfig) -> OTPSender:
    name = cfg.settings.bank_api.otp_delivery
    cls = _get_class("otp_sender", name)
    return cls(cfg.settings.bank_api, cfg.env)


def create_bank_gateway(cfg: AppConfig) -> BankGateway:
    name = cfg.settings.bank_api.gateway
    cls = _get_class("bank_gateway", name)
    return cls(cfg, cfg.env)


def query_rewriter_name(cfg: AppConfig) -> str:
    """The configured implementation, or passthrough when rewriting is off."""
    qr = cfg.settings.rag.query_rewrite
    return qr.implementation if qr.enabled else "passthrough"


def create_query_rewriter(cfg: AppConfig, llm=None) -> QueryRewriter:
    qr = cfg.settings.rag.query_rewrite
    name = query_rewriter_name(cfg)
    cls = _get_class("query_rewriter", name)
    return cls(qr, llm)


def create_tool_runtime(cfg: AppConfig, session, gateway=None,
                        search_policy=None, logger=None, clock=None):
    """Wire the validated tool runtime. Imports stay lazy to avoid cycles."""
    from agent.tool_logger import JsonlToolLogger
    from agent.tool_runtime import ToolRuntime

    if gateway is None:
        gateway = create_bank_gateway(cfg)
    if search_policy is None:
        from rag.search import build_search_policy
        search_policy = build_search_policy(cfg)
    if logger is None:
        logger = JsonlToolLogger(cfg, clock=clock)
    return ToolRuntime(cfg, cfg.tools, session, gateway, search_policy, logger, clock=clock)


def create_agent_runner(cfg: AppConfig, session=None, llm=None):
    """Wire gateway, search, logger, runtime and LLM into an AgentRunner.

    The system prompt is loaded first so a missing/empty
    agent.system_prompt_path fails fast, naming the key.
    """
    from agent.prompts import load_system_prompt
    from agent.runner import AgentRunner

    system_prompt = load_system_prompt(cfg)  # fail fast naming the key
    if session is None:
        from agent.session import SessionState

        session = SessionState()
    runtime = create_tool_runtime(cfg, session)
    if llm is None:
        llm = create_llm(cfg)
    return AgentRunner(cfg, runtime, llm, system_prompt=system_prompt)


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
