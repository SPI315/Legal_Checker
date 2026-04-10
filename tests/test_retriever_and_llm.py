import httpx

from app.services.llm.client import RiskLlmAnalyzer
from app.services.orchestration.types import EvidenceItem, RiskCandidate
from app.services.retrieval.normative_web import NormativeWebRetriever
from app.services.retrieval.query_builder import RetrievalQueryBuilder
from app.services.retrieval.types import RetrievalRequest


class DummyResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


class DummyClient:
    def __init__(self, responses: list[object]) -> None:
        self._responses = responses

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def post(self, url: str, **kwargs):
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_tavily_retriever_maps_results(monkeypatch) -> None:
    payload = {
        "results": [
            {
                "title": "Норма права",
                "url": "https://pravo.gov.ru/doc",
                "content": "Фрагмент нормативного текста",
                "score": 0.91,
            }
        ]
    }
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyClient([DummyResponse(payload)]))
    retriever = NormativeWebRetriever(
        allowed_domains=["pravo.gov.ru"],
        top_k=3,
        timeout_sec=5,
        tavily_api_key="secret",
    )

    retrieval = retriever.retrieve(
        RetrievalRequest(
            query="test",
            risk_type="AUTO_RENEWAL",
            jurisdiction="RU",
            paragraph_id="p1",
            paragraph_text="text",
        )
    )

    assert retrieval.provider_used == "tavily"
    assert retrieval.fallback_used is False
    assert len(retrieval.evidence) == 1
    assert retrieval.evidence[0].uri == "https://pravo.gov.ru/doc"


def test_tavily_retriever_retries_before_success(monkeypatch) -> None:
    payload = {
        "results": [
            {
                "title": "Норма права",
                "url": "https://pravo.gov.ru/doc",
                "content": "Фрагмент нормативного текста",
                "score": 0.91,
            }
        ]
    }
    responses = [httpx.ConnectError("boom"), DummyResponse(payload)]
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyClient(responses))
    retriever = NormativeWebRetriever(
        allowed_domains=["pravo.gov.ru"],
        top_k=3,
        timeout_sec=5,
        tavily_api_key="secret",
    )
    retriever.max_retries = 2

    retrieval = retriever.retrieve(
        RetrievalRequest(
            query="test",
            risk_type="AUTO_RENEWAL",
            jurisdiction="RU",
            paragraph_id="p1",
            paragraph_text="text",
        )
    )

    assert retrieval.provider_used == "tavily"
    assert retrieval.fallback_used is False


def test_llm_falls_back_to_vllm_when_openrouter_fails(monkeypatch) -> None:
    openrouter_error = httpx.ConnectError("boom")
    vllm_payload = {
        "choices": [
            {
                "message": {
                    "content": '{"title":"Risk","summary":"Summary","confidence":0.81,"suggested_edit":"Edit"}'
                }
            }
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 40},
    }
    responses = [openrouter_error, openrouter_error, openrouter_error, DummyResponse(vllm_payload)]
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyClient(responses))
    analyzer = RiskLlmAnalyzer(
        provider="openrouter",
        model="model-a",
        timeout_sec=5,
        openrouter_api_key="secret",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_http_referer="",
        openrouter_title="",
        vllm_base_url="http://localhost:8000/v1",
        vllm_api_key="token",
        vllm_model="model-b",
    )
    analyzer.max_retries = 3

    result = analyzer.analyze(
        RiskCandidate(
            candidate_id="c1",
            risk_type="AUTO_RENEWAL",
            paragraph_id="p1",
            paragraph_text="текст",
            matched_text="автоматически продлевается",
        ),
        [EvidenceItem("s1", "web", "title", "snippet", "https://pravo.gov.ru", 0.9, "now")],
    )

    assert result.provider_used == "vllm"
    assert result.suggested_edit == "Edit"
    assert result.fallback_used is True
    assert result.prompt_tokens == 120
    assert result.completion_tokens == 40


