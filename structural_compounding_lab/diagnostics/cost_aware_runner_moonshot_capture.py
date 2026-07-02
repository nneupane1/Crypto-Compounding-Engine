from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import package_root, project_root  # noqa: E402
from structural_compounding_lab.diagnostics.cost_aware_frozen_candidate_rebuild import (  # noqa: E402
    CANDIDATE_NAME,
    MAX_PRE_ENTRY_COST_R,
    ROUND_TRIP_COST_BPS,
    RISK_PER_TRADE,
    START_CAPITAL_25K,
)


COURT_NAME = "COST_AWARE_RUNNER_MOONSHOT_CAPTURE_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "cost_aware_runner_moonshot_capture_court_001"
TARGET_EQUITY = 1_000_000.0

RESTORES_ROLLING_SUPPORT = "RUNNER_MOONSHOT_OVERLAY_RESTORES_SOME_1M_ROLLING_SUPPORT_RESEARCH_ONLY"
PROMISING_NOT_VALIDATED = "RUNNER_MOONSHOT_OVERLAY_PROMISING_NOT_VALIDATED_RESEARCH_ONLY"
NOT_SUPPORTED = "RUNNER_MOONSHOT_OVERLAY_NOT_SUPPORTED_RESEARCH_ONLY"
WARNING = "RUNNER_MOONSHOT_OVERLAY_WARNING_RESEARCH_ONLY"
BLOCKED = "RUNNER_MOONSHOT_OVERLAY_BLOCKED_RESEARCH_ONLY"

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "real_money_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
    "behavior_change_allowed": False,
    "production_behavior_change_allowed": False,
    "scheduler_strategy_change_allowed": False,
    "candidate_deployed_to_scheduler": False,
    "strategy_changed": False,
    "entries_changed": False,
    "base_exits_changed": False,
    "sizing_changed": False,
    "pyramiding_enabled": False,
    "no_order_path_created": True,
    "no_broker_path_created": True,
    "paper_validation_ready": False,
    "eur_25000_anchor_active": False,
}


@dataclass(frozen=True)
class MoonshotPolicy:
    policy_id: str
    runner_fraction: float
    trigger_gross_r: float
    trail_r: float
    max_hold_hours: int


@dataclass(frozen=True)
class MoonshotConfig:
    project_root: Path
    package_root: Path
    candidate_root: Path
    output_root: Path
    full_archive_csv: Path
    shadow_forward_csv: Path


def default_config() -> MoonshotConfig:
    root = project_root()
    pkg = package_root()
    return MoonshotConfig(
        project_root=root,
        package_root=pkg,
        candidate_root=pkg / "output" / "cost_aware_frozen_candidate_rebuild_court_001",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
        full_archive_csv=root / "data_storage" / "BTCUSDT" / "1m" / "BTCUSDT_1m_2018-01-01_to_2026-06-13.csv",
        shadow_forward_csv=pkg / "data_storage" / "BTCUSDT" / "1m" / "btcusdt_1m_canonical_shadow_forward.csv",
    )


def default_policies() -> list[MoonshotPolicy]:
    policies: list[MoonshotPolicy] = []
    for runner_fraction in (0.10, 0.15, 0.20):
        for trigger_gross_r in (1.5, 2.0, 3.0):
            for trail_r in (1.0, 2.0, 3.0):
                for max_hold_hours in (6, 12, 24, 72):
                    policies.append(
                        MoonshotPolicy(
                            policy_id=(
                                f"runner_{int(runner_fraction * 100)}pct"
                                f"_trigger_{str(trigger_gross_r).replace('.', '_')}R"
                                f"_trail_{str(trail_r).replace('.', '_')}R"
                                f"_hold_{max_hold_hours}h"
                            ),
                            runner_fraction=runner_fraction,
                            trigger_gross_r=trigger_gross_r,
                            trail_r=trail_r,
                            max_hold_hours=max_hold_hours,
                        )
                    )
    return policies


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_output(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def _round_payload(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _round_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_payload(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return "" if math.isnan(value) or math.isinf(value) else round(value, 10)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is None:
        return ""
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_round_payload(payload), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row.keys()})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in keys})


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = row.get(key, default)
        if value in {"", None}:
            return default
        return float(value)
    except Exception:
        return default


