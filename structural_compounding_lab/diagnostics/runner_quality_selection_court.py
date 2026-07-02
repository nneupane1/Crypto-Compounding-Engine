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
from typing import Any, Callable

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import package_root, project_root  # noqa: E402
from structural_compounding_lab.diagnostics.cost_aware_frozen_candidate_rebuild import (  # noqa: E402
    CANDIDATE_NAME,
    ROUND_TRIP_COST_BPS,
    RISK_PER_TRADE,
    START_CAPITAL_25K,
)


COURT_NAME = "RUNNER_QUALITY_SELECTION_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "runner_quality_selection_court_001"
TARGET_EQUITY = 1_000_000.0

QUALITY_RESTORES_TARGET = "RUNNER_QUALITY_SELECTION_RESTORES_1M_ROLLING_SUPPORT_RESEARCH_ONLY"
QUALITY_PROMISING_SMALL = "RUNNER_QUALITY_SELECTION_SMALL_IMPROVEMENT_NOT_TARGET_VALIDATED_RESEARCH_ONLY"
QUALITY_NOT_SUPPORTED = "RUNNER_QUALITY_SELECTION_NOT_SUPPORTED_RESEARCH_ONLY"
QUALITY_ORACLE_ONLY = "RUNNER_QUALITY_SELECTION_ORACLE_ONLY_UPSIDE_NOT_DEPLOYABLE_RESEARCH_ONLY"
BLOCKED = "RUNNER_QUALITY_SELECTION_BLOCKED_RESEARCH_ONLY"

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "real_money_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
    "behavior_change_allowed": False,
    "production_behavior_change_allowed": False,
    "scheduler_strategy_change_allowed": False,
    "candidate_deployed_to_scheduler": False,
    "strategy_changed": False,
    "entries_changed": False,
    "base_exits_changed": False,
    "sizing_changed": False,
    "pyramiding_enabled": False,
    "no_order_path_created": True,
    "no_broker_path_created": True,
    "paper_validation_ready": False,
    "eur_25000_anchor_active": False,
}


@dataclass(frozen=True)
class RunnerQualityConfig:
    project_root: Path
    package_root: Path
    moonshot_root: Path
    output_root: Path


@dataclass(frozen=True)
class QualityProfile:
    profile_id: str
    deployability: str
    description: str
    predicate: Callable[[dict[str, Any]], bool]


def default_config() -> RunnerQualityConfig:
    pkg = package_root()
    return RunnerQualityConfig(
        project_root=project_root(),
        package_root=pkg,
        moonshot_root=pkg / "output" / "cost_aware_runner_moonshot_capture_court_001",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _git_output(root: Path, *args: str) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return ""


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


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


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


def _profit_factor(values: list[float]) -> float:
    wins = sum(value for value in values if value > 0.0)
    losses = abs(sum(value for value in values if value < 0.0))
    if losses == 0.0:
        return float("inf") if wins > 0.0 else 0.0
    return wins / losses


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0] if curve else 0.0
    worst = 0.0
    for equity in curve:
        peak = max(peak, equity)
        if peak > 0.0:
            worst = max(worst, (peak - equity) / peak)
    return worst


