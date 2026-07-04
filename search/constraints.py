"""Numeric constraints and geography parsing for user queries.

parse_constraints("сульфаты ≤300 мг/л при 60–80 °C")
  → [{"op": "≤", "value": 300, "unit": "мг/л", ...},
     {"op": "range", "value": 60, "value2": 80, "unit": "°c", ...}]

detect_geo("… в мировой практике") → "foreign" | "domestic" | ""
classify_geo(filename, text)       → "domestic" | "foreign"
"""
from __future__ import annotations

import re

_UNIT = (
    r"мг/дм[3³]|г/дм[3³]|мг/л|г/л|мг/м[3³]|г/т|"
    r"м[3³]/ч|м[3³]/сут|т/сут|т/ч|кг/ч|л/мин|м/с|м/ч|об/мин|"
    r"°\s?[cс]|градус(?:ов|а)?|к?вт·?ч?|мвт|м?па|атм|"
    r"г|кг|т|мм|см|км|м|%|ч|мин|сут"
)
_NUM = r"\d+(?:[.,]\d+)?"

_RANGE = re.compile(
    rf"(?:от\s+)?({_NUM})\s*(?:[–—-]|\.\.\.?|до)\s*({_NUM})\s*({_UNIT})?",
    re.IGNORECASE)
_B = r"(?<![\w\u0400-\u04FF])"
_LE = re.compile(
    rf"(?:{_B}(?:не более|не выше|не превыша\w+|максимум|менее|меньше|ниже|до)|[≤<]=?)"
    rf"\s*({_NUM})\s*({_UNIT})?", re.IGNORECASE)
_GE = re.compile(
    rf"(?:{_B}(?:не менее|не ниже|минимум|более|больше|свыше|выше|от)|[≥>]=?)"
    rf"\s*({_NUM})\s*({_UNIT})?", re.IGNORECASE)


def _num(s: str) -> float:
    return float(s.replace(",", "."))


def parse_constraints(query: str) -> list[dict]:
    """Extract numeric constraints (ranges and inequalities) from a query."""
    out: list[dict] = []
    spans: list[tuple[int, int]] = []

    def taken(m: re.Match) -> bool:
        return any(m.start() < e and m.end() > s for s, e in spans)

    for m in _RANGE.finditer(query):
        lo, hi = _num(m.group(1)), _num(m.group(2))
        if hi <= lo:
            continue
        spans.append(m.span())
        out.append({"op": "range", "value": lo, "value2": hi,
                    "unit": (m.group(3) or "").lower(),
                    "text": m.group(0).strip()})
    for rx, op in ((_LE, "≤"), (_GE, "≥")):
        for m in rx.finditer(query):
            if taken(m):
                continue
            spans.append(m.span())
            out.append({"op": op, "value": _num(m.group(1)), "value2": None,
                        "unit": (m.group(2) or "").lower(),
                        "text": m.group(0).strip()})
    out.sort(key=lambda c: query.lower().find(c["text"].lower()))
    return out


def satisfies(value: float, constraint: dict) -> bool:
    op = constraint["op"]
    if op == "range":
        return constraint["value"] <= value <= constraint["value2"]
    if op == "≤":
        return value <= constraint["value"]
    return value >= constraint["value"]


# -- geography ---------------------------------------------------------------

_DOMESTIC_Q = re.compile(
    r"отечествен|в россии|российск|\bрф\b|советск|в снг", re.IGNORECASE)
_FOREIGN_Q = re.compile(
    r"зарубеж|за рубежом|мирово[йм] практик|иностран|международн|"
    r"\bforeign\b|\bworld\b", re.IGNORECASE)

_DOMESTIC_DOC = re.compile(
    r"росси|\bрф\b|норильск|кольск|мончегорск|заполярн|талнах|надежд|"
    r"отечествен|гост\b|снип", re.IGNORECASE)
_FOREIGN_DOC = re.compile(
    r"зарубеж|foreign|international|abroad|мирова[яй]|outotec|glencore|"
    r"vale\b|bhp\b|sherritt|xstrata|финлянд|канад|австрали|чили|китайск",
    re.IGNORECASE)


def detect_geo(query: str) -> str:
    """Geography intent of a query: 'domestic', 'foreign' or '' (no intent)."""
    dom, for_ = bool(_DOMESTIC_Q.search(query)), bool(_FOREIGN_Q.search(query))
    if dom and not for_:
        return "domestic"
    if for_ and not dom:
        return "foreign"
    return ""


def classify_geo(filename: str, text: str = "") -> str:
    """Classify a document/chunk as domestic or foreign practice."""
    probe = f"{filename} {text[:1500]}"
    dom = len(_DOMESTIC_DOC.findall(probe))
    for_ = len(_FOREIGN_DOC.findall(probe))
    if for_ > dom:
        return "foreign"
    if dom > for_:
        return "domestic"
    cyr = len(re.findall(r"[\u0400-\u04FF]", text[:2000]))
    lat = len(re.findall(r"[A-Za-z]", text[:2000]))
    return "foreign" if lat > cyr else "domestic"


GEO_LABELS = {"domestic": "отечественная практика",
              "foreign": "зарубежная практика"}
