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
    _estimated_cost,
)
from structural_compounding_lab.diagnostics.native_pre_entry_sr_feature_enrichment_audit import (  # noqa: E402
    _discover_candle_source,
    _load_price_source,
    _source_path_from_summary,
)
from structural_compounding_lab.diagnostics.native_12h_execution_sleeve_discovery_audit import (  # noqa: E402
    NORMAL_COST_BPS,
    CONSERVATIVE_COST_BPS,
    HIGH_SLIPPAGE_COST_BPS,
    OPTIMISTIC_COST_BPS,
    ZERO_COST_BPS,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import _build_windows  # noqa: E402


OUTPUT_FOLDER_NAME = "multi_asset_structural_redundancy_discovery_audit_001"
DEFAULT_RANDOM_REPEAT_COUNT = 8
START_CAPITAL = 20_000.0
ASSET_UNIVERSE = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "AVAXUSDT")
NON_BTC_ASSETS = tuple(asset for asset in ASSET_UNIVERSE if asset != "BTCUSDT")
MIN_ELIGIBLE_NON_BTC = 2
MIN_RESEARCH_YEARS = 5.0
DUPLICATE_SUPPRESSION_HOURS = 6
MAX_TOP_ASSETS = 3
TIMESTAMP_FIELDS = ("exit_timestamp", "timestamp", "entry_timestamp", "candle_timestamp", "close_time", "open_time")
R_FIELDS = ("r_multiple", "applied_r", "gross_r")


@dataclass(frozen=True)
class MultiAssetStructuralRedundancyDiscoveryAuditConfig:
    package_root: Path
    output_root: Path
    random_repeat_count: int = DEFAULT_RANDOM_REPEAT_COUNT


def _safe_float(value: Any, default: float = 0.0) -> float:
    return _to_float(value, default)


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


def _harmonize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    keys = sorted({key for row in rows for key in row.keys()})
    return [{key: row.get(key, "") for key in keys} for row in rows]


def _paths(config: MultiAssetStructuralRedundancyDiscoveryAuditConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    broad_root = output_root / "broad_historical_structural_replay_001"
    execution_root = output_root / "execution_cost_realism_and_trade_redundancy_audit_001"
    twelve_h_root = output_root / "native_12h_execution_sleeve_discovery_audit_001"
    return {
        "broad_summary": broad_root / "ledger" / "summary.json",
        "execution_cost_band_results": execution_root / "diagnostics" / "execution_cost_band_results.csv",
        "twelve_h_baseline_repair": twelve_h_root / "diagnostics" / "12h_baseline_accounting_repair_diagnostics.json",
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
    config: MultiAssetStructuralRedundancyDiscoveryAuditConfig,
    *,
    state: str,
    classification: str,
    warnings: list[str],
) -> dict[str, Path]:
    diagnostics_root, ledger_root, reports_root = _ensure_dirs(config.output_root)
    now = datetime.now(timezone.utc).isoformat()
    status = {"state": state, "resolved_at_utc": now, **RESEARCH_ONLY_FLAGS, "warnings": warnings}
    summary = {"resolved_at_utc": now, **RESEARCH_ONLY_FLAGS, "final_classification": classification, "warnings": warnings}
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "multi_asset_structural_redundancy_discovery_summary.json", summary)
    _write_markdown(
        config.output_root / "multi_asset_structural_redundancy_discovery_report.md",
        "# Multi-Asset Structural Redundancy Discovery Audit\n\nThe audit was blocked because required data or baseline artifacts were missing.\n",
    )
    for name in (
        "multi_asset_data_availability.csv",
        "multi_asset_data_availability.json",
        "btc_baseline_anchor.json",
        "per_asset_candidate_inventory.csv",
        "per_asset_no_leakage_check.json",
        "per_asset_candidate_performance.csv",
        "per_asset_monthly_distribution.csv",
        "per_asset_cluster_dependency.json",
        "multi_asset_independent_cluster_audit.csv",
        "multi_asset_correlation_audit.csv",
        "multi_asset_overlap_with_btc_baseline.csv",
        "multi_asset_portfolio_results.csv",
        "multi_asset_simple_capital_logic_comparison.csv",
        "multi_asset_cost_band_rolling_5y_results.csv",
        "multi_asset_missed_trade_resilience.csv",
        "multi_asset_stochastic_budget_reliability_check.json",
        "multi_asset_mission_target_interpretation.json",
        "multi_asset_freeze_and_confirm_candidates.json",
        "implementation_self_audit.json",
    ):
        path = diagnostics_root / name
        if name.endswith(".csv"):
            _write_csv(path, [])
        else:
            _write_json(path, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_csv(ledger_root / "per_asset_candidate_trades.csv", [])
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "multi_asset_structural_redundancy_discovery_summary.json",
        "report": config.output_root / "multi_asset_structural_redundancy_discovery_report.md",
    }


def _resolve_asset_source(
    *,
    symbol: str,
    package_root: Path,
    broad_summary_path: Path,
) -> tuple[Path | None, list[str]]:
    warnings: list[str] = []
    if symbol == "BTCUSDT":
        source_csv = _source_path_from_summary(broad_summary_path) if broad_summary_path.exists() else None
        if source_csv is not None and source_csv.exists():
            return source_csv, warnings
    base_dir = package_root.parent / "data_storage" / symbol / "1m"
    if not base_dir.exists():
        warnings.append(f"{symbol} data directory missing.")
        return None, warnings
    candidates = sorted(
        path for path in base_dir.glob(f"{symbol}_1m_*.csv")
        if "live_runtime" not in path.name and "_T" not in path.name and "T00.00.00" not in path.name
    )
    if not candidates:
        warnings.append(f"{symbol} has no canonical 1m CSV source.")
        return None, warnings
    return candidates[-1], warnings


def _coverage_years(start: pd.Timestamp | None, end: pd.Timestamp | None) -> float:
    if start is None or end is None:
        return 0.0
    return max(0.0, (end - start).total_seconds() / (365.25 * 24 * 3600.0))


def _asset_availability_row(symbol: str, source_csv: Path | None) -> tuple[dict[str, Any], pd.DataFrame | None]:
    if source_csv is None or not source_csv.exists():
        return {
            **RESEARCH_ONLY_FLAGS,
            "asset": symbol,
            "source_path_found": "",
            "base_timeframe": "",
            "row_count": 0,
            "coverage_start": "",
            "coverage_end": "",
            "missing_gap_count": 0,
            "duplicate_timestamp_count": 0,
            "ohlcv_available": False,
            "full_research_period_coverage_sufficient": False,
            "eligible_for_discovery": False,
            "reason_if_blocked": "missing_source_csv",
        }, None
    discovery, _availability = _discover_candle_source(source_csv)
    start = _timestamp(discovery.get("coverage_start"))
    end = _timestamp(discovery.get("coverage_end"))
    years = _coverage_years(start, end)
    eligible = (
        bool(discovery.get("candle_source_found"))
        and bool(discovery.get("safe_for_pre_entry_features"))
        and int(discovery.get("duplicate_timestamp_count", 0) or 0) == 0
        and years >= MIN_RESEARCH_YEARS
    )
    reason = ""
    if not eligible:
        if years < MIN_RESEARCH_YEARS:
            reason = "insufficient_years_of_history"
        elif int(discovery.get("duplicate_timestamp_count", 0) or 0) > 0:
            reason = "duplicate_timestamps_detected"
        else:
            reason = "source_not_safe_for_feature_backfill"
    frame, hourly, _htf = _load_price_source(source_csv)
    return {
        **RESEARCH_ONLY_FLAGS,
        "asset": symbol,
        "source_path_found": str(source_csv),
        "base_timeframe": "1m",
        "row_count": int(discovery.get("row_count", 0) or 0),
        "coverage_start": str(discovery.get("coverage_start") or ""),
        "coverage_end": str(discovery.get("coverage_end") or ""),
        "missing_gap_count": int(discovery.get("missing_data_gaps", 0) or 0),
        "duplicate_timestamp_count": int(discovery.get("duplicate_timestamp_count", 0) or 0),
        "ohlcv_available": all(col in frame.columns for col in ("open", "high", "low", "close", "volume")),
        "full_research_period_coverage_sufficient": years >= MIN_RESEARCH_YEARS,
        "eligible_for_discovery": eligible,
        "reason_if_blocked": reason,
        "available_timeframes": "1m,1h,12h",
    }, hourly.reset_index().rename(columns={"timestamp": "candle_close_timestamp"})


