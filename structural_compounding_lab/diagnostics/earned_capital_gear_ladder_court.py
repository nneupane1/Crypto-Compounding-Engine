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
from structural_compounding_lab.diagnostics.multi_asset_capital_cap_liquidity_realism_court import (
    BASELINE_COST_BPS,
    RISK_PER_TRADE,
    START_CAPITAL,
    TAX_RESERVE_RATE,
    _adjusted_net_r,
    _max_drawdown,
    _profit_factor,
    _safe_ratio,
)


COURT_NAME = "EARNED_CAPITAL_GEAR_LADDER_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "earned_capital_gear_ladder_court_001"

PASSED = "EARNED_CAPITAL_GEAR_LADDER_READY_RESEARCH_ONLY"
WARNING = "EARNED_CAPITAL_GEAR_LADDER_WARNING_RESEARCH_ONLY"
FAILED = "EARNED_CAPITAL_GEAR_LADDER_FAILED_RESEARCH_ONLY"
BLOCKED = "EARNED_CAPITAL_GEAR_LADDER_BLOCKED_RESEARCH_ONLY"

BASE_SYMBOL_CAPS_EUR: dict[str, float] = {
    "ADAUSDT": 250_000.0,
    "LINKUSDT": 250_000.0,
    "BNBUSDT": 350_000.0,
    "XRPUSDT": 250_000.0,
    "AVAXUSDT": 250_000.0,
    "DOGEUSDT": 200_000.0,
    "ETHUSDT": 500_000.0,
    "SOLUSDT": 350_000.0,
}

GEAR_DEFINITIONS: list[dict[str, Any]] = [
    {
        "gear": 0,
        "name": "BASE_LOCKED_CAP",
        "active_cap_eur": 250_000.0,
        "total_equity_gate_eur": START_CAPITAL,
        "requires_scheduler_dry_run": False,
        "requires_six_month_forward": False,
        "requires_public_fetch_runtime": False,
        "requires_exact_fill_simulation": False,
        "requires_all_symbols_liquidity_depth_pass": False,
        "max_active_drawdown_gate": 0.25,
        "symbol_caps_eur": BASE_SYMBOL_CAPS_EUR,
    },
    {
        "gear": 1,
        "name": "EARNED_500K_CAP",
        "active_cap_eur": 500_000.0,
        "total_equity_gate_eur": 1_000_000.0,
        "requires_scheduler_dry_run": True,
        "requires_six_month_forward": False,
        "requires_public_fetch_runtime": True,
        "requires_exact_fill_simulation": False,
        "requires_all_symbols_liquidity_depth_pass": False,
        "max_active_drawdown_gate": 0.10,
        "symbol_caps_eur": {
            **BASE_SYMBOL_CAPS_EUR,
            "BNBUSDT": 700_000.0,
            "XRPUSDT": 500_000.0,
            "DOGEUSDT": 400_000.0,
            "ETHUSDT": 1_000_000.0,
            "SOLUSDT": 700_000.0,
        },
    },
    {
        "gear": 2,
        "name": "EARNED_1M_CAP",
        "active_cap_eur": 1_000_000.0,
        "total_equity_gate_eur": 3_000_000.0,
        "requires_scheduler_dry_run": True,
        "requires_six_month_forward": True,
        "requires_public_fetch_runtime": True,
        "requires_exact_fill_simulation": True,
        "requires_all_symbols_liquidity_depth_pass": False,
        "max_active_drawdown_gate": 0.08,
        "symbol_caps_eur": {
            "ADAUSDT": 500_000.0,
            "LINKUSDT": 500_000.0,
            "BNBUSDT": 1_500_000.0,
            "XRPUSDT": 1_000_000.0,
            "AVAXUSDT": 500_000.0,
            "DOGEUSDT": 750_000.0,
            "ETHUSDT": 2_000_000.0,
            "SOLUSDT": 1_500_000.0,
        },
    },
    {
        "gear": 3,
        "name": "EARNED_2M_CAP",
        "active_cap_eur": 2_000_000.0,
        "total_equity_gate_eur": 7_000_000.0,
        "requires_scheduler_dry_run": True,
        "requires_six_month_forward": True,
        "requires_public_fetch_runtime": True,
        "requires_exact_fill_simulation": True,
        "requires_all_symbols_liquidity_depth_pass": True,
        "max_active_drawdown_gate": 0.06,
        "symbol_caps_eur": {
            "ADAUSDT": 1_000_000.0,
            "LINKUSDT": 1_000_000.0,
            "BNBUSDT": 3_000_000.0,
            "XRPUSDT": 2_000_000.0,
            "AVAXUSDT": 1_000_000.0,
            "DOGEUSDT": 1_500_000.0,
            "ETHUSDT": 4_000_000.0,
            "SOLUSDT": 3_000_000.0,
        },
    },
]

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "tax_advice": False,
    "requires_steuerberater_review": True,
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
}


