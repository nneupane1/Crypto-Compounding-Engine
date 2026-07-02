from __future__ import annotations

from typing import Any


def build_htf_structure_context(htf_context: dict[str, Any], *, side: str | None = None) -> dict[str, Any]:
    bias = str(htf_context.get("bias", "neutral")).lower()
    score = float(htf_context.get("score", 0.0) or 0.0)
    aligned = (side == "long" and bias == "bullish") or (side == "short" and bias == "bearish")
    return {
        "htf_bias": bias,
        "htf_score": score,
        "htf_votes": list(htf_context.get("votes", [])),
        "htf_aligned": aligned,
        "htf_supportive": aligned or bias == "neutral",
    }
