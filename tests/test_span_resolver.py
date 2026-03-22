from app.services.anonymization.span_resolver import SpanResolver
from app.services.anonymization.types import Span


def test_span_resolver_handles_empty_input() -> None:
    resolver = SpanResolver()
    assert resolver.resolve([]) == []


def test_span_resolver_prefers_regex_over_ner_on_overlap() -> None:
    resolver = SpanResolver()
    spans = [
        Span(start=0, end=10, entity_type="PERSON", score=0.9, source="ner"),
        Span(start=0, end=8, entity_type="INN", score=1.0, source="regex"),
    ]

    result = resolver.resolve(spans)

    assert len(result) == 1
    assert result[0].source == "regex"


def test_span_resolver_keeps_non_overlapping_spans() -> None:
    resolver = SpanResolver()
    spans = [
        Span(start=0, end=4, entity_type="A", score=1.0, source="regex"),
        Span(start=10, end=14, entity_type="B", score=1.0, source="ner"),
    ]

    result = resolver.resolve(spans)

    assert len(result) == 2
    assert result[0].start == 0
    assert result[1].start == 10
