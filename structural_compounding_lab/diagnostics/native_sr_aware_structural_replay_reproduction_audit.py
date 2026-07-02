from __future__ import annotations

import json
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
    _apply_frozen_patch,
    _load_frozen_rules,
)
from structural_compounding_lab.diagnostics.equal_highs_liquidity_sweep_rescue_forensic_audit import (  # noqa: E402
    FORBIDDEN_FUTURE_FIELDS,
    _mission_row,
    _normalize_rows,
    _safe_float,
    _simulate_overlay,
    _summarize_mission_rows,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import _prepare_rows  # noqa: E402
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _median,
    _normalize_trade_rows,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import (  # noqa: E402
    _build_windows,
    _window_rows,
)


@dataclass(frozen=True)
class NativeSRAwareStructuralReplayReproductionAuditConfig:
    package_root: Path
    output_root: Path


def _paths(config: NativeSRAwareStructuralReplayReproductionAuditConfig) -> dict[str, Path]:
    source_root = config.package_root / "output"
    broad_root = source_root / "broad_historical_structural_replay_001"
    broad_ledger_root = broad_root / "ledger"
    enrichment_root = source_root / "native_pre_entry_sr_feature_enrichment_audit_001"
    return {
        "broad_trades": broad_ledger_root / "trades.csv",
        "broad_equity": broad_ledger_root / "equity.csv",
        "broad_summary": broad_ledger_root / "summary.json",
        "setup_log": broad_ledger_root / "setup_log.csv",
        "level_log": broad_ledger_root / "level_log.csv",
        "liquidity_events": broad_ledger_root / "liquidity_events.csv",
        "frozen_patch_summary": source_root / "broad_frozen_patch_validation_001" / "broad_frozen_patch_summary.json",
        "accounting_table": source_root / "broad_patch_accounting_and_short_rescue_audit_001" / "diagnostics" / "accounting_reconciliation_table.csv",
        "rolling_results": source_root / "rolling_five_year_mission_viability_audit_001" / "diagnostics" / "rolling_5y_window_results.csv",
        "support_room_summary": source_root / "support_room_short_rescue_repair_audit_001" / "support_room_short_rescue_repair_summary.json",
        "enrichment_summary": enrichment_root / "native_pre_entry_sr_feature_enrichment_summary.json",
        "enriched_trades": enrichment_root / "diagnostics" / "enriched_trade_pre_entry_sr_features.csv",
        "enriched_prototypes": enrichment_root / "diagnostics" / "enriched_rescue_prototype_results.csv",
        "enriched_best_features": enrichment_root / "diagnostics" / "enriched_sr_best_candidate_features.json",
        "enriched_no_leakage": enrichment_root / "diagnostics" / "pre_entry_sr_feature_no_leakage_check.json",
        "frozen_patch_rules": source_root / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    ledger_root = output_root / "ledger"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    ledger_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, ledger_root, reports_root


def _empty_outputs(
    config: NativeSRAwareStructuralReplayReproductionAuditConfig,
    *,
    classification: str,
    warnings: list[str],
) -> dict[str, Path]:
    diagnostics_root, ledger_root, reports_root = _ensure_dirs(config.output_root)
    status = {
        "state": "blocked",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "warnings": warnings,
    }
    summary = {**RESEARCH_ONLY_FLAGS, "warnings": warnings, "final_classification": classification}
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "native_sr_aware_structural_replay_reproduction_summary.json", summary)
    _write_markdown(config.output_root / "native_sr_aware_structural_replay_reproduction_report.md", "# Native SR-Aware Structural Replay Reproduction Audit\n\nRequired artifacts were missing or the candle source could not be validated.\n")
    for path in (
        ledger_root / "native_sr_aware_trades.csv",
        ledger_root / "native_sr_aware_equity.csv",
        diagnostics_root / "native_sr_aware_variant_comparison.csv",
        diagnostics_root / "native_sr_aware_rolling_5y_results.csv",
        diagnostics_root / "native_sr_aware_mission_hit_matrix.csv",
        diagnostics_root / "native_sr_aware_best_worst_windows.csv",
        diagnostics_root / "native_sr_aware_cost_survival.csv",
        diagnostics_root / "native_sr_aware_moonshot_survival.csv",
        diagnostics_root / "native_sr_aware_drawdown_governor.csv",
        diagnostics_root / "native_sr_aware_insolvency_clamp.csv",
    ):
        _write_csv(path, [])
    for path in (
        diagnostics_root / "sr_aware_research_spec.json",
        diagnostics_root / "sr_aware_spec_no_leakage_check.json",
        ledger_root / "native_sr_aware_summary.json",
        diagnostics_root / "native_sr_aware_variant_comparison.json",
        diagnostics_root / "native_sr_aware_replay_limitations.json",
        diagnostics_root / "no_go_risks.json",
    ):
        _write_json(path, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "native_sr_aware_structural_replay_reproduction_summary.json",
        "report": config.output_root / "native_sr_aware_structural_replay_reproduction_report.md",
    }


def _source_path(broad_summary_path: Path) -> Path | None:
    payload = _read_json(broad_summary_path, {})
    source_csv = str(payload.get("source_csv") or "").strip()
    if not source_csv:
        return None
    path = Path(source_csv)
    return path if path.exists() else None


def _spec_payload() -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "diagnostic_only": True,
        "spec_name": "SR_AWARE_SHORT_SELECTION_FROZEN_RESEARCH_SPEC_V1",
        "threshold_source": {
            "distance_to_next_support_R": "native_pre_entry_sr_feature_enrichment_audit_001 quantile separation plus conservative safety margin",
            "htf_room_to_support": "best enriched overlay prototype reference threshold",
            "rejection_from_resistance_score": "conservative confirmation threshold below strict overlay style",
            "nearest_support_blocking_score": "support-room blocker cap from repair audit family",
            "clean_downside_room_score": "allow non-negative to slightly negative room only in balanced variant",
        },
        "missing_field_behavior": "conservative_fail_closed_for_short_selection",
        "variants": [
            {
                "variant_name": "NATIVE_SR_AWARE_SHORT_SELECTION",
                "role": "primary",
                "fields_used": [
                    "archetype_key",
                    "sweep_high_confirmed_pre_entry",
                    "distance_to_next_support_R",
                    "htf_room_to_support",
                    "rejection_from_resistance_score",
                    "nearest_support_blocking_score",
                    "clean_downside_room_score",
                    "htf_trend_alignment",
                ],
                "thresholds": {
                    "distance_to_next_support_R_min": 1.40,
                    "htf_room_to_support_min": 0.015,
                    "rejection_from_resistance_score_min": 1.35,
                    "nearest_support_blocking_score_max": 1.75,
                    "clean_downside_room_score_min": -0.05,
                },
                "context_rules": [
                    "equal_highs in archetype_key or sweep_high_confirmed_pre_entry",
                    "bearish HTF or adequate HTF room",
                ],
            },
            {
                "variant_name": "NATIVE_SR_AWARE_STRICT",
                "role": "strict",
                "fields_used": [
                    "archetype_key",
                    "distance_to_next_support_R",
                    "htf_room_to_support",
                    "rejection_from_resistance_score",
                    "nearest_support_blocking_score",
                    "clean_downside_room_score",
                    "htf_trend_alignment",
                ],
                "thresholds": {
                    "distance_to_next_support_R_min": 1.75,
                    "htf_room_to_support_min": 0.020,
                    "rejection_from_resistance_score_min": 1.55,
                    "nearest_support_blocking_score_max": 1.40,
                    "clean_downside_room_score_min": 0.00,
                },
                "context_rules": ["equal_highs in archetype_key", "bearish HTF required"],
            },
            {
                "variant_name": "NATIVE_SR_AWARE_BALANCED",
                "role": "balanced",
                "fields_used": [
                    "archetype_key",
                    "sweep_high_confirmed_pre_entry",
                    "distance_to_next_support_R",
                    "htf_room_to_support",
                    "rejection_from_resistance_score",
                    "nearest_support_blocking_score",
                    "clean_downside_room_score",
                    "htf_trend_alignment",
                ],
                "thresholds": {
                    "distance_to_next_support_R_min": 1.15,
                    "htf_room_to_support_min": 0.010,
                    "rejection_from_resistance_score_min": 1.20,
                    "nearest_support_blocking_score_max": 1.95,
                    "clean_downside_room_score_min": -0.15,
                },
                "context_rules": [
                    "equal_highs in archetype_key or sweep_high_confirmed_pre_entry",
                    "bearish HTF or adequate HTF room",
                ],
            },
            {
                "variant_name": "NATIVE_SR_AWARE_WITH_COST_GUARD",
                "role": "cost_guard",
                "fields_used": [
                    "archetype_key",
                    "sweep_high_confirmed_pre_entry",
                    "distance_to_next_support_R",
                    "htf_room_to_support",
                    "rejection_from_resistance_score",
                    "nearest_support_blocking_score",
                    "clean_downside_room_score",
                    "pre_entry_stop_distance_atr",
                    "volume_confirmation_score",
                ],
                "thresholds": {
                    "distance_to_next_support_R_min": 1.40,
                    "htf_room_to_support_min": 0.015,
                    "rejection_from_resistance_score_min": 1.40,
                    "nearest_support_blocking_score_max": 1.65,
                    "clean_downside_room_score_min": -0.05,
                    "pre_entry_stop_distance_atr_min": 0.45,
                    "volume_confirmation_score_min": 0.80,
                },
                "context_rules": ["cost-aware filter to avoid tiny-stop cost fragility"],
            },
            {
                "variant_name": "NATIVE_SR_AWARE_WITH_DRAWDOWN_GOVERNOR",
                "role": "drawdown_tilt",
                "fields_used": [
                    "archetype_key",
                    "sweep_high_confirmed_pre_entry",
                    "distance_to_next_support_R",
                    "htf_room_to_support",
                    "rejection_from_resistance_score",
                    "nearest_support_blocking_score",
                    "clean_downside_room_score",
                    "htf_trend_alignment",
                ],
                "thresholds": {
                    "distance_to_next_support_R_min": 1.55,
                    "htf_room_to_support_min": 0.020,
                    "rejection_from_resistance_score_min": 1.45,
                    "nearest_support_blocking_score_max": 1.55,
                    "clean_downside_room_score_min": 0.00,
                },
                "context_rules": ["selection tightened modestly toward lower drawdown path"],
            },
        ],
    }


