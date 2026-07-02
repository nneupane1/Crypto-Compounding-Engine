from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class StructuralResearchCandidate:
    candidate_id: str
    hypothesis: str
    allowed_scope: list[str]
    forbidden_scope: list[str]
    required_inputs: list[str]
    expected_outputs: list[str]
    validation_ladder: list[str]
    acceptance_criteria: list[str]
    no_go_rules: list[str]
    safety_flags: dict[str, Any] = field(default_factory=dict)
    rollback_plan: str = "Delete candidate wiring and fall back to read-only artifact generation."
    live_allowed: bool = False
    paper_allowed: bool = False
    real_money_allowed: bool = False
    authoritative: bool = False
    requires_manual_promotion: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
