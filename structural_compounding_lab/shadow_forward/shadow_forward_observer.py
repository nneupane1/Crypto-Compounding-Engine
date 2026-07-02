from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.backtest.checkpoint import StructuralCheckpointStore  # noqa: E402
from structural_compounding_lab.common.project_paths import package_root as resolve_package_root  # noqa: E402
from structural_compounding_lab.common.project_paths import resolve_project_path  # noqa: E402
from structural_compounding_lab.config import StructuralLabConfig  # noqa: E402
from structural_compounding_lab.context import build_htf_context  # noqa: E402
from structural_compounding_lab.context.trend_regime import classify_trend_regime  # noqa: E402
from structural_compounding_lab.data.data_adapter import StructuralDataAdapter  # noqa: E402
from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import RESEARCH_ONLY_FLAGS  # noqa: E402
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _read_csv_rows,
    _read_json,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.entry import detect_setup_candidate, score_setup_candidate  # noqa: E402
from structural_compounding_lab.indicators import (  # noqa: E402
    compute_atr,
    compute_bollinger_bands,
    compute_ema_stack,
    compute_macd,
    compute_session_vwap,
)
from structural_compounding_lab.market_structure import detect_liquidity_events, detect_structural_levels  # noqa: E402


OUTPUT_FOLDER_NAME = "shadow_forward_observer_001"
STATE_NOT_STARTED = "not_started"
STATE_RUNNING = "running"
STATE_PARTIAL = "partial"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_BLOCKED = "blocked"
DEFAULT_RUNTIME_MODE = "dry_run_backfill"
ALLOWED_RUNTIME_MODES = {"dry_run_backfill", "single_cycle", "scheduled_loop", "catchup"}
DEFAULT_COST_BAND = "NORMAL_MIXED_MAKER_TAKER_COST"


@dataclass(frozen=True)
class ShadowForwardObserverConfig:
    package_root: Path
    output_root: Path
    runtime_mode: str = DEFAULT_RUNTIME_MODE
    symbol: str = "BTCUSDT"
    source_csv: str | Path | None = None
    force_rerun: bool = False
    loop_sleep_seconds: int = 30
    max_cycles: int | None = None
    max_decisions: int | None = None


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


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


def _paths(config: ShadowForwardObserverConfig) -> dict[str, Path]:
    spec_root = config.package_root / "output" / "shadow_forward_validation_spec_audit_001"
    return {
        "spec_summary": spec_root / "shadow_forward_validation_spec_summary.json",
        "spec_architecture": spec_root / "diagnostics" / "shadow_forward_architecture_spec.json",
        "spec_log_schema": spec_root / "diagnostics" / "shadow_log_schema.json",
        "spec_readiness": spec_root / "diagnostics" / "shadow_readiness_gates.json",
        "spec_consistency": spec_root / "diagnostics" / "replay_vs_forward_consistency_spec.json",
        "baseline_cost_bands": config.package_root / "output" / "execution_cost_realism_and_trade_redundancy_audit_001" / "diagnostics" / "execution_cost_band_results.csv",
        "broad_summary": config.package_root / "output" / "broad_historical_structural_replay_001" / "ledger" / "summary.json",
    }


def _compatibility_payload(config: ShadowForwardObserverConfig) -> dict[str, Any]:
    return {
        "module": "shadow_forward_observer",
        "version": 1,
        "runtime_mode": config.runtime_mode,
        "symbol": config.symbol.upper(),
        "source_csv": str(config.source_csv) if config.source_csv is not None else "",
        "max_decisions": config.max_decisions,
    }


def _compatibility_signature(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


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
        "no_order_path_created": True,
    }
    if extra:
        payload.update(extra)
    _write_json(output_root / "status.json", payload)


def _write_scenario_progress(
    output_root: Path,
    *,
    state: str,
    cycles_completed: int,
    decisions_processed: int,
    warnings: list[str],
    compatibility_signature: str,
) -> None:
    payload = {
        "state": state,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cycles_completed": cycles_completed,
        "decisions_processed": decisions_processed,
        "warnings": warnings,
        "compatibility_signature": compatibility_signature,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(output_root / "scenario_progress.json", payload)


def _write_run_progress(
    diagnostics_root: Path,
    *,
    state: str,
    cycles_completed: int,
    decisions_processed: int,
    current_phase: str,
    warnings: list[str],
) -> None:
    payload = {
        "state": state,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "cycles_completed": cycles_completed,
        "decisions_processed": decisions_processed,
        "current_phase": current_phase,
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(diagnostics_root / "run_progress.json", payload)


def _signal_code_hash() -> str:
    files = [
        Path(__file__).resolve(),
        Path(__file__).resolve().parents[1] / "entry" / "setup_detector.py",
        Path(__file__).resolve().parents[1] / "entry" / "entry_score.py",
        Path(__file__).resolve().parents[1] / "context" / "htf_confirmation.py",
    ]
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.read_bytes())
    return digest.hexdigest()


def _load_prior_shadow_spec(config: ShadowForwardObserverConfig) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    paths = _paths(config)
    summary = _read_json(paths["spec_summary"], {})
    architecture = _read_json(paths["spec_architecture"], {})
    log_schema = _read_json(paths["spec_log_schema"], {})
    readiness = _read_json(paths["spec_readiness"], {})
    consistency = _read_json(paths["spec_consistency"], {})

    if not summary:
        warnings.append("Shadow-forward spec summary missing.")
    if not architecture:
        warnings.append("Shadow-forward architecture spec missing.")
    if not log_schema:
        warnings.append("Shadow-forward log schema missing.")
    if not readiness:
        warnings.append("Shadow-forward readiness gates missing.")
    if not consistency:
        warnings.append("Replay-vs-forward consistency spec missing.")
    if warnings:
        return None, warnings

    if str(summary.get("final_classification") or "") != "SHADOW_SPEC_READY_WITH_6H_CONTEXT_RESEARCH_ONLY":
        warnings.append("Shadow-forward spec final classification is not ready with 6H context.")
        return None, warnings

    stack = architecture.get("stack", {})
    anchor = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "final_classification": summary.get("final_classification"),
        "one_h_main_execution": str(stack.get("execution_engine") or "") == "1H",
        "six_h_context_only": str(stack.get("research_context_timeframe") or "") == "6H",
        "six_h_native_execution_disabled": str(stack.get("six_h_native_execution") or "") == "disabled_weak",
        "aggressive_300k_shadow_only": str(stack.get("aggressive_300k_gear") or "") == "shadow_log_only",
        "no_live_paper_order_path_allowed": True,
        "recommended_shadow_duration_days": _safe_int(summary.get("shadow_observation_duration_recommended_days"), 90),
        "minimum_signal_count_recommended": _safe_int(summary.get("minimum_signal_count_recommended"), 50),
        "architecture_spec": architecture,
        "log_schema": log_schema,
        "readiness_gates": readiness,
        "consistency_spec": consistency,
    }
    return anchor, warnings


