from __future__ import annotations

from typing import Any

import pandas as pd


def classify_trend_regime(row: pd.Series | dict[str, Any], *, fast: int = 20, mid: int = 50, slow: int = 200) -> str:
    fast_key = f"ema_{fast}"
    mid_key = f"ema_{mid}"
    slow_key = f"ema_{slow}"
    fast_value = float(row.get(fast_key, 0.0))
    mid_value = float(row.get(mid_key, 0.0))
    slow_value = float(row.get(slow_key, 0.0))
    fast_slope = float(row.get("ema_fast_slope", 0.0))
    mid_slope = float(row.get("ema_mid_slope", 0.0))
    if fast_value > mid_value > slow_value and fast_slope >= 0 and mid_slope >= 0:
        return "bullish"
    if fast_value < mid_value < slow_value and fast_slope <= 0 and mid_slope <= 0:
        return "bearish"
    return "neutral"
