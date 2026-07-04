"""CLI: python -m ingest.chunker --input ... --output ...

Example:
    python -m ingest.chunker \\
        --input  ./stage1_output/documents.ndjson \\
        --output ./stage2_output/chunks.ndjson \\
        --workers 8 --min-tokens 800 --max-tokens 1500 --overlap 200
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ingest.chunker.config import ChunkConfig, default_config
from ingest.chunker.pipeline import run


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )


def _build_config(args: argparse.Namespace) -> ChunkConfig:
    return default_config(
        input_ndjson=Path(args.input),
        output_ndjson=Path(args.output),
        chunk_min_tokens=args.min_tokens,
        chunk_max_tokens=args.max_tokens,
        chunk_overlap_tokens=args.overlap,
        workers=args.workers,
        fix_hyphenation=not args.no_fix_hyphenation,
        collapse_whitespace=not args.no_collapse_ws,
        strip_ocr_artifacts=not args.no_strip_ocr,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="hydrax-chunker",
        description="Stage 2: chunking & normalization of Stage 1 documents.",
    )
    p.add_argument("--input", required=True,
                   help="Stage 1 NDJSON file (documents.ndjson).")
    p.add_argument("--output", required=True,
                   help="Output NDJSON file (chunks.ndjson).")
    p.add_argument("--min-tokens", type=int, default=800)
    p.add_argument("--max-tokens", type=int, default=1500)
    p.add_argument("--overlap", type=int, default=200)
    p.add_argument("--workers", type=int, default=1,
                   help="Number of worker processes (default: 1 = single-process streaming).")
    p.add_argument("--no-fix-hyphenation", action="store_true")
    p.add_argument("--no-collapse-ws", action="store_true")
    p.add_argument("--no-strip-ocr", action="store_true")
    p.add_argument("--log-level", default="INFO")

    args = p.parse_args(argv)
    _setup_logging(args.log_level)
    cfg = _build_config(args)
    stats = run(cfg)
    print(json.dumps(stats.as_dict(), ensure_ascii=False, indent=2))
    return 0 if stats.errors == 0 else 2


if __name__ == "__main__":
    sys.exit(main())