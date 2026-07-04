"""CLI: python -m ingest.extractor

Example:
    export ANTHROPIC_API_KEY=...
    python -m ingest.extractor \\
        --input  ./stage2_output/chunks.ndjson \\
        --output ./stage3_output/extracted.ndjson \\
        --workers 4 --async-concurrency 8 --batch-size 32 \\
        --model claude-sonnet-5
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from ingest.extractor.config import ExtractorConfig, default_config
from ingest.extractor.pipeline import run


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )


def _build_config(args: argparse.Namespace) -> ExtractorConfig:
    return default_config(
        input_ndjson=Path(args.input),
        output_ndjson=Path(args.output),
        model=args.model,
        workers=args.workers,
        async_concurrency=args.async_concurrency,
        batch_size=args.batch_size,
        enable_grounding_judge=not args.no_grounding,
        max_retries=args.max_retries,
        log_level=args.log_level,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="hydrax-extractor",
        description="Stage 3: LLM-based structured knowledge extraction.",
    )
    p.add_argument("--input", required=True, help="Stage 2 chunks NDJSON.")
    p.add_argument("--output", required=True, help="Output extracted NDJSON.")
    p.add_argument("--model", default="claude-sonnet-5",
                   help="Anthropic model id (default: claude-sonnet-5).")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--async-concurrency", type=int, default=8,
                   help="In-flight requests per worker process.")
    p.add_argument("--batch-size", type=int, default=32)
    p.add_argument("--no-grounding", action="store_true",
                   help="Disable LLM-as-judge grounding check.")
    p.add_argument("--max-retries", type=int, default=5)
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
    return 0 if stats.chunks_error == 0 else 2


if __name__ == "__main__":
    sys.exit(main())