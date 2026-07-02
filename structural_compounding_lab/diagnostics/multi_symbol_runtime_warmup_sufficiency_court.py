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
from structural_compounding_lab.config.settings import load_structural_lab_config
from structural_compounding_lab.shadow_forward.multi_symbol_forward_runtime import SYMBOLS


COURT_NAME = "MULTI_SYMBOL_RUNTIME_WARMUP_SUFFICIENCY_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_symbol_runtime_warmup_sufficiency_court_001"

OBSERVATION_READY = "MULTI_SYMBOL_RUNTIME_WARMUP_OBSERVATION_READY_RESEARCH_ONLY"
STRATEGY_READY = "MULTI_SYMBOL_RUNTIME_WARMUP_STRATEGY_DECISION_READY_RESEARCH_ONLY"
WARNING = "MULTI_SYMBOL_RUNTIME_WARMUP_OBSERVATION_READY_STRATEGY_DECISION_NOT_READY_RESEARCH_ONLY"
FAILED = "MULTI_SYMBOL_RUNTIME_WARMUP_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_SYMBOL_RUNTIME_WARMUP_BLOCKED_RESEARCH_ONLY"

MIN_OBSERVATION_1M_ROWS = 1_440
MIN_OBSERVATION_COMPLETE_1H_BARS = 24
MIN_PROFESSIONAL_1M_MEMORY_DAYS = 30

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
class WarmupSufficiencyConfig:
    project_root: Path
    package_root: Path
    runtime_root: Path
    output_root: Path


def default_config() -> WarmupSufficiencyConfig:
    pkg = package_root()
    return WarmupSufficiencyConfig(
        project_root=project_root(),
        package_root=pkg,
        runtime_root=pkg / "output" / "multi_symbol_forward_runtime_earned_parallel_slots",
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
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in keys})


def _settings_requirements() -> dict[str, Any]:
    settings = load_structural_lab_config()
    engine = dict(settings.get("engine", default={}) or {})
    ema = dict(settings.get("ema", default={}) or {})
    required_complete_1h = max(
        int(engine.get("structure_window_bars", 240) or 240),
        int(engine.get("liquidity_window_bars", 160) or 160),
        int(engine.get("setup_window_bars", 96) or 96),
        int(ema.get("slow", 200) or 200),
    )
    return {
        "structure_window_bars": int(engine.get("structure_window_bars", 240) or 240),
        "liquidity_window_bars": int(engine.get("liquidity_window_bars", 160) or 160),
        "setup_window_bars": int(engine.get("setup_window_bars", 96) or 96),
        "ema_slow_bars": int(ema.get("slow", 200) or 200),
        "minimum_complete_1h_bars_for_current_1h_structure_logic": required_complete_1h,
        "minimum_1m_rows_for_current_1h_structure_logic": required_complete_1h * 60,
        "professional_30d_1m_memory_rows": MIN_PROFESSIONAL_1M_MEMORY_DAYS * 24 * 60,
        "confirmation_timeframes_declared": list(settings.get("confirmation_timeframes", default=[]) or []),
        "confirmation_timeframes_materialized_by_active_runtime": ["15m", "1h"],
    }


