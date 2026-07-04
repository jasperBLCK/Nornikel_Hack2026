"""Legacy .doc extractor — antiword first, LibreOffice→docx fallback."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from ingest.extractors.base import Extractor
from ingest.structures import Page


def _antiword(path: Path) -> str:
    proc = subprocess.run(
        ["antiword", "-m", "UTF-8.txt", str(path)],
        capture_output=True, timeout=120,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode("utf-8", "replace")[:200])
    return proc.stdout.decode("utf-8", "replace").strip()


def _libreoffice_to_docx(path: Path, out_dir: Path) -> Path:
    subprocess.run(
        ["soffice", "--headless", "--convert-to", "docx",
         "--outdir", str(out_dir), str(path)],
        check=True, capture_output=True, timeout=300,
    )
    converted = out_dir / (path.stem + ".docx")
    if not converted.exists():
        raise FileNotFoundError(f"LibreOffice did not produce {converted}")
    return converted


class DocExtractor(Extractor):
    def extract(self, path: Path) -> list[Page]:
        if shutil.which("antiword"):
            try:
                text = _antiword(path)
                if text:
                    return [Page(page_number=1, text=text)]
            except Exception:
                pass
        if shutil.which("soffice"):
            try:
                from ingest.extractors.docx_extractor import DocxExtractor
                with tempfile.TemporaryDirectory() as td:
                    docx_path = _libreoffice_to_docx(path, Path(td))
                    return DocxExtractor().extract(docx_path)
            except Exception:
                pass
        return [Page(page_number=1, text="")]
