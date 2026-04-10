from __future__ import annotations

import json
import logging
from datetime import UTC, datetime

import httpx

from app.services.http_utils import retry_with_backoff
from app.services.orchestration.types import EvidenceItem
from app.services.retrieval.allowlist import DEFAULT_ALLOWED_DOMAINS
from app.services.retrieval.types import RetrievalRequest, RetrievalResult

logger = logging.getLogger(__name__)


class NormativeWebRetriever:
    def __init__(
        self,
        allowed_domains: list[str],
        top_k: int = 3,
        timeout_sec: int = 8,
        tavily_api_key: str = "",
        tavily_base_url: str = "https://api.tavily.com",
    ) -> None:
        self.allowed_domains = allowed_domains or DEFAULT_ALLOWED_DOMAINS
        self.top_k = max(1, top_k)
        self.timeout_sec = timeout_sec
        self.tavily_api_key = tavily_api_key.strip()
        self.tavily_base_url = tavily_base_url.rstrip("/")
        self.max_retries = 3

    def retrieve(self, request: RetrievalRequest) -> RetrievalResult:
        if not self.tavily_api_key:
            return RetrievalResult(
                evidence=self._fallback_evidence(request),
                provider_used="allowlist-fallback",
                fallback_used=True,
            )

        payload = {
            "api_key": self.tavily_api_key,
            "query": request.query,
            "topic": "general",
            "search_depth": "basic",
            "max_results": self.top_k,
            "include_answer": False,
            "include_raw_content": False,
            "include_domains": self.allowed_domains,
        }

        try:
            body = retry_with_backoff(
                lambda: self._perform_request(payload),
                attempts=self.max_retries,
            )
        except Exception:
            return RetrievalResult(
                evidence=self._fallback_evidence(request),
                provider_used="allowlist-fallback",
                fallback_used=True,
            )

        logger.info(
            "tavily_response query=%s body=%s",
            request.query[:180],
            self._serialize_for_log(body),
        )

        evidence = self._map_results(body.get("results", []))
        if not evidence:
            return RetrievalResult(
                evidence=self._fallback_evidence(request),
                provider_used="allowlist-fallback",
                fallback_used=True,
            )

        return RetrievalResult(
            evidence=evidence,
            provider_used="tavily",
            fallback_used=False,
        )

    def _map_results(self, results: list[dict]) -> list[EvidenceItem]:
        retrieved_at = datetime.now(UTC).isoformat()
        evidence: list[EvidenceItem] = []

        for index, item in enumerate(results[: self.top_k], start=1):
            url = str(item.get("url", ""))
            if not self._is_allowed_url(url):
                continue

            evidence.append(
                EvidenceItem(
                    source_id=f"tavily:{index}",
                    source_type="tavily_search_result",
                    title=str(item.get("title") or url or "Normative source"),
                    snippet=str(item.get("content") or item.get("raw_content") or "")[:1000],
                    uri=url,
                    retrieval_score=float(item.get("score") or 0.0),
                    retrieved_at=retrieved_at,
                )
            )

        return evidence

    def _fallback_evidence(self, request: RetrievalRequest) -> list[EvidenceItem]:
        retrieved_at = datetime.now(UTC).isoformat()
        evidence: list[EvidenceItem] = []
        for index, domain in enumerate(self.allowed_domains[: self.top_k], start=1):
            evidence.append(
                EvidenceItem(
                    source_id=f"{domain}:{request.paragraph_id}:{index}",
                    source_type="trusted_web_domain",
                    title=f"Trusted legal source: {domain}",
                    snippet=(
                        f"Check risk '{request.risk_type}' using query '{request.query[:180]}' "
                        f"on trusted legal source."
                    ),
                    uri=f"https://{domain}",
                    retrieval_score=round(1.0 - ((index - 1) * 0.1), 2),
                    retrieved_at=retrieved_at,
                )
            )
        return evidence

    def _is_allowed_url(self, url: str) -> bool:
        return any(domain in url for domain in self.allowed_domains)

    def _perform_request(self, payload: dict) -> dict:
        with httpx.Client(timeout=self.timeout_sec) as client:
            response = client.post(f"{self.tavily_base_url}/search", json=payload)
            response.raise_for_status()
            return response.json()

    def _serialize_for_log(self, payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw) <= 2000:
            return raw
        return raw[:2000] + "...<truncated>"
