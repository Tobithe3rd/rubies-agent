from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Optional

from attachments.config import AttachmentsConfig, ChatFormatConfig, load_attachments_config
from attachments.models import Block, ExtractedDocument

logger = logging.getLogger(__name__)


@dataclass
class ChatMessage:
    model_text: str
    display_text: str


def _boundary(documents: list[ExtractedDocument], size: int) -> str:
    lines = [doc.name for doc in documents]
    for doc in documents:
        lines.extend(doc.warnings)
        lines.extend(block.text for block in doc.blocks)
    corpus = "\n".join(lines)
    while True:
        token = secrets.token_hex(size)
        if token not in corpus:
            return token


def _fit_blocks(blocks: list[Block], fmt: ChatFormatConfig, remaining: int):
    """Render blocks in order without crossing the remaining budget."""
    lines: list[str] = []
    used = 0
    page = None
    truncated = False
    for block in blocks:
        piece = []
        if block.page is not None and block.page != page:
            piece.append(fmt.page_marker.format(n=block.page))
            page = block.page
        piece.append(block.text)
        text = "\n".join(piece)
        added = len(text) + (1 if lines else 0)
        if used + added > remaining:
            truncated = True
            break
        lines.extend(piece)
        used += added
    return lines, used, truncated


def build_chat_message(
    user_text: str,
    documents: list[ExtractedDocument],
    config: Optional[AttachmentsConfig] = None,
    profile_name: str = "chat_attachment",
) -> ChatMessage:
    if not user_text.strip():
        raise ValueError("user_text must not be empty")
    config = config or load_attachments_config()
    profile = config.profile(profile_name)
    fmt = config.chat_format
    boundary = _boundary(documents, fmt.boundary_bytes)

    budget = profile.max_total_chars
    used = 0
    truncated_any = False
    exhausted = False
    model_parts = [user_text, "", fmt.header]
    display_parts = [user_text, ""]

    for doc in documents:
        label = f"{doc.name} ({doc.kind}, {doc.method})"
        model_parts.append(fmt.item_open.format(boundary=boundary, label=label))
        notes = list(doc.warnings)
        remaining = budget - used
        if exhausted or remaining <= 0:
            model_parts.append(fmt.omitted_note)
            truncated_any = True
        else:
            lines, added, cut = _fit_blocks(doc.blocks, fmt, remaining)
            used += added
            if lines:
                model_parts.append("\n".join(lines))
            if cut:
                notes.append(fmt.truncated_note)
                truncated_any = True
                exhausted = True
            if doc.truncated and not any("truncat" in note.lower() for note in notes):
                notes.append(fmt.truncated_note)
            if notes:
                model_parts.append(f"{fmt.notes_label}: " + "; ".join(notes))
        model_parts.append(fmt.item_close.format(boundary=boundary, label=label))
        display_parts.append(f"[Attached: {doc.name} ({doc.kind})]")

    model_text = "\n".join(model_parts)
    display_text = "\n".join(display_parts)
    logger.info(
        "attachment_chat_message document_count=%d total_chars=%d truncated=%s",
        len(documents), used, truncated_any,
    )
    return ChatMessage(model_text=model_text, display_text=display_text)
