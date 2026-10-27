from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator
from dotenv import load_dotenv


class ConfigError(Exception):
    pass


# --- settings groups ---

class LLMConfig(BaseModel):
    model_config = {"extra": "forbid"}
    provider: str = "bedrock"
    model_id: str
    temperature: float = Field(ge=0.0, le=2.0)
    max_tokens: int = Field(ge=1)


class EmbeddingsConfig(BaseModel):
    model_config = {"extra": "forbid"}
    provider: str = "bedrock_titan"
    model_id: str
    dimensions: int = Field(ge=1)


class VectorstoreConfig(BaseModel):
    model_config = {"extra": "forbid"}
    type: str
    path: str
    collection: str


class RAGConfig(BaseModel):
    model_config = {"extra": "forbid"}
    docs_path: str
    chunking_mode: str
    top_k: int = Field(ge=1)
    similarity_threshold: float = Field(ge=0.0, le=1.0)
    max_failed_retrievals: int = Field(ge=0)


class SessionConfig(BaseModel):
    model_config = {"extra": "forbid"}
    expiry_minutes: int = Field(ge=1)
    max_failed_verifications: int = Field(ge=0)


class HandoffConfig(BaseModel):
    model_config = {"extra": "forbid"}
    max_repeated_tool_errors: int = Field(ge=1)


class LoggingConfig(BaseModel):
    model_config = {"extra": "forbid"}
    tool_log_path: str
    debug: bool


class AdapterConfig(BaseModel):
    model_config = {"extra": "forbid"}
    type: str
    host: str
    port: int = Field(ge=1, le=65535)


class SeedConfig(BaseModel):
    model_config = {"extra": "forbid"}
    random_seed: int = 42
    customer_count: int = Field(ge=1, le=100)
    history_days: int = Field(ge=1)


class StartupConfig(BaseModel):
    model_config = {"extra": "forbid"}
    require_components: bool


class BankAPIConfig(BaseModel):
    model_config = {"extra": "forbid"}
    db_path: str
    store_type: str = "sqlite"
    otp_length: int = Field(ge=4, le=10)
    otp_ttl_seconds: int = Field(ge=60)
    otp_max_attempts: int = Field(ge=1, le=10)
    otp_delivery: str = "mock"
    otp_log_path: str

    @field_validator("otp_delivery")
    @classmethod
    def only_mock_supported(cls, v: str) -> str:
        if v != "mock":
            raise ValueError("only 'mock' is supported for otp_delivery at this stage")
        return v


class Settings(BaseModel):
    model_config = {"extra": "forbid"}
    llm: LLMConfig
    embeddings: EmbeddingsConfig
    vectorstore: VectorstoreConfig
    rag: RAGConfig
    session: SessionConfig
    handoff: HandoffConfig
    logging: LoggingConfig
    adapter: AdapterConfig
    bank_api: BankAPIConfig
    startup: StartupConfig
    seed: SeedConfig


# --- tools ---

class ToolConfig(BaseModel):
    model_config = {"extra": "forbid"}
    enabled: bool
    requires_confirmation: bool
    requires_verified_session: bool
    description: str


class ToolsConfig(BaseModel):
    model_config = {"extra": "forbid"}
    # Dynamic keys handled by parsing dict then validating each value
    pass


# --- env ---

class EnvConfig(BaseModel):
    model_config = {"extra": "forbid"}
    AWS_REGION: str
    AWS_ACCESS_KEY_ID: Optional[str] = None
    AWS_SECRET_ACCESS_KEY: Optional[str] = None
    AWS_SESSION_TOKEN: Optional[str] = None
    BANK_API_URL: str
    OTP_HASH_SECRET: str

    @field_validator("AWS_REGION", "BANK_API_URL")
    @classmethod
    def must_be_non_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("must be a non-empty string")
        return v

    @field_validator("OTP_HASH_SECRET")
    @classmethod
    def otp_secret_min_length(cls, v: str) -> str:
        if not v or len(v) < 16:
            raise ValueError("OTP_HASH_SECRET is required and must be at least 16 characters")
        return v

    @field_validator("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN")
    @classmethod
    def mask_in_errors(cls, v):
        return v


