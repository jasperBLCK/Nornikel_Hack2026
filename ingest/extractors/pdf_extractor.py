"""PDF extractor using PyMuPDF (fitz).

Strategy:
1. Try text-layer extraction page by page.
2. If the average char density is below threshold → mark scanned.
3. For mixed PDFs (some pages have text, some are images), we return the
   text-layer pages as-is and flag the document. Per-page OCR re-routing
   is left to a downstream stage if needed — for now we keep the contract
   simple: one extract() = one document pass.
"""
from __future__ import annotations

import logging
from pathlib import Path

import fitz  # PyMuPDF

from ingest.extractors.base import Extractor
from ingest.structures import Page

logger = logging.getLogger(__name__)


class PdfExtractor(Extractor):
    """Pure text-layer extraction. OCR fallback is handled by the pipeline."""

    def __init__(self, scanned_threshold: int = 40, sample_pages: int = 5) -> None:
        self.scanned_threshold = scanned_threshold
        self.sample_pages = sample_pages

    def extract(self, path: Path) -> list[Page]:
        pages: list[Page] = []
        try:
            doc = fitz.open(str(path))
        except Exception as e:
            logger.warning("PDF open failed: %s — %s", path, e)
            return [Page(page_number=1, text="")]

        try:
            for i, page in enumerate(doc, start=1):
                try:
                    text = page.get_text("text") or ""
                except Exception as e:
                    logger.warning("PDF page read failed: %s p%d — %s", path, i, e)
                    text = ""
                pages.append(Page(page_number=i, text=text))
        finally:
            doc.close()

        return pages

    def looks_scanned(self, pages: list[Page]) -> bool:
        sample = [p.text for p in pages[: max(1, self.sample_pages)]]
        if not sample:
            return True
        avg = sum(len((t or "").strip()) for t in sample) / len(sample)
        return avg < self.scanned_threshold