from __future__ import annotations

from statistics import mean
from typing import Any


def build_entry_quality_report(original_vs_refined_rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not original_vs_refined_rows:
        return {"count": 0, "average_improved_R_delta": 0.0, "average_stop_reduction_pct": 0.0}
    r_deltas = [float(row.get("improved_R_delta", 0.0) or 0.0) for row in original_vs_refined_rows]
    stop_reduction = []
    for row in original_vs_refined_rows:
        original_risk = float(row.get("original_risk_distance", 0.0) or 0.0)
        refined_risk = float(row.get("refined_risk_distance", 0.0) or 0.0)
        if original_risk > 0:
            stop_reduction.append((original_risk - refined_risk) / original_risk)
    return {
        "count": len(original_vs_refined_rows),
        "average_improved_R_delta": mean(r_deltas) if r_deltas else 0.0,
        "average_stop_reduction_pct": mean(stop_reduction) if stop_reduction else 0.0,
        "pullback_detected_rate": sum(1 for row in original_vs_refined_rows if not row.get("missed_due_to_no_pullback")) / max(len(original_vs_refined_rows), 1),
    }
