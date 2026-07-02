from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path
from structural_compounding_lab.diagnostics.multi_asset_capital_cap_liquidity_realism_court import (
    BASELINE_COST_BPS,
    START_CAPITAL,
    TAX_RESERVE_RATE,
    _apply_cap_and_tax,
    _load_scanner_trades,
    _write_csv,
    _write_json,
)


COURT_NAME = "MULTI_SYMBOL_REDUCED_CAP_GEAR_LADDER_RESTATEMENT_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_symbol_reduced_cap_gear_ladder_restatement_court_001"

PASSED = "MULTI_SYMBOL_REDUCED_CAP_GEAR_LADDER_RESTATEMENT_PASSED_RESEARCH_ONLY"
WARNING = "MULTI_SYMBOL_REDUCED_CAP_GEAR_LADDER_RESTATEMENT_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_SYMBOL_REDUCED_CAP_GEAR_LADDER_RESTATEMENT_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_SYMBOL_REDUCED_CAP_GEAR_LADDER_RESTATEMENT_BLOCKED_RESEARCH_ONLY"

ACTIVE_CAP_EUR = 500_000.0

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
    "tax_advice": False,
    "requires_steuerberater_review": True,
}


@dataclass(frozen=True)
class ReducedCapConfig:
    project_root: Path
    package_root: Path
    scanner_root: Path
    exact_fill_root: Path
    output_root: Path


def default_config() -> ReducedCapConfig:
    pkg = package_root()
    return ReducedCapConfig(
        project_root=project_root(),
        package_root=pkg,
        scanner_root=pkg / "output" / "multi_asset_execution_feasibility_scanner_replay_court_001",
        exact_fill_root=pkg / "output" / "multi_symbol_exact_fill_symbol_cap_calibration_court_001",
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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_report(config: ReducedCapConfig, summary: dict[str, Any]) -> None:
    result = summary["reduced_cap_research_result"]
    holdout = summary["reduced_cap_holdout_result_no_tax"]
    lines = [
        "# Multi-Symbol Reduced-Cap Gear Ladder Restatement Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        "- Research-only. Uses exact-fill recommended symbol caps. No paper/live/order/broker path.",
        "",
        "## Restated Gear 1",
        "",
        f"- Active cap: `EUR {ACTIVE_CAP_EUR:,.0f}`",
        f"- Research ending after tax reserve: `EUR {result['ending_total_equity_after_tax']:,.2f}`",
        f"- Holdout ending, no tax: `EUR {holdout['ending_total_equity_after_tax']:,.2f}`",
        f"- Tax reserve: `EUR {result['total_tax_reserved_or_withdrawn']:,.2f}`",
        "",
        "## Recommended caps",
        "",
        "| Symbol | Cap |",
        "| --- | ---: |",
    ]
    for symbol, cap in sorted(summary["recommended_symbol_caps_eur"].items()):
        lines.append(f"| {symbol} | EUR {float(cap):,.0f} |")
    (config.output_root / "multi_symbol_reduced_cap_gear_ladder_restatement_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: ReducedCapConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    exact = _read_json(config.exact_fill_root / "multi_symbol_exact_fill_symbol_cap_calibration_summary.json")
    research_path = config.scanner_root / "research_scanner_selected_trades.csv"
    holdout_path = config.scanner_root / "sealed_holdout_scanner_selected_trades.csv"
    if not exact or not research_path.exists() or not holdout_path.exists():
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_exact_fill_or_scanner_artifacts"],
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json", summary)
        return summary
    caps = {str(symbol): float(cap) for symbol, cap in (exact.get("recommended_symbol_caps_eur") or {}).items()}
    if not caps or any(cap <= 0 for cap in caps.values()):
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": FAILED,
            "classification_reasons": ["recommended_symbol_caps_missing_or_zero"],
            "source_exact_fill_summary": str(config.exact_fill_root / "multi_symbol_exact_fill_symbol_cap_calibration_summary.json"),
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json", summary)
        return summary
    research_rows = _load_scanner_trades(research_path, period="research")
    holdout_rows = _load_scanner_trades(holdout_path, period="holdout")
    research = _apply_cap_and_tax(
        research_rows,
        active_cap=ACTIVE_CAP_EUR,
        cost_bps=BASELINE_COST_BPS,
        tax_reserve_rate=TAX_RESERVE_RATE,
        max_notional_by_symbol=caps,
    )
    holdout = _apply_cap_and_tax(
        holdout_rows,
        active_cap=ACTIVE_CAP_EUR,
        cost_bps=BASELINE_COST_BPS,
        tax_reserve_rate=0.0,
        max_notional_by_symbol=caps,
    )
    research_ok = research["ending_total_equity_after_tax"] > 1_000_000.0 and research["max_drawdown_active_capital_pre_tax"] <= 0.25
    holdout_ok = holdout["ending_total_equity_after_tax"] > START_CAPITAL and holdout["max_drawdown_active_capital_pre_tax"] <= 0.15
    if research_ok and holdout_ok:
        classification = PASSED
        reasons = ["reduced_fill_safe_caps_preserve_million_scale_research_path"]
    elif research["ending_total_equity_after_tax"] > START_CAPITAL and holdout["ending_total_equity_after_tax"] > START_CAPITAL:
        classification = WARNING
        reasons = ["reduced_fill_safe_caps_profitable_but_weaker_than_million_gate_or_drawdown_gate"]
    else:
        classification = FAILED
        reasons = ["reduced_fill_safe_caps_failed_profitability_gate"]
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_exact_fill_summary": str(config.exact_fill_root / "multi_symbol_exact_fill_symbol_cap_calibration_summary.json"),
        "source_research_scanner_trades": str(research_path),
        "source_holdout_scanner_trades": str(holdout_path),
        "active_cap_eur": ACTIVE_CAP_EUR,
        "recommended_symbol_caps_eur": caps,
        "reduced_cap_research_result": {key: value for key, value in research.items() if key not in {"trade_rows", "yearly_rows"}},
        "reduced_cap_holdout_result_no_tax": {key: value for key, value in holdout.items() if key not in {"trade_rows", "yearly_rows"}},
        "reduced_cap_yearly_tax_rows": research["yearly_rows"],
        "gate": {
            "may_treat_500k_gear1_as_fill_calibrated_research_cap": classification == PASSED,
            "may_unlock_1m_now": False,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "paper_validation_ready": False,
            "next_required_court": "SIX_MONTH_MULTI_SYMBOL_FORWARD_EVIDENCE_COURT_RESEARCH_ONLY",
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json", summary)
    _write_csv(config.output_root / "reduced_cap_yearly_tax_rows.csv", research["yearly_rows"])
    _write_csv(config.output_root / "reduced_cap_research_trade_ledger.csv", research["trade_rows"])
    _write_csv(config.output_root / "reduced_cap_holdout_trade_ledger.csv", holdout["trade_rows"])
    _write_report(config, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Restate Gear 1 using exact-fill recommended reduced symbol caps.")
    parser.add_argument("--scanner-root", default="structural_compounding_lab/output/multi_asset_execution_feasibility_scanner_replay_court_001")
    parser.add_argument("--exact-fill-root", default="structural_compounding_lab/output/multi_symbol_exact_fill_symbol_cap_calibration_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        ReducedCapConfig(
            project_root=root,
            package_root=package_root(),
            scanner_root=resolve_project_path(args.scanner_root),
            exact_fill_root=resolve_project_path(args.exact_fill_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
