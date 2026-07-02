from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import pandas as pd

from .pivots import detect_pivots


@dataclass(frozen=True)
class LiquidityEvent:
    timestamp: str
    price: float
    type: str
    side_implication: str
    source_timeframe: str
    confidence: float
    no_future_data: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def detect_liquidity_events(
    frame: pd.DataFrame,
    *,
    cutoff_timestamp: Any = None,
    timeframe_source: str = "1h",
    equal_level_tolerance_pct: float = 0.0012,
    sweep_lookback_bars: int = 20,
    reclaim_tolerance_pct: float = 0.0008,
) -> list[LiquidityEvent]:
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
    if len(working) < 5:
        return []

    events: list[LiquidityEvent] = []
    pivots = detect_pivots(working, left_bars=1, right_bars=1, cutoff_timestamp=cutoff_timestamp, timeframe_source=timeframe_source)
    highs = [pivot for pivot in pivots if pivot.side == "high"]
    lows = [pivot for pivot in pivots if pivot.side == "low"]
    for previous, current in zip(highs, highs[1:]):
        tolerance = max(abs(previous.price), abs(current.price)) * equal_level_tolerance_pct
        if abs(previous.price - current.price) <= tolerance:
            events.append(
                LiquidityEvent(
                    timestamp=current.timestamp,
                    price=(previous.price + current.price) / 2.0,
                    type="equal_highs",
                    side_implication="bearish_if_swept",
                    source_timeframe=timeframe_source,
                    confidence=0.55,
                )
            )
    for previous, current in zip(lows, lows[1:]):
        tolerance = max(abs(previous.price), abs(current.price)) * equal_level_tolerance_pct
        if abs(previous.price - current.price) <= tolerance:
            events.append(
                LiquidityEvent(
                    timestamp=current.timestamp,
                    price=(previous.price + current.price) / 2.0,
                    type="equal_lows",
                    side_implication="bullish_if_swept",
                    source_timeframe=timeframe_source,
                    confidence=0.55,
                )
            )

    for index in range(sweep_lookback_bars, len(working)):
        window = working.iloc[index - sweep_lookback_bars:index]
        row = working.iloc[index]
        timestamp = str(pd.Timestamp(working.index[index]).isoformat())
        range_high = float(window["high"].max())
        range_low = float(window["low"].min())
        reclaim_tolerance = max(abs(row["close"]) * reclaim_tolerance_pct, 1e-8)

        if float(row["high"]) > range_high and float(row["close"]) < (range_high - reclaim_tolerance):
            events.append(
                LiquidityEvent(
                    timestamp=timestamp,
                    price=float(row["high"]),
                    type="sweep_high",
                    side_implication="short",
                    source_timeframe=timeframe_source,
                    confidence=0.72,
                )
            )
            events.append(
                LiquidityEvent(
                    timestamp=timestamp,
                    price=range_high,
                    type="failed_breakout",
                    side_implication="short",
                    source_timeframe=timeframe_source,
                    confidence=0.68,
                )
            )
        elif float(row["close"]) > range_high:
            events.append(
                LiquidityEvent(
                    timestamp=timestamp,
                    price=range_high,
                    type="retest_after_breakout",
                    side_implication="long",
                    source_timeframe=timeframe_source,
                    confidence=0.5,
                )
            )

        if float(row["low"]) < range_low and float(row["close"]) > (range_low + reclaim_tolerance):
            events.append(
                LiquidityEvent(
                    timestamp=timestamp,
                    price=float(row["low"]),
                    type="sweep_low",
                    side_implication="long",
                    source_timeframe=timeframe_source,
                    confidence=0.72,
                )
            )
            events.append(
                LiquidityEvent(
                    timestamp=timestamp,
                    price=range_low,
                    type="failed_breakdown",
                    side_implication="long",
                    source_timeframe=timeframe_source,
                    confidence=0.68,
                )
            )
        elif float(row["close"]) < range_low:
            events.append(
                LiquidityEvent(
                    timestamp=timestamp,
                    price=range_low,
                    type="retest_after_breakdown",
                    side_implication="short",
                    source_timeframe=timeframe_source,
                    confidence=0.5,
                )
            )
    deduped: dict[tuple[str, str, float], LiquidityEvent] = {}
    for event in events:
        key = (event.timestamp, event.type, round(event.price, 8))
        deduped.setdefault(key, event)
    return sorted(deduped.values(), key=lambda item: (item.timestamp, item.type))
