"""Audit & security event logging (SQLite, same zero-infra pattern as
sessions.py; move to PostgreSQL by pointing AUDIT_DB at a mounted volume
and swapping the driver — the schema is portable).

Two streams:
  * actions   — who did what (queries, views, exports) with parameters;
  * logins    — auth events with IP, GeoIP and anomaly flags.

Suspicious-login detection rules:
  R1 shared_ip     — the same IP was used by another account in the last 24h;
  R2 new_geo       — first login of this user from a new country;
  R3 bruteforce    — 5+ failed attempts for the account within 10 minutes.
"""
from __future__ import annotations

import ipaddress
import os
import sqlite3
import time
from pathlib import Path

import httpx

_SCHEMA = """
CREATE TABLE IF NOT EXISTS audit_actions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  username TEXT NOT NULL,
  role TEXT NOT NULL,
  action TEXT NOT NULL,
  detail TEXT NOT NULL DEFAULT '',
  ip TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_actions_ts ON audit_actions(ts DESC);
CREATE TABLE IF NOT EXISTS login_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts REAL NOT NULL,
  username TEXT NOT NULL,
  ip TEXT NOT NULL DEFAULT '',
  country TEXT NOT NULL DEFAULT '',
  city TEXT NOT NULL DEFAULT '',
  success INTEGER NOT NULL,
  suspicious INTEGER NOT NULL DEFAULT 0,
  reasons TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_logins_ts ON login_events(ts DESC);
CREATE INDEX IF NOT EXISTS idx_logins_ip ON login_events(ip);
"""


def _db_path() -> Path:
    return Path(os.environ.get("AUDIT_DB", "./hydrax_out/audit.db"))


def _conn() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


# -- GeoIP ---------------------------------------------------------------

_geo_cache: dict[str, tuple[str, str]] = {}


def _is_private(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private or ip in ("", "testclient")
    except ValueError:
        return True


async def geoip(ip: str) -> tuple[str, str]:
    """(country, city) via ip-api.com (free tier), cached per IP."""
    if _is_private(ip):
        return ("Локальная сеть", "")
    if ip in _geo_cache:
        return _geo_cache[ip]
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(
                f"http://ip-api.com/json/{ip}",
                params={"fields": "status,country,city", "lang": "ru"})
            data = resp.json()
        result = ((data.get("country", ""), data.get("city", ""))
                  if data.get("status") == "success" else ("", ""))
    except Exception:
        result = ("", "")
    _geo_cache[ip] = result
    return result


# -- writes ----------------------------------------------------------------

def log_action(username: str, role: str, action: str, detail: str = "",
               ip: str = "") -> None:
    with _conn() as c:
        c.execute(
            "INSERT INTO audit_actions (ts, username, role, action, detail, ip)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (time.time(), username, role, action, detail[:500], ip))


def log_login(username: str, ip: str, country: str, city: str,
              success: bool) -> list[str]:
    """Record a login attempt; returns the suspicion reasons (possibly [])."""
    now = time.time()
    reasons: list[str] = []
    with _conn() as c:
        if success:
            row = c.execute(
                "SELECT COUNT(DISTINCT username) AS n FROM login_events "
                "WHERE ip = ? AND username != ? AND success = 1 AND ts > ?",
                (ip, username, now - 86400)).fetchone()
            if ip and not _is_private(ip) and row["n"] > 0:
                reasons.append("shared_ip")
            if country and country != "Локальная сеть":
                seen = c.execute(
                    "SELECT COUNT(*) AS n FROM login_events WHERE username = ?"
                    " AND country = ? AND success = 1", (username, country)
                ).fetchone()
                if seen["n"] == 0:
                    prev = c.execute(
                        "SELECT COUNT(*) AS n FROM login_events "
                        "WHERE username = ? AND success = 1",
                        (username,)).fetchone()
                    if prev["n"] > 0:
                        reasons.append("new_geo")
        else:
            fails = c.execute(
                "SELECT COUNT(*) AS n FROM login_events WHERE username = ? "
                "AND success = 0 AND ts > ?", (username, now - 600)).fetchone()
            if fails["n"] >= 4:
                reasons.append("bruteforce")
        c.execute(
            "INSERT INTO login_events (ts, username, ip, country, city, "
            "success, suspicious, reasons) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (now, username, ip, country, city, int(success),
             int(bool(reasons)), ",".join(reasons)))
    return reasons


# -- reads (admin) ---------------------------------------------------------

def actions(limit: int = 200, username: str = "", action: str = "") -> list[dict]:
    q = "SELECT * FROM audit_actions WHERE 1=1"
    args: list = []
    if username:
        q += " AND username = ?"
        args.append(username)
    if action:
        q += " AND action = ?"
        args.append(action)
    q += " ORDER BY ts DESC LIMIT ?"
    args.append(limit)
    with _conn() as c:
        return [dict(r) for r in c.execute(q, args).fetchall()]


def logins(limit: int = 200, suspicious_only: bool = False) -> list[dict]:
    q = "SELECT * FROM login_events"
    if suspicious_only:
        q += " WHERE suspicious = 1"
    q += " ORDER BY ts DESC LIMIT ?"
    with _conn() as c:
        return [dict(r) for r in c.execute(q, (limit,)).fetchall()]


def security_summary() -> dict:
    now = time.time()
    with _conn() as c:
        total = c.execute("SELECT COUNT(*) AS n FROM login_events").fetchone()["n"]
        failed24 = c.execute(
            "SELECT COUNT(*) AS n FROM login_events WHERE success = 0 AND ts > ?",
            (now - 86400,)).fetchone()["n"]
        suspicious = c.execute(
            "SELECT COUNT(*) AS n FROM login_events WHERE suspicious = 1"
        ).fetchone()["n"]
        active = c.execute(
            "SELECT COUNT(DISTINCT username) AS n FROM login_events "
            "WHERE success = 1 AND ts > ?", (now - 86400,)).fetchone()["n"]
        actions24 = c.execute(
            "SELECT COUNT(*) AS n FROM audit_actions WHERE ts > ?",
            (now - 86400,)).fetchone()["n"]
        exports24 = c.execute(
            "SELECT COUNT(*) AS n FROM audit_actions WHERE action = 'export' "
            "AND ts > ?", (now - 86400,)).fetchone()["n"]
    return {"logins_total": total, "failed_24h": failed24,
            "suspicious_total": suspicious, "active_users_24h": active,
            "actions_24h": actions24, "exports_24h": exports24}


def user_action_counts(username: str) -> dict:
    """Per-action counters for one user (personal cabinet)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT action, COUNT(*) AS n FROM audit_actions "
            "WHERE username = ? GROUP BY action", (username,)).fetchall()
    counts = {r["action"]: r["n"] for r in rows}
    counts["total"] = sum(counts.values())
    return counts


def user_directory() -> list[dict]:
    """Users observed in audit history with last activity (local mode helper)."""
    with _conn() as c:
        rows = c.execute(
            "SELECT username, MAX(ts) AS last_seen, COUNT(*) AS logins, "
            "SUM(CASE WHEN suspicious = 1 THEN 1 ELSE 0 END) AS suspicious "
            "FROM login_events WHERE success = 1 "
            "GROUP BY username ORDER BY last_seen DESC").fetchall()
    return [dict(r) for r in rows]
