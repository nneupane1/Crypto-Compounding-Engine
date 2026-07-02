from __future__ import annotations

from typing import Any

import pandas as pd


def build_volume_context(history: pd.DataFrame, row: dict[str, Any] | Any) -> dict[str, Any]:
    volume = float(getattr(row, "get", lambda key, default=None: default)("volume", 0.0) or 0.0)
    if history.empty or "volume" not in history.columns:
        return {
            "volume": volume,
            "volume_baseline": 0.0,
            "volume_expansion_ratio": 0.0,
            "volume_expansion": False,
            "volume_dryup": False,
            "distribution_warning": False,
        }
    baseline = float(pd.to_numeric(history["volume"], errors="coerce").tail(20).mean() or 0.0)
    ratio = (volume / baseline) if baseline > 0 else 0.0
    return {
        "volume": volume,
        "volume_baseline": baseline,
        "volume_expansion_ratio": ratio,
        "volume_expansion": ratio >= 1.2,
        "volume_dryup": ratio <= 0.8 if baseline > 0 else False,
        "distribution_warning": ratio >= 1.6 and float(getattr(row, "get", lambda key, default=None: default)("close", 0.0)) <= float(getattr(row, "get", lambda key, default=None: default)("open", 0.0)),
    }
