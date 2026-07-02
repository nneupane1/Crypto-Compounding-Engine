from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd

from .level_strength import compute_level_strength
from .pivots import detect_pivots


@dataclass(frozen=True)
class StructuralLevel:
    price: float
    type: str
    timeframe_source: str
    touch_count: int
    recency: float
    strength: float
    first_seen: str
    last_touched: str
    display_only: bool
    research_flag: bool
    no_future_data: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _touch_count(frame: pd.DataFrame, *, price: float, tolerance_pct: float) -> int:
    tolerance = max(abs(price) * tolerance_pct, 1e-8)
    high_touches = int((np.abs(frame["high"].to_numpy(dtype=float, copy=False) - price) <= tolerance).sum())
    low_touches = int((np.abs(frame["low"].to_numpy(dtype=float, copy=False) - price) <= tolerance).sum())
    close_touches = int((np.abs(frame["close"].to_numpy(dtype=float, copy=False) - price) <= tolerance).sum())
    return int(max(high_touches, low_touches, close_touches, 1))


def _recency_bars(frame: pd.DataFrame, timestamp: Any) -> float:
    anchor = pd.Timestamp(timestamp)
    index = pd.DatetimeIndex(frame.index)
    if index.tz is None and anchor.tzinfo is not None:
        anchor = anchor.tz_convert("UTC").tz_localize(None)
    elif index.tz is not None and anchor.tzinfo is None:
        anchor = anchor.tz_localize(index.tz)
    elif index.tz is not None and anchor.tzinfo is not None:
        anchor = anchor.tz_convert(index.tz)
    if not index.is_monotonic_increasing:
        mask = index >= anchor
        return float(max(0, int(mask.sum()) - 1))
    position = int(index.searchsorted(anchor, side="left"))
    return float(max(0, len(index) - position - 1))


def _add_level(
    levels: dict[tuple[str, float, str], StructuralLevel],
    *,
    frame: pd.DataFrame,
    price: float,
    level_type: str,
    timeframe_source: str,
    first_seen: str,
    last_touched: str,
    tolerance_pct: float,
) -> None:
    rounded_price = round(float(price), 8)
    key = (level_type, rounded_price, timeframe_source)
    if key in levels:
        return
    touch_count = _touch_count(frame, price=rounded_price, tolerance_pct=tolerance_pct)
    recency = _recency_bars(frame, last_touched)
    strength = compute_level_strength(
        touch_count=touch_count,
        timeframe_source=timeframe_source,
        last_touched=last_touched,
        now_timestamp=frame.index[-1],
    )
    levels[key] = StructuralLevel(
        price=rounded_price,
        type=level_type,
        timeframe_source=timeframe_source,
        touch_count=touch_count,
        recency=recency,
        strength=strength,
        first_seen=str(first_seen),
        last_touched=str(last_touched),
        display_only=True,
        research_flag=True,
        no_future_data=True,
    )


def detect_structural_levels(
    frame: pd.DataFrame,
    *,
    cutoff_timestamp: Any = None,
    timeframe_source: str = "1h",
    pivot_left: int = 3,
    pivot_right: int = 3,
    tolerance_pct: float = 0.002,
    rolling_range_bars: int = 48,
) -> list[StructuralLevel]:
    if frame.empty:
        return []
    working = frame.copy()
    if cutoff_timestamp is not None:
        cutoff = _to_utc_timestamp(cutoff_timestamp)
        index = pd.DatetimeIndex(working.index)
        if index.tz is None:
            index = index.tz_localize("UTC")
        else:
            index = index.tz_convert("UTC")
        working = working.loc[index <= cutoff]
    if working.empty:
        return []

    levels: dict[tuple[str, float, str], StructuralLevel] = {}
    pivots = detect_pivots(
        working,
        left_bars=pivot_left,
        right_bars=pivot_right,
        cutoff_timestamp=cutoff_timestamp,
        timeframe_source=timeframe_source,
    )
    for pivot in pivots:
        mapped_type = "resistance" if pivot.side == "high" else "support"
        _add_level(
            levels,
            frame=working,
            price=pivot.price,
            level_type=mapped_type,
            timeframe_source=timeframe_source,
            first_seen=pivot.timestamp,
            last_touched=pivot.timestamp,
            tolerance_pct=tolerance_pct,
        )

    trailing = working.tail(max(rolling_range_bars, 4))
    range_high = float(trailing["high"].max())
    range_low = float(trailing["low"].min())
    midpoint = (range_high + range_low) / 2.0
    last_timestamp = str(pd.Timestamp(working.index[-1]).isoformat())
    first_timestamp = str(pd.Timestamp(trailing.index[0]).isoformat())
    _add_level(levels, frame=working, price=range_high, level_type="range_high", timeframe_source=timeframe_source, first_seen=first_timestamp, last_touched=last_timestamp, tolerance_pct=tolerance_pct)
    _add_level(levels, frame=working, price=range_low, level_type="range_low", timeframe_source=timeframe_source, first_seen=first_timestamp, last_touched=last_timestamp, tolerance_pct=tolerance_pct)
    _add_level(levels, frame=working, price=midpoint, level_type="midpoint", timeframe_source=timeframe_source, first_seen=first_timestamp, last_touched=last_timestamp, tolerance_pct=tolerance_pct)

    daily = (
        working.resample("1D", closed="left", label="right")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    weekly = (
        working.resample("1W", closed="left", label="right")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    if len(daily) >= 2:
        prior_day = daily.iloc[-2]
        prior_day_ts = str(pd.Timestamp(daily.index[-2]).isoformat())
        _add_level(levels, frame=working, price=float(prior_day["high"]), level_type="prev_day_high", timeframe_source="1d", first_seen=prior_day_ts, last_touched=last_timestamp, tolerance_pct=tolerance_pct)
        _add_level(levels, frame=working, price=float(prior_day["low"]), level_type="prev_day_low", timeframe_source="1d", first_seen=prior_day_ts, last_touched=last_timestamp, tolerance_pct=tolerance_pct)
    if len(weekly) >= 2:
        prior_week = weekly.iloc[-2]
        prior_week_ts = str(pd.Timestamp(weekly.index[-2]).isoformat())
        _add_level(levels, frame=working, price=float(prior_week["high"]), level_type="prev_week_high", timeframe_source="1w", first_seen=prior_week_ts, last_touched=last_timestamp, tolerance_pct=tolerance_pct)
        _add_level(levels, frame=working, price=float(prior_week["low"]), level_type="prev_week_low", timeframe_source="1w", first_seen=prior_week_ts, last_touched=last_timestamp, tolerance_pct=tolerance_pct)

    return sorted(levels.values(), key=lambda level: (level.timeframe_source, level.first_seen, level.type))
