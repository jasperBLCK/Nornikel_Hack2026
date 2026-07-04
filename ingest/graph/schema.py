"""Graph schema constants and Cypher snippets.

All node types share a `canonical_key` property used as the MERGE
identity. The `name` is the original spelling (preserved for display).
"""
from __future__ import annotations

# ---- Node labels ----------------------------------------------------------

class Node:
    MATERIAL = "Material"
    PROCESS = "Process"
    EQUIPMENT = "Equipment"
    EXPERIMENT = "Experiment"
    PARAMETER = "Parameter"
    CONDITION = "Condition"


NODE_LABELS = (
    Node.MATERIAL, Node.PROCESS, Node.EQUIPMENT,
    Node.EXPERIMENT, Node.PARAMETER, Node.CONDITION,
)

# ---- Relationship types ---------------------------------------------------

class Rel:
    USES = "USES"               # Process -> Material / Equipment
    PRODUCES = "PRODUCES"       # Process -> Material
    OPERATES_IN = "OPERATES_IN" # Equipment -> Condition
    HAS_PARAMETER = "HAS_PARAMETER"  # Process/Experiment -> Parameter
    STUDIED_IN = "STUDIED_IN"   # Anything -> Experiment


REL_TYPES = (Rel.USES, Rel.PRODUCES, Rel.OPERATES_IN, Rel.HAS_PARAMETER, Rel.STUDIED_IN)

# ---- Common properties ----------------------------------------------------

PROP_CANONICAL_KEY = "canonical_key"
PROP_NAME = "name"
PROP_CHUNK_ID = "chunk_id"
PROP_DOCUMENT_ID = "document_id"
PROP_EVIDENCE = "evidence"
PROP_CREATED_AT = "created_at"

# Parameter-specific
PROP_PARAM_VALUE = "value"
PROP_PARAM_UNIT = "unit"
PROP_PARAM_SOURCE_NAME = "source_name"  # name as written in source text

# Experiment-specific
PROP_EXPERIMENT_LABEL = "label"  # "серия HL-2023-04", "опыт №3"

# ---- Constraint DDL (idempotent) ------------------------------------------

CONSTRAINTS_DDL: tuple[str, ...] = (
    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{Node.MATERIAL})  REQUIRE n.{PROP_CANONICAL_KEY} IS UNIQUE",
    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{Node.PROCESS})   REQUIRE n.{PROP_CANONICAL_KEY} IS UNIQUE",
    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{Node.EQUIPMENT}) REQUIRE n.{PROP_CANONICAL_KEY} IS UNIQUE",
    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{Node.EXPERIMENT}) REQUIRE n.{PROP_CANONICAL_KEY} IS UNIQUE",
    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{Node.PARAMETER}) REQUIRE n.{PROP_CANONICAL_KEY} IS UNIQUE",
    f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{Node.CONDITION}) REQUIRE n.{PROP_CANONICAL_KEY} IS UNIQUE",
)

# ---- UNWIND templates -----------------------------------------------------
# All use `rows` as the parameter name. `MERGE` on canonical_key
# makes the writes idempotent.

_MERGE_NODE_BASE = """
UNWIND $rows AS row
MERGE (n:{label} {{ {ck}: row.ck }})
ON CREATE SET
    n.name = row.name,
    n.created_at = timestamp()
ON MATCH SET
    n.name = coalesce(n.name, row.name)
RETURN count(n) AS merged
"""

def merge_node_cypher(label: str) -> str:
    return _MERGE_NODE_BASE.format(label=label, ck=PROP_CANONICAL_KEY)


# Relationship UNWIND templates.
# Each row: {from_ck, to_ck, evidence, chunk_id, document_id, ...extras}

_USES_REL = """
UNWIND $rows AS row
MATCH (a {Process:{ck}: row.from_ck})
MATCH (b {label:{ck}: row.to_ck})
MERGE (a)-[r:USES]->(b)
ON CREATE SET
    r.evidence = row.evidence,
    r.chunk_id = row.chunk_id,
    r.document_id = row.document_id,
    r.created_at = timestamp()
RETURN count(r) AS merged
"""

# We avoid Cypher string templating for MATCH because label differs per
# side; the batcher uses a simple per-row MATCH→MERGE pattern. Keeping
# the templates above as documentation only.
