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
    _ledger_report,
    _max_drawdown,
    _monthly_growth,
    _profit_factor,
    _read_json,
    _safe_ratio,
    _write_json,
    cost_adjusted_r,
    stop_distance_fraction,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import _prepare_rows  # noqa: E402
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _normalize_trade_rows,
    _read_csv_rows,
)


COURT_NAME = "COURT_002_NET_COST_ZERO_STOP_RESOLUTION_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "court_002_net_cost_zero_stop_resolution_court_001"
PASSED = "COURT_002_NET_COST_ZERO_STOP_RESOLUTION_PASSED_RESEARCH_ONLY"
WARNING = "COURT_002_NET_COST_ZERO_STOP_RESOLUTION_WARNING_RESEARCH_ONLY"
FAILED = "COURT_002_NET_COST_ZERO_STOP_RESOLUTION_FAILED_RESEARCH_ONLY"

POLICY_PRIMARY = "EXCLUDE_ZERO_STOP_ZERO_R_ARTIFACT_FROM_NET_COST_CONVERSION"
POLICY_MINUS_1R = "ZERO_STOP_ARTIFACT_AS_MINUS_1R"
POLICY_MINUS_2R = "ZERO_STOP_ARTIFACT_AS_MINUS_2R"

TARGET_CONFIRMED = "TARGET_ANALYSIS_CONFIRMED_AFTER_ZERO_STOP_RESOLUTION"
TARGET_SLIGHTLY_DOWNGRADED = "TARGET_ANALYSIS_SLIGHTLY_DOWNGRADED_AFTER_ZERO_STOP_RESOLUTION"
TARGET_MATERIALLY_DOWNGRADED = "TARGET_ANALYSIS_MATERIALLY_DOWNGRADED_AFTER_ZERO_STOP_RESOLUTION"
TARGET_BLOCKED = "TARGET_ANALYSIS_BLOCKED_AFTER_ZERO_STOP_RESOLUTION"


@dataclass(frozen=True)
class ZeroStopResolutionConfig:
    project_root: Path
    package_root: Path
    court_002_root: Path
    prior_restatement_root: Path
    output_root: Path


def default_config() -> ZeroStopResolutionConfig:
    pkg = package_root()
    return ZeroStopResolutionConfig(
        project_root=project_root(),
        package_root=pkg,
        court_002_root=pkg / "output" / "eur25k_sealed_6m_holdout_court_002",
        prior_restatement_root=pkg / "output" / "court_002_net_cost_restatement_court_001",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round_payload(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, dict):
        return {key: _round_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_payload(item) for item in value]
    return value


def is_zero_stop_artifact(row: dict[str, Any]) -> bool:
    entry = float(row.get("entry_price") or 0.0)
    stop = float(row.get("initial_stop") or 0.0)
    exit_price = float(row.get("exit_price") or 0.0)
    return (
        entry > 0.0
        and entry == stop
        and entry == exit_price
        and float(row.get("r_multiple") or 0.0) == 0.0
        and float(row.get("pnl") or 0.0) == 0.0
        and stop_distance_fraction(row) == 0.0
    )


def _raw_trade_row(raw_engine_root: Path, trade_id: str) -> dict[str, Any]:
    for row in _read_csv_rows(raw_engine_root / "trades.csv"):
        if str(row.get("trade_id") or "") == trade_id:
            return dict(row)
    return {}


def _prepared_rows(raw_engine_root: Path) -> list[dict[str, Any]]:
    return _prepare_rows(
        _normalize_trade_rows(
            _read_csv_rows(raw_engine_root / "trades.csv"),
            _read_csv_rows(raw_engine_root / "setup_log.csv"),
            _read_csv_rows(raw_engine_root / "level_log.csv"),
            _read_csv_rows(raw_engine_root / "liquidity_events.csv"),
        )
    )


def _zero_stop_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if stop_distance_fraction(row) == 0.0]


