from __future__ import annotations

import argparse
import csv
import json
import math
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path


COURT_NAME = "MULTI_SYMBOL_REALTIME_SCHEDULER_SHADOW_DRY_RUN_IDEMPOTENCY_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_symbol_realtime_scheduler_shadow_dry_run_court_001"

PASSED = "MULTI_SYMBOL_REALTIME_SCHEDULER_SHADOW_DRY_RUN_PASSED_RESEARCH_ONLY"
WARNING = "MULTI_SYMBOL_REALTIME_SCHEDULER_SHADOW_DRY_RUN_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_SYMBOL_REALTIME_SCHEDULER_SHADOW_DRY_RUN_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_SYMBOL_REALTIME_SCHEDULER_SHADOW_DRY_RUN_BLOCKED_RESEARCH_ONLY"

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
class MultiSymbolDryRunConfig:
    project_root: Path
    package_root: Path
    data_root: Path
    output_root: Path
    scanner_capacity_root: Path
    btc_runtime_root: Path
    catchup_minutes: int = 720


def default_config() -> MultiSymbolDryRunConfig:
    root = project_root()
    pkg = package_root()
    return MultiSymbolDryRunConfig(
        project_root=root,
        package_root=pkg,
        data_root=root / "data_storage",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
        scanner_capacity_root=pkg / "output" / "multi_symbol_scheduler_capacity_liquidity_court_001",
        btc_runtime_root=pkg / "output" / "forward_validation_runtime",
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


def _parse_timestamp(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _source_csv_for_symbol(data_root: Path, symbol: str) -> Path | None:
    candidates = sorted((data_root / symbol / "1m").glob(f"{symbol}_1m_*.csv"))
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _load_tail(path: Path, *, rows: int) -> pd.DataFrame:
    tail: deque[dict[str, str]] = deque(maxlen=rows)
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            tail.append(row)
    if not tail:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame = pd.DataFrame(list(tail))
    rename = {column: column.lower().strip() for column in frame.columns}
    frame = frame.rename(columns=rename)
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"missing required columns in {path}: {missing}")
    frame = frame[required].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in ["open", "high", "low", "close", "volume"]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=required).sort_values("timestamp").reset_index(drop=True)


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
            "clean": False,
        }
    timestamps = frame["timestamp"].sort_values().reset_index(drop=True)
    diffs = timestamps.diff().dropna()
    gap_diffs = diffs[diffs > pd.Timedelta(minutes=1)]
    duplicate_count = int(frame["timestamp"].duplicated().sum())
    ohlc_failures = frame[
        (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
        | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        | (frame["volume"] < 0)
    ]
    missing = int(sum(int(diff / pd.Timedelta(minutes=1)) - 1 for diff in gap_diffs))
    return {
        "rows": int(len(frame)),
        "first_timestamp": timestamps.iloc[0].isoformat(),
        "last_timestamp": timestamps.iloc[-1].isoformat(),
        "gap_count": int(len(gap_diffs)),
        "missing_minutes": missing,
        "duplicate_count": duplicate_count,
        "ohlc_failure_count": int(len(ohlc_failures)),
        "clean": bool(len(gap_diffs) == 0 and duplicate_count == 0 and len(ohlc_failures) == 0),
    }


def _complete_resample(frame: pd.DataFrame, rule: str, expected_count: int) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame()
    indexed = frame.set_index("timestamp").sort_index()
    grouped = indexed.resample(rule, label="left", closed="left")
    bars = grouped.agg(
        open=("open", "first"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        source_1m_count=("close", "count"),
    )
    bars = bars[bars["source_1m_count"] == expected_count].dropna(subset=["open", "high", "low", "close"])
    return bars.reset_index()


def _decision_rows(symbol: str, hourly: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for _, row in hourly.iterrows():
        start = _parse_timestamp(row["timestamp"])
        close_time = start + pd.Timedelta(minutes=59)
        rows.append(
            {
                "symbol": symbol,
                "decision_slot": start.isoformat(),
                "closed_1h_candle_start": start.isoformat(),
                "closed_1h_candle_end": close_time.isoformat(),
                "source_1m_count": int(row["source_1m_count"]),
                "dry_run_decision_processed": True,
                "strategy_signal_evaluated": False,
                "reason": "scheduler_idempotency_slot_only_no_strategy_change",
            }
        )
    return rows


def _simulate_symbol(symbol: str, source_csv: Path, *, catchup_minutes: int, output_root: Path) -> dict[str, Any]:
    tail_rows = max(catchup_minutes + 180, catchup_minutes * 2)
    frame = _load_tail(source_csv, rows=tail_rows)
    if frame.empty:
        return {
            "symbol": symbol,
            "source_csv": str(source_csv),
            "blocked": True,
            "block_reason": "source_csv_empty",
        }
    latest = frame["timestamp"].max()
    checkpoint = latest - pd.Timedelta(minutes=catchup_minutes)
    catchup = frame[frame["timestamp"] > checkpoint].copy().sort_values("timestamp").reset_index(drop=True)
    first_quality = _quality(catchup)
    bars_15m = _complete_resample(catchup, "15min", 15)
    bars_1h = _complete_resample(catchup, "1h", 60)
    decisions = _decision_rows(symbol, bars_1h)
    symbol_root = output_root / "symbol_runtime_snapshots" / symbol
    symbol_root.mkdir(parents=True, exist_ok=True)
    catchup.to_csv(symbol_root / "first_run_catchup_1m_window.csv", index=False)
    bars_15m.to_csv(symbol_root / "first_run_complete_15m_bars.csv", index=False)
    bars_1h.to_csv(symbol_root / "first_run_complete_1h_bars.csv", index=False)
    _write_csv(symbol_root / "first_run_decision_slots.csv", decisions)

    second_catchup = frame[frame["timestamp"] > latest].copy()
    second_bars = _complete_resample(second_catchup, "1h", 60)
    second_decisions = _decision_rows(symbol, second_bars)
    combined_keys = [(row["symbol"], row["decision_slot"]) for row in decisions + second_decisions]
    duplicate_decisions = len(combined_keys) - len(set(combined_keys))
    return {
        "symbol": symbol,
        "source_csv": str(source_csv),
        "blocked": False,
        "checkpoint_timestamp_before_first_run": checkpoint.isoformat(),
        "latest_source_timestamp": latest.isoformat(),
        "first_run_rows_processed": int(len(catchup)),
        "first_run_quality": first_quality,
        "first_run_complete_15m_bars": int(len(bars_15m)),
        "first_run_complete_1h_decision_slots": int(len(decisions)),
        "second_run_rows_processed": int(len(second_catchup)),
        "second_run_complete_1h_decision_slots": int(len(second_decisions)),
        "duplicate_decision_count_after_immediate_rerun": duplicate_decisions,
        "idempotency_passed": bool(len(second_catchup) == 0 and len(second_decisions) == 0 and duplicate_decisions == 0),
        "first_run_snapshot_folder": str(symbol_root),
    }


def _btc_scheduler_status(runtime_root: Path) -> dict[str, Any]:
    status = _read_json(runtime_root / "latest_status.json")
    return {
        "source": str(runtime_root / "latest_status.json"),
        "status": status.get("status"),
        "final_reason": status.get("final_reason"),
        "scheduler_installed": bool(status.get("scheduler_installed", False)),
        "scheduler_loaded": bool(status.get("scheduler_loaded", False)),
        "caught_up_to_realtime": bool(status.get("caught_up_to_realtime", False)),
        "paper_validation_ready": bool(status.get("paper_validation_ready", False)),
        "paper_allowed": bool(status.get("paper_allowed", False)),
        "live_allowed": bool(status.get("live_allowed", False)),
        "real_money_allowed": bool(status.get("real_money_allowed", False)),
        "order_path_exists": bool(status.get("order_path_exists", False)),
        "broker_path_exists": bool(status.get("broker_path_exists", False)),
    }


def _write_report(config: MultiSymbolDryRunConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# Multi-Symbol Realtime Scheduler Shadow Dry-Run Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        "- Research-only dry-run. No scheduler was installed or replaced.",
        "- Existing BTC scheduler remains the baseline evidence machine.",
        "- The court uses local historical tail windows to simulate missed-candle catch-up and immediate rerun idempotency.",
        "",
        "## Aggregate result",
        "",
        f"- Symbols checked: `{summary['aggregate']['symbols_checked']}`",
        f"- First-run 1m rows processed: `{summary['aggregate']['first_run_rows_processed']}`",
        f"- First-run complete 15m bars: `{summary['aggregate']['first_run_complete_15m_bars']}`",
        f"- First-run complete 1H decision slots: `{summary['aggregate']['first_run_complete_1h_decision_slots']}`",
        f"- Immediate rerun rows processed: `{summary['aggregate']['second_run_rows_processed']}`",
        f"- Immediate rerun 1H decision slots: `{summary['aggregate']['second_run_complete_1h_decision_slots']}`",
        f"- Duplicate decisions after rerun: `{summary['aggregate']['duplicate_decision_count_after_immediate_rerun']}`",
        "",
        "## Per-symbol results",
        "",
        "| Symbol | 1m rows | 15m bars | 1H decisions | Rerun rows | Duplicate decisions | Clean |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary["symbol_results"]:
        quality = row.get("first_run_quality", {})
        lines.append(
            "| {symbol} | {rows} | {m15} | {h1} | {rerun} | {dupes} | {clean} |".format(
                symbol=row["symbol"],
                rows=int(row.get("first_run_rows_processed") or 0),
                m15=int(row.get("first_run_complete_15m_bars") or 0),
                h1=int(row.get("first_run_complete_1h_decision_slots") or 0),
                rerun=int(row.get("second_run_rows_processed") or 0),
                dupes=int(row.get("duplicate_decision_count_after_immediate_rerun") or 0),
                clean=str(bool(quality.get("clean"))).lower(),
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            "- `paper_validation_ready=false`",
            "- `paper_allowed=false`",
            "- `live_allowed=false`",
            "- `real_money_allowed=false`",
            "- No order path, broker path, private endpoint, signed endpoint, account endpoint, or execution endpoint was created.",
        ]
    )
    (config.output_root / "multi_symbol_realtime_scheduler_shadow_dry_run_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: MultiSymbolDryRunConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    capacity_summary = _read_json(config.scanner_capacity_root / "multi_symbol_scheduler_capacity_liquidity_summary.json")
    if not capacity_summary:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_capacity_liquidity_court_artifact"],
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_symbol_realtime_scheduler_shadow_dry_run_summary.json", summary)
        return summary

    symbol_results: list[dict[str, Any]] = []
    missing: list[str] = []
    for symbol in SYMBOLS:
        source_csv = _source_csv_for_symbol(config.data_root, symbol)
        if source_csv is None:
            missing.append(symbol)
            continue
        symbol_results.append(
            _simulate_symbol(
                symbol,
                source_csv,
                catchup_minutes=config.catchup_minutes,
                output_root=config.output_root,
            )
        )

    aggregate = {
        "symbols_expected": len(SYMBOLS),
        "symbols_checked": len(symbol_results),
        "missing_symbols": missing,
        "first_run_rows_processed": sum(int(row.get("first_run_rows_processed") or 0) for row in symbol_results),
        "first_run_complete_15m_bars": sum(int(row.get("first_run_complete_15m_bars") or 0) for row in symbol_results),
        "first_run_complete_1h_decision_slots": sum(int(row.get("first_run_complete_1h_decision_slots") or 0) for row in symbol_results),
        "second_run_rows_processed": sum(int(row.get("second_run_rows_processed") or 0) for row in symbol_results),
        "second_run_complete_1h_decision_slots": sum(int(row.get("second_run_complete_1h_decision_slots") or 0) for row in symbol_results),
        "duplicate_decision_count_after_immediate_rerun": sum(int(row.get("duplicate_decision_count_after_immediate_rerun") or 0) for row in symbol_results),
    }
    all_symbols_present = len(symbol_results) == len(SYMBOLS) and not missing
    symbol_quality_ok = all(
        not row.get("blocked")
        and bool(row.get("first_run_quality", {}).get("clean"))
        and int(row.get("first_run_rows_processed") or 0) > 0
        and int(row.get("first_run_complete_1h_decision_slots") or 0) > 0
        for row in symbol_results
    )
    idempotency_ok = all(bool(row.get("idempotency_passed")) for row in symbol_results)
    btc_status = _btc_scheduler_status(config.btc_runtime_root)
    btc_scheduler_safe = (
        btc_status["scheduler_installed"]
        and btc_status["scheduler_loaded"]
        and not btc_status["paper_validation_ready"]
        and not btc_status["paper_allowed"]
        and not btc_status["live_allowed"]
        and not btc_status["real_money_allowed"]
        and not btc_status["order_path_exists"]
        and not btc_status["broker_path_exists"]
    )
    capacity_ok_for_next = capacity_summary.get("final_classification") in {
        "MULTI_SYMBOL_SCHEDULER_CAPACITY_LIQUIDITY_READY_RESEARCH_ONLY",
        "MULTI_SYMBOL_SCHEDULER_CAPACITY_LIQUIDITY_WARNING_RESEARCH_ONLY",
    }

    reasons: list[str] = []
    if all_symbols_present and symbol_quality_ok and idempotency_ok and btc_scheduler_safe and capacity_ok_for_next:
        classification = PASSED
        reasons.append("multi_symbol_catchup_resample_and_idempotency_passed_research_only")
        if capacity_summary.get("final_classification", "").endswith("WARNING_RESEARCH_ONLY"):
            reasons.append("previous_capacity_liquidity_warning_remains_before_any_execution_discussion")
    elif all_symbols_present and idempotency_ok and btc_scheduler_safe:
        classification = WARNING
        reasons.append("idempotency_passed_but_quality_or_decision_slot_count_needs_review")
    else:
        classification = FAILED
        if not all_symbols_present:
            reasons.append("missing_symbol_source_files")
        if not symbol_quality_ok:
            reasons.append("one_or_more_symbol_catchup_windows_failed_quality_or_decision_count")
        if not idempotency_ok:
            reasons.append("immediate_rerun_idempotency_failed")
        if not btc_scheduler_safe:
            reasons.append("btc_scheduler_safety_state_not_clean")

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_capacity_liquidity_summary": str(config.scanner_capacity_root / "multi_symbol_scheduler_capacity_liquidity_summary.json"),
        "capacity_liquidity_classification": capacity_summary.get("final_classification"),
        "btc_scheduler_status": btc_status,
        "dry_run_method": {
            "scheduler_installed_by_this_court": False,
            "existing_btc_scheduler_replaced": False,
            "uses_local_historical_tail_as_missed_candle_window": True,
            "catchup_minutes_per_symbol": config.catchup_minutes,
            "writes_runtime_snapshots_under_output_only": True,
            "data_storage_modified": False,
            "strategy_signal_evaluated": False,
            "decision_slots_only": True,
            "closed_1h_candles_only": True,
            "complete_15m_requires_15_source_minutes": True,
            "complete_1h_requires_60_source_minutes": True,
        },
        "aggregate": aggregate,
        "symbol_results": symbol_results,
        "gate": {
            "may_continue_to_multi_symbol_runtime_prototype": classification in {PASSED, WARNING},
            "may_install_multi_symbol_scheduler": False,
            "may_replace_btc_scheduler": False,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "paper_validation_ready": False,
            "next_required_court": "MULTI_SYMBOL_PUBLIC_FETCH_RUNTIME_PROTOTYPE_WITH_SYMBOL_CAPS_RESEARCH_ONLY",
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_symbol_realtime_scheduler_shadow_dry_run_summary.json", summary)
    _write_csv(config.output_root / "multi_symbol_realtime_scheduler_symbol_results.csv", symbol_results)
    decision_rows: list[dict[str, Any]] = []
    for row in symbol_results:
        decision_file = Path(row.get("first_run_snapshot_folder", "")) / "first_run_decision_slots.csv"
        if decision_file.exists():
            with decision_file.open(newline="", encoding="utf-8") as handle:
                decision_rows.extend(csv.DictReader(handle))
    _write_csv(config.output_root / "multi_symbol_first_run_decision_ledger.csv", decision_rows)
    _write_report(config, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-symbol realtime scheduler shadow dry-run idempotency court.")
    parser.add_argument("--data-root", default="data_storage")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    parser.add_argument("--scanner-capacity-root", default="structural_compounding_lab/output/multi_symbol_scheduler_capacity_liquidity_court_001")
    parser.add_argument("--btc-runtime-root", default="structural_compounding_lab/output/forward_validation_runtime")
    parser.add_argument("--catchup-minutes", type=int, default=720)
    args = parser.parse_args()
    root = project_root()
    summary = run(
        MultiSymbolDryRunConfig(
            project_root=root,
            package_root=package_root(),
            data_root=resolve_project_path(args.data_root),
            output_root=resolve_project_path(args.output_dir),
            scanner_capacity_root=resolve_project_path(args.scanner_capacity_root),
            btc_runtime_root=resolve_project_path(args.btc_runtime_root),
            catchup_minutes=args.catchup_minutes,
        )
    )
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
