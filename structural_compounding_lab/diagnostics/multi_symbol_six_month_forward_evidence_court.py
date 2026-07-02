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
from structural_compounding_lab.diagnostics.multi_symbol_public_fetch_runtime_prototype_court import SYMBOLS


COURT_NAME = "MULTI_SYMBOL_SIX_MONTH_FORWARD_EVIDENCE_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_symbol_six_month_forward_evidence_court_001"
ACTIVE_MULTI_SYMBOL_RUNTIME_FOLDER = "multi_symbol_forward_runtime_earned_parallel_slots"

PASSED = "MULTI_SYMBOL_SIX_MONTH_FORWARD_EVIDENCE_PASSED_RESEARCH_ONLY"
READY = "MULTI_SYMBOL_SIX_MONTH_FORWARD_EVIDENCE_READY_RESEARCH_ONLY"
WARNING = "MULTI_SYMBOL_SIX_MONTH_FORWARD_EVIDENCE_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_SYMBOL_SIX_MONTH_FORWARD_EVIDENCE_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_SYMBOL_SIX_MONTH_FORWARD_EVIDENCE_BLOCKED_RESEARCH_ONLY"

TARGET_DAYS = 180
TARGET_HOURS = TARGET_DAYS * 24
MIN_REQUIRED_SYMBOLS = len(SYMBOLS)

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
class SixMonthForwardEvidenceConfig:
    project_root: Path
    package_root: Path
    public_fetch_root: Path
    reduced_cap_root: Path
    output_root: Path