def _simulate_policy(
    *,
    rows: list[dict[str, Any]],
    start_capital: float,
    policy_name: str,
    round_trip_cost_fraction: float,
) -> dict[str, Any]:
    equity = start_capital
    curve = [start_capital]
    adjusted_r_values: list[float] = []
    gross_r_values = [float(row["r_multiple"]) for row in rows]
    total_cost_eur = 0.0
    total_cost_r = 0.0
    converted = 0
    excluded = 0
    penalized = 0
    flipped = 0
    worse_than_zero = 0
    policy_rows: list[dict[str, Any]] = []

    for index, row in enumerate(rows, start=1):
        gross_r = float(row["r_multiple"])
        artifact = is_zero_stop_artifact(row)
        if artifact and policy_name == POLICY_PRIMARY:
            net_r = 0.0
            cost_r = 0.0
            excluded += 1
            treatment = "zero_stop_zero_R_artifact_excluded_from_cost_conversion"
        elif artifact and policy_name == POLICY_MINUS_1R:
            net_r = -1.0
            cost_r = 0.0
            penalized += 1
            treatment = "zero_stop_artifact_penalized_as_minus_1R"
        elif artifact and policy_name == POLICY_MINUS_2R:
            net_r = -2.0
            cost_r = 0.0
            penalized += 1
            treatment = "zero_stop_artifact_penalized_as_minus_2R"
        else:
            adjusted, cost = cost_adjusted_r(row, round_trip_cost_fraction=round_trip_cost_fraction)
            if adjusted is None or cost is None:
                raise ValueError(f"missing_cost_input_after_zero_stop_policy:{row.get('trade_id')}")
            net_r = adjusted
            cost_r = cost
            converted += 1
            treatment = "normal_round_trip_bps_cost_converted_to_R"

        equity_before = equity
        risk_eur = equity_before * 0.01
        cost_eur = cost_r * risk_eur
        pnl_eur = net_r * risk_eur
        equity = equity_before + pnl_eur
        curve.append(equity)
        total_cost_eur += cost_eur
        total_cost_r += cost_r
        adjusted_r_values.append(net_r)
        if gross_r > 0.0 and net_r <= 0.0:
            flipped += 1
        if gross_r >= 0.0 and net_r < 0.0:
            worse_than_zero += 1
        policy_rows.append(
            {
                "trade_number": index,
                "trade_id": row.get("trade_id"),
                "entry_time": row.get("entry_time"),
                "exit_time": row.get("exit_time"),
                "side": row.get("side"),
                "gross_r": gross_r,
                "net_r": net_r,
                "cost_r": cost_r,
                "estimated_cost_eur": cost_eur,
                "equity_before_trade": equity_before,
                "equity_after_trade": equity,
                "accounting_treatment": treatment,
            }
        )

    return {
        "policy_name": policy_name,
        "starting_equity": start_capital,
        "net_ending_equity": equity,
        "net_return_multiple": equity / start_capital,
        "net_gain": equity - start_capital,
        "gross_total_R": sum(gross_r_values),
        "net_total_R": sum(adjusted_r_values),
        "net_average_R": sum(adjusted_r_values) / len(adjusted_r_values) if adjusted_r_values else 0.0,
        "net_median_R": median(adjusted_r_values) if adjusted_r_values else 0.0,
        "net_profit_factor": _profit_factor(adjusted_r_values),
        "net_win_rate": _safe_ratio(sum(1 for value in adjusted_r_values if value > 0.0), len(adjusted_r_values), 0.0),
        "net_max_drawdown": _max_drawdown(curve),
        "accepted_trades_total": len(rows),
        "accepted_trades_included_in_cost_conversion": converted,
        "accepted_trades_excluded_from_cost_conversion": excluded,
        "accepted_trades_penalized": penalized,
        "trades_flipped_from_win_to_loss_due_to_costs": flipped,
        "trades_filtered_to_worse_than_zero_due_to_costs": worse_than_zero,
        "total_estimated_cost_drag_R": total_cost_r,
        "total_estimated_cost_drag_eur": total_cost_eur,
        "policy_classification": PASSED if equity > start_capital else FAILED,
        "policy_trade_rows": policy_rows,
    }


