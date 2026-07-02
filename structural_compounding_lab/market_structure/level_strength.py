from __future__ import annotations

from typing import Any

import pandas as pd


_TIMEFRAME_WEIGHT = {
    "1h": 1.0,
    "4h": 1.15,
    "12h": 1.3,
    "1d": 1.45,
    "1w": 1.65,
}


def compute_level_strength(
    *,
    touch_count: int,
    timeframe_source: str,
    last_touched: str | None = None,
    now_timestamp: Any = None,
) -> float:
    base = 1.0 + max(0, touch_count - 1) * 0.35
    timeframe_weight = _TIMEFRAME_WEIGHT.get(str(timeframe_source).lower(), 1.0)
    recency_multiplier = 1.0
    if last_touched and now_timestamp is not None:
        age_days = max(0.0, (_to_timestamp(now_timestamp) - _to_timestamp(last_touched)).total_seconds() / 86400.0)
        recency_multiplier = max(0.5, 1.25 - min(age_days / 90.0, 0.75))
    return round(base * timeframe_weight * recency_multiplier, 4)


def _to_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")
