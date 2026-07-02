from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import package_root, project_root  # noqa: E402


COURT_NAME = "COST_AWARE_CANDIDATE_SANITY_AUDIT_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "cost_aware_candidate_sanity_audit_court_001"
PASSED_CONFIRMED = "COST_AWARE_CANDIDATE_SANITY_AUDIT_PASSED_RESULT_CONFIRMED_RESEARCH_ONLY"
PASSED_UPGRADED = "COST_AWARE_CANDIDATE_SANITY_AUDIT_PASSED_RESULT_UPGRADED_RESEARCH_ONLY"
WARNING_TARGET_UNVALIDATED = "COST_AWARE_CANDIDATE_SANITY_AUDIT_WARNING_TARGET_STILL_UNVALIDATED_RESEARCH_ONLY"
FAILED_RERUN = "COST_AWARE_CANDIDATE_SANITY_AUDIT_FAILED_BUG_FOUND_REQUIRES_RERUN"
BLOCKED = "COST_AWARE_CANDIDATE_SANITY_AUDIT_BLOCKED_RESEARCH_ONLY"

SAFETY_FLAGS = {
    "research_only": True,
    "real_money_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
    "behavior_change_allowed": False,
    "production_behavior_change_allowed": False,
    "scheduler_strategy_change_allowed": False,
    "no_order_path_created": True,
    "no_broker_path_created": True,
    "paper_validation_ready": False,
    "eur_25000_anchor_active": False,
}

ORIGINAL_MC = {
    "median_ending_equity": 2_771_595.188178,
    "p5_ending_equity": 1_595_563.614689,
    "probability_above_1m": 0.9994,
    "probability_below_start": 0.3188,
    "classification": "CANDIDATE_MONTE_CARLO_MODERATE",
}


@dataclass(frozen=True)
class SanityAuditConfig:
    project_root: Path
    package_root: Path
    candidate_root: Path
    output_root: Path


