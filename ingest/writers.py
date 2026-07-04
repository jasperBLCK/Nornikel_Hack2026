"""Output writers — NDJSON (default) or per-doc JSON files."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import TextIO

from ingest.structures import Document


class _LockedWriter:
    """Single NDJSON stream with internal lock — safe across processes
    only when the OS provides atomic appends. For multi-process safety we
    rely on one writer process (the orchestrator) and workers return
    strings over a Queue.
    """

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._fh: TextIO = open(path, "a", encoding="utf-8")

    def write(self, doc: Document) -> None:
        line = doc.to_json()
        with self._lock:
            self._fh.write(line + "\n")
            self._fh.flush()

    def close(self) -> None:
        with self._lock:
            self._fh.close()


class JsonWriter:
    """Two modes: NDJSON (scalable) or per-doc .json (debug-friendly).
    Per-doc mode shards by first 2 chars of document_id to avoid huge dirs.
    """

    def __init__(self, output_dir: Path, per_doc: bool = False) -> None:
        self.output_dir = output_dir
        self.per_doc = per_doc
        self._ndjson = None if per_doc else _LockedWriter(output_dir / "documents.ndjson")
        self._lock = threading.Lock()

    def write(self, doc: Document) -> None:
        if self.per_doc:
            shard = doc.document_id[:2]
            target = self.output_dir / "docs" / shard / f"{doc.document_id}.json"
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(".json.tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(doc.to_json())
            os.replace(tmp, target)  # atomic on POSIX & Windows
        else:
            assert self._ndjson is not None
            self._ndjson.write(doc)

    def close(self) -> None:
        if self._ndjson is not None:
            self._ndjson.close()