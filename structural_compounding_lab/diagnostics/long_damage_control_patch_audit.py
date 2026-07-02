from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (
    _aggregate_metrics,
    _classify_long_failure,
    _classify_short_success,
    _median,
    _normalize_trade_rows,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _timestamp,
    _to_float,
    _to_int,
    _write_csv,
    _write_json,
    _write_markdown,
)


PATCH_VARIANTS = [
    "BASELINE_CURRENT_SEQUENCE",
    "LONGS_DISABLED_ALL_SHORTS_KEPT",
    "BAD_LONG_ARCHETYPES_DISABLED_ALL_SHORTS_KEPT",
    "ONLY_BEST_LONG_ARCHETYPES_ALL_SHORTS_KEPT",
    "BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT",
    "SHORTS_ONLY_PROVEN_BUCKETS",
    "LONGS_ONLY_BEST_BUCKETS",
    "MOONSHOT_CAPPED_PATCH",
    "MOONSHOT_REMOVED_PATCH",
]

BAD_LONG_DISABLE_SET = {
    "LONG_OVERHEAD_RESISTANCE_TOO_CLOSE",
    "LONG_TINY_STOP_TRAP",
    "LONG_WEAK_RECLAIM",
    "LONG_VWAP_FAKEOUT",
    "LONG_EMA_FAKEOUT",
    "LONG_COST_DOMINATED",
    "LONG_COUNTER_HTF",
    "LONG_DANGER_TOO_HIGH",
}


@dataclass(frozen=True)
class LongDamageControlPatchAuditConfig:
    package_root: Path
    output_root: Path


def _artifact_paths(config: LongDamageControlPatchAuditConfig) -> dict[str, Path]:
    source_root = config.package_root / "output"
    five_year_root = source_root / "five_year_compounding_audit_001"
    long_short_root = source_root / "long_short_edge_repair_audit_001"
    refined_root = source_root / "daily_opportunity_definition_refinement_001"
    daily_root = source_root / "daily_structural_opportunity_001"
    return {
        "summary": source_root / "summary.json",
        "trades": source_root / "trades.csv",
        "setup_log": source_root / "setup_log.csv",
        "level_log": source_root / "level_log.csv",
        "liquidity_events": source_root / "liquidity_events.csv",
        "cooldown_log": source_root / "cooldown_log.csv",
        "pyramiding_log": source_root / "pyramiding_log.csv",
        "profit_vault": source_root / "profit_vault.json",
        "five_year_summary": five_year_root / "five_year_compounding_summary.json",
        "five_year_trade_growth": five_year_root / "diagnostics" / "full_active_capital_trade_growth.csv",
        "long_short_summary": long_short_root / "long_short_edge_repair_summary.json",
        "long_short_archetype_breakdown": long_short_root / "diagnostics" / "archetype_expectancy_breakdown.csv",
        "long_short_long_failure_modes": long_short_root / "diagnostics" / "long_failure_modes.csv",
        "long_short_short_success_modes": long_short_root / "diagnostics" / "short_success_modes.csv",
        "long_short_moonshot_dependency": long_short_root / "diagnostics" / "moonshot_dependency_report.json",
        "definition_refinement_summary": refined_root / "definition_refinement_summary.json",
        "daily_structural_summary": daily_root / "daily_structural_opportunity_summary.json",
    }


def _risk_eur(row: dict[str, Any]) -> float:
    pnl = float(row["pnl"])
    r_value = float(row["r_multiple"])
    if r_value == 0.0:
        return 0.0
    return abs(pnl / r_value)


def _prepare_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        item["entry_timestamp"] = _timestamp(row.get("entry_time"))
        item["exit_timestamp"] = _timestamp(row.get("exit_time"))
        item["r_multiple"] = float(row["r_multiple"])
        item["pnl"] = float(row["pnl"])
        item["holding_bars"] = int(row.get("holding_bars") or 0)
        item["trade_date"] = item["exit_timestamp"].normalize() if item["exit_timestamp"] is not None else None
        item["long_failure_mode"] = _classify_long_failure(item) if item["side"] == "long" else ""
        item["short_success_mode"] = _classify_short_success(item) if item["side"] == "short" and item["r_multiple"] > 0.0 else ""
        item["risk_eur_observed"] = _risk_eur(item)
        prepared.append(item)
    prepared.sort(key=lambda row: (row["exit_timestamp"] or pd.Timestamp.min, row["trade_id"]))
    return prepared


def _group_archetypes(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("archetype_key") or "")].append(row)
    output: dict[str, dict[str, Any]] = {}
    for key, bucket in grouped.items():
        metrics = _aggregate_metrics(bucket)
        output[key] = {"metrics": metrics, "rows": bucket}
    return output


def _proven_short_archetypes(rows: list[dict[str, Any]]) -> set[str]:
    output: set[str] = set()
    for key, payload in _group_archetypes([row for row in rows if row["side"] == "short"]).items():
        metrics = payload["metrics"]
        if (
            int(metrics["trade_count"]) >= 20
            and float(metrics["total_R"]) > 0.0
            and float(metrics["profit_factor"]) > 1.10
            and float(metrics["avg_R"]) > 0.0
        ):
            output.add(key)
    return output


