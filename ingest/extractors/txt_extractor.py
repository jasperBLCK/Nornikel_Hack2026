"""Plain-text extractor with robust encoding detection (Cyrillic-safe)."""
from __future__ import annotations

from pathlib import Path

from ingest.extractors.base import Extractor
from ingest.structures import Page

# Order matters: try Russian/Cyrillic-aware encodings first.
_CANDIDATE_ENCODINGS = (
    "utf-8",
    "utf-8-sig",
    "cp1251",      # Windows-1251 (Russian)
    "koi8-r",
    "iso-8859-5",
    "cp866",
    "mac_cyrillic",
    "latin-1",     # last-resort fallback (no decode error possible)
)


def _read_text(path: Path) -> str:
    raw = path.read_bytes()
    # BOM check shortcut
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")

    for enc in _CANDIDATE_ENCODINGS:
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    # Last resort — never fail, just replace.
    return raw.decode("utf-8", errors="replace")


class TxtExtractor(Extractor):
    def extract(self, path: Path) -> list[Page]:
        try:
            text = _read_text(path)
        except Exception as e:
            return [Page(page_number=1, text="", metadata_note=f"txt_read_failed: {e}")]
        # Normalize line endings, strip trailing whitespace per line.
        text = "\n".join(line.rstrip() for line in text.splitlines())
        return [Page(page_number=1, text=text)]