from __future__ import annotations

from typing import Any


def build_support_resistance_context(
    *,
    candidate: dict[str, Any],
    levels: list[dict[str, Any]],
) -> dict[str, Any]:
    side = str(candidate.get("side", "")).lower()
    close_price = float(candidate.get("close_price", 0.0))
    target_price = float(candidate.get("target_price", close_price))
    level_price = float(candidate.get("level_price", close_price))
    level_strength = float(candidate.get("level_strength", 0.0))
    headroom = abs(target_price - close_price)
    blocking_distance = 0.0
    for level in levels:
        price = float(level.get("price", 0.0))
        if side == "long" and price > close_price:
            distance = price - close_price
            if blocking_distance == 0.0 or distance < blocking_distance:
                blocking_distance = distance
        if side == "short" and price < close_price:
            distance = close_price - price
            if blocking_distance == 0.0 or distance < blocking_distance:
                blocking_distance = distance
    return {
        "primary_level_type": candidate.get("level_type"),
        "primary_level_price": level_price,
        "primary_level_strength": level_strength,
        "headroom_to_target": headroom,
        "blocking_resistance_distance": blocking_distance if side == "long" else None,
        "blocking_support_distance": blocking_distance if side == "short" else None,
        "breakout_retest_context": str(candidate.get("pattern", "")).startswith("retest_after_break"),
    }
