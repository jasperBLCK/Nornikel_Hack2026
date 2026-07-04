"""Token counting.

We use a whitespace tokenizer (regex-based) rather than a subword tokenizer
because:

1. This stage is preprocessing, not embedding — we only need stable counts.
2. Whitespace tokens match how humans read technical Russian text.
3. Zero external deps; pure-Python; deterministic.

For Cyrillic text, `.split()` splits on ASCII whitespace, which works because
Russian scientific docs use standard spaces/tabs/newlines.
"""
from __future__ import annotations

import re

_WS = re.compile(r"\s+")


def count_tokens(text: str) -> int:
    """Number of whitespace-delimited tokens in `text`."""
    if not text:
        return 0
    return len(_WS.split(text.strip()))


def tokenize(text: str) -> list[str]:
    if not text:
        return []
    return _WS.split(text.strip())


def split_into_token_windows(
    tokens: list[str],
    max_tokens: int,
    overlap: int,
) -> list[tuple[int, int]]:
    """Yield (start_index, end_index_exclusive) windows.

    Greedy: advance by (max_tokens - overlap) until the end.
    The final window may be shorter than max_tokens.
    """
    if not tokens:
        return []
    if max_tokens <= 0:
        raise ValueError("max_tokens must be > 0")
    if overlap < 0 or overlap >= max_tokens:
        raise ValueError("overlap must satisfy 0 <= overlap < max_tokens")

    step = max_tokens - overlap
    out: list[tuple[int, int]] = []
    start = 0
    n = len(tokens)
    while start < n:
        end = min(start + max_tokens, n)
        out.append((start, end))
        if end == n:
            break
        start += step
    return out