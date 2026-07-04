"""HydraX Knowledge Map — FastAPI backend.

    uvicorn app.main:app --port 8000

Endpoints:
    POST /api/search          {query, top_k}  → chunks + graph facts + entities
    POST /api/answer          {query, top_k}  → LLM answer with citations + sources
    POST /api/answer/stream   {query, top_k}  → SSE: sources event, then text deltas
    POST /api/graph           {query}         → subgraph for visualization
    GET  /api/graph/full                      → global graph for the explorer page
    GET  /api/documents                       → per-document corpus summary
    GET  /api/analytics                       → node/relation distributions, top entities
    GET  /api/stats                           → corpus counters
    GET  /api/gaps                            → knowledge-gap report from the graph
    GET/POST /api/sessions, GET/DELETE /api/sessions/{id} → chat sessions
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from collections import OrderedDict
from dataclasses import asdict
from pathlib import Path
from urllib.parse import quote_plus

import httpx

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import audit
from app import auth as authmod
from app import sessions as sess
from app import world
from app.auth import User, classify_sensitivity, current_user, require_admin
from search.llm import stream_answer, synthesize_answer
from search.retrieval import Retriever, detect_entities

app = FastAPI(title="HydraX Knowledge Map")

_STATIC = Path(__file__).parent / "static"
_DIST = Path(__file__).parent.parent / "frontend" / "dist"

_retriever: Retriever | None = None
_lock = asyncio.Lock()

_CACHE_MAX = 64
_answer_cache: OrderedDict[tuple, dict] = OrderedDict()

_HEAVY_TTL = float(os.environ.get("HYDRAX_CACHE_TTL", "300"))
_heavy_cache: dict[str, tuple[float, object]] = {}
_heavy_locks: dict[str, asyncio.Lock] = {}


async def _cached(key: str, fn, *args):
    """Serve heavy corpus-wide computations from a TTL cache.

    Results are identical for all users (permission filtering happens on
    top of the cached value), so one computation serves everyone.
    """
    hit = _heavy_cache.get(key)
    if hit and time.monotonic() - hit[0] < _HEAVY_TTL:
        return hit[1]
    lock = _heavy_locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _heavy_cache.get(key)
        if hit and time.monotonic() - hit[0] < _HEAVY_TTL:
            return hit[1]
        value = await asyncio.to_thread(fn, *args)
        _heavy_cache[key] = (time.monotonic(), value)
        return value


async def retriever() -> Retriever:
    global _retriever
    if _retriever is None:
        async with _lock:
            if _retriever is None:
                _retriever = await asyncio.to_thread(Retriever)
    return _retriever


async def _prewarm() -> None:
    """Precompute heavy dashboard payloads so the first page load is instant."""
    r = await retriever()
    for key, fn, args in (
        ("stats", r.stats, ()),
        ("documents:2000", r.documents, (2000,)),
        ("graph_full:120", r.full_graph, (120,)),
        ("graph_full:200", r.full_graph, (200,)),
        ("analytics", r.analytics, ()),
        ("gaps", r.knowledge_gaps, ()),
        ("contradictions", r.contradictions, ()),
        ("matrix", r.coverage_matrix, ()),
        ("parameters", r.parameters_table, ()),
    ):
        try:
            await _cached(key, fn, *args)
        except Exception:
            pass


async def _prewarm_loop() -> None:
    while True:
        try:
            await _prewarm()
        except Exception:
            pass
        await asyncio.sleep(max(_HEAVY_TTL - 30, 60))


@app.on_event("startup")
async def _warmup() -> None:
    asyncio.create_task(_prewarm_loop())


class Query(BaseModel):
    query: str
    top_k: int = 8
    session_id: str | None = None
    mode: str = "answer"  # "answer" | "review" | "compare"
    geo: str = ""         # "" | "domestic" | "foreign"
    style: str = ""       # "" | "concise" | "academic" | "simple"


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _payload(result, user: User | None = None) -> dict:
    chunks = []
    hidden = 0
    allowed = user.allowed_levels() if user else None
    for c in result.chunks:
        level = classify_sensitivity(c.filename)
        if allowed is not None and level not in allowed:
            hidden += 1
            continue
        chunks.append({**asdict(c), "sensitivity": level})
    return {
        "entities": result.entities,
        "chunks": chunks,
        "facts": [asdict(f) for f in result.facts],
        "hidden_chunks": hidden,
        "constraints": result.constraints,
        "parameter_matches": result.parameter_matches,
        "geo": result.geo,
    }


def _cache_put(key: tuple, value: dict) -> None:
    _answer_cache[key] = value
    _answer_cache.move_to_end(key)
    while len(_answer_cache) > _CACHE_MAX:
        _answer_cache.popitem(last=False)


_MODE_PREFIX = re.compile(r"^(\U0001F4DA Обзор литературы: |\u2696 Сравнение практик: )")


def _retrieval_query(query: str, history: list[dict]) -> str:
    """Short context-free follow-ups ("ок", "а точно?") retrieve garbage and
    clobber the sources panel; anchor them to the previous question."""
    if not history:
        return query
    words = re.findall(r"[\w\u0400-\u04FF-]+", query)
    has_entities = any(detect_entities(query).values())
    if len(words) > 7 or has_entities:
        return query
    last_user = next((m["content"] for m in reversed(history)
                      if m["role"] == "user"), "")
    last_user = _MODE_PREFIX.sub("", last_user)
    return f"{last_user} {query}".strip() if last_user else query


@app.post("/api/search")
async def api_search(q: Query, request: Request,
                     user: User = Depends(current_user)) -> dict:
    r = await retriever()
    result = await asyncio.to_thread(r.retrieve, q.query, q.top_k, q.geo)
    await asyncio.to_thread(audit.log_action, user.username,
                            user.primary_role, "query", q.query,
                            _client_ip(request))
    return _payload(result, user)


@app.post("/api/answer")
async def api_answer(q: Query, request: Request,
                     user: User = Depends(current_user)) -> dict:
    await asyncio.to_thread(audit.log_action, user.username,
                            user.primary_role, "query", q.query,
                            _client_ip(request))
    key = (q.query.strip().lower(), q.top_k, q.mode, user.clearance,
           q.geo, q.style)
    if key in _answer_cache:
        return {**_answer_cache[key], "cached": True}
    r = await retriever()
    result = await asyncio.to_thread(r.retrieve, q.query, q.top_k, q.geo)
    answer = await synthesize_answer(q.query, result, mode=q.mode,
                                     style=q.style)
    out = {"answer": answer, **_payload(result, user)}
    _cache_put(key, out)
    return out


@app.post("/api/answer/stream")
async def api_answer_stream(q: Query, request: Request,
                            user: User = Depends(current_user)
                            ) -> StreamingResponse:
    await asyncio.to_thread(audit.log_action, user.username,
                            user.primary_role, "query", q.query,
                            _client_ip(request))
    session_id = q.session_id
    if session_id is None or await asyncio.to_thread(
            sess.get_session, session_id) is None:
        session_id = (await asyncio.to_thread(
            sess.create_session, "", user.username))["id"]
    history = await asyncio.to_thread(sess.history, session_id)

    r = await retriever()
    rq = _retrieval_query(q.query, history)
    result = await asyncio.to_thread(r.retrieve, rq, q.top_k, q.geo)
    prefix = {"review": "\U0001F4DA Обзор литературы: ",
              "compare": "\u2696 Сравнение практик: "}.get(q.mode, "")
    await asyncio.to_thread(sess.add_message, session_id, "user",
                            prefix + q.query)

    async def gen():
        yield "event: session\ndata: " + json.dumps(
            {"session_id": session_id}, ensure_ascii=False) + "\n\n"
        yield "event: sources\ndata: " + json.dumps(
            _payload(result, user), ensure_ascii=False) + "\n\n"
        parts: list[str] = []
        async for delta in stream_answer(q.query, result, history=history,
                                         mode=q.mode, style=q.style):
            parts.append(delta)
            yield "event: delta\ndata: " + json.dumps(
                {"text": delta}, ensure_ascii=False) + "\n\n"
        answer = "".join(parts)
        await asyncio.to_thread(sess.add_message, session_id, "assistant",
                                answer, _payload(result, user))
        if rq == q.query:
            _cache_put((q.query.strip().lower(), q.top_k, q.mode,
                        user.clearance, q.geo, q.style),
                       {"answer": answer, **_payload(result, user)})
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@app.post("/api/graph")
async def api_graph(q: Query, user: User = Depends(current_user)) -> dict:
    entities = detect_entities(q.query)
    r = await retriever()
    return await asyncio.to_thread(r.subgraph, entities)


@app.get("/api/graph/full")
async def api_graph_full(limit: int = 200,
                         user: User = Depends(current_user)) -> dict:
    r = await retriever()
    limit = min(limit, 1000)
    return await _cached(f"graph_full:{limit}", r.full_graph, limit)


@app.get("/api/documents")
async def api_documents(request: Request, limit: int = 2000,
                        user: User = Depends(current_user)) -> dict:
    r = await retriever()
    limit = min(limit, 10000)
    docs, total = await _cached(f"documents:{limit}", r.documents, limit)
    allowed = user.allowed_levels()
    visible = []
    hidden = 0
    for d in docs:
        level = classify_sensitivity(d.get("filename", ""))
        if level in allowed:
            visible.append({**d, "sensitivity": level})
        else:
            hidden += 1
    await asyncio.to_thread(audit.log_action, user.username,
                            user.primary_role, "view", "documents",
                            _client_ip(request))
    return {"documents": visible, "total": total, "shown": len(visible),
            "hidden": hidden}


@app.get("/api/analytics")
async def api_analytics(user: User = Depends(current_user)) -> dict:
    r = await retriever()
    return await _cached("analytics", r.analytics)


@app.get("/api/stats")
async def api_stats() -> dict:
    r = await retriever()
    return await _cached("stats", r.stats)


@app.get("/api/gaps")
async def api_gaps(user: User = Depends(current_user)) -> dict:
    r = await retriever()
    return await _cached("gaps", r.knowledge_gaps)


@app.get("/api/contradictions")
async def api_contradictions(user: User = Depends(current_user)) -> dict:
    r = await retriever()
    return await _cached("contradictions", r.contradictions)


@app.get("/api/matrix")
async def api_matrix(user: User = Depends(current_user)) -> dict:
    r = await retriever()
    return await _cached("matrix", r.coverage_matrix)


@app.get("/api/parameters")
async def api_parameters(user: User = Depends(current_user)) -> dict:
    r = await retriever()
    return await _cached("parameters", r.parameters_table)


@app.get("/api/path")
async def api_path(source: str, target: str,
                   user: User = Depends(current_user)) -> dict:
    r = await retriever()
    return await asyncio.to_thread(r.path_between, source, target)


@app.get("/api/entities")
async def api_entities(user: User = Depends(current_user)) -> dict:
    r = await retriever()
    return {"entities": await asyncio.to_thread(r.entity_names)}


@app.get("/api/videos")
async def api_videos(q: str, limit: int = 3,
                     user: User = Depends(current_user)) -> dict:
    """Educational video lookup for the chat page. Uses the YouTube Data API
    when YOUTUBE_API_KEY is set; otherwise returns a search-link fallback."""
    query = q.strip()
    search_url = ("https://www.youtube.com/results?search_query="
                  + quote_plus(query))
    key = os.environ.get("YOUTUBE_API_KEY", "")
    if not key:
        return {"videos": [], "fallback_url": search_url}
    params = {
        "part": "snippet", "type": "video", "maxResults": min(limit, 5),
        "q": query, "relevanceLanguage": "ru", "safeSearch": "strict",
        "videoEmbeddable": "true", "videoDuration": "medium", "key": key,
    }
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://www.googleapis.com/youtube/v3/search", params=params)
            resp.raise_for_status()
            items = resp.json().get("items", [])
    except Exception:
        return {"videos": [], "fallback_url": search_url}
    videos = []
    for it in items:
        vid = (it.get("id") or {}).get("videoId")
        sn = it.get("snippet") or {}
        if not vid:
            continue
        videos.append({
            "id": vid,
            "title": sn.get("title", ""),
            "channel": sn.get("channelTitle", ""),
            "thumbnail": ((sn.get("thumbnails") or {}).get("medium") or {}).get("url", ""),
            "url": f"https://www.youtube.com/watch?v={vid}",
            "embed_url": f"https://www.youtube.com/embed/{vid}",
        })
    return {"videos": videos, "fallback_url": search_url}


@app.get("/api/queries/recent")
async def api_recent_queries(limit: int = 12,
                             user: User = Depends(current_user)) -> dict:
    return {"queries": await asyncio.to_thread(sess.recent_queries,
                                               min(limit, 50))}


@app.get("/api/world")
async def api_world(q: str, limit: int = 10, translate: bool = True,
                    user: User = Depends(current_user)) -> dict:
    try:
        return await world.search_world(q, per_page=min(limit, 25),
                                        translate=translate)
    except Exception as e:
        return {"error": str(e), "works": [], "trends": [], "total": 0,
                "query": q, "query_en": q}


@app.get("/api/entity")
async def api_entity(name: str, request: Request,
                     user: User = Depends(current_user)) -> dict:
    """Dossier for a graph entity: relations + relevant corpus fragments."""
    await asyncio.to_thread(audit.log_action, user.username,
                            user.primary_role, "view", f"entity:{name}",
                            _client_ip(request))
    r = await retriever()
    try:
        facts = await asyncio.to_thread(
            r.graph_facts, {"entities": [name]}, 40)
    except Exception:
        facts = []
    try:
        chunks = await asyncio.to_thread(r.vector_search, name, 4)
    except Exception:
        chunks = []
    return {
        "name": name,
        "facts": [asdict(f) for f in facts],
        "chunks": [asdict(c) for c in chunks],
    }


# -- auth ------------------------------------------------------------------

class LoginBody(BaseModel):
    username: str
    password: str


class RefreshBody(BaseModel):
    refresh_token: str


class ExportBody(BaseModel):
    kind: str = "md"
    detail: str = ""


@app.post("/api/auth/login")
async def api_login(body: LoginBody, request: Request) -> dict:
    ip = _client_ip(request)
    country, city = await audit.geoip(ip)
    try:
        result = await authmod.login(body.username, body.password)
    except HTTPException as e:
        await asyncio.to_thread(audit.log_login, body.username, ip,
                                country, city, False)
        raise e
    reasons = await asyncio.to_thread(audit.log_login, body.username, ip,
                                      country, city, True)
    if reasons:
        result["security_notice"] = reasons
    return result


@app.post("/api/auth/refresh")
async def api_refresh(body: RefreshBody) -> dict:
    return await authmod.refresh(body.refresh_token)


@app.get("/api/auth/me")
async def api_me(user: User = Depends(current_user)) -> dict:
    return {"user": user.as_dict(),
            "keycloak": authmod.keycloak_enabled()}


@app.get("/api/me/overview")
async def api_me_overview(user: User = Depends(current_user)) -> dict:
    """Personal cabinet: the user's sessions and recent activity."""
    my_sessions = await asyncio.to_thread(sess.list_sessions, 8, user.username)
    my_actions = await asyncio.to_thread(audit.actions, 10, user.username)
    counts = await asyncio.to_thread(audit.user_action_counts, user.username)
    return {"user": user.as_dict(), "sessions": my_sessions,
            "actions": my_actions, "counts": counts}


