"""Reject log: NDJSON of entities / relations we couldn't process.

Reasons:
  - empty_name
  - too_short
  - too_long
  - ambiguous_phrase
  - missing_target
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import TextIO


class RejectLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh: TextIO = open(path, "a", encoding="utf-8")
        self._count = 0

    def write(self, payload: dict) -> None:
        with self._lock:
            self._fh.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
            self._fh.flush()
            self._count += 1

    @property
    def count(self) -> int:
        return self._count

    def close(self) -> None:
        with self._lock:
            self._fh.close()