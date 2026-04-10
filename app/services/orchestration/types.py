from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class StageExecution:
    stage: str
    status: str
    started_at: str
    finished_at: str
    detail: str | None = None


@dataclass(slots=True)
class RiskCandidate:
    candidate_id: str
    risk_type: str
    paragraph_id: str
    paragraph_text: str
    matched_text: str
    severity: str = "medium"


@dataclass(slots=True)
class EvidenceItem:
    source_id: str
    source_type: str
    title: str
    snippet: str
    uri: str
    retrieval_score: float
    retrieved_at: str


@dataclass(slots=True)
class Finding:
    finding_id: str
    risk_type: str
    paragraph_id: str
    source_excerpt: str | None
    title: str
    summary: str
    legal_basis: str | None
    confidence: float
    suggested_edit: str
    legal_basis_supported: bool = True
    evidence: list[EvidenceItem] = field(default_factory=list)


@dataclass(slots=True)
class PipelineArtifacts:
    encrypted_report_path: str | None = None
    encrypted_anonymized_path: str | None = None
    export_docx_path: str | None = None
    events_path: str | None = None
    session_log_path: str | None = None


@dataclass(slots=True)
class PipelineEvent:
    timestamp: str
    event_type: str
    provider: str
    detail: str


@dataclass(slots=True)
class PipelineObservability:
    llm_provider: str | None = None
    llm_fallback_used: bool = False
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_cost_estimate: float = 0.0
    retrieval_provider: str | None = None
    retrieval_fallback_used: bool = False
    events: list[PipelineEvent] = field(default_factory=list)


@dataclass(slots=True)
class PipelineResult:
    session_id: str
    status: str
    file_name: str
    file_type: str
    jurisdiction: str
    degraded_flags: list[str]
    stages: list[StageExecution]
    findings: list[Finding]
    anonymized_text: str
    spans: list[dict]
    stats: dict[str, int]
    artifacts: PipelineArtifacts
    observability: PipelineObservability


@dataclass(slots=True)
class PipelineStatusSnapshot:
    session_id: str
    status: str
    current_stage: str | None
    file_name: str
    file_type: str
    degraded_flags: list[str]
    last_event: PipelineEvent | None
