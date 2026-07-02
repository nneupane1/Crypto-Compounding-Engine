from __future__ import annotations

from typing import Any


def build_indicator_confluence_report(setup_rows: list[dict[str, Any]]) -> dict[str, Any]:
    report: dict[str, Any] = {}
    for row in setup_rows:
        key = "|".join(
            [
                str(row.get("personality_label") or "NO_PERSONALITY_EDGE"),
                "macd_confirm" if row.get("macd_confirmation_flag") else "macd_warn" if row.get("macd_warning_flag") else "macd_neutral",
                "bb_compression" if row.get("bb_compression") else "bb_expansion" if row.get("bb_expansion") else "bb_neutral",
                str(row.get("side") or "flat"),
            ]
        )
        bucket = report.setdefault(key, {"count": 0, "avg_score": 0.0, "avg_rr": 0.0})
        bucket["count"] += 1
        bucket["avg_score"] += float(row.get("total_score", row.get("score", 0.0)) or 0.0)
        bucket["avg_rr"] += float(row.get("risk_reward", 0.0) or 0.0)
    for key, bucket in report.items():
        count = max(bucket["count"], 1)
        bucket["avg_score"] = bucket["avg_score"] / count
        bucket["avg_rr"] = bucket["avg_rr"] / count
    return report