# --- app config ---

class AppConfig(BaseModel):
    settings: Settings
    tools: dict[str, ToolConfig]
    env: EnvConfig


# --- helpers ---

def _load_yaml(path: Path) -> dict:
    try:
        with open(path, "r") as f:
            return yaml.safe_load(f) or {}
    except Exception as exc:
        raise ConfigError(f"Failed to read YAML file: {path}: {exc}")


def load_config(config_dir: str = "config") -> AppConfig:
    load_dotenv()

    settings_path = Path(config_dir) / "settings.yaml"
    tools_path = Path(config_dir) / "tools.yaml"

    errors: list[str] = []
    settings: Optional[Settings] = None
    env: Optional[EnvConfig] = None

    # Load settings (collect errors, don't stop)
    try:
        raw_settings = _load_yaml(settings_path)
    except ConfigError as exc:
        errors.append(str(exc))
        raw_settings = {}
    try:
        settings = Settings.model_validate(raw_settings)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            errors.append(f"settings.yaml -> {loc}: {err.get('msg', 'invalid value')}")

    # Load tools (collect errors, don't stop)
    tools: dict[str, ToolConfig] = {}
    try:
        raw_tools = _load_yaml(tools_path)
        if not isinstance(raw_tools, dict):
            errors.append(f"tools.yaml must contain a mapping; got {type(raw_tools).__name__}")
            raw_tools = {}
    except ConfigError as exc:
        errors.append(str(exc))
        raw_tools = {}

    for key, value in raw_tools.items():
        try:
            tools[key] = ToolConfig.model_validate(value)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err.get("loc", ()))
                errors.append(f"tools.yaml -> {key}.{loc}: {err.get('msg', 'invalid value')}")

    # Load env (collect errors, don't stop)
    try:
        env = EnvConfig(
            AWS_REGION=os.environ.get("AWS_REGION", ""),
            AWS_ACCESS_KEY_ID=os.environ.get("AWS_ACCESS_KEY_ID") or None,
            AWS_SECRET_ACCESS_KEY=os.environ.get("AWS_SECRET_ACCESS_KEY") or None,
            AWS_SESSION_TOKEN=os.environ.get("AWS_SESSION_TOKEN") or None,
            BANK_API_URL=os.environ.get("BANK_API_URL", ""),
            OTP_HASH_SECRET=os.environ.get("OTP_HASH_SECRET", ""),
        )
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            errors.append(f".env -> {loc}: {err.get('msg', 'invalid value')}")
        env = None

    if errors:
        raise ConfigError("Config validation failed: " + "; ".join(errors))
    if settings is None or env is None:
        raise ConfigError("Config validation failed: missing required settings or env configuration.")

    return AppConfig(settings=settings, tools=tools, env=env)


def masked_summary(app_config: AppConfig) -> dict[str, Any]:
    def mask(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: "***" if k in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "OTP_HASH_SECRET") else mask(v) for k, v in value.items()}
        if isinstance(value, list):
            return [mask(v) for v in value]
        return value

    # Build a plain dict from settings and mask secrets
    settings_dict = app_config.settings.model_dump()
    # Mask secret fields explicitly at top level of settings if any
    masked_settings = mask(settings_dict)
    return {
        "settings": masked_settings,
        "tools": {k: v.model_dump() for k, v in app_config.tools.items()},
        "env": {
            "AWS_REGION": app_config.env.AWS_REGION,
            "AWS_ACCESS_KEY_ID": "***",
            "AWS_SECRET_ACCESS_KEY": "***",
            "AWS_SESSION_TOKEN": "***" if app_config.env.AWS_SESSION_TOKEN else None,
            "BANK_API_URL": app_config.env.BANK_API_URL,
            "OTP_HASH_SECRET": "***",
        },
    }
