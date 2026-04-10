from __future__ import annotations

import logging
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

from app.services.anonymization.anonymizer import AnonymizerService
from app.services.documents.ingestion_service import DocumentIngestionService
from app.services.export.docx_exporter import DocxReportExporter
from app.services.llm.client import RiskLlmAnalyzer
from app.services.ocr.stub import OcrStubService
from app.services.orchestration.state_store import InMemoryPipelineStateStore
from app.services.orchestration.types import (
    Finding,
    PipelineArtifacts,
    PipelineEvent,
    PipelineObservability,
    PipelineResult,
    PipelineStatusSnapshot,
    StageExecution,
)
from app.services.retrieval.normative_web import NormativeWebRetriever
from app.services.retrieval.query_builder import RetrievalQueryBuilder
from app.services.rules.engine import RiskRulesEngine
from app.services.storage.artifact_store import ArtifactStore
from app.services.validation.policy_validator import PolicyValidator
from app.services.validation.report_validator import ReportValidator

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    def __init__(
        self,
        ingestion_service: DocumentIngestionService,
        anonymizer_service: AnonymizerService,
        ocr_service: OcrStubService,
        rules_engine: RiskRulesEngine,
        retriever: NormativeWebRetriever,
        query_builder: RetrievalQueryBuilder,
        llm_analyzer: RiskLlmAnalyzer,
        report_validator: ReportValidator,
        policy_validator: PolicyValidator,
        artifact_store: ArtifactStore,
        docx_exporter: DocxReportExporter,
        state_store: InMemoryPipelineStateStore,
    ) -> None:
        self.ingestion_service = ingestion_service
        self.anonymizer_service = anonymizer_service
        self.ocr_service = ocr_service
        self.rules_engine = rules_engine
        self.retriever = retriever
        self.query_builder = query_builder
        self.llm_analyzer = llm_analyzer
        self.report_validator = report_validator
        self.policy_validator = policy_validator
        self.artifact_store = artifact_store
        self.docx_exporter = docx_exporter
        self.state_store = state_store

    def process(self, file_name: str, content: bytes, jurisdiction: str = "RU", use_ner: bool = True) -> PipelineResult:
        session_id = str(uuid4())
        degraded_flags: list[str] = []
        stages: list[StageExecution] = []
        observability = PipelineObservability()
        self._update_status(
            session_id=session_id,
            status="running",
            current_stage="INIT",
            file_name=file_name,
            file_type="unknown",
            degraded_flags=[],
            last_event=None,
        )
        logger.info(
            "session_id=%s pipeline_started file_name=%s jurisdiction=%s use_ner=%s",
            session_id,
            file_name,
            jurisdiction,
            use_ner,
        )

        parse_result = self._record_stage(
            session_id,
            stages,
            "INGEST",
            lambda: self.ingestion_service.parse(file_name, content),
            "Document parsed successfully",
        )
        ocr_result = self._record_stage(
            session_id,
            stages,
            "OCR",
            lambda: self.ocr_service.run(parse_result),
            "OCR stage completed",
        )
        degraded_flags.extend(ocr_result.degraded_flags or [])
        if ocr_result.degraded_flags:
            logger.info(
                "session_id=%s stage=OCR degraded_flags=%s",
                session_id,
                ",".join(ocr_result.degraded_flags),
            )

        anonymization_result = self._record_stage(
            session_id,
            stages,
            "ANONYMIZE",
            lambda: self.anonymizer_service.anonymize(parse_result.full_text, use_ner=use_ner),
            "Text anonymized successfully",
        )
        self._record_stage(
            session_id,
            stages,
            "POLICY_CHECK",
            lambda: self.policy_validator.ensure_external_analysis_allowed(anonymization_result.anonymized_text),
            "Policy check passed",
        )

        candidates = self._record_stage(
            session_id,
            stages,
            "RULES",
            lambda: self.rules_engine.detect(parse_result.paragraphs),
            "Rules stage completed",
        )
        logger.info(
            "session_id=%s stage=RULES candidates_detected=%s",
            session_id,
            len(candidates),
        )

        findings: list[Finding] = []
        for candidate in candidates:
            logger.info(
                "session_id=%s candidate_id=%s candidate_processing_started risk_type=%s paragraph_id=%s",
                session_id,
                candidate.candidate_id,
                candidate.risk_type,
                candidate.paragraph_id,
            )
            query = self.query_builder.build(candidate, jurisdiction)
            retrieval_result = self.retriever.retrieve(query)
            evidence = retrieval_result.evidence
            observability.retrieval_provider = retrieval_result.provider_used
            observability.retrieval_fallback_used = (
                observability.retrieval_fallback_used or retrieval_result.fallback_used
            )
            observability.events.append(
                PipelineEvent(
                    timestamp=datetime.now(UTC).isoformat(),
                    event_type="retrieval",
                    provider=retrieval_result.provider_used,
                    detail=f"Retrieved {len(evidence)} evidence items for {candidate.candidate_id}",
                )
            )
            self._append_session_log(
                session_id,
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": "INFO",
                    "event_type": "retrieval",
                    "provider": retrieval_result.provider_used,
                    "candidate_id": candidate.candidate_id,
                    "message": f"Retrieved {len(evidence)} evidence items",
                },
            )
            if retrieval_result.fallback_used:
                degraded_flags.append("tavily_failed_fallback_used")
                logger.warning(
                    "session_id=%s candidate_id=%s retrieval_fallback_used provider=%s",
                    session_id,
                    candidate.candidate_id,
                    retrieval_result.provider_used,
                )
            else:
                logger.info(
                    "session_id=%s candidate_id=%s retrieval_completed provider=%s evidence_count=%s",
                    session_id,
                    candidate.candidate_id,
                    retrieval_result.provider_used,
                    len(evidence),
                )

            analysis = self.llm_analyzer.analyze(candidate, evidence)
            observability.llm_provider = analysis.provider_used
            observability.llm_fallback_used = observability.llm_fallback_used or analysis.fallback_used
            observability.llm_prompt_tokens += analysis.prompt_tokens
            observability.llm_completion_tokens += analysis.completion_tokens
            observability.llm_cost_estimate = round(
                observability.llm_cost_estimate + analysis.cost_estimate,
                6,
            )
            observability.events.append(
                PipelineEvent(
                    timestamp=datetime.now(UTC).isoformat(),
                    event_type="llm_analysis",
                    provider=analysis.provider_used,
                    detail=f"Analyzed candidate {candidate.candidate_id}",
                )
            )
            self._append_session_log(
                session_id,
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                    "level": "INFO",
                    "event_type": "llm_analysis",
                    "provider": analysis.provider_used,
                    "candidate_id": candidate.candidate_id,
                    "message": "Analyzed candidate",
                    "prompt_tokens": analysis.prompt_tokens,
                    "completion_tokens": analysis.completion_tokens,
                    "cost_estimate": analysis.cost_estimate,
                },
            )
            if analysis.provider_used == "vllm":
                degraded_flags.append("openrouter_failed_vllm_used")
                logger.warning(
                    "session_id=%s candidate_id=%s llm_fallback_to_vllm prompt_tokens=%s completion_tokens=%s",
                    session_id,
                    candidate.candidate_id,
                    analysis.prompt_tokens,
                    analysis.completion_tokens,
                )
            elif analysis.provider_used == "local-fallback":
                degraded_flags.append("llm_fallback_used")
                logger.warning(
                    "session_id=%s candidate_id=%s llm_local_fallback_used",
                    session_id,
                    candidate.candidate_id,
                )
            else:
                logger.info(
                    "session_id=%s candidate_id=%s llm_completed provider=%s prompt_tokens=%s completion_tokens=%s cost_estimate=%s",
                    session_id,
                    candidate.candidate_id,
                    analysis.provider_used,
                    analysis.prompt_tokens,
                    analysis.completion_tokens,
                    analysis.cost_estimate,
                )

            findings.append(
                Finding(
                    finding_id=f"finding:{candidate.candidate_id}",
                    risk_type=candidate.risk_type,
                    paragraph_id=candidate.paragraph_id,
                    source_excerpt=None,
                    title=analysis.title,
                    summary=analysis.summary,
                    confidence=analysis.confidence,
                    suggested_edit=f"[{analysis.provider_used}] {analysis.suggested_edit}",
                    evidence=evidence,
                )
            )

        validation_flags = self._record_stage(
            session_id,
            stages,
            "VALIDATE",
            lambda: self.report_validator.validate(parse_result, findings),
            "Report validated successfully",
        )
        degraded_flags.extend(validation_flags)
        if validation_flags:
            logger.info(
                "session_id=%s stage=VALIDATE degraded_flags=%s",
                session_id,
                ",".join(validation_flags),
            )

        status = "degraded_success" if degraded_flags else "success"
        result = PipelineResult(
            session_id=session_id,
            status=status,
            file_name=parse_result.file_name,
            file_type=parse_result.file_type,
            jurisdiction=jurisdiction,
            degraded_flags=sorted(set(degraded_flags)),
            stages=stages,
            findings=findings,
            anonymized_text=anonymization_result.anonymized_text,
            spans=anonymization_result.spans,
            stats=anonymization_result.stats,
            artifacts=PipelineArtifacts(),
            observability=observability,
        )

        report_payload = self._report_payload(result)
        result.artifacts.encrypted_report_path = self.artifact_store.save_encrypted_json(session_id, "report", report_payload)
        result.artifacts.encrypted_anonymized_path = self.artifact_store.save_encrypted_json(
            session_id,
            "anonymized",
            {
                "anonymized_text": result.anonymized_text,
                "spans": result.spans,
                "stats": result.stats,
            },
        )
        result.artifacts.export_docx_path = self.artifact_store.save_plain_bytes(
            session_id,
            "report",
            self.docx_exporter.export(result),
            "docx",
        )
        result.artifacts.events_path = self.artifact_store.save_plain_json(
            session_id,
            "events",
            [asdict(event) for event in result.observability.events],
        )
        result.artifacts.session_log_path = str(self.artifact_store.base_dir / session_id / "pipeline.jsonl")
        logger.info(
            "session_id=%s pipeline_finished status=%s findings=%s degraded_flags=%s",
            session_id,
            status,
            len(findings),
            ",".join(result.degraded_flags) if result.degraded_flags else "none",
        )
        self._append_session_log(
            session_id,
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "INFO",
                "event_type": "pipeline_finished",
                "provider": "system",
                "message": "Pipeline finished",
                "status": status,
                "findings": len(findings),
                "degraded_flags": result.degraded_flags,
            },
        )
        self._update_status(
            session_id=session_id,
            status=status,
            current_stage="FINALIZE",
            file_name=result.file_name,
            file_type=result.file_type,
            degraded_flags=result.degraded_flags,
            last_event=result.observability.events[-1] if result.observability.events else None,
        )
        self.state_store.save(session_id, result)
        return result

    def get(self, session_id: str) -> PipelineResult | None:
        state = self.state_store.get(session_id)
        if isinstance(state, PipelineResult):
            return state
        return None

    def get_status(self, session_id: str) -> PipelineStatusSnapshot | None:
        return self.state_store.get_status(session_id)

    def _record_stage(self, session_id: str, stages: list[StageExecution], stage: str, fn, detail: str):
        started_at = datetime.now(UTC).isoformat()
        logger.info("session_id=%s stage=%s status=started", session_id, stage)
        current_file_name = self.state_store.get_status(session_id).file_name if self.state_store.get_status(session_id) else "unknown"
        current_file_type = self.state_store.get_status(session_id).file_type if self.state_store.get_status(session_id) else "unknown"
        self._update_status(
            session_id=session_id,
            status="running",
            current_stage=stage,
            file_name=current_file_name,
            file_type=current_file_type,
            degraded_flags=self.state_store.get_status(session_id).degraded_flags if self.state_store.get_status(session_id) else [],
            last_event=PipelineEvent(
                timestamp=started_at,
                event_type="stage_started",
                provider="system",
                detail=f"{stage} started",
            ),
        )
        self._append_session_log(
            session_id,
            {
                "timestamp": started_at,
                "level": "INFO",
                "event_type": "stage_started",
                "provider": "system",
                "stage": stage,
                "message": f"{stage} started",
            },
        )
        try:
            payload = fn()
            finished_at = datetime.now(UTC).isoformat()
            stages.append(
                StageExecution(
                    stage=stage,
                    status="success",
                    started_at=started_at,
                    finished_at=finished_at,
                    detail=detail,
                )
            )
            logger.info("session_id=%s stage=%s status=success detail=%s", session_id, stage, detail)
            if stage == "INGEST":
                file_name = getattr(payload, "file_name", current_file_name)
                file_type = getattr(payload, "file_type", current_file_type)
            else:
                file_name = current_file_name
                file_type = current_file_type
            event = PipelineEvent(
                timestamp=finished_at,
                event_type="stage_finished",
                provider="system",
                detail=f"{stage} finished",
            )
            self._update_status(
                session_id=session_id,
                status="running",
                current_stage=stage,
                file_name=file_name,
                file_type=file_type,
                degraded_flags=self.state_store.get_status(session_id).degraded_flags if self.state_store.get_status(session_id) else [],
                last_event=event,
            )
            self._append_session_log(
                session_id,
                {
                    "timestamp": finished_at,
                    "level": "INFO",
                    "event_type": "stage_finished",
                    "provider": "system",
                    "stage": stage,
                    "message": detail,
                },
            )
            return payload
        except Exception as exc:
            finished_at = datetime.now(UTC).isoformat()
            stages.append(
                StageExecution(
                    stage=stage,
                    status="error",
                    started_at=started_at,
                    finished_at=finished_at,
                    detail=str(exc),
                )
            )
            logger.exception("session_id=%s stage=%s status=error detail=%s", session_id, stage, exc)
            event = PipelineEvent(
                timestamp=finished_at,
                event_type="stage_failed",
                provider="system",
                detail=f"{stage} failed: {exc}",
            )
            self._update_status(
                session_id=session_id,
                status="error",
                current_stage=stage,
                file_name=current_file_name,
                file_type=current_file_type,
                degraded_flags=self.state_store.get_status(session_id).degraded_flags if self.state_store.get_status(session_id) else [],
                last_event=event,
            )
            self._append_session_log(
                session_id,
                {
                    "timestamp": finished_at,
                    "level": "ERROR",
                    "event_type": "stage_failed",
                    "provider": "system",
                    "stage": stage,
                    "message": str(exc),
                },
            )
            raise

    def _append_session_log(self, session_id: str, payload: dict) -> None:
        self.artifact_store.append_jsonl(session_id, "pipeline", {"session_id": session_id, **payload})

    def _update_status(
        self,
        session_id: str,
        status: str,
        current_stage: str | None,
        file_name: str,
        file_type: str,
        degraded_flags: list[str],
        last_event: PipelineEvent | None,
    ) -> None:
        self.state_store.save_status(
            session_id,
            PipelineStatusSnapshot(
                session_id=session_id,
                status=status,
                current_stage=current_stage,
                file_name=file_name,
                file_type=file_type,
                degraded_flags=degraded_flags,
                last_event=last_event,
            ),
        )

    def _report_payload(self, result: PipelineResult) -> dict:
        return {
            "session_id": result.session_id,
            "status": result.status,
            "file_name": result.file_name,
            "file_type": result.file_type,
            "jurisdiction": result.jurisdiction,
            "degraded_flags": result.degraded_flags,
            "stages": [asdict(stage) for stage in result.stages],
            "findings": [
                {
                    **asdict(finding),
                    "evidence": [asdict(item) for item in finding.evidence],
                }
                for finding in result.findings
            ],
            "stats": result.stats,
            "observability": asdict(result.observability),
        }
