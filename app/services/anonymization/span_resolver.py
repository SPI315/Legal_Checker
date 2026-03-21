from .types import Span


class SpanResolver:
    def resolve(self, spans: list[Span]) -> list[Span]:
        if not spans:
            return []

        ordered = sorted(
            spans,
            key=lambda s: (s.start, -(s.end - s.start), -self._priority(s), -s.score),
        )

        result: list[Span] = []
        for span in ordered:
            overlap_index = self._find_overlap(result, span)
            if overlap_index is None:
                result.append(span)
                continue

            current = result[overlap_index]
            if self._is_better(span, current):
                result[overlap_index] = span

        result = sorted(result, key=lambda s: (s.start, s.end))
        return result

    def _find_overlap(self, chosen: list[Span], candidate: Span) -> int | None:
        for idx, existing in enumerate(chosen):
            if not (candidate.end <= existing.start or candidate.start >= existing.end):
                return idx
        return None

    def _is_better(self, a: Span, b: Span) -> bool:
        if self._priority(a) != self._priority(b):
            return self._priority(a) > self._priority(b)
        if (a.end - a.start) != (b.end - b.start):
            return (a.end - a.start) > (b.end - b.start)
        return a.score > b.score

    def _priority(self, span: Span) -> int:
        return 2 if span.source == "regex" else 1