def _runtime_rows(runtime_root: Path, symbol: str) -> dict[str, Any]:
    path = runtime_root / "symbol_runtime_snapshots" / symbol / "runtime_1m_copy.csv"
    bars_1h_path = runtime_root / "symbol_runtime_snapshots" / symbol / "complete_1h_bars.csv"
    if not path.exists():
        return {
            "symbol": symbol,
            "runtime_copy_exists": False,
            "runtime_copy": str(path),
            "observation_warmup_passed": False,
            "strategy_1h_warmup_passed": False,
        }
    frame = pd.read_csv(path)
    ts = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce").dt.tz_convert(None).dropna().sort_values().reset_index(drop=True)
    diffs = ts.diff().dropna()
    gaps = diffs[diffs > pd.Timedelta(minutes=1)]
    missing = int(sum(int(diff / pd.Timedelta(minutes=1)) - 1 for diff in gaps))
    duplicate_count = int(frame["timestamp"].duplicated().sum())
    ohlc_failures = frame[
        (pd.to_numeric(frame["high"], errors="coerce") < frame[["open", "close", "low"]].apply(pd.to_numeric, errors="coerce").max(axis=1))
        | (pd.to_numeric(frame["low"], errors="coerce") > frame[["open", "close", "high"]].apply(pd.to_numeric, errors="coerce").min(axis=1))
        | (pd.to_numeric(frame["high"], errors="coerce") < pd.to_numeric(frame["low"], errors="coerce"))
        | (pd.to_numeric(frame["open"], errors="coerce") <= 0)
        | (pd.to_numeric(frame["high"], errors="coerce") <= 0)
        | (pd.to_numeric(frame["low"], errors="coerce") <= 0)
        | (pd.to_numeric(frame["close"], errors="coerce") <= 0)
        | (pd.to_numeric(frame["volume"], errors="coerce") < 0)
    ]
    complete_1h = len(pd.read_csv(bars_1h_path)) if bars_1h_path.exists() else 0
    first = ts.iloc[0] if len(ts) else None
    last = ts.iloc[-1] if len(ts) else None
    span_minutes = int((last - first) / pd.Timedelta(minutes=1)) + 1 if first is not None and last is not None else 0
    clean = len(gaps) == 0 and missing == 0 and duplicate_count == 0 and len(ohlc_failures) == 0
    return {
        "symbol": symbol,
        "runtime_copy_exists": True,
        "runtime_copy": str(path),
        "rows_1m": int(len(frame)),
        "first_timestamp": first.isoformat() if first is not None else None,
        "last_timestamp": last.isoformat() if last is not None else None,
        "span_hours": span_minutes / 60.0,
        "gap_count": int(len(gaps)),
        "missing_minutes": missing,
        "duplicate_count": duplicate_count,
        "ohlc_failure_count": int(len(ohlc_failures)),
        "quality_clean": clean,
        "complete_1h_bars": int(complete_1h),
    }


