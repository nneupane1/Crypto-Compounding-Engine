from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path
from structural_compounding_lab.shadow_forward import multi_symbol_forward_runtime as runtime


COURT_NAME = "MULTI_SYMBOL_RUNTIME_HISTORICAL_WARM_START_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_symbol_runtime_historical_warm_start_court_001"

PASSED = "MULTI_SYMBOL_HISTORICAL_WARM_START_READY_RESEARCH_ONLY"
WARNING = "MULTI_SYMBOL_HISTORICAL_WARM_START_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_SYMBOL_HISTORICAL_WARM_START_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_SYMBOL_HISTORICAL_WARM_START_BLOCKED_RESEARCH_ONLY"

WARMUP_DAYS = 30
WARMUP_ROWS_1M = WARMUP_DAYS * 24 * 60

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
}


@dataclass(frozen=True)
class HistoricalWarmStartConfig:
    project_root: Path
    package_root: Path
    active_runtime_root: Path
    output_root: Path
    warmup_days: int = WARMUP_DAYS


def default_config() -> HistoricalWarmStartConfig:
    pkg = package_root()
    return HistoricalWarmStartConfig(
        project_root=project_root(),
        package_root=pkg,
        active_runtime_root=pkg / "output" / runtime.OUTPUT_FOLDER_NAME,
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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return "" if math.isnan(value) or math.isinf(value) else round(value, 10)
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in keys})


def _active_symbols(status: dict[str, Any]) -> list[str]:
    symbols = list(status.get("active_symbols") or [])
    return symbols or list(runtime.SYMBOLS)


def _current_runtime_copy(active_runtime_root: Path, symbol: str) -> pd.DataFrame:
    path = active_runtime_root / "symbol_runtime_snapshots" / symbol / "runtime_1m_copy.csv"
    if not path.exists():
        return runtime._normalize_frame(pd.DataFrame())
    return runtime._normalize_frame(pd.read_csv(path))


def _decision_start_by_symbol(decision_ledger: Path, symbols: list[str], latest_safe: pd.Timestamp) -> dict[str, pd.Timestamp]:
    cutoffs: dict[str, pd.Timestamp] = {}
    if decision_ledger.exists() and decision_ledger.stat().st_size > 0:
        with decision_ledger.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                symbol = str(row.get("symbol") or "")
                if symbol not in symbols:
                    continue
                parsed = pd.to_datetime(row.get("decision_slot"), utc=True, errors="coerce")
                if pd.isna(parsed):
                    continue
                slot = pd.Timestamp(parsed).tz_convert(None)
                cutoffs[symbol] = max(cutoffs.get(symbol, slot), slot)
    fallback = latest_safe.floor("1h")
    return {symbol: (cutoffs[symbol] + pd.Timedelta(hours=1)) if symbol in cutoffs else fallback for symbol in symbols}


def _quality(frame: pd.DataFrame) -> dict[str, Any]:
    q = runtime._quality(frame)
    return {
        "rows_1m": int(q.get("rows") or 0),
        "first_timestamp": q.get("first_timestamp"),
        "last_timestamp": q.get("last_timestamp"),
        "gap_count": int(q.get("gap_count") or 0),
        "missing_minutes": int(q.get("missing_minutes") or 0),
        "duplicate_count": int(q.get("duplicate_count") or 0),
        "ohlc_failure_count": int(q.get("ohlc_failure_count") or 0),
        "quality_clean": bool(q.get("clean")),
    }


def _materialize_context(symbol_root: Path, frame: pd.DataFrame) -> dict[str, int]:
    bars_15m = runtime._resample_complete(frame, "15min", 15)
    bars_1h = runtime._resample_complete(frame, "1h", 60)
    bars_12h = runtime._resample_complete(frame, "12h", 720)
    bars_1d = runtime._resample_complete(frame, "1d", 1440)
    bars_1w = runtime._resample_complete(frame, "1W", 10080)
    bars_15m.to_csv(symbol_root / "complete_15m_bars.csv", index=False)
    bars_1h.to_csv(symbol_root / "complete_1h_bars.csv", index=False)
    bars_12h.to_csv(symbol_root / "complete_12h_bars.csv", index=False)
    bars_1d.to_csv(symbol_root / "complete_1d_bars.csv", index=False)
    bars_1w.to_csv(symbol_root / "complete_1w_bars.csv", index=False)
    return {
        "complete_15m_bars": int(len(bars_15m)),
        "complete_1h_bars": int(len(bars_1h)),
        "complete_12h_bars": int(len(bars_12h)),
        "complete_1d_bars": int(len(bars_1d)),
        "complete_1w_bars": int(len(bars_1w)),
    }


