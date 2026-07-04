"""Text normalization — deterministic, no LLM.

Three passes:
  1. OCR artifact cleanup (common mojibake / repeated glyphs / ligatures).
  2. Hyphenation fix (line-broken compound words: "метал-\\nлургия" -> "металлургия").
  3. Whitespace normalization (collapse runs, strip control chars).

Each step is idempotent and order-independent (we run them in a fixed
sequence for determinism).
"""
from __future__ import annotations

import re
import unicodedata


# --- OCR artifact cleanup --------------------------------------------------

# Stray zero-width / BOM / private-use marks that survive OCR pipelines.
_INVISIBLE = re.compile(r"[​-‍﻿‎‏‪-‮⁠-⁩]")

# Common OCR misreads (very conservative — do not over-translate).
_LIGATURES = {
    "ﬁ": "fi", "ﬂ": "fl", "ﬀ": "ff", "ﬃ": "ffi", "ﬄ": "ffl",
    "–": "-", "—": "-", "―": "-",
    "“": '"', "”": '"', "‘": "'", "’": "'",
    " ": " ",
}

# Repeated punctuation (e.g. "....." -> ".")
_REPEAT_PUNCT = re.compile(r"([.\-_,;:!?])\1{2,}")

# Stray control characters except \n and \t.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f]")

# 3+ consecutive newlines (artifacts).
_REPEAT_NEWLINES = re.compile(r"\n{3,}")


def strip_ocr_artifacts(text: str) -> str:
    if not text:
        return text

    # Drop invisible Unicode marks.
    text = _INVISIBLE.sub("", text)

    # Replace ligatures & curly quotes.
    for k, v in _LIGATURES.items():
        text = text.replace(k, v)

    # Collapse "....." -> "." etc.
    text = _REPEAT_PUNCT.sub(r"\1\1", text)

    # Drop control chars.
    text = _CONTROL.sub("", text)

    # Collapse 3+ newlines into 2.
    text = _REPEAT_NEWLINES.sub("\n\n", text)

    return text


# --- Hyphenation fix -------------------------------------------------------

# Matches: word-<newline>word  ->  wordword
# Whitelist: only lowercase letters + cyrillic, no digits (avoid "p-\n1" cases).
_HYPHEN_BREAK = re.compile(
    r"(?<=[A-Za-zА-Яа-яёЁ])-\s*\n\s*(?=[A-Za-zА-Яа-яёЁ])"
)


def fix_hyphenation(text: str) -> str:
    if not text:
        return text
    return _HYPHEN_BREAK.sub("", text)


# --- Whitespace normalization ---------------------------------------------

_REPEAT_SPACES = re.compile(r"[ \t]{2,}")


def collapse_whitespace(text: str) -> str:
    if not text:
        return text
    text = _REPEAT_SPACES.sub(" ", text)
    # Strip trailing spaces on each line.
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    # Trim leading/trailing whitespace of the whole doc.
    return text.strip()


# --- Master entry point ----------------------------------------------------

def normalize(
    text: str,
    *,
    do_strip_ocr: bool = True,
    do_fix_hyphenation: bool = True,
    do_collapse_ws: bool = True,
) -> str:
    if not text:
        return ""
    # NFC normalize first — ensures stable tokenization across encodings.
    text = unicodedata.normalize("NFC", text)
    if do_strip_ocr:
        text = strip_ocr_artifacts(text)
    if do_fix_hyphenation:
        text = fix_hyphenation(text)
    if do_collapse_ws:
        text = collapse_whitespace(text)
    return text