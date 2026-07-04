"""Per-file processing logic (extraction + OCR fallback + assembly).

This module is the *unit of work*. It is intentionally pure — no I/O
orchestration, no shared state — so it can run inside a multiprocessing
worker without surprises (no global locks, no module-level SQLite).
"""
from __future__ import annotations

import logging
from pathlib import Path

from ingest.config import IngestConfig
from ingest.detectors import detect_scanned
from ingest.extractors.base import Extractor
from ingest.extractors.doc_extractor import DocExtractor
from ingest.extractors.docx_extractor import DocxExtractor
from ingest.extractors.ocr_extractor import OcrExtractor, OcrUnavailable
from ingest.extractors.pdf_extractor import PdfExtractor
from ingest.extractors.txt_extractor import TxtExtractor
from ingest.extractors.xlsx_extractor import XlsxExtractor
from ingest.hashing import make_document_id, sha256_file
from ingest.structures import Document, DocumentMetadata, Page

logger = logging.getLogger(__name__)


def _build_extractor(ext: str, cfg: IngestConfig) -> Extractor:
    if ext == ".pdf":
        return PdfExtractor(
            scanned_threshold=cfg.scanned_pdf_char_threshold,
            sample_pages=cfg.scanned_pdf_sample_pages,
        )
    if ext == ".docx":
        return DocxExtractor()
    if ext == ".doc":
        return DocExtractor()
    if ext == ".txt":
        return TxtExtractor()
    if ext in (".xls", ".xlsx"):
        return XlsxExtractor()
    raise ValueError(f"Unsupported extension: {ext}")


def process_file(
    path: Path,
    rel_path: str,
    size_bytes: int,
    mime_type: str,
    cfg: IngestConfig,
) -> Document:
    """Extract text from a single file. Returns a fully populated Document.
    Never raises — errors are recorded in DocumentMetadata.error.
    """
    ext = path.suffix.lower()
    file_type = ext.lstrip(".")

    pages: list[Page] = []
    ocr_used = False
    is_scanned = False
    error: str | None = None

    try:
        sha = sha256_file(path)
        doc_id = make_document_id(sha)

        extractor = _build_extractor(ext, cfg)
        pages = extractor.extract(path)

        # OCR fallback for PDFs only.
        if ext == ".pdf" and isinstance(extractor, PdfExtractor):
            verdict = detect_scanned(
                [p.text for p in pages],
                threshold=cfg.scanned_pdf_char_threshold,
                sample_pages=cfg.scanned_pdf_sample_pages,
            )
            is_scanned = verdict.is_scanned
            if is_scanned and cfg.enable_ocr:
                try:
                    ocr = OcrExtractor(
                        language=cfg.ocr_language,
                        dpi=cfg.ocr_dpi,
                        page_timeout_sec=cfg.ocr_page_timeout_sec,
                    )
                    pages = ocr.extract(path)
                    ocr_used = True
                except OcrUnavailable as e:
                    error = f"ocr_unavailable: {e}"
                except Exception as e:
                    error = f"ocr_failed: {e}"
    except Exception as e:
        logger.exception("process_file failed: %s", path)
        error = f"{type(e).__name__}: {e}"
        # We still try to provide a stable hash so the manifest entry is unique.
        try:
            sha = sha256_file(path)
            doc_id = make_document_id(sha)
        except Exception:
            sha = ""
            doc_id = ""

    full_text = "\n\n".join(p.text for p in pages if p.text)

    metadata = DocumentMetadata(
        filename=path.name,
        relative_path=rel_path,
        file_size_bytes=size_bytes,
        file_extension=ext,
        page_count=len(pages),
        is_scanned=is_scanned,
        ocr_used=ocr_used,
        sha256=sha,
        mime_type=mime_type,
        error=error,
    )

    return Document(
        document_id=doc_id,
        filename=path.name,
        file_type=file_type,
        pages=pages,
        full_text=full_text,
        metadata=metadata,
    )