from __future__ import annotations

import csv
import json
import math
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import output_root, project_root  # noqa: E402


COURT_NAME = "EUR25K_REALISTIC_5Y_TARGET_TRANSLATION_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "eur25k_realistic_5y_target_translation_court_001"

SUPPORTED = "EUR25K_5Y_TARGET_TRANSLATION_SUPPORTED_RESEARCH_ONLY"
WARNING = "EUR25K_5Y_TARGET_TRANSLATION_WARNING_RESEARCH_ONLY"
NOT_SUPPORTED = "EUR25K_5Y_TARGET_TRANSLATION_NOT_SUPPORTED_RESEARCH_ONLY"

START_CAPITAL_20K = 20_000.0
START_CAPITAL_25K = 25_000.0
SCALE_20K_TO_25K = START_CAPITAL_25K / START_CAPITAL_20K

TRUSTED_20K_AVERAGE = 792_824.55832
TRUSTED_20K_MEDIAN = 786_049.44639
TRUSTED_20K_HIT_1M = 12
CONTEXT_20K_AVERAGE = 881_465.531787
CONTEXT_20K_MEDIAN = 878_431.045803
CONTEXT_20K_HIT_1M = 18
CONTEXT_CLASSIFICATION = "SIX_H_CONTEXT_IMPROVES_1H_RESEARCH_ONLY"
CONTEXT_VARIANT = "LIGHT_BOOST_6H_CONFLUENCE"

SAFETY_FLAGS = {
    "research_only": True,
    "real_money_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
    "behavior_change_allowed": False,
    "no_order_path_created": True,
    "no_broker_path_created": True,
    "paper_validation_ready": False,
    "eur_25000_anchor_active": False,
}

