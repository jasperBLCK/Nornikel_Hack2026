"""Hybrid retrieval: vector search (Qdrant) + knowledge graph (Neo4j)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

from qdrant_client import QdrantClient

from ingest.local_extractor.dictionaries import (
    CONDITIONS, EQUIPMENT, MATERIALS, PROCESSES,
)
from search.constraints import (
    classify_geo, detect_geo, parse_constraints, satisfies,
)
from search.indexer import COLLECTION, EMBED_MODEL

DEFAULT_QDRANT_PATH = "./hydrax_out/qdrant_data"


@dataclass
class RetrievedChunk:
    chunk_id: str
    document_id: str
    filename: str
    text: str
    score: float
    geo: str = ""


@dataclass
class GraphFact:
    source: str
    relation: str
    target: str
    evidence: str
    filename: str = ""
    updated_at: float = 0.0
    version: int = 1


@dataclass
class RetrievalResult:
    chunks: list[RetrievedChunk] = field(default_factory=list)
    facts: list[GraphFact] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    constraints: list[dict] = field(default_factory=list)
    parameter_matches: list[dict] = field(default_factory=list)
    geo: str = ""


def detect_entities(query: str) -> dict[str, list[str]]:
    """Match query terms against domain dictionaries."""
    q = query.lower()
    out: dict[str, list[str]] = {}
    for kind, vocab in (("materials", MATERIALS), ("processes", PROCESSES),
                        ("equipment", EQUIPMENT), ("conditions", CONDITIONS)):
        hits = [canon for canon, stems in vocab.items()
                if any(s in q for s in stems)]
        if hits:
            out[kind] = hits
    return out


class Retriever:
    def __init__(self, qdrant_path: str | None = None) -> None:
        qdrant_path = qdrant_path or os.environ.get("QDRANT_PATH",
                                                      DEFAULT_QDRANT_PATH)
        self._qdrant = QdrantClient(path=qdrant_path)
        self._qdrant.set_model(EMBED_MODEL)
        self._neo4j = None
        try:
            from neo4j import GraphDatabase
            uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
            user = os.environ.get("NEO4J_USER", "neo4j")
            password = os.environ.get("NEO4J_PASSWORD", "testpass")
            if password:
                self._neo4j = GraphDatabase.driver(uri, auth=(user, password))
                self._neo4j.verify_connectivity()
        except Exception:
            self._neo4j = None

    # -- vector ---------------------------------------------------------

    def vector_search(self, query: str, limit: int = 8) -> list[RetrievedChunk]:
        try:
            hits = self._qdrant.query(collection_name=COLLECTION,
                                      query_text=query, limit=limit)
        except ValueError:
            # collection does not exist yet (pipeline not run)
            return []
        out = []
        for h in hits:
            md = h.metadata or {}
            filename = md.get("filename", "")
            text = md.get("text", md.get("document", ""))
            out.append(RetrievedChunk(
                chunk_id=md.get("chunk_id", ""),
                document_id=md.get("document_id", ""),
                filename=filename,
                text=text,
                score=round(h.score or 0.0, 4),
                geo=classify_geo(filename, text),
            ))
        return out

    # -- graph ----------------------------------------------------------

    def graph_facts(self, entities: dict[str, list[str]], limit: int = 30) -> list[GraphFact]:
        if self._neo4j is None:
            return []
        names = [n for v in entities.values() for n in v]
        if not names:
            return []
        cypher = """
        MATCH (a)-[r]->(b)
        WHERE a.name IN $names OR b.name IN $names
        RETURN a.name AS source, type(r) AS relation, b.name AS target,
               coalesce(r.evidence, '') AS evidence,
               coalesce(r.updated_at, r.created_at, 0) AS updated_at,
               coalesce(r.version, 1) AS version
        LIMIT $limit
        """
        try:
            with self._neo4j.session() as s:
                rows = s.run(cypher, names=names, limit=limit)
                return [GraphFact(source=r["source"], relation=r["relation"],
                                  target=r["target"], evidence=r["evidence"],
                                  updated_at=(r["updated_at"] or 0) / 1000,
                                  version=r["version"] or 1)
                        for r in rows]
        except Exception:
            return []

    def subgraph(self, entities: dict[str, list[str]], limit: int = 60) -> dict:
        """Nodes+edges around matched entities for visualization."""
        if self._neo4j is None:
            return {"nodes": [], "edges": []}
        names = [n for v in entities.values() for n in v]
        if not names:
            return {"nodes": [], "edges": []}
        cypher = """
        MATCH (a)-[r]->(b)
        WHERE a.name IN $names OR b.name IN $names
        RETURN a.name AS s, labels(a)[0] AS sl,
               type(r) AS rel,
               b.name AS t, labels(b)[0] AS tl
        LIMIT $limit
        """
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        try:
            with self._neo4j.session() as sess:
                for r in sess.run(cypher, names=names, limit=limit):
                    for name, label in ((r["s"], r["sl"]), (r["t"], r["tl"])):
                        nodes.setdefault(name, {"id": name, "label": name,
                                                "group": label})
                    edges.append({"from": r["s"], "to": r["t"],
                                  "label": r["rel"]})
        except Exception:
            pass
        return {"nodes": list(nodes.values()), "edges": edges}

    def full_graph(self, limit: int = 200) -> dict:
        """Global subgraph (highest-degree relations first) for the explorer."""
        if self._neo4j is None:
            return {"nodes": [], "edges": []}
        cypher = """
        MATCH (a)-[r]->(b)
        RETURN a.name AS s, labels(a)[0] AS sl,
               type(r) AS rel,
               b.name AS t, labels(b)[0] AS tl
        LIMIT $limit
        """
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        try:
            with self._neo4j.session() as sess:
                for r in sess.run(cypher, limit=limit):
                    for name, label in ((r["s"], r["sl"]), (r["t"], r["tl"])):
                        nodes.setdefault(name, {"id": name, "label": name,
                                                "group": label})
                    edges.append({"from": r["s"], "to": r["t"],
                                  "label": r["rel"]})
        except Exception:
            pass
        return {"nodes": list(nodes.values()), "edges": edges}

    def stats(self) -> dict:
        out = {"chunks": 0, "documents": 0, "nodes": 0, "relations": 0,
               "neo4j": self._neo4j is not None}
        try:
            info = self._qdrant.get_collection(COLLECTION)
            out["chunks"] = info.points_count or 0
            out["documents"] = self._distinct_documents()
        except Exception:
            pass
        if self._neo4j is not None:
            try:
                with self._neo4j.session() as s:
                    out["nodes"] = s.run("MATCH (n) RETURN count(n) AS c").single()["c"]
                    out["relations"] = s.run("MATCH ()-[r]->() RETURN count(r) AS c").single()["c"]
            except Exception:
                pass
        return out

    def _distinct_documents(self) -> int:
        """Count distinct document_id values across all indexed chunks."""
        seen: set[str] = set()
        offset = None
        while True:
            points, offset = self._qdrant.scroll(
                collection_name=COLLECTION, limit=1000,
                offset=offset, with_payload=["document_id"], with_vectors=False)
            for p in points:
                seen.add((p.payload or {}).get("document_id", ""))
            if offset is None:
                break
        seen.discard("")
        return len(seen)

    def documents(self, limit: int = 500) -> tuple[list[dict], int]:
        """Aggregate indexed chunks into a per-document summary.

        Returns (top `limit` documents by chunk count, total distinct docs).
        """
        docs: dict[str, dict] = {}
        offset = None
        try:
            while True:
                points, offset = self._qdrant.scroll(
                    collection_name=COLLECTION, limit=1000, offset=offset,
                    with_payload=["document_id", "filename", "text",
                                  "document"],
                    with_vectors=False)
                for p in points:
                    md = p.payload or {}
                    doc_id = md.get("document_id", "")
                    fn = md.get("filename", "") or doc_id
                    d = docs.setdefault(doc_id, {"document_id": doc_id,
                                                 "filename": fn, "chunks": 0,
                                                 "chars": 0})
                    d["chunks"] += 1
                    d["chars"] += len(md.get("text", md.get("document", "")))
                if offset is None:
                    break
        except Exception:
            pass
        ordered = sorted(docs.values(), key=lambda d: -d["chunks"])
        return ordered[:limit], len(docs)

    def analytics(self) -> dict:
        """Corpus analytics: node counts by label, top-connected entities,
        relation type distribution."""
        out = {"labels": [], "top_entities": [], "relation_types": [],
               **self.stats()}
        if self._neo4j is None:
            return out
        try:
            with self._neo4j.session() as s:
                out["labels"] = [
                    {"label": r["label"], "count": r["c"]}
                    for r in s.run(
                        "MATCH (n) RETURN labels(n)[0] AS label, count(*) AS c "
                        "ORDER BY c DESC")]
                out["top_entities"] = [
                    {"name": r["name"], "label": r["label"], "degree": r["d"]}
                    for r in s.run(
                        "MATCH (n) RETURN n.name AS name, labels(n)[0] AS label, "
                        "COUNT { (n)--() } AS d ORDER BY d DESC LIMIT 15")]
                out["relation_types"] = [
                    {"type": r["t"], "count": r["c"]}
                    for r in s.run(
                        "MATCH ()-[r]->() RETURN type(r) AS t, count(*) AS c "
                        "ORDER BY c DESC")]
        except Exception:
            pass
        return out

    def knowledge_gaps(self) -> dict:
        """Coverage gaps in the graph: weakly-connected entities per label
        and materials without any linked process."""
        out = {"weak_by_label": [], "uncovered_materials": [],
               "uncovered_processes": []}
        if self._neo4j is None:
            return out
        try:
            with self._neo4j.session() as s:
                out["weak_by_label"] = [
                    {"label": r["label"], "weak": r["weak"], "total": r["total"]}
                    for r in s.run(
                        "MATCH (n) WITH labels(n)[0] AS label, n, "
                        "COUNT { (n)--() } AS d "
                        "RETURN label, sum(CASE WHEN d <= 1 THEN 1 ELSE 0 END) "
                        "AS weak, count(*) AS total ORDER BY weak DESC")]
                out["uncovered_materials"] = [
                    r["name"] for r in s.run(
                        "MATCH (m:Material) WHERE NOT (m)--(:Process) "
                        "RETURN m.name AS name ORDER BY name LIMIT 20")]
                out["uncovered_processes"] = [
                    r["name"] for r in s.run(
                        "MATCH (p:Process) WHERE NOT (p)--(:Condition) "
                        "AND NOT (p)--(:Parameter) "
                        "RETURN p.name AS name ORDER BY name LIMIT 20")]
        except Exception:
            pass
        return out

    def contradictions(self, limit: int = 20) -> dict:
        """Parameters of the same process reported with different values
        in different sources — candidate data conflicts."""
        out = {"contradictions": []}
        if self._neo4j is None:
            return out
        cypher = """
        MATCH (p)-[r:HAS_PARAMETER]->(x:Parameter)
        RETURN p.name AS process,
               coalesce(x.source_name, x.name) AS param,
               coalesce(r.value, x.value) AS value,
               coalesce(r.unit, x.unit, '') AS unit,
               coalesce(r.document_id, '') AS document_id,
               coalesce(r.evidence, '') AS evidence,
               coalesce(r.updated_at, r.created_at, 0) AS updated_at
        """
        groups: dict[tuple[str, str, str], list[dict]] = {}
        try:
            with self._neo4j.session() as s:
                for r in s.run(cypher):
                    if r["value"] is None:
                        continue
                    key = (r["process"], (r["param"] or "").lower(), r["unit"])
                    groups.setdefault(key, []).append({
                        "value": r["value"], "document_id": r["document_id"],
                        "evidence": r["evidence"],
                        "updated_at": (r["updated_at"] or 0) / 1000})
        except Exception:
            return out
        num = re.compile(r"-?\d+(?:[.,]\d+)?")
        items = []
        for (process, param, unit), rows in groups.items():
            values = []
            for row in rows:
                m = num.search(str(row["value"]))
                if m:
                    values.append(float(m.group().replace(",", ".")))
            distinct = sorted(set(values))
            if len(distinct) < 2:
                continue
            lo, hi = distinct[0], distinct[-1]
            spread = (hi - lo) / abs(hi) if hi else 0
            if spread < 0.15:
                continue
            docs = sorted({r["document_id"] for r in rows if r["document_id"]})
            items.append({
                "process": process, "parameter": param, "unit": unit,
                "min": lo, "max": hi, "values": distinct[:10],
                "sources": len(docs) or len(rows),
                "documents": docs[:6],
                "evidence": [r["evidence"] for r in rows if r["evidence"]][:4],
                "spread": round(spread, 2),
                "updated_at": max((r["updated_at"] for r in rows), default=0),
            })
        items.sort(key=lambda i: (-i["sources"], -i["spread"]))
        out["contradictions"] = items[:limit]
        return out

    def coverage_matrix(self) -> dict:
        """Material × Process coverage: which combinations are documented."""
        out = {"materials": [], "processes": [], "cells": []}
        if self._neo4j is None:
            return out
        try:
            with self._neo4j.session() as s:
                out["materials"] = [
                    r["name"] for r in s.run(
                        "MATCH (m:Material) RETURN m.name AS name, "
                        "COUNT { (m)--() } AS d ORDER BY d DESC, name LIMIT 30")]
                out["processes"] = [
                    r["name"] for r in s.run(
                        "MATCH (p:Process) RETURN p.name AS name, "
                        "COUNT { (p)--() } AS d ORDER BY d DESC, name LIMIT 20")]
                out["cells"] = [
                    {"process": r["process"], "material": r["material"],
                     "count": r["c"], "evidence": r["evidence"] or ""}
                    for r in s.run(
                        "MATCH (p:Process)-[r:USES]-(m:Material) "
                        "RETURN p.name AS process, m.name AS material, "
                        "count(r) AS c, collect(r.evidence)[0] AS evidence")]
        except Exception:
            pass
        return out

    def parameters_table(self) -> dict:
        """All process→parameter values with units, sources and conflict flag."""
        out = {"rows": []}
        if self._neo4j is None:
            return out
        cypher = """
        MATCH (p)-[r:HAS_PARAMETER]->(x:Parameter)
        RETURN p.name AS process,
               coalesce(x.source_name, x.name) AS param,
               coalesce(r.value, x.value) AS value,
               coalesce(r.unit, x.unit, '') AS unit,
               coalesce(r.document_id, '') AS document_id,
               coalesce(r.evidence, '') AS evidence,
               coalesce(r.updated_at, r.created_at, 0) AS updated_at
        """
        groups: dict[tuple[str, str, str], list[dict]] = {}
        try:
            with self._neo4j.session() as s:
                for r in s.run(cypher):
                    if r["value"] is None:
                        continue
                    key = (r["process"], (r["param"] or "").lower(), r["unit"])
                    groups.setdefault(key, []).append({
                        "value": r["value"], "document_id": r["document_id"],
                        "evidence": r["evidence"],
                        "updated_at": (r["updated_at"] or 0) / 1000})
        except Exception:
            return out
        num = re.compile(r"-?\d+(?:[.,]\d+)?")
        rows = []
        for (process, param, unit), items in groups.items():
            values, seen = [], set()
            numeric = []
            for it in items:
                v = str(it["value"])
                if v not in seen:
                    seen.add(v)
                    values.append({"value": v,
                                   "document_id": it["document_id"],
                                   "evidence": it["evidence"]})
                m = num.search(v)
                if m:
                    numeric.append(float(m.group().replace(",", ".")))
            distinct = sorted(set(numeric))
            conflict = False
            if len(distinct) >= 2:
                lo, hi = distinct[0], distinct[-1]
                conflict = bool(hi) and (hi - lo) / abs(hi) >= 0.15
            rows.append({"process": process, "parameter": param, "unit": unit,
                         "values": values[:8], "conflict": conflict,
                         "min": distinct[0] if distinct else None,
                         "max": distinct[-1] if distinct else None,
                         "updated_at": max((it["updated_at"] for it in items),
                                           default=0)})
        rows.sort(key=lambda r: (r["process"], r["parameter"]))
        out["rows"] = rows
        return out

    def path_between(self, source: str, target: str, max_hops: int = 4) -> dict:
        """Shortest paths between two named entities with edge evidence."""
        out = {"paths": [], "nodes": [], "edges": []}
        if self._neo4j is None or not source or not target:
            return out
        cypher = f"""
        MATCH (a {{name: $a}}), (b {{name: $b}}),
              p = allShortestPaths((a)-[*..{max_hops}]-(b))
        RETURN p LIMIT 3
        """
        nodes: dict[str, dict] = {}
        edges: list[dict] = []
        paths: list[list[dict]] = []
        try:
            with self._neo4j.session() as s:
                for rec in s.run(cypher, a=source, b=target):
                    p = rec["p"]
                    steps = []
                    for rel in p.relationships:
                        sn, en = rel.start_node, rel.end_node
                        for n in (sn, en):
                            name = n.get("name", "")
                            nodes.setdefault(name, {
                                "id": name, "label": name,
                                "group": list(n.labels)[0] if n.labels else ""})
                        edge = {"from": sn.get("name", ""),
                                "to": en.get("name", ""),
                                "label": rel.type,
                                "evidence": rel.get("evidence", "") or ""}
                        edges.append(edge)
                        steps.append(edge)
                    paths.append(steps)
        except Exception:
            pass
        out["paths"] = paths
        out["nodes"] = list(nodes.values())
        out["edges"] = edges
        return out

    def entity_names(self) -> list[dict]:
        """All entity names with labels (for pickers)."""
        if self._neo4j is None:
            return []
        try:
            with self._neo4j.session() as s:
                return [{"name": r["name"], "label": r["label"]}
                        for r in s.run(
                            "MATCH (n) RETURN n.name AS name, "
                            "labels(n)[0] AS label ORDER BY name")]
        except Exception:
            return []

    def matching_parameters(self, constraints: list[dict],
                            limit: int = 12) -> list[dict]:
        """Graph parameters whose numeric value satisfies query constraints."""
        if self._neo4j is None or not constraints:
            return []
        cypher = """
        MATCH (p)-[r:HAS_PARAMETER]->(x:Parameter)
        RETURN p.name AS process,
               coalesce(x.source_name, x.name) AS param,
               coalesce(r.value, x.value) AS value,
               coalesce(r.unit, x.unit, '') AS unit,
               coalesce(r.document_id, '') AS document_id
        """
        num = re.compile(r"-?\d+(?:[.,]\d+)?")
        out = []
        try:
            with self._neo4j.session() as s:
                for r in s.run(cypher):
                    m = num.search(str(r["value"] or ""))
                    if not m:
                        continue
                    value = float(m.group().replace(",", "."))
                    unit = (r["unit"] or "").lower()
                    for c in constraints:
                        if c["unit"] and unit and c["unit"] != unit:
                            continue
                        if satisfies(value, c):
                            out.append({
                                "process": r["process"], "parameter": r["param"],
                                "value": r["value"], "unit": r["unit"],
                                "document_id": r["document_id"],
                                "constraint": c["text"]})
                            break
                    if len(out) >= limit:
                        break
        except Exception:
            return out
        return out

    # -- combined ---------------------------------------------------------

    def retrieve(self, query: str, top_k: int = 8,
                 geo: str = "") -> RetrievalResult:
        entities = detect_entities(query)
        constraints = parse_constraints(query)
        geo = geo or detect_geo(query)
        if geo in ("domestic", "foreign"):
            chunks = [c for c in self.vector_search(query, top_k * 4)
                      if c.geo == geo][:top_k]
        else:
            chunks = self.vector_search(query, top_k)
        return RetrievalResult(
            chunks=chunks,
            facts=self.graph_facts(entities),
            entities=entities,
            constraints=constraints,
            parameter_matches=self.matching_parameters(constraints),
            geo=geo,
        )
