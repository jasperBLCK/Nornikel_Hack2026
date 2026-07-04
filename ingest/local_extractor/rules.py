"""Rule-based extraction: dictionary matching + numeric parameter regex.

Produces the same ExtractionRecord shape as the LLM extractor (Stage 3),
so Stage 4 (Neo4j) consumes it unchanged.
"""
from __future__ import annotations

import re

from ingest.extractor.schema import ExtractionRecord, Parameter, Relation
from ingest.local_extractor.dictionaries import (
    CONDITIONS, EQUIPMENT, GEO_FOREIGN, GEO_RU, MATERIALS, PROCESSES,
)

# ---- Numeric parameter patterns -------------------------------------------

_NUM = r"[-+]?\d+(?:[.,]\d+)?"
_RANGE = rf"{_NUM}(?:\s*[-–—…]\s*{_NUM})?"
_CMP = r"(?:до|от|не более|не менее|около|порядка|менее|более|свыше|≤|≥|<|>|~)"

_UNITS = (
    r"°C|°С|К\b|г/л|г/дм3|г/дм³|мг/л|мг/дм3|мг/дм³|кг/т|г/т|т/сут|т/ч|т/год|"
    r"м3/ч|м³/ч|м/с|л/мин|л/ч|об/мин|кПа|МПа|атм|бар|мВ|В\b|А/м2|А/м²|кА|"
    r"мкм|мм|см\b|мин\b|час(?:а|ов)?\b|сут(?:ок)?\b|%|процент(?:а|ов)?|"
    r"g/l|mg/l|g/t|kg/t|t/h|m3/h|rpm|kPa|MPa|ppm|wt\.?%|vol\.?%"
)

_PARAM_NAMES = {
    "температура": ("температур", "temperature"),
    "давление": ("давлени", "pressure"),
    "концентрация": ("концентрац", "содержани", "concentration", "content"),
    "извлечение": ("извлечени", "recovery"),
    "скорость потока": ("скорость поток", "скорости поток", "расход", "flow rate", "скорость циркуляц"),
    "плотность тока": ("плотность тока", "плотности тока", "current density"),
    "pH": ("ph",),
    "выход": ("выход", "yield"),
    "производительность": ("производительност", "throughput", "capacity"),
    "крупность": ("крупност", "particle size", "тонина"),
    "продолжительность": ("продолжительност", "длительност", "duration"),
    "напряжение": ("напряжени", "voltage"),
    "сухой остаток": ("сухой остаток", "сухого остатка", "tds"),
}

_VALUE_RE = re.compile(
    rf"(?P<cmp>{_CMP}\s*)?(?P<value>{_RANGE})\s*(?P<unit>{_UNITS})",
    re.IGNORECASE,
)
_PH_RE = re.compile(rf"pH\s*[=:~]?\s*(?P<value>{_RANGE})", re.IGNORECASE)

_WINDOW = 80  # chars before a value in which to look for a parameter name


def _match_dict(text_lower: str, vocab: dict[str, tuple[str, ...]]) -> list[str]:
    found: list[str] = []
    for canonical, stems in vocab.items():
        if any(stem in text_lower for stem in stems):
            found.append(canonical)
    return found


def _param_name_near(text_lower: str, pos: int) -> str:
    window = text_lower[max(0, pos - _WINDOW):pos]
    best = ""
    best_pos = -1
    for canonical, stems in _PARAM_NAMES.items():
        for stem in stems:
            i = window.rfind(stem)
            if i > best_pos:
                best_pos = i
                best = canonical
    return best


def _extract_parameters(text: str, text_lower: str) -> tuple[list[Parameter], list[str]]:
    params: list[Parameter] = []
    numeric: list[str] = []
    seen: set[tuple[str, str, str]] = set()

    for m in _VALUE_RE.finditer(text):
        value = ((m.group("cmp") or "") + m.group("value")).strip()
        unit = m.group("unit").strip()
        name = _param_name_near(text_lower, m.start())
        numeric.append(f"{value} {unit}")
        if name:
            key = (name, value, unit)
            if key not in seen:
                seen.add(key)
                params.append(Parameter(name=name, value=value, unit=unit))

    for m in _PH_RE.finditer(text):
        key = ("pH", m.group("value"), "")
        if key not in seen:
            seen.add(key)
            params.append(Parameter(name="pH", value=m.group("value"), unit=""))
            numeric.append(f"pH {m.group('value')}")

    return params[:30], numeric[:50]


def _sentence_of(text: str, needle_stems: tuple[str, ...]) -> str:
    """First sentence containing any stem — used as relation evidence."""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        low = sent.lower()
        if any(s in low for s in needle_stems):
            return sent.strip()[:300]
    return text[:150].strip()


def _build_relations(text: str, text_lower: str,
                     materials: list[str], processes: list[str],
                     equipment: list[str]) -> list[Relation]:
    relations: list[Relation] = []
    for proc in processes[:6]:
        stems = PROCESSES[proc]
        evidence = _sentence_of(text, stems)
        ev_low = evidence.lower()
        for mat in materials[:8]:
            if any(s in ev_low for s in MATERIALS[mat]):
                relations.append(Relation(
                    source=proc, relation="USES", target=mat, evidence=evidence))
        for eq in equipment[:6]:
            if any(s in ev_low for s in EQUIPMENT[eq]):
                relations.append(Relation(
                    source=proc, relation="USES", target=eq, evidence=evidence))
    return relations[:20]


def extract_chunk_local(document_id: str, chunk_id: str, text: str) -> ExtractionRecord:
    text_lower = text.lower()

    materials = _match_dict(text_lower, MATERIALS)
    processes = _match_dict(text_lower, PROCESSES)
    equipment = _match_dict(text_lower, EQUIPMENT)
    conditions = _match_dict(text_lower, CONDITIONS)

    if any(g in text_lower for g in GEO_RU):
        conditions.append("отечественная практика")
    if any(g in text_lower for g in GEO_FOREIGN):
        conditions.append("зарубежная практика")

    parameters, numerical = _extract_parameters(text, text_lower)
    relations = _build_relations(text, text_lower, materials, processes, equipment)

    return ExtractionRecord(
        document_id=document_id,
        chunk_id=chunk_id,
        materials=materials,
        processes=processes,
        equipment=equipment,
        parameters=parameters,
        conditions=conditions,
        experiments=[],
        numerical_values=numerical,
        relations=relations,
        facts=[],
        model_used="local-rules",
        grounding_score=1.0,
    )
