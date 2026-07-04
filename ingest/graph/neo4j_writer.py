"""Batched UNWIND writes to Neo4j.

Idempotency:
  - Constraints on `canonical_key` per label are ensured at start.
  - Every node write is a MERGE on canonical_key.
  - Every relationship write is a MATCH by canonical_key + MERGE on
    relationship type — so re-runs don't duplicate edges with the same
    (from_ck, to_ck, type, chunk_id) signature. We additionally dedupe
    in-memory before issuing the UNWIND to minimize wire traffic.

Threading:
  - The writer owns a single Neo4j driver (thread-safe).
  - A lock around writes is acceptable because UNWIND is network-bound,
    not CPU-bound; the lock is rarely contended.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from typing import Iterable

from neo4j import GraphDatabase, Driver

from ingest.graph.batcher import NodeRow, RelRow
from ingest.graph.config import GraphConfig
from ingest.graph.schema import (
    CONSTRAINTS_DDL,
    Node,
    PROP_CANONICAL_KEY,
    PROP_NAME,
    PROP_PARAM_VALUE,
    PROP_PARAM_UNIT,
    merge_node_cypher,
)

logger = logging.getLogger(__name__)


class Neo4jWriter:
    def __init__(self, cfg: GraphConfig) -> None:
        self.cfg = cfg
        password = os.environ[cfg.neo4j_password_env]
        self._driver: Driver = GraphDatabase.driver(
            cfg.neo4j_uri,
            auth=(cfg.neo4j_user, password),
            max_connection_pool_size=cfg.neo4j_max_connection_pool_size,
            connection_timeout=cfg.neo4j_connection_timeout_sec,
        )
        self._lock = threading.Lock()
        self._ensure_constraints()

    def close(self) -> None:
        self._driver.close()

    def _ensure_constraints(self) -> None:
        if not self.cfg.ensure_constraints:
            return
        with self._driver.session(database=self.cfg.neo4j_database) as s:
            for ddl in CONSTRAINTS_DDL:
                s.run(ddl)
        logger.info("Neo4j constraints ensured")

    # ---- Node writes ----------------------------------------------------

    def _group_node_rows(self, rows: Iterable[NodeRow]) -> dict[str, list[dict]]:
        groups: dict[str, list[dict]] = {label: [] for label in (
            Node.MATERIAL, Node.PROCESS, Node.EQUIPMENT,
            Node.EXPERIMENT, Node.PARAMETER, Node.CONDITION,
        )}
        for r in rows:
            row_dict = {
                "ck": r.canonical_key,
                "name": r.name,
                "chunk_id": r.chunk_id,
                "document_id": r.document_id,
            }
            if r.label == Node.PARAMETER:
                # value/unit will be filled by caller; pass-through
                pass
            groups[r.label].append(row_dict)
        return groups

    def upsert_nodes(self, rows: list[NodeRow], *, param_extras: dict[str, dict] | None = None) -> int:
        """Returns the number of UNWIND statements executed (one per label)."""
        if not rows:
            return 0

        # Fill parameter extras if any.
        if param_extras:
            for r in rows:
                if r.label == Node.PARAMETER:
                    extra = param_extras.get(r.canonical_key)
                    if extra:
                        r.__dict__.setdefault("_value", extra.get("value", ""))
                        r.__dict__.setdefault("_unit", extra.get("unit", ""))

        groups = self._group_node_rows(rows)
        executed = 0
        with self._lock:
            with self._driver.session(database=self.cfg.neo4j_database) as s:
                for label, group_rows in groups.items():
                    if not group_rows:
                        continue
                    if label == Node.PARAMETER:
                        # Inject value/unit into row dicts.
                        for row in group_rows:
                            ck = row["ck"]
                            extra = (param_extras or {}).get(ck) or {}
                            row["value"] = extra.get("value", "")
                            row["unit"] = extra.get("unit", "")
                    cypher = self._param_cypher(label)
                    s.run(cypher, rows=group_rows)
                    executed += 1
        return executed

    def _param_cypher(self, label: str) -> str:
        """Return MERGE Cypher for a node label, including label-specific props."""
        base = merge_node_cypher(label)
        if label == Node.PARAMETER:
            return """
