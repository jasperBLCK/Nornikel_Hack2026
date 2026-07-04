"""Stage 3 orchestrator.

Multiprocess worker pool. Each worker runs its own asyncio event loop and
an Async Anthropic client with internal semaphore for concurrency control.

Topology:
  Main process: streams NDJSON, batches chunks, dispatches to pool.
  Workers:      run an async extract loop, write results through a
                multiprocess-safe queue.
  Collector:    single background thread that consumes the queue and
                writes JSONL files (avoids file-handle contention).

The queue + collector pattern is what we use instead of Ray here so that
the orchestrator has zero non-stdlib deps for the run-time side. Switch
to Ray later if you need cross-machine scheduling.
"""
from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing as mp
import queue as stdqueue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ingest.extractor.config import ExtractorConfig
from ingest.extractor.extract import extract_chunk
from ingest.extractor.llm_client import AnthropicClient
from ingest.extractor.manifest import ExtractorManifest
from ingest.extractor.streamer import iter_chunks
from ingest.extractor.writer import ExtractedWriter

logger = logging.getLogger(__name__)


# ---- Queue message types -------------------------------------------------

_MSG_OK = "ok"
_MSG_REJECT = "reject"
_MSG_ERROR = "error"
_MSG_DONE = "done"


def _msg_ok(record_dict: dict) -> dict:
    return {"kind": _MSG_OK, "record": record_dict}


def _msg_reject(document_id: str, chunk_id: str, raw: dict | None, reason: str) -> dict:
    return {"kind": _MSG_REJECT, "document_id": document_id, "chunk_id": chunk_id,
            "raw": raw, "reason": reason}


def _msg_error(document_id: str, chunk_id: str, err: str) -> dict:
    return {"kind": _MSG_ERROR, "document_id": document_id, "chunk_id": chunk_id,
            "error": err}


# ---- Worker (top-level for pickling on Windows) ---------------------------