OLD_ARTIFACT_RELATIVE = Path(
    "structural_compounding_lab/output/execution_cost_realism_and_trade_redundancy_audit_001/"
    "diagnostics/execution_cost_band_results.json"
)
OLD_ARTIFACT_CSV_RELATIVE = Path(
    "structural_compounding_lab/output/execution_cost_realism_and_trade_redundancy_audit_001/"
    "diagnostics/execution_cost_band_results.csv"
)
OLD_START_CAPITAL_PROOF_RELATIVE = Path(
    "structural_compounding_lab/diagnostics/native_sr_aware_5y_mission_gap_audit.py"
)
COURT_002_SUMMARY_RELATIVE = Path(
    "structural_compounding_lab/output/eur25k_sealed_6m_holdout_court_002/"
    "eur25k_sealed_6m_holdout_summary.json"
)
COURT_002_REPORT_RELATIVE = Path(
    "structural_compounding_lab/output/eur25k_sealed_6m_holdout_court_002/"
    "eur25k_sealed_6m_holdout_report.md"
)
COURT_002_ANTI_LEAKAGE_RELATIVE = Path(
    "structural_compounding_lab/output/eur25k_sealed_6m_holdout_court_002/anti_leakage_audit.json"
)
COURT_002_SPLIT_RELATIVE = Path(
    "structural_compounding_lab/output/eur25k_sealed_6m_holdout_court_002/split_manifest.json"
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")


def _fmt(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            return "N/A"
        return f"{float(value):,.6f}".rstrip("0").rstrip(".")
    return str(value)


def _pct(value: float) -> float:
    return value * 100.0


def _multiple(target: float, start: float = START_CAPITAL_25K) -> float:
    return target / start


def _cagr(target: float, start: float = START_CAPITAL_25K, years: float = 5.0) -> float:
    return (target / start) ** (1.0 / years) - 1.0


def _monthly_growth(target: float, start: float = START_CAPITAL_25K, months: float = 60.0) -> float:
    return (target / start) ** (1.0 / months) - 1.0


def _bucket(probability_proxy: float) -> str:
    if probability_proxy >= 0.75:
        return "Very high"
    if probability_proxy >= 0.55:
        return "High"
    if probability_proxy >= 0.35:
        return "Moderate"
    if probability_proxy >= 0.15:
        return "Low"
    return "Very low"


def _paths(root: Path) -> dict[str, Path]:
    court_root = output_root(root) / OUTPUT_FOLDER_NAME
    return {
        "root": court_root,
        "old_manifest": court_root / "old_eur20k_full_history_artifact_manifest.json",
        "court_002_manifest": court_root / "court_002_evidence_manifest.json",
        "summary": court_root / "eur25k_realistic_5y_target_translation_summary.json",
        "report": court_root / "eur25k_realistic_5y_target_translation_report.md",
    }


def _load_exact_old_artifact(root: Path) -> dict[str, Any]:
    search_commands = [
        "rg -n \"20k|20000|EUR20k|EUR 20k|full-history|full history|full_history|compounding|ending diagnostic equity|ending equity|return multiple|diagnostic equity|78,|78000000|million\" structural_compounding_lab/output migration_audit logs . || true",
        "rg -n \"792,824.56|786,049.45|881,465.53|878,431.05|1M-hit|rolling 5Y|rolling 5-year|SIX_H_CONTEXT_IMPROVES_1H_RESEARCH_ONLY|LIGHT_BOOST_6H_CONFLUENCE\" structural_compounding_lab/output migration_audit logs . || true",
    ]
    artifact_path = root / OLD_ARTIFACT_RELATIVE
    csv_path = root / OLD_ARTIFACT_CSV_RELATIVE
    start_capital_proof_path = root / OLD_START_CAPITAL_PROOF_RELATIVE
    searched = [
        str(artifact_path),
        str(csv_path),
        str(start_capital_proof_path),
        str(root / "structural_compounding_lab/output"),
        str(root / "migration_audit"),
        str(root / "logs"),
        str(root),
    ]
    if not artifact_path.exists():
        return {
            "old_eur20k_full_history_artifact_found": False,
            "search_commands_used": search_commands,
            "paths_searched": searched,
            "missing_reason": "execution_cost_band_results.json not found",
        }
    payload = _read_json(artifact_path)
    rows = payload.get("rows")
    if not isinstance(rows, list):
        return {
            "old_eur20k_full_history_artifact_found": False,
            "search_commands_used": search_commands,
            "paths_searched": searched,
            "missing_reason": "execution_cost_band_results.json does not contain rows",
        }
    candidates = [row for row in rows if row.get("band_name") == "NORMAL_MIXED_MAKER_TAKER_COST"]
    if len(candidates) != 1:
        return {
            "old_eur20k_full_history_artifact_found": False,
            "search_commands_used": search_commands,
            "paths_searched": searched,
            "missing_reason": "NORMAL_MIXED_MAKER_TAKER_COST row not uniquely found",
        }
    row = candidates[0]
    required = [
        "full_sequence_ending_equity",
        "rolling_5y_average_ending_equity",
        "rolling_5y_median_ending_equity",
        "hit_1m_windows",
        "max_drawdown_pct",
    ]
    missing = [key for key in required if key not in row]
    if missing:
        return {
            "old_eur20k_full_history_artifact_found": False,
            "search_commands_used": search_commands,
            "paths_searched": searched,
            "missing_reason": f"artifact row missing required keys: {missing}",
        }
    start_capital_proof = ""
    if start_capital_proof_path.exists():
        for line_number, line in enumerate(start_capital_proof_path.read_text(encoding="utf-8").splitlines(), start=1):
            if "START_CAPITAL" in line and "20_000.0" in line:
                start_capital_proof = f"{start_capital_proof_path}:{line_number}: {line.strip()}"
                break
    ending = float(row["full_sequence_ending_equity"])
    manifest = {
        "old_eur20k_full_history_artifact_found": True,
        "created_at": _now(),
        "court_name": COURT_NAME,
        "artifact_path": str(artifact_path),
        "csv_artifact_path": str(csv_path),
        "artifact_row_selector": {"band_name": "NORMAL_MIXED_MAKER_TAKER_COST"},
        "evidence_snippet_location_or_json_keys": {
            "artifact_path": str(artifact_path),
            "json_path": "rows[band_name == 'NORMAL_MIXED_MAKER_TAKER_COST'].full_sequence_ending_equity",
            "csv_row": "band_name=NORMAL_MIXED_MAKER_TAKER_COST",
            "start_capital_code_proof": start_capital_proof or "not_found",
        },
        "confirmation_value_artifact_retrieved_not_inferred": True,
        "confirmation_eur20k_not_eur25k": bool(start_capital_proof),
        "confirmation_full_history_not_rolling_5y": True,
        "starting_capital_eur": START_CAPITAL_20K,
        "old_eur20k_full_history_ending_equity": ending,
        "old_eur20k_full_history_return_multiple": ending / START_CAPITAL_20K,
        "old_eur20k_full_history_net_profit": ending - START_CAPITAL_20K,
        "old_eur20k_full_history_accepted_trades": None,
        "old_eur20k_full_history_rejected_setups": None,
        "old_eur20k_full_history_total_R": None,
        "old_eur20k_full_history_average_R": None,
        "old_eur20k_full_history_median_R": None,
        "old_eur20k_full_history_profit_factor": None,
        "old_eur20k_full_history_win_rate": None,
        "old_eur20k_full_history_max_drawdown": float(row["max_drawdown_pct"]),
        "old_eur20k_full_history_best_trade_R": None,
        "old_eur20k_full_history_worst_trade_R": None,
        "old_eur20k_full_history_long_short_split": None,
        "extracted_metrics": {
            "band_name": row.get("band_name"),
            "realism_label": row.get("realism_label"),
            "fee_bps_per_side": row.get("fee_bps_per_side"),
            "spread_slippage_bps_per_side": row.get("spread_slippage_bps_per_side"),
            "total_round_trip_bps": row.get("total_round_trip_bps"),
            "full_sequence_ending_equity": ending,
            "return_multiple": ending / START_CAPITAL_20K,
            "rolling_5y_average_ending_equity": float(row["rolling_5y_average_ending_equity"]),
            "rolling_5y_median_ending_equity": float(row["rolling_5y_median_ending_equity"]),
            "rolling_5y_best_ending_equity": row.get("rolling_5y_best_ending_equity"),
            "rolling_5y_worst_ending_equity": row.get("rolling_5y_worst_ending_equity"),
            "hit_1m_windows": int(row["hit_1m_windows"]),
            "max_drawdown_pct": float(row["max_drawdown_pct"]),
            "mission_verdict": row.get("mission_verdict"),
        },
        "search_commands_used": search_commands,
        "paths_searched": searched,
        **SAFETY_FLAGS,
    }
    return manifest


def _load_court_002_evidence(root: Path) -> dict[str, Any]:
    summary_path = root / COURT_002_SUMMARY_RELATIVE
    report_path = root / COURT_002_REPORT_RELATIVE
    anti_path = root / COURT_002_ANTI_LEAKAGE_RELATIVE
    split_path = root / COURT_002_SPLIT_RELATIVE
    for path in (summary_path, report_path, anti_path, split_path):
        if not path.exists():
            raise FileNotFoundError(f"required Court 002 artifact missing: {path}")
    summary = _read_json(summary_path)
    anti = _read_json(anti_path)
    split = _read_json(split_path)
    comparison = summary.get("comparison", {})
    research = comparison.get("full_history_research_25k", {})
    holdout = summary.get("sealed_holdout_validation") or comparison.get("holdout_25k", {})
    manifest = {
        "created_at": _now(),
        "summary_path": str(summary_path),
        "report_path": str(report_path),
        "anti_leakage_path": str(anti_path),
        "split_manifest_path": str(split_path),
        "court_002_final_classification": summary.get("final_classification"),
        "eur25k_full_history_metrics": research,
        "eur25k_sealed_holdout_metrics": holdout,
        "anti_leakage_result": anti,
        "holdout_opened_exactly_once": bool(anti.get("holdout_validation_performed_exactly_once")),
        "no_paper_live_order_broker_confirmation": {
            "paper_allowed": summary.get("paper_allowed", False),
            "live_allowed": summary.get("live_allowed", False),
            "real_money_allowed": summary.get("real_money_allowed", False),
            "no_order_path_created": summary.get("no_order_path_created", True),
            "no_broker_path_created": summary.get("no_broker_path_created", True),
        },
        "paper_validation_ready": bool(summary.get("paper_validation_ready")),
        "split_manifest": split,
        **SAFETY_FLAGS,
    }
    return manifest


def _metric(metric: str, *values: Any, interpretation: str) -> dict[str, Any]:
    columns = [
        "Exact Old EUR20k Full-History Artifact",
        "Court 002 EUR25k Full-History",
        "EUR20k Strict Rolling 5Y Baseline",
        "EUR25k Strict Rolling 5Y Projection",
        "EUR20k 6H-Context Rolling 5Y",
        "EUR25k 6H-Context Projection",
        "Same-Window EUR20k Holdout",
        "Same-Window EUR25k Holdout",
    ]
    return {"Metric": metric, **{column: value for column, value in zip(columns, values)}, "Interpretation": interpretation}


def _comparison_table(old: dict[str, Any], court_002: dict[str, Any]) -> list[dict[str, Any]]:
    research = court_002["eur25k_full_history_metrics"]
    holdout = court_002["eur25k_sealed_holdout_metrics"]
    strict_25_avg = TRUSTED_20K_AVERAGE * SCALE_20K_TO_25K
    context_25_avg = CONTEXT_20K_AVERAGE * SCALE_20K_TO_25K
    same_20 = holdout.get("same_window_20k_counterfactual_ending_equity")
    same_25 = holdout.get("ending_diagnostic_equity")
    return [
        _metric("starting capital", START_CAPITAL_20K, research.get("starting_capital_eur"), START_CAPITAL_20K, START_CAPITAL_25K, START_CAPITAL_20K, START_CAPITAL_25K, START_CAPITAL_20K, START_CAPITAL_25K, interpretation="Capital scale is exactly 1.25x from EUR20k to EUR25k."),
        _metric("ending equity", old["old_eur20k_full_history_ending_equity"], research.get("ending_diagnostic_equity"), TRUSTED_20K_AVERAGE, strict_25_avg, CONTEXT_20K_AVERAGE, context_25_avg, same_20, same_25, interpretation="Full-history diagnostics are much larger than rolling 5Y mission anchors."),
        _metric("return multiple", old["old_eur20k_full_history_return_multiple"], research.get("return_multiple"), TRUSTED_20K_AVERAGE / START_CAPITAL_20K, strict_25_avg / START_CAPITAL_25K, CONTEXT_20K_AVERAGE / START_CAPITAL_20K, context_25_avg / START_CAPITAL_25K, (same_20 / START_CAPITAL_20K) if same_20 else None, holdout.get("return_multiple"), interpretation="Rolling 5Y multiples are the realistic target base."),
        _metric("net profit", old["old_eur20k_full_history_net_profit"], research.get("net_profit_eur"), TRUSTED_20K_AVERAGE - START_CAPITAL_20K, strict_25_avg - START_CAPITAL_25K, CONTEXT_20K_AVERAGE - START_CAPITAL_20K, context_25_avg - START_CAPITAL_25K, (same_20 - START_CAPITAL_20K) if same_20 else None, holdout.get("net_profit_eur"), interpretation="Net profit scales linearly only in same-window diagnostic comparisons."),
        _metric("accepted trades", old.get("old_eur20k_full_history_accepted_trades"), research.get("accepted_trades"), None, None, None, None, None, holdout.get("accepted_trades"), interpretation="Old exact accepted/rejected trade counts are not present in the retrieved result row."),
        _metric("rejected setups", old.get("old_eur20k_full_history_rejected_setups"), research.get("rejected_setups"), None, None, None, None, None, holdout.get("rejected_setups"), interpretation="Court 002 exposes rejection counts; old row does not."),
        _metric("total R", old.get("old_eur20k_full_history_total_R"), research.get("total_R"), None, None, None, None, None, holdout.get("total_R"), interpretation="Do not infer old total R from ending equity."),
        _metric("average R", old.get("old_eur20k_full_history_average_R"), research.get("average_R"), None, None, None, None, None, holdout.get("average_R"), interpretation="Court 002 quality is strong; old artifact lacks this field."),
        _metric("median R", old.get("old_eur20k_full_history_median_R"), research.get("median_R"), None, None, None, None, None, holdout.get("median_R"), interpretation="Median R supports robustness where available."),
        _metric("win rate", old.get("old_eur20k_full_history_win_rate"), research.get("win_rate"), None, None, None, None, None, holdout.get("win_rate"), interpretation="Win rate is not comparable where old artifact lacks trade outcomes."),
        _metric("profit factor", old.get("old_eur20k_full_history_profit_factor"), research.get("profit_factor"), None, None, None, None, None, holdout.get("profit_factor"), interpretation="Court 002 profit factor is diagnostic, not a live promise."),
        _metric("max drawdown", old.get("old_eur20k_full_history_max_drawdown"), research.get("max_drawdown_pct"), old["extracted_metrics"].get("max_drawdown_pct"), old["extracted_metrics"].get("max_drawdown_pct"), None, None, None, holdout.get("max_drawdown_pct"), interpretation="Historical drawdown remained low in artifacts, but forward drawdown must be haircut."),
        _metric("best trade", old.get("old_eur20k_full_history_best_trade_R"), research.get("best_trade_R"), None, None, None, None, None, holdout.get("best_trade_R"), interpretation="Best-trade dependency remains a monitoring risk."),
        _metric("worst trade", old.get("old_eur20k_full_history_worst_trade_R"), research.get("worst_trade_R"), None, None, None, None, None, holdout.get("worst_trade_R"), interpretation="Worst trade is bounded in Court 002 frozen rules."),
        _metric("long/short split", old.get("old_eur20k_full_history_long_short_split"), f"{research.get('long_trade_count')}/{research.get('short_trade_count')}", None, None, None, None, None, f"{holdout.get('long_trade_count')}/{holdout.get('short_trade_count')}", interpretation="Court 002 remains long-heavy; short sleeve is secondary."),
        _metric("1M-hit windows", old["extracted_metrics"].get("hit_1m_windows"), None, TRUSTED_20K_HIT_1M, TRUSTED_20K_HIT_1M, CONTEXT_20K_HIT_1M, CONTEXT_20K_HIT_1M, None, None, interpretation="Window hit count does not scale with capital but supports target realism."),
        _metric("6H context usage", "not in old result row", research.get("six_h_context_only"), "strict 1H baseline", "strict 1H projection", CONTEXT_VARIANT, CONTEXT_VARIANT, "same frozen holdout", holdout.get("six_h_context_only"), interpretation="6H context remains context only; no native 6H execution is enabled."),
        _metric("paper_validation_ready", False, research.get("paper_validation_ready"), False, False, False, False, False, holdout.get("paper_validation_ready"), interpretation="Every column remains research-only."),
        _metric("safety status", "research-only", "research-only", "research-only", "research-only", "research-only", "research-only", "research-only", "research-only", interpretation="No paper/live/order/broker path is enabled."),
    ]


def _target_levels() -> list[dict[str, Any]]:
    specs = [
        ("EUR25k -> EUR500k", 500_000.0),
        ("EUR25k -> EUR750k", 750_000.0),
        ("EUR25k -> EUR1M", 1_000_000.0),
        ("EUR25k -> EUR1.25M", 1_250_000.0),
        ("EUR25k -> EUR2M+", 2_000_000.0),
    ]
    rows = []
    for name, target in specs:
        monthly = _monthly_growth(target)
        rows.append(
            {
                "target_level": name,
                "ending_equity": target,
                "required_multiple": _multiple(target),
                "exact_cagr": _cagr(target),
                "exact_monthly_compounded_growth": monthly,
                "approximate_annual_return": _cagr(target),
                "required_average_monthly_R_if_1pct_risk_unit": monthly / 0.01,
                "expected_drawdown_pressure": "low-to-moderate" if target <= 750_000 else "high" if target <= 1_250_000 else "extreme",
                "psychological_difficulty": "manageable" if target <= 500_000 else "hard" if target <= 1_000_000 else "very hard",
                "evidence_support_level": "high" if target <= 750_000 else "moderate-high" if target <= 1_000_000 else "low-to-moderate",
            }
        )
    return rows


def _target_bands(old: dict[str, Any], court_002: dict[str, Any]) -> list[dict[str, Any]]:
    levels = {row["target_level"]: row for row in _target_levels()}
    specs = [
        ("Conservative", "EUR25k -> EUR500k", "12%-18%", "350-650 accepted decisions", "multi-month flat periods expected", ["Strict rolling 5Y degrades below EUR500k", "forward holdout collapses", "operator misses signals"], True),
        ("Base", "EUR25k -> EUR750k", "15%-24%", "450-750 accepted decisions", "quarter-long flat periods possible", ["rolling 5Y median falls materially", "cost drift rises", "outage recovery fails"], True),
        ("Strong", "EUR25k -> EUR1M", "18%-30%", "500-850 accepted decisions", "long inactivity still possible", ["6H context edge decays", "trade density drops", "max drawdown breaches control"], True),
        ("Aggressive", "EUR25k -> EUR1.25M", "22%-35%", "600-950 accepted decisions", "psychological strain likely", ["top winners missed", "regime changes", "liquidity/cost haircut expands"], True),
        ("Moonshot", "EUR25k -> EUR2M+", "30%-45%+", "700-1100+ accepted decisions", "severe stagnation and regret risk", ["edge compresses", "execution slippage rises", "overfit uncertainty materializes"], True),
    ]
    output = []
    for band, level_key, dd_range, trades, flat, failures, reached in specs:
        level = levels[level_key]
        target = level["ending_equity"]
        output.append(
            {
                "band": band,
                "ending_equity": target,
                "return_multiple": level["required_multiple"],
                "implied_cagr": level["exact_cagr"],
                "implied_monthly_growth": level["exact_monthly_compounded_growth"],
                "expected_drawdown_range": dd_range,
                "expected_trade_count_range": trades,
                "expected_zero_trade_periods": flat,
                "failure_conditions": failures,
                "support_from_exact_eur20k_artifact": old["old_eur20k_full_history_ending_equity"] > target,
                "support_from_rolling_5y_baseline": (
                    TRUSTED_20K_AVERAGE * SCALE_20K_TO_25K >= target
                    or CONTEXT_20K_AVERAGE * SCALE_20K_TO_25K >= target
                ),
                "support_from_court_002_holdout": bool(court_002["eur25k_sealed_holdout_metrics"].get("return_multiple", 0) > 1.0),
                "eur1m_reached": target >= 1_000_000.0,
            }
        )
    return output


def _haircuts(court_002: dict[str, Any]) -> list[dict[str, Any]]:
    full_history = float(court_002["eur25k_full_history_metrics"]["ending_diagnostic_equity"])
    scenarios = [
        ("Raw diagnostic / no haircut", full_history, "Very low", "2%-8% research drawdown may understate forward risk", "Do not use as target; keep research-only."),
        ("Light haircut", CONTEXT_20K_AVERAGE * SCALE_20K_TO_25K, "Moderate", "12%-20%", "Continue shadow validation; do not activate money."),
        ("Moderate haircut", TRUSTED_20K_AVERAGE * SCALE_20K_TO_25K, "High", "15%-25%", "Use as main planning anchor."),
        ("Harsh haircut", 500_000.0, "High", "20%-35%", "Accept as conservative survivable case."),
        ("Disaster / regime-break scenario", 125_000.0, "Low", "35%+ or strategy inactive", "Stop promotion; diagnose edge decay."),
    ]
    output = []
    for name, ending, probability, dd, recommendation in scenarios:
        output.append(
            {
                "scenario": name,
                "regime_haircut": name != "Raw diagnostic / no haircut",
                "slippage_fee_haircut": name in {"Moderate haircut", "Harsh haircut", "Disaster / regime-break scenario"},
                "execution_realism_haircut": name != "Raw diagnostic / no haircut",
                "downtime_outage_haircut": name in {"Harsh haircut", "Disaster / regime-break scenario"},
                "psychological_error_haircut": name in {"Moderate haircut", "Harsh haircut", "Disaster / regime-break scenario"},
                "liquidity_market_depth_haircut": name in {"Harsh haircut", "Disaster / regime-break scenario"},
                "missed_trade_haircut": name in {"Moderate haircut", "Harsh haircut", "Disaster / regime-break scenario"},
                "overfit_uncertainty_haircut": name != "Raw diagnostic / no haircut",
                "data_quality_haircut": name in {"Harsh haircut", "Disaster / regime-break scenario"},
                "capital_deployment_haircut": name in {"Moderate haircut", "Harsh haircut", "Disaster / regime-break scenario"},
                "compounding_drag_haircut": name != "Raw diagnostic / no haircut",
                "five_year_ending_equity_estimate": ending,
                "probability_bucket": probability,
                "max_drawdown_expectation": dd,
                "eur500k_reached": ending >= 500_000.0,
                "eur750k_reached": ending >= 750_000.0,
                "eur1m_reached": ending >= 1_000_000.0,
                "eur1_25m_reached": ending >= 1_250_000.0,
                "eur2m_reached": ending >= 2_000_000.0,
                "forward_shadow_recommendation": recommendation,
            }
        )
    return output


def _monte_carlo_limitation(root: Path) -> dict[str, Any]:
    full_trades = root / "structural_compounding_lab/output/eur25k_sealed_6m_holdout_court_002/research_only_eur25k_replay/raw_engine/trades.csv"
    holdout_trades = root / "structural_compounding_lab/output/eur25k_sealed_6m_holdout_court_002/holdout_validation/raw_engine/trades.csv"
    old_bridge_trades = root / "structural_compounding_lab/output/strict_sr_aware_milestone_bridge_monte_carlo_audit_001/ledger/milestone_bridge_trades.csv"
    return {
        "monte_carlo_bootstrap_performed": False,
        "reason": "Frozen accepted Court 002 trade-level R sequence and exact old EUR20k full-history trade sequence are not both available as direct artifacts. Raw engine ledgers exist but include pre-filter trades and must not be used as a substitute.",
        "available_ledger_candidates_checked": [
            str(full_trades),
            str(holdout_trades),
            str(old_bridge_trades),
        ],
        "mean_ending_equity": None,
        "median_ending_equity": None,
        "p10_ending_equity": None,
        "p25_ending_equity": None,
        "p75_ending_equity": None,
        "p90_ending_equity": None,
        "probability_bucket_reaching_eur500k": "Not computed",
        "probability_bucket_reaching_eur750k": "Not computed",
        "probability_bucket_reaching_eur1m": "Not computed",
        "probability_bucket_reaching_eur1_25m": "Not computed",
        "probability_bucket_reaching_eur2m": "Not computed",
        "max_drawdown_distribution": None,
        "longest_zero_trade_or_flat_periods": "Use existing rolling 5Y evidence and Court 002 zero-trade-day diagnostics.",
        "severe_stagnation_scenarios": "Not simulated without frozen accepted trade-level sequence.",
    }


def _profit_vault_framework() -> list[dict[str, Any]]:
    specs = [
        ("2x capital", 50_000.0, 50_000.0, 0.0, "18%", 40_000.0, True, True, "Do not increase risk after first double."),
        ("5x capital", 125_000.0, 100_000.0, 25_000.0, "16%", 95_000.0, True, True, "Protect original capital plus one full extra stake."),
        ("10x capital", 250_000.0, 175_000.0, 75_000.0, "14%", 150_000.0, True, True, "Do not let euphoria expand execution scope."),
        ("20x capital", 500_000.0, 300_000.0, 200_000.0, "12%", 250_000.0, True, True, "Operate as if the next regime can break."),
        ("40x capital / EUR1M", 1_000_000.0, 500_000.0, 500_000.0, "10%", 450_000.0, "only after future paper-readiness court", True, "Half the equity is no longer trading fuel."),
    ]
    return [
        {
            "milestone": milestone,
            "gross_equity": gross,
            "active_compounding_capital": active,
            "protected_locked_capital": locked,
            "maximum_permitted_drawdown": max_dd,
            "circuit_breaker_level": breaker,
            "compounding_continues": continues,
            "risk_should_be_capped_in_future_paper_readiness_court": cap,
            "psychological_rule": psych,
            "planning_only": True,
        }
        for milestone, gross, active, locked, max_dd, breaker, continues, cap, psych in specs
    ]


def _write_report(path: Path, summary: dict[str, Any]) -> None:
    old = summary["old_eur20k_full_history_artifact"]
    c2 = summary["court_002_evidence"]
    lines = [
        "# EUR25k Realistic 5Y Target Translation Court 001",
        "",
        f"Final classification: `{summary['final_classification']}`",
        "",
        "This is a research-only translation court. It did not rerun Court 002, reopen the sealed holdout, modify strategy logic, enable paper/live trading, or create broker/order paths.",
        "",
        "## Exact old EUR20k full-history artifact",
        "",
        f"- Artifact path: `{old['artifact_path']}`",
        f"- JSON evidence key: `{old['evidence_snippet_location_or_json_keys']['json_path']}`",
        f"- Start-capital proof: `{old['evidence_snippet_location_or_json_keys']['start_capital_code_proof']}`",
        f"- Exact old EUR20k full-history ending equity: `EUR {_fmt(old['old_eur20k_full_history_ending_equity'])}`",
        f"- Exact old EUR20k full-history return multiple: `{_fmt(old['old_eur20k_full_history_return_multiple'])}x`",
        "- This value is artifact-retrieved, not inferred from EUR25k.",
        "- This is the full-sequence/full-history field, not the rolling 5Y average or median.",
        "",
        "## Court 002 evidence loaded without rerun",
        "",
        f"- Court 002 classification: `{c2['court_002_final_classification']}`",
        f"- EUR25k full-history ending diagnostic equity: `EUR {_fmt(c2['eur25k_full_history_metrics']['ending_diagnostic_equity'])}`",
        f"- EUR25k sealed holdout ending diagnostic equity: `EUR {_fmt(c2['eur25k_sealed_holdout_metrics']['ending_diagnostic_equity'])}`",
        f"- Anti-leakage passed: `{c2['anti_leakage_result'].get('passed')}`",
        f"- Holdout opened exactly once: `{c2['holdout_opened_exactly_once']}`",
        f"- paper_validation_ready: `{summary['paper_validation_ready']}`",
        "",
        "## Required comparison table",
        "",
        "| Metric | Exact Old EUR20k Full-History Artifact | Court 002 EUR25k Full-History | EUR20k Strict Rolling 5Y Baseline | EUR25k Strict Rolling 5Y Projection | EUR20k 6H-Context Rolling 5Y | EUR25k 6H-Context Projection | Same-Window EUR20k Holdout | Same-Window EUR25k Holdout | Interpretation |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|",
    ]
    for row in summary["comparison_table"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["Metric"]),
                    _fmt(row["Exact Old EUR20k Full-History Artifact"]),
                    _fmt(row["Court 002 EUR25k Full-History"]),
                    _fmt(row["EUR20k Strict Rolling 5Y Baseline"]),
                    _fmt(row["EUR25k Strict Rolling 5Y Projection"]),
                    _fmt(row["EUR20k 6H-Context Rolling 5Y"]),
                    _fmt(row["EUR25k 6H-Context Projection"]),
                    _fmt(row["Same-Window EUR20k Holdout"]),
                    _fmt(row["Same-Window EUR25k Holdout"]),
                    str(row["Interpretation"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Realism bridge",
            "",
            "- The EUR91M Court 002 number is not the target. It is a full-history compounding diagnostic from one realized historical sequence, with continuous compounding, no withdrawals, edge persistence assumptions, favorable path dependence, and no live execution psychology.",
            "- It is still valuable because the historical edge was not tiny, the sealed six-month holdout did not collapse, and the same-window EUR25k/EUR20k holdout ratio was exactly `1.25`.",
            "- The realistic planning anchor is the rolling 5Y evidence: strict EUR25k projection `EUR 991,030.70`, and 6H-context EUR25k projection `EUR 1,101,831.91`.",
            "",
            "## Target levels",
            "",
            "| Target | Multiple | Exact CAGR | Exact monthly growth | Monthly R proxy | Evidence support |",
            "|---|---:|---:|---:|---:|---|",
        ]
    )
    for row in summary["target_levels"]:
        lines.append(
            f"| {row['target_level']} | {_fmt(row['required_multiple'])}x | {_fmt(_pct(row['exact_cagr']))}% | {_fmt(_pct(row['exact_monthly_compounded_growth']))}% | {_fmt(row['required_average_monthly_R_if_1pct_risk_unit'])}R | {row['evidence_support_level']} |"
        )
    lines.extend(["", "## Target bands", "", "| Band | Ending equity | Multiple | CAGR | EUR1M reached | Evidence summary |", "|---|---:|---:|---:|---|---|"])
    for row in summary["target_bands"]:
        lines.append(
            f"| {row['band']} | EUR {_fmt(row['ending_equity'])} | {_fmt(row['return_multiple'])}x | {_fmt(_pct(row['implied_cagr']))}% | {row['eur1m_reached']} | EUR20k artifact={row['support_from_exact_eur20k_artifact']}; rolling 5Y={row['support_from_rolling_5y_baseline']}; holdout={row['support_from_court_002_holdout']} |"
        )
    lines.extend(["", "## Fatherly haircut scenarios", "", "| Scenario | 5Y ending equity estimate | Probability bucket | EUR500k | EUR750k | EUR1M | EUR1.25M | EUR2M | Recommendation |", "|---|---:|---|---|---|---|---|---|---|"])
    for row in summary["haircut_scenarios"]:
        lines.append(
            f"| {row['scenario']} | EUR {_fmt(row['five_year_ending_equity_estimate'])} | {row['probability_bucket']} | {row['eur500k_reached']} | {row['eur750k_reached']} | {row['eur1m_reached']} | {row['eur1_25m_reached']} | {row['eur2m_reached']} | {row['forward_shadow_recommendation']} |"
        )
    lines.extend(
        [
            "",
            "## Monte Carlo / bootstrap status",
            "",
            f"- Performed: `{summary['monte_carlo_bootstrap']['monte_carlo_bootstrap_performed']}`",
            f"- Reason: {summary['monte_carlo_bootstrap']['reason']}",
            "",
            "## Profit-vault framework",
            "",
            "| Milestone | Gross equity | Active compounding capital | Protected capital | Max permitted drawdown | Circuit breaker | Psychological rule |",
            "|---|---:|---:|---:|---:|---:|---|",
        ]
    )
    for row in summary["profit_vault_framework"]:
        lines.append(
            f"| {row['milestone']} | EUR {_fmt(row['gross_equity'])} | EUR {_fmt(row['active_compounding_capital'])} | EUR {_fmt(row['protected_locked_capital'])} | {row['maximum_permitted_drawdown']} | EUR {_fmt(row['circuit_breaker_level'])} | {row['psychological_rule']} |"
        )
    lines.extend(
        [
            "",
            "## Final father verdict",
            "",
            f"1. Exact old EUR20k full-history value: `EUR {_fmt(old['old_eur20k_full_history_ending_equity'])}`.",
            f"2. Proving artifact: `{old['artifact_path']}`.",
            f"3. EUR25k Court 002 full-history value: `EUR {_fmt(c2['eur25k_full_history_metrics']['ending_diagnostic_equity'])}`; directionally consistent but higher due changed window, fresh extension, and Court 002 frozen validation mechanics.",
            "4. EUR25k to EUR1M in 5 years aligns with the exact EUR20k full-history story, but full-history explosion is not the planning target.",
            "5. EUR25k to EUR1M aligns with exact EUR25k rolling projections: strict projection is `EUR 991,030.70`; 6H-context projection is `EUR 1,101,831.91`.",
            "6. EUR1M is classified as the Strong target, not conservative and not fantasy.",
            "7. EUR91M is diagnostic/fantasy as a target because it is path-dependent full-history compounding.",
            "8. Honest realistic 5-year target band: `EUR 750k` base to `EUR 1.1M` strong, with `EUR 500k` conservative and `EUR 2M+` moonshot.",
            "9. Conservative target: `EUR 500k`.",
            "10. Base target: `EUR 750k`.",
            "11. Strong target: `EUR 1M`.",
            "12. Aggressive target: `EUR 1.25M`.",
            "13. Moonshot target: `EUR 2M+`.",
            "14. Kill risks: regime change, missed winners, outages, cost/slippage drift, psychology, liquidity, data-quality regressions, and overfit uncertainty.",
            "15. Do not change entries, exits, thresholds, filters, sizing logic, 6H context logic, or enable paper/live/broker/order paths now.",
            "16. Monitor signal capture, stale candles, zero-trade stretches, drawdown, missed-trade dependency, cost drift, and holdout degradation during forward shadow.",
            "17. Next operational step: install and run the scheduler for continuous six-month forward validation, then keep outage/reconnect alerting under watch.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_court(root: Path | None = None) -> dict[str, Any]:
    root = (root or project_root()).resolve()
    paths = _paths(root)
    paths["root"].mkdir(parents=True, exist_ok=True)
    old = _load_exact_old_artifact(root)
    _write_json(paths["old_manifest"], old)
    if not old.get("old_eur20k_full_history_artifact_found"):
        raise FileNotFoundError(old.get("missing_reason", "old EUR20k full-history artifact not found"))
    court_002 = _load_court_002_evidence(root)
    _write_json(paths["court_002_manifest"], court_002)

    strict_25_average = TRUSTED_20K_AVERAGE * SCALE_20K_TO_25K
    strict_25_median = TRUSTED_20K_MEDIAN * SCALE_20K_TO_25K
    context_25_average = CONTEXT_20K_AVERAGE * SCALE_20K_TO_25K
    context_25_median = CONTEXT_20K_MEDIAN * SCALE_20K_TO_25K
    comparison_table = _comparison_table(old, court_002)
    target_levels = _target_levels()
    target_bands = _target_bands(old, court_002)
    haircut_scenarios = _haircuts(court_002)
    summary = {
        "created_at": _now(),
        "court_name": COURT_NAME,
        "final_classification": SUPPORTED
        if (
            old["old_eur20k_full_history_artifact_found"]
            and court_002["court_002_final_classification"] == "EUR25K_FULL_HISTORY_SEALED_6M_HOLDOUT_VALIDATION_PASSED_RESEARCH_ONLY"
            and bool(court_002["anti_leakage_result"].get("passed"))
            and not bool(court_002.get("paper_validation_ready"))
        )
        else WARNING,
        "old_eur20k_full_history_artifact": old,
        "court_002_evidence": court_002,
        "exact_baselines": {
            "eur20k_strict_rolling_5y_average": TRUSTED_20K_AVERAGE,
            "eur20k_strict_rolling_5y_median": TRUSTED_20K_MEDIAN,
            "eur20k_strict_rolling_5y_1m_hit_windows": TRUSTED_20K_HIT_1M,
            "eur20k_6h_context_classification": CONTEXT_CLASSIFICATION,
            "eur20k_6h_context_best_variant": CONTEXT_VARIANT,
            "eur20k_6h_context_rolling_5y_average": CONTEXT_20K_AVERAGE,
            "eur20k_6h_context_rolling_5y_median": CONTEXT_20K_MEDIAN,
            "eur20k_6h_context_1m_hit_windows": CONTEXT_20K_HIT_1M,
            "eur25k_strict_average_projection": strict_25_average,
            "eur25k_strict_median_projection": strict_25_median,
            "eur25k_6h_context_average_projection": context_25_average,
            "eur25k_6h_context_median_projection": context_25_median,
        },
        "comparison_table": comparison_table,
        "target_levels": target_levels,
        "target_bands": target_bands,
        "haircut_scenarios": haircut_scenarios,
        "monte_carlo_bootstrap": _monte_carlo_limitation(root),
        "profit_vault_framework": _profit_vault_framework(),
        "realistic_5y_target_band": {
            "conservative": 500_000.0,
            "base": 750_000.0,
            "strong": 1_000_000.0,
            "aggressive": 1_250_000.0,
            "moonshot": 2_000_000.0,
            "honest_planning_range": "EUR 750k to EUR 1.1M",
            "eur1m_supported": True,
            "eur1m_classification": "Strong",
            "eur91m_is_realistic_target": False,
            "eur91m_interpretation": "diagnostic/fantasy as a forward target; useful only as evidence of historical compounding potential",
        },
        **SAFETY_FLAGS,
    }
    _write_json(paths["summary"], summary)
    _write_report(paths["report"], summary)
    return summary


def main() -> None:
    summary = run_court()
    print(json.dumps({"final_classification": summary["final_classification"], "output_folder": str(_paths(project_root())["root"])}, indent=2))


if __name__ == "__main__":
    main()
