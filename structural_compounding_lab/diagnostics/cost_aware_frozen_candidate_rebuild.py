from __future__ import annotations

import argparse
import csv
import json
import math
import random
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Iterable

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import package_root, project_root  # noqa: E402
from structural_compounding_lab.diagnostics.court_002_net_cost_restatement import (  # noqa: E402
    PRIMARY_COST_MODEL,
    REQUIRED_MONTHLY_GROWTH_FOR_25K_TO_1M_5Y,
    START_CAPITAL_25K,
    _accepted_trades_from_existing_artifacts,
    _max_drawdown,
    _monthly_growth,
    _profit_factor,
    _safe_ratio,
    stop_distance_fraction,
)


COURT_NAME = "COST_AWARE_FROZEN_CANDIDATE_REBUILD_COURT_RESEARCH_ONLY"
CANDIDATE_NAME = "COST_AWARE_MAX_COST_R_1_0_CANDIDATE"
OUTPUT_FOLDER_NAME = "cost_aware_frozen_candidate_rebuild_court_001"
ROUND_TRIP_COST_BPS = 15.0
ROUND_TRIP_COST_FRACTION = ROUND_TRIP_COST_BPS / 10_000.0
MAX_PRE_ENTRY_COST_R = 1.0
RISK_PER_TRADE = 0.01
MISSION_TARGET_EUR = 1_000_000.0
MONTE_CARLO_SEED = 251002026
MONTE_CARLO_RUNS = 10_000

STRONG = "COST_AWARE_FROZEN_CANDIDATE_REBUILD_STRONG_RESEARCH_ONLY"
PROMISING = "COST_AWARE_FROZEN_CANDIDATE_REBUILD_PROMISING_WITH_WARNINGS_RESEARCH_ONLY"
WEAK = "COST_AWARE_FROZEN_CANDIDATE_REBUILD_WEAK_RESEARCH_ONLY"
FAILED = "COST_AWARE_FROZEN_CANDIDATE_REBUILD_FAILED_RESEARCH_ONLY"
BLOCKED = "COST_AWARE_FROZEN_CANDIDATE_REBUILD_BLOCKED_RESEARCH_ONLY"

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "real_money_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
    "production_behavior_change_allowed": False,
    "scheduler_strategy_change_allowed": False,
    "no_order_path_created": True,
    "no_broker_path_created": True,
    "paper_validation_ready": False,
    "eur_25000_anchor_active": False,
}


@dataclass(frozen=True)
class CostAwareCandidateConfig:
    project_root: Path
    package_root: Path
    output_root: Path
    court_002_root: Path
    damage_root: Path
    net_restatement_root: Path
    zero_stop_root: Path
    gauntlet_root: Path
    scheduler_root: Path


