from __future__ import annotations


def compute_position_size(
    *,
    active_capital: float,
    risk_per_trade_pct: float,
    entry_price: float,
    stop_price: float,
    risk_multiplier: float = 1.0,
) -> float:
    risk_budget = max(active_capital, 0.0) * max(risk_per_trade_pct, 0.0) * max(risk_multiplier, 0.0)
    stop_distance = max(abs(entry_price - stop_price), 1e-8)
    return risk_budget / stop_distance