@app.post("/api/audit/export")
async def api_audit_export(body: ExportBody, request: Request,
                           user: User = Depends(current_user)) -> dict:
    """Frontend reports data exports (.md / JSON-LD / PDF) here so they land
    in the audit trail; export is denied for roles without the permission."""
    if not user.can_export:
        raise HTTPException(403, "Экспорт данных недоступен для вашей роли")
    await asyncio.to_thread(audit.log_action, user.username,
                            user.primary_role, "export",
                            f"{body.kind}: {body.detail}", _client_ip(request))
    return {"logged": True}


# -- admin -------------------------------------------------------------------

@app.get("/api/admin/summary")
async def api_admin_summary(user: User = Depends(require_admin)) -> dict:
    return await asyncio.to_thread(audit.security_summary)


@app.get("/api/admin/audit")
async def api_admin_audit(limit: int = 200, username: str = "",
                          action: str = "",
                          user: User = Depends(require_admin)) -> dict:
    rows = await asyncio.to_thread(audit.actions, min(limit, 1000),
                                   username, action)
    return {"actions": rows}


@app.get("/api/admin/logins")
async def api_admin_logins(limit: int = 200, suspicious: bool = False,
                           user: User = Depends(require_admin)) -> dict:
    rows = await asyncio.to_thread(audit.logins, min(limit, 1000), suspicious)
    return {"logins": rows}


