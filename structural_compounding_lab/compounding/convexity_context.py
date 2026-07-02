from __future__ import annotations


def derive_convexity_context(*, risk_multiplier: float, convexity_label: str | None) -> dict[str, object]:
    return {
        "risk_multiplier": float(risk_multiplier),
        "convexity_label": convexity_label or "normal",
        "convexity_aggressive": float(risk_multiplier) > 1.0,
    }
