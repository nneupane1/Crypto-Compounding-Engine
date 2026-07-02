from __future__ import annotations

from typing import Any

import pandas as pd


def build_original_vs_refined_entry_rows(
    trades: list[dict[str, Any]],
    setup_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    setup_frame = pd.DataFrame(setup_rows)
    if not setup_frame.empty and "timestamp" in setup_frame.columns:
        setup_frame["timestamp"] = pd.to_datetime(setup_frame["timestamp"], utc=True, errors="coerce")
    for trade in trades:
        entry_time = pd.Timestamp(trade.get("entry_time"))
        entry_ts = entry_time.tz_localize("UTC") if entry_time.tzinfo is None else entry_time.tz_convert("UTC")
        symbol = str(trade.get("symbol", "")).upper()
        side = str(trade.get("side", "")).lower()
        candidates = setup_frame
        if not setup_frame.empty:
            candidates = setup_frame[
                (setup_frame["symbol"].astype(str).str.upper() == symbol)
                & (setup_frame["side"].astype(str).str.lower() == side)
                & (setup_frame["timestamp"] <= entry_ts)
            ]
        setup_row = candidates.iloc[-1].to_dict() if not candidates.empty else {}
        original_entry = float(trade.get("entry_price", 0.0) or 0.0)
        original_stop = float(trade.get("initial_stop", trade.get("stop_price", 0.0)) or 0.0)
        refined_entry = float(setup_row.get("pullback_entry_price", setup_row.get("entry_candidate_price", original_entry)) or original_entry)
        refined_stop = float(setup_row.get("pullback_stop_price", setup_row.get("pullback_stop", original_stop)) or original_stop)
        target_price = float(setup_row.get("target_price", trade.get("exit_price", original_entry)) or trade.get("exit_price", original_entry))
        original_risk = abs(original_entry - original_stop)
        refined_risk = abs(refined_entry - refined_stop)
        if side == "long":
            original_r = ((target_price - original_entry) / original_risk) if original_risk > 0 else 0.0
            refined_r = ((target_price - refined_entry) / refined_risk) if refined_risk > 0 else original_r
        else:
            original_r = ((original_entry - target_price) / original_risk) if original_risk > 0 else 0.0
            refined_r = ((refined_entry - target_price) / refined_risk) if refined_risk > 0 else original_r
        rows.append(
            {
                "trade_id": trade.get("trade_id"),
                "symbol": symbol,
                "side": side,
                "original_entry_time": trade.get("entry_time"),
                "original_entry_price": original_entry,
                "original_stop": original_stop,
                "refined_entry_time": setup_row.get("pullback_entry_time", setup_row.get("timestamp")),
                "refined_entry_price": refined_entry,
                "refined_stop": refined_stop,
                "original_risk_distance": original_risk,
                "refined_risk_distance": refined_risk,
                "original_R_to_same_target": original_r,
                "refined_R_to_same_target": refined_r,
                "improved_R_delta": refined_r - original_r,
                "worsened_R_delta": original_r - refined_r if refined_r < original_r else 0.0,
                "missed_due_to_no_pullback": not bool(setup_row.get("micro_pullback_detected", False)),
                "pullback_type": setup_row.get("pullback_type"),
                "notes": setup_row.get("pullback_explanation", setup_row.get("explanation", "")),
            }
        )
    return rows
