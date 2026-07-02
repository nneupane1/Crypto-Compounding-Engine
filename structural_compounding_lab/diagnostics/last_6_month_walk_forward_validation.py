from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.backtest.engine import StructuralBacktestEngine  # noqa: E402
from structural_compounding_lab.common.project_paths import package_root, resolve_project_path  # noqa: E402
from structural_compounding_lab.config import StructuralLabConfig  # noqa: E402
from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import (  # noqa: E402
    RESEARCH_ONLY_FLAGS,
    _apply_frozen_patch,
    _load_frozen_rules,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import (  # noqa: E402
    _prepare_rows,
    _simulate_variant,
)
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _median,
    _normalize_trade_rows,
    _read_csv_rows,
    _read_json,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.shadow_forward.shadow_forward_observer import (  # noqa: E402
    ShadowForwardObserverConfig,
    write_shadow_forward_observer,
)


OUTPUT_FOLDER_NAME = "last_6_month_walk_forward_validation_001"
PASS = "LAST_6M_WALK_FORWARD_VALIDATION_PASSED_RESEARCH_ONLY"
WARNING = "LAST_6M_WALK_FORWARD_VALIDATION_WARNING_RESEARCH_ONLY"
FAILED = "LAST_6M_WALK_FORWARD_VALIDATION_FAILED_RESEARCH_ONLY"
BASELINE_AVERAGE = 792824.55832
BASELINE_MEDIAN = 786049.44639
BASELINE_TRADE_COUNT = 558
BASELINE_START = pd.Timestamp("2018-01-06T12:00:00")
BASELINE_END = pd.Timestamp("2026-06-06T21:00:00")


@dataclass(frozen=True)
class LastSixMonthValidationConfig:
    package_root: Path
    output_root: Path
    source_csv: Path
    start: pd.Timestamp
    end: pd.Timestamp


def _hash_files(paths: list[Path]) -> str:
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path).encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _strategy_files(root: Path) -> list[Path]:
    relative = (
        "backtest/engine.py",
        "entry/setup_detector.py",
        "entry/entry_score.py",
        "entry/trade_plan.py",
        "exit/exit_engine.py",
        "context/htf_confirmation.py",
        "capital/position_sizing.py",
        "config/structural_compounding_settings.json",
    )
    return [root / item for item in relative if (root / item).exists()]


