from __future__ import annotations

from typing import Any

import pandas as pd


def extract_macd_features(history: pd.DataFrame | None, row: dict[str, Any] | Any | None = None) -> dict[str, Any]:
    if history is None or history.empty:
        return {
            "macd_state": "missing",
            "macd_confirmation_flag": False,
            "macd_warning_flag": False,
            "macd_histogram_slope": None,
            "macd_acceleration": None,
            "missing_data_fields": ["macd_history"],
        }
    working_row = row if row is not None else history.iloc[-1]
    macd_line = float(getattr(working_row, "get", lambda key, default=None: default)("macd_line", 0.0) or 0.0)
    signal_line = float(getattr(working_row, "get", lambda key, default=None: default)("macd_signal", 0.0) or 0.0)
    histogram = float(getattr(working_row, "get", lambda key, default=None: default)("macd_histogram", 0.0) or 0.0)
    slope = float(getattr(working_row, "get", lambda key, default=None: default)("macd_histogram_slope", 0.0) or 0.0)
    acceleration = float(getattr(working_row, "get", lambda key, default=None: default)("macd_acceleration", 0.0) or 0.0)
    state = "bullish" if macd_line >= signal_line and histogram >= 0 else "bearish"
    divergence_candidate = bool(
        len(history) >= 5
        and pd.to_numeric(history["close"], errors="coerce").tail(5).iloc[-1] > pd.to_numeric(history["close"], errors="coerce").tail(5).iloc[0]
        and histogram < 0
    )
    return {
        "macd_state": state,
        "macd_line": macd_line,
        "macd_signal": signal_line,
        "macd_histogram": histogram,
        "macd_histogram_slope": slope,
        "macd_acceleration": acceleration,
        "macd_confirmation_flag": histogram >= 0 and slope >= 0,
        "macd_warning_flag": histogram < 0 or slope < 0,
        "macd_divergence_candidate": divergence_candidate,
        "missing_data_fields": [],
    }
