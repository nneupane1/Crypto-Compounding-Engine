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


COURT_NAME = "MULTI_ASSET_CAPITAL_CAP_AND_LIQUIDITY_REALISM_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_asset_capital_cap_liquidity_realism_court_001"

PASSED = "MULTI_ASSET_CAPITAL_CAP_REALISM_VALIDATED_RESEARCH_ONLY"
WARNING = "MULTI_ASSET_CAPITAL_CAP_REALISM_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_ASSET_CAPITAL_CAP_REALISM_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_ASSET_CAPITAL_CAP_REALISM_BLOCKED_RESEARCH_ONLY"

START_CAPITAL = 25_000.0
RISK_PER_TRADE = 0.01
BASELINE_COST_BPS = 15.0
TAX_RESERVE_RATE = 0.47475

ACTIVE_CAPS: tuple[float, ...] = (25_000.0, 50_000.0, 100_000.0, 250_000.0, 500_000.0, 1_000_000.0, 2_000_000.0)
COST_STRESS_BPS: tuple[float, ...] = (15.0, 25.0, 50.0, 100.0)
MAX_NOTIONAL_BY_SYMBOL: dict[str, float] = {
    "ADAUSDT": 250_000.0,
    "LINKUSDT": 250_000.0,
    "BNBUSDT": 350_000.0,
    "XRPUSDT": 250_000.0,
    "AVAXUSDT": 250_000.0,
    "DOGEUSDT": 200_000.0,
    "ETHUSDT": 500_000.0,
    "SOLUSDT": 350_000.0,
}

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "tax_advice": False,
    "requires_steuerberater_review": True,
    "paper_validation_ready": False,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "no_order_path_created": True,
    "no_broker_path_created": True,
    "private_endpoint_used": False,
    "signed_endpoint_used": False,
}


@dataclass(frozen=True)
class CapitalCapConfig:
    project_root: Path
    package_root: Path
    scanner_root: Path
    output_root: Path


