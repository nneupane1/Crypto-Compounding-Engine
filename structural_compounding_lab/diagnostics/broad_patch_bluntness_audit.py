from __future__ import annotations

import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import (  # noqa: E402
    RESEARCH_ONLY_FLAGS,
    TARGET_YEARS,
    _apply_frozen_patch,
    _artifact_paths as _frozen_validation_artifact_paths,
    _baseline_span_days,
    _load_frozen_rules,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import (  # noqa: E402
    _prepare_rows,
    _simulate_variant,
)
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
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


@dataclass(frozen=True)
class BroadPatchBluntnessAuditConfig:
    package_root: Path
    output_root: Path


def _paths(config: BroadPatchBluntnessAuditConfig) -> dict[str, Path]:
    source_root = config.package_root / "output"
    broad_root = source_root / "broad_historical_structural_replay_001"
    broad_ledger_root = broad_root / "ledger"
    frozen_rule_root = source_root / "frozen_patch_validation_audit_001"
    broad_patch_validation_root = source_root / "broad_frozen_patch_validation_001"
    return {
        "trades": broad_ledger_root / "trades.csv",
        "setup_log": broad_ledger_root / "setup_log.csv",
        "level_log": broad_ledger_root / "level_log.csv",
        "liquidity_events": broad_ledger_root / "liquidity_events.csv",
        "cooldown_log": broad_ledger_root / "cooldown_log.csv",
        "pyramiding_log": broad_ledger_root / "pyramiding_log.csv",
        "equity": broad_ledger_root / "equity.csv",
        "ledger_summary": broad_ledger_root / "summary.json",
        "profit_vault": broad_ledger_root / "profit_vault.json",
        "execution_cost_sensitivity": broad_ledger_root / "execution_realism" / "execution_cost_sensitivity.json",
        "broad_summary": broad_root / "broad_historical_replay_summary.json",
        "broad_health": broad_root / "diagnostics" / "replay_health_report.json",
        "frozen_patch_rules": frozen_rule_root / "diagnostics" / "frozen_patch_rules.json",
        "patch_summary": broad_patch_validation_root / "broad_frozen_patch_summary.json",
        "patch_comparison": broad_patch_validation_root / "diagnostics" / "raw_vs_frozen_patch_comparison.json",
        "top_removed_winners": broad_patch_validation_root / "diagnostics" / "top_removed_winning_trades.csv",
        "top_removed_losers": broad_patch_validation_root / "diagnostics" / "top_removed_losing_trades.csv",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, reports_root


def _read_csv_optional(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return _read_csv_rows(path)


def _empty_outputs(config: BroadPatchBluntnessAuditConfig, warnings: list[str]) -> dict[str, Path]:
    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    status_payload = {
        "state": "empty",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "warnings": warnings,
    }
    summary_payload = {
        **RESEARCH_ONLY_FLAGS,
        "warnings": warnings,
        "final_classification": "PATCH_REJECTED_AFTER_BLUNTNESS_AUDIT",
    }
    report_md = "# Broad Patch Bluntness Audit\n\nRequired broad replay or frozen patch artifacts are missing.\n"
    _write_json(config.output_root / "status.json", status_payload)
    _write_json(config.output_root / "broad_patch_bluntness_summary.json", summary_payload)
    _write_markdown(config.output_root / "broad_patch_bluntness_report.md", report_md)
    for name in (
        "kept_removed_quadrant_audit.csv",
        "removed_short_convexity_audit.csv",
        "removed_loss_failure_mode_audit.csv",
        "variant_replay_comparison.csv",
        "variant_yearly_survival.csv",
        "removed_winners_by_archetype_year.csv",
        "removed_losers_by_failure_mode_year.csv",
    ):
        _write_csv(diagnostics_root / name, [])
    for name in (
        "variant_execution_cost_sensitivity.json",
        "equity_explosion_accounting_audit.json",
        "no_go_risks.json",
    ):
        _write_json(diagnostics_root / name, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_markdown(diagnostics_root / "equity_explosion_accounting_audit.md", report_md)
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "broad_patch_bluntness_summary.json",
        "report": config.output_root / "broad_patch_bluntness_report.md",
    }


def _sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or ""))


def _year(row: dict[str, Any]) -> str:
    timestamp = row.get("exit_timestamp")
    if timestamp is None:
        return "unknown"
    return str(pd.Timestamp(timestamp).year)


def _r_bucket(r_value: float) -> str:
    if r_value <= -2.0:
        return "loss_le_-2R"
    if r_value < 0.0:
        return "loss_-2R_to_0R"
    if r_value < 1.0:
        return "win_0R_to_1R"
    if r_value < 3.0:
        return "win_1R_to_3R"
    if r_value < 5.0:
        return "win_3R_to_5R"
    if r_value < 10.0:
        return "win_5R_to_10R"
    return "win_10R_plus"


def _stats(rows: list[dict[str, Any]]) -> dict[str, float]:
    r_values = [float(row.get("r_multiple") or 0.0) for row in rows]
    pnl_values = [float(row.get("pnl") or 0.0) for row in rows]
    return {
        "count": float(len(rows)),
        "total_R": round(sum(r_values), 6),
        "avg_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
        "median_R": round(_median(r_values), 6) if r_values else 0.0,
        "max_R": round(max(r_values), 6) if r_values else 0.0,
        "total_pnl": round(sum(pnl_values), 6),
    }


def _quadrant(row: dict[str, Any], *, kept: bool) -> str:
    r_value = float(row.get("r_multiple") or 0.0)
    if kept:
        return "kept_winner" if r_value > 0.0 else "kept_loser"
    return "removed_winner" if r_value > 0.0 else "removed_loser"


def _failure_bucket(row: dict[str, Any]) -> str:
    if row.get("side") == "long":
        return str(row.get("long_failure_mode") or "LONG_OTHER")
    return "SHORT_NOT_PROVEN"


def _moonshot_flag(row: dict[str, Any]) -> str:
    return "moonshot" if float(row.get("r_multiple") or 0.0) >= 5.0 else "non_moonshot"


def _quadrant_audit_rows(kept_rows: list[dict[str, Any]], removed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    all_rows = kept_rows + removed_rows
    total_abs_r = sum(abs(float(row.get("r_multiple") or 0.0)) for row in all_rows) or 1.0
    total_abs_pnl = sum(abs(float(row.get("pnl") or 0.0)) for row in all_rows) or 1.0
    grouped: dict[tuple[str, str, str, str, str, str, str], list[dict[str, Any]]] = {}
    for kept_flag, rows in ((True, kept_rows), (False, removed_rows)):
        for row in rows:
            key = (
                _quadrant(row, kept=kept_flag),
                str(row.get("side") or ""),
                _year(row),
                _r_bucket(float(row.get("r_multiple") or 0.0)),
                str(row.get("archetype_key") or "n/a"),
                _failure_bucket(row),
                _moonshot_flag(row),
            )
            grouped.setdefault(key, []).append(row)
    rows_out: list[dict[str, Any]] = []
    for key, bucket in sorted(grouped.items()):
        stat = _stats(bucket)
        rows_out.append(
            {
                "quadrant": key[0],
                "side": key[1],
                "year": key[2],
                "r_bucket": key[3],
                "archetype_key": key[4],
                "failure_mode_bucket": key[5],
                "moonshot_flag": key[6],
                "trade_count": int(stat["count"]),
                "total_R": stat["total_R"],
                "avg_R": stat["avg_R"],
                "median_R": stat["median_R"],
                "max_R": stat["max_R"],
                "total_pnl": stat["total_pnl"],
                "contribution_share_abs_R": round(sum(abs(float(row.get("r_multiple") or 0.0)) for row in bucket) / total_abs_r, 6),
                "contribution_share_abs_pnl": round(sum(abs(float(row.get("pnl") or 0.0)) for row in bucket) / total_abs_pnl, 6),
            }
        )
    return rows_out


def _removed_winners_by_archetype_year(removed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    winners = [row for row in removed_rows if float(row.get("r_multiple") or 0.0) > 0.0]
    total_abs_r = sum(abs(float(row.get("r_multiple") or 0.0)) for row in winners) or 1.0
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in winners:
        key = (_year(row), str(row.get("side") or ""), str(row.get("archetype_key") or "n/a"))
        grouped.setdefault(key, []).append(row)
    rows_out: list[dict[str, Any]] = []
    for key, bucket in sorted(grouped.items(), key=lambda item: sum(float(row.get("r_multiple") or 0.0) for row in item[1]), reverse=True):
        stat = _stats(bucket)
        rows_out.append(
            {
                "year": key[0],
                "side": key[1],
                "archetype_key": key[2],
                "trade_count": int(stat["count"]),
                "total_R": stat["total_R"],
                "avg_R": stat["avg_R"],
                "median_R": stat["median_R"],
                "max_R": stat["max_R"],
                "total_pnl": stat["total_pnl"],
                "winner_share_abs_R": round(sum(abs(float(row.get("r_multiple") or 0.0)) for row in bucket) / total_abs_r, 6),
                "moonshot_count": sum(1 for row in bucket if float(row.get("r_multiple") or 0.0) >= 5.0),
            }
        )
    return rows_out


def _removed_losers_by_failure_mode_year(removed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    losers = [row for row in removed_rows if float(row.get("r_multiple") or 0.0) < 0.0]
    total_abs_r = sum(abs(float(row.get("r_multiple") or 0.0)) for row in losers) or 1.0
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in losers:
        key = (_year(row), str(row.get("side") or ""), _failure_bucket(row))
        grouped.setdefault(key, []).append(row)
    rows_out: list[dict[str, Any]] = []
    for key, bucket in sorted(grouped.items(), key=lambda item: sum(abs(float(row.get("r_multiple") or 0.0)) for row in item[1]), reverse=True):
        stat = _stats(bucket)
        rows_out.append(
            {
                "year": key[0],
                "side": key[1],
                "failure_mode_bucket": key[2],
                "trade_count": int(stat["count"]),
                "total_R": stat["total_R"],
                "avg_R": stat["avg_R"],
                "median_R": stat["median_R"],
                "max_R": stat["max_R"],
                "total_pnl": stat["total_pnl"],
                "loser_share_abs_R": round(sum(abs(float(row.get("r_multiple") or 0.0)) for row in bucket) / total_abs_r, 6),
            }
        )
    return rows_out


def _find_original_trades(trade_rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("trade_id") or ""): dict(row)
        for row in trade_rows
        if str(row.get("trade_id") or "").strip()
    }


def _allowed_short_labels(matched_short_archetypes: set[str]) -> str:
    return "; ".join(sorted(matched_short_archetypes))


def _removed_short_convexity_rows(
    removed_rows: list[dict[str, Any]],
    *,
    matched_short_archetypes: set[str],
    top_removed_winners: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    top_ids = [str(row.get("trade_id") or "") for row in top_removed_winners if str(row.get("trade_id") or "").strip()]
    removed_by_id = {str(row.get("trade_id") or ""): row for row in removed_rows}
    rows_out: list[dict[str, Any]] = []
    allowed_labels = _allowed_short_labels(matched_short_archetypes)
    for trade_id in top_ids:
        row = removed_by_id.get(trade_id)
        if not row or row.get("side") != "short" or float(row.get("r_multiple") or 0.0) <= 0.0:
            continue
        archetype = str(row.get("archetype_key") or "")
        failed_predicate = "archetype_not_in_allowed_short_bucket" if archetype not in matched_short_archetypes else "other"
        moonshot_flag = _moonshot_flag(row)
        explanation = (
            f"Removed because frozen patch only keeps exact short archetype labels in the allowed set. "
            f"This trade used `{archetype}`, which was not in the frozen allow-list despite producing {float(row.get('r_multiple') or 0.0):.2f}R."
        )
        rows_out.append(
            {
                "trade_id": trade_id,
                "exit_time": _timestamp(row.get("exit_timestamp")),
                "year": _year(row),
                "side": str(row.get("side") or ""),
                "r_multiple": round(float(row.get("r_multiple") or 0.0), 6),
                "pnl": round(float(row.get("pnl") or 0.0), 6),
                "note": "removed_short_moonshot" if moonshot_flag == "moonshot" else "removed_positive_short",
                "moonshot_flag": moonshot_flag,
                "archetype_key": archetype,
                "short_success_mode": str(row.get("short_success_mode") or ""),
                "personality_label": str(row.get("personality_label") or ""),
                "pullback_type": str(row.get("pullback_type") or ""),
                "setup_class": str(row.get("setup_class") or ""),
                "entry_reason": str(row.get("entry_reason") or ""),
                "exit_reason": str(row.get("exit_reason") or ""),
                "holding_bars": int(row.get("holding_bars") or 0),
                "failed_predicate": failed_predicate,
                "missing_allowed_label": archetype if failed_predicate == "archetype_not_in_allowed_short_bucket" else "",
                "allowed_short_labels": allowed_labels,
                "human_explanation": explanation,
            }
        )
    return rows_out


def _removed_loss_failure_mode_rows(removed_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    losers = [row for row in removed_rows if float(row.get("r_multiple") or 0.0) < 0.0]
    total_abs_r = sum(abs(float(row.get("r_multiple") or 0.0)) for row in losers) or 1.0
    grouped: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in losers:
        key = (_year(row), str(row.get("side") or ""), _failure_bucket(row))
        grouped.setdefault(key, []).append(row)
    rows_out: list[dict[str, Any]] = []
    for key, bucket in sorted(grouped.items(), key=lambda item: sum(abs(float(row.get("r_multiple") or 0.0)) for row in item[1]), reverse=True):
        stat = _stats(bucket)
        rows_out.append(
            {
                "year": key[0],
                "side": key[1],
                "failure_mode_bucket": key[2],
                "trade_count": int(stat["count"]),
                "total_R": stat["total_R"],
                "avg_R": stat["avg_R"],
                "median_R": stat["median_R"],
                "max_R": stat["max_R"],
                "total_pnl": stat["total_pnl"],
                "removed_loser_share_abs_R": round(sum(abs(float(row.get("r_multiple") or 0.0)) for row in bucket) / total_abs_r, 6),
            }
        )
    return rows_out


def _simulate_rows(
    *,
    name: str,
    selected_rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    cooldown_rows: list[dict[str, Any]],
    moonshot_override: str | None = None,
) -> dict[str, Any]:
    return _simulate_variant(
        name=name,
        selected_rows=selected_rows,
        all_rows=all_rows,
        start_capital=20000.0,
        baseline_span_days=_baseline_span_days(all_rows if all_rows else selected_rows),
        cooldown_rows=cooldown_rows,
        moonshot_override=moonshot_override,
    )


def _variant_trade_rows_for_costs(
    *,
    selected_rows: list[dict[str, Any]],
    original_trade_map: dict[str, dict[str, Any]],
    moonshot_override: str | None = None,
) -> list[dict[str, Any]]:
    rows_out: list[dict[str, Any]] = []
    for row in selected_rows:
        trade_id = str(row.get("trade_id") or "")
        original = original_trade_map.get(trade_id)
        if not original:
            continue
        cloned = dict(original)
        original_r = float(cloned.get("r_multiple") or 0.0)
        adjusted_r = original_r
        if moonshot_override == "cap_10_to_5" and adjusted_r > 10.0:
            adjusted_r = 5.0
        elif moonshot_override == "cap_5_to_3" and adjusted_r > 5.0:
            adjusted_r = 3.0
        if not math.isclose(adjusted_r, original_r):
            original_pnl = float(cloned.get("pnl") or 0.0)
            risk_value = abs(original_pnl / original_r) if abs(original_r) > 1e-8 else max(abs(original_pnl), 1.0)
            cloned["r_multiple"] = adjusted_r
            cloned["pnl"] = adjusted_r * risk_value
        rows_out.append(cloned)
    return rows_out


def _yearly_variant_rows(
    *,
    variant_name: str,
    raw_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    cooldown_rows: list[dict[str, Any]],
    moonshot_override: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows_out: list[dict[str, Any]] = []
    years_helped = 0
    years_hurt = 0
    for year in TARGET_YEARS:
        start = pd.Timestamp(year=year, month=1, day=1)
        end = pd.Timestamp(year=year, month=12, day=31, hour=23, minute=59, second=59)
        raw_year = [row for row in raw_rows if row.get("exit_timestamp") is not None and start <= row["exit_timestamp"] <= end]
        variant_year = [row for row in selected_rows if row.get("exit_timestamp") is not None and start <= row["exit_timestamp"] <= end]
        raw_summary = _simulate_rows(
            name=f"RAW_{year}",
            selected_rows=raw_year,
            all_rows=raw_year,
            cooldown_rows=cooldown_rows,
        )["summary"] if raw_year else {}
        variant_summary = _simulate_rows(
            name=f"{variant_name}_{year}",
            selected_rows=variant_year,
            all_rows=raw_year,
            cooldown_rows=cooldown_rows,
            moonshot_override=moonshot_override,
        )["summary"] if raw_year else {}
        raw_pnl = float(raw_summary.get("ending_capital") or 20000.0) - 20000.0
        variant_pnl = float(variant_summary.get("ending_capital") or 20000.0) - 20000.0
        verdict = "helped" if variant_pnl > raw_pnl else "hurt" if variant_pnl < raw_pnl else "flat"
        if verdict == "helped":
            years_helped += 1
        elif verdict == "hurt":
            years_hurt += 1
        rows_out.append(
            {
                "variant_name": variant_name,
                "year": str(year),
                "raw_pnl": round(raw_pnl, 6),
                "variant_pnl": round(variant_pnl, 6),
                "raw_profit_factor": round(float(raw_summary.get("profit_factor") or 0.0), 6),
                "variant_profit_factor": round(float(variant_summary.get("profit_factor") or 0.0), 6),
                "raw_max_drawdown_pct": round(float(raw_summary.get("max_drawdown_pct") or 0.0), 6),
                "variant_max_drawdown_pct": round(float(variant_summary.get("max_drawdown_pct") or 0.0), 6),
                "helped_or_hurt": verdict,
            }
        )
    return rows_out, {"years_helped": years_helped, "years_hurt": years_hurt}


def _moonshot_classification(summary: dict[str, Any]) -> str:
    contribution = float(summary.get("moonshot_profit_contribution_pct") or 0.0)
    profit_without = float(summary.get("profit_without_moonshots") or 0.0)
    if profit_without <= 0.0:
        return "NO_EDGE_WITHOUT_MOONSHOTS"
    if contribution > 0.75:
        return "TOO_MOONSHOT_DEPENDENT"
    if contribution > 0.35:
        return "MODERATE_MOONSHOT_DEPENDENCY"
    return "ROBUST_WITHOUT_MOONSHOTS"


def _variant_rows_for_output(
    *,
    raw_ledger_summary: dict[str, Any],
    raw_proxy_summary: dict[str, Any],
    variant_outputs: dict[str, dict[str, Any]],
    yearly_counts: dict[str, dict[str, int]],
) -> list[dict[str, Any]]:
    rows_out = [
        {
            "variant_name": "RAW_BROAD_LEDGER_ACTUAL",
            "comparison_basis": "native_ledger",
            "research_only_overlay": False,
            "trade_count": int(raw_ledger_summary.get("trade_count") or 0),
            "ending_equity": round(float(raw_ledger_summary.get("ending_equity") or raw_ledger_summary.get("current_equity") or 0.0), 6),
            "profit_factor": round(float((raw_ledger_summary.get("metrics") or {}).get("profit_factor") or 0.0), 6),
            "win_rate": "",
            "avg_R": round(float((raw_ledger_summary.get("metrics") or {}).get("avg_r") or 0.0), 6),
            "total_R": "",
            "max_drawdown_pct": round(float((raw_ledger_summary.get("metrics") or {}).get("max_drawdown_pct") or 0.0), 6),
            "years_helped": 0,
            "years_hurt": 0,
            "moonshot_dependency_classification": "n/a",
        },
        {
            "variant_name": "RAW_BROAD_PROXY_REPLAY",
            "comparison_basis": "proxy_replay",
            "research_only_overlay": True,
            "trade_count": int(raw_proxy_summary.get("trade_count") or 0),
            "ending_equity": round(float(raw_proxy_summary.get("ending_capital") or 0.0), 6),
            "profit_factor": round(float(raw_proxy_summary.get("profit_factor") or 0.0), 6),
            "win_rate": round(float(raw_proxy_summary.get("win_rate") or 0.0), 6),
            "avg_R": round(float(raw_proxy_summary.get("avg_R") or 0.0), 6),
            "total_R": round(float(raw_proxy_summary.get("total_R") or 0.0), 6),
            "max_drawdown_pct": round(float(raw_proxy_summary.get("max_drawdown_pct") or 0.0), 6),
            "years_helped": 0,
            "years_hurt": 0,
            "moonshot_dependency_classification": _moonshot_classification(raw_proxy_summary),
        },
    ]
    for name, payload in variant_outputs.items():
        summary = payload["summary"]
        rows_out.append(
            {
                "variant_name": name,
                "comparison_basis": "research_overlay_proxy_replay",
                "research_only_overlay": True,
                "trade_count": int(summary.get("trade_count") or 0),
                "ending_equity": round(float(summary.get("ending_capital") or 0.0), 6),
                "profit_factor": round(float(summary.get("profit_factor") or 0.0), 6),
                "win_rate": round(float(summary.get("win_rate") or 0.0), 6),
                "avg_R": round(float(summary.get("avg_R") or 0.0), 6),
                "total_R": round(float(summary.get("total_R") or 0.0), 6),
                "max_drawdown_pct": round(float(summary.get("max_drawdown_pct") or 0.0), 6),
                "years_helped": int(yearly_counts.get(name, {}).get("years_helped") or 0),
                "years_hurt": int(yearly_counts.get(name, {}).get("years_hurt") or 0),
                "moonshot_dependency_classification": _moonshot_classification(summary),
            }
        )
    return rows_out


def _bluntness_payload(
    *,
    raw_proxy_summary: dict[str, Any],
    patched_summary: dict[str, Any],
    removed_rows: list[dict[str, Any]],
    kept_rows: list[dict[str, Any]],
    removed_short_convexity_rows: list[dict[str, Any]],
    baseline_execution: dict[str, Any],
    patched_execution: dict[str, Any],
) -> dict[str, Any]:
    removed_winners = [row for row in removed_rows if float(row.get("r_multiple") or 0.0) > 0.0]
    removed_losers = [row for row in removed_rows if float(row.get("r_multiple") or 0.0) < 0.0]
    removed_short_winners = [row for row in removed_winners if row.get("side") == "short"]
    removed_long_losers = [row for row in removed_losers if row.get("side") == "long"]
    raw_normal_cost = float(((baseline_execution.get("scenario_metrics") or {}).get("normal_cost") or {}).get("net_pnl_after_costs") or 0.0)
    patched_normal_cost = float(((patched_execution.get("scenario_metrics") or {}).get("normal_cost") or {}).get("net_pnl_after_costs") or 0.0)
    raw_fees = float(((baseline_execution.get("scenario_metrics") or {}).get("normal_cost") or {}).get("total_fees") or 0.0)
    patched_fees = float(((patched_execution.get("scenario_metrics") or {}).get("normal_cost") or {}).get("total_fees") or 0.0)
    drawdown_reduction = float(raw_proxy_summary.get("max_drawdown_pct") or 0.0) - float(patched_summary.get("max_drawdown_pct") or 0.0)
    trade_selectivity = 1.0 - _safe_ratio(float(patched_summary.get("trade_count") or 0.0), float(raw_proxy_summary.get("trade_count") or 1.0), 0.0)
    return {
        "removed_winner_count": len(removed_winners),
        "removed_loser_count": len(removed_losers),
        "removed_short_winner_count": len(removed_short_winners),
        "removed_long_loser_count": len(removed_long_losers),
        "removed_short_winner_total_R": round(sum(float(row.get("r_multiple") or 0.0) for row in removed_short_winners), 6),
        "removed_long_loser_abs_R": round(sum(abs(float(row.get("r_multiple") or 0.0)) for row in removed_long_losers), 6),
        "removed_loser_abs_R": round(sum(abs(float(row.get("r_multiple") or 0.0)) for row in removed_losers), 6),
        "removed_winner_total_R": round(sum(float(row.get("r_multiple") or 0.0) for row in removed_winners), 6),
        "drawdown_reduction_pct_points": round(drawdown_reduction, 6),
        "trade_selectivity_ratio": round(trade_selectivity, 6),
        "normal_cost_improvement": round(patched_normal_cost - raw_normal_cost, 6),
        "normal_cost_fee_reduction": round(raw_fees - patched_fees, 6),
        "top_removed_short_convexity_count": len(removed_short_convexity_rows),
        "primary_driver_guess": (
            "accounting_or_selectivity"
            if trade_selectivity > 0.75 and float(patched_summary.get("ending_capital") or 0.0) > float(raw_proxy_summary.get("ending_capital") or 0.0) * 100.0
            else "loss_cleanup_and_drawdown_repair"
        ),
    }


def _equity_explosion_accounting_audit(
    *,
    raw_ledger_summary: dict[str, Any],
    raw_proxy_summary: dict[str, Any],
    patched_summary: dict[str, Any],
    kept_rows: list[dict[str, Any]],
    patched_output: dict[str, Any],
    profit_vault: dict[str, Any],
) -> tuple[dict[str, Any], str]:
    chronological = all(
        (kept_rows[index - 1].get("exit_timestamp") or pd.Timestamp.min) <= (kept_rows[index].get("exit_timestamp") or pd.Timestamp.min)
        for index in range(1, len(kept_rows))
    )
    recomputed_equity = round(float((patched_output.get("summary") or {}).get("ending_capital") or 0.0), 6)
    reported_equity = round(float(patched_summary.get("patched_broad_ending_equity") or 0.0), 6)
    native_ending_equity = round(float(raw_ledger_summary.get("ending_equity") or raw_ledger_summary.get("current_equity") or 0.0), 6)
    proxy_ending_equity = round(float(raw_proxy_summary.get("ending_capital") or 0.0), 6)
    active_capital_field = float(profit_vault.get("active_trading_capital") or 0.0)
    locked_profit_field = float(profit_vault.get("locked_profit") or 0.0)
    payload = {
        **RESEARCH_ONLY_FLAGS,
        "chronological_replay_order_confirmed": chronological,
        "replay_start_capital": 20000.0,
        "native_ledger_ending_equity": native_ending_equity,
        "raw_proxy_replay_ending_equity": proxy_ending_equity,
        "patched_reported_ending_equity": reported_equity,
        "patched_recomputed_ending_equity": recomputed_equity,
        "ending_equity_matches_recomputed_patch": math.isclose(reported_equity, recomputed_equity, rel_tol=0.0, abs_tol=1e-6),
        "risk_model_inside_filtered_replay": "1pct_of_current_active_capital_per_trade",
        "filtered_replay_uses_profit_vault_locking": False,
        "filtered_replay_uses_native_locked_profit_path": False,
        "native_profit_vault_active_trading_capital": active_capital_field,
        "native_profit_vault_locked_profit": locked_profit_field,
        "filtered_replay_deducts_execution_costs_inside_equity_curve": False,
        "execution_costs_reported_separately_only": True,
        "interpretation": "patched_equity_is_filtered_trade_theoretical_compounding_artifact"
        if reported_equity > native_ending_equity * 100.0
        else "patched_equity_is_directionally_consistent_but_still_research_only",
    }
    markdown = "\n".join(
        [
            "# Equity Explosion Accounting Audit",
            "",
            f"- chronological replay order: `{payload['chronological_replay_order_confirmed']}`",
            f"- native ledger ending equity: `{native_ending_equity}`",
            f"- raw proxy replay ending equity: `{proxy_ending_equity}`",
            f"- patched reported ending equity: `{reported_equity}`",
            f"- patched recomputed ending equity: `{recomputed_equity}`",
            "",
            "The patched equity figure is produced by a filtered-trade proxy replay that compounds 1% risk off the current active capital on each kept trade.",
            "It does not replay the native engine's profit-vault lock/release path and does not deduct execution costs inside the compounded equity curve.",
            "So the very large ending equity should be treated as a theoretical selectivity-compounding artifact, not as a native engine cash-equity truth.",
            "",
        ]
    )
    return payload, markdown


def _no_go_risks(
    *,
    bluntness_payload: dict[str, Any],
    accounting_payload: dict[str, Any],
    variant_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    rescue_candidates = [row for row in variant_rows if "RESCUE" in str(row.get("variant_name") or "")]
    rescue_best = max(rescue_candidates, key=lambda row: float(row.get("ending_equity") or 0.0), default={})
    flags = {
        "accounting_reconciliation_needed": accounting_payload.get("interpretation") == "patched_equity_is_filtered_trade_theoretical_compounding_artifact",
        "patch_too_blunt_on_short_convexity": float(bluntness_payload.get("removed_short_winner_total_R") or 0.0) > 100.0,
        "patch_relies_on_extreme_selectivity": float(bluntness_payload.get("trade_selectivity_ratio") or 0.0) > 0.75,
        "patch_benefit_depends_on_loss_cleanup": float(bluntness_payload.get("removed_loser_abs_R") or 0.0) > float(bluntness_payload.get("removed_winner_total_R") or 0.0),
        "rescued_short_overlay_promising": bool(rescue_best) and float(rescue_best.get("ending_equity") or 0.0) > 0.0,
    }
    return {
        **RESEARCH_ONLY_FLAGS,
        "flags": flags,
        "promotion_blocker_count": sum(1 for key, value in flags.items() if value and key != "rescued_short_overlay_promising"),
        "best_rescue_variant": rescue_best.get("variant_name"),
    }


def _classification(*, no_go_payload: dict[str, Any], variant_rows: list[dict[str, Any]]) -> str:
    flags = no_go_payload.get("flags", {})
    if flags.get("accounting_reconciliation_needed"):
        return "PATCH_ACCOUNTING_NEEDS_RECONCILIATION"
    best_rescue = max(
        [row for row in variant_rows if "RESCUE" in str(row.get("variant_name") or "")],
        key=lambda row: float(row.get("ending_equity") or 0.0),
        default={},
    )
    if best_rescue and float(best_rescue.get("ending_equity") or 0.0) > 0.0 and flags.get("patch_too_blunt_on_short_convexity"):
        return "PATCH_STRONG_AND_SHORT_RESCUE_PROMISING"
    if flags.get("patch_too_blunt_on_short_convexity"):
        return "PATCH_STRONG_BUT_TOO_BLUNT"
    moonshot_rows = [row for row in variant_rows if row.get("variant_name") == "FROZEN_PATCH"]
    if moonshot_rows and str(moonshot_rows[0].get("moonshot_dependency_classification") or "") == "TOO_MOONSHOT_DEPENDENT":
        return "PATCH_STRONG_BUT_MOONSHOT_DEPENDENT"
    return "PATCH_REJECTED_AFTER_BLUNTNESS_AUDIT"


def _next_recommendation(classification: str) -> dict[str, Any]:
    if classification == "PATCH_ACCOUNTING_NEEDS_RECONCILIATION":
        step = "reconcile_filtered_replay_accounting_then_test_targeted_short_rescue_overlays"
    elif classification == "PATCH_STRONG_AND_SHORT_RESCUE_PROMISING":
        step = "test_narrow_short_rescue_rules_without_touching_live_or_runtime"
    elif classification == "PATCH_STRONG_BUT_TOO_BLUNT":
        step = "keep_patch_research_only_and inspect exact short rescue predicates"
    elif classification == "PATCH_STRONG_BUT_MOONSHOT_DEPENDENT":
        step = "cap_moonshots_and stress_test_before_any_further_interest"
    else:
        step = "reject_for_promotion_and continue forensic structural research only"
    return {
        **RESEARCH_ONLY_FLAGS,
        "next_step": step,
    }


def _report_markdown(
    *,
    classification: str,
    raw_summary: dict[str, Any],
    patch_summary: dict[str, Any],
    bluntness_payload: dict[str, Any],
    accounting_payload: dict[str, Any],
    no_go_payload: dict[str, Any],
    top_removed_shorts: list[dict[str, Any]],
    removed_winners_by_year_archetype: list[dict[str, Any]],
    removed_losers_by_year_failure: list[dict[str, Any]],
    next_step: dict[str, Any],
) -> str:
    lines = [
        "# Broad Patch Bluntness Audit",
        "",
        "This is a research-only forensic audit built from the completed broad BTCUSDT replay ledger and the frozen patch outputs already on disk.",
        "",
        "## Headline",
        "",
        f"- classification: `{classification}`",
        f"- raw broad ending equity: `{raw_summary.get('raw_broad_ending_equity')}`",
        f"- patched broad ending equity: `{patch_summary.get('patched_broad_ending_equity')}`",
        f"- removed winners: `{bluntness_payload.get('removed_winner_count')}`",
        f"- removed losers: `{bluntness_payload.get('removed_loser_count')}`",
        f"- removed short winner total R: `{bluntness_payload.get('removed_short_winner_total_R')}`",
        f"- drawdown reduction: `{bluntness_payload.get('drawdown_reduction_pct_points')}`",
        "",
        "## Court-test explanation",
        "",
        "The frozen patch clearly removes a large amount of losing flow and materially reduces drawdown, but it is also too blunt on the short side.",
        "The top removed winners are major short moonshots, which means the patch is not just deleting garbage; it is also deleting real convexity.",
        "",
        f"- accounting interpretation: `{accounting_payload.get('interpretation')}`",
        f"- no-go blockers: `{no_go_payload.get('promotion_blocker_count')}`",
        "",
        "## Biggest removed short winners",
        "",
    ]
    for row in top_removed_shorts[:5]:
        lines.append(
            f"- `{row.get('trade_id')}` year=`{row.get('year')}` R=`{row.get('r_multiple')}` archetype=`{row.get('archetype_key')}` reason=`{row.get('failed_predicate')}`"
        )
    lines.extend(
        [
            "",
            "## Removed winner hotspots",
            "",
        ]
    )
    for row in removed_winners_by_year_archetype[:5]:
        lines.append(
            f"- year `{row.get('year')}` archetype `{row.get('archetype_key')}` total_R `{row.get('total_R')}` trades `{row.get('trade_count')}`"
        )
    lines.extend(
        [
            "",
            "## Removed loser hotspots",
            "",
        ]
    )
    for row in removed_losers_by_year_failure[:5]:
        lines.append(
            f"- year `{row.get('year')}` side `{row.get('side')}` failure `{row.get('failure_mode_bucket')}` total_R `{row.get('total_R')}` trades `{row.get('trade_count')}`"
        )
    lines.extend(
        [
            "",
            "## Conclusion",
            "",
            "The patch wins for multiple reasons: deleting many losing trades, reducing drawdown path damage, reducing cost load, and becoming extremely selective.",
            "But the huge patched ending equity is not a native engine cash-equity truth; it is a filtered-trade compounding artifact and must be treated as such.",
            "Any next step should stay research-only and focus on whether specific removed short moonshots can be rescued without reintroducing too many losses.",
            "",
            f"- next recommended step: `{next_step.get('next_step')}`",
            "",
        ]
    )
    return "\n".join(lines)


def write_broad_patch_bluntness_audit(config: BroadPatchBluntnessAuditConfig) -> dict[str, Path]:
    paths = _paths(config)
    required = (
        paths["trades"],
        paths["setup_log"],
        paths["level_log"],
        paths["liquidity_events"],
        paths["ledger_summary"],
        paths["profit_vault"],
        paths["frozen_patch_rules"],
        paths["patch_summary"],
        paths["patch_comparison"],
        paths["top_removed_winners"],
        paths["top_removed_losers"],
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return _empty_outputs(config, [f"missing_required_artifact:{path}" for path in missing])

    trade_rows = _read_csv_rows(paths["trades"])
    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    cooldown_rows = _read_csv_optional(paths["cooldown_log"])
    raw_ledger_summary = _read_json(paths["ledger_summary"], {})
    profit_vault = _read_json(paths["profit_vault"], {})
    raw_execution = _read_json(paths["execution_cost_sensitivity"], {})
    broad_summary = _read_json(paths["broad_summary"], {})
    broad_health = _read_json(paths["broad_health"], {})
    patch_summary = _read_json(paths["patch_summary"], {})
    patch_comparison = _read_json(paths["patch_comparison"], {})
    top_removed_winners = _read_csv_rows(paths["top_removed_winners"])
    top_removed_losers = _read_csv_rows(paths["top_removed_losers"])

    matched_short_archetypes, disabled_long_modes, frozen_rules = _load_frozen_rules(paths["frozen_patch_rules"])
    if not matched_short_archetypes:
        return _empty_outputs(config, ["missing_frozen_matched_short_archetypes"])

    normalized_rows = _normalize_trade_rows(trade_rows, setup_rows, level_rows, liquidity_rows)
    if not normalized_rows:
        return _empty_outputs(config, ["no_usable_trade_rows"])

    prepared_rows = _prepare_rows(normalized_rows)
    kept_rows, removed_rows = _apply_frozen_patch(
        prepared_rows,
        matched_short_archetypes=matched_short_archetypes,
        disabled_long_modes=disabled_long_modes,
    )

    raw_proxy_output = _simulate_rows(
        name="RAW_BROAD_PROXY_REPLAY",
        selected_rows=prepared_rows,
        all_rows=prepared_rows,
        cooldown_rows=cooldown_rows,
    )
    frozen_patch_output = _simulate_rows(
        name="FROZEN_PATCH",
        selected_rows=kept_rows,
        all_rows=prepared_rows,
        cooldown_rows=cooldown_rows,
    )
    raw_proxy_summary = raw_proxy_output["summary"]
    frozen_patch_summary = frozen_patch_output["summary"]

    original_trade_map = _find_original_trades(trade_rows)
    removed_short_winners = _sort_rows(
        [row for row in removed_rows if row.get("side") == "short" and float(row.get("r_multiple") or 0.0) > 0.0]
    )
    removed_short_winners_r_desc = sorted(
        removed_short_winners,
        key=lambda row: (float(row.get("r_multiple") or 0.0), float(row.get("pnl") or 0.0)),
        reverse=True,
    )

    rescue_ge_3 = _sort_rows(kept_rows + [row for row in removed_short_winners if float(row.get("r_multiple") or 0.0) >= 3.0])
    rescue_ge_5 = _sort_rows(kept_rows + [row for row in removed_short_winners if float(row.get("r_multiple") or 0.0) >= 5.0])
    rescue_ge_10 = _sort_rows(kept_rows + [row for row in removed_short_winners if float(row.get("r_multiple") or 0.0) >= 10.0])
    rescue_top20 = _sort_rows(kept_rows + removed_short_winners_r_desc[:20])
    long_filter_all_shorts = _sort_rows(
        [row for row in prepared_rows if row.get("side") == "short" or row.get("long_failure_mode") not in disabled_long_modes]
    )

    variant_specs = {
        "FROZEN_PATCH": {"rows": kept_rows, "moonshot_override": None},
        "FROZEN_PATCH_RESCUE_SHORTS_R_GE_3": {"rows": rescue_ge_3, "moonshot_override": None},
        "FROZEN_PATCH_RESCUE_SHORTS_R_GE_5": {"rows": rescue_ge_5, "moonshot_override": None},
        "FROZEN_PATCH_RESCUE_SHORTS_R_GE_10": {"rows": rescue_ge_10, "moonshot_override": None},
        "FROZEN_PATCH_RESCUE_TOP20_REMOVED_SHORT_WINNERS": {"rows": rescue_top20, "moonshot_override": None},
        "REMOVE_ONLY_BAD_LONG_FAILURES_KEEP_ALL_SHORTS": {"rows": long_filter_all_shorts, "moonshot_override": None},
        "FROZEN_PATCH_CAP_10R_TO_5R": {"rows": kept_rows, "moonshot_override": "cap_10_to_5"},
        "FROZEN_PATCH_CAP_5R_TO_3R": {"rows": kept_rows, "moonshot_override": "cap_5_to_3"},
    }

    variant_outputs: dict[str, dict[str, Any]] = {}
    variant_execution: dict[str, Any] = {"research_only": True, "variants": {}}
    variant_yearly_rows: list[dict[str, Any]] = []
    yearly_counts: dict[str, dict[str, int]] = {}
    for name, spec in variant_specs.items():
        variant_output = _simulate_rows(
            name=name,
            selected_rows=spec["rows"],
            all_rows=prepared_rows,
            cooldown_rows=cooldown_rows,
            moonshot_override=spec["moonshot_override"],
        )
        variant_outputs[name] = variant_output
        cost_trade_rows = _variant_trade_rows_for_costs(
            selected_rows=spec["rows"],
            original_trade_map=original_trade_map,
            moonshot_override=spec["moonshot_override"],
        )
        cost_output_root = config.output_root / "diagnostics" / "execution_realism" / name.lower()
        variant_execution["variants"][name] = build_execution_cost_outputs(trades=cost_trade_rows, output_root=cost_output_root)
        yearly_rows, counts = _yearly_variant_rows(
            variant_name=name,
            raw_rows=prepared_rows,
            selected_rows=spec["rows"],
            cooldown_rows=cooldown_rows,
            moonshot_override=spec["moonshot_override"],
        )
        variant_yearly_rows.extend(yearly_rows)
        yearly_counts[name] = counts

    patched_execution = variant_execution["variants"]["FROZEN_PATCH"]
    quadrant_rows = _quadrant_audit_rows(kept_rows, removed_rows)
    removed_winner_year_archetype_rows = _removed_winners_by_archetype_year(removed_rows)
    removed_loser_year_failure_rows = _removed_losers_by_failure_mode_year(removed_rows)
    removed_short_convexity_rows = _removed_short_convexity_rows(
        removed_rows,
        matched_short_archetypes=matched_short_archetypes,
        top_removed_winners=top_removed_winners,
    )
    removed_loss_rows = _removed_loss_failure_mode_rows(removed_rows)
    variant_rows = _variant_rows_for_output(
        raw_ledger_summary=raw_ledger_summary,
        raw_proxy_summary=raw_proxy_summary,
        variant_outputs=variant_outputs,
        yearly_counts=yearly_counts,
    )

    bluntness_payload = _bluntness_payload(
        raw_proxy_summary=raw_proxy_summary,
        patched_summary=frozen_patch_summary,
        removed_rows=removed_rows,
        kept_rows=kept_rows,
        removed_short_convexity_rows=removed_short_convexity_rows,
        baseline_execution=raw_execution,
        patched_execution=patched_execution,
    )
    accounting_payload, accounting_md = _equity_explosion_accounting_audit(
        raw_ledger_summary=raw_ledger_summary,
        raw_proxy_summary=raw_proxy_summary,
        patched_summary=patch_summary,
        kept_rows=kept_rows,
        patched_output=frozen_patch_output,
        profit_vault=profit_vault,
    )
    no_go_payload = _no_go_risks(
        bluntness_payload=bluntness_payload,
        accounting_payload=accounting_payload,
        variant_rows=variant_rows,
    )
    classification = _classification(no_go_payload=no_go_payload, variant_rows=variant_rows)
    next_step = _next_recommendation(classification)

    summary_payload = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "broad_replay_state": broad_health.get("successful_replay"),
        "frozen_patch_candidate": "BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT",
        "raw_broad_ending_equity": patch_summary.get("raw_broad_ending_equity"),
        "patched_broad_ending_equity": patch_summary.get("patched_broad_ending_equity"),
        "raw_broad_profit_factor": patch_summary.get("raw_broad_profit_factor"),
        "patched_broad_profit_factor": patch_summary.get("patched_broad_profit_factor"),
        "removed_winner_count": bluntness_payload["removed_winner_count"],
        "removed_loser_count": bluntness_payload["removed_loser_count"],
        "removed_short_winner_total_R": bluntness_payload["removed_short_winner_total_R"],
        "drawdown_reduction_pct_points": bluntness_payload["drawdown_reduction_pct_points"],
        "primary_driver_guess": bluntness_payload["primary_driver_guess"],
        "best_rescue_variant": no_go_payload.get("best_rescue_variant"),
        "final_classification": classification,
        "next_recommended_step": next_step.get("next_step"),
    }
    report_md = _report_markdown(
        classification=classification,
        raw_summary=patch_summary,
        patch_summary=patch_summary,
        bluntness_payload=bluntness_payload,
        accounting_payload=accounting_payload,
        no_go_payload=no_go_payload,
        top_removed_shorts=removed_short_convexity_rows,
        removed_winners_by_year_archetype=removed_winner_year_archetype_rows,
        removed_losers_by_year_failure=removed_loser_year_failure_rows,
        next_step=next_step,
    )

    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    _write_json(
        config.output_root / "status.json",
        {
            "state": "complete",
            "resolved_at_utc": summary_payload["resolved_at_utc"],
            **RESEARCH_ONLY_FLAGS,
        },
    )
    _write_json(config.output_root / "broad_patch_bluntness_summary.json", summary_payload)
    _write_markdown(config.output_root / "broad_patch_bluntness_report.md", report_md)
    _write_csv(diagnostics_root / "kept_removed_quadrant_audit.csv", quadrant_rows)
    _write_csv(diagnostics_root / "removed_short_convexity_audit.csv", removed_short_convexity_rows)
    _write_csv(diagnostics_root / "removed_loss_failure_mode_audit.csv", removed_loss_rows)
    _write_csv(diagnostics_root / "variant_replay_comparison.csv", variant_rows)
    _write_json(diagnostics_root / "variant_execution_cost_sensitivity.json", variant_execution)
    _write_csv(diagnostics_root / "variant_yearly_survival.csv", variant_yearly_rows)
    _write_csv(diagnostics_root / "removed_winners_by_archetype_year.csv", removed_winner_year_archetype_rows)
    _write_csv(diagnostics_root / "removed_losers_by_failure_mode_year.csv", removed_loser_year_failure_rows)
    _write_json(diagnostics_root / "equity_explosion_accounting_audit.json", accounting_payload)
    _write_markdown(diagnostics_root / "equity_explosion_accounting_audit.md", accounting_md)
    _write_json(diagnostics_root / "no_go_risks.json", no_go_payload)
    _write_json(reports_root / "next_research_recommendation.json", next_step)
    _write_markdown(
        reports_root / "next_research_recommendation.md",
        "# Next Research Recommendation\n\n"
        f"- next_step: `{next_step.get('next_step')}`\n"
        f"- final_classification: `{classification}`\n"
        "- This remains research-only and does not change live, paper, runtime, or production behavior.\n",
    )
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "broad_patch_bluntness_summary.json",
        "report": config.output_root / "broad_patch_bluntness_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    result = write_broad_patch_bluntness_audit(
        BroadPatchBluntnessAuditConfig(
            package_root=package_root,
            output_root=package_root / "output" / "broad_patch_bluntness_audit_001",
        )
    )
    print(result["summary"])


if __name__ == "__main__":
    main()
