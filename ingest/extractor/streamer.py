"""Streaming NDJSON reader for Stage 2 chunks."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterator


def iter_chunks(ndjson_path: Path) -> Iterator[dict]:
    with open(ndjson_path, "r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(
                    f"Invalid JSON at {ndjson_path}:{line_no}: {e}"
                ) from e