def _spec_no_leakage(spec: dict[str, Any]) -> dict[str, Any]:
    checks = []
    for variant in spec["variants"]:
        fields = variant["fields_used"]
        checks.append(
            {
                "variant_name": variant["variant_name"],
                "fields_used": fields,
                "forbidden_future_fields_used": any(field in FORBIDDEN_FUTURE_FIELDS for field in fields),
                "verdict": "pre_entry_safe" if not any(field in FORBIDDEN_FUTURE_FIELDS for field in fields) else "leaky",
            }
        )
    return {
        **RESEARCH_ONLY_FLAGS,
        "checks": checks,
        "final_no_leakage_verdict": all(not item["forbidden_future_fields_used"] for item in checks),
    }


def _overlay_reference_predicate(row: dict[str, Any]) -> bool:
    return (
        "equal_highs" in str(row.get("archetype_key") or "")
        and str(row.get("htf_trend_alignment") or "") == "bearish"
        and _safe_float(row.get("htf_room_to_support")) >= 0.02
        and _safe_float(row.get("distance_to_next_support_R")) >= 1.40
    )


def _variant_definitions(spec: dict[str, Any]) -> list[dict[str, Any]]:
    def _has_context(row: dict[str, Any]) -> bool:
        return ("equal_highs" in str(row.get("archetype_key") or "")) or bool(row.get("sweep_high_confirmed_pre_entry"))

    return [
        {
            "variant_name": "NATIVE_SR_AWARE_SHORT_SELECTION",
            "predicate": lambda row: _has_context(row)
            and (str(row.get("htf_trend_alignment") or "") == "bearish" or _safe_float(row.get("htf_room_to_support")) >= 0.015)
            and _safe_float(row.get("distance_to_next_support_R")) >= 1.40
            and _safe_float(row.get("rejection_from_resistance_score")) >= 1.35
            and _safe_float(row.get("nearest_support_blocking_score")) <= 1.75
            and _safe_float(row.get("clean_downside_room_score")) >= -0.05,
        },
        {
            "variant_name": "NATIVE_SR_AWARE_STRICT",
            "predicate": lambda row: "equal_highs" in str(row.get("archetype_key") or "")
            and str(row.get("htf_trend_alignment") or "") == "bearish"
            and _safe_float(row.get("htf_room_to_support")) >= 0.020
            and _safe_float(row.get("distance_to_next_support_R")) >= 1.75
            and _safe_float(row.get("rejection_from_resistance_score")) >= 1.55
            and _safe_float(row.get("nearest_support_blocking_score")) <= 1.40
            and _safe_float(row.get("clean_downside_room_score")) >= 0.00,
        },
        {
            "variant_name": "NATIVE_SR_AWARE_BALANCED",
            "predicate": lambda row: _has_context(row)
            and (str(row.get("htf_trend_alignment") or "") == "bearish" or _safe_float(row.get("htf_room_to_support")) >= 0.010)
            and _safe_float(row.get("distance_to_next_support_R")) >= 1.15
            and _safe_float(row.get("rejection_from_resistance_score")) >= 1.20
            and _safe_float(row.get("nearest_support_blocking_score")) <= 1.95
            and _safe_float(row.get("clean_downside_room_score")) >= -0.15,
        },
        {
            "variant_name": "NATIVE_SR_AWARE_WITH_COST_GUARD",
            "predicate": lambda row: _has_context(row)
            and (str(row.get("htf_trend_alignment") or "") == "bearish" or _safe_float(row.get("htf_room_to_support")) >= 0.015)
            and _safe_float(row.get("distance_to_next_support_R")) >= 1.40
            and _safe_float(row.get("rejection_from_resistance_score")) >= 1.40
            and _safe_float(row.get("nearest_support_blocking_score")) <= 1.65
            and _safe_float(row.get("clean_downside_room_score")) >= -0.05
            and _safe_float(row.get("pre_entry_stop_distance_atr")) >= 0.45
            and _safe_float(row.get("volume_confirmation_score")) >= 0.80,
        },
        {
            "variant_name": "NATIVE_SR_AWARE_WITH_DRAWDOWN_GOVERNOR",
            "predicate": lambda row: _has_context(row)
            and (str(row.get("htf_trend_alignment") or "") == "bearish" or _safe_float(row.get("htf_room_to_support")) >= 0.020)
            and _safe_float(row.get("distance_to_next_support_R")) >= 1.55
            and _safe_float(row.get("rejection_from_resistance_score")) >= 1.45
            and _safe_float(row.get("nearest_support_blocking_score")) <= 1.55
            and _safe_float(row.get("clean_downside_room_score")) >= 0.0,
        },
    ]


