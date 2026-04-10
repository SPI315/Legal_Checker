from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from app.services.anonymization.anonymizer import AnonymizerService
from app.services.documents.ingestion_service import DocumentIngestionService
from app.services.export.docx_exporter import DocxReportExporter
from app.services.llm.client import RiskLlmAnalyzer
from app.services.ocr.stub import OcrStubService
from app.services.orchestration.state_store import InMemoryPipelineStateStore
from app.services.orchestration.types import (
    EvidenceItem,
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

MIN_EVIDENCE_COUNT = 2
MIN_RETRIEVAL_SCORE = 0.35
LEGAL_BASIS_MARKERS = (
    "ст.",
    "статья",
    "гк рф",
    "постановление",
    "обзор судебной практики",
    "верховного суда",
)


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
        self.initialize_session(session_id, file_name)
        return self.process_with_session(
            session_id=session_id,
            file_name=file_name,
            content=content,
            jurisdiction=jurisdiction,
            use_ner=use_ner,
        )

    def initialize_session(self, session_id: str, file_name: str) -> None:
        self._update_status(
            session_id=session_id,
            status="queued",
            current_stage="INIT",
            file_name=file_name,
            file_type="unknown",
            degraded_flags=[],
            last_event=None,
        )
        self._append_session_log(
            session_id,
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "INFO",
                "event_type": "session_queued",
                "provider": "system",
                "message": "Session queued for processing",
            },
        )

    def process_with_session(
        self,
        session_id: str,
        file_name: str,
        content: bytes,
        jurisdiction: str = "RU",
        use_ner: bool = True,
    ) -> PipelineResult:
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
            finding = self._process_candidate(
                session_id=session_id,
                candidate=candidate,
                jurisdiction=jurisdiction,
                observability=observability,
                degraded_flags=degraded_flags,
            )
            findings.append(finding)

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

    def get_timeline(self, session_id: str) -> list[dict] | None:
        path = self.artifact_store.base_dir / session_id / "pipeline.jsonl"
        if not path.exists():
            return None

        entries: list[dict] = []
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                entries.append(json.loads(line))
        return entries

    def _process_candidate(
        self,
        session_id: str,
        candidate,
        jurisdiction: str,
        observability: PipelineObservability,
        degraded_flags: list[str],
    ) -> Finding:
        logger.info(
            "session_id=%s candidate_id=%s candidate_processing_started risk_type=%s paragraph_id=%s",
            session_id,
            candidate.candidate_id,
            candidate.risk_type,
            candidate.paragraph_id,
        )
        self._log_candidate_event(
            session_id,
            candidate.candidate_id,
            "candidate_selected",
            "system",
            f"Candidate selected for bounded decision loop ({candidate.risk_type})",
            observability,
        )

        initial_query = self.query_builder.build(candidate, jurisdiction)
        initial_result = self._run_retrieval_pass(
            session_id=session_id,
            candidate_id=candidate.candidate_id,
            retrieval_request=initial_query,
            pass_index=1,
            observability=observability,
        )

        selected_query = initial_query
        selected_result = initial_result
        selected_evidence = initial_result.evidence
        evidence_reason = self._evidence_reason(initial_result.evidence, initial_result.fallback_used)

        self._log_candidate_event(
            session_id,
            candidate.candidate_id,
            "evidence_evaluated",
            "system",
            f"Pass 1 evidence evaluation: {evidence_reason}",
            observability,
        )
        logger.info(
            "session_id=%s candidate_id=%s decision=evidence_evaluated pass=1 sufficient=%s reason=%s",
            session_id,
            candidate.candidate_id,
            self._evidence_is_sufficient(initial_result.evidence, initial_result.fallback_used),
            evidence_reason,
        )

        if not self._evidence_is_sufficient(initial_result.evidence, initial_result.fallback_used):
            refined_query = self.query_builder.build_refined(
                candidate=candidate,
                jurisdiction=jurisdiction,
                prior_query=initial_query.query,
                evidence=initial_result.evidence,
            )
            self._log_candidate_event(
                session_id,
                candidate.candidate_id,
                "retrieval_refine_decision",
                "system",
                "Evidence insufficient after pass 1; running one refined retrieval pass",
                observability,
            )
            logger.info(
                "session_id=%s candidate_id=%s decision=refine_retrieval reason=%s prior_query=%s refined_query=%s",
                session_id,
                candidate.candidate_id,
                evidence_reason,
                initial_query.query,
                refined_query.query,
            )
            refined_result = self._run_retrieval_pass(
                session_id=session_id,
                candidate_id=candidate.candidate_id,
                retrieval_request=refined_query,
                pass_index=2,
                observability=observability,
            )
            selected_query, selected_result = self._select_retrieval_result(
                initial_query,
                initial_result,
                refined_query,
                refined_result,
            )
            selected_evidence = selected_result.evidence
            refined_reason = self._evidence_reason(selected_result.evidence, selected_result.fallback_used)
            self._log_candidate_event(
                session_id,
                candidate.candidate_id,
                "evidence_evaluated",
                "system",
                f"Final evidence decision after pass 2: {refined_reason}",
                observability,
            )
            logger.info(
                "session_id=%s candidate_id=%s decision=final_evidence_selection selected_pass=%s sufficient=%s reason=%s",
                session_id,
                candidate.candidate_id,
                2 if selected_query.query == refined_query.query else 1,
                self._evidence_is_sufficient(selected_result.evidence, selected_result.fallback_used),
                refined_reason,
            )

        if selected_result.fallback_used:
            degraded_flags.append("tavily_failed_fallback_used")
            logger.warning(
                "session_id=%s candidate_id=%s retrieval_fallback_used provider=%s",
                session_id,
                candidate.candidate_id,
                selected_result.provider_used,
            )

        if not self._evidence_is_sufficient(selected_evidence, selected_result.fallback_used):
            degraded_flags.append("retrieval_low_evidence")
            logger.warning(
                "session_id=%s candidate_id=%s retrieval_low_evidence provider=%s evidence_count=%s max_score=%s query=%s",
                session_id,
                candidate.candidate_id,
                selected_result.provider_used,
                len(selected_evidence),
                self._max_retrieval_score(selected_evidence),
                selected_query.query,
            )

        analysis = self.llm_analyzer.analyze(candidate, selected_evidence)
        observability.llm_provider = analysis.provider_used
        observability.llm_fallback_used = observability.llm_fallback_used or analysis.fallback_used
        observability.llm_prompt_tokens += analysis.prompt_tokens
        observability.llm_completion_tokens += analysis.completion_tokens
        observability.llm_cost_estimate = round(
            observability.llm_cost_estimate + analysis.cost_estimate,
            6,
        )
        self._log_candidate_event(
            session_id,
            candidate.candidate_id,
            "llm_analysis",
            analysis.provider_used,
            "Analyzed candidate after evidence resolution",
            observability,
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

        unsupported_citation_terms = self._unsupported_finding_citation_terms(analysis, selected_evidence)
        legal_basis_supported = (
            self._legal_basis_is_supported(analysis.legal_basis, selected_evidence)
            and not unsupported_citation_terms
        )
        self._log_candidate_event(
            session_id,
            candidate.candidate_id,
            "legal_basis_evaluated",
            "system",
            (
                "Legal basis supported by evidence"
                if legal_basis_supported
                else "Legal basis not confirmed by evidence"
            ),
            observability,
        )
        logger.info(
            "session_id=%s candidate_id=%s decision=legal_basis_evaluated supported=%s legal_basis=%s",
            session_id,
            candidate.candidate_id,
            legal_basis_supported,
            analysis.legal_basis or "<empty>",
        )

        if (analysis.legal_basis or unsupported_citation_terms) and not legal_basis_supported:
            focus_terms = self._extract_legal_basis_focus_terms(analysis.legal_basis)
            focus_terms.extend(unsupported_citation_terms)
            focus_terms = list(dict.fromkeys(focus_terms))
            legal_basis_query = self.query_builder.build_refined(
                candidate=candidate,
                jurisdiction=jurisdiction,
                prior_query=selected_query.query,
                evidence=selected_evidence,
                focus_terms=focus_terms,
            )
            self._log_candidate_event(
                session_id,
                candidate.candidate_id,
                "legal_basis_refine_decision",
                "system",
                "Legal basis unsupported; running targeted retrieval for supporting sources",
                observability,
            )
            logger.info(
                "session_id=%s candidate_id=%s decision=legal_basis_refine prior_query=%s refined_query=%s focus_terms=%s",
                session_id,
                candidate.candidate_id,
                selected_query.query,
                legal_basis_query.query,
                ",".join(focus_terms) if focus_terms else "none",
            )
            legal_basis_result = self._run_retrieval_pass(
                session_id=session_id,
                candidate_id=candidate.candidate_id,
                retrieval_request=legal_basis_query,
                pass_index=3,
                observability=observability,
            )
            if self._retrieval_quality_score(legal_basis_result.evidence, legal_basis_result.fallback_used) > self._retrieval_quality_score(
                selected_evidence,
                selected_result.fallback_used,
            ):
                selected_query = legal_basis_query
                selected_result = legal_basis_result
                selected_evidence = legal_basis_result.evidence
                analysis = self.llm_analyzer.analyze(candidate, selected_evidence)
                observability.llm_provider = analysis.provider_used
                observability.llm_fallback_used = observability.llm_fallback_used or analysis.fallback_used
                observability.llm_prompt_tokens += analysis.prompt_tokens
                observability.llm_completion_tokens += analysis.completion_tokens
                observability.llm_cost_estimate = round(
                    observability.llm_cost_estimate + analysis.cost_estimate,
                    6,
                )
                self._log_candidate_event(
                    session_id,
                    candidate.candidate_id,
                    "llm_analysis",
                    analysis.provider_used,
                    "Re-analyzed candidate after legal basis retrieval refinement",
                    observability,
                )
                logger.info(
                    "session_id=%s candidate_id=%s llm_reanalysis_completed provider=%s prompt_tokens=%s completion_tokens=%s cost_estimate=%s",
                    session_id,
                    candidate.candidate_id,
                    analysis.provider_used,
                    analysis.prompt_tokens,
                    analysis.completion_tokens,
                    analysis.cost_estimate,
                )
                unsupported_citation_terms = self._unsupported_finding_citation_terms(analysis, selected_evidence)
                legal_basis_supported = (
                    self._legal_basis_is_supported(analysis.legal_basis, selected_evidence)
                    and not unsupported_citation_terms
                )

        if (analysis.legal_basis or unsupported_citation_terms) and not legal_basis_supported:
            degraded_flags.append("unsupported_legal_basis")
            self._log_candidate_event(
                session_id,
                candidate.candidate_id,
                "legal_basis_warning",
                "system",
                "Finding contains legal basis text that is not confirmed by current evidence",
                observability,
            )
            logger.warning(
                "session_id=%s candidate_id=%s legal_basis_unsupported legal_basis=%s",
                session_id,
                candidate.candidate_id,
                analysis.legal_basis,
            )

        self._log_candidate_event(
            session_id,
            candidate.candidate_id,
            "finding_accepted",
            "system",
            f"Finding accepted with provider={analysis.provider_used} evidence_count={len(selected_evidence)}",
            observability,
        )
        logger.info(
            "session_id=%s candidate_id=%s decision=finding_accepted provider=%s evidence_count=%s confidence=%s",
            session_id,
            candidate.candidate_id,
            analysis.provider_used,
            len(selected_evidence),
            analysis.confidence,
        )

        return Finding(
            finding_id=f"finding:{candidate.candidate_id}",
            risk_type=candidate.risk_type,
            paragraph_id=candidate.paragraph_id,
            source_excerpt=candidate.paragraph_text,
            title=analysis.title,
            summary=self._summary_with_clause(candidate.paragraph_id, analysis.summary),
            legal_basis=self._legal_basis_with_best_source(analysis.legal_basis, selected_evidence),
            legal_basis_supported=legal_basis_supported,
            confidence=analysis.confidence,
            suggested_edit=f"[{analysis.provider_used}] {analysis.suggested_edit}",
            evidence=selected_evidence,
        )

    def _run_retrieval_pass(
        self,
        session_id: str,
        candidate_id: str,
        retrieval_request,
        pass_index: int,
        observability: PipelineObservability,
    ):
        logger.info(
            "session_id=%s candidate_id=%s retrieval_pass_started pass=%s query=%s",
            session_id,
            candidate_id,
            pass_index,
            retrieval_request.query,
        )
        result = self.retriever.retrieve(retrieval_request)
        self._log_candidate_event(
            session_id,
            candidate_id,
            f"retrieval_pass_{pass_index}",
            result.provider_used,
            f"Retrieved {len(result.evidence)} evidence items on pass {pass_index}",
            observability,
        )
        self._append_session_log(
            session_id,
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "level": "INFO",
                "event_type": f"retrieval_pass_{pass_index}",
                "provider": result.provider_used,
                "candidate_id": candidate_id,
                "query": retrieval_request.query,
                "message": f"Retrieved {len(result.evidence)} evidence items",
                "evidence_count": len(result.evidence),
                "fallback_used": result.fallback_used,
            },
        )
        if result.fallback_used:
            logger.warning(
                "session_id=%s candidate_id=%s retrieval_fallback_used pass=%s provider=%s",
                session_id,
                candidate_id,
                pass_index,
                result.provider_used,
            )
        else:
            logger.info(
                "session_id=%s candidate_id=%s retrieval_completed pass=%s provider=%s evidence_count=%s",
                session_id,
                candidate_id,
                pass_index,
                result.provider_used,
                len(result.evidence),
            )
        return result

    def _select_retrieval_result(self, initial_query, initial_result, refined_query, refined_result):
        initial_score = self._retrieval_quality_score(initial_result.evidence, initial_result.fallback_used)
        refined_score = self._retrieval_quality_score(refined_result.evidence, refined_result.fallback_used)
        if refined_score > initial_score:
            return refined_query, refined_result
        return initial_query, initial_result

    def _retrieval_quality_score(self, evidence: list[EvidenceItem], fallback_used: bool) -> float:
        base = len(evidence) * 10
        if fallback_used:
            base -= 10
        return base + self._max_retrieval_score(evidence)

    def _max_retrieval_score(self, evidence: list[EvidenceItem]) -> float:
        if not evidence:
            return 0.0
        return max(item.retrieval_score for item in evidence)

    def _legal_basis_is_supported(self, legal_basis: str, evidence: list[EvidenceItem]) -> bool:
        normalized = (legal_basis or "").strip().lower()
        if not normalized:
            return True

        evidence_text = " ".join(
            f"{item.title} {item.snippet} {item.uri}".lower()
            for item in evidence
        )
        if not evidence_text:
            return False

        if any(marker in normalized for marker in LEGAL_BASIS_MARKERS):
            citations = self._extract_citation_tokens(normalized)
            if citations:
                return all(self._citation_token_supported(token, evidence_text) for token in citations)
            return any(marker in evidence_text for marker in LEGAL_BASIS_MARKERS if marker in normalized)

        return True

    def _summary_with_clause(self, paragraph_id: str, summary: str) -> str:
        clean_summary = " ".join((summary or "").split())
        if not clean_summary:
            clean_summary = "Обнаружена потенциально рискованная формулировка."

        clause_match = re.search(r"p\d+_(\d+)", paragraph_id or "")
        clause = clause_match.group(1) if clause_match else paragraph_id
        if not clause:
            return clean_summary

        clause_prefix = f"Пункт {clause}"
        if clean_summary.lower().startswith(clause_prefix.lower()):
            return clean_summary
        return f"{clause_prefix}: {clean_summary}"

    def _legal_basis_with_best_source(self, legal_basis: str, evidence: list[EvidenceItem]) -> str | None:
        clean_basis = " ".join((legal_basis or "").split())
        best_source = self._best_evidence_source(evidence)
        if not clean_basis and not best_source:
            return None
        if not best_source:
            return clean_basis or None

        source_excerpt = self._trim_source_excerpt(best_source.snippet)
        parts = []
        if clean_basis:
            parts.append(clean_basis)
        if source_excerpt:
            parts.append(f"Фрагмент источника: {source_excerpt}")
        parts.append(f"Источник: {best_source.title} — {best_source.uri}")
        return "\n".join(parts)

    def _best_evidence_source(self, evidence: list[EvidenceItem]) -> EvidenceItem | None:
        if not evidence:
            return None
        return max(evidence, key=lambda item: item.retrieval_score)

    def _trim_source_excerpt(self, snippet: str, limit: int = 520) -> str:
        clean_snippet = " ".join((snippet or "").split())
        if len(clean_snippet) <= limit:
            return clean_snippet
        return clean_snippet[:limit].rstrip(" ,.;:") + "..."

    def _unsupported_finding_citation_terms(self, analysis, evidence: list[EvidenceItem]) -> list[str]:
        finding_text = " ".join(
            [
                analysis.title or "",
                analysis.summary or "",
                analysis.legal_basis or "",
                analysis.suggested_edit or "",
            ]
        ).lower()
        tokens = self._extract_citation_tokens(finding_text)
        if not tokens:
            return []

        evidence_text = " ".join(
            f"{item.title} {item.snippet} {item.uri}".lower()
            for item in evidence
        )
        return [
            token
            for token in tokens
            if not self._citation_token_supported(token, evidence_text)
        ]

    def _extract_citation_tokens(self, legal_basis: str) -> list[str]:
        tokens = re.findall(r"(ст\.?\s*\d+(?:\.\d+)?)", legal_basis)
        if "гк рф" in legal_basis:
            tokens.append("гк рф")
        return list(dict.fromkeys(token.strip().lower() for token in tokens))

    def _citation_token_supported(self, token: str, evidence_text: str) -> bool:
        if token in evidence_text:
            return True
        article_match = re.search(r"ст\.?\s*(\d+(?:\.\d+)?)", token)
        if article_match:
            number = article_match.group(1)
            return f"статья {number}" in evidence_text or f"ст. {number}" in evidence_text
        return False

    def _extract_legal_basis_focus_terms(self, legal_basis: str) -> list[str]:
        focus_terms: list[str] = []
        for token in self._extract_citation_tokens(legal_basis):
            focus_terms.append(token)
        if "скрыт" in legal_basis.lower():
            focus_terms.append("скрытые недостатки товара")
        return list(dict.fromkeys(term for term in focus_terms if term))

    def _evidence_is_sufficient(self, evidence: list[EvidenceItem], fallback_used: bool) -> bool:
        if fallback_used:
            return False
        if len(evidence) < MIN_EVIDENCE_COUNT:
            return False
        return self._max_retrieval_score(evidence) >= MIN_RETRIEVAL_SCORE

    def _evidence_reason(self, evidence: list[EvidenceItem], fallback_used: bool) -> str:
        if fallback_used:
            return "fallback_evidence_used"
        if not evidence:
            return "retrieval_empty"
        if len(evidence) < MIN_EVIDENCE_COUNT:
            return f"evidence_count_below_threshold:{len(evidence)}"
        max_score = self._max_retrieval_score(evidence)
        if max_score < MIN_RETRIEVAL_SCORE:
            return f"retrieval_score_below_threshold:{max_score:.3f}"
        return "evidence_sufficient"

    def _log_candidate_event(
        self,
        session_id: str,
        candidate_id: str,
        event_type: str,
        provider: str,
        detail: str,
        observability: PipelineObservability,
    ) -> None:
        event = PipelineEvent(
            timestamp=datetime.now(UTC).isoformat(),
            event_type=event_type,
            provider=provider,
            detail=f"{candidate_id}: {detail}",
        )
        observability.events.append(event)
        self._append_session_log(
            session_id,
            {
                "timestamp": event.timestamp,
                "level": "INFO",
                "event_type": event_type,
                "provider": provider,
                "candidate_id": candidate_id,
                "message": detail,
            },
        )

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