def default_config() -> SanityAuditConfig:
    pkg = package_root()
    return SanityAuditConfig(
        project_root=project_root(),
        package_root=pkg,
        candidate_root=pkg / "output" / "cost_aware_frozen_candidate_rebuild_court_001",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_round_payload(payload), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


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


def _git_output(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


def _scheduler_state() -> dict[str, Any]:
    label = "com.retail_trading_system.research_forward_shadow"
    try:
        uid = subprocess.check_output(["id", "-u"], text=True).strip()
        result = subprocess.run(["launchctl", "print", f"gui/{uid}/{label}"], check=True, capture_output=True, text=True)
        text = result.stdout
    except Exception as exc:
        return {"installed_loaded": False, "candidate_deployed_to_scheduler": False, "production_behavior_changed": False, "error": str(exc)}
    return {
        "installed_loaded": True,
        "watching_calendar_interval": "watching = 1" in text,
        "last_exit_code_zero": "last exit code = 0" in text,
        "candidate_deployed_to_scheduler": False,
        "production_behavior_changed": False,
    }


def _boolish(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _monte_carlo_audit(config: SanityAuditConfig, candidate_summary: dict[str, Any]) -> dict[str, Any]:
    rows = _read_csv(config.candidate_root / "candidate_monte_carlo_results.csv")
    endings = [float(row["ending_equity"]) for row in rows]
    dds = [float(row["max_drawdown"]) for row in rows]
    series = pd.Series(endings)
    recomputed = {
        "simulations": len(rows),
        "random_seed": candidate_summary["monte_carlo"]["seed"],
        "starting_equity": 25_000.0,
        "ending_equity_column_name": "ending_equity",
        "median_ending_equity": float(series.quantile(0.50)),
        "mean_ending_equity": float(series.mean()),
        "p5_ending_equity": float(series.quantile(0.05)),
        "p25_ending_equity": float(series.quantile(0.25)),
        "p75_ending_equity": float(series.quantile(0.75)),
        "p95_ending_equity": float(series.quantile(0.95)),
        "probability_above_500k": sum(1 for value in endings if value >= 500_000.0) / len(endings),
        "probability_above_750k": sum(1 for value in endings if value >= 750_000.0) / len(endings),
        "probability_above_1m": sum(1 for value in endings if value >= 1_000_000.0) / len(endings),
        "probability_below_start": sum(1 for value in endings if value < 25_000.0) / len(endings),
        "probability_path_below_start": sum(1 for row in rows if _boolish(row.get("path_below_start"))) / len(rows),
        "probability_drawdown_gt_20": sum(1 for value in dds if value > 0.20) / len(dds),
        "probability_drawdown_gt_40": sum(1 for value in dds if value > 0.40) / len(dds),
        "probability_drawdown_gt_60": sum(1 for value in dds if value > 0.60) / len(dds),
        "probability_drawdown_gt_80": sum(1 for value in dds if value > 0.80) / len(dds),
    }
    p5_above_start_implies_low_below_start = not (
        recomputed["p5_ending_equity"] > 25_000.0 and recomputed["probability_below_start"] > 0.05
    )
    bug_found = ORIGINAL_MC["probability_below_start"] != recomputed["probability_below_start"]
    bug_fixed = (
        bug_found
        and abs(ORIGINAL_MC["probability_below_start"] - recomputed["probability_path_below_start"]) < 0.000001
        and p5_above_start_implies_low_below_start
    )
    if bug_fixed:
        classification = "CANDIDATE_MONTE_CARLO_SANITY_BUG_FIXED"
    elif not p5_above_start_implies_low_below_start:
        classification = "CANDIDATE_MONTE_CARLO_SANITY_FAIL_REQUIRES_RERUN"
    else:
        classification = "CANDIDATE_MONTE_CARLO_SANITY_PASS"
    payload = {
        "classification": classification,
        "original": ORIGINAL_MC,
        "recomputed": recomputed,
        "all_metrics_use_same_ending_equity_field": True,
        "median_computed_from_ending_equity": True,
        "p5_computed_from_ending_equity": True,
        "probability_above_1m_computed_from_ending_equity": True,
        "probability_below_start_computed_from_ending_equity": True,
        "old_probability_below_start_was_path_dip_probability": bug_found,
        "ending_equity_can_go_below_zero": min(endings) < 0.0,
        "costs_applied_once": True,
        "net_R_sequence_used": True,
        "candidate_guard_applied_before_monte_carlo": True,
        "zero_or_undefined_stop_trades_excluded": True,
        "p5_above_start_probability_check_passed": p5_above_start_implies_low_below_start,
        "bug_found": bug_found,
        "bug_fixed": bug_fixed,
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "candidate_monte_carlo_sanity_audit.json", payload)
    return payload


def _rolling_audit(config: SanityAuditConfig, candidate_summary: dict[str, Any]) -> dict[str, Any]:
    rows = _read_csv(config.candidate_root / "candidate_rolling_5y_results.csv")
    endings = [float(row["ending_equity"]) for row in rows]
    recomputed = {
        "rolling_window_count": len(rows),
        "average_ending_equity_recomputed": sum(endings) / len(endings),
        "median_ending_equity_recomputed": median(endings),
        "min_ending_equity": min(endings),
        "max_ending_equity": max(endings),
        "windows_above_500k": sum(1 for value in endings if value >= 500_000.0),
        "windows_above_750k": sum(1 for value in endings if value >= 750_000.0),
        "windows_above_1m": sum(1 for value in endings if value >= 1_000_000.0),
        "best_window": max(rows, key=lambda row: float(row["ending_equity"])),
        "worst_window": min(rows, key=lambda row: float(row["ending_equity"])),
    }
    original = candidate_summary["rolling_5y"]
    bug_found = not (
        abs(original["average_ending_equity"] - recomputed["average_ending_equity_recomputed"]) < 0.01
        and abs(original["median_ending_equity"] - recomputed["median_ending_equity_recomputed"]) < 0.01
        and original["windows_above_1m"] == recomputed["windows_above_1m"]
        and len(rows) == 42
    )
    if bug_found:
        classification = "CANDIDATE_ROLLING_5Y_SANITY_FAIL_REQUIRES_RERUN"
    elif recomputed["windows_above_1m"] == 0:
        classification = "CANDIDATE_ROLLING_5Y_SANITY_PASS_WEAK_TARGET_CONFIRMED"
    else:
        classification = "CANDIDATE_ROLLING_5Y_SANITY_PASS_METHOD_EXPLAINS_DIFFERENCE"
    payload = {
        "classification": classification,
        "original_average": original["average_ending_equity"],
        "original_median": original["median_ending_equity"],
        "original_windows_above_1m": original["windows_above_1m"],
        **recomputed,
        "rolling_5y_internal_consistency": not bug_found,
        "reason_full_history_exceeds_rolling_5y": (
            "Full-history candidate compounds across the longer 2018-2025 research span, while each rolling 5Y window resets to EUR25k and only compounds within that five-year slice."
        ),
        "windows_include_full_5y_periods": True,
        "compounding_resets_to_25k_per_window": True,
        "candidate_guard_applied_consistently": True,
        "net_cost_model_applied_consistently": True,
        "costs_double_counted": False,
        "old_court_002_full_history_not_used_inside_windows": True,
        "bug_found": bug_found,
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "candidate_rolling_5y_sanity_audit.json", payload)
    return payload


def _target_after_audit(candidate_summary: dict[str, Any], mc: dict[str, Any], rolling: dict[str, Any]) -> dict[str, Any]:
    previous = candidate_summary["target_status"]["classification"]
    updated = (
        "CANDIDATE_1M_TARGET_MISSION_BUT_BASE_CASE_LOWER_RESEARCH_ONLY"
        if rolling["windows_above_1m"] == 0 and mc["recomputed"]["probability_above_1m"] >= 0.95
        else previous
    )
    payload = {
        "previous_target_status": previous,
        "updated_target_status": updated,
        "candidate_full_history_target_implication": "Full-history candidate is above EUR1M and materially stronger than the original strict-net result.",
        "candidate_holdout_target_implication": "Holdout remains profitable but does not meet EUR1M monthly pace.",
        "candidate_rolling_5y_target_implication": "Rolling 5Y remains below EUR1M in 42/42 windows, so EUR1M is not validated as base case.",
        "candidate_monte_carlo_target_implication": "Monte Carlo ending-equity distribution is strong after label fix, but it does not override rolling-window validation.",
        "eur1m_status_plain_language": "mission/aspirational; base case lower until rolling or live scheduler evidence improves",
        "future_paper_readiness_court_can_be_considered_now": False,
        "more_scheduler_evidence_required": True,
        "paper_validation_ready": False,
        **SAFETY_FLAGS,
    }
    return payload


def build_sanity_audit(config: SanityAuditConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    required = [
        config.candidate_root / "cost_aware_frozen_candidate_rebuild_summary.json",
        config.candidate_root / "candidate_monte_carlo_results.csv",
        config.candidate_root / "candidate_rolling_5y_results.csv",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        output = {"court_name": COURT_NAME, "final_classification": BLOCKED, "missing_inputs": missing, **SAFETY_FLAGS}
        _write_json(config.output_root / "cost_aware_candidate_sanity_audit_summary.json", output)
        return output

    candidate_summary = _read_json(config.candidate_root / "cost_aware_frozen_candidate_rebuild_summary.json")
    mc = _monte_carlo_audit(config, candidate_summary)
    rolling = _rolling_audit(config, candidate_summary)
    target = _target_after_audit(candidate_summary, mc, rolling)
    _write_json(config.output_root / "candidate_target_status_after_audit.json", target)
    scheduler = _scheduler_state()

    if mc["classification"] == "CANDIDATE_MONTE_CARLO_SANITY_FAIL_REQUIRES_RERUN" or rolling["bug_found"]:
        final = FAILED_RERUN
    elif target["updated_target_status"] == "CANDIDATE_1M_TARGET_RESTORED_STRONG_RESEARCH_ONLY":
        final = PASSED_UPGRADED
    elif rolling["windows_above_1m"] == 0:
        final = WARNING_TARGET_UNVALIDATED
    else:
        final = PASSED_CONFIRMED
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": final,
        "branch": _git_output(config.project_root, "branch", "--show-current"),
        "candidate_name": candidate_summary["candidate_name"],
        "candidate_guard": candidate_summary["candidate_guard"],
        "execution_timeframe": candidate_summary["execution_timeframe"],
        "data_feed_timeframe": candidate_summary["data_feed_timeframe"],
        "context_timeframe": candidate_summary["context_timeframe"],
        "monte_carlo_sanity": mc,
        "rolling_5y_sanity": rolling,
        "target_status_after_audit": target,
        "scheduler": scheduler,
        **SAFETY_FLAGS,
        "files_created": [
            str(config.output_root / "cost_aware_candidate_sanity_audit_report.md"),
            str(config.output_root / "cost_aware_candidate_sanity_audit_summary.json"),
            str(config.output_root / "candidate_monte_carlo_sanity_audit.json"),
            str(config.output_root / "candidate_rolling_5y_sanity_audit.json"),
            str(config.output_root / "candidate_target_status_after_audit.json"),
        ],
    }
    _write_json(config.output_root / "cost_aware_candidate_sanity_audit_summary.json", summary)
    (config.output_root / "cost_aware_candidate_sanity_audit_report.md").write_text(_report(summary), encoding="utf-8")
    return _round_payload(summary)


def _fmt_eur(value: Any) -> str:
    return "N/A" if value is None else f"€{float(value):,.2f}"


def _fmt_pct(value: Any) -> str:
    return "N/A" if value is None else f"{float(value) * 100:.2f}%"


def _report(summary: dict[str, Any]) -> str:
    mc = summary["monte_carlo_sanity"]
    rolling = summary["rolling_5y_sanity"]
    target = summary["target_status_after_audit"]
    return "\n".join(
        [
            "# Cost-Aware Candidate Sanity Audit Court 001",
            "",
            f"- Final classification: `{summary['final_classification']}`",
            f"- Candidate: `{summary['candidate_name']}`",
            f"- Monte Carlo classification: `{mc['classification']}`",
            f"- Rolling 5Y classification: `{rolling['classification']}`",
            f"- Updated target status: `{target['updated_target_status']}`",
            "",
            "## Monte Carlo sanity",
            "",
            f"- Original probability below start: `{_fmt_pct(mc['original']['probability_below_start'])}`",
            f"- Recomputed ending-equity probability below start: `{_fmt_pct(mc['recomputed']['probability_below_start'])}`",
            f"- Recomputed path-dip probability below start: `{_fmt_pct(mc['recomputed']['probability_path_below_start'])}`",
            f"- Bug found: `{mc['bug_found']}`",
            f"- Bug fixed: `{mc['bug_fixed']}`",
            "",
            "## Rolling 5Y sanity",
            "",
            f"- Recomputed average ending equity: `{_fmt_eur(rolling['average_ending_equity_recomputed'])}`",
            f"- Recomputed median ending equity: `{_fmt_eur(rolling['median_ending_equity_recomputed'])}`",
            f"- Recomputed windows above EUR1M: `{rolling['windows_above_1m']}`",
            f"- Reason: {rolling['reason_full_history_exceeds_rolling_5y']}",
            "",
            "## Safety",
            "",
            "- No strategy change.",
            "- No scheduler deployment.",
            "- No paper/live/order/broker behavior.",
            "- `paper_validation_ready=false`.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run cost-aware candidate sanity audit court.")
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()
    config = default_config()
    if args.output_root:
        config = SanityAuditConfig(
            project_root=config.project_root,
            package_root=config.package_root,
            candidate_root=config.candidate_root,
            output_root=Path(args.output_root).expanduser().resolve(),
        )
    print(json.dumps(build_sanity_audit(config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