def _merge_enriched(
    rows: list[dict[str, Any]],
    enriched_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    merged = []
    for row in rows:
        item = dict(row)
        item.update(enriched_map.get(str(row.get("trade_id") or ""), {}))
        merged.append(item)
    return merged


def _avg_trades_per_month(rows: list[dict[str, Any]]) -> float:
    timestamps = [row.get("exit_timestamp") for row in rows if row.get("exit_timestamp") is not None]
    if not timestamps:
        return 0.0
    months = max(1.0, ((max(timestamps).year - min(timestamps).year) * 12) + (max(timestamps).month - min(timestamps).month) + 1)
    return round(len(rows) / months, 6)


def _full_span_metrics(selected_rows: list[dict[str, Any]]) -> dict[str, Any]:
    output = _simulate_overlay(selected_rows=selected_rows)
    r_values = [_safe_float(row.get("r_multiple")) for row in selected_rows]
    return {
        "trade_count": len(selected_rows),
        "ending_equity": output["ending_equity"],
        "profit_factor": output["profit_factor"],
        "avg_R": output["avg_R"],
        "median_R": output["median_R"],
        "total_R": output["total_R"],
        "win_rate": output["win_rate"],
        "max_drawdown_pct": output["max_drawdown_pct"],
        "five_R_plus_count": sum(1 for value in r_values if value >= 5.0),
        "ten_R_plus_count": sum(1 for value in r_values if value >= 10.0),
        "average_trades_per_month": _avg_trades_per_month(selected_rows),
        "daily_rows": output["daily_rows"],
    }


def _rolling_results_for_variant(
    *,
    variant_name: str,
    selected_rows: list[dict[str, Any]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mission_rows = []
    for start, end, label in windows:
        chosen = _window_rows(selected_rows, start, end)
        output = _simulate_overlay(selected_rows=chosen)
        mission_rows.append(_mission_row(variant_name=variant_name, window_label=label, start=start, end=end, output=output))
    summary = _summarize_mission_rows(mission_rows)
    return mission_rows, summary


def _robustness_specs() -> list[dict[str, Any]]:
    return [
        {"overlay_name": "LOW_COST", "category": "cost", "cost_bps_total": 7.0},
        {"overlay_name": "NORMAL_COST", "category": "cost", "cost_bps_total": 15.0},
        {"overlay_name": "HIGH_COST", "category": "cost", "cost_bps_total": 25.0},
        {"overlay_name": "STRESS_COST", "category": "cost", "cost_bps_total": 45.0},
        {"overlay_name": "MOONSHOTS_CAPPED_10R", "category": "moonshot", "moonshot_cap": 10.0},
        {"overlay_name": "MOONSHOTS_CAPPED_5R", "category": "moonshot", "moonshot_cap": 5.0},
        {"overlay_name": "MOONSHOTS_CAPPED_3R", "category": "moonshot", "moonshot_cap": 3.0},
        {"overlay_name": "ALL_5R_PLUS_REMOVED", "category": "moonshot", "remove_5plus": True},
        {"overlay_name": "INSOLVENCY_CLAMP_ZERO", "category": "insolvency", "insolvency_clamp": True},
        {"overlay_name": "DRAWDOWN_CIRCUIT_BREAKER_10", "category": "governor", "drawdown_breaker_pct": 0.10},
        {"overlay_name": "DRAWDOWN_CIRCUIT_BREAKER_15", "category": "governor", "drawdown_breaker_pct": 0.15},
        {"overlay_name": "DRAWDOWN_CIRCUIT_BREAKER_20", "category": "governor", "drawdown_breaker_pct": 0.20},
    ]


def _evaluate_robustness(
    *,
    native_variants: dict[str, list[dict[str, Any]]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cost_rows: list[dict[str, Any]] = []
    moonshot_rows: list[dict[str, Any]] = []
    governor_rows: list[dict[str, Any]] = []
    insolvency_rows: list[dict[str, Any]] = []
    for variant_name, selected_rows in native_variants.items():
        for spec in _robustness_specs():
            overlay_rows = []
            for start, end, label in windows:
                chosen = _window_rows(selected_rows, start, end)
                output = _simulate_overlay(
                    selected_rows=chosen,
                    cost_bps_total=_safe_float(spec.get("cost_bps_total")),
                    moonshot_cap=spec.get("moonshot_cap"),
                    remove_5plus=bool(spec.get("remove_5plus")),
                    insolvency_clamp=bool(spec.get("insolvency_clamp")),
                    drawdown_breaker_pct=spec.get("drawdown_breaker_pct"),
                )
                row = _mission_row(variant_name=spec["overlay_name"], window_label=label, start=start, end=end, output=output)
                row["research_variant_name"] = variant_name
                row["overlay_category"] = spec["category"]
                overlay_rows.append(row)
            summary = _summarize_mission_rows(overlay_rows)
            payload = {
                "research_variant_name": variant_name,
                "overlay_name": spec["overlay_name"],
                "average_5Y_ending_equity": summary["average_ending_equity"],
                "median_5Y_ending_equity": summary["median_ending_equity"],
                "best_5Y_ending_equity": summary["best_ending_equity"],
                "worst_5Y_ending_equity": summary["worst_ending_equity"],
                "1M_hit_windows": summary["hit_1m_windows"],
                "5M_hit_windows": summary["hit_5m_windows"],
                "10M_hit_windows": summary["hit_10m_windows"],
                "max_drawdown_pct": summary["worst_max_drawdown_pct"],
            }
            if spec["category"] == "cost":
                cost_rows.append(payload)
            elif spec["category"] == "moonshot":
                moonshot_rows.append(payload)
            elif spec["category"] == "governor":
                governor_rows.append(payload)
            elif spec["category"] == "insolvency":
                insolvency_rows.append(payload)
    return cost_rows, moonshot_rows, governor_rows, insolvency_rows


def write_native_sr_aware_structural_replay_reproduction_audit(
    config: NativeSRAwareStructuralReplayReproductionAuditConfig,
) -> dict[str, Path]:
    paths = _paths(config)
    required = [
        paths["broad_trades"],
        paths["setup_log"],
        paths["level_log"],
        paths["liquidity_events"],
        paths["broad_summary"],
        paths["frozen_patch_rules"],
        paths["enrichment_summary"],
        paths["enriched_trades"],
        paths["enriched_prototypes"],
        paths["enriched_no_leakage"],
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return _empty_outputs(
            config,
            classification="NATIVE_SR_REPLAY_BLOCKED",
            warnings=missing,
        )

    source_csv = _source_path(paths["broad_summary"])
    if source_csv is None:
        return _empty_outputs(
            config,
            classification="NATIVE_SR_REPLAY_BLOCKED",
            warnings=["missing_or_unreadable_source_csv_in_broad_summary"],
        )

    diagnostics_root, ledger_root, reports_root = _ensure_dirs(config.output_root)
    spec = _spec_payload()
    spec_leakage = _spec_no_leakage(spec)
    _write_json(diagnostics_root / "sr_aware_research_spec.json", spec)
    _write_json(diagnostics_root / "sr_aware_spec_no_leakage_check.json", spec_leakage)

    broad_summary_before = paths["broad_summary"].read_text(encoding="utf-8")

    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    all_rows = _normalize_trade_rows(_read_csv_rows(paths["broad_trades"]), setup_rows, level_rows, liquidity_rows)
    all_rows = _prepare_rows(all_rows)
    matched_short_archetypes, disabled_long_modes, _ = _load_frozen_rules(paths["frozen_patch_rules"])
    kept_rows, removed_rows = _apply_frozen_patch(
        all_rows,
        matched_short_archetypes=matched_short_archetypes,
        disabled_long_modes=disabled_long_modes,
    )

    enriched_rows = _read_csv_rows(paths["enriched_trades"])
    enriched_map = {str(row.get("trade_id") or ""): row for row in enriched_rows}
    all_rows_enriched = _merge_enriched(all_rows, enriched_map)
    kept_rows_enriched = _merge_enriched(kept_rows, enriched_map)
    removed_rows_enriched = _merge_enriched(removed_rows, enriched_map)

    kept_longs = [row for row in kept_rows_enriched if str(row.get("side") or "") == "long"]
    all_shorts = [row for row in all_rows_enriched if str(row.get("side") or "") == "short"]
    removed_shorts = [row for row in removed_rows_enriched if str(row.get("side") or "") == "short"]

    overlay_reference_rows = kept_rows_enriched + [row for row in removed_shorts if _overlay_reference_predicate(row)]
    windows = _build_windows(all_rows)

    reference_variants = {
        "ORIGINAL_BROAD_REPLAY_REFERENCE": all_rows_enriched,
        "FROZEN_PATCH_REFERENCE": kept_rows_enriched,
        "ENRICHED_OVERLAY_PROTOTYPE_REFERENCE": sorted(overlay_reference_rows, key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or "")),
    }
    native_variants: dict[str, list[dict[str, Any]]] = {}
    for definition in _variant_definitions(spec):
        selected_shorts = [row for row in all_shorts if definition["predicate"](row)]
        native_variants[definition["variant_name"]] = sorted(
            kept_longs + selected_shorts,
            key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or ""),
        )

    all_variants = {**reference_variants, **native_variants}

    comparison_rows = []
    rolling_rows = []
    hit_matrix = []
    best_worst_rows = []
    full_span_outputs: dict[str, dict[str, Any]] = {}
    for variant_name, selected_rows in all_variants.items():
        full_span = _full_span_metrics(selected_rows)
        full_span_outputs[variant_name] = full_span
        mission_rows, rolling_summary = _rolling_results_for_variant(
            variant_name=variant_name,
            selected_rows=selected_rows,
            windows=windows,
        )
        rolling_rows.extend(mission_rows)
        best_window = max(mission_rows, key=lambda row: _safe_float(row.get("ending_equity")), default={})
        worst_window = min(mission_rows, key=lambda row: _safe_float(row.get("ending_equity")), default={})
        best_worst_rows.extend(
            [
                {
                    "variant_name": variant_name,
                    "window_role": "best",
                    "window_label": best_window.get("window_label", ""),
                    "ending_equity": best_window.get("ending_equity", 0.0),
                    "hit_1m": best_window.get("hit_1m", False),
                    "hit_5m": best_window.get("hit_5m", False),
                    "hit_10m": best_window.get("hit_10m", False),
                },
                {
                    "variant_name": variant_name,
                    "window_role": "worst",
                    "window_label": worst_window.get("window_label", ""),
                    "ending_equity": worst_window.get("ending_equity", 0.0),
                    "hit_1m": worst_window.get("hit_1m", False),
                    "hit_5m": worst_window.get("hit_5m", False),
                    "hit_10m": worst_window.get("hit_10m", False),
                },
            ]
        )
        for row in mission_rows:
            hit_matrix.append(
                {
                    "variant_name": variant_name,
                    "window_label": row["window_label"],
                    "hit_1m": row["hit_1m"],
                    "hit_5m": row["hit_5m"],
                    "hit_10m": row["hit_10m"],
                    "ending_equity": row["ending_equity"],
                }
            )
        comparison_rows.append(
            {
                "variant_name": variant_name,
                "variant_family": "reference" if variant_name in reference_variants else "native_sr_aware",
                "trade_count": full_span["trade_count"],
                "ending_equity": full_span["ending_equity"],
                "profit_factor": full_span["profit_factor"],
                "avg_R": full_span["avg_R"],
                "median_R": full_span["median_R"],
                "total_R": full_span["total_R"],
                "win_rate": full_span["win_rate"],
                "max_drawdown_pct": full_span["max_drawdown_pct"],
                "average_trades_per_month": full_span["average_trades_per_month"],
                "five_R_plus_count": full_span["five_R_plus_count"],
                "ten_R_plus_count": full_span["ten_R_plus_count"],
                "average_5Y_ending_equity": rolling_summary["average_ending_equity"],
                "median_5Y_ending_equity": rolling_summary["median_ending_equity"],
                "best_5Y_ending_equity": rolling_summary["best_ending_equity"],
                "worst_5Y_ending_equity": rolling_summary["worst_ending_equity"],
                "1M_hit_windows": rolling_summary["hit_1m_windows"],
                "5M_hit_windows": rolling_summary["hit_5m_windows"],
                "10M_hit_windows": rolling_summary["hit_10m_windows"],
            }
        )

    native_best = max(
        [row for row in comparison_rows if row["variant_family"] == "native_sr_aware"],
        key=lambda row: (_safe_float(row.get("average_5Y_ending_equity")), _safe_float(row.get("ending_equity"))),
        default={},
    )

    cost_rows, moonshot_rows, governor_rows, insolvency_rows = _evaluate_robustness(
        native_variants=native_variants,
        windows=windows,
    )

    primary_variant_name = "NATIVE_SR_AWARE_SHORT_SELECTION"
    primary_rows = native_variants.get(primary_variant_name, [])
    primary_full = full_span_outputs.get(primary_variant_name, {})
    _write_csv(ledger_root / "native_sr_aware_trades.csv", _normalize_rows(primary_rows))
    _write_csv(ledger_root / "native_sr_aware_equity.csv", _normalize_rows(primary_full.get("daily_rows", [])))
    _write_json(
        ledger_root / "native_sr_aware_summary.json",
        {
            **RESEARCH_ONLY_FLAGS,
            "variant_name": primary_variant_name,
            "trade_count": primary_full.get("trade_count", 0),
            "ending_equity": primary_full.get("ending_equity", 0.0),
            "profit_factor": primary_full.get("profit_factor", 0.0),
            "avg_R": primary_full.get("avg_R", 0.0),
            "max_drawdown_pct": primary_full.get("max_drawdown_pct", 0.0),
        },
    )

    limitations = {
        **RESEARCH_ONLY_FLAGS,
        "reproduction_mode": "isolated_decision_time_gate_over_broad_candidate_ledger",
        "engine_mutation": False,
        "full_trade_generator_rerun": False,
        "limitations": [
            "This audit does not regenerate brand-new trade opportunities beyond the existing broad structural candidate stream.",
            "It reproduces native decision-time SR-aware short selection by gating the full broad BTCUSDT trade ledger with pre-entry-safe enriched fields.",
            "Robustness overlays are research accounting simulations only, not production execution behavior.",
        ],
    }

    frozen_reference = next((row for row in comparison_rows if row["variant_name"] == "FROZEN_PATCH_REFERENCE"), {})
    overlay_reference = next((row for row in comparison_rows if row["variant_name"] == "ENRICHED_OVERLAY_PROTOTYPE_REFERENCE"), {})
    if not native_best:
        classification = "NATIVE_SR_REPLAY_REJECTED"
    elif int(_safe_float(native_best.get("1M_hit_windows"))) > 0:
        classification = "NATIVE_SR_REPLAY_1M_PROMISING_RESEARCH_ONLY"
    elif _safe_float(native_best.get("average_5Y_ending_equity")) > max(
        _safe_float(frozen_reference.get("average_5Y_ending_equity")),
        _safe_float(overlay_reference.get("average_5Y_ending_equity")),
    ):
        classification = "NATIVE_SR_REPLAY_IMPROVES_BUT_NOT_MISSION_MOVING"
    elif _safe_float(native_best.get("average_5Y_ending_equity")) < _safe_float(frozen_reference.get("average_5Y_ending_equity")) * 0.90:
        classification = "NATIVE_SR_REPLAY_ABANDON_EQUAL_HIGHS_PATH"
    else:
        classification = "NATIVE_SR_REPLAY_WEAK"

    next_step = (
        "freeze the best native SR-aware variant and run stress plus Monte Carlo research-only validation before any broader continuation"
        if classification in {"NATIVE_SR_REPLAY_IMPROVES_BUT_NOT_MISSION_MOVING", "NATIVE_SR_REPLAY_1M_PROMISING_RESEARCH_ONLY"}
        else "abandon equal-highs short rescue as a mission path or redesign around a broader SR-aware short family outside the equal-highs rescue frame"
        if classification == "NATIVE_SR_REPLAY_ABANDON_EQUAL_HIGHS_PATH"
        else "do not promote; either redesign the native SR-aware short family or stop this path"
    )
    no_go_risks = {
        **RESEARCH_ONLY_FLAGS,
        "native_best_zero_1m_hits": int(_safe_float(native_best.get("1M_hit_windows"))) == 0,
        "cost_survival_fragile": any(_safe_float(row.get("average_5Y_ending_equity")) <= 0.0 for row in cost_rows if row["research_variant_name"] == native_best.get("variant_name")),
        "sample_too_selective": int(_safe_float(native_best.get("trade_count"))) < 100,
        "broad_artifacts_unchanged": broad_summary_before == paths["broad_summary"].read_text(encoding="utf-8"),
    }
    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "isolated_native_sr_aware_replay_ran": True,
        "primary_variant_name": primary_variant_name,
        "primary_trade_count": int(_safe_float(primary_full.get("trade_count"))),
        "primary_ending_equity": _safe_float(primary_full.get("ending_equity")),
        "primary_profit_factor": _safe_float(primary_full.get("profit_factor")),
        "primary_avg_R": _safe_float(primary_full.get("avg_R")),
        "primary_max_drawdown_pct": _safe_float(primary_full.get("max_drawdown_pct")),
        "best_native_variant": native_best.get("variant_name", ""),
        "best_native_trade_count": int(_safe_float(native_best.get("trade_count"))),
        "best_native_average_5Y_ending_equity": _safe_float(native_best.get("average_5Y_ending_equity")),
        "best_native_median_5Y_ending_equity": _safe_float(native_best.get("median_5Y_ending_equity")),
        "best_native_best_5Y_ending_equity": _safe_float(native_best.get("best_5Y_ending_equity")),
        "best_native_worst_5Y_ending_equity": _safe_float(native_best.get("worst_5Y_ending_equity")),
        "best_native_1M_hit_windows": int(_safe_float(native_best.get("1M_hit_windows"))),
        "best_native_5M_hit_windows": int(_safe_float(native_best.get("5M_hit_windows"))),
        "best_native_10M_hit_windows": int(_safe_float(native_best.get("10M_hit_windows"))),
        "best_native_cost_survival": max((_safe_float(row.get("average_5Y_ending_equity")) for row in cost_rows if row["research_variant_name"] == native_best.get("variant_name") and row["overlay_name"] == "NORMAL_COST"), default=0.0),
        "best_native_moonshot_survival": max((_safe_float(row.get("average_5Y_ending_equity")) for row in moonshot_rows if row["research_variant_name"] == native_best.get("variant_name") and row["overlay_name"] == "MOONSHOTS_CAPPED_5R"), default=0.0),
        "final_classification": classification,
        "next_recommended_research_step": next_step,
    }

    report_lines = [
        "# Native SR-Aware Structural Replay Reproduction Audit",
        "",
        "## Court Verdict",
        "",
        f"1. Did native SR-aware replay reproduce the enriched overlay edge? `{_safe_float(native_best.get('average_5Y_ending_equity')) >= _safe_float(overlay_reference.get('average_5Y_ending_equity'))}`",
        f"2. Did it improve over the frozen patch baseline? `{_safe_float(native_best.get('average_5Y_ending_equity')) > _safe_float(frozen_reference.get('average_5Y_ending_equity'))}`",
        f"3. Did it restore 1M rolling 5Y mission support? `{int(_safe_float(native_best.get('1M_hit_windows'))) > 0}`",
        f"4. Did it support 5M or 10M? `{int(_safe_float(native_best.get('5M_hit_windows'))) > 0 or int(_safe_float(native_best.get('10M_hit_windows'))) > 0}`",
        f"5. Did it survive costs? `{summary['best_native_cost_survival'] > 0}`",
        f"6. Did it survive moonshot caps? `{summary['best_native_moonshot_survival'] > 0}`",
        f"7. Did it reduce bad shorts into nearby support? `{classification in {'NATIVE_SR_REPLAY_IMPROVES_BUT_NOT_MISSION_MOVING', 'NATIVE_SR_REPLAY_1M_PROMISING_RESEARCH_ONLY'}}`",
        f"8. Did it become too selective? `{int(_safe_float(native_best.get('trade_count'))) < 100}`",
        f"9. Is this ready for another research replay, or should equal-highs rescue be rejected? `{classification}`",
        f"10. What is the next research step? `{next_step}`",
        "",
        "## Best Native Variant",
        "",
        f"- variant: `{summary['best_native_variant']}`",
        f"- trade count: `{summary['best_native_trade_count']}`",
        f"- average / median 5Y ending equity: `{summary['best_native_average_5Y_ending_equity']} / {summary['best_native_median_5Y_ending_equity']}`",
        f"- best / worst 5Y ending equity: `{summary['best_native_best_5Y_ending_equity']} / {summary['best_native_worst_5Y_ending_equity']}`",
        f"- 1M / 5M / 10M windows: `{summary['best_native_1M_hit_windows']} / {summary['best_native_5M_hit_windows']} / {summary['best_native_10M_hit_windows']}`",
        f"- normal-cost survival: `{summary['best_native_cost_survival']}`",
        f"- moonshot-capped-5R survival: `{summary['best_native_moonshot_survival']}`",
        "",
        "This remained research-only. No live, paper, runtime, production strategy defaults, allocator, risk, sizing, entry, exit, threshold, sleeve, or config behavior changed. Previous broad replay artifacts were read-only and preserved.",
    ]

    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "native_sr_aware_structural_replay_reproduction_summary.json", summary)
    _write_markdown(config.output_root / "native_sr_aware_structural_replay_reproduction_report.md", "\n".join(report_lines))
    _write_csv(diagnostics_root / "native_sr_aware_variant_comparison.csv", _normalize_rows(comparison_rows))
    _write_json(diagnostics_root / "native_sr_aware_variant_comparison.json", {"research_only": True, "variants": comparison_rows})
    _write_json(diagnostics_root / "native_sr_aware_replay_limitations.json", limitations)
    _write_csv(diagnostics_root / "native_sr_aware_rolling_5y_results.csv", _normalize_rows(rolling_rows))
    _write_csv(diagnostics_root / "native_sr_aware_mission_hit_matrix.csv", _normalize_rows(hit_matrix))
    _write_csv(diagnostics_root / "native_sr_aware_best_worst_windows.csv", _normalize_rows(best_worst_rows))
    _write_csv(diagnostics_root / "native_sr_aware_cost_survival.csv", _normalize_rows(cost_rows))
    _write_csv(diagnostics_root / "native_sr_aware_moonshot_survival.csv", _normalize_rows(moonshot_rows))
    _write_csv(diagnostics_root / "native_sr_aware_drawdown_governor.csv", _normalize_rows(governor_rows))
    _write_csv(diagnostics_root / "native_sr_aware_insolvency_clamp.csv", _normalize_rows(insolvency_rows))
    _write_json(diagnostics_root / "no_go_risks.json", no_go_risks)
    _write_json(reports_root / "next_research_recommendation.json", {"research_only": True, "next_step": next_step})

    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "native_sr_aware_structural_replay_reproduction_summary.json",
        "report": config.output_root / "native_sr_aware_structural_replay_reproduction_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    result = write_native_sr_aware_structural_replay_reproduction_audit(
        NativeSRAwareStructuralReplayReproductionAuditConfig(
            package_root=package_root,
            output_root=package_root / "output" / "native_sr_aware_structural_replay_reproduction_audit_001",
        )
    )
    print(result["summary"])


if __name__ == "__main__":
    main()
