"""Scanned-PDF detection heuristics.

Strategy: sample the first N pages, compute the average extracted character
density (chars per page). If it's below a configurable threshold, the PDF
is treated as image-only and routed to OCR. We deliberately avoid
importing PyMuPDF/pdfplumber here — the detector is pure-Python over the
already-extracted page text supplied by the PDF extractor.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScanVerdict:
    is_scanned: bool
    avg_chars_per_page: float
    sampled_pages: int
    threshold: int


def detect_scanned(
    page_texts: list[str],
    threshold: int = 40,
    sample_pages: int = 5,
) -> ScanVerdict:
    """page_texts: list of strings, one per page (already extracted via
    text-layer extraction). Empty list → treated as scanned.
    """
    if not page_texts:
        return ScanVerdict(True, 0.0, 0, threshold)

    sample = page_texts[: max(1, sample_pages)]
    total_chars = sum(len((t or "").strip()) for t in sample)
    avg = total_chars / len(sample)
    return ScanVerdict(
        is_scanned=avg < threshold,
        avg_chars_per_page=avg,
        sampled_pages=len(sample),
        threshold=threshold,
    )