from fastapi import APIRouter, Depends

from app.api.deps import get_anonymizer_service
from app.schemas.anonymization import AnonymizeRequest, AnonymizeResponse, SpanResult
from app.services.anonymization.anonymizer import AnonymizerService

router = APIRouter(prefix="/api", tags=["anonymization"])


@router.post("/anonymize", response_model=AnonymizeResponse)
def anonymize(
    payload: AnonymizeRequest,
    service: AnonymizerService = Depends(get_anonymizer_service),
) -> AnonymizeResponse:
    result = service.anonymize(payload.text, use_ner=payload.use_ner)

    return AnonymizeResponse(
        anonymized_text=result.anonymized_text,
        spans=[SpanResult(**span) for span in result.spans],
        stats=result.stats,
    )
