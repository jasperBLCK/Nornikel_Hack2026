"""Chat session storage (SQLite, zero extra infrastructure).

Sessions hold a dialog history so follow-up questions keep the context
of previous answers. DB path: SESSIONS_DB (default ./hydrax_out/sessions.db).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL DEFAULT '',
  username TEXT NOT NULL DEFAULT '',
  created_at REAL NOT NULL,
  updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  sources TEXT,
  created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


def _db_path() -> Path:
    return Path(os.environ.get("SESSIONS_DB", "./hydrax_out/sessions.db"))


def _conn() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript(_SCHEMA)
    cols = {r["name"] for r in c.execute("PRAGMA table_info(sessions)")}
    if "username" not in cols:
        c.execute("ALTER TABLE sessions ADD COLUMN username TEXT "
                  "NOT NULL DEFAULT ''")
    return c


def create_session(title: str = "", username: str = "") -> dict:
    now = time.time()
    sid = uuid.uuid4().hex
    with _conn() as c:
        c.execute("INSERT INTO sessions (id, title, username, created_at, "
                  "updated_at) VALUES (?, ?, ?, ?, ?)",
                  (sid, title[:80], username, now, now))
    return {"id": sid, "title": title[:80], "username": username,
            "created_at": now, "updated_at": now}


def list_sessions(limit: int = 50, username: str = "") -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT s.id, s.title, s.username, s.created_at, s.updated_at, "
            "       COUNT(m.id) AS messages "
            "FROM sessions s LEFT JOIN messages m ON m.session_id = s.id "
            "WHERE s.username IN ('', ?) "
            "GROUP BY s.id ORDER BY s.updated_at DESC LIMIT ?",
            (username, limit)).fetchall()
    return [dict(r) for r in rows]


def get_session(sid: str) -> dict | None:
    with _conn() as c:
        s = c.execute("SELECT * FROM sessions WHERE id = ?", (sid,)).fetchone()
        if s is None:
            return None
        msgs = c.execute(
            "SELECT role, content, sources, created_at FROM messages "
            "WHERE session_id = ? ORDER BY id", (sid,)).fetchall()
    out = dict(s)
    out["messages"] = [
        {"role": m["role"], "content": m["content"],
         "sources": json.loads(m["sources"]) if m["sources"] else None,
         "created_at": m["created_at"]}
        for m in msgs]
    return out


def delete_session(sid: str) -> bool:
    with _conn() as c:
        cur = c.execute("DELETE FROM sessions WHERE id = ?", (sid,))
    return cur.rowcount > 0


def add_message(sid: str, role: str, content: str,
                sources: dict | None = None) -> None:
    now = time.time()
    with _conn() as c:
        c.execute("INSERT INTO messages (session_id, role, content, sources, "
                  "created_at) VALUES (?, ?, ?, ?, ?)",
                  (sid, role, content,
                   json.dumps(sources, ensure_ascii=False) if sources else None,
                   now))
        c.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (now, sid))
        if role == "user":
            c.execute("UPDATE sessions SET title = ? "
                      "WHERE id = ? AND title = ''", (content[:80], sid))


def recent_queries(limit: int = 12) -> list[dict]:
    """Latest user questions across all sessions (newest first)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT m.content, m.created_at, m.session_id FROM messages m "
            "WHERE m.role = 'user' ORDER BY m.id DESC LIMIT ?",
            (limit,)).fetchall()
    return [{"query": r["content"], "created_at": r["created_at"],
             "session_id": r["session_id"]} for r in rows]


def history(sid: str, limit: int = 6) -> list[dict]:
    """Last `limit` messages as LLM chat history (oldest first)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT role, content FROM messages WHERE session_id = ? "
            "ORDER BY id DESC LIMIT ?", (sid, limit)).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
