from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

import pandas as pd


_WINDOWS = ("smoke", "diagnostic_fast", "holdout_recent_preview")
_ALLOWED_CLASSIFICATIONS = (
    "reject",
    "continue_research",
    "needs_detector_tightening",
    "eligible_for_second_fast_review",
)
_PULLBACK_TYPE_MAP = {
    "NO_PULLBACK_SIGNAL": "NO_VALID_PULLBACK",
}


@dataclass(frozen=True)
class EvidenceRefinementConfig:
    source_review_root: Path
    output_root: Path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _safe_mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _safe_median(values: list[float]) -> float | None:
    return median(values) if values else None


def _quantile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    fraction = pos - lo
    return ordered[lo] * (1 - fraction) + ordered[hi] * fraction


def _trimmed_mean(values: list[float], trim_fraction: float = 0.1) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    cut = int(len(ordered) * trim_fraction)
    if (len(ordered) - 2 * cut) <= 0:
        return mean(ordered)
    return mean(ordered[cut : len(ordered) - cut])


def _winsorized_mean(values: list[float], winsor_fraction: float = 0.1) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    lower = _quantile(ordered, winsor_fraction)
    upper = _quantile(ordered, 1 - winsor_fraction)
    assert lower is not None and upper is not None
    clipped = [min(max(v, lower), upper) for v in ordered]
    return mean(clipped)


def _infer_tick_size(source_csv: Path, sample_rows: int = 256) -> float:
    max_decimals = 0
    with source_csv.open("r", encoding="utf-8") as handle:
        next(handle, None)
        for idx, line in enumerate(handle):
            if idx >= sample_rows:
                break
            parts = line.strip().split(",")
            for value in parts[1:5]:
                if "." in value:
                    max_decimals = max(max_decimals, len(value.split(".")[1]))
    return 10 ** (-max_decimals) if max_decimals > 0 else 1.0


