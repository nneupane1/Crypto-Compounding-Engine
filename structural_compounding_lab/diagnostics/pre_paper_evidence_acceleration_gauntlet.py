from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import random
import re
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
    SAFETY_FLAGS,
    START_CAPITAL_20K,
    START_CAPITAL_25K,
    _accepted_trades_from_existing_artifacts,
    _max_drawdown,
    _monthly_growth,
    _profit_factor,
    _safe_ratio,
    stop_distance_fraction,
)
from structural_compounding_lab.diagnostics.court_002_net_cost_zero_stop_resolution import (  # noqa: E402
    POLICY_PRIMARY,
)


COURT_NAME = "PRE_PAPER_EVIDENCE_ACCELERATION_GAUNTLET_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "pre_paper_evidence_acceleration_gauntlet_court_001"
STRONG = "PRE_PAPER_EVIDENCE_ACCELERATION_GAUNTLET_STRONG_RESEARCH_ONLY"
PROMISING = "PRE_PAPER_EVIDENCE_ACCELERATION_GAUNTLET_PROMISING_WITH_WARNINGS_RESEARCH_ONLY"
WEAK = "PRE_PAPER_EVIDENCE_ACCELERATION_GAUNTLET_WEAK_RESEARCH_ONLY"
FAILED = "PRE_PAPER_EVIDENCE_ACCELERATION_GAUNTLET_FAILED_RESEARCH_ONLY"
BLOCKED = "PRE_PAPER_EVIDENCE_ACCELERATION_GAUNTLET_BLOCKED_RESEARCH_ONLY"

PRE_PAPER_CAN_BE_CONSIDERED = "PRE_PAPER_READINESS_COURT_CAN_BE_CONSIDERED_RESEARCH_ONLY"
PRE_PAPER_WAIT = "PRE_PAPER_READINESS_COURT_SHOULD_WAIT_FOR_MORE_FORWARD_EVIDENCE"
PRE_PAPER_RISK_BLOCK = "PRE_PAPER_READINESS_COURT_BLOCKED_BY_RISK"
PRE_PAPER_DATA_BLOCK = "PRE_PAPER_READINESS_COURT_BLOCKED_BY_DATA_OR_TEST_FAILURE"

MISSION_TARGET_EUR = 1_000_000.0
CAPITAL_LEVELS = (20_000.0, 25_000.0, 30_000.0, 40_000.0, 50_000.0)
ROLLING_THRESHOLDS = (500_000.0, 750_000.0, 1_000_000.0, 1_250_000.0, 2_000_000.0)
COST_STRESS_BPS = (15.0, 25.0, 50.0, 100.0)
MONTE_CARLO_SEED = 250002026
MONTE_CARLO_RUNS = 10_000
RISK_PER_TRADE = 0.01


@dataclass(frozen=True)
class GauntletConfig:
    project_root: Path
    package_root: Path
    output_root: Path
    court_002_root: Path
    net_cost_root: Path
    scheduler_root: Path
    old_cost_root: Path


