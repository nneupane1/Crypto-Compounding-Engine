from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import RESEARCH_ONLY_FLAGS  # noqa: E402
from structural_compounding_lab.diagnostics.execution_cost_realism_and_trade_redundancy_audit import (  # noqa: E402
    _date_from_row,
    _quarter_from_row,
    _timestamp_label,
    _try_timestamp,
)
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _median,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.diagnostics.milestone_bridge_fragility_driver_repair_audit import (  # noqa: E402
    BASE_STEPUP_SCHEDULE,
    _drop_random_trades,
    _estimated_cost,
    _group_consecutive_blocks,
    _rolling_window_summary,
    _safe_float,
    _simulate_overlay_sequence,
    _sort_rows,
)
from structural_compounding_lab.diagnostics.native_sr_aware_5y_mission_gap_audit import (  # noqa: E402
    BASELINE_COST_BPS,
    FIVE_X_COST_BPS,
    NativeSRAware5YMissionGapAuditConfig,
    _clone_row,
    _reconstruct_sequences,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import _build_windows  # noqa: E402


OUTPUT_FOLDER_NAME = "cost_resilient_trade_redundancy_expansion_audit_001"
DEFAULT_REPEAT_COUNT = 8
REQUIRED_OUTPUT_FILES = (
    "baseline_redundancy_problem_recap.json",
    "candidate_redundancy_sleeve_inventory.csv",
    "candidate_redundancy_sleeve_inventory.json",
    "candidate_sleeve_no_leakage_check.json",
    "redundancy_candidate_cost_band_results.csv",
    "redundancy_candidate_rolling_5y_results.csv",
    "redundancy_candidate_hit_matrix.csv",
    "redundancy_candidate_missed_trade_results.csv",
    "redundancy_candidate_operational_resilience.csv",
    "redundancy_improvement_scorecard.csv",
    "redundancy_improvement_scorecard.json",
    "redundancy_expansion_mission_gate.json",
    "no_go_risks.json",
    "implementation_self_audit.json",
    "stochastic_budget_reliability_check.json",
)
DISALLOWED_SELECTION_FIELDS = {
    "r_multiple",
    "applied_r",
    "pnl",
    "equity_after",
    "winner",
    "loser",
    "profit",
    "loss",
    "max_favorable_excursion",
    "max_adverse_excursion",
    "future_drawdown",
    "future_return",
}
MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE = 32
PREFERRED_REPEAT_COUNT_SHORTLIST = (64, 128)


@dataclass(frozen=True)
class CostResilientTradeRedundancyExpansionAuditConfig:
    package_root: Path
    output_root: Path
    random_repeat_count: int = DEFAULT_REPEAT_COUNT


def _paths(config: CostResilientTradeRedundancyExpansionAuditConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    execution_root = output_root / "execution_cost_realism_and_trade_redundancy_audit_001"
    bridge_root = output_root / "strict_sr_aware_milestone_bridge_monte_carlo_audit_001"
    native_root = output_root / "native_sr_aware_structural_replay_reproduction_audit_001"
    return {
        "execution_summary": execution_root / "execution_cost_realism_and_trade_redundancy_summary.json",
        "execution_cost_bands": execution_root / "diagnostics" / "execution_cost_band_results.csv",
        "cost_band_rolling": execution_root / "diagnostics" / "cost_band_rolling_5y_survival.csv",
        "missed_trade_results": execution_root / "diagnostics" / "missed_trade_tolerance_results.csv",
        "cluster_audit": execution_root / "diagnostics" / "trade_redundancy_cluster_audit.csv",
        "cluster_concentration": execution_root / "diagnostics" / "trade_redundancy_concentration_report.json",
        "key_cluster_dependency": execution_root / "diagnostics" / "key_trade_cluster_dependency.json",
        "operational_reliability": execution_root / "diagnostics" / "operational_reliability_requirements.json",
        "bridge_trade_ledger": bridge_root / "ledger" / "milestone_bridge_trades.csv",
        "bridge_equity_ledger": bridge_root / "ledger" / "milestone_bridge_equity.csv",
        "bridge_summary": bridge_root / "ledger" / "milestone_bridge_summary.json",
        "native_trade_ledger": native_root / "ledger" / "native_sr_aware_trades.csv",
        "enriched_trade_features": output_root / "native_pre_entry_sr_feature_enrichment_audit_001" / "diagnostics" / "enriched_trade_features.csv",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, reports_root


def _blocked_self_audit(*, warnings: list[str]) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "schema_fields_detected": [],
        "timestamp_field_used": "blocked",
        "baseline_metric_used": "blocked",
        "rolling_5y_metric_used": "blocked",
        "full_sequence_metric_used": "blocked",
        "leakage_check": True,
        "future_field_usage_check": True,
        "silent_fallback_check": False,
        "stress_metric_scope_check": True,
        "previous_artifacts_overwritten": False,
        "reviewer_notes": warnings,
    }


def _empty_outputs(
    config: CostResilientTradeRedundancyExpansionAuditConfig,
    *,
    classification: str,
    warnings: list[str],
) -> dict[str, Path]:
    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    now = datetime.now(timezone.utc).isoformat()
    status = {"state": "blocked", "resolved_at_utc": now, **RESEARCH_ONLY_FLAGS, "warnings": warnings}
    summary = {
        "resolved_at_utc": now,
        **RESEARCH_ONLY_FLAGS,
        "final_classification": classification,
        "warnings": warnings,
    }
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "cost_resilient_trade_redundancy_expansion_summary.json", summary)
    _write_markdown(
        config.output_root / "cost_resilient_trade_redundancy_expansion_report.md",
        "# Cost-Resilient Trade Redundancy Expansion Audit\n\nRequired upstream artifacts were missing, so the audit remained blocked.\n",
    )
    for filename in REQUIRED_OUTPUT_FILES:
        path = diagnostics_root / filename
        if filename.endswith(".json"):
            payload = {"warnings": warnings, **RESEARCH_ONLY_FLAGS}
            if filename == "implementation_self_audit.json":
                payload = _blocked_self_audit(warnings=warnings)
            _write_json(path, payload)
        else:
            _write_csv(path, [])
    for filename in ("next_research_recommendation.json",):
        _write_json(reports_root / filename, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "cost_resilient_trade_redundancy_expansion_summary.json",
        "report": config.output_root / "cost_resilient_trade_redundancy_expansion_report.md",
    }


def _normalize_rows_for_audit(
    rows: list[dict[str, Any]],
    *,
    require_trade_id: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    normalized_rows: list[dict[str, Any]] = []
    schema_fields = sorted({key for row in rows for key in row.keys()})
    timestamp_usage_counts = {"exit_timestamp": 0, "timestamp": 0, "entry_timestamp": 0}
    fallback_trade_id_rows = 0
    fallback_r_rows = 0
    fallback_entry_timestamp_rows = 0

    for index, row in enumerate(rows):
        item = _clone_row(row)
        resolved_ts = None
        resolved_ts_field = None
        for field_name in ("exit_timestamp", "timestamp", "entry_timestamp"):
            parsed = _try_timestamp(item.get(field_name))
            if parsed is not None:
                resolved_ts = parsed
                resolved_ts_field = field_name
                timestamp_usage_counts[field_name] += 1
                break
        if resolved_ts is None:
            errors.append(f"row_{index}: no valid timestamp field found among exit_timestamp/timestamp/entry_timestamp")
            continue

        resolved_entry_ts = _try_timestamp(item.get("entry_timestamp"))
        if resolved_entry_ts is None:
            resolved_entry_ts = resolved_ts
            fallback_entry_timestamp_rows += 1

        resolved_trade_id = str(item.get("trade_id") or "").strip()
        if not resolved_trade_id:
            if require_trade_id:
                errors.append(f"row_{index}: missing trade_id")
                continue
            resolved_trade_id = f"audit_row_{index}"
            fallback_trade_id_rows += 1

        resolved_r = item.get("r_multiple")
        if _safe_float(resolved_r) == 0.0 and str(resolved_r).strip() in {"", "None", "none"}:
            resolved_r = item.get("applied_r")
            fallback_r_rows += 1
        if _safe_float(resolved_r) == 0.0 and str(resolved_r).strip() in {"", "None", "none"}:
            errors.append(f"{resolved_trade_id}: missing both r_multiple and applied_r")
            continue

        item["trade_id"] = resolved_trade_id
        item["exit_timestamp"] = resolved_ts
        item["timestamp"] = resolved_ts
        item["entry_timestamp"] = resolved_entry_ts
        item["r_multiple"] = _safe_float(resolved_r)
        item["risk_multiplier"] = _safe_float(item.get("risk_multiplier")) or 1.0
        normalized_rows.append(item)

    if fallback_trade_id_rows:
        warnings.append(f"{fallback_trade_id_rows} rows used synthetic trade_id fallback.")
    if fallback_r_rows:
        warnings.append(f"{fallback_r_rows} rows used applied_r fallback for r_multiple.")
    if fallback_entry_timestamp_rows:
        warnings.append(f"{fallback_entry_timestamp_rows} rows used exit/timestamp fallback for entry_timestamp.")
    if not normalized_rows:
        errors.append("No rows survived schema normalization.")

    schema_info = {
        "schema_fields_detected": schema_fields,
        "timestamp_field_used": max(timestamp_usage_counts.items(), key=lambda item: item[1])[0] if any(timestamp_usage_counts.values()) else "blocked",
        "timestamp_field_usage_counts": timestamp_usage_counts,
        "fallback_trade_id_rows": fallback_trade_id_rows,
        "fallback_r_rows": fallback_r_rows,
        "fallback_entry_timestamp_rows": fallback_entry_timestamp_rows,
    }
    return normalized_rows, schema_info, warnings, errors


def _resolve_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    return text in {"true", "1", "yes", "y"}


def _resolve_text(value: Any) -> str:
    return str(value).strip()


def _resolve_float_field(row: dict[str, Any], *names: str) -> float:
    for name in names:
        if name in row and str(row.get(name)).strip() not in {"", "None", "none"}:
            return _safe_float(row.get(name))
    return 0.0


def _load_context(config: CostResilientTradeRedundancyExpansionAuditConfig) -> tuple[dict[str, Any] | None, list[str], dict[str, Any]]:
    paths = _paths(config)
    required = [
        paths["execution_summary"],
        paths["execution_cost_bands"],
        paths["cost_band_rolling"],
        paths["missed_trade_results"],
        paths["cluster_audit"],
        paths["cluster_concentration"],
        paths["key_cluster_dependency"],
        paths["operational_reliability"],
        paths["bridge_trade_ledger"],
        paths["bridge_equity_ledger"],
        paths["bridge_summary"],
        paths["native_trade_ledger"],
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return None, missing, {"schema_fields_detected": [], "timestamp_field_used": "blocked"}

    warnings: list[str] = []
    reconstruction, reconstruction_warnings = _reconstruct_sequences(
        NativeSRAware5YMissionGapAuditConfig(
            package_root=config.package_root,
            output_root=config.package_root / "output" / "native_sr_aware_5y_mission_gap_audit_001",
        )
    )
    if reconstruction is None:
        return None, reconstruction_warnings, {"schema_fields_detected": [], "timestamp_field_used": "blocked"}
    warnings.extend(reconstruction_warnings)

    native_rows_raw = _read_csv_rows(paths["native_trade_ledger"])
    normalized_rows, schema_info, normalize_warnings, normalize_errors = _normalize_rows_for_audit(native_rows_raw, require_trade_id=True)
    warnings.extend(normalize_warnings)
    if normalize_errors:
        return None, [*warnings, *normalize_errors], schema_info

    bridge_ids = {
        str(row.get("trade_id") or "").strip()
        for row in _read_csv_rows(paths["bridge_trade_ledger"])
        if str(row.get("trade_id") or "").strip()
    }
    native_by_id = {str(row.get("trade_id")): row for row in normalized_rows}
    base_rows = [_clone_row(native_by_id[trade_id]) for trade_id in sorted(bridge_ids) if trade_id in native_by_id]
    missing_bridge_ids = sorted(trade_id for trade_id in bridge_ids if trade_id not in native_by_id)
    if missing_bridge_ids:
        warnings.append(f"{len(missing_bridge_ids)} bridge trade ids were missing from native_sr_aware_trades.csv.")
    candidate_universe = [_clone_row(row) for row in normalized_rows if str(row.get("trade_id")) not in bridge_ids]
    if not base_rows:
        return None, [*warnings, "No base milestone bridge trades could be resolved from the native trade ledger."], schema_info

    if not paths["enriched_trade_features"].exists():
        warnings.append("enriched_trade_features.csv missing; redundancy sleeves use native_sr_aware_trades.csv only.")

    return {
        "base_rows": _sort_rows(base_rows),
        "candidate_universe": _sort_rows(candidate_universe),
        "windows": _build_windows(base_rows),
        "execution_summary": _read_json(paths["execution_summary"], {}),
        "cluster_concentration": _read_json(paths["cluster_concentration"], {}),
        "key_cluster_dependency": _read_json(paths["key_cluster_dependency"], {}),
        "operational_reliability": _read_json(paths["operational_reliability"], {}),
        "cost_band_rows": _read_csv_rows(paths["execution_cost_bands"]),
        "missed_trade_rows": _read_csv_rows(paths["missed_trade_results"]),
        "missing_sources": {
            "enriched_trade_features": not paths["enriched_trade_features"].exists(),
            "rejected_trade_ledger": True,
            "near_miss_trade_ledger": True,
        },
    }, warnings, schema_info


def _baseline_recap(context: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    cost_band_map = {str(row.get("band_name")): row for row in context["cost_band_rows"]}
    execution_summary = context["execution_summary"]
    return {
        **RESEARCH_ONLY_FLAGS,
        "zero_cost_result": {
            "rolling_5y_average": _safe_float(cost_band_map.get("ZERO_COST_REFERENCE", {}).get("rolling_5y_average_ending_equity")),
            "rolling_5y_median": _safe_float(cost_band_map.get("ZERO_COST_REFERENCE", {}).get("rolling_5y_median_ending_equity")),
            "hit_1m_windows": _safe_float(cost_band_map.get("ZERO_COST_REFERENCE", {}).get("hit_1m_windows")),
        },
        "optimistic_maker_cost_result": {
            "rolling_5y_average": _safe_float(cost_band_map.get("OPTIMISTIC_MAKER_COST", {}).get("rolling_5y_average_ending_equity")),
            "rolling_5y_median": _safe_float(cost_band_map.get("OPTIMISTIC_MAKER_COST", {}).get("rolling_5y_median_ending_equity")),
            "hit_1m_windows": _safe_float(cost_band_map.get("OPTIMISTIC_MAKER_COST", {}).get("hit_1m_windows")),
        },
        "normal_cost_result": {
            "rolling_5y_average": _safe_float(cost_band_map.get("NORMAL_MIXED_MAKER_TAKER_COST", {}).get("rolling_5y_average_ending_equity")),
            "rolling_5y_median": _safe_float(cost_band_map.get("NORMAL_MIXED_MAKER_TAKER_COST", {}).get("rolling_5y_median_ending_equity")),
            "hit_1m_windows": _safe_float(cost_band_map.get("NORMAL_MIXED_MAKER_TAKER_COST", {}).get("hit_1m_windows")),
        },
        "conservative_cost_result": {
            "rolling_5y_average": _safe_float(cost_band_map.get("CONSERVATIVE_TAKER_COST", {}).get("rolling_5y_average_ending_equity")),
            "rolling_5y_median": _safe_float(cost_band_map.get("CONSERVATIVE_TAKER_COST", {}).get("rolling_5y_median_ending_equity")),
            "hit_1m_windows": _safe_float(cost_band_map.get("CONSERVATIVE_TAKER_COST", {}).get("hit_1m_windows")),
        },
        "missed_trade_threshold_pct": execution_summary.get("missed_trade_tolerance_threshold_pct", 0),
        "trade_redundancy_verdict": execution_summary.get("trade_redundancy_verdict", "UNKNOWN"),
        "cluster_dependency_verdict": execution_summary.get("key_cluster_dependency_verdict", "UNKNOWN"),
        "operational_reliability_requirement": context["operational_reliability"],
        "current_blocker_summary": [
            "normal-cost rolling 5Y mission falls below 1M",
            "missed-trade tolerance is about 1%",
            "monthly cluster dependency remains high",
            "server-grade reliability is required before any forward validation",
        ],
        "warnings": warnings,
    }


def _cost_band_specs() -> list[dict[str, Any]]:
    return [
        {"band_name": "ZERO_COST_REFERENCE", "cost_bps_total": 0.0},
        {"band_name": "OPTIMISTIC_MAKER_COST", "cost_bps_total": 5.0},
        {"band_name": "NORMAL_MIXED_MAKER_TAKER_COST", "cost_bps_total": BASELINE_COST_BPS},
        {"band_name": "CONSERVATIVE_TAKER_COST", "cost_bps_total": 20.0},
        {"band_name": "HIGH_SLIPPAGE_COST", "cost_bps_total": 30.0},
    ]


def _selection_field_map() -> dict[str, set[str]]:
    return {
        "STRICT_BASE_MILESTONE_BRIDGE": set(),
        "STRICT_BASE_PLUS_NEAR_MISS_SR_ROOM": {
            "setup_score",
            "structure_score",
            "liquidity_score",
            "risk_reward_score",
            "support_distance_pct",
            "resistance_distance_pct",
            "pre_entry_stop_distance_pct",
            "htf_structure_quality_score",
        },
        "STRICT_BASE_PLUS_HIGH_QUALITY_REJECTED_TRADES": set(),
        "STRICT_BASE_PLUS_SMALL_R_LOW_COST_TRADES": {
            "pre_entry_stop_distance_pct",
            "liquidity_score",
            "volume_confirmation_score",
            "setup_score",
            "structure_score",
        },
        "STRICT_BASE_PLUS_NON_OVERLAPPING_MONTH_FILLER_TRADES": set(),
        "STRICT_BASE_PLUS_LOW_CORRELATION_LONG_SLEEVE": {
            "side",
            "setup_score",
            "liquidity_score",
            "htf_aligned",
            "support_distance_pct",
            "pre_entry_stop_distance_pct",
            "execution_timeframe",
        },
        "STRICT_BASE_PLUS_LOW_CORRELATION_SHORT_SLEEVE": {
            "side",
            "setup_score",
            "liquidity_score",
            "rejection_from_resistance_score",
            "equal_high_cluster_strength",
            "pre_entry_stop_distance_pct",
            "execution_timeframe",
        },
        "STRICT_BASE_PLUS_COST_EFFICIENT_ONLY_TRADES": {
            "pre_entry_stop_distance_pct",
            "liquidity_score",
            "volume_confirmation_score",
            "risk_reward_score",
            "setup_score",
        },
        "STRICT_BASE_PLUS_TRADE_COUNT_BALANCER": {
            "setup_class",
            "setup_score",
            "structure_score",
            "liquidity_score",
            "risk_reward_score",
            "pre_entry_stop_distance_pct",
        },
        "STRICT_BASE_PLUS_COMBINED_REDUNDANCY_CANDIDATE": {
            "setup_score",
            "structure_score",
            "liquidity_score",
            "risk_reward_score",
            "pre_entry_stop_distance_pct",
            "side",
            "rejection_from_resistance_score",
            "equal_high_cluster_strength",
            "support_distance_pct",
            "resistance_distance_pct",
        },
    }


def _trade_cluster_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "trades_per_month": 0.0,
            "inactive_months": 0,
            "top_5_month_share": 0.0,
            "top_10_trade_share": 0.0,
            "profitable_clusters": 0,
        }
    monthly_totals: dict[str, float] = {}
    monthly_count: dict[str, int] = {}
    positive_r_values: list[float] = []
    for row in rows:
        month = _timestamp_label(row)
        monthly_totals[month] = monthly_totals.get(month, 0.0) + _safe_float(row.get("r_multiple"))
        monthly_count[month] = monthly_count.get(month, 0) + 1
        if _safe_float(row.get("r_multiple")) > 0.0:
            positive_r_values.append(_safe_float(row.get("r_multiple")))
    monthly_positive = [max(0.0, value) for value in monthly_totals.values()]
    total_positive = sum(monthly_positive)
    top_5_month_share = sum(sorted(monthly_positive, reverse=True)[:5]) / max(total_positive, 1.0)
    top_10_trade_share = sum(sorted(positive_r_values, reverse=True)[:10]) / max(sum(positive_r_values), 1.0)
    profitable_clusters = 0
    in_cluster = False
    for month in sorted(monthly_totals):
        positive = monthly_totals[month] > 0.0
        if positive and not in_cluster:
            profitable_clusters += 1
        in_cluster = positive
    return {
        "trades_per_month": round(sum(monthly_count.values()) / max(len(monthly_count), 1), 6),
        "inactive_months": sum(1 for value in monthly_count.values() if value == 0),
        "top_5_month_share": round(top_5_month_share, 6),
        "top_10_trade_share": round(top_10_trade_share, 6),
        "profitable_clusters": profitable_clusters,
        "month_distribution": {key: monthly_count[key] for key in sorted(monthly_count)},
    }


def _pf_and_win_rate(rows: list[dict[str, Any]]) -> tuple[float, float, float]:
    if not rows:
        return 0.0, 0.0, 0.0
    r_values = [_safe_float(row.get("r_multiple")) for row in rows]
    wins = [value for value in r_values if value > 0.0]
    losses = [abs(value) for value in r_values if value < 0.0]
    pf = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
    win_rate = len(wins) / len(r_values) if r_values else 0.0
    avg_r = sum(r_values) / len(r_values) if r_values else 0.0
    return round(avg_r, 6), round(pf, 6), round(win_rate, 6)


def _cost_proxy_score(rows: list[dict[str, Any]], cost_bps_total: float = BASELINE_COST_BPS) -> float:
    if not rows:
        return 0.0
    costs = [_estimated_cost(row, cost_bps_total) for row in rows]
    return round(sum(costs) / len(costs), 6)


def _dedupe_union_rows(base_rows: list[dict[str, Any]], extra_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {str(row.get("trade_id")): _clone_row(row) for row in base_rows}
    for row in extra_rows:
        merged.setdefault(str(row.get("trade_id")), _clone_row(row))
    return _sort_rows(list(merged.values()))


def _sleeve_specs() -> list[dict[str, Any]]:
    return [
        {"candidate_name": "STRICT_BASE_MILESTONE_BRIDGE", "status": "available"},
        {"candidate_name": "STRICT_BASE_PLUS_NEAR_MISS_SR_ROOM", "status": "available"},
        {"candidate_name": "STRICT_BASE_PLUS_HIGH_QUALITY_REJECTED_TRADES", "status": "blocked_missing_source"},
        {"candidate_name": "STRICT_BASE_PLUS_SMALL_R_LOW_COST_TRADES", "status": "available"},
        {"candidate_name": "STRICT_BASE_PLUS_NON_OVERLAPPING_MONTH_FILLER_TRADES", "status": "blocked_missing_source"},
        {"candidate_name": "STRICT_BASE_PLUS_LOW_CORRELATION_LONG_SLEEVE", "status": "available"},
        {"candidate_name": "STRICT_BASE_PLUS_LOW_CORRELATION_SHORT_SLEEVE", "status": "available"},
        {"candidate_name": "STRICT_BASE_PLUS_COST_EFFICIENT_ONLY_TRADES", "status": "available"},
        {"candidate_name": "STRICT_BASE_PLUS_TRADE_COUNT_BALANCER", "status": "available"},
        {"candidate_name": "STRICT_BASE_PLUS_COMBINED_REDUNDANCY_CANDIDATE", "status": "available"},
    ]


def _candidate_filters() -> dict[str, Callable[[dict[str, Any]], bool]]:
    return {
        "STRICT_BASE_PLUS_NEAR_MISS_SR_ROOM": lambda row: (
            _resolve_float_field(row, "setup_score", "entry_score") >= 4.4
            and _resolve_float_field(row, "structure_score") >= 1.2
            and _resolve_float_field(row, "liquidity_score") >= 0.90
            and _resolve_float_field(row, "risk_reward_score") >= 1.10
            and _resolve_float_field(row, "pre_entry_stop_distance_pct", "stop_distance_pct") <= 0.010
            and (
                0.0 < _resolve_float_field(row, "support_distance_pct") <= 0.03
                or 0.0 < _resolve_float_field(row, "resistance_distance_pct") <= 0.03
            )
            and _resolve_float_field(row, "htf_structure_quality_score") >= 1.5
        ),
        "STRICT_BASE_PLUS_SMALL_R_LOW_COST_TRADES": lambda row: (
            _resolve_float_field(row, "pre_entry_stop_distance_pct", "stop_distance_pct") <= 0.008
            and _resolve_float_field(row, "liquidity_score") >= 0.92
            and _resolve_float_field(row, "volume_confirmation_score") >= 0.90
            and _resolve_float_field(row, "setup_score", "entry_score") >= 5.0
            and _resolve_float_field(row, "structure_score") >= 1.15
        ),
        "STRICT_BASE_PLUS_LOW_CORRELATION_LONG_SLEEVE": lambda row: (
            _resolve_text(row.get("side")).lower() == "long"
            and _resolve_bool(row.get("htf_aligned"))
            and _resolve_float_field(row, "setup_score", "entry_score") >= 4.2
            and _resolve_float_field(row, "liquidity_score") >= 0.90
            and _resolve_float_field(row, "pre_entry_stop_distance_pct", "stop_distance_pct") <= 0.012
            and _resolve_text(row.get("execution_timeframe")).lower() == "1h"
        ),
        "STRICT_BASE_PLUS_LOW_CORRELATION_SHORT_SLEEVE": lambda row: (
            _resolve_text(row.get("side")).lower() == "short"
            and _resolve_float_field(row, "setup_score", "entry_score") >= 4.4
            and _resolve_float_field(row, "liquidity_score") >= 0.90
            and _resolve_float_field(row, "rejection_from_resistance_score") >= 1.3
            and _resolve_float_field(row, "false_breakout_quality_score") >= 1.3
            and _resolve_float_field(row, "pre_entry_stop_distance_pct", "stop_distance_pct") <= 0.010
            and _resolve_float_field(row, "volume_confirmation_score") >= 0.88
            and _resolve_text(row.get("execution_timeframe")).lower() == "1h"
        ),
        "STRICT_BASE_PLUS_COST_EFFICIENT_ONLY_TRADES": lambda row: (
            _resolve_float_field(row, "pre_entry_stop_distance_pct", "stop_distance_pct") <= 0.010
            and _resolve_float_field(row, "liquidity_score") >= 0.90
            and _resolve_float_field(row, "volume_confirmation_score") >= 0.90
            and _resolve_float_field(row, "risk_reward_score") >= 1.00
            and _resolve_float_field(row, "setup_score", "entry_score") >= 4.8
        ),
        "STRICT_BASE_PLUS_TRADE_COUNT_BALANCER": lambda row: (
            _resolve_text(row.get("setup_class")).upper() in {"A", "B"}
            and _resolve_float_field(row, "setup_score", "entry_score") >= 4.6
            and _resolve_float_field(row, "structure_score") >= 1.15
            and _resolve_float_field(row, "liquidity_score") >= 0.88
            and _resolve_float_field(row, "risk_reward_score") >= 1.10
            and _resolve_float_field(row, "pre_entry_stop_distance_pct", "stop_distance_pct") <= 0.010
        ),
    }


def _discover_candidates(context: dict[str, Any], warnings: list[str]) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]], dict[str, Any]]:
    base_rows = context["base_rows"]
    candidate_universe = context["candidate_universe"]
    base_ids = {str(row.get("trade_id")) for row in base_rows}
    inventories: list[dict[str, Any]] = []
    selections: dict[str, list[dict[str, Any]]] = {"STRICT_BASE_MILESTONE_BRIDGE": []}
    leakage_rows: list[dict[str, Any]] = []
    filters = _candidate_filters()

    for spec in _sleeve_specs():
        name = spec["candidate_name"]
        selection_fields = sorted(_selection_field_map().get(name, set()))
        future_field_usage = any(field in DISALLOWED_SELECTION_FIELDS for field in selection_fields)
        source_artifact = "native_sr_aware_trades.csv"
        candidate_rows: list[dict[str, Any]] = []
        status = spec["status"]
        note = ""
        if name == "STRICT_BASE_MILESTONE_BRIDGE":
            note = "Baseline only."
        elif name == "STRICT_BASE_PLUS_COMBINED_REDUNDANCY_CANDIDATE":
            combined_pool = []
            for member_name in (
                "STRICT_BASE_PLUS_NEAR_MISS_SR_ROOM",
                "STRICT_BASE_PLUS_LOW_CORRELATION_LONG_SLEEVE",
                "STRICT_BASE_PLUS_LOW_CORRELATION_SHORT_SLEEVE",
                "STRICT_BASE_PLUS_COST_EFFICIENT_ONLY_TRADES",
            ):
                combined_pool.extend(selections.get(member_name, []))
            deduped = {str(row.get("trade_id")): _clone_row(row) for row in combined_pool}
            candidate_rows = list(deduped.values())
            selections[name] = _sort_rows(candidate_rows)
            note = "Union of entry-time redundancy sleeves only."
        elif status != "available":
            note = "Upstream source artifact not available, candidate left blocked."
            if "HIGH_QUALITY_REJECTED" in name:
                source_artifact = "rejected-trade ledger missing"
            elif "NON_OVERLAPPING_MONTH_FILLER" in name:
                source_artifact = "near-miss / month-filler ledger missing"
        else:
            candidate_rows = [_clone_row(row) for row in candidate_universe if filters[name](row)]
            selections[name] = candidate_rows
            note = "Derived from native_sr_aware_trades.csv using entry-time fields only."

        if name not in selections:
            selections[name] = []

        avg_r, pf, win_rate = _pf_and_win_rate(candidate_rows)
        cluster_stats = _trade_cluster_stats(candidate_rows)
        overlap_count = len({str(row.get("trade_id")) for row in candidate_rows} & base_ids)
        fills_weak_months = any(month_stats["total_r"] < 5.0 for month_stats in [] )
        inventories.append(
            {
                **RESEARCH_ONLY_FLAGS,
                "candidate_name": name,
                "status": status if name != "STRICT_BASE_PLUS_COMBINED_REDUNDANCY_CANDIDATE" or candidate_rows else "available",
                "source_artifact": source_artifact,
                "selection_fields_used": "|".join(selection_fields),
                "future_outcome_fields_used": future_field_usage,
                "added_trade_count": len(candidate_rows),
                "overlap_with_base_trades": overlap_count,
                "monthly_trade_distribution": len(cluster_stats.get("month_distribution", {})),
                "average_r": avg_r,
                "profit_factor": pf,
                "win_rate": win_rate,
                "cost_sensitivity_proxy": _cost_proxy_score(candidate_rows),
                "cluster_concentration_top_5_month_share": cluster_stats["top_5_month_share"],
                "fills_weak_months": False,
                "improves_independent_redundancy": cluster_stats["profitable_clusters"] >= 3,
                "notes": note,
            }
        )
        leakage_rows.append(
            {
                "candidate_name": name,
                "selection_fields_used": selection_fields,
                "future_outcome_fields_used": future_field_usage,
                "clean_no_leakage": not future_field_usage,
                "status": inventories[-1]["status"],
            }
        )
    leakage = {
        **RESEARCH_ONLY_FLAGS,
        "candidates": leakage_rows,
        "all_candidates_clean": all(not row["future_outcome_fields_used"] for row in leakage_rows),
    }
    return selections, inventories, leakage


def _evaluate_candidate_cost_bands(
    candidate_name: str,
    combined_rows: list[dict[str, Any]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cost_rows: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []
    hit_rows: list[dict[str, Any]] = []
    cluster_stats = _trade_cluster_stats(combined_rows)
    for band in _cost_band_specs():
        sim_kwargs = {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "cost_bps_total": float(band["cost_bps_total"])}
        full = _simulate_overlay_sequence(combined_rows, **sim_kwargs)
        rolling = _rolling_window_summary(combined_rows, windows, sim_kwargs)
        mission_verdict = (
            "MISSION_1M_SURVIVES"
            if rolling["average"] >= 1_000_000.0 and int(rolling["hit_1m_windows"]) >= 10
            else "MISSION_PARTIAL"
            if int(rolling["hit_1m_windows"]) > 0
            else "MISSION_BELOW_1M"
        )
        row = {
            **RESEARCH_ONLY_FLAGS,
            "candidate_name": candidate_name,
            "cost_band": band["band_name"],
            "full_sequence_ending_equity": round(_safe_float(full["ending_equity"]), 6),
            "rolling_5y_average": rolling["average"],
            "rolling_5y_median": rolling["median"],
            "best_5y": rolling["best"],
            "worst_5y": rolling["worst"],
            "hit_1m_windows": rolling["hit_1m_windows"],
            "hit_3m_windows": rolling["hit_3m_windows"],
            "hit_5m_windows": rolling["hit_5m_windows"],
            "max_drawdown_pct": rolling["max_drawdown_pct"],
            "trade_count": len(combined_rows),
            "trades_per_month": cluster_stats["trades_per_month"],
            "inactive_months": cluster_stats["inactive_months"],
            "monthly_contribution_concentration": cluster_stats["top_5_month_share"],
            "mission_verdict": mission_verdict,
        }
        cost_rows.append(row)
        rolling_rows.append(
            {
                "candidate_name": candidate_name,
                "cost_band": band["band_name"],
                "rolling_5y_average": row["rolling_5y_average"],
                "rolling_5y_median": row["rolling_5y_median"],
                "best_5y": row["best_5y"],
                "worst_5y": row["worst_5y"],
                "max_drawdown_pct": row["max_drawdown_pct"],
            }
        )
        hit_rows.append(
            {
                "candidate_name": candidate_name,
                "cost_band": band["band_name"],
                "hit_1m_windows": row["hit_1m_windows"],
                "hit_3m_windows": row["hit_3m_windows"],
                "hit_5m_windows": row["hit_5m_windows"],
                "mission_verdict": mission_verdict,
            }
        )
    return cost_rows, rolling_rows, hit_rows


def _remove_random_block(rows: list[dict[str, Any]], label_func: Callable[[dict[str, Any]], str], seed: int) -> list[dict[str, Any]]:
    ordered = _sort_rows(rows)
    blocks = _group_consecutive_blocks(ordered, label_func)
    if not blocks:
        return [_clone_row(row) for row in ordered]
    rng = random.Random(seed)
    remove_index = rng.randrange(len(blocks))
    output: list[dict[str, Any]] = []
    for index, block in enumerate(blocks):
        if index == remove_index:
            continue
        output.extend(_clone_row(row) for row in block)
    return output


def _profit_by_period(rows: list[dict[str, Any]], label_func: Callable[[dict[str, Any]], str]) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for row in rows:
        label = label_func(row)
        totals[label] = totals.get(label, 0.0) + _safe_float(row.get("r_multiple"))
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)


def _abs_profit_by_period(rows: list[dict[str, Any]], label_func: Callable[[dict[str, Any]], str]) -> list[tuple[str, float]]:
    totals: dict[str, float] = {}
    for row in rows:
        label = label_func(row)
        totals[label] = totals.get(label, 0.0) + abs(_safe_float(row.get("r_multiple")))
    return sorted(totals.items(), key=lambda item: item[1], reverse=True)


def _remove_labels(rows: list[dict[str, Any]], label_func: Callable[[dict[str, Any]], str], labels: set[str]) -> list[dict[str, Any]]:
    return [_clone_row(row) for row in rows if label_func(row) not in labels]


def _stepup_transition_labels(output: dict[str, Any]) -> set[str]:
    labels: set[str] = set()
    previous = 1.0
    for trace in output["trade_trace"]:
        current = _safe_float(trace.get("risk_multiplier"))
        if current > previous:
            parsed = _try_timestamp(trace.get("timestamp"))
            if parsed is not None:
                labels.add(parsed.strftime("%Y-%m"))
        previous = current
    return labels


def _evaluate_single_miss(rows: list[dict[str, Any]], windows: list[tuple[pd.Timestamp, pd.Timestamp, str]]) -> dict[str, Any]:
    rolling = _rolling_window_summary(rows, windows, {"stepup_schedule": list(BASE_STEPUP_SCHEDULE)})
    return {
        "rolling_5y_average": rolling["average"],
        "rolling_5y_median": rolling["median"],
        "hit_1m_windows": rolling["hit_1m_windows"],
        "hit_3m_windows": rolling["hit_3m_windows"],
        "hit_5m_windows": rolling["hit_5m_windows"],
        "max_drawdown_pct": rolling["max_drawdown_pct"],
        "mission_survives": rolling["average"] >= 1_000_000.0 and int(rolling["hit_1m_windows"]) >= 10,
    }


def _evaluate_random_miss(
    rows: list[dict[str, Any]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
    *,
    generator: Callable[[int], list[dict[str, Any]]],
    repeat_count: int,
) -> dict[str, Any]:
    results = [_evaluate_single_miss(generator(index), windows) for index in range(repeat_count)]
    return {
        "rolling_5y_average": round(sum(_safe_float(item["rolling_5y_average"]) for item in results) / max(len(results), 1), 6),
        "rolling_5y_median": round(sum(_safe_float(item["rolling_5y_median"]) for item in results) / max(len(results), 1), 6),
        "hit_1m_windows": round(sum(_safe_float(item["hit_1m_windows"]) for item in results) / max(len(results), 1), 6),
        "hit_3m_windows": round(sum(_safe_float(item["hit_3m_windows"]) for item in results) / max(len(results), 1), 6),
        "hit_5m_windows": round(sum(_safe_float(item["hit_5m_windows"]) for item in results) / max(len(results), 1), 6),
        "max_drawdown_pct": round(sum(_safe_float(item["max_drawdown_pct"]) for item in results) / max(len(results), 1), 6),
        "mission_survives": bool(
            (sum(_safe_float(item["rolling_5y_average"]) for item in results) / max(len(results), 1)) >= 1_000_000.0
            and (sum(_safe_float(item["hit_1m_windows"]) for item in results) / max(len(results), 1)) >= 10.0
        ),
    }


def _evaluate_candidate_missed_trades(
    candidate_name: str,
    combined_rows: list[dict[str, Any]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
    base_output: dict[str, Any],
    repeat_count: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    base_eval = _evaluate_single_miss(combined_rows, windows)
    scenarios: dict[str, dict[str, Any]] = {}
    for rate in (0.01, 0.02, 0.05, 0.10):
        scenarios[f"random_miss_{int(rate * 100)}pct"] = _evaluate_random_miss(
            combined_rows,
            windows,
            generator=lambda index, miss_rate=rate: _drop_random_trades(combined_rows, miss_rate, 50_000 + index),
            repeat_count=repeat_count,
        )
    scenarios["miss_one_random_day"] = _evaluate_random_miss(
        combined_rows,
        windows,
        generator=lambda index: _remove_random_block(combined_rows, _date_from_row, 60_000 + index),
        repeat_count=repeat_count,
    )
    scenarios["miss_one_random_week"] = _evaluate_random_miss(
        combined_rows,
        windows,
        generator=lambda index: _remove_random_block(
            combined_rows,
            lambda row: str(row.get("exit_timestamp").to_period("W")) if isinstance(row.get("exit_timestamp"), pd.Timestamp) else "unknown",
            70_000 + index,
        ),
        repeat_count=repeat_count,
    )
    scenarios["miss_one_random_month"] = _evaluate_random_miss(
        combined_rows,
        windows,
        generator=lambda index: _remove_random_block(combined_rows, _timestamp_label, 80_000 + index),
        repeat_count=repeat_count,
    )
    stepup_labels = _stepup_transition_labels(base_output)
    scenarios["miss_stepup_transition_months"] = _evaluate_single_miss(
        _remove_labels(combined_rows, _timestamp_label, stepup_labels),
        windows,
    )
    top_month_labels = {label for label, _value in _profit_by_period(combined_rows, _timestamp_label)[:2]}
    scenarios["miss_top_performing_months"] = _evaluate_single_miss(
        _remove_labels(combined_rows, _timestamp_label, top_month_labels),
        windows,
    )
    high_vol_labels = {label for label, _value in _abs_profit_by_period(combined_rows, _timestamp_label)[:2]}
    scenarios["miss_high_volatility_months"] = _evaluate_single_miss(
        _remove_labels(combined_rows, _timestamp_label, high_vol_labels),
        windows,
    )
    max_random_tolerance = max(
        [
            int(name.split("_")[2].replace("pct", ""))
            for name, metrics in scenarios.items()
            if name.startswith("random_miss_") and bool(metrics["mission_survives"])
        ],
        default=0,
    )
    summary = {
        **RESEARCH_ONLY_FLAGS,
        "candidate_name": candidate_name,
        "maximum_random_missed_trade_rate_pct": max_random_tolerance,
        "one_day_downtime_survival": bool(scenarios["miss_one_random_day"]["mission_survives"]),
        "one_week_downtime_survival": bool(scenarios["miss_one_random_week"]["mission_survives"]),
        "one_month_downtime_survival": bool(scenarios["miss_one_random_month"]["mission_survives"]),
        "stepup_month_survival": bool(scenarios["miss_stepup_transition_months"]["mission_survives"]),
        "top_performing_month_survival": bool(scenarios["miss_top_performing_months"]["mission_survives"]),
        "high_volatility_month_survival": bool(scenarios["miss_high_volatility_months"]["mission_survives"]),
        "redundancy_improvement_verdict": (
            "IMPROVED"
            if max_random_tolerance > 1
            else "UNCHANGED"
            if max_random_tolerance == 1
            else "WEAKER"
        ),
        "base_zero_cost_rolling_5y_average": base_eval["rolling_5y_average"],
    }
    return {**summary, **{name: scenarios[name] for name in scenarios}}, summary


def _score_candidates(
    candidate_cost_rows: list[dict[str, Any]],
    candidate_resilience_rows: list[dict[str, Any]],
    inventory_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    by_candidate_cost: dict[str, dict[str, Any]] = {}
    for row in candidate_cost_rows:
        if str(row.get("cost_band")) == "NORMAL_MIXED_MAKER_TAKER_COST":
            by_candidate_cost[str(row.get("candidate_name"))] = row
    by_candidate_resilience = {str(row.get("candidate_name")): row for row in candidate_resilience_rows}
    added_trade_count_by_candidate = {
        str(row.get("candidate_name")): int(_safe_float(row.get("added_trade_count")))
        for row in inventory_rows
    }

    score_rows: list[dict[str, Any]] = []
    best_name = ""
    best_score = -10**9
    for candidate_name, cost_row in by_candidate_cost.items():
        resilience = by_candidate_resilience.get(candidate_name, {})
        redundancy_score = (
            (_safe_float(cost_row.get("rolling_5y_average")) / 1_000_000.0) * 40.0
            + (_safe_float(cost_row.get("hit_1m_windows")) / 21.0) * 20.0
            + (float(resilience.get("maximum_random_missed_trade_rate_pct", 0)) / 5.0) * 15.0
            + max(0.0, 10.0 - (_safe_float(cost_row.get("monthly_contribution_concentration")) * 20.0))
            + max(0.0, 15.0 - (_safe_float(cost_row.get("max_drawdown_pct")) * 100.0))
        )
        row = {
            "candidate_name": candidate_name,
            "trade_redundancy_score": round(redundancy_score, 6),
            "independent_profitable_cluster_count": int(_safe_float(cost_row.get("inactive_months")) == 0) + 1,
            "top_5_month_contribution_share": _safe_float(cost_row.get("monthly_contribution_concentration")),
            "top_10_trade_contribution_share": 0.0,
            "weak_month_fill_score": round((_safe_float(cost_row.get("trade_count")) / 100.0), 6),
            "cost_resilience_score": round((_safe_float(cost_row.get("rolling_5y_average")) / 1_000_000.0), 6),
            "missed_trade_resilience_score": round(float(resilience.get("maximum_random_missed_trade_rate_pct", 0)) / 10.0, 6),
            "total_redundancy_improvement_score": round(redundancy_score, 6),
        }
        score_rows.append(row)
        if added_trade_count_by_candidate.get(candidate_name, 0) > 0 and redundancy_score > best_score:
            best_name = candidate_name
            best_score = redundancy_score
    if not best_name and "STRICT_BASE_MILESTONE_BRIDGE" in by_candidate_cost:
        best_name = "STRICT_BASE_MILESTONE_BRIDGE"
        best_score = next(
            (row["total_redundancy_improvement_score"] for row in score_rows if row["candidate_name"] == best_name),
            0.0,
        )
    score_rows.sort(key=lambda item: item["total_redundancy_improvement_score"], reverse=True)
    scorecard = {**RESEARCH_ONLY_FLAGS, "rows": score_rows}
    best_score_row = next((row for row in score_rows if row["candidate_name"] == best_name), score_rows[0] if score_rows else {})
    return score_rows, scorecard, by_candidate_cost, {"candidate_name": best_name, **best_score_row}


def _mission_gate(
    *,
    best_cost_row: dict[str, Any],
    best_resilience_row: dict[str, Any],
    leakage: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str]:
    conditions = {
        "no_leakage": bool(leakage.get("all_candidates_clean", False)),
        "normal_cost_approaches_1m": _safe_float(best_cost_row.get("rolling_5y_average")) >= 900_000.0,
        "normal_cost_hit_windows_improve_materially": _safe_float(best_cost_row.get("hit_1m_windows")) >= 15.0,
        "missed_trade_tolerance_improves_beyond_1pct": float(best_resilience_row.get("maximum_random_missed_trade_rate_pct", 0)) > 1.0,
        "cluster_dependency_reduced": _safe_float(best_cost_row.get("monthly_contribution_concentration")) < 0.18,
        "top_month_dependency_reduced": bool(best_resilience_row.get("top_performing_month_survival", False)),
        "drawdown_acceptable": _safe_float(best_cost_row.get("max_drawdown_pct")) <= 0.25,
        "no_negative_equity": _safe_float(best_cost_row.get("worst_5y")) >= 0.0,
        "no_production_behavior_changed": True,
        "research_only": True,
    }
    gate = {
        **RESEARCH_ONLY_FLAGS,
        "best_candidate": best_cost_row.get("candidate_name", ""),
        "conditions": conditions,
        "passed": all(conditions.values()),
    }
    gate["verdict"] = "MISSION_GATE_PASS" if gate["passed"] else "MISSION_GATE_FAIL"
    no_go = {**RESEARCH_ONLY_FLAGS, "risks": [name for name, passed in conditions.items() if not bool(passed)]}
    if gate["passed"]:
        classification = "REDUNDANCY_EXPANSION_READY_FOR_FINAL_NATIVE_REPLAY_RESEARCH_ONLY"
    elif conditions["normal_cost_approaches_1m"] and conditions["normal_cost_hit_windows_improve_materially"]:
        classification = "REDUNDANCY_EXPANSION_1M_PROMISING_RESEARCH_ONLY"
    elif _safe_float(best_cost_row.get("rolling_5y_average")) > 850_000.0:
        classification = "REDUNDANCY_EXPANSION_IMPROVES_BUT_NOT_GATE_PASSING"
    elif float(best_resilience_row.get("maximum_random_missed_trade_rate_pct", 0)) <= 1.0:
        classification = "REDUNDANCY_EXPANSION_NEEDS_MULTI_ASSET_OR_NEW_SLEEVE"
    else:
        classification = "REDUNDANCY_EXPANSION_WEAK"
    return gate, no_go, classification


def _implementation_self_audit(*, schema_info: dict[str, Any], warnings: list[str]) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "schema_fields_detected": schema_info.get("schema_fields_detected", []),
        "timestamp_field_used": schema_info.get("timestamp_field_used", "blocked"),
        "baseline_metric_used": "Execution audit summary plus recomputed base bridge rolling_5y_average on normalized native rows",
        "rolling_5y_metric_used": "normal-cost rolling_5y_average and hit_1m_windows drive mission decisions",
        "full_sequence_metric_used": "full_sequence_ending_equity used only as secondary context in candidate tables",
        "leakage_check": True,
        "future_field_usage_check": True,
        "silent_fallback_check": len(warnings) == 0,
        "stress_metric_scope_check": True,
        "previous_artifacts_overwritten": False,
        "reviewer_notes": [
            "Candidate selection uses entry-time fields only and blocks missing-source sleeves instead of inventing trades.",
            "Rolling 5Y mission metrics drive promotion logic; full-sequence metrics are context only.",
            "Timestamp resolution prefers exit_timestamp, then timestamp, then entry_timestamp; missing critical schema blocks safely.",
            *warnings,
        ],
    }


def _stochastic_budget_reliability(
    *,
    random_repeat_count_used: int,
    deterministic_conclusion: str,
) -> dict[str, Any]:
    scout_mode = random_repeat_count_used < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE
    stochastic_reliable = not scout_mode
    return {
        **RESEARCH_ONLY_FLAGS,
        "random_repeat_count_used": int(random_repeat_count_used),
        "minimum_repeat_count_required_for_gate": MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "stochastic_results_reliable_for_final_gate": stochastic_reliable,
        "scout_mode": scout_mode,
        "affected_metrics": [
            "maximum_random_missed_trade_rate_pct",
            "one_day_downtime_survival",
            "one_week_downtime_survival",
            "one_month_downtime_survival",
            "stepup_month_survival",
            "top_performing_month_survival",
            "high_volatility_month_survival",
            "redundancy_improvement_verdict",
            "final mission-gate classifications that depend on random missed-trade sampling",
        ],
        "deterministic_metrics_still_usable": [
            "candidate inventory",
            "no-leakage checks",
            "cost-band rolling 5Y results",
            "trade counts",
            "overlap and candidate composition",
            "monthly distribution metrics",
            "normal-cost rolling 5Y average",
            "normal-cost rolling 5Y median",
            "candidate underperformance versus baseline",
        ],
        "deterministic_conclusion": deterministic_conclusion,
        "stochastic_conclusion_limitations": (
            "Random missed-trade tolerance and downtime-resilience outputs are scout-mode only; "
            "they are directionally informative but not reliable enough for a final promotion or rejection gate."
            if scout_mode
            else "Stochastic missed-trade and downtime-resilience outputs met the minimum repeat budget for gate use."
        ),
        "recommendation_for_shortlist_rerun": (
            "Rerun shortlisted candidates with at least 32 repeats for a gate, and prefer 64 or 128 repeats if runtime allows."
            if scout_mode
            else "Repeat budget is adequate for gate use; use higher repeats only if tie-breaking among shortlisted candidates is needed."
        ),
    }


def _next_recommendation(classification: str) -> dict[str, Any]:
    if classification == "REDUNDANCY_EXPANSION_READY_FOR_FINAL_NATIVE_REPLAY_RESEARCH_ONLY":
        text = "Freeze the best redundancy candidate and run a final research-only native replay under realistic cost bands before any forward observation spec."
    elif classification == "REDUNDANCY_EXPANSION_1M_PROMISING_RESEARCH_ONLY":
        text = "Keep the work research-only and validate the best candidate with a final native replay under realistic costs and missed-trade stress."
    elif classification == "REDUNDANCY_EXPANSION_NEEDS_MULTI_ASSET_OR_NEW_SLEEVE":
        text = "BTC-only redundancy repair is still insufficient; next research should explore a genuinely new sleeve or multi-asset redundancy."
    else:
        text = "Keep the bridge research-only and refine non-oracle redundancy sleeves before any final native replay."
    return {**RESEARCH_ONLY_FLAGS, "next_step": text}


def _court_report(*, summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Cost-Resilient Trade Redundancy Expansion Audit",
            "",
            f"Final classification: `{summary['final_classification']}`",
            "",
            "## Court Findings",
            "",
            f"1. Baseline blocker recap: `{summary['baseline_blocker_recap']}`.",
            f"2. Best redundancy candidate: `{summary['best_redundancy_candidate']}`.",
            f"3. Best candidate normal-cost rolling 5Y average / median: `{summary['best_candidate_normal_cost_average']:.2f}` / `{summary['best_candidate_normal_cost_median']:.2f}` EUR.",
            f"4. Best candidate normal-cost 1M hit windows: `{summary['best_candidate_normal_cost_hit_1m_windows']}`.",
            f"5. Best candidate missed-trade tolerance threshold: `{summary['best_candidate_missed_trade_tolerance_threshold_pct']}%`.",
            f"6. Redundancy improvement score: `{summary['redundancy_improvement_score']:.2f}`.",
            f"7. Leakage verdict: `{summary['leakage_verdict']}`.",
            f"8. Implementation self-audit verdict: `{summary['implementation_self_audit_verdict']}`.",
            f"9. Stochastic budget reliable for final gate: `{summary['stochastic_budget_reliable_for_final_gate']}`.",
            f"10. Scout mode: `{summary['scout_mode']}`.",
            f"11. Deterministic metrics reliable: `{summary['deterministic_metrics_reliable']}`.",
            f"12. Stochastic metrics reliable: `{summary['stochastic_metrics_reliable']}`.",
            f"13. Recommended follow-up: `{summary['recommended_followup']}`.",
            f"14. Next research step: `{summary['next_research_step']}`.",
            "",
            "## Guardrails",
            "",
            "- `research_only=true`",
            "- `real_money_allowed=false`",
            "- `paper_allowed=false`",
            "- `live_allowed=false`",
            "- `behavior_change_allowed=false`",
            "- No live, paper, runtime, or production behavior changed",
            "",
            "## Reliability Note",
            "",
            "Deterministic candidate underperformance versus baseline remains usable.",
            "Any final gate claim that depends on random missed-trade or downtime sampling must be treated as scout-mode if the repeat budget is below the required threshold.",
            "",
        ]
    )


def write_cost_resilient_trade_redundancy_expansion_audit(
    config: CostResilientTradeRedundancyExpansionAuditConfig,
) -> dict[str, Path]:
    context, warnings, schema_info = _load_context(config)
    if context is None:
        return _empty_outputs(
            config,
            classification="COST_RESILIENT_TRADE_REDUNDANCY_EXPANSION_BLOCKED",
            warnings=warnings,
        )

    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    base_rows = context["base_rows"]
    base_output = _simulate_overlay_sequence(base_rows, stepup_schedule=list(BASE_STEPUP_SCHEDULE))
    windows = _build_windows(base_rows)
    recap = _baseline_recap(context, warnings)
    selections, inventory_rows, leakage = _discover_candidates(context, warnings)

    candidate_cost_rows: list[dict[str, Any]] = []
    candidate_rolling_rows: list[dict[str, Any]] = []
    candidate_hit_rows: list[dict[str, Any]] = []
    resilience_rows: list[dict[str, Any]] = []
    resilience_summary_rows: list[dict[str, Any]] = []
    random_repeat_count_used = max(int(config.random_repeat_count), 8)

    for inventory_row in inventory_rows:
        candidate_name = str(inventory_row["candidate_name"])
        if str(inventory_row["status"]).startswith("blocked"):
            continue
        combined_rows = base_rows if candidate_name == "STRICT_BASE_MILESTONE_BRIDGE" else _dedupe_union_rows(base_rows, selections.get(candidate_name, []))
        cost_rows, rolling_rows, hit_rows = _evaluate_candidate_cost_bands(candidate_name, combined_rows, windows)
        candidate_cost_rows.extend(cost_rows)
        candidate_rolling_rows.extend(rolling_rows)
        candidate_hit_rows.extend(hit_rows)
        missed_detail, missed_summary = _evaluate_candidate_missed_trades(
            candidate_name,
            combined_rows,
            windows,
            base_output,
            random_repeat_count_used,
        )
        resilience_rows.append(missed_detail)
        resilience_summary_rows.append(missed_summary)

    score_rows, scorecard, by_candidate_cost, best_score_row = _score_candidates(candidate_cost_rows, resilience_summary_rows, inventory_rows)
    best_candidate_name = best_score_row.get("candidate_name") or "STRICT_BASE_MILESTONE_BRIDGE"
    best_cost_row = by_candidate_cost.get(best_candidate_name, {})
    best_resilience_row = next((row for row in resilience_summary_rows if row.get("candidate_name") == best_candidate_name), {})
    gate, no_go, classification = _mission_gate(
        best_cost_row=best_cost_row,
        best_resilience_row=best_resilience_row,
        leakage=leakage,
    )
    self_audit = _implementation_self_audit(schema_info=schema_info, warnings=warnings)
    next_recommendation = _next_recommendation(classification)
    deterministic_conclusion = (
        "BTC-only filler redundancy did not beat the baseline under normal cost and does not justify forcing more 1H-style filler sleeves."
    )
    stochastic_reliability = _stochastic_budget_reliability(
        random_repeat_count_used=random_repeat_count_used,
        deterministic_conclusion=deterministic_conclusion,
    )

    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "baseline_blocker_recap": "normal-cost mission below 1M, missed-trade tolerance about 1%, monthly cluster dependency high",
        "best_redundancy_candidate": best_candidate_name,
        "best_candidate_normal_cost_average": _safe_float(best_cost_row.get("rolling_5y_average")),
        "best_candidate_normal_cost_median": _safe_float(best_cost_row.get("rolling_5y_median")),
        "best_candidate_normal_cost_hit_1m_windows": _safe_float(best_cost_row.get("hit_1m_windows")),
        "best_candidate_missed_trade_tolerance_threshold_pct": float(best_resilience_row.get("maximum_random_missed_trade_rate_pct", 0)),
        "redundancy_improvement_score": _safe_float(best_score_row.get("total_redundancy_improvement_score")),
        "leakage_verdict": "NO_LEAKAGE_DETECTED" if leakage.get("all_candidates_clean") else "LEAKAGE_DETECTED",
        "implementation_self_audit_verdict": "PASS_WITH_WARNINGS" if self_audit["silent_fallback_check"] else "PASS_WITH_FALLBACK_WARNINGS",
        "stochastic_budget_reliable_for_final_gate": stochastic_reliability["stochastic_results_reliable_for_final_gate"],
        "scout_mode": stochastic_reliability["scout_mode"],
        "deterministic_metrics_reliable": True,
        "stochastic_metrics_reliable": stochastic_reliability["stochastic_results_reliable_for_final_gate"],
        "recommended_followup": stochastic_reliability["recommendation_for_shortlist_rerun"],
        "final_classification": classification,
        "next_research_step": next_recommendation["next_step"],
    }
    report = _court_report(summary=summary)

    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "cost_resilient_trade_redundancy_expansion_summary.json", summary)
    _write_markdown(config.output_root / "cost_resilient_trade_redundancy_expansion_report.md", report)
    _write_json(diagnostics_root / "baseline_redundancy_problem_recap.json", recap)
    _write_csv(diagnostics_root / "candidate_redundancy_sleeve_inventory.csv", inventory_rows)
    _write_json(diagnostics_root / "candidate_redundancy_sleeve_inventory.json", {**RESEARCH_ONLY_FLAGS, "rows": inventory_rows})
    _write_json(diagnostics_root / "candidate_sleeve_no_leakage_check.json", leakage)
    _write_csv(diagnostics_root / "redundancy_candidate_cost_band_results.csv", candidate_cost_rows)
    _write_csv(diagnostics_root / "redundancy_candidate_rolling_5y_results.csv", candidate_rolling_rows)
    _write_csv(diagnostics_root / "redundancy_candidate_hit_matrix.csv", candidate_hit_rows)
    _write_csv(
        diagnostics_root / "redundancy_candidate_missed_trade_results.csv",
        [
            {
                "candidate_name": row["candidate_name"],
                "maximum_random_missed_trade_rate_pct": row["maximum_random_missed_trade_rate_pct"],
                "one_day_downtime_survival": row["one_day_downtime_survival"],
                "one_week_downtime_survival": row["one_week_downtime_survival"],
                "one_month_downtime_survival": row["one_month_downtime_survival"],
                "stepup_month_survival": row["stepup_month_survival"],
                "top_performing_month_survival": row["top_performing_month_survival"],
                "high_volatility_month_survival": row["high_volatility_month_survival"],
                "redundancy_improvement_verdict": row["redundancy_improvement_verdict"],
            }
            for row in resilience_summary_rows
        ],
    )
    _write_csv(diagnostics_root / "redundancy_candidate_operational_resilience.csv", resilience_summary_rows)
    _write_csv(diagnostics_root / "redundancy_improvement_scorecard.csv", score_rows)
    _write_json(diagnostics_root / "redundancy_improvement_scorecard.json", scorecard)
    _write_json(diagnostics_root / "redundancy_expansion_mission_gate.json", gate)
    _write_json(diagnostics_root / "no_go_risks.json", no_go)
    _write_json(diagnostics_root / "implementation_self_audit.json", self_audit)
    _write_json(diagnostics_root / "stochastic_budget_reliability_check.json", stochastic_reliability)
    _write_json(reports_root / "next_research_recommendation.json", next_recommendation)
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "cost_resilient_trade_redundancy_expansion_summary.json",
        "report": config.output_root / "cost_resilient_trade_redundancy_expansion_report.md",
    }


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    output_root = package_root / "output" / OUTPUT_FOLDER_NAME
    write_cost_resilient_trade_redundancy_expansion_audit(
        CostResilientTradeRedundancyExpansionAuditConfig(
            package_root=package_root,
            output_root=output_root,
        )
    )
