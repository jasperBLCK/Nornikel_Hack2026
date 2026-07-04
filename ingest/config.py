"""Runtime configuration for the ingestion pipeline."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class IngestConfig:
    # IO
    input_root: Path
    output_dir: Path

    # Worker pool
    workers: int = max(1, (os.cpu_count() or 4) - 1)
    queue_size: int = 256

    # File types accepted
    allowed_extensions: frozenset[str] = frozenset(
        {".pdf", ".docx", ".doc", ".txt", ".xls", ".xlsx"}
    )

    # Scanning heuristics
    scanned_pdf_char_threshold: int = 40
    """Below this avg chars per page, the page is considered image-only."""

    scanned_pdf_sample_pages: int = 5
    """How many pages to sample when deciding if a PDF is scanned."""

    # OCR
    ocr_language: str = "eng+rus"
    ocr_dpi: int = 300
    ocr_page_timeout_sec: int = 120
    enable_ocr: bool = True

    # Output
    write_per_doc_json: bool = False
    """If False → NDJSON. If True → one .json per doc (slower at scale)."""

    manifest_db: Optional[Path] = None
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        object.__setattr__(self, "input_root", Path(self.input_root).resolve())
        object.__setattr__(self, "output_dir", Path(self.output_dir).resolve())
        if self.manifest_db is None:
            object.__setattr__(
                self,
                "manifest_db",
                self.output_dir / "_manifest.sqlite",
            )
        else:
            object.__setattr__(self, "manifest_db", Path(self.manifest_db))
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_db.parent.mkdir(parents=True, exist_ok=True)


def default_config(input_root: str | Path, output_dir: str | Path, **overrides) -> IngestConfig:
    cfg = IngestConfig(input_root=Path(input_root), output_dir=Path(output_dir))
    return IngestConfig(**{**cfg.__dict__, **overrides})