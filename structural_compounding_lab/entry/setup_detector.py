from __future__ import annotations

from typing import Any

import pandas as pd


_LONG_LEVEL_TYPES = {"support", "range_low", "prev_day_low", "prev_week_low", "midpoint"}
_SHORT_LEVEL_TYPES = {"resistance", "range_high", "prev_day_high", "prev_week_high", "midpoint"}


def _bars_since(event_time: Any, current_time: pd.Timestamp, history_index: pd.DatetimeIndex) -> int | None:
    try:
        event_timestamp = pd.Timestamp(event_time)
    except Exception:
        return None
    if event_timestamp.tzinfo is None and current_time.tzinfo is not None:
        event_timestamp = event_timestamp.tz_localize(current_time.tzinfo)
    elif event_timestamp.tzinfo is not None and current_time.tzinfo is None:
        event_timestamp = event_timestamp.tz_convert("UTC").tz_localize(None)
    elif event_timestamp.tzinfo is not None and current_time.tzinfo is not None:
        event_timestamp = event_timestamp.tz_convert(current_time.tzinfo)
    index = pd.DatetimeIndex(history_index)
    if index.tz is None and event_timestamp.tzinfo is not None:
        event_timestamp = event_timestamp.tz_convert("UTC").tz_localize(None)
    elif index.tz is not None and event_timestamp.tzinfo is None:
        event_timestamp = event_timestamp.tz_localize(index.tz)
    elif index.tz is not None and event_timestamp.tzinfo is not None:
        event_timestamp = event_timestamp.tz_convert(index.tz)
    if index.empty:
        return None
    if not index.is_monotonic_increasing:
        positions = index.get_indexer([event_timestamp], method="pad")
        if len(positions) == 0 or positions[0] < 0:
            return None
        return int(max(0, len(index) - 1 - positions[0]))
    position = int(index.searchsorted(event_timestamp, side="right")) - 1
    if position < 0:
        return None
    return int(max(0, len(index) - 1 - position))


def _nearest_level(
    levels: list[dict[str, Any]],
    close_price: float,
    *,
    side: str | None = None,
) -> dict[str, Any] | None:
    filtered = levels
    if side == "long":
        filtered = [level for level in levels if str(level.get("type", "")).lower() in _LONG_LEVEL_TYPES]
    elif side == "short":
        filtered = [level for level in levels if str(level.get("type", "")).lower() in _SHORT_LEVEL_TYPES]
    if not filtered:
        filtered = levels
    if not filtered:
        return None
    return min(filtered, key=lambda level: abs(float(level["price"]) - close_price))


def _opposing_target(
    levels: list[dict[str, Any]],
    *,
    side: str,
    close_price: float,
) -> float | None:
    candidates: list[float] = []
    for level in levels:
        level_price = float(level.get("price", 0.0))
        level_type = str(level.get("type", "")).lower()
        if side == "long" and level_price > close_price and level_type in _SHORT_LEVEL_TYPES:
            candidates.append(level_price)
        if side == "short" and level_price < close_price and level_type in _LONG_LEVEL_TYPES:
            candidates.append(level_price)
    if not candidates:
        return None
    return min(candidates) if side == "long" else max(candidates)


def _latest_actionable_liquidity_event(
    liquidity_events: list[dict[str, Any]],
    *,
    current_time: pd.Timestamp,
    history_index: pd.DatetimeIndex,
    lookback_bars: int,
) -> dict[str, Any] | None:
    best: tuple[int, float, dict[str, Any]] | None = None
    for event in liquidity_events:
        age_bars = _bars_since(event.get("timestamp"), current_time, history_index)
        if age_bars is None or age_bars > lookback_bars:
            continue
        confidence = float(event.get("confidence", 0.0))
        rank = (age_bars, -confidence)
        if best is None or rank < (best[0], -best[1]):
            best = (age_bars, confidence, event)
    return best[2] if best is not None else None


