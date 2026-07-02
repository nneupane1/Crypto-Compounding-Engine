from __future__ import annotations

import pandas as pd

def compute_session_vwap(frame: pd.DataFrame) -> pd.Series:
    session_key = frame.index.normalize()
    typical_price = (frame["high"] + frame["low"] + frame["close"]) / 3.0
    turnover = typical_price * frame["volume"]
    cumulative_turnover = turnover.groupby(session_key).cumsum()
    cumulative_volume = frame["volume"].groupby(session_key).cumsum()
    return cumulative_turnover / (cumulative_volume + 1e-9)
