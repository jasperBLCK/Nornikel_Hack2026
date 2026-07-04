"""
HydraX end-to-end runner.

Делает все 4 стадии подряд:
  Stage 1: ETL (PDF/DOCX/TXT → documents.ndjson)
  Stage 2: Chunking (→ chunks.ndjson)
  Stage 3: Extraction (LLM, → extracted.ndjson + rejected.ndjson)
  Stage 4: Neo4j ingestion (→ graph)

Использование (Windows PowerShell):
    $env:ANTHROPIC_API_KEY = "sk-ant-..."
    $env:NEO4J_PASSWORD   = "testpass"   # необязательно, testpass — значение по умолчанию
    python run_pipeline.py

Опциональные аргументы (через переменные окружения или редактирование DEFAULT):
    HYDRAX_INPUT   — папка с документами (default: ./corpus)
    HYDRAX_OUTPUT  — папка для всех стадий (default: ./hydrax_out)
    HYDRAX_NEO4J_URI  (default: bolt://localhost:7687)
    HYDRAX_NEO4J_USER (default: neo4j)
    HYDRAX_NEO4J_DB   (default: neo4j)
    HYDRAX_WORKERS    (default: max(1, cpu-1))
    HYDRAX_EXTRACTOR=local|llm — Stage 3 режим (default: local — без вызовов LLM)
    HYDRAX_SKIP_EXTRACTION=1 — пропустить Stage 3 (нужен уже готовый extracted.ndjson)
    HYDRAX_SKIP_GRAPH=1      — пропустить Stage 4
    HYDRAX_SKIP_INDEX=1      — пропустить Stage 5 (векторный индекс)
    HYDRAX_FORCE=1           — принудительно пересчитать все стадии

Инкрементальность: каждая стадия пропускается, если её артефакт уже
существует и не старше своих входных данных (Stage 4 дополнительно
проверяет, что граф в Neo4j действительно не пуст). Повторный запуск
на готовой папке hydrax_out завершается за секунды.
"""
import os
import sys
import time
import shutil
import subprocess
from pathlib import Path

# ---- Defaults (override via env or edit here) ----------------------------

DEFAULT_INPUT   = Path(os.environ.get("HYDRAX_INPUT",  "./corpus"))
DEFAULT_OUTPUT  = Path(os.environ.get("HYDRAX_OUTPUT", "./hydrax_out"))
NEO4J_URI       = os.environ.get("HYDRAX_NEO4J_URI",  "bolt://localhost:7687")
NEO4J_USER      = os.environ.get("HYDRAX_NEO4J_USER", "neo4j")
NEO4J_DB        = os.environ.get("HYDRAX_NEO4J_DB",   "neo4j")
WORKERS         = int(os.environ.get("HYDRAX_WORKERS", str(max(1, (os.cpu_count() or 4) - 1))))
EXTRACTOR_MODE  = os.environ.get("HYDRAX_EXTRACTOR", "local")  # local | llm
SKIP_EXTRACTION = os.environ.get("HYDRAX_SKIP_EXTRACTION", "0") == "1"
SKIP_GRAPH      = os.environ.get("HYDRAX_SKIP_GRAPH",      "0") == "1"
SKIP_INDEX      = os.environ.get("HYDRAX_SKIP_INDEX",      "0") == "1"
FORCE           = os.environ.get("HYDRAX_FORCE",           "0") == "1"

# ---- Paths ---------------------------------------------------------------

INPUT  = Path(DEFAULT_INPUT).resolve()
OUTPUT = Path(DEFAULT_OUTPUT).resolve()

S1_DIR  = OUTPUT / "stage1_etl"
S2_DIR  = OUTPUT / "stage2_chunks"
S3_DIR  = OUTPUT / "stage3_extraction"
S4_DIR  = OUTPUT / "stage4_graph"

S1_DOCS = S1_DIR / "documents.ndjson"
S2_CHUNKS = S2_DIR / "chunks.ndjson"
S3_EXTRACTED = S3_DIR / "extracted.ndjson"
S3_REJECTED  = S3_DIR / "extracted.rejected.ndjson"
S4_REJECTS   = S4_DIR / "graph_rejected.ndjson"

PY = sys.executable


def banner(msg: str) -> None:
    print()
    print("=" * 78)
    print(f"  {msg}")
    print("=" * 78)


