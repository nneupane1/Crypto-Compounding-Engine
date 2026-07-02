from __future__ import annotations

from .add_on_readiness import evaluate_add_on_readiness
from .cooldown_context import derive_cooldown_context
from .convexity_context import derive_convexity_context
from .de_risk_score import compute_de_risk_score
from .patience_score import compute_patience_score
from .runner_eligibility import classify_runner_eligibility


def assess_compounding_readiness(
    *,
    personality_label: str,
    htf_aligned: bool,
    risk_reward: float,
    pullback_quality_score: float,
    exhaustion_warning: bool,
    volume_distribution_warning: bool,
    cooldown_active: bool,
    fast_clear_eligible: bool,
    risk_multiplier: float,
    convexity_label: str | None,
    pullback_type: str,
) -> dict[str, object]:
    patience = compute_patience_score(
        personality_label=personality_label,
        htf_aligned=htf_aligned,
        risk_reward=risk_reward,
        exhaustion_warning=exhaustion_warning,
    )
    de_risk = compute_de_risk_score(
        exhaustion_warning=exhaustion_warning,
        pullback_type=pullback_type,
        volume_distribution_warning=volume_distribution_warning,
    )
    runner = classify_runner_eligibility(
        personality_label=personality_label,
        risk_reward=risk_reward,
        htf_aligned=htf_aligned,
        pullback_quality_score=pullback_quality_score,
    )
    add_on = evaluate_add_on_readiness(
        pullback_quality_score=pullback_quality_score,
        personality_label=personality_label,
        htf_aligned=htf_aligned,
    )
    cooldown = derive_cooldown_context(
        cooldown_active=cooldown_active,
        fast_clear_eligible=fast_clear_eligible,
    )
    convexity = derive_convexity_context(
        risk_multiplier=risk_multiplier,
        convexity_label=convexity_label,
    )
    readiness = max(0.0, min(1.0, 0.25 + (0.35 * patience) + (0.25 * pullback_quality_score) - (0.2 * de_risk)))
    return {
        "compounding_readiness_score": round(readiness, 4),
        "patience_score": patience,
        "de_risk_score": de_risk,
        **runner,
        **add_on,
        **cooldown,
        **convexity,
        "explanation": "Research-only readiness score for runner patience, add-on quality, and de-risk pressure.",
    }
