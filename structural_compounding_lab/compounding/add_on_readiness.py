from __future__ import annotations


def evaluate_add_on_readiness(*, pullback_quality_score: float, personality_label: str, htf_aligned: bool) -> dict[str, object]:
    ready = pullback_quality_score >= 0.6 and personality_label in {"PULLBACK_CONTINUATION", "STRUCTURAL_RUNNER", "MOMENTUM_BURST"} and htf_aligned
    return {
        "add_on_research_candidate": ready,
        "add_on_readiness_score": round(min(1.0, (pullback_quality_score + (0.2 if htf_aligned else 0.0))), 4),
    }
