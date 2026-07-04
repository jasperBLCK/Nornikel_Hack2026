"""Recursive folder scanner — yields file paths with metadata."""
from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ScannedFile:
    path: Path
    relative_path: str
    extension: str
    size_bytes: int
    mime_type: str


def scan_folder(root: Path, allowed_extensions: frozenset[str]) -> list[ScannedFile]:
    """Walk the input tree once. Sorting is deliberate — gives deterministic
    ordering so re-runs produce the same output sequence (useful for diffing).
    """
    if not root.exists():
        raise FileNotFoundError(f"Input root not found: {root}")

    results: list[ScannedFile] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext not in allowed_extensions:
            continue
        try:
            size = p.stat().st_size
        except OSError:
            continue
        mime, _ = mimetypes.guess_type(str(p))
        results.append(
            ScannedFile(
                path=p,
                relative_path=str(p.relative_to(root)),
                extension=ext,
                size_bytes=size,
                mime_type=mime or "",
            )
        )
    return results