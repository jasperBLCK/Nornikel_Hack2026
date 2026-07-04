"""OCR extractor — Tesseract fallback for scanned PDFs.

Renders each page to a high-DPI image and runs Tesseract. Cyrillic is
supported via the 'rus' language code (configured globally in
IngestConfig.ocr_language, default 'eng+rus').
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

import fitz  # PyMuPDF for rendering

from ingest.extractors.base import Extractor
from ingest.structures import Page

logger = logging.getLogger(__name__)


class OcrUnavailable(RuntimeError):
    """Raised when Tesseract binary is missing."""


class OcrExtractor(Extractor):
    """Renders PDF pages to PNGs, then shells out to Tesseract."""

    def __init__(
        self,
        language: str = "eng+rus",
        dpi: int = 300,
        page_timeout_sec: int = 120,
    ) -> None:
        if shutil.which("tesseract") is None:
            raise OcrUnavailable(
                "Tesseract binary not found on PATH. Install tesseract-ocr "
                "and the 'rus' language pack."
            )
        self.language = language
        self.dpi = dpi
        self.page_timeout_sec = page_timeout_sec

    def extract(self, path: Path) -> list[Page]:
        pages: list[Page] = []
        try:
            doc = fitz.open(str(path))
        except Exception as e:
            logger.error("OCR: cannot open PDF %s — %s", path, e)
            return [Page(page_number=1, text="", is_scanned=True)]

        zoom = self.dpi / 72.0
        matrix = fitz.Matrix(zoom, zoom)

        try:
            with tempfile.TemporaryDirectory(prefix="hydrax_ocr_") as tmpdir:
                tmp = Path(tmpdir)
                for i, page in enumerate(doc, start=1):
                    try:
                        pix = page.get_pixmap(matrix=matrix, alpha=False)
                        img_path = tmp / f"p{i:04d}.png"
                        pix.save(str(img_path))

                        result = subprocess.run(
                            [
                                "tesseract",
                                str(img_path),
                                "-",
                                "-l", self.language,
                                "--psm", "6",
                            ],
                            capture_output=True,
                            text=True,
                            timeout=self.page_timeout_sec,
                        )
                        text = result.stdout if result.returncode == 0 else ""
                        pages.append(Page(page_number=i, text=text, is_scanned=True))
                    except subprocess.TimeoutExpired:
                        logger.warning("OCR timeout: %s p%d", path, i)
                        pages.append(Page(page_number=i, text="", is_scanned=True))
                    except Exception as e:
                        logger.warning("OCR page error: %s p%d — %s", path, i, e)
                        pages.append(Page(page_number=i, text="", is_scanned=True))
        finally:
            doc.close()

        return pages