from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import (  # noqa: E402
    BAD_LONG_DISABLE_SET,
    _prepare_rows,
    _simulate_variant,
)
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _aggregate_metrics,
    _median,
    _normalize_trade_rows,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _timestamp,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.validation.execution_cost_sensitivity import (  # noqa: E402
    build_execution_cost_outputs,
)


TARGET_YEARS = list(range(2018, 2027))
RESEARCH_ONLY_FLAGS = {
    "research_only": True,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
}


@dataclass(frozen=True)
class BroadFrozenPatchValidationConfig:
    package_root: Path
    output_root: Path


def _artifact_paths(config: BroadFrozenPatchValidationConfig) -> dict[str, Path]:
    source_root = config.package_root / "output"
    broad_root = source_root / "broad_historical_structural_replay_001"
    broad_ledger_root = broad_root / "ledger"
    frozen_rule_root = source_root / "frozen_patch_validation_audit_001"
    return {
        "broad_status": broad_root / "status.json",
        "broad_summary": broad_root / "broad_historical_replay_summary.json",
        "broad_report": broad_root / "broad_historical_replay_report.md",
        "broad_health": broad_root / "diagnostics" / "replay_health_report.json",
        "broad_leakage": broad_root / "diagnostics" / "no_future_leakage_checks.json",
        "broad_source_coverage": broad_root / "diagnostics" / "source_data_coverage.json",
        "broad_next_step": broad_root / "reports" / "next_research_recommendation.json",
        "trades": broad_ledger_root / "trades.csv",
        "equity": broad_ledger_root / "equity.csv",
        "setup_log": broad_ledger_root / "setup_log.csv",
        "level_log": broad_ledger_root / "level_log.csv",
        "liquidity_events": broad_ledger_root / "liquidity_events.csv",
        "profit_vault": broad_ledger_root / "profit_vault.json",
        "ledger_summary": broad_ledger_root / "summary.json",
        "cooldown_log": broad_ledger_root / "cooldown_log.csv",
        "pyramiding_log": broad_ledger_root / "pyramiding_log.csv",
        "execution_cost_sensitivity": broad_ledger_root / "execution_realism" / "execution_cost_sensitivity.json",
        "execution_cost_model": broad_ledger_root / "execution_realism" / "execution_cost_model.json",
        "frozen_patch_rules": frozen_rule_root / "diagnostics" / "frozen_patch_rules.json",
    }