def _load_hourly_market_context(source_csv: Path, start: pd.Timestamp, end: pd.Timestamp, atr_period: int = 14) -> pd.DataFrame:
    frame = pd.read_csv(source_csv, parse_dates=["timestamp"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp"])
    start_bound = start - pd.Timedelta(days=7)
    end_bound = end + pd.Timedelta(days=2)
    frame = frame[(frame["timestamp"] >= start_bound) & (frame["timestamp"] <= end_bound)].copy()
    frame = frame.set_index("timestamp").sort_index()
    hourly = frame.resample("1h").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    ).dropna(subset=["open", "high", "low", "close"])
    prev_close = hourly["close"].shift(1)
    true_range = pd.concat(
        [
            hourly["high"] - hourly["low"],
            (hourly["high"] - prev_close).abs(),
            (hourly["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    hourly["atr"] = true_range.rolling(atr_period, min_periods=1).mean()
    hourly["bar_range"] = hourly["high"] - hourly["low"]
    hourly["upper_wick"] = hourly["high"] - hourly[["open", "close"]].max(axis=1)
    hourly["lower_wick"] = hourly[["open", "close"]].min(axis=1) - hourly["low"]
    hourly["local_wick_noise"] = hourly[["upper_wick", "lower_wick"]].max(axis=1).rolling(6, min_periods=1).mean()
    hourly["recent_candle_noise"] = hourly["bar_range"].rolling(6, min_periods=1).mean()
    return hourly


def _lookup_market_context(hourly: pd.DataFrame, timestamp: pd.Timestamp) -> dict[str, float]:
    if hourly.empty:
        return {
            "atr": 0.0,
            "recent_candle_noise": 0.0,
            "local_wick_noise": 0.0,
            "close": 0.0,
        }
    idx = hourly.index.asof(timestamp)
    if pd.isna(idx):
        row = hourly.iloc[0]
    else:
        row = hourly.loc[idx]
    return {
        "atr": float(row.get("atr", 0.0) or 0.0),
        "recent_candle_noise": float(row.get("recent_candle_noise", 0.0) or 0.0),
        "local_wick_noise": float(row.get("local_wick_noise", 0.0) or 0.0),
        "close": float(row.get("close", 0.0) or 0.0),
    }


def _load_window_rows(window_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    with (window_root / "trades.csv").open("r", encoding="utf-8", newline="") as handle:
        trades = list(csv.DictReader(handle))
    with (window_root / "setup_log.csv").open("r", encoding="utf-8", newline="") as handle:
        setups = list(csv.DictReader(handle))
    with (window_root / "diagnostics" / "original_vs_pullback_entry.csv").open("r", encoding="utf-8", newline="") as handle:
        entries = list(csv.DictReader(handle))
    return trades, setups, entries


def _join_window_data(
    *,
    window: str,
    trades: list[dict[str, Any]],
    setups: list[dict[str, Any]],
    entries: list[dict[str, Any]],
    hourly_context: pd.DataFrame,
    execution_model: dict[str, Any],
    tick_size: float,
) -> list[dict[str, Any]]:
    trade_by_id = {str(row.get("trade_id")): row for row in trades}
    setup_by_signature = {
        (
            str(row.get("symbol", "")).upper(),
            str(row.get("side", "")).lower(),
            str(row.get("timestamp")),
        ): row
        for row in setups
    }
    atr_floor_fraction = 0.35
    unrealistic_atr_fraction = 0.20
    normal_scenario = execution_model["scenarios"]["normal_cost"]
    rows: list[dict[str, Any]] = []

    for entry in entries:
        trade_id = str(entry.get("trade_id"))
        trade = trade_by_id.get(trade_id, {})
        signature = (
            str(entry.get("symbol", "")).upper(),
            str(entry.get("side", "")).lower(),
            str(entry.get("original_entry_time")),
        )
        setup = setup_by_signature.get(signature, {})

        side = str(entry.get("side", "")).lower()
        original_entry = float(entry.get("original_entry_price", 0.0) or 0.0)
        refined_entry = float(entry.get("refined_entry_price", original_entry) or original_entry)
        original_stop = float(entry.get("original_stop", 0.0) or 0.0)
        refined_stop = float(entry.get("refined_stop", original_stop) or original_stop)
        original_risk = abs(original_entry - original_stop)
        refined_risk = abs(refined_entry - refined_stop)
        original_gross_r = float(entry.get("original_R_to_same_target", 0.0) or 0.0)
        refined_gross_r = float(entry.get("refined_R_to_same_target", 0.0) or 0.0)
        improved_r_delta = float(entry.get("improved_R_delta", 0.0) or 0.0)
        timestamp = pd.Timestamp(entry.get("original_entry_time"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.tz_localize("UTC")
        else:
            timestamp = timestamp.tz_convert("UTC")
        market = _lookup_market_context(hourly_context, timestamp)
        atr_value = market["atr"]
        recent_noise = market["recent_candle_noise"]
        wick_noise = market["local_wick_noise"]
        close_price = market["close"] or original_entry or refined_entry

        target_abs_move = original_gross_r * original_risk
        target_price = original_entry + target_abs_move if side == "long" else original_entry - target_abs_move
        refined_reward_abs = abs(target_price - refined_entry)
        original_reward_abs = abs(target_price - original_entry)

        pullback_type = str(entry.get("pullback_type") or setup.get("pullback_type") or "NO_VALID_PULLBACK")
        pullback_type = _PULLBACK_TYPE_MAP.get(pullback_type, pullback_type)
        pullback_detected = str(setup.get("micro_pullback_detected", "")).lower() == "true"
        pullback_depth_atr = float(setup.get("pullback_depth_atr", 0.0) or 0.0)
        pullback_quality_score = float(setup.get("pullback_quality_score", 0.0) or 0.0)

        def cost_amount(entry_price: float, reward_abs: float, scenario: dict[str, float], include_slippage: bool = True) -> float:
            exit_price = entry_price + reward_abs if side == "long" else entry_price - reward_abs
            notional = abs((entry_price + exit_price) * 0.5)
            fee_component = notional * ((scenario["fee_bps"] * 2.0) / 10000.0)
            if not include_slippage:
                return fee_component
            friction_component = notional * ((scenario["spread_bps"] + scenario["slippage_bps"]) / 10000.0)
            return fee_component + friction_component

        original_net_r_after_fees = ((original_reward_abs - cost_amount(original_entry, original_reward_abs, normal_scenario, include_slippage=False)) / original_risk) if original_risk > 0 else 0.0
        refined_net_r_after_fees = ((refined_reward_abs - cost_amount(refined_entry, refined_reward_abs, normal_scenario, include_slippage=False)) / refined_risk) if refined_risk > 0 else 0.0
        refined_net_r_after_fees_slippage = ((refined_reward_abs - cost_amount(refined_entry, refined_reward_abs, normal_scenario, include_slippage=True)) / refined_risk) if refined_risk > 0 else 0.0
        original_net_r_after_fees_slippage = ((original_reward_abs - cost_amount(original_entry, original_reward_abs, normal_scenario, include_slippage=True)) / original_risk) if original_risk > 0 else 0.0

        scenario_survival: dict[str, bool] = {}
        scenario_net_r: dict[str, float] = {}
        expected_cost_r = 0.0
        for scenario_name, scenario in execution_model["scenarios"].items():
            refined_cost = cost_amount(refined_entry, refined_reward_abs, scenario, include_slippage=True)
            original_cost = cost_amount(original_entry, original_reward_abs, scenario, include_slippage=True)
            refined_net_r = ((refined_reward_abs - refined_cost) / refined_risk) if refined_risk > 0 else 0.0
            original_net_r = ((original_reward_abs - original_cost) / original_risk) if original_risk > 0 else 0.0
            scenario_net_r[scenario_name] = refined_net_r
            scenario_survival[scenario_name] = refined_net_r > 0.0 and refined_net_r > original_net_r
            if scenario_name == "normal_cost":
                expected_cost_r = (refined_cost / refined_risk) if refined_risk > 0 else 0.0

        refined_stop_atr_fraction = (refined_risk / atr_value) if atr_value > 0 else 0.0
        refined_stop_cost_multiple = (refined_risk / cost_amount(refined_entry, refined_reward_abs, normal_scenario, include_slippage=True)) if refined_reward_abs > 0 else 0.0
        tiny_stop_flag = refined_stop_atr_fraction < atr_floor_fraction or refined_risk <= max(tick_size * 4.0, wick_noise * 0.35)
        unrealistic_stop_flag = refined_stop_atr_fraction < unrealistic_atr_fraction or refined_stop_cost_multiple < 1.5
        noise_stop_flag = refined_risk < max(recent_noise * 0.35, wick_noise * 1.25)
        cost_dominated_stop_flag = expected_cost_r >= 0.35 or refined_stop_cost_multiple < 2.0
        outlier_dominated = improved_r_delta > 100.0 or refined_stop_atr_fraction < 0.15

        if not pullback_detected:
            if pullback_type == "NO_VALID_PULLBACK":
                missed_reason = "missed_due_to_no_pullback"
            elif pullback_type in {"DEEP_VALUE_PULLBACK", "EXHAUSTION_DIP", "STRUCTURE_BREAK_DIP"} or pullback_depth_atr >= 1.8:
                missed_reason = "missed_due_to_pullback_too_deep"
            elif 0.0 < pullback_depth_atr <= 0.30:
                missed_reason = "missed_due_to_pullback_too_shallow"
            else:
                missed_reason = "missed_due_to_late_confirmation"
        else:
            missed_reason = ""

        cost_aware_pullback_candidate = (
            scenario_survival["low_cost"]
            and scenario_survival["normal_cost"]
            and not tiny_stop_flag
            and not unrealistic_stop_flag
            and not noise_stop_flag
            and not cost_dominated_stop_flag
        )
        reasons_not_cost_aware: list[str] = []
        if not scenario_survival["low_cost"]:
            reasons_not_cost_aware.append("fails_low_cost")
        if not scenario_survival["normal_cost"]:
            reasons_not_cost_aware.append("fails_normal_cost")
        if tiny_stop_flag:
            reasons_not_cost_aware.append("tiny_stop")
        if unrealistic_stop_flag:
            reasons_not_cost_aware.append("unrealistic_stop")
        if noise_stop_flag:
            reasons_not_cost_aware.append("noise_stop")
        if cost_dominated_stop_flag:
            reasons_not_cost_aware.append("cost_dominated_stop")

        rows.append(
            {
                "window": window,
                "trade_id": trade_id,
                "symbol": str(entry.get("symbol", "")).upper(),
                "side": side,
                "entry_time": str(entry.get("original_entry_time")),
                "personality_label": str(trade.get("personality_label") or setup.get("personality_label") or "UNKNOWN"),
                "runner_label": str(trade.get("runner_label") or setup.get("runner_label") or "unknown"),
                "moonshot_state": str(trade.get("moonshot_state") or "normal"),
                "pullback_type": pullback_type,
                "pullback_quality_score": pullback_quality_score,
                "pullback_detected": pullback_detected,
                "missed_due_to_waiting": str(entry.get("missed_due_to_no_pullback", "")).lower() == "true",
                "missed_reason": missed_reason,
                "trade_pnl": float(trade.get("pnl", 0.0) or 0.0),
                "trade_r_multiple": float(trade.get("r_multiple", 0.0) or 0.0),
                "exit_reason": str(trade.get("exit_reason") or ""),
                "entry_score": float(trade.get("entry_score", 0.0) or 0.0),
                "original_entry_price": original_entry,
                "original_stop": original_stop,
                "refined_entry_price": refined_entry,
                "refined_stop": refined_stop,
                "target_price_same": target_price,
                "original_risk_distance": original_risk,
                "refined_stop_distance": refined_risk,
                "refined_stop_atr_fraction": refined_stop_atr_fraction,
                "refined_stop_cost_multiple": refined_stop_cost_multiple,
                "atr_value": atr_value,
                "recent_candle_noise": recent_noise,
                "local_wick_noise": wick_noise,
                "tick_size_estimate": tick_size,
                "tiny_stop_flag": tiny_stop_flag,
                "unrealistic_stop_flag": unrealistic_stop_flag,
                "noise_stop_flag": noise_stop_flag,
                "cost_dominated_stop_flag": cost_dominated_stop_flag,
                "original_gross_r": original_gross_r,
                "refined_gross_r": refined_gross_r,
                "original_net_r_after_fees": original_net_r_after_fees,
                "refined_net_r_after_fees": refined_net_r_after_fees,
                "original_net_r_after_fees_slippage": original_net_r_after_fees_slippage,
                "refined_net_r_after_fees_slippage": refined_net_r_after_fees_slippage,
                "cost_drag_in_r": refined_gross_r - refined_net_r_after_fees_slippage,
                "refined_improves_after_costs": refined_net_r_after_fees_slippage > original_net_r_after_fees_slippage,
                "cost_destroys_refined_advantage": improved_r_delta > 0 and refined_net_r_after_fees_slippage <= original_net_r_after_fees_slippage,
                "minimum_required_move_after_costs": cost_amount(refined_entry, refined_reward_abs, normal_scenario, include_slippage=True),
                "net_reward_to_cost_ratio": (refined_reward_abs / cost_amount(refined_entry, refined_reward_abs, normal_scenario, include_slippage=True)) if refined_reward_abs > 0 else 0.0,
                "expected_cost_r": expected_cost_r,
                "survives_low_cost": scenario_survival["low_cost"],
                "survives_normal_cost": scenario_survival["normal_cost"],
                "survives_high_cost": scenario_survival["high_cost"],
                "survives_stress_cost": scenario_survival["stress_cost"],
                "cost_aware_pullback_candidate": cost_aware_pullback_candidate,
                "reason_not_cost_aware": "|".join(reasons_not_cost_aware),
                "tiny_stop_outlier": outlier_dominated,
                "improved_r_delta": improved_r_delta,
                "pullback_depth_atr": pullback_depth_atr,
            }
        )
    return rows


def _build_robust_r_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    deltas = [float(row["improved_r_delta"]) for row in rows]
    tiny_count = sum(1 for row in rows if row["tiny_stop_outlier"])
    capped_values = [min(float(row["improved_r_delta"]), 25.0) for row in rows]
    return {
        "count": len(rows),
        "raw_mean_improved_r_delta": _safe_mean(deltas),
        "median_improved_r_delta": _safe_median(deltas),
        "trimmed_mean_improved_r_delta": _trimmed_mean(deltas, 0.1),
        "winsorized_mean_improved_r_delta": _winsorized_mean(deltas, 0.1),
        "improved_r_delta_p25": _quantile(deltas, 0.25),
        "improved_r_delta_p75": _quantile(deltas, 0.75),
        "max_capped_improved_r_delta": max(capped_values) if capped_values else None,
        "tiny_stop_outlier_count": tiny_count,
        "tiny_stop_outlier_rate": (tiny_count / len(rows)) if rows else None,
        "tiny_stop_dominated_count_gt100r": sum(1 for row in rows if float(row["improved_r_delta"]) > 100.0),
        "promotion_metric_rule": "Raw mean improved_R_delta must not be used as a promotion metric.",
    }


def _build_tiny_stop_outlier_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "tiny_stop_flag_count": sum(1 for row in rows if row["tiny_stop_flag"]),
        "unrealistic_stop_flag_count": sum(1 for row in rows if row["unrealistic_stop_flag"]),
        "noise_stop_flag_count": sum(1 for row in rows if row["noise_stop_flag"]),
        "cost_dominated_stop_flag_count": sum(1 for row in rows if row["cost_dominated_stop_flag"]),
        "tiny_stop_outlier_count": sum(1 for row in rows if row["tiny_stop_outlier"]),
    }
    total = len(rows) or 1
    counts["tiny_stop_flag_rate"] = counts["tiny_stop_flag_count"] / total
    counts["unrealistic_stop_flag_rate"] = counts["unrealistic_stop_flag_count"] / total
    counts["noise_stop_flag_rate"] = counts["noise_stop_flag_count"] / total
    counts["cost_dominated_stop_flag_rate"] = counts["cost_dominated_stop_flag_count"] / total
    counts["tiny_stop_outlier_rate"] = counts["tiny_stop_outlier_count"] / total
    counts["median_refined_stop_atr_fraction"] = _safe_median([float(row["refined_stop_atr_fraction"]) for row in rows])
    counts["median_refined_stop_cost_multiple"] = _safe_median([float(row["refined_stop_cost_multiple"]) for row in rows])
    return counts


def _build_missed_winner_penalty_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    missed_rows = [row for row in rows if row["missed_due_to_waiting"]]
    winner_rows = [row for row in missed_rows if float(row["trade_r_multiple"]) > 0.0]
    reasons = Counter(row["missed_reason"] for row in missed_rows if row["missed_reason"])
    personalities = Counter(row["personality_label"] for row in winner_rows)
    return {
        "missed_trade_count": len(missed_rows),
        "missed_trade_rate": (len(missed_rows) / len(rows)) if rows else None,
        "missed_winner_count": len(winner_rows),
        "missed_winner_rate": (len(winner_rows) / len(rows)) if rows else None,
        "average_r_of_missed_winners": _safe_mean([float(row["trade_r_multiple"]) for row in winner_rows]),
        "median_r_of_missed_winners": _safe_median([float(row["trade_r_multiple"]) for row in winner_rows]),
        "total_missed_r": sum(float(row["trade_r_multiple"]) for row in winner_rows),
        "missed_moonshot_count": sum(1 for row in winner_rows if str(row["moonshot_state"]).lower() != "normal"),
        "missed_structural_runner_count": sum(1 for row in winner_rows if str(row["runner_label"]).lower() not in {"tactical_scalp", "unknown"}),
        "missed_trade_personality_distribution": dict(personalities),
        "miss_reason_distribution": dict(reasons),
    }


def _build_pullback_type_net_performance(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["pullback_type"])].append(row)
    payload: dict[str, Any] = {}
    for pullback_type, items in grouped.items():
        payload[pullback_type] = {
            "count": len(items),
            "gross_r_mean": _safe_mean([float(row["refined_gross_r"]) for row in items]),
            "gross_r_median": _safe_median([float(row["refined_gross_r"]) for row in items]),
            "net_r_after_normal_cost_mean": _safe_mean([float(row["refined_net_r_after_fees_slippage"]) for row in items]),
            "net_r_after_normal_cost_median": _safe_median([float(row["refined_net_r_after_fees_slippage"]) for row in items]),
            "actual_trade_r_mean": _safe_mean([float(row["trade_r_multiple"]) for row in items]),
            "actual_trade_pnl_mean": _safe_mean([float(row["trade_pnl"]) for row in items]),
            "cost_aware_candidate_rate": sum(1 for row in items if row["cost_aware_pullback_candidate"]) / len(items),
            "survives_low_cost_rate": sum(1 for row in items if row["survives_low_cost"]) / len(items),
            "survives_normal_cost_rate": sum(1 for row in items if row["survives_normal_cost"]) / len(items),
            "tiny_stop_outlier_rate": sum(1 for row in items if row["tiny_stop_outlier"]) / len(items),
            "missed_winner_rate": (sum(1 for row in items if row["missed_due_to_waiting"] and float(row["trade_r_multiple"]) > 0.0) / len(items)),
        }
    return payload


def _build_personality_net_usefulness(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["personality_label"])].append(row)
    payload: dict[str, Any] = {}
    for label, items in grouped.items():
        payload[label] = {
            "count": len(items),
            "gross_r_mean": _safe_mean([float(row["trade_r_multiple"]) for row in items]),
            "net_r_after_normal_cost_mean": _safe_mean([float(row["refined_net_r_after_fees_slippage"]) for row in items]),
            "missed_winner_rate": sum(1 for row in items if row["missed_due_to_waiting"] and float(row["trade_r_multiple"]) > 0.0) / len(items),
            "tiny_stop_outlier_rate": sum(1 for row in items if row["tiny_stop_outlier"]) / len(items),
            "cost_survival_low_rate": sum(1 for row in items if row["survives_low_cost"]) / len(items),
            "cost_survival_normal_rate": sum(1 for row in items if row["survives_normal_cost"]) / len(items),
            "runner_probability": sum(1 for row in items if str(row["runner_label"]).lower() not in {"tactical_scalp", "unknown"}) / len(items),
            "exhaustion_failure_rate": sum(1 for row in items if str(row["exit_reason"]).lower() in {"stop_hit", "hard_exit", "danger_sniffed"} and float(row["trade_pnl"]) < 0.0) / len(items),
        }
    return payload


def _build_net_r_cost_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    refined = [float(row["refined_net_r_after_fees_slippage"]) for row in rows]
    original = [float(row["original_net_r_after_fees_slippage"]) for row in rows]
    filtered = [row for row in rows if not row["tiny_stop_outlier"]]
    filtered_refined = [float(row["refined_net_r_after_fees_slippage"]) for row in filtered]
    filtered_original = [float(row["original_net_r_after_fees_slippage"]) for row in filtered]
    return {
        "count": len(rows),
        "refined_net_r_mean": _safe_mean(refined),
        "refined_net_r_median": _safe_median(refined),
        "refined_net_r_trimmed_mean": _trimmed_mean(refined, 0.1),
        "original_net_r_mean": _safe_mean(original),
        "original_net_r_median": _safe_median(original),
        "original_net_r_trimmed_mean": _trimmed_mean(original, 0.1),
        "non_outlier_count": len(filtered),
        "non_outlier_refined_net_r_mean": _safe_mean(filtered_refined),
        "non_outlier_refined_net_r_median": _safe_median(filtered_refined),
        "non_outlier_refined_net_r_trimmed_mean": _trimmed_mean(filtered_refined, 0.1),
        "non_outlier_original_net_r_mean": _safe_mean(filtered_original),
        "non_outlier_original_net_r_median": _safe_median(filtered_original),
        "non_outlier_original_net_r_trimmed_mean": _trimmed_mean(filtered_original, 0.1),
        "non_outlier_normal_survival_rate": (sum(1 for row in filtered if row["survives_normal_cost"]) / len(filtered)) if filtered else 0.0,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _fmt(value: float | None, spec: str = ".3f") -> str:
    if value is None:
        return "n/a"
    return format(value, spec)


def write_evidence_refinement(config: EvidenceRefinementConfig) -> dict[str, Path]:
    source_root = config.source_review_root
    output_root = config.output_root
    output_root.mkdir(parents=True, exist_ok=True)
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    status_source = _read_json(source_root / "status.json")
    source_csv = Path(str(status_source["source_csv"]))
    tick_size = _infer_tick_size(source_csv)
    all_starts = [pd.Timestamp(status_source["windows"][window]["start"], tz="UTC") for window in _WINDOWS]
    all_ends = [pd.Timestamp(status_source["windows"][window]["end"], tz="UTC") + pd.Timedelta(days=1) for window in _WINDOWS]
    hourly_context = _load_hourly_market_context(source_csv, min(all_starts), max(all_ends))

    all_rows: list[dict[str, Any]] = []
    by_window_rows: dict[str, list[dict[str, Any]]] = {}
    execution_model = _read_json(source_root / "diagnostic_fast" / "execution_realism" / "execution_cost_model.json")

    for window in _WINDOWS:
        trades, setups, entries = _load_window_rows(source_root / window)
        joined = _join_window_data(
            window=window,
            trades=trades,
            setups=setups,
            entries=entries,
            hourly_context=hourly_context,
            execution_model=execution_model,
            tick_size=tick_size,
        )
        by_window_rows[window] = joined
        all_rows.extend(joined)

    robust_payload = {
        "by_window": {window: _build_robust_r_metrics(rows) for window, rows in by_window_rows.items()},
        "combined": _build_robust_r_metrics(all_rows),
    }
    tiny_stop_payload = {
        "by_window": {window: _build_tiny_stop_outlier_report(rows) for window, rows in by_window_rows.items()},
        "combined": _build_tiny_stop_outlier_report(all_rows),
    }
    missed_payload = {
        "by_window": {window: _build_missed_winner_penalty_report(rows) for window, rows in by_window_rows.items()},
        "combined": _build_missed_winner_penalty_report(all_rows),
    }
    type_payload = {
        "by_window": {window: _build_pullback_type_net_performance(rows) for window, rows in by_window_rows.items()},
        "combined": _build_pullback_type_net_performance(all_rows),
    }
    personality_payload = {
        "by_window": {window: _build_personality_net_usefulness(rows) for window, rows in by_window_rows.items()},
        "combined": _build_personality_net_usefulness(all_rows),
        "soft_evidence_only": True,
    }
    net_cost_payload = {
        "by_window": {window: _build_net_r_cost_summary(rows) for window, rows in by_window_rows.items()},
        "combined": _build_net_r_cost_summary(all_rows),
    }

    combined_robust = robust_payload["combined"]
    combined_tiny = tiny_stop_payload["combined"]
    combined_missed = missed_payload["combined"]
    combined_cost_aware_rate = sum(1 for row in all_rows if row["cost_aware_pullback_candidate"]) / len(all_rows)
    combined_normal_survival_rate = sum(1 for row in all_rows if row["survives_normal_cost"]) / len(all_rows)
    holdout_rows = by_window_rows["holdout_recent_preview"]
    holdout_normal_survival_rate = sum(1 for row in holdout_rows if row["survives_normal_cost"]) / len(holdout_rows)
    holdout_net_summary = net_cost_payload["by_window"]["holdout_recent_preview"]
    holdout_refined_net_r_mean = holdout_net_summary["refined_net_r_mean"]
    holdout_original_net_r_mean = holdout_net_summary["original_net_r_mean"]
    holdout_non_outlier_refined_net_r_median = holdout_net_summary["non_outlier_refined_net_r_median"]
    holdout_non_outlier_original_net_r_median = holdout_net_summary["non_outlier_original_net_r_median"]

    if (
        combined_robust["trimmed_mean_improved_r_delta"] is not None
        and combined_robust["trimmed_mean_improved_r_delta"] > 0.0
        and (combined_tiny["tiny_stop_outlier_rate"] or 0.0) <= 0.10
        and net_cost_payload["combined"]["non_outlier_normal_survival_rate"] >= 0.55
        and (combined_missed["missed_winner_rate"] or 1.0) <= 0.20
        and holdout_non_outlier_refined_net_r_median is not None
        and holdout_non_outlier_original_net_r_median is not None
        and holdout_non_outlier_refined_net_r_median > holdout_non_outlier_original_net_r_median
    ):
        classification = "eligible_for_second_fast_review"
    elif (
        (combined_tiny["tiny_stop_outlier_rate"] or 0.0) >= 0.12
        or net_cost_payload["combined"]["non_outlier_normal_survival_rate"] < 0.35
        or holdout_non_outlier_refined_net_r_median is None
        or holdout_non_outlier_original_net_r_median is None
        or holdout_non_outlier_refined_net_r_median <= holdout_non_outlier_original_net_r_median
    ):
        classification = "needs_detector_tightening"
    else:
        classification = "continue_research"

    recommendation = {
        "classification": classification,
        "allowed_classifications": list(_ALLOWED_CLASSIFICATIONS),
        "cost_aware_candidate_rate": combined_cost_aware_rate,
        "normal_cost_survival_rate": combined_normal_survival_rate,
        "holdout_normal_cost_survival_rate": holdout_normal_survival_rate,
        "reasons": [
            "raw_mean_improved_r_delta_removed_from_promotion_logic",
            "tiny_stop_and_cost_dominance_are_now explicit diagnostics",
            "pullback waiting remains too expensive unless detector quality improves",
        ],
        "forbidden": [
            "no_live_runtime_changes",
            "no_paper_runtime_changes",
            "no_real_money_enablement",
            "no_stress_windows",
            "no_macd_bollinger_hard_gates",
        ],
    }

    summary_payload = {
        "refinement_name": "Structural Compounding Lab Evidence Refinement 001",
        "source_review_root": str(source_root.resolve()),
        "output_root": str(output_root.resolve()),
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "real_money_allowed": False,
        "classification": classification,
        "allowed_classifications": list(_ALLOWED_CLASSIFICATIONS),
        "review_scope": {
            "full_history_started": False,
            "stress_windows_started": False,
            "live_behavior_changed": False,
            "paper_behavior_changed": False,
            "config_settings_changed": False,
            "macd_bollinger_hard_gates_enabled": False,
            "pullback_buying_runtime_enabled": False,
        },
        "robust_r_summary": robust_payload,
        "tiny_stop_outlier_summary": tiny_stop_payload,
        "missed_winner_penalty_summary": missed_payload,
        "pullback_type_net_performance": type_payload,
        "personality_net_usefulness_summary": personality_payload,
        "net_r_after_costs_summary": {
            "combined_cost_aware_candidate_rate": combined_cost_aware_rate,
            "combined_normal_survival_rate": combined_normal_survival_rate,
            "combined_non_outlier_normal_survival_rate": net_cost_payload["combined"]["non_outlier_normal_survival_rate"],
            "holdout_refined_net_r_after_normal_cost_mean": holdout_refined_net_r_mean,
            "holdout_original_net_r_after_normal_cost_mean": holdout_original_net_r_mean,
            "holdout_non_outlier_refined_net_r_after_normal_cost_median": holdout_non_outlier_refined_net_r_median,
            "holdout_non_outlier_original_net_r_after_normal_cost_median": holdout_non_outlier_original_net_r_median,
            "robust_net_r_by_window": net_cost_payload["by_window"],
        },
        "next_research_gate": recommendation,
    }

    report_md = f"""# Structural Compounding Lab Evidence Refinement 001

## Final Classification

`{classification}`

## Robust R Summary

- combined median improved R delta: `{_fmt(combined_robust['median_improved_r_delta'])}`
- combined trimmed mean improved R delta: `{_fmt(combined_robust['trimmed_mean_improved_r_delta'])}`
- combined winsorized mean improved R delta: `{_fmt(combined_robust['winsorized_mean_improved_r_delta'])}`
- combined p25/p75 improved R delta: `{_fmt(combined_robust['improved_r_delta_p25'])}` / `{_fmt(combined_robust['improved_r_delta_p75'])}`
- tiny-stop dominated rate: `{combined_robust['tiny_stop_outlier_rate']:.3%}`

Raw mean improved R delta is retained for transparency only and is not valid as a promotion metric.

## Tiny-Stop / Cost-Dominance Summary

- tiny stop flag rate: `{combined_tiny['tiny_stop_flag_rate']:.3%}`
- unrealistic stop flag rate: `{combined_tiny['unrealistic_stop_flag_rate']:.3%}`
- noise stop flag rate: `{combined_tiny['noise_stop_flag_rate']:.3%}`
- cost-dominated stop flag rate: `{combined_tiny['cost_dominated_stop_flag_rate']:.3%}`
- median refined stop ATR fraction: `{_fmt(combined_tiny['median_refined_stop_atr_fraction'])}`
- median refined stop cost multiple: `{_fmt(combined_tiny['median_refined_stop_cost_multiple'])}`

## Net R After Costs

- combined normal-cost survival rate: `{combined_normal_survival_rate:.3%}`
- combined non-outlier normal-cost survival rate: `{net_cost_payload['combined']['non_outlier_normal_survival_rate']:.3%}`
- holdout refined net R after normal cost mean: `{_fmt(holdout_refined_net_r_mean)}`
- holdout original net R after normal cost mean: `{_fmt(holdout_original_net_r_mean)}`
- holdout non-outlier refined net R median: `{_fmt(holdout_non_outlier_refined_net_r_median)}`
- holdout non-outlier original net R median: `{_fmt(holdout_non_outlier_original_net_r_median)}`
- cost-aware candidate rate: `{combined_cost_aware_rate:.3%}`

## Missed Winner Penalty

- missed trade rate: `{combined_missed['missed_trade_rate']:.3%}`
- missed winner rate: `{combined_missed['missed_winner_rate']:.3%}`
- average R of missed winners: `{_fmt(combined_missed['average_r_of_missed_winners'])}`
- median R of missed winners: `{_fmt(combined_missed['median_r_of_missed_winners'])}`
- total missed R: `{_fmt(combined_missed['total_missed_r'])}`

## Recommendation

Keep the work research-only. Do not promote. Do not open stress windows. Do not change live/paper behavior.
"""

    _write_json(output_root / "status.json", {
        "state": "complete",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "research_only": True,
        "real_money_allowed": False,
        "source_review_root": str(source_root.resolve()),
        "artifacts": {
            "refinement_summary": str((output_root / "refinement_summary.json").resolve()),
            "refinement_report": str((output_root / "refinement_report.md").resolve()),
            "robust_r_metrics": str((diagnostics_root / "robust_r_metrics.json").resolve()),
            "cost_aware_entries": str((diagnostics_root / "original_vs_pullback_entry_cost_aware.csv").resolve()),
            "tiny_stop_outlier_report": str((diagnostics_root / "tiny_stop_outlier_report.json").resolve()),
            "missed_winner_penalty_report": str((diagnostics_root / "missed_winner_penalty_report.json").resolve()),
            "pullback_type_net_performance": str((diagnostics_root / "pullback_type_net_performance.json").resolve()),
            "personality_net_usefulness_report": str((diagnostics_root / "personality_net_usefulness_report.json").resolve()),
            "cost_aware_pullback_candidates": str((diagnostics_root / "cost_aware_pullback_candidates.csv").resolve()),
        },
    })
    _write_json(output_root / "refinement_summary.json", summary_payload)
    _write_markdown(output_root / "refinement_report.md", report_md)
    _write_json(diagnostics_root / "robust_r_metrics.json", robust_payload)
    _write_csv(diagnostics_root / "original_vs_pullback_entry_cost_aware.csv", all_rows)
    _write_json(diagnostics_root / "tiny_stop_outlier_report.json", tiny_stop_payload)
    _write_json(diagnostics_root / "missed_winner_penalty_report.json", missed_payload)
    _write_json(diagnostics_root / "pullback_type_net_performance.json", type_payload)
    _write_json(diagnostics_root / "personality_net_usefulness_report.json", personality_payload)
    _write_csv(diagnostics_root / "cost_aware_pullback_candidates.csv", [row for row in all_rows if row["cost_aware_pullback_candidate"]])
    _write_json(reports_root / "next_research_recommendation.json", recommendation)
    _write_markdown(
        reports_root / "next_research_recommendation.md",
        "\n".join(
            [
                "# Next Research Recommendation",
                "",
                f"Classification: `{classification}`",
                "",
                "Keep the refinement passive and research-only.",
                "",
                "No live/paper changes. No stress windows. No promotion.",
            ]
        )
        + "\n",
    )
    return {
        "status": output_root / "status.json",
        "summary": output_root / "refinement_summary.json",
        "report": output_root / "refinement_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    source_review_root = root / "structural_compounding_lab" / "output" / "evidence_review_001"
    output_root = root / "structural_compounding_lab" / "output" / "evidence_refinement_001"
    write_evidence_refinement(EvidenceRefinementConfig(source_review_root=source_review_root, output_root=output_root))
    print(f"Structural evidence refinement written to: {output_root}")


if __name__ == "__main__":
    main()