def run_module(args: list[str], env: dict | None = None) -> int:
    """Run `python -m <args>` and stream output. Returns exit code."""
    full_env = os.environ.copy()
    if env:
        full_env.update(env)
    print(f"\n>> {' '.join(args)}\n")
    proc = subprocess.run([PY, "-m", *args], env=full_env)
    return proc.returncode


def newest_mtime(root: Path) -> float:
    """Newest mtime across all files under root (or the file itself)."""
    if root.is_file():
        return root.stat().st_mtime
    latest = 0.0
    for p in root.rglob("*"):
        if p.is_file():
            latest = max(latest, p.stat().st_mtime)
    return latest


def is_fresh(output: Path, *inputs: Path) -> bool:
    """True if output exists, is non-empty and is not older than any input."""
    if FORCE or not output.exists() or output.stat().st_size == 0:
        return False
    out_mtime = output.stat().st_mtime
    return all(newest_mtime(i) <= out_mtime for i in inputs if i.exists())


def graph_node_count() -> int:
    """Node count in Neo4j; -1 if unreachable."""
    try:
        from neo4j import GraphDatabase
        auth = (NEO4J_USER, os.environ.get("NEO4J_PASSWORD", "testpass"))
        with GraphDatabase.driver(NEO4J_URI, auth=auth) as driver:
            recs, _, _ = driver.execute_query(
                "MATCH (n) RETURN count(n) AS c", database_=NEO4J_DB)
            return recs[0]["c"]
    except Exception as e:
        print(f"WARN: cannot query Neo4j node count: {e}")
        return -1


def need_tesseract() -> bool:
    return shutil.which("tesseract") is None


def preflight() -> None:
    banner("PREFLIGHT")
    if not INPUT.exists():
        sys.exit(f"ERROR: input folder not found: {INPUT}")
    if (not os.environ.get("ANTHROPIC_API_KEY") and not SKIP_EXTRACTION
            and EXTRACTOR_MODE == "llm"):
        sys.exit("ERROR: ANTHROPIC_API_KEY not set (required for Stage 3 llm mode).")
    if not os.environ.get("NEO4J_PASSWORD") and not SKIP_GRAPH:
        os.environ["NEO4J_PASSWORD"] = "testpass"
        print("WARN: NEO4J_PASSWORD not set — using default 'testpass'.")
    if need_tesseract() and not SKIP_EXTRACTION is False:
        # only fatal if extraction runs (OCR may be needed)
        print("WARN: tesseract not in PATH — OCR for scanned PDFs will fail.")


def stage1() -> int:
    banner("STAGE 1 — ETL (PDF / DOCX / TXT → documents.ndjson)")
    if is_fresh(S1_DOCS, INPUT):
        print(f"[skip] Stage 1 — {S1_DOCS} актуален ({count_lines(S1_DOCS)} документов)")
        return 0
    S1_DIR.mkdir(parents=True, exist_ok=True)
    rc = run_module([
        "ingest.run",
        "--input",  str(INPUT),
        "--output", str(S1_DIR),
        "--workers", str(WORKERS),
        "--ocr-lang", "eng+rus",
    ])
    if rc != 0:
        return rc
    n = count_lines(S1_DOCS)
    print(f"\n[stage1] {n} documents written → {S1_DOCS}")
    return 0


def stage2() -> int:
    banner("STAGE 2 — Chunking & Normalization")
    if not S1_DOCS.exists():
        return 1
    if is_fresh(S2_CHUNKS, S1_DOCS):
        print(f"[skip] Stage 2 — {S2_CHUNKS} актуален ({count_lines(S2_CHUNKS)} чанков)")
        return 0
    S2_DIR.mkdir(parents=True, exist_ok=True)
    rc = run_module([
        "ingest.chunker",
        "--input",  str(S1_DOCS),
        "--output", str(S2_CHUNKS),
        "--min-tokens", "800",
        "--max-tokens", "1500",
        "--overlap",    "200",
        "--workers",    str(WORKERS),
    ])
    if rc != 0:
        return rc
    n = count_lines(S2_CHUNKS)
    print(f"\n[stage2] {n} chunks written → {S2_CHUNKS}")
    return 0