def _warm_symbol(
    *,
    symbol: str,
    runtime_config: runtime.MultiSymbolForwardRuntimeConfig,
    active_runtime_root: Path,
    warmup_rows: int,
    decision_start: pd.Timestamp,
) -> dict[str, Any]:
    source_csv = runtime._source_csv_for_symbol(runtime_config, symbol)
    if source_csv is None:
        return {
            "symbol": symbol,
            "blocked": True,
            "block_reason": "missing_source_csv",
            "decision_start": decision_start.isoformat(),
        }
    source_tail = runtime._tail_frame(source_csv, max(warmup_rows + 20_000, warmup_rows))
    current = _current_runtime_copy(active_runtime_root, symbol)
    combined = (
        pd.concat([source_tail, current], ignore_index=True)
        .drop_duplicates("timestamp", keep="last")
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    if combined.empty:
        return {
            "symbol": symbol,
            "blocked": True,
            "block_reason": "empty_combined_source_and_runtime",
            "source_csv": str(source_csv),
            "decision_start": decision_start.isoformat(),
        }
    warmed = combined.tail(warmup_rows).reset_index(drop=True)
    symbol_root = active_runtime_root / "symbol_runtime_snapshots" / symbol
    symbol_root.mkdir(parents=True, exist_ok=True)
    (config_path := symbol_root / "runtime_1m_copy.csv")
    warmed.to_csv(config_path, index=False)
    context_counts = _materialize_context(symbol_root, warmed)
    quality = _quality(warmed)
    complete_1h_before_decision_start = 0
    bars_1h_path = symbol_root / "complete_1h_bars.csv"
    if bars_1h_path.exists():
        bars_1h = pd.read_csv(bars_1h_path)
        timestamps = pd.to_datetime(bars_1h["timestamp"], utc=True, errors="coerce").dt.tz_convert(None)
        complete_1h_before_decision_start = int((timestamps < decision_start).sum())
    return {
        "symbol": symbol,
        "blocked": False,
        "block_reason": "",
        "source_csv": str(source_csv),
        "runtime_copy": str(config_path),
        "decision_start": decision_start.isoformat(),
        "warmup_context_only": True,
        "complete_1h_context_bars_before_decision_start": complete_1h_before_decision_start,
        **quality,
        **context_counts,
    }


def _write_report(config: HistoricalWarmStartConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# Multi-Symbol Historical Warm-Start Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        "- Research-only. Output-local runtime copies only. No `data_storage` mutation.",
        "- Warm-up bars are context only and do not become forward evidence rows.",
        "",
        "| Symbol | 1m rows | First | Last | 1H | 12H | 1D | 1W | Decision start | Clean |",
        "| --- | ---: | --- | --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for row in summary.get("symbol_rows", []):
        lines.append(
            "| {symbol} | {rows} | {first} | {last} | {h1} | {h12} | {d1} | {w1} | {decision} | {clean} |".format(
                symbol=row.get("symbol", ""),
                rows=int(row.get("rows_1m") or 0),
                first=row.get("first_timestamp", ""),
                last=row.get("last_timestamp", ""),
                h1=int(row.get("complete_1h_bars") or 0),
                h12=int(row.get("complete_12h_bars") or 0),
                d1=int(row.get("complete_1d_bars") or 0),
                w1=int(row.get("complete_1w_bars") or 0),
                decision=row.get("decision_start", ""),
                clean=str(bool(row.get("quality_clean"))).lower(),
            )
        )
    lines.extend(
        [
            "",
            "## Gate",
            "",
            f"- May freeze historical warm start for observation runtime: `{str(summary['gate']['may_freeze_historical_warm_start_for_observation_runtime']).lower()}`",
            f"- May authorize first strategy trade decision: `{str(summary['gate']['may_authorize_first_strategy_trade_decision']).lower()}`",
            "- May enable paper/live/order/broker: `false`",
        ]
    )
    (config.output_root / "multi_symbol_runtime_historical_warm_start_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: HistoricalWarmStartConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    status_path = config.active_runtime_root / "latest_status.json"
    status = _read_json(status_path)
    if not status:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_active_runtime_status"],
            "source_runtime_status": str(status_path),
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_symbol_runtime_historical_warm_start_summary.json", summary)
        return summary

    symbols = _active_symbols(status)
    latest_safe = pd.to_datetime(status.get("latest_safe_1m_timestamp"), utc=True, errors="coerce")
    if pd.isna(latest_safe):
        latest_safe = pd.Timestamp(datetime.now(timezone.utc)).floor("min") - pd.Timedelta(minutes=2)
    latest_safe = pd.Timestamp(latest_safe).tz_convert(None)
    cutoffs = _decision_start_by_symbol(
        config.active_runtime_root / "ledger" / "multi_symbol_forward_decision_ledger.csv",
        symbols,
        latest_safe,
    )
    runtime_config = runtime.MultiSymbolForwardRuntimeConfig(
        project_root=config.project_root,
        package_root=config.package_root,
        data_root=config.project_root / "data_storage",
        reduced_cap_root=config.package_root / "output" / "multi_symbol_btc_exact_fill_cap_calibration_court_001",
        output_root=config.active_runtime_root,
        seed_tail_rows=config.warmup_days * 24 * 60,
        max_catchup_minutes=10080,
        throttle_seconds=0.0,
    )

    warmup_rows = int(config.warmup_days * 24 * 60)
    rows = [
        _warm_symbol(
            symbol=symbol,
            runtime_config=runtime_config,
            active_runtime_root=config.active_runtime_root,
            warmup_rows=warmup_rows,
            decision_start=cutoffs[symbol],
        )
        for symbol in symbols
    ]
    all_clean = all(not row.get("blocked") and row.get("quality_clean") for row in rows)
    all_30d = all(int(row.get("rows_1m") or 0) >= warmup_rows for row in rows)
    all_context = all(int(row.get("complete_12h_bars") or 0) > 0 and int(row.get("complete_1d_bars") or 0) > 0 for row in rows)

    if all_clean and all_30d and all_context:
        classification = PASSED
        reasons = ["all_active_symbols_warm_started_with_30d_clean_context"]
    elif all_clean and all_context:
        classification = WARNING
        reasons = ["symbols_clean_and_context_materialized_but_less_than_30d_rows"]
    else:
        classification = FAILED
        reasons = ["one_or_more_symbols_failed_warm_start_quality_or_context_gate"]

    manifest = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "warmup_context_only": True,
        "warmup_days": config.warmup_days,
        "warmup_rows_1m": warmup_rows,
        "decision_start_by_symbol": {symbol: cutoffs[symbol].isoformat() for symbol in symbols},
        "source_court_output_root": str(config.output_root),
        "may_authorize_first_strategy_trade_decision": False,
        **SAFETY_FLAGS,
    }
    manifest_path = config.active_runtime_root / "checkpoints" / "historical_warm_start_manifest.json"
    _write_json(manifest_path, manifest)

    summary = {
        **manifest,
        "classification_reasons": reasons,
        "source_runtime_status": str(status_path),
        "active_runtime_root": str(config.active_runtime_root),
        "active_symbols": symbols,
        "symbol_rows": rows,
        "gate": {
            "may_freeze_historical_warm_start_for_observation_runtime": classification == PASSED,
            "warmup_bars_are_context_only": True,
            "decision_ledger_start_cutoffs_written": True,
            "may_authorize_first_strategy_trade_decision": False,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "paper_validation_ready": False,
            "next_required_court": "STRATEGY_EVALUATOR_INTEGRATION_AND_WARMUP_GATE_RESEARCH_ONLY",
        },
        "active_manifest_path": str(manifest_path),
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_symbol_runtime_historical_warm_start_summary.json", summary)
    _write_json(config.output_root / "historical_warm_start_manifest.json", manifest)
    _write_csv(config.output_root / "multi_symbol_runtime_historical_warm_start_rows.csv", rows)
    _write_report(config, summary)
    return _round_payload(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--active-runtime-root", default=f"structural_compounding_lab/output/{runtime.OUTPUT_FOLDER_NAME}")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    parser.add_argument("--warmup-days", type=int, default=WARMUP_DAYS)
    args = parser.parse_args()
    root = project_root()
    summary = run(
        HistoricalWarmStartConfig(
            project_root=root,
            package_root=package_root(),
            active_runtime_root=resolve_project_path(args.active_runtime_root),
            output_root=resolve_project_path(args.output_dir),
            warmup_days=args.warmup_days,
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
