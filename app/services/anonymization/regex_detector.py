import re
from typing import Pattern

from .types import Span


class RegexDetector:
    def __init__(self) -> None:
        self.patterns: dict[str, Pattern[str]] = {
            "EMAIL": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
            "PHONE": re.compile(
                r"(?:\+7|8)\s*\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}"
            ),
            "INN": re.compile(r"(?<!\d)(?:\d{10}|\d{12})(?!\d)"),
            "SNILS": re.compile(r"\b\d{3}-\d{3}-\d{3}\s\d{2}\b"),
            "PASSPORT": re.compile(r"\b\d{4}\s?\d{6}\b"),
            "OGRN": re.compile(r"(?<!\d)(?:\d{13}|\d{15})(?!\d)"),
            "BANK_ACCOUNT": re.compile(r"(?<!\d)\d{20}(?!\d)"),
            "BIC": re.compile(r"(?<!\d)\d{9}(?!\d)"),
        }

    def detect(self, text: str) -> list[Span]:
        spans: list[Span] = []
        for entity_type, pattern in self.patterns.items():
            for match in pattern.finditer(text):
                spans.append(
                    Span(
                        start=match.start(),
                        end=match.end(),
                        entity_type=entity_type,
                        score=1.0,
                        source="regex",
                    )
                )
        return spans
