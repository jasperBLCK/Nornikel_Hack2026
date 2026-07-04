# HydraX — Scientific Knowledge Graph Platform

## Technical System Documentation

**Document version:** 1.0
**Date:** 2026-07-03
**Audience:** Devin AI (continuing development)
**Scope:** Production-grade ingestion → extraction → knowledge graph → hybrid retrieval pipeline for mining/metallurgy R&D corpora.

---

## 1. System Overview

HydraX converts ~4 GB of unstructured scientific documents (PDF, DOCX, scanned reports, experimental notes) into a queryable hybrid knowledge system backed by:

- **Neo4j** — explicit knowledge graph (entities, relations, evidence)
- **Qdrant** — semantic vector index over chunked text
- **Claude Sonnet 5** — structured extraction engine
- **Claude Sonnet 4.8** — final reasoning engine (Stage 5)

The system is engineered for:
- Determinism (reproducible runs, idempotent writes)
- Horizontal scalability (multiprocessing + async)
- Zero hallucination tolerance (schema-validated, evidence-gated)
- Resume on crash (SQLite WAL manifests per stage)
- Streaming IO (constant memory regardless of corpus size)

---

## 2. End-to-End Data Flow

```
        ┌──────────────────────────────────────────────────────────┐
        │                    INPUT CORPUS                          │
        │  ~4 GB PDFs / DOCX / scanned reports / TXT (RU text)      │
        └─────────────────────────┬────────────────────────────────┘
                                  │
                                  ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  STAGE 1 — ETL / Ingestion                                  │
   │  ingest/                                                     │
   │    • recursive scan (scanner.py)                             │
   │    • SHA-256 content-addressed doc_id (hashing.py)          │
   │    • PDF extractor (PyMuPDF, text-layer)                    │
   │    • DOCX extractor (python-docx, headings+tables)          │
   │    • TXT extractor (CP1251/KOI8-R/UTF-8 detection)          │
   │    • OCR fallback (Tesseract eng+rus, 300 DPI)              │
   │    • scanned-PDF detector (char-density heuristic)          │
   │    • multiprocessing pool (N workers)                       │
   │    • SQLite manifest (WAL mode, resume)                     │
   │                                                              │
   │  Output: documents.ndjson                                    │
   │    { document_id, filename, file_type, pages[], full_text,  │
   │      metadata{ sha256, page_count, is_scanned, ocr_used }}  │
   └─────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  STAGE 2 — Chunking & Normalization                         │
   │  ingest/chunker/                                             │
   │    • streaming NDJSON reader (line-by-line)                 │
   │    • normalizer: OCR cleanup, hyphenation fix, whitespace   │
   │    • whitespace tokenizer (RU-safe)                         │
   │    • sliding token windows: 800–1500 tokens, 200 overlap    │
   │    • page_range tracking via binary search                  │
   │    • heading detection (regex on #/##/###)                  │
   │    • deterministic chunk_id = sha256(doc_id+idx+text)[:32]  │
   │    • multiprocessing batch pipeline                         │
   │    • SQLite resume manifest                                 │
   │                                                              │
   │  Output: chunks.ndjson                                       │
   │    { document_id, chunk_id, chunk_index, text,              │
   │      page_range[2], metadata{token_count, heading, ...} }   │
   └─────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  STAGE 3 — Knowledge Extraction (LLM)                       │
   │  ingest/extractor/                                           │
   │    • async Anthropic client (httpx, retry/backoff)          │
   │    • RU system prompt + EN JSON keys + few-shot priming     │
   │    • per-chunk extraction → raw JSON                         │
   │    • Pydantic v2 strict schema validation                   │
   │    • grounding judge (separate LLM call, score ≥ 0.6)        │
   │    • multiprocess workers × async semaphore(8)              │
   │    • collector thread → ok + rejected NDJSON                │
   │    • SQLite resume manifest                                 │
   │                                                              │
   │  Output: extracted.ndjson (validated)                        │
   │  Sidecar: extracted.rejected.ndjson                          │
   │    { document_id, chunk_id,                                 │
   │      materials[], processes[], equipment[],                 │
   │      parameters[{name,value,unit}], conditions[],           │
   │      experiments[], numerical_values[],                      │
   │      relations[{source,relation,target,evidence}],          │
   │      facts[{statement, confidence}],                         │
   │      model_used, grounding_score }                          │
   └─────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  STAGE 4 — Knowledge Graph Construction (Neo4j)             │
   │  ingest/graph/                                               │
   │    • streaming NDJSON reader                                 │
   │    • Cyrillic-aware canonicalization                        │
   │        (ё→е, NFKD, RU adj suffix stripping,                 │
   │         Latin chem formula → RU noun)                       │
   │    • in-memory dedup (canonical_key per node label)         │
   │    • batcher: per-record → NodeRow / RelRow                 │
   │    • UNWIND batched MERGE writes (1000/batch)               │
   │    • idempotency: unique constraints + signature dedup      │
   │    • reject_log.ndjson for ambiguous/empty entities         │
   │    • evidence + chunk_id + document_id on every edge        │
   │                                                              │
   │  Nodes: Material, Process, Equipment, Experiment,           │
   │         Parameter, Condition                                │
   │  Edges: USES, PRODUCES, OPERATES_IN,                        │
   │         HAS_PARAMETER, STUDIED_IN                           │
   └─────────────────────────┬───────────────────────────────────┘
                             │
                             ▼
   ┌─────────────────────────────────────────────────────────────┐
   │  STAGE 5 — Hybrid Retrieval & Reasoning (PLANNED)           │
   │  (to be implemented)                                         │
   │    • Query router (Opus 4.8): graph vs vector vs hybrid      │
   │    • Neo4j Cypher generator (Cypher templates + LLM)        │
   │    • Qdrant vector search (semantic recall)                 │
   │    • Reciprocal Rank Fusion engine                          │
   │    • Final reasoning: Claude Sonnet 4.8                        │
   │    • Citations anchored to chunk_id + evidence              │
   └─────────────────────────────────────────────────────────────┘
```

