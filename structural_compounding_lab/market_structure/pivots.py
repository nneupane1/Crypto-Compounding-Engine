from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any

import numpy as np
import pandas as pd


def _to_utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


@dataclass(frozen=True)
class PivotPoint:
    timestamp: str
    price: float
    side: str
    timeframe_source: str
    left_bars: int
    right_bars: int
    no_future_data: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_pivots(
    frame: pd.DataFrame,
    *,
    left_bars: int = 3,
    right_bars: int = 3,
    cutoff_timestamp: Any = None,
    timeframe_source: str = "unknown",
) -> list[PivotPoint]:
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
    if len(working) < left_bars + right_bars + 1:
        return []
    rows: list[PivotPoint] = []
    highs = working["high"].to_numpy(dtype=float, copy=False)
    lows = working["low"].to_numpy(dtype=float, copy=False)
    for index in range(left_bars, len(working) - right_bars):
        center_high = highs[index]
        center_low = lows[index]
        left_highs = highs[index - left_bars:index]
        right_highs = highs[index + 1:index + 1 + right_bars]
        left_lows = lows[index - left_bars:index]
        right_lows = lows[index + 1:index + 1 + right_bars]
        timestamp = pd.Timestamp(working.index[index])
        if bool(np.all(center_high > left_highs)) and bool(np.all(center_high >= right_highs)):
            rows.append(
                PivotPoint(
                    timestamp=timestamp.isoformat(),
                    price=float(center_high),
                    side="high",
                    timeframe_source=timeframe_source,
                    left_bars=left_bars,
                    right_bars=right_bars,
                )
            )
        if bool(np.all(center_low < left_lows)) and bool(np.all(center_low <= right_lows)):
            rows.append(
                PivotPoint(
                    timestamp=timestamp.isoformat(),
                    price=float(center_low),
                    side="low",
                    timeframe_source=timeframe_source,
                    left_bars=left_bars,
                    right_bars=right_bars,
                )
            )
    return rows
