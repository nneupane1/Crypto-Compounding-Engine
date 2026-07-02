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
from structural_compounding_lab.diagnostics.multi_asset_execution_feasibility_scanner_replay_court import (  # noqa: E402
    _load_assets,
)
from structural_compounding_lab.diagnostics.multi_asset_portfolio_selection_court import (  # noqa: E402
    SAFETY_FLAGS as PORTFOLIO_SAFETY_FLAGS,
    TRANSFER_ASSETS,
    _max_drawdown,
    _profit_factor,
    _read_json,
    _safe_ratio,
)


COURT_NAME = "MULTI_ASSET_EARNED_PARALLEL_SLOT_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_asset_earned_parallel_slot_court_001"

PASSED = "MULTI_ASSET_EARNED_PARALLEL_SLOT_FREEZE_CANDIDATE_RESEARCH_ONLY"
WARNING = "MULTI_ASSET_EARNED_PARALLEL_SLOT_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_ASSET_EARNED_PARALLEL_SLOT_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_ASSET_EARNED_PARALLEL_SLOT_BLOCKED_RESEARCH_ONLY"

START_CAPITAL = 25_000.0
ACTIVE_CAP = 500_000.0
TAX_RESERVE_RATE = 0.47475

ONE_SLOT_LADDER = (
    {"min_active_equity": 0.0, "max_slots": 1, "max_total_open_risk_pct": 0.01, "max_risk_per_trade_pct": 0.01},
)

EARNED_SLOT_LADDER = (
    {"min_active_equity": 0.0, "max_slots": 1, "max_total_open_risk_pct": 0.01, "max_risk_per_trade_pct": 0.01},
    {"min_active_equity": 100_000.0, "max_slots": 2, "max_total_open_risk_pct": 0.0125, "max_risk_per_trade_pct": 0.0075},
    {"min_active_equity": 300_000.0, "max_slots": 3, "max_total_open_risk_pct": 0.015, "max_risk_per_trade_pct": 0.006},
    {"min_active_equity": 500_000.0, "max_slots": 5, "max_total_open_risk_pct": 0.02, "max_risk_per_trade_pct": 0.005},
)

MODERATE_EARNED_SLOT_LADDER = (
    {"min_active_equity": 0.0, "max_slots": 1, "max_total_open_risk_pct": 0.01, "max_risk_per_trade_pct": 0.01},
    {"min_active_equity": 100_000.0, "max_slots": 2, "max_total_open_risk_pct": 0.015, "max_risk_per_trade_pct": 0.0075},
    {"min_active_equity": 300_000.0, "max_slots": 3, "max_total_open_risk_pct": 0.02, "max_risk_per_trade_pct": 0.0067},
    {"min_active_equity": 500_000.0, "max_slots": 5, "max_total_open_risk_pct": 0.025, "max_risk_per_trade_pct": 0.005},
)

USER_LITERAL_SLOT_LADDER = (
    {"min_active_equity": 0.0, "max_slots": 1, "max_total_open_risk_pct": 0.01, "max_risk_per_trade_pct": 0.01},
    {"min_active_equity": 100_000.0, "max_slots": 2, "max_total_open_risk_pct": 0.02, "max_risk_per_trade_pct": 0.01},
    {"min_active_equity": 300_000.0, "max_slots": 3, "max_total_open_risk_pct": 0.03, "max_risk_per_trade_pct": 0.01},
    {"min_active_equity": 500_000.0, "max_slots": 5, "max_total_open_risk_pct": 0.05, "max_risk_per_trade_pct": 0.01},
)

EARNED_SLOT_VARIANTS: tuple[tuple[str, tuple[dict[str, Any], ...]], ...] = (
    ("risk_compressed_slots", EARNED_SLOT_LADDER),
    ("moderate_slots", MODERATE_EARNED_SLOT_LADDER),
    ("user_literal_1pct_each_slot", USER_LITERAL_SLOT_LADDER),
)

SAFETY_FLAGS: dict[str, Any] = {
    **PORTFOLIO_SAFETY_FLAGS,
    "research_only": True,
    "tax_advice": False,
    "requires_steuerberater_review": True,
    "paper_validation_ready": False,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "order_path_created": False,
    "broker_path_created": False,
    "private_endpoint_used": False,
    "signed_endpoint_used": False,
    "strategy_logic_changed": False,
    "entries_changed": False,
    "exits_changed": False,
    "thresholds_tuned": False,
    "scheduler_changed": False,
}


