"""Stage 3 configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class ExtractorConfig:
    # IO
    input_ndjson: Path          # Stage 2 chunks.ndjson
    output_ndjson: Path         # Stage 3 extracted.ndjson
    rejected_ndjson: Path       # Chunks that failed validation
    manifest_db: Path

    # Model
    model: str = "claude-sonnet-5"
    api_key_env: str = "ANTHROPIC_API_KEY"
    api_base: str = "https://api.anthropic.com"
    anthropic_version: str = "2023-06-01"
    max_input_tokens: int = 8000
    max_output_tokens: int = 4000
    temperature: float = 0.0   # deterministic
    request_timeout_sec: float = 120.0
    max_retries: int = 5

    # Concurrency
    workers: int = 4            # processes
    async_concurrency: int = 8  # in-flight requests per process

    # Grounding judge (separate small call)
    enable_grounding_judge: bool = True
    grounding_judge_model: str | None = None  # defaults to `model`
    grounding_min_score: float = 0.6          # drop below this
    grounding_max_calls_per_chunk: int = 1    # never retry per chunk

    # Batching
    batch_size: int = 32        # chunks per worker task

    # IO size
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not os.environ.get(self.api_key_env):
            raise EnvironmentError(
                f"API key not set. Export {self.api_key_env} before running."
            )
        if self.grounding_judge_model is None:
            object.__setattr__(self, "grounding_judge_model", self.model)
        for p in (self.input_ndjson, self.output_ndjson, self.rejected_ndjson):
            Path(p).parent.mkdir(parents=True, exist_ok=True)


def default_config(input_ndjson: Path, output_ndjson: Path, **overrides) -> ExtractorConfig:
    cfg = ExtractorConfig(
        input_ndjson=Path(input_ndjson),
        output_ndjson=Path(output_ndjson),
        rejected_ndjson=Path(output_ndjson).with_suffix(".rejected.ndjson"),
        manifest_db=Path(output_ndjson).parent / "_extractor_manifest.sqlite",
    )
    return ExtractorConfig(**{**cfg.__dict__, **overrides})