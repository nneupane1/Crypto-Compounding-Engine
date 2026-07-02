from __future__ import annotations

from typing import Any


def score_setup_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    side = str(candidate["side"]).lower()
    htf_bias = str(candidate.get("htf_bias", "neutral")).lower()
    htf_score_raw = float(candidate.get("htf_score", 0.0))
    htf_aligned = (side == "long" and htf_bias == "bullish") or (side == "short" and htf_bias == "bearish")

    level_strength = float(candidate.get("level_strength", 0.0))
    level_distance_atr = float(candidate.get("level_distance_atr", 9.0))
    liquidity_support = float(candidate.get("liquidity_support", 0.0))
    liquidity_event_age_bars = candidate.get("liquidity_event_age_bars")
    liquidity_event_age_bars = int(liquidity_event_age_bars) if liquidity_event_age_bars is not None else None

    structure_score = min(1.45, 0.45 + (level_strength * 0.28))
    if level_distance_atr <= 0.5:
        structure_score += 0.25
    elif level_distance_atr <= 0.9:
        structure_score += 0.12
    elif level_distance_atr >= 1.35:
        structure_score -= 0.18

    liquidity_score = 0.0
    if liquidity_support > 0.0:
        liquidity_score = min(1.25, 0.2 + liquidity_support)
        if liquidity_event_age_bars is not None:
            if liquidity_event_age_bars <= 2:
                liquidity_score += 0.18
            elif liquidity_event_age_bars <= 6:
                liquidity_score += 0.08
            elif liquidity_event_age_bars >= 14:
                liquidity_score -= 0.12

    ema_fast = float(candidate.get("ema_fast", 0.0))
    ema_mid = float(candidate.get("ema_mid", 0.0))
    ema_slow = float(candidate.get("ema_slow", 0.0))
    ema_alignment = 0.0
    if side == "long" and ema_fast >= ema_mid:
        ema_alignment += 0.45
    if side == "short" and ema_fast <= ema_mid:
        ema_alignment += 0.45
    if side == "long" and ema_mid >= ema_slow:
        ema_alignment += 0.35
    if side == "short" and ema_mid <= ema_slow:
        ema_alignment += 0.35
    if side == "long" and ema_fast >= ema_slow:
        ema_alignment += 0.12
    if side == "short" and ema_fast <= ema_slow:
        ema_alignment += 0.12

    htf_score = 0.0
    if htf_aligned:
        htf_score = 0.55 + min(0.35, abs(htf_score_raw) * 0.12)
    elif htf_bias == "neutral":
        htf_score = 0.18
    else:
        htf_score = -0.2

    volatility_score = 0.35 if float(candidate.get("atr", 0.0)) > 0 else 0.0
    if level_distance_atr > 1.0:
        volatility_score -= 0.08

    risk_reward = float(candidate.get("risk_reward", 0.0))
    risk_reward_score = min(1.25, risk_reward / 2.2)

    total = structure_score + liquidity_score + ema_alignment + htf_score + volatility_score + risk_reward_score
    if total >= 4.45:
        classification = "A"
    elif total >= 3.5:
        classification = "B"
    elif total >= 2.75:
        classification = "C"
    else:
        classification = "no_trade"

    accepted = classification != "no_trade"
    explanation = (
        f"{classification} structural setup: {candidate.get('pattern')} near {candidate.get('level_type')} "
        f"| RR {risk_reward:.2f} | HTF {htf_bias} ({htf_score_raw:.1f}) | "
        f"level distance {level_distance_atr:.2f} ATR."
    )
    return {
        **candidate,
        "structure_score": round(structure_score, 4),
        "liquidity_score": round(liquidity_score, 4),
        "ema_score": round(ema_alignment, 4),
        "htf_confirmation_score": round(htf_score, 4),
        "volatility_score": round(volatility_score, 4),
        "risk_reward_score": round(risk_reward_score, 4),
        "total_score": round(total, 4),
        "classification": classification,
        "htf_aligned": htf_aligned,
        "accepted": accepted,
        "entry_reason": explanation,
        "decision": "qualified" if accepted else "rejected",
    }
