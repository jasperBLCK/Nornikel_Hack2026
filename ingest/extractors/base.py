"""Abstract extractor — every format implements this."""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from ingest.structures import Page


class Extractor(ABC):
    """Returns one Page per logical page in the document.
    For non-paginated formats (TXT) the contract is still respected:
    the entire content is returned as Page(1, ...).
    """

    @abstractmethod
    def extract(self, path: Path) -> list[Page]:
        """Return ordered pages with extracted text. Must NOT raise on
        partial failure — yield pages with empty text and let the
        pipeline flag the error in metadata.
        """
        raise NotImplementedError