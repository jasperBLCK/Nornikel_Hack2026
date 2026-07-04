"""Stage 2 orchestrator.

Streaming-friendly: reads Stage 1 NDJSON line-by-line, batches documents
into worker tasks (one task = many documents), preserves deterministic
chunk ordering per document.

For millions of chunks, the bottleneck is usually the WRITER. We use:
  - One background writer thread for sequential append.
  - A bounded queue between workers and writer to apply backpressure.
  - SQLite manifest for resume across crashes.
"""
from __future__ import annotations

import json
import logging
import multiprocessing as mp
import time
from dataclasses import dataclass
from pathlib import Path
from ingest.chunker.chunker import chunk_document
from ingest.chunker.config import ChunkConfig
from ingest.chunker.manifest import ChunkManifest
from ingest.chunker.streamer import iter_documents
from ingest.chunker.writer import ChunkWriter

logger = logging.getLogger(__name__)


@dataclass
class ChunkRunStats:
    documents_read: int = 0
    documents_skipped: int = 0
    documents_chunked: int = 0
    chunks_written: int = 0
    errors: int = 0
    elapsed_sec: float = 0.0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


# --- Worker (top-level for Windows pickling) -------------------------------


def _worker_process_documents(args):
    """Process a batch of documents → return list of (document_id, [chunk_dicts])."""
    documents, cfg_dict = args
    cfg = ChunkConfig(
        input_ndjson=Path(cfg_dict["input_ndjson"]),
        output_ndjson=Path(cfg_dict["output_ndjson"]),
        manifest_db=Path(cfg_dict["manifest_db"]),
        chunk_min_tokens=cfg_dict["chunk_min_tokens"],
        chunk_max_tokens=cfg_dict["chunk_max_tokens"],
        chunk_overlap_tokens=cfg_dict["chunk_overlap_tokens"],
        heading_pattern=cfg_dict["heading_pattern"],
        workers=1,
        fix_hyphenation=cfg_dict["fix_hyphenation"],
        collapse_whitespace=cfg_dict["collapse_whitespace"],
        strip_ocr_artifacts=cfg_dict["strip_ocr_artifacts"],
    )
    out: list[tuple[str, list[dict]]] = []
    for doc in documents:
        try:
            chunks = list(chunk_document(doc, cfg))
            out.append((doc.get("document_id", ""), chunks))
        except Exception as e:
            logger.exception("chunking failed for %s", doc.get("document_id"))
            out.append((doc.get("document_id", ""), [{"__error__": f"{type(e).__name__}: {e}"}]))
    return out


def _cfg_to_dict(cfg: ChunkConfig) -> dict:
    return {
        "input_ndjson": str(cfg.input_ndjson),
        "output_ndjson": str(cfg.output_ndjson),
        "manifest_db": str(cfg.manifest_db),
        "chunk_min_tokens": cfg.chunk_min_tokens,
        "chunk_max_tokens": cfg.chunk_max_tokens,
        "chunk_overlap_tokens": cfg.chunk_overlap_tokens,
        "heading_pattern": cfg.heading_pattern,
        "fix_hyphenation": cfg.fix_hyphenation,
        "collapse_whitespace": cfg.collapse_whitespace,
        "strip_ocr_artifacts": cfg.strip_ocr_artifacts,
    }


# --- Public entrypoint -----------------------------------------------------


def run(cfg: ChunkConfig, batch_size: int = 64) -> ChunkRunStats:
    """Stream the input NDJSON, chunk each document, append chunks to output."""
    started = time.monotonic()
    stats = ChunkRunStats()

    if not cfg.input_ndjson.exists():
        raise FileNotFoundError(f"Input NDJSON not found: {cfg.input_ndjson}")

    manifest = ChunkManifest(cfg.manifest_db)
    writer = ChunkWriter(cfg.output_ndjson)

    cfg_dict = _cfg_to_dict(cfg)

    # Optional: pre-load IDs to skip already-done documents.
    # For very large corpora, we do this in batches to bound memory.
    def _already_done(doc_id: str) -> bool:
        return manifest.is_done(doc_id)

    batch: list[dict] = []
    workers = max(1, cfg.workers)

    pool = None
    if workers > 1:
        pool = mp.Pool(processes=workers)

    try:
        pending_results: list = []  # list of async results / direct outputs

        def _drain_one(result, stats: ChunkRunStats):
            for doc_id, chunks in result:
                if not chunks:
                    stats.documents_skipped += 1
                    manifest.mark(doc_id, 0)
                    continue
                # Error sentinel?
                if len(chunks) == 1 and "__error__" in chunks[0]:
                    stats.errors += 1
                    manifest.mark(doc_id, 0)
                    continue
                for ch in chunks:
                    writer.write(ch)
                manifest.mark(doc_id, len(chunks))
                stats.documents_chunked += 1
                stats.chunks_written += len(chunks)

        for doc in iter_documents(cfg.input_ndjson):
            stats.documents_read += 1
            doc_id = doc.get("document_id", "")
            if not doc_id:
                continue
            if _already_done(doc_id):
                stats.documents_skipped += 1
                continue

            batch.append(doc)
            if len(batch) >= batch_size:
                if pool is not None:
                    pending_results.append(
                        pool.apply_async(_worker_process_documents, ((batch, cfg_dict),))
                    )
                else:
                    result = _worker_process_documents((batch, cfg_dict))
                    _drain_one(result, stats)
                batch = []

                # Periodically harvest completed async results.
                if pool is not None and len(pending_results) >= workers * 2:
                    still_pending = []
                    for r in pending_results:
                        if r.ready():
                            _drain_one(r.get(), stats)
                        else:
                            still_pending.append(r)
                    pending_results = still_pending

        # Flush trailing batch.
        if batch:
            if pool is not None:
                pending_results.append(
                    pool.apply_async(_worker_process_documents, ((batch, cfg_dict),))
                )
            else:
                _drain_one(_worker_process_documents((batch, cfg_dict)), stats)

        # Drain remaining async results.
        if pool is not None:
            for r in pending_results:
                _drain_one(r.get(), stats)
    finally:
        if pool is not None:
            pool.close()
            pool.join()
        writer.close()
        manifest.close()

    stats.elapsed_sec = time.monotonic() - started
    logger.info("Chunking done: %s", stats.as_dict())
    return stats