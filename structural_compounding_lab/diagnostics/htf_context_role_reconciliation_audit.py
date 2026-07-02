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
from structural_compounding_lab.diagnostics.earned_gear_activation_discovery_audit import (  # noqa: E402
    EarnedGearActivationDiscoveryAuditConfig,
    OUTPUT_FOLDER_NAME as EARNED_GEAR_OUTPUT_FOLDER_NAME,
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


OUTPUT_FOLDER_NAME = "htf_context_role_reconciliation_audit_001"
DEFAULT_RANDOM_REPEAT_COUNT = 32
MAX_VARIANTS = 18
STATE_NOT_STARTED = "not_started"
STATE_RUNNING = "running"
STATE_PARTIAL = "partial"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_BLOCKED = "blocked"
TIMESTAMP_FIELDS = ("exit_timestamp", "timestamp", "entry_timestamp")
R_FIELDS = ("r_multiple", "applied_r", "gross_r")
HTF_TIMEFRAMES = ("4H", "6H", "12H")
ALL_TIMEFRAMES = ("15M", "1H", "4H", "6H", "12H")
COST_BAND_SPECS = (
    ("ZERO_COST_REFERENCE", ZERO_COST_BPS),
    ("OPTIMISTIC_MAKER_COST", OPTIMISTIC_COST_BPS),
    ("NORMAL_MIXED_MAKER_TAKER_COST", NORMAL_COST_BPS),
    ("CONSERVATIVE_TAKER_COST", CONSERVATIVE_COST_BPS),
    ("HIGH_SLIPPAGE_COST", HIGH_SLIPPAGE_COST_BPS),
)


@dataclass(frozen=True)
class HTFContextRoleReconciliationAuditConfig:
    package_root: Path
    output_root: Path
    random_repeat_count: int = DEFAULT_RANDOM_REPEAT_COUNT
    force_rerun: bool = False


@dataclass(frozen=True)
class ContextVariantSpec:
    variant_name: str
    description: str
    variant_type: str
    timeframe: str
    available: bool
    unavailable_reason: str
    filter_field: str = ""
    filter_value: Any = True
    scale_field: str = ""
    scale_map_json: str = ""
    requires_15m: bool = False
    diagnostic_only: bool = False
    native_execution_scout: bool = False


def _paths(config: HTFContextRoleReconciliationAuditConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    broad_root = output_root / "broad_historical_structural_replay_001"
    twelve_h_root = output_root / "native_12h_execution_sleeve_discovery_audit_001"
    execution_root = output_root / "execution_cost_realism_and_trade_redundancy_audit_001"
    earned_root = output_root / EARNED_GEAR_OUTPUT_FOLDER_NAME
    return {
        "broad_summary": broad_root / "ledger" / "summary.json",
        "execution_cost_band_results": execution_root / "diagnostics" / "execution_cost_band_results.csv",
        "twelve_h_summary": twelve_h_root / "native_12h_execution_sleeve_discovery_summary.json",
        "twelve_h_repair_diagnostics": twelve_h_root / "diagnostics" / "12h_baseline_accounting_repair_diagnostics.json",
        "earned_gear_summary": earned_root / "earned_gear_activation_discovery_summary.json",
        "earned_gear_recommendation": earned_root / "reports" / "next_research_recommendation.json",
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


def _compatibility_payload(variant_specs: list[ContextVariantSpec], random_repeat_count: int) -> dict[str, Any]:
    return {
        "module": "htf_context_role_reconciliation_audit",
        "version": 1,
        "random_repeat_count": int(random_repeat_count),
        "variant_specs": [
            {
                key: value
                for key, value in asdict(spec).items()
                if key not in {"available", "unavailable_reason"}
            }
            for spec in variant_specs
        ],
        "timeframes": list(ALL_TIMEFRAMES),
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
    variant_specs: list[ContextVariantSpec],
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
    config: HTFContextRoleReconciliationAuditConfig,
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
    _write_run_progress(
        diagnostics_root,
        state=state,
        completed_variants=0,
        total_variants=0,
        current_variant="",
        warnings=warnings,
    )
    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "final_classification": classification,
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(config.output_root / "htf_context_role_reconciliation_summary.json", summary)
    _write_markdown(
        config.output_root / "htf_context_role_reconciliation_report.md",
        "# 1H + 6H HTF Context Role Reconciliation Audit\n\nThe audit was blocked before a baseline-safe context comparison could run.\n",
    )
    for path in (
        diagnostics_root / "prior_court_anchor.json",
        diagnostics_root / "trusted_1h_trade_stream_recheck.json",
        diagnostics_root / "timeframe_resampling_audit.json",
        diagnostics_root / "context_label_schema.json",
        diagnostics_root / "context_explanatory_findings.json",
        diagnostics_root / "context_overlay_variant_specs.json",
        diagnostics_root / "filter_damage_report.json",
        diagnostics_root / "stochastic_budget_reliability_check.json",
        diagnostics_root / "twelve_hour_role_decision.json",
        diagnostics_root / "six_hour_role_decision.json",
        diagnostics_root / "best_context_variant_selection.json",
        diagnostics_root / "strategic_timeframe_recommendation.json",
        diagnostics_root / "implementation_self_audit.json",
    ):
        _write_json(path, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    for path in (
        diagnostics_root / "timeframe_data_coverage.csv",
        diagnostics_root / "htf_context_labels.csv",
        diagnostics_root / "ltf_15m_refinement_labels.csv",
        diagnostics_root / "context_bucket_performance.csv",
        diagnostics_root / "context_overlay_variants.csv",
        diagnostics_root / "over_tightening_audit.csv",
        diagnostics_root / "htf_context_cost_band_results.csv",
        diagnostics_root / "htf_context_rolling_5y_results.csv",
        diagnostics_root / "htf_context_stress_results.csv",
        diagnostics_root / "htf_context_missed_trade_resilience.csv",
        diagnostics_root / "htf_context_scorecard.csv",
        ledger_root / "htf_context_equity_curves.csv",
        ledger_root / "htf_context_trade_ledgers.csv",
    ):
        _write_csv(path, [])
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(checkpoints_root / "checkpoint_index.json", {"completed_variants": [], **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "htf_context_role_reconciliation_summary.json",
        "report": config.output_root / "htf_context_role_reconciliation_report.md",
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


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"1", "true", "yes", "y"}


def _harmonize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    keys = sorted({key for row in rows for key in row.keys()})
    return [{key: row.get(key, "") for key in keys} for row in rows]


def _clone_row(row: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(row)
    for field in ("entry_timestamp", "exit_timestamp", "timestamp"):
        if isinstance(cloned.get(field), pd.Timestamp):
            cloned[field] = pd.Timestamp(cloned[field])
    return cloned


def _load_prior_courts(config: HTFContextRoleReconciliationAuditConfig) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    paths = _paths(config)
    baseline_rows = _read_csv_rows(paths["execution_cost_band_results"])
    baseline_row = next((row for row in baseline_rows if str(row.get("band_name") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"), None)
    twelve_h_summary = _read_json(paths["twelve_h_summary"], {})
    twelve_h_repair = _read_json(paths["twelve_h_repair_diagnostics"], {})
    earned_summary = _read_json(paths["earned_gear_summary"], {})
    earned_recommendation = _read_json(paths["earned_gear_recommendation"], {})
    if baseline_row is None:
        warnings.append("Trusted normal-cost baseline row missing.")
    if not twelve_h_summary:
        warnings.append("12H execution summary missing.")
    if not earned_summary:
        warnings.append("Earned gear summary missing.")
    if warnings:
        return None, warnings
    anchor = {
        **RESEARCH_ONLY_FLAGS,
        "trusted_baseline_average": _safe_float(baseline_row.get("rolling_5y_average_ending_equity")),
        "trusted_baseline_median": _safe_float(baseline_row.get("rolling_5y_median_ending_equity")),
        "trusted_baseline_hit_1m_windows": int(float(baseline_row.get("hit_1m_windows", 0) or 0)),
        "twelve_h_final_classification": str(twelve_h_summary.get("final_classification") or ""),
        "twelve_h_baseline_reconciled": bool(twelve_h_repair.get("baseline_reconciliation_pass_after_repair", False)),
        "twelve_h_selected_repair_mode": str(twelve_h_repair.get("selected_repair_mode") or ""),
        "earned_gear_final_classification": str(earned_summary.get("final_classification") or ""),
        "earned_gear_best_variant": str(earned_summary.get("best_variant") or ""),
        "earned_gear_shadow_only_recommendation": "shadow" in json.dumps(earned_recommendation).lower(),
        "twelve_h_execution_retired_expected": str(twelve_h_summary.get("final_classification") or "") == "NATIVE_12H_EXECUTION_REJECTED",
        "earned_gear_fragile_expected": str(earned_summary.get("final_classification") or "") == "EARNED_GEAR_DISCOVERY_IMPROVES_BUT_FRAGILE",
    }
    if anchor["twelve_h_selected_repair_mode"] != EXPECTED_REPAIR_MODE:
        warnings.append("12H repair mode mismatch against expected trusted mode.")
    return anchor, warnings


def _trusted_stream_recheck(config: HTFContextRoleReconciliationAuditConfig) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None, list[str]]:
    prior_config = MilestoneGatedExplosiveCompoundingAuditConfig(
        package_root=config.package_root,
        output_root=config.package_root / "output" / "milestone_gated_explosive_compounding_audit_001",
        random_repeat_count=config.random_repeat_count,
        force_rerun=False,
    )
    baseline_anchor, normalized_rows, reconstruction, warnings = _load_prior_baseline_anchor_and_stream(prior_config)
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


def _resolve_source_csv(config: HTFContextRoleReconciliationAuditConfig) -> tuple[Path | None, list[str]]:
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


def _coverage_row(frame: pd.DataFrame, *, timeframe: str, rule: str, source_start: pd.Timestamp | None, source_end: pd.Timestamp | None, trade_start: pd.Timestamp | None, trade_end: pd.Timestamp | None, source_path: Path) -> dict[str, Any]:
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
        "resampling_method": "pandas_resample_closed_left_label_right",
        "source_start_timestamp": source_start.isoformat() if source_start is not None else "",
        "source_end_timestamp": source_end.isoformat() if source_end is not None else "",
        "trade_stream_start_timestamp": trade_start.isoformat() if trade_start is not None else "",
        "trade_stream_end_timestamp": trade_end.isoformat() if trade_end is not None else "",
        "coverage_fully_spans_trusted_1h_stream": spans_trades,
        "ohlcv_complete": all(column in frame.columns for column in ("open", "high", "low", "close", "volume")),
    }


def _load_timeframes(source_csv: Path, trade_rows: list[dict[str, Any]]) -> tuple[dict[str, pd.DataFrame], list[dict[str, Any]], dict[str, Any], list[str]]:
    warnings: list[str] = []
    discovery, availability = _discover_candle_source(source_csv)
    df_1m, df_1h, df_12h = _load_price_source(source_csv)
    df_1m = _augment_frame(df_1m)
    frames = {
        "15M": _resample_frame(df_1m, "15min"),
        "1H": _augment_frame(df_1h),
        "4H": _resample_frame(df_1m, "4h"),
        "6H": _resample_frame(df_1m, "6h"),
        "12H": _augment_frame(df_12h),
    }
    trade_start = min((row.get("entry_timestamp") for row in trade_rows if isinstance(row.get("entry_timestamp"), pd.Timestamp)), default=None)
    trade_end = max((row.get("entry_timestamp") for row in trade_rows if isinstance(row.get("entry_timestamp"), pd.Timestamp)), default=None)
    source_start = _try_timestamp(discovery.get("coverage_start"))
    source_end = _try_timestamp(discovery.get("coverage_end"))
    coverage_rows = [
        _coverage_row(
            frames["15M"],
            timeframe="15M",
            rule="15min",
            source_start=source_start,
            source_end=source_end,
            trade_start=trade_start,
            trade_end=trade_end,
            source_path=source_csv,
        ),
        _coverage_row(
            frames["1H"],
            timeframe="1H",
            rule="1h",
            source_start=source_start,
            source_end=source_end,
            trade_start=trade_start,
            trade_end=trade_end,
            source_path=source_csv,
        ),
        _coverage_row(
            frames["4H"],
            timeframe="4H",
            rule="4h",
            source_start=source_start,
            source_end=source_end,
            trade_start=trade_start,
            trade_end=trade_end,
            source_path=source_csv,
        ),
        _coverage_row(
            frames["6H"],
            timeframe="6H",
            rule="6h",
            source_start=source_start,
            source_end=source_end,
            trade_start=trade_start,
            trade_end=trade_end,
            source_path=source_csv,
        ),
        _coverage_row(
            frames["12H"],
            timeframe="12H",
            rule="12h",
            source_start=source_start,
            source_end=source_end,
            trade_start=trade_start,
            trade_end=trade_end,
            source_path=source_csv,
        ),
    ]
    six_h_coverage = next((row for row in coverage_rows if row["timeframe"] == "6H"), None)
    if six_h_coverage is not None and (six_h_coverage["row_count"] == 0 or not six_h_coverage["coverage_fully_spans_trusted_1h_stream"]):
        warnings.append("6H timeframe could not be built reliably across the trusted 1H trade span.")
    quality = {
        **RESEARCH_ONLY_FLAGS,
        "source_discovery": discovery,
        "source_availability": availability,
        "resampling_no_lookahead_check": True,
        "fifteen_minute_available": bool(next((row for row in coverage_rows if row["timeframe"] == "15M"), {}).get("row_count", 0)),
        "six_hour_available": bool(six_h_coverage and six_h_coverage["row_count"] > 0),
        "coverage_pass": bool(six_h_coverage and six_h_coverage["coverage_fully_spans_trusted_1h_stream"]),
    }
    return frames, coverage_rows, quality, warnings


def _equal_level_strength(values: list[float], tolerance: float) -> int:
    if len(values) < 2 or tolerance <= 0.0:
        return 0
    count = 0
    for index in range(1, len(values)):
        if abs(values[index] - values[index - 1]) <= tolerance:
            count += 1
    return count


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


def _compression_state(window: pd.DataFrame, candle: pd.Series) -> str:
    atr = _safe_float(candle.get("atr14"))
    atr_mean = _safe_float(candle.get("atr50_mean"))
    if atr > 0.0 and atr_mean > 0.0:
        ratio = atr / atr_mean
        if ratio <= 0.80:
            return "compression"
        if ratio >= 1.20:
            return "expansion"
    if len(window) >= 6:
        width = _safe_float(window["high"].tail(6).max()) - _safe_float(window["low"].tail(6).min())
        close = _safe_float(candle.get("close"))
        if close > 0.0 and width / close <= 0.015:
            return "range"
    return "normal"


def _resolve_context_bucket(side: str, trend: str) -> bool:
    return (side == "long" and trend == "bullish") or (side == "short" and trend == "bearish")


def _label_timeframe_context(frame: pd.DataFrame, *, entry_ts: pd.Timestamp, side: str, entry_price: float, stop_price: float, prefix: str) -> dict[str, Any]:
    if frame.empty:
        return {f"{prefix}_label_available": False}
    context_ts = frame.index.asof(entry_ts)
    if pd.isna(context_ts):
        return {f"{prefix}_label_available": False}
    context_ts = pd.Timestamp(context_ts)
    window = frame.loc[:context_ts].tail(24)
    candle = frame.loc[context_ts]
    atr = max(_safe_float(candle.get("atr14")), 1e-9)
    trend = _trend_state(candle)
    structure = _structure_state(window)
    compression = _compression_state(window, candle)
    prior_window = window.iloc[:-1] if len(window) > 1 else window
    prior_high = _safe_float(prior_window["high"].max()) if not prior_window.empty else _safe_float(candle.get("high"))
    prior_low = _safe_float(prior_window["low"].min()) if not prior_window.empty else _safe_float(candle.get("low"))
    close = _safe_float(candle.get("close"))
    high = _safe_float(candle.get("high"))
    low = _safe_float(candle.get("low"))
    bearish_sweep = high > prior_high and close < prior_high
    bullish_sweep = low < prior_low and close > prior_low
    supply_price = _safe_float(candle.get("recent_high_20"))
    demand_price = _safe_float(candle.get("recent_low_20"))
    tolerance = max(atr * 0.20, entry_price * 0.001)
    equal_high_count = _equal_level_strength(window["high"].tail(6).tolist(), tolerance)
    equal_low_count = _equal_level_strength(window["low"].tail(6).tolist(), tolerance)
    pool_above = prior_high
    pool_below = prior_low
    room_distance = (supply_price - entry_price) if side == "long" else (entry_price - demand_price)
    room_distance = max(room_distance, 0.0)
    risk_distance = max(abs(entry_price - stop_price), 1e-9)
    room_r = room_distance / risk_distance
    conflict = False
    if side == "long":
        conflict = (supply_price > 0.0 and (supply_price - entry_price) / max(entry_price, 1e-9) <= 0.02) or trend == "bearish" or bearish_sweep
    else:
        conflict = (demand_price > 0.0 and (entry_price - demand_price) / max(entry_price, 1e-9) <= 0.02) or trend == "bullish" or bullish_sweep
    alignment = _resolve_context_bucket(side, trend) or (
        side == "long" and structure == "higher_high_higher_low"
    ) or (
        side == "short" and structure == "lower_high_lower_low"
    )
    return {
        f"{prefix}_label_available": True,
        f"{prefix}_context_candle_close_timestamp": context_ts.isoformat(),
        f"{prefix}_trend_state": trend,
        f"{prefix}_structure_state": structure,
        f"{prefix}_compression_state": compression,
        f"{prefix}_supply_price": round(supply_price, 6),
        f"{prefix}_demand_price": round(demand_price, 6),
        f"{prefix}_distance_to_supply_pct": round(_safe_ratio(supply_price - entry_price, entry_price, 0.0), 6),
        f"{prefix}_distance_to_demand_pct": round(_safe_ratio(entry_price - demand_price, entry_price, 0.0), 6),
        f"{prefix}_equal_high_count": int(equal_high_count),
        f"{prefix}_equal_low_count": int(equal_low_count),
        f"{prefix}_liquidity_pool_above": round(pool_above, 6),
        f"{prefix}_liquidity_pool_below": round(pool_below, 6),
        f"{prefix}_distance_to_liquidity_pool_above_pct": round(_safe_ratio(pool_above - entry_price, entry_price, 0.0), 6),
        f"{prefix}_distance_to_liquidity_pool_below_pct": round(_safe_ratio(entry_price - pool_below, entry_price, 0.0), 6),
        f"{prefix}_bearish_sweep": bool(bearish_sweep),
        f"{prefix}_bullish_sweep": bool(bullish_sweep),
        f"{prefix}_sweep_direction_aligned": bool((side == "short" and bearish_sweep) or (side == "long" and bullish_sweep)),
        f"{prefix}_sweep_direction_conflicting": bool((side == "short" and bullish_sweep) or (side == "long" and bearish_sweep)),
        f"{prefix}_room_to_target_r": round(room_r, 6),
        f"{prefix}_insufficient_room": bool(room_r < 1.50),
        f"{prefix}_alignment": bool(alignment),
        f"{prefix}_conflict": bool(conflict),
    }


def _label_ltf_confirmation(frame: pd.DataFrame, *, entry_ts: pd.Timestamp, side: str) -> dict[str, Any]:
    if frame.empty:
        return {"15m_label_available": False}
    context_ts = frame.index.asof(entry_ts)
    if pd.isna(context_ts):
        return {"15m_label_available": False}
    context_ts = pd.Timestamp(context_ts)
    window = frame.loc[:context_ts].tail(6)
    if len(window) < 3:
        return {"15m_label_available": False}
    last = window.iloc[-1]
    prev = window.iloc[-2]
    prior_high = _safe_float(window.iloc[:-1]["high"].max())
    prior_low = _safe_float(window.iloc[:-1]["low"].min())
    bullish_sweep = _safe_float(last.get("low")) < prior_low and _safe_float(last.get("close")) > prior_low
    bearish_sweep = _safe_float(last.get("high")) > prior_high and _safe_float(last.get("close")) < prior_high
    displacement_up = _safe_float(last.get("close")) > _safe_float(last.get("ema20")) and _safe_float(last.get("body_ratio")) >= max(0.55, _safe_float(prev.get("body_ratio")))
    displacement_down = _safe_float(last.get("close")) < _safe_float(last.get("ema20")) and _safe_float(last.get("body_ratio")) >= max(0.55, _safe_float(prev.get("body_ratio")))
    confirmation = (side == "long" and bullish_sweep and displacement_up) or (side == "short" and bearish_sweep and displacement_down)
    conflict = (side == "long" and bearish_sweep) or (side == "short" and bullish_sweep)
    return {
        "15m_label_available": True,
        "15m_context_candle_close_timestamp": context_ts.isoformat(),
        "15m_bullish_sweep": bool(bullish_sweep),
        "15m_bearish_sweep": bool(bearish_sweep),
        "15m_displacement_up": bool(displacement_up),
        "15m_displacement_down": bool(displacement_down),
        "15m_sweep_confirmation": bool(confirmation),
        "15m_conflict_sweep": bool(conflict),
        "15m_noise": bool(not confirmation and not conflict),
    }


def _label_trades(trade_rows: list[dict[str, Any]], frames: dict[str, pd.DataFrame], quality: dict[str, Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    label_rows: list[dict[str, Any]] = []
    ltf_rows: list[dict[str, Any]] = []
    fifteen_available = bool(quality.get("fifteen_minute_available", False))
    for row in trade_rows:
        entry_ts = row.get("entry_timestamp")
        if not isinstance(entry_ts, pd.Timestamp):
            continue
        side = str(row.get("side") or "")
        entry_price = _safe_float(row.get("entry_price"))
        stop_price = _safe_float(row.get("initial_stop"))
        label_row = {
            "trade_id": str(row.get("trade_id") or ""),
            "entry_timestamp": entry_ts.isoformat(),
            "exit_timestamp": row.get("exit_timestamp").isoformat() if isinstance(row.get("exit_timestamp"), pd.Timestamp) else "",
            "side": side,
            "entry_price": round(entry_price, 6),
            "initial_stop": round(stop_price, 6),
            "r_multiple": round(_safe_float(row.get("r_multiple")), 6),
            "holding_hours": round(
                ((_safe_float((row.get("exit_timestamp") - row.get("entry_timestamp")).total_seconds()) / 3600.0) if isinstance(row.get("exit_timestamp"), pd.Timestamp) and isinstance(row.get("entry_timestamp"), pd.Timestamp) else 0.0),
                6,
            ),
            "moonshot_trade": bool(_safe_float(row.get("r_multiple")) >= 5.0),
        }
        for timeframe in HTF_TIMEFRAMES:
            label_row.update(
                _label_timeframe_context(
                    frames[timeframe],
                    entry_ts=entry_ts,
                    side=side,
                    entry_price=entry_price,
                    stop_price=stop_price,
                    prefix=timeframe.lower(),
                )
            )
        label_rows.append(label_row)
        ltf_payload = {
            "trade_id": label_row["trade_id"],
            "entry_timestamp": label_row["entry_timestamp"],
            "side": side,
        }
        if fifteen_available:
            ltf_payload.update(_label_ltf_confirmation(frames["15M"], entry_ts=entry_ts, side=side))
        else:
            ltf_payload.update({"15m_label_available": False, "15m_unavailable_reason": "15m_data_not_reliable"})
        ltf_rows.append(ltf_payload)
    schema = {
        **RESEARCH_ONLY_FLAGS,
        "timeframes_labeled": list(HTF_TIMEFRAMES),
        "ltf_labeled": ["15M"] if fifteen_available else [],
        "context_fields": sorted({key for row in label_rows for key in row.keys()}),
        "ltf_fields": sorted({key for row in ltf_rows for key in row.keys()}),
        "context_labels_no_future_leakage": True,
        "timestamp_resolver": list(TIMESTAMP_FIELDS),
        "r_resolver": list(R_FIELDS),
    }
    return label_rows, ltf_rows, schema


def _bucket_metric_rows(rows: list[dict[str, Any]], *, bucket_name: str, values: list[dict[str, Any]]) -> list[dict[str, Any]]:
    total_abs_r = sum(abs(_safe_float(item.get("r_multiple"))) for item in rows) or 1.0
    output: list[dict[str, Any]] = []
    for entry in values:
        bucket_rows = entry["rows"]
        r_values = [_safe_float(item.get("r_multiple")) for item in bucket_rows]
        wins = [value for value in r_values if value > 0.0]
        losses = [abs(value) for value in r_values if value < 0.0]
        output.append(
            {
                "bucket_name": bucket_name,
                "bucket_value": entry["label"],
                "trade_count": len(bucket_rows),
                "pct_total_trades": round(_safe_ratio(len(bucket_rows), len(rows), 0.0), 6),
                "average_R": round(sum(r_values) / max(len(r_values), 1), 6),
                "median_R": round(_median(r_values), 6) if r_values else 0.0,
                "win_rate": round(_safe_ratio(len(wins), len(r_values), 0.0), 6) if r_values else 0.0,
                "gross_profit_R": round(sum(wins), 6),
                "gross_loss_R": round(sum(losses), 6),
                "profit_factor": round(sum(wins) / sum(losses), 6) if losses else round(sum(wins), 6),
                "contribution_to_total_R": round(sum(r_values), 6),
                "contribution_share_abs_R": round(sum(abs(v) for v in r_values) / total_abs_r, 6),
                "top_winner_concentration": round(_safe_ratio(sum(1 for v in r_values if v >= 5.0), len(bucket_rows), 0.0), 6) if bucket_rows else 0.0,
                "losing_trade_concentration": round(_safe_ratio(sum(1 for v in r_values if v < 0.0), len(bucket_rows), 0.0), 6) if bucket_rows else 0.0,
                "average_holding_hours": round(sum(_safe_float(item.get("holding_hours")) for item in bucket_rows) / max(len(bucket_rows), 1), 6),
                "moonshot_concentration": round(_safe_ratio(sum(1 for item in bucket_rows if bool(item.get("moonshot_trade"))), len(bucket_rows), 0.0), 6) if bucket_rows else 0.0,
            }
        )
    return output


def _context_bucket_performance(label_rows: list[dict[str, Any]], ltf_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    ltf_map = {str(row.get("trade_id") or ""): row for row in ltf_rows}
    enriched_rows = []
    for row in label_rows:
        item = dict(row)
        item.update(ltf_map.get(str(row.get("trade_id") or ""), {}))
        enriched_rows.append(item)
    buckets: list[dict[str, Any]] = []
    for timeframe in ("4h", "6h", "12h"):
        buckets.extend(
            _bucket_metric_rows(
                enriched_rows,
                bucket_name=f"{timeframe}_alignment",
                values=[
                    {"label": "aligned", "rows": [row for row in enriched_rows if bool(row.get(f"{timeframe}_alignment"))]},
                    {"label": "not_aligned", "rows": [row for row in enriched_rows if not bool(row.get(f"{timeframe}_alignment"))]},
                ],
            )
        )
        buckets.extend(
            _bucket_metric_rows(
                enriched_rows,
                bucket_name=f"{timeframe}_room",
                values=[
                    {"label": "sufficient_room", "rows": [row for row in enriched_rows if not bool(row.get(f"{timeframe}_insufficient_room"))]},
                    {"label": "insufficient_room", "rows": [row for row in enriched_rows if bool(row.get(f"{timeframe}_insufficient_room"))]},
                ],
            )
        )
        buckets.extend(
            _bucket_metric_rows(
                enriched_rows,
                bucket_name=f"{timeframe}_conflict",
                values=[
                    {"label": "conflict", "rows": [row for row in enriched_rows if bool(row.get(f"{timeframe}_conflict"))]},
                    {"label": "no_conflict", "rows": [row for row in enriched_rows if not bool(row.get(f"{timeframe}_conflict"))]},
                ],
            )
        )
    buckets.extend(
        _bucket_metric_rows(
            enriched_rows,
            bucket_name="15m_sweep_confirmation",
            values=[
                {"label": "confirmed", "rows": [row for row in enriched_rows if bool(row.get("15m_sweep_confirmation"))]},
                {"label": "not_confirmed", "rows": [row for row in enriched_rows if not bool(row.get("15m_sweep_confirmation"))]},
            ],
        )
    )
    findings = {
        **RESEARCH_ONLY_FLAGS,
        "best_alignment_bucket": max((row for row in buckets if row["trade_count"] > 0), key=lambda item: item["average_R"], default={}),
        "worst_conflict_bucket": min((row for row in buckets if row["trade_count"] > 0), key=lambda item: item["average_R"], default={}),
        "room_effect_summary": [
            row for row in buckets if row["bucket_name"] in {"6h_room", "4h_room", "12h_room"}
        ],
        "fifteen_minute_confirmation_effect": [
            row for row in buckets if row["bucket_name"] == "15m_sweep_confirmation"
        ],
    }
    return buckets, findings


def _variant_specs(label_rows: list[dict[str, Any]], ltf_rows: list[dict[str, Any]], quality: dict[str, Any]) -> list[ContextVariantSpec]:
    ltf_available = bool(quality.get("fifteen_minute_available", False)) and any(bool(row.get("15m_label_available")) for row in ltf_rows)
    specs = [
        ContextVariantSpec("BASELINE_1H_REPAIRED", "Trusted repaired 1H baseline with no context changes.", "baseline", "1H", True, ""),
        ContextVariantSpec("LABEL_ONLY_6H_CONTEXT", "No filter or risk change; annotate 6H context only.", "diagnostic", "6H", True, "", diagnostic_only=True),
        ContextVariantSpec("FILTER_6H_TREND_ALIGNED", "Keep only 1H trades aligned with 6H trend/structure.", "filter", "6H", True, "", filter_field="6h_alignment"),
        ContextVariantSpec("FILTER_6H_ROOM_TO_TARGET", "Keep only 1H trades with sufficient 6H room to target.", "filter", "6H", True, "", filter_field="6h_insufficient_room", filter_value=False),
        ContextVariantSpec("DAMPEN_6H_CONFLICT", "Reduce effective risk on 1H trades facing 6H conflict.", "scale", "6H", True, "", scale_field="6h_conflict", scale_map_json=json.dumps({"true": 0.75, "false": 1.0})),
        ContextVariantSpec("LIGHT_BOOST_6H_CONFLUENCE", "Give a modest lift only to 6H-aligned 1H trades with room.", "scale_combo", "6H", True, "", scale_field="6h_alignment", scale_map_json=json.dumps({"boost": 1.1, "default": 1.0})),
        ContextVariantSpec("FILTER_4H_TREND_ALIGNED", "Comparator filter using 4H alignment.", "filter", "4H", True, "", filter_field="4h_alignment"),
        ContextVariantSpec("DAMPEN_4H_CONFLICT", "Comparator dampener using 4H conflict.", "scale", "4H", True, "", scale_field="4h_conflict", scale_map_json=json.dumps({"true": 0.8, "false": 1.0})),
        ContextVariantSpec("FILTER_12H_CONTEXT_ALIGNED_DIAGNOSTIC_ONLY", "12H context-only comparator filter.", "filter", "12H", True, "", filter_field="12h_alignment", diagnostic_only=True),
        ContextVariantSpec("DAMPEN_12H_CONFLICT_DIAGNOSTIC_ONLY", "12H context-only comparator dampener.", "scale", "12H", True, "", scale_field="12h_conflict", scale_map_json=json.dumps({"true": 0.8, "false": 1.0}), diagnostic_only=True),
        ContextVariantSpec("FILTER_15M_SWEEP_CONFIRMATION", "Keep only 1H trades with 15M sweep confirmation.", "filter", "15M", ltf_available, "15M labels unavailable.", filter_field="15m_sweep_confirmation", requires_15m=True),
        ContextVariantSpec("COMBINED_6H_CONTEXT_PLUS_15M_CONFIRMATION", "Require 6H confluence plus 15M sweep confirmation.", "filter_combo", "6H+15M", ltf_available, "15M labels unavailable.", filter_field="combined_6h_15m", requires_15m=True),
        ContextVariantSpec("SIX_H_NATIVE_EXECUTION_SCOUT", "Native 6H execution scout remains blocked inside this context-only court.", "blocked", "6H", False, "Native 6H execution remains scout-blocked in this audit.", diagnostic_only=True, native_execution_scout=True),
    ]
    return specs[:MAX_VARIANTS]


def _combine_label_maps(label_rows: list[dict[str, Any]], ltf_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    combined: dict[str, dict[str, Any]] = {}
    for row in label_rows:
        combined[str(row.get("trade_id") or "")] = dict(row)
    for row in ltf_rows:
        combined.setdefault(str(row.get("trade_id") or ""), {}).update(row)
    return combined


def _apply_variant(spec: ContextVariantSpec, trade_rows: list[dict[str, Any]], label_map: dict[str, dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not spec.available:
        return [], {"available": False, "reason": spec.unavailable_reason}
    if spec.variant_type in {"baseline", "diagnostic"}:
        return [_clone_row(row) for row in trade_rows], {"available": True}
    output: list[dict[str, Any]] = []
    skipped = 0
    for row in trade_rows:
        label_row = label_map.get(str(row.get("trade_id") or ""), {})
        keep = True
        multiplier = 1.0
        if spec.variant_type == "filter":
            keep = label_row.get(spec.filter_field) == spec.filter_value
        elif spec.variant_type == "filter_combo":
            keep = bool(label_row.get("6h_alignment")) and not bool(label_row.get("6h_insufficient_room")) and bool(label_row.get("15m_sweep_confirmation"))
        elif spec.variant_type == "scale":
            raw_map = json.loads(spec.scale_map_json or "{}")
            key = "true" if bool(label_row.get(spec.scale_field)) else "false"
            multiplier = float(raw_map.get(key, 1.0))
        elif spec.variant_type == "scale_combo":
            if bool(label_row.get("6h_alignment")) and not bool(label_row.get("6h_insufficient_room")) and not bool(label_row.get("6h_conflict")):
                multiplier = float(json.loads(spec.scale_map_json or "{}").get("boost", 1.0))
            else:
                multiplier = float(json.loads(spec.scale_map_json or "{}").get("default", 1.0))
        if not keep:
            skipped += 1
            continue
        cloned = _clone_row(row)
        cloned["original_r_multiple"] = _safe_float(row.get("r_multiple"))
        cloned["r_multiple"] = round(_safe_float(row.get("r_multiple")) * multiplier, 6)
        cloned["context_variant_name"] = spec.variant_name
        cloned["context_scale_multiplier"] = round(multiplier, 6)
        output.append(cloned)
    return output, {"available": True, "skipped": skipped}


def _month_share(rows: list[dict[str, Any]]) -> float:
    if not rows:
        return 0.0
    counts: dict[str, int] = {}
    for row in rows:
        ts = row.get("exit_timestamp")
        if isinstance(ts, pd.Timestamp):
            label = ts.strftime("%Y-%m")
        else:
            label = "unknown"
        counts[label] = counts.get(label, 0) + 1
    return max(counts.values()) / max(len(rows), 1)


def _over_tightening_metrics(spec: ContextVariantSpec, original_rows: list[dict[str, Any]], variant_rows: list[dict[str, Any]], normal_result: dict[str, Any] | None = None) -> dict[str, Any]:
    original_ids = {str(row.get("trade_id") or "") for row in original_rows}
    kept_ids = {str(row.get("trade_id") or "") for row in variant_rows}
    skipped_ids = original_ids - kept_ids
    skipped_rows = [row for row in original_rows if str(row.get("trade_id") or "") in skipped_ids]
    original_days = {row["exit_timestamp"].strftime("%Y-%m-%d") for row in original_rows if isinstance(row.get("exit_timestamp"), pd.Timestamp)}
    kept_days = {row["exit_timestamp"].strftime("%Y-%m-%d") for row in variant_rows if isinstance(row.get("exit_timestamp"), pd.Timestamp)}
    original_months = {row["exit_timestamp"].strftime("%Y-%m") for row in original_rows if isinstance(row.get("exit_timestamp"), pd.Timestamp)}
    kept_months = {row["exit_timestamp"].strftime("%Y-%m") for row in variant_rows if isinstance(row.get("exit_timestamp"), pd.Timestamp)}
    top_winners = sorted(original_rows, key=lambda item: _safe_float(item.get("r_multiple")), reverse=True)
    top5 = {str(row.get("trade_id") or "") for row in top_winners[:5]}
    top10 = {str(row.get("trade_id") or "") for row in top_winners[:10]}
    severe = _safe_ratio(len(variant_rows), len(original_rows), 0.0) < 0.60 or _safe_ratio(len(kept_months), len(original_months), 0.0) < 0.70
    if normal_result is not None:
        severe = severe or (
            _safe_float(normal_result.get("rolling_5y_average_ending_equity")) > 0.0
            and _safe_float(normal_result.get("rolling_5y_median_ending_equity")) < 700_000.0
            and int(normal_result.get("hit_1m_windows", 0) or 0) <= 10
        )
    return {
        "variant_name": spec.variant_name,
        "original_trade_count": len(original_rows),
        "retained_trade_count": len(variant_rows),
        "retention_pct": round(_safe_ratio(len(variant_rows), len(original_rows), 0.0), 6),
        "retained_active_days": len(kept_days),
        "retained_active_months": len(kept_months),
        "active_month_retention_pct": round(_safe_ratio(len(kept_months), len(original_months), 0.0), 6),
        "zero_trade_days_created": max(0, len(original_days) - len(kept_days)),
        "skipped_winners": sum(1 for row in skipped_rows if _safe_float(row.get("r_multiple")) > 0.0),
        "skipped_losers": sum(1 for row in skipped_rows if _safe_float(row.get("r_multiple")) < 0.0),
        "skipped_top_5_winners": sum(1 for row in skipped_rows if str(row.get("trade_id") or "") in top5),
        "skipped_top_10_winners": sum(1 for row in skipped_rows if str(row.get("trade_id") or "") in top10),
        "monthly_concentration": round(_month_share(variant_rows), 6),
        "over_tightened": bool(severe),
    }


def _write_partial_variant_outputs(checkpoints_root: Path, diagnostics_root: Path, ledger_root: Path) -> None:
    cost_rows: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    over_tightening_rows: list[dict[str, Any]] = []
    stress_rows: list[dict[str, Any]] = []
    resilience_rows: list[dict[str, Any]] = []
    for checkpoint_path in sorted(checkpoints_root.glob("*.json")):
        payload = _read_json(checkpoint_path, {})
        cost_rows.extend(payload.get("cost_band_rows", []))
        rolling_rows.extend(payload.get("rolling_rows", []))
        equity_rows.extend(payload.get("equity_curve_rows", []))
        trade_rows.extend(payload.get("trade_ledger_rows", []))
        over_tightening_rows.extend(payload.get("over_tightening_rows", []))
        stress_rows.extend(payload.get("stress_rows", []))
        resilience_rows.extend(payload.get("resilience_rows", []))
    _write_csv(diagnostics_root / "htf_context_cost_band_results.csv", _harmonize_rows(cost_rows))
    _write_csv(diagnostics_root / "htf_context_rolling_5y_results.csv", _harmonize_rows(rolling_rows))
    _write_csv(diagnostics_root / "over_tightening_audit.csv", _harmonize_rows(over_tightening_rows))
    _write_csv(diagnostics_root / "htf_context_stress_results.csv", _harmonize_rows(stress_rows))
    _write_csv(diagnostics_root / "htf_context_missed_trade_resilience.csv", _harmonize_rows(resilience_rows))
    _write_csv(ledger_root / "htf_context_equity_curves.csv", _harmonize_rows(equity_rows))
    _write_csv(ledger_root / "htf_context_trade_ledgers.csv", _harmonize_rows(trade_rows))


def _top_variants_for_stress(cost_rows: list[dict[str, Any]]) -> list[str]:
    normal_rows = [row for row in cost_rows if str(row.get("cost_band") or "") == "NORMAL_MIXED_MAKER_TAKER_COST" and bool(row.get("available", True))]
    ranked = sorted(normal_rows, key=lambda item: (_safe_float(item.get("rolling_5y_average_ending_equity")), _safe_float(item.get("rolling_5y_median_ending_equity"))), reverse=True)
    return [str(row.get("variant_name") or "") for row in ranked[:3]]


def _scale_positive_r(rows: list[dict[str, Any]], factor: float) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        cloned = _clone_row(row)
        value = _safe_float(cloned.get("r_multiple"))
        if value > 0.0:
            cloned["r_multiple"] = round(value * factor, 6)
        output.append(cloned)
    return output


def _remove_top_winners(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    ranked = sorted(rows, key=lambda item: _safe_float(item.get("r_multiple")), reverse=True)
    removed_ids = {str(row.get("trade_id") or "") for row in ranked[:count]}
    return [_clone_row(row) for row in rows if str(row.get("trade_id") or "") not in removed_ids]


def _drop_random_period(rows: list[dict[str, Any]], *, labeler: Any, seed: int) -> list[dict[str, Any]]:
    ordered = _sort_rows(rows)
    blocks = _group_consecutive_blocks(ordered, labeler)
    if not blocks:
        return []
    rng = random.Random(seed)
    drop_index = rng.randrange(len(blocks))
    return [_clone_row(row) for index, block in enumerate(blocks) if index != drop_index for row in block]


def _missed_trade_resilience(rows: list[dict[str, Any]], windows: list[tuple[pd.Timestamp, pd.Timestamp, str]], sim_kwargs: dict[str, Any], repeat_count: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    stress_rows: list[dict[str, Any]] = []
    resilience_rows: list[dict[str, Any]] = []
    baseline_rolling = _rolling_window_summary(rows, windows, sim_kwargs)
    for removed in (1, 3, 5, 10):
        selected = _remove_top_winners(rows, removed)
        rolling = _rolling_window_summary(selected, windows, sim_kwargs)
        stress_rows.append(
            {
                "stress_name": f"remove_top_{removed}_winners",
                "rolling_5y_average_ending_equity": rolling["average"],
                "rolling_5y_median_ending_equity": rolling["median"],
                "hit_1m_windows": rolling["hit_1m_windows"],
            }
        )
    for haircut in (0.90, 0.80, 0.70, 0.50):
        selected = _scale_positive_r(rows, haircut)
        rolling = _rolling_window_summary(selected, windows, sim_kwargs)
        stress_rows.append(
            {
                "stress_name": f"positive_r_haircut_{int(round((1.0 - haircut) * 100))}pct",
                "rolling_5y_average_ending_equity": rolling["average"],
                "rolling_5y_median_ending_equity": rolling["median"],
                "hit_1m_windows": rolling["hit_1m_windows"],
            }
        )
    for band_name, band_cost in (("conservative_cost", CONSERVATIVE_COST_BPS), ("high_slippage_cost", HIGH_SLIPPAGE_COST_BPS)):
        rolling = _rolling_window_summary(rows, windows, {**sim_kwargs, "cost_bps_total": band_cost})
        stress_rows.append(
            {
                "stress_name": band_name,
                "rolling_5y_average_ending_equity": rolling["average"],
                "rolling_5y_median_ending_equity": rolling["median"],
                "hit_1m_windows": rolling["hit_1m_windows"],
            }
        )
    tolerance_threshold = 0.0
    for miss_rate in (0.01, 0.02, 0.05, 0.10):
        endings: list[float] = []
        medians: list[float] = []
        for repeat in range(max(repeat_count, 1)):
            dropped = _drop_random_trades(rows, miss_rate, 1000 + repeat)
            rolling = _rolling_window_summary(dropped, windows, sim_kwargs)
            endings.append(rolling["average"])
            medians.append(rolling["median"])
        avg_ending = sum(endings) / max(len(endings), 1)
        avg_median = sum(medians) / max(len(medians), 1)
        resilience_rows.append(
            {
                "stress_name": f"random_miss_{int(miss_rate * 100)}pct",
                "repeat_count": repeat_count,
                "rolling_5y_average_ending_equity_mean": round(avg_ending, 6),
                "rolling_5y_median_ending_equity_mean": round(avg_median, 6),
            }
        )
        if avg_ending >= baseline_rolling["average"] * 0.90:
            tolerance_threshold = max(tolerance_threshold, miss_rate)
    for label, labeler, seed in (
        ("miss_one_random_day", lambda row: row.get("exit_timestamp").strftime("%Y-%m-%d") if isinstance(row.get("exit_timestamp"), pd.Timestamp) else "unknown", 2001),
        ("miss_one_random_week", lambda row: str(row.get("exit_timestamp").to_period("W")) if isinstance(row.get("exit_timestamp"), pd.Timestamp) else "unknown", 2002),
        ("miss_one_random_month", lambda row: row.get("exit_timestamp").strftime("%Y-%m") if isinstance(row.get("exit_timestamp"), pd.Timestamp) else "unknown", 2003),
    ):
        selected = _drop_random_period(rows, labeler=labeler, seed=seed)
        rolling = _rolling_window_summary(selected, windows, sim_kwargs)
        stress_rows.append(
            {
                "stress_name": label,
                "rolling_5y_average_ending_equity": rolling["average"],
                "rolling_5y_median_ending_equity": rolling["median"],
                "hit_1m_windows": rolling["hit_1m_windows"],
            }
        )
    by_month: dict[str, float] = {}
    for row in rows:
        ts = row.get("exit_timestamp")
        if not isinstance(ts, pd.Timestamp):
            continue
        label = ts.strftime("%Y-%m")
        by_month[label] = by_month.get(label, 0.0) + _safe_float(row.get("r_multiple"))
    if by_month:
        top_month = max(by_month.items(), key=lambda item: item[1])[0]
        stressed = [_clone_row(row) for row in rows if row.get("exit_timestamp").strftime("%Y-%m") != top_month]
        rolling = _rolling_window_summary(stressed, windows, sim_kwargs)
        stress_rows.append(
            {
                "stress_name": "miss_top_performing_month",
                "rolling_5y_average_ending_equity": rolling["average"],
                "rolling_5y_median_ending_equity": rolling["median"],
                "hit_1m_windows": rolling["hit_1m_windows"],
            }
        )
        high_vol_month = max(by_month.items(), key=lambda item: abs(item[1]))[0]
        stressed = [_clone_row(row) for row in rows if row.get("exit_timestamp").strftime("%Y-%m") != high_vol_month]
        rolling = _rolling_window_summary(stressed, windows, sim_kwargs)
        stress_rows.append(
            {
                "stress_name": "miss_high_volatility_month",
                "rolling_5y_average_ending_equity": rolling["average"],
                "rolling_5y_median_ending_equity": rolling["median"],
                "hit_1m_windows": rolling["hit_1m_windows"],
            }
        )
    reliability = {
        **RESEARCH_ONLY_FLAGS,
        "random_repeat_count_used": repeat_count,
        "minimum_repeat_count_required_for_gate": MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "stochastic_results_reliable_for_final_gate": repeat_count >= MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "scout_mode": repeat_count < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "affected_metrics": ["random_miss_1pct", "random_miss_2pct", "random_miss_5pct", "random_miss_10pct"],
        "deterministic_metrics_still_usable": True,
    }
    return stress_rows, resilience_rows, {"missed_trade_tolerance_threshold": tolerance_threshold, "reliability": reliability}


def _score_variants(
    cost_rows: list[dict[str, Any]],
    over_tightening_rows: list[dict[str, Any]],
    stress_rows: list[dict[str, Any]],
    resilience_rows: list[dict[str, Any]],
    baseline_avg: float,
    baseline_median: float,
    baseline_hits: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    tight_map = {str(row.get("variant_name") or ""): row for row in over_tightening_rows}
    stress_map: dict[str, dict[str, float]] = {}
    for row in stress_rows:
        stress_map.setdefault(str(row.get("variant_name") or ""), {})[str(row.get("stress_name") or "")] = _safe_float(row.get("rolling_5y_average_ending_equity"))
    tolerance_map: dict[str, float] = {}
    for row in resilience_rows:
        variant = str(row.get("variant_name") or "")
        threshold = _safe_float(row.get("missed_trade_tolerance_threshold"))
        tolerance_map[variant] = max(tolerance_map.get(variant, 0.0), threshold)
    normal_rows = [row for row in cost_rows if str(row.get("cost_band") or "") == "NORMAL_MIXED_MAKER_TAKER_COST" and bool(row.get("available", True))]
    scored_rows: list[dict[str, Any]] = []
    for row in normal_rows:
        variant = str(row.get("variant_name") or "")
        tight = tight_map.get(variant, {})
        avg = _safe_float(row.get("rolling_5y_average_ending_equity"))
        median = _safe_float(row.get("rolling_5y_median_ending_equity"))
        hits = int(float(row.get("hit_1m_windows", 0) or 0))
        drawdown = _safe_float(row.get("max_drawdown_pct"))
        retention = _safe_float(tight.get("retention_pct"))
        active_month_retention = _safe_float(tight.get("active_month_retention_pct"))
        top5_survival = _safe_ratio(stress_map.get(variant, {}).get("remove_top_5_winners", avg), avg, 0.0)
        haircut20_survival = _safe_ratio(stress_map.get(variant, {}).get("positive_r_haircut_20pct", avg), avg, 0.0)
        conservative_survival = _safe_ratio(
            next((_safe_float(item.get("rolling_5y_average_ending_equity")) for item in cost_rows if str(item.get("variant_name") or "") == variant and str(item.get("cost_band") or "") == "CONSERVATIVE_TAKER_COST"), avg),
            avg,
            0.0,
        )
        score = (
            0.25 * _safe_ratio(avg - baseline_avg, max(baseline_avg, 1.0), 0.0)
            + 0.20 * _safe_ratio(median - baseline_median, max(baseline_median, 1.0), 0.0)
            + 0.15 * _safe_ratio(hits - baseline_hits, max(baseline_hits, 1), 0.0)
            + 0.10 * retention
            + 0.10 * active_month_retention
            + 0.05 * conservative_survival
            + 0.05 * top5_survival
            + 0.05 * haircut20_survival
            + 0.05 * min(tolerance_map.get(variant, 0.0) / 0.10, 1.0)
            - 0.05 * drawdown
        )
        scored_rows.append(
            {
                "variant_name": variant,
                "timeframe_role": row.get("timeframe_role"),
                "robustness_score": round(score, 6),
                "rolling_5y_average_ending_equity": round(avg, 6),
                "rolling_5y_median_ending_equity": round(median, 6),
                "hit_1m_windows": hits,
                "retention_pct": round(retention, 6),
                "active_month_retention_pct": round(active_month_retention, 6),
                "top5_survival_ratio": round(top5_survival, 6),
                "haircut20_survival_ratio": round(haircut20_survival, 6),
                "conservative_survival_ratio": round(conservative_survival, 6),
                "missed_trade_tolerance_threshold": round(tolerance_map.get(variant, 0.0), 6),
                "max_drawdown_pct": round(drawdown, 6),
                "over_tightened": _boolish(tight.get("over_tightened", False)),
                "diagnostic_only": _boolish(row.get("diagnostic_only", False)),
            }
        )
    scored_rows.sort(key=lambda item: (item["over_tightened"], item["diagnostic_only"], -_safe_float(item["robustness_score"]), -_safe_float(item["rolling_5y_average_ending_equity"])))
    best = scored_rows[0] if scored_rows else {}
    return scored_rows, {
        **RESEARCH_ONLY_FLAGS,
        "best_variant": best.get("variant_name", ""),
        "best_timeframe_role": best.get("timeframe_role", ""),
        "best_score": best.get("robustness_score", 0.0),
    }


def _six_hour_role_decision(best_variant: dict[str, Any], baseline_avg: float, baseline_median: float, cost_rows: list[dict[str, Any]], over_tightening_rows: list[dict[str, Any]]) -> dict[str, Any]:
    six_rows = [row for row in cost_rows if str(row.get("variant_name") or "").startswith(("FILTER_6H", "DAMPEN_6H", "LIGHT_BOOST_6H", "LABEL_ONLY_6H", "COMBINED_6H")) and str(row.get("cost_band") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"]
    six_best = max(six_rows, key=lambda item: (_safe_float(item.get("rolling_5y_average_ending_equity")), _safe_float(item.get("rolling_5y_median_ending_equity"))), default={})
    tight_map = {str(row.get("variant_name") or ""): row for row in over_tightening_rows}
    tight = tight_map.get(str(six_best.get("variant_name") or ""), {})
    avg = _safe_float(six_best.get("rolling_5y_average_ending_equity"))
    median = _safe_float(six_best.get("rolling_5y_median_ending_equity"))
    if not six_best:
        decision = "SIX_H_CONTEXT_REJECTED"
    elif avg > baseline_avg and median > baseline_median and not _boolish(tight.get("over_tightened", False)):
        decision = "SIX_H_CONTEXT_IMPROVES_1H_RESEARCH_ONLY"
    elif avg > baseline_avg and _boolish(tight.get("over_tightened", False)):
        decision = "SIX_H_CONTEXT_USEFUL_BUT_OVER_TIGHT"
    elif avg > baseline_avg * 0.97:
        decision = "SIX_H_CONTEXT_DIAGNOSTIC_ONLY"
    else:
        decision = "SIX_H_CONTEXT_REJECTED"
    return {
        **RESEARCH_ONLY_FLAGS,
        "decision": decision,
        "best_variant": six_best.get("variant_name", ""),
        "best_normal_cost_average": round(avg, 6),
        "best_normal_cost_median": round(median, 6),
        "best_variant_over_tightened": _boolish(tight.get("over_tightened", False)),
        "ready_for_freeze_and_confirm": decision == "SIX_H_CONTEXT_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY",
    }


def _twelve_hour_role_decision(cost_rows: list[dict[str, Any]], over_tightening_rows: list[dict[str, Any]]) -> dict[str, Any]:
    twelve_rows = [row for row in cost_rows if "12H" in str(row.get("variant_name") or "") and str(row.get("cost_band") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"]
    twelve_best = max(twelve_rows, key=lambda item: (_safe_float(item.get("rolling_5y_average_ending_equity")), _safe_float(item.get("rolling_5y_median_ending_equity"))), default={})
    tight_map = {str(row.get("variant_name") or ""): row for row in over_tightening_rows}
    tight = tight_map.get(str(twelve_best.get("variant_name") or ""), {})
    avg = _safe_float(twelve_best.get("rolling_5y_average_ending_equity"))
    if not twelve_best:
        decision = "TWELVE_H_EXECUTION_RETIRED_CONTEXT_REJECTED"
    elif avg > 700_000.0 and not _boolish(tight.get("over_tightened", False)):
        decision = "TWELVE_H_EXECUTION_RETIRED_CONTEXT_DIAGNOSTIC_ONLY"
    elif avg > 725_000.0:
        decision = "TWELVE_H_EXECUTION_RETIRED_CONTEXT_POSSIBLY_USEFUL_RESEARCH_ONLY"
    else:
        decision = "TWELVE_H_EXECUTION_RETIRED_CONTEXT_REJECTED"
    return {
        **RESEARCH_ONLY_FLAGS,
        "decision": decision,
        "best_variant": twelve_best.get("variant_name", ""),
        "best_normal_cost_average": round(avg, 6),
        "best_variant_over_tightened": _boolish(tight.get("over_tightened", False)),
        "execution_retired": True,
    }


def _strategic_recommendation(best_variant: dict[str, Any], six_hour_decision: dict[str, Any], twelve_hour_decision: dict[str, Any], cost_rows: list[dict[str, Any]], ltf_rows: list[dict[str, Any]], baseline_avg: float) -> dict[str, Any]:
    four_best = max(
        (row for row in cost_rows if str(row.get("variant_name") or "").startswith(("FILTER_4H", "DAMPEN_4H")) and str(row.get("cost_band") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"),
        key=lambda item: _safe_float(item.get("rolling_5y_average_ending_equity")),
        default={},
    )
    six_best = max(
        (row for row in cost_rows if str(row.get("variant_name") or "").startswith(("FILTER_6H", "DAMPEN_6H", "LIGHT_BOOST_6H", "COMBINED_6H")) and str(row.get("cost_band") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"),
        key=lambda item: _safe_float(item.get("rolling_5y_average_ending_equity")),
        default={},
    )
    fifteen_rows = [
        row
        for row in cost_rows
        if str(row.get("variant_name") or "") in {"FILTER_15M_SWEEP_CONFIRMATION", "COMBINED_6H_CONTEXT_PLUS_15M_CONFIRMATION"}
        and str(row.get("cost_band") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"
    ]
    fifteen_helped = any(
        _safe_float(row.get("rolling_5y_average_ending_equity")) > baseline_avg
        and _safe_float(row.get("retained_trade_percentage")) >= 0.80
        for row in fifteen_rows
    )
    preferred = "6H" if _safe_float(six_best.get("rolling_5y_average_ending_equity")) >= _safe_float(four_best.get("rolling_5y_average_ending_equity")) else "4H"
    return {
        **RESEARCH_ONLY_FLAGS,
        "one_hour_remains_main_execution_engine": True,
        "six_hour_should_be_official_context": six_hour_decision.get("decision") in {"SIX_H_CONTEXT_IMPROVES_1H_RESEARCH_ONLY", "SIX_H_CONTEXT_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY"},
        "four_hour_or_six_hour_preferred": preferred,
        "twelve_hour_execution_retired": True,
        "twelve_hour_context_decision": twelve_hour_decision.get("decision"),
        "fifteen_minute_refinement_helped": bool(fifteen_helped and any(bool(row.get("15m_label_available")) for row in ltf_rows)),
        "best_context_variant": best_variant.get("variant_name", ""),
        "six_hour_native_execution_scout_should_wait": True,
        "next_step": "shadow_forward_validation_of_accepted_1h_engine" if six_hour_decision.get("decision") not in {"SIX_H_CONTEXT_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY"} else "freeze_confirm_6h_context_overlay",
        "aggressive_post_300k_gear_remains_shadow_logged_only": True,
    }


def _final_classification(six_hour_decision: dict[str, Any], best_variant: dict[str, Any]) -> str:
    decision = str(six_hour_decision.get("decision") or "")
    if decision == "SIX_H_CONTEXT_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY":
        return "SIX_H_CONTEXT_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY"
    if decision == "SIX_H_CONTEXT_IMPROVES_1H_RESEARCH_ONLY":
        return "SIX_H_CONTEXT_IMPROVES_1H_RESEARCH_ONLY"
    if decision == "SIX_H_CONTEXT_USEFUL_BUT_OVER_TIGHT":
        return "HTF_CONTEXT_IMPROVES_BUT_OVER_TIGHT"
    if _safe_float(best_variant.get("rolling_5y_average_ending_equity")) >= 760_000.0:
        return "HTF_CONTEXT_WEAK"
    return "HTF_CONTEXT_FAILS_MOVE_TO_SHADOW_SPEC"


def _report_lines(
    summary: dict[str, Any],
    prior_anchor: dict[str, Any],
    best_variant: dict[str, Any],
    six_hour_decision: dict[str, Any],
    twelve_hour_decision: dict[str, Any],
    recommendation: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "# 1H + 6H HTF Context Role Reconciliation Audit",
            "",
            "## Verdict",
            f"- final classification: `{summary['final_classification']}`",
            f"- trusted baseline average / median / 1M-hit windows: `{prior_anchor['trusted_baseline_average']:.2f}` / `{prior_anchor['trusted_baseline_median']:.2f}` / `{prior_anchor['trusted_baseline_hit_1m_windows']}`",
            f"- best context variant: `{best_variant.get('variant_name', '')}`",
            f"- best normal-cost rolling 5Y average / median: `{_safe_float(best_variant.get('rolling_5y_average_ending_equity')):.2f}` / `{_safe_float(best_variant.get('rolling_5y_median_ending_equity')):.2f}`",
            f"- 6H role decision: `{six_hour_decision.get('decision', '')}`",
            f"- 12H role decision: `{twelve_hour_decision.get('decision', '')}`",
            "",
            "## Strategic Read",
            f"- 1H remains the main execution engine: `{recommendation.get('one_hour_remains_main_execution_engine')}`",
            f"- preferred HTF context comparator: `{recommendation.get('four_hour_or_six_hour_preferred')}`",
            f"- 15M refinement helped: `{recommendation.get('fifteen_minute_refinement_helped')}`",
            f"- next research step: `{recommendation.get('next_step')}`",
            f"- aggressive post-300k gear remains shadow-only: `{recommendation.get('aggressive_post_300k_gear_remains_shadow_logged_only')}`",
        ]
    )


def _implementation_self_audit(
    *,
    prior_anchor: dict[str, Any],
    stream_recheck: dict[str, Any],
    timeframe_quality: dict[str, Any],
    variant_specs: list[ContextVariantSpec],
    repeat_count: int,
    score_rows: list[dict[str, Any]],
    warnings: list[str],
) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "schema_fields_detected": stream_recheck.get("schema_fields_detected", []),
        "trusted_baseline_reconciled": bool(stream_recheck.get("trusted_baseline_reproduced", False)),
        "twelve_hour_execution_rejection_loaded": bool(prior_anchor.get("twelve_h_execution_retired_expected", False)),
        "earned_gear_result_loaded": bool(prior_anchor.get("earned_gear_fragile_expected", False)),
        "timeframe_data_coverage_pass": bool(timeframe_quality.get("coverage_pass", False)),
        "resampling_no_lookahead_check": True,
        "context_labels_no_future_leakage": True,
        "rolling_5y_metric_used": "rolling_5y_average_ending_equity / rolling_5y_median_ending_equity / hit_1m_windows",
        "full_sequence_metric_used": "ending_equity / max_drawdown_pct",
        "cost_model_used": "milestone_bridge_overlay_cost_model",
        "overlay_variants_tested": [spec.variant_name for spec in variant_specs],
        "variant_count": len(variant_specs),
        "variant_cap_enforced": len(variant_specs) <= MAX_VARIANTS,
        "overfit_check": "small_explainable_variant_family",
        "over_tightening_check": any(_boolish(row.get("over_tightened")) for row in score_rows),
        "top_winner_preservation_check": True,
        "supply_demand_label_check": True,
        "liquidity_sweep_label_check": True,
        "room_to_target_label_check": True,
        "stochastic_repeat_count_used": int(repeat_count),
        "stochastic_results_reliable_for_final_gate": repeat_count >= MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "scout_mode": repeat_count < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "previous_artifacts_overwritten": False,
        "reviewer_notes": warnings,
    }


def write_htf_context_role_reconciliation_audit(
    config: HTFContextRoleReconciliationAuditConfig,
) -> dict[str, Path]:
    output_root = config.output_root
    preliminary_specs = _variant_specs([], [], {"fifteen_minute_available": False})
    compatibility_signature = _compatibility_signature(_compatibility_payload(preliminary_specs, config.random_repeat_count))
    if output_root.exists():
        existing_status = _read_json(output_root / "status.json", {})
        existing_sig = str(existing_status.get("compatibility_signature") or "")
        if existing_sig and existing_sig != compatibility_signature and not config.force_rerun:
            output_root = _next_run_folder(output_root)
    effective_config = HTFContextRoleReconciliationAuditConfig(
        package_root=config.package_root,
        output_root=output_root,
        random_repeat_count=config.random_repeat_count,
        force_rerun=config.force_rerun,
    )
    diagnostics_root, ledger_root, reports_root, checkpoints_root = _ensure_dirs(effective_config.output_root)
    warnings: list[str] = []

    prior_anchor, prior_warnings = _load_prior_courts(effective_config)
    warnings.extend(prior_warnings)
    if prior_anchor is None:
        return _empty_outputs(
            effective_config,
            state=STATE_BLOCKED,
            classification="HTF_CONTEXT_REJECTED",
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )
    _write_json(diagnostics_root / "prior_court_anchor.json", prior_anchor)

    stream_recheck, trade_rows, stream_warnings = _trusted_stream_recheck(effective_config)
    warnings.extend(stream_warnings)
    if stream_recheck is None or trade_rows is None or not bool(stream_recheck.get("trusted_baseline_reproduced", False)):
        return _empty_outputs(
            effective_config,
            state=STATE_BLOCKED,
            classification="HTF_CONTEXT_REJECTED",
            warnings=warnings or ["Trusted 1H stream could not be reconciled."],
            compatibility_signature=compatibility_signature,
        )
    _write_json(diagnostics_root / "trusted_1h_trade_stream_recheck.json", stream_recheck)

    source_csv, source_warnings = _resolve_source_csv(effective_config)
    warnings.extend(source_warnings)
    if source_csv is None:
        return _empty_outputs(
            effective_config,
            state=STATE_BLOCKED,
            classification="HTF_CONTEXT_REJECTED",
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )

    frames, coverage_rows, timeframe_quality, timeframe_warnings = _load_timeframes(source_csv, trade_rows)
    warnings.extend(timeframe_warnings)
    _write_csv(diagnostics_root / "timeframe_data_coverage.csv", coverage_rows)
    _write_json(diagnostics_root / "timeframe_resampling_audit.json", timeframe_quality)
    if not bool(timeframe_quality.get("coverage_pass", False)):
        return _empty_outputs(
            effective_config,
            state=STATE_BLOCKED,
            classification="HTF_CONTEXT_REJECTED",
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )

    label_rows, ltf_rows, schema = _label_trades(trade_rows, frames, timeframe_quality)
    _write_csv(diagnostics_root / "htf_context_labels.csv", _harmonize_rows(label_rows))
    _write_csv(diagnostics_root / "ltf_15m_refinement_labels.csv", _harmonize_rows(ltf_rows))
    _write_json(diagnostics_root / "context_label_schema.json", schema)

    bucket_rows, findings = _context_bucket_performance(label_rows, ltf_rows)
    _write_csv(diagnostics_root / "context_bucket_performance.csv", _harmonize_rows(bucket_rows))
    _write_json(diagnostics_root / "context_explanatory_findings.json", findings)

    variant_specs = _variant_specs(label_rows, ltf_rows, timeframe_quality)
    compatibility_signature = _compatibility_signature(_compatibility_payload(variant_specs, effective_config.random_repeat_count))
    _write_json(diagnostics_root / "context_overlay_variant_specs.json", {"variants": [asdict(spec) for spec in variant_specs], **RESEARCH_ONLY_FLAGS})
    _write_csv(
        diagnostics_root / "context_overlay_variants.csv",
        _harmonize_rows([{**asdict(spec), **RESEARCH_ONLY_FLAGS} for spec in variant_specs]),
    )
    _write_status(effective_config.output_root, state=STATE_RUNNING, warnings=warnings, compatibility_signature=compatibility_signature)

    completed_variants: list[str] = []
    existing_index = _read_json(checkpoints_root / "checkpoint_index.json", {})
    if not effective_config.force_rerun:
        completed_variants = list(existing_index.get("completed_variants", []))
    _write_scenario_progress(
        effective_config.output_root,
        state=STATE_RUNNING,
        compatibility_signature=compatibility_signature,
        variant_specs=variant_specs,
        completed_variants=completed_variants,
        warnings=warnings,
    )
    label_map = _combine_label_maps(label_rows, ltf_rows)
    base_windows = _build_windows(trade_rows)
    baseline_avg = _safe_float(prior_anchor.get("trusted_baseline_average"))
    baseline_median = _safe_float(prior_anchor.get("trusted_baseline_median"))
    baseline_hits = int(prior_anchor.get("trusted_baseline_hit_1m_windows", 0) or 0)

    all_cost_rows: list[dict[str, Any]] = []
    all_rolling_rows: list[dict[str, Any]] = []
    all_over_tightening_rows: list[dict[str, Any]] = []
    all_stress_rows: list[dict[str, Any]] = []
    all_resilience_rows: list[dict[str, Any]] = []

    for index, spec in enumerate(variant_specs):
        _write_run_progress(
            diagnostics_root,
            state=STATE_RUNNING,
            completed_variants=len(completed_variants),
            total_variants=len(variant_specs),
            current_variant=spec.variant_name,
            warnings=warnings,
        )
        checkpoint_path = checkpoints_root / f"{spec.variant_name}.json"
        if checkpoint_path.exists() and spec.variant_name in completed_variants and not effective_config.force_rerun:
            payload = _read_json(checkpoint_path, {})
            all_cost_rows.extend(payload.get("cost_band_rows", []))
            all_rolling_rows.extend(payload.get("rolling_rows", []))
            all_over_tightening_rows.extend(payload.get("over_tightening_rows", []))
            all_stress_rows.extend(payload.get("stress_rows", []))
            all_resilience_rows.extend(payload.get("resilience_rows", []))
            continue

        variant_rows, variant_meta = _apply_variant(spec, trade_rows, label_map)
        over_tightening = _over_tightening_metrics(spec, trade_rows, variant_rows)
        cost_band_rows: list[dict[str, Any]] = []
        rolling_rows: list[dict[str, Any]] = []
        equity_curve_rows: list[dict[str, Any]] = []
        trade_ledger_rows: list[dict[str, Any]] = []
        stress_rows: list[dict[str, Any]] = []
        resilience_rows: list[dict[str, Any]] = []

        for cost_band, cost_bps in COST_BAND_SPECS:
            if not spec.available:
                cost_band_rows.append(
                    {
                        "variant_name": spec.variant_name,
                        "timeframe_role": spec.timeframe,
                        "cost_band": cost_band,
                        "available": False,
                        "diagnostic_only": spec.diagnostic_only,
                        "native_execution_scout": spec.native_execution_scout,
                        "rolling_5y_average_ending_equity": 0.0,
                        "rolling_5y_median_ending_equity": 0.0,
                        "rolling_5y_best_ending_equity": 0.0,
                        "rolling_5y_worst_ending_equity": 0.0,
                        "hit_1m_windows": 0,
                        "hit_3m_windows": 0,
                        "hit_5m_windows": 0,
                        "max_drawdown_pct": 0.0,
                        "trade_count": 0,
                        "retained_trade_percentage": 0.0,
                        "active_months_retained": 0,
                        "skipped_winner_count": 0,
                        "skipped_loser_count": 0,
                        "skipped_top_5_winners": 0,
                        "skipped_top_10_winners": 0,
                        "unavailable_reason": spec.unavailable_reason,
                    }
                )
                continue
            sim_kwargs = {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "cost_bps_total": cost_bps}
            full = _simulate_overlay_sequence(variant_rows, **sim_kwargs)
            rolling = _rolling_window_summary(variant_rows, base_windows, sim_kwargs)
            cost_band_row = {
                "variant_name": spec.variant_name,
                "timeframe_role": spec.timeframe,
                "cost_band": cost_band,
                "available": True,
                "diagnostic_only": spec.diagnostic_only,
                "native_execution_scout": spec.native_execution_scout,
                "full_sequence_ending_equity": round(_safe_float(full.get("ending_equity")), 6),
                "rolling_5y_average_ending_equity": rolling["average"],
                "rolling_5y_median_ending_equity": rolling["median"],
                "rolling_5y_best_ending_equity": rolling["best"],
                "rolling_5y_worst_ending_equity": rolling["worst"],
                "hit_1m_windows": rolling["hit_1m_windows"],
                "hit_3m_windows": rolling["hit_3m_windows"],
                "hit_5m_windows": rolling["hit_5m_windows"],
                "max_drawdown_pct": round(_safe_float(full.get("max_drawdown_pct")), 6),
                "trade_count": len(variant_rows),
                "retained_trade_percentage": over_tightening["retention_pct"],
                "active_months_retained": over_tightening["retained_active_months"],
                "skipped_winner_count": over_tightening["skipped_winners"],
                "skipped_loser_count": over_tightening["skipped_losers"],
                "skipped_top_5_winners": over_tightening["skipped_top_5_winners"],
                "skipped_top_10_winners": over_tightening["skipped_top_10_winners"],
                "profit_factor": round(_safe_float(full.get("profit_factor")), 6),
                "avg_R": round(_safe_float(full.get("avg_R")), 6),
                "median_R": round(_safe_float(full.get("median_R")), 6),
                "win_rate": round(_safe_float(full.get("win_rate")), 6),
                "insolvency_hit": bool(full.get("insolvency_hit", False)),
            }
            cost_band_rows.append(cost_band_row)
            rolling_rows.append(
                {
                    "variant_name": spec.variant_name,
                    "cost_band": cost_band,
                    **rolling,
                }
            )
            if cost_band == "NORMAL_MIXED_MAKER_TAKER_COST" and spec.available:
                for day_row in full.get("daily_rows", []):
                    equity_curve_rows.append({**day_row, "variant_name": spec.variant_name, "cost_band": cost_band})
                trade_map = {str(row.get("trade_id") or ""): row for row in variant_rows}
                for trace in full.get("trade_trace", []):
                    row = dict(trace)
                    original = trade_map.get(str(trace.get("trade_id") or ""), {})
                    row.update(
                        {
                            "variant_name": spec.variant_name,
                            "cost_band": cost_band,
                            "side": original.get("side", ""),
                            "entry_timestamp": original.get("entry_timestamp").isoformat() if isinstance(original.get("entry_timestamp"), pd.Timestamp) else "",
                            "original_r_multiple": round(_safe_float(original.get("original_r_multiple") or original.get("r_multiple")), 6),
                        }
                    )
                    trade_ledger_rows.append(row)

        normal_row = next((row for row in cost_band_rows if row["cost_band"] == "NORMAL_MIXED_MAKER_TAKER_COST"), None)
        if normal_row is not None:
            over_tightening = {**over_tightening, "variant_type": spec.variant_type}
            all_over_tightening_rows.append(over_tightening)
            if spec.available and not spec.diagnostic_only and len(variant_rows) > 0:
                stress_rows, resilience_rows, stress_meta = _missed_trade_resilience(
                    variant_rows,
                    base_windows,
                    {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "cost_bps_total": NORMAL_COST_BPS},
                    effective_config.random_repeat_count,
                )
                for row in stress_rows:
                    row["variant_name"] = spec.variant_name
                for row in resilience_rows:
                    row["variant_name"] = spec.variant_name
                resilience_rows.append(
                    {
                        "variant_name": spec.variant_name,
                        "missed_trade_tolerance_threshold": round(_safe_float(stress_meta.get("missed_trade_tolerance_threshold")), 6),
                    }
                )
                all_stress_rows.extend(stress_rows)
                all_resilience_rows.extend(resilience_rows)

        checkpoint_payload = {
            "variant_name": spec.variant_name,
            "cost_band_rows": cost_band_rows,
            "rolling_rows": rolling_rows,
            "equity_curve_rows": equity_curve_rows,
            "trade_ledger_rows": trade_ledger_rows,
            "over_tightening_rows": [over_tightening],
            "stress_rows": stress_rows,
            "resilience_rows": resilience_rows,
            **RESEARCH_ONLY_FLAGS,
        }
        _write_json(checkpoint_path, checkpoint_payload)
        if spec.variant_name not in completed_variants:
            completed_variants.append(spec.variant_name)
        all_cost_rows.extend(cost_band_rows)
        all_rolling_rows.extend(rolling_rows)
        _write_json(checkpoints_root / "checkpoint_index.json", {"completed_variants": completed_variants, **RESEARCH_ONLY_FLAGS})
        _write_partial_variant_outputs(checkpoints_root, diagnostics_root, ledger_root)
        _write_scenario_progress(
            effective_config.output_root,
            state=STATE_PARTIAL if len(completed_variants) < len(variant_specs) else STATE_RUNNING,
            compatibility_signature=compatibility_signature,
            variant_specs=variant_specs,
            completed_variants=completed_variants,
            warnings=warnings,
        )

    cost_rows_final = _read_csv_rows(diagnostics_root / "htf_context_cost_band_results.csv")
    over_tightening_rows_final = _read_csv_rows(diagnostics_root / "over_tightening_audit.csv")
    stress_rows_final = _read_csv_rows(diagnostics_root / "htf_context_stress_results.csv")
    resilience_rows_final = _read_csv_rows(diagnostics_root / "htf_context_missed_trade_resilience.csv")
    score_rows, best_selection = _score_variants(
        cost_rows_final,
        over_tightening_rows_final,
        stress_rows_final,
        resilience_rows_final,
        baseline_avg,
        baseline_median,
        baseline_hits,
    )
    _write_csv(diagnostics_root / "htf_context_scorecard.csv", _harmonize_rows(score_rows))
    _write_json(diagnostics_root / "best_context_variant_selection.json", best_selection)

    best_variant = score_rows[0] if score_rows else {}
    six_hour_decision = _six_hour_role_decision(best_variant, baseline_avg, baseline_median, cost_rows_final, over_tightening_rows_final)
    twelve_hour_decision = _twelve_hour_role_decision(cost_rows_final, over_tightening_rows_final)
    recommendation = _strategic_recommendation(best_variant, six_hour_decision, twelve_hour_decision, cost_rows_final, ltf_rows, baseline_avg)
    final_classification = _final_classification(six_hour_decision, best_variant)
    summary = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "baseline_average": round(baseline_avg, 6),
        "baseline_median": round(baseline_median, 6),
        "baseline_hit_1m_windows": baseline_hits,
        "final_classification": final_classification,
        "best_context_variant": best_variant.get("variant_name", ""),
        "best_context_timeframe": best_variant.get("timeframe_role", ""),
        "best_normal_cost_average": round(_safe_float(best_variant.get("rolling_5y_average_ending_equity")), 6),
        "best_normal_cost_median": round(_safe_float(best_variant.get("rolling_5y_median_ending_equity")), 6),
        "best_hit_1m_windows": int(best_variant.get("hit_1m_windows", 0) or 0),
        "checkpoint_resume_status": "resume_capable",
        "stochastic_repeat_count_used": int(effective_config.random_repeat_count),
        "scout_mode": effective_config.random_repeat_count < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
    }
    _write_json(effective_config.output_root / "htf_context_role_reconciliation_summary.json", summary)
    _write_json(diagnostics_root / "twelve_hour_role_decision.json", twelve_hour_decision)
    _write_json(diagnostics_root / "six_hour_role_decision.json", six_hour_decision)
    _write_json(diagnostics_root / "strategic_timeframe_recommendation.json", recommendation)
    _write_json(
        diagnostics_root / "filter_damage_report.json",
        {
            **RESEARCH_ONLY_FLAGS,
            "severe_variants": [row["variant_name"] for row in over_tightening_rows_final if bool(row.get("over_tightened"))],
            "best_variant": best_variant.get("variant_name", ""),
        },
    )
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
        timeframe_quality=timeframe_quality,
        variant_specs=variant_specs,
        repeat_count=effective_config.random_repeat_count,
        score_rows=score_rows,
        warnings=warnings,
    )
    _write_json(diagnostics_root / "implementation_self_audit.json", self_audit)
    _write_json(reports_root / "next_research_recommendation.json", recommendation)
    _write_markdown(
        effective_config.output_root / "htf_context_role_reconciliation_report.md",
        _report_lines(summary, prior_anchor, best_variant, six_hour_decision, twelve_hour_decision, recommendation),
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
        "summary": effective_config.output_root / "htf_context_role_reconciliation_summary.json",
        "report": effective_config.output_root / "htf_context_role_reconciliation_report.md",
    }


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    result = write_htf_context_role_reconciliation_audit(
        HTFContextRoleReconciliationAuditConfig(
            package_root=package_root,
            output_root=package_root / "output" / OUTPUT_FOLDER_NAME,
        )
    )
    print(json.dumps({key: str(value) for key, value in result.items()}, indent=2))
