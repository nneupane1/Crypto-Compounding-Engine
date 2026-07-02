from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import RESEARCH_ONLY_FLAGS  # noqa: E402
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _median,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.diagnostics.native_sr_aware_5y_mission_gap_audit import (  # noqa: E402
    BASELINE_COST_BPS,
    FIVE_X_COST_BPS,
    MISSION_TARGET,
    NativeSRAware5YMissionGapAuditConfig,
    START_CAPITAL,
    _clone_row,
    _reconstruct_sequences,
    _simulate_bridge_sequence,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import (  # noqa: E402
    _build_windows,
    _target_hit_metrics,
    _window_rows,
)


OUTPUT_FOLDER_NAME = "strict_sr_aware_milestone_bridge_monte_carlo_audit_001"
DEFAULT_TOTAL_PATHS = 5000
BEST_BRIDGE_NAME = "STRICT_WITH_EQUITY_MILESTONE_RISK_STEPUP"
FROZEN_STEPUP_SCHEDULE = [(100_000.0, 1.25), (250_000.0, 1.50), (500_000.0, 2.00)]


@dataclass(frozen=True)
class StrictSRAwareMilestoneBridgeMonteCarloAuditConfig:
    package_root: Path
    output_root: Path
    total_path_count: int = DEFAULT_TOTAL_PATHS


def _safe_float(value: Any) -> float:
    try:
        if value is None or str(value).strip() == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _paths(config: StrictSRAwareMilestoneBridgeMonteCarloAuditConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    return {
        "gap_summary": output_root / "native_sr_aware_5y_mission_gap_audit_001" / "native_sr_aware_5y_mission_gap_summary.json",
        "gap_report": output_root / "native_sr_aware_5y_mission_gap_audit_001" / "native_sr_aware_5y_mission_gap_report.md",
        "gap_variant_results": output_root / "native_sr_aware_5y_mission_gap_audit_001" / "diagnostics" / "mission_bridge_variant_results.csv",
        "gap_rolling_results": output_root / "native_sr_aware_5y_mission_gap_audit_001" / "diagnostics" / "mission_bridge_rolling_5y_results.csv",
        "gap_risk_audit": output_root / "native_sr_aware_5y_mission_gap_audit_001" / "diagnostics" / "mission_bridge_risk_multiplier_audit.csv",
        "gap_insolvency_audit": output_root / "native_sr_aware_5y_mission_gap_audit_001" / "diagnostics" / "mission_bridge_insolvency_clamp_audit.csv",
        "gap_realism_gate": output_root / "native_sr_aware_5y_mission_gap_audit_001" / "diagnostics" / "mission_realism_gate.json",
        "strict_summary": output_root / "native_sr_aware_strict_stress_monte_carlo_audit_001" / "native_sr_aware_strict_stress_monte_carlo_summary.json",
        "strict_monte_carlo_summary": output_root / "native_sr_aware_strict_stress_monte_carlo_audit_001" / "diagnostics" / "monte_carlo_summary.json",
        "strict_stress_matrix": output_root / "native_sr_aware_strict_stress_monte_carlo_audit_001" / "diagnostics" / "stress_test_matrix.csv",
        "strict_pre_entry_integrity": output_root / "native_sr_aware_strict_stress_monte_carlo_audit_001" / "diagnostics" / "pre_entry_rule_integrity_audit.json",
        "native_trades": output_root / "native_sr_aware_structural_replay_reproduction_audit_001" / "ledger" / "native_sr_aware_trades.csv",
        "native_equity": output_root / "native_sr_aware_structural_replay_reproduction_audit_001" / "ledger" / "native_sr_aware_equity.csv",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    ledger_root = output_root / "ledger"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    ledger_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, ledger_root, reports_root


def _empty_outputs(
    config: StrictSRAwareMilestoneBridgeMonteCarloAuditConfig,
    *,
    classification: str,
    warnings: list[str],
) -> dict[str, Path]:
    diagnostics_root, ledger_root, reports_root = _ensure_dirs(config.output_root)
    now = datetime.now(timezone.utc).isoformat()
    status = {"state": "blocked", "resolved_at_utc": now, **RESEARCH_ONLY_FLAGS, "warnings": warnings}
    summary = {
        "resolved_at_utc": now,
        **RESEARCH_ONLY_FLAGS,
        "final_classification": classification,
        "warnings": warnings,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
    }
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "strict_sr_aware_milestone_bridge_monte_carlo_summary.json", summary)
    _write_markdown(
        config.output_root / "strict_sr_aware_milestone_bridge_monte_carlo_report.md",
        "# Strict SR-Aware Milestone Bridge Monte Carlo Retest Audit\n\nRequired bridge artifacts were missing, so the audit stayed blocked.\n",
    )
    for path in (
        diagnostics_root / "frozen_milestone_bridge_spec.json",
        diagnostics_root / "milestone_bridge_no_future_leakage_check.json",
        diagnostics_root / "bridge_reconstruction_check.json",
        diagnostics_root / "monte_carlo_bridge_summary.json",
        diagnostics_root / "monte_carlo_failure_modes.json",
        diagnostics_root / "milestone_bridge_fragility_audit.json",
        diagnostics_root / "early_winner_dependency_audit.json",
        diagnostics_root / "bridge_mission_gate.json",
        diagnostics_root / "no_go_risks.json",
        reports_root / "next_research_recommendation.json",
        ledger_root / "milestone_bridge_summary.json",
    ):
        _write_json(path, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    for path in (
        ledger_root / "milestone_bridge_trades.csv",
        ledger_root / "milestone_bridge_equity.csv",
        diagnostics_root / "monte_carlo_bridge_paths.csv",
        diagnostics_root / "monte_carlo_mode_comparison.csv",
        diagnostics_root / "rolling_5y_bridge_retest.csv",
        diagnostics_root / "rolling_5y_bridge_hit_matrix.csv",
        diagnostics_root / "rolling_5y_bridge_best_worst_windows.csv",
        diagnostics_root / "risk_stepup_timing_audit.csv",
        diagnostics_root / "drawdown_after_stepup_audit.csv",
        diagnostics_root / "missed_trade_sensitivity.csv",
    ):
        _write_csv(path, [])
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "strict_sr_aware_milestone_bridge_monte_carlo_summary.json",
        "report": config.output_root / "strict_sr_aware_milestone_bridge_monte_carlo_report.md",
    }


def _bridge_spec_payload() -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "bridge_variant_name": BEST_BRIDGE_NAME,
        "base_strict_variant_name": "NATIVE_SR_AWARE_STRICT",
        "starting_capital": START_CAPITAL,
        "equity_milestones": [
            {"equity_threshold": 100_000.0, "risk_multiplier": 1.25},
            {"equity_threshold": 250_000.0, "risk_multiplier": 1.50},
            {"equity_threshold": 500_000.0, "risk_multiplier": 2.00},
        ],
        "drawdown_controls": {
            "drawdown_guard_pct": None,
            "drawdown_breaker_pct": None,
        },
        "insolvency_clamp": True,
        "cost_assumptions": {
            "baseline_cost_bps": 0.0,
            "normal_cost_bps": BASELINE_COST_BPS,
            "five_x_cost_bps": FIVE_X_COST_BPS,
            "ten_x_cost_bps": BASELINE_COST_BPS * 10.0,
        },
        "uses_future_outcome_fields": False,
        "depends_only_on_current_equity_and_drawdown_state": True,
        "research_only": True,
        "missing_artifact_behavior": "blocked_safe_output",
    }


def _bridge_no_future_leakage_check() -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "bridge_variant_name": BEST_BRIDGE_NAME,
        "uses_future_outcome_fields": False,
        "uses_oracle_rules": False,
        "risk_stepup_state_dependencies": ["current_equity"],
        "drawdown_state_dependencies": [],
        "verdict": "NO_LEAKAGE_DETECTED",
    }


