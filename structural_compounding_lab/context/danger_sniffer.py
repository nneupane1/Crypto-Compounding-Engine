from __future__ import annotations

from typing import Any

import pandas as pd


def detect_danger_state(
    row: pd.Series | dict[str, Any],
    *,
    side: str,
    htf_context: dict[str, Any],
    atr_shock_multiple: float = 2.4,
    open_trade: dict[str, Any] | None = None,
) -> dict[str, Any]:
    atr_value = float(row.get("atr", 0.0))
    candle_range = abs(float(row.get("high", row.get("close", 0.0))) - float(row.get("low", row.get("close", 0.0))))
    shock = atr_value > 0 and candle_range >= atr_value * atr_shock_multiple
    ema_fast_slope = float(row.get("ema_fast_slope", 0.0))
    ema_mid_slope = float(row.get("ema_mid_slope", 0.0))
    trend_against = (
        side == "long" and ema_fast_slope < 0 and ema_mid_slope < 0
    ) or (
        side == "short" and ema_fast_slope > 0 and ema_mid_slope > 0
    )
    htf_against = (
        side == "long" and htf_context.get("bias") == "bearish"
    ) or (
        side == "short" and htf_context.get("bias") == "bullish"
    )
    stop_broken = False
    pnl_r = 0.0
    if open_trade is not None:
        active_stop = float(open_trade.get("active_stop_price") or open_trade.get("stop_price") or 0.0)
        close_price = float(row.get("close", 0.0))
        entry_price = float(open_trade.get("entry_price") or close_price)
        risk_per_unit = max(float(open_trade.get("risk_per_unit") or 0.0), 1e-8)
        pnl_r = (
            (close_price - entry_price) / risk_per_unit
            if side == "long"
            else (entry_price - close_price) / risk_per_unit
        )
        stop_broken = (
            side == "long" and active_stop > 0 and close_price < active_stop
        ) or (
            side == "short" and active_stop > 0 and close_price > active_stop
        )
    recovered = pnl_r >= 0.6 and not shock and not stop_broken
    danger = shock or trend_against or htf_against or stop_broken
    reasons = []
    if shock:
        reasons.append("volatility_shock")
    if trend_against:
        reasons.append("ema_trend_reversal")
    if htf_against:
        reasons.append("htf_confirmation_lost")
    if stop_broken:
        reasons.append("active_stop_broken")
    return {
        "danger": danger,
        "recovered": recovered,
        "pnl_r": pnl_r,
        "shock": shock,
        "trend_against": trend_against,
        "htf_against": htf_against,
        "stop_broken": stop_broken,
        "reasons": reasons,
    }
