from __future__ import annotations


def classify_runner_eligibility(*, personality_label: str, risk_reward: float, htf_aligned: bool, pullback_quality_score: float) -> dict[str, object]:
    if personality_label == "STRUCTURAL_RUNNER" and htf_aligned and risk_reward >= 3.0:
        label = "structural_runner"
    elif personality_label in {"PULLBACK_CONTINUATION", "MOMENTUM_BURST"} and risk_reward >= 2.0:
        label = "normal_swing"
    elif risk_reward >= 4.0 and pullback_quality_score >= 0.65:
        label = "moonshot_candidate"
    elif personality_label == "EXHAUSTION_RISK":
        label = "exhaustion_risk_runner"
    else:
        label = "tactical_scalp"
    return {
        "runner_label": label,
        "runner_eligible_candidate": label in {"structural_runner", "moonshot_candidate", "normal_swing"},
    }
