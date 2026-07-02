from __future__ import annotations

import pandas as pd


def compute_bollinger_bands(
    frame: pd.DataFrame,
    *,
    period: int = 20,
    stddev: float = 2.0,
) -> pd.DataFrame:
    result = frame.copy()
    close_source = result.get("close")
    if close_source is None:
        return result
    close = pd.to_numeric(close_source, errors="coerce")
    basis = close.rolling(period).mean()
    sigma = close.rolling(period).std(ddof=0)
    upper = basis + (sigma * stddev)
    lower = basis - (sigma * stddev)
    width = (upper - lower) / basis.replace(0, pd.NA)
    result["bb_basis"] = basis
    result["bb_upper"] = upper
    result["bb_lower"] = lower
    result["bb_width"] = width
    result["bb_width_slope"] = width.diff()
    return result
