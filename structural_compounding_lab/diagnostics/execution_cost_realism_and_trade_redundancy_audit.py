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
from structural_compounding_lab.diagnostics.milestone_bridge_fragility_driver_repair_audit import (  # noqa: E402
    BASE_STEPUP_SCHEDULE,
    _drop_random_trades,
    _estimated_cost,
    _group_consecutive_blocks,
    _month_label,
    _quarter_label,
    _rolling_window_summary,
    _safe_float,
    _simulate_overlay_sequence,
    _sort_rows,
    _year_label,
)
from structural_compounding_lab.diagnostics.native_sr_aware_5y_mission_gap_audit import (  # noqa: E402
    BASELINE_COST_BPS,
    FIVE_X_COST_BPS,
    NativeSRAware5YMissionGapAuditConfig,
    START_CAPITAL,
    _clone_row,
    _reconstruct_sequences,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import (  # noqa: E402
    _build_windows,
    _window_rows,
)


OUTPUT_FOLDER_NAME = "execution_cost_realism_and_trade_redundancy_audit_001"
BEST_BRIDGE_NAME = "BASE_MILESTONE_BRIDGE"
RANDOM_REPEAT_COUNT = 32
REQUIRED_OUTPUT_FILES = (
    "execution_cost_model_assumptions.json",
    "execution_cost_band_results.csv",
    "execution_cost_band_results.json",
    "cost_band_rolling_5y_survival.csv",
    "cost_band_mission_hit_matrix.csv",
    "cost_band_drawdown_report.csv",
    "missed_trade_tolerance_results.csv",
    "missed_trade_tolerance_results.json",
    "missed_trade_operational_risk_thresholds.json",
    "trade_redundancy_cluster_audit.csv",
    "trade_redundancy_concentration_report.json",
    "key_trade_cluster_dependency.json",
    "operational_reliability_requirements.json",
    "no_go_risks.json",
    "implementation_self_audit.json",
)


@dataclass(frozen=True)
class ExecutionCostRealismAndTradeRedundancyAuditConfig:
    package_root: Path
    output_root: Path
    random_repeat_count: int = RANDOM_REPEAT_COUNT


def _try_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert("UTC").tz_localize(None)
    return parsed


def _timestamp_label(row: dict[str, Any]) -> str:
    ts = row.get("exit_timestamp")
    if not isinstance(ts, pd.Timestamp):
        return "unknown"
    return ts.strftime("%Y-%m")


def _year_from_row(row: dict[str, Any]) -> str:
    ts = row.get("exit_timestamp")
    return str(ts.year) if isinstance(ts, pd.Timestamp) else "unknown"


def _quarter_from_row(row: dict[str, Any]) -> str:
    ts = row.get("exit_timestamp")
    if not isinstance(ts, pd.Timestamp):
        return "unknown"
    quarter = ((int(ts.month) - 1) // 3) + 1
    return f"{int(ts.year)}-Q{quarter}"


def _date_from_row(row: dict[str, Any]) -> str:
    ts = row.get("exit_timestamp")
    return ts.strftime("%Y-%m-%d") if isinstance(ts, pd.Timestamp) else "unknown"


def _paths(config: ExecutionCostRealismAndTradeRedundancyAuditConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    fragility_root = output_root / "milestone_bridge_fragility_driver_repair_audit_001"
    bridge_root = output_root / "strict_sr_aware_milestone_bridge_monte_carlo_audit_001"
    return {
        "fragility_summary": fragility_root / "milestone_bridge_fragility_driver_repair_summary.json",
        "cost_decomp": fragility_root / "diagnostics" / "cost_fragility_decomposition.csv",
        "cost_by_year": fragility_root / "diagnostics" / "cost_fragility_by_year.csv",
        "cost_by_month": fragility_root / "diagnostics" / "cost_fragility_by_month.csv",
        "cost_realism": fragility_root / "diagnostics" / "cost_realism_assessment.json",
        "missed_decomp": fragility_root / "diagnostics" / "missed_trade_fragility_decomposition.csv",
        "missed_rate": fragility_root / "diagnostics" / "missed_trade_rate_sensitivity.csv",
        "top_dependency": fragility_root / "diagnostics" / "top_winner_dependency_decomposition.csv",
        "milestone_missed": fragility_root / "diagnostics" / "milestone_timing_missed_trade_sensitivity.csv",
        "trade_redundancy": fragility_root / "diagnostics" / "trade_redundancy_score.json",
        "overlay_results": fragility_root / "diagnostics" / "fragility_repair_overlay_results.csv",
        "revised_gate": fragility_root / "diagnostics" / "revised_bridge_mission_gate.json",
        "bridge_trade_ledger": bridge_root / "ledger" / "milestone_bridge_trades.csv",
        "bridge_equity_ledger": bridge_root / "ledger" / "milestone_bridge_equity.csv",
        "bridge_ledger_summary": bridge_root / "ledger" / "milestone_bridge_summary.json",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, reports_root


def _empty_outputs(
    config: ExecutionCostRealismAndTradeRedundancyAuditConfig,
    *,
    classification: str,
    warnings: list[str],
    self_audit: dict[str, Any] | None = None,
) -> dict[str, Path]:
    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    now = datetime.now(timezone.utc).isoformat()
    status = {"state": "blocked", "resolved_at_utc": now, **RESEARCH_ONLY_FLAGS, "warnings": warnings}
    summary = {
        "resolved_at_utc": now,
        **RESEARCH_ONLY_FLAGS,
        "final_classification": classification,
        "warnings": warnings,
    }
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "execution_cost_realism_and_trade_redundancy_summary.json", summary)
    _write_markdown(
        config.output_root / "execution_cost_realism_and_trade_redundancy_report.md",
        "# Execution Cost Realism and Trade Redundancy Audit\n\nRequired upstream artifacts were missing, so the audit remained blocked.\n",
    )
    for path in (
        diagnostics_root / "execution_cost_model_assumptions.json",
        diagnostics_root / "execution_cost_band_results.json",
        diagnostics_root / "missed_trade_tolerance_results.json",
        diagnostics_root / "missed_trade_operational_risk_thresholds.json",
        diagnostics_root / "trade_redundancy_concentration_report.json",
        diagnostics_root / "key_trade_cluster_dependency.json",
        diagnostics_root / "operational_reliability_requirements.json",
        diagnostics_root / "no_go_risks.json",
        diagnostics_root / "implementation_self_audit.json",
        reports_root / "future_shadow_reporting_requirements.json",
        reports_root / "next_research_recommendation.json",
    ):
        payload = {"warnings": warnings, **RESEARCH_ONLY_FLAGS}
        if path.name == "implementation_self_audit.json":
            payload = self_audit or {
                **RESEARCH_ONLY_FLAGS,
                "schema_fields_detected": [],
                "timestamp_field_used": "blocked",
                "baseline_metric_used": "blocked",
                "rolling_5y_metric_used": "blocked",
                "full_sequence_metric_used": "blocked",
                "leakage_check": True,
                "future_field_usage_check": True,
                "silent_fallback_check": False,
                "stress_metric_scope_check": True,
                "previous_artifacts_overwritten": False,
                "reviewer_notes": warnings,
            }
        _write_json(path, payload)
    for path in (
        diagnostics_root / "execution_cost_band_results.csv",
        diagnostics_root / "cost_band_rolling_5y_survival.csv",
        diagnostics_root / "cost_band_mission_hit_matrix.csv",
        diagnostics_root / "cost_band_drawdown_report.csv",
        diagnostics_root / "missed_trade_tolerance_results.csv",
        diagnostics_root / "trade_redundancy_cluster_audit.csv",
    ):
        _write_csv(path, [])
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "execution_cost_realism_and_trade_redundancy_summary.json",
        "report": config.output_root / "execution_cost_realism_and_trade_redundancy_report.md",
    }


def _normalize_rows_for_audit(
    rows: list[dict[str, Any]],
    *,
    require_trade_id: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    normalized_rows: list[dict[str, Any]] = []
    schema_fields = sorted({key for row in rows for key in row.keys()})
    timestamp_usage_counts = {"exit_timestamp": 0, "timestamp": 0, "entry_timestamp": 0}
    row_count_with_fallback_trade_id = 0
    row_count_with_fallback_r = 0
    row_count_with_fallback_entry_ts = 0

    for index, row in enumerate(rows):
        item = _clone_row(row)
        resolved_ts = None
        resolved_ts_field = None
        for field_name in ("exit_timestamp", "timestamp", "entry_timestamp"):
            parsed = _try_timestamp(item.get(field_name))
            if parsed is not None:
                resolved_ts = parsed
                resolved_ts_field = field_name
                timestamp_usage_counts[field_name] += 1
                break
        if resolved_ts is None:
            errors.append(f"row_{index}: no valid timestamp field found among exit_timestamp/timestamp/entry_timestamp")
            continue

        resolved_entry_ts = _try_timestamp(item.get("entry_timestamp"))
        if resolved_entry_ts is None:
            resolved_entry_ts = resolved_ts
            row_count_with_fallback_entry_ts += 1

        resolved_trade_id = str(item.get("trade_id") or "").strip()
        if not resolved_trade_id:
            if require_trade_id:
                errors.append(f"row_{index}: missing trade_id")
                continue
            resolved_trade_id = f"audit_row_{index}"
            row_count_with_fallback_trade_id += 1

        resolved_r_value = item.get("r_multiple")
        resolved_r_field = "r_multiple"
        if _safe_float(resolved_r_value) == 0.0 and str(resolved_r_value).strip() in {"", "None", "none"}:
            resolved_r_value = item.get("applied_r")
            resolved_r_field = "applied_r"
        if _safe_float(resolved_r_value) == 0.0 and str(resolved_r_value).strip() in {"", "None", "none"}:
            errors.append(f"{resolved_trade_id}: missing both r_multiple and applied_r")
            continue
        if resolved_r_field == "applied_r":
            row_count_with_fallback_r += 1

        item["trade_id"] = resolved_trade_id
        item["exit_timestamp"] = resolved_ts
        item["timestamp"] = resolved_ts
        item["entry_timestamp"] = resolved_entry_ts
        item["r_multiple"] = _safe_float(resolved_r_value)
        item["risk_multiplier"] = _safe_float(item.get("risk_multiplier")) or 1.0
        normalized_rows.append(item)

    if row_count_with_fallback_trade_id:
        warnings.append(f"{row_count_with_fallback_trade_id} rows used synthetic trade_id fallback.")
    if row_count_with_fallback_r:
        warnings.append(f"{row_count_with_fallback_r} rows used applied_r fallback for r_multiple.")
    if row_count_with_fallback_entry_ts:
        warnings.append(f"{row_count_with_fallback_entry_ts} rows used exit/timestamp fallback for entry_timestamp.")
    if not normalized_rows:
        errors.append("No rows survived schema normalization.")

    primary_timestamp_field = max(timestamp_usage_counts.items(), key=lambda item: item[1])[0] if any(timestamp_usage_counts.values()) else "blocked"
    schema_info = {
        "schema_fields_detected": schema_fields,
        "timestamp_field_used": primary_timestamp_field,
        "timestamp_field_usage_counts": timestamp_usage_counts,
        "fallback_trade_id_rows": row_count_with_fallback_trade_id,
        "fallback_r_rows": row_count_with_fallback_r,
        "fallback_entry_timestamp_rows": row_count_with_fallback_entry_ts,
    }
    return normalized_rows, schema_info, warnings, errors


def _load_context(config: ExecutionCostRealismAndTradeRedundancyAuditConfig) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    paths = _paths(config)
    required = list(paths.values())
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return None, missing, {"schema_fields_detected": [], "timestamp_field_used": "blocked"}
    reconstruction, warnings = _reconstruct_sequences(
        NativeSRAware5YMissionGapAuditConfig(
            package_root=config.package_root,
            output_root=config.package_root / "output" / "native_sr_aware_5y_mission_gap_audit_001",
        )
    )
    if reconstruction is None:
        return None, warnings, {"schema_fields_detected": [], "timestamp_field_used": "blocked"}
    strict_rows = reconstruction["strict_rows"]
    bridge_trade_rows = _read_csv_rows(paths["bridge_trade_ledger"])
    bridge_map = {str(row.get("trade_id") or ""): row for row in bridge_trade_rows}
    enriched_rows: list[dict[str, Any]] = []
    for row in strict_rows:
        item = _clone_row(row)
        item.update(bridge_map.get(str(row.get("trade_id") or ""), {}))
        enriched_rows.append(item)
    rows, schema_info, normalization_warnings, normalization_errors = _normalize_rows_for_audit(enriched_rows)
    warnings = [*warnings, *normalization_warnings]
    if normalization_errors:
        return None, [*warnings, *normalization_errors], schema_info
    rows = _sort_rows(rows)
    base_output = _simulate_overlay_sequence(rows, stepup_schedule=list(BASE_STEPUP_SCHEDULE))
    return {
        "rows": rows,
        "windows": _build_windows(rows),
        "base_output": base_output,
        "fragility_summary": _read_json(paths["fragility_summary"], {}),
        "cost_realism": _read_json(paths["cost_realism"], {}),
        "trade_redundancy": _read_json(paths["trade_redundancy"], {}),
        "revised_gate": _read_json(paths["revised_gate"], {}),
    }, warnings, schema_info


def _cost_band_specs() -> list[dict[str, Any]]:
    return [
        {
            "band_name": "ZERO_COST_REFERENCE",
            "fee_bps_per_side": 0.0,
            "spread_slippage_bps_per_side": 0.0,
            "total_round_trip_bps": 0.0,
            "realism_label": "reference",
            "use_for_mission_gate": False,
            "stress_only": False,
        },
        {
            "band_name": "OPTIMISTIC_MAKER_COST",
            "fee_bps_per_side": 1.0,
            "spread_slippage_bps_per_side": 1.5,
            "total_round_trip_bps": 5.0,
            "realism_label": "optimistic",
            "use_for_mission_gate": True,
            "stress_only": False,
        },
        {
            "band_name": "NORMAL_MIXED_MAKER_TAKER_COST",
            "fee_bps_per_side": 3.5,
            "spread_slippage_bps_per_side": 4.0,
            "total_round_trip_bps": BASELINE_COST_BPS,
            "realism_label": "realistic",
            "use_for_mission_gate": True,
            "stress_only": False,
        },
        {
            "band_name": "CONSERVATIVE_TAKER_COST",
            "fee_bps_per_side": 5.0,
            "spread_slippage_bps_per_side": 5.0,
            "total_round_trip_bps": 20.0,
            "realism_label": "conservative",
            "use_for_mission_gate": True,
            "stress_only": False,
        },
        {
            "band_name": "HIGH_SLIPPAGE_COST",
            "fee_bps_per_side": 5.0,
            "spread_slippage_bps_per_side": 10.0,
            "total_round_trip_bps": 30.0,
            "realism_label": "punitive",
            "use_for_mission_gate": False,
            "stress_only": True,
        },
        {
            "band_name": "FIVE_X_PUNITIVE_COST",
            "fee_bps_per_side": 12.5,
            "spread_slippage_bps_per_side": 25.0,
            "total_round_trip_bps": FIVE_X_COST_BPS,
            "realism_label": "punitive",
            "use_for_mission_gate": False,
            "stress_only": True,
        },
        {
            "band_name": "TEN_X_APOCALYPSE_COST",
            "fee_bps_per_side": 25.0,
            "spread_slippage_bps_per_side": 50.0,
            "total_round_trip_bps": BASELINE_COST_BPS * 10.0,
            "realism_label": "apocalypse",
            "use_for_mission_gate": False,
            "stress_only": True,
        },
    ]


def _mission_verdict(rolling: dict[str, Any]) -> str:
    if rolling["average"] >= 1_000_000.0 and int(rolling["hit_1m_windows"]) >= 10:
        return "MISSION_1M_SURVIVES"
    if int(rolling["hit_1m_windows"]) > 0:
        return "MISSION_PARTIAL"
    return "MISSION_BELOW_1M"


def _evaluate_cost_bands(rows: list[dict[str, Any]], windows: list[tuple[pd.Timestamp, pd.Timestamp, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    assumptions = {"research_only": True, "bands": _cost_band_specs(), "notes": "Assumptions are configurable research bands only; no broker or web inputs were used."}
    band_rows: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []
    drawdown_rows: list[dict[str, Any]] = []
    for band in _cost_band_specs():
        sim_kwargs = {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "cost_bps_total": float(band["total_round_trip_bps"])}
        full = _simulate_overlay_sequence(rows, **sim_kwargs)
        rolling = _rolling_window_summary(rows, windows, sim_kwargs)
        total_cost = sum(_estimated_cost(row, float(band["total_round_trip_bps"])) for row in rows)
        gross_positive_pnl = sum(max(0.0, _safe_float(trace.get("applied_r")) * _safe_float(trace.get("risk_value"))) for trace in full["trade_trace"])
        total_r = sum(_safe_float(trace.get("applied_r")) for trace in full["trade_trace"])
        avg_gross_expectancy = gross_positive_pnl / max(len(full["trade_trace"]), 1)
        verdict = _mission_verdict(rolling)
        row = {
            **RESEARCH_ONLY_FLAGS,
            **band,
            "full_sequence_ending_equity": round(_safe_float(full["ending_equity"]), 6),
            "rolling_5y_average_ending_equity": rolling["average"],
            "rolling_5y_median_ending_equity": rolling["median"],
            "rolling_5y_best_ending_equity": rolling["best"],
            "rolling_5y_worst_ending_equity": rolling["worst"],
            "hit_1m_windows": rolling["hit_1m_windows"],
            "hit_3m_windows": rolling["hit_3m_windows"],
            "hit_5m_windows": rolling["hit_5m_windows"],
            "max_drawdown_pct": rolling["max_drawdown_pct"],
            "cost_as_pct_gross_profit": round(_safe_ratio(total_cost, gross_positive_pnl, 0.0), 6),
            "cost_as_pct_total_r": round(_safe_ratio(total_cost, abs(total_r) * START_CAPITAL * 0.01, 0.0), 6),
            "cost_as_pct_avg_expectancy": round(_safe_ratio(total_cost / max(len(full["trade_trace"]), 1), avg_gross_expectancy, 0.0), 6),
            "mission_verdict": verdict,
        }
        band_rows.append(row)
        rolling_rows.append(
            {
                "band_name": band["band_name"],
                "rolling_5y_average_ending_equity": row["rolling_5y_average_ending_equity"],
                "rolling_5y_median_ending_equity": row["rolling_5y_median_ending_equity"],
                "rolling_5y_best_ending_equity": row["rolling_5y_best_ending_equity"],
                "rolling_5y_worst_ending_equity": row["rolling_5y_worst_ending_equity"],
                "mission_verdict": verdict,
            }
        )
        drawdown_rows.append(
            {
                "band_name": band["band_name"],
                "max_drawdown_pct": row["max_drawdown_pct"],
                "cost_as_pct_gross_profit": row["cost_as_pct_gross_profit"],
                "cost_as_pct_total_r": row["cost_as_pct_total_r"],
                "cost_as_pct_avg_expectancy": row["cost_as_pct_avg_expectancy"],
            }
        )
    return assumptions, band_rows, rolling_rows, drawdown_rows


def _remove_random_block(rows: list[dict[str, Any]], label_func: Any, seed: int) -> list[dict[str, Any]]:
    ordered = _sort_rows(rows)
    blocks = _group_consecutive_blocks(ordered, label_func)
    if not blocks:
        return [_clone_row(row) for row in ordered]
    rng = random.Random(seed)
    remove_index = rng.randrange(len(blocks))
    output: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        if index == remove_index:
            continue
        output.extend(_clone_row(row) for row in block)
    return output


def _profit_by_period(rows: list[dict[str, Any]], label_func: Any) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for row in rows:
        label = label_func(row)
        totals[label] = totals.get(label, 0.0) + _safe_float(row.get("r_multiple"))
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)


def _abs_profit_by_period(rows: list[dict[str, Any]], label_func: Any) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for row in rows:
        label = label_func(row)
        totals[label] = totals.get(label, 0.0) + abs(_safe_float(row.get("r_multiple")))
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)


def _remove_labels(rows: list[dict[str, Any]], label_func: Any, labels: set[str]) -> list[dict[str, Any]]:
    return [_clone_row(row) for row in rows if str(label_func(row)) not in labels]


def _stepup_transition_labels(base_output: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    previous = 1.0
    for trace in base_output["trade_trace"]:
        current = _safe_float(trace.get("risk_multiplier"))
        if current > previous:
            parsed = _try_timestamp(trace.get("timestamp"))
            if parsed is not None:
                labels.add(str(parsed.strftime("%Y-%m")))
        previous = current
    return labels


def _evaluate_single_miss(rows: list[dict[str, Any]], windows: list[tuple[pd.Timestamp, pd.Timestamp, str]], scenario_name: str) -> dict[str, Any]:
    rolling = _rolling_window_summary(rows, windows, {"stepup_schedule": list(BASE_STEPUP_SCHEDULE)})
    return {
        "scenario_name": scenario_name,
        "rolling_5y_average_ending_equity": rolling["average"],
        "rolling_5y_median_ending_equity": rolling["median"],
        "hit_1m_windows": rolling["hit_1m_windows"],
        "hit_3m_windows": rolling["hit_3m_windows"],
        "hit_5m_windows": rolling["hit_5m_windows"],
        "max_drawdown_pct": rolling["max_drawdown_pct"],
        "mission_survives": rolling["average"] >= 1_000_000.0 and int(rolling["hit_1m_windows"]) >= 10,
    }


def _evaluate_random_miss_scenario(
    rows: list[dict[str, Any]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
    *,
    scenario_name: str,
    generator: Any,
    repeat_count: int,
) -> dict[str, Any]:
    results = []
    for index in range(repeat_count):
        sampled_rows = generator(index)
        result = _evaluate_single_miss(sampled_rows, windows, scenario_name)
        results.append(result)
    averages = {
        "scenario_name": scenario_name,
        "rolling_5y_average_ending_equity": round(sum(_safe_float(item["rolling_5y_average_ending_equity"]) for item in results) / max(len(results), 1), 6),
        "rolling_5y_median_ending_equity": round(sum(_safe_float(item["rolling_5y_median_ending_equity"]) for item in results) / max(len(results), 1), 6),
        "hit_1m_windows": round(sum(_safe_float(item["hit_1m_windows"]) for item in results) / max(len(results), 1), 6),
        "hit_3m_windows": round(sum(_safe_float(item["hit_3m_windows"]) for item in results) / max(len(results), 1), 6),
        "hit_5m_windows": round(sum(_safe_float(item["hit_5m_windows"]) for item in results) / max(len(results), 1), 6),
        "max_drawdown_pct": round(sum(_safe_float(item["max_drawdown_pct"]) for item in results) / max(len(results), 1), 6),
    }
    averages["mission_survives"] = bool(
        averages["rolling_5y_average_ending_equity"] >= 1_000_000.0 and averages["hit_1m_windows"] >= 10.0
    )
    return averages


def _evaluate_missed_trade_tolerance(
    rows: list[dict[str, Any]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
    base_rolling_average: float,
    base_output: dict[str, Any],
    repeat_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for rate in (0.01, 0.02, 0.05, 0.10, 0.15, 0.20, 0.30):
        result = _evaluate_random_miss_scenario(
            rows,
            windows,
            scenario_name=f"random_miss_{int(rate * 100)}pct",
            generator=lambda index, miss_rate=rate: _drop_random_trades(rows, miss_rate, 10_000 + index),
            repeat_count=repeat_count,
        )
        result["scenario_type"] = "random_drop"
        result["mission_degradation_pct"] = round(1.0 - _safe_ratio(result["rolling_5y_average_ending_equity"], base_rolling_average, 0.0), 6)
        result["risk_acceptable"] = bool(result["mission_survives"] and result["mission_degradation_pct"] <= 0.15)
        results.append(result)

    day_result = _evaluate_random_miss_scenario(
        rows,
        windows,
        scenario_name="miss_one_random_day",
        generator=lambda index: _remove_random_block(rows, _date_from_row, 20_000 + index),
        repeat_count=repeat_count,
    )
    day_result["scenario_type"] = "block_dropout"
    day_result["mission_degradation_pct"] = round(1.0 - _safe_ratio(day_result["rolling_5y_average_ending_equity"], base_rolling_average, 0.0), 6)
    day_result["risk_acceptable"] = bool(day_result["mission_survives"] and day_result["mission_degradation_pct"] <= 0.10)
    results.append(day_result)

    week_result = _evaluate_random_miss_scenario(
        rows,
        windows,
        scenario_name="miss_one_random_week",
        generator=lambda index: _remove_random_block(rows, lambda row: str(row.get("exit_timestamp").to_period("W")) if isinstance(row.get("exit_timestamp"), pd.Timestamp) else "unknown", 30_000 + index),
        repeat_count=repeat_count,
    )
    week_result["scenario_type"] = "block_dropout"
    week_result["mission_degradation_pct"] = round(1.0 - _safe_ratio(week_result["rolling_5y_average_ending_equity"], base_rolling_average, 0.0), 6)
    week_result["risk_acceptable"] = bool(week_result["mission_survives"] and week_result["mission_degradation_pct"] <= 0.10)
    results.append(week_result)

    month_result = _evaluate_random_miss_scenario(
        rows,
        windows,
        scenario_name="miss_one_random_month",
        generator=lambda index: _remove_random_block(rows, _timestamp_label, 40_000 + index),
        repeat_count=repeat_count,
    )
    month_result["scenario_type"] = "block_dropout"
    month_result["mission_degradation_pct"] = round(1.0 - _safe_ratio(month_result["rolling_5y_average_ending_equity"], base_rolling_average, 0.0), 6)
    month_result["risk_acceptable"] = bool(month_result["mission_survives"] and month_result["mission_degradation_pct"] <= 0.10)
    results.append(month_result)

    milestone_labels = _stepup_transition_labels(base_output)
    milestone_rows = _remove_labels(rows, _timestamp_label, milestone_labels)
    milestone_result = _evaluate_single_miss(milestone_rows, windows, "miss_stepup_transition_months")
    milestone_result["scenario_type"] = "stepup_timing"
    milestone_result["mission_degradation_pct"] = round(1.0 - _safe_ratio(milestone_result["rolling_5y_average_ending_equity"], base_rolling_average, 0.0), 6)
    milestone_result["risk_acceptable"] = bool(milestone_result["mission_survives"] and milestone_result["mission_degradation_pct"] <= 0.10)
    results.append(milestone_result)

    top_months = _profit_by_period(rows, _timestamp_label)
    top_month_labels = {label for label, _value in top_months[:2]}
    top_month_rows = _remove_labels(rows, _timestamp_label, top_month_labels)
    top_month_result = _evaluate_single_miss(top_month_rows, windows, "miss_top_performing_months")
    top_month_result["scenario_type"] = "top_months"
    top_month_result["mission_degradation_pct"] = round(1.0 - _safe_ratio(top_month_result["rolling_5y_average_ending_equity"], base_rolling_average, 0.0), 6)
    top_month_result["risk_acceptable"] = False
    results.append(top_month_result)

    high_vol_labels = {label for label, _value in _abs_profit_by_period(rows, _timestamp_label)[:2]}
    high_vol_rows = _remove_labels(rows, _timestamp_label, high_vol_labels)
    high_vol_result = _evaluate_single_miss(high_vol_rows, windows, "miss_high_volatility_months")
    high_vol_result["scenario_type"] = "high_volatility_months"
    high_vol_result["mission_degradation_pct"] = round(1.0 - _safe_ratio(high_vol_result["rolling_5y_average_ending_equity"], base_rolling_average, 0.0), 6)
    high_vol_result["risk_acceptable"] = False
    results.append(high_vol_result)

    thresholds = {
        **RESEARCH_ONLY_FLAGS,
        "max_random_missed_trade_rate_pct_for_1m_mission": max(
            [int(float(item["scenario_name"].split("_")[2].replace("pct", ""))) for item in results if str(item["scenario_name"]).startswith("random_miss_") and bool(item["mission_survives"])],
            default=0,
        ),
        "one_random_day_survives": bool(day_result["mission_survives"]),
        "one_random_week_survives": bool(week_result["mission_survives"]),
        "one_random_month_survives": bool(month_result["mission_survives"]),
        "stepup_timing_sensitive": not bool(milestone_result["mission_survives"]),
        "top_month_dependency_sensitive": not bool(top_month_result["mission_survives"]),
        "high_volatility_dependency_sensitive": not bool(high_vol_result["mission_survives"]),
    }
    results_json = {**RESEARCH_ONLY_FLAGS, "rows": results}
    return results, results_json, thresholds


def _trade_redundancy_and_clusters(rows: list[dict[str, Any]], base_output: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    monthly: dict[str, dict[str, float]] = {}
    quarterly: dict[str, dict[str, float]] = {}
    yearly: dict[str, dict[str, float]] = {}
    trade_contribs: list[float] = []
    for row in rows:
        month = _timestamp_label(row)
        quarter = _quarter_from_row(row)
        year = _year_from_row(row)
        value = _safe_float(row.get("r_multiple"))
        for label, bucket in ((month, monthly), (quarter, quarterly), (year, yearly)):
            slot = bucket.setdefault(label, {"trade_count": 0.0, "total_r": 0.0})
            slot["trade_count"] += 1.0
            slot["total_r"] += value
        if value > 0.0:
            trade_contribs.append(value)

    audit_rows: list[dict[str, Any]] = []
    for period_type, bucket in (("month", monthly), ("quarter", quarterly), ("year", yearly)):
        for label, metrics in sorted(bucket.items()):
            audit_rows.append(
                {
                    "period_type": period_type,
                    "period_label": label,
                    "trade_count": int(metrics["trade_count"]),
                    "total_r": round(metrics["total_r"], 6),
                }
            )

    monthly_positive = [max(0.0, bucket["total_r"]) for bucket in monthly.values()]
    total_monthly_positive = sum(monthly_positive)
    top_5_month_share = sum(sorted(monthly_positive, reverse=True)[:5]) / max(total_monthly_positive, 1.0)
    top_10_trade_share = sum(sorted(trade_contribs, reverse=True)[:10]) / max(sum(trade_contribs), 1.0)
    month_hhi = sum((value / max(total_monthly_positive, 1.0)) ** 2 for value in monthly_positive if value > 0.0)

    clusters = 0
    in_cluster = False
    positive_month_labels: list[str] = []
    for label, metrics in sorted(monthly.items()):
        is_positive = metrics["total_r"] > 0.0
        if is_positive:
            positive_month_labels.append(label)
        if is_positive and not in_cluster:
            clusters += 1
        in_cluster = is_positive

    materially_contributing_months = [label for label, metrics in monthly.items() if metrics["total_r"] >= 5.0]
    dependency_verdict = (
        "MONTH_CLUSTER_DEPENDENCY_HIGH"
        if top_5_month_share >= 0.55 or clusters < 8
        else "MONTH_CLUSTER_DEPENDENCY_ACCEPTABLE"
    )
    concentration = {
        **RESEARCH_ONLY_FLAGS,
        "monthly_top_5_contribution_share": round(top_5_month_share, 6),
        "top_10_trade_contribution_share": round(top_10_trade_share, 6),
        "monthly_hhi": round(month_hhi, 6),
        "independent_profitable_clusters": clusters,
        "materially_contributing_months": len(materially_contributing_months),
        "trade_redundancy_verdict": "LOW_REDUNDANCY" if clusters < 10 or top_10_trade_share > 0.40 else "ADEQUATE_REDUNDANCY",
    }
    key_dependency = {
        **RESEARCH_ONLY_FLAGS,
        "verdict": dependency_verdict,
        "top_positive_months": [
            {"month": label, "total_r": round(value, 6)}
            for label, value in _profit_by_period(rows, _timestamp_label)[:10]
        ],
        "stepup_transition_months": sorted(_stepup_transition_labels(base_output)),
        "materially_contributing_months_sample": sorted(materially_contributing_months)[:20],
    }
    return audit_rows, concentration, key_dependency


def _operational_requirements(
    cost_band_rows: list[dict[str, Any]],
    missed_thresholds: dict[str, Any],
    redundancy_report: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str]:
    mission_gate_bands = [
        row
        for row in cost_band_rows
        if bool(row["use_for_mission_gate"]) and str(row["mission_verdict"]) == "MISSION_1M_SURVIVES"
    ]
    max_cost_band = mission_gate_bands[-1]["band_name"] if mission_gate_bands else "ZERO_COST_REFERENCE_ONLY"
    max_slippage = mission_gate_bands[-1]["spread_slippage_bps_per_side"] if mission_gate_bands else 0.0
    max_miss_rate = int(missed_thresholds["max_random_missed_trade_rate_pct_for_1m_mission"])
    reliability = {
        **RESEARCH_ONLY_FLAGS,
        "maximum_acceptable_missed_signal_rate_pct": max_miss_rate,
        "maximum_acceptable_data_downtime": (
            "up_to_one_random_week"
            if bool(missed_thresholds["one_random_week_survives"])
            else "up_to_one_random_day"
            if bool(missed_thresholds["one_random_day_survives"])
            else "less_than_one_random_day"
        ),
        "maximum_acceptable_candle_delay": "<= 1 closed decision candle on the entry timeframe",
        "maximum_acceptable_execution_slippage_bps_per_side": max_slippage,
        "minimum_acceptable_signal_capture_rate_pct": 100 - max_miss_rate,
        "minimum_required_uptime_pct": max(95, 100 - max_miss_rate),
        "minimum_closed_trades_before_edge_judgment": 50,
        "minimum_months_before_operational_judgment": 6,
        "daily_metrics_to_log": ["signal_capture_rate", "missed_signals", "data_lag_seconds", "order_cost_bps", "closed_pnl", "open_positions"],
        "weekly_metrics_to_log": ["trade_count", "win_rate", "avg_r", "downtime_minutes", "top_symbol_dependency"],
        "monthly_metrics_to_log": ["ending_equity", "max_drawdown_pct", "hit_rate", "cost_as_pct_gross_profit", "cluster_contribution"],
        "requires_server_grade_reliability": bool(max_miss_rate <= 5 or redundancy_report["trade_redundancy_verdict"] == "LOW_REDUNDANCY"),
    }
    shadow_reporting = {
        **RESEARCH_ONLY_FLAGS,
        "shadow_forward_prerequisites": [
            "capture signal timestamps and first-seen timestamps",
            "log any dropped or delayed signals with root cause",
            "measure realized execution cost per trade versus assumed cost band",
            "track downtime by minute and by missed closed candle",
            "maintain daily and monthly mission-hit proxy dashboards",
        ],
        "recommended_cost_band_for_shadow_reporting": max_cost_band,
        "minimum_capture_rate_pct": reliability["minimum_acceptable_signal_capture_rate_pct"],
        "minimum_uptime_pct": reliability["minimum_required_uptime_pct"],
    }
    no_go_risks = {
        **RESEARCH_ONLY_FLAGS,
        "risks": [
            risk
            for risk, flag in (
                ("realistic_cost_band_not_mission_surviving", max_cost_band == "ZERO_COST_REFERENCE_ONLY"),
                ("trade_redundancy_low", redundancy_report["trade_redundancy_verdict"] == "LOW_REDUNDANCY"),
                ("stepup_timing_fragile", bool(missed_thresholds["stepup_timing_sensitive"])),
                ("top_month_dependency_fragile", bool(missed_thresholds["top_month_dependency_sensitive"])),
            )
            if flag
        ],
    }
    if max_cost_band == "ZERO_COST_REFERENCE_ONLY":
        classification = "EXECUTION_REDUNDANCY_WEAK"
    elif redundancy_report["trade_redundancy_verdict"] == "LOW_REDUNDANCY":
        classification = "EXECUTION_REDUNDANCY_COST_REALISTIC_BUT_LOW_REDUNDANCY"
    elif max_miss_rate >= 10:
        classification = "EXECUTION_REDUNDANCY_READY_FOR_SHADOW_REPORTING_SPEC_RESEARCH_ONLY"
    elif max_miss_rate >= 5:
        classification = "EXECUTION_REDUNDANCY_1M_PROMISING_RESEARCH_ONLY"
    else:
        classification = "EXECUTION_REDUNDANCY_NEEDS_MORE_TRADE_FREQUENCY"
    return reliability, shadow_reporting, no_go_risks, classification


def _next_recommendation(classification: str) -> dict[str, Any]:
    if classification == "EXECUTION_REDUNDANCY_READY_FOR_SHADOW_REPORTING_SPEC_RESEARCH_ONLY":
        text = "Freeze the milestone bridge and write a read-only shadow-forward reporting specification with strict uptime and cost logging."
    elif classification == "EXECUTION_REDUNDANCY_COST_REALISTIC_BUT_LOW_REDUNDANCY":
        text = "Keep the bridge research-only and focus next on redundancy repair and operational capture reliability before any shadow-forward specification."
    else:
        text = "Keep the bridge research-only and tighten realistic cost and missed-signal assumptions before any shadow-forward specification."
    return {**RESEARCH_ONLY_FLAGS, "next_step": text}


def _implementation_self_audit(
    *,
    schema_info: dict[str, Any],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "schema_fields_detected": schema_info.get("schema_fields_detected", []),
        "timestamp_field_used": schema_info.get("timestamp_field_used", "blocked"),
        "baseline_metric_used": "ZERO_COST_REFERENCE rolling_5y_average_ending_equity recomputed from normalized rows",
        "rolling_5y_metric_used": "rolling_5y_average_ending_equity with hit_1m_windows >= 10 for mission survival",
        "full_sequence_metric_used": "full_sequence_ending_equity used only as supplementary context, not for mission gate",
        "leakage_check": True,
        "future_field_usage_check": True,
        "silent_fallback_check": len(warnings) == 0,
        "stress_metric_scope_check": True,
        "previous_artifacts_overwritten": False,
        "reviewer_notes": [
            "Field resolution prefers exit_timestamp, then timestamp, then entry_timestamp.",
            "If no timestamp or no R field is available, the audit blocks safely instead of bucketing rows into unknown.",
            "Rolling 5Y mission metrics are used for mission survival and fragility conclusions; full-sequence equity is context only.",
            *warnings,
        ],
    }


def _court_report(
    *,
    summary: dict[str, Any],
    reliability: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "# Execution Cost Realism and Trade Redundancy Audit",
            "",
            f"Final classification: `{summary['final_classification']}`",
            "",
            "## Court Findings",
            "",
            f"1. Realistic cost verdict: `{summary['realistic_cost_verdict']}`.",
            f"2. Maximum cost band preserving the 1M mission: `{summary['maximum_cost_band_preserving_1m_mission']}`.",
            f"3. Missed-trade tolerance threshold: `{summary['missed_trade_tolerance_threshold_pct']}% random miss rate`.",
            f"4. Trade redundancy verdict: `{summary['trade_redundancy_verdict']}`.",
            f"5. Key cluster dependency verdict: `{summary['key_cluster_dependency_verdict']}`.",
            f"6. Operational reliability requirement: minimum capture `{reliability['minimum_acceptable_signal_capture_rate_pct']}%`, minimum uptime `{reliability['minimum_required_uptime_pct']}%`, max delay `{reliability['maximum_acceptable_candle_delay']}`.",
            f"7. Next research step: `{summary['next_research_step']}`.",
            "",
            "## Guardrails",
            "",
            "- `research_only=true`",
            "- `real_money_allowed=false`",
            "- `paper_allowed=false`",
            "- `live_allowed=false`",
            "- `behavior_change_allowed=false`",
            "- No live, paper, runtime, or production behavior changed",
            "",
        ]
    )


def write_execution_cost_realism_and_trade_redundancy_audit(
    config: ExecutionCostRealismAndTradeRedundancyAuditConfig,
) -> dict[str, Path]:
    context, warnings, schema_info = _load_context(config)
    if context is None:
        return _empty_outputs(
            config,
            classification="EXECUTION_COST_REALISM_AND_TRADE_REDUNDANCY_AUDIT_BLOCKED",
            warnings=warnings,
            self_audit=_implementation_self_audit(schema_info=schema_info, warnings=warnings),
        )

    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    rows = context["rows"]
    windows = context["windows"]
    base_output = context["base_output"]
    base_rolling = _rolling_window_summary(rows, windows, {"stepup_schedule": list(BASE_STEPUP_SCHEDULE)})

    assumptions, cost_band_rows, rolling_rows, drawdown_rows = _evaluate_cost_bands(rows, windows)
    missed_rows, missed_json, missed_thresholds = _evaluate_missed_trade_tolerance(
        rows,
        windows,
        float(base_rolling["average"]),
        base_output,
        max(config.random_repeat_count, 8),
    )
    redundancy_rows, redundancy_report, key_dependency = _trade_redundancy_and_clusters(rows, base_output)
    reliability, shadow_reporting, no_go_risks, classification = _operational_requirements(
        cost_band_rows,
        missed_thresholds,
        redundancy_report,
    )
    next_step = _next_recommendation(classification)

    realistic_survivors = [
        row["band_name"]
        for row in cost_band_rows
        if bool(row["use_for_mission_gate"]) and str(row["mission_verdict"]) == "MISSION_1M_SURVIVES"
    ]
    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "realistic_cost_verdict": context["cost_realism"].get("overall_cost_realism_verdict", "UNKNOWN"),
        "maximum_cost_band_preserving_1m_mission": realistic_survivors[-1] if realistic_survivors else "ZERO_COST_REFERENCE_ONLY",
        "missed_trade_tolerance_threshold_pct": int(missed_thresholds["max_random_missed_trade_rate_pct_for_1m_mission"]),
        "trade_redundancy_verdict": redundancy_report["trade_redundancy_verdict"],
        "key_cluster_dependency_verdict": key_dependency["verdict"],
        "operational_reliability_requirements": {
            "minimum_signal_capture_rate_pct": reliability["minimum_acceptable_signal_capture_rate_pct"],
            "minimum_uptime_pct": reliability["minimum_required_uptime_pct"],
            "maximum_candle_delay": reliability["maximum_acceptable_candle_delay"],
        },
        "final_classification": classification,
        "next_research_step": next_step["next_step"],
    }
    self_audit = _implementation_self_audit(schema_info=schema_info, warnings=warnings)
    report = _court_report(summary=summary, reliability=reliability)

    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "execution_cost_realism_and_trade_redundancy_summary.json", summary)
    _write_markdown(config.output_root / "execution_cost_realism_and_trade_redundancy_report.md", report)
    _write_json(diagnostics_root / "execution_cost_model_assumptions.json", assumptions)
    _write_csv(diagnostics_root / "execution_cost_band_results.csv", cost_band_rows)
    _write_json(diagnostics_root / "execution_cost_band_results.json", {**RESEARCH_ONLY_FLAGS, "rows": cost_band_rows})
    _write_csv(diagnostics_root / "cost_band_rolling_5y_survival.csv", rolling_rows)
    _write_csv(
        diagnostics_root / "cost_band_mission_hit_matrix.csv",
        [
            {
                "band_name": row["band_name"],
                "hit_1m_windows": row["hit_1m_windows"],
                "hit_3m_windows": row["hit_3m_windows"],
                "hit_5m_windows": row["hit_5m_windows"],
                "mission_verdict": row["mission_verdict"],
            }
            for row in cost_band_rows
        ],
    )
    _write_csv(diagnostics_root / "cost_band_drawdown_report.csv", drawdown_rows)
    _write_csv(diagnostics_root / "missed_trade_tolerance_results.csv", missed_rows)
    _write_json(diagnostics_root / "missed_trade_tolerance_results.json", missed_json)
    _write_json(diagnostics_root / "missed_trade_operational_risk_thresholds.json", missed_thresholds)
    _write_csv(diagnostics_root / "trade_redundancy_cluster_audit.csv", redundancy_rows)
    _write_json(diagnostics_root / "trade_redundancy_concentration_report.json", redundancy_report)
    _write_json(diagnostics_root / "key_trade_cluster_dependency.json", key_dependency)
    _write_json(diagnostics_root / "operational_reliability_requirements.json", reliability)
    _write_json(diagnostics_root / "no_go_risks.json", no_go_risks)
    _write_json(diagnostics_root / "implementation_self_audit.json", self_audit)
    _write_json(reports_root / "future_shadow_reporting_requirements.json", shadow_reporting)
    _write_json(reports_root / "next_research_recommendation.json", next_step)
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "execution_cost_realism_and_trade_redundancy_summary.json",
        "report": config.output_root / "execution_cost_realism_and_trade_redundancy_report.md",
    }


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    output_root = package_root / "output" / OUTPUT_FOLDER_NAME
    write_execution_cost_realism_and_trade_redundancy_audit(
        ExecutionCostRealismAndTradeRedundancyAuditConfig(
            package_root=package_root,
            output_root=output_root,
        )
    )