def test_llm_retries_openrouter_before_success(monkeypatch) -> None:
    openrouter_payload = {
        "choices": [
            {
                "message": {
                    "content": '{"title":"Risk","summary":"Summary","confidence":0.81,"suggested_edit":"Edit"}'
                }
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 20},
    }
    responses = [httpx.ConnectError("boom"), DummyResponse(openrouter_payload)]
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyClient(responses))
    analyzer = RiskLlmAnalyzer(
        provider="openrouter",
        model="model-a",
        timeout_sec=5,
        openrouter_api_key="secret",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_http_referer="",
        openrouter_title="",
        vllm_base_url="http://localhost:8000/v1",
        vllm_api_key="token",
        vllm_model="model-b",
    )
    analyzer.max_retries = 2

    result = analyzer.analyze(
        RiskCandidate(
            candidate_id="c1",
            risk_type="AUTO_RENEWAL",
            paragraph_id="p1",
            paragraph_text="текст",
            matched_text="автоматически продлевается",
        ),
        [EvidenceItem("s1", "web", "title", "snippet", "https://pravo.gov.ru", 0.9, "now")],
    )

    assert result.provider_used == "openrouter"
    assert result.fallback_used is False


def test_llm_system_prompt_requires_russian_json_output() -> None:
    analyzer = RiskLlmAnalyzer(
        provider="openrouter",
        model="model-a",
        timeout_sec=5,
        openrouter_api_key="secret",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_http_referer="",
        openrouter_title="",
        vllm_base_url="",
        vllm_api_key="token",
        vllm_model="model-b",
    )

    messages = analyzer._messages({"risk_type": "AUTO_RENEWAL"})

    assert "Пиши все значения полей на русском языке" in messages[0]["content"]
    assert "JSON" in messages[0]["content"]


def test_query_builder_uses_llm_generated_query(monkeypatch) -> None:
    payload = {
        "choices": [
            {
                "message": {
                    "content": "ограничение ответственности продавца за скрытые недостатки товара ГК РФ"
                }
            }
        ]
    }
    monkeypatch.setattr(httpx, "Client", lambda timeout: DummyClient([DummyResponse(payload)]))
    builder = RetrievalQueryBuilder(
        model="model-a",
        timeout_sec=5,
        openrouter_api_key="secret",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_http_referer="",
        openrouter_title="",
        vllm_base_url="",
        vllm_api_key="",
        vllm_model="",
    )

    request = builder.build(
        RiskCandidate(
            candidate_id="c1",
            risk_type="UNILATERAL_LIABILITY_LIMITATION",
            paragraph_id="p1",
            paragraph_text="Продавец не несет ответственности за скрытые повреждения товара.",
            matched_text="не несет ответственности",
        ),
        "RU",
    )

    assert request.query == "ограничение ответственности продавца за скрытые недостатки товара ГК РФ"


def test_query_builder_falls_back_to_local_query_when_llm_unavailable(monkeypatch) -> None:
    monkeypatch.setattr(
        httpx,
        "Client",
        lambda timeout: DummyClient([httpx.ConnectError("boom"), httpx.ConnectError("boom")]),
    )
    builder = RetrievalQueryBuilder(
        model="model-a",
        timeout_sec=5,
        openrouter_api_key="secret",
        openrouter_base_url="https://openrouter.ai/api/v1",
        openrouter_http_referer="",
        openrouter_title="",
        vllm_base_url="",
        vllm_api_key="",
        vllm_model="",
    )

    request = builder.build(
        RiskCandidate(
            candidate_id="c1",
            risk_type="UNILATERAL_LIABILITY_LIMITATION",
            paragraph_id="p1",
            paragraph_text="Продавец не несет ответственности за скрытые повреждения товара.",
            matched_text="не несет ответственности",
        ),
        "RU",
    )

    assert "ограничение ответственности продавца" in request.query
    assert "ГК РФ" in request.query
