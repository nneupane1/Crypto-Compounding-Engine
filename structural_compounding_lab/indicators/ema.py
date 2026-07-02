from __future__ import annotations

import pandas as pd

def compute_ema_stack(frame: pd.DataFrame, *, fast: int = 20, mid: int = 50, slow: int = 200) -> pd.DataFrame:
    result = frame.copy()
    result[f"ema_{fast}"] = result["close"].ewm(span=fast, adjust=False).mean()
    result[f"ema_{mid}"] = result["close"].ewm(span=mid, adjust=False).mean()
    result[f"ema_{slow}"] = result["close"].ewm(span=slow, adjust=False).mean()
    result["ema_fast_slope"] = result[f"ema_{fast}"].diff()
    result["ema_mid_slope"] = result[f"ema_{mid}"].diff()
    result["ema_slow_slope"] = result[f"ema_{slow}"].diff()
    return result