@dataclass(frozen=True)
class EarnedGearConfig:
    project_root: Path
    package_root: Path
    scanner_root: Path
    capital_cap_root: Path
    capacity_root: Path
    dry_run_root: Path
    public_fetch_root: Path
    output_root: Path


def default_config() -> EarnedGearConfig:
    pkg = package_root()
    return EarnedGearConfig(
        project_root=project_root(),
        package_root=pkg,
        scanner_root=pkg / "output" / "multi_asset_execution_feasibility_scanner_replay_court_001",
        capital_cap_root=pkg / "output" / "multi_asset_capital_cap_liquidity_realism_court_001",
        capacity_root=pkg / "output" / "multi_symbol_scheduler_capacity_liquidity_court_001",
        dry_run_root=pkg / "output" / "multi_symbol_realtime_scheduler_shadow_dry_run_court_001",
        public_fetch_root=pkg / "output" / "multi_symbol_public_fetch_runtime_prototype_court_001",
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


def _parse_ts(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _load_scanner_trades(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            payload = dict(row)
            payload["symbol"] = str(row.get("symbol") or "").upper()
            payload["entry_timestamp"] = _parse_ts(str(row.get("entry_time")))
            payload["exit_timestamp"] = _parse_ts(str(row.get("exit_time")))
            payload["net_r"] = float(row.get("net_r") or 0.0)
            payload["net_cost_r"] = float(row.get("net_cost_r") or 0.0)
            payload["scanner_trade_number"] = int(float(row.get("scanner_trade_number") or 0))
            rows.append(payload)
    return sorted(rows, key=lambda item: (item["entry_timestamp"], item["scanner_trade_number"]))


def _current_evidence(config: EarnedGearConfig) -> dict[str, Any]:
    cap = _read_json(config.capital_cap_root / "multi_asset_capital_cap_liquidity_realism_summary.json")
    capacity = _read_json(config.capacity_root / "multi_symbol_scheduler_capacity_liquidity_summary.json")
    dry = _read_json(config.dry_run_root / "multi_symbol_realtime_scheduler_shadow_dry_run_summary.json")
    public_fetch = _read_json(config.public_fetch_root / "multi_symbol_public_fetch_runtime_prototype_summary.json")
    return {
        "capital_cap_realism_validated": cap.get("final_classification") == "MULTI_ASSET_CAPITAL_CAP_REALISM_VALIDATED_RESEARCH_ONLY",
        "scheduler_dry_run_passed": dry.get("final_classification") == "MULTI_SYMBOL_REALTIME_SCHEDULER_SHADOW_DRY_RUN_PASSED_RESEARCH_ONLY",
        "public_fetch_runtime_prototype_passed": public_fetch.get("final_classification") == "MULTI_SYMBOL_PUBLIC_FETCH_RUNTIME_PROTOTYPE_PASSED_RESEARCH_ONLY",
        "six_month_multi_symbol_forward_passed": False,
        "exact_fill_simulation_passed": False,
        "all_symbols_liquidity_depth_passed": bool(
            capacity.get("public_market_capacity", {}).get("all_symbols_depth_25bps_covers_assumed_notional")
        ),
        "capacity_liquidity_classification": capacity.get("final_classification"),
        "public_fetch_runtime_classification": public_fetch.get("final_classification"),
        "capacity_warning_present": capacity.get("final_classification") == "MULTI_SYMBOL_SCHEDULER_CAPACITY_LIQUIDITY_WARNING_RESEARCH_ONLY",
        "future_live_or_paper_enabled": False,
    }


def _future_assumed_evidence() -> dict[str, Any]:
    return {
        "capital_cap_realism_validated": True,
        "scheduler_dry_run_passed": True,
        "public_fetch_runtime_prototype_passed": True,
        "six_month_multi_symbol_forward_passed": True,
        "exact_fill_simulation_passed": True,
        "all_symbols_liquidity_depth_passed": True,
        "capacity_liquidity_classification": "ASSUMED_FUTURE_PASS_FOR_SENSITIVITY_ONLY",
        "capacity_warning_present": False,
        "future_live_or_paper_enabled": False,
    }


def _gear_requirements_met(gear: dict[str, Any], evidence: dict[str, Any], *, total_equity: float, active_drawdown: float) -> tuple[bool, list[str]]:
    blockers: list[str] = []
    if total_equity < float(gear["total_equity_gate_eur"]):
        blockers.append("total_equity_gate_not_reached")
    if active_drawdown > float(gear["max_active_drawdown_gate"]):
        blockers.append("active_drawdown_gate_failed")
    if gear["requires_scheduler_dry_run"] and not evidence.get("scheduler_dry_run_passed"):
        blockers.append("scheduler_dry_run_not_passed")
    if gear["requires_public_fetch_runtime"] and not evidence.get("public_fetch_runtime_prototype_passed"):
        blockers.append("public_fetch_runtime_prototype_not_passed")
    if gear["requires_six_month_forward"] and not evidence.get("six_month_multi_symbol_forward_passed"):
        blockers.append("six_month_multi_symbol_forward_not_passed")
    if gear["requires_exact_fill_simulation"] and not evidence.get("exact_fill_simulation_passed"):
        blockers.append("exact_fill_simulation_not_passed")
    if gear["requires_all_symbols_liquidity_depth_pass"] and not evidence.get("all_symbols_liquidity_depth_passed"):
        blockers.append("all_symbols_liquidity_depth_not_passed")
    return not blockers, blockers


def _simulate_ladder(
    rows: list[dict[str, Any]],
    *,
    evidence: dict[str, Any],
    scenario_name: str,
    allow_future_gears: bool,
) -> dict[str, Any]:
    active = START_CAPITAL
    vault = 0.0
    current_gear_index = 0
    current_gear = GEAR_DEFINITIONS[current_gear_index]
    active_curve = [active]
    pre_tax_total_curve = [active + vault]
    trade_rows: list[dict[str, Any]] = []
    values: list[float] = []
    gear_events: list[dict[str, Any]] = [
        {
            "trade_number": 0,
            "timestamp": None,
            "gear": current_gear["gear"],
            "gear_name": current_gear["name"],
            "active_cap_eur": current_gear["active_cap_eur"],
            "event": "initial_gear",
        }
    ]
    yearly_pnl: dict[int, float] = {}
    yearly_trade_count: dict[int, int] = {}
    notional_limited_trades = 0

    for index, row in enumerate(rows, start=1):
        total = active + vault
        active_drawdown = _max_drawdown(active_curve)
        if allow_future_gears:
            while current_gear_index + 1 < len(GEAR_DEFINITIONS):
                next_gear = GEAR_DEFINITIONS[current_gear_index + 1]
                ok, blockers = _gear_requirements_met(next_gear, evidence, total_equity=total, active_drawdown=active_drawdown)
                if not ok:
                    break
                current_gear_index += 1
                current_gear = GEAR_DEFINITIONS[current_gear_index]
                gear_events.append(
                    {
                        "trade_number": index,
                        "timestamp": row["entry_timestamp"].isoformat(),
                        "gear": current_gear["gear"],
                        "gear_name": current_gear["name"],
                        "active_cap_eur": current_gear["active_cap_eur"],
                        "event": "gear_unlocked",
                        "total_equity_before_trade": total,
                        "active_drawdown_before_trade": active_drawdown,
                    }
                )
        active_cap = float(current_gear["active_cap_eur"])
        symbol_caps = dict(current_gear["symbol_caps_eur"])
        risk_base = max(0.0, min(active, active_cap))
        theoretical_risk = risk_base * RISK_PER_TRADE
        symbol_cap = float(symbol_caps.get(str(row["symbol"]), BASE_SYMBOL_CAPS_EUR.get(str(row["symbol"]), active_cap)))
        risk_eur = min(theoretical_risk, symbol_cap * RISK_PER_TRADE)
        if risk_eur < theoretical_risk:
            notional_limited_trades += 1
        net_r = _adjusted_net_r(row, cost_bps=BASELINE_COST_BPS)
        pnl = risk_eur * net_r
        active_before = active
        vault_before = vault
        total_before = active + vault
        active += pnl
        if active > active_cap:
            vault += active - active_cap
            active = active_cap
        values.append(net_r)
        year = int(row["exit_timestamp"].year)
        yearly_pnl[year] = yearly_pnl.get(year, 0.0) + pnl
        yearly_trade_count[year] = yearly_trade_count.get(year, 0) + 1
        active_curve.append(active)
        pre_tax_total_curve.append(active + vault)
        trade_rows.append(
            {
                "trade_number": index,
                "scenario_name": scenario_name,
                "symbol": row["symbol"],
                "trade_id": row.get("trade_id"),
                "entry_time": row["entry_timestamp"].isoformat(),
                "exit_time": row["exit_timestamp"].isoformat(),
                "gear": current_gear["gear"],
                "gear_name": current_gear["name"],
                "active_cap_eur": active_cap,
                "symbol_cap_eur": symbol_cap,
                "active_before_trade": active_before,
                "vault_before_trade": vault_before,
                "total_before_trade": total_before,
                "risk_eur": risk_eur,
                "theoretical_risk_eur": theoretical_risk,
                "notional_limited": risk_eur < theoretical_risk,
                "net_r": net_r,
                "net_pnl_eur": pnl,
                "active_after_trade_pre_tax": active,
                "vault_after_trade_pre_tax": vault,
                "total_after_trade_pre_tax": active + vault,
            }
        )

    active_after_tax = START_CAPITAL
    vault_after_tax = 0.0
    cumulative_tax = 0.0
    post_tax_curve = [active_after_tax + vault_after_tax]
    yearly_rows: list[dict[str, Any]] = []
    # Re-apply the same trade rows in order for yearly tax withdrawals.
    for year in sorted(yearly_pnl):
        bucket = [row for row in trade_rows if int(str(row["exit_time"])[:4]) == year]
        year_pnl = 0.0
        for tr in bucket:
            active_after_tax += float(tr["net_pnl_eur"])
            cap = float(tr["active_cap_eur"])
            if active_after_tax > cap:
                vault_after_tax += active_after_tax - cap
                active_after_tax = cap
            year_pnl += float(tr["net_pnl_eur"])
            post_tax_curve.append(active_after_tax + vault_after_tax)
        tax = max(year_pnl, 0.0) * TAX_RESERVE_RATE
        from_vault = min(vault_after_tax, tax)
        vault_after_tax -= from_vault
        remainder = tax - from_vault
        from_active = min(active_after_tax, remainder) if remainder > 0 else 0.0
        active_after_tax = max(0.0, active_after_tax - from_active)
        cumulative_tax += tax
        yearly_rows.append(
            {
                "year": year,
                "trades": len(bucket),
                "realized_net_pnl_before_tax": year_pnl,
                "tax_reserved_or_withdrawn": tax,
                "tax_paid_from_vault": from_vault,
                "tax_paid_from_active_capital": from_active,
                "ending_active_capital_after_tax": active_after_tax,
                "ending_profit_vault_after_tax": vault_after_tax,
                "ending_total_equity_after_tax": active_after_tax + vault_after_tax,
            }
        )
        post_tax_curve.append(active_after_tax + vault_after_tax)

    ending_total = active_after_tax + vault_after_tax
    return {
        "scenario_name": scenario_name,
        "allow_future_gears": allow_future_gears,
        "starting_equity": START_CAPITAL,
        "ending_total_equity_after_tax": ending_total,
        "ending_active_capital_after_tax": active_after_tax,
        "ending_profit_vault_after_tax": vault_after_tax,
        "net_gain_after_tax": ending_total - START_CAPITAL,
        "return_multiple_after_tax": _safe_ratio(ending_total, START_CAPITAL, 0.0),
        "total_tax_reserved_or_withdrawn": cumulative_tax,
        "highest_gear_reached": current_gear["gear"],
        "highest_active_cap_eur": current_gear["active_cap_eur"],
        "accepted_trades": len(rows),
        "notional_limited_trades": notional_limited_trades,
        "profit_factor": _profit_factor(values),
        "win_rate": _safe_ratio(sum(1 for value in values if value > 0.0), len(values), 0.0),
        "net_total_R": sum(values),
        "max_drawdown_active_capital_pre_tax": _max_drawdown(active_curve),
        "max_drawdown_total_after_tax": _max_drawdown(post_tax_curve),
        "gear_events": gear_events,
        "yearly_rows": yearly_rows,
        "trade_rows": trade_rows,
    }


def _blocked_gears(evidence: dict[str, Any], *, current_total: float, current_active_drawdown: float) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for gear in GEAR_DEFINITIONS[1:]:
        ok, blockers = _gear_requirements_met(gear, evidence, total_equity=current_total, active_drawdown=current_active_drawdown)
        rows.append(
            {
                "gear": gear["gear"],
                "gear_name": gear["name"],
                "active_cap_eur": gear["active_cap_eur"],
                "currently_unlocked": ok,
                "current_blockers": blockers,
            }
        )
    return rows


def _scenario_summary(row: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key not in {"trade_rows", "yearly_rows", "gear_events"}}


def _write_report(config: EarnedGearConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# Earned Capital Gear Ladder Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        "- Research-only. No paper/live/order/broker path enabled.",
        "- Base active cap is locked at `EUR 250,000` unless future evidence gates explicitly pass.",
        "- Higher gears are not automatic compounding. They are earned capacity states.",
        "",
        "## Current evidence mode",
        "",
        f"- Ending after tax reserve: `EUR {summary['current_evidence_result']['ending_total_equity_after_tax']:,.2f}`",
        f"- Highest gear reached: `{summary['current_evidence_result']['highest_gear_reached']}`",
        f"- Highest active cap: `EUR {summary['current_evidence_result']['highest_active_cap_eur']:,.0f}`",
        "",
        "## Future earned sensitivity mode",
        "",
        f"- Ending after tax reserve: `EUR {summary['future_all_gates_pass_sensitivity_result']['ending_total_equity_after_tax']:,.2f}`",
        f"- Highest gear reached: `{summary['future_all_gates_pass_sensitivity_result']['highest_gear_reached']}`",
        f"- Highest active cap: `EUR {summary['future_all_gates_pass_sensitivity_result']['highest_active_cap_eur']:,.0f}`",
        "",
        "## Current blockers",
        "",
        "| Gear | Active cap | Currently unlocked | Blockers |",
        "| ---: | ---: | --- | --- |",
    ]
    for row in summary["current_gear_unlock_audit"]:
        lines.append(
            "| {gear} | EUR {cap:,.0f} | {ok} | {blockers} |".format(
                gear=row["gear"],
                cap=float(row["active_cap_eur"]),
                ok=str(bool(row["currently_unlocked"])).lower(),
                blockers=", ".join(row["current_blockers"]) or "none",
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "- The current court locks the system at `EUR 250,000` active cap.",
            "- The higher-million path exists only as a future evidence ladder.",
            "- The ladder cannot promote itself to paper/live/broker execution.",
        ]
    )
    (config.output_root / "earned_capital_gear_ladder_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: EarnedGearConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    trades_path = config.scanner_root / "research_scanner_selected_trades.csv"
    scanner_summary = _read_json(config.scanner_root / "multi_asset_execution_feasibility_scanner_replay_summary.json")
    if not trades_path.exists() or not scanner_summary:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_scanner_replay_artifacts"],
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "earned_capital_gear_ladder_summary.json", summary)
        return summary

    trades = _load_scanner_trades(trades_path)
    evidence = _current_evidence(config)
    future_evidence = _future_assumed_evidence()
    current_result = _simulate_ladder(
        trades,
        evidence=evidence,
        scenario_name="current_evidence_earned_gear_ladder",
        allow_future_gears=True,
    )
    future_result = _simulate_ladder(
        trades,
        evidence=future_evidence,
        scenario_name="future_all_gates_pass_sensitivity",
        allow_future_gears=True,
    )
    current_unlock_audit = _blocked_gears(
        evidence,
        current_total=float(current_result["ending_total_equity_after_tax"]),
        current_active_drawdown=float(current_result["max_drawdown_active_capital_pre_tax"]),
    )

    current_gear_valid = current_result["highest_gear_reached"] in {0, 1}
    future_path_exists = future_result["ending_total_equity_after_tax"] > current_result["ending_total_equity_after_tax"]
    if evidence["capital_cap_realism_validated"] and evidence["scheduler_dry_run_passed"] and current_gear_valid:
        classification = PASSED
        reasons = ["earned_gear_ladder_defined_and_current_evidence_applied_research_only"]
        if current_result["highest_gear_reached"] == 1:
            reasons.append("gear_1_500k_unlocked_by_public_fetch_runtime_prototype")
        else:
            reasons.append("base_250k_cap_remains_locked_until_public_fetch_runtime_passes")
        if future_path_exists:
            reasons.append("future_sensitivity_shows_higher_million_path_if_future_gates_pass")
    else:
        classification = WARNING
        reasons = ["gear_ladder_defined_but_current_evidence_stack_incomplete"]

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_scanner_summary": str(config.scanner_root / "multi_asset_execution_feasibility_scanner_replay_summary.json"),
        "source_research_scanner_trades": str(trades_path),
        "base_active_cap_locked_eur": 250_000.0,
        "gear_definitions": GEAR_DEFINITIONS,
        "current_evidence": evidence,
        "current_gear_unlock_audit": current_unlock_audit,
        "current_evidence_result": _scenario_summary(current_result),
        "future_all_gates_pass_sensitivity_result": _scenario_summary(future_result),
        "future_sensitivity_is_not_current_permission": True,
        "gear_events_file_current": str(config.output_root / "current_evidence_gear_events.csv"),
        "gear_events_file_future_sensitivity": str(config.output_root / "future_all_gates_pass_gear_events.csv"),
        "gate": {
            "may_use_250k_as_locked_planning_cap": True,
            "may_unlock_500k_now": current_result["highest_gear_reached"] >= 1,
            "may_unlock_1m_now": False,
            "may_unlock_2m_now": False,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "next_required_court": (
                "MULTI_SYMBOL_EXACT_FILL_AND_SYMBOL_CAP_CALIBRATION_COURT_RESEARCH_ONLY"
                if current_result["highest_gear_reached"] >= 1
                else "MULTI_SYMBOL_PUBLIC_FETCH_RUNTIME_PROTOTYPE_WITH_SYMBOL_CAPS_RESEARCH_ONLY"
            ),
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "earned_capital_gear_ladder_summary.json", summary)
    _write_csv(config.output_root / "current_evidence_gear_events.csv", current_result["gear_events"])
    _write_csv(config.output_root / "future_all_gates_pass_gear_events.csv", future_result["gear_events"])
    _write_csv(config.output_root / "current_evidence_yearly_tax_rows.csv", current_result["yearly_rows"])
    _write_csv(config.output_root / "future_all_gates_pass_yearly_tax_rows.csv", future_result["yearly_rows"])
    _write_csv(config.output_root / "current_evidence_trade_ledger.csv", current_result["trade_rows"])
    _write_csv(config.output_root / "future_all_gates_pass_trade_ledger.csv", future_result["trade_rows"])
    _write_report(config, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run research-only earned capital gear ladder court.")
    parser.add_argument("--scanner-root", default="structural_compounding_lab/output/multi_asset_execution_feasibility_scanner_replay_court_001")
    parser.add_argument("--capital-cap-root", default="structural_compounding_lab/output/multi_asset_capital_cap_liquidity_realism_court_001")
    parser.add_argument("--capacity-root", default="structural_compounding_lab/output/multi_symbol_scheduler_capacity_liquidity_court_001")
    parser.add_argument("--dry-run-root", default="structural_compounding_lab/output/multi_symbol_realtime_scheduler_shadow_dry_run_court_001")
    parser.add_argument("--public-fetch-root", default="structural_compounding_lab/output/multi_symbol_public_fetch_runtime_prototype_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        EarnedGearConfig(
            project_root=root,
            package_root=package_root(),
            scanner_root=resolve_project_path(args.scanner_root),
            capital_cap_root=resolve_project_path(args.capital_cap_root),
            capacity_root=resolve_project_path(args.capacity_root),
            dry_run_root=resolve_project_path(args.dry_run_root),
            public_fetch_root=resolve_project_path(args.public_fetch_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
