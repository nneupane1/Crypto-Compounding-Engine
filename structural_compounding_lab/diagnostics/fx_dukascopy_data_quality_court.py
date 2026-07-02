from __future__ import annotations

import argparse
import csv
import json
import lzma
import math
import struct
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from structural_compounding_lab.common.download_progress import DownloadProgressDisplay
from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path


COURT_NAME = "FX_DUKASCOPY_PUBLIC_DATA_QUALITY_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "fx_dukascopy_data_quality_court_001"
PASSED = "FX_PUBLIC_DATA_QUALITY_VALIDATED_RESEARCH_ONLY"
WARNING = "FX_PUBLIC_DATA_QUALITY_WARNING_RESEARCH_ONLY"
FAILED = "FX_PUBLIC_DATA_QUALITY_FAILED_RESEARCH_ONLY"

DEFAULT_SYMBOLS: tuple[str, ...] = ("EURUSD",)
DEFAULT_START_DATE = "2003-01-01"
DEFAULT_END_DATE = "2026-06-29"

SAFETY_FLAGS = {
    "paper_validation_ready": False,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "broker_path_created": False,
    "order_path_created": False,
    "account_path_created": False,
    "private_endpoint_used": False,
    "signed_endpoint_used": False,
}


@dataclass(frozen=True)
class FxCourtConfig:
    project_root: Path
    package_root: Path
    data_root: Path
    output_root: Path
    symbols: tuple[str, ...]
    start_date: str
    end_date: str
    workers: int = 8
    request_timeout_seconds: int = 35
    retries: int = 3


def default_config() -> FxCourtConfig:
    root = project_root()
    return FxCourtConfig(
        project_root=root,
        package_root=package_root(),
        data_root=root / "data_storage" / "FX",
        output_root=package_root() / "output" / OUTPUT_FOLDER_NAME,
        symbols=DEFAULT_SYMBOLS,
        start_date=DEFAULT_START_DATE,
        end_date=DEFAULT_END_DATE,
    )