def _write_report(config: WarmupSufficiencyConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# Multi-Symbol Runtime Warm-Up Sufficiency Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        "- Research-only. This audit does not change strategy, entries, exits, sizing, paper/live, order, or broker behavior.",
        "",
        "## Verdict",
        "",
        f"- Observation runtime freeze-ready: `{str(summary['gate']['observation_runtime_freeze_ready']).lower()}`",
        f"- Strategy-decision freeze-ready: `{str(summary['gate']['strategy_decision_runtime_freeze_ready']).lower()}`",
        f"- Active runtime evaluates full strategy: `{str(summary['active_runtime_strategy_evaluation']['full_strategy_evaluated_by_runtime']).lower()}`",
        "",
        "## Requirements",
        "",
        f"- Minimum observation 1m rows: `{summary['requirements']['minimum_observation_1m_rows']}`",
        f"- Minimum configured 1H strategy warm-up bars: `{summary['requirements']['minimum_complete_1h_bars_for_current_1h_structure_logic']}`",
        f"- Professional 30-day 1m memory rows: `{summary['requirements']['professional_30d_1m_memory_rows']}`",
        "",
        "| Symbol | 1m rows | Complete 1H | Span hours | Clean | Observation OK | Strategy warm-up OK |",
        "| --- | ---: | ---: | ---: | --- | --- | --- |",
    ]
    for row in summary["symbol_rows"]:
        lines.append(
            "| {symbol} | {rows} | {h1} | {span:.2f} | {clean} | {obs} | {strategy} |".format(
                symbol=row["symbol"],
                rows=int(row.get("rows_1m") or 0),
                h1=int(row.get("complete_1h_bars") or 0),
                span=float(row.get("span_hours") or 0.0),
                clean=str(bool(row.get("quality_clean"))).lower(),
                obs=str(bool(row.get("observation_warmup_passed"))).lower(),
                strategy=str(bool(row.get("strategy_1h_warmup_passed"))).lower(),
            )
        )
    lines.extend(
        [
            "",
            "## Required next action",
            "",
            summary["required_next_action"],
        ]
    )
    (config.output_root / "multi_symbol_runtime_warmup_sufficiency_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: WarmupSufficiencyConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    status_path = config.runtime_root / "latest_status.json"
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
        _write_json(config.output_root / "multi_symbol_runtime_warmup_sufficiency_summary.json", summary)
        return summary

    req = _settings_requirements()
    symbols = list(status.get("active_symbols") or SYMBOLS)
    rows = [_runtime_rows(config.runtime_root, symbol) for symbol in symbols]
    required_1h = int(req["minimum_complete_1h_bars_for_current_1h_structure_logic"])
    for row in rows:
        row["observation_warmup_passed"] = bool(
            row.get("runtime_copy_exists")
            and row.get("quality_clean")
            and int(row.get("rows_1m") or 0) >= MIN_OBSERVATION_1M_ROWS
            and int(row.get("complete_1h_bars") or 0) >= MIN_OBSERVATION_COMPLETE_1H_BARS
        )
        row["strategy_1h_warmup_passed"] = bool(
            row.get("runtime_copy_exists")
            and row.get("quality_clean")
            and int(row.get("complete_1h_bars") or 0) >= required_1h
        )
        row["professional_30d_memory_passed"] = bool(
            row.get("runtime_copy_exists")
            and row.get("quality_clean")
            and int(row.get("rows_1m") or 0) >= int(req["professional_30d_1m_memory_rows"])
        )

    all_observation = all(bool(row.get("observation_warmup_passed")) for row in rows)
    all_strategy = all(bool(row.get("strategy_1h_warmup_passed")) for row in rows)
    all_30d = all(bool(row.get("professional_30d_memory_passed")) for row in rows)
    full_strategy_eval = False
    if all_observation and all_strategy and all_30d and full_strategy_eval:
        classification = STRATEGY_READY
        reasons = ["all_symbols_have_professional_memory_and_strategy_evaluation_is_integrated"]
    elif all_observation:
        classification = WARNING
        reasons = ["runtime_observation_ready_but_strategy_decision_warmup_or_strategy_integration_not_ready"]
    else:
        classification = FAILED
        reasons = ["one_or_more_symbols_not_ready_even_for_observation_warmup"]

    blockers = []
    if not all_strategy:
        blockers.append("not_all_symbols_have_240_complete_1h_bars_required_by_current_structure_logic")
    if not all_30d:
        blockers.append("not_all_symbols_have_30_days_of_1m_runtime_memory")
    if not full_strategy_eval:
        blockers.append("active_runtime_records_decision_slots_but_does_not_evaluate_full_strategy")

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_runtime_status": str(status_path),
        "source_runtime_root": str(config.runtime_root),
        "requirements": {
            "minimum_observation_1m_rows": MIN_OBSERVATION_1M_ROWS,
            "minimum_observation_complete_1h_bars": MIN_OBSERVATION_COMPLETE_1H_BARS,
            **req,
        },
        "active_runtime_strategy_evaluation": {
            "full_strategy_evaluated_by_runtime": full_strategy_eval,
            "runtime_current_behavior": "closed_1h_decision_slot_ledger_only",
            "strategy_signal_evaluated_default": False,
            "scanner_selection_evaluated_default": False,
        },
        "symbol_rows": rows,
        "gate": {
            "observation_runtime_freeze_ready": all_observation,
            "strategy_decision_runtime_freeze_ready": all_strategy and all_30d and full_strategy_eval,
            "may_authorize_first_trade_decision_from_this_runtime": False,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "paper_validation_ready": False,
        },
        "blockers_to_strategy_decision_freeze": blockers,
        "required_next_action": (
            "Keep the 9-symbol scheduler frozen only as an observation/data-ingestion runtime. "
            "Before any first paper/live strategy decision, extend warm-up to at least 30 days per symbol, "
            "materialize required HTF context, and integrate the frozen strategy evaluator so strategy_signal_evaluated can become true."
        ),
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_symbol_runtime_warmup_sufficiency_summary.json", summary)
    _write_csv(config.output_root / "multi_symbol_runtime_warmup_sufficiency_rows.csv", rows)
    _write_report(config, summary)
    return _round_payload(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--runtime-root", default="structural_compounding_lab/output/multi_symbol_forward_runtime_earned_parallel_slots")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        WarmupSufficiencyConfig(
            project_root=root,
            package_root=package_root(),
            runtime_root=resolve_project_path(args.runtime_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