def _bool(row: dict[str, Any], key: str) -> bool:
    return str(row.get(key, "")).strip().lower() in {"true", "1", "yes"}


def _profit_factor(values: list[float]) -> float:
    wins = sum(value for value in values if value > 0.0)
    losses = abs(sum(value for value in values if value < 0.0))
    if losses == 0.0:
        return float("inf") if wins > 0.0 else 0.0
    return wins / losses


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0] if curve else 0.0
    worst = 0.0
    for equity in curve:
        peak = max(peak, equity)
        if peak > 0.0:
            worst = max(worst, (peak - equity) / peak)
    return worst


def _simulate(rows: list[dict[str, Any]], *, net_r_key: str = "net_r", start_capital: float = START_CAPITAL_25K) -> dict[str, Any]:
    equity = start_capital
    curve = [equity]
    trade_rows: list[dict[str, Any]] = []
    values = [float(row[net_r_key]) for row in rows]
    for index, row in enumerate(rows, start=1):
        before = equity
        risk = before * RISK_PER_TRADE
        pnl = float(row[net_r_key]) * risk
        equity = before + pnl
        curve.append(equity)
        trade_rows.append({**row, "trade_number": index, "equity_before_trade": before, "net_pnl_eur": pnl, "equity_after_trade": equity})
    return {
        "starting_equity": start_capital,
        "ending_equity": equity,
        "net_gain": equity - start_capital,
        "return_multiple": equity / start_capital if start_capital else 0.0,
        "accepted_trades": len(rows),
        "net_total_R": sum(values),
        "average_R": sum(values) / len(values) if values else 0.0,
        "median_R": median(values) if values else 0.0,
        "profit_factor": _profit_factor(values),
        "win_rate": sum(1 for value in values if value > 0.0) / len(values) if values else 0.0,
        "max_drawdown": _max_drawdown(curve),
        "largest_loss_R": min(values) if values else 0.0,
        "best_trade_R": max(values) if values else 0.0,
        "equity_curve": curve,
        "trade_rows": trade_rows,
    }


def _load_candidate_rows(config: MoonshotConfig) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    full = _candidate_rows_from_file(config.candidate_root / "candidate_full_history_results.csv", "full_history")
    holdout = _candidate_rows_from_file(config.candidate_root / "candidate_holdout_results.csv", "sealed_holdout")
    return full, holdout


