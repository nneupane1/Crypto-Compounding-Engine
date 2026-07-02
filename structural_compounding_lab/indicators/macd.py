from __future__ import annotations

import pandas as pd


def compute_macd(
    frame: pd.DataFrame,
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    result = frame.copy()
    close_source = result.get("close")
    if close_source is None:
        return result
    close = pd.to_numeric(close_source, errors="coerce")
    ema_fast = close.ewm(span=fast, adjust=False).mean()
    ema_slow = close.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line
    result["macd_line"] = macd_line
    result["macd_signal"] = signal_line
    result["macd_histogram"] = histogram
    result["macd_histogram_slope"] = histogram.diff()
    result["macd_acceleration"] = result["macd_histogram_slope"].diff()
    return result
