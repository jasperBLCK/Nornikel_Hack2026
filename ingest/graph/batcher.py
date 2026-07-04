"""Cypher UNWIND batch builders.

Builds row dicts for:
  - Material / Process / Equipment / Experiment / Condition node upserts.
  - Parameter node upserts (with value + unit).
  - Relationship rows (USES, PRODUCES, OPERATES_IN, HAS_PARAMETER, STUDIED_IN).

Each row is a plain dict; the writer translates these into UNWIND params.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from ingest.graph.normalize import normalize_name
from ingest.graph.schema import (
    Node,
    PROP_CANONICAL_KEY,
    PROP_NAME,
    PROP_PARAM_VALUE,
    PROP_PARAM_UNIT,
    PROP_PARAM_SOURCE_NAME,
    PROP_EXPERIMENT_LABEL,
)


# ---- Reject helper --------------------------------------------------------


def _validate_and_normalize(
    raw_name: str,
    *,
    min_len: int,
    max_len: int,
    ru_stem: bool,
    ambiguous_if_long: bool,
) -> tuple[str, str] | None:
    """Returns (canonical_key, original_name), or None if rejected.

    `original_name` is what's stored in `name` (display value).
    `canonical_key` is the MERGE identity.
    """
    name = (raw_name or "").strip()
    if not name:
        return None
    if len(name) < min_len:
        return None
    if len(name) > max_len:
        return None
    canonical = normalize_name(name, ru_stem=ru_stem)
    if not canonical:
        return None
    if ambiguous_if_long and len(canonical.split()) > 4:
        return None  # too ambiguous
    return canonical, name


# ---- Per-type generators --------------------------------------------------


@dataclass
class NodeRow:
    label: str
    canonical_key: str
    name: str
    chunk_id: str
    document_id: str


@dataclass
class RelRow:
    rel_type: str           # USES / PRODUCES / OPERATES_IN / HAS_PARAMETER / STUDIED_IN
    from_label: str
    from_key: str
    to_label: str
    to_key: str
    chunk_id: str
    document_id: str
    evidence: str = ""
    # Optional extras for HAS_PARAMETER:
    param_value: str = ""
    param_unit: str = ""


# ---- Main collector -------------------------------------------------------


@dataclass
class BatchBuilder:
    """Accumulates extracted entities into deduped node + relation rows."""

    min_len: int = 2
    max_len: int = 200
    ru_stem: bool = True
    ambiguous_if_long: bool = True

    node_rows: list[NodeRow] = field(default_factory=list)
    rel_rows: list[RelRow] = field(default_factory=list)

    rejected_count: int = 0

    # --- Helpers ----------------------------------------------------------

    def _emit_node(self, label: str, raw_name: str, chunk_id: str, document_id: str) -> str | None:
        v = _validate_and_normalize(
            raw_name,
            min_len=self.min_len,
            max_len=self.max_len,
            ru_stem=self.ru_stem,
            ambiguous_if_long=self.ambiguous_if_long,
        )
        if v is None:
            self.rejected_count += 1
            return None
        canonical, original = v
        self.node_rows.append(NodeRow(label, canonical, original, chunk_id, document_id))
        return canonical

    # --- Public API: per-record ingestion -------------------------------

    def add_extraction(self, rec: dict) -> tuple[set[str], set[str]]:
        """Process one Stage 3 record. Returns (new_node_keys, new_rel_keys)
        — used to drive the UNWIND batches downstream.
        """
        chunk_id = rec.get("chunk_id", "")
        document_id = rec.get("document_id", "")
        evidence_by_chunk: dict[str, str] = {chunk_id: ""}
        # Stage 3 may have relations with their own evidence; collect them.
        for rel in rec.get("relations", []) or []:
            ev = rel.get("evidence", "")
            if ev:
                evidence_by_chunk[rel.get("chunk_id", chunk_id) or chunk_id] = ev

        new_node_keys: set[str] = set()
        new_rel_keys: set[str] = set()

        # Plain string entities: materials / processes / equipment / conditions
        for label, key in (
            (Node.MATERIAL, "materials"),
            (Node.PROCESS, "processes"),
            (Node.EQUIPMENT, "equipment"),
            (Node.CONDITION, "conditions"),
        ):
            for raw in rec.get(key) or []:
                if not isinstance(raw, str):
                    continue
                ck = self._emit_node(label, raw, chunk_id, document_id)
                if ck is not None:
                    new_node_keys.add(f"{label}:{ck}")

        # Experiments
        for raw in rec.get("experiments") or []:
            if not isinstance(raw, str):
                continue
            v = _validate_and_normalize(
                raw, min_len=self.min_len, max_len=self.max_len,
                ru_stem=self.ru_stem, ambiguous_if_long=self.ambiguous_if_long,
            )
            if v is None:
                self.rejected_count += 1
                continue
            canonical, original = v
            self.node_rows.append(NodeRow(Node.EXPERIMENT, canonical, original, chunk_id, document_id))
            new_node_keys.add(f"{Node.EXPERIMENT}:{canonical}")

        # Parameters (special: also has value + unit)
        for param in rec.get("parameters") or []:
            if not isinstance(param, dict):
                continue
            name = param.get("name", "")
            v = _validate_and_normalize(
                name, min_len=self.min_len, max_len=self.max_len,
                ru_stem=self.ru_stem, ambiguous_if_long=False,  # params often long
            )
            if v is None:
                self.rejected_count += 1
                continue
            canonical, original = v
            value = str(param.get("value", "")).strip()
            unit = str(param.get("unit", "")).strip()
            self.node_rows.append(NodeRow(
                label=Node.PARAMETER,
                canonical_key=canonical,
                name=original,
                chunk_id=chunk_id,
                document_id=document_id,
            ))
            new_node_keys.add(f"{Node.PARAMETER}:{canonical}")
            # HAS_PARAMETER will be created from explicit relations below
            # OR from process contexts. We materialize HAS_PARAMETER edges
            # for every parameter in this chunk to all PROCESS entities
            # in the same chunk — reasonable default; consumers can filter.
            for proc_name in rec.get("processes") or []:
                v2 = _validate_and_normalize(
                    proc_name, min_len=self.min_len, max_len=self.max_len,
                    ru_stem=self.ru_stem, ambiguous_if_long=self.ambiguous_if_long,
                )
                if v2 is None:
                    continue
                proc_canonical, _ = v2
                self.rel_rows.append(RelRow(
                    rel_type="HAS_PARAMETER",
                    from_label=Node.PROCESS,
                    from_key=proc_canonical,
                    to_label=Node.PARAMETER,
                    to_key=canonical,
                    chunk_id=chunk_id,
                    document_id=document_id,
                    evidence="",
                    param_value=value,
                    param_unit=unit,
                ))
                new_rel_keys.add(f"Process:{proc_canonical}-HAS_PARAMETER->Parameter:{canonical}")

        # Relations (explicit from Stage 3)
        for rel in rec.get("relations") or []:
            if not isinstance(rel, dict):
                continue
            rtype = rel.get("relation", "")
            src = rel.get("source", "")
            tgt = rel.get("target", "")
            ev = rel.get("evidence", "")
            chunk_ref = rel.get("chunk_id", chunk_id) or chunk_id

            # Map relation type to graph rel + node labels.
            graph_rel, src_label, tgt_label = _classify_relation(rtype, src, tgt)
            if graph_rel is None:
                self.rejected_count += 1
                continue

            src_v = _validate_and_normalize(
                src, min_len=self.min_len, max_len=self.max_len,
                ru_stem=self.ru_stem, ambiguous_if_long=self.ambiguous_if_long,
            )
            tgt_v = _validate_and_normalize(
                tgt, min_len=self.min_len, max_len=self.max_len,
                ru_stem=self.ru_stem, ambiguous_if_long=self.ambiguous_if_long,
            )
            if src_v is None or tgt_v is None:
                self.rejected_count += 1
                continue
            src_ck, _ = src_v
            tgt_ck, _ = tgt_v

            # Ensure node rows exist.
            self.node_rows.append(NodeRow(src_label, src_ck, src, chunk_ref, document_id))
            self.node_rows.append(NodeRow(tgt_label, tgt_ck, tgt, chunk_ref, document_id))

            self.rel_rows.append(RelRow(
                rel_type=graph_rel,
                from_label=src_label,
                from_key=src_ck,
                to_label=tgt_label,
                to_key=tgt_ck,
                chunk_id=chunk_ref,
                document_id=document_id,
                evidence=ev,
            ))
            new_rel_keys.add(f"{src_label}:{src_ck}-{graph_rel}->{tgt_label}:{tgt_ck}")

        return new_node_keys, new_rel_keys


# ---- Relation classification ----------------------------------------------


def _classify_relation(rtype: str, src: str, tgt: str) -> tuple[str | None, str, str]:
    """Map LLM-emitted relation labels to (Neo4j rel type, src_label, tgt_label).

    If source/target look like a material/process/equipment noun, we label
    accordingly. We default to Process -> Material/Equipment for USES,
    Process -> Material for PRODUCES, Equipment -> Condition for OPERATES_IN.
    """
    rtype_norm = (rtype or "").strip().lower()
    src_norm = (src or "").strip().lower()
    tgt_norm = (tgt or "").strip().lower()

    # Heuristic: classify source/target by simple process / equipment /
    # material hints. This is intentionally coarse — graph relations are
    # best-effort; full NER is out of scope.
    def label_of(name: str) -> str:
        if any(k in name for k in ("процесс", "выщелачивание", "флотация", "электролиз", "обжиг", "осаждение", "экстракция", "сорбция", "плавка", "переработка")):
            return Node.PROCESS
        if any(k in name for k in ("аппарат", "машин", "реактор", "фильтр", "насос", "электролизёр", "печь", "классификатор", "мельниц", "катод", "анод")):
            return Node.EQUIPMENT
        return Node.MATERIAL

    if rtype_norm in ("применяется_для", "использует", "uses"):
        return "USES", label_of(src), label_of(tgt)
    if rtype_norm in ("является_продуктом", "produces", "выделяет", "образует"):
        return "PRODUCES", label_of(src), label_of(tgt)
    if rtype_norm in ("протекает_при", "operates_in", "при_условии"):
        return "OPERATES_IN", label_of(src), Node.CONDITION
    if rtype_norm in ("описан_в", "studied_in"):
        return "STUDIED_IN", label_of(src), Node.EXPERIMENT
    # Default fallback: USES, both as material/process.
    return "USES", label_of(src), label_of(tgt)