def stage3() -> int:
    if not S2_CHUNKS.exists():
        return 1
    if is_fresh(S3_EXTRACTED, S2_CHUNKS):
        banner("STAGE 3 — Extraction")
        print(f"[skip] Stage 3 — {S3_EXTRACTED} актуален ({count_lines(S3_EXTRACTED)} записей)")
        return 0
    S3_DIR.mkdir(parents=True, exist_ok=True)
    if EXTRACTOR_MODE == "local":
        banner("STAGE 3 — Local Extraction (rules, no LLM)")
        rc = run_module([
            "ingest.local_extractor",
            "--input",  str(S2_CHUNKS),
            "--output", str(S3_EXTRACTED),
        ])
        if rc != 0:
            return rc
        print(f"\n[stage3] {count_lines(S3_EXTRACTED)} records → {S3_EXTRACTED}")
        return 0
    banner("STAGE 3 — LLM Extraction (Claude)")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return 1
    rc = run_module([
        "ingest.extractor",
        "--input",  str(S2_CHUNKS),
        "--output", str(S3_EXTRACTED),
        "--model", "claude-sonnet-5",
        "--workers", str(max(1, WORKERS // 2)),
        "--async-concurrency", "4",
        "--batch-size", "32",
    ])
    if rc != 0:
        return rc
    ok = count_lines(S3_EXTRACTED)
    rej = count_lines(S3_REJECTED) if S3_REJECTED.exists() else 0
    print(f"\n[stage3] ok={ok}  rejected={rej}  → {S3_EXTRACTED}")
    return 0


def stage4() -> int:
    banner("STAGE 4 — Neo4j Graph Ingestion")
    if not S3_EXTRACTED.exists():
        return 1
    stamp = S4_DIR / ".ingested"
    if is_fresh(stamp, S3_EXTRACTED):
        nodes = graph_node_count()
        if nodes > 0:
            print(f"[skip] Stage 4 — граф уже загружен ({nodes} узлов)")
            return 0
        print("[stage4] граф пуст (новый Neo4j?) — загружаем заново")
    S4_DIR.mkdir(parents=True, exist_ok=True)
    rc = run_module([
        "ingest.graph",
        "--input",  str(S3_EXTRACTED),
        "--uri",    NEO4J_URI,
        "--user",   NEO4J_USER,
        "--database", NEO4J_DB,
        "--node-batch-size", "1000",
        "--rel-batch-size",  "1000",
    ])
    if rc != 0:
        return rc
    rej = count_lines(S4_REJECTS) if S4_REJECTS.exists() else 0
    (S4_DIR / ".ingested").write_text(str(int(time.time())))
    print(f"\n[stage4] done.  rejected={rej}")
    return 0


def stage5_index() -> int:
    banner("STAGE 5 — Vector Index (local embeddings)")
    if not S2_CHUNKS.exists():
        return 1
    stamp = OUTPUT / "qdrant_data" / ".indexed"
    if is_fresh(stamp, S2_CHUNKS):
        print("[skip] Stage 5 — векторный индекс актуален (не трогаем embedded Qdrant)")
        return 0
    rc = run_module([
        "search.indexer",
        "--input", str(S2_CHUNKS),
        "--db", str(OUTPUT / "qdrant_data"),
        "--skip-if-complete",
    ])
    if rc == 0:
        stamp.write_text(str(int(time.time())))
    return rc


def count_lines(p: Path) -> int:
    if not p.exists():
        return 0
    with open(p, "rb") as f:
        return sum(1 for _ in f)


def main() -> int:
    t0 = time.monotonic()
    preflight()
    OUTPUT.mkdir(parents=True, exist_ok=True)

    rc = stage1()
    if rc != 0: sys.exit(rc)

    rc = stage2()
    if rc != 0: sys.exit(rc)

    if not SKIP_EXTRACTION:
        rc = stage3()
        if rc != 0: sys.exit(rc)
    else:
        print("\n[skip] Stage 3 — using existing extracted.ndjson")

    if not SKIP_GRAPH:
        rc = stage4()
        if rc != 0: sys.exit(rc)
    else:
        print("\n[skip] Stage 4")

    if not SKIP_INDEX:
        rc = stage5_index()
        if rc != 0: sys.exit(rc)
    else:
        print("\n[skip] Stage 5")

    banner(f"DONE in {time.monotonic() - t0:.1f}s")
    print(f"  Stage 1: {S1_DIR}")
    print(f"  Stage 2: {S2_DIR}")
    print(f"  Stage 3: {S3_DIR}")
    print(f"  Stage 4: {S4_DIR}")
    print(f"  Stage 5: {OUTPUT / 'qdrant_data'}")
    print("\n  Веб-интерфейс:  uvicorn app.main:app --port 8000")
    return 0


if __name__ == "__main__":
    sys.exit(main())
