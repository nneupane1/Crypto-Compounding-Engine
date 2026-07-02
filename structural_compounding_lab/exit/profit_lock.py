from __future__ import annotations


def should_lock_profit(
    *,
    current_equity: float,
    base_capital: float,
    danger_state: dict,
    minimum_lock_profit: float = 0.0,
) -> bool:
    profit = current_equity - base_capital
    return bool(danger_state.get("danger")) and profit > max(minimum_lock_profit, 0.0)
