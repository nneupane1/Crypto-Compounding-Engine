from __future__ import annotations

from typing import Any


def build_ema_context(row: dict[str, Any] | Any, *, side: str | None = None) -> dict[str, Any]:
    ema_fast = float(getattr(row, "get", lambda key, default=None: default)("ema_20", 0.0))
    ema_mid = float(getattr(row, "get", lambda key, default=None: default)("ema_50", 0.0))
    ema_slow = float(getattr(row, "get", lambda key, default=None: default)("ema_200", 0.0))
    close = float(getattr(row, "get", lambda key, default=None: default)("close", 0.0))
    fast_slope = float(getattr(row, "get", lambda key, default=None: default)("ema_fast_slope", 0.0) or 0.0)
    mid_slope = float(getattr(row, "get", lambda key, default=None: default)("ema_mid_slope", 0.0) or 0.0)
    bullish_stack = close >= ema_fast >= ema_mid >= ema_slow
    bearish_stack = close <= ema_fast <= ema_mid <= ema_slow
    aligned = bullish_stack if side == "long" else bearish_stack if side == "short" else bullish_stack or bearish_stack
    return {
        "ema_fast": ema_fast,
        "ema_mid": ema_mid,
        "ema_slow": ema_slow,
        "ema_close_distance_pct": ((close - ema_fast) / ema_fast) if ema_fast else 0.0,
        "ema_fast_slope": fast_slope,
        "ema_mid_slope": mid_slope,
        "bullish_stack": bullish_stack,
        "bearish_stack": bearish_stack,
        "ema_aligned": aligned,
    }