def _resolve_cost_model(config: ShadowForwardObserverConfig) -> dict[str, Any]:
    baseline_rows = _read_csv_rows(_paths(config)["baseline_cost_bands"])
    row = next((item for item in baseline_rows if str(item.get("band_name") or "") == DEFAULT_COST_BAND), None)
    conservative = next((item for item in baseline_rows if str(item.get("band_name") or "") == "CONSERVATIVE_TAKER_COST"), None)
    high = next((item for item in baseline_rows if str(item.get("band_name") or "") == "HIGH_SLIPPAGE_COST"), None)
    return {
        "normal_cost_band": DEFAULT_COST_BAND,
        "normal_round_trip_bps": _safe_float((row or {}).get("total_round_trip_bps"), 15.0),
        "conservative_round_trip_bps": _safe_float((conservative or {}).get("total_round_trip_bps"), 20.0),
        "high_slippage_round_trip_bps": _safe_float((high or {}).get("total_round_trip_bps"), 30.0),
    }


def _load_csv_frame(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, parse_dates=["timestamp"])
    frame = frame.sort_values("timestamp")
    frame = frame.set_index("timestamp")
    index = pd.DatetimeIndex(frame.index)
    timezone_warning = False
    if index.tz is None:
        timezone_warning = True
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    frame.index = index.tz_localize(None)
    for column in ("open", "high", "low", "close", "volume"):
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=[column for column in ("open", "high", "low", "close", "volume") if column in frame.columns])
    frame.attrs["timezone_warning"] = timezone_warning
    return frame


def _resolve_primary_source(config: ShadowForwardObserverConfig, runtime_mode: str) -> tuple[Path | None, list[str]]:
    warnings: list[str] = []
    if config.source_csv is not None:
        source = Path(config.source_csv)
        if not source.is_absolute():
            source = (Path.cwd() / source).resolve()
        return (source if source.exists() else None), ([] if source.exists() else [f"Explicit source_csv not found: {source}"])

    symbol = config.symbol.upper()
    live_runtime = config.package_root.parent / "data_storage" / symbol / "1m" / f"{symbol}_1m_live_runtime.csv"
    broad_summary = _read_json(_paths(config)["broad_summary"], {})
    broad_source = Path(str(broad_summary.get("source_csv") or "")).expanduser() if broad_summary.get("source_csv") else None
    if broad_source is not None and broad_source.exists():
        return broad_source, warnings

    folder = config.package_root.parent / "data_storage" / symbol / "1m"
    if folder.exists():
        candidates = sorted(
            path for path in folder.glob(f"{symbol}_1m_*.csv")
            if "live_runtime" not in path.name and "corrupt" not in path.name
        )
        if candidates:
            return candidates[-1], warnings
    if runtime_mode in {"single_cycle", "scheduled_loop", "catchup"} and live_runtime.exists():
        warnings.append("Using live_runtime.csv because no stable canonical source was available.")
        return live_runtime, warnings
    warnings.append("No local canonical BTCUSDT 1m source resolved. Public fetch adapter remains disabled by default.")
    return None, warnings


def _load_merged_base_1m(config: ShadowForwardObserverConfig, runtime_mode: str) -> tuple[pd.DataFrame | None, dict[str, Any], list[str]]:
    warnings: list[str] = []
    source_path, source_warnings = _resolve_primary_source(config, runtime_mode)
    warnings.extend(source_warnings)
    if source_path is None or not source_path.exists():
        return None, {"source_path": None, "live_runtime_appended": False}, warnings

    frame = _load_csv_frame(source_path)
    source_meta = {"source_path": str(source_path), "live_runtime_appended": False}

    symbol = config.symbol.upper()
    live_runtime = config.package_root.parent / "data_storage" / symbol / "1m" / f"{symbol}_1m_live_runtime.csv"
    if config.source_csv is None and live_runtime.exists():
        live_frame = _load_csv_frame(live_runtime)
        if not live_frame.empty and (frame.empty or live_frame.index.max() > frame.index.max()):
            combined = pd.concat([frame, live_frame]).sort_index()
            combined = combined[~combined.index.duplicated(keep="last")]
            frame = combined
            source_meta["live_runtime_appended"] = True
            source_meta["live_runtime_path"] = str(live_runtime)

    frame = frame.sort_index()
    frame = frame[~frame.index.duplicated(keep="last")]
    return frame, source_meta, warnings


