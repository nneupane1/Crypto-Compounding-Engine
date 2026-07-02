from __future__ import annotations

from typing import Any


def classify_trade_personality(story: dict[str, Any]) -> dict[str, Any]:
    return {
        "label": story.get("personality", {}).get("personality_label", "NO_PERSONALITY_EDGE"),
        "confidence": float(story.get("personality", {}).get("personality_confidence", 0.0) or 0.0),
        "warnings": list(story.get("personality", {}).get("warning_conditions", [])),
        "supporting_conditions": list(story.get("personality", {}).get("supporting_conditions", [])),
    }
