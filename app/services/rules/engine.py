from __future__ import annotations

from app.services.documents.types import DocumentParagraph
from app.services.orchestration.types import RiskCandidate
from app.services.rules.catalog import RULE_DEFINITIONS


class RiskRulesEngine:
    def detect(self, paragraphs: list[DocumentParagraph]) -> list[RiskCandidate]:
        candidates: list[RiskCandidate] = []

        for paragraph in paragraphs:
            lowered = paragraph.text.lower()
            for rule in RULE_DEFINITIONS:
                matched_pattern = next((pattern for pattern in rule.patterns if pattern in lowered), None)
                if not matched_pattern:
                    continue
                candidates.append(
                    RiskCandidate(
                        candidate_id=f"{rule.risk_type}:{paragraph.paragraph_id}",
                        risk_type=rule.risk_type,
                        paragraph_id=paragraph.paragraph_id,
                        paragraph_text=paragraph.text,
                        matched_text=matched_pattern,
                    )
                )

        return candidates
