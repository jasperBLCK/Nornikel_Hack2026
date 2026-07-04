"""Answer synthesis: one LLM call per user query (not per chunk).

Providers (auto-detected, override with LLM_PROVIDER=yandex|anthropic):
- yandex     — Yandex AI Studio (YandexGPT via OpenAI-compatible API)
               env: YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_MODEL (default qwen3-235b-a22b-fp8/latest)
- anthropic  — Claude
               env: ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL, ANSWER_MODEL

If the primary provider fails and the other one is configured, the
non-streaming path falls back to it automatically.
"""
from __future__ import annotations

import json
import os

import httpx

from search.retrieval import RetrievalResult

_SYSTEM = """Ты — научный ассистент R&D-центра горно-металлургической компании.
Отвечай на вопрос пользователя ТОЛЬКО на основе предоставленных фрагментов документов и фактов графа знаний.
Правила:
- Каждое утверждение подкрепляй ссылкой на источник в формате [N], где N — номер фрагмента.
- Указывай числовые значения и единицы измерения точно как в источнике.
- Если данных недостаточно — прямо скажи об этом и укажи, чего не хватает (пробел в знаниях).
- Различай отечественную и зарубежную практику, если это видно из источников.
- Отвечай развёрнуто и структурированно на русском языке: начни с краткого вывода,
  затем раскрой детали по разделам (маркированные списки, подзаголовки),
  приведи все релевантные числовые параметры, условия и ограничения из источников,
  и заверши практическими рекомендациями или указанием пробелов в данных."""

_REVIEW_SYSTEM = """Ты — научный ассистент R&D-центра горно-металлургической компании.
Составь краткий литературный обзор по теме пользователя ТОЛЬКО на основе предоставленных фрагментов документов и фактов графа знаний.
Правила:
- Структура обзора: 1) введение и актуальность темы (2-3 предложения); 2) обзор подходов, сгруппированный по источникам/направлениям, с ключевыми числовыми параметрами; 3) сопоставление отечественной и зарубежной практики, если это видно из источников; 4) выявленные противоречия между источниками (разные значения одного параметра); 5) пробелы в данных и рекомендации для дальнейших исследований.
- Каждое утверждение подкрепляй ссылкой на источник в формате [N], где N — номер фрагмента.
- Числовые значения и единицы измерения указывай точно как в источнике.
- Пиши на русском языке, академическим стилем, с подзаголовками."""

_COMPARE_SYSTEM = """Ты — научный ассистент R&D-центра горно-металлургической компании.
Сравни отечественную и мировую (зарубежную) практику по теме пользователя ТОЛЬКО на основе предоставленных фрагментов документов и фактов графа знаний.
Правила:
- Начни с краткого вывода (2-3 предложения).
- Затем построй markdown-таблицу сравнения: критерий | отечественная практика | мировая практика. Включи технологии, числовые параметры (концентрации, температуры, скорости), оборудование и результаты.
- Каждое утверждение подкрепляй ссылкой [N] на номер фрагмента.
- Если по какой-то стороне данных нет — так и напиши «нет данных в корпусе», не выдумывай.
- Заверши рекомендацией: что из мировой практики стоит изучить/перенять и какие данные собрать.
- Пиши на русском языке."""

_MODE_SYSTEMS = {"review": _REVIEW_SYSTEM, "compare": _COMPARE_SYSTEM}

_STYLE_HINTS = {
    "concise": "\nСтиль ответа: максимально кратко — только суть, 3-7 предложений "
               "или компактный маркированный список, без длинных вступлений.",
    "academic": "\nСтиль ответа: строгий академический — научная лексика, "
                "структура как в научной статье, полные формулировки.",
    "simple": "\nСтиль ответа: простым языком, как для неспециалиста — "
              "поясняй термины, избегай профессионального жаргона.",
}

_YANDEX_OPENAI_BASE = "https://llm.api.cloud.yandex.net/v1"


def _context(result: RetrievalResult) -> str:
    parts = []
    for i, ch in enumerate(result.chunks, 1):
        parts.append(f"[{i}] Файл: {ch.filename}\n{ch.text[:2500]}")
    if result.facts:
        facts = "\n".join(f"- {f.source} —{f.relation}→ {f.target}"
                          + (f" (цитата: «{f.evidence[:150]}»)" if f.evidence else "")
                          for f in result.facts[:25])
        parts.append(f"Факты из графа знаний:\n{facts}")
    return "\n\n".join(parts)


def _user_message(query: str, result: RetrievalResult) -> str:
    msg = f"Вопрос: {query}\n\nИсточники:\n{_context(result)}"
    if result.constraints:
        lines = "\n".join(f"- {c['text']}" for c in result.constraints)
        msg += ("\n\nЧисловые ограничения из запроса (строго учитывай их "
                f"при отборе решений):\n{lines}")
    matches = result.parameter_matches
    if matches:
        lines = "\n".join(
            f"- {m['process']}: {m['parameter']} = {m['value']} {m['unit'] or ''}"
            f" (удовлетворяет «{m['constraint']}»)" for m in matches[:10])
        msg += f"\n\nПараметры из графа знаний, удовлетворяющие ограничениям:\n{lines}"
    return msg


# -- provider configuration ------------------------------------------------