---

## 3. Stage-by-Stage Specification

### 3.1 Stage 1 — ETL

**Module path:** `ingest/`
**Entry point:** `python -m ingest.run --input <dir> --output <dir> --workers N`

#### Components

| File | Role |
|---|---|
| `config.py` | `IngestConfig` (frozen dataclass) — paths, workers, OCR params, scanned threshold |
| `structures.py` | `Document`, `Page`, `DocumentMetadata` dataclasses with `to_json()` |
| `hashing.py` | Streamed SHA-256 → `document_id` (first 32 hex) |
| `scanner.py` | `rglob` walker, sorted for determinism, MIME sniffing |
| `detectors.py` | `detect_scanned()` — char-density over first 5 pages |
| `extractors/base.py` | Abstract `Extractor` interface |
| `extractors/pdf_extractor.py` | PyMuPDF, per-page text-layer extraction |
| `extractors/docx_extractor.py` | python-docx, headings→`#` markers, tables→pipe format |
| `extractors/txt_extractor.py` | Encoding ladder: utf-8, cp1251, koi8-r, iso-8859-5, cp866 |
| `extractors/ocr_extractor.py` | Tesseract subprocess, eng+rus, 300 DPI render |
| `manifest.py` | SQLite WAL, `processed(document_id PK)` |
| `writers.py` | NDJSON (default) or per-doc sharded JSON |
| `worker.py` | Pure per-file unit, no shared state |
| `pipeline.py` | Multiprocessing orchestrator |
| `run.py` | CLI |

#### Determinism guarantees
- Document IDs are SHA-256 of file bytes (stable across machines/runs).
- `scanner.scan_folder()` returns sorted paths.
- Multiprocessing is `imap_unordered`, but output order does not affect downstream stages (NDJSON).

