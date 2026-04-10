from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Response, UploadFile

from app.api.deps import get_document_ingestion_service, get_pipeline_orchestrator
from app.schemas.documents import ParseDocumentResponse, ParsedParagraph
from app.schemas.pipeline import (
    ArtifactResponse,
    DocumentStatusResponse,
    EvidenceResponse,
    FindingResponse,
    ObservabilityResponse,
    PipelineEventResponse,
    ProcessDocumentResponse,
    StartProcessResponse,
    StageStatusResponse,
    TimelineEntryResponse,
)
from app.services.documents.ingestion_service import (
    DocumentIngestionService,
    UnsupportedDocumentTypeError,
)
from app.services.orchestration.orchestrator import PipelineOrchestrator
from uuid import uuid4

router = APIRouter(prefix="/api", tags=["documents"])
ALLOWED_MIME_TYPES = {
    ".pdf": {"application/pdf"},
    ".docx": {
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/zip",
    },
}


@router.post("/document/parse", response_model=ParseDocumentResponse)
async def parse_document(
    file: UploadFile = File(...),
    service: DocumentIngestionService = Depends(get_document_ingestion_service),
) -> ParseDocumentResponse:
    _validate_uploaded_file(file)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        result = service.parse(file.filename or "uploaded_file", content)
    except UnsupportedDocumentTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ParseDocumentResponse(
        file_name=result.file_name,
        file_type=result.file_type,
        full_text=result.full_text,
        paragraphs=[ParsedParagraph(**asdict(p)) for p in result.paragraphs],
    )


@router.post("/documents/process", response_model=ProcessDocumentResponse)
async def process_document(
    file: UploadFile = File(...),
    jurisdiction: str = "RU",
    use_ner: bool = True,
    orchestrator: PipelineOrchestrator = Depends(get_pipeline_orchestrator),
) -> ProcessDocumentResponse:
    _validate_uploaded_file(file)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    try:
        result = orchestrator.process(
            file_name=file.filename or "uploaded_file",
            content=content,
            jurisdiction=jurisdiction,
            use_ner=use_ner,
        )
    except UnsupportedDocumentTypeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return _build_process_response(result)


@router.post("/documents/process/start", response_model=StartProcessResponse)
async def start_process_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    jurisdiction: str = "RU",
    use_ner: bool = True,
    orchestrator: PipelineOrchestrator = Depends(get_pipeline_orchestrator),
) -> StartProcessResponse:
    _validate_uploaded_file(file)
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    session_id = str(uuid4())
    file_name = file.filename or "uploaded_file"
    orchestrator.initialize_session(session_id, file_name)
    background_tasks.add_task(
        orchestrator.process_with_session,
        session_id=session_id,
        file_name=file_name,
        content=content,
        jurisdiction=jurisdiction,
        use_ner=use_ner,
    )
    status = orchestrator.get_status(session_id)
    return StartProcessResponse(
        session_id=session_id,
        status=status.status if status else "queued",
        current_stage=status.current_stage if status else "INIT",
        file_name=file_name,
        file_type=status.file_type if status else "unknown",
    )


@router.get("/documents/{session_id}", response_model=ProcessDocumentResponse)
def get_processed_document(
    session_id: str,
    orchestrator: PipelineOrchestrator = Depends(get_pipeline_orchestrator),
) -> ProcessDocumentResponse:
    result = orchestrator.get(session_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return _build_process_response(result)


@router.get("/documents/{session_id}/status", response_model=DocumentStatusResponse)
def get_document_status(
    session_id: str,
    orchestrator: PipelineOrchestrator = Depends(get_pipeline_orchestrator),
) -> DocumentStatusResponse:
    status = orchestrator.get_status(session_id)
    if status is None:
        raise HTTPException(status_code=404, detail="Session not found")

    return DocumentStatusResponse(
        session_id=status.session_id,
        status=status.status,
        current_stage=status.current_stage,
        file_name=status.file_name,
        file_type=status.file_type,
        degraded_flags=status.degraded_flags,
        last_event=PipelineEventResponse(**asdict(status.last_event)) if status.last_event else None,
    )


@router.get("/documents/{session_id}/export.docx")
def export_processed_document(
    session_id: str,
    orchestrator: PipelineOrchestrator = Depends(get_pipeline_orchestrator),
) -> Response:
    result = orchestrator.get(session_id)
    if result is None or not result.artifacts.export_docx_path:
        raise HTTPException(status_code=404, detail="Export not found")

    content = Path(result.artifacts.export_docx_path).read_bytes()
    headers = {"Content-Disposition": f'attachment; filename="{session_id}.docx"'}
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=headers,
    )


