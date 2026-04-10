from __future__ import annotations

from app.services.documents.types import DocumentParseResult
from app.services.orchestration.types import Finding


class ReportValidator:
    def validate(self, parse_result: DocumentParseResult, findings: list[Finding]) -> list[str]:
        paragraph_ids = {paragraph.paragraph_id for paragraph in parse_result.paragraphs}
        degraded_flags: list[str] = []

        for finding in findings:
            if finding.paragraph_id not in paragraph_ids:
                raise ValueError(f"Unknown paragraph_id in finding: {finding.paragraph_id}")
            if not finding.evidence:
                degraded_flags.append("retrieval_empty")

        return sorted(set(degraded_flags))
