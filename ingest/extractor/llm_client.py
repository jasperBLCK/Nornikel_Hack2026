"""Async Anthropic API client with retry/backoff.

Uses the Messages API directly via httpx (no SDK dependency) so we can
pin the exact wire format and version.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import random
from typing import Any

import httpx

from ingest.extractor.config import ExtractorConfig

logger = logging.getLogger(__name__)


class AnthropicError(RuntimeError):
    pass


class AnthropicClient:
    def __init__(self, cfg: ExtractorConfig) -> None:
        self.cfg = cfg
        api_key = os.environ.get(cfg.api_key_env, "")
        if not api_key:
            raise EnvironmentError(f"Missing API key in env {cfg.api_key_env}")
        # Allow env override of the base URL (for Anthropic-compatible proxies).
        base_url = os.environ.get("ANTHROPIC_BASE_URL", "").strip() or cfg.api_base
        # Strip trailing /api so we can keep "/v1/messages" as the path.
        base_url = base_url.rstrip("/")
        if base_url.endswith("/api"):
            base_url = base_url[:-4]
        self._client = httpx.AsyncClient(
            base_url=base_url,
            timeout=cfg.request_timeout_sec,
            headers={
                "x-api-key": api_key,
                "anthropic-version": cfg.anthropic_version,
                "content-type": "application/json",
            },
        )
        self._sem = asyncio.Semaphore(cfg.async_concurrency)

    async def close(self) -> None:
        await self._client.aclose()

    async def create_message(
        self,
        *,
        model: str,
        system: str,
        messages: list[dict],
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> dict:
        payload: dict[str, Any] = {
            "model": model,
            "system": system,
            "messages": messages,
            "max_tokens": max_tokens or self.cfg.max_output_tokens,
            "temperature": self.cfg.temperature if temperature is None else temperature,
        }

        backoff = 1.0
        last_err: Exception | None = None
        for attempt in range(self.cfg.max_retries):
            try:
                async with self._sem:
                    resp = await self._client.post("/v1/messages", json=payload)
                if resp.status_code in (429, 500, 502, 503, 504, 529):
                    raise AnthropicError(f"transient {resp.status_code}: {resp.text[:200]}")
                if resp.status_code >= 400:
                    raise AnthropicError(f"fatal {resp.status_code}: {resp.text[:500]}")
                return resp.json()
            except (httpx.RequestError, AnthropicError) as e:
                last_err = e
                sleep_s = backoff + random.uniform(0, 0.5)
                logger.warning(
                    "Anthropic call failed (attempt %d/%d): %s — sleep %.1fs",
                    attempt + 1, self.cfg.max_retries, e, sleep_s,
                )
                await asyncio.sleep(sleep_s)
                backoff = min(backoff * 2, 30.0)
        raise AnthropicError(f"exhausted retries: {last_err}")

    @staticmethod
    def extract_text(response: dict) -> str:
        """Pull concatenated text out of a Messages API response."""
        parts: list[str] = []
        for block in response.get("content", []):
            if block.get("type") == "text":
                parts.append(block.get("text", ""))
        return "\n".join(parts).strip()

    @staticmethod
    def parse_json_strict(text: str) -> dict:
        """Parse a JSON object from the model text. Strips ```json fences if present."""
        s = text.strip()
        if s.startswith("```"):
            # remove leading and trailing fences
            s = s.strip("`")
            if s.startswith("json"):
                s = s[4:]
            s = s.strip()
        try:
            obj = json.loads(s)
        except json.JSONDecodeError as e:
            raise AnthropicError(f"model returned non-JSON: {e}: {s[:200]}")
        if not isinstance(obj, dict):
            raise AnthropicError(f"model returned non-object JSON: {type(obj).__name__}")
        return obj