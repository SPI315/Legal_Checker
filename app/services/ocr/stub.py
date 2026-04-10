from __future__ import annotations

from app.services.documents.types import DocumentParseResult
from app.services.ocr.types import OcrStageResult


class OcrStubService:
    def run(self, parse_result: DocumentParseResult) -> OcrStageResult:
        if parse_result.file_type != "pdf":
            return OcrStageResult(
                status="skipped",
                detail="OCR skipped for non-PDF document",
                quality_flag=None,
                degraded_flags=[],
            )

        if parse_result.full_text.strip():
            return OcrStageResult(
                status="skipped_stub_not_needed",
                detail="PDF already contains extractable text; OCR stub not used",
                quality_flag="not_applicable",
                degraded_flags=[],
            )

        return OcrStageResult(
            status="ocr_skipped_stub",
            detail="OCR stage is stubbed in this iteration",
            quality_flag="unknown",
            degraded_flags=["ocr_stub_used", "low_quality_text"],
        )
