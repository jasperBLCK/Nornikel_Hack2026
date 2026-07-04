"""Build a local vector index over Stage 2 chunks (no API cost).

    python -m search.indexer --input hydrax_out/stage2_chunks/chunks.ndjson

Uses Qdrant in embedded mode (local folder, no Docker needed) and
fastembed ONNX multilingual embeddings (~120 MB model, downloaded once).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from qdrant_client import QdrantClient

COLLECTION = "hydrax_chunks"
EMBED_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
DEFAULT_DB = "./hydrax_out/qdrant_data"
BATCH = 256


def iter_chunks(path: Path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def main() -> int:
    p = argparse.ArgumentParser(description="Index chunks into local Qdrant.")
    p.add_argument("--input", required=True)
    p.add_argument("--db", default=DEFAULT_DB)
    p.add_argument("--skip-if-complete", action="store_true",
                   help="Не переиндексировать, если в коллекции уже >= чанков, чем во входном файле")
    args = p.parse_args()

    inp = Path(args.input)
    if not inp.exists():
        sys.exit(f"ERROR: input not found: {inp}")

    client = QdrantClient(path=args.db)

    if args.skip_if_complete:
        expected = sum(1 for ch in iter_chunks(inp) if ch.get("text"))
        try:
            existing = client.count(collection_name=COLLECTION).count
        except Exception:
            existing = 0
        if expected > 0 and existing >= expected:
            print(json.dumps({"indexed": 0, "skipped": True,
                              "existing": existing, "expected": expected}))
            return 0

    client.set_model(EMBED_MODEL)

    started = time.monotonic()
    docs: list[str] = []
    metas: list[dict] = []
    ids: list[str] = []
    total = 0

    def flush():
        nonlocal docs, metas, ids, total
        if not docs:
            return
        client.add(collection_name=COLLECTION, documents=docs,
                   metadata=metas, ids=ids)
        total += len(docs)
        print(f"  indexed {total} chunks ({time.monotonic()-started:.0f}s)", flush=True)
        docs, metas, ids = [], [], []

    for ch in iter_chunks(inp):
        text = ch.get("text", "")
        if not text:
            continue
        meta = ch.get("metadata") or {}
        docs.append(text[:4000])
        metas.append({
            "document_id": ch.get("document_id", ""),
            "chunk_id": ch.get("chunk_id", ""),
            "filename": meta.get("filename", ""),
            "text": text[:4000],
        })
        ids.append(ch.get("chunk_id", ""))
        if len(docs) >= BATCH:
            flush()
    flush()

    print(json.dumps({"indexed": total,
                      "elapsed_sec": round(time.monotonic() - started, 1)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
