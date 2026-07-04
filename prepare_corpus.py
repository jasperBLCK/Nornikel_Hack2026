"""Corpus preparation: recursively unpack ZIP/RAR archives in place.

Usage:
    python prepare_corpus.py --input "./INFO_DATA/Источники информации"

Each archive `foo.zip` is extracted into a sibling folder `foo_unpacked/`
next to it (skipped if the folder already exists). Extraction is recursive:
archives found inside extracted folders are unpacked too. The original
archives are left untouched — the ingest scanner ignores them anyway.

Requirements: `unzip` support is built-in (zipfile); RAR needs `unrar` or
`7z` on PATH (Ubuntu: apt-get install unrar-free p7zip-full).
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ARCHIVE_EXTS = {".zip", ".rar"}
MAX_DEPTH = 3

# Multi-volume RAR: unrar auto-continues from .part1, so only .part1 (or
# volumes without a part suffix) should be extracted directly.
_PART_RE = re.compile(r"\.part(\d+)$", re.IGNORECASE)


def _is_secondary_volume(path: Path) -> bool:
    m = _PART_RE.search(path.stem)
    return bool(m) and int(m.group(1)) > 1


def _zip_member_name(info: zipfile.ZipInfo) -> str:
    """Handle Cyrillic names: zipfile decodes non-UTF8 names as cp437."""
    if info.flag_bits & 0x800:  # UTF-8 flag set
        return info.filename
    try:
        return info.filename.encode("cp437").decode("cp866")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return info.filename


def extract_zip(archive: Path, dest: Path) -> None:
    with zipfile.ZipFile(archive) as zf:
        for info in zf.infolist():
            name = _zip_member_name(info)
            target = dest / name
            if not target.resolve().is_relative_to(dest.resolve()):
                continue  # zip-slip protection
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)


def extract_rar(archive: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    if shutil.which("unrar"):
        cmd = ["unrar", "x", "-o+", "-y", str(archive), str(dest) + "/"]
    elif shutil.which("7z"):
        cmd = ["7z", "x", "-y", f"-o{dest}", str(archive)]
    else:
        raise RuntimeError("Neither unrar nor 7z found on PATH")
    proc = subprocess.run(cmd, capture_output=True, timeout=1800)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:300])


def unpack_tree(root: Path) -> tuple[int, int, int]:
    ok = skipped = failed = 0
    for depth in range(MAX_DEPTH):
        archives = [p for p in sorted(root.rglob("*"))
                    if p.is_file() and p.suffix.lower() in ARCHIVE_EXTS
                    and not _is_secondary_volume(p)]
        todo = [a for a in archives
                if not a.with_name(a.stem + "_unpacked").exists()]
        if not todo:
            break
        for archive in todo:
            dest = archive.with_name(archive.stem + "_unpacked")
            try:
                print(f"[unpack] {archive.relative_to(root)}")
                if archive.suffix.lower() == ".zip":
                    extract_zip(archive, dest)
                else:
                    extract_rar(archive, dest)
                ok += 1
            except Exception as e:
                print(f"[FAIL]   {archive.relative_to(root)}: {e}", file=sys.stderr)
                shutil.rmtree(dest, ignore_errors=True)
                failed += 1
    skipped = sum(
        1 for p in root.rglob("*")
        if p.is_file() and p.suffix.lower() in ARCHIVE_EXTS
        and not _is_secondary_volume(p)
        and p.with_name(p.stem + "_unpacked").exists()
    ) - ok
    return ok, max(0, skipped), failed


def main() -> int:
    p = argparse.ArgumentParser(description="Unpack ZIP/RAR archives in corpus.")
    p.add_argument("--input", required=True, help="Corpus root folder.")
    args = p.parse_args()
    root = Path(args.input).resolve()
    if not root.exists():
        sys.exit(f"ERROR: input folder not found: {root}")
    ok, skipped, failed = unpack_tree(root)
    print(f"\nDone: unpacked={ok} already_done={skipped} failed={failed}")
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
