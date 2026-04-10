from fastapi import Depends

from app.core.settings import Settings, get_settings
from app.services.anonymization.anonymizer import AnonymizerService
from app.services.anonymization.regex_detector import RegexDetector
from app.services.anonymization.span_resolver import SpanResolver
from app.services.anonymization.transformer_detector import TransformerNerDetector
from app.services.documents.ingestion_service import DocumentIngestionService
from app.services.export.docx_exporter import DocxReportExporter
from app.services.llm.client import RiskLlmAnalyzer
from app.services.ocr.stub import OcrStubService
from app.services.orchestration.orchestrator import PipelineOrchestrator
from app.services.orchestration.state_store import InMemoryPipelineStateStore
from app.services.retrieval.normative_web import NormativeWebRetriever
from app.services.retrieval.query_builder import RetrievalQueryBuilder
from app.services.rules.engine import RiskRulesEngine
from app.services.storage.artifact_store import ArtifactStore
from app.services.storage.crypto import DpapiCipher
from app.services.validation.policy_validator import PolicyValidator
from app.services.validation.report_validator import ReportValidator

_STATE_STORE = InMemoryPipelineStateStore()


def get_anonymizer_service(settings: Settings = Depends(get_settings)) -> AnonymizerService:
    regex_detector = RegexDetector()
    ner_detector = TransformerNerDetector(
        model_name=settings.ner_model_name,
        min_score=settings.ner_min_score,
        device=settings.ner_device,
    )
    resolver = SpanResolver()
    return AnonymizerService(regex_detector, ner_detector, resolver)


def get_document_ingestion_service(
    settings: Settings = Depends(get_settings),
) -> DocumentIngestionService:
    _ = settings
    return DocumentIngestionService()


def get_pipeline_state_store() -> InMemoryPipelineStateStore:
    return _STATE_STORE


def get_pipeline_orchestrator(
    settings: Settings = Depends(get_settings),
    state_store: InMemoryPipelineStateStore = Depends(get_pipeline_state_store),
) -> PipelineOrchestrator:
    anonymizer = get_anonymizer_service(settings)
    ingestion = get_document_ingestion_service(settings)
    cipher = DpapiCipher(settings.storage_encryption_key.encode("utf-8"))
    artifact_store = ArtifactStore(settings.storage_dir_path, cipher)

    return PipelineOrchestrator(
        ingestion_service=ingestion,
        anonymizer_service=anonymizer,
        ocr_service=OcrStubService(),
        rules_engine=RiskRulesEngine(),
        retriever=NormativeWebRetriever(
            allowed_domains=settings.allowed_source_domains_list,
            top_k=settings.retriever_top_k,
            timeout_sec=settings.retriever_timeout_sec,
            tavily_api_key=settings.tavily_api_key,
            tavily_base_url=settings.tavily_base_url,
        ),
        query_builder=RetrievalQueryBuilder(
            model=settings.llm_model,
            timeout_sec=settings.llm_timeout_sec,
            openrouter_api_key=settings.openrouter_api_key,
            openrouter_base_url=settings.openrouter_base_url,
            openrouter_http_referer=settings.openrouter_http_referer,
            openrouter_title=settings.openrouter_title,
            vllm_base_url=settings.vllm_base_url,
            vllm_api_key=settings.vllm_api_key,
            vllm_model=settings.vllm_model,
        ),
        llm_analyzer=RiskLlmAnalyzer(
            provider=settings.llm_provider,
            model=settings.llm_model,
            timeout_sec=settings.llm_timeout_sec,
            openrouter_api_key=settings.openrouter_api_key,
            openrouter_base_url=settings.openrouter_base_url,
            openrouter_http_referer=settings.openrouter_http_referer,
            openrouter_title=settings.openrouter_title,
            vllm_base_url=settings.vllm_base_url,
            vllm_api_key=settings.vllm_api_key,
            vllm_model=settings.vllm_model,
        ),
        report_validator=ReportValidator(),
        policy_validator=PolicyValidator(),
        artifact_store=artifact_store,
        docx_exporter=DocxReportExporter(),
        state_store=state_store,
    )
