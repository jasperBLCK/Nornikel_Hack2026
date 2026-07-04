"""Strict Pydantic schema for Stage 3 output.

Every field is required even if empty list — guarantees the JSON shape
is identical for every chunk (downstream parsers rely on this).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---- Leaf types -----------------------------------------------------------


class Parameter(BaseModel):
    name: str = Field(..., description="Parameter name as written in text")
    value: str = Field(..., description="Numeric or qualitative value, exact as in text")
    unit: str = Field(default="", description="Unit exactly as written; '' if absent")

    @field_validator("name", "value", "unit")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class Relation(BaseModel):
    source: str
    relation: str
    target: str
    evidence: str = Field(..., min_length=1,
                          description="Verbatim quote from source text")

    @field_validator("source", "relation", "target", "evidence")
    @classmethod
    def _strip(cls, v: str) -> str:
        return v.strip()


class Fact(BaseModel):
    statement: str = Field(..., min_length=1)
    confidence: float = Field(..., ge=0.0, le=1.0)


# ---- Top-level extraction record ------------------------------------------


class ExtractionRecord(BaseModel):
    document_id: str
    chunk_id: str

    materials: list[str] = Field(default_factory=list)
    processes: list[str] = Field(default_factory=list)
    equipment: list[str] = Field(default_factory=list)

    parameters: list[Parameter] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)
    experiments: list[str] = Field(default_factory=list)
    numerical_values: list[str] = Field(default_factory=list)

    relations: list[Relation] = Field(default_factory=list)
    facts: list[Fact] = Field(default_factory=list)

    model_used: str = ""
    grounding_score: float | None = None


# ---- Grounding judge output ----------------------------------------------


class GroundingVerdict(BaseModel):
    score: float = Field(..., ge=0.0, le=1.0,
                        description="Fraction of extracted fields backed by the text")
    rationale: str = ""
    action: Literal["accept", "reject"]