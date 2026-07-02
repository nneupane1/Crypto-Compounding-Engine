from __future__ import annotations

from typing import Any

import pandas as pd


_PULLBACK_TYPES = {
    "healthy": "HEALTHY_CONTINUATION_PULLBACK",
    "micro": "MICRO_PULLBACK_MOMENTUM",
    "retest": "BREAKOUT_RETEST_PULLBACK",
    "deep": "DEEP_VALUE_PULLBACK",
    "exhaustion": "EXHAUSTION_DIP",
    "broken": "STRUCTURE_BREAK_DIP",
    "none": "NO_PULLBACK_SIGNAL",
}


def detect_micro_pullback(
    *,
    lower_timeframe_frame: pd.DataFrame | None,
    current_time: Any,
    candidate: dict[str, Any],
    macd_features: dict[str, Any] | None = None,
    bollinger_features: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if lower_timeframe_frame is None or lower_timeframe_frame.empty:
        return {
            "micro_pullback_detected": False,
            "pullback_type": _PULLBACK_TYPES["none"],
            "missing_data_fields": ["lower_timeframe_frame"],
            "explanation": "Lower timeframe history not available for pullback analysis.",
        }

    timestamp = pd.Timestamp(current_time)
    window = lower_timeframe_frame.loc[lower_timeframe_frame.index <= timestamp].tail(48).copy()
    if len(window) < 8:
        return {
            "micro_pullback_detected": False,
            "pullback_type": _PULLBACK_TYPES["none"],
            "missing_data_fields": ["insufficient_lower_timeframe_bars"],
            "explanation": "Not enough lower timeframe bars to evaluate structural pullback geometry.",
        }

    side = str(candidate.get("side", "long")).lower()
    current_close = float(window["close"].iloc[-1])
    atr_value = float(candidate.get("atr", 0.0) or 0.0)
    if atr_value <= 0.0:
        atr_value = max(abs(float(window["high"].tail(12).max()) - float(window["low"].tail(12).min())) / 6.0, 1e-8)

    lookback = window.tail(16)
    prior_impulse = lookback.iloc[:-4] if len(lookback) > 5 else lookback
    if side == "long":
        impulse_anchor = float(prior_impulse["low"].min())
        impulse_peak = float(prior_impulse["high"].max())
        pullback_low = float(lookback["low"].tail(6).min())
        pullback_high = float(lookback["high"].tail(6).max())
        stop_price = pullback_low
        stop_distance = max(current_close - stop_price, 0.0)
        reward = max(float(candidate.get("target_price", current_close)) - current_close, 0.0)
        pullback_depth = max(impulse_peak - pullback_low, 0.0)
        structure_broken = pullback_low < min(float(candidate.get("level_price", pullback_low)), impulse_anchor)
        resumed = current_close >= pullback_high * 0.997
    else:
        impulse_anchor = float(prior_impulse["high"].max())
        impulse_peak = float(prior_impulse["low"].min())
        pullback_low = float(lookback["low"].tail(6).min())
        pullback_high = float(lookback["high"].tail(6).max())
        stop_price = pullback_high
        stop_distance = max(stop_price - current_close, 0.0)
        reward = max(current_close - float(candidate.get("target_price", current_close)), 0.0)
        pullback_depth = max(pullback_high - impulse_peak, 0.0)
        structure_broken = pullback_high > max(float(candidate.get("level_price", pullback_high)), impulse_anchor)
        resumed = current_close <= pullback_low * 1.003

    depth_atr = (pullback_depth / atr_value) if atr_value > 0 else 0.0
    stop_distance_atr = (stop_distance / atr_value) if atr_value > 0 else None
    original_r = float(candidate.get("risk_reward", 0.0) or 0.0)
    refined_r = (reward / stop_distance) if stop_distance > 0 else original_r
    r_improvement = refined_r - original_r

    macd_warning = bool((macd_features or {}).get("macd_warning_flag"))
    bb_warning = bool((bollinger_features or {}).get("bb_warning_flag"))
    volume_dryup = bool(candidate.get("volume_dryup", False))
    breakout_retest = "retest_after_break" in str(candidate.get("pattern", ""))

    if structure_broken:
        pullback_type = _PULLBACK_TYPES["broken"]
    elif (macd_warning and bb_warning) or depth_atr >= 2.6:
        pullback_type = _PULLBACK_TYPES["exhaustion"]
    elif breakout_retest and depth_atr <= 1.8:
        pullback_type = _PULLBACK_TYPES["retest"]
    elif depth_atr <= 0.8 and resumed:
        pullback_type = _PULLBACK_TYPES["micro"]
    elif depth_atr <= 1.8:
        pullback_type = _PULLBACK_TYPES["healthy"]
    else:
        pullback_type = _PULLBACK_TYPES["deep"]

    detected = pullback_type not in {_PULLBACK_TYPES["broken"], _PULLBACK_TYPES["exhaustion"], _PULLBACK_TYPES["none"]} and resumed
    quality = 0.0
    quality += 0.3 if resumed else 0.0
    quality += 0.2 if volume_dryup else 0.0
    quality += 0.2 if r_improvement > 0 else 0.0
    quality += 0.15 if stop_distance_atr is not None and stop_distance_atr <= 1.0 else 0.0
    quality += 0.15 if pullback_type == _PULLBACK_TYPES["retest"] else 0.1 if pullback_type in {_PULLBACK_TYPES["micro"], _PULLBACK_TYPES["healthy"]} else 0.0
    quality = min(1.0, quality)

    return {
        "micro_pullback_detected": detected,
        "entry_candidate_time": pd.Timestamp(window.index[-1]).isoformat(),
        "entry_candidate_price": current_close,
        "pullback_low": pullback_low,
        "pullback_high": pullback_high,
        "stop_price": stop_price,
        "stop_distance": stop_distance,
        "stop_distance_atr": stop_distance_atr,
        "pullback_depth_atr": depth_atr,
        "estimated_R_to_existing_target": refined_r,
        "original_risk_reward": original_r,
        "r_improvement_vs_original": r_improvement,
        "pullback_quality_score": round(quality, 4),
        "pullback_type": pullback_type,
        "missing_data_fields": [],
        "explanation": f"{pullback_type} with depth {depth_atr:.2f} ATR and refined R delta {r_improvement:.2f}.",
    }