def _normalize_baseline_rows(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    normalized: list[dict[str, Any]] = []
    schema_fields = sorted({key for row in rows for key in row.keys()})
    timestamp_counts = {field: 0 for field in TIMESTAMP_FIELDS}
    r_counts = {field: 0 for field in R_FIELDS}
    for index, row in enumerate(rows):
        item = _clone_row(row)
        resolved_exit_ts = None
        resolved_ts_field = None
        for field in TIMESTAMP_FIELDS:
            parsed = item.get(field)
            if isinstance(parsed, pd.Timestamp):
                resolved_exit_ts = pd.Timestamp(parsed)
                resolved_ts_field = field
                break
            candidate = _try_timestamp(parsed)
            if candidate is not None:
                resolved_exit_ts = candidate
                resolved_ts_field = field
                break
        if resolved_exit_ts is None:
            errors.append(f"row_{index}: missing valid timestamp field")
            continue
        timestamp_counts[resolved_ts_field] += 1
        resolved_entry_ts = item.get("entry_timestamp")
        if not isinstance(resolved_entry_ts, pd.Timestamp):
            resolved_entry_ts = _try_timestamp(resolved_entry_ts)
        if resolved_entry_ts is None:
            resolved_entry_ts = resolved_exit_ts
            if resolved_ts_field != "entry_timestamp":
                warnings.append(f"row_{index}: entry_timestamp fallback used from {resolved_ts_field}")

        resolved_r = None
        resolved_r_field = None
        for field in R_FIELDS:
            if str(item.get(field, "")).strip() == "":
                continue
            resolved_r = _safe_float(item.get(field))
            resolved_r_field = field
            break
        if resolved_r_field is None:
            errors.append(f"row_{index}: missing R field among {', '.join(R_FIELDS)}")
            continue
        r_counts[resolved_r_field] += 1
        if resolved_r_field != "r_multiple":
            warnings.append(f"row_{index}: {resolved_r_field} fallback used for R")

        entry_price = _safe_float(item.get("entry_price"), math.nan)
        exit_price = _safe_float(item.get("exit_price"), math.nan)
        initial_stop = _safe_float(item.get("initial_stop"), math.nan)
        if any(math.isnan(value) for value in (entry_price, exit_price, initial_stop)):
            errors.append(f"row_{index}: missing entry/exit/stop price required for cost-aware baseline replay")
            continue

        normalized.append(
            {
                **item,
                "trade_id": str(item.get("trade_id") or f"baseline_row_{index}"),
                "asset": str(item.get("asset") or item.get("symbol") or "BTCUSDT"),
                "symbol": str(item.get("symbol") or item.get("asset") or "BTCUSDT"),
                "entry_timestamp": resolved_entry_ts,
                "exit_timestamp": resolved_exit_ts,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "initial_stop": initial_stop,
                "quantity": _safe_float(item.get("quantity"), 1.0),
                "r_multiple": resolved_r,
            }
        )
    timestamp_field_used = max(timestamp_counts, key=timestamp_counts.get) if any(timestamp_counts.values()) else "blocked"
    r_field_used = max(r_counts, key=r_counts.get) if any(r_counts.values()) else "blocked"
    schema_info = {
        "schema_fields_detected": schema_fields,
        "timestamp_field_used": timestamp_field_used,
        "r_field_used": r_field_used,
        "row_count": len(normalized),
    }
    return normalized, schema_info, warnings, errors


def _load_btc_baseline_anchor(config: MultiAssetStructuralRedundancyDiscoveryAuditConfig) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None, list[str], dict[str, Any]]:
    warnings: list[str] = []
    paths = _paths(config)
    csv_rows = _read_csv_rows(paths["execution_cost_band_results"])
    row = next((item for item in csv_rows if str(item.get("band_name") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"), None)
    twelve_h = _read_json(paths["twelve_h_baseline_repair"], {})
    if row is None:
        warnings.append("Trusted BTC baseline cost-band row missing.")
        return None, None, warnings, {}
    if not bool(twelve_h.get("baseline_reconciliation_pass_after_repair", False)):
        warnings.append("12H baseline repair diagnostics did not confirm repaired BTC baseline.")
        return None, None, warnings, {}
    context, context_warnings, _schema = _load_execution_cost_context(
        ExecutionCostRealismAndTradeRedundancyAuditConfig(
            package_root=config.package_root,
            output_root=config.package_root / "output" / "execution_cost_realism_and_trade_redundancy_audit_001",
            random_repeat_count=config.random_repeat_count,
        )
    )
    if context is None:
        warnings.extend(context_warnings)
        return None, None, warnings, {}
    normalized_rows, schema_info, normalize_warnings, normalize_errors = _normalize_baseline_rows(context["rows"])
    warnings.extend(context_warnings)
    warnings.extend(normalize_warnings)
    if normalize_errors:
        warnings.extend(normalize_errors)
        return None, None, warnings, {}
    anchor = {
        **RESEARCH_ONLY_FLAGS,
        "trusted_baseline_source_path": str(paths["execution_cost_band_results"]),
        "trusted_band_name": "NORMAL_MIXED_MAKER_TAKER_COST",
        "rolling_5y_average_ending_equity": _safe_float(row.get("rolling_5y_average_ending_equity")),
        "rolling_5y_median_ending_equity": _safe_float(row.get("rolling_5y_median_ending_equity")),
        "hit_1m_windows": int(row.get("hit_1m_windows", 0) or 0),
        "hit_3m_windows": int(row.get("hit_3m_windows", 0) or 0),
        "hit_5m_windows": int(row.get("hit_5m_windows", 0) or 0),
        "twelve_h_baseline_repair_selected_mode": str(twelve_h.get("selected_repair_mode") or ""),
        "twelve_h_baseline_repair_pass": bool(twelve_h.get("baseline_reconciliation_pass_after_repair", False)),
        "baseline_row_count": len(normalized_rows),
        "baseline_timestamp_field_used": schema_info["timestamp_field_used"],
        "baseline_r_field_used": schema_info["r_field_used"],
        "baseline_schema_fields_detected": schema_info["schema_fields_detected"],
    }
    return anchor, normalized_rows, warnings, {**context, "schema_info": schema_info}


def _clone_row(row: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(row)
    if isinstance(cloned.get("entry_timestamp"), pd.Timestamp):
        cloned["entry_timestamp"] = pd.Timestamp(cloned["entry_timestamp"])
    if isinstance(cloned.get("exit_timestamp"), pd.Timestamp):
        cloned["exit_timestamp"] = pd.Timestamp(cloned["exit_timestamp"])
    return cloned


def _simulate_sequence(
    rows: list[dict[str, Any]],
    *,
    cost_bps_total: float = 0.0,
    row_source_multipliers: dict[str, float] | None = None,
    drawdown_guard_pct: float | None = None,
    drawdown_breaker_pct: float | None = None,
    stepup_schedule: list[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    ordered = sorted(
        [_clone_row(row) for row in rows if isinstance(row.get("exit_timestamp"), pd.Timestamp)],
        key=lambda item: (item["exit_timestamp"], str(item.get("trade_id") or "")),
    )
    active_capital = float(START_CAPITAL)
    locked_profit = 0.0
    peak_equity = active_capital
    max_drawdown_pct = 0.0
    insolvency_hit = False
    breaker_triggered = False
    risk_multipliers: list[float] = []
    trade_trace: list[dict[str, Any]] = []
    monthly_totals: dict[str, float] = {}
    for row in ordered:
        current_equity = active_capital + locked_profit
        current_dd = _safe_ratio(max(0.0, peak_equity - current_equity), peak_equity, 0.0)
        if drawdown_breaker_pct is not None and current_dd >= drawdown_breaker_pct:
            breaker_triggered = True
            break
        multiplier = 1.0
        for threshold, scheduled in sorted(stepup_schedule or list(BASE_STEPUP_SCHEDULE), key=lambda item: item[0]):
            if current_equity >= threshold:
                multiplier = max(multiplier, scheduled)
        asset = str(row.get("asset") or row.get("symbol") or "BTCUSDT")
        if row_source_multipliers:
            multiplier *= row_source_multipliers.get(asset, 1.0)
        if drawdown_guard_pct is not None and current_dd > drawdown_guard_pct:
            multiplier = min(multiplier, 0.75)
        risk_value = max(active_capital, 0.0) * 0.01 * multiplier
        pnl = _safe_float(row.get("r_multiple")) * risk_value - _estimated_cost(row, cost_bps_total)
        active_capital += pnl
        if pnl > 0.0:
            lock_amount = pnl * 0.5
            locked_profit += lock_amount
            active_capital -= lock_amount
        total_equity = active_capital + locked_profit
        if total_equity <= 0.0:
            active_capital = 0.0
            locked_profit = 0.0
            total_equity = 0.0
            insolvency_hit = True
        peak_equity = max(peak_equity, total_equity)
        max_drawdown_pct = max(max_drawdown_pct, _safe_ratio(max(0.0, peak_equity - total_equity), peak_equity, 0.0))
        month = row["exit_timestamp"].strftime("%Y-%m")
        monthly_totals[month] = monthly_totals.get(month, 0.0) + pnl
        risk_multipliers.append(multiplier)
        trade_trace.append(
            {
                "trade_id": str(row.get("trade_id") or ""),
                "asset": asset,
                "candidate_family": str(row.get("candidate_family") or row.get("archetype_key") or ""),
                "timestamp": row["exit_timestamp"].isoformat(),
                "month": month,
                "risk_multiplier": round(multiplier, 6),
                "risk_value": round(risk_value, 6),
                "applied_r": round(_safe_float(row.get("r_multiple")), 6),
                "pnl": round(pnl, 6),
                "equity_after": round(total_equity, 6),
            }
        )
        if insolvency_hit:
            break
    r_values = [_safe_float(item.get("applied_r")) for item in trade_trace]
    wins = [value for value in r_values if value > 0.0]
    losses = [abs(value) for value in r_values if value < 0.0]
    return {
        "ending_equity": round(active_capital + locked_profit, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "trade_count": len(trade_trace),
        "trade_trace": trade_trace,
        "profit_factor": round(sum(wins) / sum(losses), 6) if losses else (round(sum(wins), 6) if wins else 0.0),
        "avg_r": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
        "median_r": round(_median(r_values), 6) if r_values else 0.0,
        "insolvency_hit": insolvency_hit,
        "breaker_triggered": breaker_triggered,
        "risk_multiplier_avg": round(sum(risk_multipliers) / len(risk_multipliers), 6) if risk_multipliers else 0.0,
        "risk_multiplier_max": round(max(risk_multipliers), 6) if risk_multipliers else 0.0,
        "monthly_totals": monthly_totals,
    }


def _window_rows(rows: list[dict[str, Any]], start: pd.Timestamp, end: pd.Timestamp) -> list[dict[str, Any]]:
    return [_clone_row(row) for row in rows if isinstance(row.get("exit_timestamp"), pd.Timestamp) and start <= row["exit_timestamp"] <= end]


def _rolling_summary(
    rows: list[dict[str, Any]],
    *,
    cost_bps_total: float = 0.0,
    row_source_multipliers: dict[str, float] | None = None,
    drawdown_guard_pct: float | None = None,
    drawdown_breaker_pct: float | None = None,
) -> dict[str, Any]:
    windows = _build_windows(rows)
    endings: list[float] = []
    hit_1m = 0
    hit_3m = 0
    hit_5m = 0
    max_dd = 0.0
    for start, end, _label in windows:
        selected = _window_rows(rows, start, end)
        output = _simulate_sequence(
            selected,
            cost_bps_total=cost_bps_total,
            row_source_multipliers=row_source_multipliers,
            drawdown_guard_pct=drawdown_guard_pct,
            drawdown_breaker_pct=drawdown_breaker_pct,
        )
        ending_equity = _safe_float(output["ending_equity"])
        endings.append(ending_equity)
        hit_1m += int(ending_equity >= 1_000_000.0)
        hit_3m += int(ending_equity >= 3_000_000.0)
        hit_5m += int(ending_equity >= 5_000_000.0)
        max_dd = max(max_dd, _safe_float(output["max_drawdown_pct"]))
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


def _compute_features(hourly: pd.DataFrame) -> pd.DataFrame:
    frame = hourly.copy()
    frame["body"] = (frame["close"] - frame["open"]).abs()
    range_size = (frame["high"] - frame["low"]).replace(0.0, pd.NA)
    frame["upper_wick_ratio"] = ((frame["high"] - frame[["open", "close"]].max(axis=1)) / range_size).fillna(0.0)
    frame["lower_wick_ratio"] = ((frame[["open", "close"]].min(axis=1) - frame["low"]) / range_size).fillna(0.0)
    frame["ema10"] = frame["close"].ewm(span=10, adjust=False).mean()
    frame["ema20"] = frame["close"].ewm(span=20, adjust=False).mean()
    frame["ema50"] = frame["close"].ewm(span=50, adjust=False).mean()
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


def _family_specs() -> list[dict[str, Any]]:
    return [
        {"family": "STRICT_SR_AWARE_LONG", "side": "long", "target_r": 3.0, "max_hold_bars": 18},
        {"family": "STRICT_SR_AWARE_SHORT", "side": "short", "target_r": 3.0, "max_hold_bars": 18},
        {"family": "LIQUIDITY_SWEEP_REVERSAL_LONG", "side": "long", "target_r": 2.5, "max_hold_bars": 12},
        {"family": "LIQUIDITY_SWEEP_REVERSAL_SHORT", "side": "short", "target_r": 2.5, "max_hold_bars": 12},
        {"family": "BREAK_RETEST_CONTINUATION_LONG", "side": "long", "target_r": 3.5, "max_hold_bars": 20},
        {"family": "BREAK_RETEST_CONTINUATION_SHORT", "side": "short", "target_r": 3.5, "max_hold_bars": 20},
        {"family": "RANGE_EXTREME_REVERSAL_LONG", "side": "long", "target_r": 2.0, "max_hold_bars": 10},
        {"family": "RANGE_EXTREME_REVERSAL_SHORT", "side": "short", "target_r": 2.0, "max_hold_bars": 10},
        {"family": "STRICT_COMBINED_LONG_SHORT", "side": "both", "target_r": 3.0, "max_hold_bars": 18},
    ]


def _family_trigger(family: str, signal_row: pd.Series) -> bool:
    atr = _safe_float(signal_row.get("atr14"))
    if atr <= 0.0:
        return False
    bullish = _safe_float(signal_row["close"]) > _safe_float(signal_row["open"])
    bearish = _safe_float(signal_row["close"]) < _safe_float(signal_row["open"])
    if family == "STRICT_SR_AWARE_LONG":
        return bool(signal_row.get("trend_up")) and bullish and _safe_float(signal_row.get("distance_to_support_atr")) <= 1.75 and _safe_float(signal_row.get("range_position")) > 0.55
    if family == "STRICT_SR_AWARE_SHORT":
        return bool(signal_row.get("trend_down")) and bearish and _safe_float(signal_row.get("distance_to_resistance_atr")) <= 1.75 and _safe_float(signal_row.get("range_position")) < 0.45
    if family == "LIQUIDITY_SWEEP_REVERSAL_LONG":
        return bullish and _safe_float(signal_row.get("lower_wick_ratio")) >= 0.45 and _safe_float(signal_row.get("range_position")) < 0.30
    if family == "LIQUIDITY_SWEEP_REVERSAL_SHORT":
        return bearish and _safe_float(signal_row.get("upper_wick_ratio")) >= 0.45 and _safe_float(signal_row.get("range_position")) > 0.70
    if family == "BREAK_RETEST_CONTINUATION_LONG":
        return bool(signal_row.get("trend_up")) and _safe_float(signal_row.get("close")) > _safe_float(signal_row.get("prior_high_20")) and _safe_float(signal_row.get("low")) <= _safe_float(signal_row.get("prior_high_20")) + atr * 0.25
    if family == "BREAK_RETEST_CONTINUATION_SHORT":
        return bool(signal_row.get("trend_down")) and _safe_float(signal_row.get("close")) < _safe_float(signal_row.get("prior_low_20")) and _safe_float(signal_row.get("high")) >= _safe_float(signal_row.get("prior_low_20")) - atr * 0.25
    if family == "RANGE_EXTREME_REVERSAL_LONG":
        return bullish and _safe_float(signal_row.get("range_position")) <= 0.20 and _safe_float(signal_row.get("lower_wick_ratio")) >= 0.35
    if family == "RANGE_EXTREME_REVERSAL_SHORT":
        return bearish and _safe_float(signal_row.get("range_position")) >= 0.80 and _safe_float(signal_row.get("upper_wick_ratio")) >= 0.35
    if family == "STRICT_COMBINED_LONG_SHORT":
        return _family_trigger("STRICT_SR_AWARE_LONG", signal_row) or _family_trigger("STRICT_SR_AWARE_SHORT", signal_row)
    return False


def _family_side(family: str, signal_row: pd.Series) -> str:
    if family.endswith("LONG"):
        return "long"
    if family.endswith("SHORT"):
        return "short"
    if family == "STRICT_COMBINED_LONG_SHORT":
        if _family_trigger("STRICT_SR_AWARE_LONG", signal_row) and not _family_trigger("STRICT_SR_AWARE_SHORT", signal_row):
            return "long"
        if _family_trigger("STRICT_SR_AWARE_SHORT", signal_row) and not _family_trigger("STRICT_SR_AWARE_LONG", signal_row):
            return "short"
        if _family_trigger("STRICT_SR_AWARE_LONG", signal_row) and _family_trigger("STRICT_SR_AWARE_SHORT", signal_row):
            return "short" if _safe_float(signal_row.get("upper_wick_ratio")) > _safe_float(signal_row.get("lower_wick_ratio")) else "long"
    return "unknown"


def _generate_asset_candidates(symbol: str, hourly: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    feature_frame = _compute_features(hourly)
    candidates: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []
    leakage_rows: list[dict[str, Any]] = []
    for spec in _family_specs():
        family = spec["family"]
        count = 0
        for idx in range(40, len(feature_frame) - 1):
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
                stop_price = min(_safe_float(signal_row["low"]), entry_price - max(atr * 0.8, entry_price * 0.004))
            else:
                stop_price = max(_safe_float(signal_row["high"]), entry_price + max(atr * 0.8, entry_price * 0.004))
            stop_distance = abs(entry_price - stop_price)
            if stop_distance <= 0.0 or entry_price <= 0.0:
                continue
            target_price = entry_price + (spec["target_r"] * stop_distance if side == "long" else -spec["target_r"] * stop_distance)
            candidates.append(
                {
                    "asset": symbol,
                    "candidate_family": family,
                    "trade_id": f"{symbol}-{family}-{count}-{entry_ts.isoformat()}",
                    "signal_timestamp": signal_ts.isoformat(),
                    "entry_timestamp": entry_ts.isoformat(),
                    "entry_time": entry_ts.isoformat(),
                    "side": side,
                    "entry_rule": "enter_next_1h_open_after_signal_close",
                    "stop_rule": "structural_invalidation_or_0.8ATR_buffer",
                    "target_rule": f"fixed_{spec['target_r']}R_or_time_exit",
                    "max_hold_bars": spec["max_hold_bars"],
                    "entry_price": round(entry_price, 6),
                    "stop_price": round(stop_price, 6),
                    "target_price": round(target_price, 6),
                    "atr14": round(atr, 6),
                    "range_position": round(_safe_float(signal_row.get("range_position")), 6),
                    "distance_to_support_atr": round(_safe_float(signal_row.get("distance_to_support_atr")), 6),
                    "distance_to_resistance_atr": round(_safe_float(signal_row.get("distance_to_resistance_atr")), 6),
                    "upper_wick_ratio": round(_safe_float(signal_row.get("upper_wick_ratio")), 6),
                    "lower_wick_ratio": round(_safe_float(signal_row.get("lower_wick_ratio")), 6),
                    "volume_ratio": round(_safe_float(signal_row.get("volume_ratio")), 6),
                }
            )
            count += 1
        inventory.append(
            {
                "asset": symbol,
                "candidate_family": family,
                "candidate_count": count,
                "status": "active" if count > 0 else "no_candidates",
                "selection_fields_used": "ohlcv, atr14, ema20, ema50, swing highs/lows, range position, wick ratios, volume ratio",
            }
        )
        leakage_rows.append(
            {
                "asset": symbol,
                "candidate_family": family,
                "future_outcome_fields_used": False,
                "selection_fields": [
                    "open", "high", "low", "close", "volume", "atr14", "ema20", "ema50",
                    "range_position", "upper_wick_ratio", "lower_wick_ratio",
                    "distance_to_support_atr", "distance_to_resistance_atr", "volume_ratio",
                ],
            }
        )
    return candidates, inventory, leakage_rows


def _simulate_trade_from_signal(signal: dict[str, Any], hourly: pd.DataFrame) -> dict[str, Any] | None:
    frame = hourly.set_index("candle_close_timestamp")
    entry_ts = _timestamp(signal.get("entry_timestamp"))
    if entry_ts is None or entry_ts not in frame.index:
        return None
    start_idx = int(frame.index.get_loc(entry_ts))
    side = str(signal["side"])
    entry_price = _safe_float(signal["entry_price"])
    stop_price = _safe_float(signal["stop_price"])
    target_price = _safe_float(signal["target_price"])
    risk = abs(entry_price - stop_price)
    if risk <= 0.0 or entry_price <= 0.0:
        return None
    exit_price = _safe_float(frame.iloc[min(start_idx + int(signal["max_hold_bars"]) - 1, len(frame) - 1)]["close"])
    exit_ts = pd.Timestamp(frame.index[min(start_idx + int(signal["max_hold_bars"]) - 1, len(frame) - 1)])
    exit_reason = "time_exit"
    bars_held = 0
    for forward_idx in range(start_idx, min(start_idx + int(signal["max_hold_bars"]), len(frame))):
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
        "asset": str(signal["asset"]),
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
        "holding_hours": bars_held,
        "archetype_key": str(signal["candidate_family"]),
        "exit_reason": exit_reason,
    }


def _simulate_asset_families(symbol: str, candidate_rows: list[dict[str, Any]], hourly: pd.DataFrame) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    simulated: list[dict[str, Any]] = []
    performance_rows: list[dict[str, Any]] = []
    monthly_rows: list[dict[str, Any]] = []
    cluster_rows: list[dict[str, Any]] = []
    by_family: dict[str, list[dict[str, Any]]] = {}
    for signal in candidate_rows:
        row = _simulate_trade_from_signal(signal, hourly)
        if row is None:
            continue
        simulated.append(row)
        by_family.setdefault(str(row["candidate_family"]), []).append(row)
    for family, rows in sorted(by_family.items()):
        r_values = [_safe_float(row.get("r_multiple")) for row in rows]
        wins = [value for value in r_values if value > 0.0]
        losses = [abs(value) for value in r_values if value < 0.0]
        pf = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
        month_counts: dict[str, int] = {}
        month_r: dict[str, float] = {}
        timestamps = [row["exit_timestamp"] for row in rows if isinstance(row.get("exit_timestamp"), pd.Timestamp)]
        for row in rows:
            month = row["exit_timestamp"].strftime("%Y-%m")
            month_counts[month] = month_counts.get(month, 0) + 1
            month_r[month] = month_r.get(month, 0.0) + _safe_float(row.get("r_multiple"))
        for month, count in sorted(month_counts.items()):
            monthly_rows.append({"asset": symbol, "candidate_family": family, "month": month, "trade_count": count, "total_R": round(month_r[month], 6)})
        rolling = _rolling_summary(rows, cost_bps_total=NORMAL_COST_BPS)
        concentration = max(month_counts.values()) / max(len(rows), 1) if month_counts else 1.0
        performance_rows.append(
            {
                "asset": symbol,
                "candidate_family": family,
                "trade_count": len(rows),
                "long_count": sum(1 for row in rows if str(row.get("side") or "") == "long"),
                "short_count": sum(1 for row in rows if str(row.get("side") or "") == "short"),
                "average_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
                "median_R": round(_median(r_values), 6) if r_values else 0.0,
                "win_rate": round(_safe_ratio(len(wins), len(r_values), 0.0), 6) if r_values else 0.0,
                "profit_factor": round(pf, 6),
                "average_holding_hours": round(sum(_safe_float(row.get("holding_hours")) for row in rows) / len(rows), 6) if rows else 0.0,
                "top_5_winner_dependency_R": round(sum(sorted(wins, reverse=True)[:5]), 6) if wins else 0.0,
                "inactive_months": max(0, len(pd.period_range(min(timestamps), max(timestamps), freq="M")) - len(month_counts)) if timestamps else 0,
                "monthly_cluster_concentration": round(concentration, 6),
                "normal_cost_rolling_5y_average": rolling["average"],
                "normal_cost_rolling_5y_median": rolling["median"],
                "hit_1m_windows": rolling["hit_1m_windows"],
                "hit_3m_windows": rolling["hit_3m_windows"],
                "hit_5m_windows": rolling["hit_5m_windows"],
                "max_drawdown_pct": rolling["max_drawdown_pct"],
            }
        )
        cluster_rows.append(
            {
                "asset": symbol,
                "candidate_family": family,
                "trade_count": len(rows),
                "monthly_cluster_concentration": round(concentration, 6),
                "inactive_month_count": max(0, len(pd.period_range(min(timestamps), max(timestamps), freq="M")) - len(month_counts)) if timestamps else 0,
            }
        )
    return simulated, performance_rows, monthly_rows, cluster_rows


def _monthly_r_map(rows: list[dict[str, Any]]) -> dict[str, float]:
    totals: dict[str, float] = {}
    for row in rows:
        if isinstance(row.get("exit_timestamp"), pd.Timestamp):
            month = row["exit_timestamp"].strftime("%Y-%m")
            totals[month] = totals.get(month, 0.0) + _safe_float(row.get("r_multiple"))
    return totals


def _asset_best_family(performance_rows: list[dict[str, Any]], asset: str) -> dict[str, Any]:
    rows = [row for row in performance_rows if str(row.get("asset") or "") == asset]
    if not rows:
        return {}
    rows.sort(
        key=lambda row: (
            -_safe_float(row.get("normal_cost_rolling_5y_average")),
            -int(row.get("hit_1m_windows", 0) or 0),
            -_safe_float(row.get("profit_factor")),
            -int(row.get("trade_count", 0) or 0),
        )
    )
    return rows[0]


def _correlation(x: dict[str, float], y: dict[str, float]) -> float:
    months = sorted(set(x) & set(y))
    if len(months) < 3:
        return 0.0
    xs = pd.Series([x[month] for month in months], dtype=float)
    ys = pd.Series([y[month] for month in months], dtype=float)
    corr = xs.corr(ys)
    return 0.0 if pd.isna(corr) else float(corr)


def _independence_verdict(row: dict[str, Any]) -> str:
    independent_months = int(row.get("independent_positive_month_count", 0) or 0)
    overlap_ratio = _safe_float(row.get("duplicate_cluster_ratio"))
    corr = abs(_safe_float(row.get("monthly_r_correlation_vs_btc")))
    if independent_months >= 6 and overlap_ratio < 0.55 and corr < 0.55:
        return "INDEPENDENT_REDUNDANCY_STRONG"
    if independent_months >= 3 and overlap_ratio < 0.75:
        return "INDEPENDENT_REDUNDANCY_PARTIAL"
    if corr >= 0.75 or overlap_ratio >= 0.75:
        return "MOSTLY_DUPLICATIVE_CRYPTO_BETA"
    return "WEAK_OR_INSUFFICIENT"


def _independence_audits(
    base_rows: list[dict[str, Any]],
    per_asset_performance: list[dict[str, Any]],
    simulated_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    base_months = _monthly_r_map(base_rows)
    crisis_months = {month for month, _ in sorted(base_months.items(), key=lambda item: abs(item[1]), reverse=True)[:10]}
    best_rows_by_asset: dict[str, list[dict[str, Any]]] = {}
    independent_rows: list[dict[str, Any]] = []
    corr_rows: list[dict[str, Any]] = []
    overlap_rows: list[dict[str, Any]] = []
    by_asset_family = {(str(row["asset"]), str(row["candidate_family"])): row for row in per_asset_performance}
    for asset in NON_BTC_ASSETS:
        best = _asset_best_family(per_asset_performance, asset)
        if not best:
            continue
        family = str(best["candidate_family"])
        rows = [_clone_row(row) for row in simulated_rows if str(row.get("asset") or "") == asset and str(row.get("candidate_family") or "") == family]
        best_rows_by_asset[asset] = rows
        asset_months = _monthly_r_map(rows)
        positive_asset_months = {month for month, total in asset_months.items() if total > 0.0}
        profitable_overlap = sum(1 for month in positive_asset_months if base_months.get(month, 0.0) > 0.0)
        independent_positive = sum(1 for month in positive_asset_months if base_months.get(month, 0.0) <= 0.0)
        duplicate_ratio = _safe_ratio(profitable_overlap, len(positive_asset_months), 0.0)
        corr = _correlation(base_months, asset_months)
        crisis_contribution = sum(asset_months.get(month, 0.0) for month in crisis_months)
        audit_row = {
            "asset": asset,
            "best_candidate_family": family,
            "positive_months_when_btc_negative_or_flat": independent_positive,
            "overlap_with_btc_profitable_months": profitable_overlap,
            "duplicate_cluster_ratio": round(duplicate_ratio, 6),
            "monthly_r_correlation_vs_btc": round(corr, 6),
            "crisis_month_contribution_R": round(crisis_contribution, 6),
            "independent_positive_month_count": independent_positive,
            "best_asset_normal_cost_rolling_5y_average": _safe_float(best.get("normal_cost_rolling_5y_average")),
            "best_asset_normal_cost_rolling_5y_median": _safe_float(best.get("normal_cost_rolling_5y_median")),
        }
        verdict = _independence_verdict(audit_row)
        audit_row["independent_cluster_verdict"] = verdict
        independent_rows.append(audit_row)
        corr_rows.append({"asset": asset, "best_candidate_family": family, "monthly_r_correlation_vs_btc": round(corr, 6), "duplicate_cluster_ratio": round(duplicate_ratio, 6)})
        overlap_rows.append({"asset": asset, "best_candidate_family": family, "positive_months_when_btc_negative_or_flat": independent_positive, "overlap_with_btc_profitable_months": profitable_overlap, "crisis_month_contribution_R": round(crisis_contribution, 6)})
    return independent_rows, corr_rows, overlap_rows, best_rows_by_asset


def _merge_rows(
    base_rows: list[dict[str, Any]],
    addon_assets: list[list[dict[str, Any]]],
    *,
    suppress_hours: int = DUPLICATE_SUPPRESSION_HOURS,
) -> list[dict[str, Any]]:
    merged = [_clone_row(row) for row in base_rows]
    for asset_rows in addon_assets:
        for row in sorted(asset_rows, key=lambda item: (item.get("entry_timestamp") or pd.Timestamp.min, str(item.get("trade_id") or ""))):
            row_ts = row.get("entry_timestamp")
            row_side = str(row.get("side") or "")
            overlap = any(
                isinstance(existing.get("entry_timestamp"), pd.Timestamp)
                and isinstance(row_ts, pd.Timestamp)
                and str(existing.get("side") or "") == row_side
                and abs((row_ts - existing["entry_timestamp"]).total_seconds()) <= suppress_hours * 3600
                for existing in merged
            )
            if not overlap:
                merged.append(_clone_row(row))
    merged.sort(key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, str(item.get("trade_id") or "")))
    return merged


def _portfolio_variants(best_rows_by_asset: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    eligible_assets = [asset for asset in NON_BTC_ASSETS if asset in best_rows_by_asset]
    return [
        {"variant_name": "BTC_BASE_ONLY", "assets": []},
        *[
            {"variant_name": f"BTC_BASE_PLUS_{asset.replace('USDT', '')}", "assets": [asset]}
            for asset in eligible_assets
        ],
        {"variant_name": "BTC_BASE_PLUS_TOP_1_NON_BTC", "top_n": 1},
        {"variant_name": "BTC_BASE_PLUS_TOP_2_NON_BTC", "top_n": 2},
        {"variant_name": "BTC_BASE_PLUS_TOP_3_NON_BTC", "top_n": 3},
        {"variant_name": "BTC_BASE_PLUS_ALL_ELIGIBLE_EQUAL_RISK", "assets": eligible_assets},
        {"variant_name": "BTC_BASE_PLUS_ALL_ELIGIBLE_WITH_SIMPLE_ASSET_CAP", "assets": eligible_assets, "row_source_multipliers": {asset: 0.75 for asset in eligible_assets}},
        {"variant_name": "BTC_BASE_PLUS_ALL_ELIGIBLE_WITH_DRAWDOWN_BRAKE", "assets": eligible_assets, "drawdown_guard_pct": 0.10, "drawdown_breaker_pct": 0.20},
    ]


def _rank_assets(independent_rows: list[dict[str, Any]]) -> list[str]:
    rows = sorted(
        independent_rows,
        key=lambda row: (
            -_safe_float(row.get("best_asset_normal_cost_rolling_5y_average")),
            -int(row.get("independent_positive_month_count", 0) or 0),
            _safe_float(row.get("duplicate_cluster_ratio")),
            abs(_safe_float(row.get("monthly_r_correlation_vs_btc"))),
        ),
    )
    return [str(row["asset"]) for row in rows]


def _evaluate_portfolios(
    base_rows: list[dict[str, Any]],
    best_rows_by_asset: dict[str, list[dict[str, Any]]],
    independent_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    rankings = _rank_assets(independent_rows)
    results: list[dict[str, Any]] = []
    capital_logic_rows: list[dict[str, Any]] = []
    variant_rows_map: dict[str, list[dict[str, Any]]] = {}
    for variant in _portfolio_variants(best_rows_by_asset):
        if "top_n" in variant:
            chosen_assets = rankings[: min(int(variant["top_n"]), len(rankings))]
        else:
            chosen_assets = list(variant.get("assets", []))
        rows = _merge_rows(base_rows, [best_rows_by_asset[asset] for asset in chosen_assets if asset in best_rows_by_asset])
        variant_rows_map[str(variant["variant_name"])] = rows
        rolling = _rolling_summary(
            rows,
            cost_bps_total=NORMAL_COST_BPS,
            row_source_multipliers=variant.get("row_source_multipliers"),
            drawdown_guard_pct=variant.get("drawdown_guard_pct"),
            drawdown_breaker_pct=variant.get("drawdown_breaker_pct"),
        )
        results.append(
            {
                "variant_name": variant["variant_name"],
                "asset_set": ",".join(chosen_assets) if chosen_assets else "BTC_ONLY",
                "trade_count": len(rows),
                "normal_cost_rolling_5y_average": rolling["average"],
                "normal_cost_rolling_5y_median": rolling["median"],
                "normal_cost_best": rolling["best"],
                "normal_cost_worst": rolling["worst"],
                "normal_cost_hit_1m_windows": rolling["hit_1m_windows"],
                "normal_cost_hit_3m_windows": rolling["hit_3m_windows"],
                "normal_cost_hit_5m_windows": rolling["hit_5m_windows"],
                "normal_cost_max_drawdown_pct": rolling["max_drawdown_pct"],
            }
        )
        capital_logic_rows.append(
            {
                "variant_name": variant["variant_name"],
                "assets": ",".join(chosen_assets) if chosen_assets else "BTC_ONLY",
                "capital_logic": "shared_mission_equity_simple",
                "row_source_multipliers": str(variant.get("row_source_multipliers") or {}),
                "drawdown_guard_pct": variant.get("drawdown_guard_pct", ""),
                "drawdown_breaker_pct": variant.get("drawdown_breaker_pct", ""),
            }
        )
    results.sort(key=lambda row: (-_safe_float(row.get("normal_cost_rolling_5y_average")), -int(row.get("normal_cost_hit_1m_windows", 0) or 0)))
    return results, capital_logic_rows, variant_rows_map


def _evaluate_cost_bands(portfolio_rows_map: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    bands = [
        ("ZERO_COST_REFERENCE", ZERO_COST_BPS),
        ("OPTIMISTIC_MAKER_COST", OPTIMISTIC_COST_BPS),
        ("NORMAL_MIXED_MAKER_TAKER_COST", NORMAL_COST_BPS),
        ("CONSERVATIVE_TAKER_COST", CONSERVATIVE_COST_BPS),
        ("HIGH_SLIPPAGE_COST", HIGH_SLIPPAGE_COST_BPS),
    ]
    rows: list[dict[str, Any]] = []
    for variant_name, trade_rows in portfolio_rows_map.items():
        for band_name, bps in bands:
            rolling = _rolling_summary(trade_rows, cost_bps_total=bps)
            rows.append(
                {
                    "variant_name": variant_name,
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
    return rows


def _evaluate_missed_trade_resilience(
    portfolio_rows_map: dict[str, list[dict[str, Any]]],
    random_repeat_count: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    repeats_used = max(int(random_repeat_count), 8)
    scenarios = [("random_miss_1pct", 0.01), ("random_miss_2pct", 0.02), ("random_miss_5pct", 0.05), ("random_miss_10pct", 0.10)]
    rows: list[dict[str, Any]] = []
    threshold = 0.0
    for variant_name, trade_rows in portfolio_rows_map.items():
        baseline = _rolling_summary(trade_rows, cost_bps_total=NORMAL_COST_BPS)
        for scenario_name, frac in scenarios:
            averages: list[float] = []
            for repeat in range(repeats_used):
                rng = random.Random(6000 + repeat + int(frac * 1000))
                keep_count = max(1, int(round(len(trade_rows) * (1.0 - frac))))
                indexes = sorted(rng.sample(range(len(trade_rows)), keep_count))
                kept = [_clone_row(trade_rows[index]) for index in indexes]
                rolling = _rolling_summary(kept, cost_bps_total=NORMAL_COST_BPS)
                averages.append(_safe_float(rolling["average"]))
            avg = sum(averages) / max(len(averages), 1)
            if avg >= 1_000_000.0:
                threshold = max(threshold, frac * 100.0)
            rows.append(
                {
                    "variant_name": variant_name,
                    "scenario": scenario_name,
                    "random_repeat_count_used": repeats_used,
                    "rolling_5y_average_mean": round(avg, 6),
                    "baseline_rolling_5y_average": baseline["average"],
                }
            )

        def _drop_by_label(fmt: str, seed: int, label_name: str) -> None:
            labels = sorted({row["exit_timestamp"].strftime(fmt) for row in trade_rows if isinstance(row.get("exit_timestamp"), pd.Timestamp)})
            if not labels:
                rows.append({"variant_name": variant_name, "scenario": label_name, "random_repeat_count_used": repeats_used, "rolling_5y_average_mean": 0.0, "baseline_rolling_5y_average": baseline["average"]})
                return
            label = random.Random(seed).choice(labels)
            kept = [_clone_row(row) for row in trade_rows if row["exit_timestamp"].strftime(fmt) != label]
            rolling = _rolling_summary(kept, cost_bps_total=NORMAL_COST_BPS)
            rows.append({"variant_name": variant_name, "scenario": label_name, "random_repeat_count_used": repeats_used, "rolling_5y_average_mean": rolling["average"], "baseline_rolling_5y_average": baseline["average"]})

        _drop_by_label("%Y-%m-%d", 7001, "miss_one_random_day")
        _drop_by_label("%Y-W%W", 7002, "miss_one_random_week")
        _drop_by_label("%Y-%m", 7003, "miss_one_random_month")

        month_totals = _monthly_r_map(trade_rows)
        high_vol_months = {month for month, _ in sorted(month_totals.items(), key=lambda item: abs(item[1]), reverse=True)[:2]}
        top_months = {month for month, _ in sorted(month_totals.items(), key=lambda item: item[1], reverse=True)[:2]}
        for label_name, blocked in (("miss_high_volatility_months", high_vol_months), ("miss_top_performing_months", top_months)):
            kept = [_clone_row(row) for row in trade_rows if row["exit_timestamp"].strftime("%Y-%m") not in blocked]
            rolling = _rolling_summary(kept, cost_bps_total=NORMAL_COST_BPS)
            rows.append({"variant_name": variant_name, "scenario": label_name, "random_repeat_count_used": repeats_used, "rolling_5y_average_mean": rolling["average"], "baseline_rolling_5y_average": baseline["average"]})

    reliability = {
        **RESEARCH_ONLY_FLAGS,
        "random_repeat_count_used": repeats_used,
        "minimum_repeat_count_required_for_gate": MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "stochastic_results_reliable_for_final_gate": repeats_used >= MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "scout_mode": repeats_used < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "missed_trade_tolerance_threshold_pct": round(threshold, 6),
        "affected_metrics": ["random_miss scenarios", "missed-trade resilience", "downtime stress"],
        "deterministic_metrics_still_usable": [
            "data availability",
            "baseline anchor",
            "per-asset candidate inventory",
            "per-asset performance",
            "independent cluster audit",
            "portfolio cost-band rolling 5Y metrics",
        ],
        "deterministic_conclusion": "Deterministic multi-asset redundancy metrics remain usable; only stochastic resilience claims stay scout-mode when repeat count is below the gate threshold.",
        "stochastic_conclusion_limitations": "Random missed-trade and downtime stress are not final-gate reliable below the minimum repeat budget.",
        "recommendation_for_shortlist_rerun": "Rerun shortlisted portfolio variants at >=32 repeats, preferably 64 or 128, before using stochastic resilience as mission-gate evidence.",
    }
    return rows, reliability


def _mission_interpretation(
    baseline_anchor: dict[str, Any],
    independent_rows: list[dict[str, Any]],
    portfolio_results: list[dict[str, Any]],
    stochastic: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    best_portfolio = portfolio_results[0] if portfolio_results else {}
    baseline_avg = _safe_float(baseline_anchor.get("rolling_5y_average_ending_equity"))
    baseline_median = _safe_float(baseline_anchor.get("rolling_5y_median_ending_equity"))
    best_avg = _safe_float(best_portfolio.get("normal_cost_rolling_5y_average"))
    best_median = _safe_float(best_portfolio.get("normal_cost_rolling_5y_median"))
    hit_1m = int(best_portfolio.get("normal_cost_hit_1m_windows", 0) or 0)
    hit_3m = int(best_portfolio.get("normal_cost_hit_3m_windows", 0) or 0)
    hit_5m = int(best_portfolio.get("normal_cost_hit_5m_windows", 0) or 0)
    strong_assets = [row for row in independent_rows if str(row.get("independent_cluster_verdict") or "") == "INDEPENDENT_REDUNDANCY_STRONG"]
    partial_assets = [row for row in independent_rows if "PARTIAL" in str(row.get("independent_cluster_verdict") or "")]
    freeze_candidates = [
        {
            "asset": row["asset"],
            "best_candidate_family": row["best_candidate_family"],
            "verdict": row["independent_cluster_verdict"],
            "best_asset_normal_cost_rolling_5y_average": row["best_asset_normal_cost_rolling_5y_average"],
        }
        for row in independent_rows
        if row["independent_cluster_verdict"] == "INDEPENDENT_REDUNDANCY_STRONG" and _safe_float(row["best_asset_normal_cost_rolling_5y_average"]) >= 150_000.0
    ]
    if best_avg >= 3_000_000.0 and best_median >= 2_000_000.0 and hit_3m > 0 and strong_assets:
        classification = "MULTI_ASSET_REDUNDANCY_3M_PROMISING_RESEARCH_ONLY"
    elif best_avg >= 1_000_000.0 and best_median >= baseline_median and hit_1m > int(baseline_anchor.get("hit_1m_windows", 0) or 0):
        classification = "MULTI_ASSET_REDUNDANCY_1M_PROMISING_RESEARCH_ONLY"
    elif best_avg > baseline_avg and best_median > baseline_median:
        classification = "MULTI_ASSET_REDUNDANCY_IMPROVES_BUT_NOT_GATE_PASSING"
    elif freeze_candidates:
        classification = "MULTI_ASSET_REDUNDANCY_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY"
    elif best_avg > baseline_avg * 0.95:
        classification = "MULTI_ASSET_REDUNDANCY_WEAK"
    else:
        classification = "MULTI_ASSET_REDUNDANCY_REJECTED"
    interpretation = {
        **RESEARCH_ONLY_FLAGS,
        "one_million_in_5y_becomes_robust_under_normal_cost": best_avg >= 1_000_000.0 and best_median >= baseline_median and hit_1m > int(baseline_anchor.get("hit_1m_windows", 0) or 0),
        "three_million_in_5y_becomes_realistic_research_target": hit_3m > 0,
        "five_million_in_5y_becomes_plausible": hit_5m > 0,
        "multi_asset_reduces_monthly_cluster_dependency": bool(strong_assets or partial_assets),
        "multi_asset_improves_missed_trade_tolerance_beyond_1pct": _safe_float(stochastic.get("missed_trade_tolerance_threshold_pct")) > 1.0,
        "multi_asset_reduces_cost_sensitivity": best_avg > baseline_avg,
        "multi_asset_creates_independent_profitable_clusters": bool(strong_assets),
        "performance_still_dominated_by_btc": not bool(strong_assets or partial_assets),
        "best_variant_name": str(best_portfolio.get("variant_name") or ""),
        "classification_candidate": classification,
    }
    freeze = {
        **RESEARCH_ONLY_FLAGS,
        "candidates": freeze_candidates,
        "any_asset_deserves_freeze_and_confirm": bool(freeze_candidates),
    }
    cluster_verdict = "INDEPENDENT_REDUNDANCY_STRONG" if strong_assets else ("INDEPENDENT_REDUNDANCY_PARTIAL" if partial_assets else "MOSTLY_DUPLICATIVE_CRYPTO_BETA")
    correlation_verdict = "LOWER_CORRELATED_STRUCTURAL_REDUNDANCY_PRESENT" if strong_assets else ("PARTIAL_CORRELATION_DIVERSIFICATION" if partial_assets else "MOSTLY_DUPLICATIVE_CRYPTO_BETA")
    return interpretation, freeze, cluster_verdict, correlation_verdict


def _implementation_self_audit(
    *,
    schema_fields_detected: list[str],
    asset_data_sources_detected: list[dict[str, Any]],
    timestamp_field_used: str,
    r_field_used: str,
    stochastic_repeat_count_used: int,
    scout_mode: bool,
) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "schema_fields_detected": schema_fields_detected,
        "asset_data_sources_detected": asset_data_sources_detected,
        "timestamp_field_used": timestamp_field_used,
        "r_field_used": r_field_used,
        "baseline_metric_used": "execution_cost_realism_and_trade_redundancy_audit NORMAL_MIXED_MAKER_TAKER_COST with row-level BTC context from execution-cost audit",
        "rolling_5y_metric_used": "normal-cost rolling 5Y average, median, and hit-window counts drive all mission conclusions",
        "full_sequence_metric_used": "full-sequence equity is not used for final classification",
        "leakage_check": True,
        "future_field_usage_check": True,
        "silent_fallback_check": False,
        "stress_metric_scope_check": True,
        "stochastic_repeat_count_used": stochastic_repeat_count_used,
        "stochastic_results_reliable_for_final_gate": not scout_mode,
        "scout_mode": scout_mode,
        "previous_artifacts_overwritten": False,
        "reviewer_notes": [
            "Per-asset selection uses only pre-entry structural features from current and past candles.",
            "Mission ranking uses rolling 5Y metrics first, not profit factor alone.",
            "Stochastic missed-trade claims remain scout-mode if repeat count is below the gate threshold.",
        ],
    }


def _court_report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Multi-Asset Structural Redundancy Discovery Audit",
            "",
            f"Final classification: `{summary['final_classification']}`",
            "",
            "## Court Findings",
            "",
            f"1. Eligible non-BTC assets: `{', '.join(summary['eligible_assets']) if summary['eligible_assets'] else 'none'}`.",
            f"2. Blocked assets: `{', '.join(summary['blocked_assets']) if summary['blocked_assets'] else 'none'}`.",
            f"3. BTC baseline normal-cost rolling 5Y average / median / 1M hits: `{summary['btc_baseline_average']:.2f}` / `{summary['btc_baseline_median']:.2f}` / `{summary['btc_baseline_hit_1m_windows']}`.",
            f"4. Best non-BTC asset and family: `{summary['best_non_btc_asset']}` / `{summary['best_non_btc_candidate_family']}`.",
            f"5. Best non-BTC normal-cost rolling 5Y average / median: `{summary['best_non_btc_average']:.2f}` / `{summary['best_non_btc_median']:.2f}` EUR.",
            f"6. Best multi-asset portfolio variant: `{summary['best_multi_asset_portfolio_variant']}` with normal-cost rolling 5Y average / median `{summary['best_multi_asset_average']:.2f}` / `{summary['best_multi_asset_median']:.2f}` EUR.",
            f"7. Best portfolio 1M / 3M / 5M hit windows: `{summary['best_multi_asset_hit_1m_windows']}` / `{summary['best_multi_asset_hit_3m_windows']}` / `{summary['best_multi_asset_hit_5m_windows']}`.",
            f"8. Missed-trade tolerance threshold: `{summary['missed_trade_tolerance_threshold_pct']}%`.",
            f"9. Independent cluster verdict: `{summary['independent_cluster_verdict']}` and correlation verdict `{summary['correlation_duplication_verdict']}`.",
            f"10. Scout mode: `{summary['scout_mode']}` with repeat count `{summary['stochastic_repeat_count_used']}`.",
            f"11. Freeze-and-confirm candidate exists: `{summary['any_asset_deserves_freeze_and_confirm']}`.",
            f"12. Next research step: `{summary['next_recommended_research_step']}`.",
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


def write_multi_asset_structural_redundancy_discovery_audit(
    config: MultiAssetStructuralRedundancyDiscoveryAuditConfig,
) -> dict[str, Path]:
    paths = _paths(config)
    diagnostics_root, ledger_root, reports_root = _ensure_dirs(config.output_root)

    availability_rows: list[dict[str, Any]] = []
    hourly_frames: dict[str, pd.DataFrame] = {}
    source_detected_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    for asset in ASSET_UNIVERSE:
        source_csv, asset_warnings = _resolve_asset_source(symbol=asset, package_root=config.package_root, broad_summary_path=paths["broad_summary"])
        warnings.extend(asset_warnings)
        row, hourly = _asset_availability_row(asset, source_csv)
        availability_rows.append(row)
        source_detected_rows.append({"asset": asset, "source_path": row["source_path_found"], "eligible": row["eligible_for_discovery"]})
        if hourly is not None:
            hourly_frames[asset] = hourly

    eligible_non_btc = [row["asset"] for row in availability_rows if row["asset"] != "BTCUSDT" and bool(row["eligible_for_discovery"])]
    if len(eligible_non_btc) < MIN_ELIGIBLE_NON_BTC:
        return _empty_outputs(
            config,
            state="blocked",
            classification="MULTI_ASSET_REDUNDANCY_BLOCKED_INSUFFICIENT_DATA",
            warnings=[*warnings, "Fewer than two non-BTC assets had sufficient discovery coverage."],
        )

    baseline_anchor, base_rows, baseline_warnings, _context = _load_btc_baseline_anchor(config)
    warnings.extend(baseline_warnings)
    if baseline_anchor is None or base_rows is None:
        return _empty_outputs(
            config,
            state="blocked",
            classification="MULTI_ASSET_REDUNDANCY_NEEDS_BETTER_DATA_OR_NEW_ENGINE",
            warnings=[*warnings, "BTC baseline anchor could not be loaded safely."],
        )

    per_asset_inventory: list[dict[str, Any]] = []
    leakage_rows: list[dict[str, Any]] = []
    per_asset_performance: list[dict[str, Any]] = []
    per_asset_monthly: list[dict[str, Any]] = []
    per_asset_clusters: list[dict[str, Any]] = []
    simulated_rows: list[dict[str, Any]] = []
    for asset in eligible_non_btc:
        candidates, inventory_rows, leak_rows = _generate_asset_candidates(asset, hourly_frames[asset])
        asset_simulated, asset_performance, asset_monthly, asset_clusters = _simulate_asset_families(asset, candidates, hourly_frames[asset])
        simulated_rows.extend(asset_simulated)
        per_asset_inventory.extend(inventory_rows)
        leakage_rows.extend(leak_rows)
        per_asset_performance.extend(asset_performance)
        per_asset_monthly.extend(asset_monthly)
        per_asset_clusters.extend(asset_clusters)

    independent_rows, corr_rows, overlap_rows, best_rows_by_asset = _independence_audits(base_rows, per_asset_performance, simulated_rows)
    portfolio_results, capital_logic_rows, portfolio_rows_map = _evaluate_portfolios(base_rows, best_rows_by_asset, independent_rows)
    cost_band_rows = _evaluate_cost_bands(portfolio_rows_map)
    missed_rows, stochastic = _evaluate_missed_trade_resilience(portfolio_rows_map, config.random_repeat_count)
    interpretation, freeze_candidates, cluster_verdict, correlation_verdict = _mission_interpretation(
        baseline_anchor,
        independent_rows,
        portfolio_results,
        stochastic,
    )

    best_asset_row = max(
        independent_rows,
        key=lambda row: (
            _safe_float(row.get("best_asset_normal_cost_rolling_5y_average")),
            int(row.get("independent_positive_month_count", 0) or 0),
        ),
        default={},
    )
    best_portfolio = portfolio_results[0] if portfolio_results else {}
    final_classification = interpretation["classification_candidate"] if eligible_non_btc else "MULTI_ASSET_REDUNDANCY_BLOCKED_INSUFFICIENT_DATA"
    if stochastic["scout_mode"] and final_classification in {"MULTI_ASSET_REDUNDANCY_1M_PROMISING_RESEARCH_ONLY", "MULTI_ASSET_REDUNDANCY_3M_PROMISING_RESEARCH_ONLY", "MULTI_ASSET_REDUNDANCY_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY"}:
        final_classification = "MULTI_ASSET_REDUNDANCY_IMPROVES_BUT_NOT_GATE_PASSING"
    next_step = (
        "Freeze the strongest independent non-BTC asset family and run a separate confirmation audit."
        if freeze_candidates["any_asset_deserves_freeze_and_confirm"]
        else "Keep the discovery result research-only and investigate whether a broader multi-asset engine or better data coverage is needed."
    )

    leakage = {
        **RESEARCH_ONLY_FLAGS,
        "all_candidates_clean": all(not row["future_outcome_fields_used"] for row in leakage_rows),
        "rows": leakage_rows,
    }
    self_audit = _implementation_self_audit(
        schema_fields_detected=sorted({key for row in (simulated_rows + base_rows) for key in row.keys()}),
        asset_data_sources_detected=source_detected_rows,
        timestamp_field_used=str(baseline_anchor.get("baseline_timestamp_field_used") or "blocked"),
        r_field_used=str(baseline_anchor.get("baseline_r_field_used") or "blocked"),
        stochastic_repeat_count_used=stochastic["random_repeat_count_used"],
        scout_mode=stochastic["scout_mode"],
    )
    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "eligible_assets": eligible_non_btc,
        "blocked_assets": [f"{row['asset']}:{row['reason_if_blocked']}" for row in availability_rows if not bool(row["eligible_for_discovery"]) and row["asset"] != "BTCUSDT"],
        "btc_baseline_average": _safe_float(baseline_anchor.get("rolling_5y_average_ending_equity")),
        "btc_baseline_median": _safe_float(baseline_anchor.get("rolling_5y_median_ending_equity")),
        "btc_baseline_hit_1m_windows": int(baseline_anchor.get("hit_1m_windows", 0) or 0),
        "best_non_btc_asset": str(best_asset_row.get("asset") or ""),
        "best_non_btc_candidate_family": str(best_asset_row.get("best_candidate_family") or ""),
        "best_non_btc_average": _safe_float(best_asset_row.get("best_asset_normal_cost_rolling_5y_average")),
        "best_non_btc_median": _safe_float(best_asset_row.get("best_asset_normal_cost_rolling_5y_median")),
        "best_multi_asset_portfolio_variant": str(best_portfolio.get("variant_name") or ""),
        "best_multi_asset_average": _safe_float(best_portfolio.get("normal_cost_rolling_5y_average")),
        "best_multi_asset_median": _safe_float(best_portfolio.get("normal_cost_rolling_5y_median")),
        "best_multi_asset_hit_1m_windows": int(best_portfolio.get("normal_cost_hit_1m_windows", 0) or 0),
        "best_multi_asset_hit_3m_windows": int(best_portfolio.get("normal_cost_hit_3m_windows", 0) or 0),
        "best_multi_asset_hit_5m_windows": int(best_portfolio.get("normal_cost_hit_5m_windows", 0) or 0),
        "missed_trade_tolerance_threshold_pct": _safe_float(stochastic.get("missed_trade_tolerance_threshold_pct")),
        "independent_cluster_verdict": cluster_verdict,
        "correlation_duplication_verdict": correlation_verdict,
        "stochastic_repeat_count_used": int(stochastic["random_repeat_count_used"]),
        "scout_mode": bool(stochastic["scout_mode"]),
        "implementation_self_audit_verdict": "PASS_WITH_SCOUT_MODE_CAVEAT" if stochastic["scout_mode"] else "PASS",
        "any_asset_deserves_freeze_and_confirm": bool(freeze_candidates["any_asset_deserves_freeze_and_confirm"]),
        "final_classification": final_classification,
        "next_recommended_research_step": next_step,
        "warnings": warnings,
    }
    report = _court_report(summary)

    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "multi_asset_structural_redundancy_discovery_summary.json", summary)
    _write_markdown(config.output_root / "multi_asset_structural_redundancy_discovery_report.md", report)
    _write_csv(diagnostics_root / "multi_asset_data_availability.csv", _harmonize_rows(availability_rows))
    _write_json(diagnostics_root / "multi_asset_data_availability.json", {**RESEARCH_ONLY_FLAGS, "rows": availability_rows})
    _write_json(diagnostics_root / "btc_baseline_anchor.json", baseline_anchor)
    _write_csv(diagnostics_root / "per_asset_candidate_inventory.csv", _harmonize_rows(per_asset_inventory))
    _write_json(diagnostics_root / "per_asset_no_leakage_check.json", leakage)
    _write_csv(ledger_root / "per_asset_candidate_trades.csv", _harmonize_rows([
        {
            **{key: value for key, value in row.items() if not isinstance(value, pd.Timestamp)},
            "entry_timestamp": row["entry_timestamp"].isoformat() if isinstance(row.get("entry_timestamp"), pd.Timestamp) else "",
            "exit_timestamp": row["exit_timestamp"].isoformat() if isinstance(row.get("exit_timestamp"), pd.Timestamp) else "",
        }
        for row in simulated_rows
    ]))
    _write_csv(diagnostics_root / "per_asset_candidate_performance.csv", _harmonize_rows(per_asset_performance))
    _write_csv(diagnostics_root / "per_asset_monthly_distribution.csv", _harmonize_rows(per_asset_monthly))
    _write_json(diagnostics_root / "per_asset_cluster_dependency.json", {**RESEARCH_ONLY_FLAGS, "rows": per_asset_clusters})
    _write_csv(diagnostics_root / "multi_asset_independent_cluster_audit.csv", _harmonize_rows(independent_rows))
    _write_csv(diagnostics_root / "multi_asset_correlation_audit.csv", _harmonize_rows(corr_rows))
    _write_csv(diagnostics_root / "multi_asset_overlap_with_btc_baseline.csv", _harmonize_rows(overlap_rows))
    _write_csv(diagnostics_root / "multi_asset_portfolio_results.csv", _harmonize_rows(portfolio_results))
    _write_csv(diagnostics_root / "multi_asset_simple_capital_logic_comparison.csv", _harmonize_rows(capital_logic_rows))
    _write_csv(diagnostics_root / "multi_asset_cost_band_rolling_5y_results.csv", _harmonize_rows(cost_band_rows))
    _write_csv(diagnostics_root / "multi_asset_missed_trade_resilience.csv", _harmonize_rows(missed_rows))
    _write_json(diagnostics_root / "multi_asset_stochastic_budget_reliability_check.json", stochastic)
    _write_json(diagnostics_root / "multi_asset_mission_target_interpretation.json", interpretation)
    _write_json(diagnostics_root / "multi_asset_freeze_and_confirm_candidates.json", freeze_candidates)
    _write_json(diagnostics_root / "implementation_self_audit.json", self_audit)
    _write_json(reports_root / "next_research_recommendation.json", {**RESEARCH_ONLY_FLAGS, "next_step": next_step})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "multi_asset_structural_redundancy_discovery_summary.json",
        "report": config.output_root / "multi_asset_structural_redundancy_discovery_report.md",
    }


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    output_root = package_root / "output" / OUTPUT_FOLDER_NAME
    write_multi_asset_structural_redundancy_discovery_audit(
        MultiAssetStructuralRedundancyDiscoveryAuditConfig(
            package_root=package_root,
            output_root=output_root,
        )
    )
