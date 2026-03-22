from __future__ import annotations

import logging
from typing import Any

from .types import Span

logger = logging.getLogger(__name__)


class TransformerNerDetector:
    def __init__(
        self,
        model_name: str,
        min_score: float = 0.6,
        device: int = -1,
        entity_mapping: dict[str, str] | None = None,
    ) -> None:
        self.model_name = model_name.strip()
        self.min_score = min_score
        self.device = device
        self.entity_mapping = entity_mapping or {
            "PER": "PERSON",
            "PERSON": "PERSON",
            "ORG": "ORGANIZATION",
            "LOC": "LOCATION",
            "GPE": "LOCATION",
        }
        self._pipeline: Any | None = None

    def _load_pipeline(self) -> None:
        if self._pipeline is not None:
            return
        if not self.model_name:
            logger.warning("NER model is not configured. Running regex-only mode.")
            return

        try:
            from transformers import pipeline

            self._pipeline = pipeline(
                task="token-classification",
                model=self.model_name,
                aggregation_strategy="simple",
                device=self.device,
            )
        except Exception:
            logger.exception("Failed to initialize transformers NER pipeline")
            self._pipeline = None

    def detect(self, text: str) -> list[Span]:
        self._load_pipeline()
        if self._pipeline is None:
            return []

        spans: list[Span] = []
        try:
            predictions = self._pipeline(text)
        except Exception:
            logger.exception("Failed to run NER inference")
            return []

        for pred in predictions:
            score = float(pred.get("score", 0.0))
            if score < self.min_score:
                continue

            raw_entity = self._normalize_label(
                str(pred.get("entity_group") or pred.get("entity") or "").upper()
            )
            mapped = self.entity_mapping.get(raw_entity)
            if not mapped:
                continue

            start = pred.get("start")
            end = pred.get("end")
            if start is None or end is None:
                continue

            spans.append(
                Span(
                    start=int(start),
                    end=int(end),
                    entity_type=mapped,
                    score=score,
                    source="ner",
                )
            )

        return spans

    def _normalize_label(self, label: str) -> str:
        if not label:
            return ""

        # Common token-level prefixes in NER tags.
        for prefix in ("B-", "I-", "L-", "U-", "S-", "E-"):
            if label.startswith(prefix):
                return label[len(prefix) :]

        # Some models output underscore variants like B_PER.
        for prefix in ("B_", "I_", "L_", "U_", "S_", "E_"):
            if label.startswith(prefix):
                return label[len(prefix) :]

        return label