def default_config() -> CapitalCapConfig:
    pkg = package_root()
    return CapitalCapConfig(
        project_root=project_root(),
        package_root=pkg,
        scanner_root=pkg / "output" / "multi_asset_execution_feasibility_scanner_replay_court_001",
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


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_ts(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _load_scanner_trades(path: Path, *, period: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            payload = dict(row)
            payload["period"] = period
            payload["symbol"] = str(row.get("symbol") or "").upper()
            payload["entry_timestamp"] = _parse_ts(str(row.get("entry_time")))
            payload["exit_timestamp"] = _parse_ts(str(row.get("exit_time")))
            payload["net_r"] = float(row.get("net_r") or 0.0)
            payload["net_cost_r"] = float(row.get("net_cost_r") or 0.0)
            rows.append(payload)
    return sorted(rows, key=lambda item: (item["entry_timestamp"], int(float(item.get("scanner_trade_number") or 0))))


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def _profit_factor(values: list[float]) -> float:
    wins = sum(value for value in values if value > 0.0)
    losses = abs(sum(value for value in values if value < 0.0))
    return wins / losses if losses else float(wins > 0.0)


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0] if curve else 0.0
    worst = 0.0
    for value in curve:
        peak = max(peak, value)
        worst = max(worst, _safe_ratio(peak - value, peak, 0.0))
    return worst


def _adjusted_net_r(row: dict[str, Any], *, cost_bps: float) -> float:
    extra_cost_r = max(0.0, (cost_bps - BASELINE_COST_BPS) / BASELINE_COST_BPS) * float(row.get("net_cost_r") or 0.0)
    return float(row["net_r"]) - extra_cost_r


def _apply_cap_and_tax(
    rows: list[dict[str, Any]],
    *,
    active_cap: float,
    cost_bps: float = BASELINE_COST_BPS,
    tax_reserve_rate: float = TAX_RESERVE_RATE,
    max_notional_by_symbol: dict[str, float] | None = None,
) -> dict[str, Any]:
    max_notional_by_symbol = max_notional_by_symbol or {}
    active = START_CAPITAL
    vault = 0.0
    tax_reserved = 0.0
    total_equity_curve = [active + vault]
    active_curve = [active]
    trade_rows: list[dict[str, Any]] = []
    yearly: dict[int, dict[str, Any]] = {}
    values: list[float] = []
    notional_limited_trades = 0
    for index, row in enumerate(rows, start=1):
        year = int(row["exit_timestamp"].year)
        current_active_cap = min(active, active_cap)
        risk_base = max(0.0, current_active_cap)
        theoretical_risk = risk_base * RISK_PER_TRADE
        symbol_cap = max_notional_by_symbol.get(str(row["symbol"]), float("inf"))
        notional_risk_cap = symbol_cap * RISK_PER_TRADE if symbol_cap != float("inf") else float("inf")
        risk_eur = min(theoretical_risk, notional_risk_cap)
        if risk_eur < theoretical_risk:
            notional_limited_trades += 1
        adjusted_r = _adjusted_net_r(row, cost_bps=cost_bps)
        pnl = risk_eur * adjusted_r
        active_before = active
        vault_before = vault
        total_before = active + vault
        active += pnl
        if active > active_cap:
            vault += active - active_cap
            active = active_cap
        total_after_pre_tax = active + vault
        yearly.setdefault(
            year,
            {
                "year": year,
                "trades": 0,
                "realized_net_pnl_before_tax": 0.0,
                "tax_reserved_or_withdrawn": 0.0,
                "ending_active_capital": active,
                "ending_profit_vault": vault,
                "ending_total_equity_after_tax": active + vault,
            },
        )
        yearly[year]["trades"] += 1
        yearly[year]["realized_net_pnl_before_tax"] += pnl
        yearly[year]["ending_active_capital"] = active
        yearly[year]["ending_profit_vault"] = vault
        yearly[year]["ending_total_equity_after_tax"] = active + vault
        values.append(adjusted_r)
        trade_rows.append(
            {
                "trade_number": index,
                "symbol": row["symbol"],
                "trade_id": row.get("trade_id"),
                "entry_time": row["entry_timestamp"].isoformat(),
                "exit_time": row["exit_timestamp"].isoformat(),
                "net_r_after_cost_stress": adjusted_r,
                "baseline_net_r": row["net_r"],
                "net_cost_r": row.get("net_cost_r"),
                "active_cap": active_cap,
                "cost_bps": cost_bps,
                "active_before_trade": active_before,
                "vault_before_trade": vault_before,
                "total_equity_before_trade": total_before,
                "risk_eur": risk_eur,
                "theoretical_risk_eur_before_notional_cap": theoretical_risk,
                "symbol_max_notional_eur": symbol_cap if symbol_cap != float("inf") else None,
                "notional_risk_limited": risk_eur < theoretical_risk,
                "net_pnl_eur": pnl,
                "active_after_trade_before_year_tax": active,
                "vault_after_trade_before_year_tax": vault,
                "total_equity_after_trade_before_year_tax": total_after_pre_tax,
            }
        )
        total_equity_curve.append(active + vault)
        active_curve.append(active)

    yearly_rows: list[dict[str, Any]] = []
    # Apply tax reserve at each year end by replaying year groups once more from trade rows.
    active = START_CAPITAL
    vault = 0.0
    cumulative_tax = 0.0
    post_tax_curve = [active + vault]
    for year in sorted(yearly):
        bucket = [row for row in trade_rows if int(str(row["exit_time"])[:4]) == year]
        year_pnl = 0.0
        for tr in bucket:
            active += float(tr["net_pnl_eur"])
            if active > active_cap:
                vault += active - active_cap
                active = active_cap
            year_pnl += float(tr["net_pnl_eur"])
            post_tax_curve.append(active + vault)
        tax = max(year_pnl, 0.0) * tax_reserve_rate
        tax_paid_from_vault = 0.0
        tax_paid_from_active = 0.0
        if tax > 0:
            from_vault = min(vault, tax)
            vault -= from_vault
            tax_paid_from_vault = from_vault
            remainder = tax - from_vault
            if remainder > 0:
                tax_paid_from_active = min(active, remainder)
                active = max(0.0, active - remainder)
            cumulative_tax += tax
        yearly_rows.append(
            {
                "year": year,
                "trades": len(bucket),
                "realized_net_pnl_before_tax": year_pnl,
                "tax_reserved_or_withdrawn": tax,
                "tax_paid_from_vault": tax_paid_from_vault,
                "tax_paid_from_active_capital": tax_paid_from_active,
                "ending_active_capital_after_tax": active,
                "ending_profit_vault_after_tax": vault,
                "ending_total_equity_after_tax": active + vault,
            }
        )
        post_tax_curve.append(active + vault)

    ending_total = active + vault
    return {
        "active_cap": active_cap,
        "cost_bps": cost_bps,
        "tax_reserve_rate": tax_reserve_rate,
        "starting_equity": START_CAPITAL,
        "ending_total_equity_after_tax": ending_total,
        "ending_active_capital_after_tax": active,
        "ending_profit_vault_after_tax": vault,
        "total_tax_reserved_or_withdrawn": cumulative_tax,
        "net_gain_after_tax": ending_total - START_CAPITAL,
        "return_multiple_after_tax": _safe_ratio(ending_total, START_CAPITAL, 0.0),
        "accepted_trades": len(rows),
        "notional_limited_trades": notional_limited_trades,
        "net_total_R_after_cost_stress": sum(values),
        "profit_factor_after_cost_stress": _profit_factor(values),
        "win_rate_after_cost_stress": _safe_ratio(sum(1 for value in values if value > 0.0), len(values), 0.0),
        "max_drawdown_total_equity_after_tax": _max_drawdown(post_tax_curve),
        "max_drawdown_total_equity_after_tax_includes_yearly_tax_withdrawals": True,
        "max_drawdown_active_capital_pre_tax": _max_drawdown(active_curve),
        "yearly_rows": yearly_rows,
        "trade_rows": trade_rows,
    }


def _scenario_rows(scenarios: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        rows.append({key: value for key, value in scenario.items() if key not in {"yearly_rows", "trade_rows"}})
    return rows


def _write_report(config: CapitalCapConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# Multi-Asset Capital Cap and Liquidity Realism Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        "- Research-only diagnostic. No paper/live/order/broker path enabled.",
        "- Uses selected frozen scanner trades; strategy logic was not rerun or changed.",
        "- Execution costs are already included at baseline 15 bps; stress scenarios add extra cost drag.",
        "- Tax reserve is a planning placeholder, not tax advice.",
        "",
        "## Baseline capped scenarios after yearly tax reserve",
        "",
        "| Active cap | Ending total equity | Active capital | Vault | Tax reserved | Max DD |",
        "| ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["baseline_active_cap_scenarios"]:
        lines.append(
            "| €{cap:,.0f} | €{ending:,.2f} | €{active:,.2f} | €{vault:,.2f} | €{tax:,.2f} | {dd:.2%} |".format(
                cap=float(row["active_cap"]),
                ending=float(row["ending_total_equity_after_tax"]),
                active=float(row["ending_active_capital_after_tax"]),
                vault=float(row["ending_profit_vault_after_tax"]),
                tax=float(row["total_tax_reserved_or_withdrawn"]),
                dd=float(row["max_drawdown_total_equity_after_tax"]),
            )
        )
    lines.extend(
        [
            "",
            "## Cost stress at selected active cap",
            "",
            f"- Selected planning cap: `€{summary['selected_planning_cap']:,.0f}`",
            "",
            "| Cost bps | Ending total equity | Tax reserved | Max DD | PF | Win rate |",
            "| ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary["cost_stress_at_selected_cap"]:
        lines.append(
            "| {bps:.0f} | €{ending:,.2f} | €{tax:,.2f} | {dd:.2%} | {pf:.2f} | {wr:.2%} |".format(
                bps=float(row["cost_bps"]),
                ending=float(row["ending_total_equity_after_tax"]),
                tax=float(row["total_tax_reserved_or_withdrawn"]),
                dd=float(row["max_drawdown_total_equity_after_tax"]),
                pf=float(row["profit_factor_after_cost_stress"]),
                wr=float(row["win_rate_after_cost_stress"]),
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- Uncapped scanner equity is intentionally not used as a planning number.",
            "- These capped paths answer how much could be extracted while limiting active trading capital.",
            "- German tax reserve is simplified and requires Steuerberater review.",
        ]
    )
    (config.output_root / "multi_asset_capital_cap_liquidity_realism_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: CapitalCapConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    scanner_summary_path = config.scanner_root / "multi_asset_execution_feasibility_scanner_replay_summary.json"
    research_trades_path = config.scanner_root / "research_scanner_selected_trades.csv"
    holdout_trades_path = config.scanner_root / "sealed_holdout_scanner_selected_trades.csv"
    if not scanner_summary_path.exists() or not research_trades_path.exists() or not holdout_trades_path.exists():
        summary = {
            "court_name": COURT_NAME,
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_scanner_replay_artifacts"],
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_asset_capital_cap_liquidity_realism_summary.json", summary)
        return summary
    scanner_summary = _read_json(scanner_summary_path)
    research_rows = _load_scanner_trades(research_trades_path, period="research")
    holdout_rows = _load_scanner_trades(holdout_trades_path, period="sealed_holdout")

    baseline_scenarios = [
        _apply_cap_and_tax(research_rows, active_cap=cap, cost_bps=BASELINE_COST_BPS, tax_reserve_rate=TAX_RESERVE_RATE, max_notional_by_symbol=MAX_NOTIONAL_BY_SYMBOL)
        for cap in ACTIVE_CAPS
    ]
    holdout_capped_scenarios = [
        _apply_cap_and_tax(holdout_rows, active_cap=cap, cost_bps=BASELINE_COST_BPS, tax_reserve_rate=0.0, max_notional_by_symbol=MAX_NOTIONAL_BY_SYMBOL)
        for cap in ACTIVE_CAPS
    ]
    selected_planning_cap = 250_000.0
    cost_stress = [
        _apply_cap_and_tax(research_rows, active_cap=selected_planning_cap, cost_bps=bps, tax_reserve_rate=TAX_RESERVE_RATE, max_notional_by_symbol=MAX_NOTIONAL_BY_SYMBOL)
        for bps in COST_STRESS_BPS
    ]
    selected_baseline = next(row for row in baseline_scenarios if row["active_cap"] == selected_planning_cap)
    selected_holdout = next(row for row in holdout_capped_scenarios if row["active_cap"] == selected_planning_cap)

    # Yearly tax reserves are real cash outflows, but they are not trading drawdowns.
    # The strategy risk gate therefore uses active-capital pre-tax drawdown while
    # still reporting total after-tax wealth drawdown separately.
    realism_passed = (
        selected_baseline["ending_total_equity_after_tax"] > START_CAPITAL
        and selected_baseline["max_drawdown_active_capital_pre_tax"] <= 0.25
        and selected_holdout["ending_total_equity_after_tax"] > START_CAPITAL
    )
    one_million_after_tax_caps = [
        row["active_cap"] for row in baseline_scenarios if float(row["ending_total_equity_after_tax"]) >= 1_000_000.0
    ]
    if realism_passed and one_million_after_tax_caps:
        classification = PASSED
        reasons = ["capped_after_tax_research_path_preserves_million_scale_under_realism_constraints"]
    elif realism_passed:
        classification = WARNING
        reasons = ["capped_after_tax_path_profitable_but_does_not_reach_million_scale"]
    else:
        classification = FAILED
        reasons = ["capped_after_tax_path_failed_profitability_or_drawdown_gate"]

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_scanner_summary": str(scanner_summary_path),
        "source_research_scanner_trades": str(research_trades_path),
        "source_holdout_scanner_trades": str(holdout_trades_path),
        "scanner_classification": scanner_summary.get("final_classification"),
        "strategy_logic_changed": False,
        "thresholds_tuned": False,
        "entries_changed": False,
        "exits_changed": False,
        "baseline_cost_model_already_in_trade_rows": {
            "round_trip_cost_bps": BASELINE_COST_BPS,
            "costs_already_embedded_in_net_r": True,
        },
        "realism_model": {
            "active_cap_limits_risk_base": True,
            "profits_above_active_cap_move_to_vault": True,
            "risk_per_trade": RISK_PER_TRADE,
            "yearly_tax_reserve_rate": TAX_RESERVE_RATE,
            "tax_advice": False,
            "requires_steuerberater_review": True,
            "max_notional_by_symbol": MAX_NOTIONAL_BY_SYMBOL,
            "capital_caps_tested": list(ACTIVE_CAPS),
            "cost_stress_bps": list(COST_STRESS_BPS),
        },
        "selected_planning_cap": selected_planning_cap,
        "selected_planning_cap_result": {key: value for key, value in selected_baseline.items() if key not in {"trade_rows", "yearly_rows"}},
        "selected_planning_cap_holdout_result_no_tax": {key: value for key, value in selected_holdout.items() if key not in {"trade_rows", "yearly_rows"}},
        "active_caps_reaching_1m_after_tax": one_million_after_tax_caps,
        "baseline_active_cap_scenarios": _scenario_rows(baseline_scenarios),
        "holdout_active_cap_scenarios_no_tax": _scenario_rows(holdout_capped_scenarios),
        "cost_stress_at_selected_cap": _scenario_rows(cost_stress),
        "selected_planning_cap_yearly_tax_rows": selected_baseline["yearly_rows"],
        "interpretation_limits": {
            "uncapped_quintillion_number_should_not_be_used_as_cash_forecast": True,
            "capped_results_are_planning_numbers_not_live_promises": True,
            "tax_model_is_simplified": True,
            "liquidity_model_is_placeholder_until_exchange_order_book_depth_court": True,
            "strategy_drawdown_gate_uses_active_capital_pre_tax_drawdown": True,
            "total_after_tax_drawdown_includes_yearly_tax_withdrawals": True,
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_asset_capital_cap_liquidity_realism_summary.json", summary)
    _write_csv(config.output_root / "capital_cap_baseline_scenarios.csv", _scenario_rows(baseline_scenarios))
    _write_csv(config.output_root / "capital_cap_holdout_scenarios_no_tax.csv", _scenario_rows(holdout_capped_scenarios))
    _write_csv(config.output_root / "capital_cap_cost_stress_selected_cap.csv", _scenario_rows(cost_stress))
    _write_csv(config.output_root / "selected_planning_cap_yearly_tax_rows.csv", selected_baseline["yearly_rows"])
    _write_csv(config.output_root / "selected_planning_cap_trade_ledger.csv", selected_baseline["trade_rows"])
    _write_report(config, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run capped capital/liquidity realism court for the multi-asset scanner.")
    parser.add_argument("--scanner-root", default=f"structural_compounding_lab/output/multi_asset_execution_feasibility_scanner_replay_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        CapitalCapConfig(
            project_root=root,
            package_root=package_root(),
            scanner_root=resolve_project_path(args.scanner_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
