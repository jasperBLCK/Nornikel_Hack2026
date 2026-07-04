"""Integration with OpenAlex — the open catalog of world scientific papers.

Searches foreign publications for a topic, with optional RU translation of
titles/abstracts via the configured LLM provider (YandexGPT).
"""
from __future__ import annotations

import asyncio
import json
import os
from collections import OrderedDict

import httpx

_OPENALEX = "https://api.openalex.org/works"
_MAILTO = "hydrax@example.com"

_cache: OrderedDict[str, dict] = OrderedDict()
_CACHE_MAX = 40


def _abstract_from_index(inv: dict | None, max_words: int = 80) -> str:
    if not inv:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inv.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    words = [w for _, w in positions[:max_words]]
    tail = "…" if len(positions) > max_words else ""
    return " ".join(words) + tail


async def _translate_batch(texts: list[str]) -> list[str]:
    """Translate EN → RU in one LLM call. Returns [] on any failure."""
    api_key = os.environ.get("YANDEX_API_KEY", "")
    folder = os.environ.get("YANDEX_FOLDER_ID", "")
    if not api_key or not folder or not texts:
        return []
    model = os.environ.get("YANDEX_MODEL", "qwen3-235b-a22b-fp8/latest")
    payload = {
        "model": f"gpt://{folder}/{model}",
        "max_tokens": 4000,
        "temperature": 0.1,
        "messages": [
            {"role": "system",
             "content": "Переведи каждый элемент JSON-массива с английского на "
                        "русский. Сохрани научную терминологию. Ответь ТОЛЬКО "
                        "JSON-массивом строк той же длины, без пояснений."},
            {"role": "user", "content": json.dumps(texts, ensure_ascii=False)},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                "https://llm.api.cloud.yandex.net/v1/chat/completions",
                json=payload, headers={"Authorization": f"Bearer {api_key}"})
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):
            content = content.strip("`").lstrip("json").strip()
        out = json.loads(content)
        if isinstance(out, list) and len(out) == len(texts):
            return [str(t) for t in out]
    except Exception:
        pass
    return []


async def _translate_query(query: str) -> str:
    """RU → EN search query for OpenAlex."""
    if not any("а" <= ch.lower() <= "я" for ch in query):
        return query
    out = await _translate_to_en(query)
    return out or query


async def _translate_to_en(text: str) -> str:
    api_key = os.environ.get("YANDEX_API_KEY", "")
    folder = os.environ.get("YANDEX_FOLDER_ID", "")
    if not api_key or not folder:
        return ""
    model = os.environ.get("YANDEX_MODEL", "qwen3-235b-a22b-fp8/latest")
    payload = {
        "model": f"gpt://{folder}/{model}",
        "max_tokens": 200,
        "temperature": 0.0,
        "messages": [
            {"role": "system",
             "content": "Translate the user's mining/metallurgy search query "
                        "to English. Reply with ONLY the translation."},
            {"role": "user", "content": text},
        ],
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://llm.api.cloud.yandex.net/v1/chat/completions",
                json=payload, headers={"Authorization": f"Bearer {api_key}"})
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""


async def search_world(query: str, per_page: int = 10,
                       translate: bool = True) -> dict:
    key = f"{query.strip().lower()}|{per_page}|{translate}"
    if key in _cache:
        return _cache[key]

    query_en = await _translate_query(query)
    params = {
        "search": query_en,
        "per-page": per_page,
        "mailto": _MAILTO,
        "select": ("id,doi,title,publication_year,cited_by_count,"
                   "authorships,primary_location,abstract_inverted_index,"
                   "open_access"),
    }
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.get(_OPENALEX, params=params)
        resp.raise_for_status()
        data = resp.json()
        trends_resp = await client.get(_OPENALEX, params={
            "search": query_en, "group_by": "publication_year",
            "mailto": _MAILTO})
        trends_raw = (trends_resp.json().get("group_by", [])
                      if trends_resp.status_code == 200 else [])

    works = []
    for w in data.get("results", []):
        authors = [a.get("author", {}).get("display_name", "")
                   for a in (w.get("authorships") or [])[:4]]
        loc = w.get("primary_location") or {}
        src = (loc.get("source") or {})
        works.append({
            "id": w.get("id", ""),
            "doi": w.get("doi") or "",
            "title": w.get("title") or "",
            "year": w.get("publication_year"),
            "cited_by": w.get("cited_by_count", 0),
            "authors": [a for a in authors if a],
            "venue": src.get("display_name") or "",
            "open_access": bool((w.get("open_access") or {}).get("is_oa")),
            "abstract": _abstract_from_index(w.get("abstract_inverted_index")),
        })

    if translate and works:
        texts = []
        for w in works:
            texts.append(w["title"])
            texts.append(w["abstract"] or "-")
        translated = await _translate_batch(texts)
        if translated:
            for i, w in enumerate(works):
                w["title_ru"] = translated[2 * i]
                w["abstract_ru"] = ("" if translated[2 * i + 1] == "-"
                                    else translated[2 * i + 1])

    trends = sorted(
        ({"year": int(t["key"]), "count": t["count"]}
         for t in trends_raw if str(t.get("key", "")).isdigit()
         and 2000 <= int(t["key"]) <= 2030),
        key=lambda t: t["year"])

    out = {
        "query": query,
        "query_en": query_en,
        "total": (data.get("meta") or {}).get("count", len(works)),
        "works": works,
        "trends": trends,
    }
    _cache[key] = out
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)
    return out
