"""Multiprocessing orchestrator.

Topology:
  - Main process: scans the input folder, hashes file headers for cheap
    dedup, dispatches tasks to a process pool, writes results.
  - Workers: run process_file() on a single file, return a Document.
  - Shared state: SQLite manifest (file-backed, WAL mode).

Why multiprocessing, not threading:
  - CPU-bound PDF parsing & OCR releases the GIL poorly.
  - The task is embarrassingly parallel — one file per worker, no IPC.
"""
from __future__ import annotations

import logging
import multiprocessing as mp
import time
from dataclasses import dataclass
from typing import Iterable

from ingest.config import IngestConfig
from ingest.hashing import make_document_id, sha256_file
from ingest.manifest import Manifest
from ingest.scanner import ScannedFile, scan_folder
from ingest.writers import JsonWriter
from ingest.worker import process_file

logger = logging.getLogger(__name__)


@dataclass
class RunStats:
    found: int = 0
    skipped_existing: int = 0
    succeeded: int = 0
    failed: int = 0
    ocr_used: int = 0
    scanned_detected: int = 0
    elapsed_sec: float = 0.0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


# ---- Module-level worker (Windows pickling requirement) -----------------


def _worker_entry(args):
    """args = (sf_path, sf_rel, sf_size, sf_mime, sf_sha, doc_id, cfg_dict).

    We pass a plain dict for cfg instead of IngestConfig because dataclasses
    with frozen=True pickle fine, but Path objects are easiest as strings.
    """
    sf_path, sf_rel, sf_size, sf_mime, sf_sha, doc_id, cfg = args
    cfg_obj = IngestConfig(
        input_root=cfg["input_root"],
        output_dir=cfg["output_dir"],
        workers=cfg["workers"],
        queue_size=cfg["queue_size"],
        allowed_extensions=frozenset(cfg["allowed_extensions"]),
        scanned_pdf_char_threshold=cfg["scanned_pdf_char_threshold"],
        scanned_pdf_sample_pages=cfg["scanned_pdf_sample_pages"],
        ocr_language=cfg["ocr_language"],
        ocr_dpi=cfg["ocr_dpi"],
        ocr_page_timeout_sec=cfg["ocr_page_timeout_sec"],
        enable_ocr=cfg["enable_ocr"],
        write_per_doc_json=cfg["write_per_doc_json"],
        manifest_db=cfg["manifest_db"],
        log_level=cfg["log_level"],
    )
    from pathlib import Path
    try:
        doc = process_file(
            Path(sf_path), sf_rel, sf_size, sf_mime, cfg_obj
        )
        return (doc_id, "ok", doc, None)
    except Exception as e:
        logger.exception("worker crashed on %s", sf_path)
        return (doc_id, "fail", None, f"{type(e).__name__}: {e}")


def _cfg_to_dict(cfg: IngestConfig) -> dict:
    return {
        "input_root": str(cfg.input_root),
        "output_dir": str(cfg.output_dir),
        "workers": cfg.workers,
        "queue_size": cfg.queue_size,
        "allowed_extensions": list(cfg.allowed_extensions),
        "scanned_pdf_char_threshold": cfg.scanned_pdf_char_threshold,
        "scanned_pdf_sample_pages": cfg.scanned_pdf_sample_pages,
        "ocr_language": cfg.ocr_language,
        "ocr_dpi": cfg.ocr_dpi,
        "ocr_page_timeout_sec": cfg.ocr_page_timeout_sec,
        "enable_ocr": cfg.enable_ocr,
        "write_per_doc_json": cfg.write_per_doc_json,
        "manifest_db": str(cfg.manifest_db),
        "log_level": cfg.log_level,
    }


# ---- Orchestrator -------------------------------------------------------


def _precompute_ids(files: Iterable[ScannedFile]) -> list[tuple[ScannedFile, str, str]]:
    out: list[tuple[ScannedFile, str, str]] = []
    for f in files:
        try:
            sha = sha256_file(f.path)
        except OSError as e:
            logger.warning("Cannot hash %s: %s", f.path, e)
            continue
        out.append((f, sha, make_document_id(sha)))
    return out


def run(cfg: IngestConfig) -> RunStats:
    started = time.monotonic()
    logger.info("Scanning: %s", cfg.input_root)
    files = scan_folder(cfg.input_root, cfg.allowed_extensions)
    logger.info("Discovered %d files", len(files))

    pre = _precompute_ids(files)
    logger.info("Hashed %d files", len(pre))

    manifest = Manifest(cfg.manifest_db)
    writer = JsonWriter(cfg.output_dir, per_doc=cfg.write_per_doc_json)

    pre_map: dict[str, tuple[ScannedFile, str]] = {
        doc_id: (f, sha) for f, sha, doc_id in pre
    }

    pending = manifest.filter_unprocessed(
        [(doc_id, f.relative_path) for f, _, doc_id in pre]
    )
    skipped = len(pre) - len(pending)
    stats = RunStats(found=len(pre), skipped_existing=skipped)
    logger.info("Pending: %d  (skipped %d already done)", len(pending), skipped)

    cfg_dict = _cfg_to_dict(cfg)
    tasks = []
    for doc_id, _ in pending:
        if doc_id not in pre_map:
            continue
        f, sha = pre_map[doc_id]
        tasks.append((
            str(f.path), f.relative_path, f.size_bytes, f.mime_type,
            sha, doc_id, cfg_dict,
        ))

    if not tasks:
        logger.info("Nothing to do.")
        writer.close()
        manifest.close()
        stats.elapsed_sec = time.monotonic() - started
        return stats

    pool_size = max(1, cfg.workers)
    logger.info("Starting pool with %d workers", pool_size)
    with mp.Pool(processes=pool_size) as pool:
        for doc_id, status, doc, err in pool.imap_unordered(
            _worker_entry, tasks, chunksize=1
        ):
            if status == "ok" and doc is not None:
                writer.write(doc)
                assert doc.metadata is not None
                manifest.mark(
                    document_id=doc.document_id,
                    sha256=doc.metadata.sha256,
                    rel_path=doc.metadata.relative_path,
                    status="ok",
                )
                stats.succeeded += 1
                if doc.metadata.ocr_used:
                    stats.ocr_used += 1
                if doc.metadata.is_scanned:
                    stats.scanned_detected += 1
            else:
                f, sha = pre_map.get(doc_id, (None, ""))
                manifest.mark(
                    document_id=doc_id,
                    sha256=sha,
                    rel_path=f.relative_path if f else "",
                    status="failed",
                    error=err,
                )
                stats.failed += 1

    writer.close()
    manifest.close()
    stats.elapsed_sec = time.monotonic() - started
    logger.info("Done. %s", stats.as_dict())
    return stats