def _candidate_rows_from_file(path: Path, period: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in _read_csv(path):
        if not _bool(row, "candidate_guard_accepted"):
            continue
        entry_ts = pd.to_datetime(row.get("entry_timestamp") or row.get("entry_time"), utc=True, errors="coerce")
        exit_ts = pd.to_datetime(row.get("exit_timestamp") or row.get("exit_time"), utc=True, errors="coerce")
        payload = dict(row)
        payload.update(
            {
                "moonshot_row_key": f"{period}:{len(rows) + 1}:{row.get('trade_id') or ''}",
                "period": period,
                "entry_timestamp": entry_ts,
                "exit_timestamp": exit_ts,
                "entry_price": _float(row, "entry_price"),
                "exit_price": _float(row, "exit_price"),
                "initial_stop": _float(row, "initial_stop"),
                "gross_r": _float(row, "gross_r"),
                "net_r": _float(row, "net_r"),
                "net_cost_r": _float(row, "net_cost_r"),
                "pre_entry_cost_r_at_15bps": _float(row, "pre_entry_cost_r_at_15bps"),
            }
        )
        rows.append(payload)
    return sorted(rows, key=lambda item: item["entry_timestamp"])


def _load_candles(config: MoonshotConfig) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in (config.full_archive_csv, config.shadow_forward_csv):
        if not path.exists():
            continue
        frame = pd.read_csv(path, usecols=["timestamp", "open", "high", "low", "close"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
        frames.append(frame.dropna(subset=["timestamp"]))
    if not frames:
        return pd.DataFrame(columns=["open", "high", "low", "close"])
    data = pd.concat(frames, ignore_index=True)
    data = data.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")
    for col in ("open", "high", "low", "close"):
        data[col] = pd.to_numeric(data[col], errors="coerce")
    data = data.dropna(subset=["open", "high", "low", "close"])
    return data.set_index("timestamp")


def _risk_per_unit(row: dict[str, Any]) -> float:
    return abs(float(row["entry_price"]) - float(row["initial_stop"]))


def _price_to_gross_r(row: dict[str, Any], price: float) -> float:
    risk = _risk_per_unit(row)
    if risk <= 0.0:
        return float(row["gross_r"])
    if str(row.get("side", "")).lower() == "short":
        return (float(row["entry_price"]) - price) / risk
    return (price - float(row["entry_price"])) / risk


def _future_window(candles: pd.DataFrame, exit_ts: pd.Timestamp, max_hold_hours: int) -> pd.DataFrame:
    end = exit_ts + pd.Timedelta(hours=max_hold_hours)
    return candles[(candles.index > exit_ts) & (candles.index <= end)]


def _precompute_future_windows(rows: list[dict[str, Any]], candles: pd.DataFrame, *, horizon_hours: int = 72) -> dict[str, pd.DataFrame]:
    return {
        str(row["moonshot_row_key"]): _future_window(candles, row["exit_timestamp"], horizon_hours)
        for row in rows
        if pd.notna(row["exit_timestamp"])
    }


def _cached_future_window(row: dict[str, Any], future_windows: dict[str, pd.DataFrame] | None, max_hold_hours: int) -> pd.DataFrame:
    if future_windows is None:
        return pd.DataFrame()
    future = future_windows.get(str(row["moonshot_row_key"]))
    if future is None or future.empty:
        return pd.DataFrame()
    end = row["exit_timestamp"] + pd.Timedelta(hours=max_hold_hours)
    return future[future.index <= end]


def _runner_exit(row: dict[str, Any], policy: MoonshotPolicy, future_windows: dict[str, pd.DataFrame] | None = None) -> dict[str, Any]:
    if float(row["gross_r"]) < policy.trigger_gross_r:
        return {
            "runner_eligible": False,
            "runner_exit_reason": "not_triggered",
            "runner_exit_timestamp": row["exit_timestamp"],
            "runner_gross_r": float(row["gross_r"]),
            "runner_extra_gross_r": 0.0,
            "runner_minutes_held_after_base_exit": 0,
            "future_candles_available": 0,
        }
    risk = _risk_per_unit(row)
    if risk <= 0.0 or pd.isna(row["exit_timestamp"]):
        return {
            "runner_eligible": False,
            "runner_exit_reason": "invalid_risk_or_timestamp",
            "runner_exit_timestamp": row["exit_timestamp"],
            "runner_gross_r": float(row["gross_r"]),
            "runner_extra_gross_r": 0.0,
            "runner_minutes_held_after_base_exit": 0,
            "future_candles_available": 0,
        }
    future = _cached_future_window(row, future_windows, policy.max_hold_hours)
    if future.empty:
        return {
            "runner_eligible": True,
            "runner_exit_reason": "no_future_candles",
            "runner_exit_timestamp": row["exit_timestamp"],
            "runner_gross_r": float(row["gross_r"]),
            "runner_extra_gross_r": 0.0,
            "runner_minutes_held_after_base_exit": 0,
            "future_candles_available": 0,
        }

    side = str(row.get("side", "")).lower()
    entry = float(row["entry_price"])
    exit_price = float(row["exit_price"])
    if side == "short":
        low_water = exit_price
        stop = min(entry, exit_price + (policy.trail_r * risk))
        timestamps = future.index.to_list()
        highs = future["high"].to_numpy()
        lows = future["low"].to_numpy()
        closes = future["close"].to_numpy()
        for index, ts in enumerate(timestamps):
            high = float(highs[index])
            low = float(lows[index])
            if high >= stop:
                gross_r = _price_to_gross_r(row, stop)
                return _runner_payload(row, ts, gross_r, len(future), "trailing_stop")
            low_water = min(low_water, low)
            stop = min(stop, low_water + (policy.trail_r * risk))
        gross_r = _price_to_gross_r(row, float(closes[-1]))
        return _runner_payload(row, future.index[-1], gross_r, len(future), "max_hold_close")

    high_water = exit_price
    stop = max(entry, exit_price - (policy.trail_r * risk))
    timestamps = future.index.to_list()
    highs = future["high"].to_numpy()
    lows = future["low"].to_numpy()
    closes = future["close"].to_numpy()
    for index, ts in enumerate(timestamps):
        low = float(lows[index])
        high = float(highs[index])
        if low <= stop:
            gross_r = _price_to_gross_r(row, stop)
            return _runner_payload(row, ts, gross_r, len(future), "trailing_stop")
        high_water = max(high_water, high)
        stop = max(stop, high_water - (policy.trail_r * risk))
    gross_r = _price_to_gross_r(row, float(closes[-1]))
    return _runner_payload(row, future.index[-1], gross_r, len(future), "max_hold_close")


def _runner_payload(row: dict[str, Any], exit_ts: pd.Timestamp, gross_r: float, future_count: int, reason: str) -> dict[str, Any]:
    minutes = max(int((exit_ts - row["exit_timestamp"]).total_seconds() // 60), 0)
    return {
        "runner_eligible": True,
        "runner_exit_reason": reason,
        "runner_exit_timestamp": exit_ts,
        "runner_gross_r": gross_r,
        "runner_extra_gross_r": gross_r - float(row["gross_r"]),
        "runner_minutes_held_after_base_exit": minutes,
        "future_candles_available": future_count,
    }


def _post_exit_opportunity(row: dict[str, Any], future_windows: dict[str, pd.DataFrame], *, horizon_hours: int = 72) -> dict[str, Any]:
    risk = _risk_per_unit(row)
    future = _cached_future_window(row, future_windows, horizon_hours) if risk > 0.0 and pd.notna(row["exit_timestamp"]) else pd.DataFrame()
    if future.empty:
        return {
            "trade_id": row.get("trade_id"),
            "period": row["period"],
            "side": row.get("side"),
            "entry_timestamp": row["entry_timestamp"],
            "exit_timestamp": row["exit_timestamp"],
            "gross_r": float(row["gross_r"]),
            "net_r": float(row["net_r"]),
            "post_exit_best_gross_r_72h": float(row["gross_r"]),
            "post_exit_extra_gross_r_72h": 0.0,
            "post_exit_moonshot_ge_3R_extra": False,
            "post_exit_moonshot_ge_5R_extra": False,
            "future_candles_available": 0,
        }
    if str(row.get("side", "")).lower() == "short":
        best_price = float(future["low"].min())
    else:
        best_price = float(future["high"].max())
    best_r = _price_to_gross_r(row, best_price)
    extra = best_r - float(row["gross_r"])
    return {
        "trade_id": row.get("trade_id"),
        "period": row["period"],
        "side": row.get("side"),
        "entry_timestamp": row["entry_timestamp"],
        "exit_timestamp": row["exit_timestamp"],
        "gross_r": float(row["gross_r"]),
        "net_r": float(row["net_r"]),
        "post_exit_best_gross_r_72h": best_r,
        "post_exit_extra_gross_r_72h": extra,
        "post_exit_moonshot_ge_3R_extra": extra >= 3.0,
        "post_exit_moonshot_ge_5R_extra": extra >= 5.0,
        "future_candles_available": len(future),
    }


def _apply_policy(rows: list[dict[str, Any]], policy: MoonshotPolicy, future_windows: dict[str, pd.DataFrame]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        runner = _runner_exit(row, policy, future_windows)
        base_gross = float(row["gross_r"])
        if runner["runner_eligible"]:
            overlay_gross_r = ((1.0 - policy.runner_fraction) * base_gross) + (policy.runner_fraction * float(runner["runner_gross_r"]))
        else:
            overlay_gross_r = base_gross
        overlay_net_r = overlay_gross_r - float(row["net_cost_r"])
        output.append(
            {
                **row,
                "policy_id": policy.policy_id,
                "runner_fraction": policy.runner_fraction,
                "trigger_gross_r": policy.trigger_gross_r,
                "trail_r": policy.trail_r,
                "max_hold_hours": policy.max_hold_hours,
                **runner,
                "overlay_gross_r": overlay_gross_r,
                "overlay_net_r": overlay_net_r,
                "overlay_delta_net_r": overlay_net_r - float(row["net_r"]),
            }
        )
    return output


def _rolling_windows() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    starts = pd.date_range("2018-01-01", "2021-06-01", freq="MS", tz="UTC")
    return [(start, start + pd.DateOffset(years=5) - pd.Timedelta(minutes=1)) for start in starts]


def _rolling_summary(rows: list[dict[str, Any]], *, net_r_key: str) -> dict[str, Any]:
    window_rows: list[dict[str, Any]] = []
    for idx, (start, end) in enumerate(_rolling_windows(), start=1):
        selected = [row for row in rows if pd.notna(row["entry_timestamp"]) and start <= row["entry_timestamp"] <= end]
        sim = _simulate(selected, net_r_key=net_r_key)
        window_rows.append(
            {
                "window_number": idx,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "ending_equity": sim["ending_equity"],
                "return_multiple": sim["return_multiple"],
                "accepted_trades": sim["accepted_trades"],
                "net_total_R": sim["net_total_R"],
                "max_drawdown": sim["max_drawdown"],
                "above_1m": sim["ending_equity"] >= TARGET_EQUITY,
            }
        )
    endings = [float(row["ending_equity"]) for row in window_rows]
    return {
        "window_count": len(window_rows),
        "average_ending_equity": sum(endings) / len(endings) if endings else 0.0,
        "median_ending_equity": median(endings) if endings else 0.0,
        "maximum_ending_equity": max(endings) if endings else 0.0,
        "minimum_ending_equity": min(endings) if endings else 0.0,
        "windows_above_1m": sum(1 for value in endings if value >= TARGET_EQUITY),
        "best_window": max(window_rows, key=lambda row: float(row["ending_equity"])) if window_rows else None,
        "window_rows": window_rows,
    }


def _policy_result(
    policy: MoonshotPolicy,
    full_rows: list[dict[str, Any]],
    holdout_rows: list[dict[str, Any]],
    rolling_rows: list[dict[str, Any]],
    baseline_full: dict[str, Any],
    baseline_holdout: dict[str, Any],
    baseline_rolling: dict[str, Any],
) -> dict[str, Any]:
    full_sim = _simulate(full_rows, net_r_key="overlay_net_r")
    holdout_sim = _simulate(holdout_rows, net_r_key="overlay_net_r")
    rolling = _rolling_summary(rolling_rows, net_r_key="overlay_net_r")
    runner_rows = [row for row in full_rows + holdout_rows if row["runner_eligible"]]
    improved_rows = [row for row in runner_rows if float(row["overlay_delta_net_r"]) > 0.0]
    damaged_rows = [row for row in runner_rows if float(row["overlay_delta_net_r"]) < 0.0]
    return {
        "policy_id": policy.policy_id,
        "runner_fraction": policy.runner_fraction,
        "trigger_gross_r": policy.trigger_gross_r,
        "trail_r": policy.trail_r,
        "max_hold_hours": policy.max_hold_hours,
        "eligible_trades": len(runner_rows),
        "runner_improved_trades": len(improved_rows),
        "runner_damaged_trades": len(damaged_rows),
        "full_history_ending_equity": full_sim["ending_equity"],
        "full_history_delta_eur": full_sim["ending_equity"] - baseline_full["ending_equity"],
        "full_history_delta_pct": (full_sim["ending_equity"] / baseline_full["ending_equity"] - 1.0) if baseline_full["ending_equity"] else 0.0,
        "full_history_max_drawdown": full_sim["max_drawdown"],
        "full_history_best_trade_R": full_sim["best_trade_R"],
        "holdout_ending_equity": holdout_sim["ending_equity"],
        "holdout_delta_eur": holdout_sim["ending_equity"] - baseline_holdout["ending_equity"],
        "holdout_delta_pct": (holdout_sim["ending_equity"] / baseline_holdout["ending_equity"] - 1.0) if baseline_holdout["ending_equity"] else 0.0,
        "holdout_max_drawdown": holdout_sim["max_drawdown"],
        "rolling_average_ending_equity": rolling["average_ending_equity"],
        "rolling_median_ending_equity": rolling["median_ending_equity"],
        "rolling_max_ending_equity": rolling["maximum_ending_equity"],
        "rolling_windows_above_1m": rolling["windows_above_1m"],
        "rolling_max_delta_eur": rolling["maximum_ending_equity"] - baseline_rolling["maximum_ending_equity"],
        "full_sim": full_sim,
        "holdout_sim": holdout_sim,
        "rolling": rolling,
    }


def run_moonshot_court(config: MoonshotConfig | None = None, policies: list[MoonshotPolicy] | None = None) -> dict[str, Any]:
    config = config or default_config()
    policies = policies or default_policies()
    config.output_root.mkdir(parents=True, exist_ok=True)
    required = [
        config.candidate_root / "cost_aware_frozen_candidate_rebuild_summary.json",
        config.candidate_root / "candidate_full_history_results.csv",
        config.candidate_root / "candidate_holdout_results.csv",
        config.full_archive_csv,
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        summary = {"court_name": COURT_NAME, "final_classification": BLOCKED, "missing_inputs": missing, **SAFETY_FLAGS}
        _write_json(config.output_root / "cost_aware_runner_moonshot_capture_summary.json", summary)
        return summary

    candidate_summary = _read_json(config.candidate_root / "cost_aware_frozen_candidate_rebuild_summary.json")
    full_rows, holdout_rows = _load_candidate_rows(config)
    candles = _load_candles(config)
    if candles.empty:
        summary = {"court_name": COURT_NAME, "final_classification": BLOCKED, "missing_inputs": ["1m candles"], **SAFETY_FLAGS}
        _write_json(config.output_root / "cost_aware_runner_moonshot_capture_summary.json", summary)
        return summary

    baseline_full = _simulate(full_rows)
    baseline_holdout = _simulate(holdout_rows)
    baseline_rolling = _rolling_summary(full_rows + holdout_rows, net_r_key="net_r")
    all_rows = full_rows + holdout_rows
    future_windows = _precompute_future_windows(all_rows, candles)
    opportunity = [_post_exit_opportunity(row, future_windows) for row in all_rows]

    policy_rows: list[dict[str, Any]] = []
    policy_details: dict[str, dict[str, Any]] = {}
    for policy in policies:
        full_overlay = _apply_policy(full_rows, policy, future_windows)
        holdout_overlay = _apply_policy(holdout_rows, policy, future_windows)
        result = _policy_result(policy, full_overlay, holdout_overlay, full_overlay + holdout_overlay, baseline_full, baseline_holdout, baseline_rolling)
        policy_details[policy.policy_id] = result
        policy_rows.append({key: value for key, value in result.items() if key not in {"full_sim", "holdout_sim", "rolling"}})

    best = max(
        policy_details.values(),
        key=lambda item: (
            int(item["rolling_windows_above_1m"]),
            float(item["rolling_max_ending_equity"]),
            float(item["full_history_ending_equity"]),
            float(item["holdout_ending_equity"]),
        ),
    )
    best_full_rows = _apply_policy(full_rows, _policy_from_id(best["policy_id"], policies), future_windows)
    best_holdout_rows = _apply_policy(holdout_rows, _policy_from_id(best["policy_id"], policies), future_windows)

    opportunity_extras = [float(row["post_exit_extra_gross_r_72h"]) for row in opportunity]
    moonshot_extra_ge_3 = sum(1 for value in opportunity_extras if value >= 3.0)
    moonshot_extra_ge_5 = sum(1 for value in opportunity_extras if value >= 5.0)
    full_improves = best["full_history_ending_equity"] > baseline_full["ending_equity"]
    holdout_not_damaged = best["holdout_ending_equity"] >= baseline_holdout["ending_equity"] * 0.98
    rolling_improves = best["rolling_max_ending_equity"] > baseline_rolling["maximum_ending_equity"]
    if best["rolling_windows_above_1m"] > 0 and holdout_not_damaged:
        final = RESTORES_ROLLING_SUPPORT
    elif full_improves and holdout_not_damaged and rolling_improves:
        final = PROMISING_NOT_VALIDATED
    elif not full_improves and best["holdout_ending_equity"] < baseline_holdout["ending_equity"]:
        final = NOT_SUPPORTED
    else:
        final = WARNING

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "branch": _git_output(config.project_root, "branch", "--show-current"),
        "final_classification": final,
        "candidate_name": CANDIDATE_NAME,
        "cost_model": {
            "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "base_candidate_cost_model_preserved": True,
            "runner_overlay_does_not_double_count_entry_cost": True,
            "separate_slippage_model_added": False,
        },
        "candidate_guard": {
            "max_pre_entry_cost_r": MAX_PRE_ENTRY_COST_R,
            "changed": False,
        },
        "input_artifacts": {
            "candidate_summary": str(config.candidate_root / "cost_aware_frozen_candidate_rebuild_summary.json"),
            "candidate_full_history_results": str(config.candidate_root / "candidate_full_history_results.csv"),
            "candidate_holdout_results": str(config.candidate_root / "candidate_holdout_results.csv"),
            "full_archive_csv": str(config.full_archive_csv),
            "shadow_forward_csv": str(config.shadow_forward_csv),
        },
        "baseline": {
            "full_history_ending_equity": baseline_full["ending_equity"],
            "full_history_best_trade_R": baseline_full["best_trade_R"],
            "holdout_ending_equity": baseline_holdout["ending_equity"],
            "holdout_best_trade_R": baseline_holdout["best_trade_R"],
            "rolling_average_ending_equity": baseline_rolling["average_ending_equity"],
            "rolling_median_ending_equity": baseline_rolling["median_ending_equity"],
            "rolling_max_ending_equity": baseline_rolling["maximum_ending_equity"],
            "rolling_windows_above_1m": baseline_rolling["windows_above_1m"],
        },
        "post_exit_opportunity": {
            "accepted_trades_checked": len(opportunity),
            "trades_with_3R_extra_available_after_exit_72h": moonshot_extra_ge_3,
            "trades_with_5R_extra_available_after_exit_72h": moonshot_extra_ge_5,
            "max_extra_gross_R_after_exit_72h": max(opportunity_extras) if opportunity_extras else 0.0,
            "median_extra_gross_R_after_exit_72h": median(opportunity_extras) if opportunity_extras else 0.0,
        },
        "best_policy": {key: value for key, value in best.items() if key not in {"full_sim", "holdout_sim", "rolling"}},
        "best_policy_interpretation": {
            "rolling_1m_target_validated": best["rolling_windows_above_1m"] > 0,
            "full_history_improved": full_improves,
            "holdout_not_materially_damaged": holdout_not_damaged,
            "rolling_max_improved": rolling_improves,
            "paper_readiness_court_can_be_considered_now": False,
            "requires_separate_freeze_and_fresh_forward_validation": True,
        },
        "original_candidate_summary_reference": {
            "full_history": candidate_summary.get("full_history"),
            "sealed_holdout": candidate_summary.get("sealed_holdout"),
            "rolling_5y": candidate_summary.get("rolling_5y"),
        },
        **SAFETY_FLAGS,
        "files_created": [
            str(config.output_root / "cost_aware_runner_moonshot_capture_summary.json"),
            str(config.output_root / "cost_aware_runner_moonshot_capture_report.md"),
            str(config.output_root / "runner_moonshot_policy_results.csv"),
            str(config.output_root / "runner_moonshot_best_policy_trades.csv"),
            str(config.output_root / "runner_moonshot_post_exit_opportunity.csv"),
            str(config.output_root / "runner_moonshot_best_policy_rolling_windows.csv"),
        ],
    }
    _write_csv(config.output_root / "runner_moonshot_policy_results.csv", policy_rows)
    _write_csv(config.output_root / "runner_moonshot_best_policy_trades.csv", best_full_rows + best_holdout_rows)
    _write_csv(config.output_root / "runner_moonshot_post_exit_opportunity.csv", opportunity)
    _write_csv(config.output_root / "runner_moonshot_best_policy_rolling_windows.csv", best["rolling"]["window_rows"])
    _write_json(config.output_root / "cost_aware_runner_moonshot_capture_summary.json", summary)
    (config.output_root / "cost_aware_runner_moonshot_capture_report.md").write_text(_report(summary), encoding="utf-8")
    return _round_payload(summary)


def _policy_from_id(policy_id: str, policies: list[MoonshotPolicy]) -> MoonshotPolicy:
    for policy in policies:
        if policy.policy_id == policy_id:
            return policy
    raise ValueError(f"Unknown policy_id: {policy_id}")


def _fmt_eur(value: Any) -> str:
    return f"€{float(value):,.2f}"


def _fmt_pct(value: Any) -> str:
    return f"{float(value) * 100:.2f}%"


def _report(summary: dict[str, Any]) -> str:
    best = summary["best_policy"]
    base = summary["baseline"]
    opportunity = summary["post_exit_opportunity"]
    return "\n".join(
        [
            "# Cost-Aware Runner Moonshot Capture Court 001",
            "",
            f"- Final classification: `{summary['final_classification']}`",
            f"- Candidate: `{summary['candidate_name']}`",
            f"- Research-only: `{summary['research_only']}`",
            f"- Paper validation ready: `{summary['paper_validation_ready']}`",
            "",
            "## Post-exit moonshot opportunity",
            "",
            f"- Accepted trades checked: `{opportunity['accepted_trades_checked']}`",
            f"- Trades with at least +3R extra available within 72h after base exit: `{opportunity['trades_with_3R_extra_available_after_exit_72h']}`",
            f"- Trades with at least +5R extra available within 72h after base exit: `{opportunity['trades_with_5R_extra_available_after_exit_72h']}`",
            f"- Max extra gross R after base exit: `{opportunity['max_extra_gross_R_after_exit_72h']:.2f}R`",
            "",
            "## Best runner policy",
            "",
            f"- Policy: `{best['policy_id']}`",
            f"- Runner fraction: `{_fmt_pct(best['runner_fraction'])}`",
            f"- Trigger: `{best['trigger_gross_r']}R gross at base exit`",
            f"- Trail: `{best['trail_r']}R`",
            f"- Max hold: `{best['max_hold_hours']}h`",
            "",
            "## Baseline vs best policy",
            "",
            f"- Full-history baseline: `{_fmt_eur(base['full_history_ending_equity'])}`",
            f"- Full-history best policy: `{_fmt_eur(best['full_history_ending_equity'])}`",
            f"- Holdout baseline: `{_fmt_eur(base['holdout_ending_equity'])}`",
            f"- Holdout best policy: `{_fmt_eur(best['holdout_ending_equity'])}`",
            f"- Rolling max baseline: `{_fmt_eur(base['rolling_max_ending_equity'])}`",
            f"- Rolling max best policy: `{_fmt_eur(best['rolling_max_ending_equity'])}`",
            f"- Rolling windows above EUR1M: `{best['rolling_windows_above_1m']}`",
            "",
            "No entries, base exits, sizing, scheduler, paper, live, order, or broker behavior was changed.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run research-only cost-aware runner moonshot capture court.")
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()
    config = default_config()
    if args.output_root:
        config = MoonshotConfig(
            project_root=config.project_root,
            package_root=config.package_root,
            candidate_root=config.candidate_root,
            output_root=Path(args.output_root).expanduser().resolve(),
            full_archive_csv=config.full_archive_csv,
            shadow_forward_csv=config.shadow_forward_csv,
        )
    print(json.dumps(run_moonshot_court(config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
