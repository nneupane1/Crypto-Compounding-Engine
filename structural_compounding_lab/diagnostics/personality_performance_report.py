from __future__ import annotations

from typing import Any


def build_personality_performance_report(trades: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for trade in trades:
        personality = str(trade.get("personality_label") or "NO_PERSONALITY_EDGE")
        bucket = grouped.setdefault(
            personality,
            {"count": 0, "wins": 0, "total_pnl": 0.0, "total_r": 0.0, "holding_bars": 0, "add_on_count": 0},
        )
        pnl = float(trade.get("pnl", 0.0) or 0.0)
        r_multiple = float(trade.get("r_multiple", 0.0) or 0.0)
        bucket["count"] += 1
        bucket["wins"] += 1 if pnl > 0 else 0
        bucket["total_pnl"] += pnl
        bucket["total_r"] += r_multiple
        bucket["holding_bars"] += int(trade.get("holding_bars", 0) or 0)
        bucket["add_on_count"] += int(trade.get("add_on_count", 0) or 0)
    report: dict[str, Any] = {}
    for personality, bucket in grouped.items():
        count = max(bucket["count"], 1)
        report[personality] = {
            "count": bucket["count"],
            "win_rate": bucket["wins"] / count,
            "total_pnl": bucket["total_pnl"],
            "avg_r": bucket["total_r"] / count,
            "median_r_proxy": bucket["total_r"] / count,
            "profit_factor_proxy": float(bucket["wins"]) / float(max(1, bucket["count"] - bucket["wins"])),
            "average_holding_time": bucket["holding_bars"] / count,
            "add_on_candidate_frequency": bucket["add_on_count"] / count,
        }
    return report
