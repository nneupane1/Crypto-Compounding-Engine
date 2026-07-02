from __future__ import annotations

from typing import Any


def build_convexity_profile(
    candidate: dict[str, Any],
    *,
    min_risk_multiplier: float = 0.7,
    max_risk_multiplier: float = 1.35,
    strong_score_threshold: float = 3.6,
    elite_score_threshold: float = 4.1,
) -> dict[str, Any]:
    side = str(candidate.get("side", "flat")).lower()
    classification = str(candidate.get("classification", "no_trade")).upper()
    total_score = float(candidate.get("total_score", 0.0))
    risk_reward = float(candidate.get("risk_reward", 0.0))
    htf_bias = str(candidate.get("htf_bias", "neutral")).lower()
    aligned = (side == "long" and htf_bias == "bullish") or (side == "short" and htf_bias == "bearish")

    base_multiplier = {
        "A": 1.10,
        "B": 1.00,
        "C": 0.82,
    }.get(classification, 0.0)
    if aligned:
        base_multiplier += 0.08
    if risk_reward >= 2.5:
        base_multiplier += 0.05
    if float(candidate.get("liquidity_support", 0.0)) >= 0.6:
        base_multiplier += 0.04

    risk_multiplier = max(min_risk_multiplier, min(max_risk_multiplier, base_multiplier))
    if total_score >= elite_score_threshold:
        label = "elite_convexity"
    elif total_score >= strong_score_threshold:
        label = "strong_convexity"
    elif classification in {"A", "B"}:
        label = "measured_convexity"
    else:
        label = "capital_preservation"

    add_on_budget = {
        "elite_convexity": 2,
        "strong_convexity": 2,
        "measured_convexity": 1,
        "capital_preservation": 0,
    }[label]
    if not aligned and label != "elite_convexity":
        add_on_budget = max(0, add_on_budget - 1)

    return {
        "label": label,
        "aligned_with_htf": aligned,
        "risk_multiplier": round(risk_multiplier, 4),
        "add_on_budget": int(add_on_budget),
        "add_on_min_score": 3.05 if classification in {"A", "B"} else 3.35,
        "add_on_min_stop_upgrade_r": 0.30 if classification == "A" else 0.45,
        "trail_activation_r": 0.85 if aligned else 1.10,
        "profit_lock_floor_r": 1.10 if aligned else 0.80,
        "cooldown_fast_clear_eligible": aligned and total_score >= strong_score_threshold,
    }