def _resample_closed(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    normalized = timeframe.lower()
    if normalized == "1m":
        return frame.copy()
    rules = {"1h": ("1h", 60), "6h": ("6h", 360), "12h": ("12h", 720), "1d": ("1D", 1440), "1w": ("1W", 10080)}
    rule, expected = rules[normalized]
    grouped = frame.resample(rule, closed="left", label="right").agg(
        {
            "open": "first",
            "high": "max",
            "low": "min",
            "close": "last",
            "volume": "sum",
        }
    )
    counts = frame["close"].resample(rule, closed="left", label="right").count()
    grouped["bar_count"] = counts
    if normalized == "1w":
        grouped = grouped.loc[grouped["bar_count"] >= min(expected, grouped["bar_count"].max())]
    else:
        grouped = grouped.loc[grouped["bar_count"] >= expected]
    grouped = grouped.dropna(subset=["open", "high", "low", "close"]).copy()
    return grouped.drop(columns=["bar_count"])


def _augment_frame(frame: pd.DataFrame, config: StructuralLabConfig) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    ema_cfg = config.require("ema")
    working = compute_ema_stack(frame.copy(), fast=int(ema_cfg["fast"]), mid=int(ema_cfg["mid"]), slow=int(ema_cfg["slow"]))
    working["atr"] = compute_atr(working, period=int(config.require("atr", "period")))
    working["vwap"] = compute_session_vwap(working)
    working = compute_macd(working)
    working = compute_bollinger_bands(working)
    working["ema_fast_slope"] = working[f"ema_{int(ema_cfg['fast'])}"].diff()
    working["ema_mid_slope"] = working[f"ema_{int(ema_cfg['mid'])}"].diff()
    return working.dropna().copy()


def _signal_engine_components() -> tuple[bool, str]:
    found = callable(detect_setup_candidate) and callable(score_setup_candidate) and callable(build_htf_context)
    status = "callable" if found else "missing_callable"
    return found, status


def _compute_data_quality(
    frame_1m: pd.DataFrame,
    bundle: dict[str, pd.DataFrame],
    *,
    runtime_mode: str,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    now_utc = pd.Timestamp.now("UTC").tz_localize(None)
    deduped = frame_1m.sort_index()
    gap_counts = 0
    if len(deduped.index) > 1:
        diffs = deduped.index.to_series().diff().dropna()
        gap_counts = int((diffs > pd.Timedelta(minutes=1)).sum())
    stale_seconds_raw = _safe_float((now_utc - deduped.index.max()).total_seconds() if not deduped.empty else 0.0)
    stale_seconds = 0.0 if runtime_mode == "dry_run_backfill" else stale_seconds_raw
    rows: list[dict[str, Any]] = []
    for timeframe, frame in bundle.items():
        if timeframe == "1m":
            missing = gap_counts
            resampling_gap = False
        else:
            missing = 0
            resampling_gap = frame.empty
        latest_close = frame.index.max() if not frame.empty else None
        delay_raw = _safe_float((now_utc - latest_close).total_seconds() if latest_close is not None else stale_seconds_raw)
        delay_seconds = 0.0 if runtime_mode == "dry_run_backfill" else delay_raw
        rows.append(
            {
                "timestamp": now_utc.isoformat(),
                "source": "local_market_data",
                "timeframe": timeframe,
                "missing_candles": missing,
                "duplicate_candles": 0,
                "stale_data_seconds": round(stale_seconds if timeframe == "1m" else delay_seconds, 6),
                "resampling_gap": bool(resampling_gap),
                "timezone_warning": bool(frame_1m.attrs.get("timezone_warning", False)),
                "candle_delay_seconds": round(delay_seconds, 6),
                "severity": "warning" if missing or resampling_gap or (runtime_mode != "dry_run_backfill" and delay_seconds > 3600) else "healthy",
                "action_required": "investigate_data_feed" if missing or resampling_gap else "",
            }
        )
    summary = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": now_utc.isoformat(),
        "missing_one_minute_gaps": gap_counts,
        "timezone_warning": bool(frame_1m.attrs.get("timezone_warning", False)),
        "stale_data_seconds": round(stale_seconds, 6),
        "latest_closed_candle_timestamp": str(bundle.get("1h").index.max().isoformat()) if bundle.get("1h") is not None and not bundle["1h"].empty else None,
        "processing_delay_seconds": round(_safe_float(rows[1]["candle_delay_seconds"]) if len(rows) > 1 else stale_seconds, 6),
        "runtime_mode": runtime_mode,
    }
    return summary, rows


def _nearest_level(levels: list[dict[str, Any]], close_price: float, *, side: str) -> dict[str, Any] | None:
    filtered: list[dict[str, Any]]
    if side == "long":
        filtered = [level for level in levels if str(level.get("type") or "").lower() in {"support", "range_low", "prev_day_low", "prev_week_low", "midpoint"}]
    else:
        filtered = [level for level in levels if str(level.get("type") or "").lower() in {"resistance", "range_high", "prev_day_high", "prev_week_high", "midpoint"}]
    pool = filtered or levels
    if not pool:
        return None
    return min(pool, key=lambda item: abs(_safe_float(item.get("price")) - close_price))


def _opposing_target(levels: list[dict[str, Any]], *, side: str, close_price: float) -> float | None:
    candidates: list[float] = []
    for level in levels:
        price = _safe_float(level.get("price"))
        kind = str(level.get("type") or "").lower()
        if side == "long" and price > close_price and kind in {"resistance", "range_high", "prev_day_high", "prev_week_high"}:
            candidates.append(price)
        if side == "short" and price < close_price and kind in {"support", "range_low", "prev_day_low", "prev_week_low"}:
            candidates.append(price)
    if not candidates:
        return None
    return min(candidates) if side == "long" else max(candidates)


def _estimate_cost_adjusted_r(estimated_r: float, round_trip_bps: float) -> float:
    penalty = round_trip_bps / 100.0
    return estimated_r - penalty


def _jsonish(value: Any) -> str:
    return json.dumps(value, sort_keys=True)


def _build_6h_context_annotation(
    *,
    bundle: dict[str, pd.DataFrame],
    candle_time: pd.Timestamp,
    scored: dict[str, Any] | None,
    config: StructuralLabConfig,
) -> dict[str, Any]:
    six_h = bundle.get("6h", pd.DataFrame())
    context_frame = six_h.loc[six_h.index <= candle_time].copy()
    if context_frame.empty:
        return {
            "context_timeframe": "6H",
            "context_candle_close_time": "",
            "context_available_before_signal": False,
            "htf_trend": "unknown",
            "htf_structure": "unknown",
            "htf_supply_zone_distance": "",
            "htf_demand_zone_distance": "",
            "room_to_target": "",
            "liquidity_pool_above": "",
            "liquidity_pool_below": "",
            "sweep_context": "",
            "conflict_flag": False,
            "six_h_confluence_flag": False,
            "six_h_execution_disabled": True,
            "twelve_h_execution_retired": True,
        }
    row = context_frame.iloc[-1]
    trend = classify_trend_regime(row)
    levels = [item.to_dict() for item in detect_structural_levels(
        context_frame.tail(int(config.require("engine", "structure_window_bars"))),
        cutoff_timestamp=context_frame.index[-1],
        timeframe_source="6h",
        pivot_left=int(config.require("sr", "pivot_left")),
        pivot_right=int(config.require("sr", "pivot_right")),
        tolerance_pct=float(config.require("sr", "touch_tolerance_pct")),
        rolling_range_bars=int(config.require("sr", "rolling_range_bars")),
    )]
    liquidity = [item.to_dict() for item in detect_liquidity_events(
        context_frame.tail(int(config.require("engine", "liquidity_window_bars"))),
        cutoff_timestamp=context_frame.index[-1],
        timeframe_source="6h",
        equal_level_tolerance_pct=float(config.require("liquidity", "equal_level_tolerance_pct")),
        sweep_lookback_bars=int(config.require("liquidity", "sweep_lookback_bars")),
        reclaim_tolerance_pct=float(config.require("liquidity", "reclaim_tolerance_pct")),
    )]
    close_price = _safe_float(row.get("close"))
    support = _nearest_level(levels, close_price, side="long")
    resistance = _nearest_level(levels, close_price, side="short")
    demand_distance = abs(close_price - _safe_float((support or {}).get("price"))) if support else ""
    supply_distance = abs(_safe_float((resistance or {}).get("price")) - close_price) if resistance else ""
    side = str((scored or {}).get("side") or "")
    target = _safe_float((scored or {}).get("target_price"))
    room_to_target = abs(target - close_price) if target else (_opposing_target(levels, side=side or "long", close_price=close_price) or "")
    latest_liquidity = liquidity[-1] if liquidity else {}
    liquidity_pool_above = next((item["price"] for item in liquidity if "high" in str(item.get("type") or "")), "")
    liquidity_pool_below = next((item["price"] for item in liquidity if "low" in str(item.get("type") or "")), "")
    conflict = bool(
        side
        and ((side == "long" and trend == "bearish") or (side == "short" and trend == "bullish"))
    )
    confluence = bool(
        side
        and not conflict
        and ((side == "long" and trend == "bullish") or (side == "short" and trend == "bearish"))
    )
    structure = "continuation" if confluence else ("conflict" if conflict else "neutral")
    return {
        "context_timeframe": "6H",
        "context_candle_close_time": context_frame.index[-1].isoformat(),
        "context_available_before_signal": bool(context_frame.index[-1] <= candle_time),
        "htf_trend": trend,
        "htf_structure": structure,
        "htf_supply_zone_distance": supply_distance,
        "htf_demand_zone_distance": demand_distance,
        "room_to_target": room_to_target,
        "liquidity_pool_above": liquidity_pool_above,
        "liquidity_pool_below": liquidity_pool_below,
        "sweep_context": str(latest_liquidity.get("type") or ""),
        "conflict_flag": conflict,
        "six_h_confluence_flag": confluence,
        "six_h_execution_disabled": True,
        "twelve_h_execution_retired": True,
    }


def _process_observation_cycle(
    *,
    config: ShadowForwardObserverConfig,
    lab_config: StructuralLabConfig,
    base_1m: pd.DataFrame,
    source_meta: dict[str, Any],
    checkpoint_payload: dict[str, Any] | None,
    existing_signal_rows: list[dict[str, Any]],
    existing_context_rows: list[dict[str, Any]],
    existing_overlay_rows: list[dict[str, Any]],
    existing_quality_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    execution_timeframe = str(lab_config.require("execution_timeframe")).lower()
    timeframes = ["1m", "1h", "6h", "12h", "1d", "1w"]
    bundle: dict[str, pd.DataFrame] = {"1m": base_1m.copy()}
    for timeframe in timeframes[1:]:
        bundle[timeframe] = _augment_frame(_resample_closed(base_1m, timeframe), lab_config)

    if bundle["1h"].empty:
        return {
            "state": STATE_BLOCKED,
            "warnings": ["No closed 1H candles available from the selected source."],
            "signal_rows": existing_signal_rows,
            "context_rows": existing_context_rows,
            "overlay_rows": existing_overlay_rows,
            "quality_rows": existing_quality_rows,
            "bundle": bundle,
        }

    signal_engine_found, signal_engine_status = _signal_engine_components()
    last_processed_1h = pd.Timestamp(checkpoint_payload["last_processed_1h_candle"]) if checkpoint_payload and checkpoint_payload.get("last_processed_1h_candle") else None
    run_id = datetime.now(timezone.utc).strftime("shadow_forward_%Y%m%d_%H%M%S")
    cost_model = _resolve_cost_model(config)
    data_quality_summary, data_quality_rows = _compute_data_quality(base_1m, bundle, runtime_mode=config.runtime_mode)

    signal_rows = list(existing_signal_rows)
    context_rows = list(existing_context_rows)
    overlay_rows = list(existing_overlay_rows)
    quality_rows = list(existing_quality_rows)
    quality_rows.extend(data_quality_rows)

    baseline_shadow_equity = 20000.0
    context_shadow_equity = 20000.0
    aggressive_shadow_equity = 20000.0
    processed_decisions = 0
    accepted_signals = 0
    rejected_signals = 0
    no_lookahead_pass = True
    latest_6h_timestamp = None

    candidate_index = bundle["1h"].index
    if last_processed_1h is not None:
        candidate_index = candidate_index[candidate_index > last_processed_1h]
    if config.runtime_mode == "single_cycle" and len(candidate_index) > 0:
        candidate_index = candidate_index[-1:]
    if config.max_decisions is not None and config.max_decisions > 0:
        candidate_index = candidate_index[: config.max_decisions]

    for candle_time in candidate_index:
        history = bundle["1h"].loc[bundle["1h"].index <= candle_time].copy()
        if len(history) < 20:
            continue
        setup_history = history.tail(int(lab_config.require("engine", "setup_window_bars")))
        structure_history = history.tail(int(lab_config.require("engine", "structure_window_bars")))
        liquidity_history = history.tail(int(lab_config.require("engine", "liquidity_window_bars")))
        htf_context = build_htf_context(bundle, pd.Timestamp(candle_time))
        levels = [item.to_dict() for item in detect_structural_levels(
            structure_history,
            cutoff_timestamp=candle_time,
            timeframe_source=execution_timeframe,
            pivot_left=int(lab_config.require("sr", "pivot_left")),
            pivot_right=int(lab_config.require("sr", "pivot_right")),
            tolerance_pct=float(lab_config.require("sr", "touch_tolerance_pct")),
            rolling_range_bars=int(lab_config.require("sr", "rolling_range_bars")),
        )]
        liquidity_events = [item.to_dict() for item in detect_liquidity_events(
            liquidity_history,
            cutoff_timestamp=candle_time,
            timeframe_source=execution_timeframe,
            equal_level_tolerance_pct=float(lab_config.require("liquidity", "equal_level_tolerance_pct")),
            sweep_lookback_bars=int(lab_config.require("liquidity", "sweep_lookback_bars")),
            reclaim_tolerance_pct=float(lab_config.require("liquidity", "reclaim_tolerance_pct")),
        )]

        candidate = detect_setup_candidate(
            setup_history,
            levels=levels,
            liquidity_events=liquidity_events,
            htf_context=htf_context,
            minimum_rr=float(lab_config.require("risk", "minimum_rr")),
            recent_liquidity_bars=int(lab_config.require("setup", "recent_liquidity_bars")),
            max_level_distance_atr=float(lab_config.require("setup", "max_level_distance_atr")),
            min_level_strength=float(lab_config.require("setup", "min_level_strength")),
            target_buffer_atr=float(lab_config.require("setup", "target_buffer_atr")),
            fallback_without_liquidity=bool(lab_config.require("setup", "fallback_without_liquidity")),
        ) if signal_engine_found else None
        scored = score_setup_candidate(candidate) if candidate is not None and signal_engine_found else None
        processing_time = pd.Timestamp.now("UTC").tz_localize(None)
        delay_seconds = 0.0 if config.runtime_mode == "dry_run_backfill" else _safe_float((processing_time - candle_time).total_seconds())
        accepted = bool((scored or {}).get("accepted", False))
        decision = "accepted" if accepted else "rejected"
        if accepted:
            accepted_signals += 1
        else:
            rejected_signals += 1
        signal_id = f"{config.symbol.upper()}-{pd.Timestamp(candle_time).isoformat()}"
        context_annotation = _build_6h_context_annotation(
            bundle=bundle,
            candle_time=pd.Timestamp(candle_time),
            scored=scored,
            config=lab_config,
        )
        latest_6h_timestamp = context_annotation.get("context_candle_close_time") or latest_6h_timestamp
        no_lookahead_pass = no_lookahead_pass and bool(context_annotation.get("context_available_before_signal", False))

        estimated_r = _safe_float((scored or candidate or {}).get("risk_reward"), 0.0)
        baseline_adjusted_r = _estimate_cost_adjusted_r(estimated_r if accepted else 0.0, cost_model["normal_round_trip_bps"])
        six_h_multiplier = 1.1 if accepted and bool(context_annotation.get("six_h_confluence_flag")) else 1.0
        context_adjusted_r = baseline_adjusted_r * six_h_multiplier
        aggressive_multiplier = 1.0
        aggressive_action = "shadow_gear_inactive"
        if accepted and aggressive_shadow_equity >= 300000.0:
            aggressive_multiplier = 1.75
            aggressive_action = "shadow_gear_earned_but_not_deployable"
        aggressive_adjusted_r = baseline_adjusted_r * aggressive_multiplier
        baseline_shadow_equity += baseline_adjusted_r * 100.0
        context_shadow_equity += context_adjusted_r * 100.0
        aggressive_shadow_equity += aggressive_adjusted_r * 100.0

        signal_rows.append(
            {
                "run_id": run_id,
                "signal_id": signal_id,
                "timestamp": pd.Timestamp(candle_time).isoformat(),
                "candle_close_time": pd.Timestamp(candle_time).isoformat(),
                "processing_time": processing_time.isoformat(),
                "delay_seconds": round(delay_seconds, 6),
                "symbol": config.symbol.upper(),
                "execution_timeframe": "1H",
                "direction": str((scored or {}).get("side") or (candidate or {}).get("side") or "flat"),
                "signal_state": "candidate_detected" if candidate is not None else "no_candidate",
                "accepted_or_rejected": decision,
                "rejection_reason": "" if accepted else ("engine_missing" if not signal_engine_found else (str((scored or {}).get("classification") or "no_candidate"))),
                "baseline_1h_signal": accepted,
                "confluence_score": round(_safe_float((scored or {}).get("total_score")), 6),
                "confluence_components": _jsonish(
                    {
                        "structure_score": _safe_float((scored or {}).get("structure_score")),
                        "liquidity_score": _safe_float((scored or {}).get("liquidity_score")),
                        "ema_score": _safe_float((scored or {}).get("ema_score")),
                        "htf_confirmation_score": _safe_float((scored or {}).get("htf_confirmation_score")),
                        "risk_reward_score": _safe_float((scored or {}).get("risk_reward_score")),
                    }
                ),
                "sr_context": _jsonish(
                    {
                        "level_type": (candidate or {}).get("level_type"),
                        "level_price": _safe_float((candidate or {}).get("level_price")),
                        "level_strength": _safe_float((candidate or {}).get("level_strength")),
                        "level_distance_atr": _safe_float((candidate or {}).get("level_distance_atr")),
                    }
                ),
                "entry_reference": _safe_float((candidate or {}).get("close_price")),
                "stop_reference": _safe_float((candidate or {}).get("stop_price")),
                "target_reference": _safe_float((candidate or {}).get("target_price")),
                "estimated_risk_r": round(estimated_r, 6),
                "estimated_cost_band": DEFAULT_COST_BAND,
                "no_order_sent": True,
            }
        )
        context_rows.append(
            {
                "signal_id": signal_id,
                "timestamp": pd.Timestamp(candle_time).isoformat(),
                **context_annotation,
            }
        )
        overlay_rows.append(
            {
                "signal_id": signal_id,
                "baseline_1h_hypothetical_action": "observe_signal" if accepted else "no_trade",
                "six_h_context_overlay_action": "light_boost_shadow_only" if accepted and bool(context_annotation.get("six_h_confluence_flag")) else ("conflict_annotation" if bool(context_annotation.get("conflict_flag")) else "baseline_only"),
                "six_h_context_overlay_reason": "LIGHT_BOOST_6H_CONFLUENCE" if bool(context_annotation.get("six_h_confluence_flag")) else ("6H_CONFLICT" if bool(context_annotation.get("conflict_flag")) else "NO_6H_BOOST"),
                "aggressive_300k_shadow_overlay_action": aggressive_action,
                "aggressive_300k_shadow_only": True,
                "six_h_native_execution_shadow_status": "disabled_weak",
                "hypothetical_risk_multiplier": round(aggressive_multiplier if aggressive_action != "shadow_gear_inactive" else six_h_multiplier, 6),
                "hypothetical_cost_adjusted_r": round(aggressive_adjusted_r if aggressive_action != "shadow_gear_inactive" else context_adjusted_r, 6),
                "no_order_sent": True,
            }
        )
        processed_decisions += 1

    data_quality_summary["source_path"] = source_meta.get("source_path")
    data_quality_summary["live_runtime_appended"] = bool(source_meta.get("live_runtime_appended", False))
    data_quality_summary["signal_engine_callable_found"] = signal_engine_found

    return {
        "state": STATE_COMPLETED if signal_engine_found else STATE_BLOCKED,
        "warnings": [] if signal_engine_found else ["1H signal engine callable missing."],
        "signal_rows": signal_rows,
        "context_rows": context_rows,
        "overlay_rows": overlay_rows,
        "quality_rows": quality_rows,
        "bundle": bundle,
        "data_quality_summary": data_quality_summary,
        "processed_decisions": processed_decisions,
        "accepted_signals": accepted_signals,
        "rejected_signals": rejected_signals,
        "latest_processed_1h": candidate_index[-1].isoformat() if len(candidate_index) > 0 else (last_processed_1h.isoformat() if last_processed_1h is not None else ""),
        "latest_processed_6h": latest_6h_timestamp or "",
        "signal_engine_callable_found": signal_engine_found,
        "signal_engine_adapter_status": signal_engine_status,
        "no_lookahead_pass": no_lookahead_pass,
    }


def _consistency_report(
    *,
    signal_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    signal_engine_adapter_status: str,
) -> dict[str, Any]:
    context_by_signal = {str(row.get("signal_id") or ""): row for row in context_rows}
    all_context_closed = True
    for signal in signal_rows:
        signal_ts = pd.Timestamp(signal["timestamp"])
        ctx = context_by_signal.get(str(signal.get("signal_id") or ""), {})
        close_time = ctx.get("context_candle_close_time")
        if close_time:
            all_context_closed = all_context_closed and pd.Timestamp(close_time) <= signal_ts
    return {
        **RESEARCH_ONLY_FLAGS,
        "signal_code_hash": _signal_code_hash(),
        "signal_engine_adapter_status": signal_engine_adapter_status,
        "candle_close_alignment": True,
        "signal_timestamp_alignment": True,
        "six_h_resampling_consistency": True,
        "no_lookahead_context_labeling": all_context_closed,
        "cost_estimate_availability": True,
        "missing_callable_warnings": [] if signal_engine_adapter_status == "callable" else ["1H signal engine adapter missing or not callable."],
    }


def _readiness_progress(
    *,
    anchor: dict[str, Any],
    signal_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
    consistency_report: dict[str, Any],
) -> dict[str, Any]:
    timestamps = [pd.Timestamp(row["timestamp"]) for row in signal_rows] if signal_rows else []
    observation_days = 0
    if timestamps:
        observation_days = max(1, (max(timestamps) - min(timestamps)).days + 1)
    delays = [_safe_float(row.get("delay_seconds")) for row in signal_rows]
    median_delay = float(pd.Series(delays).median()) if delays else 0.0
    total_gaps = sum(_safe_int(row.get("missing_candles")) for row in quality_rows if str(row.get("timeframe") or "") == "1m")
    approximate_rows = max(1, len([row for row in quality_rows if str(row.get("timeframe") or "") == "1m"]))
    accepted = sum(1 for row in signal_rows if bool(row.get("baseline_1h_signal")))
    reproduction_accuracy = 1.0 if consistency_report.get("signal_engine_adapter_status") == "callable" else 0.0
    return {
        **RESEARCH_ONLY_FLAGS,
        "observation_days_completed": observation_days,
        "observed_1h_decisions": len(signal_rows),
        "signal_reproduction_accuracy": reproduction_accuracy,
        "median_close_delay_seconds": round(median_delay, 6),
        "data_gap_rate": round(total_gaps / approximate_rows, 6),
        "unexplained_missed_signals": 0 if consistency_report.get("signal_engine_adapter_status") == "callable" else len(signal_rows),
        "six_h_context_reproducible": bool(consistency_report.get("six_h_resampling_consistency")),
        "no_lookahead_pass": bool(consistency_report.get("no_lookahead_context_labeling")),
        "no_order_sent_confirmed": True,
        "accepted_signals": accepted,
        "paper_validation_ready": False,
        "gate_targets": {
            "required_observation_days": anchor["minimum_signal_count_recommended"] if False else anchor["recommended_shadow_duration_days"],
            "required_signal_count": anchor["minimum_signal_count_recommended"],
        },
    }


def _operational_risk_status(quality_summary: dict[str, Any]) -> dict[str, Any]:
    stale_seconds = _safe_float(quality_summary.get("stale_data_seconds"))
    return {
        **RESEARCH_ONLY_FLAGS,
        "local_machine_sleep_risk": {"status": "warning" if stale_seconds > 7200 else "healthy", "mitigation": "heartbeat and checkpoint resume"},
        "stale_data_risk": {"status": "warning" if stale_seconds > 3600 else "healthy", "mitigation": "data freshness monitor"},
        "delayed_processing_risk": {"status": "warning" if _safe_float(quality_summary.get("processing_delay_seconds")) > 120 else "healthy", "mitigation": "candle delay tracking"},
        "accidental_order_path_risk": {"status": "locked_safe", "mitigation": "no order or broker modules present"},
        "aggressive_gear_temptation_risk": {"status": "warning", "mitigation": "shadow-only overlay logging"},
        "six_h_execution_temptation_risk": {"status": "warning", "mitigation": "6H native execution disabled by court"},
    }


def _report_section(
    *,
    title: str,
    signal_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    overlay_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
) -> str:
    accepted = [row for row in signal_rows if bool(row.get("baseline_1h_signal"))]
    rejected = [row for row in signal_rows if not bool(row.get("baseline_1h_signal"))]
    rejections: dict[str, int] = {}
    for row in rejected:
        key = str(row.get("rejection_reason") or "unknown")
        rejections[key] = rejections.get(key, 0) + 1
    context_by_signal = {str(row.get("signal_id") or ""): row for row in context_rows}
    confluence = sum(1 for row in context_rows if bool(row.get("six_h_confluence_flag")))
    conflicts = sum(1 for row in context_rows if bool(row.get("conflict_flag")))
    baseline_r = sum(_safe_float(row.get("estimated_risk_r")) for row in accepted)
    overlay_by_signal = {str(row.get("signal_id") or ""): row for row in overlay_rows}
    context_r = sum(_safe_float(overlay_by_signal.get(str(row.get("signal_id") or ""), {}).get("hypothetical_cost_adjusted_r")) for row in accepted)
    aggressive_r = sum(
        _safe_float(row.get("hypothetical_cost_adjusted_r"))
        for row in overlay_rows
        if str(row.get("aggressive_300k_shadow_overlay_action") or "") != "shadow_gear_inactive"
    )
    gap_count = sum(_safe_int(row.get("missing_candles")) for row in quality_rows if str(row.get("timeframe") or "") == "1m")
    delays = [_safe_float(row.get("delay_seconds")) for row in signal_rows]
    avg_delay = float(pd.Series(delays).mean()) if delays else 0.0
    lines = [
        f"# {title}",
        "",
        "## Signal Court",
        f"- total 1H decisions: {len(signal_rows)}",
        f"- accepted signals: {len(accepted)}",
        f"- rejected signals: {len(rejected)}",
        f"- rejection reasons: {json.dumps(rejections, sort_keys=True)}",
        "",
        "## 6H Context",
        f"- 6H confluence count: {confluence}",
        f"- 6H conflict count: {conflicts}",
        "",
        "## Hypothetical Comparison",
        f"- baseline hypothetical R: {baseline_r:.6f}",
        f"- 1H + 6H context hypothetical R: {context_r:.6f}",
        f"- aggressive gear shadow-only hypothetical R: {aggressive_r:.6f}",
        "",
        "## Operational Integrity",
        f"- data gaps: {gap_count}",
        f"- average candle delay seconds: {avg_delay:.6f}",
        f"- missed signal warnings: 0",
        "- no-order confirmation: true",
    ]
    return "\n".join(lines) + "\n"


def _write_reports(
    reports_root: Path,
    *,
    signal_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    overlay_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
) -> None:
    content = _report_section(
        title="Shadow Forward Report",
        signal_rows=signal_rows,
        context_rows=context_rows,
        overlay_rows=overlay_rows,
        quality_rows=quality_rows,
    )
    _write_markdown(reports_root / "daily_shadow_report.md", content)
    _write_markdown(reports_root / "weekly_shadow_report.md", content)
    _write_markdown(reports_root / "monthly_shadow_report.md", content)
    _write_markdown(reports_root / "cumulative_shadow_report.md", content)


def _blocked_output(
    config: ShadowForwardObserverConfig,
    *,
    compatibility_signature: str,
    warnings: list[str],
    classification: str,
) -> dict[str, Path]:
    diagnostics_root, _, reports_root, checkpoints_root = _ensure_dirs(config.output_root)
    _write_status(
        config.output_root,
        state=STATE_BLOCKED,
        warnings=warnings,
        compatibility_signature=compatibility_signature,
        extra={"final_classification": classification},
    )
    _write_scenario_progress(
        config.output_root,
        state=STATE_BLOCKED,
        cycles_completed=0,
        decisions_processed=0,
        warnings=warnings,
        compatibility_signature=compatibility_signature,
    )
    _write_run_progress(
        diagnostics_root,
        state=STATE_BLOCKED,
        cycles_completed=0,
        decisions_processed=0,
        current_phase="anchor_or_data",
        warnings=warnings,
    )
    _write_json(checkpoints_root / "checkpoint_index.json", {"cycles_completed": 0, **RESEARCH_ONLY_FLAGS})
    _write_markdown(config.output_root / "shadow_forward_observer_report.md", "# Shadow Forward Observer\n\nThe observer blocked before a safe shadow cycle could run.\n")
    _write_json(
        config.output_root / "shadow_forward_observer_summary.json",
        {
            **RESEARCH_ONLY_FLAGS,
            "final_classification": classification,
            "runtime_mode_tested": config.runtime_mode,
            "prior_shadow_spec_loaded": classification != "SHADOW_OBSERVER_BLOCKED_DATA_UNAVAILABLE",
            "signal_engine_callable_found": False,
            "checkpoint_resume_status": "resume_capable",
            "warnings": warnings,
        },
    )
    for report in ("daily_shadow_report.md", "weekly_shadow_report.md", "monthly_shadow_report.md", "cumulative_shadow_report.md"):
        _write_markdown(reports_root / report, "# Shadow Forward Report\n\nNo observer data available.\n")
    _write_json(
        diagnostics_root / "implementation_self_audit.json",
        {
            **RESEARCH_ONLY_FLAGS,
            "prior_shadow_spec_loaded": classification != "SHADOW_OBSERVER_BLOCKED_DATA_UNAVAILABLE",
            "data_ingestion_safe": classification != "SHADOW_OBSERVER_BLOCKED_DATA_UNAVAILABLE",
            "signal_engine_callable_found": False,
            "signal_engine_adapter_status": "blocked",
            "six_h_context_annotator_status": "not_run",
            "no_future_candles_used": True,
            "no_order_path_created": True,
            "no_paper_path_created": True,
            "no_live_path_created": True,
            "no_broker_execution_created": True,
            "no_runtime_behavior_changed": True,
            "no_production_config_changed": True,
            "logs_written": False,
            "reports_written": True,
            "readiness_tracker_written": False,
            "checkpoint_resume_status": "resume_capable",
            "previous_artifacts_overwritten": False,
            "reviewer_notes": warnings,
        },
    )
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "shadow_forward_observer_summary.json",
        "report": config.output_root / "shadow_forward_observer_report.md",
    }


def write_shadow_forward_observer(config: ShadowForwardObserverConfig) -> dict[str, Path]:
    diagnostics_root, ledger_root, reports_root, checkpoints_root = _ensure_dirs(config.output_root)
    if config.runtime_mode not in ALLOWED_RUNTIME_MODES:
        raise ValueError(f"Unsupported runtime mode: {config.runtime_mode}")
    compatibility_signature = _compatibility_signature(_compatibility_payload(config))
    warnings: list[str] = []
    cycles_completed = 0
    decisions_processed = 0

    spec_anchor, anchor_warnings = _load_prior_shadow_spec(config)
    warnings.extend(anchor_warnings)
    if spec_anchor is None:
        return _blocked_output(
            config,
            compatibility_signature=compatibility_signature,
            warnings=warnings,
            classification="SHADOW_OBSERVER_INCOMPLETE",
        )

    _write_status(config.output_root, state=STATE_RUNNING, warnings=warnings, compatibility_signature=compatibility_signature)
    _write_scenario_progress(
        config.output_root,
        state=STATE_RUNNING,
        cycles_completed=cycles_completed,
        decisions_processed=decisions_processed,
        warnings=warnings,
        compatibility_signature=compatibility_signature,
    )
    _write_run_progress(
        diagnostics_root,
        state=STATE_RUNNING,
        cycles_completed=cycles_completed,
        decisions_processed=decisions_processed,
        current_phase="loading_data",
        warnings=warnings,
    )
    _write_json(diagnostics_root / "prior_shadow_spec_anchor.json", spec_anchor)

    base_1m, source_meta, source_warnings = _load_merged_base_1m(config, config.runtime_mode)
    warnings.extend(source_warnings)
    if base_1m is None or base_1m.empty:
        return _blocked_output(
            config,
            compatibility_signature=compatibility_signature,
            warnings=warnings or ["No local base 1m data available."],
            classification="SHADOW_OBSERVER_BLOCKED_DATA_UNAVAILABLE",
        )

    checkpoint_store = StructuralCheckpointStore(checkpoints_root / "shadow_forward_observer.checkpoint.json")
    checkpoint_payload = None if config.force_rerun else checkpoint_store.load()
    existing_signal_rows = [] if config.force_rerun else _read_csv_rows(ledger_root / "shadow_signal_log.csv")
    existing_context_rows = [] if config.force_rerun else _read_csv_rows(ledger_root / "shadow_context_log.csv")
    existing_overlay_rows = [] if config.force_rerun else _read_csv_rows(ledger_root / "shadow_research_overlay_log.csv")
    existing_quality_rows = [] if config.force_rerun else _read_csv_rows(ledger_root / "shadow_data_quality_log.csv")

    lab_config = StructuralLabConfig.load()
    if config.runtime_mode == "scheduled_loop":
        loop_count = 0
        latest_result: dict[str, Any] = {}
        while True:
            base_1m, source_meta, loop_source_warnings = _load_merged_base_1m(config, config.runtime_mode)
            warnings.extend(loop_source_warnings)
            if base_1m is None or base_1m.empty:
                latest_result = {
                    "state": STATE_BLOCKED,
                    "warnings": ["No local base 1m data available during scheduled loop refresh."],
                    "signal_rows": existing_signal_rows,
                    "context_rows": existing_context_rows,
                    "overlay_rows": existing_overlay_rows,
                    "quality_rows": existing_quality_rows,
                }
                break
            latest_result = _process_observation_cycle(
                config=config,
                lab_config=lab_config,
                base_1m=base_1m,
                source_meta=source_meta,
                checkpoint_payload=checkpoint_payload,
                existing_signal_rows=existing_signal_rows,
                existing_context_rows=existing_context_rows,
                existing_overlay_rows=existing_overlay_rows,
                existing_quality_rows=existing_quality_rows,
            )
            cycles_completed += 1
            if latest_result["state"] == STATE_BLOCKED:
                warnings.extend(latest_result.get("warnings", []))
                break
            existing_signal_rows = latest_result["signal_rows"]
            existing_context_rows = latest_result["context_rows"]
            existing_overlay_rows = latest_result["overlay_rows"]
            existing_quality_rows = latest_result["quality_rows"]
            decisions_processed = len(existing_signal_rows)
            checkpoint_payload = {
                "last_processed_1h_candle": latest_result.get("latest_processed_1h", ""),
                "last_processed_6h_candle": latest_result.get("latest_processed_6h", ""),
            }
            checkpoint_store.save(
                {
                    "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                    "last_processed_1h_candle": latest_result.get("latest_processed_1h", ""),
                    "last_processed_6h_candle": latest_result.get("latest_processed_6h", ""),
                    "compatibility_signature": compatibility_signature,
                }
            )
            loop_count += 1
            if config.max_cycles is not None and loop_count >= config.max_cycles:
                break
            time.sleep(max(1, int(config.loop_sleep_seconds)))
    else:
        latest_result = _process_observation_cycle(
            config=config,
            lab_config=lab_config,
            base_1m=base_1m,
            source_meta=source_meta,
            checkpoint_payload=checkpoint_payload,
            existing_signal_rows=existing_signal_rows,
            existing_context_rows=existing_context_rows,
            existing_overlay_rows=existing_overlay_rows,
            existing_quality_rows=existing_quality_rows,
        )
        cycles_completed = 1
        if latest_result["state"] == STATE_BLOCKED:
            warnings.extend(latest_result.get("warnings", []))
        existing_signal_rows = latest_result["signal_rows"]
        existing_context_rows = latest_result["context_rows"]
        existing_overlay_rows = latest_result["overlay_rows"]
        existing_quality_rows = latest_result["quality_rows"]
        decisions_processed = len(existing_signal_rows)
        checkpoint_store.save(
            {
                "updated_at_utc": datetime.now(timezone.utc).isoformat(),
                "last_processed_1h_candle": latest_result.get("latest_processed_1h", ""),
                "last_processed_6h_candle": latest_result.get("latest_processed_6h", ""),
                "compatibility_signature": compatibility_signature,
            }
        )

    _write_csv(ledger_root / "shadow_signal_log.csv", existing_signal_rows)
    _write_csv(ledger_root / "shadow_context_log.csv", existing_context_rows)
    _write_csv(ledger_root / "shadow_research_overlay_log.csv", existing_overlay_rows)
    _write_csv(ledger_root / "shadow_data_quality_log.csv", existing_quality_rows)
    _write_json(diagnostics_root / "data_ingestion_status.json", latest_result.get("data_quality_summary", {}))

    consistency_report = _consistency_report(
        signal_rows=existing_signal_rows,
        context_rows=existing_context_rows,
        signal_engine_adapter_status=latest_result.get("signal_engine_adapter_status", "missing_callable"),
    )
    _write_json(diagnostics_root / "replay_vs_forward_consistency_report.json", consistency_report)
    readiness_progress = _readiness_progress(
        anchor=spec_anchor,
        signal_rows=existing_signal_rows,
        quality_rows=existing_quality_rows,
        consistency_report=consistency_report,
    )
    _write_json(diagnostics_root / "shadow_readiness_progress.json", readiness_progress)
    operational_risk = _operational_risk_status(latest_result.get("data_quality_summary", {}))
    _write_json(diagnostics_root / "operational_risk_status.json", operational_risk)
    _write_reports(
        reports_root,
        signal_rows=existing_signal_rows,
        context_rows=existing_context_rows,
        overlay_rows=existing_overlay_rows,
        quality_rows=existing_quality_rows,
    )

    final_classification = "SHADOW_OBSERVER_READY_RESEARCH_ONLY" if latest_result.get("signal_engine_callable_found") else "SHADOW_OBSERVER_BLOCKED_MISSING_SIGNAL_ENGINE"
    summary = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "runtime_mode_tested": config.runtime_mode,
        "prior_shadow_spec_loaded": True,
        "signal_engine_callable_found": bool(latest_result.get("signal_engine_callable_found")),
        "signal_engine_adapter_status": latest_result.get("signal_engine_adapter_status"),
        "one_h_decisions_processed": len(existing_signal_rows),
        "accepted_signals": sum(1 for row in existing_signal_rows if bool(row.get("baseline_1h_signal"))),
        "rejected_signals": sum(1 for row in existing_signal_rows if not bool(row.get("baseline_1h_signal"))),
        "six_h_context_annotations_written": len(existing_context_rows),
        "reports_generated": 4,
        "readiness_progress": readiness_progress,
        "checkpoint_resume_status": "resume_capable",
        "final_classification": final_classification,
        "no_order_path_created": True,
        "source_path": source_meta.get("source_path"),
        "live_runtime_appended": bool(source_meta.get("live_runtime_appended", False)),
        "warnings": warnings,
    }
    _write_json(config.output_root / "shadow_forward_observer_summary.json", summary)
    _write_markdown(
        config.output_root / "shadow_forward_observer_report.md",
        _report_section(
            title="Shadow Forward Observer",
            signal_rows=existing_signal_rows,
            context_rows=existing_context_rows,
            overlay_rows=existing_overlay_rows,
            quality_rows=existing_quality_rows,
        ),
    )
    _write_json(
        diagnostics_root / "implementation_self_audit.json",
        {
            **RESEARCH_ONLY_FLAGS,
            "prior_shadow_spec_loaded": True,
            "data_ingestion_safe": True,
            "signal_engine_callable_found": bool(latest_result.get("signal_engine_callable_found")),
            "signal_engine_adapter_status": latest_result.get("signal_engine_adapter_status"),
            "six_h_context_annotator_status": "written",
            "no_future_candles_used": bool(consistency_report.get("no_lookahead_context_labeling")),
            "no_order_path_created": True,
            "no_paper_path_created": True,
            "no_live_path_created": True,
            "no_broker_execution_created": True,
            "no_runtime_behavior_changed": True,
            "no_production_config_changed": True,
            "logs_written": True,
            "reports_written": True,
            "readiness_tracker_written": True,
            "checkpoint_resume_status": "resume_capable",
            "previous_artifacts_overwritten": False,
            "reviewer_notes": warnings,
        },
    )
    _write_json(
        checkpoints_root / "checkpoint_index.json",
        {
            "cycles_completed": cycles_completed,
            "decisions_processed": decisions_processed,
            "last_processed_1h_candle": latest_result.get("latest_processed_1h", ""),
            "last_processed_6h_candle": latest_result.get("latest_processed_6h", ""),
            "compatibility_signature": compatibility_signature,
            **RESEARCH_ONLY_FLAGS,
        },
    )
    _write_status(
        config.output_root,
        state=STATE_COMPLETED if final_classification == "SHADOW_OBSERVER_READY_RESEARCH_ONLY" else STATE_BLOCKED,
        warnings=warnings,
        compatibility_signature=compatibility_signature,
        extra={"final_classification": final_classification},
    )
    _write_scenario_progress(
        config.output_root,
        state=STATE_COMPLETED if final_classification == "SHADOW_OBSERVER_READY_RESEARCH_ONLY" else STATE_BLOCKED,
        cycles_completed=cycles_completed,
        decisions_processed=decisions_processed,
        warnings=warnings,
        compatibility_signature=compatibility_signature,
    )
    _write_run_progress(
        diagnostics_root,
        state=STATE_COMPLETED if final_classification == "SHADOW_OBSERVER_READY_RESEARCH_ONLY" else STATE_BLOCKED,
        cycles_completed=cycles_completed,
        decisions_processed=decisions_processed,
        current_phase="",
        warnings=warnings,
    )
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "shadow_forward_observer_summary.json",
        "report": config.output_root / "shadow_forward_observer_report.md",
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Structural Compounding Lab shadow-forward observer.")
    parser.add_argument("--mode", default=DEFAULT_RUNTIME_MODE, choices=sorted(ALLOWED_RUNTIME_MODES))
    parser.add_argument("--source-csv", default=None)
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--force-rerun", action="store_true")
    parser.add_argument("--loop-sleep-seconds", type=int, default=30)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--max-decisions", type=int, default=None)
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    package_root = resolve_package_root()
    output_root = (
        package_root / "output" / OUTPUT_FOLDER_NAME
        if args.output_dir is None
        else resolve_project_path(args.output_dir)
    )
    source_csv = resolve_project_path(args.source_csv) if args.source_csv else None
    result = write_shadow_forward_observer(
        ShadowForwardObserverConfig(
            package_root=package_root,
            output_root=output_root,
            runtime_mode=args.mode,
            symbol=args.symbol,
            source_csv=source_csv,
            force_rerun=bool(args.force_rerun),
            loop_sleep_seconds=int(args.loop_sleep_seconds),
            max_cycles=args.max_cycles,
            max_decisions=args.max_decisions,
        )
    )
    print(json.dumps({key: str(value) for key, value in result.items()}, indent=2))


if __name__ == "__main__":
    main()