def _best_long_archetypes(rows: list[dict[str, Any]]) -> set[str]:
    output: set[str] = set()
    for key, payload in _group_archetypes([row for row in rows if row["side"] == "long"]).items():
        metrics = payload["metrics"]
        if (
            int(metrics["trade_count"]) >= 20
            and float(metrics["total_R"]) > 0.0
            and float(metrics["profit_factor"]) > 1.05
            and float(metrics["avg_R"]) > 0.0
        ):
            output.add(key)
    return output


def _simulate_variant(
    *,
    name: str,
    selected_rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    start_capital: float,
    baseline_span_days: int,
    cooldown_rows: list[dict[str, Any]],
    moonshot_override: str | None = None,
) -> dict[str, Any]:
    active_capital = start_capital
    peak_equity = start_capital
    max_drawdown_pct = 0.0
    max_drawdown_eur = 0.0
    daily_records: dict[str, list[dict[str, Any]]] = defaultdict(list)
    replay_rows: list[dict[str, Any]] = []
    total_removed_trade_count = len(all_rows) - len(selected_rows)
    selected_ids = {row["trade_id"] for row in selected_rows}
    selected_short_r = sum(row["r_multiple"] for row in selected_rows if row["side"] == "short")
    selected_long_r = sum(row["r_multiple"] for row in selected_rows if row["side"] == "long")

    for index, row in enumerate(selected_rows, start=1):
        original_r = float(row["r_multiple"])
        adjusted_r = original_r
        filter_reason = "kept"
        if moonshot_override == "cap_10_to_5" and adjusted_r > 10.0:
            adjusted_r = 5.0
            filter_reason = "10R_plus_capped_to_5R"
        elif moonshot_override == "cap_5_to_3" and adjusted_r > 5.0:
            adjusted_r = 3.0
            filter_reason = "5R_plus_capped_to_3R"
        elif moonshot_override == "remove_5_plus" and adjusted_r >= 5.0:
            continue

        equity_before_trade = active_capital
        risk_eur = equity_before_trade * 0.01
        pnl_eur = adjusted_r * risk_eur
        active_capital = equity_before_trade + pnl_eur
        peak_equity = max(peak_equity, active_capital)
        drawdown_eur = peak_equity - active_capital
        drawdown_pct = _safe_ratio(drawdown_eur, peak_equity, 0.0)
        max_drawdown_eur = max(max_drawdown_eur, drawdown_eur)
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
        exit_timestamp = row["exit_timestamp"]
        date_key = exit_timestamp.strftime("%Y-%m-%d") if exit_timestamp is not None else ""
        replay_row = {
            "variant_name": name,
            "trade_number": index,
            "trade_id": row["trade_id"],
            "timestamp": exit_timestamp.isoformat() if exit_timestamp is not None else "",
            "side": row["side"],
            "archetype_key": row["archetype_key"],
            "long_failure_mode": row.get("long_failure_mode") or "",
            "short_success_mode": row.get("short_success_mode") or "",
            "equity_before_trade": round(equity_before_trade, 6),
            "risk_eur": round(risk_eur, 6),
            "original_trade_R": round(original_r, 6),
            "applied_trade_R": round(adjusted_r, 6),
            "pnl_eur": round(pnl_eur, 6),
            "equity_after_trade": round(active_capital, 6),
            "filter_reason": filter_reason,
        }
        replay_rows.append(replay_row)
        daily_records[date_key].append(replay_row)

    r_values = [row["applied_trade_R"] for row in replay_rows]
    pnl_values = [row["pnl_eur"] for row in replay_rows]
    long_r_values = [row["applied_trade_R"] for row in replay_rows if row["side"] == "long"]
    short_r_values = [row["applied_trade_R"] for row in replay_rows if row["side"] == "short"]
    wins = [value for value in r_values if value > 0.0]
    long_wins = [row["applied_trade_R"] for row in replay_rows if row["side"] == "long" and row["applied_trade_R"] > 0.0]
    short_wins = [row["applied_trade_R"] for row in replay_rows if row["side"] == "short" and row["applied_trade_R"] > 0.0]

    daily_rows: list[dict[str, Any]] = []
    for date_key, bucket in sorted(daily_records.items()):
        day_r = sum(row["applied_trade_R"] for row in bucket)
        day_pnl = sum(row["pnl_eur"] for row in bucket)
        daily_rows.append(
            {
                "variant_name": name,
                "date": date_key,
                "daily_R": round(day_r, 6),
                "daily_pnl": round(day_pnl, 6),
                "trade_count": len(bucket),
                "equity_end": round(bucket[-1]["equity_after_trade"], 6),
            }
        )

    monthly_returns: list[float] = []
    if daily_rows:
        month_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in daily_rows:
            month_groups[str(row["date"])[:7]].append(row)
        for _, bucket in sorted(month_groups.items()):
            starting_equity = bucket[0]["equity_end"] - bucket[0]["daily_pnl"]
            ending_equity = bucket[-1]["equity_end"]
            monthly_returns.append(_safe_ratio(ending_equity - starting_equity, starting_equity, 0.0))

    moonshot_replay = [row for row in replay_rows if row["applied_trade_R"] >= 5.0]
    risk_eur_by_trade = {row["trade_id"]: row["risk_eur_observed"] for row in selected_rows}
    profit_without_moonshots = 0.0
    profit_with_10R_plus_capped_to_5R = 0.0
    profit_with_all_5R_plus_capped_to_3R = 0.0
    for row in selected_rows:
        original_r = float(row["r_multiple"])
        if moonshot_override == "remove_5_plus" and original_r >= 5.0:
            continue
        risk_eur = risk_eur_by_trade[row["trade_id"]]
        if original_r < 5.0:
            profit_without_moonshots += original_r * risk_eur
        capped_10 = min(original_r, 5.0) if original_r > 0.0 else original_r
        capped_5 = min(original_r, 3.0) if original_r > 0.0 else original_r
        profit_with_10R_plus_capped_to_5R += capped_10 * risk_eur
        profit_with_all_5R_plus_capped_to_3R += capped_5 * risk_eur

    moonshot_profit_total = sum(row["pnl_eur"] for row in replay_rows if row["applied_trade_R"] >= 5.0)
    moonshot_dependency = _safe_ratio(moonshot_profit_total, sum(pnl_values), 0.0) if pnl_values and sum(pnl_values) != 0.0 else 0.0
    if profit_without_moonshots <= 0.0:
        moonshot_dependency_label = "NO_EDGE_WITHOUT_MOONSHOTS"
    elif moonshot_dependency > 1.0:
        moonshot_dependency_label = "EXTREME_MOONSHOT_DEPENDENCY"
    elif moonshot_dependency > 0.5:
        moonshot_dependency_label = "MODERATE_MOONSHOT_DEPENDENCY"
    else:
        moonshot_dependency_label = "HEALTHY_MOONSHOT_SUPPORT"

    average_trades_per_day = len(replay_rows) / baseline_span_days if baseline_span_days else 0.0
    active_day_count = len(daily_rows)
    average_trades_per_active_day = len(replay_rows) / active_day_count if active_day_count else 0.0
    max_trades_one_day = max((row["trade_count"] for row in daily_rows), default=0)
    worst_day_r = min((row["daily_R"] for row in daily_rows), default=0.0)
    best_day_r = max((row["daily_R"] for row in daily_rows), default=0.0)
    gross_profit = sum(value for value in r_values if value > 0.0)
    gross_loss_abs = abs(sum(value for value in r_values if value < 0.0))
    profit_factor = gross_profit / gross_loss_abs if gross_loss_abs > 0.0 else (gross_profit if gross_profit > 0.0 else 0.0)
    long_profit_factor = (
        sum(value for value in long_r_values if value > 0.0) / abs(sum(value for value in long_r_values if value < 0.0))
        if any(value < 0.0 for value in long_r_values)
        else (sum(value for value in long_r_values if value > 0.0) if any(value > 0.0 for value in long_r_values) else 0.0)
    )
    short_profit_factor = (
        sum(value for value in short_r_values if value > 0.0) / abs(sum(value for value in short_r_values if value < 0.0))
        if any(value < 0.0 for value in short_r_values)
        else (sum(value for value in short_r_values if value > 0.0) if any(value > 0.0 for value in short_r_values) else 0.0)
    )

    ending_capital = active_capital
    survives = ending_capital > 0.0
    if not survives or ending_capital <= start_capital or sum(r_values) <= 0.0 or profit_factor < 1.0:
        readiness = "NOT_READY_FOR_COMPOUNDING"
    elif max_drawdown_pct <= 0.22 and profit_factor >= 1.15 and moonshot_dependency <= 0.75:
        readiness = "READY_FOR_AGGRESSIVE_RESEARCH_ONLY_COMPOUNDING"
    elif max_drawdown_pct <= 0.22 and profit_factor >= 1.05 and moonshot_dependency <= 1.0:
        readiness = "READY_FOR_CONTROLLED_FULL_CAPITAL_COMPOUNDING"
    else:
        readiness = "READY_FOR_SMALL_COMPOUNDING"

    removed_long_r = sum(row["r_multiple"] for row in all_rows if row["trade_id"] not in selected_ids and row["side"] == "long")
    variant_summary = {
        "variant_name": name,
        "trade_count": len(replay_rows),
        "long_trade_count": sum(1 for row in replay_rows if row["side"] == "long"),
        "short_trade_count": sum(1 for row in replay_rows if row["side"] == "short"),
        "removed_trade_count": total_removed_trade_count,
        "ending_capital": round(ending_capital, 6),
        "total_return_pct": round(_safe_ratio(ending_capital - start_capital, start_capital, 0.0), 6),
        "total_R": round(sum(r_values), 6),
        "long_total_R": round(sum(long_r_values), 6),
        "short_total_R": round(sum(short_r_values), 6),
        "win_rate": round(_safe_ratio(len(wins), len(replay_rows), 0.0), 6),
        "long_win_rate": round(_safe_ratio(len(long_wins), len(long_r_values), 0.0), 6) if long_r_values else 0.0,
        "short_win_rate": round(_safe_ratio(len(short_wins), len(short_r_values), 0.0), 6) if short_r_values else 0.0,
        "profit_factor": round(profit_factor, 6),
        "long_profit_factor": round(long_profit_factor, 6),
        "short_profit_factor": round(short_profit_factor, 6),
        "avg_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
        "median_R": round(_median(r_values), 6) if r_values else 0.0,
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "max_drawdown_eur": round(max_drawdown_eur, 6),
        "worst_day_R": round(worst_day_r, 6),
        "best_day_R": round(best_day_r, 6),
        "monthly_geometric_return": round((pd.Series([1.0 + value for value in monthly_returns]).prod() ** (1 / len(monthly_returns)) - 1.0), 6) if monthly_returns else 0.0,
        "monthly_average_return": round(sum(monthly_returns) / len(monthly_returns), 6) if monthly_returns else 0.0,
        "monthly_median_return": round(_median(monthly_returns), 6) if monthly_returns else 0.0,
        "moonshot_5R_plus_count": sum(1 for row in replay_rows if row["applied_trade_R"] >= 5.0),
        "moonshot_8R_plus_count": sum(1 for row in replay_rows if row["applied_trade_R"] >= 8.0),
        "moonshot_10R_plus_count": sum(1 for row in replay_rows if row["applied_trade_R"] >= 10.0),
        "moonshot_R_total": round(sum(row["applied_trade_R"] for row in replay_rows if row["applied_trade_R"] >= 5.0), 6),
        "moonshot_profit_contribution_pct": round(moonshot_dependency, 6),
        "profit_without_moonshots": round(profit_without_moonshots, 6),
        "profit_with_10R_plus_capped_to_5R": round(profit_with_10R_plus_capped_to_5R, 6),
        "profit_with_all_5R_plus_capped_to_3R": round(profit_with_all_5R_plus_capped_to_3R, 6),
        "long_damage_removed_R": round(-removed_long_r, 6),
        "short_edge_preserved_R": round(selected_short_r, 6),
        "short_edge_preserved_pct": round(_safe_ratio(selected_short_r, sum(row["r_multiple"] for row in all_rows if row["side"] == "short"), 0.0), 6),
        "average_trades_per_day": round(average_trades_per_day, 6),
        "average_trades_per_active_day": round(average_trades_per_active_day, 6),
        "max_trades_one_day": max_trades_one_day,
        "cooldown_count": sum(1 for row in cooldown_rows if _timestamp(row.get("timestamp")) in {trade["exit_timestamp"] for trade in selected_rows}),
        "survives_full_active_capital_flag": survives,
        "readiness_classification": readiness,
        "moonshot_dependency_label": moonshot_dependency_label,
    }
    return {
        "summary": variant_summary,
        "trade_replay_rows": replay_rows,
        "daily_rows": daily_rows,
    }


