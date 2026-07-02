from __future__ import annotations

from typing import Any


_FEATURE_FLAGS: dict[str, Any] = {
    "momentum_personality_layer": {
        "enabled": True,
        "authoritative": False,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "description": "Soft evidence layer using MACD/Bollinger to classify setup personality without blocking core setup logic.",
    },
    "intelligent_pullback_accumulation": {
        "enabled": True,
        "authoritative": False,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "description": "Research-only structural pullback scoring and original-vs-pullback entry comparison.",
    },
    "structural_pullback_compounding_entry": {
        "enabled": True,
        "authoritative": False,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "description": "Compounding-readiness study for improved pullback geometry and add-on base quality.",
    },
}


def load_feature_flags() -> dict[str, Any]:
    return {key: dict(value) for key, value in _FEATURE_FLAGS.items()}
