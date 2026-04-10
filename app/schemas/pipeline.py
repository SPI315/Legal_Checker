from pydantic import BaseModel, Field

from app.schemas.anonymization import SpanResult


class StageStatusResponse(BaseModel):
    stage: str
    status: str
    detail: str | None = None
    started_at: str
    finished_at: str


class EvidenceResponse(BaseModel):
    source_id: str
    source_type: str
    title: str
    snippet: str
    uri: str
    retrieval_score: float
    retrieved_at: str


class FindingResponse(BaseModel):
    finding_id: str
    risk_type: str
    paragraph_id: str
    title: str
    summary: str
    confidence: float
    suggested_edit: str
    evidence: list[EvidenceResponse]


class ArtifactResponse(BaseModel):
    encrypted_report_path: str | None = None
    encrypted_anonymized_path: str | None = None
    export_docx_path: str | None = None
    events_path: str | None = None
    session_log_path: str | None = None


class PipelineEventResponse(BaseModel):
    timestamp: str
    event_type: str
    provider: str
    detail: str


class ObservabilityResponse(BaseModel):
    llm_provider: str | None = None
    llm_fallback_used: bool
    llm_prompt_tokens: int
    llm_completion_tokens: int
    llm_cost_estimate: float
    retrieval_provider: str | None = None
    retrieval_fallback_used: bool
    events: list[PipelineEventResponse]


class ProcessDocumentResponse(BaseModel):
    session_id: str
    status: str
    file_name: str
    file_type: str
    jurisdiction: str = Field(default="RU", min_length=2)
    degraded_flags: list[str]
    stages: list[StageStatusResponse]
    findings: list[FindingResponse]
    anonymized_text: str
    spans: list[SpanResult]
    stats: dict[str, int]
    artifacts: ArtifactResponse
    observability: ObservabilityResponse


class DocumentStatusResponse(BaseModel):
    session_id: str
    status: str
    current_stage: str | None = None
    file_name: str
    file_type: str
    degraded_flags: list[str]
    last_event: PipelineEventResponse | None = None