#### Failure model
- Per-file exceptions are caught in `worker.process_file()` and stored in `metadata.error`.
- Failed files are still marked in manifest with `status='failed'`.
- Resume: SQLite `processed` table skips completed IDs.

#### Output shape

```json
{
  "document_id": "ab12cd34...",
  "filename": "metallurgy_report.pdf",
  "file_type": "pdf",
  "pages": [
    { "page_number": 1, "text": "...", "is_scanned": false }
  ],
  "full_text": "...",
  "metadata": {
    "filename": "...",
    "relative_path": "subdir/metallurgy_report.pdf",
    "file_size_bytes": 1234567,
    "file_extension": ".pdf",
    "page_count": 42,
    "is_scanned": false,
    "ocr_used": false,
    "sha256": "...",
    "mime_type": "application/pdf",
    "error": null
  }
}
```

---

### 3.2 Stage 2 — Chunking & Normalization

**Module path:** `ingest/chunker/`
**Entry point:** `python -m ingest.chunker --input <stage1.ndjson> --output <stage2.ndjson> --workers N`

#### Components

| File | Role |
|---|---|
| `config.py` | `ChunkConfig` (frozen): min/max/overlap tokens, heading regex, normalization toggles |
| `tokenizer.py` | Whitespace tokenizer + `split_into_token_windows()` |
| `normalizer.py` | OCR cleanup, hyphenation fix, whitespace collapse (NFC-normalized) |
| `streamer.py` | `iter_documents()` — line-by-line NDJSON |
| `writer.py` | `ChunkWriter` — append-only NDJSON |
| `chunker.py` | `chunk_document()` — token windows + page_range + heading detection |
| `manifest.py` | SQLite WAL, `chunked(document_id PK, chunk_count)` |
| `pipeline.py` | Multiprocessing orchestrator with async batching |
| `__main__.py` | CLI |

#### Algorithm

1. Normalize `full_text` once (NFC → OCR cleanup → hyphenation → whitespace).
2. Re-tokenize per normalized page; build cumulative page-token offsets.
3. Flatten into a single token stream.
4. Compute windows: greedy step = `max_tokens - overlap_tokens`.
5. For each window:
   - Reconstruct text by joining tokens.
   - Binary-search `page_range` from token offsets.
   - Detect heading by regex on first `#` marker.
   - `chunk_id = sha256(document_id ‖ chunk_index ‖ text)[:32]`.

#### Determinism guarantees
- Pure function of input + config.
- chunk_id is content-hashed — identical text + index → identical ID across runs.
- Window boundaries are integer-token deterministic.

#### Output shape

```json
{
  "document_id": "ab12cd34...",
  "chunk_id": "9f8e7d6c...",
  "chunk_index": 0,
  "text": "...",
  "page_range": [1, 2],
  "metadata": {
    "token_count": 1247,
    "heading": "Введение",
    "filename": "metallurgy_report.pdf",
    "file_type": "pdf",
    "sha256": "...",
    "is_scanned": false,
    "ocr_used": false
  }
}
```

---

### 3.3 Stage 3 — Knowledge Extraction (LLM)

**Module path:** `ingest/extractor/`
**Entry point:** `python -m ingest.extractor --input <stage2.ndjson> --output <stage3.ndjson>`

**Requirement:** `ANTHROPIC_API_KEY` env var.

#### Components

| File | Role |
|---|---|
| `config.py` | `ExtractorConfig` (frozen) — model, workers, async_concurrency, batch_size, grounding params |
| `schema.py` | Pydantic v2: `ExtractionRecord`, `Parameter`, `Relation`, `Fact`, `GroundingVerdict` |
| `prompts.py` | RU system prompt, EN JSON keys, few-shot example, grounding judge prompt |
| `llm_client.py` | Async Anthropic via httpx, exponential backoff, JSON parsing |
| `validator.py` | Pydantic schema + grounding judge |
| `extract.py` | `extract_chunk()` — one async call per chunk |
| `streamer.py` | NDJSON reader |
| `writer.py` | `ExtractedWriter` — ok + rejected streams |
| `manifest.py` | SQLite WAL, `extracted(chunk_id PK, status, reason, grounding_score)` |
| `pipeline.py` | Multiprocess × async orchestrator, collector thread |
| `__main__.py` | CLI |

