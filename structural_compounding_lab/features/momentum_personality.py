from __future__ import annotations

from typing import Any


def classify_momentum_personality(
    *,
    candidate: dict[str, Any],
    ema_context: dict[str, Any],
    volume_context: dict[str, Any],
    vwap_context: dict[str, Any],
    macd_features: dict[str, Any],
    bollinger_features: dict[str, Any],
    pullback_features: dict[str, Any],
    htf_context: dict[str, Any],
) -> dict[str, Any]:
    supporting: list[str] = []
    warnings: list[str] = []
    missing = list(macd_features.get("missing_data_fields", [])) + list(bollinger_features.get("missing_data_fields", [])) + list(pullback_features.get("missing_data_fields", []))

    if ema_context.get("ema_aligned"):
        supporting.append("ema_aligned")
    if volume_context.get("volume_expansion"):
        supporting.append("volume_expansion")
    if volume_context.get("volume_dryup"):
        supporting.append("volume_dryup_on_pullback")
    if vwap_context.get("vwap_supportive"):
        supporting.append("vwap_supportive")
    if htf_context.get("htf_supportive"):
        supporting.append("htf_supportive")
    if macd_features.get("macd_confirmation_flag"):
        supporting.append("macd_confirmation")
    if bollinger_features.get("bb_confirmation_flag"):
        supporting.append("bollinger_expansion_confirmation")

    if macd_features.get("macd_warning_flag"):
        warnings.append("macd_warning")
    if bollinger_features.get("bb_warning_flag"):
        warnings.append("bollinger_exhaustion_warning")
    if volume_context.get("distribution_warning"):
        warnings.append("distribution_warning")
    if not htf_context.get("htf_aligned") and htf_context.get("htf_bias") != "neutral":
        warnings.append("htf_countertrend")

    pullback_type = str(pullback_features.get("pullback_type", "NO_PULLBACK_SIGNAL"))
    if pullback_type == "MICRO_PULLBACK_MOMENTUM":
        label = "PULLBACK_CONTINUATION"
    elif pullback_type == "BREAKOUT_RETEST_PULLBACK":
        label = "STRUCTURAL_RUNNER"
    elif bollinger_features.get("bb_compression") and macd_features.get("macd_confirmation_flag"):
        label = "COMPRESSION_BREAKOUT"
    elif macd_features.get("macd_confirmation_flag") and volume_context.get("volume_expansion"):
        label = "MOMENTUM_BURST"
    elif "exhaustion" in pullback_type.lower() or len(warnings) >= 2:
        label = "EXHAUSTION_RISK"
    elif not supporting:
        label = "NO_PERSONALITY_EDGE"
    else:
        label = "CHOPPY_LOW_TRUST"

    confidence = min(0.95, 0.2 + (0.12 * len(supporting)) - (0.08 * len(warnings)))
    explanation = (
        f"{label} from EMA/HTF structure, volume state, MACD/Bollinger soft evidence, and pullback type {pullback_type}. "
        f"Warnings do not invalidate the core setup; they downgrade confidence only."
    )
    return {
        "personality_label": label,
        "personality_confidence": round(max(0.05, confidence), 4),
        "supporting_conditions": supporting,
        "warning_conditions": warnings,
        "missing_data_fields": missing,
        "explanation_text": explanation,
    }
