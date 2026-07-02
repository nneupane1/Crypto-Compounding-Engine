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

from structural_compounding_lab.common.project_paths import package_root, project_root  # noqa: E402


COURT_NAME = "GERMANY_CRYPTO_TAX_RESERVE_PLANNING_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "germany_crypto_tax_reserve_planning_001"
START_CAPITAL_EUR = 25_000.0
SOURCE_ARTIFACT = "cost_aware_frozen_candidate_rebuild_court_001/candidate_full_history_results.csv"

SCENARIOS = {
    "reserve_35pct_mid_high_income_placeholder": 0.35,
    "reserve_42pct_top_marginal_without_soli": 0.42,
    "reserve_44_31pct_42pct_plus_soli_on_tax": 0.42 * 1.055,
    "reserve_45pct_rich_tax_without_soli": 0.45,
    "reserve_47_475pct_rich_tax_plus_soli_on_tax": 0.45 * 1.055,
}

SAFETY_FLAGS = {
    "research_only": True,
    "tax_advice": False,
    "requires_steuerberater_review": True,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "no_order_path_created": True,
    "no_broker_path_created": True,
    "paper_validation_ready": False,
}


@dataclass(frozen=True)
class TaxReserveConfig:
    project_root: Path
    package_root: Path
    source_trades_csv: Path
    output_root: Path


