from dataclasses import dataclass


@dataclass(slots=True)
class Span:
    start: int
    end: int
    entity_type: str
    score: float
    source: str


@dataclass(slots=True)
class AnonymizationResult:
    anonymized_text: str
    spans: list[dict]
    stats: dict[str, int]
