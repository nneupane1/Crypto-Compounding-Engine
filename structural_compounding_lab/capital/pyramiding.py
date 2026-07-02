from __future__ import annotations


def should_add_to_winner(
    *,
    side: str,
    entry_price: float,
    current_price: float,
    active_stop_price: float,
    add_on_count: int,
    max_add_ons: int,
    pnl_r: float,
    trigger_r: float,
    score: float = 0.0,
    min_score: float = 0.0,
    stop_improved_by_r: float = 0.0,
    min_stop_upgrade_r: float = 0.0,
    convexity_budget_remaining: int | None = None,
) -> bool:
    if add_on_count >= max_add_ons:
        return False
    if convexity_budget_remaining is not None and convexity_budget_remaining <= 0:
        return False
    if pnl_r < trigger_r:
        return False
    if score < min_score:
        return False
    if stop_improved_by_r < min_stop_upgrade_r:
        return False
    if side == "long":
        return current_price > entry_price and active_stop_price >= entry_price
    return current_price < entry_price and active_stop_price <= entry_price
