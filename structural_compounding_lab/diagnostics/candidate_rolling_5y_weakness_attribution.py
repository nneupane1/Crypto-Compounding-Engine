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


COURT_NAME = "CANDIDATE_ROLLING_5Y_WEAKNESS_ATTRIBUTION_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "candidate_rolling_5y_weakness_attribution_court_001"
CANDIDATE_NAME = "COST_AWARE_MAX_COST_R_1_0_CANDIDATE"
START_CAPITAL = 25_000.0
TARGET_EQUITY = 1_000_000.0
TARGET_MULTIPLE = TARGET_EQUITY / START_CAPITAL

PASS_METHOD_EXPLAINS = "CANDIDATE_ROLLING_5Y_WEAKNESS_ATTRIBUTION_METHOD_EXPLAINS_GAP_RESEARCH_ONLY"
TARGET_GAP_MANAGEABLE = "CANDIDATE_ROLLING_5Y_WEAKNESS_ATTRIBUTION_TARGET_GAP_MANAGEABLE_RESEARCH_ONLY"
TARGET_GAP_MATERIAL = "CANDIDATE_ROLLING_5Y_WEAKNESS_ATTRIBUTION_TARGET_GAP_MATERIAL_RESEARCH_ONLY"
FAILED = "CANDIDATE_ROLLING_5Y_WEAKNESS_ATTRIBUTION_FAILED_RESEARCH_ONLY"
BLOCKED = "CANDIDATE_ROLLING_5Y_WEAKNESS_ATTRIBUTION_BLOCKED_RESEARCH_ONLY"

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


@dataclass(frozen=True)
class RollingWeaknessConfig:
    project_root: Path
    package_root: Path
    candidate_root: Path
    sanity_root: Path
    output_root: Path


def default_config() -> RollingWeaknessConfig:
    pkg = package_root()
    return RollingWeaknessConfig(
        project_root=project_root(),
        package_root=pkg,
        candidate_root=pkg / "output" / "cost_aware_frozen_candidate_rebuild_court_001",
        sanity_root=pkg / "output" / "cost_aware_candidate_sanity_audit_court_001",
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


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row.keys()})
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