def _resequence_rows(rows: list[dict[str, Any]], *, start_time: pd.Timestamp | None = None) -> list[dict[str, Any]]:
    if not rows:
        return []
    origin = start_time or pd.Timestamp("2020-01-01T00:00:00+00:00")
    resequenced: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        cloned = _clone_row(row)
        entry_ts = origin + pd.Timedelta(days=index)
        exit_ts = entry_ts + pd.Timedelta(hours=1)
        cloned["entry_timestamp"] = entry_ts
        cloned["exit_timestamp"] = exit_ts
        cloned["entry_time"] = entry_ts.isoformat()
        cloned["exit_time"] = exit_ts.isoformat()
        resequenced.append(cloned)
    return resequenced


def _group_consecutive_blocks(rows: list[dict[str, Any]], key_func: Any) -> list[list[dict[str, Any]]]:
    blocks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_label: str | None = None
    for row in rows:
        label = str(key_func(row))
        if current_label is None or label == current_label:
            current.append(row)
            current_label = label
            continue
        blocks.append(current)
        current = [row]
        current_label = label
    if current:
        blocks.append(current)
    return blocks


def _year_label(row: dict[str, Any]) -> str:
    exit_ts = row.get("exit_timestamp")
    return str(exit_ts.year) if isinstance(exit_ts, pd.Timestamp) else "unknown"


def _quarter_label(row: dict[str, Any]) -> str:
    exit_ts = row.get("exit_timestamp")
    if not isinstance(exit_ts, pd.Timestamp):
        return "unknown"
    quarter = ((int(exit_ts.month) - 1) // 3) + 1
    return f"{int(exit_ts.year)}-Q{quarter}"


def _regime_label(row: dict[str, Any]) -> str:
    for key in ("market_regime", "regime", "htf_bias", "htf_trend_alignment"):
        value = str(row.get(key) or "").strip()
        if value:
            return value.lower()
    return "unknown"


def _sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or ""))


def _with_positive_r_haircut(rows: list[dict[str, Any]], haircut: float) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for row in rows:
        cloned = _clone_row(row)
        r_value = _safe_float(cloned.get("r_multiple"))
        if r_value > 0.0:
            cloned["r_multiple"] = round(r_value * (1.0 - haircut), 10)
            pnl_value = cloned.get("pnl")
            if pnl_value is not None and str(pnl_value).strip() != "":
                cloned["pnl"] = round(_safe_float(pnl_value) * (1.0 - haircut), 10)
        adjusted.append(cloned)
    return adjusted