#### Concurrency model

```
Main thread:    stream NDJSON → batch (32) → mp.Queue
                                                  ↓
Worker proc i:  batch → asyncio.Semaphore(8) → Anthropic API
                                                  ↓
Collector thd:  mp.Queue → ok.ndjson + rejected.ndjson + manifest.sqlite
```

- N processes × M async requests = N×M parallel API calls.
- Single collector thread serializes disk writes (no file-handle contention).
- `temperature=0.0` for determinism.

#### Schema enforcement

Pydantic v2 strict validation runs on every model response. Failure modes:
- `json_parse_failed` — non-JSON output → rejected
- `schema_invalid` — wrong shape → rejected
- `grounding_rejected: score=X.XX` — judge score < 0.6 → rejected
- All rejected chunks go to `extracted.rejected.ndjson` with raw payload preserved.

#### Output shape

```json
{
  "document_id": "ab12cd34...",
  "chunk_id": "9f8e7d6c...",
  "materials": ["окисленная медная руда", "серная кислота", "медь"],
  "processes": ["кучное выщелачивание", "электроэкстракция"],
  "equipment": ["электролизёр", "титановый катод"],
  "parameters": [
    {"name": "концентрация серной кислоты", "value": "50", "unit": "г/л"},
    {"name": "извлечение меди", "value": "78,4", "unit": "%"}
  ],
  "conditions": ["кислая среда"],
  "experiments": ["серия HL-2023-04"],
  "numerical_values": ["50 г/л", "90 суток", "78,4%"],
  "relations": [
    {
      "source": "кучное выщелачивание",
      "relation": "применяется_для",
      "target": "окисленная медная руда",
      "evidence": "Кучное выщелачивание окисленной медной руды проводили"
    }
  ],
  "facts": [
    {"statement": "Извлечение меди в раствор составило 78,4%.", "confidence": 1.0}
  ],
  "model_used": "claude-sonnet-5",
  "grounding_score": 0.95
}
```

---

### 3.4 Stage 4 — Knowledge Graph Construction (Neo4j)

**Module path:** `ingest/graph/`
**Entry point:** `python -m ingest.graph --input <stage3.ndjson> --uri bolt://localhost:7687`

**Requirement:** `NEO4J_PASSWORD` env var.

#### Components

| File | Role |
|---|---|
| `config.py` | `GraphConfig` — Neo4j connection, batch sizes, dedup tuning |
| `schema.py` | Node labels, rel types, constraint DDL, UNWIND templates |
| `normalize.py` | `normalize_name()` — Cyrillic-aware canonical key generation |
| `dedup.py` | `DedupIndex` — (label, canonical_key) → bool |
| `streamer.py` | NDJSON reader |
| `batcher.py` | `BatchBuilder.add_extraction()` — record → NodeRow/RelRow |
| `neo4j_writer.py` | `Neo4jWriter` — UNWIND MERGE, constraint setup |
| `reject_log.py` | NDJSON reject logger |
| `pipeline.py` | Orchestrator: stream → batch → dedup → flush |
| `__main__.py` | CLI |

#### Normalization pipeline (`normalize_name`)

1. Strip `(...)` and `[...]`.
2. `ё` → `е` (and `Ё` → `Е`).
3. NFKD + drop combining marks.
4. Lowercase.
5. Keep only `[a-z0-9а-яё]`.
6. Latin chemical formulas → Russian nouns (`h2so4` → `серная кислота`).
7. Strip Russian adjectival suffixes (`-овый/-овая/-ое/-ный/-ная/-ское/...`).
8. Whitespace collapse.

Result: surface variants of the same entity share one `canonical_key`.

#### Idempotency strategy