def _score_variant(candidate: dict[str, Any], baseline: dict[str, Any]) -> float:
    score = 0.0
    score += (candidate["ending_capital"] - baseline["ending_capital"]) / 100.0
    score += (candidate["profit_factor"] - baseline["profit_factor"]) * 80.0
    score += (candidate["total_R"] - baseline["total_R"]) * 1.5
    score += (baseline["max_drawdown_pct"] - candidate["max_drawdown_pct"]) * 120.0
    score += (baseline["moonshot_profit_contribution_pct"] - candidate["moonshot_profit_contribution_pct"]) * 40.0
    score += candidate["short_edge_preserved_pct"] * 20.0
    if candidate["trade_count"] < max(50, baseline["trade_count"] * 0.2):
        score -= 35.0
    if candidate["max_trades_one_day"] < 1:
        score -= 20.0
    if candidate["monthly_median_return"] < baseline["monthly_median_return"] - 0.01:
        score -= 15.0
    if candidate["moonshot_dependency_label"] == "EXTREME_MOONSHOT_DEPENDENCY":
        score -= 20.0
    if candidate["moonshot_dependency_label"] == "NO_EDGE_WITHOUT_MOONSHOTS":
        score -= 35.0
    return round(score, 6)


def _rejection_reasons(candidate: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if candidate["trade_count"] < max(50, baseline["trade_count"] * 0.2):
        reasons.append("trade_count_too_small")
    if candidate["max_drawdown_pct"] > baseline["max_drawdown_pct"] + 0.02:
        reasons.append("max_drawdown_worsened_materially")
    if candidate["short_total_R"] < baseline["short_total_R"] * 0.7:
        reasons.append("short_edge_damaged")
    if candidate["moonshot_dependency_label"] in {"EXTREME_MOONSHOT_DEPENDENCY", "NO_EDGE_WITHOUT_MOONSHOTS"}:
        reasons.append("moonshot_dependency_remains_extreme")
    if candidate["monthly_median_return"] < baseline["monthly_median_return"] - 0.01:
        reasons.append("monthly_consistency_worsened")
    return reasons


def _best_patch_label(best_candidate: dict[str, Any]) -> str:
    name = best_candidate["variant_name"]
    if name == "LONGS_DISABLED_ALL_SHORTS_KEPT":
        return "PRESERVE_SHORTS_DISABLE_ALL_LONGS"
    if name == "BAD_LONG_ARCHETYPES_DISABLED_ALL_SHORTS_KEPT":
        return "PRESERVE_SHORTS_DISABLE_BAD_LONG_ARCHETYPES"
    if name == "BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT":
        return "PRESERVE_PROVEN_SHORTS_ONLY"
    if name == "ONLY_BEST_LONG_ARCHETYPES_ALL_SHORTS_KEPT":
        return "PRESERVE_SHORTS_KEEP_ONLY_PROVEN_LONGS"
    return "NO_PATCH_EDGE_TOO_THIN"


def _report_markdown(summary: dict[str, Any], best_candidate: dict[str, Any], recommendation: dict[str, Any]) -> str:
    lines = [
        "# Short Preservation + Long Damage Control Patch Audit",
        "",
        "## Scope",
        "",
        "- research_only: `true`",
        "- paper_allowed: `false`",
        "- live_allowed: `false`",
        "- real_money_allowed: `false`",
        "- behavior_change_allowed: `false`",
        "",
        "## Baseline",
        "",
        f"- ending capital: `{summary['baseline_ending_capital']}`",
        f"- profit factor: `{summary['baseline_profit_factor']}`",
        f"- max drawdown pct: `{summary['baseline_max_drawdown_pct']}`",
        f"- total R: `{summary['baseline_total_R']}`",
        "",
        "## Best patch candidate",
        "",
        f"- variant: `{best_candidate['variant_name']}`",
        f"- ending capital: `{best_candidate['ending_capital']}`",
        f"- profit factor: `{best_candidate['profit_factor']}`",
        f"- max drawdown pct: `{best_candidate['max_drawdown_pct']}`",
        f"- total R: `{best_candidate['total_R']}`",
        f"- moonshot dependency: `{best_candidate['moonshot_dependency_label']}`",
        f"- readiness classification: `{best_candidate['readiness_classification']}`",
        "",
        "## Recommendation",
        "",
        f"- recommended_patch: `{recommendation['recommended_research_only_patch']}`",
        f"- long_R_removed: `{best_candidate['long_damage_removed_R']}`",
        f"- short_R_preserved: `{best_candidate['short_edge_preserved_R']}`",
        "",
        "No runtime, strategy, allocator, or config defaults were changed.",
    ]
    return "\n".join(lines) + "\n"


def _empty_outputs(config: LongDamageControlPatchAuditConfig, *, warnings: list[str]) -> dict[str, Path]:
    output_root = config.output_root
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    status = {
        "state": "empty",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
        "warnings": warnings,
    }
    summary = {
        "research_only": True,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
        "warnings": warnings,
        "recommended_research_only_patch": "NO_PATCH_EDGE_TOO_THIN",
    }
    _write_json(output_root / "status.json", status)
    _write_json(output_root / "long_damage_control_patch_summary.json", summary)
    _write_markdown(output_root / "long_damage_control_patch_report.md", "# Long Damage Control Patch Audit\n\nNo usable structural patch artifacts were available.\n")
    for name in (
        "patch_variant_summary.csv",
        "patch_variant_trade_replay.csv",
        "disabled_long_archetype_impact.csv",
        "preserved_short_edge_impact.csv",
        "full_capital_compounding_after_patch.csv",
        "drawdown_after_patch.csv",
    ):
        _write_csv(diagnostics_root / name, [])
    for name in (
        "moonshot_dependency_after_patch.json",
        "best_patch_candidate.json",
        "rejected_patch_candidates.json",
        "research_only_patch_recommendation.json",
    ):
        _write_json(diagnostics_root / name, {"research_only": True, "warnings": warnings})
    _write_json(reports_root / "next_research_recommendation.json", {"research_only": True, "warnings": warnings})
    return {
        "status": output_root / "status.json",
        "summary": output_root / "long_damage_control_patch_summary.json",
        "report": output_root / "long_damage_control_patch_report.md",
    }


def write_long_damage_control_patch_audit(config: LongDamageControlPatchAuditConfig) -> dict[str, Path]:
    paths = _artifact_paths(config)
    trade_rows = _read_csv_rows(paths["trades"])
    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    cooldown_rows = _read_csv_rows(paths["cooldown_log"])
    pyramiding_rows = _read_csv_rows(paths["pyramiding_log"])
    five_year_summary = _read_json(paths["five_year_summary"], {})
    long_short_summary = _read_json(paths["long_short_summary"], {})
    definition_refinement_summary = _read_json(paths["definition_refinement_summary"], {})
    daily_structural_summary = _read_json(paths["daily_structural_summary"], {})

    normalized_rows = _normalize_trade_rows(trade_rows, setup_rows, level_rows, liquidity_rows)
    if not normalized_rows:
        return _empty_outputs(config, warnings=["no_usable_trades_for_long_damage_control_patch_audit"])

    prepared_rows = _prepare_rows(normalized_rows)
    proven_shorts = _proven_short_archetypes(prepared_rows)
    best_longs = _best_long_archetypes(prepared_rows)

    baseline_start = min((row["exit_timestamp"] for row in prepared_rows if row["exit_timestamp"] is not None), default=None)
    baseline_end = max((row["exit_timestamp"] for row in prepared_rows if row["exit_timestamp"] is not None), default=None)
    baseline_span_days = max(1, int((baseline_end - baseline_start).days) + 1) if baseline_start is not None and baseline_end is not None else 1

    variant_rows: dict[str, list[dict[str, Any]]] = {
        "BASELINE_CURRENT_SEQUENCE": list(prepared_rows),
        "LONGS_DISABLED_ALL_SHORTS_KEPT": [row for row in prepared_rows if row["side"] == "short"],
        "BAD_LONG_ARCHETYPES_DISABLED_ALL_SHORTS_KEPT": [
            row for row in prepared_rows
            if row["side"] == "short" or row.get("long_failure_mode") not in BAD_LONG_DISABLE_SET
        ],
        "ONLY_BEST_LONG_ARCHETYPES_ALL_SHORTS_KEPT": [
            row for row in prepared_rows
            if row["side"] == "short" or row["archetype_key"] in best_longs
        ],
        "BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT": [
            row for row in prepared_rows
            if (row["side"] == "short" and row["archetype_key"] in proven_shorts)
            or (row["side"] == "long" and row.get("long_failure_mode") not in BAD_LONG_DISABLE_SET)
        ],
        "SHORTS_ONLY_PROVEN_BUCKETS": [row for row in prepared_rows if row["side"] == "short" and row["archetype_key"] in proven_shorts],
        "LONGS_ONLY_BEST_BUCKETS": [row for row in prepared_rows if row["side"] == "long" and row["archetype_key"] in best_longs],
    }

    variant_outputs: dict[str, dict[str, Any]] = {}
    for name in list(variant_rows.keys()):
        variant_outputs[name] = _simulate_variant(
            name=name,
            selected_rows=variant_rows[name],
            all_rows=prepared_rows,
            start_capital=20000.0,
            baseline_span_days=baseline_span_days,
            cooldown_rows=cooldown_rows,
        )

    pre_moonshot_candidates = [
        variant_outputs[name]["summary"]
        for name in (
            "LONGS_DISABLED_ALL_SHORTS_KEPT",
            "BAD_LONG_ARCHETYPES_DISABLED_ALL_SHORTS_KEPT",
            "ONLY_BEST_LONG_ARCHETYPES_ALL_SHORTS_KEPT",
            "BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT",
            "SHORTS_ONLY_PROVEN_BUCKETS",
            "LONGS_ONLY_BEST_BUCKETS",
        )
        if name in variant_outputs
    ]
    baseline_summary = variant_outputs["BASELINE_CURRENT_SEQUENCE"]["summary"]
    scored_candidates = [
        {**candidate, "weighted_score": _score_variant(candidate, baseline_summary)}
        for candidate in pre_moonshot_candidates
    ]
    scored_candidates.sort(key=lambda row: row["weighted_score"], reverse=True)
    best_pre_moonshot = scored_candidates[0] if scored_candidates else baseline_summary
    best_pre_rows = variant_rows.get(best_pre_moonshot["variant_name"], prepared_rows)

    variant_outputs["MOONSHOT_CAPPED_PATCH"] = _simulate_variant(
        name="MOONSHOT_CAPPED_PATCH",
        selected_rows=best_pre_rows,
        all_rows=prepared_rows,
        start_capital=20000.0,
        baseline_span_days=baseline_span_days,
        cooldown_rows=cooldown_rows,
        moonshot_override="cap_5_to_3",
    )
    variant_outputs["MOONSHOT_REMOVED_PATCH"] = _simulate_variant(
        name="MOONSHOT_REMOVED_PATCH",
        selected_rows=best_pre_rows,
        all_rows=prepared_rows,
        start_capital=20000.0,
        baseline_span_days=baseline_span_days,
        cooldown_rows=cooldown_rows,
        moonshot_override="remove_5_plus",
    )

    variant_summaries = [variant_outputs[name]["summary"] for name in PATCH_VARIANTS if name in variant_outputs]
    scored_all = [{**summary, "weighted_score": _score_variant(summary, baseline_summary)} for summary in variant_summaries if summary["variant_name"] != "BASELINE_CURRENT_SEQUENCE"]
    scored_all.sort(key=lambda row: row["weighted_score"], reverse=True)
    best_candidate = scored_all[0] if scored_all else baseline_summary
    best_patch_candidate = {
        **best_candidate,
        "recommended_patch_label": _best_patch_label(best_candidate),
    }

    rejected_candidates = []
    for candidate in scored_all[1:]:
        reasons = _rejection_reasons(candidate, baseline_summary)
        rejected_candidates.append(
            {
                "variant_name": candidate["variant_name"],
                "weighted_score": candidate["weighted_score"],
                "rejection_reasons": reasons or ["not_top_ranked_candidate"],
            }
        )

    disabled_long_impact_rows = []
    baseline_pf = baseline_summary["profit_factor"]
    baseline_capital = baseline_summary["ending_capital"]
    baseline_drawdown = baseline_summary["max_drawdown_pct"]
    for failure_mode in sorted(BAD_LONG_DISABLE_SET):
        filtered_rows = [row for row in prepared_rows if not (row["side"] == "long" and row["long_failure_mode"] == failure_mode)]
        candidate = _simulate_variant(
            name=f"DISABLE_{failure_mode}",
            selected_rows=filtered_rows,
            all_rows=prepared_rows,
            start_capital=20000.0,
            baseline_span_days=baseline_span_days,
            cooldown_rows=cooldown_rows,
        )["summary"]
        removed_bucket = [row for row in prepared_rows if row["side"] == "long" and row["long_failure_mode"] == failure_mode]
        disabled_long_impact_rows.append(
            {
                "archetype_or_failure_mode": failure_mode,
                "trade_count_removed": len(removed_bucket),
                "R_removed": round(sum(row["r_multiple"] for row in removed_bucket), 6),
                "loss_R_removed": round(sum(row["r_multiple"] for row in removed_bucket if row["r_multiple"] < 0.0), 6),
                "winner_R_removed": round(sum(row["r_multiple"] for row in removed_bucket if row["r_multiple"] > 0.0), 6),
                "moonshot_R_removed": round(sum(row["r_multiple"] for row in removed_bucket if row["r_multiple"] >= 5.0), 6),
                "profit_factor_before": baseline_pf,
                "profit_factor_after": candidate["profit_factor"],
                "ending_capital_before": baseline_capital,
                "ending_capital_after": candidate["ending_capital"],
                "drawdown_before": baseline_drawdown,
                "drawdown_after": candidate["max_drawdown_pct"],
                "disable_recommendation": "disable_in_future_research_patch" if candidate["ending_capital"] > baseline_capital and candidate["profit_factor"] >= baseline_pf else "do_not_disable_blindly",
                "reason": "long_damage_control_screen",
            }
        )

    preserved_short_rows = []
    short_mode_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in prepared_rows:
        if row["side"] == "short" and row["short_success_mode"]:
            short_mode_groups[row["short_success_mode"]].append(row)
    for mode, bucket in sorted(short_mode_groups.items()):
        metrics = _aggregate_metrics(bucket)
        preserved_short_rows.append(
            {
                "short_success_mode": mode,
                "trade_count": metrics["trade_count"],
                "total_R": metrics["total_R"],
                "avg_R": metrics["avg_R"],
                "profit_factor": metrics["profit_factor"],
                "moonshot_count": metrics["moonshot_count"],
                "moonshot_R": metrics["moonshot_R_total"],
                "drawdown_contribution": metrics["drawdown_contribution"],
                "preserve_recommendation": "PRESERVE" if mode in {"SHORT_SWEEP_HIGH_REJECTION", "SHORT_BREAKDOWN_RETEST"} or metrics["total_R"] > 0.0 else "REVIEW",
                "reason": (
                    "Do not damage SHORT_SWEEP_HIGH_REJECTION unless later evidence contradicts it."
                    if mode == "SHORT_SWEEP_HIGH_REJECTION"
                    else "Do not damage SHORT_BREAKDOWN_RETEST unless later evidence contradicts it."
                    if mode == "SHORT_BREAKDOWN_RETEST"
                    else "positive short edge contribution"
                ),
            }
        )

    moonshot_dependency_after_patch = {}
    for summary in variant_summaries:
        moonshot_dependency_after_patch[summary["variant_name"]] = {
            "normal_result": {
                "ending_capital": summary["ending_capital"],
                "profit_factor": summary["profit_factor"],
                "total_R": summary["total_R"],
            },
            "result_without_5R_plus": summary["profit_without_moonshots"],
            "result_with_10R_plus_capped_to_5R": summary["profit_with_10R_plus_capped_to_5R"],
            "result_with_all_5R_plus_capped_to_3R": summary["profit_with_all_5R_plus_capped_to_3R"],
            "moonshot_dependency_label": summary["moonshot_dependency_label"],
        }

    recommendation_patch = _best_patch_label(best_patch_candidate)
    if best_patch_candidate["profit_factor"] <= baseline_summary["profit_factor"]:
        recommendation_patch = "NO_PATCH_EDGE_TOO_THIN"
    recommendation = {
        "research_only": True,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
        "best_patch_candidate": best_patch_candidate["variant_name"],
        "recommended_research_only_patch": recommendation_patch,
        "baseline_variant": baseline_summary["variant_name"],
        "do_not_touch_rules": [
            "do_not_change_live_strategy_logic",
            "do_not_change_paper_strategy_logic",
            "do_not_change_allocator_behavior",
            "do_not_change_config_defaults",
        ],
        "baseline_readiness": baseline_summary["readiness_classification"],
        "best_patch_readiness": best_patch_candidate["readiness_classification"],
    }

    report_summary = {
        "baseline_ending_capital": baseline_summary["ending_capital"],
        "baseline_profit_factor": baseline_summary["profit_factor"],
        "baseline_max_drawdown_pct": baseline_summary["max_drawdown_pct"],
        "baseline_total_R": baseline_summary["total_R"],
    }
    report = _report_markdown(report_summary, best_patch_candidate, recommendation)

    patch_variant_replay_rows = [
        row
        for name in PATCH_VARIANTS
        if name in variant_outputs
        for row in variant_outputs[name]["trade_replay_rows"]
    ]
    full_capital_curve_rows = [
        row
        for name in PATCH_VARIANTS
        if name in variant_outputs
        for row in variant_outputs[name]["daily_rows"]
    ]
    drawdown_rows = [
        {
            "variant_name": summary["variant_name"],
            "ending_capital": summary["ending_capital"],
            "max_drawdown_pct": summary["max_drawdown_pct"],
            "max_drawdown_eur": summary["max_drawdown_eur"],
            "worst_day_R": summary["worst_day_R"],
            "best_day_R": summary["best_day_R"],
        }
        for summary in variant_summaries
    ]

    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
        "baseline_variant": baseline_summary["variant_name"],
        "baseline_ending_capital": baseline_summary["ending_capital"],
        "baseline_profit_factor": baseline_summary["profit_factor"],
        "baseline_max_drawdown_pct": baseline_summary["max_drawdown_pct"],
        "baseline_total_R": baseline_summary["total_R"],
        "best_patch_candidate": best_patch_candidate["variant_name"],
        "best_patch_ending_capital": best_patch_candidate["ending_capital"],
        "best_patch_profit_factor": best_patch_candidate["profit_factor"],
        "best_patch_max_drawdown_pct": best_patch_candidate["max_drawdown_pct"],
        "best_patch_total_R": best_patch_candidate["total_R"],
        "long_R_removed": best_patch_candidate["long_damage_removed_R"],
        "short_R_preserved": best_patch_candidate["short_edge_preserved_R"],
        "trade_count_after_patch": best_patch_candidate["trade_count"],
        "moonshot_dependency_after_patch": best_patch_candidate["moonshot_dependency_label"],
        "profit_without_moonshots_after_patch": best_patch_candidate["profit_without_moonshots"],
        "readiness_classification_after_patch": best_patch_candidate["readiness_classification"],
        "recommended_research_only_patch": recommendation_patch,
        "five_year_readiness_classification": five_year_summary.get("compounding_readiness_classification"),
        "long_short_repair_recommendation": long_short_summary.get("recommended_next_research_patch"),
        "daily_definition_classification": definition_refinement_summary.get("classification") or daily_structural_summary.get("classification"),
    }

    output_root = config.output_root
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    status = {
        "state": "complete",
        "resolved_at_utc": summary["resolved_at_utc"],
        "research_only": True,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
    }
    _write_json(output_root / "status.json", status)
    _write_json(output_root / "long_damage_control_patch_summary.json", summary)
    _write_markdown(output_root / "long_damage_control_patch_report.md", report)
    _write_csv(diagnostics_root / "patch_variant_summary.csv", variant_summaries)
    _write_csv(diagnostics_root / "patch_variant_trade_replay.csv", patch_variant_replay_rows)
    _write_csv(diagnostics_root / "disabled_long_archetype_impact.csv", disabled_long_impact_rows)
    _write_csv(diagnostics_root / "preserved_short_edge_impact.csv", preserved_short_rows)
    _write_json(diagnostics_root / "moonshot_dependency_after_patch.json", moonshot_dependency_after_patch)
    _write_csv(diagnostics_root / "full_capital_compounding_after_patch.csv", full_capital_curve_rows)
    _write_csv(diagnostics_root / "drawdown_after_patch.csv", drawdown_rows)
    _write_json(diagnostics_root / "best_patch_candidate.json", best_patch_candidate)
    _write_json(diagnostics_root / "rejected_patch_candidates.json", rejected_candidates)
    _write_json(diagnostics_root / "research_only_patch_recommendation.json", recommendation)
    _write_json(reports_root / "next_research_recommendation.json", recommendation)
    return {
        "status": output_root / "status.json",
        "summary": output_root / "long_damage_control_patch_summary.json",
        "report": output_root / "long_damage_control_patch_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    config = LongDamageControlPatchAuditConfig(
        package_root=package_root,
        output_root=package_root / "output" / "long_damage_control_patch_audit_001",
    )
    result = write_long_damage_control_patch_audit(config)
    print(result["summary"])


if __name__ == "__main__":
    main()
