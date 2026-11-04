from __future__ import annotations

import os
import re
from pathlib import Path
from string import Formatter
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator
from dotenv import load_dotenv


class ConfigError(Exception):
    pass


# --- settings groups ---

class LLMConfig(BaseModel):
    model_config = {"extra": "forbid"}
    provider: str = "bedrock"
    model_id: str
    temperature: float = Field(ge=0.0, le=1.0)
    max_tokens: int = Field(ge=1)
    # Transport resilience for the Bedrock endpoint (wifi blips, sleep/wake).
    connect_timeout_seconds: float = Field(default=5.0, ge=1, le=60)
    read_timeout_seconds: float = Field(default=60.0, ge=5, le=300)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_mode: str = "standard"

    @field_validator("provider")
    @classmethod
    def known_provider(cls, v: str) -> str:
        allowed = ["bedrock", "mock"]
        if v not in allowed:
            raise ValueError(f"llm.provider must be one of: {', '.join(allowed)}")
        return v


class EmbeddingsConfig(BaseModel):
    model_config = {"extra": "forbid"}
    provider: str = "titan"
    model_id: str
    dimensions: int = Field(ge=1)
    normalize: bool = True
    max_retries: int = Field(ge=0)
    backoff_seconds: float = Field(ge=0)
    request_timeout_seconds: int = Field(ge=1)

    @field_validator("provider")
    @classmethod
    def known_provider(cls, v: str) -> str:
        allowed = ["titan", "mock"]
        if v not in allowed:
            raise ValueError(f"embedding.provider must be one of: {', '.join(allowed)}")
        return v


class VectorstoreConfig(BaseModel):
    model_config = {"extra": "forbid"}
    type: str
    path: str
    collection: str

    @field_validator("type")
    @classmethod
    def known_type(cls, v: str) -> str:
        allowed = ["chroma"]
        if v not in allowed:
            raise ValueError(f"vector_store.type must be one of: {', '.join(allowed)}")
        return v


class ChunkingConfig(BaseModel):
    model_config = {"extra": "forbid"}
    mode: str = "heading"
    max_words: int = Field(ge=1)

    @field_validator("mode")
    @classmethod
    def known_mode(cls, v: str) -> str:
        allowed = ["heading"]
        if v not in allowed:
            raise ValueError(f"chunking.mode must be one of: {', '.join(allowed)}")
        return v


class QueryRewriteConfig(BaseModel):
    model_config = {"extra": "forbid"}
    enabled: bool = Field(strict=True)
    implementation: str = "llm"
    # null means "use llm.model_id"
    model_id: Optional[str] = None
    prompt_path: str
    max_input_chars: int = Field(ge=1)
    max_output_chars: int = Field(ge=1)
    max_tokens: int = Field(ge=1)
    temperature: float = Field(ge=0.0, le=1.0)
    timeout_seconds: float = Field(gt=0)
    log_text: bool = Field(strict=True)

    @field_validator("implementation")
    @classmethod
    def known_implementation(cls, v: str) -> str:
        allowed = ["llm", "passthrough"]
        if v not in allowed:
            raise ValueError(
                f"rag.query_rewrite.implementation must be one of: {', '.join(allowed)}"
            )
        return v

    @field_validator("prompt_path")
    @classmethod
    def path_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("rag.query_rewrite.prompt_path must not be empty")
        return v

    @field_validator("model_id")
    @classmethod
    def model_id_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("rag.query_rewrite.model_id must be null or a non-empty string")
        return v

    @field_validator("max_output_chars")
    @classmethod
    def output_le_input(cls, v: int, info) -> int:
        max_input = info.data.get("max_input_chars")
        if max_input is not None and v > max_input:
            raise ValueError(
                "rag.query_rewrite.max_output_chars must be <= max_input_chars"
            )
        return v


class ThresholdReportConfig(BaseModel):
    model_config = {"extra": "forbid"}
    sweep_start: float = Field(ge=0.0, le=1.0)
    sweep_stop: float = Field(ge=0.0, le=1.0)
    sweep_step: float = Field(gt=0.0, le=1.0)

    @field_validator("sweep_stop")
    @classmethod
    def stop_ge_start(cls, v: float, info) -> float:
        start = info.data.get("sweep_start")
        if start is not None and v < start:
            raise ValueError("rag.threshold_report.sweep_stop must be >= sweep_start")
        return v


