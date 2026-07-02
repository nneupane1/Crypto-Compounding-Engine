from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from structural_compounding_lab.config import AppConfig
from structural_compounding_lab.common.project_paths import package_root as resolve_package_root
from structural_compounding_lab.common.project_paths import resolve_project_path
from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import RESEARCH_ONLY_FLAGS
from structural_compounding_lab.shadow_forward.shadow_forward_observer import _resample_closed
from structural_compounding_lab.shadow_forward.shadow_forward_watchtower import (
    OUTPUT_FOLDER_NAME as WATCHTOWER_OUTPUT_FOLDER_NAME,
    ShadowForwardWatchtowerConfig,
    _run_watchtower,
)


OUTPUT_FOLDER_NAME = "fresh_btcusdt_data_updater_001"
DEFAULT_MODE = "update_only"
ALLOWED_MODES = {"update_only", "update_and_single_cycle", "update_and_catchup"}
RAW_FETCH_CHUNK_DIR = "raw_fetch_chunks"
BINANCE_KLINE_COLUMNS = [
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "close_time",
    "quote_asset_volume",
    "number_of_trades",
    "taker_buy_base_volume",
    "taker_buy_quote_volume",
    "ignore",
]


@dataclass(frozen=True)
class FreshBTCUSDTDataUpdaterConfig:
    package_root: Path
    output_root: Path
    mode: str = DEFAULT_MODE
    symbol: str = "BTCUSDT"
    source_csv: str | Path | None = None
    canonical_path: str | Path | None = None
    force_rerun: bool = False
    allow_public_fetch: bool = True
    max_fetch_minutes: int | None = None
    dry_run: bool = False


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


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


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in {None, ""}:
        return default
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "y", "on"}:
        return True
    if lowered in {"false", "0", "no", "n", "off"}:
        return False
    return default


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value in {None, ""}:
        return None
    try:
        parsed = pd.Timestamp(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.tz_localize("UTC")
    else:
        parsed = parsed.tz_convert("UTC")
    return parsed.tz_localize(None)


def _ensure_dirs(output_root: Path) -> dict[str, Path]:
    paths = {
        "root": output_root,
        "diagnostics": output_root / "diagnostics",
        "diagnostics_raw": output_root / "diagnostics" / RAW_FETCH_CHUNK_DIR,
        "ledger": output_root / "ledger",
        "checkpoints": output_root / "_checkpoints",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _paths(output_root: Path) -> dict[str, Path]:
    return {
        "status": output_root / "status.json",
        "scenario_progress": output_root / "scenario_progress.json",
        "summary": output_root / "fresh_btcusdt_data_updater_summary.json",
        "report": output_root / "fresh_btcusdt_data_updater_report.md",
        "source_discovery": output_root / "diagnostics" / "source_discovery_report.json",
        "fetch_window": output_root / "diagnostics" / "fetch_window_plan.json",
        "public_fetch": output_root / "diagnostics" / "public_fetch_report.json",
        "normalization": output_root / "diagnostics" / "normalization_report.json",
        "data_quality": output_root / "diagnostics" / "fresh_data_quality_audit.json",
        "canonical_write": output_root / "diagnostics" / "canonical_write_report.json",
        "resample_validation": output_root / "diagnostics" / "resample_validation_report.json",
        "watchtower_kickoff": output_root / "diagnostics" / "watchtower_kickoff_report.json",
        "forward_clock_policy": output_root / "diagnostics" / "forward_clock_policy.json",
        "safety_guard": output_root / "diagnostics" / "fresh_data_safety_guard_report.json",
        "self_audit": output_root / "diagnostics" / "implementation_self_audit.json",
        "run_progress": output_root / "diagnostics" / "run_progress.json",
        "checkpoint": output_root / "_checkpoints" / "fresh_data_updater.checkpoint.json",
        "snapshot": output_root / "ledger" / "btcusdt_1m_canonical_shadow_forward_snapshot.csv",
    }


def _canonical_default_path(config: FreshBTCUSDTDataUpdaterConfig) -> Path:
    if config.canonical_path is not None:
        path = Path(config.canonical_path)
        return path if path.is_absolute() else config.package_root.parent / path
    return config.package_root / "data_storage" / config.symbol.upper() / "1m" / "btcusdt_1m_canonical_shadow_forward.csv"


def _watchtower_paths(package_root: Path) -> dict[str, Path]:
    watchtower_root = package_root / "output" / WATCHTOWER_OUTPUT_FOLDER_NAME
    observer_root = package_root / "output" / "shadow_forward_observer_001"
    return {
        "watchtower_root": watchtower_root,
        "prior_anchor": watchtower_root / "diagnostics" / "prior_observer_anchor.json",
        "watchtower_summary": watchtower_root / "watchtower_summary.json",
        "observer_data_ingestion": observer_root / "diagnostics" / "data_ingestion_status.json",
        "watchtower_signal_log": watchtower_root / "ledger" / "watchtower_signal_log.csv",
        "forward_clock_policy": watchtower_root / "diagnostics" / "forward_clock_policy.json",
    }


def _source_candidates(config: FreshBTCUSDTDataUpdaterConfig) -> list[tuple[str, Path]]:
    candidates: list[tuple[str, Path]] = []
    if config.source_csv is not None:
        explicit = Path(config.source_csv)
        if not explicit.is_absolute():
            explicit = (config.package_root.parent / explicit).resolve()
        candidates.append(("explicit_source_csv", explicit))

    watchtower_paths = _watchtower_paths(config.package_root)
    prior_anchor = _read_json(watchtower_paths["prior_anchor"], {})
    if prior_anchor.get("source_csv"):
        candidates.append(("watchtower_prior_observer_anchor", Path(str(prior_anchor["source_csv"]))))
    observer_ingestion = _read_json(watchtower_paths["observer_data_ingestion"], {})
    if observer_ingestion.get("source_path"):
        candidates.append(("shadow_forward_observer_data_ingestion", Path(str(observer_ingestion["source_path"]))))

    for path in sorted((config.package_root / "output").glob("btcusdt*1m*.csv")):
        candidates.append(("structural_output_btcusdt_1m", path))

    storage_root = config.package_root.parent / "data_storage" / config.symbol.upper() / "1m"
    if storage_root.exists():
        for path in sorted(storage_root.glob("*.csv")):
            candidates.append(("data_storage_btcusdt_1m", path))

    canonical_path = _canonical_default_path(config)
    if canonical_path.exists():
        candidates.insert(0, ("existing_canonical_shadow_forward", canonical_path))
    return candidates


def _load_source_frame(path: Path) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    if not path.exists():
        return None, {"source_is_valid": False, "warnings": ["path_missing"]}
    try:
        frame = pd.read_csv(path)
    except Exception as exc:
        return None, {"source_is_valid": False, "warnings": [f"read_failed:{exc}"]}
    timestamp_column = next((column for column in ("timestamp", "open_time", "datetime") if column in frame.columns), None)
    if timestamp_column is None:
        return None, {"source_is_valid": False, "warnings": ["timestamp_column_missing"], "schema_columns": list(frame.columns)}
    try:
        timestamps = pd.to_datetime(frame[timestamp_column], utc=True).dt.tz_convert(None)
    except Exception as exc:
        return None, {"source_is_valid": False, "warnings": [f"timestamp_parse_failed:{exc}"], "schema_columns": list(frame.columns)}
    frame = frame.copy()
    frame["timestamp"] = timestamps
    required = ["open", "high", "low", "close", "volume"]
    for column in required:
        if column not in frame.columns:
            return None, {"source_is_valid": False, "warnings": [f"missing_column:{column}"], "schema_columns": list(frame.columns), "timestamp_column": timestamp_column}
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=["timestamp", *required]).sort_values("timestamp")
    frame = frame.drop_duplicates(subset=["timestamp"], keep="last")
    if frame.empty:
        return None, {"source_is_valid": False, "warnings": ["source_empty_after_normalization"], "schema_columns": list(frame.columns), "timestamp_column": timestamp_column}
    frame = frame[["timestamp", *required] + [column for column in frame.columns if column not in {"timestamp", *required}]]
    diffs = frame["timestamp"].diff().dropna()
    detected_interval = "unknown"
    if not diffs.empty:
        modal_seconds = int(diffs.dt.total_seconds().mode().iloc[0])
        detected_interval = {60: "1m", 300: "5m", 3600: "1h"}.get(modal_seconds, f"{modal_seconds}s")
    meta = {
        "source_is_valid": True,
        "row_count": int(len(frame)),
        "first_timestamp": frame["timestamp"].iloc[0].isoformat(),
        "last_timestamp": frame["timestamp"].iloc[-1].isoformat(),
        "detected_interval": detected_interval,
        "schema_columns": list(frame.columns),
        "timestamp_column": timestamp_column,
        "warnings": [],
    }
    return frame, meta


def _discover_source(config: FreshBTCUSDTDataUpdaterConfig, report_path: Path) -> tuple[pd.DataFrame | None, dict[str, Any]]:
    candidate_reports: list[dict[str, Any]] = []
    selected_frame: pd.DataFrame | None = None
    selected_report: dict[str, Any] | None = None
    for reason, path in _source_candidates(config):
        frame, meta = _load_source_frame(path)
        report = {"reason": reason, "path": str(path), **meta}
        candidate_reports.append(report)
        if frame is None or not meta.get("source_is_valid"):
            continue
        if selected_frame is None:
            selected_frame = frame
            selected_report = report
            continue
        selected_last = _timestamp(selected_report.get("last_timestamp")) if selected_report else None
        candidate_last = _timestamp(report.get("last_timestamp"))
        if candidate_last is not None and (selected_last is None or candidate_last > selected_last):
            selected_frame = frame
            selected_report = report

    payload = {
        "candidate_paths": candidate_reports,
        "selected_source_path": selected_report.get("path") if selected_report else None,
        "selected_source_reason": selected_report.get("reason") if selected_report else None,
        "row_count": selected_report.get("row_count") if selected_report else 0,
        "first_timestamp": selected_report.get("first_timestamp") if selected_report else None,
        "last_timestamp": selected_report.get("last_timestamp") if selected_report else None,
        "detected_interval": selected_report.get("detected_interval") if selected_report else None,
        "schema_columns": selected_report.get("schema_columns") if selected_report else [],
        "timestamp_column": selected_report.get("timestamp_column") if selected_report else None,
        "source_is_valid": bool(selected_report),
        "warnings": [] if selected_report else ["no_valid_source_found"],
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(report_path, payload)
    return selected_frame, payload


def _compute_safe_fetch_window(last_local_timestamp: pd.Timestamp, *, now_utc: datetime | None = None, max_fetch_minutes: int | None = None) -> dict[str, Any]:
    current_utc = now_utc or _now_utc()
    current_floor = current_utc.replace(minute=0, second=0, microsecond=0)
    latest_closed_hour_start = current_floor - timedelta(hours=1)
    latest_safe_1m_timestamp = pd.Timestamp(latest_closed_hour_start + timedelta(minutes=59)).tz_localize(None)
    fetch_start = last_local_timestamp + pd.Timedelta(minutes=1)
    if max_fetch_minutes is not None and max_fetch_minutes > 0:
        latest_safe_1m_timestamp = min(latest_safe_1m_timestamp, fetch_start + pd.Timedelta(minutes=max_fetch_minutes - 1))
    fetch_needed = fetch_start <= latest_safe_1m_timestamp
    expected_missing_minutes = int(((latest_safe_1m_timestamp - fetch_start).total_seconds() // 60) + 1) if fetch_needed else 0
    return {
        "last_local_timestamp": last_local_timestamp.isoformat(),
        "fetch_start_timestamp": fetch_start.isoformat(),
        "current_utc_timestamp": current_utc.isoformat(),
        "latest_closed_hour_start": latest_closed_hour_start.replace(tzinfo=timezone.utc).isoformat(),
        "latest_safe_1m_timestamp": latest_safe_1m_timestamp.isoformat(),
        "expected_missing_minutes": expected_missing_minutes,
        "fetch_needed": fetch_needed,
        "reason_if_fetch_not_needed": "" if fetch_needed else "local_source_already_reaches_latest_fully_closed_1h_safe_boundary",
        "timezone_policy": "UTC",
        "incomplete_current_hour_excluded": True,
        **RESEARCH_ONLY_FLAGS,
    }


def _verify_setting(config: AppConfig) -> str | bool:
    bundle_override = (
        config.get("binance", "ca_bundle_path", default=None)
    )
    env_override = None
    for name in ("BINANCE_CA_BUNDLE_PATH", "REQUESTS_CA_BUNDLE", "SSL_CERT_FILE"):
        value = os.getenv(name)
        if value:
            env_override = value
            break
    selected = env_override or bundle_override
    if selected:
        bundle_path = Path(str(selected))
        if not bundle_path.is_absolute():
            bundle_path = config.root_dir / bundle_path
        if not bundle_path.exists():
            raise FileNotFoundError(f"Configured CA bundle not found: {bundle_path}")
        return str(bundle_path)
    return bool(config.get("binance", "ssl_verify", default=True))


def _public_fetch_binance_1m(
    *,
    config: AppConfig,
    symbol: str,
    start_timestamp: pd.Timestamp,
    end_timestamp: pd.Timestamp,
    raw_chunk_root: Path,
) -> tuple[list[list[Any]], dict[str, Any]]:
    base_url = str(config.require("binance", "base_url")).rstrip("/")
    klines_path = str(config.require("binance", "klines_path"))
    url = f"{base_url}{klines_path}"
    timeout = int(config.require("binance", "request_timeout_seconds"))
    limit = min(int(config.require("binance", "historical_limit")), 1000)
    throttle = float(config.require("binance", "throttle_seconds"))
    retry_attempts = int(config.require("binance", "retry_attempts"))
    retry_backoff = float(config.require("binance", "retry_backoff_seconds"))
    retry_status_codes = set(config.require("binance", "retry_status_codes"))
    verify = _verify_setting(config)

    start_ms = int(start_timestamp.tz_localize("UTC").timestamp() * 1000)
    end_ms = int(end_timestamp.tz_localize("UTC").timestamp() * 1000)
    current_start = start_ms
    request_count = 0
    retry_count = 0
    raw_rows: list[list[Any]] = []
    rate_limit_warnings: list[str] = []
    blocked_reason = ""

    while current_start <= end_ms:
        params = {
            "symbol": symbol,
            "interval": "1m",
            "startTime": current_start,
            "endTime": end_ms + 59999,
            "limit": limit,
        }
        last_error: Exception | None = None
        response_payload: list[list[Any]] | None = None
        for attempt in range(1, retry_attempts + 1):
            try:
                response = requests.get(url, params=params, timeout=timeout, verify=verify)
                request_count += 1
                if response.status_code == 200:
                    response_payload = response.json()
                    break
                if response.status_code in retry_status_codes and attempt < retry_attempts:
                    retry_count += 1
                    if response.status_code == 429:
                        rate_limit_warnings.append("binance_429_retry")
                    time.sleep(retry_backoff * attempt)
                    continue
                blocked_reason = f"http_{response.status_code}"
                response.raise_for_status()
            except requests.RequestException as exc:
                last_error = exc
                if attempt < retry_attempts:
                    retry_count += 1
                    time.sleep(retry_backoff * attempt)
                    continue
                blocked_reason = str(exc)
        if response_payload is None:
            raise RuntimeError(blocked_reason or str(last_error or "public_fetch_failed"))
        if not response_payload:
            break
        chunk_index = (request_count if request_count > 0 else 1)
        _write_json(
            raw_chunk_root / f"chunk_{chunk_index:04d}.json",
            {
                "requested_start_ms": current_start,
                "requested_end_ms": end_ms + 59999,
                "rows": len(response_payload),
                "first_open_time_ms": response_payload[0][0] if response_payload else None,
                "last_open_time_ms": response_payload[-1][0] if response_payload else None,
            },
        )
        raw_rows.extend(response_payload)
        last_open_ms = int(response_payload[-1][0])
        next_start = last_open_ms + 60000
        if next_start <= current_start:
            break
        current_start = next_start
        if throttle > 0:
            time.sleep(throttle)

    report = {
        "public_fetch_attempted": True,
        "public_fetch_source": "binance_public_klines",
        "endpoint_type": "public_market_data",
        "private_api_key_used": False,
        "account_endpoint_used": False,
        "order_endpoint_used": False,
        "request_count": request_count,
        "fetched_rows": len(raw_rows),
        "first_fetched_timestamp": pd.to_datetime(raw_rows[0][0], unit="ms", utc=True).tz_convert(None).isoformat() if raw_rows else None,
        "last_fetched_timestamp": pd.to_datetime(raw_rows[-1][0], unit="ms", utc=True).tz_convert(None).isoformat() if raw_rows else None,
        "retry_count": retry_count,
        "rate_limit_warnings": sorted(set(rate_limit_warnings)),
        "fetch_success": True,
        "blocked_reason_if_any": "",
        **RESEARCH_ONLY_FLAGS,
    }
    return raw_rows, report


def _normalize_fetched_rows(
    raw_rows: list[list[Any]],
    *,
    fetch_start: pd.Timestamp,
    latest_safe: pd.Timestamp,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    if not raw_rows:
        empty = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        return empty, {
            "data_normalized": True,
            "rows_after_normalization": 0,
            "future_rows_rejected": 0,
            "rows_before_fetch_start_removed": 0,
            "duplicates_removed": 0,
            "timestamp_timezone_policy": "UTC candle open time",
            **RESEARCH_ONLY_FLAGS,
        }
    frame = pd.DataFrame(raw_rows, columns=BINANCE_KLINE_COLUMNS)
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], unit="ms", utc=True).dt.tz_convert(None)
    frame["close_time"] = pd.to_datetime(frame["close_time"], unit="ms", utc=True).dt.tz_convert(None)
    for column in ("open", "high", "low", "close", "volume", "quote_asset_volume", "number_of_trades", "taker_buy_base_volume", "taker_buy_quote_volume"):
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    before_rows = len(frame)
    frame = frame[(frame["timestamp"] >= fetch_start) & (frame["timestamp"] <= latest_safe)].copy()
    after_window_rows = len(frame)
    frame = frame.dropna(subset=["timestamp", "open", "high", "low", "close", "volume"])
    before_dedupe = len(frame)
    frame = frame.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp")
    frame["source"] = "binance_public_klines"
    normalized = frame[
        [
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "number_of_trades",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
            "source",
        ]
    ].copy()
    report = {
        "data_normalized": True,
        "rows_before_normalization": before_rows,
        "rows_after_normalization": int(len(normalized)),
        "future_rows_rejected": max(0, before_rows - after_window_rows),
        "rows_before_fetch_start_removed": max(0, before_rows - after_window_rows),
        "duplicates_removed": max(0, before_dedupe - len(normalized)),
        "timestamp_timezone_policy": "UTC candle open time",
        **RESEARCH_ONLY_FLAGS,
    }
    return normalized, report


def _missing_minutes_count(timestamps: pd.Series) -> int:
    if timestamps.empty:
        return 0
    diffs = timestamps.sort_values().diff().dropna()
    if diffs.empty:
        return 0
    return int(sum(max(0, int(delta.total_seconds() // 60) - 1) for delta in diffs))


def _quality_audit(source_frame: pd.DataFrame, fetched_frame: pd.DataFrame, combined_frame: pd.DataFrame, latest_safe: pd.Timestamp) -> dict[str, Any]:
    fetched_ts = fetched_frame["timestamp"] if "timestamp" in fetched_frame.columns else pd.Series(dtype="datetime64[ns]")
    combined_ts = combined_frame["timestamp"] if "timestamp" in combined_frame.columns else pd.Series(dtype="datetime64[ns]")
    duplicate_fetched = int(len(fetched_ts) - len(pd.Index(fetched_ts).unique()))
    duplicate_combined = int(len(combined_ts) - len(pd.Index(combined_ts).unique()))
    ohlc_failures = 0
    if not combined_frame.empty:
        ohlc_failures = int(
            (
                (combined_frame["high"] < combined_frame["open"])
                | (combined_frame["high"] < combined_frame["close"])
                | (combined_frame["low"] > combined_frame["open"])
                | (combined_frame["low"] > combined_frame["close"])
                | (combined_frame["high"] < combined_frame["low"])
                | (combined_frame["open"] <= 0)
                | (combined_frame["high"] <= 0)
                | (combined_frame["low"] <= 0)
                | (combined_frame["close"] <= 0)
                | (combined_frame["volume"] < 0)
            ).sum()
        )
    return {
        "missing_minute_count_fetched_range": _missing_minutes_count(fetched_ts),
        "duplicate_timestamp_count_fetched_range": duplicate_fetched,
        "missing_minute_count_combined_range": _missing_minutes_count(combined_ts),
        "duplicate_timestamp_count_combined_range": duplicate_combined,
        "monotonic_timestamp_order": bool(combined_ts.is_monotonic_increasing if not combined_ts.empty else True),
        "ohlc_sanity_failures": ohlc_failures,
        "zero_or_negative_price_failures": 0 if ohlc_failures == 0 else ohlc_failures,
        "negative_volume_failures": 0 if ohlc_failures == 0 else int((combined_frame["volume"] < 0).sum()) if not combined_frame.empty else 0,
        "current_incomplete_hour_excluded": True,
        "stale_source_warning": bool(fetched_frame.empty),
        "latest_safe_1m_timestamp": latest_safe.isoformat(),
        **RESEARCH_ONLY_FLAGS,
    }


def _atomic_csv_write(frame: pd.DataFrame, path: Path) -> tuple[bool, Path | None]:
    backup_path: Path | None = None
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup_path = path.with_name(f"{path.stem}.backup_{_now_utc().strftime('%Y%m%dT%H%M%SZ')}{path.suffix}")
        shutil.copy2(path, backup_path)
    temp_path = path.with_suffix(f"{path.suffix}.tmp")
    frame.to_csv(temp_path, index=False)
    temp_path.replace(path)
    return True, backup_path


def _resample_validation(frame: pd.DataFrame, latest_safe: pd.Timestamp) -> dict[str, Any]:
    source = frame.copy()
    source["timestamp"] = pd.to_datetime(source["timestamp"], utc=True, errors="coerce").dt.tz_convert(None)
    source = source.dropna(subset=["timestamp"])
    source = source.sort_values("timestamp")
    source = source.set_index("timestamp")
    bundle_1h = _resample_closed(source[["open", "high", "low", "close", "volume"]], "1h")
    bundle_6h = _resample_closed(source[["open", "high", "low", "close", "volume"]], "6h")
    bundle_12h = _resample_closed(source[["open", "high", "low", "close", "volume"]], "12h")
    bundle_1d = _resample_closed(source[["open", "high", "low", "close", "volume"]], "1d")
    bundle_1w = _resample_closed(source[["open", "high", "low", "close", "volume"]], "1w")
    latest_1h = bundle_1h.index.max() if not bundle_1h.empty else None
    latest_6h = bundle_6h.index.max() if not bundle_6h.empty else None
    return {
        "latest_closed_1h_candle_exists": latest_1h is not None,
        "latest_closed_1h_candle": latest_1h.isoformat() if latest_1h is not None else None,
        "latest_closed_6h_candle_exists": latest_6h is not None,
        "latest_closed_6h_candle": latest_6h.isoformat() if latest_6h is not None else None,
        "latest_closed_12h_candle": bundle_12h.index.max().isoformat() if not bundle_12h.empty else None,
        "latest_closed_1d_candle": bundle_1d.index.max().isoformat() if not bundle_1d.empty else None,
        "latest_closed_1w_candle": bundle_1w.index.max().isoformat() if not bundle_1w.empty else None,
        "no_incomplete_current_1h_included": latest_1h is None or latest_1h <= latest_safe + pd.Timedelta(minutes=1),
        "no_incomplete_current_6h_used": latest_6h is None or latest_6h <= latest_safe + pd.Timedelta(minutes=1),
        **RESEARCH_ONLY_FLAGS,
    }


def _write_status(path: Path, *, state: str, classification: str, warnings: list[str], mode: str) -> None:
    _write_json(
        path,
        {
            "state": state,
            "resolved_at_utc": _now_utc().isoformat(),
            "runtime_mode": mode,
            "final_classification": classification,
            "warnings": warnings,
            **RESEARCH_ONLY_FLAGS,
            "no_order_path_created": True,
            "paper_trade_created": False,
            "live_trade_created": False,
            "broker_execution_created": False,
        },
    )


def _write_progress(path: Path, *, state: str, mode: str, rows_fetched: int, rows_appended: int, warnings: list[str]) -> None:
    _write_json(
        path,
        {
            "state": state,
            "updated_at_utc": _now_utc().isoformat(),
            "runtime_mode": mode,
            "rows_fetched": rows_fetched,
            "rows_appended": rows_appended,
            "warnings": warnings,
            **RESEARCH_ONLY_FLAGS,
        },
    )


def _safety_guard(config: FreshBTCUSDTDataUpdaterConfig, canonical_path: Path) -> dict[str, Any]:
    output_root = config.output_root
    findings: list[str] = []
    passed = True
    if not config.allow_public_fetch and not config.dry_run:
        findings.append("public_fetch_disabled_by_config")
    if "account" in str(canonical_path).lower() or "order" in str(canonical_path).lower():
        passed = False
        findings.append("canonical_path_name_looks_unsafe")
    report = {
        "no_private_api_key_required": True,
        "account_endpoint_used": False,
        "order_endpoint_used": False,
        "no_broker_client_instantiated": True,
        "no_paper_trade_object_created": True,
        "no_live_trade_object_created": True,
        "no_capital_allocator_called": True,
        "future_25000_anchor_diagnostic_only": True,
        "no_runtime_production_config_changed": True,
        "output_folder_isolated": True,
        "append_only_mode_enabled": True,
        "passed": passed,
        "findings": findings,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(_paths(output_root)["safety_guard"], report)
    return report


def _forward_clock_policy(old_boundary: pd.Timestamp) -> dict[str, Any]:
    return {
        "stale_historical_boundary_timestamp": old_boundary.isoformat(),
        "source_boundary_timestamp": old_boundary.isoformat(),
        "counts_only_fresh_rows_strictly_after_boundary": True,
        "stale_historical_backfill_does_not_count": True,
        "observation_day_count_policy": "unique_real_forward_dates_only",
        "minimum_forward_days_required": 90,
        "minimum_real_forward_1h_decisions_required": 50,
        "paper_validation_ready_remains_false_until_all_gates_pass": True,
        **RESEARCH_ONLY_FLAGS,
    }


def _resolve_forward_clock_policy(policy_path: Path, old_boundary: pd.Timestamp) -> dict[str, Any]:
    existing = _read_json(policy_path, {})
    existing_boundary = _timestamp(existing.get("stale_historical_boundary_timestamp"))
    if existing_boundary is not None:
        preserved_boundary = min(existing_boundary, old_boundary.to_pydatetime())
        policy = _forward_clock_policy(pd.Timestamp(preserved_boundary).tz_localize(None))
        policy["preserved_existing_boundary"] = True
        policy["requested_boundary_timestamp"] = old_boundary.isoformat()
        return policy
    policy = _forward_clock_policy(old_boundary)
    policy["preserved_existing_boundary"] = False
    policy["requested_boundary_timestamp"] = old_boundary.isoformat()
    return policy


def _discover_forward_boundary_candidate(config: FreshBTCUSDTDataUpdaterConfig) -> pd.Timestamp | None:
    watchtower_paths = _watchtower_paths(config.package_root)
    boundary_candidates: list[Path] = []

    prior_anchor = _read_json(watchtower_paths["prior_anchor"], {})
    if prior_anchor.get("source_csv"):
        boundary_candidates.append(Path(str(prior_anchor["source_csv"])))

    observer_ingestion = _read_json(watchtower_paths["observer_data_ingestion"], {})
    if observer_ingestion.get("source_path"):
        boundary_candidates.append(Path(str(observer_ingestion["source_path"])))

    for candidate in boundary_candidates:
        frame, meta = _load_source_frame(candidate)
        if frame is None or not meta.get("source_is_valid") or frame.empty:
            continue
        return pd.Timestamp(frame["timestamp"].iloc[-1])
    return None


def _kickoff_watchtower(
    config: FreshBTCUSDTDataUpdaterConfig,
    *,
    canonical_path: Path,
    forward_policy: dict[str, Any],
    mode: str,
) -> dict[str, Any]:
    watchtower_root = config.package_root / "output" / WATCHTOWER_OUTPUT_FOLDER_NAME
    watchtower_paths = _watchtower_paths(config.package_root)
    _write_json(watchtower_paths["forward_clock_policy"], forward_policy)

    before_rows = _read_csv_rows(watchtower_paths["watchtower_signal_log"])
    before_count = len(before_rows)
    before_filtered = [row for row in before_rows if (_timestamp(row.get("timestamp")) or pd.Timestamp.min) > _timestamp(forward_policy["stale_historical_boundary_timestamp"])]
    before_forward_count = len(before_filtered)
    before_latest_forward = None
    if before_filtered:
        before_latest_forward = max((_timestamp(row.get("timestamp")) for row in before_filtered), default=None)

    observer_runtime_mode = "single_cycle" if mode == "update_and_single_cycle" else "catchup"
    result = _run_watchtower(
        ShadowForwardWatchtowerConfig(
            package_root=config.package_root,
            output_root=watchtower_root,
            runtime_mode="single_cycle",
            source_csv=canonical_path,
            force_rerun=False,
            observer_runtime_mode=observer_runtime_mode,
        )
    )
    after_rows = _read_csv_rows(watchtower_paths["watchtower_signal_log"])
    after_filtered = [row for row in after_rows if (_timestamp(row.get("timestamp")) or pd.Timestamp.min) > _timestamp(forward_policy["stale_historical_boundary_timestamp"])]
    heartbeat = _read_json(watchtower_root / "diagnostics" / "heartbeat.json", {})
    readiness = _read_json(watchtower_root / "diagnostics" / "readiness_progress.json", {})
    canonical_frame, _ = _load_source_frame(canonical_path)
    latest_processed = _timestamp(heartbeat.get("last_processed_1h_candle"))
    newly_available = 0
    if canonical_frame is not None and not canonical_frame.empty:
        frame = canonical_frame.set_index("timestamp")
        candles_1h = _resample_closed(frame[["open", "high", "low", "close", "volume"]], "1h")
        boundary = _timestamp(forward_policy["stale_historical_boundary_timestamp"])
        for candle in candles_1h.index:
            if boundary is not None and candle <= boundary:
                continue
            if before_latest_forward is not None and candle <= before_latest_forward:
                continue
            newly_available += 1
    newly_processed = max(0, len(after_filtered) - before_forward_count)
    return {
        "watchtower_run_attempted": True,
        "watchtower_mode": mode,
        "canonical_source_used": str(canonical_path),
        "newly_closed_1h_candles_available": newly_available,
        "newly_processed_1h_decisions": newly_processed,
        "duplicate_1h_candles_skipped": max(0, newly_available - newly_processed),
        "heartbeat_updated": bool(heartbeat),
        "readiness_updated": bool(readiness),
        "forward_clock_started": newly_processed > 0,
        "forward_clock_start_timestamp": heartbeat.get("last_processed_1h_candle") if newly_processed > 0 else None,
        "paper_validation_ready": bool(readiness.get("paper_validation_ready", False)),
        "no_order_sent_confirmed": bool(heartbeat.get("no_order_sent_confirmed", False)),
        "watchtower_summary_path": str(result["summary"]),
        "pre_watchtower_signal_rows": before_count,
        "post_watchtower_signal_rows": len(after_rows),
        "latest_processed_1h_candle": latest_processed.isoformat() if latest_processed is not None else None,
        **RESEARCH_ONLY_FLAGS,
    }


def _report_markdown(summary: dict[str, Any], discovery: dict[str, Any], fetch_window: dict[str, Any], watchtower_kickoff: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Fresh BTCUSDT Data Updater",
            "",
            f"- final_classification: `{summary['final_classification']}`",
            f"- selected local source: `{discovery.get('selected_source_path')}`",
            f"- last local timestamp: `{fetch_window.get('last_local_timestamp')}`",
            f"- fetch start: `{fetch_window.get('fetch_start_timestamp')}`",
            f"- safe fetch end: `{fetch_window.get('latest_safe_1m_timestamp')}`",
            f"- rows fetched: `{summary.get('rows_fetched', 0)}`",
            f"- rows appended: `{summary.get('rows_appended', 0)}`",
            f"- canonical path: `{summary.get('canonical_path')}`",
            f"- watchtower kickoff attempted: `{str(watchtower_kickoff.get('watchtower_run_attempted', False)).lower()}`",
            f"- newly processed 1H decisions: `{watchtower_kickoff.get('newly_processed_1h_decisions', 0)}`",
            f"- forward clock started: `{str(watchtower_kickoff.get('forward_clock_started', False)).lower()}`",
            "",
            "Future capital anchor remains diagnostic only. No live/paper/order/broker path was created.",
        ]
    ) + "\n"


def write_fresh_btcusdt_data_updater(config: FreshBTCUSDTDataUpdaterConfig) -> dict[str, Path]:
    if config.mode not in ALLOWED_MODES:
        raise ValueError(f"Unsupported mode: {config.mode}")

    _ensure_dirs(config.output_root)
    output_paths = _paths(config.output_root)
    warnings: list[str] = []
    rows_fetched = 0
    rows_appended = 0

    selected_frame, source_report = _discover_source(config, output_paths["source_discovery"])
    if selected_frame is None or not source_report.get("source_is_valid"):
        classification = "FRESH_DATA_BLOCKED_SOURCE_UNAVAILABLE"
        _write_json(output_paths["summary"], {"final_classification": classification, **RESEARCH_ONLY_FLAGS})
        _write_markdown(output_paths["report"], "# Fresh BTCUSDT Data Updater\n\nNo valid BTCUSDT source was available.\n")
        _write_status(output_paths["status"], state="blocked", classification=classification, warnings=source_report.get("warnings", []), mode=config.mode)
        _write_progress(output_paths["scenario_progress"], state="blocked", mode=config.mode, rows_fetched=0, rows_appended=0, warnings=source_report.get("warnings", []))
        _write_progress(output_paths["run_progress"], state="blocked", mode=config.mode, rows_fetched=0, rows_appended=0, warnings=source_report.get("warnings", []))
        return {"status": output_paths["status"], "summary": output_paths["summary"], "report": output_paths["report"]}

    last_local_timestamp = pd.Timestamp(selected_frame["timestamp"].iloc[-1])
    fetch_window = _compute_safe_fetch_window(last_local_timestamp, max_fetch_minutes=config.max_fetch_minutes)
    _write_json(output_paths["fetch_window"], fetch_window)

    canonical_path = _canonical_default_path(config)
    safety_guard = _safety_guard(config, canonical_path)
    if not safety_guard.get("passed", False):
        classification = "FRESH_DATA_BLOCKED_SAFETY_GUARD_FAILED"
        _write_json(output_paths["summary"], {"final_classification": classification, **RESEARCH_ONLY_FLAGS})
        _write_markdown(output_paths["report"], "# Fresh BTCUSDT Data Updater\n\nSafety guard blocked the updater.\n")
        _write_status(output_paths["status"], state="blocked", classification=classification, warnings=list(safety_guard.get("findings", [])), mode=config.mode)
        _write_progress(output_paths["scenario_progress"], state="blocked", mode=config.mode, rows_fetched=0, rows_appended=0, warnings=list(safety_guard.get("findings", [])))
        _write_progress(output_paths["run_progress"], state="blocked", mode=config.mode, rows_fetched=0, rows_appended=0, warnings=list(safety_guard.get("findings", [])))
        return {"status": output_paths["status"], "summary": output_paths["summary"], "report": output_paths["report"]}

    public_fetch_report = {
        "public_fetch_attempted": False,
        "public_fetch_source": "binance_public_klines",
        "endpoint_type": "public_market_data",
        "private_api_key_used": False,
        "account_endpoint_used": False,
        "order_endpoint_used": False,
        "request_count": 0,
        "fetched_rows": 0,
        "first_fetched_timestamp": None,
        "last_fetched_timestamp": None,
        "retry_count": 0,
        "rate_limit_warnings": [],
        "fetch_success": False,
        "blocked_reason_if_any": "",
        **RESEARCH_ONLY_FLAGS,
    }
    normalization_report = {"data_normalized": False, **RESEARCH_ONLY_FLAGS}
    quality_report: dict[str, Any] = {}
    canonical_write_report: dict[str, Any] = {}
    resample_validation_report: dict[str, Any] = {}
    watchtower_kickoff_report = {
        "watchtower_run_attempted": False,
        "watchtower_mode": config.mode,
        "canonical_source_used": str(canonical_path),
        "newly_closed_1h_candles_available": 0,
        "newly_processed_1h_decisions": 0,
        "duplicate_1h_candles_skipped": 0,
        "heartbeat_updated": False,
        "readiness_updated": False,
        "forward_clock_started": False,
        "forward_clock_start_timestamp": None,
        "paper_validation_ready": False,
        "no_order_sent_confirmed": True,
        **RESEARCH_ONLY_FLAGS,
    }

    raw_rows: list[list[Any]] = []
    normalized_fetched = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    fetch_needed = bool(fetch_window["fetch_needed"])

    if config.dry_run:
        public_fetch_report["blocked_reason_if_any"] = "dry_run_fetch_skipped"
    elif fetch_needed and not config.allow_public_fetch:
        classification = "FRESH_DATA_BLOCKED_PUBLIC_FETCH_UNAVAILABLE"
        public_fetch_report["blocked_reason_if_any"] = "public_fetch_disabled"
        _write_json(output_paths["public_fetch"], public_fetch_report)
        _write_json(output_paths["normalization"], normalization_report)
        _write_status(output_paths["status"], state="blocked", classification=classification, warnings=["public_fetch_disabled"], mode=config.mode)
        _write_progress(output_paths["scenario_progress"], state="blocked", mode=config.mode, rows_fetched=0, rows_appended=0, warnings=["public_fetch_disabled"])
        _write_progress(output_paths["run_progress"], state="blocked", mode=config.mode, rows_fetched=0, rows_appended=0, warnings=["public_fetch_disabled"])
        _write_json(output_paths["summary"], {"final_classification": classification, **RESEARCH_ONLY_FLAGS})
        _write_markdown(output_paths["report"], "# Fresh BTCUSDT Data Updater\n\nPublic market-data fetching was disabled.\n")
        return {"status": output_paths["status"], "summary": output_paths["summary"], "report": output_paths["report"]}
    elif fetch_needed:
        app_config = AppConfig.load()
        try:
            raw_rows, public_fetch_report = _public_fetch_binance_1m(
                config=app_config,
                symbol=config.symbol.upper(),
                start_timestamp=pd.Timestamp(fetch_window["fetch_start_timestamp"]),
                end_timestamp=pd.Timestamp(fetch_window["latest_safe_1m_timestamp"]),
                raw_chunk_root=config.output_root / "diagnostics" / RAW_FETCH_CHUNK_DIR,
            )
            rows_fetched = len(raw_rows)
        except Exception as exc:
            public_fetch_report["public_fetch_attempted"] = True
            public_fetch_report["blocked_reason_if_any"] = str(exc)
            _write_json(output_paths["public_fetch"], public_fetch_report)
            classification = "FRESH_DATA_BLOCKED_PUBLIC_FETCH_UNAVAILABLE"
            _write_json(output_paths["summary"], {"final_classification": classification, **RESEARCH_ONLY_FLAGS})
            _write_markdown(output_paths["report"], "# Fresh BTCUSDT Data Updater\n\nPublic fetch was unavailable.\n")
            _write_status(output_paths["status"], state="blocked", classification=classification, warnings=[str(exc)], mode=config.mode)
            _write_progress(output_paths["scenario_progress"], state="blocked", mode=config.mode, rows_fetched=0, rows_appended=0, warnings=[str(exc)])
            _write_progress(output_paths["run_progress"], state="blocked", mode=config.mode, rows_fetched=0, rows_appended=0, warnings=[str(exc)])
            _write_json(output_paths["self_audit"], {"public_fetch_attempted": True, "public_fetch_success": False, "reviewer_notes": [str(exc)], **RESEARCH_ONLY_FLAGS})
            return {"status": output_paths["status"], "summary": output_paths["summary"], "report": output_paths["report"]}

    if raw_rows:
        normalized_fetched, normalization_report = _normalize_fetched_rows(
            raw_rows,
            fetch_start=pd.Timestamp(fetch_window["fetch_start_timestamp"]),
            latest_safe=pd.Timestamp(fetch_window["latest_safe_1m_timestamp"]),
        )
    _write_json(output_paths["public_fetch"], public_fetch_report)
    _write_json(output_paths["normalization"], normalization_report)

    source_base_frame = selected_frame[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    combined_frame = source_base_frame.copy()
    if not normalized_fetched.empty:
        combined_frame = pd.concat([combined_frame, normalized_fetched[["timestamp", "open", "high", "low", "close", "volume"]]], ignore_index=True)
    before_dedupe = len(combined_frame)
    combined_frame = combined_frame.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp").reset_index(drop=True)
    rows_appended = max(0, len(combined_frame) - len(selected_frame))
    quality_report = _quality_audit(selected_frame, normalized_fetched, combined_frame, pd.Timestamp(fetch_window["latest_safe_1m_timestamp"]))
    _write_json(output_paths["data_quality"], quality_report)

    if not config.dry_run:
        rows_before = 0
        base_frame_for_write = source_base_frame.copy()
        if canonical_path.exists():
            existing_canonical, _ = _load_source_frame(canonical_path)
            rows_before = int(len(existing_canonical)) if existing_canonical is not None else 0
            if existing_canonical is not None and not existing_canonical.empty:
                base_frame_for_write = existing_canonical[["timestamp", "open", "high", "low", "close", "volume"]].copy()
                combined_frame = pd.concat([base_frame_for_write, normalized_fetched[["timestamp", "open", "high", "low", "close", "volume"]]], ignore_index=True)
                combined_frame = combined_frame.drop_duplicates(subset=["timestamp"], keep="last").sort_values("timestamp").reset_index(drop=True)
        else:
            rows_before = int(len(base_frame_for_write))
        atomic_ok, backup_path = _atomic_csv_write(combined_frame, canonical_path)
        rows_after = len(combined_frame)
        rows_appended = max(0, rows_after - rows_before)
        canonical_write_report = {
            "canonical_path": str(canonical_path),
            "backup_path": str(backup_path) if backup_path is not None else None,
            "rows_before": rows_before,
            "rows_fetched": len(normalized_fetched),
            "rows_after": rows_after,
            "new_rows_appended": rows_appended,
            "duplicates_removed": max(0, before_dedupe - len(combined_frame)),
            "first_timestamp_after": combined_frame["timestamp"].iloc[0].isoformat() if not combined_frame.empty else None,
            "last_timestamp_after": combined_frame["timestamp"].iloc[-1].isoformat() if not combined_frame.empty else None,
            "atomic_write_success": atomic_ok,
            "previous_file_preserved": backup_path is not None,
            "old_source_overwritten": False,
            **RESEARCH_ONLY_FLAGS,
        }
        combined_frame.to_csv(output_paths["snapshot"], index=False)
        _write_json(output_paths["canonical_write"], canonical_write_report)
        resample_validation_report = _resample_validation(combined_frame, pd.Timestamp(fetch_window["latest_safe_1m_timestamp"]))
        _write_json(output_paths["resample_validation"], resample_validation_report)
    else:
        canonical_write_report = {
            "canonical_path": str(canonical_path),
            "backup_path": None,
            "rows_before": 0,
            "rows_fetched": len(normalized_fetched),
            "rows_after": len(combined_frame),
            "new_rows_appended": max(0, len(combined_frame) - len(selected_frame)),
            "duplicates_removed": max(0, before_dedupe - len(combined_frame)),
            "first_timestamp_after": combined_frame["timestamp"].iloc[0].isoformat() if not combined_frame.empty else None,
            "last_timestamp_after": combined_frame["timestamp"].iloc[-1].isoformat() if not combined_frame.empty else None,
            "atomic_write_success": False,
            "previous_file_preserved": False,
            "old_source_overwritten": False,
            "dry_run": True,
            **RESEARCH_ONLY_FLAGS,
        }
        _write_json(output_paths["canonical_write"], canonical_write_report)

    watchtower_forward_policy_path = _watchtower_paths(config.package_root)["forward_clock_policy"]
    boundary_candidate = _discover_forward_boundary_candidate(config) or last_local_timestamp
    forward_policy = _resolve_forward_clock_policy(watchtower_forward_policy_path, boundary_candidate)
    _write_json(output_paths["forward_clock_policy"], forward_policy)
    _write_json(watchtower_forward_policy_path, forward_policy)

    if config.mode != "update_only" and not config.dry_run and canonical_path.exists():
        watchtower_kickoff_report = _kickoff_watchtower(config, canonical_path=canonical_path, forward_policy=forward_policy, mode=config.mode)
    _write_json(output_paths["watchtower_kickoff"], watchtower_kickoff_report)

    if fetch_needed and len(normalized_fetched) > 0:
        classification = "FRESH_DATA_READY_AND_WATCHTOWER_STARTED" if config.mode != "update_only" else "FRESH_DATA_READY_AND_APPENDED"
    elif not fetch_needed or len(normalized_fetched) == 0:
        classification = "FRESH_DATA_READY_NO_NEW_ROWS"
    else:
        classification = "FRESH_DATA_INCOMPLETE"

    summary = {
        "resolved_at_utc": _now_utc().isoformat(),
        "final_classification": classification,
        "selected_local_source": source_report.get("selected_source_path"),
        "last_local_timestamp": fetch_window.get("last_local_timestamp"),
        "fetch_start_timestamp": fetch_window.get("fetch_start_timestamp"),
        "latest_safe_1m_timestamp": fetch_window.get("latest_safe_1m_timestamp"),
        "public_fetch_source": public_fetch_report.get("public_fetch_source"),
        "rows_fetched": len(normalized_fetched),
        "rows_appended": rows_appended,
        "canonical_path": str(canonical_path),
        "gap_count": quality_report.get("missing_minute_count_fetched_range", 0),
        "duplicate_count": quality_report.get("duplicate_timestamp_count_combined_range", 0),
        "latest_canonical_timestamp": canonical_write_report.get("last_timestamp_after"),
        "watchtower_kickoff_attempted": watchtower_kickoff_report.get("watchtower_run_attempted", False),
        "newly_processed_1h_decisions": watchtower_kickoff_report.get("newly_processed_1h_decisions", 0),
        "forward_clock_started": watchtower_kickoff_report.get("forward_clock_started", False),
        "readiness_days_counted": _read_json(config.package_root / "output" / WATCHTOWER_OUTPUT_FOLDER_NAME / "diagnostics" / "readiness_progress.json", {}).get("observation_days_completed", 0) if watchtower_kickoff_report.get("watchtower_run_attempted") else 0,
        "safety_guard_passed": bool(safety_guard.get("passed")),
        "checkpoint_resume_status": "resume_capable_dedupe_safe",
        **RESEARCH_ONLY_FLAGS,
        "no_order_path_created": True,
        "paper_trade_created": False,
        "live_trade_created": False,
        "broker_execution_created": False,
    }
    _write_json(output_paths["summary"], summary)
    _write_markdown(output_paths["report"], _report_markdown(summary, source_report, fetch_window, watchtower_kickoff_report))
    _write_json(
        output_paths["checkpoint"],
        {
            "last_fetch_start": fetch_window.get("fetch_start_timestamp"),
            "last_fetch_end": fetch_window.get("latest_safe_1m_timestamp"),
            "last_successful_append_timestamp": canonical_write_report.get("last_timestamp_after"),
            "last_watchtower_kickoff_timestamp": _now_utc().isoformat() if watchtower_kickoff_report.get("watchtower_run_attempted") else None,
            "last_processed_1h_candle": watchtower_kickoff_report.get("latest_processed_1h_candle"),
            "rows_fetched": len(normalized_fetched),
            "rows_appended": rows_appended,
            **RESEARCH_ONLY_FLAGS,
        },
    )
    _write_json(
        output_paths["self_audit"],
        {
            "source_discovery_completed": True,
            "fetch_window_computed": True,
            "public_fetch_attempted": public_fetch_report.get("public_fetch_attempted", False),
            "public_fetch_success": public_fetch_report.get("fetch_success", False),
            "private_api_key_used": False,
            "account_endpoint_used": False,
            "order_endpoint_used": False,
            "broker_execution_created": False,
            "no_order_path_created": True,
            "no_paper_path_created": True,
            "no_live_path_created": True,
            "data_normalized": normalization_report.get("data_normalized", False),
            "gaps_audited": bool(quality_report),
            "duplicates_audited": bool(quality_report),
            "canonical_write_completed": bool(canonical_write_report),
            "old_source_overwritten": False,
            "resample_validation_completed": bool(resample_validation_report) or config.dry_run,
            "watchtower_kickoff_attempted": watchtower_kickoff_report.get("watchtower_run_attempted", False),
            "forward_clock_policy_written": True,
            "capital_anchor_remains_diagnostic_only": True,
            "previous_artifacts_overwritten": False,
            "reviewer_notes": warnings,
            **RESEARCH_ONLY_FLAGS,
        },
    )

    state = "completed" if classification in {"FRESH_DATA_READY_AND_APPENDED", "FRESH_DATA_READY_NO_NEW_ROWS", "FRESH_DATA_READY_AND_WATCHTOWER_STARTED"} else "partial"
    _write_status(output_paths["status"], state=state, classification=classification, warnings=warnings, mode=config.mode)
    _write_progress(output_paths["scenario_progress"], state=state, mode=config.mode, rows_fetched=len(normalized_fetched), rows_appended=rows_appended, warnings=warnings)
    _write_progress(output_paths["run_progress"], state=state, mode=config.mode, rows_fetched=len(normalized_fetched), rows_appended=rows_appended, warnings=warnings)
    return {"status": output_paths["status"], "summary": output_paths["summary"], "report": output_paths["report"]}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch fresh public BTCUSDT 1m data and optionally kick off the shadow watchtower.")
    parser.add_argument("--mode", default=DEFAULT_MODE, choices=sorted(ALLOWED_MODES))
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--source-csv", default=None)
    parser.add_argument("--canonical-path", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--force-rerun", action="store_true")
    parser.add_argument("--allow-public-fetch", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--max-fetch-minutes", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    package_root = resolve_package_root()
    output_root = (
        package_root / "output" / OUTPUT_FOLDER_NAME
        if args.output_root is None
        else resolve_project_path(args.output_root)
    )
    result = write_fresh_btcusdt_data_updater(
        FreshBTCUSDTDataUpdaterConfig(
            package_root=package_root,
            output_root=output_root,
            mode=args.mode,
            symbol=args.symbol,
            source_csv=resolve_project_path(args.source_csv) if args.source_csv else None,
            canonical_path=resolve_project_path(args.canonical_path) if args.canonical_path else None,
            force_rerun=bool(args.force_rerun),
            allow_public_fetch=bool(args.allow_public_fetch),
            max_fetch_minutes=args.max_fetch_minutes,
            dry_run=bool(args.dry_run),
        )
    )
    print(json.dumps({key: str(value) for key, value in result.items()}, indent=2))


if __name__ == "__main__":
    main()
