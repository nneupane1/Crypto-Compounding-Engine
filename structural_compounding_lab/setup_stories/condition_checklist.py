from __future__ import annotations

from typing import Any


def build_condition_checklist(story: dict[str, Any]) -> list[dict[str, Any]]:
    conditions = [
        ("htf_aligned", bool(story.get("htf", {}).get("htf_aligned"))),
        ("ema_aligned", bool(story.get("ema_context", {}).get("ema_aligned"))),
        ("supportive_level", float(story.get("support_resistance", {}).get("primary_level_strength", 0.0)) >= 1.0),
        ("volume_not_distributing", not bool(story.get("volume_context", {}).get("distribution_warning"))),
        ("vwap_supportive", bool(story.get("vwap_context", {}).get("vwap_supportive"))),
        ("pullback_not_broken", str(story.get("pullback", {}).get("pullback_type", "")).upper() != "STRUCTURE_BREAK_DIP"),
        ("positive_compounding_readiness", float(story.get("compounding", {}).get("compounding_readiness_score", 0.0)) >= 0.45),
    ]
    return [{"label": label, "passed": passed} for label, passed in conditions]