class RAGConfig(BaseModel):
    model_config = {"extra": "forbid"}
    docs_path: str
    chunking_mode: str
    chunking: ChunkingConfig
    ignore_prefixes: list[str] = Field(default_factory=lambda: ["_"])
    chunks_path: str
    top_k: int = Field(ge=1, le=20)
    similarity_threshold: float = Field(ge=0.0, le=1.0)
    max_failed_retrievals: int = Field(ge=0)
    max_query_chars: int = Field(ge=50, le=5000)
    no_result_message: str
    query_rewrite: QueryRewriteConfig
    threshold_report: ThresholdReportConfig

    @field_validator("no_result_message")
    @classmethod
    def message_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("rag.no_result_message must not be empty")
        return v

    @field_validator("similarity_threshold")
    @classmethod
    def threshold_in_range(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("rag.similarity_threshold must be between 0 and 1")
        return v

    @field_validator("top_k")
    @classmethod
    def top_k_in_range(cls, v: int) -> int:
        if not (1 <= v <= 20):
            raise ValueError("rag.top_k must be an integer from 1 to 20")
        return v

    @field_validator("max_query_chars")
    @classmethod
    def max_query_chars_in_range(cls, v: int) -> int:
        if not (50 <= v <= 5000):
            raise ValueError("rag.max_query_chars must be an integer from 50 to 5000")
        return v


class SessionConfig(BaseModel):
    model_config = {"extra": "forbid"}
    expiry_minutes: int = Field(ge=1)
    max_failed_verifications: int = Field(ge=0)


class HandoffConfig(BaseModel):
    model_config = {"extra": "forbid"}
    max_repeated_tool_errors: int = Field(ge=1)
    max_failed_retrievals: int = Field(ge=1)
    max_failed_verifications: int = Field(ge=1)


class LoggingConfig(BaseModel):
    model_config = {"extra": "forbid"}
    tool_log_path: str
    debug: bool
    redact_keys: list[str] = Field(min_length=1)
    mask_phone_keep_last: int = Field(ge=1)
    pending_token_prefix_chars: int = Field(ge=1)

    @field_validator("redact_keys")
    @classmethod
    def redact_keys_not_empty(cls, v: list[str]) -> list[str]:
        if not v or any(not key or not key.strip() for key in v):
            raise ValueError(
                "logging.redact_keys must be a non-empty list of non-empty strings"
            )
        return v


class AdapterConfig(BaseModel):
    model_config = {"extra": "forbid"}
    type: str
    host: str
    port: int = Field(ge=1, le=65535)

    @field_validator("type")
    @classmethod
    def known_type(cls, v: str) -> str:
        allowed = ["cli"]
        if v not in allowed:
            raise ValueError(f"adapter.type must be one of: {', '.join(allowed)}")
        return v


class CliAdapterConfig(BaseModel):
    model_config = {"extra": "forbid"}
    # strict so a non-bool like "yes" fails instead of being coerced to True
    allow_otp_command: bool = Field(strict=True)
    prompt_text: str
    agent_label: str

    @field_validator("prompt_text")
    @classmethod
    def prompt_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("adapters.cli.prompt_text must not be empty")
        return v

    @field_validator("agent_label")
    @classmethod
    def label_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("adapters.cli.agent_label must not be empty")
        return v


class WebAdapterConfig(BaseModel):
    model_config = {"extra": "forbid"}
    host: str = "127.0.0.1"
    port: int = Field(ge=1, le=65535)
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    session_idle_seconds: int = Field(ge=60)
    session_max_age_seconds: int = Field(ge=60)
    history_max_events: int = Field(ge=1)
    history_wait_seconds: int = Field(ge=1)
    clear_transcript_on_verification_expiry: bool = Field(strict=True, default=True)
    max_sessions: int = Field(ge=1)
    max_message_chars: int = Field(ge=1)
    allow_dev_otp: bool = Field(strict=True, default=False)
    otp_log_path: str
    error_message: str
    stream_enabled: bool = Field(strict=True)
    heartbeat_seconds: int = Field(ge=1)
    max_stream_seconds: int = Field(ge=1)
    panel_summary_max_chars: int = Field(default=500, ge=1)

    @field_validator("otp_log_path")
    @classmethod
    def otp_path_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("adapters.web.otp_log_path must not be empty")
        return v

    @field_validator("error_message")
    @classmethod
    def error_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("adapters.web.error_message must not be empty")
        return v


class AdaptersConfig(BaseModel):
    model_config = {"extra": "forbid"}
    cli: CliAdapterConfig
    web: WebAdapterConfig


class AcceptanceConfig(BaseModel):
    model_config = {"extra": "forbid"}
    max_attempts_per_scenario: int = Field(ge=1)


class AgentConfig(BaseModel):
    model_config = {"extra": "forbid"}
    system_prompt_path: str
    pidgin_examples_path: str
    max_history_messages: int = Field(ge=1)
    tool_timeout_seconds: int = Field(ge=1)
    bank_api_timeout_seconds: int = Field(ge=1)
    max_tool_calls_per_turn: int = Field(ge=1)
    fallback_message: str
    # Retries for connection/timeout failures from the model endpoint.
    model_retries: int = Field(default=2, ge=0, le=5)
    retry_backoff_seconds: float = Field(default=1.0, ge=0, le=30)
    network_error_message: str = (
        "I can't reach our systems right now. Please try again in a moment."
    )

    @field_validator("system_prompt_path", "pidgin_examples_path")
    @classmethod
    def prompt_path_not_empty(cls, v: str, info) -> str:
        if not v or not v.strip():
            key = info.field_name
            raise ValueError(f"agent.{key} must not be empty")
        return v

    @field_validator("fallback_message")
    @classmethod
    def fallback_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("agent.fallback_message must not be empty")
        return v


class SeedConfig(BaseModel):
    model_config = {"extra": "forbid"}
    random_seed: int = 42
    customer_count: int = Field(ge=1, le=100)
    history_days: int = Field(ge=1)


class StartupConfig(BaseModel):
    model_config = {"extra": "forbid"}
    require_components: bool


class EligibilityConfig(BaseModel):
    model_config = {"extra": "forbid"}
    min_account_age_days: int = Field(ge=0)
    min_avg_monthly_inflow_naira: int = Field(ge=0)
    max_loan_to_inflow_multiple: float = Field(gt=0)
    kyc_tiers_allowed: list[str] = Field(min_length=1)
    requested_amount_max_naira: int = Field(ge=1)


class BankAPIConfig(BaseModel):
    model_config = {"extra": "forbid"}
    db_path: str
    store_type: str = "sqlite"
    gateway: str = "http"
    otp_length: int = Field(ge=4, le=10)
    otp_ttl_seconds: int = Field(ge=60)
    otp_max_attempts: int = Field(ge=1, le=10)
    otp_delivery: str = "mock"
    otp_log_path: str
    phone_pattern: str = r"^\+234[789]\d{9}$"
    pending_action_ttl_seconds: int = Field(ge=60)
    mini_statement_max_n: int = Field(ge=1)
    mini_statement_default_n: int = Field(ge=1)
    eligibility: EligibilityConfig
    handoff_summary_max_chars: int = Field(ge=1)
    handoff_reason_codes: list[str] = Field(min_length=1)

    @field_validator("otp_delivery")
    @classmethod
    def only_mock_supported(cls, v: str) -> str:
        if v != "mock":
            raise ValueError("only 'mock' is supported for otp_delivery at this stage")
        return v

    @field_validator("gateway")
    @classmethod
    def only_http_supported(cls, v: str) -> str:
        if v != "http":
            raise ValueError("only 'http' is supported for bank_api.gateway at this stage")
        return v

    @field_validator("phone_pattern")
    @classmethod
    def phone_pattern_is_valid_regex(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("bank_api.phone_pattern must not be empty")
        try:
            re.compile(v)
        except re.error as exc:
            raise ValueError(f"bank_api.phone_pattern is not a valid regex: {exc}") from exc
        return v

    @field_validator("mini_statement_default_n")
    @classmethod
    def default_le_max(cls, v: int, info) -> int:
        max_n = info.data.get("mini_statement_max_n")
        if max_n is not None and v > max_n:
            raise ValueError("mini_statement_default_n must be <= mini_statement_max_n")
        return v


class Settings(BaseModel):
    model_config = {"extra": "forbid"}
    timezone: str
    llm: LLMConfig
    embeddings: EmbeddingsConfig
    vectorstore: VectorstoreConfig
    rag: RAGConfig
    session: SessionConfig
    handoff: HandoffConfig
    logging: LoggingConfig
    adapter: AdapterConfig
    adapters: AdaptersConfig
    acceptance: AcceptanceConfig
    agent: AgentConfig
    bank_api: BankAPIConfig
    startup: StartupConfig
    seed: SeedConfig

    @field_validator("timezone")
    @classmethod
    def known_timezone(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            raise ValueError(f"unknown IANA timezone: {v!r}")
        return v


# --- tools ---

# The tool contract (ARCHITECTURE.md section 6). tools.yaml keys must be one of
# these; anything else is a typo and fails fast at startup.
KNOWN_TOOLS = frozenset({
    "verify_customer",
    "get_balance",
    "get_mini_statement",
    "get_transaction_status",
    "open_dispute",
    "block_card",
    "check_loan_eligibility",
    "get_loan_status",
    "handoff_to_human",
    "search_policy",
    "confirm_action",
})


class ToolLabels(BaseModel):
    model_config = {"extra": "forbid"}
    running: str
    done: str
    failed: str
    awaiting: Optional[str] = None
    no_action: Optional[str] = None

    @field_validator("running", "done", "failed", "awaiting", "no_action")
    @classmethod
    def label_not_empty(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("must not be empty")
        return v


RECEIPT_KIND_BY_TOOL = {
    "open_dispute": "dispute",
    "block_card": "card_block",
    "handoff_to_human": "handoff",
}
RECEIPT_TEMPLATE_FIELDS = frozenset({"reference", "last4", "summary"})


class ReceiptConfig(BaseModel):
    model_config = {"extra": "forbid"}
    kind: str
    template: str

    @field_validator("kind")
    @classmethod
    def known_kind(cls, v: str) -> str:
        if v not in set(RECEIPT_KIND_BY_TOOL.values()):
            raise ValueError(f"receipt.kind must be one of: {', '.join(sorted(set(RECEIPT_KIND_BY_TOOL.values())))}")
        return v

    @field_validator("template")
    @classmethod
    def valid_template(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("receipt.template must not be empty")
        try:
            fields = {
                field.split(".")[0].split("[")[0]
                for _, field, _, _ in Formatter().parse(v)
                if field is not None
            }
        except ValueError as exc:
            raise ValueError(f"receipt.template is invalid: {exc}") from exc
        unknown = fields - RECEIPT_TEMPLATE_FIELDS
        if unknown:
            raise ValueError(
                "receipt.template may only use "
                f"{', '.join(sorted(RECEIPT_TEMPLATE_FIELDS))}; got {', '.join(sorted(unknown))}"
            )
        return v


class ToolConfig(BaseModel):
    model_config = {"extra": "forbid"}
    enabled: bool
    requires_confirmation: bool
    requires_verified_session: bool
    blocked_on_attachment_turns: bool = False
    description: str
    labels: Optional[ToolLabels] = None
    receipt: Optional[ReceiptConfig] = None

    @field_validator("description")
    @classmethod
    def description_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("description must not be empty")
        return v

    @model_validator(mode="after")
    def labels_complete_for_enabled_tool(self):
        if not self.enabled:
            return self
        if self.labels is None:
            raise ValueError(
                "labels are required for an enabled tool "
                "(running, done, failed, plus awaiting/no_action for confirmation tools)"
            )
        missing = [key for key in ("running", "done", "failed") if not getattr(self.labels, key)]
        if self.requires_confirmation:
            for key in ("awaiting", "no_action"):
                if not getattr(self.labels, key):
                    missing.append(key)
        if missing:
            raise ValueError(f"labels missing: {', '.join(missing)}")
        return self


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
        if key not in KNOWN_TOOLS:
            errors.append(f"tools.yaml -> {key}: unknown tool name")
            continue
        try:
            tools[key] = ToolConfig.model_validate(value)
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(p) for p in err.get("loc", ()))
                errors.append(f"tools.yaml -> {key}.{loc}: {err.get('msg', 'invalid value')}")
            continue
        receipt = tools[key].receipt
        expected_kind = RECEIPT_KIND_BY_TOOL.get(key)
        if receipt and receipt.kind != expected_kind:
            errors.append(
                f"tools.yaml -> {key}.receipt.kind: must be {expected_kind!r} for this tool"
            )

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
