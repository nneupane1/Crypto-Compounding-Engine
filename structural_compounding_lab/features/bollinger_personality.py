from __future__ import annotations

from typing import Any

import pandas as pd


def extract_bollinger_features(history: pd.DataFrame | None, row: dict[str, Any] | Any | None = None) -> dict[str, Any]:
    if history is None or history.empty:
        return {
            "bb_state": "missing",
            "bb_confirmation_flag": False,
            "bb_warning_flag": False,
            "missing_data_fields": ["bollinger_history"],
        }
    working_row = row if row is not None else history.iloc[-1]
    close = float(getattr(working_row, "get", lambda key, default=None: default)("close", 0.0) or 0.0)
    upper = float(getattr(working_row, "get", lambda key, default=None: default)("bb_upper", 0.0) or 0.0)
    lower = float(getattr(working_row, "get", lambda key, default=None: default)("bb_lower", 0.0) or 0.0)
    basis = float(getattr(working_row, "get", lambda key, default=None: default)("bb_basis", 0.0) or 0.0)
    width = float(getattr(working_row, "get", lambda key, default=None: default)("bb_width", 0.0) or 0.0)
    width_slope = float(getattr(working_row, "get", lambda key, default=None: default)("bb_width_slope", 0.0) or 0.0)
    width_series = pd.to_numeric(history.get("bb_width"), errors="coerce").dropna()
    width_percentile = float((width_series <= width).mean()) if not width_series.empty else 0.0
    outside_upper = upper > 0 and close > upper
    outside_lower = lower > 0 and close < lower
    compression = width_percentile <= 0.25
    expansion = width_slope > 0 and width_percentile >= 0.55
    return {
        "bb_state": "expansion" if expansion else "compression" if compression else "neutral",
        "bb_basis": basis,
        "bb_upper": upper,
        "bb_lower": lower,
        "bb_width": width,
        "bb_width_percentile": width_percentile,
        "bb_compression": compression,
        "bb_expansion": expansion,
        "bb_price_outside_upper": outside_upper,
        "bb_price_outside_lower": outside_lower,
        "bb_mean_reversion_warning": outside_upper or outside_lower,
        "bb_confirmation_flag": expansion and not (outside_upper or outside_lower),
        "bb_warning_flag": outside_upper or outside_lower,
        "missing_data_fields": [],
    }
