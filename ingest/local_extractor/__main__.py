"""Stage 3-lite CLI: local rule-based extraction over chunks NDJSON.

    python -m ingest.local_extractor --input chunks.ndjson --output extracted.ndjson

Processes ~30k chunks in minutes with zero API cost. Output is
ExtractionRecord NDJSON, drop-in compatible with Stage 4 (ingest.graph).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ingest.local_extractor.rules import extract_chunk_local


def main() -> int:
    p = argparse.ArgumentParser(description="Local (no-LLM) extraction.")
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    inp, outp = Path(args.input), Path(args.output)
    if not inp.exists():
        sys.exit(f"ERROR: input not found: {inp}")
    outp.parent.mkdir(parents=True, exist_ok=True)

    started = time.monotonic()
    n_read = n_ok = 0
    with open(inp, encoding="utf-8") as fin, open(outp, "w", encoding="utf-8") as fout:
        for line in fin:
            line = line.strip()
            if not line:
                continue
            n_read += 1
            ch = json.loads(line)
            text = ch.get("text", "")
            if not text:
                continue
            rec = extract_chunk_local(
                ch.get("document_id", ""), ch.get("chunk_id", ""), text)
            fout.write(rec.model_dump_json() + "\n")
            n_ok += 1
            if n_ok % 5000 == 0:
                print(f"  ... {n_ok} chunks", flush=True)

    stats = {"chunks_read": n_read, "chunks_ok": n_ok,
             "elapsed_sec": round(time.monotonic() - started, 2)}
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
