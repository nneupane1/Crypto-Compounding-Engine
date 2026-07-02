from __future__ import annotations

from typing import Any


def build_trade_plan(candidate: dict[str, Any], *, max_hold_bars: int) -> dict[str, Any]:
    entry_price = float(candidate["close_price"])
    stop_price = float(candidate["stop_price"])
    side = str(candidate["side"])
    risk_per_unit = max(abs(entry_price - stop_price), 1e-8)
    target_price = candidate.get("target_price")
    if target_price is not None:
        initial_target = float(target_price)
    elif side == "long":
        initial_target = entry_price + risk_per_unit * max(float(candidate.get("risk_reward", 1.5)), 1.5)
    else:
        initial_target = entry_price - risk_per_unit * max(float(candidate.get("risk_reward", 1.5)), 1.5)
    return {
        "entry_price": entry_price,
        "stop_price": stop_price,
        "initial_target": initial_target,
        "risk_per_unit": risk_per_unit,
        "max_hold_bars": max_hold_bars,
    }
