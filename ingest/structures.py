"""Structured document representation."""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass
class Page:
    page_number: int
    text: str
    is_scanned: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DocumentMetadata:
    filename: str
    relative_path: str
    file_size_bytes: int
    file_extension: str
    page_count: int
    is_scanned: bool
    ocr_used: bool
    sha256: str
    mime_type: str = ""
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Document:
    document_id: str
    filename: str
    file_type: str
    pages: list[Page] = field(default_factory=list)
    full_text: str = ""
    metadata: DocumentMetadata | None = None

    def to_json(self) -> str:
        payload = {
            "document_id": self.document_id,
            "filename": self.filename,
            "file_type": self.file_type,
            "pages": [p.to_dict() for p in self.pages],
            "full_text": self.full_text,
            "metadata": self.metadata.to_dict() if self.metadata else {},
        }
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    def to_dict(self) -> dict[str, Any]:
        return json.loads(self.to_json())