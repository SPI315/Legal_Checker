from dataclasses import dataclass


@dataclass(slots=True)
class AnalysisDraft:
    title: str
    summary: str
    confidence: float
    suggested_edit: str
    provider_used: str
    fallback_used: bool
    prompt_tokens: int
    completion_tokens: int
    cost_estimate: float
