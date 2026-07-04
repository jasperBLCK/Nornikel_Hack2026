"""Stage 4 orchestrator.

Stream → BatchBuilder → dedup → flush to Neo4j in chunks of N records.
A single writer thread handles all Cypher calls — keeps the driver
session count bounded and lets the Bolt connection pool do its job.
"""
from __future__ import annotations

import logging
import time
from collections import defaultdict
from dataclasses import dataclass

from ingest.graph.batcher import BatchBuilder, NodeRow, RelRow
from ingest.graph.config import GraphConfig
from ingest.graph.dedup import DedupIndex
from ingest.graph.neo4j_writer import Neo4jWriter
from ingest.graph.reject_log import RejectLog
from ingest.graph.streamer import iter_extractions

logger = logging.getLogger(__name__)


@dataclass
class GraphStats:
    records_read: int = 0
    nodes_built: int = 0
    rels_built: int = 0
    nodes_written: int = 0
    rels_written: int = 0
    rejected: int = 0
    elapsed_sec: float = 0.0

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def _deduped_node_rows(rows: list[NodeRow], index: DedupIndex) -> list[NodeRow]:
    out: list[NodeRow] = []
    for r in rows:
        if index.mark(r.label, r.canonical_key, r.name):
            out.append(r)
    return out


def _deduped_rel_rows(rows: list[RelRow], index: DedupIndex) -> list[RelRow]:
    """Edge dedup signature: (from_label, from_ck, type, to_label, to_ck, chunk_id)."""
    out: list[RelRow] = []
    for r in rows:
        sig = (r.from_label, r.from_key, r.rel_type, r.to_label, r.to_key, r.chunk_id)
        if index.mark("__rel__", "|".join(sig), ""):
            out.append(r)
    return out


def run(cfg: GraphConfig) -> GraphStats:
    started = time.monotonic()
    stats = GraphStats()
    index = DedupIndex()
    rel_index = DedupIndex()
    rejects = RejectLog(cfg.reject_ndjson)
    builder = BatchBuilder(
        min_len=cfg.canonical_min_length,
        max_len=cfg.canonical_max_length,
        ru_stem=cfg.enable_russian_stemming,
        ambiguous_if_long=cfg.ambiguous_if_splits_phrase,
    )

    writer = Neo4jWriter(cfg)

    # Stage-level bookkeeping for parameter value/unit
    param_extras: dict[str, dict] = {}
    # buffer: accumulate rows; flush when thresholds met
    node_buffer: list[NodeRow] = []
    rel_buffer: list[RelRow] = []
    last_flush = time.monotonic()

    def _flush(force: bool = False) -> None:
        nonlocal node_buffer, rel_buffer, last_flush
        if not node_buffer and not rel_buffer:
            return
        if not force:
            if len(node_buffer) < cfg.node_batch_size and \
               len(rel_buffer) < cfg.rel_batch_size and \
               (time.monotonic() - last_flush) < cfg.flush_every_sec:
                return

        # Dedup + send
        nodes = _deduped_node_rows(node_buffer, index)
        rels = _deduped_rel_rows(rel_buffer, rel_index)
        stats.nodes_built += len(nodes)
        stats.rels_built += len(rels)

        try:
            writer.upsert_nodes(nodes, param_extras=param_extras)
            writer.upsert_relationships(rels)
            stats.nodes_written += len(nodes)
            stats.rels_written += len(rels)
        except Exception as e:
            logger.exception("Neo4j flush failed: %s", e)
            # Record every buffered row to rejects so we can re-run safely.
            for r in nodes:
                rejects.write({
                    "kind": "node_flush_failed",
                    "label": r.label,
                    "canonical_key": r.canonical_key,
                    "name": r.name,
                    "chunk_id": r.chunk_id,
                    "document_id": r.document_id,
                    "error": str(e),
                })
                stats.rejected += 1
            for r in rels:
                rejects.write({
                    "kind": "rel_flush_failed",
                    "rel_type": r.rel_type,
                    "from": f"{r.from_label}:{r.from_key}",
                    "to": f"{r.to_label}:{r.to_key}",
                    "chunk_id": r.chunk_id,
                    "document_id": r.document_id,
                    "error": str(e),
                })
                stats.rejected += 1

        node_buffer = []
        rel_buffer = []
        last_flush = time.monotonic()

    try:
        for rec in iter_extractions(cfg.input_ndjson):
            stats.records_read += 1

            # Snapshot param extras BEFORE BatchBuilder consumes the record,
            # so we can later map canonical_key -> (value, unit).
            pre_param_extras: dict[str, dict] = {}
            for p in rec.get("parameters") or []:
                if not isinstance(p, dict):
                    continue
                pre_param_extras[p.get("name", "").strip()] = {
                    "value": str(p.get("value", "")).strip(),
                    "unit": str(p.get("unit", "")).strip(),
                }

            before_rejected = builder.rejected_count
            node_rows, rel_rows = [], []  # not used directly
            # Process the record.
            builder.add_extraction(rec)
            stats.rejected += builder.rejected_count - before_rejected

            # Move any newly added rows into our buffers.
            # BatchBuilder appends to its own lists — we consume and reset.
            if builder.node_rows:
                node_buffer.extend(builder.node_rows)
                builder.node_rows = []
            if builder.rel_rows:
                rel_buffer.extend(builder.rel_rows)
                builder.rel_rows = []

            # Update param_extras with normalized keys
            for pname, extra in pre_param_extras.items():
                if not pname:
                    continue
                from ingest.graph.normalize import normalize_name
                ck = normalize_name(pname, ru_stem=cfg.enable_russian_stemming)
                if ck:
                    param_extras[ck] = extra

            _flush(force=False)

        _flush(force=True)
    finally:
        writer.close()
        rejects.close()

    stats.elapsed_sec = time.monotonic() - started
    logger.info("Graph build done: %s", stats.as_dict())
    return stats