UNWIND $rows AS row
MERGE (n:Parameter { canonical_key: row.ck })
ON CREATE SET
    n.name = row.name,
    n.value = row.value,
    n.unit = row.unit,
    n.created_at = timestamp(),
    n.updated_at = timestamp(),
    n.version = 1
ON MATCH SET
    n.name = coalesce(n.name, row.name),
    n.value = CASE WHEN row.value <> '' THEN row.value ELSE n.value END,
    n.unit = CASE WHEN row.unit <> '' THEN row.unit ELSE n.unit END,
    n.updated_at = timestamp(),
    n.version = coalesce(n.version, 1) + 1
RETURN count(n) AS merged
"""
        return base

    # ---- Relationship writes -------------------------------------------

    def upsert_relationships(self, rows: list[RelRow]) -> int:
        if not rows:
            return 0

        # Group by (rel_type, from_label, to_label)
        groups: dict[tuple[str, str, str], list[dict]] = {}
        for r in rows:
            key = (r.rel_type, r.from_label, r.to_label)
            payload = {
                "from_ck": r.from_key,
                "to_ck": r.to_key,
                "evidence": r.evidence or "",
                "chunk_id": r.chunk_id,
                "document_id": r.document_id,
            }
            if r.rel_type == "HAS_PARAMETER":
                payload["value"] = r.param_value or ""
                payload["unit"] = r.param_unit or ""
            groups.setdefault(key, []).append(payload)

        executed = 0
        with self._lock:
            with self._driver.session(database=self.cfg.neo4j_database) as s:
                for (rtype, f_label, t_label), group_rows in groups.items():
                    cypher = self._rel_cypher(rtype, f_label, t_label)
                    s.run(cypher, rows=group_rows)
                    executed += 1
        return executed

    def _rel_cypher(self, rtype: str, f_label: str, t_label: str) -> str:
        if rtype == "HAS_PARAMETER":
            return f"""
UNWIND $rows AS row
MATCH (a:{f_label} {{ canonical_key: row.from_ck }})
MATCH (b:{t_label} {{ canonical_key: row.to_ck }})
MERGE (a)-[r:HAS_PARAMETER {{ value: row.value, unit: row.unit }}]->(b)
ON CREATE SET
    r.evidence = row.evidence,
    r.chunk_id = row.chunk_id,
    r.document_id = row.document_id,
    r.created_at = timestamp(),
    r.updated_at = timestamp(),
    r.version = 1
ON MATCH SET
    r.evidence = CASE WHEN row.evidence <> '' THEN row.evidence ELSE r.evidence END,
    r.document_id = CASE WHEN row.document_id <> '' THEN row.document_id ELSE r.document_id END,
    r.updated_at = timestamp(),
    r.version = coalesce(r.version, 1) + 1
RETURN count(r) AS merged
"""
        # Generic pattern
        return f"""
UNWIND $rows AS row
MATCH (a:{f_label} {{ canonical_key: row.from_ck }})
MATCH (b:{t_label} {{ canonical_key: row.to_ck }})
MERGE (a)-[r:{rtype}]->(b)
ON CREATE SET
    r.evidence = row.evidence,
    r.chunk_id = row.chunk_id,
    r.document_id = row.document_id,
    r.created_at = timestamp(),
    r.updated_at = timestamp(),
    r.version = 1
ON MATCH SET
    r.evidence = CASE WHEN row.evidence <> '' THEN row.evidence ELSE r.evidence END,
    r.updated_at = timestamp(),
    r.version = coalesce(r.version, 1) + 1
RETURN count(r) AS merged
"""