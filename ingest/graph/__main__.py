"""CLI: python -m ingest.graph

Example:
    export NEO4J_PASSWORD=...
    python -m ingest.graph \\
        --input  ./stage3_output/extracted.ndjson \\
        --uri    bolt://localhost:7687 \\
        --user   neo4j \\
        --database neo4j \\
        --node-batch-size 1000 --rel-batch-size 1000
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ingest.graph.config import GraphConfig, default_config
from ingest.graph.pipeline import run


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )


def _build_config(args: argparse.Namespace) -> GraphConfig:
    return default_config(
        input_ndjson=Path(args.input),
        neo4j_uri=args.uri,
        neo4j_user=args.user,
        neo4j_database=args.database,
        node_batch_size=args.node_batch_size,
        rel_batch_size=args.rel_batch_size,
        flush_every_sec=args.flush_interval,
        enable_russian_stemming=not args.no_ru_stem,
        log_level=args.log_level,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="hydrax-graph",
        description="Stage 4: build Knowledge Graph in Neo4j from Stage 3 extractions.",
    )
    p.add_argument("--input", required=True, help="Stage 3 NDJSON (extracted.ndjson).")
    p.add_argument("--uri", default="bolt://localhost:7687")
    p.add_argument("--user", default="neo4j")
    p.add_argument("--database", default="neo4j")
    p.add_argument("--node-batch-size", type=int, default=1000)
    p.add_argument("--rel-batch-size", type=int, default=1000)
    p.add_argument("--flush-interval", type=float, default=5.0,
                   help="Max seconds between flushes (default: 5.0).")
    p.add_argument("--no-ru-stem", action="store_true",
                   help="Disable Russian suffix stripping in canonicalization.")
    p.add_argument("--log-level", default="INFO")

    args = p.parse_args(argv)
    _setup_logging(args.log_level)

    try:
        cfg = _build_config(args)
    except EnvironmentError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    stats = run(cfg)
    print(json.dumps(stats.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())