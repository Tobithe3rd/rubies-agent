from __future__ import annotations

import codecs
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from core.config import ConfigError

# Canonical kinds. Filename aliases (jpg) are mapped in validate.py.
KNOWN_ATTACHMENT_KINDS = frozenset({"png", "jpeg", "pdf", "docx", "xlsx", "txt", "csv"})


class AttachmentProfile(BaseModel):
    model_config = {"extra": "forbid"}
    max_files_per_message: int = Field(ge=1)
    max_file_bytes: int = Field(ge=1)
    max_total_bytes: int = Field(ge=1)
    allowed_types: list[str] = Field(min_length=1)
    max_image_pixels: int = Field(ge=1)
    max_image_side: int = Field(ge=1)
    text_must_decode: str
    max_chars_per_document: int = Field(ge=1)
    max_total_chars: int = Field(ge=1)
    max_request_bytes: int = Field(ge=1)
    require_verified_session: bool
    max_pdf_pages: int = Field(ge=1)
    pdf_min_chars_per_page: int = Field(ge=0)
    max_sheets: int = Field(ge=1)
    max_rows_per_sheet: int = Field(ge=1)
    max_cols: int = Field(ge=1)
    max_cell_chars: int = Field(ge=1)
    zip_max_uncompressed_bytes: int = Field(ge=1)
    zip_max_entries: int = Field(ge=1)
    zip_max_ratio: int = Field(ge=1)
    max_vision_pdf_pages: int = Field(ge=1)

    @field_validator("allowed_types")
    @classmethod
    def known_types(cls, v: list[str]) -> list[str]:
        unknown = sorted(set(v) - KNOWN_ATTACHMENT_KINDS)
        if unknown:
            raise ValueError(
                "allowed_types may only contain "
                f"{', '.join(sorted(KNOWN_ATTACHMENT_KINDS))}; got {', '.join(unknown)}"
            )
        if len(set(v)) != len(v):
            raise ValueError("allowed_types must not contain duplicates")
        return v

    @field_validator("text_must_decode")
    @classmethod
    def known_encoding(cls, v: str) -> str:
        try:
            codecs.lookup(v)
        except LookupError as exc:
            raise ValueError(f"unknown text encoding: {v!r}") from exc
        return v

    @model_validator(mode="after")
    def total_covers_one_file(self):
        if self.max_total_bytes < self.max_file_bytes:
            raise ValueError("max_total_bytes must be >= max_file_bytes")
        if self.max_request_bytes < self.max_total_bytes:
            raise ValueError("max_request_bytes must be >= max_total_bytes")
        return self


class VisionConfig(BaseModel):
    model_config = {"extra": "forbid"}
    provider: str
    model_id: str
    max_output_tokens: int = Field(ge=1)
    temperature: float = Field(ge=0.0, le=1.0)
    connect_timeout_seconds: float = Field(gt=0)
    read_timeout_seconds: float = Field(gt=0)
    max_retries: int = Field(ge=0)
    prompt_path: str
    warning_text: str

    @field_validator("provider")
    @classmethod
    def known_provider(cls, v: str) -> str:
        allowed = ["bedrock", "mock"]
        if v not in allowed:
            raise ValueError(f"vision.provider must be one of: {', '.join(allowed)}")
        return v

    @field_validator("model_id", "prompt_path", "warning_text")
    @classmethod
    def not_empty(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"vision.{info.field_name} must not be empty")
        return v


class ChatFormatConfig(BaseModel):
    model_config = {"extra": "forbid"}
    header: str
    item_open: str
    item_close: str
    notes_label: str
    page_marker: str
    truncated_note: str
    omitted_note: str
    boundary_bytes: int = Field(ge=1, le=64)

    @field_validator("header", "item_open", "item_close", "notes_label", "page_marker",
                     "truncated_note", "omitted_note")
    @classmethod
    def not_empty(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"chat_format.{info.field_name} must not be empty")
        return v

    @field_validator("item_open", "item_close")
    @classmethod
    def has_item_placeholders(cls, v: str, info) -> str:
        if "{boundary}" not in v or "{label}" not in v:
            raise ValueError(f"chat_format.{info.field_name} must contain {{boundary}} and {{label}}")
        return v

    @field_validator("page_marker")
    @classmethod
    def has_page_placeholder(cls, v: str) -> str:
        if "{n}" not in v:
            raise ValueError("chat_format.page_marker must contain {n}")
        return v


class WebUploadConfig(BaseModel):
    model_config = {"extra": "forbid"}
    reading_label: str
    not_verified_message: str

    @field_validator("reading_label", "not_verified_message")
    @classmethod
    def not_empty(cls, v: str, info) -> str:
        if not v or not v.strip():
            raise ValueError(f"web_upload.{info.field_name} must not be empty")
        return v


class AttachmentsConfig(BaseModel):
    model_config = {"extra": "forbid"}
    enabled: bool
    vision: VisionConfig
    chat_format: ChatFormatConfig
    web_upload: WebUploadConfig
    profiles: dict[str, AttachmentProfile] = Field(min_length=1)

    def profile(self, name: str) -> AttachmentProfile:
        try:
            return self.profiles[name]
        except KeyError:
            raise ConfigError(f"unknown attachment profile: {name!r}") from None


def load_attachments_config(config_dir: str = "config", path: Optional[Path] = None) -> AttachmentsConfig:
    source = Path(path) if path is not None else Path(config_dir) / "attachments.yaml"
    try:
        raw = yaml.safe_load(source.read_text()) or {}
    except Exception as exc:
        raise ConfigError(f"Failed to read YAML file: {source}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ConfigError(
            f"attachments.yaml must contain a mapping; got {type(raw).__name__}"
        )
    try:
        return AttachmentsConfig.model_validate(raw)
    except ValidationError as exc:
        errors = []
        for err in exc.errors():
            loc = ".".join(str(p) for p in err.get("loc", ()))
            errors.append(f"attachments.yaml -> {loc}: {err.get('msg', 'invalid value')}")
        raise ConfigError("Config validation failed: " + "; ".join(errors)) from exc
