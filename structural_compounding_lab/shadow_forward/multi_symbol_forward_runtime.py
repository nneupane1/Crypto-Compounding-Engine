from __future__ import annotations

import argparse
import csv
import copy
import json
import math
import os
import smtplib
import sys
import time
from dataclasses import dataclass
from datetime import datetime, time as datetime_time, timedelta, timezone
from email.message import EmailMessage
from html import escape
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.config import AppConfig  # noqa: E402
from structural_compounding_lab.backtest.engine import StructuralBacktestEngine  # noqa: E402
from structural_compounding_lab.common.email_safety import smtp_allowed_for_output_root  # noqa: E402
from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path  # noqa: E402
from structural_compounding_lab.config import StructuralLabConfig  # noqa: E402
from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import _apply_frozen_patch, _load_frozen_rules  # noqa: E402
from structural_compounding_lab.diagnostics.cost_aware_frozen_candidate_rebuild import (  # noqa: E402
    CANDIDATE_NAME,
    MAX_PRE_ENTRY_COST_R,
    ROUND_TRIP_COST_BPS,
    _candidate_rows,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import _prepare_rows  # noqa: E402
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import _normalize_trade_rows, _read_csv_rows  # noqa: E402
from structural_compounding_lab.diagnostics.multi_asset_earned_parallel_slot_court import (  # noqa: E402
    ACTIVE_CAP,
    START_CAPITAL,
    TAX_RESERVE_RATE,
    USER_LITERAL_SLOT_LADDER,
    _replay as _earned_slot_replay,
    _write_csv as _write_replay_csv,
)
from structural_compounding_lab.shadow_forward.fresh_btcusdt_data_updater import (  # noqa: E402
    _normalize_fetched_rows,
    _public_fetch_binance_1m,
)


OUTPUT_FOLDER_NAME = "multi_symbol_forward_runtime_earned_parallel_slots"
DEFAULT_ALERT_TO = "nneupane1@gmail.com"
LOCAL_REPORT_TIMEZONE = "Europe/Berlin"
ALLOWED_MODES = {"run_once", "status", "evidence_check"}
EARNED_PARALLEL_SLOT_SPEC_ID = "user_literal_1pct_each_slot"
EARNED_PARALLEL_SLOT_FREEZE_CLASSIFICATION = "MULTI_ASSET_9_SYMBOL_BTC_INCLUSION_FREEZE_CANDIDATE_RESEARCH_ONLY"
ACTIVE_MULTI_SYMBOL_UNIVERSE_ID = "btc_research_ranked_9_symbol"
ACTIVE_MULTI_SYMBOL_FREEZE_COURT = "multi_asset_earned_parallel_slot_btc_inclusion_court_001"
ACTIVE_MULTI_SYMBOL_FREEZE_NOTE = (
    "BTC-inclusive nine-symbol earned-slot research freeze. This is still output-only "
    "shadow-forward observation; it does not enable paper, live, order, or broker behavior."
)
ACTIVE_6H_CONTEXT_OVERLAY_COURT = "multi_asset_6h_context_overlay_court_001"
ACTIVE_6H_CONTEXT_OVERLAY_CLASSIFICATION = "MULTI_ASSET_6H_CONTEXT_OVERLAY_FREEZE_CANDIDATE_RESEARCH_ONLY"
ACTIVE_6H_CONTEXT_VARIANT = "light_boost_6h_confluence"
ACTIVE_6H_CONTEXT_BOOST_MULTIPLIER = 1.10
SPOT_COMPATIBLE_LONG_ONLY = True
SHORT_SELLING_ALLOWED = False
EARNED_PARALLEL_SLOT_LADDER: tuple[dict[str, Any], ...] = (
    {"min_closed_active_equity_eur": 0.0, "max_simultaneous_trades": 1, "risk_per_slot_pct": 0.01, "max_total_open_risk_pct": 0.01},
    {"min_closed_active_equity_eur": 100_000.0, "max_simultaneous_trades": 2, "risk_per_slot_pct": 0.01, "max_total_open_risk_pct": 0.02},
    {"min_closed_active_equity_eur": 300_000.0, "max_simultaneous_trades": 3, "risk_per_slot_pct": 0.01, "max_total_open_risk_pct": 0.03},
    {"min_closed_active_equity_eur": 500_000.0, "max_simultaneous_trades": 5, "risk_per_slot_pct": 0.01, "max_total_open_risk_pct": 0.05},
)

STATUS_GREEN = "GREEN"
STATUS_YELLOW = "YELLOW"
STATUS_RED = "RED"

SYMBOLS: tuple[str, ...] = (
    "ADAUSDT",
    "LINKUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "AVAXUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "BTCUSDT",
    "SOLUSDT",
)

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "paper_validation_ready": False,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "private_endpoint_used": False,
    "signed_endpoint_used": False,
    "account_endpoint_used": False,
    "order_endpoint_used": False,
    "broker_path_created": False,
    "order_path_created": False,
    "strategy_logic_changed": False,
    "thresholds_tuned": False,
    "entries_changed": False,
    "exits_changed": False,
    "sizing_changed": False,
    "data_storage_modified": False,
    "btc_scheduler_replaced": False,
    "multi_symbol_scheduler_installed": False,
}

FetchFunction = Callable[[str, pd.Timestamp, pd.Timestamp], pd.DataFrame]


@dataclass(frozen=True)
class MultiSymbolForwardRuntimeConfig:
    project_root: Path
    package_root: Path
    data_root: Path
    reduced_cap_root: Path
    output_root: Path
    now_utc: datetime | None = None
    fetch_function: FetchFunction | None = None
    seed_tail_rows: int = 43200
    max_catchup_minutes: int = 10080
    throttle_seconds: float = 0.05


def default_config() -> MultiSymbolForwardRuntimeConfig:
    root = project_root()
    pkg = package_root()
    return MultiSymbolForwardRuntimeConfig(
        project_root=root,
        package_root=pkg,
        data_root=root / "data_storage",
        reduced_cap_root=pkg / "output" / "multi_symbol_btc_exact_fill_cap_calibration_court_001",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
    )


def _now(config: MultiSymbolForwardRuntimeConfig) -> datetime:
    value = config.now_utc or datetime.now(timezone.utc)
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _latest_safe_1m_timestamp(config: MultiSymbolForwardRuntimeConfig) -> pd.Timestamp:
    current_minute = _now(config).astimezone(timezone.utc).replace(second=0, microsecond=0)
    return pd.Timestamp(current_minute - pd.Timedelta(minutes=2)).tz_convert(None)


def _round_payload(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _round_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_payload(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_round_payload(payload), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return "" if math.isnan(value) or math.isinf(value) else round(value, 10)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is None:
        return ""
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in keys})


def _append_csv(path: Path, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    existing_keys: list[str] | None = None
    if path.exists() and path.stat().st_size > 0:
        with path.open(newline="", encoding="utf-8") as handle:
            existing_keys = next(csv.reader(handle), None)
    fieldnames = existing_keys or keys
    if existing_keys is not None and any(key not in existing_keys for key in keys):
        fieldnames = sorted(set(existing_keys).union(keys))
        old_rows: list[dict[str, Any]] = []
        with path.open(newline="", encoding="utf-8") as handle:
            old_rows = list(csv.DictReader(handle))
        _write_csv(path, old_rows + rows)
        return len(rows)
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if existing_keys is None:
            writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in fieldnames})
    return len(rows)


def _paths(output_root: Path) -> dict[str, Path]:
    return {
        "status": output_root / "latest_status.json",
        "checkpoint": output_root / "checkpoints" / "multi_symbol_forward_runtime_checkpoint.json",
        "decision_ledger": output_root / "ledger" / "multi_symbol_forward_decision_ledger.csv",
        "strategy_selected_trades": output_root / "ledger" / "forward_strategy_selected_trades.csv",
        "strategy_rejected_trades": output_root / "ledger" / "forward_strategy_rejected_trades.csv",
        "strategy_all_candidates": output_root / "ledger" / "forward_strategy_all_symbol_candidates.csv",
        "strategy_summary": output_root / "diagnostics" / "strategy_evaluator_summary.json",
        "allocator_state": output_root / "ledger" / "earned_parallel_slot_allocator_state.json",
        "symbol_quality": output_root / "diagnostics" / "symbol_quality_latest.json",
        "catchup_report": output_root / "diagnostics" / "catchup_report.json",
        "idempotency": output_root / "diagnostics" / "idempotency_report.json",
        "trade_event_email_ledger": output_root / "alerts" / "multi_asset_trade_events" / "multi_asset_trade_event_email_ledger.csv",
        "daily_no_trade_email_ledger": output_root / "alerts" / "daily_no_trade_digest" / "daily_no_trade_email_ledger.csv",
        "historical_warm_start_manifest": output_root / "checkpoints" / "historical_warm_start_manifest.json",
        "lock": output_root / "runtime.lock",
    }


def _ensure_dirs(output_root: Path) -> None:
    for folder in (
        output_root,
        output_root / "checkpoints",
        output_root / "ledger",
        output_root / "diagnostics",
        output_root / "diagnostics" / "raw_fetch_chunks",
        output_root / "symbol_runtime_snapshots",
        output_root / "alerts",
        output_root / "alerts" / "multi_asset_trade_events",
        output_root / "alerts" / "daily_no_trade_digest",
    ):
        folder.mkdir(parents=True, exist_ok=True)


def _source_csv_for_symbol(config: MultiSymbolForwardRuntimeConfig, symbol: str) -> Path | None:
    candidates = sorted((config.data_root / symbol / "1m").glob(f"{symbol}_1m_*.csv"))
    if symbol == "BTCUSDT":
        canonical = (
            config.package_root
            / "data_storage"
            / "BTCUSDT"
            / "1m"
            / "btcusdt_1m_canonical_shadow_forward.csv"
        )
        if canonical.exists():
            candidates.append(canonical)
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_size)


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame is None or frame.empty:
        return pd.DataFrame(
            {
                "timestamp": pd.Series(dtype="datetime64[ns]"),
                "open": pd.Series(dtype="float64"),
                "high": pd.Series(dtype="float64"),
                "low": pd.Series(dtype="float64"),
                "close": pd.Series(dtype="float64"),
                "volume": pd.Series(dtype="float64"),
            }
        )
    renamed = frame.rename(columns={column: column.lower().strip() for column in frame.columns})
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in renamed.columns]
    if missing:
        raise ValueError(f"missing required columns: {missing}")
    working = renamed[required].copy()
    working["timestamp"] = pd.to_datetime(working["timestamp"], utc=True, errors="coerce").dt.tz_convert(None)
    for column in ["open", "high", "low", "close", "volume"]:
        working[column] = pd.to_numeric(working[column], errors="coerce")
    return working.dropna(subset=required).drop_duplicates("timestamp", keep="last").sort_values("timestamp").reset_index(drop=True)


def _tail_frame(path: Path, max_rows: int) -> pd.DataFrame:
    rows: list[dict[str, str]]
    with path.open(newline="", encoding="utf-8") as handle:
        from collections import deque

        rows = list(deque(csv.DictReader(handle), maxlen=max_rows))
    return _normalize_frame(pd.DataFrame(rows))


def _runtime_copy_path(output_root: Path, symbol: str) -> Path:
    return output_root / "symbol_runtime_snapshots" / symbol / "runtime_1m_copy.csv"


def _load_or_seed_runtime_copy(config: MultiSymbolForwardRuntimeConfig, symbol: str) -> tuple[pd.DataFrame, Path | None, bool]:
    runtime_path = _runtime_copy_path(config.output_root, symbol)
    if runtime_path.exists():
        return _normalize_frame(pd.read_csv(runtime_path)), None, False
    source_csv = _source_csv_for_symbol(config, symbol)
    if source_csv is None:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"]), None, False
    seeded = _tail_frame(source_csv, config.seed_tail_rows)
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    seeded.to_csv(runtime_path, index=False)
    return seeded, source_csv, True


