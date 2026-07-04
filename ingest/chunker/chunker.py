"""Chunking logic — pure, no I/O.

Input: a Stage 1 document dict (with `pages`, `full_text`, `metadata`).
Output: an ordered list of chunk dicts ready for JSON serialization.

Algorithm:
  1. Build a flat token stream with per-token page-number tags.
  2. Walk the stream with token windows of (max - overlap) step.
  3. For each window, reconstruct the text, detect the heading
     (if any '#' marker is present in the window), and record
     the page range (min/max page_number touched).
  4. chunk_id = sha256(document_id + chunk_index + normalized_text).
"""
from __future__ import annotations

import hashlib
import re
from typing import Iterable

from ingest.chunker.config import ChunkConfig
from ingest.chunker.normalizer import normalize
from ingest.chunker.tokenizer import (
    count_tokens,
    split_into_token_windows,
    tokenize,
)

_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def _make_chunk_id(document_id: str, chunk_index: int, text: str) -> str:
    h = hashlib.sha256()
    h.update(document_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(str(chunk_index).encode("ascii"))
    h.update(b"\x00")
    h.update(text.encode("utf-8"))
    return h.hexdigest()[:32]


def _page_offsets_from_pages(pages: list[dict]) -> list[int]:
    """Return a list of cumulative token offsets per page (1-indexed by
    adding 1 element at index 0). offsets[i] = first token index of page i+1.
    """
    offsets = [0]
    for p in pages:
        toks = tokenize(p.get("text", "") or "")
        offsets.append(offsets[-1] + len(toks))
    return offsets


def _find_page(offsets: list[int], token_idx: int) -> int:
    """Binary-search the page number for an absolute token index."""
    # offsets: [0, n1, n1+n2, ...]
    lo, hi = 0, len(offsets) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if offsets[mid] <= token_idx:
            lo = mid
        else:
            hi = mid - 1
    return lo  # page number (1-indexed, since offsets[0]=0 corresponds to page 1)


def _detect_heading(text: str) -> str | None:
    """Return the heading string (without '#' markers) if a markdown-style
    heading is present in the window. Prefers the FIRST heading found.
    """
    for line in text.splitlines():
        m = _HEADING.match(line)
        if m:
            return m.group(2).strip()
    return None


def chunk_document(doc: dict, cfg: ChunkConfig) -> Iterable[dict]:
    """Yield chunk dicts for one Stage 1 document."""
    document_id = doc.get("document_id", "")
    pages = doc.get("pages") or []
    full_text = doc.get("full_text") or ""

    # Normalize once at the document level.
    norm_full = normalize(
        full_text,
        do_strip_ocr=cfg.strip_ocr_artifacts,
        do_fix_hyphenation=cfg.fix_hyphenation,
        do_collapse_ws=cfg.collapse_whitespace,
    )
    if not norm_full:
        return

    # Build page-token offsets against the NORMALIZED text, per page.
    # This means we re-tokenize per page from the normalized version.
    norm_pages_text: list[str] = [
        normalize(
            (p.get("text") or ""),
            do_strip_ocr=cfg.strip_ocr_artifacts,
            do_fix_hyphenation=cfg.fix_hyphenation,
            do_collapse_ws=cfg.collapse_whitespace,
        )
        for p in pages
    ]
    # Re-split into a flat token stream aligned with the per-page boundaries.
    page_token_counts: list[int] = [count_tokens(t) for t in norm_pages_text]
    offsets = [0]
    for n in page_token_counts:
        offsets.append(offsets[-1] + n)

    flat_tokens: list[str] = tokenize(norm_full)
    total_tokens = len(flat_tokens)
    if total_tokens == 0:
        return

    windows = split_into_token_windows(
        flat_tokens,
        max_tokens=cfg.chunk_max_tokens,
        overlap=cfg.chunk_overlap_tokens,
    )

    source_meta = doc.get("metadata") or {}

    for chunk_index, (start, end) in enumerate(windows):
        chunk_text = " ".join(flat_tokens[start:end])

        page_start = _find_page(offsets, start)
        page_end = _find_page(offsets, max(end - 1, start))
        # Convert offsets to 1-indexed page numbers.
        page_range = [page_start + 1, page_end + 1]

        heading = _detect_heading(chunk_text)
        token_count = end - start

        chunk_id = _make_chunk_id(document_id, chunk_index, chunk_text)

        yield {
            "document_id": document_id,
            "chunk_id": chunk_id,
            "chunk_index": chunk_index,
            "text": chunk_text,
            "page_range": page_range,
            "metadata": {
                "token_count": token_count,
                "heading": heading,
                "filename": source_meta.get("filename", ""),
                "file_type": source_meta.get("file_extension", "").lstrip("."),
                "sha256": source_meta.get("sha256", ""),
                "is_scanned": source_meta.get("is_scanned", False),
                "ocr_used": source_meta.get("ocr_used", False),
            },
        }