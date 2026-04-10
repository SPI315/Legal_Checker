from dataclasses import dataclass


@dataclass(slots=True)
class RetrievalRequest:
    query: str
    risk_type: str
    jurisdiction: str
    paragraph_id: str
    paragraph_text: str


@dataclass(slots=True)
class RetrievalResult:
    evidence: list
    provider_used: str
    fallback_used: bool
