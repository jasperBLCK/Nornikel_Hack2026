"""CLI entrypoint.

Usage:
    python -m ingest.run --input ./corpus --output ./output

On Windows, multiprocessing requires the entrypoint to be guarded by
`if __name__ == "__main__":`.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys

from ingest.config import IngestConfig, default_config
from ingest.pipeline import run


def _setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
        stream=sys.stderr,
    )


def _build_config(args: argparse.Namespace) -> IngestConfig:
    return default_config(
        input_root=args.input,
        output_dir=args.output,
        workers=args.workers,
        ocr_language=args.ocr_lang,
        ocr_dpi=args.ocr_dpi,
        enable_ocr=not args.no_ocr,
        write_per_doc_json=args.per_doc,
        log_level=args.log_level,
    )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="hydrax-ingest",
        description="Document ingestion pipeline (PDF/DOCX/TXT → NDJSON).",
    )
    p.add_argument("--input", required=True, help="Input folder (recursive).")
    p.add_argument("--output", required=True, help="Output folder.")
    p.add_argument("--workers", type=int, default=None,
                   help="Worker processes (default = CPU-1).")
    p.add_argument("--ocr-lang", default="eng+rus",
                   help="Tesseract language codes (default: eng+rus).")
    p.add_argument("--ocr-dpi", type=int, default=300,
                   help="Render DPI for OCR (default: 300).")
    p.add_argument("--no-ocr", action="store_true",
                   help="Disable OCR fallback for scanned PDFs.")
    p.add_argument("--per-doc", action="store_true",
                   help="Write one .json per doc (slower). Default: NDJSON.")
    p.add_argument("--log-level", default="INFO")

    args = p.parse_args(argv)
    _setup_logging(args.log_level)

    cfg = _build_config(args)
    stats = run(cfg)

    print(json.dumps(stats.as_dict(), ensure_ascii=False, indent=2))
    return 0 if stats.failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())