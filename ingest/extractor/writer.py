"""Append-only NDJSON writers (extracted + rejected)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TextIO


class _LockedJSONL:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh: TextIO = open(path, "a", encoding="utf-8")

    def write(self, payload: dict) -> None:
        line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            self._fh.close()


class ExtractedWriter:
    def __init__(self, ok_path: Path, reject_path: Path) -> None:
        self._ok = _LockedJSONL(ok_path)
        self._rej = _LockedJSONL(reject_path)

    def write_ok(self, record: dict) -> None:
        self._ok.write(record)

    def write_rejected(self, document_id: str, chunk_id: str, raw: dict | None, reason: str) -> None:
        self._rej.write({
            "document_id": document_id,
            "chunk_id": chunk_id,
            "reason": reason,
            "raw": raw,
        })

    def close(self) -> None:
        self._ok.close()
        self._rej.close()