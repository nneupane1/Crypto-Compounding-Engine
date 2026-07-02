from __future__ import annotations


def compute_de_risk_score(*, exhaustion_warning: bool, pullback_type: str, volume_distribution_warning: bool) -> float:
    score = 0.15
    if exhaustion_warning:
        score += 0.35
    if pullback_type in {"EXHAUSTION_DIP", "STRUCTURE_BREAK_DIP"}:
        score += 0.35
    if volume_distribution_warning:
        score += 0.15
    return round(max(0.0, min(1.0, score)), 4)
