"""In-memory dedup map: (node_type, canonical_key) -> node_id.

We also keep a parallel `names` map for diagnostics (canonical_key -> first
seen original name) so we can audit merges.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


@dataclass
class DedupIndex:
    """Holds canonical_key -> node_id mappings per node label."""

    # We don't store node_ids in memory — Neo4j assigns them on MERGE.
    # What we track is the (label, canonical_key) we've already pushed.
    _seen: set[tuple[str, str]] = field(default_factory=set)
    _original_names: dict[tuple[str, str], str] = field(default_factory=dict)
    _size: int = 0

    def has(self, label: str, canonical_key: str) -> bool:
        return (label, canonical_key) in self._seen

    def mark(self, label: str, canonical_key: str, original_name: str) -> bool:
        """Returns True if newly inserted, False if already present."""
        key = (label, canonical_key)
        if key in self._seen:
            return False
        self._seen.add(key)
        self._original_names[key] = original_name
        self._size += 1
        return True

    def mark_many(self, label: str, items: Iterable[tuple[str, str]]) -> list[str]:
        """Returns canonical_keys that were newly inserted (for batching)."""
        new_keys: list[str] = []
        for canonical_key, original_name in items:
            if self.mark(label, canonical_key, original_name):
                new_keys.append(canonical_key)
        return new_keys

    def first_name(self, label: str, canonical_key: str) -> str | None:
        return self._original_names.get((label, canonical_key))

    def __len__(self) -> int:
        return self._size