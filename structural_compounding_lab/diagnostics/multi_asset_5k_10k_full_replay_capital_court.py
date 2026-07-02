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

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path  # noqa: E402
from structural_compounding_lab.diagnostics.multi_asset_execution_feasibility_scanner_replay_court import (  # noqa: E402
    _load_assets,
    _overlap_audit,
    _timestamp_alignment,
)
from structural_compounding_lab.diagnostics.multi_asset_portfolio_selection_court import (  # noqa: E402
    RISK_PER_TRADE,
    SAFETY_FLAGS as PORTFOLIO_SAFETY_FLAGS,
    TRANSFER_ASSETS,
    _max_drawdown,
    _profit_factor,
    _read_json,
    _safe_ratio,
    _select_non_overlapping_shared_pool,
)


COURT_NAME = "MULTI_ASSET_5K_10K_FULL_REPLAY_CAPITAL_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_asset_5k_10k_full_replay_capital_court_001"

PASSED = "MULTI_ASSET_5K_10K_FULL_REPLAY_CAPITAL_PASSED_RESEARCH_ONLY"
WARNING = "MULTI_ASSET_5K_10K_FULL_REPLAY_CAPITAL_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_ASSET_5K_10K_FULL_REPLAY_CAPITAL_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_ASSET_5K_10K_FULL_REPLAY_CAPITAL_BLOCKED_RESEARCH_ONLY"

START_CAPITALS_EUR: tuple[float, ...] = (5_000.0, 10_000.0)
TAX_RESERVE_RATE = 0.47475
ACTIVE_CAP_MULTIPLES: tuple[tuple[str, float | None], ...] = (
    ("proportional_base_cap_10x_start", 10.0),
    ("proportional_gear1_cap_20x_start", 20.0),
    ("same_absolute_500k_cap_sensitivity", None),
)
ABSOLUTE_CAP_EUR = 500_000.0

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
class FullReplayCapitalConfig:
    project_root: Path
    package_root: Path
    transfer_root: Path
    portfolio_root: Path
    scanner_root: Path
    reduced_cap_root: Path
    output_root: Path