@router.get("/documents/{session_id}/timeline", response_model=list[TimelineEntryResponse])
def get_document_timeline(
    session_id: str,
    orchestrator: PipelineOrchestrator = Depends(get_pipeline_orchestrator),
) -> list[TimelineEntryResponse]:
    timeline = orchestrator.get_timeline(session_id)
    if timeline is None:
        raise HTTPException(status_code=404, detail="Session timeline not found")

    return [
        TimelineEntryResponse(
            timestamp=item["timestamp"],
            level=item.get("level", "INFO"),
            event_type=item["event_type"],
            provider=item.get("provider"),
            stage=item.get("stage"),
            candidate_id=item.get("candidate_id"),
            message=item.get("message", ""),
            query=item.get("query"),
            evidence_count=item.get("evidence_count"),
            fallback_used=item.get("fallback_used"),
            status=item.get("status"),
            findings=item.get("findings"),
            degraded_flags=item.get("degraded_flags"),
        )
        for item in timeline
    ]


def _build_process_response(result) -> ProcessDocumentResponse:
    return ProcessDocumentResponse(
        session_id=result.session_id,
        status=result.status,
        file_name=result.file_name,
        file_type=result.file_type,
        jurisdiction=result.jurisdiction,
        degraded_flags=result.degraded_flags,
        stages=[StageStatusResponse(**asdict(stage)) for stage in result.stages],
        findings=[
            FindingResponse(
                finding_id=finding.finding_id,
                risk_type=finding.risk_type,
                paragraph_id=finding.paragraph_id,
                title=finding.title,
                summary=finding.summary,
                legal_basis=finding.legal_basis,
                legal_basis_supported=finding.legal_basis_supported,
                confidence=finding.confidence,
                suggested_edit=finding.suggested_edit,
                evidence=[EvidenceResponse(**asdict(item)) for item in finding.evidence],
            )
            for finding in result.findings
        ],
        anonymized_text=result.anonymized_text,
        spans=result.spans,
        stats=result.stats,
        artifacts=ArtifactResponse(
            encrypted_report_path=result.artifacts.encrypted_report_path,
            encrypted_anonymized_path=result.artifacts.encrypted_anonymized_path,
            export_docx_path=result.artifacts.export_docx_path,
            events_path=result.artifacts.events_path,
            session_log_path=result.artifacts.session_log_path,
        ),
        observability=ObservabilityResponse(
            llm_provider=result.observability.llm_provider,
            llm_fallback_used=result.observability.llm_fallback_used,
            llm_prompt_tokens=result.observability.llm_prompt_tokens,
            llm_completion_tokens=result.observability.llm_completion_tokens,
            llm_cost_estimate=result.observability.llm_cost_estimate,
            retrieval_provider=result.observability.retrieval_provider,
            retrieval_fallback_used=result.observability.retrieval_fallback_used,
            events=[PipelineEventResponse(**asdict(event)) for event in result.observability.events],
        ),
    )


def _validate_uploaded_file(file: UploadFile) -> None:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_MIME_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported file type. Allowed: .pdf, .docx")

    content_type = file.content_type or ""
    if content_type not in ALLOWED_MIME_TYPES[suffix]:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported MIME type for {suffix}: {content_type}",
        )