def detect_setup_candidate(
    history: pd.DataFrame,
    *,
    levels: list[dict[str, Any]],
    liquidity_events: list[dict[str, Any]],
    htf_context: dict[str, Any],
    minimum_rr: float,
    recent_liquidity_bars: int = 16,
    max_level_distance_atr: float = 1.25,
    min_level_strength: float = 1.0,
    target_buffer_atr: float = 0.2,
    fallback_without_liquidity: bool = True,
) -> dict[str, Any] | None:
    if len(history) < 20:
        return None

    row = history.iloc[-1]
    prior = history.iloc[-2]
    current_time = pd.Timestamp(history.index[-1])
    history_index = pd.DatetimeIndex(history.index)
    close_price = float(row["close"])
    atr_value = float(row.get("atr", 0.0))
    if atr_value <= 0:
        return None

    recent_event = _latest_actionable_liquidity_event(
        liquidity_events,
        current_time=current_time,
        history_index=history_index,
        lookback_bars=recent_liquidity_bars,
    )

    side: str | None = None
    pattern = "none"
    liquidity_support = 0.0
    liquidity_event_age_bars: int | None = None

    if recent_event is not None:
        event_type = str(recent_event.get("type", ""))
        implication = str(recent_event.get("side_implication", ""))
        liquidity_support = float(recent_event.get("confidence", 0.0))
        liquidity_event_age_bars = _bars_since(recent_event.get("timestamp"), current_time, history_index)
        if implication in {"long", "bullish_if_swept"} and event_type in {"sweep_low", "failed_breakdown", "retest_after_breakout", "equal_lows"}:
            side = "long"
            pattern = event_type
        elif implication in {"short", "bearish_if_swept"} and event_type in {"sweep_high", "failed_breakout", "retest_after_breakdown", "equal_highs"}:
            side = "short"
            pattern = event_type

    ema_fast = float(row.get("ema_20", 0.0))
    ema_mid = float(row.get("ema_50", 0.0))
    ema_slow = float(row.get("ema_200", 0.0))

    if side is None and fallback_without_liquidity:
        bullish_stack = close_price >= ema_fast >= ema_mid and ema_mid >= ema_slow
        bearish_stack = close_price <= ema_fast <= ema_mid and ema_mid <= ema_slow
        if close_price > float(prior["close"]) and bullish_stack:
            side = "long"
            pattern = "structure_reclaim"
        elif close_price < float(prior["close"]) and bearish_stack:
            side = "short"
            pattern = "structure_breakdown"

    if side is None:
        return None

    level = _nearest_level(levels, close_price, side=side)
    if level is None:
        return None

    level_strength = float(level.get("strength", 0.0))
    if level_strength < min_level_strength:
        return None

    level_price = float(level["price"])
    level_distance_atr = abs(close_price - level_price) / max(atr_value, 1e-8)
    if level_distance_atr > max_level_distance_atr:
        return None

    if side == "long":
        stop_price = min(level_price, float(history.tail(8)["low"].min()))
    else:
        stop_price = max(level_price, float(history.tail(8)["high"].max()))

    risk = max(abs(close_price - stop_price), atr_value * 0.35)
    target_price = _opposing_target(levels, side=side, close_price=close_price)
    if target_price is None:
        if side == "long":
            target_price = float(history.tail(96)["high"].max())
        else:
            target_price = float(history.tail(96)["low"].min())
    if side == "long":
        reward = max(target_price - close_price - (atr_value * target_buffer_atr), risk)
    else:
        reward = max(close_price - target_price - (atr_value * target_buffer_atr), risk)
    rr = reward / max(risk, 1e-8)
    if rr < minimum_rr:
        return None

    return {
        "timestamp": current_time.isoformat(),
        "side": side,
        "close_price": close_price,
        "pattern": pattern,
        "level_type": level["type"],
        "level_price": level_price,
        "level_strength": level_strength,
        "level_distance_atr": round(level_distance_atr, 4),
        "ema_fast": ema_fast,
        "ema_mid": ema_mid,
        "ema_slow": ema_slow,
        "liquidity_support": liquidity_support,
        "liquidity_event_type": recent_event.get("type") if recent_event else None,
        "liquidity_event_age_bars": liquidity_event_age_bars,
        "htf_bias": htf_context.get("bias", "neutral"),
        "htf_score": float(htf_context.get("score", 0.0)),
        "atr": atr_value,
        "risk_reward": rr,
        "stop_price": stop_price,
        "target_price": target_price,
    }
