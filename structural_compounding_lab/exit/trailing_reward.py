from __future__ import annotations

from typing import Any

import pandas as pd


def evaluate_exit(
    trade: dict[str, Any],
    row: pd.Series | dict[str, Any],
    *,
    holding_bars: int,
    danger_state: dict[str, Any],
) -> dict[str, Any]:
    side = str(trade["side"])
    close_price = float(row["close"])
    high_price = float(row["high"])
    low_price = float(row["low"])
    stop_price = float(trade["active_stop_price"])
    risk_per_unit = max(float(trade["risk_per_unit"]), 1e-8)
    if side == "long":
        pnl_r = (close_price - float(trade["entry_price"])) / risk_per_unit
        max_extension = (high_price - float(trade["entry_price"])) / risk_per_unit
        if low_price <= stop_price:
            return {"exit": True, "reason": "stop_hit", "exit_price": stop_price, "pnl_r": (stop_price - float(trade["entry_price"])) / risk_per_unit}
    else:
        pnl_r = (float(trade["entry_price"]) - close_price) / risk_per_unit
        max_extension = (float(trade["entry_price"]) - low_price) / risk_per_unit
        if high_price >= stop_price:
            return {"exit": True, "reason": "stop_hit", "exit_price": stop_price, "pnl_r": (float(trade["entry_price"]) - stop_price) / risk_per_unit}

    if danger_state.get("danger"):
        return {"exit": True, "reason": "danger_sniffed", "exit_price": close_price, "pnl_r": pnl_r}
    if holding_bars >= int(trade["max_hold_bars"]):
        return {"exit": True, "reason": "time_stop", "exit_price": close_price, "pnl_r": pnl_r}
    if pnl_r >= 2.0 and max_extension < pnl_r + 0.15:
        return {"exit": True, "reason": "slow_grind_exit", "exit_price": close_price, "pnl_r": pnl_r}
    if pnl_r >= 4.0:
        return {"exit": True, "reason": "moonshot_capture", "exit_price": close_price, "pnl_r": pnl_r}
    new_stop = stop_price
    if side == "long":
        if max_extension >= 1.0:
            new_stop = max(new_stop, float(trade["entry_price"]))
        if max_extension >= 2.0:
            new_stop = max(new_stop, float(trade["entry_price"]) + risk_per_unit)
    else:
        if max_extension >= 1.0:
            new_stop = min(new_stop, float(trade["entry_price"]))
        if max_extension >= 2.0:
            new_stop = min(new_stop, float(trade["entry_price"]) - risk_per_unit)
    return {"exit": False, "reason": "", "exit_price": None, "pnl_r": pnl_r, "new_stop": new_stop}