Three layers of protection:

1. **Unique constraints** on `canonical_key` per label (DDL run once at start).
2. **In-memory dedup** — only emit UNWIND rows for unseen keys.
3. **Cypher MERGE** with `ON CREATE SET … ON MATCH SET …` — safe to re-run.

#### Graph schema

**Nodes:**
- `Material {canonical_key, name, created_at}`
- `Process {canonical_key, name, created_at}`
- `Equipment {canonical_key, name, created_at}`
- `Experiment {canonical_key, name, created_at}`
- `Parameter {canonical_key, name, value, unit, created_at}`
- `Condition {canonical_key, name, created_at}`

**Edges** (all carry `evidence`, `chunk_id`, `document_id`, `created_at`):

| Rel | From → To | Extra props |
|---|---|---|
| `USES` | Process → Material/Equipment | — |
| `PRODUCES` | Process → Material | — |
| `OPERATES_IN` | Equipment → Condition | — |
| `HAS_PARAMETER` | Process → Parameter | `value`, `unit` |
| `STUDIED_IN` | * → Experiment | — |

---

### 3.5 Stage 5 — Hybrid Retrieval & Reasoning (PLANNED)

**Module path:** `ingest/retrieval/` (to be created)

#### Planned components

| File | Planned role |
|---|---|
| `config.py` | Neo4j + Qdrant + Anthropic config |
| `qdrant_indexer.py` | Bulk-upload Stage 2 chunks as vectors (embed via Voyage AI or local model) |
| `query_router.py` | Opus 4.8 classification: graph-only / vector-only / hybrid |
| `cypher_generator.py` | NL → Cypher via Opus 4.8 with schema context |
| `vector_search.py` | Qdrant dense retrieval, top-k |
| `fusion.py` | Reciprocal Rank Fusion over graph + vector results |
| `reasoner.py` | Opus 4.8 final answer with grounded citations |
| `pipeline.py` | End-to-end orchestrator |
| `__main__.py` | CLI / FastAPI server |

#### Retrieval flow

```
user query
    ↓
[Opus 4.8 router]
    ↓
   ┌──────────┬─────────────┐
   ↓          ↓             ↓
[Neo4j]   [Qdrant]    [direct LLM]
   ↓          ↓             ↓
   └──── RRF ─┴─────────────┘
                ↓
       [Opus 4.8 reasoner]
                ↓
       answer + citations (chunk_id, evidence, document_id)
```

---

## 4. Component Dependency Map

```
ingest/
├── run.py                        # Stage 1 CLI
├── config.py, structures.py, …
├── extractors/{pdf,docx,txt,ocr}_extractor.py
├── worker.py, pipeline.py
│
├── chunker/                      # Stage 2
│   ├── __main__.py
│   ├── tokenizer.py
│   ├── normalizer.py
│   ├── chunker.py
│   ├── pipeline.py
│   └── …
│
├── extractor/                    # Stage 3
│   ├── __main__.py
│   ├── llm_client.py
│   ├── prompts.py
│   ├── schema.py
│   ├── validator.py
│   ├── extract.py
│   ├── pipeline.py
│   └── …
│
└── graph/                        # Stage 4
    ├── __main__.py
    ├── schema.py
    ├── normalize.py
    ├── neo4j_writer.py
    ├── pipeline.py
    └── …
```

Each stage is **independently runnable** and **independently resumable**.

---

## 5. Design Decisions and Rationale