def default_config() -> TaxReserveConfig:
    pkg = package_root()
    return TaxReserveConfig(
        project_root=project_root(),
        package_root=pkg,
        source_trades_csv=pkg / "output" / SOURCE_ARTIFACT,
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(row: dict[str, Any], key: str) -> float:
    try:
        return float(row.get(key) or 0.0)
    except Exception:
        return 0.0


def _bool(row: dict[str, Any], key: str) -> bool:
    return str(row.get(key, "")).strip().lower() in {"true", "1", "yes"}


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
    path.write_text(json.dumps(_round_payload(payload), indent=2, sort_keys=True), encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def _load_trades(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            if not _bool(row, "candidate_guard_accepted"):
                continue
            ts = str(row.get("exit_timestamp") or row.get("exit_time") or row.get("entry_timestamp"))
            payload = dict(row)
            payload["tax_year"] = int(ts[:4])
            payload["net_pnl_eur"] = _float(row, "net_pnl_eur")
            rows.append(payload)
    return rows


def _yearly_realized(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for year in sorted({row["tax_year"] for row in rows}):
        bucket = [row for row in rows if row["tax_year"] == year]
        pnl = sum(float(row["net_pnl_eur"]) for row in bucket)
        out.append(
            {
                "year": year,
                "accepted_trades": len(bucket),
                "winning_trades": sum(1 for row in bucket if float(row["net_pnl_eur"]) > 0),
                "losing_trades": sum(1 for row in bucket if float(row["net_pnl_eur"]) < 0),
                "realized_net_pnl_eur_before_tax_reserve": pnl,
            }
        )
    return out


def _tax_scenarios(yearly: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in yearly:
        pnl = float(item["realized_net_pnl_eur_before_tax_reserve"])
        taxable_gain = max(pnl, 0.0)
        for name, rate in SCENARIOS.items():
            tax = taxable_gain * rate
            rows.append(
                {
                    **item,
                    "scenario": name,
                    "reserve_rate": rate,
                    "estimated_tax_reserve_eur": tax,
                    "after_tax_profit_available_to_keep_or_compound_eur": pnl - tax,
                }
            )
    return rows


def _equity_after_yearly_tax(yearly: list[dict[str, Any]], rate: float) -> dict[str, Any]:
    equity = START_CAPITAL_EUR
    rows: list[dict[str, Any]] = []
    total_tax = 0.0
    for item in yearly:
        pnl = float(item["realized_net_pnl_eur_before_tax_reserve"])
        before_tax = equity + pnl
        tax = max(pnl, 0.0) * rate
        equity = before_tax - tax
        total_tax += tax
        rows.append(
            {
                "year": item["year"],
                "equity_before_year_tax_payment_eur": before_tax,
                "tax_reserved_or_withdrawn_eur": tax,
                "equity_after_year_tax_payment_eur": equity,
            }
        )
    return {
        "reserve_rate": rate,
        "ending_equity_after_yearly_tax_reserve": equity,
        "total_tax_reserved_or_withdrawn": total_tax,
        "yearly_rows": rows,
    }


def build_germany_tax_reserve_report(config: TaxReserveConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    if not config.source_trades_csv.exists():
        summary = {"court_name": COURT_NAME, "blocked": True, "missing_source": str(config.source_trades_csv), **SAFETY_FLAGS}
        _write_json(config.output_root / "germany_crypto_tax_reserve_summary.json", summary)
        return summary

    trades = _load_trades(config.source_trades_csv)
    yearly = _yearly_realized(trades)
    tax_rows = _tax_scenarios(yearly)
    gross_profit = sum(float(row["realized_net_pnl_eur_before_tax_reserve"]) for row in yearly)
    gross_ending = START_CAPITAL_EUR + gross_profit
    reserve_plans = {name: _equity_after_yearly_tax(yearly, rate) for name, rate in SCENARIOS.items()}
    conservative_key = "reserve_47_475pct_rich_tax_plus_soli_on_tax"
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "source_trades_csv": str(config.source_trades_csv),
        "personal_context_used": {
            "country": "Germany",
            "tax_residency_assumption": "German tax resident",
            "age": 43,
            "married": True,
            "children": True,
            "full_time_job": True,
            "modeling_assumption": "crypto gains are additional income on top of employment income; exact household tax requires Steuerberater and full taxable income.",
        },
        "important_tax_assumptions": {
            "withdrawal_is_not_the_only_tax_event": True,
            "yearly_realized_trade_profit_may_be_taxable_even_if_left_on_exchange": True,
            "active_frequent_trading_assumed_short_holding_period": True,
            "social_insurance_not_modeled": True,
            "church_tax_not_modeled": True,
            "commercial_trading_classification_not_modeled": True,
        },
        "gross_research_path_before_tax_reserve": {
            "starting_equity": START_CAPITAL_EUR,
            "ending_equity": gross_ending,
            "net_profit": gross_profit,
        },
        "yearly_realized_pnl": yearly,
        "tax_reserve_scenarios": {name: {k: v for k, v in plan.items() if k != "yearly_rows"} for name, plan in reserve_plans.items()},
        "recommended_planning_case": conservative_key,
        "recommended_planning_case_summary": {k: v for k, v in reserve_plans[conservative_key].items() if k != "yearly_rows"},
        **SAFETY_FLAGS,
        "files_created": [
            str(config.output_root / "germany_crypto_tax_reserve_summary.json"),
            str(config.output_root / "germany_crypto_yearly_realized_pnl.csv"),
            str(config.output_root / "germany_crypto_tax_reserve_scenarios.csv"),
            str(config.output_root / "germany_crypto_tax_reserve_report.md"),
        ],
    }
    _write_csv(config.output_root / "germany_crypto_yearly_realized_pnl.csv", yearly)
    _write_csv(config.output_root / "germany_crypto_tax_reserve_scenarios.csv", tax_rows)
    _write_json(config.output_root / "germany_crypto_tax_reserve_summary.json", summary)
    (config.output_root / "germany_crypto_tax_reserve_report.md").write_text(_report(summary), encoding="utf-8")
    return _round_payload(summary)


def _eur(value: Any) -> str:
    return f"€{float(value):,.2f}"


def _pct(value: Any) -> str:
    return f"{float(value) * 100:.3f}%"


def _report(summary: dict[str, Any]) -> str:
    lines = [
        "# Germany Crypto Tax Reserve Planning",
        "",
        f"- Court: `{summary['court_name']}`",
        f"- Tax advice: `{str(summary['tax_advice']).lower()}`",
        f"- Requires Steuerberater review: `{str(summary['requires_steuerberater_review']).lower()}`",
        "",
        "## Gross research path before tax reserve",
        "",
        f"- Starting equity: `{_eur(summary['gross_research_path_before_tax_reserve']['starting_equity'])}`",
        f"- Ending equity: `{_eur(summary['gross_research_path_before_tax_reserve']['ending_equity'])}`",
        f"- Net profit: `{_eur(summary['gross_research_path_before_tax_reserve']['net_profit'])}`",
        "",
        "## Conservative planning case",
        "",
        f"- Scenario: `{summary['recommended_planning_case']}`",
        f"- Reserve rate: `{_pct(summary['recommended_planning_case_summary']['reserve_rate'])}`",
        f"- Total tax reserve: `{_eur(summary['recommended_planning_case_summary']['total_tax_reserved_or_withdrawn'])}`",
        f"- Ending equity after yearly reserves: `{_eur(summary['recommended_planning_case_summary']['ending_equity_after_yearly_tax_reserve'])}`",
        "",
        "## Notes",
        "",
        "- This is not tax advice.",
        "- German tax is calculated on total household taxable income, not Binance income in isolation.",
        "- The report treats yearly realized trading profit as needing a yearly reserve even if funds stay on exchange.",
        "- Church tax, exact salary, spouse income, deductions, child allowances, and commercial-trading classification are not modeled.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()
    config = default_config()
    if args.output_root:
        config = TaxReserveConfig(
            project_root=config.project_root,
            package_root=config.package_root,
            source_trades_csv=config.source_trades_csv,
            output_root=Path(args.output_root).expanduser().resolve(),
        )
    print(json.dumps(build_germany_tax_reserve_report(config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
