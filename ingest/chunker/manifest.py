"""Resumable run manifest for the chunking stage.

Tracks which source documents have been fully chunked. Lets us resume
multi-million-document runs without reprocessing.
"""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS chunked (
    document_id TEXT PRIMARY KEY,
    chunk_count INTEGER NOT NULL,
    updated_at  REAL NOT NULL
);
"""


class ChunkManifest:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    def is_done(self, document_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM chunked WHERE document_id = ? LIMIT 1", (document_id,)
        )
        return cur.fetchone() is not None

    def mark(self, document_id: str, chunk_count: int) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                """
                INSERT INTO chunked(document_id, chunk_count, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    chunk_count=excluded.chunk_count,
                    updated_at=excluded.updated_at
                """,
                (document_id, chunk_count, time.time()),
            )
            self._conn.execute("COMMIT")

    def filter_pending(self, document_ids: list[str]) -> list[str]:
        if not document_ids:
            return []
        placeholders = ",".join("?" for _ in document_ids)
        cur = self._conn.execute(
            f"SELECT document_id FROM chunked WHERE document_id IN ({placeholders})",
            document_ids,
        )
        done = {row[0] for row in cur.fetchall()}
        return [d for d in document_ids if d not in done]

    def close(self) -> None:
        with self._lock:
            self._conn.close()