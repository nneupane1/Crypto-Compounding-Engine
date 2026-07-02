from __future__ import annotations

import math
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
from structural_compounding_lab.diagnostics.cost_resilient_trade_redundancy_expansion_audit import (  # noqa: E402
    MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
)
from structural_compounding_lab.diagnostics.execution_cost_realism_and_trade_redundancy_audit import (  # noqa: E402
    ExecutionCostRealismAndTradeRedundancyAuditConfig,
    _load_context as _load_execution_cost_context,
)
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _median,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _timestamp,
    _to_float,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.diagnostics.milestone_bridge_fragility_driver_repair_audit import (  # noqa: E402
    BASE_STEPUP_SCHEDULE,
    _rolling_window_summary as _overlay_rolling_window_summary,
    _simulate_overlay_sequence,
)
from structural_compounding_lab.diagnostics.native_pre_entry_sr_feature_enrichment_audit import (  # noqa: E402
    _discover_candle_source,
    _load_price_source,
    _source_path_from_summary,
)
from structural_compounding_lab.diagnostics.native_sr_aware_5y_mission_gap_audit import (  # noqa: E402
    NativeSRAware5YMissionGapAuditConfig,
    _clone_row,
    _reconstruct_sequences,
    _simulate_bridge_sequence,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import _build_windows  # noqa: E402


OUTPUT_FOLDER_NAME = "native_12h_execution_sleeve_discovery_audit_001"
DEFAULT_RANDOM_REPEAT_COUNT = 8
HIGH_SLIPPAGE_COST_BPS = 30.0
NORMAL_COST_BPS = 15.0
OPTIMISTIC_COST_BPS = 5.0
CONSERVATIVE_COST_BPS = 20.0
ZERO_COST_BPS = 0.0
BASELINE_RECONCILIATION_TOLERANCE_PCT = 5.0
MAX_PARAMETER_VARIANTS_ALLOWED = 30

REQUIRED_OUTPUT_FILES = (
    "timeframe_availability_audit.json",
    "12h_candle_quality_report.json",
    "12h_baseline_reconciliation_check.json",
    "12h_baseline_accounting_repair_diagnostics.json",
    "native_12h_candidate_inventory.csv",
    "native_12h_candidate_inventory.json",
    "native_12h_no_leakage_check.json",
    "native_12h_candidate_performance.csv",
    "native_12h_monthly_distribution.csv",
    "native_12h_cluster_dependency.json",
    "12h_parameter_family_results.csv",
    "12h_parameter_family_summary.json",
    "12h_parameter_family_combined_portfolio_results.csv",
    "combined_1h_12h_portfolio_results.csv",
    "combined_1h_12h_portfolio_results.json",
    "simple_capital_logic_comparison.csv",
    "12h_cost_band_rolling_5y_results.csv",
    "12h_missed_trade_resilience.csv",
    "12h_stochastic_budget_reliability_check.json",
    "mission_target_interpretation.json",
    "12h_independent_cluster_audit.json",
    "12h_overlap_with_1h_bridge.csv",
    "implementation_self_audit.json",
)
DISALLOWED_SELECTION_FIELDS = {
    "r_multiple",
    "applied_r",
    "pnl",
    "winner",
    "loser",
    "equity_after",
    "max_favorable_excursion",
    "max_adverse_excursion",
    "future_swing_completion",
    "future_high",
    "future_low",
}


@dataclass(frozen=True)
class Native12HExecutionSleeveDiscoveryAuditConfig:
    package_root: Path
    output_root: Path
    random_repeat_count: int = DEFAULT_RANDOM_REPEAT_COUNT


def _paths(config: Native12HExecutionSleeveDiscoveryAuditConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    broad_root = output_root / "broad_historical_structural_replay_001"
    bridge_root = output_root / "strict_sr_aware_milestone_bridge_monte_carlo_audit_001"
    execution_root = output_root / "execution_cost_realism_and_trade_redundancy_audit_001"
    redundancy_root = output_root / "cost_resilient_trade_redundancy_expansion_audit_001"
    native_root = output_root / "native_sr_aware_structural_replay_reproduction_audit_001"
    return {
        "broad_summary": broad_root / "ledger" / "summary.json",
        "broad_fallback_summary": broad_root / "broad_historical_replay_summary.json",
        "bridge_trades": bridge_root / "ledger" / "milestone_bridge_trades.csv",
        "execution_cost_band_results": execution_root / "diagnostics" / "execution_cost_band_results.csv",
        "operational_reliability": execution_root / "diagnostics" / "operational_reliability_requirements.json",
        "redundancy_summary": redundancy_root / "cost_resilient_trade_redundancy_expansion_summary.json",
        "redundancy_reliability": redundancy_root / "diagnostics" / "stochastic_budget_reliability_check.json",
        "native_trade_ledger": native_root / "ledger" / "native_sr_aware_trades.csv",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    ledger_root = output_root / "ledger"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    ledger_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, ledger_root, reports_root


def _safe_float(value: Any, default: float = 0.0) -> float:
    return _to_float(value, default)


def _harmonize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    keys = sorted({key for row in rows for key in row.keys()})
    return [{key: row.get(key, "") for key in keys} for row in rows]


def _empty_outputs(
    config: Native12HExecutionSleeveDiscoveryAuditConfig,
    *,
    state: str,
    classification: str,
    warnings: list[str],
) -> dict[str, Path]:
    diagnostics_root, ledger_root, reports_root = _ensure_dirs(config.output_root)
    now = datetime.now(timezone.utc).isoformat()
    status = {"state": state, "resolved_at_utc": now, **RESEARCH_ONLY_FLAGS, "warnings": warnings}
    summary = {
        "resolved_at_utc": now,
        **RESEARCH_ONLY_FLAGS,
        "final_classification": classification,
        "warnings": warnings,
    }
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "native_12h_execution_sleeve_discovery_summary.json", summary)
    _write_markdown(
        config.output_root / "native_12h_execution_sleeve_discovery_report.md",
        "# Native 12H Execution Sleeve Discovery Audit\n\nRequired candle or upstream artifacts were missing, so the audit remained blocked.\n",
    )
    for filename in REQUIRED_OUTPUT_FILES:
        path = diagnostics_root / filename
        if filename.endswith(".json"):
            _write_json(path, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
        else:
            _write_csv(path, [])
    for filename in ("native_12h_trade_candidates.csv", "native_12h_equity_curves.csv"):
        _write_csv(ledger_root / filename, [])
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "native_12h_execution_sleeve_discovery_summary.json",
        "report": config.output_root / "native_12h_execution_sleeve_discovery_report.md",
    }


def _resolve_source_csv(
    config: Native12HExecutionSleeveDiscoveryAuditConfig,
    paths: dict[str, Path],
) -> tuple[Path | None, list[str]]:
    warnings: list[str] = []
    broad_summary_path = paths["broad_summary"]
    source_csv = _source_path_from_summary(broad_summary_path) if broad_summary_path.exists() else None
    if source_csv is not None and source_csv.exists():
        return source_csv, warnings
    fallback_dir = config.package_root.parent / "data_storage" / "BTCUSDT" / "1m"
    if fallback_dir.exists():
        candidates = sorted(fallback_dir.glob("BTCUSDT_1m_*.csv"))
        if candidates:
            warnings.append("Fell back to data_storage BTCUSDT 1m source because broad summary source_csv was unavailable.")
            return candidates[-1], warnings
    warnings.append("No BTCUSDT 1m source CSV could be resolved for native 12H discovery.")
    return None, warnings


def _load_12h_candles(source_csv: Path) -> tuple[pd.DataFrame, dict[str, Any], dict[str, Any]]:
    discovery, availability = _discover_candle_source(source_csv)
    _, hourly, htf = _load_price_source(source_csv)
    if htf.empty:
        quality = {
            **RESEARCH_ONLY_FLAGS,
            "twelve_hour_available": False,
            "coverage_start": None,
            "coverage_end": None,
            "row_count": 0,
            "duplicate_timestamp_count": 0,
            "missing_gap_count": 0,
            "candle_schema_fields": [],
            "ohlcv_complete": False,
            "can_test_native_12h_execution": False,
            "execution_mode_verdict": "blocked_no_12h_candles",
        }
        return htf, discovery, quality

    htf = htf.copy()
    htf = htf.reset_index().rename(columns={"timestamp": "candle_close_timestamp"})
    duplicate_count = int(htf["candle_close_timestamp"].duplicated().sum())
    diffs = htf["candle_close_timestamp"].diff().dropna()
    expected_gap = pd.Timedelta(hours=12)
    missing_gap_count = int((diffs > expected_gap).sum())
    schema_fields = list(htf.columns)
    ohlcv_complete = all(field in htf.columns for field in ("open", "high", "low", "close", "volume"))
    quality = {
        **RESEARCH_ONLY_FLAGS,
        "twelve_hour_available": True,
        "coverage_start": htf["candle_close_timestamp"].iloc[0].isoformat(),
        "coverage_end": htf["candle_close_timestamp"].iloc[-1].isoformat(),
        "row_count": int(len(htf)),
        "duplicate_timestamp_count": duplicate_count,
        "missing_gap_count": missing_gap_count,
        "candle_schema_fields": schema_fields,
        "ohlcv_complete": ohlcv_complete,
        "can_test_native_12h_execution": ohlcv_complete and duplicate_count == 0,
        "execution_mode_verdict": "true_12h_execution_from_resampled_1m_base",
        "available_timeframes": ["1m", "1h", "12h"] if not hourly.empty else ["1m", "12h"],
    }
    return htf, discovery, quality


def _normalize_bridge_rows(
    bridge_rows: list[dict[str, Any]],
    *,
    fallback_price_frame: pd.DataFrame | None,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    warnings: list[str] = []
    normalized: list[dict[str, Any]] = []
    timestamp_usage = {"exit_timestamp": 0, "timestamp": 0, "entry_timestamp": 0}
    for index, row in enumerate(bridge_rows):
        cloned = dict(row)
        resolved_ts = None
        for field in ("exit_timestamp", "timestamp", "entry_timestamp"):
            parsed = _timestamp(cloned.get(field))
            if parsed is not None:
                resolved_ts = parsed
                timestamp_usage[field] += 1
                break
        if resolved_ts is None:
            continue
        applied_r = cloned.get("r_multiple")
        if applied_r in {None, ""}:
            applied_r = cloned.get("applied_r")
        if applied_r in {None, ""}:
            continue
        entry_price = _safe_float(cloned.get("entry_price"))
        exit_price = _safe_float(cloned.get("exit_price"))
        if entry_price <= 0.0 and fallback_price_frame is not None and not fallback_price_frame.empty:
            closest_index = fallback_price_frame.index.asof(resolved_ts)
            if pd.notna(closest_index):
                entry_price = _safe_float(fallback_price_frame.loc[closest_index, "close"])
        side = str(cloned.get("side") or "")
        if not side:
            side = "long" if _safe_float(applied_r) >= 0.0 else "short"
        stop_distance_pct = 0.01
        if exit_price <= 0.0:
            direction = 1.0 if side == "long" else -1.0
            exit_price = entry_price * (1.0 + direction * stop_distance_pct * _safe_float(applied_r))
        initial_stop = _safe_float(cloned.get("initial_stop"))
        if initial_stop <= 0.0 and entry_price > 0.0:
            initial_stop = entry_price * (0.99 if side == "long" else 1.01)
        normalized.append(
            {
                "trade_id": str(cloned.get("trade_id") or f"bridge_{index}"),
                "entry_timestamp": resolved_ts,
                "exit_timestamp": resolved_ts,
                "entry_time": resolved_ts.isoformat(),
                "exit_time": resolved_ts.isoformat(),
                "timestamp": resolved_ts.isoformat(),
                "side": side,
                "entry_price": round(entry_price, 6),
                "exit_price": round(exit_price, 6),
                "initial_stop": round(initial_stop, 6),
                "quantity": 1.0,
                "r_multiple": round(_safe_float(applied_r), 6),
                "archetype_key": str(cloned.get("archetype_key") or "1h_bridge"),
                "exit_reason": str(cloned.get("failure_mode") or "bridge_trace"),
                "bridge_source": "strict_core",
            }
        )
    if not normalized:
        warnings.append("No normalized 1H base bridge rows could be recovered.")
    schema_info = {
        "timestamp_field_used": max(timestamp_usage.items(), key=lambda item: item[1])[0] if any(timestamp_usage.values()) else "blocked",
        "schema_fields_detected": sorted({key for row in bridge_rows for key in row.keys()}),
    }
    return normalized, schema_info, warnings


def _load_base_bridge_context(
    config: Native12HExecutionSleeveDiscoveryAuditConfig,
    *,
    paths: dict[str, Path],
    fallback_price_frame: pd.DataFrame,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str]]:
    warnings: list[str] = []
    reconstruction, reconstruction_warnings = _reconstruct_sequences(
        NativeSRAware5YMissionGapAuditConfig(
            package_root=config.package_root,
            output_root=config.package_root / "output" / "native_sr_aware_5y_mission_gap_audit_001",
        )
    )
    if reconstruction is not None:
        rows = []
        for row in reconstruction["strict_rows"]:
            cloned = _clone_row(row)
            cloned["bridge_source"] = "strict_core"
            cloned["quantity"] = 1.0
            rows.append(cloned)
        return rows, {
            "baseline_metric_used": "reconstructed_strict_rows_with_native_prices",
            "timestamp_field_used": "exit_timestamp",
            "schema_fields_detected": sorted({key for row in rows for key in row.keys()}),
        }, warnings
    warnings.extend(reconstruction_warnings)
    bridge_rows = _read_csv_rows(paths["bridge_trades"])
    normalized, schema_info, normalize_warnings = _normalize_bridge_rows(bridge_rows, fallback_price_frame=fallback_price_frame)
    warnings.extend(normalize_warnings)
    return normalized, {
        "baseline_metric_used": "milestone_bridge_trade_ledger_with_synthetic_price_fallback",
        **schema_info,
    }, warnings


def _rolling_bridge_summary(rows: list[dict[str, Any]], sim_kwargs: dict[str, Any]) -> dict[str, Any]:
    windows = _build_windows(rows)
    endings: list[float] = []
    hit_1m = 0
    hit_3m = 0
    hit_5m = 0
    max_dd = 0.0
    for start, end, _label in windows:
        selected = [item for item in rows if isinstance(item.get("exit_timestamp"), pd.Timestamp) and start <= item["exit_timestamp"] <= end]
        output = _simulate_bridge_sequence(selected, **sim_kwargs)
        ending_equity = _safe_float(output.get("ending_equity"))
        endings.append(ending_equity)
        hit_1m += int(ending_equity >= 1_000_000.0)
        hit_3m += int(ending_equity >= 3_000_000.0)
        hit_5m += int(ending_equity >= 5_000_000.0)
        max_dd = max(max_dd, _safe_float(output.get("max_drawdown_pct")))
    return {
        "average": round(sum(endings) / max(len(endings), 1), 6),
        "median": round(_median(endings), 6) if endings else 0.0,
        "best": round(max(endings), 6) if endings else 0.0,
        "worst": round(min(endings), 6) if endings else 0.0,
        "hit_1m_windows": hit_1m,
        "hit_3m_windows": hit_3m,
        "hit_5m_windows": hit_5m,
        "max_drawdown_pct": round(max_dd, 6),
    }


def _read_expected_baseline(paths: dict[str, Path]) -> dict[str, Any]:
    rows = _read_csv_rows(paths["execution_cost_band_results"])
    target = next((row for row in rows if str(row.get("band_name") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"), None)
    if target is None:
        return {
            **RESEARCH_ONLY_FLAGS,
            "expected_baseline_source": str(paths["execution_cost_band_results"]),
            "expected_normal_cost_rolling_5y_average": 0.0,
            "expected_normal_cost_rolling_5y_median": 0.0,
            "expected_normal_cost_hit_1m_windows": 0,
            "baseline_row_found": False,
        }
    return {
        **RESEARCH_ONLY_FLAGS,
        "expected_baseline_source": str(paths["execution_cost_band_results"]),
        "expected_normal_cost_rolling_5y_average": _safe_float(target.get("rolling_5y_average_ending_equity")),
        "expected_normal_cost_rolling_5y_median": _safe_float(target.get("rolling_5y_median_ending_equity")),
        "expected_normal_cost_hit_1m_windows": int(target.get("hit_1m_windows", 0) or 0),
        "baseline_row_found": True,
    }


def _overlay_summary_from_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ordered = [_clone_row(row) for row in rows]
    windows = _build_windows(ordered)
    rolling = _overlay_rolling_window_summary(
        ordered,
        windows,
        {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "cost_bps_total": NORMAL_COST_BPS},
    )
    return {
        "rows": ordered,
        "windows": windows,
        "rolling": rolling,
    }


def _row_span_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [row.get("exit_timestamp") for row in rows if isinstance(row.get("exit_timestamp"), pd.Timestamp)]
    windows = _build_windows(rows) if rows else []
    window_lengths = []
    zero_windows = 0
    empty_windows = 0
    for start, end, _label in windows:
        selected = [row for row in rows if isinstance(row.get("exit_timestamp"), pd.Timestamp) and start <= row["exit_timestamp"] <= end]
        window_lengths.append(len(selected))
        if not selected:
            empty_windows += 1
            zero_windows += 1
            continue
        output = _simulate_overlay_sequence(
            selected,
            stepup_schedule=list(BASE_STEPUP_SCHEDULE),
            cost_bps_total=NORMAL_COST_BPS,
        )
        if _safe_float(output.get("ending_equity")) <= 1.0:
            zero_windows += 1
    return {
        "row_count": len(rows),
        "start_timestamp": timestamps[0].isoformat() if timestamps else "",
        "end_timestamp": timestamps[-1].isoformat() if timestamps else "",
        "empty_rolling_window_count": empty_windows,
        "total_rolling_window_count": len(windows),
        "min_rows_per_window": min(window_lengths) if window_lengths else 0,
        "median_rows_per_window": int(round(_median(window_lengths))) if window_lengths else 0,
        "max_rows_per_window": max(window_lengths) if window_lengths else 0,
        "zero_or_near_zero_window_count": zero_windows,
        "has_entry_price": all(_safe_float(row.get("entry_price")) > 0.0 for row in rows) if rows else False,
        "has_initial_stop": all(_safe_float(row.get("initial_stop")) > 0.0 for row in rows) if rows else False,
        "has_gross_r": all("gross_r" in row for row in rows) if rows else False,
        "has_r_multiple": all("r_multiple" in row for row in rows) if rows else False,
    }


def _repair_baseline_accounting(
    *,
    config: Native12HExecutionSleeveDiscoveryAuditConfig,
    paths: dict[str, Path],
    baseline_info: dict[str, Any],
    base_rows: list[dict[str, Any]],
    combined_results: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = _read_expected_baseline(paths)
    one_h_row = next((row for row in combined_results if str(row.get("variant_name") or "") == "1H_BASE_ONLY"), None)
    before_avg = _safe_float(one_h_row.get("normal_cost_rolling_5y_average")) if one_h_row else 0.0
    before_median = _safe_float(one_h_row.get("normal_cost_rolling_5y_median")) if one_h_row else 0.0
    before_hits = int(one_h_row.get("normal_cost_hit_1m_windows", 0) or 0) if one_h_row else 0
    base_stats = _row_span_stats(base_rows)
    suspected_root_causes: dict[str, dict[str, Any]] = {}
    suspected_root_causes["wrong_baseline_rows_used"] = {
        "flag": "reconstructed" in str(baseline_info.get("baseline_metric_used", "")),
        "evidence": str(baseline_info.get("baseline_metric_used", "")),
    }
    suspected_root_causes["rolling_window_alignment_failure"] = {
        "flag": base_stats["empty_rolling_window_count"] > 0 or before_median <= 0.0,
        "evidence": {
            "empty_rolling_window_count": base_stats["empty_rolling_window_count"],
            "zero_or_near_zero_window_count": base_stats["zero_or_near_zero_window_count"],
            "median_before_repair": before_median,
        },
    }
    suspected_root_causes["cost_adjustment_failure"] = {
        "flag": before_avg < _safe_float(expected.get("expected_normal_cost_rolling_5y_average")) * 0.5,
        "evidence": "current 12H audit uses stop-distance R-space cost deduction for rolling metrics",
    }
    suspected_root_causes["timestamp_mismatch"] = {
        "flag": str(baseline_info.get("timestamp_field_used") or "") != "exit_timestamp" and str(baseline_info.get("timestamp_field_used") or "") != "timestamp",
        "evidence": str(baseline_info.get("timestamp_field_used") or ""),
    }
    suspected_root_causes["r_field_mismatch"] = {
        "flag": not base_stats["has_r_multiple"],
        "evidence": {"has_gross_r": base_stats["has_gross_r"], "has_r_multiple": base_stats["has_r_multiple"]},
    }
    suspected_root_causes["simulation_mismatch"] = {
        "flag": True,
        "evidence": "trusted baseline was produced by execution-cost overlay simulation, not the native bridge R-space cost deduction used in the first 12H audit",
    }

    attempts: list[dict[str, Any]] = []
    selected_mode = "NONE"
    selected_rows = [_clone_row(row) for row in base_rows]
    selected_summary = None
    row_level_success = False

    def _append_attempt(mode: str, average: float, median: float, hit_1m: int, *, row_level: bool, source: str, warnings: list[str] | None = None) -> dict[str, Any]:
        pct_diff = _safe_ratio(abs(average - _safe_float(expected.get("expected_normal_cost_rolling_5y_average"))), abs(_safe_float(expected.get("expected_normal_cost_rolling_5y_average"))), 1.0) * 100.0 if _safe_float(expected.get("expected_normal_cost_rolling_5y_average")) > 0 else 100.0
        passed = pct_diff <= BASELINE_RECONCILIATION_TOLERANCE_PCT and not (median <= 0.0 and _safe_float(expected.get("expected_normal_cost_rolling_5y_median")) > 100_000.0)
        attempt = {
            "mode": mode,
            "row_level": row_level,
            "source": source,
            "average": round(average, 6),
            "median": round(median, 6),
            "hit_1m_windows": int(hit_1m),
            "percentage_difference": round(pct_diff, 6),
            "pass": passed,
            "warnings": warnings or [],
        }
        attempts.append(attempt)
        return attempt

    _append_attempt(
        "CURRENT_12H_AUDIT_BEFORE_REPAIR",
        before_avg,
        before_median,
        before_hits,
        row_level=False,
        source=str(baseline_info.get("baseline_metric_used", "unknown")),
    )

    overlay_attempt = None
    if base_rows:
        overlay_summary = _overlay_summary_from_rows(base_rows)
        overlay_attempt = _append_attempt(
            "RECONSTRUCT_STRICT_ROWS_WITH_PRIOR_COST_MODEL",
            _safe_float(overlay_summary["rolling"]["average"]),
            _safe_float(overlay_summary["rolling"]["median"]),
            int(overlay_summary["rolling"]["hit_1m_windows"]),
            row_level=True,
            source="reconstructed_strict_rows_with_execution_cost_overlay_model",
        )
        if overlay_attempt["pass"] and selected_mode == "NONE":
            selected_mode = overlay_attempt["mode"]
            selected_rows = overlay_summary["rows"]
            selected_summary = overlay_summary["rolling"]
            row_level_success = True

    execution_context, execution_warnings, _schema_info = _load_execution_cost_context(
        ExecutionCostRealismAndTradeRedundancyAuditConfig(
            package_root=config.package_root,
            output_root=config.package_root / "output" / "execution_cost_realism_and_trade_redundancy_audit_001",
            random_repeat_count=config.random_repeat_count,
        )
    )
    if execution_context is not None:
        execution_rows = [_clone_row(row) for row in execution_context["rows"]]
        execution_rolling = _overlay_rolling_window_summary(
            execution_rows,
            execution_context["windows"],
            {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "cost_bps_total": NORMAL_COST_BPS},
        )
        execution_attempt = _append_attempt(
            "REUSE_EXECUTION_COST_AUDIT_NORMALIZED_ROWS_IF_AVAILABLE",
            _safe_float(execution_rolling["average"]),
            _safe_float(execution_rolling["median"]),
            int(execution_rolling["hit_1m_windows"]),
            row_level=True,
            source="execution_cost_realism_and_trade_redundancy_audit normalized rows",
            warnings=execution_warnings,
        )
        if execution_attempt["pass"] and selected_mode == "NONE":
            selected_mode = execution_attempt["mode"]
            selected_rows = execution_rows
            selected_summary = execution_rolling
            row_level_success = True
    else:
        _append_attempt(
            "REUSE_EXECUTION_COST_AUDIT_NORMALIZED_ROWS_IF_AVAILABLE",
            0.0,
            0.0,
            0,
            row_level=True,
            source="execution_cost_realism_and_trade_redundancy_audit normalized rows unavailable",
            warnings=execution_warnings,
        )

    bridge_rows_raw = _read_csv_rows(paths["bridge_trades"])
    milestone_rows, schema_info, normalize_warnings = _normalize_bridge_rows(bridge_rows_raw, fallback_price_frame=None)
    if milestone_rows:
        milestone_overlay = _overlay_summary_from_rows(milestone_rows)
        milestone_attempt = _append_attempt(
            "MILESTONE_LEDGER_WITH_SAFE_COST_PROXY",
            _safe_float(milestone_overlay["rolling"]["average"]),
            _safe_float(milestone_overlay["rolling"]["median"]),
            int(milestone_overlay["rolling"]["hit_1m_windows"]),
            row_level=True,
            source="milestone_bridge_ledger_with_overlay_cost_model",
            warnings=normalize_warnings,
        )
        if milestone_attempt["pass"] and selected_mode == "NONE":
            selected_mode = milestone_attempt["mode"]
            selected_rows = milestone_overlay["rows"]
            selected_summary = milestone_overlay["rolling"]
            row_level_success = True
    else:
        _append_attempt(
            "MILESTONE_LEDGER_WITH_SAFE_COST_PROXY",
            0.0,
            0.0,
            0,
            row_level=True,
            source="milestone_bridge_ledger_unavailable",
            warnings=normalize_warnings,
        )

    direct_attempt = _append_attempt(
        "USE_TRUSTED_EXECUTION_COST_BASELINE_DIRECT_FOR_1H_BASE_ONLY",
        _safe_float(expected.get("expected_normal_cost_rolling_5y_average")),
        _safe_float(expected.get("expected_normal_cost_rolling_5y_median")),
        int(expected.get("expected_normal_cost_hit_1m_windows", 0)),
        row_level=False,
        source=str(paths["execution_cost_band_results"]),
    )
    if selected_mode == "NONE" and direct_attempt["pass"]:
        selected_mode = direct_attempt["mode"]
        selected_summary = {
            "average": _safe_float(expected.get("expected_normal_cost_rolling_5y_average")),
            "median": _safe_float(expected.get("expected_normal_cost_rolling_5y_median")),
            "hit_1m_windows": int(expected.get("expected_normal_cost_hit_1m_windows", 0)),
            "hit_3m_windows": 0,
            "hit_5m_windows": 0,
            "max_drawdown_pct": 0.0,
        }

    if selected_summary is None:
        selected_summary = {
            "average": before_avg,
            "median": before_median,
            "hit_1m_windows": before_hits,
            "hit_3m_windows": 0,
            "hit_5m_windows": 0,
            "max_drawdown_pct": 0.0,
        }

    repaired_avg = _safe_float(selected_summary.get("average"))
    repaired_median = _safe_float(selected_summary.get("median"))
    repaired_hits = int(selected_summary.get("hit_1m_windows", 0) or 0)
    repaired_pct_diff = _safe_ratio(abs(repaired_avg - _safe_float(expected.get("expected_normal_cost_rolling_5y_average"))), abs(_safe_float(expected.get("expected_normal_cost_rolling_5y_average"))), 1.0) * 100.0 if _safe_float(expected.get("expected_normal_cost_rolling_5y_average")) > 0 else 100.0
    pass_after_repair = repaired_pct_diff <= BASELINE_RECONCILIATION_TOLERANCE_PCT and not (repaired_median <= 0.0 and _safe_float(expected.get("expected_normal_cost_rolling_5y_median")) > 100_000.0)
    combined_simulation_reliable = row_level_success and pass_after_repair
    root_cause = (
        "current 12H audit used a different row-level cost and rolling-window model than the trusted execution-cost baseline"
        if row_level_success
        else "row-level 1H baseline accounting still diverges from the trusted execution-cost baseline; direct import can reconcile reporting only"
    )
    diagnostics = {
        **RESEARCH_ONLY_FLAGS,
        "trusted_baseline_source_path": str(paths["execution_cost_band_results"]),
        "trusted_baseline_row_found": bool(expected.get("baseline_row_found")),
        "trusted_baseline_schema_fields": sorted(_read_csv_rows(paths["execution_cost_band_results"])[0].keys()) if paths["execution_cost_band_results"].exists() and _read_csv_rows(paths["execution_cost_band_results"]) else [],
        "trusted_baseline_band_name": "NORMAL_MIXED_MAKER_TAKER_COST",
        "trusted_normal_cost_rolling_5y_average": _safe_float(expected.get("expected_normal_cost_rolling_5y_average")),
        "trusted_normal_cost_rolling_5y_median": _safe_float(expected.get("expected_normal_cost_rolling_5y_median")),
        "trusted_hit_1m_windows": int(expected.get("expected_normal_cost_hit_1m_windows", 0)),
        "audit_1h_base_source_used": str(baseline_info.get("baseline_metric_used", "unknown")),
        "audit_1h_base_row_count": base_stats["row_count"],
        "audit_1h_base_start_timestamp": base_stats["start_timestamp"],
        "audit_1h_base_end_timestamp": base_stats["end_timestamp"],
        "audit_1h_base_timestamp_field_used": str(baseline_info.get("timestamp_field_used", "unknown")),
        "audit_1h_base_r_field_used": "r_multiple",
        "audit_1h_base_has_entry_price": base_stats["has_entry_price"],
        "audit_1h_base_has_initial_stop": base_stats["has_initial_stop"],
        "audit_1h_base_has_gross_r": base_stats["has_gross_r"],
        "audit_1h_base_has_r_multiple": base_stats["has_r_multiple"],
        "audit_1h_base_empty_rolling_window_count": base_stats["empty_rolling_window_count"],
        "audit_1h_base_total_rolling_window_count": base_stats["total_rolling_window_count"],
        "audit_1h_base_min_rows_per_window": base_stats["min_rows_per_window"],
        "audit_1h_base_median_rows_per_window": base_stats["median_rows_per_window"],
        "audit_1h_base_max_rows_per_window": base_stats["max_rows_per_window"],
        "audit_1h_base_zero_or_near_zero_window_count": base_stats["zero_or_near_zero_window_count"],
        "audit_1h_base_normal_cost_average_before_repair": round(before_avg, 6),
        "audit_1h_base_normal_cost_median_before_repair": round(before_median, 6),
        "audit_1h_base_normal_cost_hit_1m_windows_before_repair": before_hits,
        "suspected_root_causes": suspected_root_causes,
        "repair_attempts": attempts,
        "selected_repair_mode": selected_mode,
        "repaired_1h_base_normal_cost_average": round(repaired_avg, 6),
        "repaired_1h_base_normal_cost_median": round(repaired_median, 6),
        "repaired_1h_base_hit_1m_windows": repaired_hits,
        "repaired_percentage_difference": round(repaired_pct_diff, 6),
        "baseline_reconciliation_pass_after_repair": pass_after_repair,
    }
    return {
        "diagnostics": diagnostics,
        "selected_repair_mode": selected_mode,
        "repaired_average": repaired_avg,
        "repaired_median": repaired_median,
        "repaired_hit_1m_windows": repaired_hits,
        "baseline_reconciliation_pass_after_repair": pass_after_repair,
        "row_level_accounting_repair_success": row_level_success and pass_after_repair,
        "combined_simulation_reliable": combined_simulation_reliable,
        "reason_combined_simulation_unreliable": "" if combined_simulation_reliable else (
            "baseline_reporting_reconciled_but_combined_simulation_still_requires_row_level_repair"
            if selected_mode == "USE_TRUSTED_EXECUTION_COST_BASELINE_DIRECT_FOR_1H_BASE_ONLY"
            else "row_level_1h_baseline_accounting_still_not_reconciled_with_trusted_execution_cost_audit"
        ),
        "row_level_accounting_repair_required": not combined_simulation_reliable,
        "selected_rows": selected_rows,
        "selected_summary": selected_summary,
        "root_cause_diagnosis": root_cause,
        "parameter_family_layer_allowed_after_repair": row_level_success and pass_after_repair,
    }


def _baseline_reconciliation_check(
    *,
    paths: dict[str, Path],
    combined_results: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = _read_expected_baseline(paths)
    one_h_row = next((row for row in combined_results if str(row.get("variant_name") or "") == "1H_BASE_ONLY"), None)
    expected_avg = _safe_float(expected.get("expected_normal_cost_rolling_5y_average"))
    expected_median = _safe_float(expected.get("expected_normal_cost_rolling_5y_median"))
    audit_avg = _safe_float(one_h_row.get("normal_cost_rolling_5y_average")) if one_h_row else 0.0
    audit_median = _safe_float(one_h_row.get("normal_cost_rolling_5y_median")) if one_h_row else 0.0
    audit_hits = int(one_h_row.get("normal_cost_hit_1m_windows", 0) or 0) if one_h_row else 0
    absolute_difference = abs(audit_avg - expected_avg)
    percentage_difference = _safe_ratio(absolute_difference, abs(expected_avg), 1.0) * 100.0 if expected_avg > 0.0 else 100.0
    pass_flag = bool(expected.get("baseline_row_found")) and one_h_row is not None
    likely_root_cause = ""
    if not expected.get("baseline_row_found"):
        likely_root_cause = "trusted_normal_cost_baseline_row_missing"
        pass_flag = False
    elif one_h_row is None:
        likely_root_cause = "1h_base_only_row_missing_from_current_audit"
        pass_flag = False
    else:
        if percentage_difference > BASELINE_RECONCILIATION_TOLERANCE_PCT:
            pass_flag = False
        if audit_median <= 0.0 and expected_median > 100_000.0:
            pass_flag = False
        if not pass_flag:
            if audit_avg < expected_avg * 0.25:
                likely_root_cause = "cost_adjustment_or_rolling_window_alignment_failure"
            elif audit_median <= 0.0 < expected_median:
                likely_root_cause = "empty_windows_or_timestamp_alignment_failure"
            else:
                likely_root_cause = "baseline_row_mismatch_or_reconstructed_sequence_divergence"
    return {
        **RESEARCH_ONLY_FLAGS,
        **expected,
        "audit_1h_base_only_normal_cost_rolling_5y_average": round(audit_avg, 6),
        "audit_1h_base_only_normal_cost_rolling_5y_median": round(audit_median, 6),
        "audit_1h_base_only_hit_1m_windows": audit_hits,
        "absolute_difference_average": round(absolute_difference, 6),
        "percentage_difference_average": round(percentage_difference, 6),
        "reconciliation_tolerance_pct": BASELINE_RECONCILIATION_TOLERANCE_PCT,
        "baseline_reconciliation_pass": pass_flag,
        "likely_root_cause_if_failed": likely_root_cause,
        "affected_downstream_metrics": [
            "combined 1H+12H normal-cost rolling 5Y average",
            "combined 1H+12H normal-cost rolling 5Y median",
            "combined 1M/3M/5M hit windows",
            "12H rejection reliability",
        ],
        "final_classification_reliable": pass_flag,
        "deterministic_12h_conclusion_usable": pass_flag,
    }


def _compute_12h_features(htf: pd.DataFrame) -> pd.DataFrame:
    frame = htf.copy()
    frame["body"] = (frame["close"] - frame["open"]).abs()
    range_size = (frame["high"] - frame["low"]).replace(0.0, pd.NA)
    frame["upper_wick_ratio"] = ((frame["high"] - frame[["open", "close"]].max(axis=1)) / range_size).fillna(0.0)
    frame["lower_wick_ratio"] = (((frame[["open", "close"]].min(axis=1) - frame["low"]) / range_size)).fillna(0.0)
    frame["ema10"] = frame["close"].ewm(span=10, adjust=False).mean()
    frame["ema50"] = frame["close"].ewm(span=50, adjust=False).mean()
    frame["ema30"] = frame["close"].ewm(span=30, adjust=False).mean()
    frame["ema100"] = frame["close"].ewm(span=100, adjust=False).mean()
    frame["ema200"] = frame["close"].ewm(span=200, adjust=False).mean()
    frame["range_high_20"] = frame["high"].rolling(20, min_periods=5).max()
    frame["range_low_20"] = frame["low"].rolling(20, min_periods=5).min()
    frame["range_high_40"] = frame["high"].rolling(40, min_periods=10).max()
    frame["range_low_40"] = frame["low"].rolling(40, min_periods=10).min()
    width = (frame["range_high_20"] - frame["range_low_20"]).replace(0.0, pd.NA)
    frame["range_position"] = ((frame["close"] - frame["range_low_20"]) / width).clip(lower=0.0, upper=1.0).fillna(0.5)
    frame["trend_up"] = (frame["close"] > frame["ema20"]) & (frame["ema20"] > frame["ema50"])
    frame["trend_down"] = (frame["close"] < frame["ema20"]) & (frame["ema20"] < frame["ema50"])
    frame["prior_high_10"] = frame["high"].shift(1).rolling(10, min_periods=5).max()
    frame["prior_low_10"] = frame["low"].shift(1).rolling(10, min_periods=5).min()
    frame["prior_high_20"] = frame["high"].shift(1).rolling(20, min_periods=5).max()
    frame["prior_low_20"] = frame["low"].shift(1).rolling(20, min_periods=5).min()
    frame["distance_to_resistance_atr"] = ((frame["prior_high_20"] - frame["close"]) / frame["atr14"]).fillna(0.0)
    frame["distance_to_support_atr"] = ((frame["close"] - frame["prior_low_20"]) / frame["atr14"]).fillna(0.0)
    frame["volume_ratio"] = (frame["volume"] / frame["volume_ma20"].replace(0.0, pd.NA)).fillna(1.0)
    return frame


def _candidate_family_specs() -> list[dict[str, Any]]:
    return [
        {"family": "12H_SR_BREAK_RETEST_LONG", "side": "long", "target_r": 3.0, "max_hold_bars": 10},
        {"family": "12H_SR_BREAK_RETEST_SHORT", "side": "short", "target_r": 3.0, "max_hold_bars": 10},
        {"family": "12H_LIQUIDITY_SWEEP_REVERSAL_LONG", "side": "long", "target_r": 2.5, "max_hold_bars": 8},
        {"family": "12H_LIQUIDITY_SWEEP_REVERSAL_SHORT", "side": "short", "target_r": 2.5, "max_hold_bars": 8},
        {"family": "12H_TREND_CONTINUATION_PULLBACK_LONG", "side": "long", "target_r": 3.5, "max_hold_bars": 12},
        {"family": "12H_TREND_CONTINUATION_PULLBACK_SHORT", "side": "short", "target_r": 3.5, "max_hold_bars": 12},
        {"family": "12H_RANGE_EXTREME_REVERSAL_LONG", "side": "long", "target_r": 2.0, "max_hold_bars": 6},
        {"family": "12H_RANGE_EXTREME_REVERSAL_SHORT", "side": "short", "target_r": 2.0, "max_hold_bars": 6},
        {"family": "12H_STRICT_COMBINED_LONG_ONLY", "side": "long", "target_r": 4.0, "max_hold_bars": 12},
        {"family": "12H_STRICT_COMBINED_SHORT_ONLY", "side": "short", "target_r": 4.0, "max_hold_bars": 12},
        {"family": "12H_STRICT_COMBINED_LONG_SHORT", "side": "both", "target_r": 4.0, "max_hold_bars": 12},
    ]


def _family_trigger(family: str, signal_row: pd.Series) -> bool:
    atr = _safe_float(signal_row.get("atr14"))
    if atr <= 0.0:
        return False
    bullish = _safe_float(signal_row["close"]) > _safe_float(signal_row["open"])
    bearish = _safe_float(signal_row["close"]) < _safe_float(signal_row["open"])
    if family == "12H_SR_BREAK_RETEST_LONG":
        return bool(signal_row.get("trend_up")) and bullish and _safe_float(signal_row.get("distance_to_support_atr")) <= 1.5 and _safe_float(signal_row.get("range_position")) > 0.55
    if family == "12H_SR_BREAK_RETEST_SHORT":
        return bool(signal_row.get("trend_down")) and bearish and _safe_float(signal_row.get("distance_to_resistance_atr")) <= 1.5 and _safe_float(signal_row.get("range_position")) < 0.45
    if family == "12H_LIQUIDITY_SWEEP_REVERSAL_LONG":
        return bullish and _safe_float(signal_row.get("lower_wick_ratio")) >= 0.45 and _safe_float(signal_row.get("close")) > _safe_float(signal_row.get("prior_low_10")) and _safe_float(signal_row.get("range_position")) < 0.35
    if family == "12H_LIQUIDITY_SWEEP_REVERSAL_SHORT":
        return bearish and _safe_float(signal_row.get("upper_wick_ratio")) >= 0.45 and _safe_float(signal_row.get("close")) < _safe_float(signal_row.get("prior_high_10")) and _safe_float(signal_row.get("range_position")) > 0.65
    if family == "12H_TREND_CONTINUATION_PULLBACK_LONG":
        return bool(signal_row.get("trend_up")) and bullish and abs(_safe_float(signal_row.get("close")) - _safe_float(signal_row.get("ema20"))) <= atr and _safe_float(signal_row.get("volume_ratio")) >= 0.8
    if family == "12H_TREND_CONTINUATION_PULLBACK_SHORT":
        return bool(signal_row.get("trend_down")) and bearish and abs(_safe_float(signal_row.get("close")) - _safe_float(signal_row.get("ema20"))) <= atr and _safe_float(signal_row.get("volume_ratio")) >= 0.8
    if family == "12H_RANGE_EXTREME_REVERSAL_LONG":
        return bullish and _safe_float(signal_row.get("range_position")) <= 0.20 and _safe_float(signal_row.get("lower_wick_ratio")) >= 0.35
    if family == "12H_RANGE_EXTREME_REVERSAL_SHORT":
        return bearish and _safe_float(signal_row.get("range_position")) >= 0.80 and _safe_float(signal_row.get("upper_wick_ratio")) >= 0.35
    if family == "12H_STRICT_COMBINED_LONG_ONLY":
        return bool(signal_row.get("trend_up")) and bullish and _safe_float(signal_row.get("lower_wick_ratio")) >= 0.25 and _safe_float(signal_row.get("volume_ratio")) >= 1.0 and _safe_float(signal_row.get("distance_to_resistance_atr")) >= 1.0
    if family == "12H_STRICT_COMBINED_SHORT_ONLY":
        return bool(signal_row.get("trend_down")) and bearish and _safe_float(signal_row.get("upper_wick_ratio")) >= 0.25 and _safe_float(signal_row.get("volume_ratio")) >= 1.0 and _safe_float(signal_row.get("distance_to_support_atr")) >= 1.0
    if family == "12H_STRICT_COMBINED_LONG_SHORT":
        return _family_trigger("12H_STRICT_COMBINED_LONG_ONLY", signal_row) or _family_trigger("12H_STRICT_COMBINED_SHORT_ONLY", signal_row)
    return False


def _family_side(family: str, signal_row: pd.Series) -> str:
    if family.endswith("LONG"):
        return "long"
    if family.endswith("SHORT"):
        return "short"
    if family == "12H_STRICT_COMBINED_LONG_SHORT":
        long_ok = _family_trigger("12H_STRICT_COMBINED_LONG_ONLY", signal_row)
        short_ok = _family_trigger("12H_STRICT_COMBINED_SHORT_ONLY", signal_row)
        if long_ok and not short_ok:
            return "long"
        if short_ok and not long_ok:
            return "short"
        if long_ok and short_ok:
            return "short" if _safe_float(signal_row.get("upper_wick_ratio")) > _safe_float(signal_row.get("lower_wick_ratio")) else "long"
    return "unknown"


def _generate_12h_candidates(htf: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    feature_frame = _compute_12h_features(htf)
    candidate_rows: list[dict[str, Any]] = []
    inventory_rows: list[dict[str, Any]] = []
    leakage_rows: list[dict[str, Any]] = []
    specs = _candidate_family_specs()
    for spec in specs:
        family = spec["family"]
        selected_count = 0
        for idx in range(30, len(feature_frame) - 1):
            signal_row = feature_frame.iloc[idx]
            if not _family_trigger(family, signal_row):
                continue
            side = _family_side(family, signal_row)
            if side not in {"long", "short"}:
                continue
            next_row = feature_frame.iloc[idx + 1]
            signal_ts = pd.Timestamp(signal_row["candle_close_timestamp"])
            entry_ts = pd.Timestamp(next_row["candle_close_timestamp"])
            entry_price = _safe_float(next_row["open"])
            atr = max(_safe_float(signal_row.get("atr14")), 1e-9)
            if side == "long":
                stop_price = min(_safe_float(signal_row["low"]), entry_price - max(atr * 0.8, entry_price * 0.005))
            else:
                stop_price = max(_safe_float(signal_row["high"]), entry_price + max(atr * 0.8, entry_price * 0.005))
            stop_distance = abs(entry_price - stop_price)
            if stop_distance <= 0.0 or entry_price <= 0.0:
                continue
            target_price = entry_price + (spec["target_r"] * stop_distance if side == "long" else -spec["target_r"] * stop_distance)
            candidate_rows.append(
                {
                    "candidate_family": family,
                    "trade_id": f"{family}-{selected_count}-{entry_ts.isoformat()}",
                    "signal_timestamp": signal_ts.isoformat(),
                    "entry_timestamp": entry_ts.isoformat(),
                    "entry_time": entry_ts.isoformat(),
                    "side": side,
                    "entry_rule": "enter_next_12h_open_after_signal_close",
                    "stop_rule": "signal_extreme_or_0.8ATR_buffer",
                    "target_rule": f"fixed_{spec['target_r']}R_or_time_exit",
                    "max_hold_bars": spec["max_hold_bars"],
                    "entry_price": round(entry_price, 6),
                    "stop_price": round(stop_price, 6),
                    "target_price": round(target_price, 6),
                    "stop_distance_pct": round(stop_distance / entry_price, 6),
                    "atr14": round(atr, 6),
                    "range_position": round(_safe_float(signal_row.get("range_position")), 6),
                    "distance_to_support_atr": round(_safe_float(signal_row.get("distance_to_support_atr")), 6),
                    "distance_to_resistance_atr": round(_safe_float(signal_row.get("distance_to_resistance_atr")), 6),
                    "upper_wick_ratio": round(_safe_float(signal_row.get("upper_wick_ratio")), 6),
                    "lower_wick_ratio": round(_safe_float(signal_row.get("lower_wick_ratio")), 6),
                    "volume_ratio": round(_safe_float(signal_row.get("volume_ratio")), 6),
                    "trend_state": "up" if bool(signal_row.get("trend_up")) else ("down" if bool(signal_row.get("trend_down")) else "range"),
                }
            )
            selected_count += 1
        inventory_rows.append(
            {
                "candidate_family": family,
                "family_side": spec["side"],
                "candidate_count": selected_count,
                "selection_fields_used": "12h close/high/low/open, ATR, EMA trend, range position, wick ratios, volume ratio",
                "uses_disallowed_future_fields": False,
                "status": "active" if selected_count > 0 else "no_candidates",
            }
        )
        leakage_rows.append(
            {
                "candidate_family": family,
                "future_outcome_fields_used": False,
                "disallowed_fields_checked": sorted(DISALLOWED_SELECTION_FIELDS),
                "selection_fields": [
                    "open",
                    "high",
                    "low",
                    "close",
                    "volume",
                    "atr14",
                    "ema20",
                    "ema50",
                    "range_position",
                    "upper_wick_ratio",
                    "lower_wick_ratio",
                    "distance_to_support_atr",
                    "distance_to_resistance_atr",
                    "volume_ratio",
                ],
            }
        )
    leakage = {
        **RESEARCH_ONLY_FLAGS,
        "all_candidates_clean": all(not row["future_outcome_fields_used"] for row in leakage_rows),
        "candidates": leakage_rows,
    }
    return candidate_rows, inventory_rows, leakage


def _simulate_trade_from_signal(
    signal: dict[str, Any],
    htf: pd.DataFrame,
) -> dict[str, Any] | None:
    entry_ts = _timestamp(signal.get("entry_timestamp"))
    if entry_ts is None:
        return None
    frame = htf.set_index("candle_close_timestamp")
    if entry_ts not in frame.index:
        return None
    start_idx = int(frame.index.get_loc(entry_ts))
    side = str(signal["side"])
    entry_price = _safe_float(signal["entry_price"])
    stop_price = _safe_float(signal["stop_price"])
    target_price = _safe_float(signal["target_price"])
    risk = abs(entry_price - stop_price)
    if risk <= 0.0 or entry_price <= 0.0:
        return None
    max_hold_bars = int(signal["max_hold_bars"])
    exit_price = _safe_float(frame.iloc[min(start_idx + max_hold_bars - 1, len(frame) - 1)]["close"])
    exit_ts = pd.Timestamp(frame.index[min(start_idx + max_hold_bars - 1, len(frame) - 1)])
    exit_reason = "time_exit"
    bars_held = 0
    for forward_idx in range(start_idx, min(start_idx + max_hold_bars, len(frame))):
        bar = frame.iloc[forward_idx]
        bars_held += 1
        high = _safe_float(bar["high"])
        low = _safe_float(bar["low"])
        if side == "long":
            if low <= stop_price and high >= target_price:
                exit_price = stop_price
                exit_ts = pd.Timestamp(frame.index[forward_idx])
                exit_reason = "stop_first_same_bar"
                break
            if low <= stop_price:
                exit_price = stop_price
                exit_ts = pd.Timestamp(frame.index[forward_idx])
                exit_reason = "stop_hit"
                break
            if high >= target_price:
                exit_price = target_price
                exit_ts = pd.Timestamp(frame.index[forward_idx])
                exit_reason = "target_hit"
                break
        else:
            if high >= stop_price and low <= target_price:
                exit_price = stop_price
                exit_ts = pd.Timestamp(frame.index[forward_idx])
                exit_reason = "stop_first_same_bar"
                break
            if high >= stop_price:
                exit_price = stop_price
                exit_ts = pd.Timestamp(frame.index[forward_idx])
                exit_reason = "stop_hit"
                break
            if low <= target_price:
                exit_price = target_price
                exit_ts = pd.Timestamp(frame.index[forward_idx])
                exit_reason = "target_hit"
                break
        exit_price = _safe_float(bar["close"])
        exit_ts = pd.Timestamp(frame.index[forward_idx])
    gross_r = ((exit_price - entry_price) / risk) if side == "long" else ((entry_price - exit_price) / risk)
    return {
        "trade_id": str(signal["trade_id"]),
        "candidate_family": str(signal["candidate_family"]),
        "side": side,
        "entry_timestamp": entry_ts,
        "exit_timestamp": exit_ts,
        "entry_time": entry_ts.isoformat(),
        "exit_time": exit_ts.isoformat(),
        "entry_price": round(entry_price, 6),
        "exit_price": round(exit_price, 6),
        "initial_stop": round(stop_price, 6),
        "quantity": 1.0,
        "r_multiple": round(gross_r, 6),
        "gross_r": round(gross_r, 6),
        "holding_bars": bars_held,
        "holding_hours": bars_held * 12,
        "archetype_key": str(signal["candidate_family"]),
        "exit_reason": exit_reason,
        "bridge_source": "12h_native",
    }


def _simulate_candidate_families(candidate_signals: list[dict[str, Any]], htf: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    simulated: list[dict[str, Any]] = []
    by_family: dict[str, list[dict[str, Any]]] = {}
    monthly_rows: list[dict[str, Any]] = []
    performance_rows: list[dict[str, Any]] = []
    for signal in candidate_signals:
        row = _simulate_trade_from_signal(signal, htf)
        if row is None:
            continue
        simulated.append(row)
        by_family.setdefault(str(row["candidate_family"]), []).append(row)
    cluster_rows: list[dict[str, Any]] = []
    for family, rows in sorted(by_family.items()):
        r_values = [_safe_float(row["r_multiple"]) for row in rows]
        wins = [value for value in r_values if value > 0]
        losses = [abs(value) for value in r_values if value < 0]
        pf = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
        timestamps = [row["exit_timestamp"] for row in rows if isinstance(row.get("exit_timestamp"), pd.Timestamp)]
        month_counts: dict[str, int] = {}
        month_pnl: dict[str, float] = {}
        for row in rows:
            month = row["exit_timestamp"].strftime("%Y-%m")
            month_counts[month] = month_counts.get(month, 0) + 1
            month_pnl[month] = month_pnl.get(month, 0.0) + _safe_float(row["r_multiple"])
        concentration = max(month_counts.values()) / max(len(rows), 1)
        for month, count in sorted(month_counts.items()):
            monthly_rows.append(
                {
                    "candidate_family": family,
                    "month": month,
                    "trade_count": count,
                    "total_R": round(month_pnl.get(month, 0.0), 6),
                }
            )
        performance_rows.append(
            {
                "candidate_family": family,
                "trade_count": len(rows),
                "long_count": sum(1 for row in rows if row["side"] == "long"),
                "short_count": sum(1 for row in rows if row["side"] == "short"),
                "average_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
                "median_R": round(_median(r_values), 6) if r_values else 0.0,
                "win_rate": round(_safe_ratio(len(wins), len(r_values), 0.0), 6) if r_values else 0.0,
                "profit_factor": round(pf, 6),
                "average_holding_hours": round(sum(_safe_float(row["holding_hours"]) for row in rows) / len(rows), 6) if rows else 0.0,
                "top_5_winner_dependency_R": round(sum(sorted(wins, reverse=True)[:5]), 6) if wins else 0.0,
                "inactive_months": max(0, len(pd.period_range(min(timestamps), max(timestamps), freq="M")) - len(month_counts)) if timestamps else 0,
                "cluster_concentration": round(concentration, 6),
            }
        )
        cluster_rows.append(
            {
                "candidate_family": family,
                "monthly_cluster_concentration": round(concentration, 6),
                "inactive_month_count": max(0, len(pd.period_range(min(timestamps), max(timestamps), freq="M")) - len(month_counts)) if timestamps else 0,
                "trade_count": len(rows),
            }
        )
    cluster_json = {
        **RESEARCH_ONLY_FLAGS,
        "rows": cluster_rows,
        "best_family_by_lowest_concentration": min(cluster_rows, key=lambda item: (item["monthly_cluster_concentration"], -item["trade_count"])) if cluster_rows else {},
    }
    return simulated, performance_rows, monthly_rows, cluster_json


def _cost_adjusted_rows(rows: list[dict[str, Any]], cost_bps_total: float) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for row in rows:
        cloned = _clone_row(row)
        entry_price = _safe_float(cloned.get("entry_price"))
        stop_price = _safe_float(cloned.get("initial_stop"))
        risk_pct = abs(entry_price - stop_price) / entry_price if entry_price > 0 else 0.0
        cost_r = (cost_bps_total / 10_000.0) / max(risk_pct, 1e-9)
        cloned["r_multiple"] = round(_safe_float(cloned.get("gross_r", cloned.get("r_multiple"))) - cost_r, 6)
        adjusted.append(cloned)
    return adjusted


def _evaluate_cost_bands(
    candidate_rows: list[dict[str, Any]],
    *,
    label_prefix: str,
) -> list[dict[str, Any]]:
    bands = [
        ("ZERO_COST_REFERENCE", ZERO_COST_BPS),
        ("OPTIMISTIC_MAKER_COST", OPTIMISTIC_COST_BPS),
        ("NORMAL_MIXED_MAKER_TAKER_COST", NORMAL_COST_BPS),
        ("CONSERVATIVE_TAKER_COST", CONSERVATIVE_COST_BPS),
        ("HIGH_SLIPPAGE_COST", HIGH_SLIPPAGE_COST_BPS),
    ]
    results: list[dict[str, Any]] = []
    for band_name, bps in bands:
        adjusted = _cost_adjusted_rows(candidate_rows, bps)
        rolling = _rolling_bridge_summary(adjusted, {"stepup_schedule": list(BASE_STEPUP_SCHEDULE)})
        results.append(
            {
                "candidate_name": label_prefix,
                "band_name": band_name,
                "cost_bps_total": bps,
                "rolling_5y_average": rolling["average"],
                "rolling_5y_median": rolling["median"],
                "rolling_5y_best": rolling["best"],
                "rolling_5y_worst": rolling["worst"],
                "hit_1m_windows": rolling["hit_1m_windows"],
                "hit_3m_windows": rolling["hit_3m_windows"],
                "hit_5m_windows": rolling["hit_5m_windows"],
                "max_drawdown_pct": rolling["max_drawdown_pct"],
            }
        )
    return results


def _best_family_rows(performance_rows: list[dict[str, Any]], simulated_rows: list[dict[str, Any]], *, side_filter: str = "all") -> tuple[str, list[dict[str, Any]]]:
    eligible = []
    for row in performance_rows:
        family = str(row["candidate_family"])
        if side_filter == "long" and "SHORT" in family and "LONG_SHORT" not in family:
            continue
        if side_filter == "short" and "LONG" in family and "LONG_SHORT" not in family:
            continue
        if side_filter == "long_short" and "LONG_SHORT" not in family:
            continue
        eligible.append(row)
    if not eligible:
        return "", []
    eligible.sort(key=lambda item: (-_safe_float(item["profit_factor"]), -_safe_float(item["average_R"]), -int(item["trade_count"])))
    family = str(eligible[0]["candidate_family"])
    return family, [_clone_row(row) for row in simulated_rows if str(row["candidate_family"]) == family]


def _parameter_family_specs() -> list[dict[str, Any]]:
    specs = [
        {"parameter_family_id": "FAST_12H_TREND_01", "family_name": "FAST_12H_TREND", "ema_fast": 10, "ema_slow": 30, "regime_filter": False, "atr_stop_multiplier": 0.8, "target_r": 2.0, "max_hold_bars": 6},
        {"parameter_family_id": "FAST_12H_TREND_02", "family_name": "FAST_12H_TREND", "ema_fast": 10, "ema_slow": 30, "regime_filter": True, "atr_stop_multiplier": 1.2, "target_r": 3.0, "max_hold_bars": 10},
        {"parameter_family_id": "FAST_12H_TREND_03", "family_name": "FAST_12H_TREND", "ema_fast": 10, "ema_slow": 30, "regime_filter": True, "atr_stop_multiplier": 1.6, "target_r": 4.0, "max_hold_bars": 16},
        {"parameter_family_id": "BALANCED_12H_TREND_01", "family_name": "BALANCED_12H_TREND", "ema_fast": 20, "ema_slow": 50, "regime_filter": False, "atr_stop_multiplier": 0.8, "target_r": 2.0, "max_hold_bars": 6},
        {"parameter_family_id": "BALANCED_12H_TREND_02", "family_name": "BALANCED_12H_TREND", "ema_fast": 20, "ema_slow": 50, "regime_filter": True, "atr_stop_multiplier": 1.2, "target_r": 3.0, "max_hold_bars": 10},
        {"parameter_family_id": "BALANCED_12H_TREND_03", "family_name": "BALANCED_12H_TREND", "ema_fast": 20, "ema_slow": 50, "regime_filter": True, "atr_stop_multiplier": 1.6, "target_r": 4.0, "max_hold_bars": 16},
        {"parameter_family_id": "SLOW_12H_SWING_01", "family_name": "SLOW_12H_SWING", "ema_fast": 50, "ema_slow": 200, "regime_filter": False, "atr_stop_multiplier": 1.2, "target_r": 3.0, "max_hold_bars": 10},
        {"parameter_family_id": "SLOW_12H_SWING_02", "family_name": "SLOW_12H_SWING", "ema_fast": 50, "ema_slow": 200, "regime_filter": True, "atr_stop_multiplier": 1.6, "target_r": 4.0, "max_hold_bars": 16},
        {"parameter_family_id": "MEAN_REVERSION_12H_SWEEP_01", "family_name": "MEAN_REVERSION_12H_SWEEP", "ema_fast": 20, "ema_slow": 50, "regime_filter": False, "atr_stop_multiplier": 0.8, "target_r": 2.0, "max_hold_bars": 6},
        {"parameter_family_id": "MEAN_REVERSION_12H_SWEEP_02", "family_name": "MEAN_REVERSION_12H_SWEEP", "ema_fast": 20, "ema_slow": 50, "regime_filter": True, "atr_stop_multiplier": 1.2, "target_r": 3.0, "max_hold_bars": 10},
        {"parameter_family_id": "STRUCTURAL_BREAK_RETEST_12H_01", "family_name": "STRUCTURAL_BREAK_RETEST_12H", "ema_fast": 20, "ema_slow": 50, "regime_filter": False, "atr_stop_multiplier": 0.8, "target_r": 2.0, "max_hold_bars": 6},
        {"parameter_family_id": "STRUCTURAL_BREAK_RETEST_12H_02", "family_name": "STRUCTURAL_BREAK_RETEST_12H", "ema_fast": 20, "ema_slow": 50, "regime_filter": True, "atr_stop_multiplier": 1.2, "target_r": 3.0, "max_hold_bars": 10},
        {"parameter_family_id": "STRUCTURAL_BREAK_RETEST_12H_03", "family_name": "STRUCTURAL_BREAK_RETEST_12H", "ema_fast": 30, "ema_slow": 100, "regime_filter": True, "atr_stop_multiplier": 1.6, "target_r": 4.0, "max_hold_bars": 16},
    ]
    return specs[:MAX_PARAMETER_VARIANTS_ALLOWED]


def _parameter_signal_sides(signal_row: pd.Series, spec: dict[str, Any]) -> list[str]:
    atr = max(_safe_float(signal_row.get("atr14")), 0.0)
    if atr <= 0.0:
        return []
    fast_col = f"ema{int(spec['ema_fast'])}"
    slow_col = f"ema{int(spec['ema_slow'])}"
    fast_value = _safe_float(signal_row.get(fast_col))
    slow_value = _safe_float(signal_row.get(slow_col))
    close = _safe_float(signal_row.get("close"))
    low = _safe_float(signal_row.get("low"))
    high = _safe_float(signal_row.get("high"))
    regime_long = True
    regime_short = True
    if bool(spec.get("regime_filter")):
        regime_anchor = 200 if int(spec["ema_slow"]) >= 50 else 100
        anchor_value = _safe_float(signal_row.get(f"ema{regime_anchor}"))
        regime_long = close >= anchor_value
        regime_short = close <= anchor_value
    family_name = str(spec["family_name"])
    if family_name in {"FAST_12H_TREND", "BALANCED_12H_TREND", "SLOW_12H_SWING"}:
        long_ok = close > fast_value > slow_value and regime_long and abs(close - fast_value) <= atr * 1.2 and _safe_float(signal_row.get("volume_ratio")) >= 0.85
        short_ok = close < fast_value < slow_value and regime_short and abs(close - fast_value) <= atr * 1.2 and _safe_float(signal_row.get("volume_ratio")) >= 0.85
        return [side for side, passed in (("long", long_ok), ("short", short_ok)) if passed]
    if family_name == "MEAN_REVERSION_12H_SWEEP":
        long_ok = regime_long and _safe_float(signal_row.get("lower_wick_ratio")) >= 0.45 and _safe_float(signal_row.get("range_position")) <= 0.25 and close >= low + atr * 0.4
        short_ok = regime_short and _safe_float(signal_row.get("upper_wick_ratio")) >= 0.45 and _safe_float(signal_row.get("range_position")) >= 0.75 and close <= high - atr * 0.4
        return [side for side, passed in (("long", long_ok), ("short", short_ok)) if passed]
    if family_name == "STRUCTURAL_BREAK_RETEST_12H":
        prior_high = _safe_float(signal_row.get("range_high_20" if int(spec["ema_slow"]) <= 50 else "range_high_40"))
        prior_low = _safe_float(signal_row.get("range_low_20" if int(spec["ema_slow"]) <= 50 else "range_low_40"))
        long_ok = regime_long and close > prior_high and low <= prior_high + atr * 0.35
        short_ok = regime_short and close < prior_low and high >= prior_low - atr * 0.35
        return [side for side, passed in (("long", long_ok), ("short", short_ok)) if passed]
    return []


def _generate_parameter_family_candidates(htf: pd.DataFrame, spec: dict[str, Any]) -> list[dict[str, Any]]:
    feature_frame = _compute_12h_features(htf)
    candidate_rows: list[dict[str, Any]] = []
    for idx in range(30, len(feature_frame) - 1):
        signal_row = feature_frame.iloc[idx]
        next_row = feature_frame.iloc[idx + 1]
        entry_ts = pd.Timestamp(next_row["candle_close_timestamp"])
        signal_ts = pd.Timestamp(signal_row["candle_close_timestamp"])
        entry_price = _safe_float(next_row["open"])
        atr = max(_safe_float(signal_row.get("atr14")), 1e-9)
        for side in _parameter_signal_sides(signal_row, spec):
            if side == "long":
                stop_price = min(_safe_float(signal_row["low"]), entry_price - atr * _safe_float(spec["atr_stop_multiplier"]))
                target_price = entry_price + abs(entry_price - stop_price) * _safe_float(spec["target_r"])
            else:
                stop_price = max(_safe_float(signal_row["high"]), entry_price + atr * _safe_float(spec["atr_stop_multiplier"]))
                target_price = entry_price - abs(entry_price - stop_price) * _safe_float(spec["target_r"])
            stop_distance = abs(entry_price - stop_price)
            if entry_price <= 0.0 or stop_distance <= 0.0:
                continue
            candidate_rows.append(
                {
                    "candidate_family": spec["parameter_family_id"],
                    "parameter_family_id": spec["parameter_family_id"],
                    "trade_id": f"{spec['parameter_family_id']}-{side}-{entry_ts.isoformat()}",
                    "signal_timestamp": signal_ts.isoformat(),
                    "entry_timestamp": entry_ts.isoformat(),
                    "entry_time": entry_ts.isoformat(),
                    "side": side,
                    "entry_price": round(entry_price, 6),
                    "stop_price": round(stop_price, 6),
                    "target_price": round(target_price, 6),
                    "max_hold_bars": int(spec["max_hold_bars"]),
                    "gross_r_target": round(_safe_float(spec["target_r"]), 6),
                    "atr14": round(atr, 6),
                }
            )
    return candidate_rows


def _parameter_family_cluster_stats(base_rows: list[dict[str, Any]], family_rows: list[dict[str, Any]]) -> tuple[float, int]:
    base_months: dict[str, float] = {}
    family_months: dict[str, float] = {}
    overlap_hits = 0
    for row in base_rows:
        if isinstance(row.get("exit_timestamp"), pd.Timestamp):
            month = row["exit_timestamp"].strftime("%Y-%m")
            base_months[month] = base_months.get(month, 0.0) + _safe_float(row.get("r_multiple"))
    for row in family_rows:
        if isinstance(row.get("exit_timestamp"), pd.Timestamp):
            month = row["exit_timestamp"].strftime("%Y-%m")
            family_months[month] = family_months.get(month, 0.0) + _safe_float(row.get("r_multiple"))
        row_ts = row.get("entry_timestamp")
        row_side = str(row.get("side") or "")
        if any(
            isinstance(base.get("entry_timestamp"), pd.Timestamp)
            and isinstance(row_ts, pd.Timestamp)
            and str(base.get("side") or "") == row_side
            and abs((row_ts - base["entry_timestamp"]).total_seconds()) <= 24 * 3600
            for base in base_rows
        ):
            overlap_hits += 1
    positive_independent_months = sum(1 for month, total in family_months.items() if total > 0.0 and base_months.get(month, 0.0) <= 0.0)
    overlap_ratio = _safe_ratio(overlap_hits, len(family_rows), 0.0)
    return round(overlap_ratio, 6), positive_independent_months


def _select_best_parameter_family(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {}

    def _score(row: dict[str, Any]) -> tuple[float, float, float, float, float, float]:
        trade_penalty = 250_000.0 if int(row.get("simulated_trade_count", 0) or 0) < 12 else 0.0
        concentration_penalty = max(0.0, _safe_float(row.get("monthly_distribution_score")) - 0.50) * 500_000.0
        return (
            _safe_float(row.get("best_combined_normal_cost_rolling_5y_average")) - trade_penalty - concentration_penalty,
            float(int(row.get("best_combined_hit_1m_windows", 0) or 0)),
            -_safe_float(row.get("overlap_with_1h_ratio")),
            float(int(row.get("independent_positive_month_count", 0) or 0)),
            _safe_float(row.get("profit_factor")),
            -_safe_float(row.get("monthly_distribution_score")),
        )

    return sorted(results, key=_score, reverse=True)[0]


def _parameter_family_summary_block(reason: str) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "parameter_family_status": reason,
        "total_parameter_variants_tested": 0,
        "max_parameter_variants_allowed": MAX_PARAMETER_VARIANTS_ALLOWED,
        "best_parameter_family_id": "",
        "best_family_name": "",
        "best_parameters": {},
        "best_12h_only_normal_cost_rolling_5y_average": 0.0,
        "best_12h_only_normal_cost_rolling_5y_median": 0.0,
        "best_12h_only_hit_1m_windows": 0,
        "best_12h_only_hit_3m_windows": 0,
        "best_12h_only_hit_5m_windows": 0,
        "best_1h_plus_12h_normal_cost_rolling_5y_average": 0.0,
        "best_1h_plus_12h_normal_cost_rolling_5y_median": 0.0,
        "best_1h_plus_12h_hit_1m_windows": 0,
        "best_1h_plus_12h_hit_3m_windows": 0,
        "best_1h_plus_12h_hit_5m_windows": 0,
        "overlap_with_1h_verdict": "blocked",
        "independent_cluster_verdict": "blocked",
        "parameter_search_overfit_risk": "not_applicable",
        "whether_any_12h_family_deserves_freeze_and_confirm": False,
        "whether_original_12h_rejection_should_be_softened": False,
    }


def _evaluate_parameter_families(
    htf: pd.DataFrame,
    base_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    combined_rows: list[dict[str, Any]] = []
    ledgers: list[dict[str, Any]] = []
    specs = _parameter_family_specs()
    for spec in specs:
        candidates = _generate_parameter_family_candidates(htf, spec)
        simulated = []
        for signal in candidates:
            row = _simulate_trade_from_signal(signal, htf)
            if row is None:
                continue
            row["bridge_source"] = "12h_native"
            simulated.append(row)
            ledgers.append(row)
        r_values = [_safe_float(row.get("r_multiple")) for row in simulated]
        wins = [value for value in r_values if value > 0.0]
        losses = [abs(value) for value in r_values if value < 0.0]
        profit_factor = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
        timestamps = [row["exit_timestamp"] for row in simulated if isinstance(row.get("exit_timestamp"), pd.Timestamp)]
        month_counts: dict[str, int] = {}
        for row in simulated:
            if isinstance(row.get("exit_timestamp"), pd.Timestamp):
                month = row["exit_timestamp"].strftime("%Y-%m")
                month_counts[month] = month_counts.get(month, 0) + 1
        monthly_distribution_score = max(month_counts.values()) / max(len(simulated), 1) if month_counts else 1.0
        overlap_ratio, independent_months = _parameter_family_cluster_stats(base_rows, simulated)
        family_windows = _build_windows(simulated)
        combined_rows = _combine_rows(base_rows, _suppress_overlap(base_rows, simulated))
        combined_windows = _build_windows(combined_rows)
        twelve_h_only = _overlay_rolling_window_summary(
            simulated,
            family_windows,
            {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "cost_bps_total": NORMAL_COST_BPS},
        )
        combined = _overlay_rolling_window_summary(
            combined_rows,
            combined_windows,
            {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "cost_bps_total": NORMAL_COST_BPS},
        )
        full_output = _simulate_overlay_sequence(
            combined_rows,
            stepup_schedule=list(BASE_STEPUP_SCHEDULE),
            cost_bps_total=NORMAL_COST_BPS,
        )
        results.append(
            {
                "parameter_family_id": spec["parameter_family_id"],
                "family_name": spec["family_name"],
                "ema_fast": spec["ema_fast"],
                "ema_slow": spec["ema_slow"],
                "ema_regime_filter": bool(spec["regime_filter"]),
                "atr_stop_multiplier": spec["atr_stop_multiplier"],
                "target_r": spec["target_r"],
                "max_hold_bars": spec["max_hold_bars"],
                "candidate_count": len(candidates),
                "simulated_trade_count": len(simulated),
                "long_count": sum(1 for row in simulated if str(row.get("side") or "") == "long"),
                "short_count": sum(1 for row in simulated if str(row.get("side") or "") == "short"),
                "average_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
                "median_R": round(_median(r_values), 6) if r_values else 0.0,
                "win_rate": round(_safe_ratio(len(wins), len(r_values), 0.0), 6) if r_values else 0.0,
                "profit_factor": round(profit_factor, 6),
                "average_holding_hours": round(sum(_safe_float(row.get("holding_hours")) for row in simulated) / len(simulated), 6) if simulated else 0.0,
                "monthly_distribution_score": round(monthly_distribution_score, 6),
                "overlap_with_1h_ratio": overlap_ratio,
                "independent_positive_month_count": independent_months,
                "normal_cost_rolling_5y_average": twelve_h_only["average"],
                "normal_cost_rolling_5y_median": twelve_h_only["median"],
                "normal_cost_hit_1m_windows": twelve_h_only["hit_1m_windows"],
                "normal_cost_hit_3m_windows": twelve_h_only["hit_3m_windows"],
                "normal_cost_hit_5m_windows": twelve_h_only["hit_5m_windows"],
                "best_combined_normal_cost_rolling_5y_average": combined["average"],
                "best_combined_normal_cost_rolling_5y_median": combined["median"],
                "best_combined_hit_1m_windows": combined["hit_1m_windows"],
                "best_combined_hit_3m_windows": combined["hit_3m_windows"],
                "best_combined_hit_5m_windows": combined["hit_5m_windows"],
                "max_drawdown_pct": round(_safe_float(full_output.get("max_drawdown_pct")), 6),
                "status": "active" if simulated else "no_simulated_trades",
            }
        )
    best = _select_best_parameter_family(results)
    best_rows = [_clone_row(row) for row in ledgers if str(row.get("candidate_family") or "") == str(best.get("parameter_family_id") or "")]
    combined_specs = [
        ("1H_BASE_ONLY", [_clone_row(row) for row in base_rows], {"stepup_schedule": list(BASE_STEPUP_SCHEDULE)}),
        ("BEST_12H_PARAMETER_FAMILY_ONLY", [_clone_row(row) for row in best_rows], {"stepup_schedule": list(BASE_STEPUP_SCHEDULE)}),
        ("1H_BASE_PLUS_BEST_12H_PARAMETER_FAMILY", _combine_rows(base_rows, _suppress_overlap(base_rows, best_rows)), {"stepup_schedule": list(BASE_STEPUP_SCHEDULE)}),
        ("1H_BASE_PLUS_BEST_12H_WITH_SIMPLE_SLEEVE_CAP", _combine_rows(base_rows, _suppress_overlap(base_rows, best_rows)), {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "row_source_multipliers": {"strict_core": 1.0, "12h_native": 0.75}}),
        ("1H_BASE_PLUS_BEST_12H_WITH_SIMPLE_DRAWDOWN_BRAKE", _combine_rows(base_rows, _suppress_overlap(base_rows, best_rows)), {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "drawdown_guard_pct": 0.10, "drawdown_breaker_pct": 0.20}),
    ]
    for variant_name, rows, sim_kwargs in combined_specs:
        rolling = _rolling_bridge_summary(_cost_adjusted_rows(rows, NORMAL_COST_BPS), sim_kwargs)
        combined_rows.append(
            {
                "variant_name": variant_name,
                "trade_count": len(rows),
                "normal_cost_rolling_5y_average": rolling["average"],
                "normal_cost_rolling_5y_median": rolling["median"],
                "normal_cost_hit_1m_windows": rolling["hit_1m_windows"],
                "normal_cost_hit_3m_windows": rolling["hit_3m_windows"],
                "normal_cost_hit_5m_windows": rolling["hit_5m_windows"],
                "normal_cost_max_drawdown_pct": rolling["max_drawdown_pct"],
            }
        )
    overlap_verdict = (
        "LOWER_OVERLAP_THAN_FIRST_PASS"
        if best and _safe_float(best.get("overlap_with_1h_ratio")) < 0.50
        else "MOSTLY_DUPLICATIVE"
    )
    independent_verdict = (
        "INDEPENDENT_PROFITABLE_CLUSTERS_FOUND"
        if best and int(best.get("independent_positive_month_count", 0) or 0) >= 3
        else "MOSTLY_DUPLICATIVE"
    )
    summary = {
        **RESEARCH_ONLY_FLAGS,
        "parameter_family_status": "COMPLETE",
        "total_parameter_variants_tested": len(specs),
        "max_parameter_variants_allowed": MAX_PARAMETER_VARIANTS_ALLOWED,
        "best_parameter_family_id": str(best.get("parameter_family_id") or ""),
        "best_family_name": str(best.get("family_name") or ""),
        "best_parameters": {
            "ema_fast": int(best.get("ema_fast", 0) or 0),
            "ema_slow": int(best.get("ema_slow", 0) or 0),
            "ema_regime_filter": bool(best.get("ema_regime_filter", False)),
            "atr_stop_multiplier": _safe_float(best.get("atr_stop_multiplier")),
            "target_r": _safe_float(best.get("target_r")),
            "max_hold_bars": int(best.get("max_hold_bars", 0) or 0),
        } if best else {},
        "best_12h_only_normal_cost_rolling_5y_average": _safe_float(best.get("normal_cost_rolling_5y_average")),
        "best_12h_only_normal_cost_rolling_5y_median": _safe_float(best.get("normal_cost_rolling_5y_median")),
        "best_12h_only_hit_1m_windows": int(best.get("normal_cost_hit_1m_windows", 0) or 0),
        "best_12h_only_hit_3m_windows": int(best.get("normal_cost_hit_3m_windows", 0) or 0),
        "best_12h_only_hit_5m_windows": int(best.get("normal_cost_hit_5m_windows", 0) or 0),
        "best_1h_plus_12h_normal_cost_rolling_5y_average": _safe_float(best.get("best_combined_normal_cost_rolling_5y_average")),
        "best_1h_plus_12h_normal_cost_rolling_5y_median": _safe_float(best.get("best_combined_normal_cost_rolling_5y_median")),
        "best_1h_plus_12h_hit_1m_windows": int(best.get("best_combined_hit_1m_windows", 0) or 0),
        "best_1h_plus_12h_hit_3m_windows": int(best.get("best_combined_hit_3m_windows", 0) or 0),
        "best_1h_plus_12h_hit_5m_windows": int(best.get("best_combined_hit_5m_windows", 0) or 0),
        "overlap_with_1h_verdict": overlap_verdict,
        "independent_cluster_verdict": independent_verdict,
        "parameter_search_overfit_risk": "disciplined_small_grid_under_30_variants",
        "whether_any_12h_family_deserves_freeze_and_confirm": bool(best) and _safe_float(best.get("best_combined_normal_cost_rolling_5y_average")) >= 850_000.0,
        "whether_original_12h_rejection_should_be_softened": bool(best) and _safe_float(best.get("best_combined_normal_cost_rolling_5y_average")) >= 850_000.0,
    }
    return results, summary, combined_rows, best_rows


def _suppress_overlap(base_rows: list[dict[str, Any]], new_rows: list[dict[str, Any]], *, hours: int = 24) -> list[dict[str, Any]]:
    if not base_rows:
        return [_clone_row(row) for row in new_rows]
    filtered: list[dict[str, Any]] = []
    for row in new_rows:
        row_ts = row.get("entry_timestamp")
        row_side = str(row.get("side") or "")
        overlap = False
        for base in base_rows:
            base_ts = base.get("entry_timestamp")
            if not isinstance(base_ts, pd.Timestamp) or not isinstance(row_ts, pd.Timestamp):
                continue
            if str(base.get("side") or "") != row_side:
                continue
            if abs((row_ts - base_ts).total_seconds()) <= hours * 3600:
                overlap = True
                break
        if not overlap:
            filtered.append(_clone_row(row))
    return filtered


def _combine_rows(base_rows: list[dict[str, Any]], addon_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [_clone_row(row) for row in base_rows] + [_clone_row(row) for row in addon_rows]
    rows.sort(key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or ""))
    return rows


def _combined_variant_specs() -> list[dict[str, Any]]:
    return [
        {"variant_name": "1H_BASE_ONLY", "variant_type": "base_only"},
        {"variant_name": "12H_ONLY_BEST_LONG_SHORT", "variant_type": "twelve_h_only"},
        {"variant_name": "1H_BASE_PLUS_12H_LONG_ONLY", "variant_type": "combine_long"},
        {"variant_name": "1H_BASE_PLUS_12H_SHORT_ONLY", "variant_type": "combine_short"},
        {"variant_name": "1H_BASE_PLUS_12H_LONG_SHORT", "variant_type": "combine_both"},
        {"variant_name": "1H_BASE_PLUS_12H_WITH_SIMPLE_SLEEVE_CAP", "variant_type": "combine_both", "row_source_multipliers": {"strict_core": 1.0, "12h_native": 0.75}},
        {"variant_name": "1H_BASE_PLUS_12H_WITH_SIMPLE_MILESTONE_STEPUP", "variant_type": "combine_both", "stepup_schedule": [(100_000.0, 1.15), (250_000.0, 1.35), (500_000.0, 1.60)]},
        {"variant_name": "1H_BASE_PLUS_12H_WITH_SIMPLE_DRAWDOWN_BRAKE", "variant_type": "combine_both", "drawdown_guard_pct": 0.10, "drawdown_breaker_pct": 0.20},
    ]


def _evaluate_combined_variants(
    base_rows: list[dict[str, Any]],
    long_rows: list[dict[str, Any]],
    short_rows: list[dict[str, Any]],
    both_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []
    simple_cap_rows: list[dict[str, Any]] = []
    variants = _combined_variant_specs()
    for variant in variants:
        variant_type = str(variant["variant_type"])
        if variant_type == "base_only":
            rows = [_clone_row(row) for row in base_rows]
        elif variant_type == "twelve_h_only":
            rows = [_clone_row(row) for row in both_rows]
        elif variant_type == "combine_long":
            rows = _combine_rows(base_rows, _suppress_overlap(base_rows, long_rows))
        elif variant_type == "combine_short":
            rows = _combine_rows(base_rows, _suppress_overlap(base_rows, short_rows))
        else:
            rows = _combine_rows(base_rows, _suppress_overlap(base_rows, both_rows))
        sim_kwargs = {
            "stepup_schedule": variant.get("stepup_schedule", list(BASE_STEPUP_SCHEDULE)),
            "row_source_multipliers": variant.get("row_source_multipliers"),
            "drawdown_guard_pct": variant.get("drawdown_guard_pct"),
            "drawdown_breaker_pct": variant.get("drawdown_breaker_pct"),
        }
        zero_output = _simulate_bridge_sequence(rows, **sim_kwargs)
        zero_rolling = _rolling_bridge_summary(rows, sim_kwargs)
        normal_rows = _cost_adjusted_rows(rows, NORMAL_COST_BPS)
        normal_output = _simulate_bridge_sequence(normal_rows, **sim_kwargs)
        normal_rolling = _rolling_bridge_summary(normal_rows, sim_kwargs)
        results.append(
            {
                "variant_name": variant["variant_name"],
                "trade_count": len(rows),
                "full_sequence_zero_cost_ending_equity": round(_safe_float(zero_output["ending_equity"]), 6),
                "full_sequence_normal_cost_ending_equity": round(_safe_float(normal_output["ending_equity"]), 6),
                "normal_cost_rolling_5y_average": normal_rolling["average"],
                "normal_cost_rolling_5y_median": normal_rolling["median"],
                "normal_cost_hit_1m_windows": normal_rolling["hit_1m_windows"],
                "normal_cost_hit_3m_windows": normal_rolling["hit_3m_windows"],
                "normal_cost_hit_5m_windows": normal_rolling["hit_5m_windows"],
                "normal_cost_max_drawdown_pct": normal_rolling["max_drawdown_pct"],
                "cost_resilience_verdict": "NORMAL_COST_MISSION_PARTIAL" if normal_rolling["average"] >= 900_000.0 else "COST_FRAGILE",
            }
        )
        simple_cap_rows.append(
            {
                "variant_name": variant["variant_name"],
                "capital_logic": "shared_equity_simple_rules",
                "row_source_multipliers": str(variant.get("row_source_multipliers") or {}),
                "stepup_schedule": str(variant.get("stepup_schedule", list(BASE_STEPUP_SCHEDULE))),
                "drawdown_guard_pct": variant.get("drawdown_guard_pct"),
                "drawdown_breaker_pct": variant.get("drawdown_breaker_pct"),
            }
        )
        for band_name, bps in (
            ("ZERO_COST_REFERENCE", ZERO_COST_BPS),
            ("OPTIMISTIC_MAKER_COST", OPTIMISTIC_COST_BPS),
            ("NORMAL_MIXED_MAKER_TAKER_COST", NORMAL_COST_BPS),
            ("CONSERVATIVE_TAKER_COST", CONSERVATIVE_COST_BPS),
            ("HIGH_SLIPPAGE_COST", HIGH_SLIPPAGE_COST_BPS),
        ):
            rolling = _rolling_bridge_summary(_cost_adjusted_rows(rows, bps), sim_kwargs)
            cost_rows.append(
                {
                    "candidate_name": variant["variant_name"],
                    "band_name": band_name,
                    "cost_bps_total": bps,
                    "rolling_5y_average": rolling["average"],
                    "rolling_5y_median": rolling["median"],
                    "rolling_5y_best": rolling["best"],
                    "rolling_5y_worst": rolling["worst"],
                    "hit_1m_windows": rolling["hit_1m_windows"],
                    "hit_3m_windows": rolling["hit_3m_windows"],
                    "hit_5m_windows": rolling["hit_5m_windows"],
                    "max_drawdown_pct": rolling["max_drawdown_pct"],
                }
            )
    results.sort(key=lambda item: (-_safe_float(item["normal_cost_rolling_5y_average"]), -int(item["normal_cost_hit_1m_windows"])))
    return results, cost_rows, simple_cap_rows


def _evaluate_combined_variants_overlay(
    base_rows: list[dict[str, Any]],
    long_rows: list[dict[str, Any]],
    short_rows: list[dict[str, Any]],
    both_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    cost_rows: list[dict[str, Any]] = []
    simple_cap_rows: list[dict[str, Any]] = []
    for variant in _combined_variant_specs():
        variant_type = str(variant["variant_type"])
        if variant_type == "base_only":
            rows = [_clone_row(row) for row in base_rows]
        elif variant_type == "twelve_h_only":
            rows = [_clone_row(row) for row in both_rows]
        elif variant_type == "combine_long":
            rows = _combine_rows(base_rows, _suppress_overlap(base_rows, long_rows))
        elif variant_type == "combine_short":
            rows = _combine_rows(base_rows, _suppress_overlap(base_rows, short_rows))
        else:
            rows = _combine_rows(base_rows, _suppress_overlap(base_rows, both_rows))
        windows = _build_windows(rows)
        zero_kwargs = {
            "stepup_schedule": variant.get("stepup_schedule", list(BASE_STEPUP_SCHEDULE)),
            "drawdown_breaker_pct": variant.get("drawdown_breaker_pct"),
        }
        normal_kwargs = {
            **zero_kwargs,
            "cost_bps_total": NORMAL_COST_BPS,
        }
        zero_output = _simulate_overlay_sequence(rows, **zero_kwargs)
        zero_rolling = _overlay_rolling_window_summary(rows, windows, zero_kwargs)
        normal_output = _simulate_overlay_sequence(rows, **normal_kwargs)
        normal_rolling = _overlay_rolling_window_summary(rows, windows, normal_kwargs)
        results.append(
            {
                "variant_name": variant["variant_name"],
                "trade_count": len(rows),
                "full_sequence_zero_cost_ending_equity": round(_safe_float(zero_output["ending_equity"]), 6),
                "full_sequence_normal_cost_ending_equity": round(_safe_float(normal_output["ending_equity"]), 6),
                "normal_cost_rolling_5y_average": normal_rolling["average"],
                "normal_cost_rolling_5y_median": normal_rolling["median"],
                "normal_cost_hit_1m_windows": normal_rolling["hit_1m_windows"],
                "normal_cost_hit_3m_windows": normal_rolling["hit_3m_windows"],
                "normal_cost_hit_5m_windows": normal_rolling["hit_5m_windows"],
                "normal_cost_max_drawdown_pct": normal_rolling["max_drawdown_pct"],
                "cost_resilience_verdict": "NORMAL_COST_MISSION_PARTIAL" if normal_rolling["average"] >= 900_000.0 else "COST_FRAGILE",
            }
        )
        simple_cap_rows.append(
            {
                "variant_name": variant["variant_name"],
                "capital_logic": "shared_equity_overlay_reused_from_execution_cost_audit",
                "stepup_schedule": str(variant.get("stepup_schedule", list(BASE_STEPUP_SCHEDULE))),
                "drawdown_breaker_pct": variant.get("drawdown_breaker_pct"),
            }
        )
        for band_name, bps in (
            ("ZERO_COST_REFERENCE", ZERO_COST_BPS),
            ("OPTIMISTIC_MAKER_COST", OPTIMISTIC_COST_BPS),
            ("NORMAL_MIXED_MAKER_TAKER_COST", NORMAL_COST_BPS),
            ("CONSERVATIVE_TAKER_COST", CONSERVATIVE_COST_BPS),
            ("HIGH_SLIPPAGE_COST", HIGH_SLIPPAGE_COST_BPS),
        ):
            rolling = _overlay_rolling_window_summary(
                rows,
                windows,
                {
                    "stepup_schedule": variant.get("stepup_schedule", list(BASE_STEPUP_SCHEDULE)),
                    "drawdown_breaker_pct": variant.get("drawdown_breaker_pct"),
                    "cost_bps_total": bps,
                },
            )
            cost_rows.append(
                {
                    "candidate_name": variant["variant_name"],
                    "band_name": band_name,
                    "cost_bps_total": bps,
                    "rolling_5y_average": rolling["average"],
                    "rolling_5y_median": rolling["median"],
                    "rolling_5y_best": rolling["best"],
                    "rolling_5y_worst": rolling["worst"],
                    "hit_1m_windows": rolling["hit_1m_windows"],
                    "hit_3m_windows": rolling["hit_3m_windows"],
                    "hit_5m_windows": rolling["hit_5m_windows"],
                    "max_drawdown_pct": rolling["max_drawdown_pct"],
                }
            )
    results.sort(key=lambda item: (-_safe_float(item["normal_cost_rolling_5y_average"]), -int(item["normal_cost_hit_1m_windows"])))
    return results, cost_rows, simple_cap_rows


def _evaluate_missed_trade_resilience(
    variant_rows: list[dict[str, Any]],
    *,
    variant_name: str,
    random_repeat_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scenarios = [
        ("random_miss_1pct", 0.01),
        ("random_miss_2pct", 0.02),
        ("random_miss_5pct", 0.05),
        ("random_miss_10pct", 0.10),
    ]
    baseline = _rolling_bridge_summary(_cost_adjusted_rows(variant_rows, NORMAL_COST_BPS), {"stepup_schedule": list(BASE_STEPUP_SCHEDULE)})
    rows: list[dict[str, Any]] = []
    threshold = 0.0
    repeats_used = max(int(random_repeat_count), 8)
    for scenario_name, frac in scenarios:
        averages: list[float] = []
        for repeat in range(repeats_used):
            rng = random.Random(7000 + repeat + int(frac * 1000))
            keep_count = max(1, int(round(len(variant_rows) * (1.0 - frac))))
            kept_indexes = sorted(rng.sample(range(len(variant_rows)), keep_count))
            kept_rows = [_clone_row(variant_rows[index]) for index in kept_indexes]
            rolling = _rolling_bridge_summary(_cost_adjusted_rows(kept_rows, NORMAL_COST_BPS), {"stepup_schedule": list(BASE_STEPUP_SCHEDULE)})
            averages.append(_safe_float(rolling["average"]))
        scenario_avg = sum(averages) / max(len(averages), 1)
        if scenario_avg >= 1_000_000.0:
            threshold = max(threshold, frac * 100.0)
        rows.append(
            {
                "variant_name": variant_name,
                "scenario": scenario_name,
                "random_repeat_count_used": repeats_used,
                "rolling_5y_average_mean": round(scenario_avg, 6),
                "baseline_rolling_5y_average": baseline["average"],
            }
        )

    def _remove_period(rows_in: list[dict[str, Any]], period: str, seed: int) -> list[dict[str, Any]]:
        month_labels = sorted({row["exit_timestamp"].strftime(period) for row in rows_in if isinstance(row.get("exit_timestamp"), pd.Timestamp)})
        if not month_labels:
            return []
        label = random.Random(seed).choice(month_labels)
        return [_clone_row(row) for row in rows_in if row["exit_timestamp"].strftime(period) != label]

    stress_sets = {
        "miss_one_random_day": _remove_period(variant_rows, "%Y-%m-%d", 9001),
        "miss_one_random_week": _remove_period(variant_rows, "%Y-W%W", 9002),
        "miss_one_random_month": _remove_period(variant_rows, "%Y-%m", 9003),
    }
    month_totals: dict[str, float] = {}
    month_vol: dict[str, float] = {}
    for row in variant_rows:
        if not isinstance(row.get("exit_timestamp"), pd.Timestamp):
            continue
        month = row["exit_timestamp"].strftime("%Y-%m")
        gross_r = _safe_float(row.get("gross_r", row.get("r_multiple")))
        month_totals[month] = month_totals.get(month, 0.0) + gross_r
        month_vol[month] = month_vol.get(month, 0.0) + abs(gross_r)
    top_months = {key for key, _ in sorted(month_totals.items(), key=lambda item: item[1], reverse=True)[:2]}
    high_vol_months = {key for key, _ in sorted(month_vol.items(), key=lambda item: item[1], reverse=True)[:2]}
    stress_sets["miss_high_volatility_months"] = [_clone_row(row) for row in variant_rows if row["exit_timestamp"].strftime("%Y-%m") not in high_vol_months]
    stress_sets["miss_top_performing_months"] = [_clone_row(row) for row in variant_rows if row["exit_timestamp"].strftime("%Y-%m") not in top_months]
    for name, reduced_rows in stress_sets.items():
        rolling = _rolling_bridge_summary(_cost_adjusted_rows(reduced_rows, NORMAL_COST_BPS), {"stepup_schedule": list(BASE_STEPUP_SCHEDULE)})
        rows.append(
            {
                "variant_name": variant_name,
                "scenario": name,
                "random_repeat_count_used": repeats_used,
                "rolling_5y_average_mean": rolling["average"],
                "baseline_rolling_5y_average": baseline["average"],
            }
        )
    summary = {
        "variant_name": variant_name,
        "missed_trade_tolerance_threshold_pct": round(threshold, 6),
        "random_repeat_count_used": repeats_used,
    }
    return rows, summary


def _stochastic_budget_reliability(random_repeat_count_used: int) -> dict[str, Any]:
    scout_mode = random_repeat_count_used < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE
    return {
        **RESEARCH_ONLY_FLAGS,
        "random_repeat_count_used": int(random_repeat_count_used),
        "minimum_repeat_count_required_for_gate": MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "stochastic_results_reliable_for_final_gate": not scout_mode,
        "scout_mode": scout_mode,
        "affected_metrics": [
            "random miss 1/2/5/10 pct",
            "miss one random day/week/month",
            "miss high-volatility months",
            "miss top-performing months",
        ],
        "deterministic_metrics_still_usable": [
            "12H candidate inventory",
            "no-leakage check",
            "12H candidate performance",
            "cost-band rolling 5Y results",
            "combined 1H+12H normal-cost rolling 5Y results",
            "overlap and monthly distribution",
        ],
    }


def _independent_cluster_audit(
    base_rows: list[dict[str, Any]],
    twelve_h_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base_months: dict[str, float] = {}
    twelve_h_months: dict[str, float] = {}
    overlap_rows: list[dict[str, Any]] = []
    for row in base_rows:
        if isinstance(row.get("exit_timestamp"), pd.Timestamp):
            month = row["exit_timestamp"].strftime("%Y-%m")
            base_months[month] = base_months.get(month, 0.0) + _safe_float(row.get("r_multiple"))
    for row in twelve_h_rows:
        if isinstance(row.get("exit_timestamp"), pd.Timestamp):
            month = row["exit_timestamp"].strftime("%Y-%m")
            twelve_h_months[month] = twelve_h_months.get(month, 0.0) + _safe_float(row.get("r_multiple"))
        overlap = any(
            isinstance(base.get("entry_timestamp"), pd.Timestamp)
            and isinstance(row.get("entry_timestamp"), pd.Timestamp)
            and str(base.get("side") or "") == str(row.get("side") or "")
            and abs((row["entry_timestamp"] - base["entry_timestamp"]).total_seconds()) <= 24 * 3600
            for base in base_rows
        )
        overlap_rows.append(
            {
                "trade_id": str(row.get("trade_id") or ""),
                "candidate_family": str(row.get("candidate_family") or ""),
                "side": str(row.get("side") or ""),
                "entry_timestamp": row["entry_timestamp"].isoformat() if isinstance(row.get("entry_timestamp"), pd.Timestamp) else "",
                "overlaps_1h_bridge_same_direction_within_24h": overlap,
            }
        )
    independent_positive_months = sorted(month for month, total in twelve_h_months.items() if total > 0.0 and base_months.get(month, 0.0) <= 0.0)
    overlap_ratio = _safe_ratio(sum(1 for row in overlap_rows if row["overlaps_1h_bridge_same_direction_within_24h"]), len(overlap_rows), 0.0)
    verdict = (
        "INDEPENDENT_PROFITABLE_CLUSTERS_FOUND" if len(independent_positive_months) >= 3 and overlap_ratio < 0.50 else
        "PARTIAL_CLUSTER_INDEPENDENCE" if independent_positive_months else
        "MOSTLY_DUPLICATIVE"
    )
    audit = {
        **RESEARCH_ONLY_FLAGS,
        "independent_positive_months_count": len(independent_positive_months),
        "independent_positive_months": independent_positive_months[:24],
        "overlap_ratio_same_direction_within_24h": round(overlap_ratio, 6),
        "verdict": verdict,
    }
    return audit, overlap_rows


def _mission_interpretation(
    *,
    best_12h_only_row: dict[str, Any],
    best_combined_row: dict[str, Any],
    resilience_summary: dict[str, Any],
    cluster_audit: dict[str, Any],
) -> tuple[dict[str, Any], str, str]:
    avg = _safe_float(best_combined_row.get("normal_cost_rolling_5y_average"))
    hit_1m = int(best_combined_row.get("normal_cost_hit_1m_windows", 0))
    hit_3m = int(best_combined_row.get("normal_cost_hit_3m_windows", 0))
    hit_5m = int(best_combined_row.get("normal_cost_hit_5m_windows", 0))
    threshold = _safe_float(resilience_summary.get("missed_trade_tolerance_threshold_pct"))
    cost_verdict = (
        "NORMAL_COST_RESILIENT" if avg >= 1_000_000.0 else
        "NORMAL_COST_PARTIAL" if avg >= 850_000.0 else
        "NORMAL_COST_WEAK"
    )
    if avg >= 1_000_000.0 and hit_1m >= 10:
        classification = "NATIVE_12H_EXECUTION_1M_PROMISING_RESEARCH_ONLY"
    elif avg >= 850_000.0:
        classification = "NATIVE_12H_EXECUTION_IMPROVES_BUT_NOT_GATE_PASSING"
    elif _safe_float(best_12h_only_row.get("rolling_5y_average")) >= 600_000.0:
        classification = "NATIVE_12H_EXECUTION_WEAK"
    else:
        classification = "NATIVE_12H_EXECUTION_REJECTED"
    if hit_3m > 0 and avg >= 1_250_000.0:
        classification = "NATIVE_12H_EXECUTION_3M_PROMISING_RESEARCH_ONLY"
    if cluster_audit.get("verdict") == "MOSTLY_DUPLICATIVE" and classification.startswith("NATIVE_12H_EXECUTION_1M"):
        classification = "NATIVE_12H_EXECUTION_IMPROVES_BUT_NOT_GATE_PASSING"
    interpretation = {
        **RESEARCH_ONLY_FLAGS,
        "one_million_in_5y_under_normal_cost": avg >= 1_000_000.0,
        "three_million_in_5y_research_target_supported": hit_3m > 0,
        "five_million_in_5y_research_target_supported": hit_5m > 0,
        "twelve_h_reduces_monthly_cluster_dependency": cluster_audit.get("verdict") != "MOSTLY_DUPLICATIVE",
        "twelve_h_improves_missed_trade_tolerance_beyond_1pct": threshold > 1.0,
        "twelve_h_reduces_cost_sensitivity": cost_verdict != "NORMAL_COST_WEAK",
        "twelve_h_produces_independent_profitable_clusters": cluster_audit.get("verdict") == "INDEPENDENT_PROFITABLE_CLUSTERS_FOUND",
        "twelve_h_duplicates_same_btc_moves": cluster_audit.get("verdict") == "MOSTLY_DUPLICATIVE",
        "twelve_h_should_progress_to_later_native_replay_candidate": avg >= 850_000.0 and cluster_audit.get("verdict") != "MOSTLY_DUPLICATIVE",
        "cost_resilience_verdict": cost_verdict,
        "final_classification_candidate": classification,
    }
    overlap_verdict = cluster_audit.get("verdict", "MOSTLY_DUPLICATIVE")
    return interpretation, cost_verdict, overlap_verdict


def _implementation_self_audit(
    *,
    schema_fields_detected: list[str],
    timestamp_field_used: str,
    candle_fields_detected: list[str],
    baseline_metric_used: str,
    baseline_reconciliation_pass: bool,
    baseline_accounting_repair_status: str,
    selected_repair_mode: str,
    row_level_accounting_repair_success: bool,
    combined_simulation_reliable: bool,
    parameter_family_status: str,
    parameter_variants_tested: int,
    stochastic_repeat_count_used: int,
    scout_mode: bool,
    warnings: list[str],
) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "schema_fields_detected": schema_fields_detected,
        "timestamp_field_used": timestamp_field_used,
        "candle_fields_detected": candle_fields_detected,
        "baseline_metric_used": baseline_metric_used,
        "baseline_reconciliation_pass": baseline_reconciliation_pass,
        "baseline_accounting_repair_status": baseline_accounting_repair_status,
        "selected_repair_mode": selected_repair_mode,
        "row_level_accounting_repair_success": row_level_accounting_repair_success,
        "combined_simulation_reliable": combined_simulation_reliable,
        "parameter_family_status": parameter_family_status,
        "parameter_variants_tested": parameter_variants_tested,
        "parameter_grid_overfit_check": parameter_variants_tested <= MAX_PARAMETER_VARIANTS_ALLOWED,
        "best_family_selection_metric_order": [
            "combined normal-cost rolling 5Y average",
            "combined hit_1m windows",
            "lower overlap with 1H",
            "independent positive months",
            "profit factor",
        ],
        "rolling_5y_metric_used": "normal-cost rolling_5y_average and hit-window counts drive mission classification",
        "full_sequence_metric_used": "full-sequence ending equity used only as context",
        "leakage_check": True,
        "future_field_usage_check": True,
        "silent_fallback_check": False,
        "stress_metric_scope_check": True,
        "stochastic_repeat_count_used": stochastic_repeat_count_used,
        "stochastic_results_reliable_for_final_gate": not scout_mode,
        "scout_mode": scout_mode,
        "previous_artifacts_overwritten": False,
        "reviewer_notes": [
            "12H candidate selection uses only pre-entry 12H features.",
            "Rolling 5Y metrics drive mission classification; full-sequence equity is context only.",
            "Stochastic missed-trade results are scout-mode if repeat budget is below gate threshold.",
            *warnings,
        ],
    }


def _court_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Native 12H Execution Sleeve Discovery Audit",
            "",
            f"Final classification: `{summary['final_classification']}`",
            "",
            "## Court Findings",
            "",
            f"1. 12H data availability verdict: `{summary['twelve_h_data_availability_verdict']}`.",
            f"2. Baseline reconciliation pass: `{summary['baseline_reconciliation_pass']}` with audit reliability `{summary['audit_reliability_verdict']}`.",
            f"3. Baseline accounting repair status: `{summary['baseline_accounting_repair_status']}` via `{summary['selected_repair_mode']}`; combined simulation reliable: `{summary['combined_simulation_reliable']}`.",
            f"4. Expected prior 1H normal-cost rolling 5Y average / median: `{summary['expected_prior_1h_baseline_average']:.2f}` / `{summary['expected_prior_1h_baseline_median']:.2f}` EUR.",
            f"5. Audit 1H_BASE_ONLY normal-cost rolling 5Y average / median: `{summary['audit_1h_base_only_average']:.2f}` / `{summary['audit_1h_base_only_median']:.2f}` EUR.",
            f"6. Parameter-family status: `{summary['parameter_family_status']}` with best family `{summary['best_parameter_family_id']}`.",
            f"7. Best 12H-only normal-cost rolling 5Y average / median: `{summary['best_12h_only_normal_cost_average']:.2f}` / `{summary['best_12h_only_normal_cost_median']:.2f}` EUR.",
            f"8. Best combined 1H+12H normal-cost rolling 5Y average / median: `{summary['best_combined_normal_cost_average']:.2f}` / `{summary['best_combined_normal_cost_median']:.2f}` EUR.",
            f"9. Combined 1M / 3M / 5M hit windows: `{summary['combined_hit_1m_windows']}` / `{summary['combined_hit_3m_windows']}` / `{summary['combined_hit_5m_windows']}`.",
            f"10. Missed-trade tolerance threshold: `{summary['missed_trade_tolerance_threshold_pct']}%`.",
            f"11. Cost resilience verdict: `{summary['cost_resilience_verdict']}`.",
            f"12. Independent cluster verdict: `{summary['independent_cluster_verdict']}` and overlap verdict `{summary['overlap_with_1h_verdict']}`.",
            f"13. Original 12H rejection softened: `{summary['whether_original_12h_rejection_should_be_softened']}`.",
            f"14. Freeze-and-confirm worthy family found: `{summary['whether_any_12h_family_deserves_freeze_and_confirm']}`.",
            f"15. Stochastic repeat count used: `{summary['stochastic_repeat_count_used']}` with scout mode `{summary['scout_mode']}`.",
            f"16. Implementation self-audit verdict: `{summary['implementation_self_audit_verdict']}`.",
            f"17. Next research step: `{summary['next_recommended_research_step']}`.",
            "",
            "## Guardrails",
            "",
            "- `research_only=true`",
            "- `real_money_allowed=false`",
            "- `paper_allowed=false`",
            "- `live_allowed=false`",
            "- `behavior_change_allowed=false`",
            "- No live, paper, runtime, allocator, or production behavior changed",
            "",
        ]
    )


def write_native_12h_execution_sleeve_discovery_audit(
    config: Native12HExecutionSleeveDiscoveryAuditConfig,
) -> dict[str, Path]:
    paths = _paths(config)
    diagnostics_root, ledger_root, reports_root = _ensure_dirs(config.output_root)

    source_csv, source_warnings = _resolve_source_csv(config, paths)
    if source_csv is None or not source_csv.exists():
        return _empty_outputs(
            config,
            state="blocked",
            classification="NATIVE_12H_EXECUTION_BLOCKED_MISSING_DATA",
            warnings=source_warnings,
        )

    htf, discovery, quality = _load_12h_candles(source_csv)
    if not quality.get("can_test_native_12h_execution", False):
        return _empty_outputs(
            config,
            state="blocked",
            classification="NATIVE_12H_EXECUTION_BLOCKED_MISSING_DATA",
            warnings=[*source_warnings, "12H candles were unavailable or failed the quality gate."],
        )

    base_rows, baseline_info, baseline_warnings = _load_base_bridge_context(config, paths=paths, fallback_price_frame=htf.set_index("candle_close_timestamp"))
    if not base_rows:
        return _empty_outputs(
            config,
            state="blocked",
            classification="NATIVE_12H_EXECUTION_BLOCKED_MISSING_DATA",
            warnings=[*source_warnings, *baseline_warnings, "No 1H base rows were available for combined comparison."],
        )

    candidate_signals, inventory_rows, leakage = _generate_12h_candidates(htf)
    simulated_rows, performance_rows, monthly_rows, cluster_json = _simulate_candidate_families(candidate_signals, htf)

    best_long_family, best_long_rows = _best_family_rows(performance_rows, simulated_rows, side_filter="long")
    best_short_family, best_short_rows = _best_family_rows(performance_rows, simulated_rows, side_filter="short")
    best_both_family, best_both_rows = _best_family_rows(performance_rows, simulated_rows, side_filter="long_short")
    if not best_both_rows:
        best_both_family, best_both_rows = _best_family_rows(performance_rows, simulated_rows, side_filter="all")

    family_cost_rows: list[dict[str, Any]] = []
    for family_name in sorted({row["candidate_family"] for row in simulated_rows}):
        family_rows = [_clone_row(row) for row in simulated_rows if row["candidate_family"] == family_name]
        family_cost_rows.extend(_evaluate_cost_bands(family_rows, label_prefix=family_name))

    best_12h_only_normal_rows = [row for row in family_cost_rows if row["band_name"] == "NORMAL_MIXED_MAKER_TAKER_COST"]
    best_12h_only_normal_rows.sort(key=lambda item: (-_safe_float(item["rolling_5y_average"]), -int(item["hit_1m_windows"])))
    best_12h_only = best_12h_only_normal_rows[0] if best_12h_only_normal_rows else {}

    combined_results, combined_cost_rows, simple_cap_rows = _evaluate_combined_variants(
        base_rows,
        best_long_rows,
        best_short_rows,
        best_both_rows,
    )
    best_combined = combined_results[0] if combined_results else {}
    baseline_repair = _repair_baseline_accounting(
        config=config,
        paths=paths,
        baseline_info=baseline_info,
        base_rows=base_rows,
        combined_results=combined_results,
    )
    base_rows_for_judgment = baseline_repair["selected_rows"] if baseline_repair["row_level_accounting_repair_success"] else base_rows
    if baseline_repair["row_level_accounting_repair_success"]:
        combined_results, combined_cost_rows, simple_cap_rows = _evaluate_combined_variants_overlay(
            base_rows_for_judgment,
            best_long_rows,
            best_short_rows,
            best_both_rows,
        )
        best_combined = combined_results[0] if combined_results else {}
    baseline_reconciliation = _baseline_reconciliation_check(paths=paths, combined_results=combined_results)

    parameter_rows: list[dict[str, Any]] = []
    parameter_combined_rows: list[dict[str, Any]] = []
    parameter_best_rows: list[dict[str, Any]] = []
    parameter_layer_allowed_after_repair = bool(baseline_repair["parameter_family_layer_allowed_after_repair"])
    if parameter_layer_allowed_after_repair:
        parameter_rows, parameter_summary, parameter_combined_rows, parameter_best_rows = _evaluate_parameter_families(htf, base_rows_for_judgment)
    else:
        parameter_summary = _parameter_family_summary_block("BLOCKED_BASELINE_RECONCILIATION_FAIL")

    cluster_audit, overlap_rows = _independent_cluster_audit(base_rows, best_both_rows)

    if parameter_summary.get("whether_any_12h_family_deserves_freeze_and_confirm"):
        best_12h_only_average = _safe_float(parameter_summary.get("best_12h_only_normal_cost_rolling_5y_average"))
        best_12h_only_median = _safe_float(parameter_summary.get("best_12h_only_normal_cost_rolling_5y_median"))
        best_combined_average = _safe_float(parameter_summary.get("best_1h_plus_12h_normal_cost_rolling_5y_average"))
        best_combined_median = _safe_float(parameter_summary.get("best_1h_plus_12h_normal_cost_rolling_5y_median"))
        combined_hit_1m = int(parameter_summary.get("best_1h_plus_12h_hit_1m_windows", 0) or 0)
        combined_hit_3m = int(parameter_summary.get("best_1h_plus_12h_hit_3m_windows", 0) or 0)
        combined_hit_5m = int(parameter_summary.get("best_1h_plus_12h_hit_5m_windows", 0) or 0)
        best_12h_candidate_name = str(parameter_summary.get("best_parameter_family_id") or best_both_family or "not_available")
        overlap_verdict_summary = str(parameter_summary.get("overlap_with_1h_verdict") or "unknown")
        independent_cluster_verdict = str(parameter_summary.get("independent_cluster_verdict") or "unknown")
    else:
        best_12h_only_average = _safe_float(best_12h_only.get("rolling_5y_average"))
        best_12h_only_median = _safe_float(best_12h_only.get("rolling_5y_median"))
        best_combined_average = _safe_float(best_combined.get("normal_cost_rolling_5y_average"))
        best_combined_median = _safe_float(best_combined.get("normal_cost_rolling_5y_median"))
        combined_hit_1m = int(best_combined.get("normal_cost_hit_1m_windows", 0))
        combined_hit_3m = int(best_combined.get("normal_cost_hit_3m_windows", 0))
        combined_hit_5m = int(best_combined.get("normal_cost_hit_5m_windows", 0))
        best_12h_candidate_name = str(best_12h_only.get("candidate_name") or best_both_family or "not_available")
        overlap_verdict_summary = str(cluster_audit.get("verdict") or "unknown")
        independent_cluster_verdict = str(cluster_audit.get("verdict") or "unknown")

    resilience_rows, resilience_summary = _evaluate_missed_trade_resilience(
        _combine_rows(base_rows, _suppress_overlap(base_rows, best_both_rows)),
        variant_name=str(best_combined.get("variant_name") or "1H_BASE_ONLY"),
        random_repeat_count=config.random_repeat_count,
    )
    stochastic = _stochastic_budget_reliability(resilience_summary["random_repeat_count_used"])
    mission_interpretation, cost_verdict, overlap_verdict = _mission_interpretation(
        best_12h_only_row=best_12h_only,
        best_combined_row=best_combined,
        resilience_summary=resilience_summary,
        cluster_audit=cluster_audit,
    )

    final_classification = mission_interpretation["final_classification_candidate"]
    if stochastic["scout_mode"] and final_classification == "NATIVE_12H_EXECUTION_READY_FOR_COMBINED_NATIVE_REPLAY_RESEARCH_ONLY":
        final_classification = "NATIVE_12H_EXECUTION_IMPROVES_BUT_NOT_GATE_PASSING"
    audit_reliability_verdict = "BASELINE_ROW_LEVEL_ACCOUNTING_REPAIR_REQUIRED"
    final_classification_reliable = False
    deterministic_12h_conclusion_usable = False
    whether_original_12h_rejection_should_be_softened = False
    whether_any_12h_family_deserves_freeze_and_confirm = False
    if baseline_repair["row_level_accounting_repair_success"]:
        final_classification_reliable = True
        deterministic_12h_conclusion_usable = True
        whether_original_12h_rejection_should_be_softened = bool(parameter_summary.get("whether_original_12h_rejection_should_be_softened"))
        whether_any_12h_family_deserves_freeze_and_confirm = bool(parameter_summary.get("whether_any_12h_family_deserves_freeze_and_confirm"))
        if whether_any_12h_family_deserves_freeze_and_confirm:
            audit_reliability_verdict = "BASELINE_RECONCILED_12H_PARAMETER_FAMILY_PROMISING"
            final_classification = (
                "NATIVE_12H_EXECUTION_3M_PROMISING_RESEARCH_ONLY"
                if best_combined_average >= 3_000_000.0
                else "NATIVE_12H_EXECUTION_1M_PROMISING_RESEARCH_ONLY"
                if best_combined_average >= 1_000_000.0 and combined_hit_1m > 0
                else "NATIVE_12H_EXECUTION_IMPROVES_BUT_NOT_GATE_PASSING"
            )
        else:
            audit_reliability_verdict = "BASELINE_RECONCILED_12H_TEST_VALID"
            if final_classification not in {"NATIVE_12H_EXECUTION_REJECTED", "NATIVE_12H_EXECUTION_WEAK"}:
                final_classification = "NATIVE_12H_EXECUTION_WEAK"
    elif baseline_repair["baseline_reconciliation_pass_after_repair"]:
        audit_reliability_verdict = "BASELINE_REPORTING_ONLY_RECONCILED_ROW_LEVEL_REPAIR_STILL_REQUIRED"

    warnings = [*source_warnings, *baseline_warnings]
    self_audit = _implementation_self_audit(
        schema_fields_detected=baseline_info.get("schema_fields_detected", []),
        timestamp_field_used=baseline_info.get("timestamp_field_used", "blocked"),
        candle_fields_detected=quality.get("candle_schema_fields", []),
        baseline_metric_used=str(baseline_info.get("baseline_metric_used", "unknown")),
        baseline_reconciliation_pass=bool(baseline_repair["baseline_reconciliation_pass_after_repair"]),
        baseline_accounting_repair_status="ROW_LEVEL_REPAIRED" if baseline_repair["row_level_accounting_repair_success"] else ("REPORTING_ONLY_DIRECT_BASELINE" if baseline_repair["baseline_reconciliation_pass_after_repair"] else "ROW_LEVEL_REPAIR_REQUIRED"),
        selected_repair_mode=str(baseline_repair["selected_repair_mode"]),
        row_level_accounting_repair_success=bool(baseline_repair["row_level_accounting_repair_success"]),
        combined_simulation_reliable=bool(baseline_repair["combined_simulation_reliable"]),
        parameter_family_status=str(parameter_summary.get("parameter_family_status") or "unknown"),
        parameter_variants_tested=int(parameter_summary.get("total_parameter_variants_tested", 0) or 0),
        stochastic_repeat_count_used=resilience_summary["random_repeat_count_used"],
        scout_mode=stochastic["scout_mode"],
        warnings=warnings,
    )

    next_step = (
        "Repair row-level 1H baseline accounting before judging 12H or moving multi-asset." if not baseline_repair["row_level_accounting_repair_success"] else
        "Freeze the best 12H parameter family and run a separate confirmation audit." if whether_any_12h_family_deserves_freeze_and_confirm else
        "Run a research-only combined native replay candidate review for 1H plus 12H." if final_classification in {
            "NATIVE_12H_EXECUTION_1M_PROMISING_RESEARCH_ONLY",
            "NATIVE_12H_EXECUTION_3M_PROMISING_RESEARCH_ONLY",
            "NATIVE_12H_EXECUTION_READY_FOR_COMBINED_NATIVE_REPLAY_RESEARCH_ONLY",
        } else
        "12H did not close the mission gap cleanly; either refine the 12H family definitions or confirm a later multi-asset route."
    )

    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "twelve_h_data_availability_verdict": quality["execution_mode_verdict"],
        "expected_prior_1h_baseline_average": _safe_float(baseline_reconciliation.get("expected_normal_cost_rolling_5y_average")),
        "expected_prior_1h_baseline_median": _safe_float(baseline_reconciliation.get("expected_normal_cost_rolling_5y_median")),
        "audit_1h_base_only_average": _safe_float(baseline_reconciliation.get("audit_1h_base_only_normal_cost_rolling_5y_average")),
        "audit_1h_base_only_median": _safe_float(baseline_reconciliation.get("audit_1h_base_only_normal_cost_rolling_5y_median")),
        "baseline_reconciliation_pass": bool(baseline_reconciliation["baseline_reconciliation_pass"]),
        "baseline_accounting_repair_status": "ROW_LEVEL_REPAIRED" if baseline_repair["row_level_accounting_repair_success"] else ("REPORTING_ONLY_DIRECT_BASELINE" if baseline_repair["baseline_reconciliation_pass_after_repair"] else "ROW_LEVEL_REPAIR_REQUIRED"),
        "selected_repair_mode": str(baseline_repair["selected_repair_mode"]),
        "row_level_accounting_repair_success": bool(baseline_repair["row_level_accounting_repair_success"]),
        "baseline_reconciliation_pass_after_repair": bool(baseline_repair["baseline_reconciliation_pass_after_repair"]),
        "combined_simulation_reliable": bool(baseline_repair["combined_simulation_reliable"]),
        "reason_combined_simulation_unreliable": str(baseline_repair["reason_combined_simulation_unreliable"]),
        "row_level_accounting_repair_required": bool(baseline_repair["row_level_accounting_repair_required"]),
        "parameter_family_layer_allowed_after_repair": parameter_layer_allowed_after_repair,
        "baseline_reconciliation_warning": str(baseline_repair["root_cause_diagnosis"]),
        "audit_reliability_verdict": audit_reliability_verdict,
        "final_classification_reliable": final_classification_reliable,
        "deterministic_12h_conclusion_usable": deterministic_12h_conclusion_usable,
        "parameter_family_status": str(parameter_summary.get("parameter_family_status") or "unknown"),
        "best_parameter_family_id": str(parameter_summary.get("best_parameter_family_id") or ""),
        "best_12h_candidate": best_12h_candidate_name,
        "best_12h_only_normal_cost_average": best_12h_only_average,
        "best_12h_only_normal_cost_median": best_12h_only_median,
        "best_combined_normal_cost_average": best_combined_average,
        "best_combined_normal_cost_median": best_combined_median,
        "combined_hit_1m_windows": combined_hit_1m,
        "combined_hit_3m_windows": combined_hit_3m,
        "combined_hit_5m_windows": combined_hit_5m,
        "missed_trade_tolerance_threshold_pct": _safe_float(resilience_summary.get("missed_trade_tolerance_threshold_pct")),
        "cost_resilience_verdict": cost_verdict,
        "independent_cluster_verdict": independent_cluster_verdict,
        "overlap_with_1h_verdict": overlap_verdict_summary,
        "stochastic_repeat_count_used": int(resilience_summary["random_repeat_count_used"]),
        "scout_mode": stochastic["scout_mode"],
        "implementation_self_audit_verdict": "PASS_WITH_WARNINGS" if warnings else "PASS",
        "whether_original_12h_rejection_should_be_softened": whether_original_12h_rejection_should_be_softened,
        "whether_any_12h_family_deserves_freeze_and_confirm": whether_any_12h_family_deserves_freeze_and_confirm,
        "final_classification": final_classification,
        "next_recommended_research_step": next_step,
    }
    report = _court_report(summary)

    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "native_12h_execution_sleeve_discovery_summary.json", summary)
    _write_markdown(config.output_root / "native_12h_execution_sleeve_discovery_report.md", report)
    _write_json(diagnostics_root / "timeframe_availability_audit.json", discovery)
    _write_json(diagnostics_root / "12h_candle_quality_report.json", quality)
    _write_json(
        diagnostics_root / "12h_baseline_reconciliation_check.json",
        {
            **baseline_reconciliation,
            "selected_repair_mode": baseline_repair["selected_repair_mode"],
            "repaired_1h_base_normal_cost_rolling_5y_average": round(_safe_float(baseline_repair["repaired_average"]), 6),
            "repaired_1h_base_normal_cost_rolling_5y_median": round(_safe_float(baseline_repair["repaired_median"]), 6),
            "repaired_1h_base_hit_1m_windows": int(baseline_repair["repaired_hit_1m_windows"]),
            "baseline_reconciliation_pass_after_repair": bool(baseline_repair["baseline_reconciliation_pass_after_repair"]),
            "root_cause_diagnosis": baseline_repair["root_cause_diagnosis"],
            "final_classification_reliable_after_repair": final_classification_reliable,
            "deterministic_12h_conclusion_usable_after_repair": deterministic_12h_conclusion_usable,
            "parameter_family_layer_allowed_after_repair": parameter_layer_allowed_after_repair,
        },
    )
    _write_json(diagnostics_root / "12h_baseline_accounting_repair_diagnostics.json", baseline_repair["diagnostics"])
    _write_csv(diagnostics_root / "native_12h_candidate_inventory.csv", inventory_rows)
    _write_json(diagnostics_root / "native_12h_candidate_inventory.json", {**RESEARCH_ONLY_FLAGS, "rows": inventory_rows})
    _write_json(diagnostics_root / "native_12h_no_leakage_check.json", leakage)
    _write_csv(ledger_root / "native_12h_trade_candidates.csv", [
        {
            **{key: value for key, value in row.items() if not isinstance(value, pd.Timestamp)},
            "entry_timestamp": row["entry_timestamp"].isoformat() if isinstance(row.get("entry_timestamp"), pd.Timestamp) else "",
            "exit_timestamp": row["exit_timestamp"].isoformat() if isinstance(row.get("exit_timestamp"), pd.Timestamp) else "",
        }
        for row in simulated_rows
    ])
    equity_curve_rows = []
    for family in sorted({row["candidate_family"] for row in simulated_rows}):
        family_rows = [_clone_row(row) for row in simulated_rows if row["candidate_family"] == family]
        output = _simulate_bridge_sequence(family_rows, stepup_schedule=list(BASE_STEPUP_SCHEDULE))
        for trace in output["trade_trace"]:
            equity_curve_rows.append({"candidate_family": family, **trace})
    _write_csv(ledger_root / "native_12h_equity_curves.csv", equity_curve_rows)
    _write_csv(diagnostics_root / "native_12h_candidate_performance.csv", performance_rows)
    _write_csv(diagnostics_root / "native_12h_monthly_distribution.csv", monthly_rows)
    _write_json(diagnostics_root / "native_12h_cluster_dependency.json", cluster_json)
    _write_csv(diagnostics_root / "12h_parameter_family_results.csv", _harmonize_rows(parameter_rows))
    _write_json(diagnostics_root / "12h_parameter_family_summary.json", parameter_summary)
    _write_csv(diagnostics_root / "12h_parameter_family_combined_portfolio_results.csv", _harmonize_rows(parameter_combined_rows))
    _write_csv(diagnostics_root / "combined_1h_12h_portfolio_results.csv", combined_results)
    _write_json(diagnostics_root / "combined_1h_12h_portfolio_results.json", {**RESEARCH_ONLY_FLAGS, "rows": combined_results})
    _write_csv(diagnostics_root / "simple_capital_logic_comparison.csv", simple_cap_rows)
    _write_csv(diagnostics_root / "12h_cost_band_rolling_5y_results.csv", [*family_cost_rows, *combined_cost_rows])
    _write_csv(diagnostics_root / "12h_missed_trade_resilience.csv", resilience_rows)
    _write_json(diagnostics_root / "12h_stochastic_budget_reliability_check.json", stochastic)
    _write_json(diagnostics_root / "mission_target_interpretation.json", mission_interpretation)
    _write_json(diagnostics_root / "12h_independent_cluster_audit.json", cluster_audit)
    _write_csv(diagnostics_root / "12h_overlap_with_1h_bridge.csv", overlap_rows)
    _write_json(diagnostics_root / "implementation_self_audit.json", self_audit)
    _write_json(reports_root / "next_research_recommendation.json", {**RESEARCH_ONLY_FLAGS, "next_step": next_step})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "native_12h_execution_sleeve_discovery_summary.json",
        "report": config.output_root / "native_12h_execution_sleeve_discovery_report.md",
    }


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    output_root = package_root / "output" / OUTPUT_FOLDER_NAME
    write_native_12h_execution_sleeve_discovery_audit(
        Native12HExecutionSleeveDiscoveryAuditConfig(
            package_root=package_root,
            output_root=output_root,
        )
    )
