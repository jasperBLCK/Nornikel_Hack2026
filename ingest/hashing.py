"""Deterministic, content-addressed document IDs."""
from __future__ import annotations

import hashlib
from pathlib import Path


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    """Streamed SHA-256 — never loads the file fully into memory."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            h.update(chunk)
    return h.hexdigest()


def make_document_id(sha256: str) -> str:
    """Stable 32-char document ID from the file hash."""
    return sha256[:32]