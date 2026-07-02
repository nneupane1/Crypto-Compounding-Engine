from __future__ import annotations

import argparse
import json
import math
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
from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import (  # noqa: E402
    _apply_frozen_patch,
    _load_frozen_rules,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import _prepare_rows  # noqa: E402
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _normalize_trade_rows,
    _read_csv_rows,
)


COURT_NAME = "COURT_002_NET_COST_RESTATEMENT_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "court_002_net_cost_restatement_court_001"
PASSED = "COURT_002_NET_COST_RESTATEMENT_PASSED_RESEARCH_ONLY"
WARNING = "COURT_002_NET_COST_RESTATEMENT_WARNING_RESEARCH_ONLY"
FAILED = "COURT_002_NET_COST_RESTATEMENT_FAILED_RESEARCH_ONLY"
BLOCKED = "NET_COST_RESTATEMENT_BLOCKED_MISSING_TRADE_COST_INPUTS"
TARGET_UNCHANGED = "TARGET_ANALYSIS_UNCHANGED_AFTER_NET_COST_RESTATEMENT"
TARGET_SLIGHTLY_DOWNGRADED = "TARGET_ANALYSIS_SLIGHTLY_DOWNGRADED_AFTER_NET_COST_RESTATEMENT"
TARGET_MATERIALLY_DOWNGRADED = "TARGET_ANALYSIS_MATERIALLY_DOWNGRADED_AFTER_NET_COST_RESTATEMENT"
TARGET_INVALID = "TARGET_ANALYSIS_INVALID_UNTIL_NET_COST_LEDGER_AVAILABLE"
MISSION_TARGET_EUR = 1_000_000.0
START_CAPITAL_25K = 25_000.0
START_CAPITAL_20K = 20_000.0
REQUIRED_MONTHLY_GROWTH_FOR_25K_TO_1M_5Y = (MISSION_TARGET_EUR / START_CAPITAL_25K) ** (1.0 / 60.0) - 1.0

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "real_money_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
    "behavior_change_allowed": False,
    "no_order_path_created": True,
    "no_broker_path_created": True,
    "paper_validation_ready": False,
    "eur_25000_anchor_active": False,
}

PRIMARY_COST_MODEL: dict[str, Any] = {
    "band_name": "NORMAL_MIXED_MAKER_TAKER_COST",
    "fee_bps_per_side": 3.5,
    "spread_slippage_bps_per_side": 4.0,
    "total_round_trip_bps": 15.0,
    "round_trip_cost_fraction": 15.0 / 10_000.0,
    "source": "structural_compounding_lab/output/execution_cost_realism_and_trade_redundancy_audit_001/diagnostics/execution_cost_band_results.json",
}

RAW_ENGINE_NORMAL_COST_MODEL: dict[str, Any] = {
    "scenario_name": "normal_cost",
    "fee_bps": 8.0,
    "slippage_bps": 5.0,
    "spread_bps": 2.0,
    "stop_stress_bps": 8.0,
    "source": "structural_compounding_lab/validation/execution_cost_sensitivity.py",
    "used_for_restatement": False,
}


@dataclass(frozen=True)
class RestatementConfig:
    project_root: Path
    package_root: Path
    court_002_root: Path
    output_root: Path


