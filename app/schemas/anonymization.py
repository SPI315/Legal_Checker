from pydantic import BaseModel, Field


class AnonymizeRequest(BaseModel):
    text: str = Field(min_length=1)
    use_ner: bool = True


class SpanResult(BaseModel):
    start: int
    end: int
    entity_type: str
    score: float
    source: str
    replacement: str


class AnonymizeResponse(BaseModel):
    anonymized_text: str
    spans: list[SpanResult]
    stats: dict[str, int]