def default_config() -> FullReplayCapitalConfig:
    pkg = package_root()
    return FullReplayCapitalConfig(
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


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_symbol_caps(config: FullReplayCapitalConfig) -> dict[str, float]:
    summary_path = config.reduced_cap_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json"
    payload = _read_json(summary_path) if summary_path.exists() else {}
    return {str(symbol): float(cap) for symbol, cap in (payload.get("recommended_symbol_caps_eur") or {}).items()}


def _scanner_priority(config: FullReplayCapitalConfig) -> list[str]:
    portfolio_path = config.portfolio_root / "multi_asset_portfolio_selection_summary.json"
    portfolio = _read_json(portfolio_path) if portfolio_path.exists() else {}
    priority = list(portfolio.get("research_rank_by_ending_equity") or [])
    if set(priority) != set(TRANSFER_ASSETS):
        return list(TRANSFER_ASSETS)
    return priority


def _select_period_rows(
    assets: dict[str, dict[str, Any]],
    *,
    period_key: str,
    priority_symbols: list[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    priority = {symbol: index for index, symbol in enumerate(priority_symbols, start=1)}
    all_rows = [row for symbol in priority_symbols for row in assets[symbol][period_key]]
    selected, rejected = _select_non_overlapping_shared_pool(all_rows, allowed_symbols=priority_symbols, symbol_priority=priority)
    return all_rows, selected, rejected


def _sequence_signature(rows: list[dict[str, Any]]) -> list[str]:
    return [f"{row['symbol']}|{row.get('trade_id')}|{row['entry_timestamp'].isoformat()}|{row['exit_timestamp'].isoformat()}" for row in rows]


def _saved_sequence_signature(path: Path) -> list[str]:
    rows = _read_csv(path)
    return [f"{row.get('symbol')}|{row.get('trade_id')}|{row.get('entry_time')}|{row.get('exit_time')}" for row in rows]


def _active_cap(start_capital: float, cap_multiple: float | None) -> float:
    return ABSOLUTE_CAP_EUR if cap_multiple is None else start_capital * cap_multiple


def _replay_capital(
    selected_rows: list[dict[str, Any]],
    *,
    start_capital: float,
    active_cap: float,
    tax_rate: float,
    symbol_caps: dict[str, float],
    scenario_id: str,
    period: str,
) -> dict[str, Any]:
    active = start_capital
    vault = 0.0
    values: list[float] = []
    active_curve = [active]
    pre_tax_total_curve = [active + vault]
    trade_rows: list[dict[str, Any]] = []
    notional_limited = 0
    stopped = False
    stopped_at = ""

    for trade_number, row in enumerate(sorted(selected_rows, key=lambda item: (item["entry_timestamp"], item["symbol"])), start=1):
        risk_base = max(0.0, min(active, active_cap))
        if risk_base <= 0.0:
            stopped = True
            stopped_at = row["entry_timestamp"].isoformat()
            break
        theoretical_risk = risk_base * RISK_PER_TRADE
        symbol_cap = symbol_caps.get(str(row["symbol"]), float("inf"))
        notional_risk_cap = symbol_cap * RISK_PER_TRADE if math.isfinite(symbol_cap) else float("inf")
        risk_eur = min(theoretical_risk, notional_risk_cap)
        if risk_eur < theoretical_risk:
            notional_limited += 1
        net_r = float(row["net_r"])
        pnl = risk_eur * net_r
        active_before = active
        vault_before = vault
        total_before = active + vault
        active += pnl
        if active < 0.0:
            active = 0.0
            stopped = True
            stopped_at = row["exit_timestamp"].isoformat()
        if active > active_cap:
            vault += active - active_cap
            active = active_cap
        values.append(net_r)
        active_curve.append(active)
        pre_tax_total_curve.append(active + vault)
        trade_rows.append(
            {
                "scenario_id": scenario_id,
                "period": period,
                "trade_number": trade_number,
                "symbol": row["symbol"],
                "trade_id": row.get("trade_id"),
                "entry_time": row["entry_timestamp"].isoformat(),
                "exit_time": row["exit_timestamp"].isoformat(),
                "side": row.get("side"),
                "net_r": net_r,
                "net_cost_r": float(row.get("net_cost_r") or 0.0),
                "selection_rank": row.get("selection_rank"),
                "selection_reason": row.get("selection_reason"),
                "start_capital": start_capital,
                "active_cap": active_cap,
                "active_before_trade": active_before,
                "vault_before_trade": vault_before,
                "total_before_trade": total_before,
                "theoretical_risk_eur": theoretical_risk,
                "symbol_cap_eur": symbol_cap if math.isfinite(symbol_cap) else None,
                "risk_eur": risk_eur,
                "notional_limited": risk_eur < theoretical_risk,
                "net_pnl_before_tax": pnl,
                "active_after_trade_before_tax": active,
                "vault_after_trade_before_tax": vault,
                "total_after_trade_before_tax": active + vault,
            }
        )
        if stopped:
            break

    active = start_capital
    vault = 0.0
    tax_total = 0.0
    yearly_rows: list[dict[str, Any]] = []
    post_tax_total_curve = [active + vault]
    for year in sorted({int(str(row["exit_time"])[:4]) for row in trade_rows}):
        bucket = [row for row in trade_rows if int(str(row["exit_time"])[:4]) == year]
        year_pnl = 0.0
        for item in bucket:
            pnl = float(item["net_pnl_before_tax"])
            active += pnl
            if active < 0.0:
                active = 0.0
            if active > active_cap:
                vault += active - active_cap
                active = active_cap
            year_pnl += pnl
            post_tax_total_curve.append(active + vault)
        tax = max(year_pnl, 0.0) * tax_rate
        from_vault = min(vault, tax)
        vault -= from_vault
        remainder = tax - from_vault
        from_active = 0.0
        if remainder > 0.0:
            from_active = min(active, remainder)
            active = max(0.0, active - remainder)
        tax_total += tax
        yearly_rows.append(
            {
                "scenario_id": scenario_id,
                "period": period,
                "year": year,
                "trades": len(bucket),
                "realized_net_pnl_before_tax": year_pnl,
                "tax_reserved_or_withdrawn": tax,
                "tax_paid_from_vault": from_vault,
                "tax_paid_from_active": from_active,
                "ending_active_capital_after_tax": active,
                "ending_profit_vault_after_tax": vault,
                "ending_total_equity_after_tax": active + vault,
            }
        )
        post_tax_total_curve.append(active + vault)

    return {
        "scenario_id": scenario_id,
        "period": period,
        "starting_equity": start_capital,
        "active_cap": active_cap,
        "tax_rate": tax_rate,
        "ending_total_equity_after_tax": active + vault,
        "ending_active_capital_after_tax": active,
        "ending_profit_vault_after_tax": vault,
        "net_gain_after_tax": active + vault - start_capital,
        "return_multiple_after_tax": _safe_ratio(active + vault, start_capital, 0.0),
        "total_tax_reserved_or_withdrawn": tax_total,
        "accepted_trades_available": len(selected_rows),
        "processed_trades": len(trade_rows),
        "notional_limited_trades": notional_limited,
        "account_stopped": stopped,
        "stopped_at": stopped_at,
        "sum_net_r": sum(values),
        "profit_factor": _profit_factor(values),
        "win_rate": _safe_ratio(sum(1 for value in values if value > 0.0), len(values), 0.0),
        "max_drawdown_total_after_tax": _max_drawdown(post_tax_total_curve),
        "max_drawdown_active_pre_tax": _max_drawdown(active_curve),
        "yearly_rows": yearly_rows,
        "trade_rows": trade_rows,
    }


def run(config: FullReplayCapitalConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)

    transfer_summary_path = config.transfer_root / "multi_asset_frozen_transfer_summary.json"
    portfolio_summary_path = config.portfolio_root / "multi_asset_portfolio_selection_summary.json"
    scanner_summary_path = config.scanner_root / "multi_asset_execution_feasibility_scanner_replay_summary.json"
    reduced_summary_path = config.reduced_cap_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json"
    missing = [str(path) for path in [transfer_summary_path, portfolio_summary_path, scanner_summary_path, reduced_summary_path] if not path.exists()]
    if missing:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_required_source_artifacts"],
            "missing_artifacts": missing,
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_asset_5k_10k_full_replay_capital_summary.json", summary)
        return summary

    assets = _load_assets(
        type(
            "ScannerConfig",
            (),
            {
                "transfer_root": config.transfer_root,
            },
        )()
    )
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
        _write_json(config.output_root / "multi_asset_5k_10k_full_replay_capital_summary.json", summary)
        return summary

    priority_symbols = _scanner_priority(config)
    symbol_caps = _load_symbol_caps(config)
    research_all, research_selected, research_rejected = _select_period_rows(assets, period_key="research_rows", priority_symbols=priority_symbols)
    holdout_all, holdout_selected, holdout_rejected = _select_period_rows(assets, period_key="holdout_rows", priority_symbols=priority_symbols)

    scanner_research_file = config.scanner_root / "research_scanner_selected_trades.csv"
    scanner_holdout_file = config.scanner_root / "sealed_holdout_scanner_selected_trades.csv"
    sequence_checks = {
        "research_rebuilt_selection_matches_saved_scanner_ledger": _sequence_signature(research_selected) == _saved_sequence_signature(scanner_research_file),
        "holdout_rebuilt_selection_matches_saved_scanner_ledger": _sequence_signature(holdout_selected) == _saved_sequence_signature(scanner_holdout_file),
        "research_rebuilt_selected_count": len(research_selected),
        "holdout_rebuilt_selected_count": len(holdout_selected),
        "saved_research_selected_count": len(_saved_sequence_signature(scanner_research_file)),
        "saved_holdout_selected_count": len(_saved_sequence_signature(scanner_holdout_file)),
    }

    audit = {
        "research_timestamp_alignment": _timestamp_alignment(research_all),
        "holdout_timestamp_alignment": _timestamp_alignment(holdout_all),
        "research_overlap_audit": _overlap_audit(research_selected),
        "holdout_overlap_audit": _overlap_audit(holdout_selected),
        "sequence_checks": sequence_checks,
    }

    scenarios: list[dict[str, Any]] = []
    yearly_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    for start in START_CAPITALS_EUR:
        for cap_name, multiple in ACTIVE_CAP_MULTIPLES:
            cap = _active_cap(start, multiple)
            scenario_id = f"start_{int(start)}_{cap_name}"
            for period, rows, tax_rate in (
                ("research_taxed", research_selected, TAX_RESERVE_RATE),
                ("holdout_no_tax", holdout_selected, 0.0),
                ("holdout_taxed", holdout_selected, TAX_RESERVE_RATE),
            ):
                result = _replay_capital(
                    rows,
                    start_capital=start,
                    active_cap=cap,
                    tax_rate=tax_rate,
                    symbol_caps=symbol_caps,
                    scenario_id=scenario_id,
                    period=period,
                )
                scenarios.append({key: value for key, value in result.items() if key not in {"yearly_rows", "trade_rows"}})
                yearly_rows.extend(result["yearly_rows"])
                trade_rows.extend(result["trade_rows"])

    scenarios_by_id = {(row["scenario_id"], row["period"]): row for row in scenarios}
    base_5k = scenarios_by_id.get(("start_5000_proportional_base_cap_10x_start", "research_taxed"), {})
    gear_5k = scenarios_by_id.get(("start_5000_proportional_gear1_cap_20x_start", "research_taxed"), {})
    base_10k = scenarios_by_id.get(("start_10000_proportional_base_cap_10x_start", "research_taxed"), {})
    gear_10k = scenarios_by_id.get(("start_10000_proportional_gear1_cap_20x_start", "research_taxed"), {})

    replay_ok = (
        sequence_checks["research_rebuilt_selection_matches_saved_scanner_ledger"]
        and sequence_checks["holdout_rebuilt_selection_matches_saved_scanner_ledger"]
        and audit["research_overlap_audit"]["max_one_active_trade_respected"]
        and audit["holdout_overlap_audit"]["max_one_active_trade_respected"]
        and audit["research_timestamp_alignment"]["all_entries_1h_aligned"]
        and audit["holdout_timestamp_alignment"]["all_entries_1h_aligned"]
    )
    million_path_5k = float(gear_5k.get("ending_total_equity_after_tax") or 0.0) >= 1_000_000.0
    million_path_10k = float(base_10k.get("ending_total_equity_after_tax") or 0.0) >= 1_000_000.0
    holdout_positive = all(
        float(scenarios_by_id.get((f"start_{int(start)}_proportional_base_cap_10x_start", "holdout_taxed"), {}).get("ending_total_equity_after_tax") or 0.0)
        > start
        for start in START_CAPITALS_EUR
    )

    if replay_ok and million_path_5k and million_path_10k and holdout_positive:
        classification = PASSED
        reasons = ["rebuilt_scanner_sequence_verified_and_5k_10k_million_path_supported_by_research_with_positive_holdout"]
    elif replay_ok and holdout_positive and (million_path_5k or million_path_10k):
        classification = WARNING
        reasons = ["rebuilt_scanner_sequence_verified_but_only_one_starting_capital_reaches_million_gate"]
    else:
        classification = FAILED
        reasons = []
        if not replay_ok:
            reasons.append("rebuilt_scanner_sequence_or_audit_failed")
        if not holdout_positive:
            reasons.append("one_or_more_holdout_taxed_scenarios_not_positive")
        if not (million_path_5k or million_path_10k):
            reasons.append("no_5k_10k_million_path_after_caps_tax")

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_transfer_summary": str(transfer_summary_path),
        "source_portfolio_summary": str(portfolio_summary_path),
        "source_scanner_summary": str(scanner_summary_path),
        "source_reduced_cap_summary": str(reduced_summary_path),
        "fixed_scanner_priority": priority_symbols,
        "recommended_symbol_caps_eur": symbol_caps,
        "method": {
            "rebuilt_candidate_pools_from_asset_transfer_artifacts": True,
            "reran_fixed_priority_max_one_active_scanner_selection": True,
            "verified_rebuilt_sequence_matches_saved_scanner_ledger": True,
            "starting_capitals_eur": list(START_CAPITALS_EUR),
            "active_cap_scenarios": [
                {"name": name, "multiple": multiple, "absolute_cap": ABSOLUTE_CAP_EUR if multiple is None else None}
                for name, multiple in ACTIVE_CAP_MULTIPLES
            ],
            "risk_per_trade": RISK_PER_TRADE,
            "tax_reserve_rate": TAX_RESERVE_RATE,
            "normal_cost_model_already_embedded_in_net_r": True,
            "selection_depends_on_capital": False,
            "selection_inputs": ["entry_timestamp", "fixed_research_rank_priority", "active_trade_until", "pre_entry_cost_r_tiebreak"],
        },
        "audit": audit,
        "scenarios": scenarios,
        "headline": {
            "eur5k_base_cap_research_after_tax": base_5k.get("ending_total_equity_after_tax"),
            "eur5k_gear1_cap_research_after_tax": gear_5k.get("ending_total_equity_after_tax"),
            "eur10k_base_cap_research_after_tax": base_10k.get("ending_total_equity_after_tax"),
            "eur10k_gear1_cap_research_after_tax": gear_10k.get("ending_total_equity_after_tax"),
            "eur5k_million_path_supported": million_path_5k,
            "eur10k_million_path_supported": million_path_10k,
        },
        "gate": {
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "paper_validation_ready": False,
            "next_required_step": "continue_multi_symbol_forward_scheduler_evidence",
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_asset_5k_10k_full_replay_capital_summary.json", summary)
    _write_csv(config.output_root / "multi_asset_5k_10k_full_replay_scenarios.csv", scenarios)
    _write_csv(config.output_root / "multi_asset_5k_10k_full_replay_yearly_tax_rows.csv", yearly_rows)
    _write_csv(config.output_root / "multi_asset_5k_10k_full_replay_trade_ledger.csv", trade_rows)
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
        FullReplayCapitalConfig(
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