def _simulate(rows: list[dict[str, Any]], *, use_runner: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    equity = START_CAPITAL_25K
    curve = [equity]
    values: list[float] = []
    for row in rows:
        net_r = float(row["overlay_net_r"]) if use_runner(row) else float(row["net_r"])
        values.append(net_r)
        equity += equity * RISK_PER_TRADE * net_r
        curve.append(equity)
    return {
        "ending_equity": equity,
        "return_multiple": equity / START_CAPITAL_25K,
        "net_gain": equity - START_CAPITAL_25K,
        "accepted_trades": len(rows),
        "net_total_R": sum(values),
        "average_R": sum(values) / len(values) if values else 0.0,
        "median_R": median(values) if values else 0.0,
        "profit_factor": _profit_factor(values),
        "win_rate": sum(1 for value in values if value > 0.0) / len(values) if values else 0.0,
        "max_drawdown": _max_drawdown(curve),
        "best_trade_R": max(values) if values else 0.0,
        "worst_trade_R": min(values) if values else 0.0,
    }


def _rolling_windows() -> list[tuple[pd.Timestamp, pd.Timestamp]]:
    starts = pd.date_range("2018-01-01", "2021-06-01", freq="MS", tz="UTC")
    return [(start, start + pd.DateOffset(years=5) - pd.Timedelta(minutes=1)) for start in starts]


def _rolling_summary(rows: list[dict[str, Any]], *, use_runner: Callable[[dict[str, Any]], bool]) -> dict[str, Any]:
    output: list[dict[str, Any]] = []
    for index, (start, end) in enumerate(_rolling_windows(), start=1):
        selected = [row for row in rows if start <= row["entry_timestamp"] <= end]
        sim = _simulate(selected, use_runner=use_runner)
        output.append(
            {
                "window_number": index,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "ending_equity": sim["ending_equity"],
                "return_multiple": sim["return_multiple"],
                "accepted_trades": len(selected),
                "max_drawdown": sim["max_drawdown"],
                "above_1m": sim["ending_equity"] >= TARGET_EQUITY,
            }
        )
    endings = [float(row["ending_equity"]) for row in output]
    return {
        "window_rows": output,
        "window_count": len(output),
        "average_ending_equity": sum(endings) / len(endings) if endings else 0.0,
        "median_ending_equity": median(endings) if endings else 0.0,
        "maximum_ending_equity": max(endings) if endings else 0.0,
        "minimum_ending_equity": min(endings) if endings else 0.0,
        "windows_above_1m": sum(1 for value in endings if value >= TARGET_EQUITY),
    }


def _load_rows(config: RunnerQualityConfig) -> list[dict[str, Any]]:
    rows = _read_csv(config.moonshot_root / "runner_moonshot_best_policy_trades.csv")
    opportunity_rows = _read_csv(config.moonshot_root / "runner_moonshot_post_exit_opportunity.csv")
    opportunity_by_key = {(row.get("period"), row.get("trade_id")): row for row in opportunity_rows}
    parsed: list[dict[str, Any]] = []
    for row in rows:
        opportunity = opportunity_by_key.get((row.get("period"), row.get("trade_id")), {})
        payload = dict(row)
        payload.update(
            {
                "entry_timestamp": pd.to_datetime(row.get("entry_timestamp") or row.get("entry_time"), utc=True, errors="coerce"),
                "exit_timestamp": pd.to_datetime(row.get("exit_timestamp") or row.get("exit_time"), utc=True, errors="coerce"),
                "runner_eligible": _bool(row, "runner_eligible"),
                "gross_r": _float(row, "gross_r"),
                "net_r": _float(row, "net_r"),
                "overlay_net_r": _float(row, "overlay_net_r"),
                "overlay_delta_net_r": _float(row, "overlay_delta_net_r"),
                "net_cost_r": _float(row, "net_cost_r"),
                "runner_extra_gross_r": _float(row, "runner_extra_gross_r"),
                "post_exit_extra_gross_r_72h": _float(opportunity, "post_exit_extra_gross_r_72h"),
            }
        )
        if pd.notna(payload["entry_timestamp"]):
            parsed.append(payload)
    return sorted(parsed, key=lambda item: item["entry_timestamp"])


def _profiles() -> list[QualityProfile]:
    return [
        QualityProfile("broad_all_runner_reference", "reference", "The broad best runner policy from the previous court.", lambda row: True),
        QualityProfile("setup_A_only", "deployable", "Allow runner only on setup_class A.", lambda row: row.get("setup_class") == "A"),
        QualityProfile("elite_convexity_only", "deployable", "Allow runner only on elite_convexity rows.", lambda row: row.get("convexity_label") == "elite_convexity"),
        QualityProfile(
            "setup_A_elite_convexity",
            "deployable",
            "Allow runner only when setup_class A and elite_convexity agree.",
            lambda row: row.get("setup_class") == "A" and row.get("convexity_label") == "elite_convexity",
        ),
        QualityProfile("gross_ge_2R", "deployable", "Allow runner only when base exit is at least 2R gross.", lambda row: float(row["gross_r"]) >= 2.0),
        QualityProfile("gross_ge_3R", "deployable", "Allow runner only when base exit is at least 3R gross.", lambda row: float(row["gross_r"]) >= 3.0),
        QualityProfile(
            "gross_ge_2R_setup_A",
            "deployable",
            "Allow runner only when base exit is at least 2R gross and setup_class A.",
            lambda row: float(row["gross_r"]) >= 2.0 and row.get("setup_class") == "A",
        ),
        QualityProfile(
            "gross_ge_3R_setup_A",
            "deployable",
            "Allow runner only when base exit is at least 3R gross and setup_class A.",
            lambda row: float(row["gross_r"]) >= 3.0 and row.get("setup_class") == "A",
        ),
        QualityProfile("cost_R_le_0_5", "deployable", "Allow runner only when net cost-R is at most 0.5R.", lambda row: float(row["net_cost_r"]) <= 0.5),
        QualityProfile(
            "gross_ge_2R_cost_R_le_0_5",
            "deployable",
            "Allow runner only when base exit is at least 2R gross and net cost-R is at most 0.5R.",
            lambda row: float(row["gross_r"]) >= 2.0 and float(row["net_cost_r"]) <= 0.5,
        ),
        QualityProfile("long_only", "deployable", "Side-only diagnostic: allow runners only on longs.", lambda row: row.get("side") == "long"),
        QualityProfile("short_only", "deployable", "Side-only diagnostic: allow runners only on shorts.", lambda row: row.get("side") == "short"),
        QualityProfile(
            "oracle_runner_delta_gt_0",
            "oracle_future_leak",
            "Oracle ceiling: allow only runners known after the fact to improve net R.",
            lambda row: float(row["overlay_delta_net_r"]) > 0.0,
        ),
        QualityProfile(
            "oracle_runner_delta_ge_1R",
            "oracle_future_leak",
            "Oracle ceiling: allow only runners known after the fact to improve by at least 1R.",
            lambda row: float(row["overlay_delta_net_r"]) >= 1.0,
        ),
        QualityProfile(
            "oracle_post_exit_extra_ge_3R",
            "oracle_future_leak",
            "Oracle ceiling: allow only trades with at least 3R extra available within 72h.",
            lambda row: float(row["post_exit_extra_gross_r_72h"]) >= 3.0,
        ),
    ]


def _use_runner(profile: QualityProfile) -> Callable[[dict[str, Any]], bool]:
    return lambda row: bool(row["runner_eligible"]) and profile.predicate(row)


def _profile_result(profile: QualityProfile, rows: list[dict[str, Any]], baseline: dict[str, Any]) -> dict[str, Any]:
    use_runner = _use_runner(profile)
    full_rows = [row for row in rows if row.get("period") == "full_history"]
    holdout_rows = [row for row in rows if row.get("period") == "sealed_holdout"]
    sleeve_rows = [row for row in rows if use_runner(row)]
    full = _simulate(full_rows, use_runner=use_runner)
    holdout = _simulate(holdout_rows, use_runner=use_runner)
    rolling = _rolling_summary(rows, use_runner=use_runner)
    return {
        "profile_id": profile.profile_id,
        "deployability": profile.deployability,
        "description": profile.description,
        "sleeve_trades": len(sleeve_rows),
        "runner_improved_trades": sum(1 for row in sleeve_rows if float(row["overlay_delta_net_r"]) > 0.0),
        "runner_damaged_trades": sum(1 for row in sleeve_rows if float(row["overlay_delta_net_r"]) < 0.0),
        "runner_flat_trades": sum(1 for row in sleeve_rows if float(row["overlay_delta_net_r"]) == 0.0),
        "full_history_ending_equity": full["ending_equity"],
        "full_history_delta_eur": full["ending_equity"] - baseline["full_history_ending_equity"],
        "full_history_delta_pct": full["ending_equity"] / baseline["full_history_ending_equity"] - 1.0,
        "full_history_max_drawdown": full["max_drawdown"],
        "holdout_ending_equity": holdout["ending_equity"],
        "holdout_delta_eur": holdout["ending_equity"] - baseline["holdout_ending_equity"],
        "holdout_delta_pct": holdout["ending_equity"] / baseline["holdout_ending_equity"] - 1.0,
        "holdout_max_drawdown": holdout["max_drawdown"],
        "rolling_average_ending_equity": rolling["average_ending_equity"],
        "rolling_average_delta_eur": rolling["average_ending_equity"] - baseline["rolling_average_ending_equity"],
        "rolling_median_ending_equity": rolling["median_ending_equity"],
        "rolling_max_ending_equity": rolling["maximum_ending_equity"],
        "rolling_max_delta_eur": rolling["maximum_ending_equity"] - baseline["rolling_max_ending_equity"],
        "rolling_windows_above_1m": rolling["windows_above_1m"],
        "paper_readiness_court_can_be_considered_now": False,
    }


def run_runner_quality_selection_court(config: RunnerQualityConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    required = [
        config.moonshot_root / "cost_aware_runner_moonshot_capture_summary.json",
        config.moonshot_root / "runner_moonshot_best_policy_trades.csv",
        config.moonshot_root / "runner_moonshot_post_exit_opportunity.csv",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        summary = {"court_name": COURT_NAME, "final_classification": BLOCKED, "missing_inputs": missing, **SAFETY_FLAGS}
        _write_json(config.output_root / "runner_quality_selection_summary.json", summary)
        return summary

    moonshot_summary = _read_json(config.moonshot_root / "cost_aware_runner_moonshot_capture_summary.json")
    rows = _load_rows(config)
    baseline = moonshot_summary["baseline"]
    results = [_profile_result(profile, rows, baseline) for profile in _profiles()]
    deployable_results = [row for row in results if row["deployability"] == "deployable"]
    oracle_results = [row for row in results if row["deployability"] == "oracle_future_leak"]
    best_deployable = max(
        deployable_results,
        key=lambda row: (
            int(row["rolling_windows_above_1m"]),
            float(row["rolling_max_ending_equity"]),
            float(row["full_history_ending_equity"]),
            float(row["holdout_ending_equity"]),
        ),
    )
    best_balanced_deployable = max(
        deployable_results,
        key=lambda row: (
            float(row["holdout_ending_equity"]) >= float(baseline["holdout_ending_equity"]),
            float(row["full_history_ending_equity"]) >= float(baseline["full_history_ending_equity"]),
            float(row["rolling_max_ending_equity"]) >= float(baseline["rolling_max_ending_equity"]),
            -int(row["runner_damaged_trades"]),
            float(row["rolling_max_ending_equity"]),
        ),
    )
    best_oracle = max(
        oracle_results,
        key=lambda row: (
            int(row["rolling_windows_above_1m"]),
            float(row["rolling_max_ending_equity"]),
            float(row["full_history_ending_equity"]),
        ),
    )
    deployable_restores = int(best_deployable["rolling_windows_above_1m"]) > 0
    deployable_improves = (
        float(best_deployable["full_history_ending_equity"]) > float(baseline["full_history_ending_equity"])
        and float(best_deployable["rolling_max_ending_equity"]) > float(baseline["rolling_max_ending_equity"])
    )
    oracle_only = int(best_oracle["rolling_windows_above_1m"]) > 0 and not deployable_restores
    if deployable_restores:
        final = QUALITY_RESTORES_TARGET
    elif deployable_improves:
        final = QUALITY_PROMISING_SMALL
    elif oracle_only:
        final = QUALITY_ORACLE_ONLY
    else:
        final = QUALITY_NOT_SUPPORTED

    selected_profile_id = best_balanced_deployable["profile_id"]
    selected_profile = next(profile for profile in _profiles() if profile.profile_id == selected_profile_id)
    selected_rows = [
        {
            **row,
            "quality_profile_id": selected_profile_id,
            "quality_runner_allowed": _use_runner(selected_profile)(row),
            "quality_net_r": float(row["overlay_net_r"]) if _use_runner(selected_profile)(row) else float(row["net_r"]),
        }
        for row in rows
    ]
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "branch": _git_output(config.project_root, "branch", "--show-current"),
        "final_classification": final,
        "candidate_name": CANDIDATE_NAME,
        "cost_model": {
            "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "inherits_previous_moonshot_cost_model": True,
            "separate_slippage_model_added": False,
        },
        "input_artifacts": {
            "moonshot_summary": str(config.moonshot_root / "cost_aware_runner_moonshot_capture_summary.json"),
            "moonshot_best_policy_trades": str(config.moonshot_root / "runner_moonshot_best_policy_trades.csv"),
            "moonshot_post_exit_opportunity": str(config.moonshot_root / "runner_moonshot_post_exit_opportunity.csv"),
        },
        "baseline": baseline,
        "broad_runner_reference": next(row for row in results if row["profile_id"] == "broad_all_runner_reference"),
        "best_deployable_by_rolling_max": best_deployable,
        "best_balanced_deployable": best_balanced_deployable,
        "best_oracle_ceiling": best_oracle,
        "oracle_profiles_are_not_deployable": True,
        "target_status_after_quality_selection": (
            "EUR1M_TARGET_RESTORED_BY_DEPLOYABLE_RUNNER_QUALITY"
            if deployable_restores
            else "EUR1M_TARGET_NOT_RESTORED_BY_DEPLOYABLE_RUNNER_QUALITY"
        ),
        "interpretation": {
            "damaged_runner_trade_problem_reduced": int(best_deployable["runner_damaged_trades"]) < int(moonshot_summary["best_policy"]["runner_damaged_trades"]),
            "damaged_runner_trade_problem_solved": int(best_deployable["runner_damaged_trades"]) == 0,
            "rolling_1m_target_validated": deployable_restores,
            "paper_readiness_court_can_be_considered_now": False,
            "requires_new_runner_hypothesis_or_multi_asset_edge": not deployable_restores,
        },
        **SAFETY_FLAGS,
        "files_created": [
            str(config.output_root / "runner_quality_selection_summary.json"),
            str(config.output_root / "runner_quality_selection_report.md"),
            str(config.output_root / "runner_quality_profile_results.csv"),
            str(config.output_root / "runner_quality_best_profile_trades.csv"),
        ],
    }
    _write_csv(config.output_root / "runner_quality_profile_results.csv", results)
    _write_csv(config.output_root / "runner_quality_best_profile_trades.csv", selected_rows)
    _write_json(config.output_root / "runner_quality_selection_summary.json", summary)
    (config.output_root / "runner_quality_selection_report.md").write_text(_report(summary), encoding="utf-8")
    return _round_payload(summary)


def _fmt_eur(value: Any) -> str:
    return f"€{float(value):,.2f}"


def _fmt_pct(value: Any) -> str:
    return f"{float(value) * 100:.2f}%"


def _report(summary: dict[str, Any]) -> str:
    best = summary["best_deployable_by_rolling_max"]
    balanced = summary["best_balanced_deployable"]
    oracle = summary["best_oracle_ceiling"]
    baseline = summary["baseline"]
    return "\n".join(
        [
            "# Runner Quality Selection Court 001",
            "",
            f"- Final classification: `{summary['final_classification']}`",
            f"- Target status: `{summary['target_status_after_quality_selection']}`",
            f"- Research-only: `{summary['research_only']}`",
            f"- Paper validation ready: `{summary['paper_validation_ready']}`",
            "",
            "## Baseline",
            "",
            f"- Full-history baseline: `{_fmt_eur(baseline['full_history_ending_equity'])}`",
            f"- Holdout baseline: `{_fmt_eur(baseline['holdout_ending_equity'])}`",
            f"- Rolling max baseline: `{_fmt_eur(baseline['rolling_max_ending_equity'])}`",
            f"- Rolling windows above EUR1M baseline: `{baseline['rolling_windows_above_1m']}`",
            "",
            "## Best deployable profile by rolling max",
            "",
            f"- Profile: `{best['profile_id']}`",
            f"- Sleeve trades: `{best['sleeve_trades']}`",
            f"- Improved / damaged sleeve trades: `{best['runner_improved_trades']} / {best['runner_damaged_trades']}`",
            f"- Full-history equity: `{_fmt_eur(best['full_history_ending_equity'])}`",
            f"- Holdout equity: `{_fmt_eur(best['holdout_ending_equity'])}`",
            f"- Rolling max equity: `{_fmt_eur(best['rolling_max_ending_equity'])}`",
            f"- Rolling windows above EUR1M: `{best['rolling_windows_above_1m']}`",
            "",
            "## Best balanced deployable profile",
            "",
            f"- Profile: `{balanced['profile_id']}`",
            f"- Full-history equity: `{_fmt_eur(balanced['full_history_ending_equity'])}`",
            f"- Holdout equity: `{_fmt_eur(balanced['holdout_ending_equity'])}`",
            f"- Rolling max equity: `{_fmt_eur(balanced['rolling_max_ending_equity'])}`",
            "",
            "## Oracle ceiling, not deployable",
            "",
            f"- Profile: `{oracle['profile_id']}`",
            f"- Full-history equity: `{_fmt_eur(oracle['full_history_ending_equity'])}`",
            f"- Rolling max equity: `{_fmt_eur(oracle['rolling_max_ending_equity'])}`",
            f"- Rolling windows above EUR1M: `{oracle['rolling_windows_above_1m']}`",
            "",
            "Oracle profiles use future information and are not deployable evidence.",
            "No entries, base exits, sizing, scheduler, paper, live, order, or broker behavior was changed.",
            "",
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run research-only runner quality selection court.")
    parser.add_argument("--output-root", default=None)
    args = parser.parse_args()
    config = default_config()
    if args.output_root:
        config = RunnerQualityConfig(
            project_root=config.project_root,
            package_root=config.package_root,
            moonshot_root=config.moonshot_root,
            output_root=Path(args.output_root).expanduser().resolve(),
        )
    print(json.dumps(run_runner_quality_selection_court(config), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