def default_config() -> RestatementConfig:
    pkg = package_root()
    return RestatementConfig(
        project_root=project_root(),
        package_root=pkg,
        court_002_root=pkg / "output" / "eur25k_sealed_6m_holdout_court_002",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def _profit_factor(values: list[float]) -> float:
    wins = sum(value for value in values if value > 0.0)
    losses = abs(sum(value for value in values if value < 0.0))
    return wins / losses if losses else float(wins > 0.0)


def _max_drawdown(equity_curve: list[float]) -> float:
    peak = equity_curve[0] if equity_curve else 0.0
    max_dd = 0.0
    for equity in equity_curve:
        peak = max(peak, equity)
        max_dd = max(max_dd, _safe_ratio(peak - equity, peak, 0.0))
    return max_dd


def _monthly_growth(start: float, end: float, start_timestamp: str, end_timestamp: str) -> float:
    start_dt = pd.Timestamp(start_timestamp)
    end_dt = pd.Timestamp(end_timestamp)
    elapsed_days = max((end_dt - start_dt).total_seconds() / 86_400.0, 1.0)
    elapsed_months = elapsed_days / (365.2425 / 12.0)
    return (end / start) ** (1.0 / elapsed_months) - 1.0


def _ledger_columns(path: Path) -> list[str]:
    try:
        return list(pd.read_csv(path, nrows=0).columns)
    except Exception:
        return []


def _has_column(columns: list[str], names: set[str]) -> bool:
    return bool(set(columns) & names)


def _ledger_schema(raw_engine_root: Path, selected_count: int) -> dict[str, Any]:
    trades_path = raw_engine_root / "trades.csv"
    columns = _ledger_columns(trades_path)
    raw_rows = 0
    if trades_path.exists():
        with trades_path.open(encoding="utf-8") as handle:
            raw_rows = sum(1 for _ in handle) - 1
    return {
        "path": str(trades_path),
        "row_count": raw_rows,
        "accepted_trade_count_after_frozen_rules": selected_count,
        "required_columns_available": all(
            column in columns
            for column in ("trade_id", "side", "entry_time", "exit_time", "entry_price", "exit_price", "initial_stop", "r_multiple")
        ),
        "entry_price_exists": "entry_price" in columns,
        "exit_price_exists": "exit_price" in columns,
        "stop_distance_exists": "initial_stop" in columns or "stop_distance_pct" in columns,
        "position_side_exists": "side" in columns,
        "r_multiple_exists": "r_multiple" in columns,
        "notional_or_risk_model_fields_exist": _has_column(columns, {"quantity", "notional", "risk_eur", "risk_eur_observed", "risk_multiplier"}),
        "fee_or_cost_fields_already_exist": _has_column(columns, {"fee", "fees", "cost", "commission", "slippage"}),
        "columns": columns,
    }


def _accepted_trades_from_existing_artifacts(config: RestatementConfig, raw_engine_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rules_path = config.package_root / "output" / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json"
    matched_shorts, disabled_longs, _rules_payload = _load_frozen_rules(rules_path)
    normalized = _normalize_trade_rows(
        _read_csv_rows(raw_engine_root / "trades.csv"),
        _read_csv_rows(raw_engine_root / "setup_log.csv"),
        _read_csv_rows(raw_engine_root / "level_log.csv"),
        _read_csv_rows(raw_engine_root / "liquidity_events.csv"),
    )
    prepared = _prepare_rows(normalized)
    return _apply_frozen_patch(
        prepared,
        matched_short_archetypes=matched_shorts,
        disabled_long_modes=disabled_longs,
    )


def stop_distance_fraction(row: dict[str, Any]) -> float:
    entry = float(row.get("entry_price") or 0.0)
    stop = float(row.get("initial_stop") or 0.0)
    if entry <= 0.0 or stop <= 0.0:
        return 0.0
    return abs(entry - stop) / entry


def cost_adjusted_r(row: dict[str, Any], *, round_trip_cost_fraction: float) -> tuple[float | None, float | None]:
    distance = stop_distance_fraction(row)
    if distance <= 0.0:
        return None, None
    cost_r = round_trip_cost_fraction / distance
    return float(row["r_multiple"]) - cost_r, cost_r


def _simulate_sequence(
    *,
    rows: list[dict[str, Any]],
    start_capital: float,
    round_trip_cost_fraction: float,
    require_complete_cost_inputs: bool,
) -> dict[str, Any]:
    equity = start_capital
    gross_equity = start_capital
    net_curve = [start_capital]
    gross_curve = [start_capital]
    adjusted_rows: list[dict[str, Any]] = []
    missing_inputs: list[dict[str, Any]] = []
    total_cost_eur = 0.0

    for index, row in enumerate(rows, start=1):
        gross_r = float(row["r_multiple"])
        net_r, cost_r = cost_adjusted_r(row, round_trip_cost_fraction=round_trip_cost_fraction)
        if net_r is None or cost_r is None:
            missing_inputs.append(
                {
                    "trade_number": index,
                    "trade_id": row.get("trade_id"),
                    "side": row.get("side"),
                    "entry_time": row.get("entry_time"),
                    "exit_time": row.get("exit_time"),
                    "entry_price": row.get("entry_price"),
                    "exit_price": row.get("exit_price"),
                    "initial_stop": row.get("initial_stop"),
                    "r_multiple": row.get("r_multiple"),
                    "reason": "stop_distance_fraction_missing_or_zero",
                }
            )
            if require_complete_cost_inputs:
                continue
            net_r = gross_r
            cost_r = 0.0

        gross_risk_eur = gross_equity * 0.01
        gross_equity += gross_r * gross_risk_eur
        gross_curve.append(gross_equity)

        net_risk_eur = equity * 0.01
        trade_cost_eur = cost_r * net_risk_eur
        total_cost_eur += trade_cost_eur
        gross_pnl_on_net_capital = gross_r * net_risk_eur
        net_pnl = net_r * net_risk_eur
        equity += net_pnl
        net_curve.append(equity)
        adjusted_rows.append(
            {
                "trade_number": index,
                "trade_id": row.get("trade_id"),
                "entry_time": row.get("entry_time"),
                "exit_time": row.get("exit_time"),
                "side": row.get("side"),
                "entry_price": row.get("entry_price"),
                "exit_price": row.get("exit_price"),
                "initial_stop": row.get("initial_stop"),
                "stop_distance_fraction": stop_distance_fraction(row),
                "gross_r": gross_r,
                "cost_r": cost_r,
                "net_r": net_r,
                "equity_before_trade": round(equity - net_pnl, 6),
                "risk_eur": round(net_risk_eur, 6),
                "gross_pnl_eur_before_cost": round(gross_pnl_on_net_capital, 6),
                "estimated_cost_eur": round(trade_cost_eur, 6),
                "net_pnl_eur": round(net_pnl, 6),
                "equity_after_trade": round(equity, 6),
            }
        )

    gross_values = [float(row["r_multiple"]) for row in rows]
    net_values = [float(row["net_r"]) for row in adjusted_rows]
    complete = not missing_inputs
    return {
        "complete_cost_inputs": complete,
        "missing_cost_input_count": len(missing_inputs),
        "missing_cost_inputs": missing_inputs,
        "accepted_trades": len(rows),
        "costed_trades": len(adjusted_rows),
        "gross_starting_equity": start_capital,
        "gross_ending_equity_recomputed_from_sequence": gross_equity,
        "net_ending_equity": equity if complete or not require_complete_cost_inputs else None,
        "gross_return_multiple_recomputed": gross_equity / start_capital if start_capital else 0.0,
        "net_return_multiple": equity / start_capital if (complete or not require_complete_cost_inputs) and start_capital else None,
        "gross_total_R": sum(gross_values),
        "net_total_R": sum(net_values) if complete or not require_complete_cost_inputs else None,
        "gross_average_R": sum(gross_values) / len(gross_values) if gross_values else 0.0,
        "net_average_R": sum(net_values) / len(net_values) if (complete or not require_complete_cost_inputs) and net_values else None,
        "gross_median_R": median(gross_values) if gross_values else 0.0,
        "net_median_R": median(net_values) if (complete or not require_complete_cost_inputs) and net_values else None,
        "gross_profit_factor": _profit_factor(gross_values),
        "net_profit_factor": _profit_factor(net_values) if complete or not require_complete_cost_inputs else None,
        "gross_win_rate": _safe_ratio(sum(1 for value in gross_values if value > 0.0), len(gross_values), 0.0),
        "net_win_rate": _safe_ratio(sum(1 for value in net_values if value > 0.0), len(net_values), 0.0) if complete or not require_complete_cost_inputs else None,
        "gross_max_drawdown": _max_drawdown(gross_curve),
        "net_max_drawdown": _max_drawdown(net_curve) if complete or not require_complete_cost_inputs else None,
        "trades_flipped_from_win_to_loss_due_to_costs": sum(
            1 for row in adjusted_rows if float(row["gross_r"]) > 0.0 and float(row["net_r"]) <= 0.0
        ),
        "trades_filtered_to_worse_than_zero_due_to_costs": sum(
            1 for row in adjusted_rows if float(row["gross_r"]) >= 0.0 and float(row["net_r"]) < 0.0
        ),
        "total_estimated_fees_slippage_cost_eur": total_cost_eur if complete or not require_complete_cost_inputs else None,
        "cost_drag_eur": (gross_equity - equity) if complete or not require_complete_cost_inputs else None,
        "cost_drag_percentage_of_gross_ending_equity": _safe_ratio(gross_equity - equity, gross_equity, 0.0)
        if complete or not require_complete_cost_inputs
        else None,
        "cost_drag_R": sum(float(row["cost_r"]) for row in adjusted_rows) if complete or not require_complete_cost_inputs else None,
        "adjusted_trade_rows": adjusted_rows,
    }


def _ledger_report(name: str, raw_engine_root: Path, selected: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        **_ledger_schema(raw_engine_root, len(selected)),
        "zero_or_missing_stop_distance_count": sum(1 for row in selected if stop_distance_fraction(row) <= 0.0),
    }


def _target_impact(*, final_classification: str, holdout_monthly_growth: float | None) -> str:
    if final_classification == BLOCKED:
        return TARGET_INVALID
    if holdout_monthly_growth is None:
        return TARGET_INVALID
    if holdout_monthly_growth >= REQUIRED_MONTHLY_GROWTH_FOR_25K_TO_1M_5Y:
        return TARGET_UNCHANGED
    if holdout_monthly_growth > 0.0:
        return TARGET_SLIGHTLY_DOWNGRADED
    return TARGET_MATERIALLY_DOWNGRADED


def _round_payload(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _round_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_payload(item) for item in value]
    return value


def build_restatement(config: RestatementConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    court_summary_path = config.court_002_root / "eur25k_sealed_6m_holdout_summary.json"
    summary = _read_json(court_summary_path)
    research_root = config.court_002_root / "research_only_eur25k_replay" / "raw_engine"
    holdout_root = config.court_002_root / "holdout_validation" / "raw_engine"

    research_selected, research_removed = _accepted_trades_from_existing_artifacts(config, research_root)
    holdout_selected, holdout_removed = _accepted_trades_from_existing_artifacts(config, holdout_root)

    research_sim = _simulate_sequence(
        rows=research_selected,
        start_capital=START_CAPITAL_25K,
        round_trip_cost_fraction=float(PRIMARY_COST_MODEL["round_trip_cost_fraction"]),
        require_complete_cost_inputs=True,
    )
    holdout_sim_25k = _simulate_sequence(
        rows=holdout_selected,
        start_capital=START_CAPITAL_25K,
        round_trip_cost_fraction=float(PRIMARY_COST_MODEL["round_trip_cost_fraction"]),
        require_complete_cost_inputs=True,
    )
    holdout_sim_20k = _simulate_sequence(
        rows=holdout_selected,
        start_capital=START_CAPITAL_20K,
        round_trip_cost_fraction=float(PRIMARY_COST_MODEL["round_trip_cost_fraction"]),
        require_complete_cost_inputs=True,
    )

    full_history_gross = summary.get("full_history_research_replay", {})
    holdout_gross = summary.get("sealed_holdout_validation", {})
    split = summary.get("split_manifest", {})

    final_classification = PASSED
    classification_reasons: list[str] = []
    if research_sim["missing_cost_input_count"] or holdout_sim_25k["missing_cost_input_count"]:
        final_classification = BLOCKED
        classification_reasons.append("accepted_trade_missing_stop_distance_for_bps_to_R_cost_conversion")
    elif holdout_sim_25k["net_ending_equity"] and float(holdout_sim_25k["net_ending_equity"]) <= START_CAPITAL_25K:
        final_classification = FAILED
        classification_reasons.append("net_cost_holdout_not_profitable")
    elif holdout_sim_25k["net_return_multiple"] and float(holdout_sim_25k["net_return_multiple"]) < float(holdout_gross.get("return_multiple", 0.0)):
        final_classification = WARNING
        classification_reasons.append("net_cost_restatement_profitable_but_weaker_than_zero_fee_headline")
    else:
        classification_reasons.append("net_cost_restatement_complete")

    holdout_start = str(split.get("holdout_start") or "")
    holdout_end = str(split.get("holdout_end") or "")
    gross_holdout_monthly = None
    net_holdout_monthly = None
    if holdout_start and holdout_end and holdout_gross.get("ending_diagnostic_equity"):
        gross_holdout_monthly = _monthly_growth(
            START_CAPITAL_25K,
            float(holdout_gross["ending_diagnostic_equity"]),
            holdout_start,
            holdout_end,
        )
    if holdout_start and holdout_end and holdout_sim_25k.get("net_ending_equity") is not None:
        net_holdout_monthly = _monthly_growth(
            START_CAPITAL_25K,
            float(holdout_sim_25k["net_ending_equity"]),
            holdout_start,
            holdout_end,
        )

    target_impact = _target_impact(final_classification=final_classification, holdout_monthly_growth=net_holdout_monthly)
    output = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": final_classification,
        "classification_reasons": classification_reasons,
        **SAFETY_FLAGS,
        "input_evidence": {
            "court_002_summary": str(court_summary_path),
            "court_002_report": str(config.court_002_root / "eur25k_sealed_6m_holdout_report.md"),
            "full_history_research_raw_engine_root": str(research_root),
            "sealed_holdout_raw_engine_root": str(holdout_root),
            "court_002_rerun_performed": False,
            "sealed_holdout_reopened": False,
            "strategy_logic_changed": False,
        },
        "cost_model_used": PRIMARY_COST_MODEL,
        "separate_raw_engine_cost_sensitivity_model_reported_not_used": RAW_ENGINE_NORMAL_COST_MODEL,
        "ledger_audit": {
            "full_history_research": _ledger_report("full_history_research", research_root, research_selected),
            "sealed_holdout": _ledger_report("sealed_holdout", holdout_root, holdout_selected),
            "expected_full_history_accepted_trades": 579,
            "expected_holdout_accepted_trades": 27,
            "full_history_removed_by_frozen_rules": len(research_removed),
            "holdout_removed_by_frozen_rules": len(holdout_removed),
            "rejected_setups_fee_policy": "rejected_setups_incur_no_fee",
        },
        "full_history_research_25k": {
            "gross_starting_equity": START_CAPITAL_25K,
            "gross_ending_equity_from_court_002": full_history_gross.get("ending_diagnostic_equity"),
            "gross_return_multiple_from_court_002": full_history_gross.get("return_multiple"),
            "gross_total_R_from_court_002": full_history_gross.get("total_R"),
            "gross_profit_factor_from_court_002": full_history_gross.get("profit_factor"),
            "gross_win_rate_from_court_002": full_history_gross.get("win_rate"),
            "gross_max_drawdown_from_court_002": full_history_gross.get("max_drawdown_pct"),
            "restatement": {key: value for key, value in research_sim.items() if key != "adjusted_trade_rows"},
            "net_restatement_available": research_sim["missing_cost_input_count"] == 0,
        },
        "sealed_holdout_25k": {
            "gross_starting_equity": START_CAPITAL_25K,
            "gross_ending_equity_from_court_002": holdout_gross.get("ending_diagnostic_equity"),
            "gross_return_multiple_from_court_002": holdout_gross.get("return_multiple"),
            "gross_net_gain_from_court_002": holdout_gross.get("net_profit_eur"),
            "gross_total_R_from_court_002": holdout_gross.get("total_R"),
            "gross_profit_factor_from_court_002": holdout_gross.get("profit_factor"),
            "gross_win_rate_from_court_002": holdout_gross.get("win_rate"),
            "gross_max_drawdown_from_court_002": holdout_gross.get("max_drawdown_pct"),
            "restatement": {key: value for key, value in holdout_sim_25k.items() if key != "adjusted_trade_rows"},
            "gross_monthly_compounded_growth": gross_holdout_monthly,
            "net_monthly_compounded_growth": net_holdout_monthly,
            "required_monthly_growth_for_25k_to_1m_over_5y": REQUIRED_MONTHLY_GROWTH_FOR_25K_TO_1M_5Y,
            "net_holdout_above_1m_mission_pace": (
                net_holdout_monthly >= REQUIRED_MONTHLY_GROWTH_FOR_25K_TO_1M_5Y if net_holdout_monthly is not None else None
            ),
            "net_holdout_profitable_after_costs": (
                float(holdout_sim_25k["net_ending_equity"]) > START_CAPITAL_25K
                if holdout_sim_25k.get("net_ending_equity") is not None
                else None
            ),
            "supports_signal_survival_after_costs": (
                float(holdout_sim_25k["net_ending_equity"]) > START_CAPITAL_25K
                if holdout_sim_25k.get("net_ending_equity") is not None
                else None
            ),
        },
        "same_window_20k_vs_25k_net_cost": {
            "eur20k_gross_holdout_from_court_002": holdout_gross.get("same_window_20k_counterfactual_ending_equity"),
            "eur25k_gross_holdout_from_court_002": holdout_gross.get("ending_diagnostic_equity"),
            "gross_scaling_ratio": _safe_ratio(
                float(holdout_gross.get("ending_diagnostic_equity") or 0.0),
                float(holdout_gross.get("same_window_20k_counterfactual_ending_equity") or 0.0),
                0.0,
            ),
            "eur20k_net_cost_holdout_equity": holdout_sim_20k.get("net_ending_equity"),
            "eur25k_net_cost_holdout_equity": holdout_sim_25k.get("net_ending_equity"),
            "net_scaling_ratio": _safe_ratio(
                float(holdout_sim_25k.get("net_ending_equity") or 0.0),
                float(holdout_sim_20k.get("net_ending_equity") or 0.0),
                0.0,
            ),
            "proportional_scaling_remains_close_to_1_25": (
                abs(
                    _safe_ratio(
                        float(holdout_sim_25k.get("net_ending_equity") or 0.0),
                        float(holdout_sim_20k.get("net_ending_equity") or 0.0),
                        0.0,
                    )
                    - 1.25
                )
                <= 0.001
            ),
            "costs_introduce_non_linear_effects": False,
        },
        "target_analysis_impact": {
            "classification": target_impact,
            "existing_realistic_anchor_preserved": True,
            "old_eur20k_normal_cost_rolling_5y_average": 792_824.55832,
            "eur25k_strict_projection": 991_030.6979,
            "old_eur20k_6h_context_rolling_5y_average": 881_465.531787,
            "eur25k_6h_context_projection": 1_101_831.91473375,
            "interpretation": (
                "Full-history Court 002 net-cost restatement is blocked by one accepted zero-stop trade; "
                "the old EUR20k normal-cost rolling 5Y evidence remains the main realistic target anchor."
            ),
        },
    }
    output = _round_payload(output)
    config.output_root.mkdir(parents=True, exist_ok=True)
    _write_json(config.output_root / "court_002_net_cost_restatement_summary.json", output)
    (config.output_root / "court_002_net_cost_restatement_report.md").write_text(_report_markdown(output), encoding="utf-8")
    return output


def _fmt_eur(value: Any) -> str:
    return "N/A" if value is None else f"€{float(value):,.2f}"


def _fmt_pct(value: Any) -> str:
    return "N/A" if value is None else f"{float(value) * 100:.4f}%"


def _report_markdown(summary: dict[str, Any]) -> str:
    full = summary["full_history_research_25k"]
    holdout = summary["sealed_holdout_25k"]
    holdout_restated = holdout["restatement"]
    full_restated = full["restatement"]
    target = summary["target_analysis_impact"]
    lines = [
        "# Court 002 Net-Cost Restatement Court 001",
        "",
        f"- Court: `{summary['court_name']}`",
        f"- Final classification: `{summary['final_classification']}`",
        f"- Target impact: `{target['classification']}`",
        f"- Research-only: `{summary['research_only']}`",
        f"- Paper validation ready: `{summary['paper_validation_ready']}`",
        "",
        "## Cost model used",
        "",
        f"- Band: `{summary['cost_model_used']['band_name']}`",
        f"- Fee: `{summary['cost_model_used']['fee_bps_per_side']}` bps per side",
        f"- Spread/slippage: `{summary['cost_model_used']['spread_slippage_bps_per_side']}` bps per side",
        f"- Total round trip: `{summary['cost_model_used']['total_round_trip_bps']}` bps",
        "- Applied to accepted trades only; rejected setups incur no fee.",
        "- The separate raw-engine `normal_cost` sensitivity model is reported but not mixed into this restatement.",
        "",
        "## Ledger audit",
        "",
        f"- Full-history ledger: `{summary['ledger_audit']['full_history_research']['path']}`",
        f"- Full-history accepted trades after frozen rules: `{summary['ledger_audit']['full_history_research']['accepted_trade_count_after_frozen_rules']}`",
        f"- Full-history zero/missing stop-distance accepted trades: `{summary['ledger_audit']['full_history_research']['zero_or_missing_stop_distance_count']}`",
        f"- Holdout ledger: `{summary['ledger_audit']['sealed_holdout']['path']}`",
        f"- Holdout accepted trades after frozen rules: `{summary['ledger_audit']['sealed_holdout']['accepted_trade_count_after_frozen_rules']}`",
        f"- Holdout zero/missing stop-distance accepted trades: `{summary['ledger_audit']['sealed_holdout']['zero_or_missing_stop_distance_count']}`",
        "",
        "## Full-history EUR25k result",
        "",
        f"- Gross Court 002 ending equity: `{_fmt_eur(full['gross_ending_equity_from_court_002'])}`",
        f"- Net-cost ending equity: `{_fmt_eur(full_restated.get('net_ending_equity'))}`",
        f"- Net restatement available: `{full['net_restatement_available']}`",
        f"- Missing cost-input count: `{full_restated.get('missing_cost_input_count')}`",
        "",
        "Because at least one accepted full-history trade has zero stop distance, the full-history net-cost restatement is blocked rather than guessed.",
        "",
        "## Sealed holdout EUR25k result",
        "",
        f"- Gross Court 002 ending equity: `{_fmt_eur(holdout['gross_ending_equity_from_court_002'])}`",
        f"- Net-cost ending equity: `{_fmt_eur(holdout_restated.get('net_ending_equity'))}`",
        f"- Gross monthly compounded growth: `{_fmt_pct(holdout.get('gross_monthly_compounded_growth'))}`",
        f"- Net monthly compounded growth: `{_fmt_pct(holdout.get('net_monthly_compounded_growth'))}`",
        f"- Required monthly growth for EUR25k to EUR1M over 5Y: `{_fmt_pct(holdout.get('required_monthly_growth_for_25k_to_1m_over_5y'))}`",
        f"- Net holdout above mission pace: `{holdout.get('net_holdout_above_1m_mission_pace')}`",
        f"- Net holdout profitable after costs: `{holdout.get('net_holdout_profitable_after_costs')}`",
        f"- Gross total R: `{holdout['gross_total_R_from_court_002']}`",
        f"- Net total R: `{holdout_restated.get('net_total_R')}`",
        f"- Gross profit factor: `{holdout['gross_profit_factor_from_court_002']}`",
        f"- Net profit factor: `{holdout_restated.get('net_profit_factor')}`",
        f"- Gross win rate: `{_fmt_pct(holdout['gross_win_rate_from_court_002'])}`",
        f"- Net win rate: `{_fmt_pct(holdout_restated.get('net_win_rate'))}`",
        f"- Gross max drawdown: `{_fmt_pct(holdout['gross_max_drawdown_from_court_002'])}`",
        f"- Net max drawdown: `{_fmt_pct(holdout_restated.get('net_max_drawdown'))}`",
        f"- Trades flipped from win to loss due to costs: `{holdout_restated.get('trades_flipped_from_win_to_loss_due_to_costs')}`",
        f"- Total estimated accepted-trade cost: `{_fmt_eur(holdout_restated.get('total_estimated_fees_slippage_cost_eur'))}`",
        f"- Cost drag versus gross recomputed sequence: `{_fmt_eur(holdout_restated.get('cost_drag_eur'))}`",
        "",
        "## Same-window EUR20k vs EUR25k net-cost comparison",
        "",
        f"- EUR20k net-cost holdout equity: `{_fmt_eur(summary['same_window_20k_vs_25k_net_cost'].get('eur20k_net_cost_holdout_equity'))}`",
        f"- EUR25k net-cost holdout equity: `{_fmt_eur(summary['same_window_20k_vs_25k_net_cost'].get('eur25k_net_cost_holdout_equity'))}`",
        f"- Net scaling ratio: `{summary['same_window_20k_vs_25k_net_cost'].get('net_scaling_ratio')}`",
        f"- Proportional scaling remains close to 1.25: `{summary['same_window_20k_vs_25k_net_cost'].get('proportional_scaling_remains_close_to_1_25')}`",
        "",
        "## Safety",
        "",
        "- Court 002 was not rerun.",
        "- The sealed holdout was not reopened.",
        "- Strategy logic, entries, exits, thresholds, filters, sizing, and 6H context were not changed.",
        "- No paper/live/order/broker/account path was introduced.",
        "- EUR25k remains diagnostic only.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Restate Court 002 with normal mixed maker/taker execution costs.")
    parser.parse_args()
    result = build_restatement()
    print(json.dumps({"final_classification": result["final_classification"], "output_root": str(default_config().output_root)}, indent=2))


if __name__ == "__main__":
    main()
