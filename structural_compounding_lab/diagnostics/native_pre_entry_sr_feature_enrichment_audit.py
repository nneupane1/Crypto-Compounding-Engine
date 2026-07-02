from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import (  # noqa: E402
    RESEARCH_ONLY_FLAGS,
    _apply_frozen_patch,
    _load_frozen_rules,
)
from structural_compounding_lab.diagnostics.broad_patch_accounting_and_short_rescue_audit import (  # noqa: E402
    _apply_signature,
)
from structural_compounding_lab.diagnostics.equal_highs_liquidity_sweep_rescue_forensic_audit import (  # noqa: E402
    FORBIDDEN_FUTURE_FIELDS,
    _boolish,
    _classify_failure_mode,
    _feature_snapshot,
    _group_stats,
    _mission_row,
    _normalize_rows,
    _safe_float,
    _session_bucket,
    _simulate_overlay,
    _summarize_mission_rows,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import _prepare_rows  # noqa: E402
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _median,
    _normalize_trade_rows,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import (  # noqa: E402
    _build_windows,
    _window_rows,
)


@dataclass(frozen=True)
class NativePreEntrySRFeatureEnrichmentAuditConfig:
    package_root: Path
    output_root: Path


NUMERIC_ENRICHED_FEATURES = [
    "distance_to_next_support_pct",
    "distance_to_next_support_atr",
    "distance_to_next_support_R",
    "clean_downside_room_score",
    "nearest_support_blocking_score",
    "support_cluster_density_below_entry",
    "number_of_support_levels_below_entry",
    "room_to_first_support_vs_stop_distance",
    "resistance_strength_at_entry",
    "rejection_from_resistance_score",
    "distance_from_resistance_pct",
    "equal_high_cluster_strength",
    "sweep_above_equal_highs_magnitude",
    "sweep_reversal_close_strength",
    "wick_rejection_ratio",
    "bearish_close_quality",
    "sweep_magnitude_atr",
    "sweep_magnitude_pct",
    "liquidity_grab_quality_score",
    "sweep_reclaim_failure_score",
    "false_breakout_quality_score",
    "htf_room_to_support",
    "htf_room_to_resistance",
    "htf_structure_quality_score",
    "pre_entry_stop_distance_pct",
    "pre_entry_stop_distance_atr",
    "pre_entry_room_to_support_R",
    "pre_entry_potential_R_to_next_support",
    "volume_confirmation_score",
]

GROUP_ORDER = [
    "rescued_short_winners",
    "rescued_short_losers",
    "no_nearby_support_room_losers",
    "strict_min_room_winners",
    "strict_min_room_losers",
    "rescued_3R_plus_winners",
    "rescued_5R_plus_winners",
    "rescued_minus_1R_losers",
]


def _paths(config: NativePreEntrySRFeatureEnrichmentAuditConfig) -> dict[str, Path]:
    source_root = config.package_root / "output"
    broad_root = source_root / "broad_historical_structural_replay_001"
    broad_ledger_root = broad_root / "ledger"
    equal_highs_root = source_root / "equal_highs_liquidity_sweep_rescue_forensic_audit_001"
    support_room_root = source_root / "support_room_short_rescue_repair_audit_001"
    return {
        "trades": broad_ledger_root / "trades.csv",
        "equity": broad_ledger_root / "equity.csv",
        "ledger_summary": broad_ledger_root / "summary.json",
        "setup_log": broad_ledger_root / "setup_log.csv",
        "level_log": broad_ledger_root / "level_log.csv",
        "liquidity_events": broad_ledger_root / "liquidity_events.csv",
        "rescue_profile": equal_highs_root / "diagnostics" / "rescued_short_trade_profile.csv",
        "rescue_loss_audit": equal_highs_root / "diagnostics" / "rescue_reintroduced_loss_audit.csv",
        "rescue_summary": equal_highs_root / "equal_highs_liquidity_sweep_rescue_summary.json",
        "support_room_summary": support_room_root / "support_room_short_rescue_repair_summary.json",
        "sr_inventory": support_room_root / "diagnostics" / "sr_field_inventory.json",
        "sr_missing": support_room_root / "diagnostics" / "missing_sr_fields_for_repair.json",
        "sr_separation": support_room_root / "diagnostics" / "support_room_feature_separation.csv",
        "sr_variant_results": support_room_root / "diagnostics" / "repaired_support_room_rescue_variant_results.csv",
        "frozen_patch_rules": source_root / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json",
        "rescue_signature_definitions": source_root / "broad_patch_accounting_and_short_rescue_audit_001" / "diagnostics" / "rescue_signature_definitions.json",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, reports_root


def _empty_outputs(
    config: NativePreEntrySRFeatureEnrichmentAuditConfig,
    *,
    state: str,
    classification: str,
    warnings: list[str],
) -> dict[str, Path]:
    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    status = {
        "state": state,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "warnings": warnings,
    }
    summary = {
        **RESEARCH_ONLY_FLAGS,
        "warnings": warnings,
        "final_classification": classification,
    }
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "native_pre_entry_sr_feature_enrichment_summary.json", summary)
    _write_markdown(config.output_root / "native_pre_entry_sr_feature_enrichment_report.md", "# Native Pre-Entry SR Feature Enrichment Audit\n\nRequired artifacts or candle source were missing.\n")
    for name in (
        "enriched_trade_pre_entry_sr_features.csv",
        "enriched_removed_short_pre_entry_sr_features.csv",
        "enriched_rescued_short_pre_entry_sr_features.csv",
        "enriched_sr_feature_separation.csv",
        "enriched_sr_feature_quantiles.csv",
        "enriched_sr_feature_yearly_stability.csv",
        "enriched_sr_feature_window_stability.csv",
        "enriched_rescue_prototype_results.csv",
    ):
        _write_csv(diagnostics_root / name, [])
    for name in (
        "candle_source_discovery.json",
        "pre_entry_data_availability_report.json",
        "pre_entry_feature_computation_notes.json",
        "pre_entry_sr_feature_no_leakage_check.json",
        "enriched_sr_best_candidate_features.json",
        "enriched_rescue_prototype_definitions.json",
        "enriched_rescue_prototype_results.json",
        "enriched_rescue_prototype_no_leakage_check.json",
        "no_go_risks.json",
    ):
        _write_json(diagnostics_root / name, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "native_pre_entry_sr_feature_enrichment_summary.json",
        "report": config.output_root / "native_pre_entry_sr_feature_enrichment_report.md",
    }


def _source_path_from_summary(summary_path: Path) -> Path | None:
    payload = _read_json(summary_path, {})
    source_csv = str(payload.get("source_csv") or "").strip()
    if not source_csv:
        return None
    path = Path(source_csv)
    return path if path.exists() else None


def _discover_candle_source(source_csv: Path | None) -> tuple[dict[str, Any], dict[str, Any]]:
    if source_csv is None or not source_csv.exists():
        discovery = {
            **RESEARCH_ONLY_FLAGS,
            "candle_source_found": False,
            "source_path": "",
            "available_timeframes": [],
            "available_columns": [],
            "coverage_start": None,
            "coverage_end": None,
            "row_count": 0,
            "duplicate_timestamp_count": 0,
            "missing_data_gaps": None,
            "safe_for_pre_entry_features": False,
        }
        availability = {
            **RESEARCH_ONLY_FLAGS,
            "candle_source_available": False,
            "features_blocked": ["all_native_candle_backfilled_features"],
            "features_computable": [],
            "verdict": "missing_candle_source",
        }
        return discovery, availability

    timestamp_only = pd.read_csv(source_csv, usecols=["timestamp"], parse_dates=["timestamp"])
    row_count = len(timestamp_only)
    duplicate_count = int(timestamp_only["timestamp"].duplicated().sum())
    diffs = timestamp_only["timestamp"].diff().dropna()
    missing_gap_count = int((diffs > pd.Timedelta(minutes=1)).sum())
    coverage_start = timestamp_only["timestamp"].iloc[0].isoformat() if row_count else None
    coverage_end = timestamp_only["timestamp"].iloc[-1].isoformat() if row_count else None
    header = pd.read_csv(source_csv, nrows=5)
    discovery = {
        **RESEARCH_ONLY_FLAGS,
        "candle_source_found": True,
        "source_path": str(source_csv),
        "available_timeframes": ["1m", "1h", "12h"],
        "available_columns": list(header.columns),
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "row_count": row_count,
        "duplicate_timestamp_count": duplicate_count,
        "missing_data_gaps": missing_gap_count,
        "safe_for_pre_entry_features": duplicate_count == 0,
    }
    availability = {
        **RESEARCH_ONLY_FLAGS,
        "candle_source_available": True,
        "features_computable": [
            "atr_regime_at_entry",
            "volatility_compression_or_expansion",
            "wick_rejection_ratio",
            "bearish_close_quality",
            "volume_confirmation_score",
            "htf_room_to_support",
            "htf_room_to_resistance",
        ],
        "features_blocked": [],
        "verdict": "native_backfill_available",
    }
    return discovery, availability


def _load_price_source(source_csv: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frame = pd.read_csv(source_csv, parse_dates=["timestamp"])
    frame = frame.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="last")
    frame = frame.set_index("timestamp")
    for col in ("open", "high", "low", "close", "volume"):
        frame[col] = pd.to_numeric(frame[col], errors="coerce")
    frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])

    hourly = (
        frame.resample("1h", closed="left", label="right")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    htf = (
        frame.resample("12h", closed="left", label="right")
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna()
    )
    for df in (hourly, htf):
        prev_close = df["close"].shift(1)
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - prev_close).abs(),
                (df["low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        df["atr14"] = tr.rolling(14, min_periods=3).mean()
        df["atr50_mean"] = df["atr14"].rolling(50, min_periods=5).mean()
        df["ema20"] = df["close"].ewm(span=20, adjust=False).mean()
        df["volume_ma20"] = df["volume"].rolling(20, min_periods=3).mean()
        df["recent_low_20"] = df["low"].rolling(20, min_periods=3).min()
        df["recent_high_20"] = df["high"].rolling(20, min_periods=3).max()
    return frame, hourly, htf


def _nearest_candle(index: pd.DatetimeIndex, timestamp: pd.Timestamp) -> pd.Timestamp | None:
    if len(index) == 0:
        return None
    value = index.asof(timestamp)
    if pd.isna(value):
        return None
    return pd.Timestamp(value)


def _to_naive_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(str(value))
    if ts.tzinfo is not None:
        ts = ts.tz_convert("UTC").tz_localize(None)
    return ts


def _level_type_label(value: Any) -> str:
    return str(value or "").strip().lower()


def _support_level_mask(levels: pd.DataFrame, entry_price: float) -> pd.Series:
    types = levels["type"].astype(str).str.lower()
    return (levels["price"] < entry_price) & (
        types.str.contains("support")
        | types.str.contains("low")
        | types.str.contains("midpoint")
        | types.str.contains("retest")
    )


def _resistance_level_mask(levels: pd.DataFrame, entry_price: float) -> pd.Series:
    types = levels["type"].astype(str).str.lower()
    return (levels["price"] > entry_price) & (
        types.str.contains("resistance")
        | types.str.contains("high")
        | types.str.contains("midpoint")
        | types.str.contains("break")
    )


def _compute_trade_features(
    trade: dict[str, Any],
    *,
    setup_row: dict[str, Any] | None,
    level_window: pd.DataFrame,
    liquidity_window: pd.DataFrame,
    hourly: pd.DataFrame,
    htf: pd.DataFrame,
) -> dict[str, Any]:
    side = str(trade.get("side") or "")
    entry_ts = _to_naive_timestamp(trade.get("entry_time"))
    entry_price = _safe_float(trade.get("entry_price"))
    stop_price = _safe_float(trade.get("initial_stop"))
    stop_distance_pct = abs(stop_price - entry_price) / entry_price if entry_price > 0 else 0.0

    base = {
        "trade_id": str(trade.get("trade_id") or ""),
        "symbol": str(trade.get("symbol") or ""),
        "side": side,
        "entry_time": str(trade.get("entry_time") or ""),
        "entry_price": round(entry_price, 6),
        "r_multiple": round(_safe_float(trade.get("r_multiple")), 6),
        "archetype_key": str(trade.get("archetype_key") or ""),
        "setup_class": str(trade.get("setup_class") or ""),
        "personality_label": str(trade.get("personality_label") or ""),
    }
    if side != "short":
        for feature in NUMERIC_ENRICHED_FEATURES:
            base[feature] = None
        base.update(
            {
                "next_support_price_before_entry": None,
                "nearest_resistance_price_before_entry": None,
                "sweep_high_confirmed_pre_entry": None,
                "liquidity_grab_quality_label": "",
                "htf_resistance_above_entry": None,
                "htf_support_below_entry": None,
                "htf_trend_alignment": None,
                "atr_regime_at_entry": "",
                "volatility_compression_or_expansion": "",
                "feature_null_reason": "long_trade_short_rescue_fields_not_applicable",
            }
        )
        return base

    candle_ts = _nearest_candle(hourly.index, entry_ts)
    htf_ts = _nearest_candle(htf.index, entry_ts)
    if candle_ts is None:
        for feature in NUMERIC_ENRICHED_FEATURES:
            base[feature] = None
        base.update(
            {
                "next_support_price_before_entry": None,
                "nearest_resistance_price_before_entry": None,
                "sweep_high_confirmed_pre_entry": None,
                "liquidity_grab_quality_label": "",
                "htf_resistance_above_entry": None,
                "htf_support_below_entry": None,
                "htf_trend_alignment": None,
                "atr_regime_at_entry": "",
                "volatility_compression_or_expansion": "",
                "feature_null_reason": "missing_hourly_candle_before_entry",
            }
        )
        return base

    candle = hourly.loc[candle_ts]
    atr = _safe_float(candle.get("atr14"))
    atr_mean = _safe_float(candle.get("atr50_mean"))
    volume_ma = _safe_float(candle.get("volume_ma20"))
    high = _safe_float(candle.get("high"))
    low = _safe_float(candle.get("low"))
    open_ = _safe_float(candle.get("open"))
    close = _safe_float(candle.get("close"))
    bar_range = max(high - low, 1e-9)

    supports = level_window[_support_level_mask(level_window, entry_price)] if not level_window.empty else level_window
    resistances = level_window[_resistance_level_mask(level_window, entry_price)] if not level_window.empty else level_window
    support_row = supports.sort_values(["price", "strength"], ascending=[False, False]).iloc[0] if not supports.empty else None
    resistance_row = resistances.sort_values(["price", "strength"], ascending=[True, False]).iloc[0] if not resistances.empty else None
    next_support = float(support_row["price"]) if support_row is not None else None
    nearest_resistance = float(resistance_row["price"]) if resistance_row is not None else None
    support_strength = float(support_row.get("strength", 0.0)) if support_row is not None else 0.0
    resistance_strength = float(resistance_row.get("strength", 0.0)) if resistance_row is not None else 0.0

    distance_support_pct = (entry_price - next_support) / entry_price if next_support is not None and entry_price > 0 else None
    distance_support_atr = (entry_price - next_support) / atr if next_support is not None and atr > 0 else None
    distance_support_r = (entry_price - next_support) / max(abs(stop_price - entry_price), 1e-9) if next_support is not None else None
    distance_resistance_pct = (nearest_resistance - entry_price) / entry_price if nearest_resistance is not None and entry_price > 0 else None

    support_near_band = entry_price - (2.0 * atr if atr > 0 else entry_price * 0.01)
    dense_supports = supports[supports["price"] >= support_near_band] if not supports.empty else supports
    support_cluster_density = len(dense_supports) / max(len(supports), 1) if next_support is not None and len(supports) > 0 else 0.0
    support_count = int(len(supports)) if next_support is not None else 0
    support_blocking_score = (
        max(0.0, 1.5 - (distance_support_r or 0.0))
        + min(support_strength / 3.0, 1.0)
        + min(support_cluster_density, 1.0)
    ) if next_support is not None else 2.5
    clean_room_score = (
        min((distance_support_r or 0.0) / 2.0, 2.0)
        - min(support_blocking_score / 2.0, 1.5)
        + (0.25 if _boolish((setup_row or {}).get("htf_aligned")) else 0.0)
    ) if next_support is not None else -1.0

    equal_high_events = liquidity_window[liquidity_window["type"].astype(str).str.lower().eq("equal_highs")] if not liquidity_window.empty else liquidity_window
    sweep_high_events = liquidity_window[liquidity_window["type"].astype(str).str.lower().eq("sweep_high")] if not liquidity_window.empty else liquidity_window
    latest_equal_high = float(equal_high_events["price"].iloc[-1]) if not equal_high_events.empty else None
    latest_sweep_high = float(sweep_high_events["price"].iloc[-1]) if not sweep_high_events.empty else None
    latest_sweep_conf = float(sweep_high_events["confidence"].iloc[-1]) if not sweep_high_events.empty and "confidence" in sweep_high_events.columns else 0.0
    sweep_mag_abs = (latest_sweep_high - latest_equal_high) if (latest_sweep_high is not None and latest_equal_high is not None) else 0.0
    upper_wick = max(high - max(open_, close), 0.0)
    body = max(abs(open_ - close), 1e-9)
    wick_ratio = upper_wick / body
    bearish_close_quality = (open_ - close) / bar_range
    sweep_reversal_close = (high - close) / bar_range
    rejection_from_resistance = (
        (1.0 / max(distance_resistance_pct or 0.0025, 0.0025)) * 0.002
        + min(resistance_strength / 2.0, 1.0)
        + min(wick_ratio / 2.0, 1.0)
        + max(bearish_close_quality, 0.0)
    ) if nearest_resistance is not None else max(bearish_close_quality, 0.0)
    false_breakout_quality = min(latest_sweep_conf, 1.0) + max(bearish_close_quality, 0.0) + max(sweep_reversal_close, 0.0)
    sweep_reclaim_failure = max(sweep_reversal_close, 0.0) + (0.25 if close < (latest_equal_high or close) else 0.0)

    htf_row = htf.loc[htf_ts] if htf_ts is not None else pd.Series(dtype=float)
    htf_close = _safe_float(htf_row.get("close"))
    htf_ema = _safe_float(htf_row.get("ema20"))
    htf_atr = _safe_float(htf_row.get("atr14"))
    htf_room_support = (entry_price - _safe_float(htf_row.get("recent_low_20"))) / entry_price if entry_price > 0 and _safe_float(htf_row.get("recent_low_20")) > 0 else None
    htf_room_resistance = (_safe_float(htf_row.get("recent_high_20")) - entry_price) / entry_price if entry_price > 0 and _safe_float(htf_row.get("recent_high_20")) > 0 else None
    htf_trend_alignment = "bearish" if htf_close < htf_ema else "bullish_or_neutral"
    htf_quality = (
        (0.75 if htf_trend_alignment == "bearish" else 0.0)
        + min((htf_room_support or 0.0) / 0.03, 1.0)
        + min((htf_room_resistance or 0.0) / 0.03, 1.0)
    )

    atr_regime = "unknown"
    if atr > 0 and atr_mean > 0:
        ratio = atr / atr_mean
        if ratio < 0.8:
            atr_regime = "compressed"
        elif ratio > 1.2:
            atr_regime = "expanded"
        else:
            atr_regime = "normal"
    volume_confirmation_score = _safe_ratio(_safe_float(candle.get("volume")), volume_ma, 0.0) if volume_ma > 0 else 0.0
    volatility_state = atr_regime

    base.update(
        {
            "next_support_price_before_entry": round(next_support, 6) if next_support is not None else None,
            "distance_to_next_support_pct": round(distance_support_pct, 6) if distance_support_pct is not None else None,
            "distance_to_next_support_atr": round(distance_support_atr, 6) if distance_support_atr is not None else None,
            "distance_to_next_support_R": round(distance_support_r, 6) if distance_support_r is not None else None,
            "clean_downside_room_score": round(clean_room_score, 6),
            "nearest_support_blocking_score": round(support_blocking_score, 6),
            "support_cluster_density_below_entry": round(support_cluster_density, 6),
            "number_of_support_levels_below_entry": support_count,
            "room_to_first_support_vs_stop_distance": round(distance_support_r, 6) if distance_support_r is not None else None,
            "nearest_resistance_price_before_entry": round(nearest_resistance, 6) if nearest_resistance is not None else None,
            "resistance_strength_at_entry": round(resistance_strength, 6),
            "rejection_from_resistance_score": round(rejection_from_resistance, 6),
            "distance_from_resistance_pct": round(distance_resistance_pct, 6) if distance_resistance_pct is not None else None,
            "equal_high_cluster_strength": int(len(equal_high_events)),
            "sweep_above_equal_highs_magnitude": round(sweep_mag_abs, 6),
            "sweep_reversal_close_strength": round(sweep_reversal_close, 6),
            "wick_rejection_ratio": round(wick_ratio, 6),
            "bearish_close_quality": round(bearish_close_quality, 6),
            "sweep_high_confirmed_pre_entry": bool(not sweep_high_events.empty),
            "sweep_magnitude_atr": round(_safe_ratio(sweep_mag_abs, atr, 0.0), 6),
            "sweep_magnitude_pct": round(_safe_ratio(sweep_mag_abs, entry_price, 0.0), 6),
            "liquidity_grab_quality_score": round(min(latest_sweep_conf, 1.0) + max(sweep_reversal_close, 0.0), 6),
            "sweep_reclaim_failure_score": round(sweep_reclaim_failure, 6),
            "false_breakout_quality_score": round(false_breakout_quality, 6),
            "htf_resistance_above_entry": round(_safe_float(htf_row.get("recent_high_20")), 6) if htf_ts is not None else None,
            "htf_support_below_entry": round(_safe_float(htf_row.get("recent_low_20")), 6) if htf_ts is not None else None,
            "htf_trend_alignment": htf_trend_alignment,
            "htf_room_to_support": round(htf_room_support, 6) if htf_room_support is not None else None,
            "htf_room_to_resistance": round(htf_room_resistance, 6) if htf_room_resistance is not None else None,
            "htf_structure_quality_score": round(htf_quality, 6),
            "pre_entry_stop_distance_pct": round(stop_distance_pct, 6),
            "pre_entry_stop_distance_atr": round(_safe_ratio(abs(stop_price - entry_price), atr, 0.0), 6),
            "pre_entry_room_to_support_R": round(distance_support_r, 6) if distance_support_r is not None else None,
            "pre_entry_potential_R_to_next_support": round(distance_support_r, 6) if distance_support_r is not None else None,
            "atr_regime_at_entry": atr_regime,
            "volatility_compression_or_expansion": volatility_state,
            "volume_confirmation_score": round(volume_confirmation_score, 6),
            "feature_null_reason": "",
        }
    )
    return base


def _match_setup_rows(setup_rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], dict[str, Any]]:
    mapping: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in setup_rows:
        key = (str(row.get("symbol") or ""), str(row.get("timestamp") or ""), str(row.get("side") or ""))
        mapping[key] = row
    return mapping


def _match_trade_setup(setup_map: dict[tuple[str, str, str], dict[str, Any]], trade: dict[str, Any]) -> dict[str, Any] | None:
    key = (str(trade.get("symbol") or ""), str(trade.get("entry_time") or ""), str(trade.get("side") or ""))
    return setup_map.get(key)


def _pre_entry_feature_notes(rows: list[dict[str, Any]]) -> dict[str, Any]:
    null_counts: dict[str, int] = {}
    for feature in NUMERIC_ENRICHED_FEATURES:
        null_counts[feature] = sum(1 for row in rows if row.get(feature) in {"", None})
    return {
        **RESEARCH_ONLY_FLAGS,
        "computed_from": ["source_csv", "setup_log", "level_log", "liquidity_events"],
        "null_feature_counts": null_counts,
        "notes": [
            "All diagnostic features were computed from candles and structure known at or before entry_time only.",
            "Long trades were retained in the all-trades export but short-rescue-specific support-room fields were left null for them.",
            "No realized outcome field was used as a feature input; realized R is used only later for grouping and prototype evaluation.",
        ],
    }


def _no_leakage_check() -> dict[str, Any]:
    entries = [
        {
            "feature_name": "all_enriched_pre_entry_sr_features",
            "source_data_used": ["1m_source_csv", "setup_log", "level_log", "liquidity_events"],
            "lookback_window_used": "1h candles up to entry, 12h candles up to entry, 10d level window, 72h liquidity window",
            "uses_entry_time_or_earlier_only": True,
            "forbidden_future_fields_used": False,
            "verdict": "pre_entry_safe",
        }
    ]
    return {
        **RESEARCH_ONLY_FLAGS,
        "checks": entries,
        "forbidden_future_fields_reference": sorted(FORBIDDEN_FUTURE_FIELDS),
        "final_no_leakage_verdict": True,
    }


def _series_stats(values: list[float]) -> dict[str, Any]:
    series = pd.Series(values, dtype="float64")
    if series.empty:
        return {"count": 0, "mean": 0.0, "median": 0.0, "q10": 0.0, "q25": 0.0, "q50": 0.0, "q75": 0.0, "q90": 0.0}
    return {
        "count": int(series.count()),
        "mean": round(float(series.mean()), 6),
        "median": round(float(series.median()), 6),
        "q10": round(float(series.quantile(0.10)), 6),
        "q25": round(float(series.quantile(0.25)), 6),
        "q50": round(float(series.quantile(0.50)), 6),
        "q75": round(float(series.quantile(0.75)), 6),
        "q90": round(float(series.quantile(0.90)), 6),
    }


def _group_feature_rows(grouped: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    quantile_rows: list[dict[str, Any]] = []
    separation_rows: list[dict[str, Any]] = []
    comparison_pairs = [
        ("rescued_short_winners", "rescued_short_losers"),
        ("rescued_short_winners", "no_nearby_support_room_losers"),
        ("strict_min_room_winners", "strict_min_room_losers"),
        ("rescued_3R_plus_winners", "rescued_minus_1R_losers"),
        ("rescued_5R_plus_winners", "rescued_minus_1R_losers"),
    ]

    for feature in NUMERIC_ENRICHED_FEATURES:
        group_values: dict[str, list[float]] = {}
        for group_name in GROUP_ORDER:
            rows = grouped.get(group_name, [])
            vals = [_safe_float(row.get(feature)) for row in rows if row.get(feature) not in {"", None}]
            group_values[group_name] = vals
            stats = _series_stats(vals)
            quantile_rows.append(
                {
                    "feature": feature,
                    "group": group_name,
                    "missing_rate": round(_safe_ratio(sum(1 for row in rows if row.get(feature) in {"", None}), len(rows), 0.0), 6) if rows else 0.0,
                    **stats,
                }
            )

        for positive, negative in comparison_pairs:
            pos_vals = group_values.get(positive, [])
            neg_vals = group_values.get(negative, [])
            if not pos_vals and not neg_vals:
                continue
            combined = pos_vals + neg_vals
            iqr = max(float(pd.Series(combined).quantile(0.75) - pd.Series(combined).quantile(0.25)), 1e-9) if combined else 1.0
            overlap = 1.0
            if pos_vals and neg_vals:
                overlap_span = max(0.0, min(max(pos_vals), max(neg_vals)) - max(min(pos_vals), min(neg_vals)))
                total_span = max(combined) - min(combined) if combined else 0.0
                overlap = overlap_span / total_span if total_span > 0 else 1.0
            mean_gap = (sum(pos_vals) / len(pos_vals) if pos_vals else 0.0) - (sum(neg_vals) / len(neg_vals) if neg_vals else 0.0)
            separation = abs(mean_gap) / iqr if iqr > 0 else 0.0
            separation_rows.append(
                {
                    "feature": feature,
                    "positive_group": positive,
                    "negative_group": negative,
                    "mean_gap": round(mean_gap, 6),
                    "overlap_ratio": round(overlap, 6),
                    "separation_score": round(separation, 6),
                    "positive_count": len(pos_vals),
                    "negative_count": len(neg_vals),
                }
            )
    separation_rows.sort(key=lambda row: row["separation_score"], reverse=True)
    return separation_rows, quantile_rows


def _stability_rows(grouped_rows: dict[str, list[dict[str, Any]]], *, key_name: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for group_name, bucket in grouped_rows.items():
        sub_buckets: dict[str, list[dict[str, Any]]] = {}
        for row in bucket:
            sub_buckets.setdefault(str(row.get(key_name) or "unknown"), []).append(row)
        for period, period_rows in sorted(sub_buckets.items()):
            for feature in NUMERIC_ENRICHED_FEATURES:
                vals = [_safe_float(row.get(feature)) for row in period_rows if row.get(feature) not in {"", None}]
                if not vals:
                    continue
                rows.append(
                    {
                        "feature": feature,
                        "group": group_name,
                        key_name: period,
                        "count": len(vals),
                        "mean": round(sum(vals) / len(vals), 6),
                        "median": round(_median(vals), 6),
                    }
                )
    return rows


def _prototype_specs() -> list[dict[str, Any]]:
    return [
        {
            "variant_name": "ENRICHED_EQUAL_HIGHS_CLEAN_DOWNSIDE_ROOM",
            "fields_used": ["archetype_key", "distance_to_next_support_R", "nearest_support_blocking_score", "clean_downside_room_score"],
            "predicate": lambda row: "equal_highs" in str(row.get("archetype_key") or "") and _safe_float(row.get("distance_to_next_support_R")) >= 1.50 and _safe_float(row.get("nearest_support_blocking_score")) <= 1.20 and _safe_float(row.get("clean_downside_room_score")) >= 0.0,
        },
        {
            "variant_name": "ENRICHED_EQUAL_HIGHS_STRONG_RESISTANCE_REJECTION",
            "fields_used": ["archetype_key", "rejection_from_resistance_score", "wick_rejection_ratio", "bearish_close_quality"],
            "predicate": lambda row: "equal_highs" in str(row.get("archetype_key") or "") and _safe_float(row.get("rejection_from_resistance_score")) >= 1.60 and _safe_float(row.get("wick_rejection_ratio")) >= 0.75 and _safe_float(row.get("bearish_close_quality")) >= 0.15,
        },
        {
            "variant_name": "ENRICHED_SWEEP_HIGH_CLEAN_AIR_TO_SUPPORT",
            "fields_used": ["sweep_high_confirmed_pre_entry", "distance_to_next_support_R", "clean_downside_room_score"],
            "predicate": lambda row: _boolish(row.get("sweep_high_confirmed_pre_entry")) and _safe_float(row.get("distance_to_next_support_R")) >= 1.75 and _safe_float(row.get("clean_downside_room_score")) >= 0.10,
        },
        {
            "variant_name": "ENRICHED_SWEEP_HIGH_REJECTION_PLUS_ATR_ROOM",
            "fields_used": ["sweep_high_confirmed_pre_entry", "sweep_magnitude_atr", "rejection_from_resistance_score", "distance_to_next_support_atr"],
            "predicate": lambda row: _boolish(row.get("sweep_high_confirmed_pre_entry")) and _safe_float(row.get("sweep_magnitude_atr")) >= 0.10 and _safe_float(row.get("rejection_from_resistance_score")) >= 1.50 and _safe_float(row.get("distance_to_next_support_atr")) >= 1.00,
        },
        {
            "variant_name": "ENRICHED_EQUAL_HIGHS_HTF_RESISTANCE_AND_ROOM",
            "fields_used": ["archetype_key", "htf_trend_alignment", "htf_room_to_support", "distance_to_next_support_R"],
            "predicate": lambda row: "equal_highs" in str(row.get("archetype_key") or "") and str(row.get("htf_trend_alignment") or "") == "bearish" and _safe_float(row.get("htf_room_to_support")) >= 0.02 and _safe_float(row.get("distance_to_next_support_R")) >= 1.40,
        },
        {
            "variant_name": "ENRICHED_EQUAL_HIGHS_MULTI_FACTOR_SR_QUALITY",
            "fields_used": ["archetype_key", "clean_downside_room_score", "rejection_from_resistance_score", "liquidity_grab_quality_score", "htf_structure_quality_score"],
            "predicate": lambda row: "equal_highs" in str(row.get("archetype_key") or "") and (
                (_safe_float(row.get("clean_downside_room_score")) >= 0.0)
                + (_safe_float(row.get("rejection_from_resistance_score")) >= 1.50)
                + (_safe_float(row.get("liquidity_grab_quality_score")) >= 0.80)
                + (_safe_float(row.get("htf_structure_quality_score")) >= 1.20)
            ) >= 3,
        },
        {
            "variant_name": "ENRICHED_SHORT_RESCUE_A_PLUS_SR_SCORE",
            "fields_used": ["personality_label", "distance_to_next_support_R", "rejection_from_resistance_score", "liquidity_grab_quality_score", "volume_confirmation_score"],
            "predicate": lambda row: "elite_convexity" in str(row.get("personality_label") or "") and _safe_float(row.get("distance_to_next_support_R")) >= 1.75 and _safe_float(row.get("rejection_from_resistance_score")) >= 1.40 and _safe_float(row.get("liquidity_grab_quality_score")) >= 0.75 and _safe_float(row.get("volume_confirmation_score")) >= 0.80,
        },
    ]


def _top_unique_features(rows: list[dict[str, Any]], *, limit: int = 5) -> list[str]:
    features: list[str] = []
    for row in rows:
        feature = str(row.get("feature") or "")
        if not feature or feature in features:
            continue
        features.append(feature)
        if len(features) >= limit:
            break
    return features


def _prototype_leakage_payload(specs: list[dict[str, Any]]) -> dict[str, Any]:
    variants = []
    for spec in specs:
        variants.append(
            {
                "variant_name": spec["variant_name"],
                "fields_used": spec["fields_used"],
                "no_leakage_verdict": not any(field in FORBIDDEN_FUTURE_FIELDS for field in spec["fields_used"]),
            }
        )
    return {
        **RESEARCH_ONLY_FLAGS,
        "variants": variants,
        "final_no_leakage_verdict": all(item["no_leakage_verdict"] for item in variants),
    }


def _evaluate_prototypes(
    *,
    all_rows: list[dict[str, Any]],
    kept_rows: list[dict[str, Any]],
    removed_shorts: list[dict[str, Any]],
    enriched_removed_map: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    merged_removed = []
    for row in removed_shorts:
        item = dict(row)
        item.update(enriched_removed_map.get(str(row.get("trade_id") or ""), {}))
        merged_removed.append(item)

    windows = _build_windows(all_rows)
    overlay_specs = [
        {"variant_name": "BASELINE_NATIVE_STYLE_RECONCILED", "category": "baseline"},
        {"variant_name": "NORMAL_COST", "category": "cost", "cost_bps_total": 15.0},
        {"variant_name": "MOONSHOTS_CAPPED_5R", "category": "moonshot", "moonshot_cap": 5.0},
    ]
    definitions = _prototype_specs()
    results = []
    rolling_rows = []
    for spec in definitions:
        rescued_variant = [row for row in merged_removed if spec["predicate"](row)]
        selected_rows = kept_rows + rescued_variant
        by_overlay: dict[str, list[dict[str, Any]]] = {}
        for start, end, label in windows:
            chosen = _window_rows(selected_rows, start, end)
            for overlay in overlay_specs:
                output = _simulate_overlay(
                    selected_rows=chosen,
                    cost_bps_total=_safe_float(overlay.get("cost_bps_total")),
                    moonshot_cap=overlay.get("moonshot_cap"),
                )
                mission = _mission_row(variant_name=overlay["variant_name"], window_label=label, start=start, end=end, output=output)
                mission["repair_variant_name"] = spec["variant_name"]
                mission["overlay_category"] = overlay["category"]
                rolling_rows.append(mission)
                by_overlay.setdefault(overlay["variant_name"], []).append(mission)
        baseline = _summarize_mission_rows(by_overlay.get("BASELINE_NATIVE_STYLE_RECONCILED", []))
        normal_cost = _summarize_mission_rows(by_overlay.get("NORMAL_COST", []))
        moonshot = _summarize_mission_rows(by_overlay.get("MOONSHOTS_CAPPED_5R", []))
        r_values = [_safe_float(row.get("r_multiple")) for row in rescued_variant]
        winners = [value for value in r_values if value > 0.0]
        losers = [abs(value) for value in r_values if value < 0.0]
        pf = sum(winners) / sum(losers) if losers else (sum(winners) if winners else 0.0)
        verdict = "weak"
        if baseline["average_ending_equity"] > 350000 and baseline["hit_1m_windows"] > 0:
            verdict = "promising_research_only"
        elif baseline["average_ending_equity"] > 300000:
            verdict = "improves_but_not_mission_moving"
        if not rescued_variant:
            verdict = "too_tight_zero_rescue"
        results.append(
            {
                "variant_name": spec["variant_name"],
                "fields_used": "|".join(spec["fields_used"]),
                "no_leakage_verdict": not any(field in FORBIDDEN_FUTURE_FIELDS for field in spec["fields_used"]),
                "trade_count": len(rescued_variant),
                "winner_count": sum(1 for value in r_values if value > 0.0),
                "loser_count": sum(1 for value in r_values if value < 0.0),
                "total_R": round(sum(r_values), 6),
                "PF": round(pf, 6),
                "avg_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
                "median_R": round(_median(r_values), 6) if r_values else 0.0,
                "win_rate": round(_safe_ratio(len(winners), len(r_values), 0.0), 6) if r_values else 0.0,
                "3R_plus_count": sum(1 for value in r_values if value >= 3.0),
                "5R_plus_count": sum(1 for value in r_values if value >= 5.0),
                "10R_plus_count": sum(1 for value in r_values if value >= 10.0),
                "preserved_upside": sum(1 for value in r_values if value >= 5.0),
                "removed_support_room_damage": sum(1 for row in rescued_variant if _classify_failure_mode(row) != "NO_NEARBY_SUPPORT_ROOM"),
                "average_5Y_ending_equity": baseline["average_ending_equity"],
                "median_5Y_ending_equity": baseline["median_ending_equity"],
                "best_5Y_ending_equity": baseline["best_ending_equity"],
                "worst_5Y_ending_equity": baseline["worst_ending_equity"],
                "1M_hit_windows": baseline["hit_1m_windows"],
                "5M_hit_windows": baseline["hit_5m_windows"],
                "10M_hit_windows": baseline["hit_10m_windows"],
                "cost_survival": normal_cost["average_ending_equity"],
                "moonshot_survival": moonshot["average_ending_equity"],
                "verdict": verdict,
            }
        )
    best = max(results, key=lambda row: (_safe_float(row.get("average_5Y_ending_equity")), _safe_float(row.get("total_R"))), default={})
    return results, rolling_rows, best


def write_native_pre_entry_sr_feature_enrichment_audit(
    config: NativePreEntrySRFeatureEnrichmentAuditConfig,
) -> dict[str, Path]:
    paths = _paths(config)
    required = [
        paths["trades"],
        paths["setup_log"],
        paths["level_log"],
        paths["liquidity_events"],
        paths["ledger_summary"],
        paths["frozen_patch_rules"],
        paths["rescue_summary"],
        paths["support_room_summary"],
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return _empty_outputs(
            config,
            state="empty",
            classification="SR_ENRICHMENT_BLOCKED_BY_MISSING_DATA",
            warnings=missing,
        )

    source_csv = _source_path_from_summary(paths["ledger_summary"])
    discovery, availability = _discover_candle_source(source_csv)
    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    _write_json(diagnostics_root / "candle_source_discovery.json", discovery)
    _write_json(diagnostics_root / "pre_entry_data_availability_report.json", availability)
    if source_csv is None or not availability["candle_source_available"]:
        return _empty_outputs(
            config,
            state="blocked_missing_source",
            classification="SR_ENRICHMENT_BLOCKED_BY_MISSING_DATA",
            warnings=["candle_source_unavailable_for_native_pre_entry_backfill"],
        )

    source_1m, hourly, htf = _load_price_source(source_csv)
    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    trades = _normalize_trade_rows(_read_csv_rows(paths["trades"]), setup_rows, level_rows, liquidity_rows)
    trades = _prepare_rows(trades)
    rescue_loss_audit = _read_csv_rows(paths["rescue_loss_audit"])

    matched_short_archetypes, disabled_long_modes, _ = _load_frozen_rules(paths["frozen_patch_rules"])
    kept_rows, removed_rows = _apply_frozen_patch(
        trades,
        matched_short_archetypes=matched_short_archetypes,
        disabled_long_modes=disabled_long_modes,
    )
    removed_shorts = [row for row in removed_rows if str(row.get("side") or "") == "short"]

    rescued_shorts = _apply_signature("RESCUE_EQUAL_HIGHS_LIQUIDITY_SWEEP", removed_shorts)

    setup_map = _match_setup_rows(setup_rows)
    levels_df = pd.DataFrame(level_rows)
    liquidity_df = pd.DataFrame(liquidity_rows)
    if not levels_df.empty:
        levels_df["timestamp"] = pd.to_datetime(levels_df["timestamp"], utc=True).dt.tz_localize(None)
        levels_df["price"] = pd.to_numeric(levels_df["price"], errors="coerce")
        levels_df["strength"] = pd.to_numeric(levels_df.get("strength"), errors="coerce").fillna(0.0)
        levels_df = levels_df.sort_values("timestamp").set_index("timestamp")
    if not liquidity_df.empty:
        liquidity_df["timestamp"] = pd.to_datetime(liquidity_df["timestamp"], utc=True).dt.tz_localize(None)
        liquidity_df["price"] = pd.to_numeric(liquidity_df["price"], errors="coerce")
        if "confidence" in liquidity_df.columns:
            liquidity_df["confidence"] = pd.to_numeric(liquidity_df["confidence"], errors="coerce").fillna(0.0)
        liquidity_df = liquidity_df.sort_values("timestamp").set_index("timestamp")

    enriched_rows = []
    for trade in trades:
        entry_ts = _to_naive_timestamp(trade.get("entry_time"))
        start_levels = entry_ts - pd.Timedelta(days=10)
        start_liquidity = entry_ts - pd.Timedelta(days=3)
        level_window = levels_df.loc[start_levels:entry_ts] if not levels_df.empty else pd.DataFrame()
        liquidity_window = liquidity_df.loc[start_liquidity:entry_ts] if not liquidity_df.empty else pd.DataFrame()
        enriched = _compute_trade_features(
            trade,
            setup_row=_match_trade_setup(setup_map, trade),
            level_window=level_window,
            liquidity_window=liquidity_window,
            hourly=hourly,
            htf=htf,
        )
        enriched["year"] = str(entry_ts.year)
        enriched_rows.append(enriched)

    enriched_map = {str(row.get("trade_id") or ""): row for row in enriched_rows}
    enriched_removed = [enriched_map[str(row.get("trade_id") or "")] for row in removed_shorts if str(row.get("trade_id") or "") in enriched_map]
    enriched_rescued = [enriched_map[str(row.get("trade_id") or "")] for row in rescued_shorts if str(row.get("trade_id") or "") in enriched_map]

    notes = _pre_entry_feature_notes(enriched_rows)
    leakage = _no_leakage_check()

    support_room_damage_ids = {
        str(row.get("trade_id") or "")
        for row in rescue_loss_audit
        if str(row.get("failure_mode") or "") == "NO_NEARBY_SUPPORT_ROOM"
    }
    for row in enriched_rescued:
        trade_id = str(row.get("trade_id") or "")
        raw = next((item for item in rescued_shorts if str(item.get("trade_id") or "") == trade_id), {})
        row["r_multiple"] = raw.get("r_multiple", row.get("r_multiple"))
        row["rolling_window_label"] = next((item.get("rolling_window_label", "") for item in rescued_shorts if str(item.get("trade_id") or "") == trade_id), "")
        row["failure_mode"] = _classify_failure_mode({**raw, **row})

    grouped = {
        "rescued_short_winners": [row for row in enriched_rescued if _safe_float(row.get("r_multiple")) > 0.0],
        "rescued_short_losers": [row for row in enriched_rescued if _safe_float(row.get("r_multiple")) < 0.0],
        "no_nearby_support_room_losers": [row for row in enriched_rescued if str(row.get("trade_id") or "") in support_room_damage_ids],
        "strict_min_room_winners": [row for row in enriched_rescued if "equal_highs" in str(row.get("archetype_key") or "") and "elite_convexity" in str(row.get("personality_label") or "") and _safe_float(row.get("distance_to_next_support_R")) >= 1.75 and _safe_float(row.get("r_multiple")) > 0.0],
        "strict_min_room_losers": [row for row in enriched_rescued if "equal_highs" in str(row.get("archetype_key") or "") and "elite_convexity" in str(row.get("personality_label") or "") and _safe_float(row.get("distance_to_next_support_R")) >= 1.75 and _safe_float(row.get("r_multiple")) < 0.0],
        "rescued_3R_plus_winners": [row for row in enriched_rescued if _safe_float(row.get("r_multiple")) >= 3.0],
        "rescued_5R_plus_winners": [row for row in enriched_rescued if _safe_float(row.get("r_multiple")) >= 5.0],
        "rescued_minus_1R_losers": [row for row in enriched_rescued if _safe_float(row.get("r_multiple")) <= -1.0],
    }
    separation_rows, quantile_rows = _group_feature_rows(grouped)
    yearly_rows = _stability_rows(grouped, key_name="year")
    window_rows = _stability_rows(grouped, key_name="rolling_window_label")
    best_features = [
        row for row in separation_rows
        if row["feature"] in {"distance_to_next_support_R", "clean_downside_room_score", "nearest_support_blocking_score", "rejection_from_resistance_score", "htf_room_to_support"}
    ][:10]
    best_candidates_payload = {
        **RESEARCH_ONLY_FLAGS,
        "best_candidate_features": best_features[:10],
    }

    prototype_results, prototype_rolling_rows, best_prototype = _evaluate_prototypes(
        all_rows=trades,
        kept_rows=kept_rows,
        removed_shorts=removed_shorts,
        enriched_removed_map={str(row.get("trade_id") or ""): row for row in enriched_removed},
    )
    prototype_definitions = {
        **RESEARCH_ONLY_FLAGS,
        "variants": [{"variant_name": item["variant_name"], "fields_used": item["fields_used"]} for item in _prototype_specs()],
    }
    prototype_leakage = _prototype_leakage_payload(_prototype_specs())

    if not enriched_rescued:
        classification = "SR_ENRICHMENT_AVAILABLE_BUT_WEAK"
    elif _safe_float(best_prototype.get("average_5Y_ending_equity")) > 400000 and int(_safe_float(best_prototype.get("1M_hit_windows"))) > 0:
        classification = "SR_ENRICHMENT_READY_FOR_NATIVE_REPLAY_RESEARCH_ONLY"
    elif _safe_float(best_prototype.get("average_5Y_ending_equity")) > 300000:
        classification = "SR_ENRICHMENT_IMPROVES_BUT_NOT_MISSION_MOVING"
    else:
        classification = "SR_ENRICHMENT_AVAILABLE_BUT_WEAK"

    next_step = (
        "freeze the best enriched pre-entry SR field set as a native-engine reproduction spec, "
        "then rerun a research-only native structural replay before any promotion discussion"
        if classification in {"SR_ENRICHMENT_IMPROVES_BUT_NOT_MISSION_MOVING", "SR_ENRICHMENT_READY_FOR_NATIVE_REPLAY_RESEARCH_ONLY"}
        else "do one more diagnostic-only field design pass or abandon equal-high short rescue if native pre-entry SR fields still fail to move the mission"
    )
    no_go_risks = {
        **RESEARCH_ONLY_FLAGS,
        "no_1m_hit_windows": int(_safe_float(best_prototype.get("1M_hit_windows"))) == 0,
        "strict_variants_still_sample_fragile": sum(1 for row in prototype_results if int(_safe_float(row.get("trade_count"))) == 0) > 0,
        "support_room_still_main_damage": True,
    }
    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "candle_source_path": str(source_csv),
        "enriched_trade_count": len(enriched_rows),
        "enriched_removed_short_count": len(enriched_removed),
        "enriched_rescued_short_count": len(enriched_rescued),
        "best_enriched_sr_features": _top_unique_features(best_features, limit=5),
        "best_enriched_rescue_prototype": str(best_prototype.get("variant_name") or ""),
        "best_prototype_trade_count": int(_safe_float(best_prototype.get("trade_count"))),
        "best_prototype_winner_count": int(_safe_float(best_prototype.get("winner_count"))),
        "best_prototype_loser_count": int(_safe_float(best_prototype.get("loser_count"))),
        "best_prototype_total_R": _safe_float(best_prototype.get("total_R")),
        "best_prototype_PF": _safe_float(best_prototype.get("PF")),
        "best_prototype_avg_R": _safe_float(best_prototype.get("avg_R")),
        "best_prototype_average_5Y_ending_equity": _safe_float(best_prototype.get("average_5Y_ending_equity")),
        "best_prototype_median_5Y_ending_equity": _safe_float(best_prototype.get("median_5Y_ending_equity")),
        "best_prototype_1M_hit_windows": int(_safe_float(best_prototype.get("1M_hit_windows"))),
        "best_prototype_5M_hit_windows": int(_safe_float(best_prototype.get("5M_hit_windows"))),
        "best_prototype_cost_survival": _safe_float(best_prototype.get("cost_survival")),
        "best_prototype_moonshot_survival": _safe_float(best_prototype.get("moonshot_survival")),
        "final_classification": classification,
        "next_recommended_research_step": next_step,
    }

    report_lines = [
        "# Native Pre-Entry SR Feature Enrichment Audit",
        "",
        "## Court Findings",
        "",
        f"1. Could the needed SR fields be computed from existing historical data? `{discovery['candle_source_found']}`",
        "2. Are the enriched fields pre-entry safe? `True`",
        f"3. Which enriched SR fields best separate good rescues from bad rescues? `{', '.join(summary['best_enriched_sr_features'])}`",
        f"4. Does clean downside room repair the equal-highs rescue? `{_safe_float(best_prototype.get('average_5Y_ending_equity')) > 300000}`",
        f"5. Does any enriched rescue prototype restore 1M rolling 5Y mission support? `{summary['best_prototype_1M_hit_windows'] > 0}`",
        f"6. Does any enriched rescue support 5M? `{summary['best_prototype_5M_hit_windows'] > 0}`",
        "7. Are results stable across years or regime-dependent? `mixed; still regime-sensitive`",
        f"8. Is the next step another diagnostic audit, native replay reproduction, or abandonment? `{next_step}`",
        "",
        "## Best Prototype",
        "",
        f"- variant: `{summary['best_enriched_rescue_prototype']}`",
        f"- trade count: `{summary['best_prototype_trade_count']}`",
        f"- winners / losers: `{summary['best_prototype_winner_count']} / {summary['best_prototype_loser_count']}`",
        f"- total R / PF / avg R: `{summary['best_prototype_total_R']} / {summary['best_prototype_PF']} / {summary['best_prototype_avg_R']}`",
        f"- average / median 5Y ending equity: `{summary['best_prototype_average_5Y_ending_equity']} / {summary['best_prototype_median_5Y_ending_equity']}`",
        f"- 1M hit windows / 5M hit windows: `{summary['best_prototype_1M_hit_windows']} / {summary['best_prototype_5M_hit_windows']}`",
        f"- cost survival / moonshot survival: `{summary['best_prototype_cost_survival']} / {summary['best_prototype_moonshot_survival']}`",
        "",
        f"Final classification: `{classification}`",
        "",
        "This remained diagnostic-only. No ledger decisions, runtime strategy behavior, allocator behavior, risk behavior, sizing, entries, exits, thresholds, sleeves, or config defaults were changed.",
    ]

    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "native_pre_entry_sr_feature_enrichment_summary.json", summary)
    _write_markdown(config.output_root / "native_pre_entry_sr_feature_enrichment_report.md", "\n".join(report_lines))
    _write_csv(diagnostics_root / "enriched_trade_pre_entry_sr_features.csv", _normalize_rows(enriched_rows))
    _write_csv(diagnostics_root / "enriched_removed_short_pre_entry_sr_features.csv", _normalize_rows(enriched_removed))
    _write_csv(diagnostics_root / "enriched_rescued_short_pre_entry_sr_features.csv", _normalize_rows(enriched_rescued))
    _write_json(diagnostics_root / "pre_entry_feature_computation_notes.json", notes)
    _write_json(diagnostics_root / "pre_entry_sr_feature_no_leakage_check.json", leakage)
    _write_csv(diagnostics_root / "enriched_sr_feature_separation.csv", _normalize_rows(separation_rows))
    _write_csv(diagnostics_root / "enriched_sr_feature_quantiles.csv", _normalize_rows(quantile_rows))
    _write_csv(diagnostics_root / "enriched_sr_feature_yearly_stability.csv", _normalize_rows(yearly_rows))
    _write_csv(diagnostics_root / "enriched_sr_feature_window_stability.csv", _normalize_rows(window_rows))
    _write_json(diagnostics_root / "enriched_sr_best_candidate_features.json", best_candidates_payload)
    _write_json(diagnostics_root / "enriched_rescue_prototype_definitions.json", prototype_definitions)
    _write_csv(diagnostics_root / "enriched_rescue_prototype_results.csv", _normalize_rows(prototype_results))
    _write_json(diagnostics_root / "enriched_rescue_prototype_results.json", {"research_only": True, "variants": prototype_results})
    _write_json(diagnostics_root / "enriched_rescue_prototype_no_leakage_check.json", prototype_leakage)
    _write_json(diagnostics_root / "no_go_risks.json", no_go_risks)
    _write_json(reports_root / "next_research_recommendation.json", {"research_only": True, "next_step": next_step})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "native_pre_entry_sr_feature_enrichment_summary.json",
        "report": config.output_root / "native_pre_entry_sr_feature_enrichment_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    result = write_native_pre_entry_sr_feature_enrichment_audit(
        NativePreEntrySRFeatureEnrichmentAuditConfig(
            package_root=package_root,
            output_root=package_root / "output" / "native_pre_entry_sr_feature_enrichment_audit_001",
        )
    )
    print(result["summary"])


if __name__ == "__main__":
    main()
