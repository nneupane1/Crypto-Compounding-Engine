from __future__ import annotations

import argparse
import csv
import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path
from structural_compounding_lab.diagnostics.earned_capital_gear_ladder_court import BASE_SYMBOL_CAPS_EUR


COURT_NAME = "MULTI_SYMBOL_PUBLIC_FETCH_RUNTIME_PROTOTYPE_WITH_SYMBOL_CAPS_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_symbol_public_fetch_runtime_prototype_court_001"

PASSED = "MULTI_SYMBOL_PUBLIC_FETCH_RUNTIME_PROTOTYPE_PASSED_RESEARCH_ONLY"
WARNING = "MULTI_SYMBOL_PUBLIC_FETCH_RUNTIME_PROTOTYPE_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_SYMBOL_PUBLIC_FETCH_RUNTIME_PROTOTYPE_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_SYMBOL_PUBLIC_FETCH_RUNTIME_PROTOTYPE_BLOCKED_RESEARCH_ONLY"

SYMBOLS: tuple[str, ...] = (
    "ADAUSDT",
    "LINKUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "AVAXUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "SOLUSDT",
)

BINANCE_BASE_URL = "https://api.binance.com"
FETCH_LIMIT = 120
TAIL_ROWS_FOR_RUNTIME_COPY = 900
MAX_CATCHUP_BATCHES = 20

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
}


@dataclass(frozen=True)
class PublicFetchPrototypeConfig:
    project_root: Path
    package_root: Path
    data_root: Path
    earned_gear_root: Path
    dry_run_root: Path
    output_root: Path
    fetch_limit: int = FETCH_LIMIT
    max_catchup_batches: int = MAX_CATCHUP_BATCHES
    fetch_function: Callable[[str, int], list[dict[str, Any]]] | None = None


