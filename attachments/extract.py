from __future__ import annotations

from typing import Optional

from attachments.config import AttachmentsConfig, load_attachments_config
from attachments.extractors.base import NeedsVision, get_extractor
from attachments.extractors.vision import extract_with_vision
from attachments.models import ExtractedDocument, ValidatedFile
from attachments.vision.base import VisionExtractor, get_vision_extractor

VISION_KINDS = frozenset({"png", "jpeg"})


def extract_document(
    file: ValidatedFile,
    profile_name: str,
    config: Optional[AttachmentsConfig] = None,
    vision_extractor: Optional[VisionExtractor] = None,
) -> ExtractedDocument:
    config = config or load_attachments_config()
    profile = config.profile(profile_name)
    if vision_extractor is None:
        vision_extractor = get_vision_extractor(config.vision)

    if file.kind in VISION_KINDS:
        return extract_with_vision(file, profile, config.vision, vision_extractor)
    try:
        return get_extractor(file.kind).extract(file, profile)
    except NeedsVision:
        return extract_with_vision(file, profile, config.vision, vision_extractor)
