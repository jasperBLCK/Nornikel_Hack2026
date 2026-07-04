"""Per-chunk extraction core.

One call to the model produces raw JSON; we then:
  1. validate with Pydantic (shape),
  2. call the grounding judge (faithfulness),
  3. attach metadata (model, score) and return.
"""
from __future__ import annotations

import logging

from ingest.extractor.config import ExtractorConfig
from ingest.extractor.llm_client import AnthropicClient
from ingest.extractor.prompts import (
    SYSTEM_PROMPT,
    build_extraction_messages,
)
from ingest.extractor.schema import ExtractionRecord
from ingest.extractor.validator import judge_grounding, validate_schema

logger = logging.getLogger(__name__)


async def extract_chunk(
    client: AnthropicClient,
    cfg: ExtractorConfig,
    document_id: str,
    chunk_id: str,
    text: str,
) -> tuple[ExtractionRecord | None, dict | None, str | None]:
    """Returns (record, raw_extracted, rejection_reason).

    On success: record is set, raw_extracted is set, rejection_reason is None.
    On failure: record is None, raw_extracted is the model's output (if any),
                 rejection_reason is a short string.
    """
    messages = build_extraction_messages(document_id, chunk_id, text)
    response = await client.create_message(
        model=cfg.model,
        system=SYSTEM_PROMPT,
        messages=messages,
    )
    raw_text = AnthropicClient.extract_text(response)
    if not raw_text:
        return None, None, "empty_model_output"

    try:
        raw = AnthropicClient.parse_json_strict(raw_text)
    except Exception as e:
        return None, {"raw_text": raw_text}, f"json_parse_failed: {e}"

    # Ensure document_id / chunk_id are the ones we asked for, regardless
    # of what the model echoed.
    raw["document_id"] = document_id
    raw["chunk_id"] = chunk_id

    try:
        record = validate_schema(raw)
    except Exception as e:
        return None, raw, f"schema_invalid: {e}"

    # Grounding check
    verdict = await judge_grounding(client, cfg, text, raw)
    if verdict.action == "reject":
        return None, raw, f"grounding_rejected: score={verdict.score:.2f}"

    record.model_used = cfg.model
    record.grounding_score = verdict.score
    return record, raw, None