def default_config() -> SixMonthForwardEvidenceConfig:
    pkg = package_root()
    return SixMonthForwardEvidenceConfig(
        project_root=project_root(),
        package_root=pkg,
        public_fetch_root=pkg / "output" / ACTIVE_MULTI_SYMBOL_RUNTIME_FOLDER,
        reduced_cap_root=pkg / "output" / "multi_symbol_reduced_cap_gear_ladder_restatement_court_001",
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


def _runtime_copy_path(public_fetch_root: Path, symbol: str) -> Path:
    runtime_path = public_fetch_root / "symbol_runtime_snapshots" / symbol / "runtime_1m_copy.csv"
    if runtime_path.exists():
        return runtime_path
    return public_fetch_root / "symbol_runtime_snapshots" / symbol / "prototype_runtime_1m_copy.csv"


def _runtime_summary_path(public_fetch_root: Path) -> Path:
    for candidate in (
        public_fetch_root / "multi_symbol_forward_runtime_summary.json",
        public_fetch_root / "latest_status.json",
        public_fetch_root / "multi_symbol_public_fetch_runtime_prototype_summary.json",
    ):
        if candidate.exists():
            return candidate
    return public_fetch_root / "multi_symbol_forward_runtime_summary.json"


def _runtime_prerequisite_passed(summary: dict[str, Any]) -> bool:
    if summary.get("final_classification") == "MULTI_SYMBOL_PUBLIC_FETCH_RUNTIME_PROTOTYPE_PASSED_RESEARCH_ONLY":
        return True
    return bool(summary.get("status_color") in {"GREEN", "YELLOW"} and summary.get("research_only") is True)


def _load_runtime_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame = pd.read_csv(path)
    frame = frame.rename(columns={column: column.lower().strip() for column in frame.columns})
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
            "complete_1h_slots": 0,
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
    hourly = (
        frame.set_index("timestamp")
        .sort_index()
        .resample("1h", label="left", closed="left")
        .agg(source_1m_count=("close", "count"))
    )
    complete_1h = int((hourly["source_1m_count"] == 60).sum())
    missing = int(sum(int(diff / pd.Timedelta(minutes=1)) - 1 for diff in gap_diffs))
    return {
        "rows": int(len(frame)),
        "first_timestamp": timestamps.iloc[0].isoformat(),
        "last_timestamp": timestamps.iloc[-1].isoformat(),
        "gap_count": int(len(gap_diffs)),
        "missing_minutes": missing,
        "duplicate_count": duplicate_count,
        "ohlc_failure_count": int(len(ohlc_failures)),
        "complete_1h_slots": complete_1h,
        "clean": bool(len(gap_diffs) == 0 and duplicate_count == 0 and len(ohlc_failures) == 0),
    }


def _write_contract(config: SixMonthForwardEvidenceConfig, summary: dict[str, Any]) -> None:
    contract = {
        "court_name": COURT_NAME,
        "created_at_utc": summary["created_at_utc"],
        "purpose": "Accumulate six calendar months of multi-symbol forward evidence before any promotion beyond research.",
        "target_days": TARGET_DAYS,
        "target_hours": TARGET_HOURS,
        "symbols": list(SYMBOLS),
        "reduced_symbol_caps_eur": summary.get("recommended_symbol_caps_eur", {}),
        "required_rules": {
            "public_unsigned_binance_klines_only": True,
            "output_runtime_copies_only": True,
            "closed_1h_decision_slots_only": True,
            "max_one_active_trade_shared_pool": True,
            "reduced_symbol_caps_required": True,
            "no_strategy_tuning": True,
            "no_threshold_tuning": True,
            "no_synthetic_candles": True,
            "no_forward_fill_or_back_fill": True,
            "btc_scheduler_must_not_be_replaced_by_this_court": True,
            "paper_validation_ready_must_remain_false": True,
            "paper_live_order_broker_paths_forbidden": True,
        },
        "pass_rules": {
            "minimum_elapsed_calendar_days": TARGET_DAYS,
            "all_symbols_clean": True,
            "no_duplicate_decisions": True,
            "runtime_rerun_idempotent": True,
            "net_cost_equity_primary": True,
            "fill_calibrated_caps_used": True,
            "manual_review_required_before_any_scheduler_replacement": True,
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "six_month_forward_evidence_contract.json", contract)


def _write_report(config: SixMonthForwardEvidenceConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# Multi-Symbol Six-Month Forward Evidence Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        f"- Observation status: `{summary['observation_status']}`",
        f"- Target: `{TARGET_DAYS}` calendar days / `{TARGET_HOURS}` hourly decision slots per fully observed symbol",
        "- Research-only. No paper/live/order/broker path. Does not replace the installed BTC scheduler.",
        "",
        "## Current snapshot",
        "",
        f"- Symbols expected: `{summary['aggregate']['symbols_expected']}`",
        f"- Symbols clean: `{summary['aggregate']['symbols_clean']}`",
        f"- Earliest runtime timestamp: `{summary['aggregate']['earliest_runtime_timestamp']}`",
        f"- Latest runtime timestamp: `{summary['aggregate']['latest_runtime_timestamp']}`",
        f"- Minimum complete `1H` slots currently present: `{summary['aggregate']['minimum_complete_1h_slots']}`",
        "",
        "## Gate",
        "",
        f"- May install multi-symbol scheduler now: `{str(summary['gate']['may_install_multi_symbol_scheduler_now']).lower()}`",
        f"- May replace BTC scheduler: `{str(summary['gate']['may_replace_btc_scheduler']).lower()}`",
        f"- Paper validation ready: `{str(summary['gate']['paper_validation_ready']).lower()}`",
        f"- Next required action: `{summary['gate']['next_required_action']}`",
        "",
        "## Per-symbol quality",
        "",
        "| Symbol | Rows | Gaps | Duplicates | OHLC failures | Complete 1H slots | Clean |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in summary["symbol_results"]:
        lines.append(
            "| {symbol} | {rows} | {gap_count} | {duplicate_count} | {ohlc_failure_count} | {complete_1h_slots} | {clean} |".format(
                **row
            )
        )
    (config.output_root / "multi_symbol_six_month_forward_evidence_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: SixMonthForwardEvidenceConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)

    public_fetch_summary_path = _runtime_summary_path(config.public_fetch_root)
    reduced_cap_summary_path = config.reduced_cap_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json"
    public_fetch = _read_json(public_fetch_summary_path)
    reduced_cap = _read_json(reduced_cap_summary_path)

    missing = []
    if not public_fetch:
        missing.append(str(public_fetch_summary_path))
    if not reduced_cap:
        missing.append(str(reduced_cap_summary_path))
    if missing:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "observation_status": "blocked_missing_prerequisite_artifacts",
            "classification_reasons": ["missing_public_fetch_or_reduced_cap_artifact"],
            "missing_artifacts": missing,
            "gate": {
                "may_install_multi_symbol_scheduler_now": False,
                "may_replace_btc_scheduler": False,
                "may_enable_paper_trading": False,
                "may_enable_live_trading": False,
                "may_create_order_or_broker_path": False,
                "paper_validation_ready": False,
                "next_required_action": "rerun_public_fetch_and_reduced_cap_courts",
            },
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_symbol_six_month_forward_evidence_summary.json", summary)
        return summary

    symbol_results: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        runtime_path = _runtime_copy_path(config.public_fetch_root, symbol)
        if not runtime_path.exists():
            symbol_results.append(
                {
                    "symbol": symbol,
                    "runtime_copy": str(runtime_path),
                    "rows": 0,
                    "first_timestamp": None,
                    "last_timestamp": None,
                    "gap_count": 0,
                    "missing_minutes": 0,
                    "duplicate_count": 0,
                    "ohlc_failure_count": 0,
                    "complete_1h_slots": 0,
                    "clean": False,
                    "blocked": True,
                    "block_reason": "missing_runtime_copy",
                }
            )
            continue
        quality = _quality(_load_runtime_frame(runtime_path))
        symbol_results.append(
            {
                "symbol": symbol,
                "runtime_copy": str(runtime_path),
                "blocked": False,
                "block_reason": "",
                **quality,
            }
        )

    clean_symbols = sum(1 for row in symbol_results if row["clean"])
    blocked_symbols = [row["symbol"] for row in symbol_results if row.get("blocked")]
    dirty_symbols = [row["symbol"] for row in symbol_results if not row["clean"] and not row.get("blocked")]
    complete_slots = [int(row["complete_1h_slots"]) for row in symbol_results if row["clean"]]
    latest_values = [row["last_timestamp"] for row in symbol_results if row["last_timestamp"]]
    earliest_values = [row["first_timestamp"] for row in symbol_results if row["first_timestamp"]]
    minimum_complete_slots = min(complete_slots) if complete_slots else 0

    decision_duplicate_count = int(public_fetch.get("decision_ledger_duplicate_keys") or 0)
    prerequisites_passed = (
        _runtime_prerequisite_passed(public_fetch)
        and reduced_cap.get("final_classification") == "MULTI_SYMBOL_REDUCED_CAP_GEAR_LADDER_RESTATEMENT_PASSED_RESEARCH_ONLY"
        and bool(reduced_cap.get("gate", {}).get("may_treat_500k_gear1_as_fill_calibrated_research_cap")) is True
        and decision_duplicate_count == 0
    )
    all_symbols_clean = clean_symbols == MIN_REQUIRED_SYMBOLS and not blocked_symbols and not dirty_symbols
    enough_six_month_evidence = all_symbols_clean and minimum_complete_slots >= TARGET_HOURS

    if not prerequisites_passed:
        classification = BLOCKED
        status = "blocked_prerequisite_court_not_passed"
        reasons = ["runtime_or_reduced_cap_prerequisite_not_passed"]
    elif blocked_symbols or dirty_symbols:
        classification = FAILED
        status = "failed_current_runtime_quality"
        reasons = ["one_or_more_symbol_runtime_copies_missing_or_unclean"]
    elif enough_six_month_evidence:
        classification = PASSED
        status = "six_month_forward_evidence_complete"
        reasons = ["six_month_multi_symbol_forward_evidence_complete_research_only"]
    else:
        classification = READY
        status = "ready_waiting_for_elapsed_forward_time"
        reasons = ["prerequisites_passed_and_runtime_copies_clean_but_six_months_not_elapsed"]

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "observation_status": status,
        "classification_reasons": reasons,
        "source_public_fetch_summary": str(public_fetch_summary_path),
        "source_runtime_summary": str(public_fetch_summary_path),
        "source_reduced_cap_summary": str(reduced_cap_summary_path),
        "target_days": TARGET_DAYS,
        "target_hours": TARGET_HOURS,
        "recommended_symbol_caps_eur": reduced_cap.get("recommended_symbol_caps_eur", {}),
        "symbol_results": symbol_results,
        "aggregate": {
            "symbols_expected": MIN_REQUIRED_SYMBOLS,
            "symbols_checked": len(symbol_results),
            "symbols_clean": clean_symbols,
            "blocked_symbols": blocked_symbols,
            "dirty_symbols": dirty_symbols,
            "minimum_complete_1h_slots": minimum_complete_slots,
            "target_complete_1h_slots": TARGET_HOURS,
            "remaining_1h_slots_before_six_month_gate": max(0, TARGET_HOURS - minimum_complete_slots),
            "earliest_runtime_timestamp": min(earliest_values) if earliest_values else None,
            "latest_runtime_timestamp": max(latest_values) if latest_values else None,
            "all_symbols_clean": all_symbols_clean,
            "prerequisites_passed": prerequisites_passed,
            "decision_ledger_duplicate_keys": decision_duplicate_count,
        },
        "method": {
            "public_unsigned_binance_klines_only": True,
            "output_runtime_copies_only": True,
            "data_storage_modified": False,
            "btc_scheduler_replaced": False,
            "multi_symbol_scheduler_installed": False,
            "closed_1h_decision_slots_only": True,
            "uses_reduced_fill_calibrated_symbol_caps": True,
            "max_one_active_trade_shared_pool": True,
            "six_months_can_only_pass_after_elapsed_forward_time": True,
        },
        "gate": {
            "may_install_multi_symbol_scheduler_now": False,
            "may_replace_btc_scheduler": False,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "paper_validation_ready": False,
            "next_required_action": "run_multi_symbol_forward_runtime_in_research_mode_until_180_days_of_clean_evidence_exist",
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_symbol_six_month_forward_evidence_summary.json", summary)
    _write_csv(config.output_root / "multi_symbol_forward_evidence_symbol_quality.csv", symbol_results)
    _write_contract(config, summary)
    _write_report(config, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Check the six-month multi-symbol forward evidence gate.")
    parser.add_argument("--public-fetch-root", default=f"structural_compounding_lab/output/{ACTIVE_MULTI_SYMBOL_RUNTIME_FOLDER}")
    parser.add_argument("--reduced-cap-root", default="structural_compounding_lab/output/multi_symbol_reduced_cap_gear_ladder_restatement_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        SixMonthForwardEvidenceConfig(
            project_root=root,
            package_root=package_root(),
            public_fetch_root=resolve_project_path(args.public_fetch_root),
            reduced_cap_root=resolve_project_path(args.reduced_cap_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
