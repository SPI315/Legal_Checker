from __future__ import annotations

import json

import httpx

from app.services.http_utils import retry_with_backoff
from app.services.llm.prompts import RISK_SUMMARIES, RISK_TITLES
from app.services.llm.types import AnalysisDraft
from app.services.orchestration.types import EvidenceItem, RiskCandidate
from app.services.rules.catalog import RULE_DEFINITIONS


class RiskLlmAnalyzer:
    def __init__(
        self,
        provider: str,
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
        self.provider = provider
        self.model = model
        self.timeout_sec = timeout_sec
        self.openrouter_api_key = openrouter_api_key.strip()
        self.openrouter_base_url = openrouter_base_url.rstrip("/")
        self.openrouter_http_referer = openrouter_http_referer.strip()
        self.openrouter_title = openrouter_title.strip()
        self.vllm_base_url = vllm_base_url.rstrip("/")
        self.vllm_api_key = vllm_api_key.strip()
        self.vllm_model = vllm_model.strip()
        self._suggested_edit_by_risk = {rule.risk_type: rule.suggested_edit for rule in RULE_DEFINITIONS}
        self.max_retries = 3

    def analyze(self, candidate: RiskCandidate, evidence: list[EvidenceItem]) -> AnalysisDraft:
        payload = self._build_llm_payload(candidate, evidence)

        if self.openrouter_api_key:
            openrouter_result = self._call_openrouter(payload)
            if openrouter_result is not None:
                return openrouter_result

        vllm_result = self._call_vllm(payload)
        if vllm_result is not None:
            return vllm_result

        return self._local_fallback(candidate, evidence, provider_used="local-fallback", fallback_used=True)

    def _build_llm_payload(self, candidate: RiskCandidate, evidence: list[EvidenceItem]) -> dict:
        evidence_lines = [
            {"title": item.title, "snippet": item.snippet[:500], "uri": item.uri}
            for item in evidence
        ]
        return {
            "risk_type": candidate.risk_type,
            "paragraph_id": candidate.paragraph_id,
            "paragraph_text": candidate.paragraph_text,
            "matched_text": candidate.matched_text,
            "evidence": evidence_lines,
        }

    def _call_openrouter(self, payload: dict) -> AnalysisDraft | None:
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
            "messages": self._messages(payload),
            "response_format": {"type": "json_object"},
        }
        return self._call_chat_api(
            url=f"{self.openrouter_base_url}/chat/completions",
            headers=headers,
            body=body,
            provider_used="openrouter",
            fallback_used=False,
        )

    def _call_vllm(self, payload: dict) -> AnalysisDraft | None:
        if not self.vllm_base_url:
            return None

        headers = {
            "Authorization": f"Bearer {self.vllm_api_key or 'local-token'}",
            "Content-Type": "application/json",
        }
        body = {
            "model": self.vllm_model or self.model,
            "messages": self._messages(payload),
        }
        return self._call_chat_api(
            url=f"{self.vllm_base_url}/chat/completions",
            headers=headers,
            body=body,
            provider_used="vllm",
            fallback_used=True,
        )

    def _call_chat_api(
        self,
        url: str,
        headers: dict[str, str],
        body: dict,
        provider_used: str,
        fallback_used: bool,
    ) -> AnalysisDraft | None:
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

        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            return None

        usage = payload.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        cost_estimate = self._estimate_cost(provider_used, prompt_tokens, completion_tokens)

        return AnalysisDraft(
            title=str(parsed.get("title") or "Юридический риск"),
            summary=str(parsed.get("summary") or "Обнаружена потенциально рискованная формулировка."),
            legal_basis=str(parsed.get("legal_basis") or "").strip(),
            confidence=float(parsed.get("confidence") or 0.6),
            suggested_edit=str(
                parsed.get("suggested_edit") or "Требуется ручная юридическая проверка и редактирование."
            ),
            provider_used=provider_used,
            fallback_used=fallback_used,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_estimate=cost_estimate,
        )

    def _messages(self, payload: dict) -> list[dict]:
        return [
            {
                "role": "system",
                "content": (
                    "Ты анализируешь анонимизированный юридический текст и evidence. "
                    "Верни строго JSON-объект без markdown и без дополнительных пояснений. "
                    "Обязательные поля: title, summary, legal_basis, confidence, suggested_edit. "
                    "Пиши все значения полей на русском языке. "
                    "summary должен содержать только вывод по риску без ссылок на статьи, нормы и источники. "
                    "В summary обязательно явно укажи пункт или пункты договора, например: 'Пункт 4.2: ...'. "
                    "legal_basis должен содержать только подтвержденное правовое обоснование из переданного evidence. "
                    "legal_basis должен быть достаточно подробным: укажи подтверждающий фрагмент evidence и, если он есть в evidence, название источника или ссылку. "
                    "Запрещено упоминать статьи, нормы, кодексы, судебные акты и источники, которых нет в evidence. "
                    "Если evidence не содержит подтвержденного правового обоснования, верни legal_basis как пустую строку. "
                    "Учитывай только предоставленный текст и evidence. "
                    "summary должен быть кратким и конкретным. "
                    "suggested_edit должен содержать практичную формулировку правки на русском языке."
                ),
            },
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]

    def _extract_content(self, payload: dict) -> str:
        choices = payload.get("choices") or []
        if not choices:
            return ""
        message = choices[0].get("message") or {}
        content = message.get("content") or ""
        if isinstance(content, list):
            return "".join(part.get("text", "") for part in content if isinstance(part, dict))
        return str(content)

    def _estimate_cost(self, provider_used: str, prompt_tokens: int, completion_tokens: int) -> float:
        total_tokens = prompt_tokens + completion_tokens
        if total_tokens <= 0:
            return 0.0
        rate = 0.000002 if provider_used == "openrouter" else 0.0
        return round(total_tokens * rate, 6)

    def _perform_request(self, url: str, headers: dict[str, str], body: dict) -> dict:
        with httpx.Client(timeout=self.timeout_sec) as client:
            response = client.post(url, headers=headers, json=body)
            response.raise_for_status()
            return response.json()

    def _local_fallback(
        self,
        candidate: RiskCandidate,
        evidence: list[EvidenceItem],
        provider_used: str,
        fallback_used: bool,
    ) -> AnalysisDraft:
        confidence = 0.72 if evidence else 0.58
        evidence_note = (
            " Есть интернет-ориентиры для уточнения по доверенным источникам."
            if evidence
            else " Внешнее подтверждение не найдено, поэтому вывод предварительный."
        )
        legal_basis = ""
        if evidence:
            legal_basis = f"Подтверждение следует уточнить по источникам: {', '.join(item.title for item in evidence[:2])}."

        return AnalysisDraft(
            title=RISK_TITLES.get(candidate.risk_type, "Юридический риск"),
            summary=(
                f"{RISK_SUMMARIES.get(candidate.risk_type, 'Обнаружена потенциально рискованная формулировка.')}"
                f" Абзац содержит триггер: '{candidate.matched_text}'.{evidence_note}"
            ),
            legal_basis=legal_basis,
            confidence=confidence,
            suggested_edit=self._suggested_edit_by_risk.get(
                candidate.risk_type,
                "Переписать условие в более сбалансированной редакции.",
            ),
            provider_used=provider_used,
            fallback_used=fallback_used,
            prompt_tokens=0,
            completion_tokens=0,
            cost_estimate=0.0,
        )
