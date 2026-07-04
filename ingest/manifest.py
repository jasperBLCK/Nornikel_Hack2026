"""Resumable run manifest backed by SQLite.

Used to skip files that were already processed in a previous run.
Workers read+write through this object — SQLite handles concurrent access.
"""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Iterable


_SCHEMA = """
CREATE TABLE IF NOT EXISTS processed (
    document_id TEXT PRIMARY KEY,
    sha256      TEXT NOT NULL,
    rel_path    TEXT NOT NULL,
    status      TEXT NOT NULL,   -- 'ok' | 'failed'
    error       TEXT,
    updated_at  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_processed_path ON processed(rel_path);
"""


class Manifest:
    """Thread-safe SQLite manifest. One DB per output dir."""

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            isolation_level=None,  # autocommit; we use BEGIN manually
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def is_processed(self, document_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM processed WHERE document_id = ? LIMIT 1",
            (document_id,),
        )
        return cur.fetchone() is not None

    def mark(
        self,
        document_id: str,
        sha256: str,
        rel_path: str,
        status: str,
        error: str | None = None,
    ) -> None:
        import time
        with self._lock:
            self._conn.execute(
                "BEGIN IMMEDIATE"
            )
            self._conn.execute(
                """
                INSERT INTO processed(document_id, sha256, rel_path, status, error, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    sha256=excluded.sha256,
                    rel_path=excluded.rel_path,
                    status=excluded.status,
                    error=excluded.error,
                    updated_at=excluded.updated_at
                """,
                (document_id, sha256, rel_path, status, error, time.time()),
            )
            self._conn.execute("COMMIT")

    def filter_unprocessed(self, items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
        """Given an iterable of (document_id, rel_path), return only unprocessed.
        Single SELECT — efficient for batches.
        """
        ids = [d for d, _ in items]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        cur = self._conn.execute(
            f"SELECT document_id FROM processed WHERE document_id IN ({placeholders})",
            ids,
        )
        seen = {row[0] for row in cur.fetchall()}
        return [(d, p) for d, p in items if d not in seen]