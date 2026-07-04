---
name: testing-hydrax
description: Test the HydraX knowledge-map app end-to-end (pipeline, search UI, chat sessions, YandexGPT answers, graph/analytics pages). Use when verifying changes to ingest/, search/, app/ or frontend/.
---

# Testing HydraX end-to-end

## Setup

1. Start Neo4j + app: `docker compose up -d --build` (the `ingest` service auto-runs Stage 1-5 if the graph is empty). Or run manually: `python run_pipeline.py` then `uvicorn app.main:app --port 8000`.
2. Fast option for UI testing: create a tiny 3-doc corpus in `data/` (each doc a few sentences with concrete numbers/materials/processes) — the pipeline finishes in seconds and answers stay verifiable.
3. Check `localhost:8000/api/stats`: expect `"neo4j": true` and `nodes > 0`. If `nodes: 0` the graph pages will be empty — rerun the pipeline against the SAME Neo4j the app uses (compose containers vs manual `docker run` containers are separate!).
4. LLM: set `YANDEX_API_KEY` + `YANDEX_FOLDER_ID` (secret names below). Default model qwen3-235b. Occasional empty "Ошибка LLM: yandex:" errors may be transient (retries exist); a direct curl to the Yandex completion endpoint confirms API health.
5. Frontend changes require rebuild: `cd frontend && npm run build` (dist served by FastAPI). Verify the served bundle hash changed: `curl -s localhost:8000/ | grep -o 'index-[^"]*\.js'`. Hard-refresh (Ctrl+Shift+R) in browser.

## Golden-path UI tests (record these)

- Search page: click an example chip → answer streams with [N] citations, sources card, recognized entities.
- Chat sessions: first question auto-creates a session with auto-title in sidebar; a context-free follow-up ("а какая температура там поддерживается?") must be answered using dialog context.
- "+ Новый диалог" then ask again → new session; switch back to old session restores full dialog + sources; ✕ deletes a session. Also click "+ Новый диалог" WHILE an answer is streaming — must reset instantly with no crash/stale deltas.
- Retrieval anchoring: after a normal question, send a short reply («ок») — the «Источники» card must keep the SAME files/relevance (short context-free follow-ups are anchored to the previous question server-side in `_retrieval_query`, app/main.py). A full new question must still re-query and update sources/graph.
- «■ Стоп»: while streaming the send button shows «■ Стоп»; clicking stops token flow and returns to «Спросить».
- Dossier navigation: contradiction card on Dashboard and top-hub names on Analytics both open `/graph?entity=<name>` with the dossier panel.
- Graph page: nodes render (needs Neo4j populated).
- Analytics page: stats cards, entity/relation bars, «Пробелы в знаниях» card. Historically crashed with React error #31 — watch for "Unexpected Application Error".

## Known pitfalls

- Streaming race: SSE deltas arriving during session switches previously crashed the page ("Cannot read properties of undefined (reading 'content')"). Always retest the "+ Новый диалог → ask immediately" path after touching Search.jsx streaming code.
- Typing Cyrillic via keyboard emulation can produce stray "?" characters in the input — prefer clicking example chips, or paste via clipboard (`printf 'текст' | xclip -selection clipboard -d :0`, then Ctrl+V; `sudo apt-get install -y xclip` if missing).
- On a tiny 3-doc corpus every query returns the same 3 sources, so "sources unchanged after «ок»" must be judged by ordering + relevance scores + answer topic, not just filenames.
- The per-query «Граф знаний» panel on the Search page may show "Нет данных графа" on tiny corpora even when Neo4j is populated — not necessarily a bug; check the global Graph page.
- Users running `docker compose up` without `--build` will see the old UI; always instruct `git pull && docker compose up -d --build`.

## Devin Secrets Needed

- `YANDEX_API_KEY` — Yandex AI Studio API key
- `YANDEX_FOLDER_ID` — Yandex Cloud folder id
- `NEO4J_PASSWORD` — defaults to `testpass`, only needed if changed
