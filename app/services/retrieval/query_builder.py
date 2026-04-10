from __future__ import annotations

import json
import logging
import re

import httpx

from app.services.http_utils import retry_with_backoff
from app.services.orchestration.types import EvidenceItem, RiskCandidate
from app.services.retrieval.types import RetrievalRequest

logger = logging.getLogger(__name__)

MAX_QUERY_LENGTH = 180
CYRILLIC_RATIO_THRESHOLD = 0.45
NOISY_LATIN_TOKENS = {
    "unjustified",
    "legal",
    "text",
    "clause",
    "unsupported",
    "citation",
    "article",
    "basis",
}
RISK_QUERY_HINTS = {
    "AUTO_RENEWAL": "автопролонгация договора судебная практика ГК РФ",
    "UNILATERAL_LIABILITY_LIMITATION": "ограничение ответственности продавца скрытые недостатки товара судебная практика ГК РФ",
    "UNILATERAL_CHANGE": "одностороннее изменение условий договора судебная практика ГК РФ",
}


class RetrievalQueryBuilder:
    def __init__(
        self,
        model: str,
        timeout_sec: int,
        openrouter_api_key: str,
        openrouter_base_url: str,
        openrouter_http_referer: str,
        openrouter_title: str,
        vllm_base_url: str,
        vllm_api_key: str,
        vllm_model: str,
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
        fallback_query = self._fallback_query(candidate, jurisdiction)
        query = self._generate_query(
            candidate=candidate,
            jurisdiction=jurisdiction,
            mode="initial",
            fallback_query=fallback_query,
            prior_query=None,
            evidence=None,
            focus_terms=None,
        )
        logger.info(
            "retrieval_query_generated provider=%s mode=initial risk_type=%s query=%s",
            "llm" if query != fallback_query else "fallback",
            candidate.risk_type,
            query,
        )
        return RetrievalRequest(
            query=query,
            risk_type=candidate.risk_type,
            jurisdiction=jurisdiction,
            paragraph_id=candidate.paragraph_id,
            paragraph_text=candidate.paragraph_text,
        )

    def build_refined(
        self,
        candidate: RiskCandidate,
        jurisdiction: str,
        prior_query: str,
        evidence: list[EvidenceItem],
        focus_terms: list[str] | None = None,
    ) -> RetrievalRequest:
        fallback_query = self._refined_fallback_query(candidate, jurisdiction, prior_query, focus_terms)
        query = self._generate_query(
            candidate=candidate,
            jurisdiction=jurisdiction,
            mode="refined",
            fallback_query=fallback_query,
            prior_query=prior_query,
            evidence=evidence,
            focus_terms=focus_terms,
        )
        logger.info(
            "retrieval_query_generated provider=%s mode=refined risk_type=%s query=%s",
            "llm" if query != fallback_query else "fallback",
            candidate.risk_type,
            query,
        )
        return RetrievalRequest(
            query=query,
            risk_type=candidate.risk_type,
            jurisdiction=jurisdiction,
            paragraph_id=candidate.paragraph_id,
            paragraph_text=candidate.paragraph_text,
        )

    def _generate_query(
        self,
        candidate: RiskCandidate,
        jurisdiction: str,
        mode: str,
        fallback_query: str,
        prior_query: str | None,
        evidence: list[EvidenceItem] | None,
        focus_terms: list[str] | None,
    ) -> str:
        generated = self._call_openrouter(candidate, jurisdiction, mode, prior_query, evidence, focus_terms)
        if generated is None:
            generated = self._call_vllm(candidate, jurisdiction, mode, prior_query, evidence, focus_terms)
        return self._sanitize_query(generated or fallback_query, fallback_query)

    def _call_openrouter(
        self,
        candidate: RiskCandidate,
        jurisdiction: str,
        mode: str,
        prior_query: str | None,
        evidence: list[EvidenceItem] | None,
        focus_terms: list[str] | None,
    ) -> str | None:
        if not self.openrouter_api_key:
            return None

        headers = {
            "Authorization": f"Bearer {self.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        if self.openrouter_http_referer:
            headers["HTTP-Referer"] = self.openrouter_http_referer
        if self.openrouter_title:
            headers["X-OpenRouter-Title"] = self.openrouter_title

        body = {
            "model": self.model,
            "messages": self._messages(candidate, jurisdiction, mode, prior_query, evidence, focus_terms),
        }
        return self._call_chat_api(f"{self.openrouter_base_url}/chat/completions", headers, body)

    def _call_vllm(
        self,
        candidate: RiskCandidate,
        jurisdiction: str,
        mode: str,
        prior_query: str | None,
        evidence: list[EvidenceItem] | None,
        focus_terms: list[str] | None,
    ) -> str | None:
        if not self.vllm_base_url:
            return None

        headers = {
            "Authorization": f"Bearer {self.vllm_api_key or 'local-token'}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.vllm_model or self.model,
            "messages": self._messages(candidate, jurisdiction, mode, prior_query, evidence, focus_terms),
        }
        return self._call_chat_api(f"{self.vllm_base_url}/chat/completions", headers, body)

    def _call_chat_api(self, url: str, headers: dict[str, str], body: dict) -> str | None:
        try:
            payload = retry_with_backoff(
                lambda: self._perform_request(url, headers, body),
                attempts=self.max_retries,
            )
        except Exception:
            return None

        choices = payload.get("choices") or []
        if not choices:
            return None
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return str(content).strip()

    def _perform_request(self, url: str, headers: dict[str, str], body: dict) -> dict:
        with httpx.Client(timeout=self.timeout_sec) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()

    def _messages(
        self,
        candidate: RiskCandidate,
        jurisdiction: str,
        mode: str,
        prior_query: str | None,
        evidence: list[EvidenceItem] | None,
        focus_terms: list[str] | None,
    ) -> list[dict]:
        payload = {
            "mode": mode,
            "jurisdiction": jurisdiction,
            "risk_type": candidate.risk_type,
            "paragraph_text": candidate.paragraph_text[:700],
            "matched_text": candidate.matched_text,
            "prior_query": prior_query,
            "evidence_titles": [item.title for item in (evidence or [])[:3]],
            "focus_terms": focus_terms or [],
        }
        return [
            {
                "role": "system",
                "content": (
                    "Ты составляешь короткий юридический поисковый запрос для web-retrieval по договорному риску. "
                    "Верни только одну строку запроса на русском языке без пояснений, без JSON и без кавычек. "
                    "Запрос должен быть естественным, пригодным для поиска по судебной практике и правовым материалам. "
                    "Не вставляй внутренние коды риска, технические метки, английские слова, служебные хвосты и мусорные токены. "
                    "Если mode=refined, уточни запрос так, чтобы найти правовое обоснование и подтверждающие источники. "
                    "Если есть focus_terms, обязательно включи их в запрос в естественной форме. "
                    "Длина ответа не должна превышать 18 слов."
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

    def _sanitize_query(self, query: str, fallback_query: str) -> str:
        cleaned = " ".join((query or "").split())
        if not cleaned:
            return fallback_query

        words = []
        for word in cleaned.split():
            normalized = re.sub(r"[^\wА-Яа-яЁё\-./]", "", word)
            if not normalized:
                continue
            if normalized.lower() in NOISY_LATIN_TOKENS:
                continue
            words.append(normalized)

        cleaned = " ".join(words).strip()[:MAX_QUERY_LENGTH].strip(" ,.;:-")
        if not cleaned:
            return fallback_query
        if self._looks_too_noisy(cleaned):
            return fallback_query
        return cleaned

    def _looks_too_noisy(self, query: str) -> bool:
        letters = re.findall(r"[A-Za-zА-Яа-яЁё]", query)
        if not letters:
            return True
        cyrillic = re.findall(r"[А-Яа-яЁё]", query)
        if len(cyrillic) / len(letters) < CYRILLIC_RATIO_THRESHOLD:
            return True

        latin_words = re.findall(r"\b[A-Za-z][A-Za-z\-]+\b", query)
        if any(word.lower() in NOISY_LATIN_TOKENS for word in latin_words):
            return True

        return False

    def _fallback_query(self, candidate: RiskCandidate, jurisdiction: str) -> str:
        hint = RISK_QUERY_HINTS.get(candidate.risk_type, "судебная практика по рисковому условию договора")
        matched = self._trim_terms(candidate.matched_text)
        query = f"{hint} {matched} {jurisdiction}".strip()
        return self._truncate_query(query)

    def _refined_fallback_query(
        self,
        candidate: RiskCandidate,
        jurisdiction: str,
        prior_query: str,
        focus_terms: list[str] | None,
    ) -> str:
        extra = " ".join(self._trim_terms(term) for term in (focus_terms or []) if term).strip()
        base_hint = RISK_QUERY_HINTS.get(candidate.risk_type, "судебная практика по рисковому условию договора")
        if extra:
            query = f"{base_hint} {extra} {jurisdiction}"
        else:
            query = f"{base_hint} {self._trim_terms(candidate.matched_text)} судебная практика {jurisdiction}"
        if prior_query and extra and extra not in prior_query:
            query = f"{query} {extra}"
        return self._truncate_query(query)

    def _trim_terms(self, text: str) -> str:
        return " ".join((text or "").split())[:80].strip()

    def _truncate_query(self, query: str) -> str:
        return " ".join(query.split())[:MAX_QUERY_LENGTH].strip(" ,.;:-")