def _date_range(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days


def _parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y-%m-%d").date()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round_payload(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 8)
    if isinstance(value, dict):
        return {key: _round_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_payload(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_round_payload(payload), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _price_scale(symbol: str) -> float:
    return 1000.0 if "JPY" in symbol.upper() else 100000.0


def _dukascopy_url(symbol: str, day: date, side: str) -> str:
    # Dukascopy months are zero-based in datafeed paths.
    month_zero_based = day.month - 1
    return (
        f"https://datafeed.dukascopy.com/datafeed/{symbol.upper()}/"
        f"{day.year:04d}/{month_zero_based:02d}/{day.day:02d}/"
        f"{side.upper()}_candles_min_1.bi5"
    )


def _decode_bi5_candles(raw: bytes, *, symbol: str, day: date, side: str) -> pd.DataFrame:
    if not raw:
        return pd.DataFrame()
    data = lzma.decompress(raw)
    row_size = 24
    if len(data) % row_size != 0:
        raise ValueError(f"{symbol}:{day}:{side}:unexpected_bi5_size:{len(data)}")
    scale = _price_scale(symbol)
    rows: list[dict[str, Any]] = []
    for offset in range(0, len(data), row_size):
        seconds, open_i, high_i, low_i, close_i, volume = struct.unpack(">IIIIIf", data[offset : offset + row_size])
        timestamp = datetime(day.year, day.month, day.day, tzinfo=timezone.utc) + timedelta(seconds=int(seconds))
        rows.append(
            {
                "timestamp": timestamp,
                f"{side.lower()}_open": open_i / scale,
                f"{side.lower()}_high": high_i / scale,
                f"{side.lower()}_low": low_i / scale,
                f"{side.lower()}_close": close_i / scale,
                f"{side.lower()}_volume": float(volume),
            }
        )
    return pd.DataFrame(rows)


def _http_get(url: str, *, timeout_seconds: int, retries: int) -> tuple[bytes, str]:
    headers = {"User-Agent": "Retail-Trading-System-FX-Research/1.0"}
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                if getattr(response, "status", 200) != 200:
                    return b"", f"http_{response.status}"
                return response.read(), "ok"
        except urllib.error.HTTPError as exc:
            if exc.code in {404, 503}:
                return b"", f"http_{exc.code}_no_data"
            last_error = f"http_{exc.code}"
        except Exception as exc:  # noqa: BLE001 - downloader records exact external failure
            last_error = str(exc)
        if attempt < retries:
            time.sleep(min(2.0 * attempt, 8.0))
    return b"", f"error:{last_error}"


def _fetch_side(symbol: str, day: date, side: str, *, timeout_seconds: int, retries: int) -> tuple[pd.DataFrame, dict[str, Any]]:
    url = _dukascopy_url(symbol, day, side)
    started = time.time()
    raw, status = _http_get(url, timeout_seconds=timeout_seconds, retries=retries)
    elapsed = time.time() - started
    if status != "ok":
        return pd.DataFrame(), {"side": side, "url": url, "status": status, "rows": 0, "elapsed_seconds": elapsed}
    frame = _decode_bi5_candles(raw, symbol=symbol, day=day, side=side)
    return frame, {"side": side, "url": url, "status": status, "rows": len(frame), "elapsed_seconds": elapsed}


def _merge_bid_ask(symbol: str, day: date, bid: pd.DataFrame, ask: pd.DataFrame) -> pd.DataFrame:
    if bid.empty or ask.empty:
        return pd.DataFrame()
    merged = bid.merge(ask, on="timestamp", how="inner").sort_values("timestamp")
    if merged.empty:
        return merged
    for field in ("open", "high", "low", "close"):
        merged[field] = (merged[f"bid_{field}"] + merged[f"ask_{field}"]) / 2.0
    merged["high"] = merged[["open", "high", "low", "close"]].max(axis=1)
    merged["low"] = merged[["open", "high", "low", "close"]].min(axis=1)
    merged["volume"] = (merged["bid_volume"] + merged["ask_volume"]) / 2.0
    merged["spread_close"] = merged["ask_close"] - merged["bid_close"]
    merged["spread_close_bps"] = (merged["spread_close"] / merged["close"]) * 10000.0
    merged["source"] = "dukascopy_bid_ask_1m_mid"
    merged["symbol"] = symbol.upper()
    columns = [
        "timestamp",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "bid_open",
        "bid_high",
        "bid_low",
        "bid_close",
        "ask_open",
        "ask_high",
        "ask_low",
        "ask_close",
        "bid_volume",
        "ask_volume",
        "spread_close",
        "spread_close_bps",
        "source",
        "symbol",
    ]
    return merged[columns]


def _fetch_day(symbol: str, day: date, *, timeout_seconds: int, retries: int) -> dict[str, Any]:
    bid, bid_meta = _fetch_side(symbol, day, "BID", timeout_seconds=timeout_seconds, retries=retries)
    ask, ask_meta = _fetch_side(symbol, day, "ASK", timeout_seconds=timeout_seconds, retries=retries)
    merged = _merge_bid_ask(symbol, day, bid, ask)
    status = "ok"
    if bid.empty and ask.empty:
        status = "no_bid_ask_data"
    elif bid.empty:
        status = "missing_bid_data"
    elif ask.empty:
        status = "missing_ask_data"
    elif merged.empty:
        status = "bid_ask_no_overlap"
    return {
        "symbol": symbol.upper(),
        "day": day.isoformat(),
        "status": status,
        "rows": len(merged),
        "bid": bid_meta,
        "ask": ask_meta,
        "frame": merged,
    }


def _symbol_paths(config: FxCourtConfig, symbol: str) -> dict[str, Path]:
    folder = config.data_root / symbol.upper() / "1m"
    filename = f"{symbol.upper()}_1m_{config.start_date}_to_{config.end_date}.csv"
    output = config.output_root / "symbols" / symbol.upper()
    return {
        "folder": folder,
        "final": folder / filename,
        "partial": folder / f"{filename}.partial",
        "checkpoint": folder / "_checkpoints" / f"{filename}.checkpoint.json",
        "output": output,
        "source_manifest": output / "source_data_manifest.json",
        "gap_manifest": output / "fx_gap_manifest.json",
        "quality_summary": output / "quality_summary.json",
    }


def _derive_resume_day(partial_path: Path, fallback: date) -> date:
    if not partial_path.exists() or partial_path.stat().st_size == 0:
        return fallback
    try:
        frame = pd.read_csv(partial_path, usecols=["timestamp"])
        if frame.empty:
            return fallback
        last_ts = pd.to_datetime(frame["timestamp"].iloc[-1], utc=True)
        return max(fallback, (last_ts.date() + timedelta(days=1)))
    except Exception:
        return fallback


def _append_rows(path: Path, frame: pd.DataFrame) -> None:
    if frame.empty:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not path.exists() or path.stat().st_size == 0
    frame.to_csv(path, mode="a", header=write_header, index=False)


def download_symbol(config: FxCourtConfig, symbol: str) -> Path:
    paths = _symbol_paths(config, symbol)
    paths["folder"].mkdir(parents=True, exist_ok=True)
    if paths["final"].exists():
        print(f"\nCompleted FX historical file already exists: {paths['final']}")
        return paths["final"]

    start_day = _parse_day(config.start_date)
    end_day = _parse_day(config.end_date)
    checkpoint = _read_json(paths["checkpoint"], {})
    resume_day = _parse_day(checkpoint["next_day"]) if checkpoint.get("next_day") else _derive_resume_day(paths["partial"], start_day)
    all_days = [item for item in _date_range(resume_day, end_day) if item <= end_day]
    total_days = len(_date_range(start_day, end_day))
    already_done = max(0, (resume_day - start_day).days)
    rows_written = int(checkpoint.get("rows_written") or 0)
    day_events: list[dict[str, Any]] = list(checkpoint.get("recent_day_events") or [])

    display = DownloadProgressDisplay(enabled=True)
    initial_pct = min(100.0, (already_done / max(total_days, 1)) * 100.0)
    display.start(
        symbol=symbol.upper(),
        interval="1m FX bid/ask mid",
        start_date=config.start_date,
        end_date=config.end_date,
        final_path=paths["final"],
        checkpoint_path=paths["checkpoint"],
        resumed=already_done > 0,
        resume_point=resume_day.isoformat() if already_done > 0 else None,
        total_rows=rows_written,
        initial_progress_pct=initial_pct,
        verify_mode="dukascopy_public_https",
    )

    started = time.time()
    completed_days = already_done
    chunk_size = max(config.workers * 2, 4)
    try:
        for chunk_start in range(0, len(all_days), chunk_size):
            chunk = all_days[chunk_start : chunk_start + chunk_size]
            display.update_request(
                batch_number=completed_days + 1,
                request_from=chunk[0].isoformat(),
                limit=len(chunk),
            )
            chunk_results: list[dict[str, Any]] = []
            with ThreadPoolExecutor(max_workers=config.workers) as executor:
                futures = {
                    executor.submit(
                        _fetch_day,
                        symbol.upper(),
                        day,
                        timeout_seconds=config.request_timeout_seconds,
                        retries=config.retries,
                    ): day
                    for day in chunk
                }
                for future in as_completed(futures):
                    result = future.result()
                    chunk_results.append(result)
            chunk_results.sort(key=lambda item: item["day"])
            chunk_rows = 0
            for result in chunk_results:
                frame = result.pop("frame")
                if not frame.empty:
                    _append_rows(paths["partial"], frame)
                chunk_rows += int(result["rows"])
                day_events.append(result)
            completed_days += len(chunk)
            rows_written += chunk_rows
            progress_pct = min(100.0, (completed_days / max(total_days, 1)) * 100.0)
            elapsed = time.time() - started
            done_this_session = max(1, completed_days - already_done)
            remaining_days = max(0, total_days - completed_days)
            eta = elapsed * (remaining_days / done_this_session)
            next_day = chunk[-1] + timedelta(days=1)
            _write_json(
                paths["checkpoint"],
                {
                    "symbol": symbol.upper(),
                    "source": "dukascopy_public_datafeed",
                    "start_date": config.start_date,
                    "end_date": config.end_date,
                    "next_day": next_day.isoformat(),
                    "rows_written": rows_written,
                    "completed": False,
                    "partial_csv": str(paths["partial"]),
                    "final_csv": str(paths["final"]),
                    "recent_day_events": day_events[-50:],
                    "updated_at": _now(),
                    **SAFETY_FLAGS,
                },
            )
            display.update_batch_result(
                batch_number=completed_days,
                window_start=chunk[0].isoformat(),
                window_end=chunk[-1].isoformat(),
                batch_rows=chunk_rows,
                total_rows=rows_written,
                progress_pct=progress_pct,
                remaining_pct=max(0.0, 100.0 - progress_pct),
                elapsed_seconds=elapsed,
                eta_seconds=eta,
                resume_point=next_day.isoformat(),
            )
    except BaseException as exc:
        display.update_interrupted(exc, paths["checkpoint"])
        display.stop()
        raise

    display.update_finalizing()
    if not paths["partial"].exists():
        raise RuntimeError(f"{symbol}:no_rows_downloaded")
    frame = pd.read_csv(paths["partial"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp", keep="last")
    frame.to_csv(paths["final"], index=False)
    _write_json(
        paths["checkpoint"],
        {
            "symbol": symbol.upper(),
            "source": "dukascopy_public_datafeed",
            "start_date": config.start_date,
            "end_date": config.end_date,
            "rows_written": len(frame),
            "completed": True,
            "final_csv": str(paths["final"]),
            "completed_at": _now(),
            "recent_day_events": day_events[-50:],
            **SAFETY_FLAGS,
        },
    )
    display.update_completed(len(frame), time.time() - started, paths["final"])
    display.stop()
    return paths["final"]


def _expected_fx_market_closure(ts: pd.Timestamp) -> bool:
    # Conservative UTC trading-week approximation for major FX:
    # closed after Friday 22:00 UTC, all Saturday, and before Sunday 21:00 UTC.
    weekday = ts.weekday()
    if weekday == 5:
        return True
    if weekday == 4 and ts.hour >= 22:
        return True
    if weekday == 6 and ts.hour < 21:
        return True
    return False


def _minute_gap_classification(start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    minutes = pd.date_range(start=start, end=end, freq="min", tz="UTC")
    expected = sum(1 for item in minutes if _expected_fx_market_closure(item))
    unexpected = len(minutes) - expected
    classification = "EXPECTED_FX_MARKET_CLOSURE" if unexpected == 0 else "DOCUMENTED_DUKASCOPY_NO_CANDLE_INTERVAL"
    return {
        "missing_start": start.isoformat(),
        "missing_end": end.isoformat(),
        "missing_minutes": len(minutes),
        "expected_market_closure_minutes": expected,
        "unexpected_in_session_minutes": unexpected,
        "classification": classification,
        "synthetic_candles_inserted": False,
        "forward_fill_inserted": False,
        "back_fill_inserted": False,
    }


def validate_symbol(config: FxCourtConfig, symbol: str, source_csv: Path) -> dict[str, Any]:
    paths = _symbol_paths(config, symbol)
    frame = pd.read_csv(source_csv)
    required = ["timestamp", "open", "high", "low", "close", "volume", "bid_close", "ask_close", "spread_close_bps"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"{symbol}:missing_columns:{','.join(missing)}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in [item for item in required if item != "timestamp"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=required).sort_values("timestamp").reset_index(drop=True)

    duplicate_count = int(frame["timestamp"].duplicated().sum())
    ohlc_failures = int(((frame["high"] < frame[["open", "close", "low"]].max(axis=1)) | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))).sum())
    negative_spread_rows = int((frame["spread_close"] < 0).sum()) if "spread_close" in frame else 0
    deltas = frame["timestamp"].diff().dropna()
    gap_indices = deltas[deltas > pd.Timedelta(minutes=1)].index.tolist()
    gaps = []
    for idx in gap_indices:
        prev_ts = frame.loc[idx - 1, "timestamp"]
        curr_ts = frame.loc[idx, "timestamp"]
        gaps.append(_minute_gap_classification(prev_ts + pd.Timedelta(minutes=1), curr_ts - pd.Timedelta(minutes=1)))

    latest = frame["timestamp"].max()
    holdout_start = (latest - pd.DateOffset(months=6)).floor("D")
    research_end = holdout_start - pd.Timedelta(minutes=1)
    holdout_gaps = [
        gap
        for gap in gaps
        if pd.Timestamp(gap["missing_end"]) >= holdout_start
    ]
    holdout_unexpected_minutes = sum(int(gap["unexpected_in_session_minutes"]) for gap in holdout_gaps)
    holdout = frame.loc[(frame["timestamp"] >= holdout_start) & (frame["timestamp"] <= latest)]
    holdout_duplicates = int(holdout["timestamp"].duplicated().sum())
    holdout_ohlc = int(((holdout["high"] < holdout[["open", "close", "low"]].max(axis=1)) | (holdout["low"] > holdout[["open", "close", "high"]].min(axis=1))).sum())
    source_manifest = {
        "court_name": COURT_NAME,
        "symbol": symbol.upper(),
        "source": "Dukascopy public HTTPS datafeed BID/ASK 1m candles",
        "source_csv": str(source_csv),
        "data_root": str(config.data_root),
        "rows": len(frame),
        "first_timestamp": frame["timestamp"].min().isoformat(),
        "last_timestamp": latest.isoformat(),
        "research_start": frame["timestamp"].min().isoformat(),
        "research_end": research_end.isoformat(),
        "sealed_holdout_start": holdout_start.isoformat(),
        "sealed_holdout_end": latest.isoformat(),
        "sealed_holdout_rows": len(holdout),
        "bid_ask_mid_ohlcv_used_for_engine_compatibility": True,
        "bid_ask_columns_preserved": True,
        "spread_columns_preserved": True,
        "synthetic_candles_inserted": False,
        "forward_fill_inserted": False,
        "back_fill_inserted": False,
        "weekend_market_closures_allowed": True,
        "sealed_holdout_must_be_session_clean": True,
        "sealed_holdout_unexpected_in_session_missing_minutes": holdout_unexpected_minutes,
        **SAFETY_FLAGS,
    }
    gap_manifest = {
        "court_name": COURT_NAME,
        "symbol": symbol.upper(),
        "total_gaps": len(gaps),
        "total_missing_minutes": sum(int(gap["missing_minutes"]) for gap in gaps),
        "expected_fx_market_closure_minutes": sum(int(gap["expected_market_closure_minutes"]) for gap in gaps),
        "unexpected_in_session_missing_minutes": sum(int(gap["unexpected_in_session_minutes"]) for gap in gaps),
        "holdout_gap_count": len(holdout_gaps),
        "holdout_unexpected_in_session_missing_minutes": holdout_unexpected_minutes,
        "gaps": gaps,
        "synthetic_candles_inserted": False,
        "forward_fill_inserted": False,
        "back_fill_inserted": False,
    }
    holdout_session_clean = holdout_unexpected_minutes == 0 and holdout_duplicates == 0 and holdout_ohlc == 0
    mechanical_clean = duplicate_count == 0 and ohlc_failures == 0 and negative_spread_rows == 0
    classification = PASSED if mechanical_clean and holdout_session_clean else FAILED
    if classification == PASSED and gap_manifest["unexpected_in_session_missing_minutes"] > 0:
        classification = WARNING
    summary = {
        "court_name": COURT_NAME,
        "symbol": symbol.upper(),
        "final_classification": classification,
        "rows": len(frame),
        "duplicate_count": duplicate_count,
        "ohlc_sanity_failures": ohlc_failures,
        "negative_spread_rows": negative_spread_rows,
        "total_gaps": len(gaps),
        "total_missing_minutes": gap_manifest["total_missing_minutes"],
        "unexpected_in_session_missing_minutes": gap_manifest["unexpected_in_session_missing_minutes"],
        "sealed_holdout_start": holdout_start.isoformat(),
        "sealed_holdout_end": latest.isoformat(),
        "sealed_holdout_rows": len(holdout),
        "sealed_holdout_duplicate_count": holdout_duplicates,
        "sealed_holdout_ohlc_sanity_failures": holdout_ohlc,
        "sealed_holdout_unexpected_in_session_missing_minutes": holdout_unexpected_minutes,
        "sealed_holdout_session_clean": holdout_session_clean,
        "ready_for_frozen_strategy_transfer_court": classification in {PASSED, WARNING} and holdout_session_clean,
        "average_spread_close_bps": float(frame["spread_close_bps"].mean()),
        "median_spread_close_bps": float(frame["spread_close_bps"].median()),
        "p95_spread_close_bps": float(frame["spread_close_bps"].quantile(0.95)),
        "created_at": _now(),
        **SAFETY_FLAGS,
    }
    _write_json(paths["source_manifest"], source_manifest)
    _write_json(paths["gap_manifest"], gap_manifest)
    _write_json(paths["quality_summary"], summary)
    return summary


def run_court(config: FxCourtConfig, *, download: bool = True, validate: bool = True) -> dict[str, Any]:
    summaries: list[dict[str, Any]] = []
    for symbol in config.symbols:
        source_csv = _symbol_paths(config, symbol)["final"]
        if download:
            source_csv = download_symbol(config, symbol)
        if validate:
            summaries.append(validate_symbol(config, symbol, source_csv))
    passed = [item for item in summaries if item.get("final_classification") == PASSED]
    warnings = [item for item in summaries if item.get("final_classification") == WARNING]
    failed = [item for item in summaries if item.get("final_classification") == FAILED]
    if failed:
        classification = FAILED
    elif warnings:
        classification = WARNING
    else:
        classification = PASSED
    combined = {
        "court_name": COURT_NAME,
        "final_classification": classification,
        "symbols": summaries,
        "symbol_count": len(summaries),
        "passed_symbols": [item["symbol"] for item in passed],
        "warning_symbols": [item["symbol"] for item in warnings],
        "failed_symbols": [item["symbol"] for item in failed],
        "next_step_if_ready": "run FX frozen strategy transfer court with sealed holdout unopened until freeze",
        "created_at": _now(),
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "fx_data_quality_court_summary.json", combined)
    _write_csv(config.output_root / "fx_data_quality_scorecard.csv", summaries)
    return combined


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download and validate public Dukascopy FX 1m BID/ASK data.")
    parser.add_argument("--symbols", nargs="+", default=list(DEFAULT_SYMBOLS), help="FX pairs such as EURUSD GBPUSD USDJPY.")
    parser.add_argument("--start-date", default=DEFAULT_START_DATE)
    parser.add_argument("--end-date", default=DEFAULT_END_DATE)
    parser.add_argument("--data-root", default=None, help="Default: data_storage/FX under detected project root.")
    parser.add_argument("--output-root", default=None, help="Default: structural_compounding_lab/output/fx_dukascopy_data_quality_court_001.")
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--download-only", action="store_true")
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    base = default_config()
    config = FxCourtConfig(
        project_root=base.project_root,
        package_root=base.package_root,
        data_root=resolve_project_path(args.data_root) if args.data_root else base.data_root,
        output_root=resolve_project_path(args.output_root) if args.output_root else base.output_root,
        symbols=tuple(symbol.upper() for symbol in args.symbols),
        start_date=args.start_date,
        end_date=args.end_date,
        workers=max(1, int(args.workers)),
    )
    result = run_court(config, download=not args.validate_only, validate=not args.download_only)
    print(json.dumps(_round_payload(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
