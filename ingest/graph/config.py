"""Stage 4 configuration: Neo4j connection + batch sizes + dedup tuning."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


@dataclass(frozen=True)
class GraphConfig:
    # IO
    input_ndjson: Path          # Stage 3 extracted.ndjson
    reject_ndjson: Path        # Rejected entities log
    manifest_db: Path          # SQLite checkpoint

    # Neo4j
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password_env: str = "NEO4J_PASSWORD"
    neo4j_database: str = "neo4j"
    neo4j_max_connection_pool_size: int = 50
    neo4j_connection_timeout_sec: float = 30.0
    neo4j_write_timeout_sec: float = 60.0
    ensure_constraints: bool = True

    # Batching
    node_batch_size: int = 1000
    rel_batch_size: int = 1000
    flush_every_sec: float = 5.0
    max_inflight_batches: int = 4

    # Dedup / normalization
    canonical_min_length: int = 2
    canonical_max_length: int = 200
    enable_russian_stemming: bool = True
    """Aggressive suffix stripping for Russian adjective endings:
       '-овый', '-овая', '-овое', '-ный', '-ная', '-ное', '-ной', '-ные', '-ных',
       '-ский', '-ская', '-ское', '-ий', '-ая', '-ое'."""

    # Ambiguity
    ambiguous_if_splits_phrase: bool = True
    """If the canonical form has more than 4 words, mark as ambiguous."""

    # Resume
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if not os.environ.get(self.neo4j_password_env):
            raise EnvironmentError(
                f"Neo4j password not set. Export {self.neo4j_password_env}."
            )
        # Validate URI scheme.
        scheme = urlparse(self.neo4j_uri).scheme
        if scheme not in ("bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"):
            raise ValueError(f"Unsupported Neo4j URI scheme: {scheme!r}")
        Path(self.reject_ndjson).parent.mkdir(parents=True, exist_ok=True)
        Path(self.manifest_db).parent.mkdir(parents=True, exist_ok=True)


def default_config(input_ndjson: Path, **overrides) -> "GraphConfig":
    cfg = GraphConfig(
        input_ndjson=Path(input_ndjson),
        reject_ndjson=Path(input_ndjson).parent / "graph_rejected.ndjson",
        manifest_db=Path(input_ndjson).parent / "_graph_manifest.sqlite",
    )
    out = GraphConfig(**{**cfg.__dict__, **overrides})
    return out