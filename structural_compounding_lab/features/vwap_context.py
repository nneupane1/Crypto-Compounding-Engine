from __future__ import annotations

from typing import Any


def build_vwap_context(row: dict[str, Any] | Any, *, side: str | None = None) -> dict[str, Any]:
    close = float(getattr(row, "get", lambda key, default=None: default)("close", 0.0))
    vwap = float(getattr(row, "get", lambda key, default=None: default)("vwap", 0.0) or 0.0)
    distance = ((close - vwap) / vwap) if vwap else 0.0
    supportive = close >= vwap if side == "long" else close <= vwap if side == "short" else abs(distance) <= 0.01
    return {
        "vwap": vwap,
        "vwap_distance_pct": distance,
        "vwap_supportive": supportive,
        "vwap_reaction": "above" if close >= vwap else "below",
    }
