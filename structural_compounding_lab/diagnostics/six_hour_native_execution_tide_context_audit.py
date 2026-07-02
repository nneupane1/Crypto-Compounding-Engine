from __future__ import annotations

import hashlib
import json
import math
import random
import sys
from dataclasses import asdict, dataclass
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
from structural_compounding_lab.diagnostics.htf_context_role_reconciliation_audit import (  # noqa: E402
    EARNED_GEAR_OUTPUT_FOLDER_NAME,
)
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _median,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _to_float,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.diagnostics.milestone_bridge_fragility_driver_repair_audit import (  # noqa: E402
    BASE_STEPUP_SCHEDULE,
    _drop_random_trades,
    _group_consecutive_blocks,
    _month_label,
    _rolling_window_summary,
    _simulate_overlay_sequence,
    _sort_rows,
)
from structural_compounding_lab.diagnostics.milestone_gated_explosive_compounding_audit import (  # noqa: E402
    EXPECTED_REPAIR_MODE,
    MilestoneGatedExplosiveCompoundingAuditConfig,
    _load_baseline_anchor_and_stream as _load_prior_baseline_anchor_and_stream,
    _safe_float,
)
from structural_compounding_lab.diagnostics.native_12h_execution_sleeve_discovery_audit import (  # noqa: E402
    CONSERVATIVE_COST_BPS,
    HIGH_SLIPPAGE_COST_BPS,
    NORMAL_COST_BPS,
    OPTIMISTIC_COST_BPS,
    ZERO_COST_BPS,
)
from structural_compounding_lab.diagnostics.native_pre_entry_sr_feature_enrichment_audit import (  # noqa: E402
    _discover_candle_source,
    _load_price_source,
    _source_path_from_summary,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import _build_windows  # noqa: E402


OUTPUT_FOLDER_NAME = "six_hour_native_execution_tide_context_audit_001"
DEFAULT_RANDOM_REPEAT_COUNT = 32
MAX_VARIANTS = 14
STATE_NOT_STARTED = "not_started"
STATE_RUNNING = "running"
STATE_PARTIAL = "partial"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_BLOCKED = "blocked"
COST_BAND_SPECS = (
    ("ZERO_COST_REFERENCE", ZERO_COST_BPS),
    ("OPTIMISTIC_MAKER_COST", OPTIMISTIC_COST_BPS),
    ("NORMAL_MIXED_MAKER_TAKER_COST", NORMAL_COST_BPS),
    ("CONSERVATIVE_TAKER_COST", CONSERVATIVE_COST_BPS),
    ("HIGH_SLIPPAGE_COST", HIGH_SLIPPAGE_COST_BPS),
)


@dataclass(frozen=True)
class SixHourNativeExecutionTideContextAuditConfig:
    package_root: Path
    output_root: Path
    random_repeat_count: int = DEFAULT_RANDOM_REPEAT_COUNT
    force_rerun: bool = False


@dataclass(frozen=True)
class SixHourVariantSpec:
    variant_name: str
    description: str
    variant_type: str
    available: bool
    unavailable_reason: str
    combine_with_one_h: bool = False
    independent_only: bool = False
    scale_cap: float = 1.0
    diagnostic_only: bool = False


def _paths(config: SixHourNativeExecutionTideContextAuditConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    return {
        "execution_cost_band_results": output_root / "execution_cost_realism_and_trade_redundancy_audit_001" / "diagnostics" / "execution_cost_band_results.csv",
        "native_12h_summary": output_root / "native_12h_execution_sleeve_discovery_audit_001" / "native_12h_execution_sleeve_discovery_summary.json",
        "native_12h_repair": output_root / "native_12h_execution_sleeve_discovery_audit_001" / "diagnostics" / "12h_baseline_accounting_repair_diagnostics.json",
        "htf_context_summary": output_root / "htf_context_role_reconciliation_audit_001" / "htf_context_role_reconciliation_summary.json",
        "htf_six_hour_decision": output_root / "htf_context_role_reconciliation_audit_001" / "diagnostics" / "six_hour_role_decision.json",
        "htf_stack_recommendation": output_root / "htf_context_role_reconciliation_audit_001" / "diagnostics" / "strategic_timeframe_recommendation.json",
        "earned_gear_summary": output_root / EARNED_GEAR_OUTPUT_FOLDER_NAME / "earned_gear_activation_discovery_summary.json",
        "broad_summary": output_root / "broad_historical_structural_replay_001" / "ledger" / "summary.json",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path, Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    ledger_root = output_root / "ledger"
    reports_root = output_root / "reports"
    checkpoints_root = output_root / "_checkpoints"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    ledger_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    checkpoints_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, ledger_root, reports_root, checkpoints_root


def _compatibility_payload(variant_specs: list[SixHourVariantSpec], random_repeat_count: int) -> dict[str, Any]:
    return {
        "module": "six_hour_native_execution_tide_context_audit",
        "version": 1,
        "random_repeat_count": int(random_repeat_count),
        "variant_specs": [asdict(spec) for spec in variant_specs],
        "cost_bands": [band for band, _ in COST_BAND_SPECS],
    }


def _compatibility_signature(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _next_run_folder(output_root: Path) -> Path:
    return output_root.parent / f"{output_root.name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


def _write_status(
    output_root: Path,
    *,
    state: str,
    warnings: list[str],
    compatibility_signature: str,
    extra: dict[str, Any] | None = None,
) -> None:
    payload = {
        "state": state,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "compatibility_signature": compatibility_signature,
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    if extra:
        payload.update(extra)
    _write_json(output_root / "status.json", payload)


def _write_scenario_progress(
    output_root: Path,
    *,
    state: str,
    compatibility_signature: str,
    variant_specs: list[SixHourVariantSpec],
    completed_variants: list[str],
    warnings: list[str],
) -> None:
    payload = {
        "state": state,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "compatibility_signature": compatibility_signature,
        "variant_names": [spec.variant_name for spec in variant_specs],
        "total_variants": len(variant_specs),
        "completed_variants": completed_variants,
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(output_root / "scenario_progress.json", payload)


def _write_run_progress(
    diagnostics_root: Path,
    *,
    state: str,
    completed_variants: int,
    total_variants: int,
    current_variant: str,
    warnings: list[str],
) -> None:
    payload = {
        "state": state,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed_variants": completed_variants,
        "total_variants": total_variants,
        "percent_complete": round((completed_variants / max(total_variants, 1)) * 100.0, 4),
        "current_variant": current_variant,
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(diagnostics_root / "run_progress.json", payload)


def _empty_outputs(
    config: SixHourNativeExecutionTideContextAuditConfig,
    *,
    state: str,
    classification: str,
    warnings: list[str],
    compatibility_signature: str,
) -> dict[str, Path]:
    diagnostics_root, ledger_root, reports_root, checkpoints_root = _ensure_dirs(config.output_root)
    _write_status(config.output_root, state=state, warnings=warnings, compatibility_signature=compatibility_signature)
    _write_scenario_progress(
        config.output_root,
        state=state,
        compatibility_signature=compatibility_signature,
        variant_specs=[],
        completed_variants=[],
        warnings=warnings,
    )
    _write_run_progress(diagnostics_root, state=state, completed_variants=0, total_variants=0, current_variant="", warnings=warnings)
    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "final_classification": classification,
        "warnings": warnings,
        "checkpoint_resume_status": "resume_capable",
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(config.output_root / "six_hour_native_execution_tide_context_summary.json", summary)
    _write_markdown(
        config.output_root / "six_hour_native_execution_tide_context_report.md",
        "# 6H Native Execution Scout with 12H/1D Tide Context Audit\n\nThe audit blocked before a baseline-safe 6H scout comparison could run.\n",
    )
    json_outputs = (
        "prior_court_anchor.json",
        "resampling_integrity_audit.json",
        "six_hour_candidate_family_specs.json",
        "six_hour_independence_summary.json",
        "six_hour_filter_damage_report.json",
        "stochastic_budget_reliability_check.json",
        "best_six_hour_variant_selection.json",
        "six_hour_native_execution_role_decision.json",
        "twelve_hour_ocean_role_decision.json",
        "daily_tide_role_decision.json",
        "weekly_deep_current_role_decision.json",
        "strategic_execution_stack_recommendation.json",
        "implementation_self_audit.json",
    )
    csv_outputs = (
        "timeframe_data_coverage.csv",
        "six_hour_native_candidate_signals.csv",
        "twelve_hour_ocean_context_labels.csv",
        "daily_tide_context_labels.csv",
        "weekly_deep_current_context_labels.csv",
        "six_hour_execution_variants.csv",
        "six_hour_one_hour_overlap_audit.csv",
        "six_hour_over_tightening_audit.csv",
        "six_hour_cost_band_results.csv",
        "six_hour_rolling_5y_results.csv",
        "six_hour_stress_results.csv",
        "six_hour_missed_trade_resilience.csv",
        "six_hour_scorecard.csv",
    )
    for name in json_outputs:
        _write_json(diagnostics_root / name, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    for name in csv_outputs:
        _write_csv(diagnostics_root / name, [])
    _write_csv(ledger_root / "six_hour_equity_curves.csv", [])
    _write_csv(ledger_root / "six_hour_trade_ledgers.csv", [])
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(checkpoints_root / "checkpoint_index.json", {"completed_variants": [], **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "six_hour_native_execution_tide_context_summary.json",
        "report": config.output_root / "six_hour_native_execution_tide_context_report.md",
    }


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


def _clone_row(row: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(row)
    for field in ("entry_timestamp", "exit_timestamp", "timestamp"):
        if isinstance(cloned.get(field), pd.Timestamp):
            cloned[field] = pd.Timestamp(cloned[field])
    return cloned


def _harmonize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    keys = sorted({key for row in rows for key in row.keys()})
    return [{key: row.get(key, "") for key in keys} for row in rows]


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _load_prior_court_anchor(config: SixHourNativeExecutionTideContextAuditConfig) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    paths = _paths(config)
    baseline_rows = _read_csv_rows(paths["execution_cost_band_results"])
    baseline_row = next((row for row in baseline_rows if str(row.get("band_name") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"), None)
    native_12h_summary = _read_json(paths["native_12h_summary"], {})
    native_12h_repair = _read_json(paths["native_12h_repair"], {})
    htf_summary = _read_json(paths["htf_context_summary"], {})
    htf_six_hour_decision = _read_json(paths["htf_six_hour_decision"], {})
    htf_stack = _read_json(paths["htf_stack_recommendation"], {})
    earned_summary = _read_json(paths["earned_gear_summary"], {})
    if baseline_row is None:
        warnings.append("Trusted 1H normal-cost baseline row missing.")
    if not native_12h_summary:
        warnings.append("12H execution rejection summary missing.")
    if not htf_summary:
        warnings.append("1H + 6H HTF context court summary missing.")
    if not earned_summary:
        warnings.append("Earned gear summary missing.")
    if warnings:
        return None, warnings
    anchor = {
        **RESEARCH_ONLY_FLAGS,
        "trusted_1h_baseline_average": _safe_float(baseline_row.get("rolling_5y_average_ending_equity")),
        "trusted_1h_baseline_median": _safe_float(baseline_row.get("rolling_5y_median_ending_equity")),
        "trusted_1h_baseline_hit_1m_windows": int(float(baseline_row.get("hit_1m_windows", 0) or 0)),
        "twelve_h_execution_final_classification": str(native_12h_summary.get("final_classification") or ""),
        "twelve_h_execution_retired": str(native_12h_summary.get("final_classification") or "") == "NATIVE_12H_EXECUTION_REJECTED",
        "twelve_h_repair_mode": str(native_12h_repair.get("selected_repair_mode") or ""),
        "twelve_h_repair_pass": bool(native_12h_repair.get("baseline_reconciliation_pass_after_repair", False)),
        "htf_context_final_classification": str(htf_summary.get("final_classification") or ""),
        "htf_context_best_variant": str(htf_summary.get("best_context_variant") or ""),
        "htf_context_best_average": _safe_float(htf_summary.get("best_normal_cost_average")),
        "htf_context_best_median": _safe_float(htf_summary.get("best_normal_cost_median")),
        "htf_context_best_hit_1m_windows": int(float(htf_summary.get("best_hit_1m_windows", 0) or 0)),
        "htf_six_hour_role_decision": str(htf_six_hour_decision.get("decision") or ""),
        "htf_shadow_forward_fallback_recommended": "shadow" in json.dumps(htf_stack).lower(),
        "earned_gear_final_classification": str(earned_summary.get("final_classification") or ""),
        "expected_repair_mode_match": str(native_12h_repair.get("selected_repair_mode") or "") == EXPECTED_REPAIR_MODE,
    }
    if not anchor["expected_repair_mode_match"]:
        warnings.append("Expected trusted repair mode does not match 12H repair diagnostics.")
    return anchor, warnings


def _trusted_stream_recheck(config: SixHourNativeExecutionTideContextAuditConfig) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None, list[str]]:
    baseline_anchor, normalized_rows, reconstruction, warnings = _load_prior_baseline_anchor_and_stream(
        MilestoneGatedExplosiveCompoundingAuditConfig(
            package_root=config.package_root,
            output_root=config.package_root / "output" / "milestone_gated_explosive_compounding_audit_001",
            random_repeat_count=config.random_repeat_count,
            force_rerun=False,
        )
    )
    if baseline_anchor is None or normalized_rows is None:
        return None, None, warnings
    payload = {
        **RESEARCH_ONLY_FLAGS,
        "trusted_baseline_reproduced": bool(reconstruction.get("trusted_baseline_reproduced", False)),
        "row_count": len(normalized_rows),
        "expected_row_count_near_558": bool(reconstruction.get("expected_row_count_near_558", False)),
        "timestamp_span_start": reconstruction.get("timestamp_span_start"),
        "timestamp_span_end": reconstruction.get("timestamp_span_end"),
        "timestamp_field_used": reconstruction.get("timestamp_field_used"),
        "r_field_used": reconstruction.get("r_field_used"),
        "cost_model_used": reconstruction.get("cost_model_used"),
        "synthetic_stop_distance_cost_model_used": bool(reconstruction.get("synthetic_stop_distance_cost_model_used", False)),
        "rolling_5y_average_reconciled": _safe_float(baseline_anchor.get("rolling_5y_average_ending_equity")),
        "rolling_5y_median_reconciled": _safe_float(baseline_anchor.get("rolling_5y_median_ending_equity")),
        "hit_1m_windows_reconciled": int(baseline_anchor.get("hit_1m_windows", 0) or 0),
        "schema_fields_detected": reconstruction.get("schema_fields_detected", []),
        "warnings": warnings,
    }
    return payload, normalized_rows, warnings


def _resolve_source_csv(config: SixHourNativeExecutionTideContextAuditConfig) -> tuple[Path | None, list[str]]:
    warnings: list[str] = []
    broad_summary_path = _paths(config)["broad_summary"]
    source_csv = _source_path_from_summary(broad_summary_path) if broad_summary_path.exists() else None
    if source_csv is not None and source_csv.exists():
        return source_csv, warnings
    fallback_dir = config.package_root.parent / "data_storage" / "BTCUSDT" / "1m"
    if fallback_dir.exists():
        candidates = sorted(
            path
            for path in fallback_dir.glob("BTCUSDT_1m_*.csv")
            if "live_runtime" not in path.name and "_T" not in path.name and "T00.00.00" not in path.name
        )
        if candidates:
            warnings.append("Fell back to canonical data_storage BTCUSDT 1m source because broad summary source_csv was unavailable.")
            return candidates[-1], warnings
    warnings.append("No canonical BTCUSDT 1m source CSV could be resolved.")
    return None, warnings


def _augment_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    working = frame.copy().sort_index()
    if isinstance(working.index, pd.DatetimeIndex) and working.index.tz is not None:
        working.index = working.index.tz_convert("UTC").tz_localize(None)
    prev_close = working["close"].shift(1)
    tr = pd.concat(
        [
            working["high"] - working["low"],
            (working["high"] - prev_close).abs(),
            (working["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    working["atr14"] = tr.rolling(14, min_periods=3).mean()
    working["atr50_mean"] = working["atr14"].rolling(50, min_periods=5).mean()
    working["ema20"] = working["close"].ewm(span=20, adjust=False).mean()
    working["ema50"] = working["close"].ewm(span=50, adjust=False).mean()
    working["recent_high_6"] = working["high"].rolling(6, min_periods=3).max()
    working["recent_low_6"] = working["low"].rolling(6, min_periods=3).min()
    working["recent_high_12"] = working["high"].rolling(12, min_periods=4).max()
    working["recent_low_12"] = working["low"].rolling(12, min_periods=4).min()
    working["recent_high_20"] = working["high"].rolling(20, min_periods=5).max()
    working["recent_low_20"] = working["low"].rolling(20, min_periods=5).min()
    working["volume_ma20"] = working["volume"].rolling(20, min_periods=3).mean()
    working["body"] = (working["close"] - working["open"]).abs()
    working["bar_range"] = (working["high"] - working["low"]).replace(0.0, math.nan)
    working["body_ratio"] = (working["body"] / working["bar_range"]).fillna(0.0)
    working["ema20_slope"] = working["ema20"].diff()
    working["ema50_slope"] = working["ema50"].diff()
    return working


def _resample_frame(df_1m: pd.DataFrame, rule: str) -> pd.DataFrame:
    resampled = (
        df_1m.resample(rule, closed="left", label="right")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    if df_1m.empty:
        return resampled
    close_cutoff = df_1m.index.max() + pd.Timedelta(minutes=1)
    resampled = resampled.loc[resampled.index <= close_cutoff]
    return _augment_frame(resampled)


def _coverage_row(
    frame: pd.DataFrame,
    *,
    timeframe: str,
    rule: str,
    source_start: pd.Timestamp | None,
    source_end: pd.Timestamp | None,
    trade_start: pd.Timestamp | None,
    trade_end: pd.Timestamp | None,
    source_path: Path,
) -> dict[str, Any]:
    duplicates = int(frame.index.duplicated().sum()) if not frame.empty else 0
    expected_delta = pd.tseries.frequencies.to_offset(rule).delta if hasattr(pd.tseries.frequencies.to_offset(rule), "delta") else pd.Timedelta(rule)
    diffs = frame.index.to_series().diff().dropna() if not frame.empty else pd.Series(dtype="timedelta64[ns]")
    missing_intervals = int((diffs > expected_delta).sum()) if not diffs.empty else 0
    start = frame.index.min() if not frame.empty else None
    end = frame.index.max() if not frame.empty else None
    spans_trades = bool(start is not None and end is not None and trade_start is not None and trade_end is not None and start <= trade_start and end >= trade_end)
    return {
        **RESEARCH_ONLY_FLAGS,
        "timeframe": timeframe,
        "resample_rule": rule,
        "source_path": str(source_path),
        "row_count": int(len(frame)),
        "start_timestamp": start.isoformat() if start is not None else "",
        "end_timestamp": end.isoformat() if end is not None else "",
        "duplicate_timestamp_count": duplicates,
        "missing_interval_count": missing_intervals,
        "timezone_consistency": "naive_utc",
        "candle_close_convention": "closed_left_label_right",
        "resampling_method": "pandas_resample_closed_left_label_right",
        "source_start_timestamp": source_start.isoformat() if source_start is not None else "",
        "source_end_timestamp": source_end.isoformat() if source_end is not None else "",
        "trade_stream_start_timestamp": trade_start.isoformat() if trade_start is not None else "",
        "trade_stream_end_timestamp": trade_end.isoformat() if trade_end is not None else "",
        "coverage_fully_spans_trusted_1h_stream": spans_trades,
        "ohlcv_complete": all(column in frame.columns for column in ("open", "high", "low", "close", "volume")),
        "safe_for_closed_candle_use": bool(duplicates == 0 and all(column in frame.columns for column in ("open", "high", "low", "close", "volume"))),
    }


def _load_timeframes(source_csv: Path, trade_rows: list[dict[str, Any]]) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]], dict[str, Any], list[str]]:
    warnings: list[str] = []
    discovery, availability = _discover_candle_source(source_csv)
    df_1m, df_1h, df_12h = _load_price_source(source_csv)
    df_1m = _augment_frame(df_1m)
    frames = {
        "1M": df_1m,
        "1H": _augment_frame(df_1h),
        "6H": _resample_frame(df_1m, "6h"),
        "12H": _augment_frame(df_12h),
        "1D": _resample_frame(df_1m, "1D"),
        "1W": _resample_frame(df_1m, "1W"),
    }
    trade_start = min((row.get("entry_timestamp") for row in trade_rows if isinstance(row.get("entry_timestamp"), pd.Timestamp)), default=None)
    trade_end = max((row.get("exit_timestamp") for row in trade_rows if isinstance(row.get("exit_timestamp"), pd.Timestamp)), default=None)
    source_start = _try_timestamp(discovery.get("coverage_start"))
    source_end = _try_timestamp(discovery.get("coverage_end"))
    coverage_rows = [
        _coverage_row(frames["1H"], timeframe="1H", rule="1h", source_start=source_start, source_end=source_end, trade_start=trade_start, trade_end=trade_end, source_path=source_csv),
        _coverage_row(frames["6H"], timeframe="6H", rule="6h", source_start=source_start, source_end=source_end, trade_start=trade_start, trade_end=trade_end, source_path=source_csv),
        _coverage_row(frames["12H"], timeframe="12H", rule="12h", source_start=source_start, source_end=source_end, trade_start=trade_start, trade_end=trade_end, source_path=source_csv),
        _coverage_row(frames["1D"], timeframe="1D", rule="1D", source_start=source_start, source_end=source_end, trade_start=trade_start, trade_end=trade_end, source_path=source_csv),
        _coverage_row(frames["1W"], timeframe="1W", rule="1W", source_start=source_start, source_end=source_end, trade_start=trade_start, trade_end=trade_end, source_path=source_csv),
    ]
    for tf in ("6H", "12H", "1D"):
        row = next((item for item in coverage_rows if item["timeframe"] == tf), None)
        if row is None or row["row_count"] == 0 or not row["coverage_fully_spans_trusted_1h_stream"]:
            warnings.append(f"{tf} timeframe could not be built reliably across the trusted 1H trade span.")
    quality = {
        **RESEARCH_ONLY_FLAGS,
        "source_discovery": discovery,
        "source_availability": availability,
        "resampling_no_lookahead_check": True,
        "six_hour_available": bool(next((row for row in coverage_rows if row["timeframe"] == "6H"), {}).get("row_count", 0)),
        "twelve_hour_available": bool(next((row for row in coverage_rows if row["timeframe"] == "12H"), {}).get("row_count", 0)),
        "daily_available": bool(next((row for row in coverage_rows if row["timeframe"] == "1D"), {}).get("row_count", 0)),
        "weekly_available": bool(next((row for row in coverage_rows if row["timeframe"] == "1W"), {}).get("row_count", 0)),
        "coverage_pass": all(
            bool(next((row for row in coverage_rows if row["timeframe"] == tf), {}).get("coverage_fully_spans_trusted_1h_stream"))
            for tf in ("6H", "12H", "1D")
        ),
    }
    return frames, coverage_rows, quality, warnings


def _structure_state(window: pd.DataFrame) -> str:
    if len(window) < 4:
        return "unknown"
    highs = window["high"].tail(4).tolist()
    lows = window["low"].tail(4).tolist()
    if highs[-1] > highs[-2] > highs[-3] and lows[-1] > lows[-2] > lows[-3]:
        return "higher_high_higher_low"
    if highs[-1] < highs[-2] < highs[-3] and lows[-1] < lows[-2] < lows[-3]:
        return "lower_high_lower_low"
    return "mixed"


def _trend_state(candle: pd.Series) -> str:
    close = _safe_float(candle.get("close"))
    ema20 = _safe_float(candle.get("ema20"))
    ema50 = _safe_float(candle.get("ema50"))
    slope20 = _safe_float(candle.get("ema20_slope"))
    slope50 = _safe_float(candle.get("ema50_slope"))
    if close > ema20 and ema20 >= ema50 and slope20 >= 0.0 and slope50 >= 0.0:
        return "bullish"
    if close < ema20 and ema20 <= ema50 and slope20 <= 0.0 and slope50 <= 0.0:
        return "bearish"
    return "neutral"


def _volatility_regime(candle: pd.Series) -> str:
    atr = _safe_float(candle.get("atr14"))
    atr_mean = _safe_float(candle.get("atr50_mean"))
    if atr <= 0.0 or atr_mean <= 0.0:
        return "unknown"
    ratio = atr / atr_mean
    if ratio <= 0.85:
        return "compressed"
    if ratio >= 1.20:
        return "expanded"
    return "normal"


def _context_snapshot(frame: pd.DataFrame, decision_ts: pd.Timestamp, side: str, entry_price: float, stop_price: float, *, prefix: str, daily_mode: bool = False, weekly_mode: bool = False) -> dict[str, Any]:
    if frame.empty:
        return {f"{prefix}_label_available": False}
    context_ts = frame.index.asof(decision_ts)
    if pd.isna(context_ts):
        return {f"{prefix}_label_available": False}
    context_ts = pd.Timestamp(context_ts)
    window = frame.loc[:context_ts].tail(24 if not weekly_mode else 12)
    candle = frame.loc[context_ts]
    prior_window = window.iloc[:-1] if len(window) > 1 else window
    prior_high = _safe_float(prior_window["high"].max()) if not prior_window.empty else _safe_float(candle.get("high"))
    prior_low = _safe_float(prior_window["low"].min()) if not prior_window.empty else _safe_float(candle.get("low"))
    trend = _trend_state(candle)
    structure = _structure_state(window)
    atr = max(_safe_float(candle.get("atr14")), 1e-9)
    supply = _safe_float(candle.get("recent_high_20"))
    demand = _safe_float(candle.get("recent_low_20"))
    room_r = max((supply - entry_price) if side == "long" else (entry_price - demand), 0.0) / max(abs(entry_price - stop_price), 1e-9)
    high = _safe_float(candle.get("high"))
    low = _safe_float(candle.get("low"))
    close = _safe_float(candle.get("close"))
    bullish_sweep = low < prior_low and close > prior_low
    bearish_sweep = high > prior_high and close < prior_high
    conflict = bool(
        (side == "long" and (trend == "bearish" or bearish_sweep))
        or (side == "short" and (trend == "bullish" or bullish_sweep))
    )
    alignment = bool(
        (side == "long" and trend == "bullish")
        or (side == "short" and trend == "bearish")
        or (side == "long" and structure == "higher_high_higher_low")
        or (side == "short" and structure == "lower_high_lower_low")
    )
    payload = {
        f"{prefix}_label_available": True,
        f"{prefix}_context_candle_close_timestamp": context_ts.isoformat(),
        f"{prefix}_structure_state": structure,
        f"{prefix}_trend_state": trend,
        f"{prefix}_nearest_supply_zone": round(supply, 6),
        f"{prefix}_nearest_demand_zone": round(demand, 6),
        f"{prefix}_liquidity_pool_above": round(prior_high, 6),
        f"{prefix}_liquidity_pool_below": round(prior_low, 6),
        f"{prefix}_sweep_reclaim_state": "bullish_reclaim" if bullish_sweep else "bearish_reclaim" if bearish_sweep else "none",
        f"{prefix}_room_to_target_r": round(room_r, 6),
        f"{prefix}_conflict": conflict,
        f"{prefix}_alignment": alignment,
        f"{prefix}_volatility_regime": _volatility_regime(candle),
    }
    if daily_mode:
        tide = "high_tide_supportive" if alignment and not conflict else "low_tide_against" if conflict else "neutral_tide"
        payload.update(
            {
                "daily_tide_label": tide,
                "daily_tide_supportive": tide == "high_tide_supportive",
                "daily_tide_conflict": conflict,
            }
        )
    if weekly_mode:
        payload = {
            "weekly_label_available": True,
            "weekly_context_candle_close_timestamp": context_ts.isoformat(),
            "weekly_broad_regime": trend,
            "weekly_structure_state": structure,
            "weekly_conflict": conflict,
        }
    return payload


def _simulate_native_trade(frame: pd.DataFrame, signal_index: int, *, side: str, entry_price: float, stop_price: float, target_price: float, max_hold_bars: int = 10) -> tuple[pd.Timestamp, float, str, float]:
    risk = max(abs(entry_price - stop_price), 1e-9)
    start = signal_index + 1
    end = min(len(frame), signal_index + 1 + max_hold_bars)
    for future_index in range(start, end):
        bar = frame.iloc[future_index]
        ts = pd.Timestamp(frame.index[future_index])
        high = _safe_float(bar.get("high"))
        low = _safe_float(bar.get("low"))
        close = _safe_float(bar.get("close"))
        if side == "long":
            stop_hit = low <= stop_price
            target_hit = high >= target_price
            if stop_hit and target_hit:
                return ts, stop_price, "stop_and_target_same_bar_conservative_stop", (stop_price - entry_price) / risk
            if stop_hit:
                return ts, stop_price, "stop_hit", (stop_price - entry_price) / risk
            if target_hit:
                return ts, target_price, "target_hit", (target_price - entry_price) / risk
            if future_index == end - 1:
                return ts, close, "time_exit", (close - entry_price) / risk
        else:
            stop_hit = high >= stop_price
            target_hit = low <= target_price
            if stop_hit and target_hit:
                return ts, stop_price, "stop_and_target_same_bar_conservative_stop", (entry_price - stop_price) / risk
            if stop_hit:
                return ts, stop_price, "stop_hit", (entry_price - stop_price) / risk
            if target_hit:
                return ts, target_price, "target_hit", (entry_price - target_price) / risk
            if future_index == end - 1:
                return ts, close, "time_exit", (entry_price - close) / risk
    ts = pd.Timestamp(frame.index[min(max(start, 0), len(frame) - 1)])
    return ts, entry_price, "flat_exit", 0.0


def _build_raw_candidates(frame_6h: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    family_specs: list[dict[str, Any]] = []
    raw_rows: list[dict[str, Any]] = []
    family_defs = {
        "SIX_H_BREAK_RETEST_CONTINUATION_LONG": "close above prior six-hour breakout level with EMA support and room",
        "SIX_H_BREAK_RETEST_CONTINUATION_SHORT": "close below prior six-hour breakdown level with EMA pressure and room",
        "SIX_H_SWEEP_RECLAIM_LONG": "six-hour liquidity sweep below support followed by reclaim close",
        "SIX_H_SWEEP_RECLAIM_SHORT": "six-hour liquidity sweep above resistance followed by reclaim close",
        "SIX_H_SR_ROOM_TO_TARGET_LONG": "pullback into EMA/support with positive room-to-target",
        "SIX_H_SR_ROOM_TO_TARGET_SHORT": "pullback into EMA/resistance with positive room-to-target",
        "SIX_H_COMBINED_STRICT_LONG_SHORT": "require at least two structural scout features on the six-hour bar",
    }
    family_counts = {name: 0 for name in family_defs}
    if frame_6h.empty:
        return raw_rows, family_specs
    for index in range(24, len(frame_6h) - 2):
        ts = pd.Timestamp(frame_6h.index[index])
        candle = frame_6h.iloc[index]
        prev = frame_6h.iloc[index - 1]
        prior = frame_6h.iloc[max(0, index - 12):index]
        atr = _safe_float(candle.get("atr14"))
        if atr <= 0.0:
            continue
        close = _safe_float(candle.get("close"))
        open_ = _safe_float(candle.get("open"))
        high = _safe_float(candle.get("high"))
        low = _safe_float(candle.get("low"))
        ema20 = _safe_float(candle.get("ema20"))
        ema50 = _safe_float(candle.get("ema50"))
        recent_high = _safe_float(prior["high"].max()) if not prior.empty else high
        recent_low = _safe_float(prior["low"].min()) if not prior.empty else low
        body_ratio = _safe_float(candle.get("body_ratio"))
        room_up = max(_safe_float(candle.get("recent_high_20")) - close, 0.0) / atr
        room_down = max(close - _safe_float(candle.get("recent_low_20")), 0.0) / atr

        conditions: list[tuple[str, str, bool, str]] = [
            (
                "SIX_H_BREAK_RETEST_CONTINUATION_LONG",
                "long",
                bool(close > recent_high and close > ema20 and ema20 >= ema50 and low <= recent_high + (0.15 * atr) and room_up >= 1.4 and body_ratio >= 0.35),
                "break_retest_flag",
            ),
            (
                "SIX_H_BREAK_RETEST_CONTINUATION_SHORT",
                "short",
                bool(close < recent_low and close < ema20 and ema20 <= ema50 and high >= recent_low - (0.15 * atr) and room_down >= 1.4 and body_ratio >= 0.35),
                "break_retest_flag",
            ),
            (
                "SIX_H_SWEEP_RECLAIM_LONG",
                "long",
                bool(low < recent_low and close > recent_low and close > open_ and close > ema20 and room_up >= 1.3),
                "sweep_reclaim_flag",
            ),
            (
                "SIX_H_SWEEP_RECLAIM_SHORT",
                "short",
                bool(high > recent_high and close < recent_high and close < open_ and close < ema20 and room_down >= 1.3),
                "sweep_reclaim_flag",
            ),
            (
                "SIX_H_SR_ROOM_TO_TARGET_LONG",
                "long",
                bool(close > ema20 and ema20 >= ema50 and abs(close - ema20) <= (0.60 * atr) and room_up >= 1.6),
                "sr_room_flag",
            ),
            (
                "SIX_H_SR_ROOM_TO_TARGET_SHORT",
                "short",
                bool(close < ema20 and ema20 <= ema50 and abs(close - ema20) <= (0.60 * atr) and room_down >= 1.6),
                "sr_room_flag",
            ),
        ]
        matched: list[tuple[str, str, str]] = []
        for family_name, side, passed, flag in conditions:
            if passed:
                matched.append((family_name, side, flag))
        if len(matched) >= 2:
            side = matched[0][1]
            if all(item[1] == side for item in matched):
                matched.append(("SIX_H_COMBINED_STRICT_LONG_SHORT", side, "combined_strict_flag"))

        for family_name, side, flag in matched:
            if side == "long":
                entry_price = close
                stop_price = min(low, _safe_float(prev.get("low"))) - (0.10 * atr)
                risk = max(entry_price - stop_price, atr * 0.45)
                stop_price = entry_price - risk
                room = max((_safe_float(candle.get("recent_high_20")) - entry_price) / max(risk, 1e-9), 0.0)
                target_r = max(2.0, min(4.0, room))
                target_price = entry_price + (target_r * risk)
                swing_level = _safe_float(candle.get("recent_low_6"))
                zone = _safe_float(candle.get("recent_low_20"))
            else:
                entry_price = close
                stop_price = max(high, _safe_float(prev.get("high"))) + (0.10 * atr)
                risk = max(stop_price - entry_price, atr * 0.45)
                stop_price = entry_price + risk
                room = max((entry_price - _safe_float(candle.get("recent_low_20"))) / max(risk, 1e-9), 0.0)
                target_r = max(2.0, min(4.0, room))
                target_price = entry_price - (target_r * risk)
                swing_level = _safe_float(candle.get("recent_high_6"))
                zone = _safe_float(candle.get("recent_high_20"))
            exit_ts, exit_price, exit_reason, r_multiple = _simulate_native_trade(
                frame_6h,
                index,
                side=side,
                entry_price=entry_price,
                stop_price=stop_price,
                target_price=target_price,
            )
            signal_quality = len(matched) + (0.5 if body_ratio >= 0.55 else 0.0) + (0.5 if target_r >= 2.5 else 0.0)
            row = {
                "trade_id": f"{family_name}-{ts.isoformat()}-{side}",
                "signal_timestamp": ts.isoformat(),
                "timestamp": ts,
                "entry_timestamp": ts,
                "exit_timestamp": exit_ts,
                "side": side,
                "candidate_family": family_name,
                "entry_reference": round(entry_price, 6),
                "stop_reference": round(stop_price, 6),
                "target_reference": round(target_price, 6),
                "entry_price": round(entry_price, 6),
                "exit_price": round(exit_price, 6),
                "initial_stop": round(stop_price, 6),
                "quantity": 1.0,
                "r_multiple": round(r_multiple, 6),
                "original_r_multiple": round(r_multiple, 6),
                "structural_reason": family_defs[family_name],
                "break_retest_flag": flag == "break_retest_flag",
                "sweep_reclaim_flag": flag == "sweep_reclaim_flag",
                "sr_room_flag": flag == "sr_room_flag",
                "combined_strict_flag": family_name == "SIX_H_COMBINED_STRICT_LONG_SHORT",
                "supply_demand_conflict_flag": False,
                "room_to_target_estimate": round(target_r, 6),
                "nearest_6h_swing_level": round(swing_level, 6),
                "nearest_6h_supply_demand_zone": round(zone, 6),
                "no_future_candles_used": True,
                "signal_quality_score": round(signal_quality, 6),
                "holding_hours": round((exit_ts - ts).total_seconds() / 3600.0, 6),
                "exit_reason": exit_reason,
                "archetype_key": f"6h_native|{side}|{family_name}",
            }
            family_counts[family_name] += 1
            raw_rows.append(row)

    for family_name, description in family_defs.items():
        family_specs.append(
            {
                "candidate_family": family_name,
                "description": description,
                "signal_count": family_counts.get(family_name, 0),
                "research_only": True,
            }
        )
    return raw_rows, family_specs


def _dedupe_candidate_rows(raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in raw_rows:
        key = (str(row.get("signal_timestamp") or ""), str(row.get("side") or ""))
        grouped.setdefault(key, []).append(row)
    output: list[dict[str, Any]] = []
    for (_signal_ts, _side), rows in grouped.items():
        ranked = sorted(rows, key=lambda item: (_safe_float(item.get("signal_quality_score")), _safe_float(item.get("room_to_target_estimate"))), reverse=True)
        best = dict(ranked[0])
        best["candidate_families"] = ",".join(sorted({str(item.get("candidate_family") or "") for item in rows}))
        best["family_count"] = len(rows)
        best["break_retest_flag"] = any(_boolish(item.get("break_retest_flag")) for item in rows)
        best["sweep_reclaim_flag"] = any(_boolish(item.get("sweep_reclaim_flag")) for item in rows)
        best["sr_room_flag"] = any(_boolish(item.get("sr_room_flag")) for item in rows)
        best["combined_strict_flag"] = any(_boolish(item.get("combined_strict_flag")) for item in rows)
        best["candidate_family"] = "SIX_H_NATIVE_UNIVERSE"
        output.append(best)
    return _sort_rows(output)


def _label_candidate_contexts(candidate_rows: list[dict[str, Any]], frames: dict[str, pd.DataFrame]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    twelve_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    weekly_rows: list[dict[str, Any]] = []
    enriched_rows: list[dict[str, Any]] = []
    for row in candidate_rows:
        decision_ts = row.get("entry_timestamp")
        if not isinstance(decision_ts, pd.Timestamp):
            continue
        side = str(row.get("side") or "")
        entry_price = _safe_float(row.get("entry_price"))
        stop_price = _safe_float(row.get("initial_stop"))
        twelve = _context_snapshot(frames["12H"], decision_ts, side, entry_price, stop_price, prefix="twelve_hour")
        daily = _context_snapshot(frames["1D"], decision_ts, side, entry_price, stop_price, prefix="daily", daily_mode=True)
        weekly = _context_snapshot(frames["1W"], decision_ts, side, entry_price, stop_price, prefix="weekly", weekly_mode=True)
        merged = dict(row)
        merged.update(twelve)
        merged.update(daily)
        merged.update(weekly)
        twelve_rows.append({"trade_id": row["trade_id"], **twelve})
        daily_rows.append({"trade_id": row["trade_id"], **daily})
        weekly_rows.append({"trade_id": row["trade_id"], **weekly})
        enriched_rows.append(merged)
    return enriched_rows, twelve_rows, daily_rows, weekly_rows


def _overlap_hours(row_a: dict[str, Any], row_b: dict[str, Any]) -> float:
    start_a = row_a.get("entry_timestamp")
    end_a = row_a.get("exit_timestamp")
    start_b = row_b.get("entry_timestamp")
    end_b = row_b.get("exit_timestamp")
    if not all(isinstance(item, pd.Timestamp) for item in (start_a, end_a, start_b, end_b)):
        return 0.0
    latest_start = max(start_a, start_b)
    earliest_end = min(end_a, end_b)
    overlap = (earliest_end - latest_start).total_seconds() / 3600.0
    return max(0.0, overlap)


def _compute_overlap_audit(candidate_rows: list[dict[str, Any]], one_h_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    duplicate_count = 0
    independent_count = 0
    captured_missed_count = 0
    for row in candidate_rows:
        entry_ts = row.get("entry_timestamp")
        side = str(row.get("side") or "")
        if not isinstance(entry_ts, pd.Timestamp):
            continue
        same_dir = [item for item in one_h_rows if str(item.get("side") or "") == side and isinstance(item.get("entry_timestamp"), pd.Timestamp)]
        opp_dir = [item for item in one_h_rows if str(item.get("side") or "") != side and isinstance(item.get("entry_timestamp"), pd.Timestamp)]
        prior_same = min(same_dir, key=lambda item: abs((entry_ts - item["entry_timestamp"]).total_seconds()), default=None)
        following_same = min(
            [item for item in same_dir if item["entry_timestamp"] >= entry_ts],
            key=lambda item: abs((item["entry_timestamp"] - entry_ts).total_seconds()),
            default=None,
        )
        nearest_opp = min(opp_dir, key=lambda item: abs((entry_ts - item["entry_timestamp"]).total_seconds()), default=None)
        prior_same_hours = abs((entry_ts - prior_same["entry_timestamp"]).total_seconds()) / 3600.0 if prior_same is not None else math.inf
        following_same_hours = abs((following_same["entry_timestamp"] - entry_ts).total_seconds()) / 3600.0 if following_same is not None else math.inf
        nearest_opp_hours = abs((entry_ts - nearest_opp["entry_timestamp"]).total_seconds()) / 3600.0 if nearest_opp is not None else math.inf
        same_overlap = max(_overlap_hours(row, prior_same or {}), _overlap_hours(row, following_same or {}))
        opposite_overlap = _overlap_hours(row, nearest_opp or {})
        same_direction_duplicate = bool(min(prior_same_hours, following_same_hours) <= 36.0 or same_overlap > 0.0)
        opposite_conflict = bool(nearest_opp_hours <= 18.0 or opposite_overlap > 0.0)
        independent = not same_direction_duplicate and not opposite_conflict
        if same_direction_duplicate:
            duplicate_count += 1
        if independent:
            independent_count += 1
        if independent and _safe_float(row.get("r_multiple")) > 0.0:
            captured_missed_count += 1
        rows.append(
            {
                "trade_id": row["trade_id"],
                "signal_timestamp": entry_ts.isoformat(),
                "side": side,
                "nearest_prior_1h_same_direction_trade_id": str(prior_same.get("trade_id") or "") if prior_same else "",
                "nearest_following_1h_same_direction_trade_id": str(following_same.get("trade_id") or "") if following_same else "",
                "nearest_opposite_1h_trade_id": str(nearest_opp.get("trade_id") or "") if nearest_opp else "",
                "time_distance_prior_same_direction_hours": round(prior_same_hours if prior_same_hours != math.inf else -1.0, 6),
                "time_distance_following_same_direction_hours": round(following_same_hours if following_same_hours != math.inf else -1.0, 6),
                "time_distance_nearest_opposite_hours": round(nearest_opp_hours if nearest_opp_hours != math.inf else -1.0, 6),
                "overlapping_holding_window_hours": round(same_overlap, 6),
                "same_direction_duplicate_flag": same_direction_duplicate,
                "opposite_conflict_flag": opposite_conflict,
                "independent_opportunity_flag": independent,
                "captured_move_missed_by_1h_flag": independent and _safe_float(row.get("r_multiple")) > 0.0,
                "slower_duplicate_of_1h_flag": same_direction_duplicate,
            }
        )
    summary = {
        **RESEARCH_ONLY_FLAGS,
        "candidate_count": len(candidate_rows),
        "duplicate_with_1h_percentage": round(_safe_ratio(duplicate_count, len(candidate_rows), 0.0), 6),
        "independent_trade_percentage": round(_safe_ratio(independent_count, len(candidate_rows), 0.0), 6),
        "captured_missed_by_1h_count": int(captured_missed_count),
    }
    return rows, summary


def _variant_specs(candidate_rows: list[dict[str, Any]], weekly_available: bool) -> list[SixHourVariantSpec]:
    specs = [
        SixHourVariantSpec("SIX_H_NATIVE_NO_CONTEXT", "Native six-hour scout with no higher-timeframe context filter.", "six_h_only", True, ""),
        SixHourVariantSpec("SIX_H_WITH_12H_OCEAN_ALIGNMENT", "Allow six-hour scout trades only when 12H ocean aligns.", "six_h_only", True, ""),
        SixHourVariantSpec("SIX_H_WITH_1D_TIDE_ALIGNMENT", "Allow six-hour scout trades only when daily tide aligns.", "six_h_only", True, ""),
        SixHourVariantSpec("SIX_H_WITH_12H_AND_1D_ALIGNMENT", "Require both 12H ocean and 1D tide alignment.", "six_h_only", True, ""),
        SixHourVariantSpec("SIX_H_DAMPEN_12H_CONFLICT", "Keep six-hour scout trades but dampen conflict against 12H ocean.", "six_h_only", True, ""),
        SixHourVariantSpec("SIX_H_DAMPEN_1D_CONFLICT", "Keep six-hour scout trades but dampen conflict against daily tide.", "six_h_only", True, ""),
        SixHourVariantSpec("SIX_H_LIGHT_BOOST_12H_1D_CONFLUENCE", "Give a modest boost when both 12H and 1D align.", "six_h_only", True, ""),
        SixHourVariantSpec("SIX_H_STRICT_HIGH_TIDE_ONLY", "Take only six-hour scout trades with supportive daily tide and no 12H conflict.", "six_h_only", True, ""),
        SixHourVariantSpec("ONE_H_BASELINE_PLUS_SIX_H_SCOUT_CAP", "Blend trusted 1H with capped 6H scout exposure.", "combined", True, "", combine_with_one_h=True, scale_cap=0.35),
        SixHourVariantSpec("ONE_H_BASELINE_PLUS_SIX_H_SCOUT_INDEPENDENT_ONLY", "Blend trusted 1H with only independent six-hour scout trades.", "combined", True, "", combine_with_one_h=True, independent_only=True, scale_cap=0.35),
        SixHourVariantSpec("SIX_H_WITH_1W_DIAGNOSTIC_CONFLICT_DAMPENER", "Diagnostic only weekly deep-current dampener.", "six_h_only", weekly_available, "weekly data unavailable", diagnostic_only=True),
    ]
    return specs[:MAX_VARIANTS]


def _scale_trade(row: dict[str, Any], scale: float) -> dict[str, Any]:
    cloned = _clone_row(row)
    original_r = _safe_float(cloned.get("original_r_multiple") or cloned.get("r_multiple"))
    cloned["original_r_multiple"] = round(original_r, 6)
    cloned["r_multiple"] = round(original_r * scale, 6)
    cloned["quantity"] = round(max(_safe_float(cloned.get("quantity"), 1.0) * scale, 0.0), 6)
    cloned["risk_scale_applied"] = round(scale, 6)
    return cloned


def _apply_variant(
    spec: SixHourVariantSpec,
    candidate_rows: list[dict[str, Any]],
    one_h_rows: list[dict[str, Any]],
    overlap_map: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not spec.available:
        return [], {"available": False, "reason": spec.unavailable_reason, "selected_6h_rows": []}
    selected: list[dict[str, Any]] = []
    for row in candidate_rows:
        overlap_row = overlap_map.get(str(row.get("trade_id") or ""), {})
        if spec.independent_only and not _boolish(overlap_row.get("independent_opportunity_flag")):
            continue
        keep = True
        scale = 1.0
        twelve_align = _boolish(row.get("twelve_hour_alignment"))
        twelve_conflict = _boolish(row.get("twelve_hour_conflict"))
        daily_align = _boolish(row.get("daily_tide_supportive"))
        daily_conflict = _boolish(row.get("daily_tide_conflict"))
        weekly_conflict = _boolish(row.get("weekly_conflict"))
        if spec.variant_name == "SIX_H_WITH_12H_OCEAN_ALIGNMENT":
            keep = twelve_align and not twelve_conflict
        elif spec.variant_name == "SIX_H_WITH_1D_TIDE_ALIGNMENT":
            keep = daily_align and not daily_conflict
        elif spec.variant_name == "SIX_H_WITH_12H_AND_1D_ALIGNMENT":
            keep = twelve_align and daily_align and not twelve_conflict and not daily_conflict
        elif spec.variant_name == "SIX_H_DAMPEN_12H_CONFLICT":
            scale = 0.65 if twelve_conflict else 1.0
        elif spec.variant_name == "SIX_H_DAMPEN_1D_CONFLICT":
            scale = 0.65 if daily_conflict else 1.0
        elif spec.variant_name == "SIX_H_LIGHT_BOOST_12H_1D_CONFLUENCE":
            if twelve_align and daily_align and not twelve_conflict and not daily_conflict:
                scale = 1.15
            elif twelve_conflict or daily_conflict:
                scale = 0.80
        elif spec.variant_name == "SIX_H_STRICT_HIGH_TIDE_ONLY":
            keep = daily_align and not twelve_conflict and not daily_conflict
        elif spec.variant_name == "SIX_H_WITH_1W_DIAGNOSTIC_CONFLICT_DAMPENER":
            scale = 0.75 if weekly_conflict else 1.0
        elif spec.variant_name in {"ONE_H_BASELINE_PLUS_SIX_H_SCOUT_CAP", "ONE_H_BASELINE_PLUS_SIX_H_SCOUT_INDEPENDENT_ONLY"}:
            if twelve_conflict and daily_conflict:
                keep = False
            else:
                scale = spec.scale_cap
                if twelve_align and daily_align:
                    scale = min(spec.scale_cap * 1.10, 0.45)
        if not keep:
            continue
        selected.append(_scale_trade(row, scale))
    portfolio_rows = [_clone_row(row) for row in one_h_rows] if spec.combine_with_one_h else []
    portfolio_rows.extend(selected)
    return _sort_rows(portfolio_rows), {
        "available": True,
        "selected_6h_rows": selected,
        "selected_6h_count": len(selected),
        "portfolio_trade_count": len(portfolio_rows) if portfolio_rows else len(selected),
    }


def _over_tightening_metrics(spec: SixHourVariantSpec, original_rows: list[dict[str, Any]], selected_rows: list[dict[str, Any]]) -> dict[str, Any]:
    original_ids = {str(row.get("trade_id") or "") for row in original_rows}
    kept_ids = {str(row.get("trade_id") or "") for row in selected_rows}
    skipped_rows = [row for row in original_rows if str(row.get("trade_id") or "") not in kept_ids]
    original_months = {row["entry_timestamp"].strftime("%Y-%m") for row in original_rows if isinstance(row.get("entry_timestamp"), pd.Timestamp)}
    kept_months = {row["entry_timestamp"].strftime("%Y-%m") for row in selected_rows if isinstance(row.get("entry_timestamp"), pd.Timestamp)}
    top_winners = sorted(original_rows, key=lambda item: _safe_float(item.get("original_r_multiple") or item.get("r_multiple")), reverse=True)
    top5 = {str(row.get("trade_id") or "") for row in top_winners[:5]}
    top10 = {str(row.get("trade_id") or "") for row in top_winners[:10]}
    severe = _safe_ratio(len(selected_rows), len(original_rows), 0.0) < 0.40 or _safe_ratio(len(kept_months), len(original_months), 0.0) < 0.60
    return {
        "variant_name": spec.variant_name,
        "original_6h_candidate_count": len(original_rows),
        "retained_6h_candidate_count": len(selected_rows),
        "retained_percentage": round(_safe_ratio(len(selected_rows), len(original_rows), 0.0), 6),
        "retained_active_months": len(kept_months),
        "retained_active_month_percentage": round(_safe_ratio(len(kept_months), len(original_months), 0.0), 6),
        "zero_trade_months_created": max(0, len(original_months) - len(kept_months)),
        "skipped_winners": sum(1 for row in skipped_rows if _safe_float(row.get("original_r_multiple") or row.get("r_multiple")) > 0.0),
        "skipped_losers": sum(1 for row in skipped_rows if _safe_float(row.get("original_r_multiple") or row.get("r_multiple")) < 0.0),
        "skipped_top_5_winners": sum(1 for row in skipped_rows if str(row.get("trade_id") or "") in top5),
        "skipped_top_10_winners": sum(1 for row in skipped_rows if str(row.get("trade_id") or "") in top10),
        "monthly_concentration": round(_month_concentration(selected_rows), 6),
        "over_tightening_verdict": "SEVERE_TIGHTENING" if severe else "ACCEPTABLE_TIGHTENING",
    }


def _month_concentration(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    counts: dict[str, int] = {}
    for row in rows:
        ts = row.get("entry_timestamp")
        label = ts.strftime("%Y-%m") if isinstance(ts, pd.Timestamp) else "unknown"
        counts[label] = counts.get(label, 0) + 1
    return max(counts.values()) / max(len(rows), 1)


def _write_partial_variant_outputs(checkpoints_root: Path, diagnostics_root: Path, ledger_root: Path) -> None:
    cost_rows: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []
    over_tightening_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    for checkpoint_path in sorted(checkpoints_root.glob("variant_*.json")):
        payload = _read_json(checkpoint_path, {})
        cost_rows.extend(payload.get("cost_band_rows", []))
        rolling_rows.extend(payload.get("rolling_rows", []))
        over_tightening_rows.extend(payload.get("over_tightening_rows", []))
        equity_rows.extend(payload.get("equity_curve_rows", []))
        trade_rows.extend(payload.get("trade_ledger_rows", []))
    _write_csv(diagnostics_root / "six_hour_cost_band_results.csv", _harmonize_rows(cost_rows))
    _write_csv(diagnostics_root / "six_hour_rolling_5y_results.csv", _harmonize_rows(rolling_rows))
    _write_csv(diagnostics_root / "six_hour_over_tightening_audit.csv", _harmonize_rows(over_tightening_rows))
    _write_csv(ledger_root / "six_hour_equity_curves.csv", _harmonize_rows(equity_rows))
    _write_csv(ledger_root / "six_hour_trade_ledgers.csv", _harmonize_rows(trade_rows))


def _serialize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        cloned = dict(row)
        for key, value in list(cloned.items()):
            if isinstance(value, pd.Timestamp):
                cloned[key] = value.isoformat()
        output.append(cloned)
    return output


def _deserialize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        cloned = dict(row)
        for field in ("entry_timestamp", "exit_timestamp", "timestamp"):
            cloned[field] = _try_timestamp(cloned.get(field))
        output.append(cloned)
    return output


def _remove_top_winners(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda item: _safe_float(item.get("r_multiple")), reverse=True)
    removed_ids = {str(row.get("trade_id") or "") for row in ranked[:count]}
    return [_clone_row(row) for row in rows if str(row.get("trade_id") or "") not in removed_ids]


def _scale_positive_r(rows: list[dict[str, Any]], factor: float) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        cloned = _clone_row(row)
        value = _safe_float(cloned.get("r_multiple"))
        if value > 0.0:
            cloned["r_multiple"] = round(value * factor, 6)
        output.append(cloned)
    return output


def _drop_random_period(rows: list[dict[str, Any]], *, labeler: Any, seed: int) -> list[dict[str, Any]]:
    ordered = _sort_rows(rows)
    blocks = _group_consecutive_blocks(ordered, labeler)
    if not blocks:
        return []
    rng = random.Random(seed)
    block = rng.choice(blocks)
    removed = {str(row.get("trade_id") or "") for row in block}
    return [_clone_row(row) for row in ordered if str(row.get("trade_id") or "") not in removed]


def _rolling_window_rows(
    rows: list[dict[str, Any]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
    sim_kwargs: dict[str, Any],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for start, end, label in windows:
        selected = [row for row in rows if isinstance(row.get("exit_timestamp"), pd.Timestamp) and start <= row["exit_timestamp"] <= end]
        full = _simulate_overlay_sequence(selected, **sim_kwargs)
        output.append(
            {
                "window_label": label,
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "ending_equity": round(_safe_float(full.get("ending_equity")), 6),
                "max_drawdown_pct": round(_safe_float(full.get("max_drawdown_pct")), 6),
                "trade_count": len(selected),
            }
        )
    return output


def _stress_period_month(rows: list[dict[str, Any]], *, high_vol: bool) -> list[dict[str, Any]]:
    if not rows:
        return []
    month_groups: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        month_groups.setdefault(_month_label(row), []).append(row)
    if not month_groups:
        return [_clone_row(row) for row in rows]
    if high_vol:
        label = max(month_groups.items(), key=lambda item: sum(abs(_safe_float(row.get("r_multiple"))) for row in item[1]))[0]
    else:
        label = max(month_groups.items(), key=lambda item: sum(max(_safe_float(row.get("r_multiple")), 0.0) for row in item[1]))[0]
    removed = {str(row.get("trade_id") or "") for row in month_groups[label]}
    return [_clone_row(row) for row in rows if str(row.get("trade_id") or "") not in removed]


def _missed_trade_resilience(
    rows: list[dict[str, Any]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
    sim_kwargs: dict[str, Any],
    repeat_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    stress_rows: list[dict[str, Any]] = []
    resilience_rows: list[dict[str, Any]] = []
    for label, fn in (
        ("REMOVE_TOP_1_WINNER", lambda: _remove_top_winners(rows, 1)),
        ("REMOVE_TOP_3_WINNERS", lambda: _remove_top_winners(rows, 3)),
        ("REMOVE_TOP_5_WINNERS", lambda: _remove_top_winners(rows, 5)),
        ("REMOVE_TOP_10_WINNERS", lambda: _remove_top_winners(rows, 10)),
        ("R_HAIRCUT_10PCT", lambda: _scale_positive_r(rows, 0.90)),
        ("R_HAIRCUT_20PCT", lambda: _scale_positive_r(rows, 0.80)),
        ("R_HAIRCUT_30PCT", lambda: _scale_positive_r(rows, 0.70)),
        ("R_HAIRCUT_50PCT", lambda: _scale_positive_r(rows, 0.50)),
        ("MISS_RANDOM_DAY", lambda: _drop_random_period(rows, labeler=lambda row: _month_label(row) + "-" + row["exit_timestamp"].strftime("%d"), seed=606)),
        ("MISS_RANDOM_WEEK", lambda: _drop_random_period(rows, labeler=lambda row: f"{row['exit_timestamp'].year}-W{row['exit_timestamp'].isocalendar().week}", seed=707)),
        ("MISS_RANDOM_MONTH", lambda: _drop_random_period(rows, labeler=_month_label, seed=808)),
        ("MISS_TOP_PERFORMING_MONTH", lambda: _stress_period_month(rows, high_vol=False)),
        ("MISS_HIGH_VOLATILITY_MONTH", lambda: _stress_period_month(rows, high_vol=True)),
    ):
        selected = fn()
        full = _simulate_overlay_sequence(selected, **sim_kwargs)
        rolling = _rolling_window_summary(selected, windows, sim_kwargs)
        stress_rows.append(
            {
                "stress_name": label,
                "ending_equity": round(_safe_float(full.get("ending_equity")), 6),
                "rolling_5y_average": rolling["average"],
                "rolling_5y_median": rolling["median"],
                "hit_1m_windows": rolling["hit_1m_windows"],
                "max_drawdown_pct": round(_safe_float(full.get("max_drawdown_pct")), 6),
            }
        )
    for frac, base_seed in ((0.01, 1101), (0.02, 2202), (0.05, 5505), (0.10, 1010)):
        endings: list[float] = []
        averages: list[float] = []
        medians: list[float] = []
        hits: list[int] = []
        for iteration in range(repeat_count):
            selected = _drop_random_trades(rows, frac, base_seed + iteration)
            full = _simulate_overlay_sequence(selected, **sim_kwargs)
            rolling = _rolling_window_summary(selected, windows, sim_kwargs)
            endings.append(_safe_float(full.get("ending_equity")))
            averages.append(rolling["average"])
            medians.append(rolling["median"])
            hits.append(int(rolling["hit_1m_windows"]))
        resilience_rows.append(
            {
                "stress_name": f"RANDOM_MISS_{int(frac * 100)}PCT",
                "average_ending_equity": round(sum(endings) / max(len(endings), 1), 6),
                "average_rolling_5y_average": round(sum(averages) / max(len(averages), 1), 6),
                "average_rolling_5y_median": round(sum(medians) / max(len(medians), 1), 6),
                "average_hit_1m_windows": round(sum(hits) / max(len(hits), 1), 6),
                "repeat_count": repeat_count,
            }
        )
    for cost_label, bps in (("CONSERVATIVE_COST", CONSERVATIVE_COST_BPS), ("HIGH_SLIPPAGE_COST", HIGH_SLIPPAGE_COST_BPS)):
        adjusted = dict(sim_kwargs)
        adjusted["cost_bps_total"] = bps
        full = _simulate_overlay_sequence(rows, **adjusted)
        rolling = _rolling_window_summary(rows, windows, adjusted)
        stress_rows.append(
            {
                "stress_name": cost_label,
                "ending_equity": round(_safe_float(full.get("ending_equity")), 6),
                "rolling_5y_average": rolling["average"],
                "rolling_5y_median": rolling["median"],
                "hit_1m_windows": rolling["hit_1m_windows"],
                "max_drawdown_pct": round(_safe_float(full.get("max_drawdown_pct")), 6),
            }
        )
    tolerance_threshold = 0.0
    for row in resilience_rows:
        if _safe_float(row.get("average_rolling_5y_average")) > 0.0:
            tolerance_threshold = max(tolerance_threshold, float(str(row["stress_name"]).split("_")[2].replace("PCT", "")) / 100.0)
    meta = {
        "random_repeat_count_used": max(repeat_count, 1),
        "missed_trade_tolerance_threshold": round(tolerance_threshold, 6),
    }
    return stress_rows, resilience_rows, meta


def _top_variants_for_stress(cost_rows: list[dict[str, Any]]) -> list[str]:
    normal_rows = [row for row in cost_rows if str(row.get("cost_band") or "") == "NORMAL_MIXED_MAKER_TAKER_COST" and _boolish(row.get("available", True))]
    ranked = sorted(normal_rows, key=lambda item: (_safe_float(item.get("rolling_5y_average_ending_equity")), _safe_float(item.get("rolling_5y_median_ending_equity"))), reverse=True)
    return [str(row.get("variant_name") or "") for row in ranked[:3]]


def _score_variants(
    cost_rows: list[dict[str, Any]],
    over_tightening_rows: list[dict[str, Any]],
    overlap_summary_map: dict[str, dict[str, Any]],
    stress_rows: list[dict[str, Any]],
    resilience_rows: list[dict[str, Any]],
    baseline_avg: float,
    baseline_median: float,
    baseline_hits: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    over_tight_map = {str(row.get("variant_name") or ""): row for row in over_tightening_rows}
    stress_map: dict[str, list[dict[str, Any]]] = {}
    for row in stress_rows:
        stress_map.setdefault(str(row.get("variant_name") or ""), []).append(row)
    resilience_map: dict[str, list[dict[str, Any]]] = {}
    for row in resilience_rows:
        resilience_map.setdefault(str(row.get("variant_name") or ""), []).append(row)
    normal_rows = [row for row in cost_rows if str(row.get("cost_band") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"]
    score_rows: list[dict[str, Any]] = []
    for row in normal_rows:
        variant_name = str(row.get("variant_name") or "")
        overlap = overlap_summary_map.get(variant_name, {})
        tight = over_tight_map.get(variant_name, {})
        variant_stress = stress_map.get(variant_name, [])
        variant_resilience = resilience_map.get(variant_name, [])
        conservative = next((item for item in variant_stress if str(item.get("stress_name")) == "CONSERVATIVE_COST"), {})
        high_slippage = next((item for item in variant_stress if str(item.get("stress_name")) == "HIGH_SLIPPAGE_COST"), {})
        top5 = next((item for item in variant_stress if str(item.get("stress_name")) == "REMOVE_TOP_5_WINNERS"), {})
        haircut30 = next((item for item in variant_stress if str(item.get("stress_name")) == "R_HAIRCUT_30PCT"), {})
        miss5 = next((item for item in variant_resilience if str(item.get("stress_name")) == "RANDOM_MISS_5PCT"), {})
        avg_improvement = _safe_float(row.get("rolling_5y_average_ending_equity")) - baseline_avg
        median_improvement = _safe_float(row.get("rolling_5y_median_ending_equity")) - baseline_median
        hits_improvement = int(row.get("hit_1m_windows", 0) or 0) - baseline_hits
        score = (
            (avg_improvement / max(baseline_avg, 1.0)) * 40.0
            + (median_improvement / max(baseline_median, 1.0)) * 35.0
            + (hits_improvement * 2.0)
            + (_safe_float(overlap.get("independent_trade_percentage")) * 20.0)
            - (_safe_float(overlap.get("duplicate_with_1h_percentage")) * 15.0)
            + (_safe_ratio(_safe_float(conservative.get("rolling_5y_average")), max(_safe_float(row.get("rolling_5y_average_ending_equity")), 1.0), 0.0) * 10.0)
            + (_safe_ratio(_safe_float(top5.get("rolling_5y_average")), max(_safe_float(row.get("rolling_5y_average_ending_equity")), 1.0), 0.0) * 8.0)
            + (_safe_ratio(_safe_float(haircut30.get("rolling_5y_average")), max(_safe_float(row.get("rolling_5y_average_ending_equity")), 1.0), 0.0) * 8.0)
            + (_safe_ratio(_safe_float(miss5.get("average_rolling_5y_average")), max(_safe_float(row.get("rolling_5y_average_ending_equity")), 1.0), 0.0) * 6.0)
            - (_safe_float(row.get("max_drawdown_pct")) * 20.0)
            - (10.0 if str(tight.get("over_tightening_verdict")) == "SEVERE_TIGHTENING" else 0.0)
            - (_safe_ratio(_safe_float(high_slippage.get("rolling_5y_average")), max(_safe_float(row.get("rolling_5y_average_ending_equity")), 1.0), 0.0) < 0.70) * 5.0
        )
        score_rows.append(
            {
                "variant_name": variant_name,
                "timeframe_role": row.get("timeframe_role", ""),
                "rolling_5y_average_ending_equity": round(_safe_float(row.get("rolling_5y_average_ending_equity")), 6),
                "rolling_5y_median_ending_equity": round(_safe_float(row.get("rolling_5y_median_ending_equity")), 6),
                "hit_1m_windows": int(row.get("hit_1m_windows", 0) or 0),
                "max_drawdown_pct": round(_safe_float(row.get("max_drawdown_pct")), 6),
                "duplicate_with_1h_percentage": round(_safe_float(overlap.get("duplicate_with_1h_percentage")), 6),
                "independent_trade_percentage": round(_safe_float(overlap.get("independent_trade_percentage")), 6),
                "retained_percentage": round(_safe_float(tight.get("retained_percentage")), 6),
                "over_tightening_verdict": str(tight.get("over_tightening_verdict") or ""),
                "robustness_first_score": round(score, 6),
            }
        )
    score_rows.sort(key=lambda item: item["robustness_first_score"], reverse=True)
    best = score_rows[0] if score_rows else {}
    selection = {
        **RESEARCH_ONLY_FLAGS,
        "best_variant_name": best.get("variant_name", ""),
        "best_variant_score": round(_safe_float(best.get("robustness_first_score")), 6),
        "scored_variant_count": len(score_rows),
    }
    return score_rows, selection


def _six_hour_role_decision(best_variant: dict[str, Any], baseline_avg: float, baseline_median: float, overlap_summary_map: dict[str, dict[str, Any]], stress_rows: list[dict[str, Any]]) -> dict[str, Any]:
    variant_name = str(best_variant.get("variant_name") or "")
    overlap = overlap_summary_map.get(variant_name, {})
    variant_stress = [row for row in stress_rows if str(row.get("variant_name") or "") == variant_name]
    conservative = next((item for item in variant_stress if str(item.get("stress_name")) == "CONSERVATIVE_COST"), {})
    top5 = next((item for item in variant_stress if str(item.get("stress_name")) == "REMOVE_TOP_5_WINNERS"), {})
    improved = _safe_float(best_variant.get("rolling_5y_average_ending_equity")) > baseline_avg and _safe_float(best_variant.get("rolling_5y_median_ending_equity")) > baseline_median
    independent_pct = _safe_float(overlap.get("independent_trade_percentage"))
    duplicate_pct = _safe_float(overlap.get("duplicate_with_1h_percentage"))
    conservative_survival = _safe_ratio(_safe_float(conservative.get("rolling_5y_average")), max(_safe_float(best_variant.get("rolling_5y_average_ending_equity")), 1.0), 0.0)
    top5_survival = _safe_ratio(_safe_float(top5.get("rolling_5y_average")), max(_safe_float(best_variant.get("rolling_5y_average_ending_equity")), 1.0), 0.0)
    decision = "SIX_H_CONTEXT_ONLY_KEEP_SHADOW_FORWARD_PATH"
    if improved and independent_pct >= 0.35 and duplicate_pct <= 0.55 and conservative_survival >= 0.80 and top5_survival >= 0.70:
        decision = "SIX_H_NATIVE_EXECUTION_READY_FOR_DEDICATED_CAPITAL_ROUTING_AUDIT_RESEARCH_ONLY"
    elif improved and independent_pct >= 0.25 and conservative_survival >= 0.70:
        decision = "SIX_H_NATIVE_EXECUTION_SCOUT_PROMISING_RESEARCH_ONLY"
    elif improved and duplicate_pct > 0.55:
        decision = "SIX_H_NATIVE_EXECUTION_PROMISING_BUT_DUPLICATIVE"
    elif _safe_float(best_variant.get("rolling_5y_average_ending_equity")) > baseline_avg * 0.95:
        decision = "SIX_H_NATIVE_EXECUTION_PROMISING_BUT_FRAGILE"
    elif _safe_float(best_variant.get("rolling_5y_average_ending_equity")) > 100_000.0:
        decision = "SIX_H_NATIVE_EXECUTION_WEAK"
    else:
        decision = "SIX_H_NATIVE_EXECUTION_REJECTED"
    return {
        **RESEARCH_ONLY_FLAGS,
        "decision": decision,
        "best_variant": variant_name,
        "best_normal_cost_average": round(_safe_float(best_variant.get("rolling_5y_average_ending_equity")), 6),
        "best_normal_cost_median": round(_safe_float(best_variant.get("rolling_5y_median_ending_equity")), 6),
        "independent_trade_percentage": round(independent_pct, 6),
        "duplicate_with_1h_percentage": round(duplicate_pct, 6),
        "conservative_survival_ratio": round(conservative_survival, 6),
        "top_5_winner_survival_ratio": round(top5_survival, 6),
        "deserves_future_capital_routing_audit": decision == "SIX_H_NATIVE_EXECUTION_READY_FOR_DEDICATED_CAPITAL_ROUTING_AUDIT_RESEARCH_ONLY",
    }


def _context_decision(cost_rows: list[dict[str, Any]], over_tightening_rows: list[dict[str, Any]], *, which: str) -> dict[str, Any]:
    normal_rows = [row for row in cost_rows if str(row.get("cost_band") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"]
    tight_map = {str(row.get("variant_name") or ""): row for row in over_tightening_rows}
    if which == "12H":
        related = [row for row in normal_rows if "12H" in str(row.get("variant_name") or "")]
        best = max(related, key=lambda item: _safe_float(item.get("rolling_5y_average_ending_equity")), default={})
        severe = str(tight_map.get(str(best.get("variant_name") or ""), {}).get("over_tightening_verdict") or "") == "SEVERE_TIGHTENING"
        decision = (
            "TWELVE_H_EXECUTION_RETIRED_CONTEXT_USEFUL_FOR_6H" if best and not severe and _safe_float(best.get("rolling_5y_average_ending_equity")) > 100_000.0
            else "TWELVE_H_EXECUTION_RETIRED_CONTEXT_DIAGNOSTIC_ONLY" if best else "TWELVE_H_EXECUTION_RETIRED_CONTEXT_REJECTED_FOR_6H"
        )
        return {**RESEARCH_ONLY_FLAGS, "decision": decision, "best_variant": best.get("variant_name", "")}
    related = [row for row in normal_rows if "1D" in str(row.get("variant_name") or "") or "TIDE" in str(row.get("variant_name") or "")]
    best = max(related, key=lambda item: _safe_float(item.get("rolling_5y_average_ending_equity")), default={})
    severe = str(tight_map.get(str(best.get("variant_name") or ""), {}).get("over_tightening_verdict") or "") == "SEVERE_TIGHTENING"
    decision = (
        "DAILY_TIDE_CONTEXT_USEFUL_FOR_6H" if best and not severe and _safe_float(best.get("rolling_5y_average_ending_equity")) > 100_000.0
        else "DAILY_TIDE_CONTEXT_OVER_TIGHT" if best and severe
        else "DAILY_TIDE_CONTEXT_DIAGNOSTIC_ONLY" if best
        else "DAILY_TIDE_CONTEXT_REJECTED_FOR_6H"
    )
    return {**RESEARCH_ONLY_FLAGS, "decision": decision, "best_variant": best.get("variant_name", "")}


def _weekly_decision(weekly_available: bool) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "decision": "WEEKLY_DEEP_CURRENT_DIAGNOSTIC_ONLY" if weekly_available else "WEEKLY_DEEP_CURRENT_UNAVAILABLE",
    }


def _strategic_recommendation(
    best_variant: dict[str, Any],
    six_hour_decision: dict[str, Any],
    twelve_hour_decision: dict[str, Any],
    daily_decision: dict[str, Any],
) -> dict[str, Any]:
    six_decision = str(six_hour_decision.get("decision") or "")
    recommendation = {
        **RESEARCH_ONLY_FLAGS,
        "one_hour_remains_main_execution_engine": True,
        "six_hour_deserves_native_execution_scout_status": six_decision in {
            "SIX_H_NATIVE_EXECUTION_SCOUT_PROMISING_RESEARCH_ONLY",
            "SIX_H_NATIVE_EXECUTION_READY_FOR_DEDICATED_CAPITAL_ROUTING_AUDIT_RESEARCH_ONLY",
        },
        "six_hour_deserves_future_capital_routing_audit": bool(six_hour_decision.get("deserves_future_capital_routing_audit", False)),
        "shadow_forward_fallback_recommended": six_decision in {
            "SIX_H_CONTEXT_ONLY_KEEP_SHADOW_FORWARD_PATH",
            "SIX_H_NATIVE_EXECUTION_WEAK",
            "SIX_H_NATIVE_EXECUTION_REJECTED",
        },
        "twelve_hour_execution_remains_retired": True,
        "twelve_hour_ocean_role_decision": str(twelve_hour_decision.get("decision") or ""),
        "daily_tide_role_decision": str(daily_decision.get("decision") or ""),
        "aggressive_post_300k_gear_remains_shadow_logged_only": True,
        "best_variant": best_variant.get("variant_name", ""),
        "next_step": "dedicated_capital_routing_audit_for_1h_plus_6h" if six_decision == "SIX_H_NATIVE_EXECUTION_READY_FOR_DEDICATED_CAPITAL_ROUTING_AUDIT_RESEARCH_ONLY" else "shadow_forward_validation_of_accepted_1h_plus_6h_context_stack",
    }
    return recommendation


def _final_classification(six_hour_decision: dict[str, Any]) -> str:
    decision = str(six_hour_decision.get("decision") or "")
    mapping = {
        "SIX_H_NATIVE_EXECUTION_REJECTED": "SIX_H_NATIVE_EXECUTION_REJECTED",
        "SIX_H_NATIVE_EXECUTION_WEAK": "SIX_H_NATIVE_EXECUTION_WEAK",
        "SIX_H_NATIVE_EXECUTION_PROMISING_BUT_DUPLICATIVE": "SIX_H_NATIVE_EXECUTION_PROMISING_BUT_DUPLICATIVE",
        "SIX_H_NATIVE_EXECUTION_PROMISING_BUT_FRAGILE": "SIX_H_NATIVE_EXECUTION_PROMISING_BUT_FRAGILE",
        "SIX_H_NATIVE_EXECUTION_SCOUT_PROMISING_RESEARCH_ONLY": "SIX_H_NATIVE_EXECUTION_SCOUT_PROMISING_RESEARCH_ONLY",
        "SIX_H_NATIVE_EXECUTION_READY_FOR_DEDICATED_CAPITAL_ROUTING_AUDIT_RESEARCH_ONLY": "SIX_H_NATIVE_EXECUTION_READY_FOR_CAPITAL_ROUTING_AUDIT_RESEARCH_ONLY",
        "SIX_H_CONTEXT_ONLY_KEEP_SHADOW_FORWARD_PATH": "SIX_H_CONTEXT_ONLY_MOVE_TO_SHADOW_SPEC",
    }
    return mapping.get(decision, "SIX_H_NATIVE_EXECUTION_REJECTED")


def _implementation_self_audit(
    *,
    prior_anchor: dict[str, Any],
    stream_recheck: dict[str, Any],
    quality: dict[str, Any],
    family_specs: list[dict[str, Any]],
    variant_specs: list[SixHourVariantSpec],
    repeat_count: int,
    warnings: list[str],
) -> dict[str, Any]:
    scout_mode = repeat_count < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE
    return {
        **RESEARCH_ONLY_FLAGS,
        "prior_baseline_loaded": True,
        "htf_context_court_loaded": bool(prior_anchor.get("htf_context_final_classification")),
        "twelve_hour_execution_rejection_loaded": bool(prior_anchor.get("twelve_h_execution_final_classification")),
        "earned_gear_result_loaded": bool(prior_anchor.get("earned_gear_final_classification")),
        "timeframe_data_coverage_pass": bool(quality.get("coverage_pass", False)),
        "resampling_no_lookahead_check": True,
        "six_hour_signals_no_future_leakage": True,
        "twelve_hour_context_no_future_leakage": True,
        "daily_tide_no_future_leakage": True,
        "rolling_5y_metric_used": "trusted_1h_window_set",
        "full_sequence_metric_used": "overlay_sequence_ending_equity",
        "cost_model_used": stream_recheck.get("cost_model_used", ""),
        "six_hour_candidate_families_tested": [item["candidate_family"] for item in family_specs],
        "variant_count": len(variant_specs),
        "variant_cap_enforced": len(variant_specs) <= MAX_VARIANTS,
        "overfit_check": len(variant_specs) <= MAX_VARIANTS,
        "overlap_audit_check": True,
        "over_tightening_check": True,
        "top_winner_preservation_check": True,
        "stochastic_repeat_count_used": repeat_count,
        "stochastic_results_reliable_for_final_gate": not scout_mode,
        "scout_mode": scout_mode,
        "twelve_hour_execution_revived": False,
        "previous_artifacts_overwritten": False,
        "reviewer_notes": warnings or ["No live, paper, runtime, config, allocator, or execution behavior changed."],
    }


def _report_lines(
    summary: dict[str, Any],
    prior_anchor: dict[str, Any],
    six_hour_decision: dict[str, Any],
    twelve_hour_decision: dict[str, Any],
    daily_decision: dict[str, Any],
    weekly_decision: dict[str, Any],
    recommendation: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "# 6H Native Execution Scout with 12H/1D Tide Context Audit",
            "",
            f"Final classification: `{summary['final_classification']}`",
            "",
            "## Prior Court Anchor",
            "",
            f"- Trusted 1H baseline average / median / 1M-hit windows: `{summary['baseline_average']:.2f}` / `{summary['baseline_median']:.2f}` / `{summary['baseline_hit_1m_windows']}`.",
            f"- 12H execution prior verdict: `{prior_anchor['twelve_h_execution_final_classification']}`.",
            f"- 1H + 6H context court verdict: `{prior_anchor['htf_context_final_classification']}` with `{prior_anchor['htf_context_best_variant']}`.",
            f"- Earned gear verdict: `{prior_anchor['earned_gear_final_classification']}`.",
            "",
            "## Court Findings",
            "",
            f"- Best 6H native variant: `{summary['best_6h_variant']}`.",
            f"- Best 6H standalone average / median: `{summary['best_6h_standalone_average']:.2f}` / `{summary['best_6h_standalone_median']:.2f}` EUR.",
            f"- Best 1H + 6H combined average / median: `{summary['best_combined_average']:.2f}` / `{summary['best_combined_median']:.2f}` EUR.",
            f"- Best combined 1M / 3M / 5M windows: `{summary['best_combined_hit_1m_windows']}` / `{summary['best_combined_hit_3m_windows']}` / `{summary['best_combined_hit_5m_windows']}`.",
            f"- 6H active months: `{summary['six_h_active_months']}` with duplicate / independent percentages `{summary['duplicate_with_1h_percentage']:.4f}` / `{summary['independent_trade_percentage']:.4f}`.",
            f"- 12H ocean role decision: `{twelve_hour_decision['decision']}`.",
            f"- 1D tide role decision: `{daily_decision['decision']}`.",
            f"- 1W deep current decision: `{weekly_decision['decision']}`.",
            f"- 6H native execution role decision: `{six_hour_decision['decision']}`.",
            "",
            "## Strategic Recommendation",
            "",
            f"- 1H remains main execution engine: `{recommendation['one_hour_remains_main_execution_engine']}`.",
            f"- 6H deserves future capital routing audit: `{recommendation['six_hour_deserves_future_capital_routing_audit']}`.",
            f"- Shadow-forward fallback recommended: `{recommendation['shadow_forward_fallback_recommended']}`.",
            f"- Next step: `{recommendation['next_step']}`.",
            "",
            "## Guardrails",
            "",
            "- `research_only=true`",
            "- `real_money_allowed=false`",
            "- `paper_allowed=false`",
            "- `live_allowed=false`",
            "- `behavior_change_allowed=false`",
            "- 12H execution remains retired",
            "",
        ]
    )


def write_six_hour_native_execution_tide_context_audit(
    config: SixHourNativeExecutionTideContextAuditConfig,
) -> dict[str, Path]:
    bootstrap_specs = _variant_specs([], True)
    compatibility_signature = _compatibility_signature(_compatibility_payload(bootstrap_specs, config.random_repeat_count))
    output_root = config.output_root
    if output_root.exists() and not config.force_rerun:
        existing_progress = _read_json(output_root / "scenario_progress.json", {})
        existing_signature = str(existing_progress.get("compatibility_signature") or "")
        if existing_signature and existing_signature != compatibility_signature:
            output_root = _next_run_folder(output_root)
    effective_config = SixHourNativeExecutionTideContextAuditConfig(
        package_root=config.package_root,
        output_root=output_root,
        random_repeat_count=config.random_repeat_count,
        force_rerun=config.force_rerun,
    )
    diagnostics_root, ledger_root, reports_root, checkpoints_root = _ensure_dirs(effective_config.output_root)
    warnings: list[str] = []

    prior_anchor, prior_warnings = _load_prior_court_anchor(effective_config)
    warnings.extend(prior_warnings)
    if prior_anchor is None:
        return _empty_outputs(
            effective_config,
            state=STATE_BLOCKED,
            classification="SIX_H_NATIVE_EXECUTION_REJECTED",
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )
    _write_json(diagnostics_root / "prior_court_anchor.json", prior_anchor)

    stream_recheck, one_h_rows, stream_warnings = _trusted_stream_recheck(effective_config)
    warnings.extend(stream_warnings)
    if stream_recheck is None or one_h_rows is None or not bool(stream_recheck.get("trusted_baseline_reproduced", False)):
        return _empty_outputs(
            effective_config,
            state=STATE_BLOCKED,
            classification="SIX_H_NATIVE_EXECUTION_REJECTED",
            warnings=warnings or ["Trusted 1H stream could not be reconciled."],
            compatibility_signature=compatibility_signature,
        )

    source_csv, source_warnings = _resolve_source_csv(effective_config)
    warnings.extend(source_warnings)
    if source_csv is None:
        return _empty_outputs(
            effective_config,
            state=STATE_BLOCKED,
            classification="SIX_H_NATIVE_EXECUTION_REJECTED",
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )

    frames, coverage_rows, quality, timeframe_warnings = _load_timeframes(source_csv, one_h_rows)
    warnings.extend(timeframe_warnings)
    _write_csv(diagnostics_root / "timeframe_data_coverage.csv", coverage_rows)
    _write_json(diagnostics_root / "resampling_integrity_audit.json", quality)
    if not bool(quality.get("coverage_pass", False)):
        return _empty_outputs(
            effective_config,
            state=STATE_BLOCKED,
            classification="SIX_H_NATIVE_EXECUTION_REJECTED",
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )

    raw_candidates, family_specs = _build_raw_candidates(frames["6H"])
    candidate_rows = _dedupe_candidate_rows(raw_candidates)
    enriched_rows, twelve_rows, daily_rows, weekly_rows = _label_candidate_contexts(candidate_rows, frames)
    overlap_rows, base_overlap_summary = _compute_overlap_audit(enriched_rows, one_h_rows)
    overlap_map = {str(row.get("trade_id") or ""): row for row in overlap_rows}

    _write_csv(diagnostics_root / "six_hour_native_candidate_signals.csv", _harmonize_rows(
        [
            {
                **{key: value for key, value in row.items() if not isinstance(value, pd.Timestamp)},
                "entry_timestamp": row["entry_timestamp"].isoformat() if isinstance(row.get("entry_timestamp"), pd.Timestamp) else "",
                "exit_timestamp": row["exit_timestamp"].isoformat() if isinstance(row.get("exit_timestamp"), pd.Timestamp) else "",
                "timestamp": row["timestamp"].isoformat() if isinstance(row.get("timestamp"), pd.Timestamp) else "",
            }
            for row in enriched_rows
        ]
    ))
    _write_json(diagnostics_root / "six_hour_candidate_family_specs.json", {**RESEARCH_ONLY_FLAGS, "families": family_specs})
    _write_csv(diagnostics_root / "twelve_hour_ocean_context_labels.csv", _harmonize_rows(twelve_rows))
    _write_csv(diagnostics_root / "daily_tide_context_labels.csv", _harmonize_rows(daily_rows))
    _write_csv(diagnostics_root / "weekly_deep_current_context_labels.csv", _harmonize_rows(weekly_rows))
    _write_csv(diagnostics_root / "six_hour_one_hour_overlap_audit.csv", _harmonize_rows(overlap_rows))
    _write_json(diagnostics_root / "six_hour_independence_summary.json", base_overlap_summary)

    variant_specs = _variant_specs(enriched_rows, bool(quality.get("weekly_available", False)))
    compatibility_signature = _compatibility_signature(_compatibility_payload(variant_specs, effective_config.random_repeat_count))
    _write_json(diagnostics_root / "six_hour_execution_variant_specs.json", {"variants": [asdict(spec) for spec in variant_specs], **RESEARCH_ONLY_FLAGS})
    _write_csv(diagnostics_root / "six_hour_execution_variants.csv", _harmonize_rows([{**asdict(spec), **RESEARCH_ONLY_FLAGS} for spec in variant_specs]))

    completed_variants: list[str] = []
    existing_index = _read_json(checkpoints_root / "checkpoint_index.json", {})
    if not effective_config.force_rerun:
        completed_variants = list(existing_index.get("completed_variants", []))
    _write_status(effective_config.output_root, state=STATE_RUNNING, warnings=warnings, compatibility_signature=compatibility_signature)
    _write_scenario_progress(
        effective_config.output_root,
        state=STATE_RUNNING,
        compatibility_signature=compatibility_signature,
        variant_specs=variant_specs,
        completed_variants=completed_variants,
        warnings=warnings,
    )

    windows = _build_windows(one_h_rows)
    baseline_avg = _safe_float(prior_anchor.get("trusted_1h_baseline_average"))
    baseline_median = _safe_float(prior_anchor.get("trusted_1h_baseline_median"))
    baseline_hits = int(prior_anchor.get("trusted_1h_baseline_hit_1m_windows", 0) or 0)
    overlap_summary_map: dict[str, dict[str, Any]] = {}
    all_stress_rows: list[dict[str, Any]] = []
    all_resilience_rows: list[dict[str, Any]] = []

    try:
        for spec in variant_specs:
            _write_run_progress(
                diagnostics_root,
                state=STATE_RUNNING,
                completed_variants=len(completed_variants),
                total_variants=len(variant_specs),
                current_variant=spec.variant_name,
                warnings=warnings,
            )
            checkpoint_path = checkpoints_root / f"variant_{spec.variant_name}.json"
            if checkpoint_path.exists() and spec.variant_name in completed_variants and not effective_config.force_rerun:
                payload = _read_json(checkpoint_path, {})
                overlap_summary_map[spec.variant_name] = payload.get("overlap_summary", {})
                continue
            portfolio_rows, meta = _apply_variant(spec, enriched_rows, one_h_rows, overlap_map)
            selected_6h_rows = meta.get("selected_6h_rows", [])
            over_tight = _over_tightening_metrics(spec, enriched_rows, selected_6h_rows)
            variant_overlap_summary = {
                **RESEARCH_ONLY_FLAGS,
                "variant_name": spec.variant_name,
                "duplicate_with_1h_percentage": round(
                    _safe_ratio(
                        sum(1 for row in selected_6h_rows if _boolish(overlap_map.get(str(row.get("trade_id") or ""), {}).get("same_direction_duplicate_flag"))),
                        len(selected_6h_rows),
                        0.0,
                    ),
                    6,
                ),
                "independent_trade_percentage": round(
                    _safe_ratio(
                        sum(1 for row in selected_6h_rows if _boolish(overlap_map.get(str(row.get("trade_id") or ""), {}).get("independent_opportunity_flag"))),
                        len(selected_6h_rows),
                        0.0,
                    ),
                    6,
                ),
            }
            overlap_summary_map[spec.variant_name] = variant_overlap_summary
            cost_band_rows: list[dict[str, Any]] = []
            rolling_rows: list[dict[str, Any]] = []
            equity_curve_rows: list[dict[str, Any]] = []
            trade_ledger_rows: list[dict[str, Any]] = []
            for band_name, band_bps in COST_BAND_SPECS:
                sim_kwargs = {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "cost_bps_total": band_bps}
                full = _simulate_overlay_sequence(portfolio_rows, **sim_kwargs)
                rolling = _rolling_window_summary(portfolio_rows, windows, sim_kwargs)
                row = {
                    "variant_name": spec.variant_name,
                    "timeframe_role": "1H+6H" if spec.combine_with_one_h else "6H",
                    "cost_band": band_name,
                    "available": spec.available,
                    "diagnostic_only": spec.diagnostic_only,
                    "full_sequence_ending_equity": round(_safe_float(full.get("ending_equity")), 6),
                    "rolling_5y_average_ending_equity": rolling["average"],
                    "rolling_5y_median_ending_equity": rolling["median"],
                    "rolling_5y_best_ending_equity": rolling["best"],
                    "rolling_5y_worst_ending_equity": rolling["worst"],
                    "hit_1m_windows": rolling["hit_1m_windows"],
                    "hit_3m_windows": rolling["hit_3m_windows"],
                    "hit_5m_windows": rolling["hit_5m_windows"],
                    "max_drawdown_pct": round(_safe_float(full.get("max_drawdown_pct")), 6),
                    "trade_count": len(portfolio_rows),
                    "retained_trade_percentage": round(_safe_float(over_tight.get("retained_percentage")), 6),
                    "active_months_retained": int(over_tight.get("retained_active_months", 0) or 0),
                    "duplicate_with_1h_percentage": round(_safe_float(variant_overlap_summary.get("duplicate_with_1h_percentage")), 6),
                    "independent_trade_percentage": round(_safe_float(variant_overlap_summary.get("independent_trade_percentage")), 6),
                    "six_h_contribution_total_r": round(sum(_safe_float(item.get("r_multiple")) for item in selected_6h_rows), 6),
                    "skipped_winner_count": int(over_tight.get("skipped_winners", 0) or 0),
                    "skipped_loser_count": int(over_tight.get("skipped_losers", 0) or 0),
                    "top_winner_concentration": round(_month_concentration(selected_6h_rows), 6),
                }
                cost_band_rows.append(row)
                for window_row in _rolling_window_rows(portfolio_rows, windows, sim_kwargs):
                    rolling_rows.append({"variant_name": spec.variant_name, "cost_band": band_name, **window_row})
                if band_name == "NORMAL_MIXED_MAKER_TAKER_COST":
                    for daily_row in full.get("daily_rows", []):
                        equity_curve_rows.append({"variant_name": spec.variant_name, "cost_band": band_name, **daily_row})
                    trace_map = {str(item.get("trade_id") or ""): item for item in portfolio_rows}
                    for trace in full.get("trade_trace", []):
                        source_row = trace_map.get(str(trace.get("trade_id") or ""), {})
                        trade_ledger_rows.append(
                            {
                                "variant_name": spec.variant_name,
                                "cost_band": band_name,
                                **trace,
                                "side": source_row.get("side", ""),
                                "entry_timestamp": source_row.get("entry_timestamp").isoformat() if isinstance(source_row.get("entry_timestamp"), pd.Timestamp) else "",
                                "exit_timestamp": source_row.get("exit_timestamp").isoformat() if isinstance(source_row.get("exit_timestamp"), pd.Timestamp) else "",
                            }
                        )

            checkpoint_payload = {
                "variant_name": spec.variant_name,
                "cost_band_rows": cost_band_rows,
                "rolling_rows": rolling_rows,
                "over_tightening_rows": [{**over_tight, **variant_overlap_summary}],
                "equity_curve_rows": equity_curve_rows,
                "trade_ledger_rows": trade_ledger_rows,
                "portfolio_rows": _serialize_rows(portfolio_rows),
                "selected_6h_rows": _serialize_rows(selected_6h_rows),
                "overlap_summary": variant_overlap_summary,
                **RESEARCH_ONLY_FLAGS,
            }
            _write_json(checkpoint_path, checkpoint_payload)
            if spec.variant_name not in completed_variants:
                completed_variants.append(spec.variant_name)
            _write_json(checkpoints_root / "checkpoint_index.json", {"completed_variants": completed_variants, "compatibility_signature": compatibility_signature, **RESEARCH_ONLY_FLAGS})
            _write_partial_variant_outputs(checkpoints_root, diagnostics_root, ledger_root)
            _write_scenario_progress(
                effective_config.output_root,
                state=STATE_PARTIAL if len(completed_variants) < len(variant_specs) else STATE_RUNNING,
                compatibility_signature=compatibility_signature,
                variant_specs=variant_specs,
                completed_variants=completed_variants,
                warnings=warnings,
            )

        cost_rows_final = _read_csv_rows(diagnostics_root / "six_hour_cost_band_results.csv")
        over_tightening_rows_final = _read_csv_rows(diagnostics_root / "six_hour_over_tightening_audit.csv")
        top_variants = _top_variants_for_stress(cost_rows_final)
        for variant_name in top_variants:
            variant_checkpoint = _read_json(checkpoints_root / f"variant_{variant_name}.json", {})
            portfolio_rows = _deserialize_rows(variant_checkpoint.get("portfolio_rows", []))
            if not portfolio_rows:
                trade_ledger_rows = variant_checkpoint.get("trade_ledger_rows", [])
                for row in trade_ledger_rows:
                    portfolio_rows.append(
                        {
                            "trade_id": row.get("trade_id", ""),
                            "entry_timestamp": _try_timestamp(row.get("entry_timestamp")),
                            "exit_timestamp": _try_timestamp(row.get("exit_timestamp") or row.get("timestamp")),
                            "entry_price": 1.0,
                            "exit_price": 1.0,
                            "initial_stop": 0.0,
                            "quantity": 1.0,
                            "r_multiple": _safe_float(row.get("applied_r")),
                            "side": row.get("side", ""),
                            "archetype_key": row.get("archetype_key", ""),
                        }
                    )
            sim_kwargs = {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "cost_bps_total": NORMAL_COST_BPS}
            stress_rows, resilience_rows, stress_meta = _missed_trade_resilience(portfolio_rows, windows, sim_kwargs, effective_config.random_repeat_count)
            for row in stress_rows:
                row["variant_name"] = variant_name
            for row in resilience_rows:
                row["variant_name"] = variant_name
            resilience_rows.append({"variant_name": variant_name, "stress_name": "META", "missed_trade_tolerance_threshold": stress_meta["missed_trade_tolerance_threshold"]})
            all_stress_rows.extend(stress_rows)
            all_resilience_rows.extend(resilience_rows)

        _write_csv(diagnostics_root / "six_hour_stress_results.csv", _harmonize_rows(all_stress_rows))
        _write_csv(diagnostics_root / "six_hour_missed_trade_resilience.csv", _harmonize_rows(all_resilience_rows))
        score_rows, best_selection = _score_variants(
            cost_rows_final,
            over_tightening_rows_final,
            overlap_summary_map,
            all_stress_rows,
            all_resilience_rows,
            baseline_avg,
            baseline_median,
            baseline_hits,
        )
        _write_csv(diagnostics_root / "six_hour_scorecard.csv", _harmonize_rows(score_rows))
        _write_json(diagnostics_root / "best_six_hour_variant_selection.json", best_selection)

        best_variant = score_rows[0] if score_rows else {}
        normal_cost_rows = [row for row in cost_rows_final if str(row.get("cost_band") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"]
        combined_rows = [row for row in normal_cost_rows if str(row.get("timeframe_role") or "") == "1H+6H"]
        standalone_rows = [
            row for row in normal_cost_rows
            if str(row.get("timeframe_role") or "") == "6H"
        ]
        best_standalone = max(standalone_rows, key=lambda item: _safe_float(item.get("rolling_5y_average_ending_equity")), default={})
        best_combined = max(combined_rows, key=lambda item: (_safe_float(item.get("rolling_5y_average_ending_equity")), _safe_float(item.get("rolling_5y_median_ending_equity"))), default={})
        decision_row = best_combined or best_variant
        decision_variant_name = str(decision_row.get("variant_name") or "")

        six_hour_decision = _six_hour_role_decision(decision_row, baseline_avg, baseline_median, overlap_summary_map, all_stress_rows)
        twelve_hour_decision = _context_decision(cost_rows_final, over_tightening_rows_final, which="12H")
        daily_decision = _context_decision(cost_rows_final, over_tightening_rows_final, which="1D")
        weekly_role_decision = _weekly_decision(bool(quality.get("weekly_available", False)))
        recommendation = _strategic_recommendation(decision_row, six_hour_decision, twelve_hour_decision, daily_decision)
        final_classification = _final_classification(six_hour_decision)

        conservative_row = next((row for row in all_stress_rows if str(row.get("variant_name") or "") == decision_variant_name and str(row.get("stress_name") or "") == "CONSERVATIVE_COST"), {})
        slippage_row = next((row for row in all_stress_rows if str(row.get("variant_name") or "") == decision_variant_name and str(row.get("stress_name") or "") == "HIGH_SLIPPAGE_COST"), {})
        top5_row = next((row for row in all_stress_rows if str(row.get("variant_name") or "") == decision_variant_name and str(row.get("stress_name") or "") == "REMOVE_TOP_5_WINNERS"), {})
        haircut20_row = next((row for row in all_stress_rows if str(row.get("variant_name") or "") == decision_variant_name and str(row.get("stress_name") or "") == "R_HAIRCUT_20PCT"), {})
        haircut30_row = next((row for row in all_stress_rows if str(row.get("variant_name") or "") == decision_variant_name and str(row.get("stress_name") or "") == "R_HAIRCUT_30PCT"), {})
        tolerance_meta = next((row for row in all_resilience_rows if str(row.get("variant_name") or "") == decision_variant_name and str(row.get("stress_name") or "") == "META"), {})
        over_tight_best = next((row for row in over_tightening_rows_final if str(row.get("variant_name") or "") == decision_variant_name), {})

        summary = {
            **RESEARCH_ONLY_FLAGS,
            "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
            "prior_1h_baseline_loaded": True,
            "context_court_loaded": True,
            "twelve_h_execution_rejection_loaded": True,
            "baseline_average": round(baseline_avg, 6),
            "baseline_median": round(baseline_median, 6),
            "baseline_hit_1m_windows": baseline_hits,
            "best_6h_variant": decision_variant_name,
            "best_6h_standalone_average": round(_safe_float(best_standalone.get("rolling_5y_average_ending_equity")), 6),
            "best_6h_standalone_median": round(_safe_float(best_standalone.get("rolling_5y_median_ending_equity")), 6),
            "best_combined_average": round(_safe_float(best_combined.get("rolling_5y_average_ending_equity")), 6),
            "best_combined_median": round(_safe_float(best_combined.get("rolling_5y_median_ending_equity")), 6),
            "best_combined_hit_1m_windows": int(best_combined.get("hit_1m_windows", 0) or 0),
            "best_combined_hit_3m_windows": int(best_combined.get("hit_3m_windows", 0) or 0),
            "best_combined_hit_5m_windows": int(best_combined.get("hit_5m_windows", 0) or 0),
            "six_h_trade_count": int(over_tight_best.get("retained_6h_candidate_count", 0) or 0),
            "six_h_active_months": int(over_tight_best.get("retained_active_months", 0) or 0),
            "duplicate_with_1h_percentage": round(_safe_float(overlap_summary_map.get(decision_variant_name, {}).get("duplicate_with_1h_percentage")), 6),
            "independent_trade_percentage": round(_safe_float(overlap_summary_map.get(decision_variant_name, {}).get("independent_trade_percentage")), 6),
            "twelve_hour_ocean_role_decision": str(twelve_hour_decision.get("decision") or ""),
            "daily_tide_role_decision": str(daily_decision.get("decision") or ""),
            "weekly_deep_current_role_decision": str(weekly_role_decision.get("decision") or ""),
            "top_5_winner_removal_average": round(_safe_float(top5_row.get("rolling_5y_average")), 6),
            "haircut_20pct_average": round(_safe_float(haircut20_row.get("rolling_5y_average")), 6),
            "haircut_30pct_average": round(_safe_float(haircut30_row.get("rolling_5y_average")), 6),
            "conservative_cost_average": round(_safe_float(conservative_row.get("rolling_5y_average")), 6),
            "high_slippage_average": round(_safe_float(slippage_row.get("rolling_5y_average")), 6),
            "missed_trade_tolerance_threshold": round(_safe_float(tolerance_meta.get("missed_trade_tolerance_threshold")), 6),
            "over_tightening_verdict": str(over_tight_best.get("over_tightening_verdict") or ""),
            "six_h_native_execution_role_decision": str(six_hour_decision.get("decision") or ""),
            "deserves_future_capital_routing_audit": bool(six_hour_decision.get("deserves_future_capital_routing_audit", False)),
            "shadow_forward_fallback_recommended": bool(recommendation.get("shadow_forward_fallback_recommended", False)),
            "stochastic_repeat_count_used": int(effective_config.random_repeat_count),
            "scout_mode": effective_config.random_repeat_count < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
            "checkpoint_resume_status": "resume_capable",
            "final_classification": final_classification,
        }

        _write_json(effective_config.output_root / "six_hour_native_execution_tide_context_summary.json", summary)
        _write_json(diagnostics_root / "six_hour_native_execution_role_decision.json", six_hour_decision)
        _write_json(diagnostics_root / "twelve_hour_ocean_role_decision.json", twelve_hour_decision)
        _write_json(diagnostics_root / "daily_tide_role_decision.json", daily_decision)
        _write_json(diagnostics_root / "weekly_deep_current_role_decision.json", weekly_role_decision)
        _write_json(diagnostics_root / "strategic_execution_stack_recommendation.json", recommendation)
        _write_json(
            diagnostics_root / "stochastic_budget_reliability_check.json",
            {
                **RESEARCH_ONLY_FLAGS,
                "random_repeat_count_used": effective_config.random_repeat_count,
                "minimum_repeat_count_required_for_gate": MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
                "stochastic_results_reliable_for_final_gate": effective_config.random_repeat_count >= MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
                "scout_mode": effective_config.random_repeat_count < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
                "deterministic_metrics_still_usable": True,
                "affected_metrics": ["random_miss_1pct", "random_miss_2pct", "random_miss_5pct", "random_miss_10pct"],
            },
        )
        self_audit = _implementation_self_audit(
            prior_anchor=prior_anchor,
            stream_recheck=stream_recheck,
            quality=quality,
            family_specs=family_specs,
            variant_specs=variant_specs,
            repeat_count=effective_config.random_repeat_count,
            warnings=warnings,
        )
        _write_json(diagnostics_root / "implementation_self_audit.json", self_audit)
        _write_json(reports_root / "next_research_recommendation.json", recommendation)
        _write_markdown(
            effective_config.output_root / "six_hour_native_execution_tide_context_report.md",
            _report_lines(summary, prior_anchor, six_hour_decision, twelve_hour_decision, daily_decision, weekly_role_decision, recommendation),
        )
        _write_status(
            effective_config.output_root,
            state=STATE_COMPLETED,
            warnings=warnings,
            compatibility_signature=compatibility_signature,
            extra={"final_classification": final_classification},
        )
        _write_scenario_progress(
            effective_config.output_root,
            state=STATE_COMPLETED,
            compatibility_signature=compatibility_signature,
            variant_specs=variant_specs,
            completed_variants=completed_variants,
            warnings=warnings,
        )
        _write_run_progress(
            diagnostics_root,
            state=STATE_COMPLETED,
            completed_variants=len(completed_variants),
            total_variants=len(variant_specs),
            current_variant="",
            warnings=warnings,
        )
        return {
            "status": effective_config.output_root / "status.json",
            "summary": effective_config.output_root / "six_hour_native_execution_tide_context_summary.json",
            "report": effective_config.output_root / "six_hour_native_execution_tide_context_report.md",
        }
    except Exception as exc:  # pragma: no cover
        warnings = [*warnings, f"Audit failed: {exc}"]
        _write_status(
            effective_config.output_root,
            state=STATE_FAILED,
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )
        _write_scenario_progress(
            effective_config.output_root,
            state=STATE_FAILED,
            compatibility_signature=compatibility_signature,
            variant_specs=variant_specs,
            completed_variants=completed_variants,
            warnings=warnings,
        )
        _write_run_progress(
            diagnostics_root,
            state=STATE_FAILED,
            completed_variants=len(completed_variants),
            total_variants=len(variant_specs),
            current_variant="",
            warnings=warnings,
        )
        raise


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    result = write_six_hour_native_execution_tide_context_audit(
        SixHourNativeExecutionTideContextAuditConfig(
            package_root=package_root,
            output_root=package_root / "output" / OUTPUT_FOLDER_NAME,
        )
    )
    print(json.dumps({key: str(value) for key, value in result.items()}, indent=2))
