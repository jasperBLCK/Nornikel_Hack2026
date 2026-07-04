"""Append-only NDJSON writer (thread-safe)."""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TextIO


class ChunkWriter:
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