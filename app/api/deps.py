from fastapi import Depends

from app.core.settings import Settings, get_settings
from app.services.anonymization.anonymizer import AnonymizerService
from app.services.anonymization.regex_detector import RegexDetector
from app.services.anonymization.span_resolver import SpanResolver
from app.services.anonymization.transformer_detector import TransformerNerDetector


def get_anonymizer_service(settings: Settings = Depends(get_settings)) -> AnonymizerService:
    regex_detector = RegexDetector()
    ner_detector = TransformerNerDetector(
        model_name=settings.ner_model_name,
        min_score=settings.ner_min_score,
        device=settings.ner_device,
    )
    resolver = SpanResolver()
    return AnonymizerService(regex_detector, ner_detector, resolver)
