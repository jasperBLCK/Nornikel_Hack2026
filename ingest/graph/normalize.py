"""Cyrillic-aware name normalization for entity canonicalization.

Goals (no LLM):
  1. Stable canonical key for MERGE idempotency.
  2. Merge surface variants: "кучное выщелачивание" / "Кучное выщелачивание"
     / "КУЧНОЕ ВЫЩЕЛАЧИВАНИЕ" / "кучного выщелачивания" → same key.
  3. Russian adjective suffix stripping for merging noun stems.
  4. Drop parenthetical / qualifier noise: "медь (Cu)" → "медь".

The key is the foundation of the dedup logic — must be deterministic
across runs and machines.
"""
from __future__ import annotations

import re
import unicodedata


_PARENS = re.compile(r"\([^)]*\)")
_BRACKETS = re.compile(r"\[[^\]]*\]")
_NON_ALNUM_CYR = re.compile(r"[^a-z0-9а-яё\s]")
_MULTI_SPACE = re.compile(r"\s+")
_LAT_TO_CYR = {
    # Common chemical-formula transliterated tokens we want to keep readable
    # but folded into a cyrillic-friendly form.
    "h2so4": "серная кислота",
    "hcl": "соляная кислота",
    "hno3": "азотная кислота",
    "naoh": "гидроксид натрия",
    "cu": "медь",
    "zn": "цинк",
    "fe": "железо",
    "au": "золото",
    "ag": "серебро",
    "ni": "никель",
    "co": "кобальт",
}

# Russian adjective endings to strip (descending length so longer matches
# are tried first). Conservative — only suffix forms that are clearly
# adjectival modifiers in technical text.
_RU_ADJ_SUFFIXES = (
    "овыми", "овому", "овыми", "овская", "овское", "овский",
    "ового", "овому", "овыми", "овом", "овой", "овую", "овых", "овые", "овый",
    "ская", "цкое", "цкий", "скими", "цким", "цких", "цкой",
    "ными", "ному", "ном", "ными", "ная", "ное", "ный", "ные", "ный", "ная",
    "ими", "ему", "ими", "ие", "ий", "ая", "ое", "ые",
    "ой", "ую", "ым", "ах", "ях", "ов", "ев",
)

# Russian noun case endings commonly seen in scientific text — strip them
# to find a stable stem. Limited to common genitive/plural forms.
_RU_NOUN_SUFFIXES = (
    "ами", "ями", "ах", "ях", "ов", "ев", "ей", "ом", "ем", "ою", "ею",
    "ы", "и", "у", "ю", "а", "я", "о", "е",
)

# Acronyms that should NOT be lowercased.
_KEEP_UPPER = {"ph", "rpm", "rpm"}


def _strip_parens(s: str) -> str:
    s = _PARENS.sub(" ", s)
    s = _BRACKETS.sub(" ", s)
    return s


def _fold_diacritics(s: str) -> str:
    # NFKD then drop combining marks. Works for both Latin and Cyrillic.
    nfkd = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in nfkd if not unicodedata.combining(ch))


def _safe_lower(token: str) -> str:
    """Lowercase but keep Cyrillic characters intact."""
    return token.lower()


def _strip_ru_affixes(token: str, *, do_noun: bool = True) -> str:
    """Aggressively trim Russian adjectival / noun case endings."""
    if not token or len(token) < 4:
        return token
    for suf in _RU_ADJ_SUFFIXES:
        if token.endswith(suf) and len(token) - len(suf) >= 3:
            return token[: -len(suf)]
    if do_noun:
        for suf in _RU_NOUN_SUFFIXES:
            if token.endswith(suf) and len(token) - len(suf) >= 3:
                return token[: -len(suf)]
    return token


def normalize_name(name: str, *, ru_stem: bool = True) -> str:
    """Produce a stable canonical key for the entity name.

    Pipeline:
      1. Strip parentheses / brackets.
      2. Fold diacritics (ё→е already at NFKD; 'ё' is preserved by
         request — replace ё→е to merge variants).
      3. Lowercase.
      4. Drop non-alphanumeric noise.
      5. Tokenize, fold Latin chemical formula tokens to Russian nouns.
      6. Optionally trim Russian adjective/noun suffixes.
      7. Rejoin with single spaces, trim.
    """
    if not name:
        return ""

    s = _strip_parens(name)
    s = s.replace("ё", "е").replace("Ё", "Е")
    s = _fold_diacritics(s)
    s = _safe_lower(s)
    s = _NON_ALNUM_CYR.sub(" ", s)
    s = _MULTI_SPACE.sub(" ", s).strip()
    if not s:
        return ""

    tokens = s.split(" ")
    out: list[str] = []
    for tok in tokens:
        if not tok:
            continue
        # Latin chemical formula -> Russian noun folding
        if tok in _LAT_TO_CYR:
            out.extend(_LAT_TO_CYR[tok].split())
            continue
        if ru_stem:
            tok = _strip_ru_affixes(tok, do_noun=False)
        out.append(tok)

    s = " ".join(t for t in out if t)
    s = _MULTI_SPACE.sub(" ", s).strip()
    return s