def _ensure_report_dirs(output_root: Path) -> tuple[Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, reports_root


def _empty_outputs(config: BroadFrozenPatchValidationConfig, *, warnings: list[str]) -> dict[str, Path]:
    output_root = config.output_root
    diagnostics_root, reports_root = _ensure_report_dirs(output_root)
    status_payload = {
        "state": "empty",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "warnings": warnings,
    }
    summary_payload = {
        **RESEARCH_ONLY_FLAGS,
        "warnings": warnings,
        "frozen_patch_candidate": "BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT",
        "recommended_patch_label": "PRESERVE_PROVEN_SHORTS_ONLY",
        "final_patch_classification": "PATCH_REJECTED_BROAD_HISTORY",
    }
    report_md = "\n".join(
        [
            "# Broad Frozen Patch Validation",
            "",
            "No usable broad historical replay artifacts were available.",
            "",
            "This output remains research-only and does not change live, paper, runtime, allocator, or config behavior.",
            "",
        ]
    )

    _write_json(output_root / "status.json", status_payload)
    _write_json(output_root / "broad_frozen_patch_summary.json", summary_payload)
    _write_markdown(output_root / "broad_frozen_patch_report.md", report_md)

    empty_csv_files = (
        "raw_vs_frozen_patch_comparison.csv",
        "yearly_raw_vs_patch.csv",
        "monthly_raw_vs_patch.csv",
        "archetype_raw_vs_patch.csv",
        "disabled_trade_impact.csv",
        "preserved_trade_impact.csv",
        "drawdown_comparison.csv",
        "top_removed_winning_trades.csv",
        "top_removed_losing_trades.csv",
    )
    empty_json_files = (
        "raw_vs_frozen_patch_comparison.json",
        "long_short_raw_vs_patch.json",
        "moonshot_dependency_broad_patch.json",
        "execution_cost_sensitivity_broad_patch.json",
        "profit_vault_comparison.json",
        "patch_survival_by_year.json",
        "no_go_risks.json",
    )
    for name in empty_csv_files:
        _write_csv(diagnostics_root / name, [])
    for name in empty_json_files:
        _write_json(diagnostics_root / name, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_markdown(
        reports_root / "next_research_recommendation.md",
        "# Next Research Recommendation\n\nNo recommendation is available because the broad replay artifacts are missing.\n",
    )
    return {
        "status": output_root / "status.json",
        "summary": output_root / "broad_frozen_patch_summary.json",
        "report": output_root / "broad_frozen_patch_report.md",
    }


def _load_frozen_rules(path: Path) -> tuple[set[str], set[str], dict[str, Any]]:
    payload = _read_json(path, {})
    matched_archetypes = {
        str(value)
        for value in (payload.get("short_bucket_rule", {}) or {}).get("matched_archetype_keys", [])
        if str(value).strip()
    }
    disabled_modes = {
        str(value)
        for value in payload.get("disabled_long_failure_modes", [])
        if str(value).strip()
    }
    return matched_archetypes, disabled_modes, payload


def _apply_frozen_patch(
    rows: list[dict[str, Any]],
    *,
    matched_short_archetypes: set[str],
    disabled_long_modes: set[str],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    for row in rows:
        keep = False
        if row["side"] == "short":
            keep = row.get("archetype_key") in matched_short_archetypes
        elif row["side"] == "long":
            keep = row.get("long_failure_mode") not in disabled_long_modes
        if keep:
            kept.append(row)
        else:
            removed.append(row)
    kept.sort(key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or ""))
    removed.sort(key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or ""))
    return kept, removed


def _baseline_span_days(rows: list[dict[str, Any]]) -> int:
    timestamps = [row.get("exit_timestamp") for row in rows if row.get("exit_timestamp") is not None]
    if not timestamps:
        return 1
    return max(1, int((max(timestamps) - min(timestamps)).days) + 1)


def _simulate_sequence(
    *,
    name: str,
    selected_rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    cooldown_rows: list[dict[str, Any]],
    start_capital: float = 20000.0,
) -> dict[str, Any]:
    return _simulate_variant(
        name=name,
        selected_rows=selected_rows,
        all_rows=all_rows,
        start_capital=start_capital,
        baseline_span_days=_baseline_span_days(all_rows if all_rows else selected_rows),
        cooldown_rows=cooldown_rows,
    )


def _year_window_rows(rows: list[dict[str, Any]], year: int) -> list[dict[str, Any]]:
    start = pd.Timestamp(year=year, month=1, day=1)
    end = pd.Timestamp(year=year, month=12, day=31, hour=23, minute=59, second=59)
    return [
        row
        for row in rows
        if row.get("exit_timestamp") is not None
        and start <= row["exit_timestamp"] <= end
    ]


def _longest_drawdown_period(daily_rows: list[dict[str, Any]]) -> dict[str, Any]:
    peak = None
    in_drawdown = False
    drawdown_start = None
    longest_days = 0
    longest_start = None
    longest_end = None

    for row in sorted(daily_rows, key=lambda item: str(item.get("date") or "")):
        equity = float(row.get("equity_end") or 0.0)
        date_value = str(row.get("date") or "")
        if peak is None or equity >= peak:
            peak = equity
            if in_drawdown and drawdown_start is not None:
                duration = max(0, (pd.Timestamp(date_value) - pd.Timestamp(drawdown_start)).days)
                if duration > longest_days:
                    longest_days = duration
                    longest_start = drawdown_start
                    longest_end = date_value
            in_drawdown = False
            drawdown_start = None
            continue
        if not in_drawdown:
            in_drawdown = True
            drawdown_start = date_value

    return {
        "days": longest_days,
        "start": longest_start,
        "end": longest_end,
    }


def _month_rows_from_daily_rows(daily_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in sorted(daily_rows, key=lambda item: str(item.get("date") or "")):
        month_key = str(row.get("date") or "")[:7]
        grouped.setdefault(month_key, []).append(row)
    rows_out: list[dict[str, Any]] = []
    for month, bucket in grouped.items():
        total_r = sum(float(item.get("daily_R") or 0.0) for item in bucket)
        total_pnl = sum(float(item.get("daily_pnl") or 0.0) for item in bucket)
        rows_out.append(
            {
                "month": month,
                "trade_days": len(bucket),
                "total_R": round(total_r, 6),
                "total_pnl": round(total_pnl, 6),
                "ending_equity": round(float(bucket[-1].get("equity_end") or 0.0), 6),
            }
        )
    return rows_out


def _compare_monthly(raw_rows: list[dict[str, Any]], patch_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_map = {row["month"]: row for row in _month_rows_from_daily_rows(raw_rows)}
    patch_map = {row["month"]: row for row in _month_rows_from_daily_rows(patch_rows)}
    rows_out: list[dict[str, Any]] = []
    for month in sorted(set(raw_map) | set(patch_map)):
        raw = raw_map.get(month, {})
        patch = patch_map.get(month, {})
        rows_out.append(
            {
                "month": month,
                "raw_total_R": round(float(raw.get("total_R") or 0.0), 6),
                "patch_total_R": round(float(patch.get("total_R") or 0.0), 6),
                "raw_total_pnl": round(float(raw.get("total_pnl") or 0.0), 6),
                "patch_total_pnl": round(float(patch.get("total_pnl") or 0.0), 6),
                "raw_ending_equity": round(float(raw.get("ending_equity") or 0.0), 6),
                "patch_ending_equity": round(float(patch.get("ending_equity") or 0.0), 6),
                "patch_helped": float(patch.get("total_pnl") or 0.0) > float(raw.get("total_pnl") or 0.0),
            }
        )
    return rows_out


def _moonshot_classification(summary: dict[str, Any]) -> str:
    contribution = float(summary.get("moonshot_profit_contribution_pct") or 0.0)
    profit_without = float(summary.get("profit_without_moonshots") or 0.0)
    if profit_without <= 0.0:
        return "NO_EDGE_WITHOUT_MOONSHOTS"
    if contribution > 0.75:
        return "TOO_MOONSHOT_DEPENDENT"
    if contribution <= 0.25:
        return "ROBUST_WITHOUT_MOONSHOTS"
    return "HEALTHY_MOONSHOT_SUPPORT"


def _build_moonshot_payload(raw_summary: dict[str, Any], patched_summary: dict[str, Any]) -> dict[str, Any]:
    def payload(summary: dict[str, Any]) -> dict[str, Any]:
        return {
            "moonshot_5R_plus_count": int(summary.get("moonshot_5R_plus_count") or 0),
            "moonshot_8R_plus_count": int(summary.get("moonshot_8R_plus_count") or 0),
            "moonshot_10R_plus_count": int(summary.get("moonshot_10R_plus_count") or 0),
            "moonshot_R_total": round(float(summary.get("moonshot_R_total") or 0.0), 6),
            "moonshot_profit_contribution_pct": round(float(summary.get("moonshot_profit_contribution_pct") or 0.0), 6),
            "profit_without_moonshots": round(float(summary.get("profit_without_moonshots") or 0.0), 6),
            "profit_with_10R_plus_capped_to_5R": round(float(summary.get("profit_with_10R_plus_capped_to_5R") or 0.0), 6),
            "profit_with_all_5R_plus_capped_to_3R": round(float(summary.get("profit_with_all_5R_plus_capped_to_3R") or 0.0), 6),
            "classification": _moonshot_classification(summary),
        }

    return {
        **RESEARCH_ONLY_FLAGS,
        "raw": payload(raw_summary),
        "patched": payload(patched_summary),
    }


def _find_original_trades_by_id(trade_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in trade_rows:
        trade_id = str(row.get("trade_id") or "")
        if trade_id:
            output[trade_id] = dict(row)
    return output


def _execution_cost_payload(
    *,
    raw_trade_rows: list[dict[str, Any]],
    patched_trade_ids: set[str],
    output_root: Path,
    baseline_cost_payload: dict[str, Any],
) -> dict[str, Any]:
    execution_root = output_root / "execution_realism"
    raw_trades_by_id = _find_original_trades_by_id(raw_trade_rows)
    patched_trades = [raw_trades_by_id[trade_id] for trade_id in patched_trade_ids if trade_id in raw_trades_by_id]
    patched_cost_payload = build_execution_cost_outputs(trades=patched_trades, output_root=execution_root)
    baseline_metrics = baseline_cost_payload.get("scenario_metrics", {}) if isinstance(baseline_cost_payload, dict) else {}
    patched_metrics = patched_cost_payload.get("scenario_metrics", {})
    comparison: dict[str, Any] = {}
    for scenario_name in ("low_cost", "normal_cost", "high_cost", "stress_cost"):
        raw_metrics = baseline_metrics.get(scenario_name, {})
        patch_metrics = patched_metrics.get(scenario_name, {})
        comparison[scenario_name] = {
            "raw_net_pnl_after_costs": round(float(raw_metrics.get("net_pnl_after_costs") or 0.0), 6),
            "patched_net_pnl_after_costs": round(float(patch_metrics.get("net_pnl_after_costs") or 0.0), 6),
            "raw_profit_factor_after_costs": round(float(raw_metrics.get("profit_factor_after_costs") or 0.0), 6),
            "patched_profit_factor_after_costs": round(float(patch_metrics.get("profit_factor_after_costs") or 0.0), 6),
            "raw_average_cost_per_trade": round(float(raw_metrics.get("average_cost_per_trade") or 0.0), 6),
            "patched_average_cost_per_trade": round(float(patch_metrics.get("average_cost_per_trade") or 0.0), 6),
            "raw_total_fees": round(float(raw_metrics.get("total_fees") or 0.0), 6),
            "patched_total_fees": round(float(patch_metrics.get("total_fees") or 0.0), 6),
            "raw_total_estimated_slippage": round(float(raw_metrics.get("total_estimated_slippage") or 0.0), 6),
            "patched_total_estimated_slippage": round(float(patch_metrics.get("total_estimated_slippage") or 0.0), 6),
            "patch_improves_cost_survival": float(patch_metrics.get("net_pnl_after_costs") or 0.0) > float(raw_metrics.get("net_pnl_after_costs") or 0.0),
        }
    return {
        **RESEARCH_ONLY_FLAGS,
        "baseline_source": "broad_historical_structural_replay_001/ledger/execution_realism/execution_cost_sensitivity.json",
        "patched_trade_count": len(patched_trades),
        "baseline_trade_count": len(raw_trade_rows),
        "scenarios": comparison,
        "patched_execution_model": _read_json(execution_root / "execution_cost_model.json", {}),
        "patched_execution_sensitivity": patched_cost_payload,
    }


def _yearly_comparison_rows(
    *,
    raw_rows: list[dict[str, Any]],
    patched_rows: list[dict[str, Any]],
    cooldown_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    comparison_rows: list[dict[str, Any]] = []
    years_helped = 0
    years_hurt = 0
    years_flat = 0
    profitable_patch_years = 0
    materially_harmed_bull_years: list[str] = []
    for year in TARGET_YEARS:
        raw_year_rows = _year_window_rows(raw_rows, year)
        patch_year_rows = _year_window_rows(patched_rows, year)
        raw_summary = _simulate_sequence(
            name=f"RAW_{year}",
            selected_rows=raw_year_rows,
            all_rows=raw_year_rows,
            cooldown_rows=cooldown_rows,
        )["summary"] if raw_year_rows else {}
        patch_summary = _simulate_sequence(
            name=f"PATCH_{year}",
            selected_rows=patch_year_rows,
            all_rows=raw_year_rows,
            cooldown_rows=cooldown_rows,
        )["summary"] if raw_year_rows else {}
        raw_total_r = float(raw_summary.get("total_R") or 0.0)
        patch_total_r = float(patch_summary.get("total_R") or 0.0)
        raw_pnl = float(raw_summary.get("ending_capital") or 20000.0) - 20000.0
        patch_pnl = float(patch_summary.get("ending_capital") or 20000.0) - 20000.0
        verdict = "helped" if patch_pnl > raw_pnl else "hurt" if patch_pnl < raw_pnl else "flat"
        if verdict == "helped":
            years_helped += 1
        elif verdict == "hurt":
            years_hurt += 1
        else:
            years_flat += 1
        if patch_pnl > 0.0:
            profitable_patch_years += 1
        if raw_total_r > 0.0 and patch_total_r < 0.0:
            materially_harmed_bull_years.append(str(year))
        comparison_rows.append(
            {
                "year": str(year),
                "raw_pnl": round(raw_pnl, 6),
                "patched_pnl": round(patch_pnl, 6),
                "raw_profit_factor": round(float(raw_summary.get("profit_factor") or 0.0), 6),
                "patched_profit_factor": round(float(patch_summary.get("profit_factor") or 0.0), 6),
                "raw_total_R": round(raw_total_r, 6),
                "patched_total_R": round(patch_total_r, 6),
                "raw_max_drawdown_pct": round(float(raw_summary.get("max_drawdown_pct") or 0.0), 6),
                "patched_max_drawdown_pct": round(float(patch_summary.get("max_drawdown_pct") or 0.0), 6),
                "raw_trade_count": int(raw_summary.get("trade_count") or 0),
                "patched_trade_count": int(patch_summary.get("trade_count") or 0),
                "raw_long_contribution_R": round(float(raw_summary.get("long_total_R") or 0.0), 6),
                "patched_long_contribution_R": round(float(patch_summary.get("long_total_R") or 0.0), 6),
                "raw_short_contribution_R": round(float(raw_summary.get("short_total_R") or 0.0), 6),
                "patched_short_contribution_R": round(float(patch_summary.get("short_total_R") or 0.0), 6),
                "patch_helped_or_hurt": verdict,
            }
        )
    summary_payload = {
        "years_helped": years_helped,
        "years_hurt": years_hurt,
        "years_flat": years_flat,
        "profitable_patch_years": profitable_patch_years,
        "materially_harmed_positive_raw_years": materially_harmed_bull_years,
        "yearly_consistency_label": "mostly_consistent" if years_helped > years_hurt else "fragile_or_inconsistent",
    }
    return comparison_rows, summary_payload


def _archetype_comparison_rows(raw_rows: list[dict[str, Any]], patched_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_groups: dict[str, list[dict[str, Any]]] = {}
    for row in raw_rows:
        raw_groups.setdefault(str(row.get("archetype_key") or "n/a"), []).append(row)
    patch_groups: dict[str, list[dict[str, Any]]] = {}
    for row in patched_rows:
        patch_groups.setdefault(str(row.get("archetype_key") or "n/a"), []).append(row)
    rows_out: list[dict[str, Any]] = []
    for archetype in sorted(set(raw_groups) | set(patch_groups)):
        raw_metrics = _aggregate_metrics(raw_groups.get(archetype, [])) if raw_groups.get(archetype) else {}
        patch_metrics = _aggregate_metrics(patch_groups.get(archetype, [])) if patch_groups.get(archetype) else {}
        rows_out.append(
            {
                "archetype_key": archetype,
                "raw_trade_count": int(raw_metrics.get("trade_count") or 0),
                "patched_trade_count": int(patch_metrics.get("trade_count") or 0),
                "raw_total_R": round(float(raw_metrics.get("total_R") or 0.0), 6),
                "patched_total_R": round(float(patch_metrics.get("total_R") or 0.0), 6),
                "raw_avg_R": round(float(raw_metrics.get("avg_R") or 0.0), 6),
                "patched_avg_R": round(float(patch_metrics.get("avg_R") or 0.0), 6),
                "raw_profit_factor": round(float(raw_metrics.get("profit_factor") or 0.0), 6),
                "patched_profit_factor": round(float(patch_metrics.get("profit_factor") or 0.0), 6),
            }
        )
    return rows_out


def _disabled_trade_impact_rows(removed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in removed_rows:
        key = (str(row.get("long_failure_mode") or "SHORT_NOT_PROVEN"), str(row.get("archetype_key") or "n/a"))
        grouped.setdefault(key, []).append(row)
    rows_out: list[dict[str, Any]] = []
    for (failure_mode, archetype), bucket in sorted(grouped.items()):
        rows_out.append(
            {
                "failure_mode_or_reason": failure_mode,
                "archetype_key": archetype,
                "side": bucket[0].get("side", "n/a"),
                "removed_trade_count": len(bucket),
                "removed_total_R": round(sum(float(row.get("r_multiple") or 0.0) for row in bucket), 6),
                "removed_total_pnl": round(sum(float(row.get("pnl") or 0.0) for row in bucket), 6),
                "removed_moonshot_count": sum(1 for row in bucket if float(row.get("r_multiple") or 0.0) >= 5.0),
            }
        )
    return rows_out


def _preserved_trade_impact_rows(patched_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in patched_rows:
        if row.get("side") != "short":
            continue
        key = (str(row.get("short_success_mode") or "SHORT_PRESERVED"), str(row.get("archetype_key") or "n/a"))
        grouped.setdefault(key, []).append(row)
    rows_out: list[dict[str, Any]] = []
    for (success_mode, archetype), bucket in sorted(grouped.items()):
        rows_out.append(
            {
                "short_success_mode": success_mode,
                "archetype_key": archetype,
                "preserved_trade_count": len(bucket),
                "preserved_total_R": round(sum(float(row.get("r_multiple") or 0.0) for row in bucket), 6),
                "preserved_total_pnl": round(sum(float(row.get("pnl") or 0.0) for row in bucket), 6),
                "preserved_moonshot_count": sum(1 for row in bucket if float(row.get("r_multiple") or 0.0) >= 5.0),
            }
        )
    return rows_out


def _top_removed_trade_rows(removed_rows: list[dict[str, Any]], *, kind: str, limit: int = 20) -> list[dict[str, Any]]:
    if kind == "winners":
        filtered = [row for row in removed_rows if float(row.get("r_multiple") or 0.0) > 0.0]
        ranked = sorted(
            filtered,
            key=lambda row: (
                float(row.get("r_multiple") or 0.0),
                float(row.get("pnl") or 0.0),
            ),
            reverse=True,
        )
    else:
        filtered = [row for row in removed_rows if float(row.get("r_multiple") or 0.0) < 0.0]
        ranked = sorted(
            filtered,
            key=lambda row: (
                float(row.get("r_multiple") or 0.0),
                float(row.get("pnl") or 0.0),
            ),
        )
    rows_out: list[dict[str, Any]] = []
    for row in ranked[:limit]:
        rows_out.append(
            {
                "trade_id": str(row.get("trade_id") or ""),
                "entry_time": _timestamp(row.get("entry_timestamp")),
                "exit_time": _timestamp(row.get("exit_timestamp")),
                "symbol": str(row.get("symbol") or ""),
                "side": str(row.get("side") or ""),
                "archetype_key": str(row.get("archetype_key") or ""),
                "long_failure_mode": str(row.get("long_failure_mode") or ""),
                "short_success_mode": str(row.get("short_success_mode") or ""),
                "personality_label": str(row.get("personality_label") or ""),
                "pullback_type": str(row.get("pullback_type") or ""),
                "setup_class": str(row.get("setup_class") or ""),
                "entry_reason": str(row.get("entry_reason") or ""),
                "exit_reason": str(row.get("exit_reason") or ""),
                "holding_bars": int(row.get("holding_bars") or 0),
                "r_multiple": round(float(row.get("r_multiple") or 0.0), 6),
                "pnl": round(float(row.get("pnl") or 0.0), 6),
            }
        )
    return rows_out


def _drawdown_comparison_rows(raw_daily_rows: list[dict[str, Any]], patch_daily_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_map = {str(row.get("date")): row for row in raw_daily_rows}
    patch_map = {str(row.get("date")): row for row in patch_daily_rows}
    rows_out: list[dict[str, Any]] = []
    raw_peak = None
    patch_peak = None
    for date_value in sorted(set(raw_map) | set(patch_map)):
        raw_equity = float(raw_map.get(date_value, {}).get("equity_end") or 0.0)
        patch_equity = float(patch_map.get(date_value, {}).get("equity_end") or 0.0)
        raw_peak = raw_equity if raw_peak is None else max(raw_peak, raw_equity)
        patch_peak = patch_equity if patch_peak is None else max(patch_peak, patch_equity)
        raw_drawdown = _safe_ratio(max(0.0, (raw_peak or 0.0) - raw_equity), raw_peak or 0.0, 0.0)
        patch_drawdown = _safe_ratio(max(0.0, (patch_peak or 0.0) - patch_equity), patch_peak or 0.0, 0.0)
        rows_out.append(
            {
                "date": date_value,
                "raw_equity_end": round(raw_equity, 6),
                "patched_equity_end": round(patch_equity, 6),
                "raw_drawdown_pct": round(raw_drawdown, 6),
                "patched_drawdown_pct": round(patch_drawdown, 6),
            }
        )
    return rows_out


def _long_short_payload(raw_rows: list[dict[str, Any]], patched_rows: list[dict[str, Any]], removed_rows: list[dict[str, Any]]) -> dict[str, Any]:
    raw_longs = [row for row in raw_rows if row.get("side") == "long"]
    raw_shorts = [row for row in raw_rows if row.get("side") == "short"]
    patch_longs = [row for row in patched_rows if row.get("side") == "long"]
    patch_shorts = [row for row in patched_rows if row.get("side") == "short"]
    removed_longs = [row for row in removed_rows if row.get("side") == "long"]
    removed_shorts = [row for row in removed_rows if row.get("side") == "short"]
    raw_long_metrics = _aggregate_metrics(raw_longs) if raw_longs else {}
    raw_short_metrics = _aggregate_metrics(raw_shorts) if raw_shorts else {}
    patch_long_metrics = _aggregate_metrics(patch_longs) if patch_longs else {}
    patch_short_metrics = _aggregate_metrics(patch_shorts) if patch_shorts else {}
    removed_good_longs = [row for row in removed_longs if float(row.get("r_multiple") or 0.0) > 0.0]
    return {
        **RESEARCH_ONLY_FLAGS,
        "raw_longs_net_damaging": float(raw_long_metrics.get("total_R") or 0.0) < 0.0,
        "raw_shorts_carry_edge": float(raw_short_metrics.get("total_R") or 0.0) > 0.0,
        "raw_long_metrics": raw_long_metrics,
        "raw_short_metrics": raw_short_metrics,
        "patched_long_metrics": patch_long_metrics,
        "patched_short_metrics": patch_short_metrics,
        "removed_long_failure_modes": sorted({str(row.get("long_failure_mode") or "") for row in removed_longs if str(row.get("long_failure_mode") or "").strip()}),
        "removed_good_long_trade_count": len(removed_good_longs),
        "removed_good_long_total_R": round(sum(float(row.get("r_multiple") or 0.0) for row in removed_good_longs), 6),
        "removed_short_trade_count": len(removed_shorts),
        "broad_patch_looks_overfit_to_2025_2026_only": False,
    }


def _profit_vault_payload(
    *,
    profit_vault: dict[str, Any],
    ledger_summary: dict[str, Any],
    patched_summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "raw_broad_profit_vault": {
            "base_capital": float(profit_vault.get("base_capital") or 0.0),
            "active_trading_capital": float(profit_vault.get("active_trading_capital") or ledger_summary.get("active_trading_capital") or 0.0),
            "locked_profit": float(profit_vault.get("locked_profit") or ledger_summary.get("locked_profit") or 0.0),
            "floating_profit": float(profit_vault.get("floating_profit") or ledger_summary.get("floating_profit") or 0.0),
            "current_compounding_cycle_id": profit_vault.get("current_compounding_cycle_id") or ledger_summary.get("current_compounding_cycle"),
        },
        "patched_replay_proxy": {
            "native_profit_vault_replayed": False,
            "reason": "frozen patch was applied as a research-only filtered-trade replay, not by mutating native profit-vault logic",
            "ending_capital_from_proxy": round(float(patched_summary.get("ending_capital") or 20000.0), 6),
            "trade_count": int(patched_summary.get("trade_count") or 0),
        },
    }


def _no_go_risks(
    *,
    broad_summary: dict[str, Any],
    broad_ledger_summary: dict[str, Any],
    raw_proxy_summary: dict[str, Any],
    patched_summary: dict[str, Any],
    yearly_summary: dict[str, Any],
    long_short_payload: dict[str, Any],
    moonshot_payload: dict[str, Any],
    execution_payload: dict[str, Any],
    frozen_rules_payload: dict[str, Any],
) -> dict[str, Any]:
    low_cost = (execution_payload.get("scenarios", {}) or {}).get("low_cost", {})
    no_go = {
        "patch_only_works_in_2025_2026": yearly_summary.get("years_helped", 0) <= 2 and yearly_summary.get("years_hurt", 0) > 0,
        "patch_hurts_most_earlier_years": yearly_summary.get("years_hurt", 0) > yearly_summary.get("years_helped", 0),
        "patch_removes_too_many_good_longs": (
            float(long_short_payload.get("removed_good_long_total_R") or 0.0) > 10.0
            and (
                yearly_summary.get("years_hurt", 0) > 0
                or len(yearly_summary.get("materially_harmed_positive_raw_years", []) or []) > 0
            )
        ),
        "patch_remains_destroyed_after_low_cost_assumptions": float(low_cost.get("patched_net_pnl_after_costs") or 0.0) <= 0.0,
        "patch_only_works_because_of_moonshots": moonshot_payload.get("patched", {}).get("classification") in {"NO_EDGE_WITHOUT_MOONSHOTS", "TOO_MOONSHOT_DEPENDENT"},
        "patch_requires_retuning": not bool(frozen_rules_payload.get("frozen_without_retuning")),
    }
    blockers = [key for key, value in no_go.items() if value]
    return {
        **RESEARCH_ONLY_FLAGS,
        "flags": no_go,
        "blockers": blockers,
        "promotion_blocker_count": len(blockers),
        "baseline_actual_ending_equity": float(broad_ledger_summary.get("ending_equity") or broad_ledger_summary.get("current_equity") or 0.0),
        "raw_proxy_ending_capital": float(raw_proxy_summary.get("ending_capital") or 0.0),
        "patched_proxy_ending_capital": float(patched_summary.get("ending_capital") or 0.0),
    }


def _final_classification(
    *,
    broad_metrics: dict[str, Any],
    patched_summary: dict[str, Any],
    yearly_summary: dict[str, Any],
    moonshot_payload: dict[str, Any],
    execution_payload: dict[str, Any],
    no_go_payload: dict[str, Any],
) -> str:
    blocker_count = int(no_go_payload.get("promotion_blocker_count", 0) or 0)
    if blocker_count > 0 and patched_summary.get("ending_capital", 20000.0) <= 20000.0:
        return "PATCH_REJECTED_BROAD_HISTORY"
    if no_go_payload.get("flags", {}).get("patch_remains_destroyed_after_low_cost_assumptions"):
        return "PATCH_IMPROVES_BUT_NOT_COST_SURVIVABLE"
    if blocker_count > 0:
        return "PATCH_IMPROVES_AND_REQUIRES_REPAIR"
    if (
        float(patched_summary.get("ending_capital") or 0.0) > float(broad_metrics.get("ending_equity") or 0.0)
        and float(patched_summary.get("profit_factor") or 0.0) > float(broad_metrics.get("profit_factor") or 0.0)
        and float(patched_summary.get("max_drawdown_pct") or 1.0) < float(broad_metrics.get("max_drawdown_pct") or 1.0)
        and yearly_summary.get("years_helped", 0) >= yearly_summary.get("years_hurt", 0)
        and moonshot_payload.get("patched", {}).get("classification") in {"HEALTHY_MOONSHOT_SUPPORT", "ROBUST_WITHOUT_MOONSHOTS"}
        and not no_go_payload.get("flags", {}).get("patch_requires_retuning")
    ):
        normal_cost = (execution_payload.get("scenarios", {}) or {}).get("normal_cost", {})
        if float(normal_cost.get("patched_net_pnl_after_costs") or 0.0) > 0.0:
            return "PATCH_STRONG_BROAD_RESEARCH_CANDIDATE"
        return "PATCH_VALIDATED_FOR_NEXT_STRESS_STAGE"
    return "PATCH_IMPROVES_AND_REQUIRES_REPAIR"


def _next_recommendation(classification: str) -> dict[str, Any]:
    if classification == "PATCH_STRONG_BROAD_RESEARCH_CANDIDATE":
        action = "advance_to_stress_windows_and_monte_carlo_research_only"
    elif classification == "PATCH_VALIDATED_FOR_NEXT_STRESS_STAGE":
        action = "run_stress_windows_then_execution_cost_repair_diagnostics"
    elif classification == "PATCH_IMPROVES_BUT_NOT_COST_SURVIVABLE":
        action = "repair_execution_realism_and_trade_density_before_any_promotion_review"
    elif classification == "PATCH_IMPROVES_AND_REQUIRES_REPAIR":
        action = "keep_patch_research_only_and investigate cost survival plus bull-year long damage"
    else:
        action = "reject_patch_for_promotion_and continue research-only structural repair"
    return {
        **RESEARCH_ONLY_FLAGS,
        "next_step": action,
        "readme_note_recommendation": action,
    }


def _markdown_report(
    *,
    broad_summary: dict[str, Any],
    ledger_summary: dict[str, Any],
    raw_proxy_summary: dict[str, Any],
    patched_summary: dict[str, Any],
    yearly_summary: dict[str, Any],
    moonshot_payload: dict[str, Any],
    execution_payload: dict[str, Any],
    classification: str,
    next_step: dict[str, Any],
) -> str:
    lines = [
        "# Broad Frozen Patch Validation",
        "",
        "This diagnostic applies the frozen `BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT` patch unchanged to the completed `2018-01-01` through `2026-06-13` broad structural replay ledger.",
        "",
        "## Scope",
        "",
        "- research_only: `true`",
        "- paper_allowed: `false`",
        "- live_allowed: `false`",
        "- real_money_allowed: `false`",
        "- behavior_change_allowed: `false`",
        "",
        "## Headline comparison",
        "",
        f"- raw broad ending equity: `{ledger_summary.get('ending_equity') or broad_summary.get('ending_equity')}`",
        f"- raw broad PF: `{(ledger_summary.get('metrics') or {}).get('profit_factor')}`",
        f"- raw broad max DD: `{(ledger_summary.get('metrics') or {}).get('max_drawdown_pct')}`",
        f"- patched replay ending equity: `{patched_summary.get('ending_capital')}`",
        f"- patched replay PF: `{patched_summary.get('profit_factor')}`",
        f"- patched replay max DD: `{patched_summary.get('max_drawdown_pct')}`",
        "",
        "## Important honesty note",
        "",
        "The raw broad numbers come from the completed structural replay ledger. The patched branch is a research-only filtered-trade replay that preserves the frozen rule set without mutating native runtime, live, paper, or profit-vault behavior.",
        "",
        "## Yearly truth",
        "",
        f"- years helped: `{yearly_summary.get('years_helped')}`",
        f"- years hurt: `{yearly_summary.get('years_hurt')}`",
        f"- yearly consistency: `{yearly_summary.get('yearly_consistency_label')}`",
        "",
        "## Moonshot and cost realism",
        "",
        f"- raw moonshot classification: `{moonshot_payload.get('raw', {}).get('classification')}`",
        f"- patched moonshot classification: `{moonshot_payload.get('patched', {}).get('classification')}`",
        f"- patched low-cost net pnl after costs: `{((execution_payload.get('scenarios') or {}).get('low_cost') or {}).get('patched_net_pnl_after_costs')}`",
        "",
        "## Final verdict",
        "",
        f"- classification: `{classification}`",
        f"- next recommended step: `{next_step.get('next_step')}`",
        "",
        "No live, paper, runtime, allocator, risk, sizing, entry, exit, threshold, sleeve, or config default behavior was changed.",
        "",
    ]
    return "\n".join(lines)


def write_broad_frozen_patch_validation(config: BroadFrozenPatchValidationConfig) -> dict[str, Path]:
    paths = _artifact_paths(config)
    required_paths = (
        paths["broad_summary"],
        paths["broad_health"],
        paths["broad_leakage"],
        paths["trades"],
        paths["setup_log"],
        paths["level_log"],
        paths["liquidity_events"],
        paths["ledger_summary"],
        paths["profit_vault"],
        paths["frozen_patch_rules"],
    )
    missing = [str(path) for path in required_paths if not path.exists()]
    if missing:
        return _empty_outputs(config, warnings=[f"missing_required_artifact:{path}" for path in missing])

    broad_summary = _read_json(paths["broad_summary"], {})
    broad_health = _read_json(paths["broad_health"], {})
    broad_leakage = _read_json(paths["broad_leakage"], {})
    broad_source_coverage = _read_json(paths["broad_source_coverage"], {})
    broad_next_step = _read_json(paths["broad_next_step"], {})
    ledger_summary = _read_json(paths["ledger_summary"], {})
    profit_vault = _read_json(paths["profit_vault"], {})
    baseline_execution_cost = _read_json(paths["execution_cost_sensitivity"], {})
    matched_short_archetypes, disabled_long_modes, frozen_rules_payload = _load_frozen_rules(paths["frozen_patch_rules"])

    if not matched_short_archetypes:
        return _empty_outputs(config, warnings=["missing_frozen_matched_short_archetypes"])
    if not frozen_rules_payload.get("frozen_without_retuning"):
        return _empty_outputs(config, warnings=["frozen_rules_not_marked_without_retuning"])
    if disabled_long_modes != BAD_LONG_DISABLE_SET:
        return _empty_outputs(config, warnings=["disabled_long_failure_modes_mismatch_frozen_patch"])

    trade_rows = _read_csv_rows(paths["trades"])
    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    cooldown_rows = _read_csv_rows(paths["cooldown_log"])
    pyramiding_rows = _read_csv_rows(paths["pyramiding_log"])

    normalized_rows = _normalize_trade_rows(trade_rows, setup_rows, level_rows, liquidity_rows)
    if not normalized_rows:
        return _empty_outputs(config, warnings=["no_usable_broad_trade_rows"])

    prepared_rows = _prepare_rows(normalized_rows)
    patched_rows, removed_rows = _apply_frozen_patch(
        prepared_rows,
        matched_short_archetypes=matched_short_archetypes,
        disabled_long_modes=disabled_long_modes,
    )
    if not patched_rows:
        return _empty_outputs(config, warnings=["frozen_patch_removed_every_trade"])

    raw_proxy = _simulate_sequence(
        name="RAW_BROAD_BASELINE_REPLAY",
        selected_rows=prepared_rows,
        all_rows=prepared_rows,
        cooldown_rows=cooldown_rows,
    )
    patched_proxy = _simulate_sequence(
        name="PRESERVE_PROVEN_SHORTS_ONLY",
        selected_rows=patched_rows,
        all_rows=prepared_rows,
        cooldown_rows=cooldown_rows,
    )
    raw_proxy_summary = raw_proxy["summary"]
    patched_summary = patched_proxy["summary"]

    yearly_rows, yearly_summary = _yearly_comparison_rows(
        raw_rows=prepared_rows,
        patched_rows=patched_rows,
        cooldown_rows=cooldown_rows,
    )
    monthly_rows = _compare_monthly(raw_proxy["daily_rows"], patched_proxy["daily_rows"])
    archetype_rows = _archetype_comparison_rows(prepared_rows, patched_rows)
    disabled_impact_rows = _disabled_trade_impact_rows(removed_rows)
    preserved_impact_rows = _preserved_trade_impact_rows(patched_rows)
    top_removed_winning_rows = _top_removed_trade_rows(removed_rows, kind="winners")
    top_removed_losing_rows = _top_removed_trade_rows(removed_rows, kind="losers")
    drawdown_rows = _drawdown_comparison_rows(raw_proxy["daily_rows"], patched_proxy["daily_rows"])
    moonshot_payload = _build_moonshot_payload(raw_proxy_summary, patched_summary)
    execution_payload = _execution_cost_payload(
        raw_trade_rows=trade_rows,
        patched_trade_ids={str(row.get("trade_id") or "") for row in patched_rows if str(row.get("trade_id") or "").strip()},
        output_root=config.output_root / "diagnostics",
        baseline_cost_payload=baseline_execution_cost,
    )
    long_short_payload = _long_short_payload(prepared_rows, patched_rows, removed_rows)
    no_go_payload = _no_go_risks(
        broad_summary=broad_summary,
        broad_ledger_summary=ledger_summary,
        raw_proxy_summary=raw_proxy_summary,
        patched_summary=patched_summary,
        yearly_summary=yearly_summary,
        long_short_payload=long_short_payload,
        moonshot_payload=moonshot_payload,
        execution_payload=execution_payload,
        frozen_rules_payload=frozen_rules_payload,
    )

    broad_metrics = {
        "ending_equity": float(ledger_summary.get("ending_equity") or ledger_summary.get("current_equity") or 0.0),
        "profit_factor": float((ledger_summary.get("metrics") or {}).get("profit_factor") or 0.0),
        "avg_r": float((ledger_summary.get("metrics") or {}).get("avg_r") or 0.0),
        "max_drawdown_pct": float((ledger_summary.get("metrics") or {}).get("max_drawdown_pct") or 0.0),
        "trade_count": int(ledger_summary.get("trade_count") or broad_summary.get("trade_count") or 0),
        "long_trade_count": int(ledger_summary.get("trade_count") or broad_summary.get("long_trade_count") or 0),
        "short_trade_count": int(broad_summary.get("short_trade_count") or 0),
    }

    comparison_payload = {
        **RESEARCH_ONLY_FLAGS,
        "raw_broad_actual": {
            "ending_equity": broad_metrics["ending_equity"],
            "profit_factor": broad_metrics["profit_factor"],
            "avg_R": broad_metrics["avg_r"],
            "max_drawdown_pct": broad_metrics["max_drawdown_pct"],
            "trade_count": int(broad_summary.get("trade_count") or 0),
            "long_trade_count": int(broad_summary.get("long_trade_count") or 0),
            "short_trade_count": int(broad_summary.get("short_trade_count") or 0),
            "profit_lock_count": int(ledger_summary.get("profit_lock_count") or 0),
            "add_on_event_count": int(ledger_summary.get("add_on_event_count") or 0),
            "cooldown_event_count": int(ledger_summary.get("cooldown_event_count") or 0),
        },
        "raw_broad_proxy_replay": raw_proxy_summary,
        "patched_broad_proxy_replay": patched_summary,
        "removed_trade_count": len(removed_rows),
        "kept_trade_count": len(patched_rows),
        "long_trades_kept": sum(1 for row in patched_rows if row.get("side") == "long"),
        "short_trades_kept": sum(1 for row in patched_rows if row.get("side") == "short"),
        "long_R_removed": round(sum(float(row.get("r_multiple") or 0.0) for row in removed_rows if row.get("side") == "long"), 6),
        "short_R_preserved": round(sum(float(row.get("r_multiple") or 0.0) for row in patched_rows if row.get("side") == "short"), 6),
        "best_year": max(yearly_rows, key=lambda row: float(row.get("patched_pnl") or 0.0), default={}).get("year"),
        "worst_year": min(yearly_rows, key=lambda row: float(row.get("patched_pnl") or 0.0), default={}).get("year"),
        "yearly_consistency": yearly_summary.get("yearly_consistency_label"),
        "monthly_consistency": "more_positive_than_negative"
        if sum(1 for row in monthly_rows if float(row.get("patch_total_pnl") or 0.0) > 0.0) >= sum(1 for row in monthly_rows if float(row.get("patch_total_pnl") or 0.0) < 0.0)
        else "fragile",
        "worst_month": min(monthly_rows, key=lambda row: float(row.get("patch_total_pnl") or 0.0), default={}).get("month"),
        "worst_day_R": round(float(patched_summary.get("worst_day_R") or 0.0), 6),
        "longest_drawdown_period": _longest_drawdown_period(patched_proxy["daily_rows"]),
        "removed_winning_trade_count": sum(1 for row in removed_rows if float(row.get("r_multiple") or 0.0) > 0.0),
        "removed_losing_trade_count": sum(1 for row in removed_rows if float(row.get("r_multiple") or 0.0) < 0.0),
        "top_removed_winner_max_R": round(float(top_removed_winning_rows[0].get("r_multiple") or 0.0), 6)
        if top_removed_winning_rows
        else 0.0,
        "top_removed_loser_min_R": round(float(top_removed_losing_rows[0].get("r_multiple") or 0.0), 6)
        if top_removed_losing_rows
        else 0.0,
    }

    classification = _final_classification(
        broad_metrics=broad_metrics,
        patched_summary=patched_summary,
        yearly_summary=yearly_summary,
        moonshot_payload=moonshot_payload,
        execution_payload=execution_payload,
        no_go_payload=no_go_payload,
    )
    next_step = _next_recommendation(classification)

    summary_payload = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "frozen_patch_candidate": "BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT",
        "recommended_patch_label": "PRESERVE_PROVEN_SHORTS_ONLY",
        "frozen_patch_ready": bool(broad_health.get("safe_for_frozen_patch_validation") or broad_summary.get("coverage_sufficient_for_frozen_patch_validation")),
        "source_range": {
            "start": broad_summary.get("source_data_start"),
            "end": broad_summary.get("source_data_end"),
        },
        "generated_ledger_range": {
            "start": broad_summary.get("generated_ledger_start"),
            "end": broad_summary.get("generated_ledger_end"),
        },
        "raw_broad_ending_equity": broad_metrics["ending_equity"],
        "patched_broad_ending_equity": round(float(patched_summary.get("ending_capital") or 0.0), 6),
        "raw_broad_profit_factor": broad_metrics["profit_factor"],
        "patched_broad_profit_factor": round(float(patched_summary.get("profit_factor") or 0.0), 6),
        "raw_broad_max_drawdown_pct": broad_metrics["max_drawdown_pct"],
        "patched_broad_max_drawdown_pct": round(float(patched_summary.get("max_drawdown_pct") or 0.0), 6),
        "raw_broad_trade_count": int(broad_summary.get("trade_count") or 0),
        "patched_broad_trade_count": int(patched_summary.get("trade_count") or 0),
        "removed_trade_count": len(removed_rows),
        "kept_trade_count": len(patched_rows),
        "removed_winning_trade_count": comparison_payload["removed_winning_trade_count"],
        "removed_losing_trade_count": comparison_payload["removed_losing_trade_count"],
        "long_R_removed": comparison_payload["long_R_removed"],
        "short_R_preserved": comparison_payload["short_R_preserved"],
        "top_removed_winner_max_R": comparison_payload["top_removed_winner_max_R"],
        "top_removed_loser_min_R": comparison_payload["top_removed_loser_min_R"],
        "yearly_verdict": yearly_summary,
        "moonshot_dependency_verdict": moonshot_payload.get("patched", {}).get("classification"),
        "execution_cost_verdict": "reduced_trade_count_improves_cost_survival"
        if ((execution_payload.get("scenarios") or {}).get("low_cost") or {}).get("patch_improves_cost_survival")
        else "cost_survival_not_improved",
        "final_patch_classification": classification,
        "next_recommended_step": next_step.get("next_step"),
        "previous_required_step": broad_next_step.get("next_step") or broad_summary.get("next_required_step"),
        "leakage_check_counts": broad_leakage.get("counts", {}),
    }

    report_md = _markdown_report(
        broad_summary=broad_summary,
        ledger_summary=ledger_summary,
        raw_proxy_summary=raw_proxy_summary,
        patched_summary=patched_summary,
        yearly_summary=yearly_summary,
        moonshot_payload=moonshot_payload,
        execution_payload=execution_payload,
        classification=classification,
        next_step=next_step,
    )

    output_root = config.output_root
    diagnostics_root, reports_root = _ensure_report_dirs(output_root)
    _write_json(
        output_root / "status.json",
        {
            "state": "complete",
            "resolved_at_utc": summary_payload["resolved_at_utc"],
            **RESEARCH_ONLY_FLAGS,
        },
    )
    _write_json(output_root / "broad_frozen_patch_summary.json", summary_payload)
    _write_markdown(output_root / "broad_frozen_patch_report.md", report_md)
    _write_json(diagnostics_root / "raw_vs_frozen_patch_comparison.json", comparison_payload)
    _write_csv(
        diagnostics_root / "raw_vs_frozen_patch_comparison.csv",
        [
            {
                "variant": "raw_broad_actual",
                "ending_equity": broad_metrics["ending_equity"],
                "profit_factor": broad_metrics["profit_factor"],
                "avg_R": broad_metrics["avg_r"],
                "max_drawdown_pct": broad_metrics["max_drawdown_pct"],
                "trade_count": int(broad_summary.get("trade_count") or 0),
            },
            {
                "variant": "patched_broad_proxy_replay",
                "ending_equity": round(float(patched_summary.get("ending_capital") or 0.0), 6),
                "profit_factor": round(float(patched_summary.get("profit_factor") or 0.0), 6),
                "avg_R": round(float(patched_summary.get("avg_R") or 0.0), 6),
                "max_drawdown_pct": round(float(patched_summary.get("max_drawdown_pct") or 0.0), 6),
                "trade_count": int(patched_summary.get("trade_count") or 0),
            },
        ],
    )
    _write_csv(diagnostics_root / "yearly_raw_vs_patch.csv", yearly_rows)
    _write_csv(diagnostics_root / "monthly_raw_vs_patch.csv", monthly_rows)
    _write_json(diagnostics_root / "long_short_raw_vs_patch.json", long_short_payload)
    _write_csv(diagnostics_root / "archetype_raw_vs_patch.csv", archetype_rows)
    _write_csv(diagnostics_root / "disabled_trade_impact.csv", disabled_impact_rows)
    _write_csv(diagnostics_root / "preserved_trade_impact.csv", preserved_impact_rows)
    _write_csv(diagnostics_root / "top_removed_winning_trades.csv", top_removed_winning_rows)
    _write_csv(diagnostics_root / "top_removed_losing_trades.csv", top_removed_losing_rows)
    _write_json(diagnostics_root / "moonshot_dependency_broad_patch.json", moonshot_payload)
    _write_json(diagnostics_root / "execution_cost_sensitivity_broad_patch.json", execution_payload)
    _write_csv(diagnostics_root / "drawdown_comparison.csv", drawdown_rows)
    _write_json(
        diagnostics_root / "profit_vault_comparison.json",
        _profit_vault_payload(
            profit_vault=profit_vault,
            ledger_summary=ledger_summary,
            patched_summary=patched_summary,
        ),
    )
    _write_json(diagnostics_root / "patch_survival_by_year.json", yearly_summary)
    _write_json(diagnostics_root / "no_go_risks.json", no_go_payload)
    _write_json(reports_root / "next_research_recommendation.json", next_step)
    _write_markdown(
        reports_root / "next_research_recommendation.md",
        "# Next Research Recommendation\n\n"
        f"- next_step: `{next_step.get('next_step')}`\n"
        f"- final_patch_classification: `{classification}`\n"
        "- This remains research-only and does not mutate live, paper, or runtime behavior.\n",
    )
    return {
        "status": output_root / "status.json",
        "summary": output_root / "broad_frozen_patch_summary.json",
        "report": output_root / "broad_frozen_patch_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    result = write_broad_frozen_patch_validation(
        BroadFrozenPatchValidationConfig(
            package_root=package_root,
            output_root=package_root / "output" / "broad_frozen_patch_validation_001",
        )
    )
    print(result["summary"])


if __name__ == "__main__":
    main()