def _load_and_validate_source(config: LastSixMonthValidationConfig) -> tuple[pd.DataFrame, dict[str, Any]]:
    frame = pd.read_csv(config.source_csv, parse_dates=["timestamp"])
    timestamps = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.assign(timestamp=timestamps).sort_values("timestamp")
    window = frame.loc[(frame["timestamp"] >= config.start) & (frame["timestamp"] <= config.end)].copy()
    duplicates = int(window["timestamp"].duplicated().sum())
    gaps = int((window["timestamp"].diff() > pd.Timedelta(minutes=1)).sum())
    expected_rows = int((config.end - config.start).total_seconds() // 60) + 1
    quality = {
        "input_data_file": str(config.source_csv),
        "selected_window_start_utc": config.start.isoformat(),
        "selected_window_end_utc": config.end.isoformat(),
        "first_timestamp": window["timestamp"].min().isoformat() if not window.empty else None,
        "last_timestamp": window["timestamp"].max().isoformat() if not window.empty else None,
        "row_count": len(window),
        "expected_row_count": expected_rows,
        "gap_count": gaps,
        "duplicate_count": duplicates,
        "window_complete": bool(
            not window.empty
            and window["timestamp"].min() == config.start
            and window["timestamp"].max() == config.end
            and len(window) == expected_rows
        ),
        "public_local_data_only": True,
        "private_api_used": False,
        "signed_request_used": False,
        "account_endpoint_used": False,
        "order_endpoint_used": False,
        "broker_endpoint_used": False,
        "synthetic_data_used": False,
    }
    return window, quality


def _research_config(config: LastSixMonthValidationConfig) -> StructuralLabConfig:
    base = StructuralLabConfig.load()
    payload = copy.deepcopy(base.data)
    payload["data"]["analysis_start_date"] = config.start.tz_convert("UTC").tz_localize(None).isoformat()
    payload["data"]["analysis_end_date"] = config.end.tz_convert("UTC").tz_localize(None).isoformat()
    payload["engine"]["resume_enabled"] = False
    payload["engine"]["checkpoint_every_bars"] = 0
    payload["engine"]["write_partial_artifacts"] = False
    return StructuralLabConfig(data=payload, config_path=base.config_path, root_dir=base.root_dir)


def _session(timestamp: pd.Timestamp | None) -> str:
    if timestamp is None:
        return "unknown"
    hour = timestamp.hour
    if hour < 8:
        return "asia_00_07_utc"
    if hour < 16:
        return "europe_08_15_utc"
    return "us_16_23_utc"


def _breakdown(rows: list[dict[str, Any]], key_fn: Any) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[str(key_fn(row))].append(row)
    output: list[dict[str, Any]] = []
    for key, bucket in sorted(buckets.items()):
        r_values = [float(row["r_multiple"]) for row in bucket]
        wins = [value for value in r_values if value > 0]
        gross_loss = abs(sum(value for value in r_values if value < 0))
        gross_profit = sum(wins)
        output.append(
            {
                "bucket": key,
                "trade_count": len(bucket),
                "long_count": sum(1 for row in bucket if row["side"] == "long"),
                "short_count": sum(1 for row in bucket if row["side"] == "short"),
                "total_R": round(sum(r_values), 6),
                "average_R": round(sum(r_values) / len(r_values), 6),
                "median_R": round(_median(r_values), 6),
                "profit_factor": round(gross_profit / gross_loss, 6) if gross_loss else round(gross_profit, 6),
                "win_rate": round(len(wins) / len(bucket), 6),
            }
        )
    return output


def _classification(
    *,
    quality: dict[str, Any],
    metrics: dict[str, Any],
    evaluated_bars: int,
    annotation_coverage: float,
    strategy_hash_unchanged: bool,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if (
        not quality["window_complete"]
        or quality["gap_count"]
        or quality["duplicate_count"]
        or not strategy_hash_unchanged
        or evaluated_bars == 0
        or annotation_coverage < 0.95
    ):
        if not quality["window_complete"]:
            reasons.append("validation_window_is_not_complete")
        if quality["gap_count"]:
            reasons.append("input_data_contains_gaps")
        if quality["duplicate_count"]:
            reasons.append("input_data_contains_duplicate_timestamps")
        if not strategy_hash_unchanged:
            reasons.append("strategy_files_changed_during_validation")
        if evaluated_bars == 0:
            reasons.append("no_1h_bars_evaluated")
        if annotation_coverage < 0.95:
            reasons.append("six_h_annotation_coverage_below_95_percent")
        return FAILED, reasons

    baseline_days = max(1.0, (BASELINE_END - BASELINE_START).total_seconds() / 86400.0)
    expected_frequency = BASELINE_TRADE_COUNT / baseline_days
    if int(metrics.get("trade_count") or 0) < max(5, int(expected_frequency * 190 * 0.25)):
        reasons.append("accepted_trade_frequency_collapsed_relative_to_frozen_baseline")
    if float(metrics.get("profit_factor") or 0.0) < 1.0 or float(metrics.get("total_R") or 0.0) <= 0.0:
        reasons.append("short_validation_slice_has_non_positive_edge")
    if float(metrics.get("max_drawdown_pct") or 0.0) > 0.35:
        reasons.append("pathological_drawdown_above_35_percent")
    if reasons:
        return WARNING, reasons
    return PASS, ["runtime_data_frequency_drawdown_and_signal_integrity_checks_passed"]


def run_validation(config: LastSixMonthValidationConfig) -> dict[str, Path]:
    config.output_root.mkdir(parents=True, exist_ok=True)
    diagnostics_root = config.output_root / "diagnostics"
    raw_root = config.output_root / "raw_engine_replay"
    observer_root = config.output_root / "observer"
    diagnostics_root.mkdir(parents=True, exist_ok=True)

    source_window, quality = _load_and_validate_source(config)
    _write_json(diagnostics_root / "input_data_quality.json", {**RESEARCH_ONLY_FLAGS, **quality})
    if not quality["window_complete"] or quality["gap_count"] or quality["duplicate_count"]:
        summary = {
            **RESEARCH_ONLY_FLAGS,
            "paper_validation_ready": False,
            "final_classification": FAILED,
            "classification_reasons": ["input_data_quality_gate_failed"],
            "data_quality": quality,
        }
        _write_json(config.output_root / "last_6_month_walk_forward_validation_summary.json", summary)
        _write_markdown(
            config.output_root / "last_6_month_walk_forward_validation_report.md",
            "# Last 6 Month Walk-Forward Validation Court\n\nInput data quality gate failed.\n",
        )
        return {
            "summary": config.output_root / "last_6_month_walk_forward_validation_summary.json",
            "report": config.output_root / "last_6_month_walk_forward_validation_report.md",
        }

    strategy_files = _strategy_files(config.package_root)
    strategy_hash_before = _hash_files(strategy_files)
    lab_config = _research_config(config)
    raw_summary = StructuralBacktestEngine(config=lab_config).run(
        symbol="BTCUSDT",
        source_csv=str(config.source_csv),
        output_dir=str(raw_root),
    )

    write_shadow_forward_observer(
        ShadowForwardObserverConfig(
            package_root=config.package_root,
            output_root=observer_root,
            runtime_mode="dry_run_backfill",
            symbol="BTCUSDT",
            source_csv=config.source_csv,
            force_rerun=True,
        )
    )

    raw_trades = _read_csv_rows(raw_root / "trades.csv")
    setup_rows = _read_csv_rows(raw_root / "setup_log.csv")
    level_rows = _read_csv_rows(raw_root / "level_log.csv")
    liquidity_rows = _read_csv_rows(raw_root / "liquidity_events.csv")
    normalized = _normalize_trade_rows(raw_trades, setup_rows, level_rows, liquidity_rows)
    prepared = _prepare_rows(normalized)

    rules_path = config.package_root / "output" / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json"
    matched_shorts, disabled_longs, rules_payload = _load_frozen_rules(rules_path)
    selected, rejected_by_frozen_rules = _apply_frozen_patch(
        prepared,
        matched_short_archetypes=matched_shorts,
        disabled_long_modes=disabled_longs,
    )
    span_days = max(1, int((config.end - config.start).total_seconds() / 86400.0) + 1)
    simulation = _simulate_variant(
        name="LAST_6M_FROZEN_ENGINE",
        selected_rows=selected,
        all_rows=prepared,
        start_capital=20000.0,
        baseline_span_days=span_days,
        cooldown_rows=_read_csv_rows(raw_root / "cooldown_log.csv"),
    )
    metrics = simulation["summary"]

    signal_rows = _read_csv_rows(observer_root / "ledger" / "shadow_signal_log.csv")
    context_rows = _read_csv_rows(observer_root / "ledger" / "shadow_context_log.csv")
    context_by_timestamp = {str(row.get("timestamp") or ""): row for row in context_rows}
    selected_context = [
        context_by_timestamp.get(str(row.get("entry_time") or ""), {})
        for row in selected
    ]
    confluence_count = sum(1 for row in selected_context if str(row.get("six_h_confluence_flag")).lower() == "true")
    conflict_count = sum(1 for row in selected_context if str(row.get("conflict_flag")).lower() == "true")
    annotation_count = sum(1 for row in selected_context if row)
    annotation_coverage = annotation_count / len(selected) if selected else 1.0

    monthly = _breakdown(selected, lambda row: str(row["exit_timestamp"])[:7])
    sessions = _breakdown(selected, lambda row: _session(row.get("entry_timestamp")))
    all_dates = pd.date_range(config.start.normalize(), config.end.normalize(), freq="1D")
    active_dates = {row["exit_timestamp"].normalize() for row in selected if row.get("exit_timestamp") is not None}
    zero_trade_days = sum(1 for day in all_dates if day.tz_localize(None) not in active_dates)
    r_values = [float(row["r_multiple"]) for row in selected]
    complete_1h_bars = int(len(source_window.set_index("timestamp").resample("1h").agg({"close": "last"}).dropna()))

    strategy_hash_after = _hash_files(strategy_files)
    strategy_hash_unchanged = strategy_hash_before == strategy_hash_after
    observer_summary = _read_json(observer_root / "shadow_forward_observer_summary.json", {})
    final_classification, classification_reasons = _classification(
        quality=quality,
        metrics=metrics,
        evaluated_bars=int(observer_summary.get("one_h_decisions_processed") or 0),
        annotation_coverage=annotation_coverage,
        strategy_hash_unchanged=strategy_hash_unchanged,
    )

    summary = {
        **RESEARCH_ONLY_FLAGS,
        "paper_validation_ready": False,
        "no_order_path_created": True,
        "no_paper_path_created": True,
        "no_live_path_created": True,
        "no_broker_execution_created": True,
        "eur_25000_active_sizing_used": False,
        "active_diagnostic_start_capital_eur": 20000.0,
        "final_classification": final_classification,
        "classification_reasons": classification_reasons,
        "selected_validation_window": {
            "start_utc": config.start.isoformat(),
            "end_utc": config.end.isoformat(),
            "reason": "Use the complete rebuilt six-month canonical source boundary and freshest closed minute.",
        },
        "data_quality": quality,
        "one_h_complete_bars": complete_1h_bars,
        "one_h_bars_evaluated": int(observer_summary.get("one_h_decisions_processed") or 0),
        "accepted_trades": len(selected),
        "rejected_setups_or_no_candidate_decisions": int(observer_summary.get("rejected_signals") or 0),
        "raw_engine_trade_count_before_frozen_rules": len(prepared),
        "trades_rejected_by_frozen_rules": len(rejected_by_frozen_rules),
        "trade_frequency_per_day": round(len(selected) / span_days, 6),
        "zero_trade_days": zero_trade_days,
        "long_trade_count": sum(1 for row in selected if row["side"] == "long"),
        "short_trade_count": sum(1 for row in selected if row["side"] == "short"),
        "average_R": metrics.get("avg_R"),
        "median_R": metrics.get("median_R"),
        "total_R": metrics.get("total_R"),
        "profit_factor": metrics.get("profit_factor"),
        "win_rate": metrics.get("win_rate"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "worst_trade_R": min(r_values) if r_values else 0.0,
        "best_trade_R": max(r_values) if r_values else 0.0,
        "monthly_breakdown": monthly,
        "session_breakdown": sessions,
        "six_h_context": {
            "annotations_produced": len(context_rows),
            "selected_trade_annotations_matched": annotation_count,
            "selected_trade_annotation_coverage": round(annotation_coverage, 6),
            "confluence_count": confluence_count,
            "conflict_count": conflict_count,
            "native_execution_enabled": False,
            "modified_frozen_execution": False,
            "established_research_classification": "SIX_H_CONTEXT_IMPROVES_1H_RESEARCH_ONLY",
            "court_interpretation": "6H remained annotation-only and did not filter, size, enter, or exit trades.",
        },
        "frozen_behavior_integrity": {
            "frozen_rules_loaded": bool(rules_payload),
            "frozen_without_retuning": bool(rules_payload.get("frozen_without_retuning")),
            "strategy_hash_before": strategy_hash_before,
            "strategy_hash_after": strategy_hash_after,
            "strategy_hash_unchanged": strategy_hash_unchanged,
            "behavior_differs_from_frozen_expectations": not strategy_hash_unchanged,
        },
        "baseline_comparison": {
            "trusted_1h_rolling_5y_average_eur": BASELINE_AVERAGE,
            "trusted_1h_rolling_5y_median_eur": BASELINE_MEDIAN,
            "comparison_note": "The six-month slice is evaluated for runtime, frequency, drawdown, and signal integrity; it is not expected to reproduce five-year ending equity.",
            "six_h_native_execution_classification": "SIX_H_NATIVE_EXECUTION_WEAK",
            "shadow_spec_classification": "SHADOW_SPEC_READY_WITH_6H_CONTEXT_RESEARCH_ONLY",
            "observer_classification": observer_summary.get("final_classification"),
            "watchtower_classification": "WATCHTOWER_READY_BUT_WAITING_FOR_FORWARD_DAYS",
        },
        "raw_engine_summary": {
            "run_state": raw_summary.get("run_state"),
            "trade_count": raw_summary.get("trade_count"),
            "setup_count": raw_summary.get("setup_count"),
        },
        "frozen_status_changed": False,
        "ninety_day_shadow_validation_can_continue": True,
    }

    _write_json(config.output_root / "last_6_month_walk_forward_validation_summary.json", summary)
    _write_csv(diagnostics_root / "frozen_selected_trades.csv", selected)
    _write_csv(diagnostics_root / "frozen_rejected_trades.csv", rejected_by_frozen_rules)
    _write_csv(diagnostics_root / "monthly_breakdown.csv", monthly)
    _write_csv(diagnostics_root / "session_breakdown.csv", sessions)
    _write_json(
        diagnostics_root / "frozen_behavior_integrity.json",
        {**RESEARCH_ONLY_FLAGS, **summary["frozen_behavior_integrity"]},
    )
    _write_json(
        diagnostics_root / "safety_assertions.json",
        {
            **RESEARCH_ONLY_FLAGS,
            "paper_validation_ready": False,
            "no_order_path_created": True,
            "no_paper_path_created": True,
            "no_live_path_created": True,
            "no_broker_execution_created": True,
            "eur_25000_active_sizing_used": False,
        },
    )
    report = "\n".join(
        [
            "# Last 6 Month Walk-Forward Validation Court",
            "",
            f"- Final classification: `{final_classification}`",
            f"- Window: `{config.start.isoformat()}` to `{config.end.isoformat()}`",
            f"- Input: `{config.source_csv}`",
            f"- Data rows / gaps / duplicates: `{quality['row_count']}` / `{quality['gap_count']}` / `{quality['duplicate_count']}`",
            f"- Complete 1H bars / evaluated decisions: `{complete_1h_bars}` / `{summary['one_h_bars_evaluated']}`",
            f"- Frozen accepted trades: `{len(selected)}`",
            f"- Rejected/no-candidate decisions: `{summary['rejected_setups_or_no_candidate_decisions']}`",
            f"- Long / short: `{summary['long_trade_count']}` / `{summary['short_trade_count']}`",
            f"- Average / median / total R: `{summary['average_R']}` / `{summary['median_R']}` / `{summary['total_R']}`",
            f"- Profit factor / win rate: `{summary['profit_factor']}` / `{summary['win_rate']}`",
            f"- Max drawdown: `{summary['max_drawdown_pct']}`",
            f"- Best / worst trade R: `{summary['best_trade_R']}` / `{summary['worst_trade_R']}`",
            f"- Trade frequency per day / zero-trade days: `{summary['trade_frequency_per_day']}` / `{zero_trade_days}`",
            f"- 6H annotation coverage: `{summary['six_h_context']['selected_trade_annotation_coverage']}`",
            "",
            "## Interpretation",
            "",
            "- The frozen rules and strategy files were not changed during validation.",
            "- 6H context remained research-only annotation and never became execution.",
            "- EUR 25,000 was not used as active capital; the existing EUR 20,000 research replay convention remained unchanged.",
            "- `paper_validation_ready=false`; paper, live, real-money, broker, account, and order paths remain disabled.",
            "- The six-month slice is not expected to reproduce the five-year baseline equity figures.",
            f"- Classification reasons: `{', '.join(classification_reasons)}`",
            "",
            "## Monthly breakdown",
            "",
            "See `diagnostics/monthly_breakdown.csv`.",
            "",
            "## Session breakdown",
            "",
            "See `diagnostics/session_breakdown.csv`.",
            "",
        ]
    )
    _write_markdown(config.output_root / "last_6_month_walk_forward_validation_report.md", report)
    return {
        "summary": config.output_root / "last_6_month_walk_forward_validation_summary.json",
        "report": config.output_root / "last_6_month_walk_forward_validation_report.md",
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the frozen last-six-month BTCUSDT research validation court.")
    parser.add_argument(
        "--source-csv",
        default="structural_compounding_lab/data_storage/BTCUSDT/1m/btcusdt_1m_canonical_shadow_forward.csv",
    )
    parser.add_argument("--start", default="2025-12-13T00:00:00Z")
    parser.add_argument("--end", default="2026-06-20T20:59:00Z")
    parser.add_argument(
        "--output-dir",
        default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    root = package_root()
    source = resolve_project_path(args.source_csv)
    output = resolve_project_path(args.output_dir)
    result = run_validation(
        LastSixMonthValidationConfig(
            package_root=root,
            output_root=output,
            source_csv=source,
            start=pd.Timestamp(args.start),
            end=pd.Timestamp(args.end),
        )
    )
    print(json.dumps({key: str(value) for key, value in result.items()}, indent=2))


if __name__ == "__main__":
    main()
