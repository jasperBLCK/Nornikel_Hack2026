"""Resumable manifest for Stage 3 — tracks per-chunk outcomes."""
from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path


_SCHEMA = """
CREATE TABLE IF NOT EXISTS extracted (
    chunk_id        TEXT PRIMARY KEY,
    document_id     TEXT NOT NULL,
    status          TEXT NOT NULL,        -- 'ok' | 'rejected' | 'error'
    reason          TEXT,
    grounding_score REAL,
    updated_at      REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_extracted_doc ON extracted(document_id);
"""


class ExtractorManifest:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    def is_done(self, chunk_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM extracted WHERE chunk_id = ? LIMIT 1", (chunk_id,)
        )
        return cur.fetchone() is not None

    def mark(
        self,
        chunk_id: str,
        document_id: str,
        status: str,
        reason: str | None = None,
        grounding_score: float | None = None,
    ) -> None:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            self._conn.execute(
                """
                INSERT INTO extracted(chunk_id, document_id, status, reason, grounding_score, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(chunk_id) DO UPDATE SET
                    document_id=excluded.document_id,
                    status=excluded.status,
                    reason=excluded.reason,
                    grounding_score=excluded.grounding_score,
                    updated_at=excluded.updated_at
                """,
                (chunk_id, document_id, status, reason, grounding_score, time.time()),
            )
            self._conn.execute("COMMIT")

    def filter_pending(self, chunk_ids: list[str]) -> list[str]:
        if not chunk_ids:
            return []
        placeholders = ",".join("?" for _ in chunk_ids)
        cur = self._conn.execute(
            f"SELECT chunk_id FROM extracted WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        )
        done = {row[0] for row in cur.fetchall()}
        return [c for c in chunk_ids if c not in done]

    def close(self) -> None:
        with self._lock:
            self._conn.close()