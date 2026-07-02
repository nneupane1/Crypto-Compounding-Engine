from __future__ import annotations

import pandas as pd

def compute_atr(frame: pd.DataFrame, *, period: int = 14) -> pd.Series:
    previous_close = frame["close"].shift(1)
    true_range = (
        frame[["high", "low"]]
        .assign(
            intrabar=frame["high"] - frame["low"],
            high_gap=(frame["high"] - previous_close).abs(),
            low_gap=(frame["low"] - previous_close).abs(),
        )[["intrabar", "high_gap", "low_gap"]]
        .max(axis=1)
    )
    return true_range.rolling(period).mean()
