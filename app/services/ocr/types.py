from dataclasses import dataclass


@dataclass(slots=True)
class OcrStageResult:
    status: str
    detail: str
    quality_flag: str | None = None
    degraded_flags: list[str] | None = None
