from .regex_detector import RegexDetector
from .span_resolver import SpanResolver
from .transformer_detector import TransformerNerDetector
from .types import AnonymizationResult, Span


class AnonymizerService:
    def __init__(
        self,
        regex_detector: RegexDetector,
        ner_detector: TransformerNerDetector,
        resolver: SpanResolver,
    ) -> None:
        self.regex_detector = regex_detector
        self.ner_detector = ner_detector
        self.resolver = resolver

    def anonymize(self, text: str, use_ner: bool = True) -> AnonymizationResult:
        regex_spans = self.regex_detector.detect(text)
        ner_spans = self.ner_detector.detect(text) if use_ner else []

        merged_spans = self.resolver.resolve(regex_spans + ner_spans)
        anonymized_text, spans_payload, stats = self._apply_masks(text, merged_spans)

        return AnonymizationResult(
            anonymized_text=anonymized_text,
            spans=spans_payload,
            stats=stats,
        )

    def _apply_masks(self, text: str, spans: list[Span]) -> tuple[str, list[dict], dict[str, int]]:
        counters: dict[str, int] = {}
        stats: dict[str, int] = {}
        payload: list[dict] = []

        mutable = text
        # Replacing from right to left keeps offsets valid for untouched spans.
        for span in sorted(spans, key=lambda s: s.start, reverse=True):
            counters[span.entity_type] = counters.get(span.entity_type, 0) + 1
            replacement = f"[{span.entity_type}_{counters[span.entity_type]}]"

            mutable = mutable[: span.start] + replacement + mutable[span.end :]
            stats[span.entity_type] = stats.get(span.entity_type, 0) + 1

            payload.append(
                {
                    "start": span.start,
                    "end": span.end,
                    "entity_type": span.entity_type,
                    "score": round(span.score, 4),
                    "source": span.source,
                    "replacement": replacement,
                }
            )

        payload.sort(key=lambda x: (x["start"], x["end"]))
        return mutable, payload, stats