def default_config() -> PublicFetchPrototypeConfig:
    root = project_root()
    pkg = package_root()
    return PublicFetchPrototypeConfig(
        project_root=root,
        package_root=pkg,
        data_root=root / "data_storage",
        earned_gear_root=pkg / "output" / "earned_capital_gear_ladder_court_001",
        dry_run_root=pkg / "output" / "multi_symbol_realtime_scheduler_shadow_dry_run_court_001",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_ts(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _source_csv_for_symbol(data_root: Path, symbol: str) -> Path | None:
    candidates = sorted((data_root / symbol / "1m").glob(f"{symbol}_1m_*.csv"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _last_csv_row(path: Path) -> dict[str, str]:
    with path.open("rb") as handle:
        handle.seek(0, 2)
        end = handle.tell()
        buffer = bytearray()
        pos = end - 1
        while pos >= 0:
            handle.seek(pos)
            char = handle.read(1)
            if char == b"\n" and buffer:
                break
            buffer.extend(char)
            pos -= 1
        line = bytes(reversed(buffer)).decode("utf-8").strip()
    with path.open(newline="", encoding="utf-8") as handle:
        header = next(csv.reader(handle))
    return dict(zip(header, next(csv.reader([line]))))


def _tail_frame(path: Path, max_rows: int) -> pd.DataFrame:
    rows: list[dict[str, str]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        from collections import deque

        rows = list(deque(reader, maxlen=max_rows))
    return _normalize_rows(rows)


def _normalize_rows(rows: list[dict[str, Any]]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame = pd.DataFrame(rows).rename(columns={column: column.lower().strip() for column in rows[0]})
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    frame = frame[[column for column in required if column in frame.columns]].copy()
    for column in required:
        if column not in frame.columns:
            frame[column] = None
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=required).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)


def _public_klines(symbol: str, limit: int, *, start_ms: int | None = None) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"symbol": symbol, "interval": "1m", "limit": limit}
    if start_ms is not None:
        params["startTime"] = start_ms
    url = f"{BINANCE_BASE_URL}/api/v3/klines?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(url, headers={"User-Agent": "Crypto-Compounding-Engine-Research-Court/1.0"})
    with urllib.request.urlopen(request, timeout=15) as response:
        payload = json.loads(response.read().decode("utf-8"))
    rows: list[dict[str, Any]] = []
    for item in payload:
        rows.append(
            {
                "timestamp": pd.to_datetime(int(item[0]), unit="ms", utc=True).isoformat(),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
            }
        )
    return rows


def _public_klines_catchup(symbol: str, *, start_after: pd.Timestamp, limit: int, max_batches: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    next_start_ms = int((start_after + pd.Timedelta(minutes=1)).timestamp() * 1000)
    for _ in range(max_batches):
        batch = _public_klines(symbol, min(1000, max(1, limit)), start_ms=next_start_ms)
        if not batch:
            break
        rows.extend(batch)
        last_ts = _parse_ts(batch[-1]["timestamp"])
        next_start_ms = int((last_ts + pd.Timedelta(minutes=1)).timestamp() * 1000)
        if len(batch) < min(1000, max(1, limit)):
            break
        time.sleep(0.05)
    return rows


def _quality(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"rows": 0, "gap_count": 0, "missing_minutes": 0, "duplicate_count": 0, "ohlc_failure_count": 0, "clean": False}
    timestamps = frame["timestamp"].sort_values()
    diffs = timestamps.diff().dropna()
    gap_diffs = diffs[diffs > pd.Timedelta(minutes=1)]
    missing = int(sum(int(diff / pd.Timedelta(minutes=1)) - 1 for diff in gap_diffs))
    ohlc = frame[
        (frame["high"] < frame[["open", "low", "close"]].max(axis=1))
        | (frame["low"] > frame[["open", "high", "close"]].min(axis=1))
        | (frame["volume"] < 0)
    ]
    return {
        "rows": int(len(frame)),
        "first_timestamp": timestamps.iloc[0].isoformat(),
        "last_timestamp": timestamps.iloc[-1].isoformat(),
        "gap_count": int(len(gap_diffs)),
        "missing_minutes": missing,
        "duplicate_count": int(frame["timestamp"].duplicated().sum()),
        "ohlc_failure_count": int(len(ohlc)),
        "clean": bool(len(gap_diffs) == 0 and missing == 0 and frame["timestamp"].duplicated().sum() == 0 and len(ohlc) == 0),
    }


def _resample_complete(frame: pd.DataFrame, rule: str, expected: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    bars = (
        frame.set_index("timestamp")
        .sort_index()
        .resample(rule, label="left", closed="left")
        .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"), volume=("volume", "sum"), source_1m_count=("close", "count"))
    )
    return bars[bars["source_1m_count"] == expected].dropna().reset_index()


def _simulate_symbol(config: PublicFetchPrototypeConfig, symbol: str) -> dict[str, Any]:
    source_csv = _source_csv_for_symbol(config.data_root, symbol)
    if source_csv is None:
        return {"symbol": symbol, "blocked": True, "reason": "source_csv_missing"}
    latest_local = _parse_ts(_last_csv_row(source_csv)["timestamp"])
    fetch = config.fetch_function or _public_klines
    try:
        if config.fetch_function is not None:
            public_rows_raw = fetch(symbol, config.fetch_limit)
        else:
            public_rows_raw = _public_klines_catchup(
                symbol,
                start_after=latest_local,
                limit=1000,
                max_batches=config.max_catchup_batches,
            )
            if not public_rows_raw:
                public_rows_raw = _public_klines(symbol, config.fetch_limit)
        public_frame = _normalize_rows(public_rows_raw)
        fetch_error = None
    except Exception as exc:  # noqa: BLE001 - diagnostic court should report, not crash all symbols
        public_frame = pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
        fetch_error = f"{type(exc).__name__}: {exc}"
    appendable = public_frame[public_frame["timestamp"] > latest_local].copy()
    tail = _tail_frame(source_csv, TAIL_ROWS_FOR_RUNTIME_COPY)
    runtime_copy = pd.concat([tail, appendable], ignore_index=True).sort_values("timestamp").drop_duplicates("timestamp").reset_index(drop=True)
    symbol_root = config.output_root / "symbol_runtime_snapshots" / symbol
    symbol_root.mkdir(parents=True, exist_ok=True)
    runtime_copy.to_csv(symbol_root / "prototype_runtime_1m_copy.csv", index=False)
    appendable.to_csv(symbol_root / "appendable_public_1m_rows.csv", index=False)
    bars_15m = _resample_complete(runtime_copy, "15min", 15)
    bars_1h = _resample_complete(runtime_copy, "1h", 60)
    bars_15m.to_csv(symbol_root / "prototype_complete_15m_bars.csv", index=False)
    bars_1h.to_csv(symbol_root / "prototype_complete_1h_bars.csv", index=False)
    second_appendable = public_frame[public_frame["timestamp"] > runtime_copy["timestamp"].max()].copy() if not runtime_copy.empty else public_frame
    public_quality = _quality(public_frame)
    runtime_quality = _quality(runtime_copy)
    return {
        "symbol": symbol,
        "source_csv": str(source_csv),
        "blocked": False,
        "fetch_error": fetch_error,
        "public_fetch_attempted": True,
        "public_fetch_rows_returned": int(len(public_frame)),
        "public_fetch_first_timestamp": public_frame["timestamp"].min().isoformat() if len(public_frame) else None,
        "public_fetch_last_timestamp": public_frame["timestamp"].max().isoformat() if len(public_frame) else None,
        "latest_local_timestamp_before_prototype": latest_local.isoformat(),
        "appendable_public_rows": int(len(appendable)),
        "local_source_ahead_or_equal_public_latest": bool(len(public_frame) and public_frame["timestamp"].max() <= latest_local),
        "runtime_copy_rows": int(len(runtime_copy)),
        "runtime_copy_quality": runtime_quality,
        "public_fetch_quality": public_quality,
        "complete_15m_bars": int(len(bars_15m)),
        "complete_1h_bars": int(len(bars_1h)),
        "immediate_rerun_appendable_rows": int(len(second_appendable)),
        "idempotency_passed": bool(len(second_appendable) == 0),
        "symbol_active_cap_eur": BASE_SYMBOL_CAPS_EUR[symbol],
        "snapshot_folder": str(symbol_root),
    }


def _write_report(config: PublicFetchPrototypeConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# Multi-Symbol Public Fetch Runtime Prototype Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        "- Research-only. No scheduler installed, no BTC scheduler replacement, no data_storage mutation.",
        "- Public unsigned Binance klines only.",
        "",
        "## Aggregate",
        "",
        f"- Symbols checked: `{summary['aggregate']['symbols_checked']}`",
        f"- Public rows returned: `{summary['aggregate']['public_fetch_rows_returned']}`",
        f"- Appendable public rows: `{summary['aggregate']['appendable_public_rows']}`",
        f"- Immediate rerun appendable rows: `{summary['aggregate']['immediate_rerun_appendable_rows']}`",
        "",
        "| Symbol | Public rows | Appendable | Local ahead/equal | 1H bars | Rerun appendable |",
        "| --- | ---: | ---: | --- | ---: | ---: |",
    ]
    for row in summary["symbol_results"]:
        lines.append(
            "| {symbol} | {public} | {appendable} | {ahead} | {h1} | {rerun} |".format(
                symbol=row["symbol"],
                public=int(row.get("public_fetch_rows_returned") or 0),
                appendable=int(row.get("appendable_public_rows") or 0),
                ahead=str(bool(row.get("local_source_ahead_or_equal_public_latest"))).lower(),
                h1=int(row.get("complete_1h_bars") or 0),
                rerun=int(row.get("immediate_rerun_appendable_rows") or 0),
            )
        )
    lines.extend(["", "## Safety", "", "- `paper_validation_ready=false`", "- `paper_allowed=false`", "- `live_allowed=false`", "- no order/broker/account/private/signed endpoint"])
    (config.output_root / "multi_symbol_public_fetch_runtime_prototype_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: PublicFetchPrototypeConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    earned = _read_json(config.earned_gear_root / "earned_capital_gear_ladder_summary.json")
    dry = _read_json(config.dry_run_root / "multi_symbol_realtime_scheduler_shadow_dry_run_summary.json")
    if not earned or not dry:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_earned_gear_or_dry_run_artifacts"],
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_symbol_public_fetch_runtime_prototype_summary.json", summary)
        return summary
    symbol_results = []
    for symbol in SYMBOLS:
        symbol_results.append(_simulate_symbol(config, symbol))
        time.sleep(0.05)
    aggregate = {
        "symbols_expected": len(SYMBOLS),
        "symbols_checked": len([row for row in symbol_results if not row.get("blocked")]),
        "public_fetch_rows_returned": sum(int(row.get("public_fetch_rows_returned") or 0) for row in symbol_results),
        "appendable_public_rows": sum(int(row.get("appendable_public_rows") or 0) for row in symbol_results),
        "immediate_rerun_appendable_rows": sum(int(row.get("immediate_rerun_appendable_rows") or 0) for row in symbol_results),
        "fetch_error_count": sum(1 for row in symbol_results if row.get("fetch_error")),
        "local_ahead_or_equal_symbol_count": sum(1 for row in symbol_results if row.get("local_source_ahead_or_equal_public_latest")),
    }
    all_fetched = aggregate["symbols_checked"] == len(SYMBOLS) and aggregate["fetch_error_count"] == 0 and aggregate["public_fetch_rows_returned"] > 0
    quality_ok = all(bool(row.get("runtime_copy_quality", {}).get("clean")) for row in symbol_results if not row.get("blocked"))
    idempotent = aggregate["immediate_rerun_appendable_rows"] == 0
    appendable_exists = aggregate["appendable_public_rows"] > 0
    reasons: list[str] = []
    if all_fetched and quality_ok and idempotent and appendable_exists:
        classification = PASSED
        reasons.append("public_multi_symbol_fetch_append_and_idempotency_passed")
    elif all_fetched and quality_ok and idempotent:
        classification = WARNING
        reasons.append("public_fetch_reachable_and_idempotent_but_no_appendable_forward_candles")
    else:
        classification = FAILED
        if not all_fetched:
            reasons.append("public_fetch_failed_or_missing_symbols")
        if not quality_ok:
            reasons.append("runtime_copy_quality_failed")
        if not idempotent:
            reasons.append("immediate_rerun_idempotency_failed")
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_earned_gear_summary": str(config.earned_gear_root / "earned_capital_gear_ladder_summary.json"),
        "source_dry_run_summary": str(config.dry_run_root / "multi_symbol_realtime_scheduler_shadow_dry_run_summary.json"),
        "method": {
            "public_unsigned_binance_klines_only": True,
            "data_storage_modified": False,
            "writes_runtime_copy_under_output_only": True,
            "btc_scheduler_replaced": False,
            "scheduler_installed": False,
            "symbol_caps_applied_from_locked_250k_gear": True,
            "fetch_limit_per_symbol": config.fetch_limit,
            "max_catchup_batches_per_symbol": config.max_catchup_batches,
        },
        "symbol_caps_eur": BASE_SYMBOL_CAPS_EUR,
        "aggregate": aggregate,
        "symbol_results": symbol_results,
        "gate": {
            "may_unlock_500k_now": classification == PASSED,
            "may_install_multi_symbol_scheduler": False,
            "may_replace_btc_scheduler": False,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "paper_validation_ready": False,
            "next_required_court": "MULTI_SYMBOL_EXACT_FILL_AND_SYMBOL_CAP_CALIBRATION_COURT_RESEARCH_ONLY" if classification == PASSED else "WAIT_FOR_APPENDABLE_PUBLIC_FORWARD_CANDLES_OR_RERUN_PUBLIC_FETCH_PROTOTYPE",
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_symbol_public_fetch_runtime_prototype_summary.json", summary)
    _write_csv(config.output_root / "multi_symbol_public_fetch_symbol_results.csv", symbol_results)
    _write_report(config, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run public multi-symbol fetch runtime prototype court.")
    parser.add_argument("--data-root", default="data_storage")
    parser.add_argument("--earned-gear-root", default="structural_compounding_lab/output/earned_capital_gear_ladder_court_001")
    parser.add_argument("--dry-run-root", default="structural_compounding_lab/output/multi_symbol_realtime_scheduler_shadow_dry_run_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    parser.add_argument("--fetch-limit", type=int, default=FETCH_LIMIT)
    parser.add_argument("--max-catchup-batches", type=int, default=MAX_CATCHUP_BATCHES)
    args = parser.parse_args()
    root = project_root()
    summary = run(
        PublicFetchPrototypeConfig(
            project_root=root,
            package_root=package_root(),
            data_root=resolve_project_path(args.data_root),
            earned_gear_root=resolve_project_path(args.earned_gear_root),
            dry_run_root=resolve_project_path(args.dry_run_root),
            output_root=resolve_project_path(args.output_dir),
            fetch_limit=args.fetch_limit,
            max_catchup_batches=args.max_catchup_batches,
        )
    )
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
