from __future__ import annotations

from typing import Any


def summarize_robustness_checks(summary: dict[str, Any]) -> dict[str, Any]:
    metrics = summary.get("metrics", {}) if isinstance(summary.get("metrics"), dict) else {}
    max_drawdown = float(metrics.get("max_drawdown_pct", 0.0) or 0.0)
    profit_factor = float(metrics.get("profit_factor", 0.0) or 0.0)
    avg_r = float(metrics.get("avg_r", 0.0) or 0.0)
    return {
        "profit_factor_above_one": profit_factor > 1.0,
        "avg_r_positive": avg_r > 0.0,
        "max_drawdown_under_35pct": max_drawdown <= 0.35,
        "robustness_warning": max_drawdown > 0.35 or profit_factor <= 1.0,
    }