@dataclass(frozen=True)
class EarnedParallelSlotConfig:
    project_root: Path
    package_root: Path
    transfer_root: Path
    portfolio_root: Path
    scanner_root: Path
    reduced_cap_root: Path
    output_root: Path


def default_config() -> EarnedParallelSlotConfig:
    pkg = package_root()
    return EarnedParallelSlotConfig(
        project_root=project_root(),
        package_root=pkg,
        transfer_root=pkg / "output" / "multi_asset_frozen_transfer_court_001",
        portfolio_root=pkg / "output" / "multi_asset_portfolio_selection_court_001",
        scanner_root=pkg / "output" / "multi_asset_execution_feasibility_scanner_replay_court_001",
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
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in keys})


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _sequence_signature(rows: list[dict[str, Any]]) -> list[str]:
    return [f"{row['symbol']}|{row.get('trade_id')}|{row['entry_timestamp'].isoformat()}|{row['exit_timestamp'].isoformat()}" for row in rows]


def _saved_sequence_signature(path: Path) -> list[str]:
    rows = _read_csv(path)
    return [f"{row.get('symbol')}|{row.get('trade_id')}|{row.get('entry_time')}|{row.get('exit_time')}" for row in rows]


def _scanner_priority(config: EarnedParallelSlotConfig) -> list[str]:
    path = config.portfolio_root / "multi_asset_portfolio_selection_summary.json"
    payload = _read_json(path) if path.exists() else {}
    priority = list(payload.get("research_rank_by_ending_equity") or [])
    return priority if set(priority) == set(TRANSFER_ASSETS) else list(TRANSFER_ASSETS)


def _symbol_caps(config: EarnedParallelSlotConfig) -> dict[str, float]:
    path = config.reduced_cap_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json"
    payload = _read_json(path) if path.exists() else {}
    return {str(symbol): float(cap) for symbol, cap in (payload.get("recommended_symbol_caps_eur") or {}).items()}