def _worker_main(cfg_dict: dict, in_q: mp.Queue, out_q: mp.Queue) -> None:
    """One worker process. Each owns an asyncio loop + Anthropic client."""
    cfg = ExtractorConfig(
        input_ndjson=Path(cfg_dict["input_ndjson"]),
        output_ndjson=Path(cfg_dict["output_ndjson"]),
        rejected_ndjson=Path(cfg_dict["rejected_ndjson"]),
        manifest_db=Path(cfg_dict["manifest_db"]),
        model=cfg_dict["model"],
        api_key_env=cfg_dict["api_key_env"],
        api_base=cfg_dict["api_base"],
        anthropic_version=cfg_dict["anthropic_version"],
        max_input_tokens=cfg_dict["max_input_tokens"],
        max_output_tokens=cfg_dict["max_output_tokens"],
        temperature=cfg_dict["temperature"],
        request_timeout_sec=cfg_dict["request_timeout_sec"],
        max_retries=cfg_dict["max_retries"],
        workers=cfg_dict["workers"],
        async_concurrency=cfg_dict["async_concurrency"],
        enable_grounding_judge=cfg_dict["enable_grounding_judge"],
        grounding_judge_model=cfg_dict["grounding_judge_model"],
        grounding_min_score=cfg_dict["grounding_min_score"],
        grounding_max_calls_per_chunk=cfg_dict["grounding_max_calls_per_chunk"],
        batch_size=cfg_dict["batch_size"],
        log_level=cfg_dict["log_level"],
    )

    # Per-worker logging config (child processes have their own root logger).
    logging.basicConfig(
        level=getattr(logging, cfg.log_level.upper(), logging.INFO),
        format=f"[worker pid={mp.current_process().pid}] %(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    async def _runner():
        client = AnthropicClient(cfg)
        try:
            while True:
                batch = in_q.get()
                if batch is None:
                    break
                # Each batch is a list of chunks; we extract them concurrently
                # up to cfg.async_concurrency.
                sem = asyncio.Semaphore(cfg.async_concurrency)

                async def _one(item):
                    document_id = item["document_id"]
                    chunk_id = item["chunk_id"]
                    text = item["text"]
                    async with sem:
                        try:
                            record, raw, reason = await extract_chunk(
                                client, cfg, document_id, chunk_id, text
                            )
                            if record is not None:
                                out_q.put(_msg_ok(record.model_dump()))
                            else:
                                out_q.put(_msg_reject(document_id, chunk_id, raw, reason or "unknown"))
                        except Exception as e:
                            out_q.put(_msg_error(document_id, chunk_id, f"{type(e).__name__}: {e}"))

                await asyncio.gather(*[_one(it) for it in batch])
        finally:
            await client.close()
            out_q.put({"kind": _MSG_DONE})

    asyncio.run(_runner())


def _cfg_to_dict(cfg: ExtractorConfig) -> dict:
    return {
        "input_ndjson": str(cfg.input_ndjson),
        "output_ndjson": str(cfg.output_ndjson),
        "rejected_ndjson": str(cfg.rejected_ndjson),
        "manifest_db": str(cfg.manifest_db),
        "model": cfg.model,
        "api_key_env": cfg.api_key_env,
        "api_base": cfg.api_base,
        "anthropic_version": cfg.anthropic_version,
        "max_input_tokens": cfg.max_input_tokens,
        "max_output_tokens": cfg.max_output_tokens,
        "temperature": cfg.temperature,
        "request_timeout_sec": cfg.request_timeout_sec,
        "max_retries": cfg.max_retries,
        "workers": cfg.workers,
        "async_concurrency": cfg.async_concurrency,
        "enable_grounding_judge": cfg.enable_grounding_judge,
        "grounding_judge_model": cfg.grounding_judge_model,
        "grounding_min_score": cfg.grounding_min_score,
        "grounding_max_calls_per_chunk": cfg.grounding_max_calls_per_chunk,
        "batch_size": cfg.batch_size,
        "log_level": cfg.log_level,
    }


# ---- Run stats ------------------------------------------------------------


@dataclass
class ExtractorStats:
    chunks_read: int = 0
    chunks_skipped_existing: int = 0
    chunks_ok: int = 0
    chunks_rejected: int = 0
    chunks_error: int = 0
    elapsed_sec: float = 0.0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


# ---- Public entrypoint ----------------------------------------------------


def run(cfg: ExtractorConfig) -> ExtractorStats:
    started = time.monotonic()
    stats = ExtractorStats()

    if not cfg.input_ndjson.exists():
        raise FileNotFoundError(f"Input NDJSON not found: {cfg.input_ndjson}")

    manifest = ExtractorManifest(cfg.manifest_db)
    writer = ExtractedWriter(cfg.output_ndjson, cfg.rejected_ndjson)
    cfg_dict = _cfg_to_dict(cfg)

    in_q: mp.Queue = mp.Queue(maxsize=cfg.workers * 2)
    out_q: mp.Queue = mp.Queue(maxsize=1024)

    procs: list[mp.Process] = []
    for _ in range(cfg.workers):
        p = mp.Process(target=_worker_main, args=(cfg_dict, in_q, out_q), daemon=True)
        p.start()
        procs.append(p)

    # Collector thread: drains out_q and writes JSONL.
    done_workers = 0
    stop_collector = threading.Event()

    def _collector():
        nonlocal done_workers
        while not (stop_collector.is_set() and done_workers == cfg.workers):
            try:
                msg = out_q.get(timeout=0.5)
            except stdqueue.Empty:
                continue
            kind = msg.get("kind")
            if kind == _MSG_DONE:
                done_workers += 1
                continue
            if kind == _MSG_OK:
                rec = msg["record"]
                writer.write_ok(rec)
                manifest.mark(
                    chunk_id=rec["chunk_id"],
                    document_id=rec["document_id"],
                    status="ok",
                    grounding_score=rec.get("grounding_score"),
                )
                stats.chunks_ok += 1
            elif kind == _MSG_REJECT:
                writer.write_rejected(msg["document_id"], msg["chunk_id"], msg.get("raw"), msg["reason"])
                manifest.mark(
                    chunk_id=msg["chunk_id"],
                    document_id=msg["document_id"],
                    status="rejected",
                    reason=msg["reason"],
                )
                stats.chunks_rejected += 1
            elif kind == _MSG_ERROR:
                writer.write_rejected(msg["document_id"], msg["chunk_id"], None, msg["error"])
                manifest.mark(
                    chunk_id=msg["chunk_id"],
                    document_id=msg["document_id"],
                    status="error",
                    reason=msg["error"],
                )
                stats.chunks_error += 1

    th = threading.Thread(target=_collector, daemon=True)
    th.start()

    # Stream chunks, batch, dispatch.
    try:
        batch: list[dict] = []
        for ch in iter_chunks(cfg.input_ndjson):
            stats.chunks_read += 1
            chunk_id = ch.get("chunk_id", "")
            document_id = ch.get("document_id", "")
            text = ch.get("text", "")
            if not chunk_id or not document_id or not text:
                continue
            if manifest.is_done(chunk_id):
                stats.chunks_skipped_existing += 1
                continue

            batch.append({"document_id": document_id, "chunk_id": chunk_id, "text": text})
            if len(batch) >= cfg.batch_size:
                in_q.put(batch)
                batch = []

        if batch:
            in_q.put(batch)

        # Tell workers to stop.
        for _ in procs:
            in_q.put(None)
    finally:
        # Wait for all workers to finish.
        for p in procs:
            p.join()
        stop_collector.set()
        th.join()

        writer.close()
        manifest.close()

    stats.elapsed_sec = time.monotonic() - started
    logger.info("Extraction done: %s", stats.as_dict())
    return stats