from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path  # noqa: E402
from structural_compounding_lab.diagnostics.multi_asset_earned_parallel_slot_court import (  # noqa: E402
    ACTIVE_CAP,
    EARNED_SLOT_VARIANTS,
    OUTPUT_FOLDER_NAME as EARNED_OUTPUT_FOLDER_NAME,
    SAFETY_FLAGS as EARNED_SAFETY_FLAGS,
    START_CAPITAL,
    TAX_RESERVE_RATE,
    USER_LITERAL_SLOT_LADDER,
    EarnedParallelSlotConfig,
    _load_rows,
    _replay,
)
from structural_compounding_lab.diagnostics.multi_asset_execution_feasibility_scanner_replay_court import _load_assets  # noqa: E402
from structural_compounding_lab.diagnostics.multi_asset_portfolio_selection_court import (  # noqa: E402
    TRANSFER_ASSETS,
    _max_drawdown,
    _read_json,
    _safe_ratio,
    _write_csv,
    _write_json,
)


COURT_NAME = "MULTI_ASSET_EARNED_PARALLEL_SLOT_ROBUSTNESS_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_asset_earned_parallel_slot_robustness_court_001"

PASSED = "MULTI_ASSET_EARNED_PARALLEL_SLOT_ROBUSTNESS_PASSED_RESEARCH_ONLY"
WARNING = "MULTI_ASSET_EARNED_PARALLEL_SLOT_ROBUSTNESS_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_ASSET_EARNED_PARALLEL_SLOT_ROBUSTNESS_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_ASSET_EARNED_PARALLEL_SLOT_ROBUSTNESS_BLOCKED_RESEARCH_ONLY"

SOURCE_PASSED = "MULTI_ASSET_EARNED_PARALLEL_SLOT_FREEZE_CANDIDATE_RESEARCH_ONLY"
BEST_VARIANT = "user_literal_1pct_each_slot"
ROLLING_YEARS = 5
ROLLING_STEP_MONTHS = 3

SAFETY_FLAGS: dict[str, Any] = {
    **EARNED_SAFETY_FLAGS,
    "paper_validation_ready": False,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "order_path_created": False,
    "broker_path_created": False,
    "scheduler_changed": False,
    "demo_runner_changed": False,
}


@dataclass(frozen=True)
class EarnedParallelSlotRobustnessConfig:
    project_root: Path
    package_root: Path
    transfer_root: Path
    earned_slot_root: Path
    output_root: Path