def _ladder_state(active_equity: float, ladder: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    eligible = [row for row in ladder if active_equity >= float(row["min_active_equity"])]
    return dict(eligible[-1] if eligible else ladder[0])


def _same_signature(row: dict[str, Any]) -> str:
    return f"{row['symbol']}|{row.get('trade_id')}|{row['entry_timestamp'].isoformat()}|{row['exit_timestamp'].isoformat()}"


def _year_end_tax(active: float, vault: float, year_pnl: float, tax_rate: float) -> tuple[float, float, float]:
    tax = max(year_pnl, 0.0) * tax_rate
    from_vault = min(vault, tax)
    vault -= from_vault
    remaining = tax - from_vault
    if remaining > 0.0:
        active = max(0.0, active - remaining)
    return active, vault, tax


def _replay(
    rows: list[dict[str, Any]],
    *,
    scenario_id: str,
    period: str,
    priority_symbols: list[str],
    symbol_caps: dict[str, float],
    ladder: tuple[dict[str, Any], ...],
    active_cap: float,
    tax_rate: float,
) -> dict[str, Any]:
    priority = {symbol: index for index, symbol in enumerate(priority_symbols, start=1)}
    grouped: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["entry_timestamp"], []).append(row)
    entry_times = sorted(grouped)

    active = START_CAPITAL
    vault = 0.0
    open_positions: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    yearly_rows: list[dict[str, Any]] = []
    curve = [active + vault]
    active_curve = [active]
    values: list[float] = []
    notional_limited = 0
    rejected_by_reason: dict[str, int] = {}
    max_concurrent = 0
    slot_threshold_hits = {str(int(row["min_active_equity"])): 0 for row in ladder}
    current_year: int | None = None
    year_pnl = 0.0
    tax_total = 0.0

    def reject(row: dict[str, Any], reason: str) -> None:
        rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
        rejected.append(
            {
                "scenario_id": scenario_id,
                "period": period,
                "symbol": row["symbol"],
                "trade_id": row.get("trade_id"),
                "entry_time": row["entry_timestamp"].isoformat(),
                "exit_time": row["exit_timestamp"].isoformat(),
                "side": row.get("side"),
                "reject_reason": reason,
                "active_equity": active,
                "open_positions": len(open_positions),
            }
        )

    def process_exit(position: dict[str, Any]) -> None:
        nonlocal active, vault, year_pnl, tax_total, current_year, max_concurrent
        row = position["row"]
        exit_year = int(row["exit_timestamp"].year)
        if current_year is None:
            current_year = exit_year
        while current_year is not None and exit_year > current_year:
            active, vault, tax = _year_end_tax(active, vault, year_pnl, tax_rate)
            tax_total += tax
            yearly_rows.append(
                {
                    "scenario_id": scenario_id,
                    "period": period,
                    "year": current_year,
                    "realized_net_pnl_before_tax": year_pnl,
                    "tax_reserved_or_withdrawn": tax,
                    "ending_active_capital_after_tax": active,
                    "ending_profit_vault_after_tax": vault,
                    "ending_total_equity_after_tax": active + vault,
                }
            )
            curve.append(active + vault)
            current_year += 1
            year_pnl = 0.0
        pnl = float(position["risk_eur"]) * float(row["net_r"])
        active_before = active
        vault_before = vault
        active += pnl
        if active < 0.0:
            active = 0.0
        if active > active_cap:
            vault += active - active_cap
            active = active_cap
        year_pnl += pnl
        values.append(float(row["net_r"]))
        selected.append(row)
        curve.append(active + vault)
        active_curve.append(active)
        trade_rows.append(
            {
                "scenario_id": scenario_id,
                "period": period,
                "trade_number": len(trade_rows) + 1,
                "symbol": row["symbol"],
                "trade_id": row.get("trade_id"),
                "side": row.get("side"),
                "entry_time": row["entry_timestamp"].isoformat(),
                "exit_time": row["exit_timestamp"].isoformat(),
                "net_r": float(row["net_r"]),
                "net_cost_r": float(row.get("net_cost_r") or 0.0),
                "risk_eur": float(position["risk_eur"]),
                "pnl_eur": pnl,
                "active_before_exit": active_before,
                "vault_before_exit": vault_before,
                "active_after_exit": active,
                "vault_after_exit": vault,
                "total_after_exit_before_year_tax": active + vault,
                "concurrent_slots_at_entry": int(position["concurrent_slots_at_entry"]),
                "max_slots_at_entry": int(position["max_slots_at_entry"]),
                "max_total_open_risk_pct_at_entry": float(position["max_total_open_risk_pct_at_entry"]),
                "max_risk_per_trade_pct_at_entry": float(position["max_risk_per_trade_pct_at_entry"]),
                "symbol_cap_eur": position.get("symbol_cap_eur"),
                "notional_limited": bool(position["notional_limited"]),
            }
        )

    for entry_time in entry_times:
        due = [position for position in open_positions if position["row"]["exit_timestamp"] < entry_time]
        for position in sorted(due, key=lambda item: (item["row"]["exit_timestamp"], item["row"]["symbol"])):
            process_exit(position)
        open_positions = [position for position in open_positions if position not in due]

        state = _ladder_state(active, ladder)
        slot_threshold_hits[str(int(state["min_active_equity"]))] = slot_threshold_hits.get(str(int(state["min_active_equity"])), 0) + 1
        max_slots = int(state["max_slots"])
        max_total_risk = float(state["max_total_open_risk_pct"]) * max(0.0, min(active, active_cap))
        current_open_risk = sum(float(position["risk_eur"]) for position in open_positions)
        existing_symbols = {position["row"]["symbol"] for position in open_positions}
        bucket = sorted(
            grouped[entry_time],
            key=lambda row: (
                priority.get(row["symbol"], 999),
                float(row.get("pre_entry_cost_r_at_15bps") or row.get("net_cost_r") or 999.0),
                str(row.get("trade_id") or ""),
            ),
        )
        for row in bucket:
            if row["symbol"] in existing_symbols:
                reject(row, "symbol_already_open")
                continue
            if len(open_positions) >= max_slots:
                reject(row, "earned_slot_limit_reached")
                continue
            remaining_risk = max(0.0, max_total_risk - current_open_risk)
            if remaining_risk <= 0.0:
                reject(row, "portfolio_open_risk_limit_reached")
                continue
            risk_base = max(0.0, min(active, active_cap))
            per_trade_risk = risk_base * float(state["max_risk_per_trade_pct"])
            symbol_cap = symbol_caps.get(str(row["symbol"]), float("inf"))
            symbol_risk_cap = symbol_cap * float(state["max_risk_per_trade_pct"]) if math.isfinite(symbol_cap) else float("inf")
            risk_eur = min(per_trade_risk, remaining_risk, symbol_risk_cap)
            if risk_eur <= 0.0:
                reject(row, "zero_risk_after_caps")
                continue
            limited = risk_eur < min(per_trade_risk, remaining_risk)
            notional_limited += int(limited)
            open_positions.append(
                {
                    "row": row,
                    "risk_eur": risk_eur,
                    "concurrent_slots_at_entry": len(open_positions) + 1,
                    "max_slots_at_entry": max_slots,
                    "max_total_open_risk_pct_at_entry": state["max_total_open_risk_pct"],
                    "max_risk_per_trade_pct_at_entry": state["max_risk_per_trade_pct"],
                    "symbol_cap_eur": symbol_cap if math.isfinite(symbol_cap) else None,
                    "notional_limited": limited,
                }
            )
            current_open_risk += risk_eur
            existing_symbols.add(row["symbol"])
            max_concurrent = max(max_concurrent, len(open_positions))

    for position in sorted(open_positions, key=lambda item: (item["row"]["exit_timestamp"], item["row"]["symbol"])):
        process_exit(position)
    if current_year is not None:
        active, vault, tax = _year_end_tax(active, vault, year_pnl, tax_rate)
        tax_total += tax
        yearly_rows.append(
            {
                "scenario_id": scenario_id,
                "period": period,
                "year": current_year,
                "realized_net_pnl_before_tax": year_pnl,
                "tax_reserved_or_withdrawn": tax,
                "ending_active_capital_after_tax": active,
                "ending_profit_vault_after_tax": vault,
                "ending_total_equity_after_tax": active + vault,
            }
        )
        curve.append(active + vault)

    return {
        "scenario_id": scenario_id,
        "period": period,
        "starting_equity": START_CAPITAL,
        "active_cap": active_cap,
        "ending_total_equity_after_tax": active + vault,
        "ending_active_capital_after_tax": active,
        "ending_profit_vault_after_tax": vault,
        "return_multiple_after_tax": _safe_ratio(active + vault, START_CAPITAL, 0.0),
        "net_gain_after_tax": active + vault - START_CAPITAL,
        "tax_reserved_or_withdrawn": tax_total,
        "candidate_trades": len(rows),
        "selected_trades": len(selected),
        "rejected_trades": len(rejected),
        "rejected_by_reason": rejected_by_reason,
        "max_concurrent_positions": max_concurrent,
        "notional_limited_trades": notional_limited,
        "sum_net_r": sum(values),
        "profit_factor": _profit_factor(values),
        "win_rate": _safe_ratio(sum(1 for value in values if value > 0.0), len(values), 0.0),
        "max_drawdown_total_after_tax": _max_drawdown(curve),
        "max_drawdown_active": _max_drawdown(active_curve),
        "slot_threshold_hits": slot_threshold_hits,
        "selected_signature": _sequence_signature(selected),
        "trade_rows": trade_rows,
        "rejected_rows": rejected,
        "yearly_rows": yearly_rows,
    }