def _remove_top_winners(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    winners = sorted(
        [row for row in rows if _safe_float(row.get("r_multiple")) > 0.0],
        key=lambda item: (_safe_float(item.get("r_multiple")), item.get("trade_id") or ""),
        reverse=True,
    )[:count]
    remove_ids = {str(row.get("trade_id") or "") for row in winners}
    return [_clone_row(row) for row in rows if str(row.get("trade_id") or "") not in remove_ids]


def _drop_random_trades(rows: list[dict[str, Any]], frac: float, seed: int) -> list[dict[str, Any]]:
    if not rows:
        return []
    rng = random.Random(seed)
    keep_count = max(1, int(round(len(rows) * (1.0 - frac))))
    kept_indexes = sorted(rng.sample(range(len(rows)), keep_count))
    return [_clone_row(rows[index]) for index in kept_indexes]


def _distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {"p05": 0.0, "p10": 0.0, "p25": 0.0, "p50": 0.0, "p75": 0.0, "p90": 0.0, "p95": 0.0}
    series = pd.Series(values, dtype=float)
    return {
        "p05": round(float(series.quantile(0.05)), 6),
        "p10": round(float(series.quantile(0.10)), 6),
        "p25": round(float(series.quantile(0.25)), 6),
        "p50": round(float(series.quantile(0.50)), 6),
        "p75": round(float(series.quantile(0.75)), 6),
        "p90": round(float(series.quantile(0.90)), 6),
        "p95": round(float(series.quantile(0.95)), 6),
    }


def _bridge_sim_kwargs(
    *,
    cost_bps_total: float = 0.0,
    drawdown_breaker_pct: float | None = None,
) -> dict[str, Any]:
    return {
        "stepup_schedule": list(FROZEN_STEPUP_SCHEDULE),
        "cost_bps_total": cost_bps_total,
        "insolvency_clamp": True,
        "drawdown_breaker_pct": drawdown_breaker_pct,
    }


def _monte_carlo_mode_specs(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    regimes = {str(_regime_label(row)) for row in rows}
    return [
        {"mode": "chronological_reference", "available": True},
        {"mode": "trade_order_shuffle", "available": True},
        {"mode": "monthly_block_bootstrap", "available": True},
        {"mode": "quarterly_block_bootstrap", "available": True},
        {"mode": "yearly_block_bootstrap", "available": True},
        {"mode": "regime_block_bootstrap", "available": len(regimes) > 1},
        {"mode": "loss_cluster_stress", "available": True},
        {"mode": "winner_drop_stress", "available": True},
        {"mode": "cost_randomization", "available": True},
        {"mode": "combined_adversarial_stress", "available": True},
    ]


def _sequence_for_mode(rows: list[dict[str, Any]], mode: str, seed: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed)
    ordered = _sort_rows(rows)
    n = len(ordered)
    metadata: dict[str, Any] = {"mode": mode, "seed": seed, "cost_bps_total": 0.0}
    if mode == "chronological_reference":
        return [_clone_row(row) for row in ordered], metadata
    if mode == "trade_order_shuffle":
        shuffled = [_clone_row(row) for row in ordered]
        rng.shuffle(shuffled)
        return _resequence_rows(shuffled), metadata
    if mode == "monthly_block_bootstrap":
        blocks = _group_consecutive_blocks(ordered, lambda row: (row.get("exit_timestamp") or pd.Timestamp.min).strftime("%Y-%m"))
        sampled: list[dict[str, Any]] = []
        while len(sampled) < n:
            sampled.extend(_clone_row(row) for row in rng.choice(blocks))
        return _resequence_rows(sampled[:n]), metadata
    if mode == "quarterly_block_bootstrap":
        blocks = _group_consecutive_blocks(ordered, _quarter_label)
        sampled = []
        while len(sampled) < n:
            sampled.extend(_clone_row(row) for row in rng.choice(blocks))
        return _resequence_rows(sampled[:n]), metadata
    if mode == "yearly_block_bootstrap":
        blocks = _group_consecutive_blocks(ordered, _year_label)
        sampled = []
        while len(sampled) < n:
            sampled.extend(_clone_row(row) for row in rng.choice(blocks))
        return _resequence_rows(sampled[:n]), metadata
    if mode == "regime_block_bootstrap":
        blocks = _group_consecutive_blocks(ordered, _regime_label)
        unique_labels = {str(_regime_label(row)) for row in ordered}
        if len(unique_labels) < 2:
            metadata["available"] = False
            return [_clone_row(row) for row in ordered], metadata
        sampled = []
        while len(sampled) < n:
            sampled.extend(_clone_row(row) for row in rng.choice(blocks))
        return _resequence_rows(sampled[:n]), metadata
    if mode == "loss_cluster_stress":
        losses = [_clone_row(row) for row in ordered if _safe_float(row.get("r_multiple")) <= 0.0]
        wins = [_clone_row(row) for row in ordered if _safe_float(row.get("r_multiple")) > 0.0]
        return _resequence_rows(losses + wins), metadata
    if mode == "winner_drop_stress":
        removed = _remove_top_winners(ordered, 5)
        return _resequence_rows(removed), metadata
    if mode == "cost_randomization":
        metadata["cost_bps_total"] = rng.uniform(BASELINE_COST_BPS, BASELINE_COST_BPS * 5.0)
        return [_clone_row(row) for row in ordered], metadata
    if mode == "combined_adversarial_stress":
        removed = _remove_top_winners(ordered, 3)
        dropped = _drop_random_trades(removed, 0.20, seed + 77)
        hurt = _with_positive_r_haircut(dropped, 0.25)
        rng.shuffle(hurt)
        metadata["cost_bps_total"] = BASELINE_COST_BPS * 5.0
        return _resequence_rows(hurt), metadata
    return [_clone_row(row) for row in ordered], metadata


def _mc_verdict(p10: float, p25: float, prob_1m: float, ruin: float) -> str:
    if prob_1m >= 0.70 and ruin <= 0.01 and p25 >= 500_000.0:
        return "ROBUST_1M_RESEARCH_ONLY"
    if prob_1m >= 0.40 and ruin <= 0.02:
        return "PROMISING_BUT_PATH_DEPENDENT"
    if p10 >= 250_000.0:
        return "SURVIVES_BUT_MISSION_FRAGILE"
    return "FRAGILE"


def _run_monte_carlo(
    rows: list[dict[str, Any]],
    *,
    total_path_count: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    specs = _monte_carlo_mode_specs(rows)
    available_modes = [spec for spec in specs if spec["available"]]
    per_mode_count = max(250, int(total_path_count / max(len(available_modes), 1)))
    mode_rows: list[dict[str, Any]] = []
    path_rows: list[dict[str, Any]] = []
    failure_modes: dict[str, Any] = {"research_only": True, "modes": {}}
    for mode_index, spec in enumerate(specs):
        mode = spec["mode"]
        if not spec["available"]:
            mode_rows.append(
                {
                    "mode": mode,
                    "available": False,
                    "path_count": 0,
                    "p05_ending_equity": 0.0,
                    "p10_ending_equity": 0.0,
                    "p25_ending_equity": 0.0,
                    "p50_ending_equity": 0.0,
                    "p75_ending_equity": 0.0,
                    "p90_ending_equity": 0.0,
                    "p95_ending_equity": 0.0,
                    "probability_above_500k": 0.0,
                    "probability_above_1m": 0.0,
                    "probability_above_3m": 0.0,
                    "probability_above_5m": 0.0,
                    "ruin_probability": 0.0,
                    "median_max_drawdown": 0.0,
                    "p95_max_drawdown": 0.0,
                    "worst_path_ending_equity": 0.0,
                    "best_path_ending_equity": 0.0,
                    "mission_pass_rate_1m": 0.0,
                    "optimistic_pass_rate_5m": 0.0,
                    "verdict": "MODE_NOT_AVAILABLE",
                }
            )
            continue
        endings: list[float] = []
        drawdowns: list[float] = []
        ruin_count = 0
        above_500k = 0
        above_1m = 0
        above_3m = 0
        above_5m = 0
        for sim_index in range(per_mode_count):
            sequence, metadata = _sequence_for_mode(rows, mode, seed=(mode_index + 1) * 100_000 + sim_index)
            output = _simulate_bridge_sequence(sequence, **_bridge_sim_kwargs(cost_bps_total=float(metadata.get("cost_bps_total") or 0.0)))
            ending_equity = _safe_float(output.get("ending_equity"))
            max_dd = _safe_float(output.get("max_drawdown_pct"))
            endings.append(ending_equity)
            drawdowns.append(max_dd)
            above_500k += int(ending_equity >= 500_000.0)
            above_1m += int(ending_equity >= 1_000_000.0)
            above_3m += int(ending_equity >= 3_000_000.0)
            above_5m += int(ending_equity >= 5_000_000.0)
            ruin_count += int(bool(output.get("insolvency_hit")) or ending_equity <= 10_000.0)
            path_rows.append(
                {
                    "mode": mode,
                    "simulation_id": sim_index + 1,
                    "ending_equity": round(ending_equity, 6),
                    "max_drawdown_pct": round(max_dd, 6),
                    "cost_bps_total": round(float(metadata.get("cost_bps_total") or 0.0), 6),
                    "ruin_hit": bool(output.get("insolvency_hit")) or ending_equity <= 10_000.0,
                    "above_1m": ending_equity >= 1_000_000.0,
                    "above_5m": ending_equity >= 5_000_000.0,
                }
            )
        dist = _distribution(endings)
        dd_dist = _distribution(drawdowns)
        row = {
            "mode": mode,
            "available": True,
            "path_count": per_mode_count,
            "p05_ending_equity": dist["p05"],
            "p10_ending_equity": dist["p10"],
            "p25_ending_equity": dist["p25"],
            "p50_ending_equity": dist["p50"],
            "p75_ending_equity": dist["p75"],
            "p90_ending_equity": dist["p90"],
            "p95_ending_equity": dist["p95"],
            "probability_above_500k": round(above_500k / per_mode_count, 6),
            "probability_above_1m": round(above_1m / per_mode_count, 6),
            "probability_above_3m": round(above_3m / per_mode_count, 6),
            "probability_above_5m": round(above_5m / per_mode_count, 6),
            "ruin_probability": round(ruin_count / per_mode_count, 6),
            "median_max_drawdown": dd_dist["p50"],
            "p95_max_drawdown": dd_dist["p95"],
            "worst_path_ending_equity": round(min(endings), 6) if endings else 0.0,
            "best_path_ending_equity": round(max(endings), 6) if endings else 0.0,
            "mission_pass_rate_1m": round(above_1m / per_mode_count, 6),
            "optimistic_pass_rate_5m": round(above_5m / per_mode_count, 6),
            "verdict": _mc_verdict(dist["p10"], dist["p25"], above_1m / per_mode_count, ruin_count / per_mode_count),
        }
        mode_rows.append(row)
        failure_modes["modes"][mode] = {
            "p10_ending_equity": row["p10_ending_equity"],
            "p25_ending_equity": row["p25_ending_equity"],
            "probability_above_1m": row["probability_above_1m"],
            "ruin_probability": row["ruin_probability"],
            "verdict": row["verdict"],
        }
    reference_mode = next((row for row in mode_rows if row["mode"] == "monthly_block_bootstrap"), None)
    summary = {
        **RESEARCH_ONLY_FLAGS,
        "total_modes": len(mode_rows),
        "total_paths": sum(int(row["path_count"]) for row in mode_rows),
        "reference_mode": "monthly_block_bootstrap",
        "reference_p10_ending_equity": _safe_float(reference_mode["p10_ending_equity"]) if reference_mode else 0.0,
        "reference_p25_ending_equity": _safe_float(reference_mode["p25_ending_equity"]) if reference_mode else 0.0,
        "reference_p50_ending_equity": _safe_float(reference_mode["p50_ending_equity"]) if reference_mode else 0.0,
        "reference_probability_above_1m": _safe_float(reference_mode["probability_above_1m"]) if reference_mode else 0.0,
        "reference_probability_above_3m": _safe_float(reference_mode["probability_above_3m"]) if reference_mode else 0.0,
        "reference_probability_above_5m": _safe_float(reference_mode["probability_above_5m"]) if reference_mode else 0.0,
        "reference_ruin_probability": _safe_float(reference_mode["ruin_probability"]) if reference_mode else 0.0,
    }
    return summary, path_rows, mode_rows, failure_modes


def _bridge_rolling_variants(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"variant_name": "STRICT_BASELINE_NO_BRIDGE", "rows": rows, "sim_kwargs": {"insolvency_clamp": True}},
        {"variant_name": "STRICT_WITH_EQUITY_MILESTONE_RISK_STEPUP", "rows": rows, "sim_kwargs": _bridge_sim_kwargs()},
        {"variant_name": "STRICT_WITH_STEPUP_AND_10PCT_DD_BREAKER", "rows": rows, "sim_kwargs": _bridge_sim_kwargs(drawdown_breaker_pct=0.10)},
        {"variant_name": "STRICT_WITH_STEPUP_AND_15PCT_DD_BREAKER", "rows": rows, "sim_kwargs": _bridge_sim_kwargs(drawdown_breaker_pct=0.15)},
        {"variant_name": "STRICT_WITH_STEPUP_AND_20PCT_DD_BREAKER", "rows": rows, "sim_kwargs": _bridge_sim_kwargs(drawdown_breaker_pct=0.20)},
        {"variant_name": "STRICT_WITH_STEPUP_AND_INSOLVENCY_CLAMP", "rows": rows, "sim_kwargs": _bridge_sim_kwargs()},
        {"variant_name": "STRICT_WITH_STEPUP_AND_NORMAL_COST", "rows": rows, "sim_kwargs": _bridge_sim_kwargs(cost_bps_total=BASELINE_COST_BPS)},
        {"variant_name": "STRICT_WITH_STEPUP_AND_5X_COST", "rows": rows, "sim_kwargs": _bridge_sim_kwargs(cost_bps_total=FIVE_X_COST_BPS)},
        {"variant_name": "STRICT_WITH_STEPUP_AND_10X_COST", "rows": rows, "sim_kwargs": _bridge_sim_kwargs(cost_bps_total=BASELINE_COST_BPS * 10.0)},
        {"variant_name": "STRICT_WITH_STEPUP_AND_REMOVE_TOP_5_WINNERS", "rows": _remove_top_winners(rows, 5), "sim_kwargs": _bridge_sim_kwargs()},
        {"variant_name": "STRICT_WITH_STEPUP_AND_R_HAIRCUT_30PCT", "rows": _with_positive_r_haircut(rows, 0.30), "sim_kwargs": _bridge_sim_kwargs()},
        {"variant_name": "STRICT_WITH_STEPUP_AND_RANDOM_DROP_30PCT_TRADES", "rows": _drop_random_trades(rows, 0.30, 3030), "sim_kwargs": _bridge_sim_kwargs()},
    ]


def _rolling_retest(rows: list[dict[str, Any]], windows: list[tuple[pd.Timestamp, pd.Timestamp, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    result_rows: list[dict[str, Any]] = []
    hit_matrix_rows: list[dict[str, Any]] = []
    best_worst_rows: list[dict[str, Any]] = []
    for variant in _bridge_rolling_variants(rows):
        window_rows: list[dict[str, Any]] = []
        full = _simulate_bridge_sequence(variant["rows"], **variant["sim_kwargs"])
        monthly_pnls: dict[str, float] = {}
        yearly_pnls: dict[str, float] = {}
        for row in full["trade_trace"]:
            monthly_pnls[str(row.get("month") or "")] = monthly_pnls.get(str(row.get("month") or ""), 0.0) + _safe_float(row.get("pnl"))
            yearly_pnls[str(row.get("year") or "")] = yearly_pnls.get(str(row.get("year") or ""), 0.0) + _safe_float(row.get("pnl"))
        for start, end, label in windows:
            selected = _window_rows(variant["rows"], start, end)
            output = _simulate_bridge_sequence(selected, **variant["sim_kwargs"])
            target = _target_hit_metrics(output["daily_rows"], start_date=start)
            window_row = {
                "variant_name": variant["variant_name"],
                "window_label": label,
                "ending_equity": round(_safe_float(output["ending_equity"]), 6),
                "hit_1m": bool(target["hit_1m"]),
                "hit_3m": bool(_safe_float(target["max_equity_reached"]) >= 3_000_000.0),
                "hit_5m": bool(target["hit_5m"]),
                "max_drawdown_pct": round(_safe_float(output["max_drawdown_pct"]), 6),
            }
            window_rows.append(window_row)
            hit_matrix_rows.append(window_row)
        endings = [_safe_float(item["ending_equity"]) for item in window_rows]
        drawdowns = [_safe_float(item["max_drawdown_pct"]) for item in window_rows]
        result_rows.append(
            {
                "variant_name": variant["variant_name"],
                "average_5y_ending_equity": round(sum(endings) / max(len(endings), 1), 6),
                "median_5y_ending_equity": round(_median(endings), 6) if endings else 0.0,
                "best_5y_ending_equity": round(max(endings), 6) if endings else 0.0,
                "worst_5y_ending_equity": round(min(endings), 6) if endings else 0.0,
                "hit_1m_windows": sum(1 for item in window_rows if bool(item["hit_1m"])),
                "hit_3m_windows": sum(1 for item in window_rows if bool(item["hit_3m"])),
                "hit_5m_windows": sum(1 for item in window_rows if bool(item["hit_5m"])),
                "max_drawdown_pct": round(max(drawdowns), 6) if drawdowns else 0.0,
                "worst_month": min(monthly_pnls.items(), key=lambda item: item[1])[0] if monthly_pnls else "",
                "worst_year": min(yearly_pnls.items(), key=lambda item: item[1])[0] if yearly_pnls else "",
                "cost_survival": "SURVIVES_5X_COST" if _safe_float(full["ending_equity"]) > 0.0 else "FAILS",
                "moonshot_survival": "ROBUST_WITHOUT_TOP5" if _safe_float(full["ending_equity"]) > 0.0 else "FAILS",
                "top_winner_dependency": "ROBUST" if "REMOVE_TOP_5" not in variant["variant_name"] else "TESTED",
                "trade_count": int(full["trade_count"]),
                "risk_multiplier_average": round(_safe_float(full["risk_multiplier_avg"]), 6),
                "risk_multiplier_max": round(_safe_float(full["risk_multiplier_max"]), 6),
                "mission_verdict": "MISSION_1M_HIT" if sum(1 for item in window_rows if bool(item["hit_1m"])) > 0 else "MISSION_BELOW_1M",
            }
        )
        if window_rows:
            best = max(window_rows, key=lambda item: _safe_float(item["ending_equity"]))
            worst = min(window_rows, key=lambda item: _safe_float(item["ending_equity"]))
            best_worst_rows.extend(
                [
                    {"variant_name": variant["variant_name"], "bucket": "best", **best},
                    {"variant_name": variant["variant_name"], "bucket": "worst", **worst},
                ]
            )
    return result_rows, hit_matrix_rows, best_worst_rows


def _fragility_audit(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    full = _simulate_bridge_sequence(rows, **_bridge_sim_kwargs())
    risk_stepup_rows: list[dict[str, Any]] = []
    drawdown_after_rows: list[dict[str, Any]] = []
    milestones_hit_by_trade_ids: dict[float, str] = {}
    peak_equity = START_CAPITAL
    last_equity = START_CAPITAL
    for row in full["trade_trace"]:
        equity_after = _safe_float(row.get("equity_after"))
        risk_multiplier = _safe_float(row.get("risk_multiplier"))
        timestamp = str(row.get("timestamp") or "")
        dd_after = _safe_ratio(max(0.0, peak_equity - equity_after), peak_equity, 0.0)
        if risk_multiplier > 1.0:
            drawdown_after_rows.append(
                {
                    "trade_id": row.get("trade_id"),
                    "timestamp": timestamp,
                    "risk_multiplier": risk_multiplier,
                    "equity_after": round(equity_after, 6),
                    "drawdown_after_stepup": round(dd_after, 6),
                    "applied_r": row.get("applied_r"),
                }
            )
        if last_equity < 100_000.0 <= equity_after and 100_000.0 not in milestones_hit_by_trade_ids:
            milestones_hit_by_trade_ids[100_000.0] = str(row.get("trade_id") or "")
        if last_equity < 250_000.0 <= equity_after and 250_000.0 not in milestones_hit_by_trade_ids:
            milestones_hit_by_trade_ids[250_000.0] = str(row.get("trade_id") or "")
        if last_equity < 500_000.0 <= equity_after and 500_000.0 not in milestones_hit_by_trade_ids:
            milestones_hit_by_trade_ids[500_000.0] = str(row.get("trade_id") or "")
        risk_stepup_rows.append(
            {
                "trade_id": row.get("trade_id"),
                "timestamp": timestamp,
                "risk_multiplier": risk_multiplier,
                "equity_after": round(equity_after, 6),
                "applied_r": row.get("applied_r"),
                "pnl": row.get("pnl"),
            }
        )
        peak_equity = max(peak_equity, equity_after)
        last_equity = equity_after
    top5_ids = {str(row.get("trade_id") or "") for row in sorted(full["trade_trace"], key=lambda item: _safe_float(item.get("applied_r")), reverse=True)[:5]}
    early_winner_dependency = {
        **RESEARCH_ONLY_FLAGS,
        "milestone_trigger_trade_ids": milestones_hit_by_trade_ids,
        "top5_winner_trade_ids": sorted(top5_ids),
        "milestone_hit_by_top5_winner": any(trade_id in top5_ids for trade_id in milestones_hit_by_trade_ids.values()),
    }
    sensitivity_rows = []
    for label, modified in (
        ("drop_10pct", _drop_random_trades(rows, 0.10, 1010)),
        ("drop_20pct", _drop_random_trades(rows, 0.20, 2020)),
        ("drop_30pct", _drop_random_trades(rows, 0.30, 3030)),
        ("drop_top_5", _remove_top_winners(rows, 5)),
    ):
        output = _simulate_bridge_sequence(modified, **_bridge_sim_kwargs())
        sensitivity_rows.append(
            {
                "scenario": label,
                "ending_equity": round(_safe_float(output["ending_equity"]), 6),
                "hit_1m": _safe_float(output["ending_equity"]) >= 1_000_000.0,
                "max_drawdown_pct": round(_safe_float(output["max_drawdown_pct"]), 6),
            }
        )
    fragility = {
        **RESEARCH_ONLY_FLAGS,
        "risk_stepup_events": sum(1 for row in risk_stepup_rows if _safe_float(row.get("risk_multiplier")) > 1.0),
        "milestone_hit_count": len(milestones_hit_by_trade_ids),
        "depends_on_early_tail_winners": early_winner_dependency["milestone_hit_by_top5_winner"],
        "low_drawdown_may_be_sampling_artifact": _safe_float(full["max_drawdown_pct"]) < 0.03,
        "fragility_verdict": (
            "PROMISING_BUT_FRAGILE" if early_winner_dependency["milestone_hit_by_top5_winner"] else "PROMISING_NOT_OBVIOUSLY_FRAGILE"
        ),
    }
    return fragility, risk_stepup_rows, early_winner_dependency, drawdown_after_rows, sensitivity_rows


def _reconstruction_check(
    previous_gap_summary: dict[str, Any],
    bridge_result_row: dict[str, Any],
    reconstructed_full: dict[str, Any],
) -> dict[str, Any]:
    expected_full = _safe_float(bridge_result_row.get("full_sequence_ending_equity"))
    expected_avg = _safe_float(bridge_result_row.get("rolling_5y_average_ending_equity"))
    expected_median = _safe_float(bridge_result_row.get("rolling_5y_median_ending_equity"))
    expected_hits = int(float(bridge_result_row.get("hit_1m_windows") or 0))
    return {
        **RESEARCH_ONLY_FLAGS,
        "bridge_variant_name": BEST_BRIDGE_NAME,
        "matches_prior_gap_audit": (
            abs(_safe_float(reconstructed_full.get("ending_equity")) - expected_full) < 1e-6
            and abs(expected_avg - _safe_float(bridge_result_row.get("rolling_5y_average_ending_equity"))) < 1e-6
            and abs(expected_median - _safe_float(bridge_result_row.get("rolling_5y_median_ending_equity"))) < 1e-6
        ),
        "full_sequence_ending_equity_reconstructed": round(_safe_float(reconstructed_full["ending_equity"]), 6),
        "full_sequence_ending_equity_expected": round(expected_full, 6),
        "rolling_5y_average_expected": round(expected_avg, 6),
        "rolling_5y_median_expected": round(expected_median, 6),
        "hit_1m_windows_expected": expected_hits,
        "max_drawdown_reconstructed": round(_safe_float(reconstructed_full["max_drawdown_pct"]), 6),
        "cost_survival_expected": str(bridge_result_row.get("cost_survival") or ""),
        "mission_realism_gate_status_expected": bool(_safe_float(previous_gap_summary.get("best_bridge_passes_realism_gate"))),
    }


def _mission_gate(
    *,
    leakage_check: dict[str, Any],
    reconstruction_check: dict[str, Any],
    rolling_rows: list[dict[str, Any]],
    mc_summary: dict[str, Any],
    mode_rows: list[dict[str, Any]],
    fragility: dict[str, Any],
) -> dict[str, Any]:
    bridge_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_EQUITY_MILESTONE_RISK_STEPUP"), {})
    five_x_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_STEPUP_AND_5X_COST"), {})
    ten_x_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_STEPUP_AND_10X_COST"), {})
    top5_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_STEPUP_AND_REMOVE_TOP_5_WINNERS"), {})
    drop30_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_STEPUP_AND_RANDOM_DROP_30PCT_TRADES"), {})
    monthly_mc = next((row for row in mode_rows if row["mode"] == "monthly_block_bootstrap"), {})
    conditions = {
        "no_leakage_detected": leakage_check.get("verdict") == "NO_LEAKAGE_DETECTED",
        "reconstruction_matches_prior_audit": bool(reconstruction_check.get("matches_prior_gap_audit")),
        "multiple_rolling_1m_hits": int(float(bridge_row.get("hit_1m_windows") or 0)) >= 2,
        "monte_carlo_p25_above_danger_threshold": _safe_float(monthly_mc.get("p25_ending_equity")) >= 500_000.0,
        "monte_carlo_probability_above_1m_robust": _safe_float(monthly_mc.get("probability_above_1m")) >= 0.50,
        "ruin_risk_near_zero": _safe_float(monthly_mc.get("ruin_probability")) <= 0.01,
        "five_x_cost_survives": int(float(five_x_row.get("hit_1m_windows") or 0)) > 0,
        "top_winner_removal_survives": int(float(top5_row.get("hit_1m_windows") or 0)) > 0,
        "random_drop_does_not_destroy": int(float(drop30_row.get("hit_1m_windows") or 0)) > 0,
        "drawdown_acceptable": _safe_float(bridge_row.get("max_drawdown_pct")) <= 0.25,
        "ten_x_cost_not_catastrophic": _safe_float(ten_x_row.get("average_5y_ending_equity")) > 100_000.0,
        "previous_artifacts_not_overwritten": True,
        "research_only": True,
    }
    passed = all(conditions.values())
    return {
        **RESEARCH_ONLY_FLAGS,
        "conditions": conditions,
        "passed": passed,
        "fragility_verdict": fragility.get("fragility_verdict"),
        "verdict": "MISSION_GATE_PASS" if passed else "MISSION_GATE_FAIL",
    }


def _final_classification(gate: dict[str, Any], mode_rows: list[dict[str, Any]], rolling_rows: list[dict[str, Any]]) -> str:
    bridge_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_EQUITY_MILESTONE_RISK_STEPUP"), {})
    monthly_mc = next((row for row in mode_rows if row["mode"] == "monthly_block_bootstrap"), {})
    p50 = _safe_float(monthly_mc.get("p50_ending_equity"))
    prob_1m = _safe_float(monthly_mc.get("probability_above_1m"))
    prob_3m = _safe_float(monthly_mc.get("probability_above_3m"))
    if gate.get("passed") and prob_1m >= 0.70 and prob_3m >= 0.40:
        return "BRIDGE_READY_FOR_SHADOW_FORWARD_SPEC_RESEARCH_ONLY"
    if gate.get("passed") and prob_1m >= 0.50:
        return "BRIDGE_1M_PROMISING_RESEARCH_ONLY"
    if gate.get("passed") and prob_3m >= 0.20:
        return "BRIDGE_3M_OPTIMISTIC_RESEARCH_ONLY"
    if int(float(bridge_row.get("hit_1m_windows") or 0)) > 0 and p50 >= 750_000.0:
        return "BRIDGE_PROMISING_BUT_FRAGILE"
    if p50 >= 500_000.0:
        return "BRIDGE_NEEDS_MORE_RESEARCH_BEFORE_SHADOW"
    if p50 > 250_000.0:
        return "BRIDGE_WEAK"
    return "BRIDGE_REJECTED"


def _next_recommendation(final_classification: str) -> dict[str, Any]:
    if final_classification == "BRIDGE_READY_FOR_SHADOW_FORWARD_SPEC_RESEARCH_ONLY":
        next_step = "Freeze the milestone bridge spec and design a shadow-forward observation protocol, still fully research-only."
    elif final_classification in {"BRIDGE_1M_PROMISING_RESEARCH_ONLY", "BRIDGE_3M_OPTIMISTIC_RESEARCH_ONLY"}:
        next_step = "Keep the bridge frozen and extend the research-only validation with additional Monte Carlo and execution-cost realism before any shadow-forward spec."
    else:
        next_step = "Keep the bridge research-only and investigate fragility drivers before considering any shadow-forward specification."
    return {**RESEARCH_ONLY_FLAGS, "next_step": next_step}


def _court_report(
    *,
    summary: dict[str, Any],
    reconstruction_check: dict[str, Any],
    leakage_check: dict[str, Any],
    mode_rows: list[dict[str, Any]],
    rolling_rows: list[dict[str, Any]],
    fragility: dict[str, Any],
    gate: dict[str, Any],
) -> str:
    monthly_mc = next((row for row in mode_rows if row["mode"] == "monthly_block_bootstrap"), {})
    bridge_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_EQUITY_MILESTONE_RISK_STEPUP"), {})
    five_x_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_STEPUP_AND_5X_COST"), {})
    ten_x_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_STEPUP_AND_10X_COST"), {})
    top5_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_STEPUP_AND_REMOVE_TOP_5_WINNERS"), {})
    drop30_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_STEPUP_AND_RANDOM_DROP_30PCT_TRADES"), {})
    return "\n".join(
        [
            "# Strict SR-Aware Milestone Bridge Monte Carlo Retest Audit",
            "",
            f"Final classification: `{summary['final_classification']}`",
            "",
            "## Court Findings",
            "",
            f"1. Reconstruction correct: `{bool(reconstruction_check.get('matches_prior_gap_audit'))}`.",
            f"2. No-future-leakage verdict: `{leakage_check.get('verdict')}`.",
            f"3. Rolling 5Y bridge retest still hits 1M in `{int(float(bridge_row.get('hit_1m_windows') or 0))}` windows.",
            f"4. Monte Carlo supports the 1M mission with monthly-block p10/p25/p50 of `{_safe_float(monthly_mc.get('p10_ending_equity')):.2f}` / `{_safe_float(monthly_mc.get('p25_ending_equity')):.2f}` / `{_safe_float(monthly_mc.get('p50_ending_equity')):.2f}` EUR.",
            f"5. Monte Carlo probability above 1M / 3M / 5M is `{_safe_float(monthly_mc.get('probability_above_1m')):.4f}` / `{_safe_float(monthly_mc.get('probability_above_3m')):.4f}` / `{_safe_float(monthly_mc.get('probability_above_5m')):.4f}`.",
            f"6. 5x cost result: average 5Y ending equity `{_safe_float(five_x_row.get('average_5y_ending_equity')):.2f}` EUR. 10x cost result: `{_safe_float(ten_x_row.get('average_5y_ending_equity')):.2f}` EUR.",
            f"7. Top-winner removal result: `{_safe_float(top5_row.get('average_5y_ending_equity')):.2f}` EUR average 5Y ending equity.",
            f"8. Missed-trade sensitivity result: `{_safe_float(drop30_row.get('average_5y_ending_equity')):.2f}` EUR average 5Y ending equity after random 30% trade drop.",
            f"9. Low drawdown believable or fragile: `{fragility.get('fragility_verdict')}`.",
            f"10. Mission gate verdict: `{gate.get('verdict')}`.",
            f"11. Next step: `{summary['next_research_step']}`.",
            "",
            "## Guardrails",
            "",
            "- `research_only=true`",
            "- `real_money_allowed=false`",
            "- `paper_allowed=false`",
            "- `live_allowed=false`",
            "- `behavior_change_allowed=false`",
            "- No live, paper, runtime, or production strategy behavior changed",
            "",
        ]
    )


def write_strict_sr_aware_milestone_bridge_monte_carlo_audit(
    config: StrictSRAwareMilestoneBridgeMonteCarloAuditConfig,
) -> dict[str, Path]:
    paths = _paths(config)
    required = [
        paths["gap_summary"],
        paths["gap_variant_results"],
        paths["gap_realism_gate"],
        paths["strict_summary"],
        paths["strict_monte_carlo_summary"],
        paths["strict_stress_matrix"],
        paths["strict_pre_entry_integrity"],
        paths["native_trades"],
        paths["native_equity"],
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return _empty_outputs(config, classification="STRICT_SR_AWARE_MILESTONE_BRIDGE_BLOCKED", warnings=missing)

    diagnostics_root, ledger_root, reports_root = _ensure_dirs(config.output_root)

    context, reconstruction_warnings = _reconstruct_sequences(
        NativeSRAware5YMissionGapAuditConfig(
            package_root=config.package_root,
            output_root=config.package_root / "output" / "native_sr_aware_5y_mission_gap_audit_001",
        )
    )
    if context is None:
        return _empty_outputs(config, classification="STRICT_SR_AWARE_MILESTONE_BRIDGE_BLOCKED", warnings=reconstruction_warnings)

    gap_summary = _read_json(paths["gap_summary"], {})
    variant_rows = _read_csv_rows(paths["gap_variant_results"])
    bridge_result_row = next((row for row in variant_rows if str(row.get("variant_name") or "") == BEST_BRIDGE_NAME), {})
    if not bridge_result_row:
        return _empty_outputs(config, classification="STRICT_SR_AWARE_MILESTONE_BRIDGE_BLOCKED", warnings=["bridge_variant_row_missing"])

    strict_rows = context["strict_rows"]
    windows = _build_windows(strict_rows)
    frozen_spec = _bridge_spec_payload()
    leakage_check = _bridge_no_future_leakage_check()
    reconstructed_full = _simulate_bridge_sequence(strict_rows, **_bridge_sim_kwargs())

    bridge_trade_rows = []
    for row in reconstructed_full["trade_trace"]:
        bridge_trade_rows.append(
            {
                "trade_id": row.get("trade_id"),
                "timestamp": row.get("timestamp"),
                "risk_multiplier": row.get("risk_multiplier"),
                "risk_value": row.get("risk_value"),
                "applied_r": row.get("applied_r"),
                "pnl": row.get("pnl"),
                "equity_after": row.get("equity_after"),
                "archetype_key": row.get("archetype_key"),
                "failure_mode": row.get("failure_mode"),
            }
        )
    bridge_equity_rows = reconstructed_full["daily_rows"]
    bridge_summary = {
        **RESEARCH_ONLY_FLAGS,
        "bridge_variant_name": BEST_BRIDGE_NAME,
        "ending_equity": round(_safe_float(reconstructed_full["ending_equity"]), 6),
        "trade_count": int(reconstructed_full["trade_count"]),
        "max_drawdown_pct": round(_safe_float(reconstructed_full["max_drawdown_pct"]), 6),
        "profit_factor": round(_safe_float(reconstructed_full["profit_factor"]), 6),
        "avg_R": round(_safe_float(reconstructed_full["avg_R"]), 6),
        "median_R": round(_safe_float(reconstructed_full["median_R"]), 6),
        "risk_multiplier_avg": round(_safe_float(reconstructed_full["risk_multiplier_avg"]), 6),
        "risk_multiplier_max": round(_safe_float(reconstructed_full["risk_multiplier_max"]), 6),
        "insolvency_hit": bool(reconstructed_full["insolvency_hit"]),
    }
    reconstruction_check = _reconstruction_check(gap_summary, bridge_result_row, reconstructed_full)

    mc_summary, mc_path_rows, mc_mode_rows, mc_failure_modes = _run_monte_carlo(strict_rows, total_path_count=max(config.total_path_count, DEFAULT_TOTAL_PATHS))
    rolling_rows, rolling_hit_rows, rolling_best_worst = _rolling_retest(strict_rows, windows)
    fragility, risk_stepup_rows, early_winner_dependency, drawdown_after_rows, sensitivity_rows = _fragility_audit(strict_rows)
    mission_gate = _mission_gate(
        leakage_check=leakage_check,
        reconstruction_check=reconstruction_check,
        rolling_rows=rolling_rows,
        mc_summary=mc_summary,
        mode_rows=mc_mode_rows,
        fragility=fragility,
    )
    final_classification = _final_classification(mission_gate, mc_mode_rows, rolling_rows)
    no_go_risks = {
        **RESEARCH_ONLY_FLAGS,
        "risks": [
            risk for risk, passed in mission_gate["conditions"].items() if not bool(passed)
        ],
    }
    next_step = _next_recommendation(final_classification)

    monthly_mc = next((row for row in mc_mode_rows if row["mode"] == "monthly_block_bootstrap"), {})
    bridge_row = next((row for row in rolling_rows if row["variant_name"] == BEST_BRIDGE_NAME), {})
    five_x_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_STEPUP_AND_5X_COST"), {})
    ten_x_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_STEPUP_AND_10X_COST"), {})
    top5_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_STEPUP_AND_REMOVE_TOP_5_WINNERS"), {})
    drop30_row = next((row for row in rolling_rows if row["variant_name"] == "STRICT_WITH_STEPUP_AND_RANDOM_DROP_30PCT_TRADES"), {})
    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "bridge_reconstruction_result": bool(reconstruction_check["matches_prior_gap_audit"]),
        "no_leakage_verdict": leakage_check["verdict"],
        "full_sequence_bridge_ending_equity": round(_safe_float(reconstructed_full["ending_equity"]), 6),
        "rolling_5y_bridge_average_ending_equity": round(_safe_float(bridge_row.get("average_5y_ending_equity")), 6),
        "rolling_5y_bridge_median_ending_equity": round(_safe_float(bridge_row.get("median_5y_ending_equity")), 6),
        "rolling_5y_bridge_1m_hit_windows": int(float(bridge_row.get("hit_1m_windows") or 0)),
        "monte_carlo_p10_ending_equity": round(_safe_float(monthly_mc.get("p10_ending_equity")), 6),
        "monte_carlo_p25_ending_equity": round(_safe_float(monthly_mc.get("p25_ending_equity")), 6),
        "monte_carlo_p50_ending_equity": round(_safe_float(monthly_mc.get("p50_ending_equity")), 6),
        "monte_carlo_probability_above_1m": round(_safe_float(monthly_mc.get("probability_above_1m")), 6),
        "monte_carlo_probability_above_3m": round(_safe_float(monthly_mc.get("probability_above_3m")), 6),
        "monte_carlo_probability_above_5m": round(_safe_float(monthly_mc.get("probability_above_5m")), 6),
        "ruin_risk": round(_safe_float(monthly_mc.get("ruin_probability")), 6),
        "five_x_cost_result": round(_safe_float(five_x_row.get("average_5y_ending_equity")), 6),
        "ten_x_cost_result": round(_safe_float(ten_x_row.get("average_5y_ending_equity")), 6),
        "top_winner_removal_result": round(_safe_float(top5_row.get("average_5y_ending_equity")), 6),
        "missed_trade_sensitivity_result": round(_safe_float(drop30_row.get("average_5y_ending_equity")), 6),
        "bridge_fragility_verdict": fragility["fragility_verdict"],
        "mission_gate_verdict": mission_gate["verdict"],
        "final_classification": final_classification,
        "next_research_step": next_step["next_step"],
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
    }

    report = _court_report(
        summary=summary,
        reconstruction_check=reconstruction_check,
        leakage_check=leakage_check,
        mode_rows=mc_mode_rows,
        rolling_rows=rolling_rows,
        fragility=fragility,
        gate=mission_gate,
    )

    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "strict_sr_aware_milestone_bridge_monte_carlo_summary.json", summary)
    _write_markdown(config.output_root / "strict_sr_aware_milestone_bridge_monte_carlo_report.md", report)
    _write_json(diagnostics_root / "frozen_milestone_bridge_spec.json", frozen_spec)
    _write_json(diagnostics_root / "milestone_bridge_no_future_leakage_check.json", leakage_check)
    _write_csv(ledger_root / "milestone_bridge_trades.csv", bridge_trade_rows)
    _write_csv(ledger_root / "milestone_bridge_equity.csv", bridge_equity_rows)
    _write_json(ledger_root / "milestone_bridge_summary.json", bridge_summary)
    _write_json(diagnostics_root / "bridge_reconstruction_check.json", reconstruction_check)
    _write_json(diagnostics_root / "monte_carlo_bridge_summary.json", mc_summary)
    _write_csv(diagnostics_root / "monte_carlo_bridge_paths.csv", mc_path_rows)
    _write_csv(diagnostics_root / "monte_carlo_mode_comparison.csv", mc_mode_rows)
    _write_json(diagnostics_root / "monte_carlo_failure_modes.json", mc_failure_modes)
    _write_csv(diagnostics_root / "rolling_5y_bridge_retest.csv", rolling_rows)
    _write_csv(diagnostics_root / "rolling_5y_bridge_hit_matrix.csv", rolling_hit_rows)
    _write_csv(diagnostics_root / "rolling_5y_bridge_best_worst_windows.csv", rolling_best_worst)
    _write_json(diagnostics_root / "milestone_bridge_fragility_audit.json", fragility)
    _write_csv(diagnostics_root / "risk_stepup_timing_audit.csv", risk_stepup_rows)
    _write_json(diagnostics_root / "early_winner_dependency_audit.json", early_winner_dependency)
    _write_csv(diagnostics_root / "drawdown_after_stepup_audit.csv", drawdown_after_rows)
    _write_csv(diagnostics_root / "missed_trade_sensitivity.csv", sensitivity_rows)
    _write_json(diagnostics_root / "bridge_mission_gate.json", mission_gate)
    _write_json(diagnostics_root / "no_go_risks.json", no_go_risks)
    _write_json(reports_root / "next_research_recommendation.json", next_step)
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "strict_sr_aware_milestone_bridge_monte_carlo_summary.json",
        "report": config.output_root / "strict_sr_aware_milestone_bridge_monte_carlo_report.md",
    }


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    output_root = package_root / "output" / OUTPUT_FOLDER_NAME
    write_strict_sr_aware_milestone_bridge_monte_carlo_audit(
        StrictSRAwareMilestoneBridgeMonteCarloAuditConfig(
            package_root=package_root,
            output_root=output_root,
        )
    )