def _yandex_config() -> dict | None:
    api_key = os.environ.get("YANDEX_API_KEY", "")
    folder = os.environ.get("YANDEX_FOLDER_ID", "")
    if not (api_key and folder):
        return None
    model = os.environ.get("YANDEX_MODEL", "qwen3-235b-a22b-fp8/latest")
    return {
        "name": "yandex",
        "url": f"{_YANDEX_OPENAI_BASE}/chat/completions",
        "model": model if model.startswith("gpt://") else f"gpt://{folder}/{model}",
        "headers": {
            "Authorization": f"Bearer {api_key}",
            "content-type": "application/json",
        },
    }


def _anthropic_config() -> dict | None:
    api_key = (os.environ.get("ANTHROPIC_API_KEY")
               or os.environ.get("ANTHROPIC_AUTH_TOKEN", ""))
    if not api_key:
        return None
    base = os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com").rstrip("/")
    return {
        "name": "anthropic",
        "url": f"{base}/v1/messages",
        "model": os.environ.get("ANSWER_MODEL", "claude-sonnet-5"),
        "headers": {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
    }


def _providers() -> list[dict]:
    """Ordered provider configs: primary first, then fallback."""
    yandex, anthropic = _yandex_config(), _anthropic_config()
    forced = os.environ.get("LLM_PROVIDER", "").strip().lower()
    if forced == "yandex":
        ordered = [yandex, anthropic]
    elif forced == "anthropic":
        ordered = [anthropic, yandex]
    else:
        ordered = [yandex, anthropic]
    return [p for p in ordered if p]


def _payload(provider: dict, query: str, result: RetrievalResult,
             stream: bool = False, history: list[dict] | None = None,
             mode: str = "answer", style: str = "") -> dict:
    system = _MODE_SYSTEMS.get(mode, _SYSTEM) + _STYLE_HINTS.get(style, "")
    dialog = [{"role": m["role"], "content": m["content"]}
              for m in (history or []) if m.get("content")]
    dialog.append({"role": "user", "content": _user_message(query, result)})
    if provider["name"] == "yandex":
        payload = {
            "model": provider["model"],
            "max_tokens": 4000,
            "temperature": 0.3,
            "messages": [{"role": "system", "content": system}, *dialog],
        }
    else:
        payload = {
            "model": provider["model"],
            "max_tokens": 4000,
            "system": system,
            "messages": dialog,
        }
    if stream:
        payload["stream"] = True
    return payload


_RETRIES = 2


def _describe_error(provider: dict, e: Exception) -> str:
    detail = str(e) or type(e).__name__
    if isinstance(e, httpx.HTTPStatusError):
        detail = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
    return f"{provider['name']}: {detail}"


_NOT_CONFIGURED = ("(LLM не настроен: задайте YANDEX_API_KEY + YANDEX_FOLDER_ID "
                   "или ANTHROPIC_API_KEY. Ниже показаны найденные фрагменты "
                   "и факты графа.)")


# -- answer synthesis -------------------------------------------------------

async def synthesize_answer(query: str, result: RetrievalResult,
                            history: list[dict] | None = None,
                            mode: str = "answer", style: str = "") -> str:
    providers = _providers()
    if not providers:
        return _NOT_CONFIGURED

    last_error = ""
    for provider in providers:
        for _ in range(1 + _RETRIES):
            try:
                async with httpx.AsyncClient(timeout=120) as client:
                    resp = await client.post(
                        provider["url"],
                        json=_payload(provider, query, result, history=history,
                                      mode=mode, style=style),
                        headers=provider["headers"])
                    resp.raise_for_status()
                    data = resp.json()
                if provider["name"] == "yandex":
                    return data["choices"][0]["message"]["content"]
                return "".join(b.get("text", "") for b in data.get("content", []))
            except (httpx.HTTPError, KeyError, IndexError) as e:
                last_error = _describe_error(provider, e)
    return (f"(Ошибка LLM: {last_error}. Ниже показаны найденные фрагменты "
            "и факты графа — ими можно пользоваться без генерации.)")


async def stream_answer(query: str, result: RetrievalResult,
                        history: list[dict] | None = None,
                        mode: str = "answer", style: str = ""):
    """Yield answer text deltas (SSE streaming from the active provider)."""
    providers = _providers()
    if not providers:
        yield _NOT_CONFIGURED
        return
    provider = providers[0]

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            async with client.stream(
                    "POST", provider["url"],
                    json=_payload(provider, query, result, stream=True,
                                  history=history, mode=mode, style=style),
                    headers=provider["headers"]) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    raw = line[5:].strip()
                    if not raw or raw == "[DONE]":
                        continue
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        continue
                    text = _delta_text(provider, event)
                    if text:
                        yield text
    except Exception as e:
        # streaming failed — fall back to the non-streaming path (with
        # retries and provider fallback) so the user still gets an answer
        fallback = await synthesize_answer(query, result, history=history,
                                           mode=mode, style=style)
        if fallback and not fallback.startswith("(Ошибка LLM"):
            yield fallback
        else:
            yield f"\n\n(Ошибка LLM: {_describe_error(provider, e)})"


def _delta_text(provider: dict, event: dict) -> str:
    if provider["name"] == "yandex":
        choices = event.get("choices") or []
        if choices:
            return (choices[0].get("delta") or {}).get("content", "") or ""
        return ""
    if event.get("type") == "content_block_delta":
        return event.get("delta", {}).get("text", "") or ""
    return ""