def _load_rows(assets: dict[str, dict[str, Any]], period_key: str, priority_symbols: list[str]) -> list[dict[str, Any]]:
    rows = [row for symbol in priority_symbols for row in assets[symbol][period_key]]
    return sorted(rows, key=lambda row: (row["entry_timestamp"], row["symbol"], str(row.get("trade_id") or "")))


def _scenario_public(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key not in {"trade_rows", "rejected_rows", "yearly_rows", "selected_signature"}}


def _improvement(candidate: dict[str, Any], baseline: dict[str, Any]) -> float:
    return _safe_ratio(
        float(candidate["ending_total_equity_after_tax"]) - float(baseline["ending_total_equity_after_tax"]),
        float(baseline["ending_total_equity_after_tax"]),
        0.0,
    )


def run(config: EarnedParallelSlotConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    required = [
        config.transfer_root / "multi_asset_frozen_transfer_summary.json",
        config.portfolio_root / "multi_asset_portfolio_selection_summary.json",
        config.scanner_root / "research_scanner_selected_trades.csv",
        config.scanner_root / "sealed_holdout_scanner_selected_trades.csv",
        config.reduced_cap_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json",
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
        _write_json(config.output_root / "multi_asset_earned_parallel_slot_summary.json", summary)
        return summary

    priority_symbols = _scanner_priority(config)
    symbol_caps = _symbol_caps(config)
    assets = _load_assets(type("ScannerConfig", (), {"transfer_root": config.transfer_root})())
    missing_assets = [symbol for symbol in TRANSFER_ASSETS if symbol not in assets]
    if missing_assets:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_asset_artifacts"],
            "missing_assets": missing_assets,
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_asset_earned_parallel_slot_summary.json", summary)
        return summary

    period_rows = {
        "research": _load_rows(assets, "research_rows", priority_symbols),
        "holdout": _load_rows(assets, "holdout_rows", priority_symbols),
    }
    baseline: dict[str, dict[str, Any]] = {}
    candidate_variants: dict[str, dict[str, dict[str, Any]]] = {}
    all_trade_rows: list[dict[str, Any]] = []
    all_rejected_rows: list[dict[str, Any]] = []
    all_yearly_rows: list[dict[str, Any]] = []
    for period, rows in period_rows.items():
        baseline[period] = _replay(
            rows,
            scenario_id="baseline_max_one_slot",
            period=period,
            priority_symbols=priority_symbols,
            symbol_caps=symbol_caps,
            ladder=ONE_SLOT_LADDER,
            active_cap=ACTIVE_CAP,
            tax_rate=TAX_RESERVE_RATE,
        )
        for variant_name, variant_ladder in EARNED_SLOT_VARIANTS:
            candidate_variants.setdefault(variant_name, {})[period] = _replay(
                rows,
                scenario_id=variant_name,
                period=period,
                priority_symbols=priority_symbols,
                symbol_caps=symbol_caps,
                ladder=variant_ladder,
                active_cap=ACTIVE_CAP,
                tax_rate=TAX_RESERVE_RATE,
            )
        for result in [baseline[period], *[candidate_variants[name][period] for name, _ in EARNED_SLOT_VARIANTS]]:
            all_trade_rows.extend(result["trade_rows"])
            all_rejected_rows.extend(result["rejected_rows"])
            all_yearly_rows.extend(result["yearly_rows"])

    sequence_checks = {
        "baseline_research_matches_saved_one_slot_scanner": baseline["research"]["selected_signature"]
        == _saved_sequence_signature(config.scanner_root / "research_scanner_selected_trades.csv"),
        "baseline_holdout_matches_saved_one_slot_scanner": baseline["holdout"]["selected_signature"]
        == _saved_sequence_signature(config.scanner_root / "sealed_holdout_scanner_selected_trades.csv"),
        "baseline_research_selected": len(baseline["research"]["selected_signature"]),
        "baseline_holdout_selected": len(baseline["holdout"]["selected_signature"]),
    }
    variant_comparisons: dict[str, dict[str, Any]] = {}
    for variant_name, _ in EARNED_SLOT_VARIANTS:
        research_improvement = _improvement(candidate_variants[variant_name]["research"], baseline["research"])
        holdout_improvement = _improvement(candidate_variants[variant_name]["holdout"], baseline["holdout"])
        holdout_dd_ok = float(candidate_variants[variant_name]["holdout"]["max_drawdown_total_after_tax"]) <= max(
            0.50, float(baseline["holdout"]["max_drawdown_total_after_tax"]) * 1.25
        )
        holdout_pf_ok = float(candidate_variants[variant_name]["holdout"]["profit_factor"]) >= 3.0
        variant_comparisons[variant_name] = {
            "research_improvement_pct": research_improvement * 100.0,
            "holdout_improvement_pct": holdout_improvement * 100.0,
            "holdout_drawdown_gate_passed": holdout_dd_ok,
            "holdout_profit_factor_gate_passed": holdout_pf_ok,
            "candidate_passed": research_improvement > 0.10 and holdout_improvement > 0.0 and holdout_dd_ok and holdout_pf_ok,
        }
    best_variant = max(
        variant_comparisons,
        key=lambda name: (
            bool(variant_comparisons[name]["candidate_passed"]),
            float(variant_comparisons[name]["holdout_improvement_pct"]),
            float(variant_comparisons[name]["research_improvement_pct"]),
        ),
    )
    sequence_ok = all(sequence_checks.values())

    reasons: list[str] = []
    if sequence_ok and bool(variant_comparisons[best_variant]["candidate_passed"]):
        classification = PASSED
        reasons.append(f"earned_parallel_slots_variant_passed:{best_variant}")
    elif sequence_ok and any(
        float(candidate_variants[name]["research"]["ending_total_equity_after_tax"]) > float(baseline["research"]["ending_total_equity_after_tax"])
        and float(candidate_variants[name]["holdout"]["ending_total_equity_after_tax"]) > START_CAPITAL
        for name, _ in EARNED_SLOT_VARIANTS
    ):
        classification = WARNING
        reasons.append("earned_parallel_slots_improved_research_but_holdout_or_drawdown_needs_review")
    else:
        classification = FAILED
        if not sequence_ok:
            reasons.append("baseline_one_slot_rebuild_did_not_match_saved_scanner")
        if not any(float(row["research_improvement_pct"]) > 10.0 for row in variant_comparisons.values()):
            reasons.append("no_variant_research_improvement_above_required_margin")
        if not any(float(row["holdout_improvement_pct"]) > 0.0 for row in variant_comparisons.values()):
            reasons.append("no_variant_improved_holdout")
        if not any(bool(row["holdout_drawdown_gate_passed"]) for row in variant_comparisons.values()):
            reasons.append("all_variants_failed_holdout_drawdown_gate")
        if not any(bool(row["holdout_profit_factor_gate_passed"]) for row in variant_comparisons.values()):
            reasons.append("all_variants_failed_holdout_profit_factor_gate")

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_transfer_root": str(config.transfer_root),
        "source_scanner_root": str(config.scanner_root),
        "source_reduced_cap_root": str(config.reduced_cap_root),
        "fixed_priority_symbols": priority_symbols,
        "recommended_symbol_caps_eur": symbol_caps,
        "method": {
            "starting_capital_eur": START_CAPITAL,
            "active_cap_eur": ACTIVE_CAP,
            "tax_reserve_rate": TAX_RESERVE_RATE,
            "baseline_ladder": ONE_SLOT_LADDER,
            "earned_parallel_variants": {
                variant_name: variant_ladder for variant_name, variant_ladder in EARNED_SLOT_VARIANTS
            },
            "closed_equity_thresholds_only": True,
            "floating_pnl_unlocks_slots": False,
            "max_one_trade_per_symbol": True,
            "total_open_risk_limited": True,
            "symbol_liquidity_caps_applied": True,
            "strategy_logic_changed": False,
            "entries_changed": False,
            "exits_changed": False,
            "thresholds_tuned": False,
            "scheduler_changed": False,
        },
        "sequence_checks": sequence_checks,
        "comparison": {
            "best_variant": best_variant,
            "variant_comparisons": variant_comparisons,
        },
        "baseline": {period: _scenario_public(result) for period, result in baseline.items()},
        "earned_parallel_candidates": {
            variant_name: {period: _scenario_public(result) for period, result in periods.items()}
            for variant_name, periods in candidate_variants.items()
        },
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
    _write_json(config.output_root / "multi_asset_earned_parallel_slot_summary.json", summary)
    _write_csv(config.output_root / "multi_asset_earned_parallel_slot_trade_ledger.csv", all_trade_rows)
    _write_csv(config.output_root / "multi_asset_earned_parallel_slot_rejected_rows.csv", all_rejected_rows)
    _write_csv(config.output_root / "multi_asset_earned_parallel_slot_yearly_tax_rows.csv", all_yearly_rows)
    return _round_payload(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--transfer-root", default="structural_compounding_lab/output/multi_asset_frozen_transfer_court_001")
    parser.add_argument("--portfolio-root", default="structural_compounding_lab/output/multi_asset_portfolio_selection_court_001")
    parser.add_argument("--scanner-root", default="structural_compounding_lab/output/multi_asset_execution_feasibility_scanner_replay_court_001")
    parser.add_argument("--reduced-cap-root", default="structural_compounding_lab/output/multi_symbol_reduced_cap_gear_ladder_restatement_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        EarnedParallelSlotConfig(
            project_root=root,
            package_root=package_root(),
            transfer_root=resolve_project_path(args.transfer_root),
            portfolio_root=resolve_project_path(args.portfolio_root),
            scanner_root=resolve_project_path(args.scanner_root),
            reduced_cap_root=resolve_project_path(args.reduced_cap_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