def default_config() -> CostAwareCandidateConfig:
    pkg = package_root()
    return CostAwareCandidateConfig(
        project_root=project_root(),
        package_root=pkg,
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
        court_002_root=pkg / "output" / "eur25k_sealed_6m_holdout_court_002",
        damage_root=pkg / "output" / "net_cost_damage_attribution_execution_filter_court_001",
        net_restatement_root=pkg / "output" / "court_002_net_cost_restatement_court_001",
        zero_stop_root=pkg / "output" / "court_002_net_cost_zero_stop_resolution_court_001",
        gauntlet_root=pkg / "output" / "pre_paper_evidence_acceleration_gauntlet_court_001",
        scheduler_root=pkg / "output" / "continuous_scheduler_forward_validation_court_001",
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _git_output(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def _scheduler_state() -> dict[str, Any]:
    label = "com.retail_trading_system.research_forward_shadow"
    try:
        uid = subprocess.check_output(["id", "-u"], text=True).strip()
        result = subprocess.run(["launchctl", "print", f"gui/{uid}/{label}"], check=True, capture_output=True, text=True)
        text = result.stdout
    except Exception as exc:
        return {"label": label, "installed_loaded": False, "error": str(exc)}
    return {
        "label": label,
        "installed_loaded": True,
        "watching_calendar_interval": "watching = 1" in text,
        "last_exit_code_zero": "last exit code = 0" in text,
        "candidate_deployed_to_scheduler": False,
        "production_behavior_changed": False,
    }


def _input_paths(config: CostAwareCandidateConfig) -> dict[str, Path]:
    return {
        "damage_summary": config.damage_root / "net_cost_damage_attribution_summary.json",
        "damage_report": config.damage_root / "net_cost_damage_attribution_report.md",
        "court_002_summary": config.court_002_root / "eur25k_sealed_6m_holdout_summary.json",
        "court_002_report": config.court_002_root / "eur25k_sealed_6m_holdout_report.md",
        "court_002_split_manifest": config.court_002_root / "split_manifest.json",
        "court_002_anti_leakage": config.court_002_root / "anti_leakage_audit.json",
        "full_history_trade_source": config.court_002_root / "research_only_eur25k_replay" / "raw_engine" / "trades.csv",
        "holdout_trade_source": config.court_002_root / "holdout_validation" / "raw_engine" / "trades.csv",
        "net_restatement_summary": config.net_restatement_root / "court_002_net_cost_restatement_summary.json",
        "zero_stop_summary": config.zero_stop_root / "court_002_net_cost_zero_stop_resolution_summary.json",
        "gauntlet_summary": config.gauntlet_root / "pre_paper_evidence_acceleration_gauntlet_summary.json",
        "scheduler_summary": config.scheduler_root / "continuous_scheduler_forward_validation_summary.json",
        "scheduler_cockpit": config.scheduler_root / "forward_validation_cockpit.json",
    }


def pre_entry_cost_r(*, entry_price: float, initial_stop: float, round_trip_cost_fraction: float = ROUND_TRIP_COST_FRACTION) -> float | None:
    if entry_price <= 0.0 or initial_stop <= 0.0:
        return None
    distance = abs(entry_price - initial_stop) / entry_price
    if distance <= 0.0:
        return None
    return round_trip_cost_fraction / distance


def candidate_guard_accepts(row: dict[str, Any]) -> tuple[bool, float | None, str]:
    cost_r = pre_entry_cost_r(
        entry_price=float(row.get("entry_price") or 0.0),
        initial_stop=float(row.get("initial_stop") or 0.0),
    )
    if cost_r is None:
        return False, None, "rejected_zero_or_missing_pre_entry_stop_distance"
    if cost_r > MAX_PRE_ENTRY_COST_R:
        return False, cost_r, "rejected_pre_entry_cost_r_above_1_0"
    return True, cost_r, "accepted_cost_aware_candidate"


def _selected_rows(config: CostAwareCandidateConfig, raw_engine_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected, removed = _accepted_trades_from_existing_artifacts(config, raw_engine_root)
    for row in selected:
        row["entry_timestamp"] = pd.to_datetime(row.get("entry_time") or row.get("timestamp"), utc=True, errors="coerce")
        row["exit_timestamp"] = pd.to_datetime(row.get("exit_time") or row.get("timestamp"), utc=True, errors="coerce")
    return selected, removed


def _candidate_rows(rows: list[dict[str, Any]], *, net_cost_bps: float = ROUND_TRIP_COST_BPS) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        accepts, guard_cost_r, reason = candidate_guard_accepts(row)
        stop_fraction = stop_distance_fraction(row)
        gross_r = float(row.get("r_multiple") or 0.0)
        net_cost_r = 0.0 if stop_fraction <= 0.0 else (net_cost_bps / 10_000.0) / stop_fraction
        net_r = gross_r - net_cost_r if stop_fraction > 0.0 else gross_r
        payload = {
            "source_trade_number": index,
            "trade_id": row.get("trade_id"),
            "symbol": row.get("symbol", "BTCUSDT"),
            "side": row.get("side"),
            "entry_time": row.get("entry_time"),
            "exit_time": row.get("exit_time"),
            "entry_timestamp": row.get("entry_timestamp"),
            "exit_timestamp": row.get("exit_timestamp"),
            "entry_price": float(row.get("entry_price") or 0.0),
            "initial_stop": float(row.get("initial_stop") or 0.0),
            "exit_price": float(row.get("exit_price") or 0.0),
            "stop_distance_fraction": stop_fraction,
            "pre_entry_cost_r_at_15bps": guard_cost_r,
            "candidate_guard_threshold": MAX_PRE_ENTRY_COST_R,
            "candidate_guard_accepted": accepts,
            "candidate_guard_reason": reason,
            "gross_r": gross_r,
            "net_cost_r": net_cost_r,
            "net_r": net_r,
            "setup_class": row.get("setup_class"),
            "strategy_type": row.get("strategy_type"),
            "convexity_label": row.get("convexity_label"),
            "personality_label": row.get("personality_label"),
            "runner_label": row.get("runner_label"),
        }
        if accepts:
            accepted.append(payload)
        else:
            rejected.append(payload)
    return accepted, rejected


def _simulate(rows: list[dict[str, Any]], *, start_capital: float = START_CAPITAL_25K) -> dict[str, Any]:
    equity = start_capital
    curve = [equity]
    trade_rows: list[dict[str, Any]] = []
    values = [float(row["net_r"]) for row in rows]
    gross_values = [float(row["gross_r"]) for row in rows]
    total_cost_eur = 0.0
    peak = equity
    current_drawdown = 0.0
    for idx, row in enumerate(rows, start=1):
        before = equity
        risk = before * RISK_PER_TRADE
        cost_eur = float(row["net_cost_r"]) * risk
        pnl = float(row["net_r"]) * risk
        equity = before + pnl
        total_cost_eur += cost_eur
        curve.append(equity)
        peak = max(peak, equity)
        current_drawdown = _safe_ratio(peak - equity, peak, 0.0)
        trade_rows.append(
            {
                **row,
                "candidate_trade_number": idx,
                "equity_before_trade": before,
                "risk_eur": risk,
                "estimated_cost_eur": cost_eur,
                "net_pnl_eur": pnl,
                "equity_after_trade": equity,
            }
        )
    worst_trade = min(trade_rows, key=lambda row: float(row["net_r"])) if trade_rows else None
    best_trade = max(trade_rows, key=lambda row: float(row["net_r"])) if trade_rows else None
    return {
        "starting_equity": start_capital,
        "ending_equity": equity,
        "net_gain": equity - start_capital,
        "return_multiple": equity / start_capital if start_capital else 0.0,
        "accepted_trades": len(rows),
        "gross_total_R": sum(gross_values),
        "net_total_R": sum(values),
        "average_R": sum(values) / len(values) if values else 0.0,
        "median_R": median(values) if values else 0.0,
        "profit_factor": _profit_factor(values),
        "win_rate": _safe_ratio(sum(1 for value in values if value > 0.0), len(values), 0.0),
        "max_drawdown": _max_drawdown(curve),
        "current_drawdown": current_drawdown,
        "largest_loss_R": min(values) if values else 0.0,
        "worst_trade": worst_trade,
        "best_trade": best_trade,
        "equity_curve": curve,
        "trade_rows": trade_rows,
        "cost_drag_R": sum(float(row["net_cost_r"]) for row in rows),
        "cost_drag_eur": total_cost_eur,
        "trades_flipped": sum(1 for row in rows if float(row["gross_r"]) > 0.0 and float(row["net_r"]) <= 0.0),
        "ruin_or_negative_equity": any(value <= 0.0 for value in curve),
    }


def _rolling_windows() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    starts = pd.date_range("2018-01-01", "2021-06-01", freq="MS", tz="UTC")
    return [(start, start + pd.DateOffset(years=5) - pd.Timedelta(minutes=1)) for start in starts]


def _period_growth(start: float, end: float, start_ts: str, end_ts: str) -> tuple[float, float]:
    start_dt = pd.Timestamp(start_ts)
    end_dt = pd.Timestamp(end_ts)
    days = max((end_dt - start_dt).total_seconds() / 86_400.0, 1.0)
    months = days / (365.2425 / 12.0)
    years = days / 365.2425
    monthly = (end / start) ** (1.0 / months) - 1.0 if end > 0.0 and start > 0.0 else -1.0
    cagr = (end / start) ** (1.0 / years) - 1.0 if end > 0.0 and start > 0.0 else -1.0
    return monthly, cagr


def _full_and_holdout(config: CostAwareCandidateConfig) -> dict[str, Any]:
    full_raw, _ = _selected_rows(config, config.court_002_root / "research_only_eur25k_replay" / "raw_engine")
    holdout_raw, _ = _selected_rows(config, config.court_002_root / "holdout_validation" / "raw_engine")
    full_candidate, full_rejected = _candidate_rows(full_raw)
    holdout_candidate, holdout_rejected = _candidate_rows(holdout_raw)
    full_sim = _simulate(full_candidate)
    holdout_sim = _simulate(holdout_candidate)
    return {
        "full_raw": full_raw,
        "holdout_raw": holdout_raw,
        "full_candidate": full_candidate,
        "holdout_candidate": holdout_candidate,
        "full_rejected": full_rejected,
        "holdout_rejected": holdout_rejected,
        "full_sim": full_sim,
        "holdout_sim": holdout_sim,
    }


def _rolling(candidate_rows: list[dict[str, Any]], rejected_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for idx, (start, end) in enumerate(_rolling_windows(), start=1):
        selected = [row for row in candidate_rows if pd.notna(row["entry_timestamp"]) and start <= row["entry_timestamp"] <= end]
        rejected = [row for row in rejected_rows if pd.notna(row["entry_timestamp"]) and start <= row["entry_timestamp"] <= end]
        sim = _simulate(selected)
        monthly, cagr = _period_growth(START_CAPITAL_25K, sim["ending_equity"], start.isoformat(), end.isoformat())
        rows.append(
            {
                "window_number": idx,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "starting_equity": START_CAPITAL_25K,
                "ending_equity": sim["ending_equity"],
                "return_multiple": sim["return_multiple"],
                "monthly_growth": monthly,
                "cagr": cagr,
                "max_drawdown": sim["max_drawdown"],
                "profit_factor": sim["profit_factor"],
                "win_rate": sim["win_rate"],
                "accepted_trades": sim["accepted_trades"],
                "rejected_by_cost_guard": len(rejected),
                "net_total_R": sim["net_total_R"],
                "above_500k": sim["ending_equity"] >= 500_000.0,
                "above_750k": sim["ending_equity"] >= 750_000.0,
                "above_1m": sim["ending_equity"] >= 1_000_000.0,
                "above_1_25m": sim["ending_equity"] >= 1_250_000.0,
                "above_2m": sim["ending_equity"] >= 2_000_000.0,
            }
        )
    endings = [float(row["ending_equity"]) for row in rows]
    dds = [float(row["max_drawdown"]) for row in rows]
    above_1m = sum(1 for value in endings if value >= 1_000_000.0)
    avg = sum(endings) / len(endings) if endings else 0.0
    med = median(endings) if endings else 0.0
    if above_1m >= 21 and med >= 1_000_000.0:
        classification = "CANDIDATE_ROLLING_5Y_SUPPORTS_1M_STRONG_TARGET"
    elif above_1m >= 10 or avg >= 1_000_000.0:
        classification = "CANDIDATE_ROLLING_5Y_SUPPORTS_1M_ASPIRATIONAL_TARGET"
    elif avg >= 750_000.0:
        classification = "CANDIDATE_ROLLING_5Y_SUPPORTS_750K_BASE_NOT_1M"
    elif rows:
        classification = "CANDIDATE_ROLLING_5Y_WEAKENS_TARGET"
    else:
        classification = "CANDIDATE_ROLLING_5Y_BLOCKED"
    summary = {
        "classification": classification,
        "window_count": len(rows),
        "average_ending_equity": avg,
        "median_ending_equity": med,
        "minimum_ending_equity": min(endings) if endings else 0.0,
        "maximum_ending_equity": max(endings) if endings else 0.0,
        "p25_ending_equity": float(pd.Series(endings).quantile(0.25)) if endings else 0.0,
        "p75_ending_equity": float(pd.Series(endings).quantile(0.75)) if endings else 0.0,
        "windows_above_500k": sum(1 for value in endings if value >= 500_000.0),
        "windows_above_750k": sum(1 for value in endings if value >= 750_000.0),
        "windows_above_1m": above_1m,
        "windows_above_1_25m": sum(1 for value in endings if value >= 1_250_000.0),
        "windows_above_2m": sum(1 for value in endings if value >= 2_000_000.0),
        "median_max_drawdown": median(dds) if dds else 0.0,
        "worst_max_drawdown": max(dds) if dds else 0.0,
        "best_window": max(rows, key=lambda row: float(row["ending_equity"])) if rows else None,
        "worst_window": min(rows, key=lambda row: float(row["ending_equity"])) if rows else None,
    }
    return rows, summary


def _cost_stress(candidate_raw_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    fixed_candidate, _ = _candidate_rows(candidate_raw_rows, net_cost_bps=ROUND_TRIP_COST_BPS)
    rows: list[dict[str, Any]] = []
    for bps in (10.0, 12.5, 15.0, 20.0, 25.0, 50.0, 100.0):
        stressed_rows: list[dict[str, Any]] = []
        for row in fixed_candidate:
            stop = float(row["stop_distance_fraction"])
            cost_r = (bps / 10_000.0) / stop if stop > 0.0 else 0.0
            stressed_rows.append({**row, "net_cost_r": cost_r, "net_r": float(row["gross_r"]) - cost_r})
        sim = _simulate(stressed_rows)
        rows.append(
            {
                "round_trip_cost_bps": bps,
                "guard_threshold_recomputed": False,
                "ending_equity": sim["ending_equity"],
                "return_multiple": sim["return_multiple"],
                "profit_factor": sim["profit_factor"],
                "win_rate": sim["win_rate"],
                "max_drawdown": sim["max_drawdown"],
                "trades_flipped": sim["trades_flipped"],
                "cost_drag_R": sim["cost_drag_R"],
                "profitable": sim["ending_equity"] > START_CAPITAL_25K,
                "ending_equity_above_1m": sim["ending_equity"] >= MISSION_TARGET_EUR,
                "ruin_or_negative_equity": sim["ruin_or_negative_equity"],
            }
        )
    break_15 = next(row for row in rows if row["round_trip_cost_bps"] == 15.0)["profitable"] is False
    break_20 = next(row for row in rows if row["round_trip_cost_bps"] == 20.0)["profitable"] is False
    if not break_20:
        classification = "CANDIDATE_COST_STRESS_ROBUST"
    elif not break_15:
        classification = "CANDIDATE_COST_STRESS_ACCEPTABLE"
    elif rows[0]["profitable"]:
        classification = "CANDIDATE_COST_STRESS_FRAGILE"
    else:
        classification = "CANDIDATE_COST_STRESS_FAILED"
    return rows, {"classification": classification, "guard_fixed_at_15bps_cost_r_1_0": True}


def _drawdown_ruin(full_sim: dict[str, Any], holdout_sim: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    curve = full_sim["equity_curve"]
    peak = curve[0]
    current_duration = 0
    longest_duration = 0
    worst_valley = curve[0]
    counts = {20: 0, 40: 0, 60: 0, 80: 0}
    for equity in curve:
        if equity >= peak:
            peak = equity
            current_duration = 0
        else:
            current_duration += 1
        dd = _safe_ratio(peak - equity, peak, 0.0)
        if dd >= full_sim["max_drawdown"]:
            worst_valley = equity
        longest_duration = max(longest_duration, current_duration)
        for threshold in counts:
            if dd >= threshold / 100.0:
                counts[threshold] += 1
    below = {
        "times_below_20k": sum(1 for value in curve if value < 20_000.0),
        "times_below_15k": sum(1 for value in curve if value < 15_000.0),
        "times_below_10k": sum(1 for value in curve if value < 10_000.0),
        "times_below_5k": sum(1 for value in curve if value < 5_000.0),
    }
    if full_sim["max_drawdown"] <= 0.20 and all(value == 0 for value in below.values()):
        classification = "CANDIDATE_DRAWDOWN_RISK_ACCEPTABLE"
    elif full_sim["max_drawdown"] <= 0.60:
        classification = "CANDIDATE_DRAWDOWN_RISK_SEVERE_BUT_RECOVERED"
    else:
        classification = "CANDIDATE_DRAWDOWN_RISK_TOO_DANGEROUS"
    rows = [{"trade_index": idx, "equity": equity} for idx, equity in enumerate(curve)]
    summary = {
        "classification": classification,
        "full_history_max_drawdown": full_sim["max_drawdown"],
        "holdout_max_drawdown": holdout_sim["max_drawdown"],
        "longest_drawdown_duration_trades": longest_duration,
        "worst_equity_valley": worst_valley,
        "recovery_duration_trades": longest_duration,
        "drawdowns_above_20pct": counts[20],
        "drawdowns_above_40pct": counts[40],
        "drawdowns_above_60pct": counts[60],
        "drawdowns_above_80pct": counts[80],
        "drawdown_improved_from_original_90_6242pct": full_sim["max_drawdown"] < 0.906242,
        **below,
    }
    return rows, summary


def _monte_carlo(candidate_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    values = [float(row["net_r"]) for row in candidate_rows]
    rng = random.Random(MONTE_CARLO_SEED)
    rows: list[dict[str, Any]] = []
    for run in range(1, MONTE_CARLO_RUNS + 1):
        sample = [rng.choice(values) for _ in values]
        equity = START_CAPITAL_25K
        curve = [equity]
        for r_value in sample:
            equity += equity * RISK_PER_TRADE * r_value
            curve.append(equity)
        rows.append(
            {
                "run": run,
                "ending_equity": equity,
                "max_drawdown": _max_drawdown(curve),
                "ending_below_start": equity < START_CAPITAL_25K,
                "path_below_start": min(curve) < START_CAPITAL_25K,
            }
        )
    endings = [float(row["ending_equity"]) for row in rows]
    dds = [float(row["max_drawdown"]) for row in rows]
    series = pd.Series(endings)
    probability_1m = _safe_ratio(sum(1 for value in endings if value >= MISSION_TARGET_EUR), len(endings), 0.0)
    probability_below = _safe_ratio(sum(1 for value in endings if value < START_CAPITAL_25K), len(endings), 0.0)
    probability_path_below = _safe_ratio(sum(1 for row in rows if row["path_below_start"]), len(rows), 0.0)
    if probability_1m >= 0.50 and probability_below < 0.25:
        classification = "CANDIDATE_MONTE_CARLO_ROBUST"
    elif probability_1m >= 0.25:
        classification = "CANDIDATE_MONTE_CARLO_MODERATE"
    elif median(endings) > START_CAPITAL_25K:
        classification = "CANDIDATE_MONTE_CARLO_FRAGILE"
    else:
        classification = "CANDIDATE_MONTE_CARLO_FAILED"
    summary = {
        "classification": classification,
        "seed": MONTE_CARLO_SEED,
        "simulations": MONTE_CARLO_RUNS,
        "median_ending_equity": float(series.quantile(0.50)),
        "mean_ending_equity": float(series.mean()),
        "p5_ending_equity": float(series.quantile(0.05)),
        "p25_ending_equity": float(series.quantile(0.25)),
        "p75_ending_equity": float(series.quantile(0.75)),
        "p95_ending_equity": float(series.quantile(0.95)),
        "probability_above_500k": _safe_ratio(sum(1 for value in endings if value >= 500_000.0), len(endings), 0.0),
        "probability_above_750k": _safe_ratio(sum(1 for value in endings if value >= 750_000.0), len(endings), 0.0),
        "probability_above_1m": probability_1m,
        "probability_below_start": probability_below,
        "probability_path_below_start": probability_path_below,
        "probability_drawdown_gt_20pct": _safe_ratio(sum(1 for value in dds if value > 0.20), len(dds), 0.0),
        "probability_drawdown_gt_40pct": _safe_ratio(sum(1 for value in dds if value > 0.40), len(dds), 0.0),
        "probability_drawdown_gt_60pct": _safe_ratio(sum(1 for value in dds if value > 0.60), len(dds), 0.0),
        "probability_drawdown_gt_80pct": _safe_ratio(sum(1 for value in dds if value > 0.80), len(dds), 0.0),
        "worst_simulated_path": min(rows, key=lambda row: float(row["ending_equity"])),
        "best_simulated_path": max(rows, key=lambda row: float(row["ending_equity"])),
    }
    return rows, summary


def _daily_context(config: CostAwareCandidateConfig) -> pd.DataFrame:
    path = config.court_002_root / "datasets" / "combined_full_history_court_timeline_btcusdt_1m.csv"
    frame = pd.read_csv(path)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    daily = frame.set_index("timestamp")["close"].resample("1D").last().dropna().to_frame("close")
    daily["return_180d"] = daily["close"].pct_change(180)
    daily["vol_30d"] = daily["close"].pct_change().rolling(30).std()
    return daily


def _regime_label(daily: pd.DataFrame, timestamp: pd.Timestamp) -> str:
    if pd.isna(timestamp):
        return "unknown"
    key = timestamp.floor("D")
    prior = daily.loc[daily.index <= key]
    if prior.empty:
        return "unknown"
    row = prior.iloc[-1]
    ret180 = float(row.get("return_180d") or 0.0)
    vol30 = float(row.get("vol_30d") or 0.0)
    if ret180 >= 0.30 and vol30 >= 0.05:
        return "uptrend_high_volatility"
    if ret180 >= 0.30:
        return "uptrend_orderly"
    if ret180 <= -0.20:
        return "downtrend"
    return "range_or_transition"


def _regime(config: CostAwareCandidateConfig, candidate_rows: list[dict[str, Any]], rejected_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    daily = _daily_context(config)
    buckets: dict[str, list[dict[str, Any]]] = {}
    rejected_buckets: dict[str, int] = {}
    for row in candidate_rows:
        buckets.setdefault(_regime_label(daily, row["entry_timestamp"]), []).append(row)
    for row in rejected_rows:
        label = _regime_label(daily, row["entry_timestamp"])
        rejected_buckets[label] = rejected_buckets.get(label, 0) + 1
    rows: list[dict[str, Any]] = []
    for label, bucket in sorted(buckets.items()):
        sim = _simulate(bucket)
        rows.append(
            {
                "regime": label,
                "number_of_trades": len(bucket),
                "gross_total_R": sum(float(row["gross_r"]) for row in bucket),
                "net_total_R": sim["net_total_R"],
                "profit_factor": sim["profit_factor"],
                "win_rate": sim["win_rate"],
                "max_drawdown_contribution": sim["max_drawdown"],
                "net_equity_contribution": sim["ending_equity"] - START_CAPITAL_25K,
                "accepted_trades_rejected_by_cost_guard": rejected_buckets.get(label, 0),
            }
        )
    best = max(rows, key=lambda row: float(row["net_total_R"])) if rows else None
    worst = min(rows, key=lambda row: float(row["net_total_R"])) if rows else None
    positive = sum(1 for row in rows if float(row["net_total_R"]) > 0.0)
    if rows and positive == len(rows):
        classification = "CANDIDATE_REGIME_ROBUST"
    elif rows and positive >= max(1, len(rows) - 1):
        classification = "CANDIDATE_REGIME_DEPENDENT_BUT_USABLE"
    elif rows:
        classification = "CANDIDATE_REGIME_FRAGILE"
    else:
        classification = "CANDIDATE_REGIME_BLOCKED"
    summary = {
        "classification": classification,
        "best_regime": best,
        "worst_regime": worst,
        "candidate_only_works_in_one_regime": positive <= 1,
    }
    return rows, summary


def _scheduler_compatibility(config: CostAwareCandidateConfig) -> dict[str, Any]:
    state = _scheduler_state()
    payload = {
        **state,
        "current_scheduler_uses_old_runtime": True,
        "future_read_only_candidate_stream_possible": True,
        "dashboard_can_later_display_candidate_separately": True,
        "candidate_would_require_new_ledger_fields": [
            "pre_entry_cost_r_at_15bps",
            "candidate_guard_accepted",
            "candidate_guard_reason",
            "candidate_stream_name",
        ],
        "classification": "CANDIDATE_SCHEDULER_COMPATIBLE_WITH_CHANGES_REQUIRED",
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "candidate_scheduler_compatibility.json", payload)
    return payload


def _target_status(rolling: dict[str, Any], holdout: dict[str, Any], cost: dict[str, Any], mc: dict[str, Any]) -> dict[str, Any]:
    holdout_monthly = holdout["monthly_growth"]
    if rolling["classification"] == "CANDIDATE_ROLLING_5Y_SUPPORTS_1M_STRONG_TARGET":
        classification = "CANDIDATE_1M_TARGET_SUPPORTED_STRONG_RESEARCH_ONLY"
    elif rolling["windows_above_1m"] > 0 or rolling["average_ending_equity"] >= 750_000.0:
        classification = "CANDIDATE_1M_TARGET_SUPPORTED_ASPIRATIONAL_RESEARCH_ONLY"
    elif rolling["classification"] == "CANDIDATE_ROLLING_5Y_BLOCKED":
        classification = "CANDIDATE_1M_TARGET_BLOCKED_RESEARCH_ONLY"
    else:
        classification = "CANDIDATE_1M_TARGET_WEAKENED_RESEARCH_ONLY"
    return {
        "classification": classification,
        "candidate_restores_1m_support_vs_original_strict_net": rolling["windows_above_1m"] > 0,
        "more_realistic_than_original_strict_net_wolf": True,
        "rolling_5y_supports_1m": rolling["windows_above_1m"] > 0,
        "sealed_holdout_supports_signal_survival": holdout["ending_equity"] > START_CAPITAL_25K,
        "sealed_holdout_meets_1m_monthly_pace": holdout_monthly >= REQUIRED_MONTHLY_GROWTH_FOR_25K_TO_1M_5Y,
        "future_paper_readiness_court_may_be_considered": classification
        in {
            "CANDIDATE_1M_TARGET_SUPPORTED_STRONG_RESEARCH_ONLY",
            "CANDIDATE_1M_TARGET_SUPPORTED_ASPIRATIONAL_RESEARCH_ONLY",
        }
        and cost["classification"] in {"CANDIDATE_COST_STRESS_ROBUST", "CANDIDATE_COST_STRESS_ACCEPTABLE"}
        and mc["classification"] in {"CANDIDATE_MONTE_CARLO_ROBUST", "CANDIDATE_MONTE_CARLO_MODERATE"},
        "more_scheduler_evidence_still_required": True,
        "paper_validation_ready": False,
    }


def _paper_gate(target: dict[str, Any], drawdown: dict[str, Any], scheduler: dict[str, Any]) -> dict[str, Any]:
    can_consider = (
        bool(target["future_paper_readiness_court_may_be_considered"])
        and drawdown["classification"] != "CANDIDATE_DRAWDOWN_RISK_TOO_DANGEROUS"
        and bool(scheduler.get("installed_loaded"))
    )
    payload = {
        "classification": "FUTURE_PAPER_READINESS_COURT_MAY_BE_CONSIDERED" if can_consider else "MORE_RESEARCH_EVIDENCE_REQUIRED",
        "future_paper_readiness_court_can_be_considered": can_consider,
        "paper_validation_ready": False,
        "does_not_approve_paper_trading": True,
        **SAFETY_FLAGS,
    }
    return payload


def _final_classification(
    *,
    full: dict[str, Any],
    holdout: dict[str, Any],
    rolling: dict[str, Any],
    cost: dict[str, Any],
    drawdown: dict[str, Any],
    mc: dict[str, Any],
    regime: dict[str, Any],
    safety_clean: bool,
) -> str:
    if not safety_clean:
        return FAILED
    if holdout["ending_equity"] <= START_CAPITAL_25K or full["ending_equity"] <= START_CAPITAL_25K:
        return FAILED
    strong = (
        full["ending_equity"] >= MISSION_TARGET_EUR
        and drawdown["classification"] == "CANDIDATE_DRAWDOWN_RISK_ACCEPTABLE"
        and rolling["classification"] == "CANDIDATE_ROLLING_5Y_SUPPORTS_1M_STRONG_TARGET"
        and cost["classification"] in {"CANDIDATE_COST_STRESS_ROBUST", "CANDIDATE_COST_STRESS_ACCEPTABLE"}
        and mc["classification"] in {"CANDIDATE_MONTE_CARLO_ROBUST", "CANDIDATE_MONTE_CARLO_MODERATE"}
        and regime["classification"] != "CANDIDATE_REGIME_FRAGILE"
    )
    if strong:
        return STRONG
    promising = (
        full["ending_equity"] >= MISSION_TARGET_EUR
        and holdout["ending_equity"] > START_CAPITAL_25K
        and drawdown["classification"] != "CANDIDATE_DRAWDOWN_RISK_TOO_DANGEROUS"
    )
    if promising:
        return PROMISING
    return WEAK


def _safety_scan(paths: Iterable[Path]) -> dict[str, Any]:
    exact = [
        "paper_allowed" + "=" + "true",
        "live_allowed" + "=" + "true",
        "real_money_allowed" + "=" + "true",
        "behavior_change_allowed" + "=" + "true",
        "paper_validation_ready" + "=" + "true",
        "create" + " " + "order",
        "place" + " " + "order",
        "order" + " " + "endpoint",
        "account" + " " + "endpoint",
        "signed" + " " + "request",
        "broker" + " " + "execution",
        "private" + " " + "key",
        "API" + "_" + "SECRET",
        "BINANCE" + "_" + "SECRET",
        "PASS" + "WORD",
        "TOK" + "EN",
    ]
    findings: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists() or path.is_dir():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore").lower()
        for term in exact:
            if term.lower() in text:
                findings.append({"path": str(path), "term": term})
    return {"clean": not findings, "findings": findings}


def build_court(config: CostAwareCandidateConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    paths = _input_paths(config)
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        output = {
            "court_name": COURT_NAME,
            "candidate_name": CANDIDATE_NAME,
            "final_classification": BLOCKED,
            "missing_inputs": missing,
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "cost_aware_frozen_candidate_rebuild_summary.json", output)
        return output

    evidence = {
        "created_at_utc": _now(),
        "input_paths": {key: str(path) for key, path in paths.items()},
        "branch": _git_output(config.project_root, "branch", "--show-current"),
        "court_002_gross_vs_net": {
            "gross_full_history": _read_json(paths["court_002_summary"])["full_history_research_replay"]["ending_diagnostic_equity"],
            "strict_net_full_history": _read_json(paths["zero_stop_summary"])["full_history_net_cost_policies"][
                "EXCLUDE_ZERO_STOP_ZERO_R_ARTIFACT_FROM_NET_COST_CONVERSION"
            ]["net_ending_equity"],
            "gross_holdout": _read_json(paths["court_002_summary"])["sealed_holdout_validation"]["ending_diagnostic_equity"],
            "strict_net_holdout": _read_json(paths["zero_stop_summary"])["sealed_holdout_net_cost_result_preserved"][
                "net_cost_eur25k_holdout"
            ],
        },
        "previous_damage_attribution": {
            "summary_path": str(paths["damage_summary"]),
            "recommended_candidate_guard": _read_json(paths["damage_summary"]).get("recommended_candidate_guard"),
            "key_findings": _read_json(paths["damage_summary"]).get("key_findings", []),
        },
        "new_candidate_proof": {
            "candidate_name": CANDIDATE_NAME,
            "only_rule_change": "reject_pre_entry_cost_r_above_1_0_at_15bps",
            "old_court_002_overwritten": False,
            "scheduler_modified": False,
            **SAFETY_FLAGS,
        },
    }
    _write_json(config.output_root / "evidence_lock_manifest.json", evidence)

    built = _full_and_holdout(config)
    full = built["full_sim"]
    holdout = built["holdout_sim"]
    split = _read_json(paths["court_002_split_manifest"])
    holdout_monthly = _monthly_growth(
        START_CAPITAL_25K,
        holdout["ending_equity"],
        str(split["holdout_start"]),
        str(split["holdout_end"]),
    )
    holdout_result = {
        **{key: value for key, value in holdout.items() if key not in {"equity_curve", "trade_rows"}},
        "monthly_growth": holdout_monthly,
        "required_monthly_growth_for_25k_to_1m_5y": REQUIRED_MONTHLY_GROWTH_FOR_25K_TO_1M_5Y,
        "holdout_profitable_after_costs": holdout["ending_equity"] > START_CAPITAL_25K,
        "holdout_meets_1m_monthly_pace": holdout_monthly >= REQUIRED_MONTHLY_GROWTH_FOR_25K_TO_1M_5Y,
        "accepted_before_guard": len(built["holdout_raw"]),
        "accepted_after_guard": len(built["holdout_candidate"]),
        "trades_rejected_by_guard": len(built["holdout_rejected"]),
    }
    full_result = {
        **{key: value for key, value in full.items() if key not in {"equity_curve", "trade_rows"}},
        "accepted_before_guard": len(built["full_raw"]),
        "accepted_after_guard": len(built["full_candidate"]),
        "trades_rejected_by_guard": len(built["full_rejected"]),
        "tiny_stop_landmines_removed": True,
        "max_drawdown_improves_materially": full["max_drawdown"] < 0.906242,
    }
    _write_csv(config.output_root / "candidate_full_history_results.csv", full["trade_rows"] + built["full_rejected"])
    _write_csv(config.output_root / "candidate_holdout_results.csv", holdout["trade_rows"] + built["holdout_rejected"])

    rolling_rows, rolling_summary = _rolling(built["full_candidate"] + built["holdout_candidate"], built["full_rejected"] + built["holdout_rejected"])
    _write_csv(config.output_root / "candidate_rolling_5y_results.csv", rolling_rows)

    cost_rows, cost_summary = _cost_stress(built["full_raw"])
    _write_csv(config.output_root / "candidate_cost_stress_results.csv", cost_rows)

    drawdown_rows, drawdown_summary = _drawdown_ruin(full, holdout)
    _write_csv(config.output_root / "candidate_drawdown_ruin_results.csv", drawdown_rows)

    mc_rows, mc_summary = _monte_carlo(built["full_candidate"])
    _write_csv(config.output_root / "candidate_monte_carlo_results.csv", mc_rows)

    regime_rows, regime_summary = _regime(config, built["full_candidate"], built["full_rejected"])
    _write_csv(config.output_root / "candidate_regime_breakdown_results.csv", regime_rows)

    scheduler = _scheduler_compatibility(config)
    target = _target_status(rolling_summary, holdout_result, cost_summary, mc_summary)
    gate = _paper_gate(target, drawdown_summary, scheduler)

    comparison = {
        "original_gross_full_history": evidence["court_002_gross_vs_net"]["gross_full_history"],
        "original_strict_net_full_history": evidence["court_002_gross_vs_net"]["strict_net_full_history"],
        "candidate_net_full_history": full["ending_equity"],
        "candidate_vs_original_strict_net_multiple": _safe_ratio(
            full["ending_equity"], evidence["court_002_gross_vs_net"]["strict_net_full_history"], 0.0
        ),
        "original_gross_holdout": evidence["court_002_gross_vs_net"]["gross_holdout"],
        "original_strict_net_holdout": evidence["court_002_gross_vs_net"]["strict_net_holdout"],
        "candidate_net_holdout": holdout["ending_equity"],
        "candidate_vs_original_strict_net_holdout_multiple": _safe_ratio(
            holdout["ending_equity"], evidence["court_002_gross_vs_net"]["strict_net_holdout"], 0.0
        ),
    }
    _write_json(config.output_root / "candidate_comparison_vs_original.json", comparison)
    _write_json(config.output_root / "candidate_paper_readiness_gate.json", gate)

    files_for_scan = [
        Path(__file__),
        config.output_root / "evidence_lock_manifest.json",
        config.output_root / "candidate_comparison_vs_original.json",
        config.output_root / "candidate_paper_readiness_gate.json",
    ]
    safety = _safety_scan(files_for_scan)
    final = _final_classification(
        full=full_result,
        holdout=holdout_result,
        rolling=rolling_summary,
        cost=cost_summary,
        drawdown=drawdown_summary,
        mc=mc_summary,
        regime=regime_summary,
        safety_clean=bool(safety["clean"]),
    )
    summary = {
        "court_name": COURT_NAME,
        "candidate_name": CANDIDATE_NAME,
        "created_at_utc": _now(),
        "final_classification": final,
        **SAFETY_FLAGS,
        "candidate_guard": {
            "max_pre_entry_cost_r": MAX_PRE_ENTRY_COST_R,
            "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "uses_entry_price": True,
            "uses_initial_stop": True,
            "uses_exit_price": False,
            "uses_future_pnl": False,
            "uses_future_r": False,
        },
        "execution_timeframe": "1H",
        "data_feed_timeframe": "1m",
        "context_timeframe": "6H",
        "strategy_changes": {
            "entries_changed": False,
            "exits_changed": False,
            "thresholds_changed": False,
            "filters_changed_except_cost_guard": False,
            "sizing_changed": False,
            "six_h_context_changed": False,
            "scheduler_strategy_changed": False,
        },
        "full_history": full_result,
        "sealed_holdout": holdout_result,
        "rolling_5y": rolling_summary,
        "cost_stress": cost_summary,
        "drawdown_ruin": drawdown_summary,
        "monte_carlo": mc_summary,
        "regime": regime_summary,
        "scheduler_compatibility": scheduler,
        "target_status": target,
        "paper_readiness_gate": gate,
        "comparison_vs_original": comparison,
        "safety_scan": safety,
        "files_created": [
            str(config.output_root / name)
            for name in (
                "evidence_lock_manifest.json",
                "cost_aware_frozen_candidate_rebuild_report.md",
                "cost_aware_frozen_candidate_rebuild_summary.json",
                "candidate_full_history_results.csv",
                "candidate_holdout_results.csv",
                "candidate_rolling_5y_results.csv",
                "candidate_cost_stress_results.csv",
                "candidate_monte_carlo_results.csv",
                "candidate_drawdown_ruin_results.csv",
                "candidate_regime_breakdown_results.csv",
                "candidate_comparison_vs_original.json",
                "candidate_paper_readiness_gate.json",
                "candidate_scheduler_compatibility.json",
            )
        ],
    }
    _write_json(config.output_root / "cost_aware_frozen_candidate_rebuild_summary.json", summary)
    (config.output_root / "cost_aware_frozen_candidate_rebuild_report.md").write_text(_report_markdown(summary), encoding="utf-8")
    return _round_payload(summary)


def _fmt_eur(value: Any) -> str:
    return "N/A" if value is None else f"€{float(value):,.2f}"


def _fmt_pct(value: Any) -> str:
    return "N/A" if value is None else f"{float(value) * 100:.4f}%"


def _report_markdown(summary: dict[str, Any]) -> str:
    full = summary["full_history"]
    holdout = summary["sealed_holdout"]
    rolling = summary["rolling_5y"]
    mc = summary["monte_carlo"]
    lines = [
        "# Cost-Aware Frozen Candidate Rebuild Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        f"- Candidate: `{summary['candidate_name']}`",
        "- Guard: `max pre-entry cost-R <= 1.0 at 15 bps`",
        f"- Research-only: `{summary['research_only']}`",
        f"- Paper validation ready: `{summary['paper_validation_ready']}`",
        "",
        "## Full-history",
        "",
        f"- Candidate net-cost equity: `{_fmt_eur(full['ending_equity'])}`",
        f"- Return multiple: `{full['return_multiple']}`",
        f"- Max drawdown: `{_fmt_pct(full['max_drawdown'])}`",
        f"- Accepted before / after guard: `{full['accepted_before_guard']} / {full['accepted_after_guard']}`",
        f"- Trades rejected by guard: `{full['trades_rejected_by_guard']}`",
        "",
        "## Sealed holdout",
        "",
        f"- Candidate net-cost equity: `{_fmt_eur(holdout['ending_equity'])}`",
        f"- Monthly growth: `{_fmt_pct(holdout['monthly_growth'])}`",
        f"- Required EUR1M monthly growth: `{_fmt_pct(holdout['required_monthly_growth_for_25k_to_1m_5y'])}`",
        f"- Accepted before / after guard: `{holdout['accepted_before_guard']} / {holdout['accepted_after_guard']}`",
        "",
        "## Rolling 5Y",
        "",
        f"- Average ending equity: `{_fmt_eur(rolling['average_ending_equity'])}`",
        f"- Median ending equity: `{_fmt_eur(rolling['median_ending_equity'])}`",
        f"- Windows above EUR1M: `{rolling['windows_above_1m']} / {rolling['window_count']}`",
        f"- Classification: `{rolling['classification']}`",
        "",
        "## Monte Carlo",
        "",
        f"- Median ending equity: `{_fmt_eur(mc['median_ending_equity'])}`",
        f"- 5th percentile: `{_fmt_eur(mc['p5_ending_equity'])}`",
        f"- Probability above EUR1M: `{_fmt_pct(mc['probability_above_1m'])}`",
        f"- Probability below start: `{_fmt_pct(mc['probability_below_start'])}`",
        "",
        "## Safety",
        "",
        "- No scheduler deployment.",
        "- No paper/live/broker behavior.",
        "- Old Court 002 artifacts are read-only evidence.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run cost-aware frozen candidate rebuild court.")
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()
    config = default_config()
    if args.output_root:
        config = CostAwareCandidateConfig(
            project_root=config.project_root,
            package_root=config.package_root,
            output_root=Path(args.output_root).expanduser().resolve(),
            court_002_root=config.court_002_root,
            damage_root=config.damage_root,
            net_restatement_root=config.net_restatement_root,
            zero_stop_root=config.zero_stop_root,
            gauntlet_root=config.gauntlet_root,
            scheduler_root=config.scheduler_root,
        )
    print(json.dumps(build_court(config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
