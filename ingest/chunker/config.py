"""Runtime configuration for the chunking stage."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChunkConfig:
    # IO
    input_ndjson: Path          # Stage 1 output (documents.ndjson)
    output_ndjson: Path         # Stage 2 output (chunks.ndjson)
    manifest_db: Path

    # Chunk size (in whitespace tokens — see tokenizer.py)
    chunk_min_tokens: int = 800
    chunk_max_tokens: int = 1500
    chunk_overlap_tokens: int = 200

    # Heading layer
    heading_pattern: str = r"^(#{1,6})\s+(.+)$"

    # Workers
    workers: int = 1  # multiprocessing-friendly; default 1 to keep RAM low

    # Normalization
    fix_hyphenation: bool = True
    collapse_whitespace: bool = True
    strip_ocr_artifacts: bool = True

    def validate(self) -> None:
        if self.chunk_min_tokens <= 0:
            raise ValueError("chunk_min_tokens must be > 0")
        if self.chunk_max_tokens < self.chunk_min_tokens:
            raise ValueError("chunk_max_tokens must be >= chunk_min_tokens")
        if self.chunk_overlap_tokens < 0:
            raise ValueError("chunk_overlap_tokens must be >= 0")
        if self.chunk_overlap_tokens >= self.chunk_min_tokens:
            raise ValueError("chunk_overlap_tokens must be < chunk_min_tokens")


def default_config(input_ndjson: Path, output_ndjson: Path, **overrides) -> ChunkConfig:
    cfg = ChunkConfig(
        input_ndjson=Path(input_ndjson),
        output_ndjson=Path(output_ndjson),
        manifest_db=Path(output_ndjson).parent / "_chunks_manifest.sqlite",
    )
    out = ChunkConfig(**{**cfg.__dict__, **overrides})
    out.validate()
    out.output_ndjson.parent.mkdir(parents=True, exist_ok=True)
    out.manifest_db.parent.mkdir(parents=True, exist_ok=True)
    return out