@app.get("/api/admin/users")
async def api_admin_users(user: User = Depends(require_admin)) -> dict:
    directory = await asyncio.to_thread(audit.user_directory)
    seen = {d["username"] for d in directory}
    known = []
    for username, rec in authmod.LOCAL_USERS.items():
        role = next((r for r in authmod.ROLES if r in rec["roles"]),
                    "external_partner")
        known.append({
            "username": username, "name": rec["name"], "role": role,
            "role_label": authmod.ROLE_LABELS[role],
            "clearance": authmod.ROLE_CLEARANCE[role],
            "activity": next((d for d in directory
                              if d["username"] == username), None),
        })
    extra = [d for d in directory if d["username"] not in
             set(authmod.LOCAL_USERS)]
    return {"users": known, "external": extra,
            "keycloak": authmod.keycloak_enabled(),
            "seen_usernames": sorted(seen)}


# -- chat sessions ---------------------------------------------------------

class SessionCreate(BaseModel):
    title: str = ""


@app.get("/api/sessions")
async def api_sessions(user: User = Depends(current_user)) -> dict:
    return {"sessions": await asyncio.to_thread(sess.list_sessions, 50,
                                                user.username)}


@app.post("/api/sessions")
async def api_session_create(body: SessionCreate,
                             user: User = Depends(current_user)) -> dict:
    return await asyncio.to_thread(sess.create_session, body.title,
                                   user.username)


@app.get("/api/sessions/{session_id}")
async def api_session_get(session_id: str,
                          user: User = Depends(current_user)) -> dict:
    s = await asyncio.to_thread(sess.get_session, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    if s.get("username") not in ("", user.username) \
            and "admin" not in user.roles:
        raise HTTPException(403, "Чужая сессия")
    return s


@app.delete("/api/sessions/{session_id}")
async def api_session_delete(session_id: str,
                             user: User = Depends(current_user)) -> dict:
    s = await asyncio.to_thread(sess.get_session, session_id)
    if s is None:
        raise HTTPException(404, "session not found")
    if s.get("username") not in ("", user.username) \
            and "admin" not in user.roles:
        raise HTTPException(403, "Чужая сессия")
    await asyncio.to_thread(sess.delete_session, session_id)
    return {"deleted": True}


# -- frontend ------------------------------------------------------------
# Serve the built React app when frontend/dist exists; otherwise fall back
# to the legacy single-file UI in app/static.

if _DIST.exists():
    app.mount("/assets", StaticFiles(directory=_DIST / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str) -> FileResponse:
        candidate = _DIST / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_DIST / "index.html")
else:
    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(_STATIC / "index.html")

    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
