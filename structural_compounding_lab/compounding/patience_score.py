from __future__ import annotations

from typing import Any


def compute_patience_score(*, personality_label: str, htf_aligned: bool, risk_reward: float, exhaustion_warning: bool) -> float:
    score = 0.2
    if personality_label in {"STRUCTURAL_RUNNER", "PULLBACK_CONTINUATION"}:
        score += 0.35
    if htf_aligned:
        score += 0.2
    if risk_reward >= 2.5:
        score += 0.15
    if exhaustion_warning:
        score -= 0.2
    return round(max(0.0, min(1.0, score)), 4)
