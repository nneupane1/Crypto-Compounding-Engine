from __future__ import annotations

from typing import Any


def build_atr_context(row: dict[str, Any] | Any, *, stop_price: float | None = None) -> dict[str, Any]:
    close = float(getattr(row, "get", lambda key, default=None: default)("close", 0.0))
    atr_value = float(getattr(row, "get", lambda key, default=None: default)("atr", 0.0) or 0.0)
    stop_distance = abs(close - float(stop_price)) if stop_price is not None else None
    return {
        "atr_value": atr_value,
        "atr_pct": (atr_value / close) if close else 0.0,
        "stop_distance": stop_distance,
        "stop_distance_atr": (stop_distance / atr_value) if stop_distance is not None and atr_value > 0 else None,
        "atr_usable": atr_value > 0.0,
    }