def _policy_summary(policy_result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in policy_result.items() if key != "policy_trade_rows"}


def _target_impact(primary: dict[str, Any], minus_1r: dict[str, Any], minus_2r: dict[str, Any], holdout: dict[str, Any]) -> str:
    if primary["net_ending_equity"] <= START_CAPITAL_25K:
        return TARGET_MATERIALLY_DOWNGRADED
    if minus_1r["net_ending_equity"] <= START_CAPITAL_25K or minus_2r["net_ending_equity"] <= START_CAPITAL_25K:
        return TARGET_SLIGHTLY_DOWNGRADED
    if holdout.get("net_holdout_above_1m_mission_pace") is False:
        return TARGET_SLIGHTLY_DOWNGRADED
    return TARGET_CONFIRMED


def build_zero_stop_resolution(config: ZeroStopResolutionConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    court_summary = _read_json(config.court_002_root / "eur25k_sealed_6m_holdout_summary.json")
    prior_summary = _read_json(config.prior_restatement_root / "court_002_net_cost_restatement_summary.json")
    research_root = config.court_002_root / "research_only_eur25k_replay" / "raw_engine"
    holdout_root = config.court_002_root / "holdout_validation" / "raw_engine"

    research_selected, research_removed = _accepted_trades_from_existing_artifacts(config, research_root)
    holdout_selected, holdout_removed = _accepted_trades_from_existing_artifacts(config, holdout_root)
    research_zero_accepted = _zero_stop_rows(research_selected)
    holdout_zero_accepted = _zero_stop_rows(holdout_selected)
    research_zero_rejected = _zero_stop_rows(research_removed)
    holdout_zero_rejected = _zero_stop_rows(holdout_removed)

    target_trade_id = "BTCUSDT-5066"
    target_rows = [row for row in research_zero_accepted if str(row.get("trade_id") or "") == target_trade_id]
    target = target_rows[0] if target_rows else {}
    raw_target = _raw_trade_row(research_root, target_trade_id)
    gross_equity_changed = bool(target and float(target.get("pnl") or 0.0) != 0.0)
    zero_stop_artifact_valid = bool(target and is_zero_stop_artifact(target))

    primary = _simulate_policy(
        rows=research_selected,
        start_capital=START_CAPITAL_25K,
        policy_name=POLICY_PRIMARY,
        round_trip_cost_fraction=float(PRIMARY_COST_MODEL["round_trip_cost_fraction"]),
    )
    minus_1r = _simulate_policy(
        rows=research_selected,
        start_capital=START_CAPITAL_25K,
        policy_name=POLICY_MINUS_1R,
        round_trip_cost_fraction=float(PRIMARY_COST_MODEL["round_trip_cost_fraction"]),
    )
    minus_2r = _simulate_policy(
        rows=research_selected,
        start_capital=START_CAPITAL_25K,
        policy_name=POLICY_MINUS_2R,
        round_trip_cost_fraction=float(PRIMARY_COST_MODEL["round_trip_cost_fraction"]),
    )

    holdout_prior = prior_summary["sealed_holdout_25k"]
    target_impact = _target_impact(primary, minus_1r, minus_2r, holdout_prior)
    safety_ok = all(
        [
            len(research_zero_accepted) == 1,
            zero_stop_artifact_valid,
            len(holdout_zero_accepted) == 0,
            primary["net_ending_equity"] > START_CAPITAL_25K,
            minus_1r["net_ending_equity"] > START_CAPITAL_25K,
            minus_2r["net_ending_equity"] > START_CAPITAL_25K,
        ]
    )
    if safety_ok and target_impact == TARGET_CONFIRMED:
        final_classification = PASSED
        reasons = ["zero_stop_artifact_resolved_and_target_analysis_confirmed"]
    elif safety_ok:
        final_classification = WARNING
        reasons = ["zero_stop_artifact_resolved_but_holdout_net_cost_pace_weakens_target_interpretation"]
    else:
        final_classification = FAILED
        reasons = ["zero_stop_artifact_resolution_failed_safety_or_policy_gate"]

    zero_stop_audit = {
        "trade_id": target_trade_id,
        "raw_trade_columns": raw_target,
        "normalized_selected_trade": target,
        "accepted_by_frozen_rules": bool(target),
        "changed_gross_equity": gross_equity_changed,
        "gross_pnl_exactly_zero": bool(target and float(target.get("pnl") or 0.0) == 0.0),
        "stop_distance_exactly_zero": bool(target and stop_distance_fraction(target) == 0.0),
        "entry_equals_stop_equals_exit": bool(
            target
            and float(target.get("entry_price") or 0.0) == float(target.get("initial_stop") or 0.0)
            and float(target.get("entry_price") or 0.0) == float(target.get("exit_price") or 0.0)
        ),
        "notional_can_be_safely_inferred": False,
        "cost_in_R_can_be_safely_inferred": False,
        "appears_to_be_accounting_data_artifact": zero_stop_artifact_valid,
        "similar_zero_stop_rows_among_rejected_full_history_setups": len(research_zero_rejected),
        "similar_zero_stop_rows_among_rejected_holdout_setups": len(holdout_zero_rejected),
        "zero_stop_accepted_rows_in_full_history": len(research_zero_accepted),
        "zero_stop_accepted_rows_in_sealed_holdout": len(holdout_zero_accepted),
        "policy_allowed": safety_ok,
        "policy_reason": "single accepted zero-stop zero-R zero-PnL full-history artifact; sealed holdout clean",
    }

    split = court_summary.get("split_manifest", {})
    holdout_net = holdout_prior["restatement"]["net_ending_equity"]
    holdout_monthly = holdout_prior["net_monthly_compounded_growth"]
    if holdout_monthly is None and split.get("holdout_start") and split.get("holdout_end"):
        holdout_monthly = _monthly_growth(
            START_CAPITAL_25K,
            float(holdout_net),
            str(split["holdout_start"]),
            str(split["holdout_end"]),
        )

    output = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": final_classification,
        "classification_reasons": reasons,
        **SAFETY_FLAGS,
        "input_evidence": {
            "court_002_summary": str(config.court_002_root / "eur25k_sealed_6m_holdout_summary.json"),
            "prior_net_cost_restatement_summary": str(
                config.prior_restatement_root / "court_002_net_cost_restatement_summary.json"
            ),
            "full_history_ledger": str(research_root / "trades.csv"),
            "holdout_ledger": str(holdout_root / "trades.csv"),
            "court_002_rerun_performed": False,
            "sealed_holdout_reopened": False,
            "strategy_logic_changed": False,
        },
        "cost_model_used": PRIMARY_COST_MODEL,
        "zero_stop_trade_audit": zero_stop_audit,
        "ledger_audit": {
            "full_history_research": _ledger_report("full_history_research", research_root, research_selected),
            "sealed_holdout": _ledger_report("sealed_holdout", holdout_root, holdout_selected),
            "full_history_zero_stop_accepted_count": len(research_zero_accepted),
            "full_history_zero_stop_rejected_count": len(research_zero_rejected),
            "holdout_zero_stop_accepted_count": len(holdout_zero_accepted),
            "holdout_zero_stop_rejected_count": len(holdout_zero_rejected),
        },
        "accounting_policies": {
            POLICY_PRIMARY: {
                "primary": True,
                "description": "Document and keep the zero-stop zero-R artifact in the audit, but exclude it from bps-to-R cost conversion.",
                "strategy_behavior_changed": False,
            },
            POLICY_MINUS_1R: {
                "primary": False,
                "description": "Sensitivity only: penalize the zero-stop artifact as -1R.",
                "strategy_behavior_changed": False,
            },
            POLICY_MINUS_2R: {
                "primary": False,
                "description": "Harsh sensitivity only: penalize the zero-stop artifact as -2R.",
                "strategy_behavior_changed": False,
            },
        },
        "full_history_gross_reference": {
            "gross_starting_equity": START_CAPITAL_25K,
            "gross_ending_equity_from_court_002": court_summary["full_history_research_replay"]["ending_diagnostic_equity"],
            "gross_return_multiple_from_court_002": court_summary["full_history_research_replay"]["return_multiple"],
            "gross_total_R_from_court_002": court_summary["full_history_research_replay"]["total_R"],
            "gross_accepted_trades": court_summary["full_history_research_replay"]["accepted_trades"],
        },
        "full_history_net_cost_policies": {
            POLICY_PRIMARY: _policy_summary(primary),
            POLICY_MINUS_1R: _policy_summary(minus_1r),
            POLICY_MINUS_2R: _policy_summary(minus_2r),
        },
        "sealed_holdout_net_cost_result_preserved": {
            "gross_eur25k_holdout": holdout_prior["gross_ending_equity_from_court_002"],
            "net_cost_eur25k_holdout": holdout_net,
            "net_monthly_growth": holdout_monthly,
            "required_monthly_growth_for_eur25k_to_eur1m": REQUIRED_MONTHLY_GROWTH_FOR_25K_TO_1M_5Y,
            "net_total_R": holdout_prior["restatement"]["net_total_R"],
            "net_profit_factor": holdout_prior["restatement"]["net_profit_factor"],
            "net_win_rate": holdout_prior["restatement"]["net_win_rate"],
            "net_max_drawdown": holdout_prior["restatement"]["net_max_drawdown"],
            "holdout_remains_profitable_after_costs": holdout_net > START_CAPITAL_25K,
            "holdout_remains_signal_survival_evidence": holdout_net > START_CAPITAL_25K,
            "holdout_alone_meets_eur1m_pace_after_costs": holdout_monthly >= REQUIRED_MONTHLY_GROWTH_FOR_25K_TO_1M_5Y,
            "holdout_zero_stop_accepted_trades": len(holdout_zero_accepted),
            "holdout_was_reopened_or_rerun": False,
        },
        "same_window_20k_vs_25k_net_cost_result_preserved": {
            "eur20k_net_holdout": prior_summary["same_window_20k_vs_25k_net_cost"]["eur20k_net_cost_holdout_equity"],
            "eur25k_net_holdout": prior_summary["same_window_20k_vs_25k_net_cost"]["eur25k_net_cost_holdout_equity"],
            "net_scaling_ratio": prior_summary["same_window_20k_vs_25k_net_cost"]["net_scaling_ratio"],
        },
        "target_analysis_impact": {
            "classification": target_impact,
            "eur25k_to_eur1m_supported_as_strong_target": target_impact in {TARGET_CONFIRMED, TARGET_SLIGHTLY_DOWNGRADED},
            "supported_by_rolling_5y_normal_cost_evidence": True,
            "sealed_holdout_supportive_after_costs": holdout_net > START_CAPITAL_25K,
            "sealed_holdout_alone_meets_eur1m_pace_after_costs": holdout_monthly
            >= REQUIRED_MONTHLY_GROWTH_FOR_25K_TO_1M_5Y,
            "full_history_primary_policy_remains_strong": primary["net_ending_equity"] > 1_000_000.0,
            "full_history_minus_1r_policy_remains_strong": minus_1r["net_ending_equity"] > 1_000_000.0,
            "full_history_minus_2r_policy_remains_strong": minus_2r["net_ending_equity"] > 1_000_000.0,
            "scheduler_court_may_proceed_next": final_classification in {PASSED, WARNING},
            "target_cockpit_should_use": "net_cost_equity",
            "old_eur20k_strict_rolling_5y_average": 792_824.56,
            "eur25k_strict_projection": 991_030.70,
            "old_eur20k_6h_context_rolling_5y_average": 881_465.53,
            "eur25k_6h_context_projection": 1_101_831.91,
        },
    }
    output = _round_payload(output)
    config.output_root.mkdir(parents=True, exist_ok=True)
    _write_json(config.output_root / "zero_stop_trade_audit.json", output["zero_stop_trade_audit"])
    _write_json(config.output_root / "court_002_net_cost_zero_stop_resolution_summary.json", output)
    (config.output_root / "court_002_net_cost_zero_stop_resolution_report.md").write_text(
        _report_markdown(output),
        encoding="utf-8",
    )
    return output