| Decision | Rationale |
|---|---|
| **Multiprocessing, not threading** | PDF parsing, OCR, and Python LLM calls release the GIL poorly. Multiprocessing gives true parallelism on the CPU-bound steps. |
| **NDJSON, not JSON arrays** | Append-only writes; resumable; pipeable; trivial to stream. Per-doc files were considered but rejected (filesystem overhead at scale). |
| **SQLite WAL per stage** | Crash-safe resume without external services. Cheap, single-file, ~zero ops. |
| **Content-hashed chunk_id** | Idempotent joins across stages; lets you re-run any stage without duplicate downstream work. |
| **Whitespace tokenizer (Stage 2)** | Embedding-free, zero-dep, deterministic. Subword tokenizers (BPE/SentencePiece) would tie us to a model version. |
| **Token windows, not sentence-boundary chunking** | Domain text (technical Russian) often lacks clean sentence boundaries. Windows give stable, predictable chunk sizes. |
| **Cyrillic-aware canonicalization (Stage 4)** | Same entity may appear in 5+ surface forms. Without normalization, graph explodes with near-duplicates. |
| **Two-call extraction (extract + judge)** | A single LLM call cannot reliably self-validate grounding. Splitting the check is the cheapest way to enforce the no-hallucination rule. |
| **Collector thread for writes** | Eliminates file-handle contention from N worker processes writing simultaneously. |
| **Pydantic v2 strict** | Catches schema drift at the boundary, not deep in the pipeline. |
| **`MERGE` on `canonical_key`** | Natural idempotency in Cypher. Constraints back it up at the database level. |
| **`temperature=0.0`** | Deterministic outputs for reproducibility. |
| **Evidence required on every relation** | Downstream reasoning (Stage 5) must cite source. No evidence → no graph edge. |

---

## 6. Implementation Status

| Stage | Status | Notes |
|---|---|---|
| **Stage 1 — ETL** | ✅ Complete | Tested code paths: PDF text-layer, DOCX, TXT (CP1251/UTF-8), OCR fallback, scanned detection, multiprocessing, SQLite resume. |
| **Stage 2 — Chunking** | ✅ Complete | Streaming NDJSON, normalizer, windowed chunker, page tracking, heading detection, deterministic IDs. |
| **Stage 3 — Extraction** | ✅ Complete | Anthropic async client, RU prompt + few-shot, Pydantic schema, grounding judge, multiprocess + async. |
| **Stage 4 — Graph** | ✅ Complete | Normalization, dedup, UNWIND batch writer, constraints, reject log, CLI. |
| **Stage 5 — Retrieval** | ⏳ Planned | Architecture defined; modules not yet implemented. |

### Resumability

Each stage writes a SQLite WAL manifest. Re-running a stage:
- Skips chunks/docs with `status='ok'` in the manifest.
- Re-attempts chunks/docs marked `failed` or `rejected`.

### Failure isolation

- Stage 1: per-file try/except; errors stored in `metadata.error`.
- Stage 2: per-record try/except; failures counted in stats.
- Stage 3: rejected chunks routed to sidecar NDJSON, never lost.
- Stage 4: ambiguous/empty entities routed to `graph_rejected.ndjson`; flush failures also logged there.

---

## 7. Environment & Dependencies

### Environment variables

| Var | Required by | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | Stage 3 | Claude API access |
| `NEO4J_PASSWORD` | Stage 4 | Neo4j authentication |

### OS-level dependencies

- **Tesseract** binary with `rus` language pack (Stage 1 OCR):
  - Ubuntu: `apt-get install tesseract-ocr tesseract-ocr-rus`
  - Windows: `choco install tesseract` + manual rus traineddata
- **Neo4j 5.x** server (Stage 4), reachable on `bolt://localhost:7687`.

### Python dependencies (per stage)

- **Stage 1:** `PyMuPDF`, `python-docx`, `Pillow`
- **Stage 2:** (no external deps; stdlib only)
- **Stage 3:** `pydantic>=2.6`, `httpx>=0.27`
- **Stage 4:** `neo4j>=5.20`

---

## 8. Next Steps for Devin AI

### 8.1 Stage 5 — Hybrid Retrieval (priority)

**Module:** `ingest/retrieval/`

1. **Qdrant indexer** (`qdrant_indexer.py`):
   - Stream Stage 2 NDJSON.
   - Embed chunks (decide embedding model — Voyage AI `voyage-3` or local `BAAI/bge-m3` for RU).
   - Upsert to Qdrant with payload `{document_id, chunk_id, page_range, heading, filename}`.