def _quality(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {
            "rows": 0,
            "first_timestamp": None,
            "last_timestamp": None,
            "gap_count": 0,
            "missing_minutes": 0,
            "duplicate_count": 0,
            "ohlc_failure_count": 0,
            "complete_15m_bars": 0,
            "complete_1h_bars": 0,
            "complete_6h_context_bars": 0,
            "clean": False,
        }
    timestamps = frame["timestamp"].sort_values().reset_index(drop=True)
    diffs = timestamps.diff().dropna()
    gap_diffs = diffs[diffs > pd.Timedelta(minutes=1)]
    missing = int(sum(int(diff / pd.Timedelta(minutes=1)) - 1 for diff in gap_diffs))
    duplicate_count = int(frame["timestamp"].duplicated().sum())
    ohlc_failures = frame[
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        | (frame["high"] < frame["low"])
        | (frame["open"] <= 0)
        | (frame["high"] <= 0)
        | (frame["low"] <= 0)
        | (frame["close"] <= 0)
        | (frame["volume"] < 0)
    ]
    complete_15m = _resample_complete(frame, "15min", 15)
    complete_1h = _resample_complete(frame, "1h", 60)
    complete_6h_context = _resample_complete_6h_context(frame)
    return {
        "rows": int(len(frame)),
        "first_timestamp": timestamps.iloc[0].isoformat(),
        "last_timestamp": timestamps.iloc[-1].isoformat(),
        "gap_count": int(len(gap_diffs)),
        "missing_minutes": missing,
        "duplicate_count": duplicate_count,
        "ohlc_failure_count": int(len(ohlc_failures)),
        "complete_15m_bars": int(len(complete_15m)),
        "complete_1h_bars": int(len(complete_1h)),
        "complete_6h_context_bars": int(len(complete_6h_context)),
        "clean": bool(len(gap_diffs) == 0 and missing == 0 and duplicate_count == 0 and len(ohlc_failures) == 0),
    }


def _resample_complete(frame: pd.DataFrame, rule: str, expected: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    bars = (
        frame.set_index("timestamp")
        .sort_index()
        .resample(rule, label="left", closed="left")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            source_1m_count=("close", "count"),
        )
    )
    return bars[bars["source_1m_count"] == expected].dropna(subset=["open", "high", "low", "close"]).reset_index()


def _augment_6h_context_frame(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    working = frame.copy().sort_values("timestamp").reset_index(drop=True)
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
    working["ema20"] = working["close"].ewm(span=20, adjust=False).mean()
    working["ema50"] = working["close"].ewm(span=50, adjust=False).mean()
    working["ema20_slope"] = working["ema20"].diff()
    working["ema50_slope"] = working["ema50"].diff()
    working["recent_high_20"] = working["high"].rolling(20, min_periods=5).max()
    working["recent_low_20"] = working["low"].rolling(20, min_periods=5).min()
    return working


def _resample_complete_6h_context(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    bars = (
        frame.set_index("timestamp")
        .sort_index()
        .resample("6h", label="right", closed="left")
        .agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            source_1m_count=("close", "count"),
        )
    )
    complete = bars[bars["source_1m_count"] == 360].dropna(subset=["open", "high", "low", "close"]).reset_index()
    return _augment_6h_context_frame(complete)


def _six_h_trend_state(candle: pd.Series) -> str:
    close = _float_or_none(candle.get("close")) or 0.0
    ema20 = _float_or_none(candle.get("ema20")) or 0.0
    ema50 = _float_or_none(candle.get("ema50")) or 0.0
    slope20 = _float_or_none(candle.get("ema20_slope")) or 0.0
    slope50 = _float_or_none(candle.get("ema50_slope")) or 0.0
    if close > ema20 and ema20 >= ema50 and slope20 >= 0.0 and slope50 >= 0.0:
        return "bullish"
    if close < ema20 and ema20 <= ema50 and slope20 <= 0.0 and slope50 <= 0.0:
        return "bearish"
    return "neutral"


def _six_h_structure_state(window: pd.DataFrame) -> str:
    if len(window) < 4:
        return "unknown"
    highs = window["high"].tail(4).tolist()
    lows = window["low"].tail(4).tolist()
    if highs[-1] > highs[-2] > highs[-3] and lows[-1] > lows[-2] > lows[-3]:
        return "higher_high_higher_low"
    if highs[-1] < highs[-2] < highs[-3] and lows[-1] < lows[-2] < lows[-3]:
        return "lower_high_lower_low"
    return "mixed"


def _label_six_h_context(row: dict[str, Any], frame_6h: pd.DataFrame) -> dict[str, Any]:
    if frame_6h.empty:
        return {
            "six_h_label_available": False,
            "six_h_unavailable_reason": "no_complete_6h_bars",
            "six_h_context_only": True,
            "native_6h_execution_enabled": False,
        }
    entry_ts = pd.Timestamp(row.get("entry_timestamp") or row.get("entry_time"))
    if entry_ts.tzinfo is not None:
        entry_ts = entry_ts.tz_convert("UTC").tz_localize(None)
    eligible = frame_6h[frame_6h["timestamp"] <= entry_ts]
    if eligible.empty:
        return {
            "six_h_label_available": False,
            "six_h_unavailable_reason": "no_prior_closed_6h_context_bar",
            "six_h_context_only": True,
            "native_6h_execution_enabled": False,
        }
    context = eligible.iloc[-1]
    window = eligible.tail(24)
    side = str(row.get("side") or "").strip().lower()
    entry = _float_or_none(row.get("entry_price")) or 0.0
    stop = _float_or_none(row.get("initial_stop")) or 0.0
    trend = _six_h_trend_state(context)
    structure = _six_h_structure_state(window)
    supply = _float_or_none(context.get("recent_high_20")) or 0.0
    demand = _float_or_none(context.get("recent_low_20")) or 0.0
    risk_distance = max(abs(entry - stop), 1e-9)
    room_distance = (supply - entry) if side == "long" else (entry - demand)
    room_r = max(room_distance, 0.0) / risk_distance
    alignment = (side == "long" and trend == "bullish") or (side == "short" and trend == "bearish")
    alignment = alignment or (side == "long" and structure == "higher_high_higher_low")
    alignment = alignment or (side == "short" and structure == "lower_high_lower_low")
    if side == "long":
        conflict = trend == "bearish" or (supply > 0.0 and (supply - entry) / max(entry, 1e-9) <= 0.02)
    elif side == "short":
        conflict = trend == "bullish" or (demand > 0.0 and (entry - demand) / max(entry, 1e-9) <= 0.02)
    else:
        conflict = False
    insufficient_room = room_r < 1.50
    boost = bool(alignment and not conflict and not insufficient_room)
    return {
        "six_h_label_available": True,
        "six_h_context_candle_close_timestamp": pd.Timestamp(context["timestamp"]).isoformat(),
        "six_h_trend_state": trend,
        "six_h_structure_state": structure,
        "six_h_alignment": bool(alignment),
        "six_h_conflict": bool(conflict),
        "six_h_room_to_target_r": round(room_r, 6),
        "six_h_insufficient_room": bool(insufficient_room),
        "six_h_clean_confluence": boost,
        "six_h_context_variant": ACTIVE_6H_CONTEXT_VARIANT,
        "six_h_context_scale_multiplier": ACTIVE_6H_CONTEXT_BOOST_MULTIPLIER if boost else 1.0,
        "six_h_context_only": True,
        "native_6h_execution_enabled": False,
    }


def _apply_six_h_context_overlay(candidates: list[dict[str, Any]], frames_by_symbol: dict[str, pd.DataFrame]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    available = 0
    boosted = 0
    for row in candidates:
        symbol = str(row.get("symbol") or "")
        label = _label_six_h_context(row, frames_by_symbol.get(symbol, pd.DataFrame()))
        cloned = dict(row)
        original_net_r = _float_or_none(cloned.get("net_r")) or 0.0
        multiplier = float(label.get("six_h_context_scale_multiplier") or 1.0)
        cloned.update(label)
        cloned["original_net_r_before_6h_context"] = original_net_r
        cloned["net_r"] = round(original_net_r * multiplier, 10)
        cloned["six_h_context_overlay_court"] = ACTIVE_6H_CONTEXT_OVERLAY_COURT
        cloned["six_h_context_overlay_classification"] = ACTIVE_6H_CONTEXT_OVERLAY_CLASSIFICATION
        cloned["entries_changed"] = False
        cloned["exits_changed"] = False
        cloned["thresholds_tuned"] = False
        cloned["native_6h_execution_enabled"] = False
        available += int(bool(label.get("six_h_label_available")))
        boosted += int(multiplier != 1.0)
        adjusted.append(cloned)
    return adjusted, {
        "six_h_context_overlay_enabled": True,
        "six_h_context_overlay_court": ACTIVE_6H_CONTEXT_OVERLAY_COURT,
        "six_h_context_overlay_classification": ACTIVE_6H_CONTEXT_OVERLAY_CLASSIFICATION,
        "six_h_context_variant": ACTIVE_6H_CONTEXT_VARIANT,
        "six_h_context_boost_multiplier": ACTIVE_6H_CONTEXT_BOOST_MULTIPLIER,
        "candidate_rows": len(candidates),
        "six_h_label_available_rows": available,
        "six_h_boosted_rows": boosted,
        "six_h_label_coverage_pct": _safe_ratio(available, len(candidates), 0.0) * 100.0,
        "execution_timeframe": "1H",
        "context_timeframe": "6H",
        "native_6h_execution_enabled": False,
        "entries_changed": False,
        "exits_changed": False,
        "thresholds_tuned": False,
    }


def _default_fetch(config: MultiSymbolForwardRuntimeConfig, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    raw, _ = _public_fetch_binance_1m(
        config=AppConfig.load(),
        symbol=symbol,
        start_timestamp=start,
        end_timestamp=end,
        raw_chunk_root=config.output_root / "diagnostics" / "raw_fetch_chunks" / symbol,
    )
    normalized, _ = _normalize_fetched_rows(raw, fetch_start=start, latest_safe=end)
    return normalized[["timestamp", "open", "high", "low", "close", "volume"]].copy()


def _fetch_symbol(config: MultiSymbolForwardRuntimeConfig, symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    if config.fetch_function is not None:
        return _normalize_frame(config.fetch_function(symbol, start, end))
    return _normalize_frame(_default_fetch(config, symbol, start, end))


def _allocator_spec_metadata() -> dict[str, Any]:
    return {
        "allocator_spec_id": EARNED_PARALLEL_SLOT_SPEC_ID,
        "allocator_freeze_classification": EARNED_PARALLEL_SLOT_FREEZE_CLASSIFICATION,
        "active_multi_symbol_universe_id": ACTIVE_MULTI_SYMBOL_UNIVERSE_ID,
        "active_multi_symbol_freeze_court": ACTIVE_MULTI_SYMBOL_FREEZE_COURT,
        "active_multi_symbol_freeze_note": ACTIVE_MULTI_SYMBOL_FREEZE_NOTE,
        "active_symbols": list(SYMBOLS),
        "active_symbol_count": len(SYMBOLS),
        "allocator_research_only": True,
        "allocator_ladder": list(EARNED_PARALLEL_SLOT_LADDER),
        "allocator_unlock_basis": "closed_active_equity_only_not_floating_pnl",
        "allocator_one_open_trade_per_symbol": True,
        "allocator_fill_calibrated_symbol_caps_required": True,
        "allocator_strategy_entries_changed": False,
        "allocator_strategy_exits_changed": False,
        "allocator_thresholds_tuned": False,
        "allocator_paper_live_order_broker_enabled": False,
        "six_h_context_overlay_enabled": True,
        "six_h_context_overlay_court": ACTIVE_6H_CONTEXT_OVERLAY_COURT,
        "six_h_context_overlay_classification": ACTIVE_6H_CONTEXT_OVERLAY_CLASSIFICATION,
        "six_h_context_variant": ACTIVE_6H_CONTEXT_VARIANT,
        "six_h_context_boost_multiplier": ACTIVE_6H_CONTEXT_BOOST_MULTIPLIER,
        "six_h_context_only": True,
        "native_6h_execution_enabled": False,
        "execution_timeframe": "1H",
        "context_timeframe": "6H",
    }


def _decision_rows(
    symbol: str,
    complete_1h: pd.DataFrame,
    existing_keys: set[str],
    *,
    decision_start: pd.Timestamp | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    allocator_metadata = _allocator_spec_metadata()
    for _, row in complete_1h.iterrows():
        slot = pd.Timestamp(row["timestamp"])
        if slot.tzinfo is not None:
            slot = slot.tz_convert("UTC").tz_localize(None)
        if decision_start is not None and slot < decision_start:
            continue
        key = f"{symbol}|{slot.isoformat()}"
        if key in existing_keys:
            continue
        rows.append(
            {
                "decision_key": key,
                "symbol": symbol,
                "decision_slot": slot.isoformat(),
                "closed_1h_candle_start": slot.isoformat(),
                "closed_1h_candle_end": (slot + pd.Timedelta(minutes=59)).isoformat(),
                "source_1m_count": int(row["source_1m_count"]),
                "closed_1h_decision_slot_processed": True,
                "historical_warm_start_context_only": False,
                "decision_start_cutoff": decision_start.isoformat() if decision_start is not None else "",
                "strategy_signal_evaluated": False,
                "scanner_selection_evaluated": False,
                "allocator_spec_id": EARNED_PARALLEL_SLOT_SPEC_ID,
                "six_h_context_overlay_court": ACTIVE_6H_CONTEXT_OVERLAY_COURT,
                "six_h_context_variant": ACTIVE_6H_CONTEXT_VARIANT,
                "six_h_context_only": True,
                "native_6h_execution_enabled": False,
                "allocator_max_slots_active": "",
                "allocator_slot_action": "candle_slot_recorded_no_trade_signal",
                "reason": "earned_parallel_slot_runtime_candle_decision_slot_only_no_strategy_or_execution_change",
                "paper_trade_created": False,
                "live_trade_created": False,
                "order_created": False,
                "broker_path_used": False,
                **{key: json.dumps(value) if key == "allocator_ladder" else value for key, value in allocator_metadata.items()},
            }
        )
    return rows


def _runtime_strategy_config(*, analysis_start: str, analysis_end: str) -> StructuralLabConfig:
    base = StructuralLabConfig.load()
    payload = copy.deepcopy(base.data)
    payload["base_capital"] = START_CAPITAL
    payload["data"]["analysis_start_date"] = analysis_start
    payload["data"]["analysis_end_date"] = analysis_end
    payload["engine"]["resume_enabled"] = False
    payload["engine"]["checkpoint_every_bars"] = 0
    payload["engine"]["write_partial_artifacts"] = False
    return StructuralLabConfig(data=payload, config_path=base.config_path, root_dir=base.root_dir)


def _read_raw_rows(root: Path, filename: str) -> list[dict[str, Any]]:
    path = root / filename
    if not path.exists() or path.stat().st_size == 0:
        return []
    return _read_csv_rows(path)


def _iso(value: Any) -> str:
    if value in {None, ""}:
        return ""
    try:
        timestamp = pd.Timestamp(value)
        if timestamp.tzinfo is not None:
            timestamp = timestamp.tz_convert("UTC")
        return timestamp.isoformat()
    except Exception:
        return str(value)


def _float_or_none(value: Any) -> float | None:
    try:
        if value in {None, ""}:
            return None
        parsed = float(value)
    except Exception:
        return None
    if math.isnan(parsed) or math.isinf(parsed):
        return None
    return parsed


def _position_notional_eur(trade: dict[str, Any], candidate: dict[str, Any]) -> str:
    existing = _float_or_none(trade.get("position_notional_eur") or trade.get("amount_bought_eur"))
    if existing is not None:
        return f"{existing:.2f}"
    risk = _float_or_none(trade.get("risk_eur"))
    stop_fraction = _float_or_none(candidate.get("stop_distance_fraction"))
    if risk is None or stop_fraction is None or stop_fraction <= 0:
        return ""
    return f"{risk / stop_fraction:.2f}"


def _trade_signature(row: dict[str, Any]) -> str:
    return "|".join(
        [
            str(row.get("symbol") or ""),
            str(row.get("trade_id") or ""),
            _iso(row.get("entry_timestamp") or row.get("entry_time")),
            _iso(row.get("exit_timestamp") or row.get("exit_time")),
        ]
    )


def _load_priority_symbols(config: MultiSymbolForwardRuntimeConfig) -> list[str]:
    path = config.package_root / "output" / ACTIVE_MULTI_SYMBOL_FREEZE_COURT / "multi_asset_earned_parallel_slot_btc_inclusion_summary.json"
    payload = _read_json(path, {})
    best_policy = str(payload.get("best_btc_policy") or "")
    priority = list((payload.get("comparisons") or {}).get(best_policy, {}).get("priority_symbols") or [])
    return priority if set(priority) == set(SYMBOLS) else list(SYMBOLS)


def _load_symbol_caps(config: MultiSymbolForwardRuntimeConfig) -> dict[str, float]:
    for filename in (
        "nine_symbol_recommended_symbol_caps_manifest.json",
        "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json",
    ):
        payload = _read_json(config.reduced_cap_root / filename, {})
        caps = payload.get("recommended_symbol_caps_eur") or {}
        if set(caps) >= set(SYMBOLS):
            return {str(symbol): float(value) for symbol, value in caps.items()}
    return {}


def _evaluate_symbol_strategy(
    config: MultiSymbolForwardRuntimeConfig,
    symbol: str,
    runtime_path: Path,
) -> dict[str, Any]:
    frame = _normalize_frame(pd.read_csv(runtime_path)) if runtime_path.exists() else _normalize_frame(pd.DataFrame())
    symbol_eval_root = config.output_root / "diagnostics" / "strategy_evaluator" / symbol
    raw_engine_root = symbol_eval_root / "raw_engine"
    if frame.empty:
        return {
            "symbol": symbol,
            "blocked": True,
            "block_reason": "empty_runtime_copy",
            "candidate_rows": [],
            "cost_rejected_rows": [],
            "summary": {"symbol": symbol, "blocked": True, "block_reason": "empty_runtime_copy"},
        }
    analysis_start = pd.Timestamp(frame["timestamp"].min()).isoformat()
    analysis_end = pd.Timestamp(frame["timestamp"].max()).isoformat()
    raw_summary = StructuralBacktestEngine(
        config=_runtime_strategy_config(analysis_start=analysis_start, analysis_end=analysis_end)
    ).run(symbol=symbol, source_csv=str(runtime_path), output_dir=str(raw_engine_root))
    normalized = _normalize_trade_rows(
        _read_raw_rows(raw_engine_root, "trades.csv"),
        _read_raw_rows(raw_engine_root, "setup_log.csv"),
        _read_raw_rows(raw_engine_root, "level_log.csv"),
        _read_raw_rows(raw_engine_root, "liquidity_events.csv"),
    )
    prepared = _prepare_rows(normalized) if normalized else []
    rules_path = config.package_root / "output" / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json"
    matched_shorts, disabled_longs, rules_payload = _load_frozen_rules(rules_path)
    selected, removed = _apply_frozen_patch(
        prepared,
        matched_short_archetypes=matched_shorts,
        disabled_long_modes=disabled_longs,
    )
    cost_candidate_rows, cost_rejected = _candidate_rows(selected, net_cost_bps=ROUND_TRIP_COST_BPS)
    for row in cost_candidate_rows:
        row["symbol"] = symbol
    for row in cost_rejected:
        row["symbol"] = symbol
    _write_replay_csv(symbol_eval_root / "cost_aware_candidate_trades.csv", cost_candidate_rows)
    _write_replay_csv(symbol_eval_root / "cost_guard_rejected_trades.csv", cost_rejected)
    _write_replay_csv(symbol_eval_root / "frozen_rule_removed_trades.csv", removed)
    summary = {
        "symbol": symbol,
        "blocked": False,
        "runtime_copy": str(runtime_path),
        "analysis_start": analysis_start,
        "analysis_end": analysis_end,
        "raw_engine_run_state": raw_summary.get("run_state"),
        "raw_engine_trade_count": raw_summary.get("trade_count"),
        "raw_prepared_trade_count": len(prepared),
        "frozen_rules_loaded": bool(rules_payload),
        "frozen_rule_selected_count": len(selected),
        "frozen_rule_removed_count": len(removed),
        "cost_candidate_name": CANDIDATE_NAME,
        "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
        "max_pre_entry_cost_r": MAX_PRE_ENTRY_COST_R,
        "cost_accepted_count": len(cost_candidate_rows),
        "cost_rejected_count": len(cost_rejected),
        "strategy_signal_evaluated": True,
        "scanner_selection_evaluated": True,
        **SAFETY_FLAGS,
    }
    _write_json(symbol_eval_root / "strategy_evaluator_symbol_summary.json", summary)
    return {
        "symbol": symbol,
        "blocked": False,
        "block_reason": "",
        "candidate_rows": cost_candidate_rows,
        "cost_rejected_rows": cost_rejected,
        "summary": summary,
    }


def _strategy_event_rows(
    selected_trade_rows: list[dict[str, Any]],
    candidate_by_signature: dict[str, dict[str, Any]],
    existing_keys: set[str],
    decision_start_by_symbol: dict[str, pd.Timestamp] | None = None,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    allocator_metadata = _allocator_spec_metadata()
    decision_start_by_symbol = decision_start_by_symbol or {}
    for trade in selected_trade_rows:
        signature = _trade_signature(trade)
        candidate = candidate_by_signature.get(signature, {})
        symbol = str(trade.get("symbol") or candidate.get("symbol") or "")
        trade_id = str(trade.get("trade_id") or candidate.get("trade_id") or "")
        entry_time = _iso(trade.get("entry_time") or candidate.get("entry_time") or candidate.get("entry_timestamp"))
        exit_time = _iso(trade.get("exit_time") or candidate.get("exit_time") or candidate.get("exit_timestamp"))
        decision_start = decision_start_by_symbol.get(symbol)
        decision_start_text = decision_start.isoformat() if decision_start is not None else ""
        position_notional_eur = _position_notional_eur(trade, candidate)
        common = {
            "symbol": symbol,
            "trade_id": trade_id,
            "side": trade.get("side") or candidate.get("side"),
            "direction": trade.get("side") or candidate.get("side"),
            "spot_compatible_long_only": SPOT_COMPATIBLE_LONG_ONLY,
            "short_selling_allowed": SHORT_SELLING_ALLOWED,
            "strategy_signal_evaluated": True,
            "scanner_selection_evaluated": True,
            "scanner_selected": True,
            "trade_triggered": True,
            "setup_accepted": True,
            "allocator_slot_action": "frozen_strategy_scanner_selected_research_trade",
            "allocator_spec_id": EARNED_PARALLEL_SLOT_SPEC_ID,
            "paper_trade_created": False,
            "live_trade_created": False,
            "order_created": False,
            "broker_path_used": False,
            "paper_validation_ready": False,
            "live_allowed": False,
            "real_money_allowed": False,
            "order_path_created": False,
            "broker_path_created": False,
            "entry_price": candidate.get("entry_price", ""),
            "exit_price": candidate.get("exit_price", ""),
            "initial_stop": candidate.get("initial_stop", ""),
            "net_r": trade.get("net_r", candidate.get("net_r", "")),
            "net_cost_r": trade.get("net_cost_r", candidate.get("net_cost_r", "")),
            "risk_eur": trade.get("risk_eur", ""),
            "amount_bought_eur": position_notional_eur,
            "position_notional_eur": position_notional_eur,
            "active_equity_before_exit_eur": trade.get("active_before_exit", ""),
            "active_equity_after_exit_eur": trade.get("active_after_exit", ""),
            "total_equity_after_exit_before_tax_eur": trade.get("total_after_exit_before_year_tax", ""),
            "active_equity_reference_eur": trade.get("active_before_exit", ""),
            "pnl_eur": trade.get("pnl_eur", ""),
            "net_pnl_eur": trade.get("pnl_eur", ""),
            "estimated_cost_eur": "",
            "setup_class": candidate.get("setup_class", ""),
            "convexity_label": candidate.get("convexity_label", ""),
            "personality_label": candidate.get("personality_label", ""),
            "runner_label": candidate.get("runner_label", ""),
            "symbol_cap_eur": trade.get("symbol_cap_eur", ""),
            "concurrent_slots_at_entry": trade.get("concurrent_slots_at_entry", ""),
            "max_slots_at_entry": trade.get("max_slots_at_entry", ""),
            "six_h_context_overlay_enabled": True,
            "six_h_context_overlay_court": candidate.get("six_h_context_overlay_court", ACTIVE_6H_CONTEXT_OVERLAY_COURT),
            "six_h_context_overlay_classification": candidate.get(
                "six_h_context_overlay_classification",
                ACTIVE_6H_CONTEXT_OVERLAY_CLASSIFICATION,
            ),
            "six_h_context_variant": candidate.get("six_h_context_variant", ACTIVE_6H_CONTEXT_VARIANT),
            "six_h_context_scale_multiplier": candidate.get("six_h_context_scale_multiplier", ""),
            "six_h_label_available": candidate.get("six_h_label_available", ""),
            "six_h_unavailable_reason": candidate.get("six_h_unavailable_reason", ""),
            "six_h_context_candle_close_timestamp": candidate.get("six_h_context_candle_close_timestamp", ""),
            "six_h_trend_state": candidate.get("six_h_trend_state", ""),
            "six_h_structure_state": candidate.get("six_h_structure_state", ""),
            "six_h_alignment": candidate.get("six_h_alignment", ""),
            "six_h_conflict": candidate.get("six_h_conflict", ""),
            "six_h_room_to_target_r": candidate.get("six_h_room_to_target_r", ""),
            "six_h_insufficient_room": candidate.get("six_h_insufficient_room", ""),
            "six_h_clean_confluence": candidate.get("six_h_clean_confluence", ""),
            "six_h_context_only": True,
            "native_6h_execution_enabled": False,
            "original_net_r_before_6h_context": candidate.get("original_net_r_before_6h_context", ""),
            "net_r_after_6h_context": trade.get("net_r", candidate.get("net_r", "")),
            "entries_changed": False,
            "exits_changed": False,
            "thresholds_tuned": False,
            **{key: json.dumps(value) if key == "allocator_ladder" else value for key, value in allocator_metadata.items()},
        }
        for event_type, event_time in (("ENTRY", entry_time), ("EXIT", exit_time)):
            key = f"FORWARD_STRATEGY_{event_type}|{symbol}|{trade_id}|{event_time}"
            if not event_time or key in existing_keys:
                continue
            row = {
                **common,
                "decision_key": key,
                "event_type": event_type,
                "decision_slot": event_time,
                "closed_1h_candle_start": event_time,
                "closed_1h_candle_end": event_time,
                "source_1m_count": "",
                "closed_1h_decision_slot_processed": True,
                "historical_warm_start_context_only": False,
                "decision_start_cutoff": decision_start_text,
                "entry_time": entry_time,
                "exit_time": exit_time if event_type == "EXIT" else "",
                "total_equity_after_event_eur": trade.get("total_after_exit_before_year_tax", "") if event_type == "EXIT" else trade.get("active_before_exit", ""),
                "active_equity_after_event_eur": trade.get("active_after_exit", "") if event_type == "EXIT" else trade.get("active_before_exit", ""),
                "reason": "frozen_strategy_scanner_selected_entry_research_only" if event_type == "ENTRY" else "frozen_strategy_scanner_selected_exit_research_only",
                "entry_reason": candidate.get("entry_reason", "frozen_strategy_selected_research_entry"),
                "exit_reason": "closed_trade_research_exit" if event_type == "EXIT" else "",
            }
            rows.append(row)
            existing_keys.add(key)
    return rows


def _candidate_timestamp(row: dict[str, Any]) -> pd.Timestamp | None:
    for key in ("entry_timestamp", "entry_time", "timestamp", "decision_slot"):
        value = row.get(key)
        if value in (None, ""):
            continue
        parsed = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(parsed):
            continue
        stamp = pd.Timestamp(parsed)
        if stamp.tzinfo is not None:
            stamp = stamp.tz_convert("UTC").tz_localize(None)
        return stamp
    return None


def _is_at_or_after_decision_start(row: dict[str, Any], decision_start_by_symbol: dict[str, pd.Timestamp]) -> bool:
    symbol = str(row.get("symbol") or "")
    decision_start = decision_start_by_symbol.get(symbol)
    if decision_start is None:
        return True
    timestamp = _candidate_timestamp(row)
    if timestamp is None:
        return False
    return timestamp >= decision_start


def _evaluate_forward_strategy_events(
    config: MultiSymbolForwardRuntimeConfig,
    symbol_results: list[dict[str, Any]],
    existing_keys: set[str],
    decision_start_by_symbol: dict[str, pd.Timestamp] | None = None,
) -> dict[str, Any]:
    priority_symbols = _load_priority_symbols(config)
    symbol_caps = _load_symbol_caps(config)
    decision_start_by_symbol = decision_start_by_symbol or {}
    symbol_eval_results: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    cost_rejected: list[dict[str, Any]] = []
    frames_6h_by_symbol: dict[str, pd.DataFrame] = {}
    for result in symbol_results:
        symbol = str(result.get("symbol") or "")
        if not symbol:
            continue
        runtime_path = _runtime_copy_path(config.output_root, symbol)
        if runtime_path.exists():
            frame = _normalize_frame(pd.read_csv(runtime_path))
            six_h_context = _resample_complete_6h_context(frame)
            six_h_context.to_csv(runtime_path.parent / "complete_6h_context_bars.csv", index=False)
            frames_6h_by_symbol[symbol] = six_h_context
        else:
            frames_6h_by_symbol[symbol] = pd.DataFrame()
        eval_result = _evaluate_symbol_strategy(config, symbol, runtime_path)
        symbol_eval_results.append(eval_result["summary"])
        candidates.extend(eval_result.get("candidate_rows", []))
        cost_rejected.extend(eval_result.get("cost_rejected_rows", []))
    pre_activation_candidates = [
        row for row in candidates if not _is_at_or_after_decision_start(row, decision_start_by_symbol)
    ]
    pre_activation_cost_rejected = [
        row for row in cost_rejected if not _is_at_or_after_decision_start(row, decision_start_by_symbol)
    ]
    if decision_start_by_symbol:
        candidates = [row for row in candidates if _is_at_or_after_decision_start(row, decision_start_by_symbol)]
        cost_rejected = [row for row in cost_rejected if _is_at_or_after_decision_start(row, decision_start_by_symbol)]
    candidates = sorted(
        candidates,
        key=lambda row: (
            pd.Timestamp(row.get("entry_timestamp") or row.get("entry_time")),
            priority_symbols.index(str(row.get("symbol"))) if str(row.get("symbol")) in priority_symbols else 999,
            str(row.get("trade_id") or ""),
        ),
    )
    short_rejected_for_spot = [
        {
            **row,
            "candidate_guard_accepted": False,
            "candidate_guard_reason": "spot_long_only_runtime_rejects_short_selling",
            "spot_compatible_long_only": True,
            "short_selling_allowed": False,
            "no_synthetic_trade_inserted": True,
        }
        for row in candidates
        if str(row.get("side") or "").strip().lower() == "short"
    ]
    if SPOT_COMPATIBLE_LONG_ONLY:
        candidates = [row for row in candidates if str(row.get("side") or "").strip().lower() != "short"]
    candidates_before_6h_context = [dict(row) for row in candidates]
    candidates, six_h_context_summary = _apply_six_h_context_overlay(candidates, frames_6h_by_symbol)
    if candidates:
        portfolio = _earned_slot_replay(
            candidates,
            scenario_id="forward_runtime_research_only:user_literal_1pct_each_slot",
            period="forward_runtime",
            priority_symbols=priority_symbols,
            symbol_caps=symbol_caps,
            ladder=USER_LITERAL_SLOT_LADDER,
            active_cap=ACTIVE_CAP,
            tax_rate=TAX_RESERVE_RATE,
        )
    else:
        portfolio = {
            "scenario_id": "forward_runtime_research_only:user_literal_1pct_each_slot",
            "period": "forward_runtime",
            "starting_equity": START_CAPITAL,
            "ending_total_equity_after_tax": START_CAPITAL,
            "selected_trades": 0,
            "rejected_trades": 0,
            "trade_rows": [],
            "rejected_rows": [],
            "yearly_rows": [],
    }
    candidate_by_signature = {_trade_signature(row): row for row in candidates}
    event_rows = _strategy_event_rows(
        portfolio.get("trade_rows", []),
        candidate_by_signature,
        existing_keys,
        decision_start_by_symbol=decision_start_by_symbol,
    )
    _write_replay_csv(config.output_root / "ledger" / "forward_strategy_all_symbol_candidates_before_6h_context.csv", candidates_before_6h_context)
    _write_replay_csv(config.output_root / "ledger" / "forward_strategy_all_symbol_candidates.csv", candidates)
    _write_replay_csv(config.output_root / "ledger" / "forward_strategy_selected_trades.csv", portfolio.get("trade_rows", []))
    _write_replay_csv(config.output_root / "ledger" / "forward_strategy_rejected_trades.csv", portfolio.get("rejected_rows", []))
    _write_replay_csv(config.output_root / "ledger" / "forward_strategy_cost_guard_rejected_trades.csv", cost_rejected)
    _write_replay_csv(config.output_root / "ledger" / "forward_strategy_spot_long_only_rejected_shorts.csv", short_rejected_for_spot)
    summary = {
        "updated_at_utc": _now(config).isoformat(),
        "strategy_evaluator_enabled": True,
        "classification": "FORWARD_RUNTIME_FROZEN_STRATEGY_EVALUATED_RESEARCH_ONLY",
        "spot_compatible_long_only": SPOT_COMPATIBLE_LONG_ONLY,
        "short_selling_allowed": SHORT_SELLING_ALLOWED,
        "short_candidates_rejected_for_spot": len(short_rejected_for_spot),
        "seed_context_activation_guard": {
            "enabled": bool(decision_start_by_symbol),
            "decision_start_by_symbol": {
                symbol: value.isoformat() for symbol, value in decision_start_by_symbol.items()
            },
            "pre_activation_candidate_rows_removed": len(pre_activation_candidates),
            "pre_activation_cost_rejected_rows_removed": len(pre_activation_cost_rejected),
            "seed_context_only_not_counted_as_forward_pnl": bool(decision_start_by_symbol),
        },
        "six_h_context_overlay": six_h_context_summary,
        "priority_symbols": priority_symbols,
        "symbol_caps_eur": symbol_caps,
        "symbol_evaluator_results": symbol_eval_results,
        "all_symbol_candidate_trades": len(candidates),
        "portfolio_selected_trades": len(portfolio.get("trade_rows", [])),
        "portfolio_rejected_trades": len(portfolio.get("rejected_rows", [])),
        "new_strategy_event_rows": len(event_rows),
        "portfolio_summary": {key: value for key, value in portfolio.items() if key not in {"trade_rows", "rejected_rows", "yearly_rows", "selected_signature"}},
        "paper_validation_ready": False,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "order_path_created": False,
        "broker_path_created": False,
        "private_endpoint_used": False,
        "signed_endpoint_used": False,
        "account_endpoint_used": False,
        "order_endpoint_used": False,
        "strategy_logic_changed": False,
        "entries_changed": False,
        "exits_changed": False,
        "thresholds_tuned": False,
    }
    _write_json(config.output_root / "diagnostics" / "strategy_evaluator_summary.json", summary)
    return {
        "summary": summary,
        "event_rows": event_rows,
    }


def _truthy(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "accepted", "triggered", "selected"}


def _is_actionable_trade_trigger(row: dict[str, Any]) -> bool:
    if _truthy(row.get("order_created")) or _truthy(row.get("paper_trade_created")) or _truthy(row.get("live_trade_created")):
        return True
    trigger_keys = (
        "trade_triggered",
        "signal_triggered",
        "scanner_selected",
        "setup_accepted",
        "accepted",
        "accepted_or_rejected",
        "baseline_1h_signal",
    )
    if any(_truthy(row.get(key)) for key in trigger_keys):
        return True
    if _truthy(row.get("strategy_signal_evaluated")) and str(row.get("reason", "")).strip() not in {
        "",
        "research_runtime_candle_decision_slot_only_no_strategy_or_execution_change",
        "earned_parallel_slot_runtime_candle_decision_slot_only_no_strategy_or_execution_change",
        "no_trade",
        "no_signal",
    }:
        return True
    return False


def _processed_trade_event_keys(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        return {row.get("event_key", "") for row in csv.DictReader(handle) if row.get("event_key")}


def _alert_env() -> dict[str, Any]:
    return {
        "recipient": os.getenv("RTS_ALERT_EMAIL_TO", DEFAULT_ALERT_TO),
        "enabled": _truthy(os.getenv("RTS_ALERT_EMAIL_ENABLED")),
        "dry_run": _truthy(os.getenv("RTS_ALERT_EMAIL_DRY_RUN")),
        "host": os.getenv("RTS_ALERT_SMTP_HOST", "").strip(),
        "port": int(os.getenv("RTS_ALERT_SMTP_PORT", "587") or "587"),
        "sender": os.getenv("RTS_ALERT_EMAIL_FROM", "").strip(),
        "username": os.getenv("RTS_ALERT_SMTP_USERNAME", "").strip(),
        "password": os.getenv("RTS_ALERT_SMTP_PASSWORD", ""),
    }


def _redact(text: str, *secrets: str) -> str:
    safe = text
    for secret in secrets:
        if secret:
            safe = safe.replace(secret, "[REDACTED]")
    return safe


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def _format_plain_table(rows: list[tuple[str, Any]], *, label_width: int = 30) -> str:
    if not rows:
        return ""
    label_width = max(label_width, max(len(str(label)) for label, _ in rows))
    lines = ["+" + "-" * (label_width + 2) + "+" + "-" * 46 + "+", f"| {'Field'.ljust(label_width)} | {'Value'.ljust(44)} |", "+" + "-" * (label_width + 2) + "+" + "-" * 46 + "+"]
    for label, value in rows:
        text = str(value if value is not None else "")
        if len(text) > 44:
            text = text[:41] + "..."
        lines.append(f"| {str(label).ljust(label_width)} | {text.ljust(44)} |")
    lines.append("+" + "-" * (label_width + 2) + "+" + "-" * 46 + "+")
    return "\n".join(lines)


def _format_compact_value(value: Any) -> str:
    if value in {None, ""}:
        return "not recorded"
    return str(value)


def _html_card(*, title: str, hero: str, hero_kind: str, sections: list[tuple[str, list[tuple[str, Any]]]], footer: str) -> str:
    color = "#10b981" if hero_kind == "profit" else "#ef4444" if hero_kind == "loss" else "#f59e0b"
    accent_bg = "rgba(16,185,129,.16)" if hero_kind == "profit" else "rgba(239,68,68,.16)" if hero_kind == "loss" else "rgba(245,158,11,.16)"
    emoji = "🎯" if hero_kind == "profit" else "🛡️" if hero_kind == "loss" else "⚡"
    status_label = "PROFIT EXIT" if hero_kind == "profit" else "LOSS CONTROL EXIT" if hero_kind == "loss" else "ENTRY SIGNAL"
    first_rows = sections[1][1] if len(sections) > 1 else sections[0][1] if sections else []
    metric_html = []
    for key, value in first_rows[:4]:
        metric_html.append(
            "<td class=\"metric\">"
            f"<div class=\"metricLabel\">{escape(str(key))}</div>"
            f"<div class=\"metricValue\">{escape(_format_compact_value(value))}</div>"
            "</td>"
        )
    section_html: list[str] = []
    for heading, rows in sections:
        section_html.append(f"<div class=\"section\"><h2>{escape(heading)}</h2>")
        section_html.append("<table class=\"dataTable\">")
        for label, value in rows:
            section_html.append(
                "<tr>"
                f"<th>{escape(str(label))}</th>"
                f"<td>{escape(_format_compact_value(value))}</td>"
                "</tr>"
            )
        section_html.append("</table></div>")
    return f"""<!doctype html>
<html>
  <body style="margin:0;background:#050b16;color:#e5eef9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
    <div class="stage" style="max-width:900px;margin:0 auto;padding:28px;">
      <div class="shell">
        <div class="topbar">
          <div class="eyebrow">RTS live signal scheduler · 9-symbol frozen strategy · USDT signal stream</div>
          <h1>{escape(title)}</h1>
          <div class="subtitle">Shadow/live-market signal observation only. Binance execution emails arrive separately from the guarded USDC canary.</div>
        </div>
        <div class="content">
          <div class="hero" style="border-color:{color};background:linear-gradient(135deg,{accent_bg},rgba(15,23,42,.88));">
            <div class="orb" style="background:{color};box-shadow:0 0 34px {color};">{emoji}</div>
            <div>
              <div class="heroLabel" style="color:{color};">{status_label}</div>
              <div class="heroText">{escape(hero)}</div>
            </div>
          </div>
          <table class="metricGrid"><tr>{''.join(metric_html)}</tr></table>
          {''.join(section_html)}
          <div class="footerBox">{escape(footer)}</div>
        </div>
      </div>
    </div>
    <style>
      @keyframes pulseGlow {{ 0% {{ transform:scale(1); opacity:.92; }} 50% {{ transform:scale(1.04); opacity:1; }} 100% {{ transform:scale(1); opacity:.92; }} }}
      .shell {{ border:1px solid rgba(148,163,184,.38); border-radius:26px; background:radial-gradient(circle at 18% 0%,rgba(34,211,238,.22),transparent 34%),radial-gradient(circle at 100% 0%,rgba(168,85,247,.20),transparent 30%),linear-gradient(135deg,#07111f,#0b2532 54%,#111827); box-shadow:0 24px 70px rgba(0,0,0,.48); overflow:hidden; }}
      .topbar {{ padding:28px 32px; border-bottom:1px solid rgba(148,163,184,.24); background:rgba(255,255,255,.035); }}
      .eyebrow {{ letter-spacing:.18em; text-transform:uppercase; color:#93c5fd; font-size:12px; font-weight:900; }}
      h1 {{ font-size:31px; line-height:1.15; margin:10px 0 8px; color:#ffffff; }}
      .subtitle {{ color:#a8b3c7; font-size:14px; font-weight:700; }}
      .content {{ padding:28px 32px 32px; }}
      .hero {{ border:1px solid; border-radius:22px; padding:22px; margin-bottom:18px; display:flex; gap:16px; align-items:center; box-shadow:inset 0 0 42px rgba(255,255,255,.035); }}
      .orb {{ width:54px; height:54px; border-radius:18px; display:inline-flex; align-items:center; justify-content:center; font-size:26px; animation:pulseGlow 2.8s ease-in-out infinite; }}
      .heroLabel {{ font-size:13px; letter-spacing:.14em; text-transform:uppercase; font-weight:950; }}
      .heroText {{ font-size:32px; line-height:1.14; color:#ffffff; font-weight:950; margin-top:6px; }}
      .metricGrid {{ width:100%; border-collapse:separate; border-spacing:10px; margin:0 0 18px; }}
      .metric {{ width:25%; padding:14px; border:1px solid rgba(125,211,252,.24); border-radius:16px; background:linear-gradient(135deg,rgba(14,165,233,.12),rgba(15,23,42,.78)); vertical-align:top; }}
      .metricLabel {{ color:#93a4b8; font-size:11px; letter-spacing:.12em; text-transform:uppercase; font-weight:900; }}
      .metricValue {{ color:#f8fafc; font-size:16px; line-height:1.25; font-weight:950; margin-top:7px; }}
      .section {{ border:1px solid rgba(148,163,184,.20); border-radius:18px; padding:14px; margin:16px 0; background:rgba(2,6,23,.34); }}
      .dataTable {{ width:100%; border-collapse:collapse; background:rgba(15,23,42,.72); border-radius:14px; overflow:hidden; }}
      th,td {{ padding:12px 14px; border-bottom:1px solid rgba(148,163,184,.18); text-align:left; vertical-align:top; }}
      th {{ width:40%; color:#93a4b8; font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
      td {{ color:#f8fafc; font-size:15px; font-weight:800; }}
      h2 {{ color:#e0f2fe; font-size:18px; margin:0 0 10px; }}
      .footerBox {{ margin-top:20px; color:#cbd5e1; font-size:13px; line-height:1.6; border:1px solid rgba(148,163,184,.18); border-radius:16px; padding:14px; background:rgba(15,23,42,.55); }}
    </style>
  </body>
</html>
"""


def _event_type(row: dict[str, Any]) -> str:
    explicit = str(row.get("event_type") or row.get("order_event_type") or "").strip().upper()
    if explicit:
        return explicit
    if str(row.get("exit_reason") or "").strip():
        return "EXIT"
    return "ENTRY"


def _format_eur(value: Any, *, signed: bool = False) -> str:
    parsed = _float_or_none(value)
    if parsed is None:
        return "not recorded"
    sign = "+" if signed and parsed > 0 else ""
    return f"{sign}€{parsed:,.2f}"


def _trade_event_top_line(row: dict[str, Any], *, symbol: str) -> str:
    event_type = _event_type(row)
    side = str(row.get("side") or row.get("direction") or "").upper() or "LONG"
    if event_type == "EXIT":
        pnl = _float_or_none(row.get("net_pnl_eur", row.get("pnl_eur", ""))) or 0.0
        if pnl > 0:
            return f"CONGRATULATIONS: PROFIT {_format_eur(pnl, signed=True)} | {symbol} {side}"
        if pnl < 0:
            return f"OOPS: LOSING TRADE {_format_eur(pnl, signed=True)} | {symbol} {side}"
        return f"FLAT EXIT: €0.00 | {symbol} {side}"
    amount = row.get("amount_bought_eur", row.get("position_notional_eur", ""))
    equity = row.get("total_equity_after_event_eur", row.get("active_equity_reference_eur", ""))
    return f"ENTRY TRIGGERED: {symbol} {side} | amount {_format_eur(amount)} | equity {_format_eur(equity)}"


def _trade_event_hero(row: dict[str, Any], *, symbol: str) -> tuple[str, str, str]:
    event_type = _event_type(row)
    side = str(row.get("side") or row.get("direction") or "").upper() or "LONG"
    if event_type == "EXIT":
        pnl = _float_or_none(row.get("net_pnl_eur", row.get("pnl_eur", ""))) or 0.0
        total = _format_eur(row.get("total_equity_after_event_eur", row.get("active_equity_after_event_eur", "")))
        if pnl > 0:
            return (
                f"Exit closed: {symbol} {side}",
                f"CONGRATULATIONS — PROFIT {_format_eur(pnl, signed=True)} | Total equity {total}",
                "profit",
            )
        if pnl < 0:
            return (
                f"Exit closed: {symbol} {side}",
                f"OOPS — LOSS {_format_eur(pnl, signed=True)} | Total equity {total}",
                "loss",
            )
        return (f"Exit closed: {symbol} {side}", f"FLAT EXIT €0.00 | Total equity {total}", "entry")
    amount = _format_eur(row.get("amount_bought_eur", row.get("position_notional_eur", "")))
    total = _format_eur(row.get("total_equity_after_event_eur", row.get("active_equity_reference_eur", "")))
    return (f"Entry opened: {symbol} {side}", f"ENTRY TRIGGERED — amount {amount} | Total equity {total}", "entry")


def _plain_section(title: str, rows: list[tuple[str, Any]]) -> list[str]:
    lines = [title, "-" * len(title)]
    for label, value in rows:
        lines.append(f"{label}: {_format_compact_value(value)}")
    return lines


def _trade_event_sections(row: dict[str, Any], *, event_key: str, symbol: str, slot: str, reason: str) -> list[tuple[str, list[tuple[str, Any]]]]:
    return [
        (
            "Event",
            [
                ("Event type", _event_type(row)),
                ("Event key", event_key),
                ("Symbol", symbol),
                ("Side / direction", row.get("side", row.get("direction", ""))),
                ("Decision slot", slot),
                ("Closed 1H candle start", row.get("closed_1h_candle_start", "")),
                ("Closed 1H candle end", row.get("closed_1h_candle_end", "")),
                ("Source 1m rows", row.get("source_1m_count", "")),
                ("Reason", reason),
            ],
        ),
        (
            "PnL / equity",
            [
                ("Amount bought", _format_eur(row.get("amount_bought_eur", ""))),
                ("Position notional", _format_eur(row.get("position_notional_eur", ""))),
                ("Active equity reference", _format_eur(row.get("active_equity_reference_eur", ""))),
                ("Total equity after event", _format_eur(row.get("total_equity_after_event_eur", ""))),
                ("Net PnL", _format_eur(row.get("net_pnl_eur", row.get("pnl_eur", "")), signed=True)),
                ("Risk", _format_eur(row.get("risk_eur", ""))),
                ("Estimated cost", _format_eur(row.get("estimated_cost_eur", ""))),
                ("Net R", row.get("net_r", row.get("r_multiple", ""))),
            ],
        ),
        (
            "Trade technicals",
            [
                ("Entry price", row.get("entry_price", row.get("entry_reference", ""))),
                ("Exit price", row.get("exit_price", row.get("exit_reference", ""))),
                ("Initial stop", row.get("initial_stop", row.get("stop_reference", ""))),
                ("Target reference", row.get("target_reference", "")),
                ("Entry reason", row.get("entry_reason", row.get("reason", ""))),
                ("Exit reason", row.get("exit_reason", "")),
                ("Setup class", row.get("setup_class", "")),
                ("Pattern", row.get("pattern", "")),
                ("Liquidity event", row.get("liquidity_event_type", "")),
                ("Entry score", row.get("entry_score", row.get("score", ""))),
                ("Convexity label", row.get("convexity_label", "")),
            ],
        ),
        (
            "6H context",
            [
                ("Overlay court", row.get("six_h_context_overlay_court", ACTIVE_6H_CONTEXT_OVERLAY_COURT)),
                ("Overlay classification", row.get("six_h_context_overlay_classification", ACTIVE_6H_CONTEXT_OVERLAY_CLASSIFICATION)),
                ("Variant", row.get("six_h_context_variant", ACTIVE_6H_CONTEXT_VARIANT)),
                ("Trend state", row.get("six_h_trend_state", "")),
                ("Structure state", row.get("six_h_structure_state", "")),
                ("Alignment", row.get("six_h_alignment", "")),
                ("Conflict", row.get("six_h_conflict", "")),
                ("Room to target R", row.get("six_h_room_to_target_r", "")),
                ("Scale multiplier", row.get("six_h_context_scale_multiplier", "")),
            ],
        ),
        (
            "Allocator / safety",
            [
                ("Allocator spec", row.get("allocator_spec_id", EARNED_PARALLEL_SLOT_SPEC_ID)),
                ("Allocator action", row.get("allocator_slot_action", "")),
                ("Max slots at entry", row.get("max_slots_at_entry", row.get("allocator_max_slots_active", ""))),
                ("Concurrent slots at entry", row.get("concurrent_slots_at_entry", "")),
                ("Paper validation ready", "false"),
                ("Live allowed", "false"),
                ("Real money allowed", "false"),
                ("Order path created", "false"),
                ("Broker path created", "false"),
            ],
        ),
    ]


def _email_subject_for_trade_event(row: dict[str, Any], *, symbol: str, slot: str) -> str:
    event_type = _event_type(row)
    side = str(row.get("side") or row.get("direction") or "").upper()
    pnl_float = _float_or_none(row.get("net_pnl_eur", row.get("pnl_eur", ""))) or 0.0
    if event_type == "EXIT":
        if pnl_float > 0:
            result = f"CONGRATULATIONS PROFIT {_format_eur(pnl_float, signed=True)}"
        elif pnl_float < 0:
            result = f"OOPS LOSING TRADE {_format_eur(pnl_float, signed=True)}"
        else:
            result = "FLAT EXIT €0.00"
        return f"RTS LIVE SIGNAL EXIT - {result}: {symbol} {side} {slot}"
    return f"RTS LIVE SIGNAL ENTRY: {symbol} {side} {slot}"


def _write_trade_trigger_email(output_root: Path, row: dict[str, Any]) -> dict[str, Any]:
    alert = _alert_env()
    event_key = str(row.get("decision_key") or f"{row.get('symbol', '')}|{row.get('decision_slot', '')}")
    symbol = str(row.get("symbol", "UNKNOWN"))
    slot = str(row.get("decision_slot") or row.get("closed_1h_candle_start") or "")
    safe_name = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in event_key)[:180]
    event_dir = output_root / "alerts" / "multi_asset_trade_events"
    event_path = event_dir / f"{safe_name}.txt"
    event_html_path = event_dir / f"{safe_name}.html"
    latest_path = event_dir / "latest_multi_asset_trade_trigger_email.txt"
    latest_html_path = event_dir / "latest_multi_asset_trade_trigger_email.html"
    subject = _email_subject_for_trade_event(row, symbol=symbol, slot=slot)
    reason = str(row.get("reason", ""))
    title, hero, hero_kind = _trade_event_hero(row, symbol=symbol)
    sections = _trade_event_sections(row, event_key=event_key, symbol=symbol, slot=slot, reason=reason)
    html_body = _html_card(
        title=title,
        hero=hero,
        hero_kind=hero_kind,
        sections=sections,
        footer=(
            "This is the USDT walk-forward/live-market signal scheduler. It is not a Binance demo email "
            "and not a live-money execution email. It records frozen strategy signals only; execution is handled separately by the guarded USDC canary."
        ),
    )
    plain_lines: list[str] = [
        _trade_event_top_line(row, symbol=symbol),
        "",
        "RTS LIVE SIGNAL SCHEDULER",
        "=========================",
        "Email stream: LIVE MARKET SIGNAL / PRODUCTION MONITORING.",
        "This is NOT a Binance demo execution email.",
        "This is NOT a live-money execution email.",
        "Execution, if any, is handled separately by the guarded USDC canary.",
        "",
    ]
    for section_title, section_rows in sections:
        plain_lines.extend(_plain_section(section_title, section_rows))
        plain_lines.append("")
    plain_lines.extend(
        [
            "Alert policy",
            "------------",
            "Entry email is emitted only for an actionable ENTRY event row.",
            "Exit email is emitted only for an actionable EXIT event row.",
            "Emails are idempotent and ledgered by event_key.",
            "",
            "Safety",
            "------",
            "paper_validation_ready: false",
            "live_allowed: false",
            "real_money_allowed: false",
            "order_path_created: false",
            "broker_path_created: false",
            "private/account/signed/order endpoint used by this scheduler: false",
            "",
            f"Artifact root: {output_root}",
        ]
    )
    body = "\n".join(
        plain_lines
    )
    event_dir.mkdir(parents=True, exist_ok=True)
    event_text = f"To: {alert['recipient']}\nSubject: {subject}\n\n{body}\n"
    event_path.write_text(event_text, encoding="utf-8")
    latest_path.write_text(event_text, encoding="utf-8")
    event_html_path.write_text(html_body, encoding="utf-8")
    latest_html_path.write_text(html_body, encoding="utf-8")
    sent = False
    note = "draft_written"
    smtp_allowed, smtp_gate_note = smtp_allowed_for_output_root(output_root)
    if not smtp_allowed:
        note = smtp_gate_note
    if smtp_allowed and alert["enabled"] and not alert["dry_run"] and alert["host"] and alert["sender"]:
        msg = EmailMessage()
        msg["From"] = alert["sender"]
        msg["To"] = alert["recipient"]
        msg["Subject"] = subject
        msg.set_content(body)
        msg.add_alternative(html_body, subtype="html")
        try:
            with smtplib.SMTP(alert["host"], alert["port"], timeout=20) as smtp:
                smtp.starttls()
                if alert["username"] or alert["password"]:
                    smtp.login(alert["username"], alert["password"])
                smtp.send_message(msg)
            sent = True
            note = "smtp_sent"
        except Exception as exc:  # noqa: BLE001
            note = "smtp_failed_draft_written:" + _redact(str(exc), alert["password"])
    return {
        "event_key": event_key,
        "symbol": symbol,
        "decision_slot": slot,
        "reason": reason,
        "email_subject": subject,
        "email_recipient": alert["recipient"],
        "email_sent": sent,
        "email_draft_written": True,
        "email_path": str(event_path),
        "email_html_path": str(event_html_path),
        "latest_email_path": str(latest_path),
        "latest_email_html_path": str(latest_html_path),
        "email_note": note,
        "paper_validation_ready": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "order_path_created": False,
        "broker_path_created": False,
    }


def _send_multi_asset_trade_trigger_emails(output_root: Path, rows: list[dict[str, Any]], ledger_path: Path) -> dict[str, Any]:
    processed = _processed_trade_event_keys(ledger_path)
    event_records: list[dict[str, Any]] = []
    actionable = [row for row in rows if _is_actionable_trade_trigger(row)]
    for row in actionable:
        event_key = str(row.get("decision_key") or f"{row.get('symbol', '')}|{row.get('decision_slot', '')}")
        if event_key in processed:
            continue
        record = _write_trade_trigger_email(output_root, row)
        event_records.append(record)
        processed.add(event_key)
    if event_records:
        _append_csv(ledger_path, event_records)
    return {
        "multi_asset_trade_trigger_rows_seen_this_run": len(actionable),
        "multi_asset_trade_trigger_emails_written_this_run": len(event_records),
        "multi_asset_trade_trigger_emails_sent_this_run": sum(1 for row in event_records if row.get("email_sent")),
        "multi_asset_trade_trigger_email_ledger": str(ledger_path),
        "multi_asset_trade_trigger_latest_email": str(output_root / "alerts" / "multi_asset_trade_events" / "latest_multi_asset_trade_trigger_email.txt"),
        "multi_asset_trade_trigger_email_subject_prefix": "RTS LIVE SIGNAL SCHEDULER",
    }


def _parse_timestamp(value: Any) -> pd.Timestamp | None:
    if value in {None, ""}:
        return None
    parsed = pd.to_datetime(value, utc=True, errors="coerce")
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed)


def _local_day_window(now_utc: datetime, *, timezone_name: str = LOCAL_REPORT_TIMEZONE) -> dict[str, Any]:
    local_zone = ZoneInfo(timezone_name)
    aware_now = now_utc if now_utc.tzinfo is not None else now_utc.replace(tzinfo=timezone.utc)
    local_now = aware_now.astimezone(local_zone)
    report_date = local_now.date() - timedelta(days=1)
    start_local = datetime.combine(report_date, datetime_time.min, tzinfo=local_zone)
    end_local = datetime.combine(report_date + timedelta(days=1), datetime_time.min, tzinfo=local_zone)
    start_utc = start_local.astimezone(timezone.utc)
    end_utc = end_local.astimezone(timezone.utc)
    return {
        "report_date": report_date.isoformat(),
        "timezone": timezone_name,
        "start_local": start_local.isoformat(),
        "end_local_exclusive": end_local.isoformat(),
        "start_utc": start_utc.isoformat(),
        "end_utc_exclusive": end_utc.isoformat(),
        "start_utc_naive": pd.Timestamp(start_utc).tz_convert(None),
        "end_utc_naive": pd.Timestamp(end_utc).tz_convert(None),
    }


def _daily_digest_processed_dates(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        return {row.get("report_date", "") for row in csv.DictReader(handle) if row.get("report_date")}


def _events_in_window(path: Path, *, start_utc: pd.Timestamp, end_utc: pd.Timestamp, timestamp_fields: tuple[str, ...]) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    events: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            ts = None
            for field in timestamp_fields:
                ts = _parse_timestamp(row.get(field))
                if ts is not None:
                    break
            if ts is None:
                continue
            ts_naive = ts.tz_convert(None)
            if start_utc <= ts_naive < end_utc:
                events.append(row)
    return events


def _demo_order_events_in_window(output_root: Path, *, start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> list[dict[str, str]]:
    candidates = [
        output_root.parent / "binance_demo_walk_forward_six_month_court_001" / "execution_bridge" / "walk_forward_demo_execution_ledger.csv",
        output_root.parent / "walk_forward_demo_execution_bridge" / "walk_forward_demo_execution_ledger.csv",
    ]
    rows: list[dict[str, str]] = []
    for path in candidates:
        for row in _events_in_window(path, start_utc=start_utc, end_utc=end_utc, timestamp_fields=("created_at", "source_timestamp")):
            if _truthy(row.get("submitted")) and str(row.get("order_event_type", "")).strip():
                rows.append(row)
    return rows


def _market_day_summary(output_root: Path, *, start_utc: pd.Timestamp, end_utc: pd.Timestamp) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        runtime_path = _runtime_copy_path(output_root, symbol)
        if not runtime_path.exists():
            rows.append({"symbol": symbol, "rows": 0, "summary_available": False, "reason": "missing_runtime_snapshot"})
            continue
        frame = _normalize_frame(pd.read_csv(runtime_path))
        day = frame[(frame["timestamp"] >= start_utc) & (frame["timestamp"] < end_utc)].copy()
        if day.empty:
            rows.append({"symbol": symbol, "rows": 0, "summary_available": False, "reason": "no_rows_inside_report_day"})
            continue
        open_ = float(day.iloc[0]["open"])
        close = float(day.iloc[-1]["close"])
        high = float(day["high"].max())
        low = float(day["low"].min())
        volume = float(day["volume"].sum())
        ret = _safe_ratio(close - open_, open_, 0.0)
        range_pct = _safe_ratio(high - low, open_, 0.0)
        complete_1h = _resample_complete(day, "1h", 60)
        rows.append(
            {
                "symbol": symbol,
                "summary_available": True,
                "rows": int(len(day)),
                "first_timestamp": day.iloc[0]["timestamp"].isoformat(),
                "last_timestamp": day.iloc[-1]["timestamp"].isoformat(),
                "open": open_,
                "high": high,
                "low": low,
                "close": close,
                "return_pct": ret * 100.0,
                "intraday_range_pct": range_pct * 100.0,
                "volume": volume,
                "complete_1h_bars": int(len(complete_1h)),
                "quality_clean": _quality(day)["clean"],
            }
        )
    return rows


def _format_market_digest_lines(market_rows: list[dict[str, Any]]) -> list[str]:
    available = [row for row in market_rows if row.get("summary_available")]
    if not available:
        return ["No market snapshot rows were available for the report day."]
    ranked_return = sorted(available, key=lambda row: float(row.get("return_pct") or 0.0), reverse=True)
    ranked_range = sorted(available, key=lambda row: float(row.get("intraday_range_pct") or 0.0), reverse=True)
    lines = [
        "Market summary:",
        f"- strongest close-to-close move: {ranked_return[0]['symbol']} {float(ranked_return[0]['return_pct']):+.2f}%",
        f"- weakest close-to-close move: {ranked_return[-1]['symbol']} {float(ranked_return[-1]['return_pct']):+.2f}%",
        f"- widest intraday range: {ranked_range[0]['symbol']} {float(ranked_range[0]['intraday_range_pct']):.2f}%",
        "",
        "Per-symbol tape:",
    ]
    for row in ranked_return:
        lines.append(
            "- "
            f"{row['symbol']}: "
            f"O {float(row['open']):.6g}, H {float(row['high']):.6g}, "
            f"L {float(row['low']):.6g}, C {float(row['close']):.6g}, "
            f"return {float(row['return_pct']):+.2f}%, "
            f"range {float(row['intraday_range_pct']):.2f}%, "
            f"1m rows {int(row['rows'])}, "
            f"complete 1H bars {int(row['complete_1h_bars'])}, "
            f"quality_clean {str(row['quality_clean']).lower()}"
        )
    return lines


def _write_daily_no_trade_email(
    output_root: Path,
    *,
    report_window: dict[str, Any],
    market_rows: list[dict[str, Any]],
    decision_count: int,
    trigger_count: int,
    demo_order_count: int,
) -> dict[str, Any]:
    alert = _alert_env()
    event_dir = output_root / "alerts" / "daily_no_trade_digest"
    report_date = str(report_window["report_date"])
    event_path = event_dir / f"no_trade_daily_digest_{report_date}.txt"
    latest_path = event_dir / "latest_no_trade_daily_digest.txt"
    subject = f"RTS LIVE SIGNAL SCHEDULER DAILY NO-TRADE DIGEST: {report_date}"
    body = "\n".join(
        [
            "No live-market scheduler trade event was recorded for the report day.",
            "",
            "This is NOT a Binance demo execution email.",
            "This is NOT a live-money execution email.",
            "",
            "Report window:",
            f"- local date: {report_date}",
            f"- timezone: {report_window['timezone']}",
            f"- local start: {report_window['start_local']}",
            f"- local end exclusive: {report_window['end_local_exclusive']}",
            f"- UTC start: {report_window['start_utc']}",
            f"- UTC end exclusive: {report_window['end_utc_exclusive']}",
            "",
            "Execution/event check:",
            f"- actionable scheduler trigger emails recorded: {trigger_count}",
            f"- demo order events recorded: {demo_order_count}",
            f"- closed 1H decision rows processed: {decision_count}",
            "",
            *_format_market_digest_lines(market_rows),
            "",
            "Interpretation:",
            "- The machine collected/processed market data, but no eligible trade event was recorded.",
            "- This is not a failure by itself; it means the frozen rules did not authorize a trade for the day.",
            "",
            "Safety:",
            "- research_only: true",
            "- paper_validation_ready: false",
            "- live_allowed: false",
            "- real_money_allowed: false",
            "- order_path_created: false",
            "- broker_path_created: false",
            "",
            f"Artifact root: {output_root}",
        ]
    )
    event_dir.mkdir(parents=True, exist_ok=True)
    text = f"To: {alert['recipient']}\nSubject: {subject}\n\n{body}\n"
    event_path.write_text(text, encoding="utf-8")
    latest_path.write_text(text, encoding="utf-8")
    sent = False
    note = "draft_written"
    smtp_allowed, smtp_gate_note = smtp_allowed_for_output_root(output_root)
    if not smtp_allowed:
        note = smtp_gate_note
    if smtp_allowed and alert["enabled"] and not alert["dry_run"] and alert["host"] and alert["sender"]:
        msg = EmailMessage()
        msg["From"] = alert["sender"]
        msg["To"] = alert["recipient"]
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(alert["host"], alert["port"], timeout=20) as smtp:
                smtp.starttls()
                if alert["username"] or alert["password"]:
                    smtp.login(alert["username"], alert["password"])
                smtp.send_message(msg)
            sent = True
            note = "smtp_sent"
        except Exception as exc:  # noqa: BLE001
            note = "smtp_failed_draft_written:" + _redact(str(exc), alert["password"])
    return {
        "report_date": report_date,
        "email_subject": subject,
        "email_recipient": alert["recipient"],
        "email_sent": sent,
        "email_draft_written": True,
        "email_path": str(event_path),
        "latest_email_path": str(latest_path),
        "email_note": note,
        "decision_rows_processed": decision_count,
        "trade_trigger_events": trigger_count,
        "demo_order_events": demo_order_count,
        "paper_validation_ready": False,
        "live_allowed": False,
        "real_money_allowed": False,
    }


def _send_daily_no_trade_digest_if_due(
    config: MultiSymbolForwardRuntimeConfig,
    *,
    decision_ledger_path: Path,
    trade_event_ledger_path: Path,
    daily_digest_ledger_path: Path,
) -> dict[str, Any]:
    report_window = _local_day_window(_now(config))
    report_date = str(report_window["report_date"])
    if report_date in _daily_digest_processed_dates(daily_digest_ledger_path):
        return {
            "daily_no_trade_digest_due": False,
            "daily_no_trade_digest_reason": "already_sent_for_report_date",
            "daily_no_trade_digest_report_date": report_date,
            "daily_no_trade_digest_email_written": False,
            "daily_no_trade_digest_email_sent": False,
            "daily_no_trade_digest_ledger": str(daily_digest_ledger_path),
        }
    start_utc = report_window["start_utc_naive"]
    end_utc = report_window["end_utc_naive"]
    trigger_events = _events_in_window(
        trade_event_ledger_path,
        start_utc=start_utc,
        end_utc=end_utc,
        timestamp_fields=("decision_slot",),
    )
    demo_order_events = _demo_order_events_in_window(config.output_root, start_utc=start_utc, end_utc=end_utc)
    decision_events = _events_in_window(
        decision_ledger_path,
        start_utc=start_utc,
        end_utc=end_utc,
        timestamp_fields=("decision_slot", "closed_1h_candle_start"),
    )
    market_rows = _market_day_summary(config.output_root, start_utc=start_utc, end_utc=end_utc)
    if trigger_events or demo_order_events:
        record = {
            "report_date": report_date,
            "email_sent": False,
            "email_draft_written": False,
            "email_note": "trade_event_present_no_no_trade_digest",
            "decision_rows_processed": len(decision_events),
            "trade_trigger_events": len(trigger_events),
            "demo_order_events": len(demo_order_events),
            "paper_validation_ready": False,
            "live_allowed": False,
            "real_money_allowed": False,
        }
        _append_csv(daily_digest_ledger_path, [record])
        _write_json(
            config.output_root / "alerts" / "daily_no_trade_digest" / f"daily_digest_market_summary_{report_date}.json",
            {"report_window": report_window, "market_rows": market_rows, "record": record, **SAFETY_FLAGS},
        )
        return {
            "daily_no_trade_digest_due": False,
            "daily_no_trade_digest_reason": "trade_event_present_no_no_trade_digest",
            "daily_no_trade_digest_report_date": report_date,
            "daily_no_trade_digest_email_written": False,
            "daily_no_trade_digest_email_sent": False,
            "daily_no_trade_digest_ledger": str(daily_digest_ledger_path),
            "trade_trigger_events": len(trigger_events),
            "demo_order_events": len(demo_order_events),
        }
    record = _write_daily_no_trade_email(
        config.output_root,
        report_window=report_window,
        market_rows=market_rows,
        decision_count=len(decision_events),
        trigger_count=len(trigger_events),
        demo_order_count=len(demo_order_events),
    )
    _append_csv(daily_digest_ledger_path, [record])
    _write_json(
        config.output_root / "alerts" / "daily_no_trade_digest" / f"daily_digest_market_summary_{report_date}.json",
        {"report_window": report_window, "market_rows": market_rows, "record": record, **SAFETY_FLAGS},
    )
    return {
        "daily_no_trade_digest_due": True,
        "daily_no_trade_digest_reason": "no_trade_events_recorded_for_completed_local_day",
        "daily_no_trade_digest_report_date": report_date,
        "daily_no_trade_digest_email_written": bool(record.get("email_draft_written")),
        "daily_no_trade_digest_email_sent": bool(record.get("email_sent")),
        "daily_no_trade_digest_latest_email": record.get("latest_email_path", ""),
        "daily_no_trade_digest_ledger": str(daily_digest_ledger_path),
    }


def _existing_decision_keys(path: Path) -> set[str]:
    if not path.exists() or path.stat().st_size == 0:
        return set()
    with path.open(newline="", encoding="utf-8") as handle:
        return {row.get("decision_key", "") for row in csv.DictReader(handle) if row.get("decision_key")}


def _historical_warm_start_metadata(path: Path) -> dict[str, Any]:
    manifest = _read_json(path, {})
    cutoffs: dict[str, pd.Timestamp] = {}
    raw_cutoffs = manifest.get("decision_start_by_symbol") if isinstance(manifest, dict) else {}
    if isinstance(raw_cutoffs, dict):
        for symbol, value in raw_cutoffs.items():
            parsed = pd.to_datetime(value, utc=True, errors="coerce")
            if not pd.isna(parsed):
                cutoffs[str(symbol)] = pd.Timestamp(parsed).tz_convert(None)
    return {
        "manifest": manifest if isinstance(manifest, dict) else {},
        "decision_start_by_symbol": cutoffs,
    }


def _symbol_cap_metadata(config: MultiSymbolForwardRuntimeConfig) -> dict[str, Any]:
    summary = _read_json(config.reduced_cap_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json", {})
    return {
        "source_reduced_cap_summary": str(config.reduced_cap_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json"),
        "recommended_symbol_caps_eur": summary.get("recommended_symbol_caps_eur", {}),
        "active_symbols_missing_explicit_cap": [
            symbol for symbol in SYMBOLS if symbol not in dict(summary.get("recommended_symbol_caps_eur", {}) or {})
        ],
        "reduced_cap_gate_passed": bool(summary.get("gate", {}).get("may_treat_500k_gear1_as_fill_calibrated_research_cap")),
    }


def _acquire_lock(path: Path) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as exc:
        raise RuntimeError(f"runtime_lock_exists:{path}") from exc
    os.write(fd, str(os.getpid()).encode("utf-8"))
    return fd


def _release_lock(path: Path, fd: int | None) -> None:
    if fd is None:
        return
    os.close(fd)
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _run_symbol(
    config: MultiSymbolForwardRuntimeConfig,
    symbol: str,
    latest_safe: pd.Timestamp,
    existing_keys: set[str],
    *,
    decision_start: pd.Timestamp | None = None,
) -> dict[str, Any]:
    runtime_before, source_csv, seeded_from_data_storage = _load_or_seed_runtime_copy(config, symbol)
    runtime_path = _runtime_copy_path(config.output_root, symbol)
    if runtime_before.empty:
        return {
            "symbol": symbol,
            "blocked": True,
            "block_reason": "missing_source_and_runtime_copy",
            "runtime_copy": str(runtime_path),
            "rows_before": 0,
            "rows_after": 0,
            "appended_rows": 0,
            "new_decision_rows": 0,
            "fetch_attempted": False,
            "fetch_error": "",
            "quality": _quality(runtime_before),
        }
    latest_existing = runtime_before["timestamp"].max()
    fetch_start = latest_existing + pd.Timedelta(minutes=1)
    fetch_attempted = bool(fetch_start <= latest_safe)
    fetch_error = ""
    fetched = _normalize_frame(pd.DataFrame())
    if fetch_attempted:
        try:
            minutes = int((latest_safe - fetch_start).total_seconds() // 60) + 1
            if minutes > config.max_catchup_minutes:
                fetch_start = latest_safe - pd.Timedelta(minutes=config.max_catchup_minutes - 1)
            fetched = _fetch_symbol(config, symbol, fetch_start, latest_safe)
        except Exception as exc:  # noqa: BLE001 - runtime must report, not partially crash silently
            fetch_error = f"{type(exc).__name__}: {exc}"
            fetched = _normalize_frame(pd.DataFrame())
    appendable = fetched[(fetched["timestamp"] > latest_existing) & (fetched["timestamp"] <= latest_safe)].copy() if not fetched.empty else fetched
    runtime_after = (
        pd.concat([runtime_before, appendable], ignore_index=True)
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    runtime_after.to_csv(runtime_path, index=False)
    bars_15m = _resample_complete(runtime_after, "15min", 15)
    bars_1h = _resample_complete(runtime_after, "1h", 60)
    bars_6h = _resample_complete_6h_context(runtime_after)
    bars_15m.to_csv(runtime_path.parent / "complete_15m_bars.csv", index=False)
    bars_1h.to_csv(runtime_path.parent / "complete_1h_bars.csv", index=False)
    bars_6h.to_csv(runtime_path.parent / "complete_6h_context_bars.csv", index=False)
    decision_rows = _decision_rows(symbol, bars_1h, existing_keys, decision_start=decision_start)
    for row in decision_rows:
        existing_keys.add(row["decision_key"])
    return {
        "symbol": symbol,
        "blocked": False,
        "block_reason": "",
        "source_csv": str(source_csv) if source_csv else "",
        "seeded_from_data_storage": seeded_from_data_storage,
        "runtime_copy": str(runtime_path),
        "latest_safe_1m_timestamp": latest_safe.isoformat(),
        "latest_existing_timestamp_before_run": latest_existing.isoformat(),
        "fetch_start": fetch_start.isoformat(),
        "fetch_attempted": fetch_attempted,
        "fetch_error": fetch_error,
        "fetched_rows": int(len(fetched)),
        "appended_rows": int(len(appendable)),
        "rows_before": int(len(runtime_before)),
        "rows_after": int(len(runtime_after)),
        "complete_15m_bars": int(len(bars_15m)),
        "complete_1h_bars": int(len(bars_1h)),
        "complete_6h_context_bars": int(len(bars_6h)),
        "decision_start_cutoff": decision_start.isoformat() if decision_start is not None else "",
        "new_decision_rows": int(len(decision_rows)),
        "quality": _quality(runtime_after),
        "new_decisions": decision_rows,
    }


def run_once(config: MultiSymbolForwardRuntimeConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    _ensure_dirs(config.output_root)
    paths = _paths(config.output_root)
    lock_fd: int | None = None
    try:
        lock_fd = _acquire_lock(paths["lock"])
        latest_safe = _latest_safe_1m_timestamp(config)
        existing_keys = _existing_decision_keys(paths["decision_ledger"])
        warm_start = _historical_warm_start_metadata(paths["historical_warm_start_manifest"])
        decision_start_by_symbol: dict[str, pd.Timestamp] = warm_start["decision_start_by_symbol"]
        symbol_results: list[dict[str, Any]] = []
        new_decisions: list[dict[str, Any]] = []
        for symbol in SYMBOLS:
            result = _run_symbol(
                config,
                symbol,
                latest_safe,
                existing_keys,
                decision_start=decision_start_by_symbol.get(symbol),
            )
            new_decisions.extend(result.pop("new_decisions", []))
            symbol_results.append(result)
            if config.throttle_seconds > 0:
                time.sleep(config.throttle_seconds)
        strategy_eval = _evaluate_forward_strategy_events(
            config,
            symbol_results,
            existing_keys,
            decision_start_by_symbol=decision_start_by_symbol,
        )
        strategy_event_rows = strategy_eval["event_rows"]
        new_decisions.extend(strategy_event_rows)
        appended_decisions = _append_csv(paths["decision_ledger"], new_decisions)
        trigger_email_summary = _send_multi_asset_trade_trigger_emails(config.output_root, new_decisions, paths["trade_event_email_ledger"])
        daily_no_trade_digest_summary = _send_daily_no_trade_digest_if_due(
            config,
            decision_ledger_path=paths["decision_ledger"],
            trade_event_ledger_path=paths["trade_event_email_ledger"],
            daily_digest_ledger_path=paths["daily_no_trade_email_ledger"],
        )
        duplicate_decision_keys = _decision_duplicate_count(paths["decision_ledger"])
        quality_rows = [
            {
                "symbol": row["symbol"],
                **row.get("quality", {}),
            }
            for row in symbol_results
        ]
        _write_csv(config.output_root / "diagnostics" / "symbol_quality_latest.csv", quality_rows)
        status_color = STATUS_GREEN
        reasons: list[str] = []
        if any(row.get("fetch_error") for row in symbol_results):
            status_color = STATUS_RED
            reasons.append("one_or_more_symbol_fetch_errors")
        if any(not row.get("quality", {}).get("clean") for row in symbol_results):
            status_color = STATUS_RED
            reasons.append("one_or_more_symbol_runtime_quality_failures")
        if any(row.get("blocked") for row in symbol_results):
            status_color = STATUS_RED
            reasons.append("one_or_more_symbols_blocked")
        if not reasons and sum(int(row.get("appended_rows") or 0) for row in symbol_results) == 0:
            status_color = STATUS_YELLOW
            reasons.append("no_new_closed_public_1m_rows_available")
        cap_metadata = _symbol_cap_metadata(config)
        summary = {
            "runtime_name": "MULTI_SYMBOL_FORWARD_RUNTIME_RESEARCH_ONLY",
            "created_at_utc": _now(config).isoformat(),
            "status_color": status_color,
            "status_reasons": reasons or ["multi_symbol_forward_runtime_run_once_clean"],
            "allocator_spec": _allocator_spec_metadata(),
            "active_multi_symbol_universe_id": ACTIVE_MULTI_SYMBOL_UNIVERSE_ID,
            "active_multi_symbol_freeze_court": ACTIVE_MULTI_SYMBOL_FREEZE_COURT,
            "active_multi_symbol_freeze_classification": EARNED_PARALLEL_SLOT_FREEZE_CLASSIFICATION,
            "active_6h_context_overlay_court": ACTIVE_6H_CONTEXT_OVERLAY_COURT,
            "active_6h_context_overlay_classification": ACTIVE_6H_CONTEXT_OVERLAY_CLASSIFICATION,
            "active_6h_context_variant": ACTIVE_6H_CONTEXT_VARIANT,
            "active_6h_context_boost_multiplier": ACTIVE_6H_CONTEXT_BOOST_MULTIPLIER,
            "native_6h_execution_enabled": False,
            "six_h_context_only": True,
            "active_symbols": list(SYMBOLS),
            "latest_safe_1m_timestamp": latest_safe.isoformat(),
            "symbols_expected": len(SYMBOLS),
            "symbols_checked": len(symbol_results),
            "symbols_clean": sum(1 for row in symbol_results if row.get("quality", {}).get("clean")),
            "total_appended_rows": sum(int(row.get("appended_rows") or 0) for row in symbol_results),
            "total_new_decision_rows": appended_decisions,
            "strategy_evaluator": strategy_eval["summary"],
            "total_new_strategy_event_rows": len(strategy_event_rows),
            **trigger_email_summary,
            **daily_no_trade_digest_summary,
            "decision_ledger_duplicate_keys": duplicate_decision_keys,
            "decision_ledger": str(paths["decision_ledger"]),
            "symbol_results": symbol_results,
            "symbol_cap_metadata": cap_metadata,
            "historical_warm_start": {
                "enabled": bool(warm_start["manifest"]),
                "manifest_path": str(paths["historical_warm_start_manifest"]),
                "classification": warm_start["manifest"].get("final_classification", ""),
                "warmup_context_only": bool(warm_start["manifest"].get("warmup_context_only", False)),
                "decision_start_by_symbol": {
                    symbol: value.isoformat() for symbol, value in decision_start_by_symbol.items()
                },
            },
            "gate": {
                "may_install_multi_symbol_scheduler_now": False,
                "may_replace_btc_scheduler": False,
                "may_enable_paper_trading": False,
                "may_enable_live_trading": False,
                "may_create_order_or_broker_path": False,
                "paper_validation_ready": False,
                "next_required_court": "MULTI_SYMBOL_SIX_MONTH_FORWARD_EVIDENCE_COURT_RESEARCH_ONLY",
            },
            **SAFETY_FLAGS,
        }
        checkpoint = {
            "updated_at_utc": summary["created_at_utc"],
            "latest_safe_1m_timestamp": summary["latest_safe_1m_timestamp"],
            "allocator_spec_id": EARNED_PARALLEL_SLOT_SPEC_ID,
            "allocator_freeze_classification": EARNED_PARALLEL_SLOT_FREEZE_CLASSIFICATION,
            "six_h_context_overlay_court": ACTIVE_6H_CONTEXT_OVERLAY_COURT,
            "six_h_context_variant": ACTIVE_6H_CONTEXT_VARIANT,
            "native_6h_execution_enabled": False,
            "six_h_context_only": True,
            "latest_runtime_timestamp_by_symbol": {
                row["symbol"]: row.get("quality", {}).get("last_timestamp") for row in symbol_results
            },
            "decision_keys_recorded": len(existing_keys),
            "historical_warm_start": summary["historical_warm_start"],
            **SAFETY_FLAGS,
        }
        idempotency = {
            "immediate_rerun_new_rows_expected_if_no_new_public_candles": 0,
            "decision_ledger_duplicate_keys": duplicate_decision_keys,
            "lock_overlap_prevention": True,
            **SAFETY_FLAGS,
        }
        _write_json(paths["status"], summary)
        _write_json(config.output_root / "multi_symbol_forward_runtime_summary.json", summary)
        _write_json(paths["checkpoint"], checkpoint)
        _write_json(paths["allocator_state"], {"updated_at_utc": summary["created_at_utc"], **_allocator_spec_metadata(), **SAFETY_FLAGS})
        _write_json(paths["symbol_quality"], quality_rows)
        _write_json(paths["catchup_report"], {"symbol_results": symbol_results, **SAFETY_FLAGS})
        _write_json(paths["idempotency"], idempotency)
        return summary
    except Exception as exc:  # noqa: BLE001
        summary = {
            "runtime_name": "MULTI_SYMBOL_FORWARD_RUNTIME_RESEARCH_ONLY",
            "created_at_utc": _now(config).isoformat(),
            "status_color": STATUS_RED,
            "status_reasons": ["multi_symbol_forward_runtime_exception"],
            "error": f"{type(exc).__name__}: {exc}",
            "gate": {
                "may_install_multi_symbol_scheduler_now": False,
                "may_replace_btc_scheduler": False,
                "may_enable_paper_trading": False,
                "may_enable_live_trading": False,
                "may_create_order_or_broker_path": False,
                "paper_validation_ready": False,
            },
            **SAFETY_FLAGS,
        }
        _write_json(paths["status"], summary)
        return summary
    finally:
        _release_lock(paths["lock"], lock_fd)


def _decision_duplicate_count(path: Path) -> int:
    keys = list(_existing_decision_keys(path))
    if not path.exists() or path.stat().st_size == 0:
        return 0
    with path.open(newline="", encoding="utf-8") as handle:
        all_keys = [row.get("decision_key", "") for row in csv.DictReader(handle) if row.get("decision_key")]
    return len(all_keys) - len(set(all_keys))


def status(config: MultiSymbolForwardRuntimeConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    _ensure_dirs(config.output_root)
    paths = _paths(config.output_root)
    existing = _read_json(paths["status"], {})
    if not existing:
        existing = {
            "runtime_name": "MULTI_SYMBOL_FORWARD_RUNTIME_RESEARCH_ONLY",
            "created_at_utc": _now(config).isoformat(),
            "status_color": STATUS_YELLOW,
            "status_reasons": ["runtime_has_not_run_yet"],
            **SAFETY_FLAGS,
        }
    existing["decision_ledger_duplicate_keys"] = _decision_duplicate_count(paths["decision_ledger"])
    existing["status_checked_at_utc"] = _now(config).isoformat()
    return existing


def evidence_check(config: MultiSymbolForwardRuntimeConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    from structural_compounding_lab.diagnostics.multi_symbol_six_month_forward_evidence_court import (
        SixMonthForwardEvidenceConfig,
        run as run_evidence_court,
    )

    return run_evidence_court(
        SixMonthForwardEvidenceConfig(
            project_root=config.project_root,
            package_root=config.package_root,
            public_fetch_root=config.output_root,
            reduced_cap_root=config.reduced_cap_root,
            output_root=config.package_root / "output" / "multi_symbol_six_month_forward_evidence_court_001",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Research-only multi-symbol forward runtime.")
    parser.add_argument("--mode", choices=sorted(ALLOWED_MODES), default="run_once")
    parser.add_argument("--data-root", default="data_storage")
    parser.add_argument("--reduced-cap-root", default="structural_compounding_lab/output/multi_symbol_btc_exact_fill_cap_calibration_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    parser.add_argument("--seed-tail-rows", type=int, default=1440)
    parser.add_argument("--max-catchup-minutes", type=int, default=10080)
    args = parser.parse_args()
    root = project_root()
    config = MultiSymbolForwardRuntimeConfig(
        project_root=root,
        package_root=package_root(),
        data_root=resolve_project_path(args.data_root),
        reduced_cap_root=resolve_project_path(args.reduced_cap_root),
        output_root=resolve_project_path(args.output_dir),
        seed_tail_rows=args.seed_tail_rows,
        max_catchup_minutes=args.max_catchup_minutes,
    )
    if args.mode == "run_once":
        payload = run_once(config)
    elif args.mode == "status":
        payload = status(config)
    else:
        payload = evidence_check(config)
    print(json.dumps(_round_payload(payload), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
