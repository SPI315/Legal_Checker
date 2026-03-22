from dataclasses import asdict

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile

from app.api.deps import get_document_ingestion_service
from app.schemas.documents import ParseDocumentResponse, ParsedParagraph
from app.services.documents.ingestion_service import (
    DocumentIngestionService,
    UnsupportedDocumentTypeError,
)

router = APIRouter(prefix="/api/document", tags=["documents"])


@router.post("/parse", response_model=ParseDocumentResponse)
async def parse_document(
    file: UploadFile = File(...),
    service: DocumentIngestionService = Depends(get_document_ingestion_service),
) -> ParseDocumentResponse:
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
