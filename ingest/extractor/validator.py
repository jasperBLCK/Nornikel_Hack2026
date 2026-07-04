"""Validation: Pydantic schema + grounding-judge LLM call.

Schema validation guarantees shape; grounding judge guarantees faithfulness
to the source text. Both are required for "production-grade" as the user
specified.
"""
from __future__ import annotations

import logging
from typing import Any

from pydantic import ValidationError

from ingest.extractor.config import ExtractorConfig
from ingest.extractor.llm_client import AnthropicClient
from ingest.extractor.prompts import (
    GROUNDING_SYSTEM_PROMPT,
    build_grounding_messages,
)
from ingest.extractor.schema import ExtractionRecord, GroundingVerdict

logger = logging.getLogger(__name__)


def validate_schema(raw: dict) -> ExtractionRecord:
    """Pydantic strict validation. Raises ValidationError on bad shape."""
    return ExtractionRecord.model_validate(raw)


async def judge_grounding(
    client: AnthropicClient,
    cfg: ExtractorConfig,
    chunk_text: str,
    extracted: dict,
) -> GroundingVerdict:
    """Call a second LLM to score how much of `extracted` is grounded in
    `chunk_text`. Returns a GroundingVerdict.

    If grounding is disabled, returns accept(1.0) — the caller treats this
    as a pass-through.
    """
    if not cfg.enable_grounding_judge:
        return GroundingVerdict(score=1.0, rationale="judge_disabled", action="accept")

    messages = build_grounding_messages(chunk_text, extracted)
    response = await client.create_message(
        model=cfg.grounding_judge_model or cfg.model,
        system=GROUNDING_SYSTEM_PROMPT,
        messages=messages,
        max_tokens=500,
        temperature=0.0,
    )
    text = AnthropicClient.extract_text(response)
    obj = AnthropicClient.parse_json_strict(text)
    return GroundingVerdict.model_validate(obj)