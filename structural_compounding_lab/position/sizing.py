from __future__ import annotations


def position_notional(*, quantity: float, entry_price: float) -> float:
    return float(quantity) * float(entry_price)