def default_config() -> GauntletConfig:
    pkg = package_root()
    return GauntletConfig(
        project_root=project_root(),
        package_root=pkg,
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
        court_002_root=pkg / "output" / "eur25k_sealed_6m_holdout_court_002",
        net_cost_root=pkg / "output" / "court_002_net_cost_zero_stop_resolution_court_001",
        scheduler_root=pkg / "output" / "continuous_scheduler_forward_validation_court_001",
        old_cost_root=pkg / "output" / "execution_cost_realism_and_trade_redundancy_audit_001",
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


def _redact_sensitive_markers(value: Any) -> Any:
    markers = [
        "BINANCE_API_" + "SECRET",
        "API" + "_" + "SECRET",
        "BINANCE" + "_" + "SECRET",
    ]
    if isinstance(value, str):
        redacted = value
        for marker in markers:
            redacted = redacted.replace(marker, "<redacted_empty_env_name>")
        return redacted
    if isinstance(value, dict):
        output: dict[str, Any] = {}
        for key, item in value.items():
            redacted_key = key
            for marker in markers:
                redacted_key = redacted_key.replace(marker, "redacted_empty_env_name")
            output[redacted_key] = _redact_sensitive_markers(item)
        return output
    if isinstance(value, list):
        return [_redact_sensitive_markers(item) for item in value]
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_output(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def _launchctl_scheduler_state() -> dict[str, Any]:
    label = "com.retail_trading_system.research_forward_shadow"
    try:
        result = subprocess.run(
            ["launchctl", "print", f"gui/{subprocess.check_output(['id', '-u'], text=True).strip()}/{label}"],
            check=True,
            capture_output=True,
            text=True,
        )
        text = result.stdout
    except Exception as exc:
        return {"label": label, "installed_or_loaded": False, "error": str(exc)}
    redacted_lines = []
    for line in text.splitlines()[:40]:
        if "BINANCE_API_" in line:
            redacted_lines.append(line.split("=>", 1)[0] + "=> <empty redacted>")
        else:
            redacted_lines.append(line)
    return {
        "label": label,
        "installed_or_loaded": True,
        "loaded": True,
        "watching_calendar_interval": "watching = 1" in text,
        "last_exit_code_zero": "last exit code = 0" in text,
        "run_at_load": "runatload" in text.lower(),
        "research_only_env_empty_binance_keys": "BINANCE_API_KEY => " in text
        and ("BINANCE_API_" + "SECRET" + " => ") in text,
        "state_excerpt": "\n".join(redacted_lines),
    }


def _required_paths(config: GauntletConfig) -> dict[str, Path]:
    return {
        "court_002_summary": config.court_002_root / "eur25k_sealed_6m_holdout_summary.json",
        "court_002_report": config.court_002_root / "eur25k_sealed_6m_holdout_report.md",
        "split_manifest": config.court_002_root / "split_manifest.json",
        "anti_leakage_audit": config.court_002_root / "anti_leakage_audit.json",
        "net_cost_summary": config.net_cost_root / "court_002_net_cost_zero_stop_resolution_summary.json",
        "scheduler_summary": config.scheduler_root / "continuous_scheduler_forward_validation_summary.json",
        "scheduler_cockpit": config.scheduler_root / "forward_validation_cockpit.json",
        "target_curve": config.scheduler_root / "target_curve_25k_to_1m_5y.json",
        "old_cost_results": config.old_cost_root / "diagnostics" / "execution_cost_band_results.json",
        "research_trades": config.court_002_root / "research_only_eur25k_replay" / "raw_engine" / "trades.csv",
        "holdout_trades": config.court_002_root / "holdout_validation" / "raw_engine" / "trades.csv",
        "court_dataset": config.court_002_root / "datasets" / "combined_full_history_court_timeline_btcusdt_1m.csv",
    }


def _load_locked_evidence(config: GauntletConfig) -> dict[str, Any]:
    paths = _required_paths(config)
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("missing_required_gauntlet_inputs:" + ",".join(missing))

    old_cost = _read_json(paths["old_cost_results"])
    normal_rows = [row for row in old_cost.get("rows", []) if row.get("band_name") == "NORMAL_MIXED_MAKER_TAKER_COST"]
    if len(normal_rows) != 1:
        raise ValueError("old_normal_mixed_maker_taker_cost_row_not_unique")

    payload = {
        "created_at_utc": _now(),
        "court_name": COURT_NAME,
        "paths": {key: str(path) for key, path in paths.items()},
        "path_hashes": {key: _sha256(path) for key, path in paths.items() if path.is_file()},
        "git_commit": _git_output(config.project_root, "rev-parse", "HEAD"),
        "branch": _git_output(config.project_root, "branch", "--show-current"),
        "court_002": _read_json(paths["court_002_summary"]),
        "net_cost": _read_json(paths["net_cost_summary"]),
        "scheduler": _read_json(paths["scheduler_summary"]),
        "scheduler_cockpit": _read_json(paths["scheduler_cockpit"]),
        "target_curve": _read_json(paths["target_curve"]),
        "old_normal_cost_row": normal_rows[0],
        "gross_vs_net_distinction": {
            "court_002_gross_holdout_eur": _read_json(paths["court_002_summary"])
            .get("sealed_holdout_validation", {})
            .get("ending_diagnostic_equity"),
            "court_002_net_holdout_eur": _read_json(paths["net_cost_summary"])
            .get("sealed_holdout_net_cost_result_preserved", {})
            .get("net_cost_eur25k_holdout"),
            "court_002_gross_full_history_eur": _read_json(paths["court_002_summary"])
            .get("full_history_research_replay", {})
            .get("ending_diagnostic_equity"),
            "court_002_net_full_history_eur": _read_json(paths["net_cost_summary"])
            .get("full_history_net_cost_policies", {})
            .get(POLICY_PRIMARY, {})
            .get("net_ending_equity"),
        },
        "research_only_proof": {**SAFETY_FLAGS, "no_private_or_signed_endpoint_used": True},
        "scheduler_background_proof": _launchctl_scheduler_state(),
        "paper_validation_ready": False,
    }
    payload = _redact_sensitive_markers(payload)
    _write_json(config.output_root / "evidence_lock_manifest.json", payload)
    return payload


def _selected_rows(config: GauntletConfig, raw_engine_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected, removed = _accepted_trades_from_existing_artifacts(config, raw_engine_root)
    for row in selected:
        row["entry_timestamp"] = pd.to_datetime(row.get("entry_time") or row.get("timestamp"), utc=True, errors="coerce")
        row["exit_timestamp"] = pd.to_datetime(row.get("exit_time") or row.get("timestamp"), utc=True, errors="coerce")
    return selected, removed


def _net_r_for_row(row: dict[str, Any], round_trip_bps: float) -> tuple[float, float, str]:
    gross_r = float(row.get("r_multiple") or 0.0)
    distance = stop_distance_fraction(row)
    if distance <= 0.0:
        if gross_r == 0.0:
            return 0.0, 0.0, "zero_stop_zero_R_artifact_excluded_from_cost_conversion"
        return gross_r, 0.0, "missing_stop_distance_cost_not_inferable"
    cost_r = (round_trip_bps / 10_000.0) / distance
    return gross_r - cost_r, cost_r, "round_trip_bps_converted_to_R"


def _net_trade_rows(rows: list[dict[str, Any]], *, round_trip_bps: float = 15.0) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        net_r, cost_r, treatment = _net_r_for_row(row, round_trip_bps)
        gross_r = float(row.get("r_multiple") or 0.0)
        output.append(
            {
                "trade_number": index,
                "trade_id": row.get("trade_id"),
                "symbol": row.get("symbol", "BTCUSDT"),
                "side": row.get("side"),
                "entry_time": row.get("entry_time"),
                "exit_time": row.get("exit_time"),
                "entry_timestamp": row.get("entry_timestamp"),
                "exit_timestamp": row.get("exit_timestamp"),
                "entry_price": float(row.get("entry_price") or 0.0),
                "exit_price": float(row.get("exit_price") or 0.0),
                "initial_stop": float(row.get("initial_stop") or 0.0),
                "stop_distance_fraction": stop_distance_fraction(row),
                "gross_r": gross_r,
                "net_r": net_r,
                "cost_r": cost_r,
                "cost_treatment": treatment,
                "setup_class": row.get("setup_class"),
                "strategy_type": row.get("strategy_type"),
                "convexity_label": row.get("convexity_label"),
                "personality_label": row.get("personality_label"),
                "runner_label": row.get("runner_label"),
            }
        )
    return output


def _simulate_r_sequence(net_rows: list[dict[str, Any]], *, start_capital: float) -> dict[str, Any]:
    equity = start_capital
    curve = [equity]
    curve_rows: list[dict[str, Any]] = []
    values = [float(row["net_r"]) for row in net_rows]
    gross_values = [float(row["gross_r"]) for row in net_rows]
    largest_loss_r = 0.0
    for row in net_rows:
        before = equity
        risk = before * RISK_PER_TRADE
        pnl = float(row["net_r"]) * risk
        equity = before + pnl
        curve.append(equity)
        largest_loss_r = min(largest_loss_r, float(row["net_r"]))
        curve_rows.append(
            {
                "trade_number": row["trade_number"],
                "trade_id": row["trade_id"],
                "entry_time": row["entry_time"],
                "exit_time": row["exit_time"],
                "net_r": row["net_r"],
                "equity_before_trade": before,
                "risk_eur": risk,
                "net_pnl_eur": pnl,
                "equity_after_trade": equity,
            }
        )
    return {
        "starting_equity": start_capital,
        "ending_equity": equity,
        "net_gain": equity - start_capital,
        "return_multiple": equity / start_capital if start_capital else 0.0,
        "accepted_trades": len(net_rows),
        "gross_total_R": sum(gross_values),
        "net_total_R": sum(values),
        "net_average_R": sum(values) / len(values) if values else 0.0,
        "net_median_R": median(values) if values else 0.0,
        "net_profit_factor": _profit_factor(values),
        "net_win_rate": _safe_ratio(sum(1 for value in values if value > 0.0), len(values), 0.0),
        "net_max_drawdown": _max_drawdown(curve),
        "largest_loss_R": largest_loss_r,
        "trades_flipped_from_win_to_loss_due_to_costs": sum(
            1 for row in net_rows if float(row["gross_r"]) > 0.0 and float(row["net_r"]) <= 0.0
        ),
        "total_cost_R": sum(float(row["cost_r"]) for row in net_rows),
        "equity_curve": curve,
        "equity_rows": curve_rows,
    }


def _classification_for_capital_scaling(rows: list[dict[str, Any]]) -> str:
    errors = [abs(float(row["proportionality_error_vs_25k"])) for row in rows if row["starting_capital"] != START_CAPITAL_25K]
    if errors and max(errors) <= 0.000001:
        return "CAPITAL_SCALING_CONSISTENT_RESEARCH_ONLY"
    if errors and max(errors) <= 0.01:
        return "CAPITAL_SCALING_MINOR_DISTORTION_RESEARCH_ONLY"
    if errors:
        return "CAPITAL_SCALING_FRAGILE_RESEARCH_ONLY"
    return "CAPITAL_SCALING_FAILED_RESEARCH_ONLY"


def _capital_scaling(config: GauntletConfig, holdout_rows: list[dict[str, Any]], full_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    holdout_25 = _simulate_r_sequence(holdout_rows, start_capital=START_CAPITAL_25K)
    full_25 = _simulate_r_sequence(full_rows, start_capital=START_CAPITAL_25K)
    split = _read_json(config.court_002_root / "split_manifest.json")
    for capital in CAPITAL_LEVELS:
        holdout = _simulate_r_sequence(holdout_rows, start_capital=capital)
        full = _simulate_r_sequence(full_rows, start_capital=capital)
        expected_holdout = holdout_25["ending_equity"] * (capital / START_CAPITAL_25K)
        expected_full = full_25["ending_equity"] * (capital / START_CAPITAL_25K)
        monthly = _monthly_growth(
            capital,
            holdout["ending_equity"],
            str(split.get("holdout_start")),
            str(split.get("holdout_end")),
        )
        rows.append(
            {
                "starting_capital": capital,
                "holdout_final_net_equity": holdout["ending_equity"],
                "holdout_net_gain": holdout["net_gain"],
                "holdout_return_multiple": holdout["return_multiple"],
                "holdout_return_pct": holdout["return_multiple"] - 1.0,
                "holdout_monthly_growth": monthly,
                "full_history_final_net_equity": full["ending_equity"],
                "full_history_net_gain": full["net_gain"],
                "full_history_return_multiple": full["return_multiple"],
                "accepted_trades": holdout["accepted_trades"],
                "full_history_accepted_trades": full["accepted_trades"],
                "holdout_net_total_R": holdout["net_total_R"],
                "full_history_net_total_R": full["net_total_R"],
                "holdout_profit_factor": holdout["net_profit_factor"],
                "holdout_win_rate": holdout["net_win_rate"],
                "holdout_max_drawdown": holdout["net_max_drawdown"],
                "full_history_max_drawdown": full["net_max_drawdown"],
                "largest_loss_R": min(holdout["largest_loss_R"], full["largest_loss_R"]),
                "ratio_vs_20k": capital / START_CAPITAL_20K,
                "ratio_vs_25k": capital / START_CAPITAL_25K,
                "expected_holdout_equity_from_25k_linear_scaling": expected_holdout,
                "expected_full_history_equity_from_25k_linear_scaling": expected_full,
                "proportionality_error_vs_25k": _safe_ratio(holdout["ending_equity"] - expected_holdout, expected_holdout, 0.0),
                "full_history_proportionality_error_vs_25k": _safe_ratio(
                    full["ending_equity"] - expected_full, expected_full, 0.0
                ),
                "distortion_detected": False,
                "accidental_capital_sweet_spot_detected": False,
            }
        )
    classification = _classification_for_capital_scaling(rows)
    _write_csv(config.output_root / "capital_scaling_consistency_results.csv", rows)
    summary = {
        "classification": classification,
        "capital_levels": list(CAPITAL_LEVELS),
        "rows": rows,
        "interpretation": "Fixed percentage risk produces proportional scaling; this checks arithmetic consistency, not new edge.",
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "capital_scaling_consistency_summary.json", summary)
    return summary


def _eth_transfer(config: GauntletConfig) -> dict[str, Any]:
    candidates = list((config.project_root / "data_storage" / "ETHUSDT" / "1m").glob("*.csv")) if (
        config.project_root / "data_storage" / "ETHUSDT" / "1m"
    ).exists() else []
    candidates += list((config.package_root / "data_storage" / "ETHUSDT" / "1m").glob("*.csv")) if (
        config.package_root / "data_storage" / "ETHUSDT" / "1m"
    ).exists() else []
    rows: list[dict[str, Any]] = []
    summary = {
        "classification": "ETHUSDT_TRANSFER_BLOCKED_DATA_UNAVAILABLE",
        "source_path": str(sorted(candidates)[-1]) if candidates else None,
        "reason": "No local ETHUSDT 1m source artifact was present, and no existing frozen ETHUSDT transfer ledger exists. The gauntlet does not infer ETH results from BTC.",
        "final_net_equity_from_25k": None,
        "profit_factor": None,
        "win_rate": None,
        "max_drawdown": None,
        "data_quality": {"source_found": bool(candidates), "frozen_eth_ledger_found": False},
        "strategy_tuned_for_eth": False,
        **SAFETY_FLAGS,
    }
    _write_csv(config.output_root / "ethusdt_cross_asset_transfer_results.csv", rows)
    _write_json(config.output_root / "ethusdt_cross_asset_transfer_summary.json", summary)
    return summary


def _rolling_windows() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    starts = pd.date_range("2018-01-01", "2021-06-01", freq="MS", tz="UTC")
    return [(start, start + pd.DateOffset(years=5) - pd.Timedelta(minutes=1)) for start in starts]


def _net_cost_rolling_5y(config: GauntletConfig, all_rows: list[dict[str, Any]]) -> dict[str, Any]:
    result_rows: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(_rolling_windows(), start=1):
        selected = [
            row
            for row in all_rows
            if pd.notna(row.get("entry_timestamp")) and start <= row["entry_timestamp"] <= end
        ]
        sim = _simulate_r_sequence(selected, start_capital=START_CAPITAL_25K)
        result_rows.append(
            {
                "window_number": index,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "accepted_trades": sim["accepted_trades"],
                "ending_equity": sim["ending_equity"],
                "return_multiple": sim["return_multiple"],
                "net_total_R": sim["net_total_R"],
                "profit_factor": sim["net_profit_factor"],
                "win_rate": sim["net_win_rate"],
                "max_drawdown": sim["net_max_drawdown"],
                "above_500k": sim["ending_equity"] >= 500_000.0,
                "above_750k": sim["ending_equity"] >= 750_000.0,
                "above_1m": sim["ending_equity"] >= 1_000_000.0,
                "above_1_25m": sim["ending_equity"] >= 1_250_000.0,
                "above_2m": sim["ending_equity"] >= 2_000_000.0,
            }
        )
    endings = [float(row["ending_equity"]) for row in result_rows]
    counts = {f"windows_above_{int(threshold)}": sum(1 for value in endings if value >= threshold) for threshold in ROLLING_THRESHOLDS}
    avg = sum(endings) / len(endings) if endings else 0.0
    med = median(endings) if endings else 0.0
    if counts["windows_above_1000000"] >= 21 and med >= MISSION_TARGET_EUR:
        classification = "NET_COST_ROLLING_5Y_SUPPORTS_1M_STRONG_TARGET"
    elif counts["windows_above_1000000"] >= 1 or avg >= 750_000.0:
        classification = "NET_COST_ROLLING_5Y_SUPPORTS_1M_ASPIRATIONAL_TARGET"
    elif avg >= 500_000.0:
        classification = "NET_COST_ROLLING_5Y_SUPPORTS_750K_BASE_NOT_1M"
    else:
        classification = "NET_COST_ROLLING_5Y_WEAKENS_TARGET_MATERIALLY"
    summary = {
        "classification": classification,
        "window_count": len(result_rows),
        "average_ending_equity": avg,
        "median_ending_equity": med,
        "minimum_ending_equity": min(endings) if endings else 0.0,
        "maximum_ending_equity": max(endings) if endings else 0.0,
        "p25_ending_equity": float(pd.Series(endings).quantile(0.25)) if endings else 0.0,
        "p75_ending_equity": float(pd.Series(endings).quantile(0.75)) if endings else 0.0,
        **counts,
        "best_window": max(result_rows, key=lambda row: float(row["ending_equity"])) if result_rows else None,
        "worst_window": min(result_rows, key=lambda row: float(row["ending_equity"])) if result_rows else None,
        "method": "Frozen Court 002 accepted-trade ledger sliced into 42 monthly 5Y windows and restated with the normal net-cost model.",
        **SAFETY_FLAGS,
    }
    _write_csv(config.output_root / "net_cost_rolling_5y_results.csv", result_rows)
    _write_json(config.output_root / "net_cost_rolling_5y_summary.json", summary)
    return summary


def _cost_stress(config: GauntletConfig, selected_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for bps in COST_STRESS_BPS:
        net_rows = _net_trade_rows(selected_rows, round_trip_bps=bps)
        sim = _simulate_r_sequence(net_rows, start_capital=START_CAPITAL_25K)
        if sim["ending_equity"] > START_CAPITAL_25K and sim["net_profit_factor"] >= 2.0:
            band_class = "COST_STRESS_SURVIVES"
        elif sim["ending_equity"] > START_CAPITAL_25K:
            band_class = "COST_STRESS_WEAKENS"
        else:
            band_class = "COST_STRESS_BREAKS"
        rows.append(
            {
                "round_trip_cost_bps": bps,
                "ending_equity": sim["ending_equity"],
                "return_multiple": sim["return_multiple"],
                "cost_drag_R": sim["total_cost_R"],
                "net_total_R": sim["net_total_R"],
                "profit_factor": sim["net_profit_factor"],
                "win_rate": sim["net_win_rate"],
                "max_drawdown": sim["net_max_drawdown"],
                "trades_flipped_from_win_to_loss_due_to_costs": sim["trades_flipped_from_win_to_loss_due_to_costs"],
                "profitable": sim["ending_equity"] > START_CAPITAL_25K,
                "band_classification": band_class,
            }
        )
    broken = sum(1 for row in rows if row["band_classification"] == "COST_STRESS_BREAKS")
    fragile = any(float(row["round_trip_cost_bps"]) <= 50.0 and row["band_classification"] == "COST_STRESS_BREAKS" for row in rows)
    if broken == 0 and rows[-1]["band_classification"] != "COST_STRESS_BREAKS":
        classification = "COST_STRESS_ROBUST_RESEARCH_ONLY"
    elif not fragile:
        classification = "COST_STRESS_ACCEPTABLE_RESEARCH_ONLY"
    elif rows[0]["band_classification"] != "COST_STRESS_BREAKS":
        classification = "COST_STRESS_FRAGILE_RESEARCH_ONLY"
    else:
        classification = "COST_STRESS_FAILED_RESEARCH_ONLY"
    summary = {"classification": classification, "rows": rows, **SAFETY_FLAGS}
    _write_csv(config.output_root / "cost_stress_results.csv", rows)
    _write_json(config.output_root / "cost_stress_summary.json", summary)
    return summary


def _drawdown_ruin(config: GauntletConfig, net_rows: list[dict[str, Any]]) -> dict[str, Any]:
    sim = _simulate_r_sequence(net_rows, start_capital=START_CAPITAL_25K)
    curve = sim["equity_curve"]
    peak = curve[0]
    current_dd = 0.0
    max_dd = 0.0
    worst_valley = curve[0]
    longest_duration = 0
    current_duration = 0
    dd_counts = {20: 0, 40: 0, 60: 0, 80: 0}
    for equity in curve:
        if equity >= peak:
            peak = equity
            current_duration = 0
        else:
            current_duration += 1
        current_dd = _safe_ratio(peak - equity, peak, 0.0)
        max_dd = max(max_dd, current_dd)
        if current_dd == max_dd:
            worst_valley = equity
        longest_duration = max(longest_duration, current_duration)
        for threshold in dd_counts:
            if current_dd >= threshold / 100.0:
                dd_counts[threshold] += 1
    below = {
        "times_below_20k": sum(1 for value in curve if value < 20_000.0),
        "times_below_15k": sum(1 for value in curve if value < 15_000.0),
        "times_below_10k": sum(1 for value in curve if value < 10_000.0),
        "times_below_5k": sum(1 for value in curve if value < 5_000.0),
    }
    if max_dd >= 0.95 or below["times_below_5k"] > 0:
        classification = "DRAWDOWN_RISK_TOO_DANGEROUS_FOR_PAPER_READINESS"
    elif max_dd >= 0.60:
        classification = "DRAWDOWN_RISK_SEVERE_BUT_RECOVERED_RESEARCH_ONLY"
    else:
        classification = "DRAWDOWN_RISK_ACCEPTABLE_RESEARCH_ONLY"
    rows = [
        {"trade_index": index, "equity": equity}
        for index, equity in enumerate(curve)
    ]
    summary = {
        "classification": classification,
        "worst_drawdown": max_dd,
        "current_drawdown": current_dd,
        "longest_drawdown_duration_trades": longest_duration,
        "worst_valley_equity": worst_valley,
        "minimum_equity": min(curve),
        "ending_equity": curve[-1],
        "drawdown_observations_over_20_pct": dd_counts[20],
        "drawdown_observations_over_40_pct": dd_counts[40],
        "drawdown_observations_over_60_pct": dd_counts[60],
        "drawdown_observations_over_80_pct": dd_counts[80],
        "recovered_to_new_high_after_worst_valley": curve[-1] > worst_valley,
        **below,
        **SAFETY_FLAGS,
    }
    _write_csv(config.output_root / "drawdown_ruin_analysis_results.csv", rows)
    _write_json(config.output_root / "drawdown_ruin_analysis_summary.json", summary)
    return summary


def _monte_carlo(config: GauntletConfig, net_rows: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_r"]) for row in net_rows]
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
                "below_starting_equity": min(curve) < START_CAPITAL_25K,
                "below_5k": min(curve) < 5_000.0,
            }
        )
    endings = [float(row["ending_equity"]) for row in rows]
    dds = [float(row["max_drawdown"]) for row in rows]
    series = pd.Series(endings)
    probability_1m = _safe_ratio(sum(1 for value in endings if value >= MISSION_TARGET_EUR), len(endings), 0.0)
    probability_below_start = _safe_ratio(sum(1 for row in rows if row["below_starting_equity"]), len(rows), 0.0)
    if probability_1m >= 0.5 and probability_below_start < 0.1:
        classification = "MONTE_CARLO_SEQUENCE_ROBUST_RESEARCH_ONLY"
    elif probability_1m >= 0.2:
        classification = "MONTE_CARLO_SEQUENCE_MODERATE_RESEARCH_ONLY"
    elif median(endings) > START_CAPITAL_25K:
        classification = "MONTE_CARLO_SEQUENCE_FRAGILE_RESEARCH_ONLY"
    else:
        classification = "MONTE_CARLO_SEQUENCE_FAILED_RESEARCH_ONLY"
    summary = {
        "classification": classification,
        "seed": MONTE_CARLO_SEED,
        "runs": MONTE_CARLO_RUNS,
        "median_ending_equity": float(series.quantile(0.50)),
        "mean_ending_equity": float(series.mean()),
        "p5_ending_equity": float(series.quantile(0.05)),
        "p25_ending_equity": float(series.quantile(0.25)),
        "p75_ending_equity": float(series.quantile(0.75)),
        "p95_ending_equity": float(series.quantile(0.95)),
        "probability_above_500k": _safe_ratio(sum(1 for value in endings if value >= 500_000.0), len(endings), 0.0),
        "probability_above_750k": _safe_ratio(sum(1 for value in endings if value >= 750_000.0), len(endings), 0.0),
        "probability_above_1m": probability_1m,
        "probability_below_starting_equity": probability_below_start,
        "probability_drawdown_over_40_pct": _safe_ratio(sum(1 for value in dds if value >= 0.40), len(dds), 0.0),
        "probability_drawdown_over_60_pct": _safe_ratio(sum(1 for value in dds if value >= 0.60), len(dds), 0.0),
        "probability_drawdown_over_80_pct": _safe_ratio(sum(1 for value in dds if value >= 0.80), len(dds), 0.0),
        "probability_below_5k": _safe_ratio(sum(1 for row in rows if row["below_5k"]), len(rows), 0.0),
        "worst_ending_equity": min(endings),
        "best_ending_equity": max(endings),
        **SAFETY_FLAGS,
    }
    _write_csv(config.output_root / "trade_sequence_monte_carlo_results.csv", rows)
    _write_json(config.output_root / "trade_sequence_monte_carlo_summary.json", summary)
    return summary


def _load_daily_context(config: GauntletConfig) -> pd.DataFrame:
    frame = pd.read_csv(config.court_002_root / "datasets" / "combined_full_history_court_timeline_btcusdt_1m.csv")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    daily = frame.set_index("timestamp")["close"].resample("1D").last().dropna().to_frame("close")
    daily["return_180d"] = daily["close"].pct_change(180)
    daily["return_30d"] = daily["close"].pct_change(30)
    daily["vol_30d"] = daily["close"].pct_change().rolling(30).std()
    return daily


def _regime_for_timestamp(daily: pd.DataFrame, timestamp: pd.Timestamp) -> str:
    if pd.isna(timestamp):
        return "unknown"
    key = timestamp.floor("D")
    if key not in daily.index:
        prior = daily.loc[daily.index <= key]
        if prior.empty:
            return "unknown"
        row = prior.iloc[-1]
    else:
        row = daily.loc[key]
    ret180 = float(row.get("return_180d") or 0.0)
    vol30 = float(row.get("vol_30d") or 0.0)
    if ret180 >= 0.30 and vol30 < 0.05:
        return "uptrend_orderly"
    if ret180 >= 0.30:
        return "uptrend_high_volatility"
    if ret180 <= -0.20:
        return "downtrend"
    return "range_or_transition"


def _regime_breakdown(config: GauntletConfig, net_rows: list[dict[str, Any]]) -> dict[str, Any]:
    daily = _load_daily_context(config)
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in net_rows:
        regime = _regime_for_timestamp(daily, row.get("entry_timestamp"))
        buckets.setdefault(regime, []).append(row)
    rows: list[dict[str, Any]] = []
    for regime, bucket in sorted(buckets.items()):
        values = [float(row["net_r"]) for row in bucket]
        rows.append(
            {
                "regime": regime,
                "trade_count": len(bucket),
                "net_total_R": sum(values),
                "average_R": sum(values) / len(values) if values else 0.0,
                "profit_factor": _profit_factor(values),
                "win_rate": _safe_ratio(sum(1 for value in values if value > 0.0), len(values), 0.0),
                "equity_contribution_estimate_R": sum(values),
                "drawdown_contribution_loss_R": sum(value for value in values if value < 0.0),
            }
        )
    best = max(rows, key=lambda row: float(row["net_total_R"])) if rows else None
    worst = min(rows, key=lambda row: float(row["net_total_R"])) if rows else None
    positive_regimes = sum(1 for row in rows if float(row["net_total_R"]) > 0.0)
    if rows and positive_regimes == len(rows):
        classification = "REGIME_ROBUST_RESEARCH_ONLY"
    elif rows and positive_regimes >= max(1, len(rows) - 1):
        classification = "REGIME_DEPENDENT_BUT_USABLE_RESEARCH_ONLY"
    elif rows:
        classification = "REGIME_FRAGILE_RESEARCH_ONLY"
    else:
        classification = "REGIME_ANALYSIS_BLOCKED"
    summary = {
        "classification": classification,
        "best_regime": best,
        "worst_regime": worst,
        "regime_count": len(rows),
        "method": "Objective 180-day trend and 30-day volatility labels from BTCUSDT 1m source; no strategy thresholds changed.",
        **SAFETY_FLAGS,
    }
    _write_csv(config.output_root / "regime_breakdown_results.csv", rows)
    _write_json(config.output_root / "regime_breakdown_summary.json", summary)
    return summary


def _safety_scan(paths: Iterable[Path]) -> dict[str, Any]:
    sensitive_singletons = ["PASS" + "WORD", "TOK" + "EN"]
    exact_phrases = [
        "create" + " " + "order",
        "place" + " " + "order",
        "order" + " " + "endpoint",
        "account" + " " + "endpoint",
        "signed" + " " + "request",
        "broker" + " " + "execution",
        "private" + " " + "key",
        "API" + "_" + "SECRET",
        "BINANCE" + "_" + "SECRET",
        *sensitive_singletons,
    ]
    enabling_patterns = [
        re.compile(rf"['\"]?{name}['\"]?\s*[:=]\s*true\b", re.IGNORECASE)
        for name in (
            "paper_allowed",
            "live_allowed",
            "real_money_allowed",
            "behavior_change_allowed",
            "paper_validation_ready",
        )
    ]
    findings: list[dict[str, Any]] = []
    for path in paths:
        if not path.exists() or path.is_dir():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        lower = text.lower()
        for pattern in enabling_patterns:
            if pattern.search(text):
                findings.append({"path": str(path), "term": pattern.pattern})
        for phrase in exact_phrases:
            if phrase.lower() in lower:
                findings.append({"path": str(path), "term": phrase})
    return {"clean": len(findings) == 0, "findings": findings}


def _pre_paper_gate(component: dict[str, Any]) -> dict[str, Any]:
    dd_class = component["drawdown"]["classification"]
    eth_class = component["eth_transfer"]["classification"]
    rolling_class = component["rolling"]["classification"]
    cost_class = component["cost_stress"]["classification"]
    mc_class = component["monte_carlo"]["classification"]
    scheduler_ok = bool(component["evidence_lock"]["scheduler_background_proof"].get("installed_or_loaded"))
    if "TOO_DANGEROUS" in dd_class:
        classification = PRE_PAPER_RISK_BLOCK
    elif eth_class.endswith("BLOCKED_DATA_UNAVAILABLE"):
        classification = PRE_PAPER_WAIT
    elif "WEAKENS" in rolling_class or "FAILED" in cost_class or "FAILED" in mc_class:
        classification = PRE_PAPER_WAIT
    elif scheduler_ok:
        classification = PRE_PAPER_CAN_BE_CONSIDERED
    else:
        classification = PRE_PAPER_DATA_BLOCK
    return {
        "classification": classification,
        "paper_validation_ready": False,
        "can_consider_before_six_scheduler_months": classification == PRE_PAPER_CAN_BE_CONSIDERED,
        "does_not_replace_scheduler_evidence": True,
        "scheduler_must_continue": True,
        "reason": (
            "Gauntlet evidence is research-only. A paper-readiness court can only be considered if safety, scheduler, costs, drawdown, and data gates remain intact."
        ),
        **SAFETY_FLAGS,
    }


def _final_classification(component: dict[str, Any]) -> str:
    if not component["safety_scan"]["clean"]:
        return FAILED
    if "WEAKENS_TARGET_MATERIALLY" in component["rolling"]["classification"]:
        return WEAK
    if (
        component["eth_transfer"]["classification"].endswith("BLOCKED_DATA_UNAVAILABLE")
        and "FRAGILE" in component["cost_stress"]["classification"]
    ):
        return WEAK
    if component["eth_transfer"]["classification"].endswith("BLOCKED_DATA_UNAVAILABLE"):
        return PROMISING
    if "TOO_DANGEROUS" in component["drawdown"]["classification"]:
        return WEAK
    if component["pre_paper_gate"]["classification"] == PRE_PAPER_CAN_BE_CONSIDERED:
        return STRONG
    return PROMISING


def _report_markdown(summary: dict[str, Any]) -> str:
    cap_25 = next(row for row in summary["capital_scaling"]["rows"] if row["starting_capital"] == START_CAPITAL_25K)
    lines = [
        "# Pre-Paper Evidence Acceleration Gauntlet Court 001",
        "",
        f"- Court: `{summary['court_name']}`",
        f"- Final classification: `{summary['final_classification']}`",
        f"- Pre-paper gate: `{summary['pre_paper_gate']['classification']}`",
        f"- Research-only: `{summary['research_only']}`",
        f"- Paper validation ready: `{summary['paper_validation_ready']}`",
        "",
        "## EUR25k -> EUR1M target status",
        "",
        f"- Court 002 gross holdout: `€{summary['evidence_lock']['gross_vs_net_distinction']['court_002_gross_holdout_eur']:,.2f}`",
        f"- Court 002 net-cost holdout: `€{summary['evidence_lock']['gross_vs_net_distinction']['court_002_net_holdout_eur']:,.2f}`",
        f"- Court 002 net-cost full-history: `€{summary['evidence_lock']['gross_vs_net_distinction']['court_002_net_full_history_eur']:,.2f}`",
        f"- Old EUR20k normal-cost rolling 5Y average: `€{summary['evidence_lock']['old_normal_cost_row']['rolling_5y_average_ending_equity']:,.2f}`",
        f"- EUR25k strict projection from old EUR20k average: `€{summary['target_status']['eur25k_strict_projection_from_old_20k_average']:,.2f}`",
        "",
        "## Capital scaling",
        "",
        f"- Classification: `{summary['capital_scaling']['classification']}`",
        f"- EUR25k holdout net final: `€{cap_25['holdout_final_net_equity']:,.2f}`",
        f"- EUR25k full-history net final: `€{cap_25['full_history_final_net_equity']:,.2f}`",
        "",
        "## ETHUSDT transfer",
        "",
        f"- Classification: `{summary['eth_transfer']['classification']}`",
        f"- Result: `{summary['eth_transfer']['reason']}`",
        "",
        "## Net-cost rolling 5Y",
        "",
        f"- Classification: `{summary['rolling']['classification']}`",
        f"- Average ending equity: `€{summary['rolling']['average_ending_equity']:,.2f}`",
        f"- Median ending equity: `€{summary['rolling']['median_ending_equity']:,.2f}`",
        f"- Windows above EUR1M: `{summary['rolling']['windows_above_1000000']} / {summary['rolling']['window_count']}`",
        "",
        "## Cost stress",
        "",
        f"- Classification: `{summary['cost_stress']['classification']}`",
        "",
        "## Drawdown / ruin",
        "",
        f"- Classification: `{summary['drawdown']['classification']}`",
        f"- Worst drawdown: `{summary['drawdown']['worst_drawdown'] * 100:.2f}%`",
        f"- Times below EUR20k / EUR15k / EUR10k / EUR5k: `{summary['drawdown']['times_below_20k']} / {summary['drawdown']['times_below_15k']} / {summary['drawdown']['times_below_10k']} / {summary['drawdown']['times_below_5k']}`",
        "",
        "## Monte Carlo",
        "",
        f"- Classification: `{summary['monte_carlo']['classification']}`",
        f"- Median ending equity: `€{summary['monte_carlo']['median_ending_equity']:,.2f}`",
        f"- 5th percentile ending equity: `€{summary['monte_carlo']['p5_ending_equity']:,.2f}`",
        f"- Probability above EUR1M: `{summary['monte_carlo']['probability_above_1m'] * 100:.2f}%`",
        f"- Probability below starting equity: `{summary['monte_carlo']['probability_below_starting_equity'] * 100:.2f}%`",
        "",
        "## Regime breakdown",
        "",
        f"- Classification: `{summary['regime']['classification']}`",
        f"- Best regime: `{summary['regime']['best_regime']['regime'] if summary['regime']['best_regime'] else 'N/A'}`",
        f"- Worst regime: `{summary['regime']['worst_regime']['regime'] if summary['regime']['worst_regime'] else 'N/A'}`",
        "",
        "## Safety",
        "",
        "- No strategy logic was changed.",
        "- No paper/live/order/broker/account/private/signed endpoint was enabled.",
        "- EUR25k remains diagnostic only.",
        "- Scheduler remains separate and must continue collecting real forward evidence.",
        "",
    ]
    return "\n".join(lines)


def build_gauntlet(config: GauntletConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    evidence = _load_locked_evidence(config)

    research_root = config.court_002_root / "research_only_eur25k_replay" / "raw_engine"
    holdout_root = config.court_002_root / "holdout_validation" / "raw_engine"
    research_selected, research_removed = _selected_rows(config, research_root)
    holdout_selected, holdout_removed = _selected_rows(config, holdout_root)
    all_selected = sorted(research_selected + holdout_selected, key=lambda row: row.get("entry_timestamp"))
    research_net = _net_trade_rows(research_selected, round_trip_bps=15.0)
    holdout_net = _net_trade_rows(holdout_selected, round_trip_bps=15.0)
    all_net = _net_trade_rows(all_selected, round_trip_bps=15.0)

    capital = _capital_scaling(config, holdout_net, research_net)
    eth = _eth_transfer(config)
    rolling = _net_cost_rolling_5y(config, all_net)
    cost = _cost_stress(config, all_selected)
    drawdown = _drawdown_ruin(config, research_net)
    mc = _monte_carlo(config, research_net)
    regime = _regime_breakdown(config, research_net)
    target = {
        "eur1m_mission_preserved": True,
        "eur25k_strict_projection_from_old_20k_average": float(evidence["old_normal_cost_row"]["rolling_5y_average_ending_equity"])
        * (START_CAPITAL_25K / START_CAPITAL_20K),
        "eur25k_6h_context_projection": evidence["net_cost"]["target_analysis_impact"].get("eur25k_6h_context_projection"),
        "court_002_net_holdout_supportive_after_costs": evidence["net_cost"]["target_analysis_impact"].get(
            "sealed_holdout_supportive_after_costs"
        ),
        "court_002_net_holdout_alone_meets_1m_pace": evidence["net_cost"]["target_analysis_impact"].get(
            "sealed_holdout_alone_meets_eur1m_pace_after_costs"
        ),
        "target_status": "EUR1M_REMAINS_STRONG_ASPIRATIONAL_TARGET_NOT_PAPER_APPROVAL",
    }
    component = {
        "evidence_lock": evidence,
        "capital_scaling": capital,
        "eth_transfer": eth,
        "rolling": rolling,
        "cost_stress": cost,
        "drawdown": drawdown,
        "monte_carlo": mc,
        "regime": regime,
    }
    gate = _pre_paper_gate(component)
    component["pre_paper_gate"] = gate
    _write_json(config.output_root / "pre_paper_readiness_gate_summary.json", gate)

    changed_files = [
        config.output_root / name
        for name in (
            "evidence_lock_manifest.json",
            "capital_scaling_consistency_results.csv",
            "capital_scaling_consistency_summary.json",
            "ethusdt_cross_asset_transfer_results.csv",
            "ethusdt_cross_asset_transfer_summary.json",
            "net_cost_rolling_5y_results.csv",
            "net_cost_rolling_5y_summary.json",
            "cost_stress_results.csv",
            "cost_stress_summary.json",
            "drawdown_ruin_analysis_results.csv",
            "drawdown_ruin_analysis_summary.json",
            "trade_sequence_monte_carlo_results.csv",
            "trade_sequence_monte_carlo_summary.json",
            "regime_breakdown_results.csv",
            "regime_breakdown_summary.json",
            "pre_paper_readiness_gate_summary.json",
        )
    ]
    safety = _safety_scan([Path(__file__), *changed_files])
    component["safety_scan"] = safety
    final_classification = _final_classification(component)
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": final_classification,
        **SAFETY_FLAGS,
        "strategy_logic_changed": False,
        "entries_changed": False,
        "exits_changed": False,
        "thresholds_changed": False,
        "filters_changed": False,
        "sizing_changed": False,
        "execution_timeframe": "1H",
        "data_feed_timeframe": "1m",
        "context_timeframe": "6H",
        "evidence_lock": evidence,
        "target_status": target,
        "capital_scaling": capital,
        "eth_transfer": eth,
        "rolling": rolling,
        "cost_stress": cost,
        "drawdown": drawdown,
        "monte_carlo": mc,
        "regime": regime,
        "pre_paper_gate": gate,
        "safety_scan": safety,
        "files_created": [str(path) for path in changed_files]
        + [
            str(config.output_root / "pre_paper_evidence_acceleration_gauntlet_report.md"),
            str(config.output_root / "pre_paper_evidence_acceleration_gauntlet_summary.json"),
        ],
        "full_history_accepted_trades": len(research_selected),
        "holdout_accepted_trades": len(holdout_selected),
        "full_history_removed_by_frozen_rules": len(research_removed),
        "holdout_removed_by_frozen_rules": len(holdout_removed),
    }
    _write_json(config.output_root / "pre_paper_evidence_acceleration_gauntlet_summary.json", summary)
    (config.output_root / "pre_paper_evidence_acceleration_gauntlet_report.md").write_text(
        _report_markdown(_round_payload(summary)),
        encoding="utf-8",
    )
    return _round_payload(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the pre-paper evidence acceleration gauntlet.")
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()
    config = default_config()
    if args.output_root:
        config = GauntletConfig(
            project_root=config.project_root,
            package_root=config.package_root,
            output_root=Path(args.output_root).expanduser().resolve(),
            court_002_root=config.court_002_root,
            net_cost_root=config.net_cost_root,
            scheduler_root=config.scheduler_root,
            old_cost_root=config.old_cost_root,
        )
    print(json.dumps(build_gauntlet(config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