def default_config() -> EarnedParallelSlotRobustnessConfig:
    pkg = package_root()
    return EarnedParallelSlotRobustnessConfig(
        project_root=project_root(),
        package_root=pkg,
        transfer_root=pkg / "output" / "multi_asset_frozen_transfer_court_001",
        earned_slot_root=pkg / "output" / EARNED_OUTPUT_FOLDER_NAME,
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


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _public(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key not in {"trade_rows", "rejected_rows", "yearly_rows", "selected_signature"}}


def _symbol_caps(source_summary: dict[str, Any]) -> dict[str, float]:
    return {str(symbol): float(cap) for symbol, cap in (source_summary.get("recommended_symbol_caps_eur") or {}).items()}


def _variant_ladder() -> tuple[dict[str, Any], ...]:
    for name, ladder in EARNED_SLOT_VARIANTS:
        if name == BEST_VARIANT:
            return ladder
    return USER_LITERAL_SLOT_LADDER


def _priority_sets(priority: list[str]) -> dict[str, list[str]]:
    return {
        "frozen_priority": list(priority),
        "reversed_priority": list(reversed(priority)),
        "alphabetical_priority": sorted(priority),
    }


def _load_all_rows(config: EarnedParallelSlotRobustnessConfig, priority: list[str]) -> dict[str, list[dict[str, Any]]]:
    assets = _load_assets(type("ScannerConfig", (), {"transfer_root": config.transfer_root})())
    return {
        "research": _load_rows(assets, "research_rows", priority),
        "holdout": _load_rows(assets, "holdout_rows", priority),
    }


def _rolling_starts(rows: list[dict[str, Any]]) -> list[pd.Timestamp]:
    if not rows:
        return []
    first = min(row["entry_timestamp"] for row in rows)
    last = max(row["exit_timestamp"] for row in rows)
    end_limit = last - pd.DateOffset(years=ROLLING_YEARS)
    starts: list[pd.Timestamp] = []
    current = pd.Timestamp(first).floor("D")
    while current <= end_limit:
        starts.append(current)
        current = current + pd.DateOffset(months=ROLLING_STEP_MONTHS)
    return starts


def _rolling_windows(
    rows: list[dict[str, Any]],
    *,
    priority: list[str],
    symbol_caps: dict[str, float],
    ladder: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    records: list[dict[str, Any]] = []
    for start in _rolling_starts(rows):
        end = start + pd.DateOffset(years=ROLLING_YEARS)
        window_rows = [row for row in rows if row["entry_timestamp"] >= start and row["exit_timestamp"] <= end]
        if not window_rows:
            continue
        one_slot = _replay(
            window_rows,
            scenario_id="rolling_baseline_max_one_slot",
            period="research_rolling_5y",
            priority_symbols=priority,
            symbol_caps=symbol_caps,
            ladder=({"min_active_equity": 0.0, "max_slots": 1, "max_total_open_risk_pct": 0.01, "max_risk_per_trade_pct": 0.01},),
            active_cap=ACTIVE_CAP,
            tax_rate=TAX_RESERVE_RATE,
        )
        earned = _replay(
            window_rows,
            scenario_id=BEST_VARIANT,
            period="research_rolling_5y",
            priority_symbols=priority,
            symbol_caps=symbol_caps,
            ladder=ladder,
            active_cap=ACTIVE_CAP,
            tax_rate=TAX_RESERVE_RATE,
        )
        improvement = _safe_ratio(
            float(earned["ending_total_equity_after_tax"]) - float(one_slot["ending_total_equity_after_tax"]),
            float(one_slot["ending_total_equity_after_tax"]),
            0.0,
        )
        records.append(
            {
                "window_start": start.isoformat(),
                "window_end": end.isoformat(),
                "candidate_trades": len(window_rows),
                "baseline_ending_equity_after_tax": one_slot["ending_total_equity_after_tax"],
                "earned_ending_equity_after_tax": earned["ending_total_equity_after_tax"],
                "earned_minus_baseline_eur": earned["ending_total_equity_after_tax"] - one_slot["ending_total_equity_after_tax"],
                "earned_improvement_pct": improvement * 100.0,
                "earned_beats_baseline": earned["ending_total_equity_after_tax"] > one_slot["ending_total_equity_after_tax"],
                "earned_above_start": earned["ending_total_equity_after_tax"] > START_CAPITAL,
                "earned_max_drawdown": earned["max_drawdown_total_after_tax"],
                "earned_profit_factor": earned["profit_factor"],
                "earned_selected_trades": earned["selected_trades"],
                "earned_max_concurrent_positions": earned["max_concurrent_positions"],
            }
        )
    improvements = [float(row["earned_improvement_pct"]) for row in records]
    return {
        "rolling_years": ROLLING_YEARS,
        "step_months": ROLLING_STEP_MONTHS,
        "window_count": len(records),
        "earned_beats_baseline_count": sum(1 for row in records if row["earned_beats_baseline"]),
        "earned_above_start_count": sum(1 for row in records if row["earned_above_start"]),
        "earned_beats_baseline_rate": _safe_ratio(sum(1 for row in records if row["earned_beats_baseline"]), len(records), 0.0),
        "worst_earned_improvement_pct": min(improvements) if improvements else 0.0,
        "median_earned_improvement_pct": float(pd.Series(improvements).median()) if improvements else 0.0,
        "best_earned_improvement_pct": max(improvements) if improvements else 0.0,
        "records": records,
    }


def _priority_stress(
    rows_by_period: dict[str, list[dict[str, Any]]],
    *,
    priority: list[str],
    symbol_caps: dict[str, float],
    ladder: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    stress: dict[str, Any] = {}
    for name, symbols in _priority_sets(priority).items():
        stress[name] = {}
        for period, rows in rows_by_period.items():
            stress[name][period] = _public(
                _replay(
                    rows,
                    scenario_id=f"{BEST_VARIANT}_{name}",
                    period=period,
                    priority_symbols=symbols,
                    symbol_caps=symbol_caps,
                    ladder=ladder,
                    active_cap=ACTIVE_CAP,
                    tax_rate=TAX_RESERVE_RATE,
                )
            )
    return stress


def _cluster_risk_stress(ledger_rows: list[dict[str, str]]) -> dict[str, Any]:
    rows = [row for row in ledger_rows if row.get("scenario_id") == BEST_VARIANT]
    by_period: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        period = row.get("period") or "unknown"
        by_period.setdefault(period, []).append(
            {
                "symbol": row.get("symbol"),
                "trade_id": row.get("trade_id"),
                "entry_time": pd.Timestamp(row["entry_time"]),
                "exit_time": pd.Timestamp(row["exit_time"]),
                "risk_eur": float(row.get("risk_eur") or 0.0),
                "net_r": float(row.get("net_r") or 0.0),
                "total_after_exit_before_year_tax": float(row.get("total_after_exit_before_year_tax") or 0.0),
            }
        )

    output: dict[str, Any] = {}
    for period, period_rows in by_period.items():
        events = sorted({row["entry_time"] for row in period_rows} | {row["exit_time"] for row in period_rows})
        worst_cluster: dict[str, Any] | None = None
        max_open = 0
        for event_time in events:
            open_rows = [row for row in period_rows if row["entry_time"] <= event_time < row["exit_time"]]
            if not open_rows:
                continue
            open_risk = sum(row["risk_eur"] for row in open_rows)
            equity_anchor = max(max(row["total_after_exit_before_year_tax"] for row in open_rows), START_CAPITAL)
            open_risk_pct = _safe_ratio(open_risk, equity_anchor, 0.0)
            max_open = max(max_open, len(open_rows))
            candidate = {
                "event_time": event_time.isoformat(),
                "open_positions": len(open_rows),
                "aggregate_open_risk_eur": open_risk,
                "aggregate_open_risk_pct_of_nearby_equity": open_risk_pct,
                "symbols": sorted({str(row["symbol"]) for row in open_rows}),
                "trade_ids": [row["trade_id"] for row in sorted(open_rows, key=lambda item: str(item["trade_id"]))],
            }
            if worst_cluster is None or open_risk_pct > float(worst_cluster["aggregate_open_risk_pct_of_nearby_equity"]):
                worst_cluster = candidate
        output[period] = {
            "max_concurrent_open_positions": max_open,
            "worst_one_r_loss_cluster": worst_cluster or {},
            "bounded_by_configured_total_open_risk": True,
        }
    return output


def run(config: EarnedParallelSlotRobustnessConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    source_summary_path = config.earned_slot_root / "multi_asset_earned_parallel_slot_summary.json"
    source_ledger_path = config.earned_slot_root / "multi_asset_earned_parallel_slot_trade_ledger.csv"
    required = [
        source_summary_path,
        source_ledger_path,
        config.transfer_root / "multi_asset_frozen_transfer_summary.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_required_source_artifacts"],
            "missing_artifacts": missing,
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_asset_earned_parallel_slot_robustness_summary.json", summary)
        return summary

    source_summary = _read_json(source_summary_path)
    priority = list(source_summary.get("fixed_priority_symbols") or TRANSFER_ASSETS)
    symbol_caps = _symbol_caps(source_summary)
    ladder = _variant_ladder()
    rows_by_period = _load_all_rows(config, priority)
    ledger_rows = _read_csv(source_ledger_path)

    source_ok = source_summary.get("final_classification") == SOURCE_PASSED
    best_variant_ok = source_summary.get("comparison", {}).get("best_variant") == BEST_VARIANT
    sequence_ok = all(bool(value) for key, value in (source_summary.get("sequence_checks") or {}).items() if key.endswith("matches_saved_one_slot_scanner"))

    priority_stress = _priority_stress(rows_by_period, priority=priority, symbol_caps=symbol_caps, ladder=ladder)
    rolling = _rolling_windows(rows_by_period["research"], priority=priority, symbol_caps=symbol_caps, ladder=ladder)
    cluster_stress = _cluster_risk_stress(ledger_rows)

    holdout_priority_ok = all(
        float(periods["holdout"]["ending_total_equity_after_tax"]) > START_CAPITAL
        and float(periods["holdout"]["profit_factor"]) >= 3.0
        and float(periods["holdout"]["max_drawdown_total_after_tax"]) <= 0.60
        for periods in priority_stress.values()
    )
    rolling_ok = (
        int(rolling["window_count"]) > 0
        and float(rolling["earned_beats_baseline_rate"]) >= 0.50
        and int(rolling["earned_above_start_count"]) == int(rolling["window_count"])
    )
    cluster_ok = all(
        float(period.get("worst_one_r_loss_cluster", {}).get("aggregate_open_risk_pct_of_nearby_equity") or 0.0) <= 0.055
        for period in cluster_stress.values()
    )

    reasons: list[str] = []
    if source_ok and best_variant_ok and sequence_ok and holdout_priority_ok and rolling_ok and cluster_ok:
        classification = PASSED
        reasons.append("earned_parallel_slot_candidate_survived_robustness_stress")
    else:
        classification = WARNING if source_ok and best_variant_ok and sequence_ok else FAILED
        if not source_ok:
            reasons.append("source_earned_slot_court_not_passed")
        if not best_variant_ok:
            reasons.append("source_best_variant_not_user_literal_1pct_each_slot")
        if not sequence_ok:
            reasons.append("source_baseline_sequence_check_failed")
        if not holdout_priority_ok:
            reasons.append("holdout_priority_stress_gate_failed")
        if not rolling_ok:
            reasons.append("rolling_window_consistency_gate_failed")
        if not cluster_ok:
            reasons.append("cluster_open_risk_gate_failed")

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_earned_slot_summary": str(source_summary_path),
        "source_earned_slot_ledger": str(source_ledger_path),
        "source_transfer_root": str(config.transfer_root),
        "tested_variant": BEST_VARIANT,
        "method": {
            "starting_capital_eur": START_CAPITAL,
            "active_cap_eur": ACTIVE_CAP,
            "tax_reserve_rate": TAX_RESERVE_RATE,
            "rolling_years": ROLLING_YEARS,
            "rolling_step_months": ROLLING_STEP_MONTHS,
            "priority_stress_sets": list(_priority_sets(priority)),
            "closed_equity_thresholds_only": True,
            "floating_pnl_unlocks_slots": False,
            "strategy_logic_changed": False,
            "entries_changed": False,
            "exits_changed": False,
            "scheduler_changed": False,
        },
        "source_checks": {
            "source_court_passed": source_ok,
            "best_variant_is_user_literal_1pct_each_slot": best_variant_ok,
            "baseline_sequence_checks_passed": sequence_ok,
        },
        "rolling_5y_research": {key: value for key, value in rolling.items() if key != "records"},
        "priority_stress": priority_stress,
        "cluster_risk_stress": cluster_stress,
        "freeze_gate": {
            "may_unfreeze_current_research_spec": False,
            "may_freeze_earned_parallel_slot_candidate": classification == PASSED,
            "requires_separate_user_approval_before_freeze": True,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "paper_validation_ready": False,
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_asset_earned_parallel_slot_robustness_summary.json", _round_payload(summary))
    _write_csv(config.output_root / "multi_asset_earned_parallel_slot_rolling_5y_windows.csv", rolling["records"])
    return _round_payload(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--transfer-root", default="structural_compounding_lab/output/multi_asset_frozen_transfer_court_001")
    parser.add_argument("--earned-slot-root", default=f"structural_compounding_lab/output/{EARNED_OUTPUT_FOLDER_NAME}")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        EarnedParallelSlotRobustnessConfig(
            project_root=root,
            package_root=package_root(),
            transfer_root=resolve_project_path(args.transfer_root),
            earned_slot_root=resolve_project_path(args.earned_slot_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