2. **Query router** (`query_router.py`):
   - Opus 4.8 classifies query intent: `graph` / `vector` / `hybrid`.
   - System prompt includes the Stage 4 schema.

3. **Cypher generator** (`cypher_generator.py`):
   - Opus 4.8 generates Cypher from natural language.
   - Schema context injected from a runtime introspection of Neo4j.

4. **Vector search** (`vector_search.py`):
   - Qdrant dense retrieval, configurable top-k.
   - Filter by metadata (file_type, is_scanned, etc.).

5. **Fusion engine** (`fusion.py`):
   - Reciprocal Rank Fusion (RRF) with k=60.
   - Deduplicate by `chunk_id`.

6. **Reasoner** (`reasoner.py`):
   - Opus 4.8 final answer.
   - System prompt: "Answer ONLY using the provided context. Cite chunk_id for every claim."

7. **Orchestrator** (`pipeline.py` + `__main__.py`):
   - CLI mode: `python -m ingest.retrieval --query "..."`
   - Optional FastAPI server for integration.

### 8.2 Hardening tasks (across stages)

- **Stage 3:** Add cost/latency tracking per chunk; export to a metrics NDJSON.
- **Stage 4:** Add Cypher query templates for common metallurgy questions ("Какие процессы извлекают медь из руд с содержанием < 1%?").
- **All stages:** Add a `--dry-run` mode that prints stats without writing.
- **All stages:** Add per-stage Prometheus exporter.

### 8.3 Known limitations

- **Stage 4 relation classification** is heuristic — it uses Russian keyword matching on relation text. For higher precision, route this through Stage 3 (i.e., have the LLM emit rel_type directly in the allowed set).
- **No PDF table extraction** in Stage 1. If your corpus has many scientific tables, add `camelot-py` or `tabula-py` and emit a `tables[]` field in the document JSON.
- **Single-language OCR**: Tesseract is configured for `eng+rus`. For Kazakh (kaz) or Ukrainian (ukr) docs, update `cfg.ocr_language`.

### 8.4 Suggested test corpus

For regression testing, build a small golden set:
- 3 PDFs (1 native, 1 scanned, 1 mixed)
- 2 DOCX files (one with tables)
- 1 TXT in CP1251

Run all four stages end-to-end and snapshot:
- `chunks.ndjson` first 100 lines
- `extracted.ndjson` first 50 records
- Neo4j node/edge counts

These snapshots are the regression suite.

---

## 9. Glossary

| Term | Definition |
|---|---|
| **canonical_key** | Stable lowercase+stemmed identifier used for MERGE idempotency in Neo4j. |
| **chunk_id** | SHA-256 of `(document_id, chunk_index, text)[:32]`. Content-addressed. |
| **document_id** | SHA-256 of file bytes. |
| **grounding judge** | Second LLM call that scores whether an extraction is faithful to the source text. |
| **RRF** | Reciprocal Rank Fusion — standard technique for combining ranked lists. |
| **WAL** | Write-Ahead Logging (SQLite mode for crash-safe concurrent access). |
| **UNWIND** | Cypher clause that turns a list parameter into rows — basis of batched writes. |

---

## 10. Contact Points for Handoff

- **Architectural questions:** refer to §2 (data flow) and §3 (stage specs).
- **Adding a new entity type:** edit `ingest/graph/schema.py` (add label + constraint + UNWIND template).
- **Adding a new stage:** follow the pattern in `ingest/chunker/` or `ingest/extractor/` — config + streamer + writer + pipeline + `__main__.py`.
- **Changing the LLM provider:** swap `ingest/extractor/llm_client.py`; keep the `AnthropicClient` interface stable.
- **Changing the graph DB:** swap `ingest/graph/neo4j_writer.py`; preserve the `MERGE`-on-canonical-key semantics.

---

*End of document. Next handoff target: Stage 5 retrieval module.*
