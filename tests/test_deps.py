from app.api.deps import get_anonymizer_service, get_document_ingestion_service
from app.core.settings import Settings


def test_get_anonymizer_service_builds_service() -> None:
    settings = Settings(
        ner_model_name="",
        ner_device=-1,
        ner_min_score=0.5,
    )

    service = get_anonymizer_service(settings)

    assert service.regex_detector is not None
    assert service.ner_detector is not None
    assert service.resolver is not None


def test_get_document_ingestion_service_builds_service() -> None:
    settings = Settings()

    service = get_document_ingestion_service(settings)

    assert service is not None
