from dataclasses import dataclass


@dataclass(slots=True)
class RuleDefinition:
    risk_type: str
    title: str
    patterns: list[str]
    suggested_edit: str
