from __future__ import annotations

import json
import logging

import httpx

from app.services.http_utils import retry_with_backoff
from app.services.orchestration.types import RiskCandidate
from app.services.retrieval.types import RetrievalRequest

logger = logging.getLogger(__name__)

RISK_SEARCH_HINTS = {
    "AUTO_RENEWAL": "автоматическая пролонгация договора без согласования сторон",
    "UNILATERAL_LIABILITY_LIMITATION": "ограничение ответственности продавца за скрытые недостатки товара",
    "UNILATERAL_CHANGE": "одностороннее изменение условий договора",
}


class RetrievalQueryBuilder:
    def __init__(
        self,
        model: str = "openai/gpt-4o-mini",
        timeout_sec: int = 10,
        openrouter_api_key: str = "",
        openrouter_base_url: str = "https://openrouter.ai/api/v1",
        openrouter_http_referer: str = "",
        openrouter_title: str = "Legal Checker API",
        vllm_base_url: str = "",
        vllm_api_key: str = "",
        vllm_model: str = "",
    ) -> None:
        self.model = model
        self.timeout_sec = timeout_sec
        self.openrouter_api_key = openrouter_api_key.strip()
        self.openrouter_base_url = openrouter_base_url.rstrip("/")
        self.openrouter_http_referer = openrouter_http_referer.strip()
        self.openrouter_title = openrouter_title.strip()
        self.vllm_base_url = vllm_base_url.rstrip("/")
        self.vllm_api_key = vllm_api_key.strip()
        self.vllm_model = vllm_model.strip()
        self.max_retries = 2

    def build(self, candidate: RiskCandidate, jurisdiction: str) -> RetrievalRequest:
        query = self._build_query(candidate, jurisdiction)
        return RetrievalRequest(
            query=query,
            risk_type=candidate.risk_type,
            jurisdiction=jurisdiction,
            paragraph_id=candidate.paragraph_id,
            paragraph_text=candidate.paragraph_text,
        )

    def _build_query(self, candidate: RiskCandidate, jurisdiction: str) -> str:
        llm_query = self._build_query_with_llm(candidate, jurisdiction)
        if llm_query:
            logger.info(
                "retrieval_query_generated provider=llm risk_type=%s query=%s",
                candidate.risk_type,
                llm_query,
            )
            return llm_query

        fallback_query = self._fallback_query(candidate, jurisdiction)
        logger.info(
            "retrieval_query_generated provider=fallback risk_type=%s query=%s",
            candidate.risk_type,
            fallback_query,
        )
        return fallback_query

    def _build_query_with_llm(self, candidate: RiskCandidate, jurisdiction: str) -> str | None:
        prompt_payload = {
            "jurisdiction": jurisdiction,
            "risk_type": candidate.risk_type,
            "matched_text": candidate.matched_text,
            "paragraph_excerpt": candidate.paragraph_text[:700],
        }

        if self.openrouter_api_key:
            result = self._call_chat_api(
                url=f"{self.openrouter_base_url}/chat/completions",
                headers=self._openrouter_headers(),
                body={
                    "model": self.model,
                    "messages": self._messages(prompt_payload),
                },
            )
            if result:
                return result

        if self.vllm_base_url:
            result = self._call_chat_api(
                url=f"{self.vllm_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.vllm_api_key or 'local-token'}",
                    "Content-Type": "application/json",
                },
                body={
                    "model": self.vllm_model or self.model,
                    "messages": self._messages(prompt_payload),
                },
            )
            if result:
                return result

        return None

    def _call_chat_api(self, url: str, headers: dict[str, str], body: dict) -> str | None:
        try:
            payload = retry_with_backoff(
                lambda: self._perform_request(url, headers, body),
                attempts=self.max_retries,
            )
        except Exception:
            return None

        content = self._extract_content(payload)
        if not content:
            return None

        query = self._normalize_query(content)
        if len(query) < 12:
            return None
        return query

    def _perform_request(self, url: str, headers: dict[str, str], body: dict) -> dict:
        with httpx.Client(timeout=self.timeout_sec) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()

    def _extract_content(self, payload: dict) -> str:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            return "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return str(content)

    def _normalize_query(self, content: str) -> str:
        cleaned = content.strip()
        if cleaned.startswith("{"):
            try:
                parsed = json.loads(cleaned)
                cleaned = str(parsed.get("query") or "").strip()
            except json.JSONDecodeError:
                pass
        cleaned = cleaned.replace("\n", " ").replace("\r", " ")
        cleaned = " ".join(cleaned.split())
        return cleaned[:220]

    def _messages(self, payload: dict) -> list[dict]:
        return [
            {
                "role": "system",
                "content": (
                    "Сформируй один короткий поисковый запрос на русском языке для web-поиска по правовым источникам. "
                    "Запрос должен быть естественным, юридическим и пригодным для поиска норм, судебной практики "
                    "или разъяснений по рисковой формулировке договора. "
                    "Не используй внутренние технические коды риска. "
                    "Не добавляй пояснения, markdown, нумерацию или кавычки. "
                    "Верни только одну строку поискового запроса."
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

    def _openrouter_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        if self.openrouter_http_referer:
            headers["HTTP-Referer"] = self.openrouter_http_referer
        if self.openrouter_title:
            headers["X-OpenRouter-Title"] = self.openrouter_title
        return headers

    def _fallback_query(self, candidate: RiskCandidate, jurisdiction: str) -> str:
        hint = RISK_SEARCH_HINTS.get(candidate.risk_type, candidate.matched_text)
        excerpt = " ".join(candidate.paragraph_text.split())[:120]
        return f"{hint} {excerpt} {jurisdiction} ГК РФ"