def _float(row: dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = row.get(key, default)
        if value in {"", None}:
            return default
        return float(value)
    except Exception:
        return default


def _bool(row: dict[str, Any], key: str) -> bool:
    return str(row.get(key, "")).strip().lower() in {"true", "1", "yes"}


def _load_trade_rows(config: RollingWeaknessConfig) -> list[dict[str, Any]]:
    rows = _read_csv(config.candidate_root / "candidate_full_history_results.csv")
    holdout_path = config.candidate_root / "candidate_holdout_results.csv"
    if holdout_path.exists():
        rows.extend(_read_csv(holdout_path))
    output: list[dict[str, Any]] = []
    for row in rows:
        if not _bool(row, "candidate_guard_accepted"):
            continue
        row = dict(row)
        row["entry_timestamp"] = pd.to_datetime(row.get("entry_timestamp") or row.get("entry_time"), utc=True, errors="coerce")
        row["exit_timestamp"] = pd.to_datetime(row.get("exit_timestamp") or row.get("exit_time"), utc=True, errors="coerce")
        row["net_r_float"] = _float(row, "net_r")
        row["gross_r_float"] = _float(row, "gross_r")
        row["net_cost_r_float"] = _float(row, "net_cost_r")
        output.append(row)
    return sorted(output, key=lambda row: row["entry_timestamp"])


def _slice(rows: list[dict[str, Any]], start: pd.Timestamp, end: pd.Timestamp) -> list[dict[str, Any]]:
    return [row for row in rows if pd.notna(row["entry_timestamp"]) and start <= row["entry_timestamp"] <= end]


def _window_attribution(rolling_rows: list[dict[str, Any]], trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    attributed: list[dict[str, Any]] = []
    for row in rolling_rows:
        start = pd.Timestamp(row["start_date"])
        end = pd.Timestamp(row["end_date"])
        window_trades = _slice(trades, start, end)
        values = [trade["net_r_float"] for trade in window_trades]
        winners = [value for value in values if value > 0.0]
        losses = [value for value in values if value < 0.0]
        top_values = sorted(values, reverse=True)
        ending = _float(row, "ending_equity")
        gap = max(TARGET_EQUITY - ending, 0.0)
        required_end_multiplier = TARGET_EQUITY / ending if ending > 0.0 else float("inf")
        required_single_terminal_r = ((TARGET_EQUITY / ending) - 1.0) / 0.01 if ending > 0.0 else float("inf")
        attributed.append(
            {
                **row,
                "equity_gap_to_1m": gap,
                "ending_multiple": ending / START_CAPITAL,
                "target_multiple": TARGET_MULTIPLE,
                "required_extra_multiplier_from_window_end": required_end_multiplier,
                "required_single_terminal_R_to_hit_1m": required_single_terminal_r,
                "net_R_per_trade": sum(values) / len(values) if values else 0.0,
                "gross_R_per_trade": sum(trade["gross_r_float"] for trade in window_trades) / len(window_trades) if window_trades else 0.0,
                "cost_R_total": sum(trade["net_cost_r_float"] for trade in window_trades),
                "winner_count": len(winners),
                "loser_count": len(losses),
                "high_R_ge_3_count": sum(1 for value in values if value >= 3.0),
                "high_R_ge_5_count": sum(1 for value in values if value >= 5.0),
                "high_R_ge_10_count": sum(1 for value in values if value >= 10.0),
                "top_5_net_R": sum(top_values[:5]),
                "top_10_net_R": sum(top_values[:10]),
                "bottom_5_net_R": sum(sorted(values)[:5]),
            }
        )
    return attributed


def _yearly_contribution(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    buckets: dict[int, list[dict[str, Any]]] = {}
    for trade in trades:
        if pd.isna(trade["entry_timestamp"]):
            continue
        buckets.setdefault(int(trade["entry_timestamp"].year), []).append(trade)
    for year, bucket in sorted(buckets.items()):
        values = [row["net_r_float"] for row in bucket]
        rows.append(
            {
                "year": year,
                "accepted_trades": len(bucket),
                "net_total_R": sum(values),
                "average_net_R": sum(values) / len(values) if values else 0.0,
                "high_R_ge_3_count": sum(1 for value in values if value >= 3.0),
                "high_R_ge_5_count": sum(1 for value in values if value >= 5.0),
                "high_R_ge_10_count": sum(1 for value in values if value >= 10.0),
                "win_rate": sum(1 for value in values if value > 0.0) / len(values) if values else 0.0,
            }
        )
    return rows


def build_weakness_attribution(config: RollingWeaknessConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    required = [
        config.candidate_root / "cost_aware_frozen_candidate_rebuild_summary.json",
        config.candidate_root / "candidate_rolling_5y_results.csv",
        config.candidate_root / "candidate_full_history_results.csv",
        config.sanity_root / "cost_aware_candidate_sanity_audit_summary.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        output = {"court_name": COURT_NAME, "final_classification": BLOCKED, "missing_inputs": missing, **SAFETY_FLAGS}
        _write_json(config.output_root / "candidate_rolling_5y_weakness_attribution_summary.json", output)
        return output

    candidate = _read_json(config.candidate_root / "cost_aware_frozen_candidate_rebuild_summary.json")
    sanity = _read_json(config.sanity_root / "cost_aware_candidate_sanity_audit_summary.json")
    rolling_rows = _read_csv(config.candidate_root / "candidate_rolling_5y_results.csv")
    trades = _load_trade_rows(config)
    attribution = _window_attribution(rolling_rows, trades)
    yearly = _yearly_contribution(trades)
    endings = [_float(row, "ending_equity") for row in attribution]
    gaps = [row["equity_gap_to_1m"] for row in attribution]
    best = max(attribution, key=lambda row: float(row["ending_equity"]))
    worst = min(attribution, key=lambda row: float(row["ending_equity"]))
    full_start = min(row["entry_timestamp"] for row in trades if pd.notna(row["entry_timestamp"]))
    full_end = max(row["entry_timestamp"] for row in trades if pd.notna(row["entry_timestamp"]))
    full_years = (full_end - full_start).total_seconds() / (365.2425 * 24 * 3600)
    average = sum(endings) / len(endings)
    windows_above_1m = sum(1 for value in endings if value >= TARGET_EQUITY)
    median_gap = median(gaps)
    best_gap = max(TARGET_EQUITY - float(best["ending_equity"]), 0.0)
    main_drivers = []
    if windows_above_1m == 0:
        main_drivers.append("no_rolling_window_reaches_required_40x_multiple")
    if best_gap > 250_000:
        main_drivers.append("even_best_window_is_materially_below_1m")
    if full_years > 5.5:
        main_drivers.append("full_history_compounds_materially_longer_than_each_5y_window")
    if average < 500_000:
        main_drivers.append("average_window_base_case_is_below_500k")
    if candidate["monte_carlo"]["probability_above_1m"] >= 0.95 and windows_above_1m == 0:
        main_drivers.append("bootstrap_sequence_risk_is_strong_but_chronological_rolling_windows_do_not_validate_1m")

    if windows_above_1m > 0:
        final = TARGET_GAP_MANAGEABLE
    elif best_gap <= 250_000:
        final = TARGET_GAP_MANAGEABLE
    elif len(attribution) == 42 and not sanity["rolling_5y_sanity"]["bug_found"]:
        final = TARGET_GAP_MATERIAL
    else:
        final = PASS_METHOD_EXPLAINS

    target_status = (
        "EUR1M_MISSION_REMAINS_ASPIRATIONAL_BASE_CASE_LOWER"
        if windows_above_1m == 0
        else "EUR1M_TARGET_HAS_SOME_ROLLING_SUPPORT"
    )
    scheduler = _scheduler_state()
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": final,
        "candidate_name": CANDIDATE_NAME,
        "branch": _git_output(config.project_root, "branch", "--show-current"),
        **SAFETY_FLAGS,
        "input_artifacts": {
            "candidate_summary": str(config.candidate_root / "cost_aware_frozen_candidate_rebuild_summary.json"),
            "candidate_rolling_5y_results": str(config.candidate_root / "candidate_rolling_5y_results.csv"),
            "candidate_full_history_results": str(config.candidate_root / "candidate_full_history_results.csv"),
            "sanity_summary": str(config.sanity_root / "cost_aware_candidate_sanity_audit_summary.json"),
        },
        "rolling_summary": {
            "window_count": len(attribution),
            "average_ending_equity": average,
            "median_ending_equity": median(endings),
            "min_ending_equity": min(endings),
            "max_ending_equity": max(endings),
            "windows_above_500k": sum(1 for value in endings if value >= 500_000),
            "windows_above_750k": sum(1 for value in endings if value >= 750_000),
            "windows_above_1m": windows_above_1m,
            "median_gap_to_1m": median_gap,
            "best_gap_to_1m": best_gap,
            "worst_gap_to_1m": max(gaps),
            "best_window": best,
            "worst_window": worst,
        },
        "full_history_context": {
            "candidate_full_history_equity": candidate["full_history"]["ending_equity"],
            "candidate_full_history_return_multiple": candidate["full_history"]["return_multiple"],
            "full_history_accepted_trades": candidate["full_history"]["accepted_after_guard"],
            "full_history_span_years": full_years,
            "full_history_exceeds_5y_window_length": full_years > 5.0,
            "reason_full_history_exceeds_rolling_5y": (
                "The full-history result compounds the same candidate over a longer chronological span than five years; rolling windows reset to EUR25k and test isolated five-year slices."
            ),
        },
        "weakness_drivers": main_drivers,
        "target_status_after_attribution": target_status,
        "paper_readiness_court_can_be_considered_now": False,
        "more_scheduler_evidence_required": True,
        "candidate_deployed_to_scheduler": False,
        "production_behavior_changed": False,
        "scheduler": scheduler,
        "strategy_changed": False,
        "candidate_guard_changed": False,
        "execution_timeframe": "1H",
        "data_feed_timeframe": "1m",
        "context_timeframe": "6H",
        "files_created": [
            str(config.output_root / "candidate_rolling_5y_weakness_attribution_report.md"),
            str(config.output_root / "candidate_rolling_5y_weakness_attribution_summary.json"),
            str(config.output_root / "candidate_rolling_5y_window_attribution.csv"),
            str(config.output_root / "candidate_yearly_contribution_attribution.csv"),
            str(config.output_root / "candidate_rolling_5y_target_gap_analysis.json"),
        ],
    }
    gap = {
        "target_equity": TARGET_EQUITY,
        "target_multiple": TARGET_MULTIPLE,
        "best_window_equity": float(best["ending_equity"]),
        "best_window_gap_to_1m": best_gap,
        "best_window_required_extra_multiplier": best["required_extra_multiplier_from_window_end"],
        "average_window_gap_to_1m": TARGET_EQUITY - average,
        "rolling_1m_validated": windows_above_1m > 0,
        "plain_english": "The candidate is much cleaner, but five-year chronological windows do not yet compound enough to validate EUR1M.",
    }
    _write_csv(config.output_root / "candidate_rolling_5y_window_attribution.csv", attribution)
    _write_csv(config.output_root / "candidate_yearly_contribution_attribution.csv", yearly)
    _write_json(config.output_root / "candidate_rolling_5y_target_gap_analysis.json", gap)
    _write_json(config.output_root / "candidate_rolling_5y_weakness_attribution_summary.json", summary)
    (config.output_root / "candidate_rolling_5y_weakness_attribution_report.md").write_text(_report(summary), encoding="utf-8")
    return _round_payload(summary)


def _fmt_eur(value: Any) -> str:
    return "N/A" if value is None else f"€{float(value):,.2f}"


def _fmt_pct(value: Any) -> str:
    return "N/A" if value is None else f"{float(value) * 100:.2f}%"


def _report(summary: dict[str, Any]) -> str:
    rolling = summary["rolling_summary"]
    return "\n".join(
        [
            "# Candidate Rolling 5Y Weakness Attribution Court 001",
            "",
            f"- Final classification: `{summary['final_classification']}`",
            f"- Candidate: `{summary['candidate_name']}`",
            f"- Target status: `{summary['target_status_after_attribution']}`",
            "",
            "## Rolling 5Y target gap",
            "",
            f"- Average ending equity: `{_fmt_eur(rolling['average_ending_equity'])}`",
            f"- Median ending equity: `{_fmt_eur(rolling['median_ending_equity'])}`",
            f"- Best ending equity: `{_fmt_eur(rolling['max_ending_equity'])}`",
            f"- Windows above EUR1M: `{rolling['windows_above_1m']} / {rolling['window_count']}`",
            f"- Best gap to EUR1M: `{_fmt_eur(rolling['best_gap_to_1m'])}`",
            "",
            "## Main drivers",
            "",
            *(f"- `{driver}`" for driver in summary["weakness_drivers"]),
            "",
            "## Interpretation",
            "",
            summary["full_history_context"]["reason_full_history_exceeds_rolling_5y"],
            "",
            "No strategy, scheduler, paper, live, order, or broker behavior was changed.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run candidate rolling 5Y weakness attribution court.")
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()
    config = default_config()
    if args.output_root:
        config = RollingWeaknessConfig(
            project_root=config.project_root,
            package_root=config.package_root,
            candidate_root=config.candidate_root,
            sanity_root=config.sanity_root,
            output_root=Path(args.output_root).expanduser().resolve(),
        )
    print(json.dumps(build_weakness_attribution(config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