def _fmt_eur(value: Any) -> str:
    return "N/A" if value is None else f"€{float(value):,.2f}"


def _fmt_pct(value: Any) -> str:
    return "N/A" if value is None else f"{float(value) * 100:.4f}%"


def _report_markdown(summary: dict[str, Any]) -> str:
    policies = summary["full_history_net_cost_policies"]
    holdout = summary["sealed_holdout_net_cost_result_preserved"]
    target = summary["target_analysis_impact"]
    lines = [
        "# Court 002 Net-Cost Zero-Stop Resolution Court 001",
        "",
        f"- Court: `{summary['court_name']}`",
        f"- Final classification: `{summary['final_classification']}`",
        f"- Target impact: `{target['classification']}`",
        f"- Research-only: `{summary['research_only']}`",
        f"- Paper validation ready: `{summary['paper_validation_ready']}`",
        "",
        "## Zero-stop trade audit",
        "",
        f"- Trade ID: `{summary['zero_stop_trade_audit']['trade_id']}`",
        f"- Accepted by frozen rules: `{summary['zero_stop_trade_audit']['accepted_by_frozen_rules']}`",
        f"- Gross PnL exactly zero: `{summary['zero_stop_trade_audit']['gross_pnl_exactly_zero']}`",
        f"- Stop distance exactly zero: `{summary['zero_stop_trade_audit']['stop_distance_exactly_zero']}`",
        f"- Entry equals stop equals exit: `{summary['zero_stop_trade_audit']['entry_equals_stop_equals_exit']}`",
        f"- Cost in R safely inferable: `{summary['zero_stop_trade_audit']['cost_in_R_can_be_safely_inferred']}`",
        f"- Appears to be accounting/data artifact: `{summary['zero_stop_trade_audit']['appears_to_be_accounting_data_artifact']}`",
        f"- Full-history zero-stop accepted rows: `{summary['ledger_audit']['full_history_zero_stop_accepted_count']}`",
        f"- Holdout zero-stop accepted rows: `{summary['ledger_audit']['holdout_zero_stop_accepted_count']}`",
        "",
        "## Accounting policy",
        "",
        f"- Primary policy: `{POLICY_PRIMARY}`",
        "- The artifact remains documented and contributes 0.0R to primary net equity.",
        "- It is excluded only from bps-to-R cost conversion because cost conversion is undefined.",
        "- Sensitivities also penalize the same artifact as -1R and -2R.",
        "",
        "## Full-history EUR25k net-cost results",
        "",
        f"- Gross Court 002 ending equity: `{_fmt_eur(summary['full_history_gross_reference']['gross_ending_equity_from_court_002'])}`",
    ]
    for policy_name in (POLICY_PRIMARY, POLICY_MINUS_1R, POLICY_MINUS_2R):
        result = policies[policy_name]
        lines.extend(
            [
                "",
                f"### {policy_name}",
                "",
                f"- Net ending equity: `{_fmt_eur(result['net_ending_equity'])}`",
                f"- Net return multiple: `{result['net_return_multiple']}`",
                f"- Net gain: `{_fmt_eur(result['net_gain'])}`",
                f"- Net total R: `{result['net_total_R']}`",
                f"- Net average R: `{result['net_average_R']}`",
                f"- Net median R: `{result['net_median_R']}`",
                f"- Net profit factor: `{result['net_profit_factor']}`",
                f"- Net win rate: `{_fmt_pct(result['net_win_rate'])}`",
                f"- Net max drawdown: `{_fmt_pct(result['net_max_drawdown'])}`",
                f"- Accepted trades included in cost conversion: `{result['accepted_trades_included_in_cost_conversion']}`",
                f"- Accepted trades excluded from cost conversion: `{result['accepted_trades_excluded_from_cost_conversion']}`",
                f"- Accepted trades penalized: `{result['accepted_trades_penalized']}`",
                f"- Trades flipped from win to loss due to costs: `{result['trades_flipped_from_win_to_loss_due_to_costs']}`",
                f"- Total estimated cost drag R: `{result['total_estimated_cost_drag_R']}`",
                f"- Total estimated cost drag EUR: `{_fmt_eur(result['total_estimated_cost_drag_eur'])}`",
                f"- Policy classification: `{result['policy_classification']}`",
            ]
        )
    lines.extend(
        [
            "",
            "## Sealed holdout net-cost result preserved",
            "",
            f"- Gross EUR25k holdout: `{_fmt_eur(holdout['gross_eur25k_holdout'])}`",
            f"- Net-cost EUR25k holdout: `{_fmt_eur(holdout['net_cost_eur25k_holdout'])}`",
            f"- Net monthly growth: `{_fmt_pct(holdout['net_monthly_growth'])}`",
            f"- Required EUR25k to EUR1M monthly growth: `{_fmt_pct(holdout['required_monthly_growth_for_eur25k_to_eur1m'])}`",
            f"- Holdout remains profitable after costs: `{holdout['holdout_remains_profitable_after_costs']}`",
            f"- Holdout alone meets EUR1M pace after costs: `{holdout['holdout_alone_meets_eur1m_pace_after_costs']}`",
            "",
            "## Target interpretation",
            "",
            f"- EUR25k to EUR1M supported as Strong target: `{target['eur25k_to_eur1m_supported_as_strong_target']}`",
            f"- Supported by rolling 5Y normal-cost evidence: `{target['supported_by_rolling_5y_normal_cost_evidence']}`",
            f"- Sealed holdout supportive after costs: `{target['sealed_holdout_supportive_after_costs']}`",
            f"- Sealed holdout alone meets EUR1M pace after costs: `{target['sealed_holdout_alone_meets_eur1m_pace_after_costs']}`",
            f"- Full-history primary policy remains strong: `{target['full_history_primary_policy_remains_strong']}`",
            f"- Full-history -1R policy remains strong: `{target['full_history_minus_1r_policy_remains_strong']}`",
            f"- Full-history -2R policy remains strong: `{target['full_history_minus_2r_policy_remains_strong']}`",
            f"- Scheduler court may proceed next: `{target['scheduler_court_may_proceed_next']}`",
            f"- Target cockpit should use: `{target['target_cockpit_should_use']}`",
            "",
            "## Safety",
            "",
            "- Court 002 was not rerun.",
            "- The sealed holdout was not reopened.",
            "- No strategy logic, entries, exits, filters, thresholds, sizing, frozen rules, or 6H context changed.",
            "- No paper/live/order/broker/account path was introduced.",
            "- EUR25k remains diagnostic only.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Resolve the Court 002 zero-stop net-cost accounting artifact.")
    parser.parse_args()
    result = build_zero_stop_resolution()
    print(
        json.dumps(
            {
                "final_classification": result["final_classification"],
                "target_impact": result["target_analysis_impact"]["classification"],
                "output_root": str(default_config().output_root),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
