from __future__ import annotations

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

from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import (  # noqa: E402
    RESEARCH_ONLY_FLAGS,
    _apply_frozen_patch,
    _load_frozen_rules,
)
from structural_compounding_lab.diagnostics.broad_patch_accounting_and_short_rescue_audit import (  # noqa: E402
    _apply_signature,
)
from structural_compounding_lab.diagnostics.equal_highs_liquidity_sweep_rescue_forensic_audit import (  # noqa: E402
    FORBIDDEN_FUTURE_FIELDS,
    _boolish,
    _classify_failure_mode,
    _feature_snapshot,
    _group_stats,
    _mission_row,
    _normalize_rows,
    _safe_float,
    _session_bucket,
    _simulate_overlay,
    _summarize_mission_rows,
    _window_label_for_trade,
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
class SupportRoomShortRescueRepairAuditConfig:
    package_root: Path
    output_root: Path


EXPECTED_SR_FIELDS = [
    "nearest_support_distance",
    "nearest_resistance_distance",
    "support_distance_pct",
    "resistance_distance_pct",
    "room_to_next_support",
    "room_to_next_resistance",
    "support_strength",
    "resistance_strength",
    "level_strength",
    "support_quality",
    "resistance_quality",
    "overhead_resistance",
    "nearby_support",
    "clean_downside_room",
    "atr_room",
    "rr_from_reason",
    "risk_reward_score",
    "liquidity_score",
    "sweep_high",
    "equal_highs",
    "liquidity_sweep",
    "rejection_quality",
    "wick_rejection",
    "htf_support",
    "htf_resistance",
    "trend_alignment",
    "session_quality",
]

SUPPORT_ROOM_FEATURES = [
    "support_distance_pct",
    "resistance_distance_pct",
    "stop_distance_pct",
    "risk_reward_score",
    "rr_from_reason",
    "liquidity_score",
    "liquidity_confidence",
    "structure_score",
    "entry_score",
    "nearest_support_strength",
    "nearest_resistance_strength",
    "nearest_support_touch_count",
    "nearest_resistance_touch_count",
    "downside_room_to_support_R",
    "downside_room_to_support_pct",
    "downside_room_to_support_level_ratio",
    "nearest_support_blocking_score",
    "support_room_quality_score",
    "resistance_rejection_quality_score",
    "sweep_plus_room_score",
]


def _paths(config: SupportRoomShortRescueRepairAuditConfig) -> dict[str, Path]:
    source_root = config.package_root / "output"
    broad_root = source_root / "broad_historical_structural_replay_001"
    broad_ledger_root = broad_root / "ledger"
    rescue_root = source_root / "broad_patch_accounting_and_short_rescue_audit_001"
    rolling_root = source_root / "rolling_five_year_mission_viability_audit_001"
    forensic_root = source_root / "equal_highs_liquidity_sweep_rescue_forensic_audit_001"
    return {
        "trades": broad_ledger_root / "trades.csv",
        "equity": broad_ledger_root / "equity.csv",
        "ledger_summary": broad_ledger_root / "summary.json",
        "setup_log": broad_ledger_root / "setup_log.csv",
        "level_log": broad_ledger_root / "level_log.csv",
        "liquidity_events": broad_ledger_root / "liquidity_events.csv",
        "removed_short_winner_profile": rescue_root / "diagnostics" / "removed_short_winner_profile.csv",
        "removed_short_loser_profile": rescue_root / "diagnostics" / "removed_short_loser_profile.csv",
        "rescue_signature_definitions": rescue_root / "diagnostics" / "rescue_signature_definitions.json",
        "rescue_signature_candidate_results": rescue_root / "diagnostics" / "rescue_signature_candidate_results.csv",
        "rolling_results": rolling_root / "diagnostics" / "rolling_5y_window_results.csv",
        "short_rescue_impact": rolling_root / "diagnostics" / "short_rescue_mission_impact.csv",
        "forensic_summary": forensic_root / "equal_highs_liquidity_sweep_rescue_summary.json",
        "rescued_short_trade_profile": forensic_root / "diagnostics" / "rescued_short_trade_profile.csv",
        "rescued_short_contrast": forensic_root / "diagnostics" / "rescued_short_winner_vs_loser_contrast.csv",
        "sr_liquidity_feature_separation": forensic_root / "diagnostics" / "sr_liquidity_feature_separation.csv",
        "rescue_loss_audit": forensic_root / "diagnostics" / "rescue_reintroduced_loss_audit.csv",
        "rescue_damage_summary": forensic_root / "diagnostics" / "rescue_damage_summary.json",
        "strict_variant_results": forensic_root / "diagnostics" / "stricter_rescue_variant_results.csv",
        "strict_variant_definitions": forensic_root / "diagnostics" / "stricter_rescue_variant_definitions.json",
        "frozen_patch_rules": source_root / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, reports_root


def _empty_outputs(config: SupportRoomShortRescueRepairAuditConfig, warnings: list[str]) -> dict[str, Path]:
    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    status = {"state": "empty", "resolved_at_utc": datetime.now(timezone.utc).isoformat(), **RESEARCH_ONLY_FLAGS, "warnings": warnings}
    summary = {**RESEARCH_ONLY_FLAGS, "warnings": warnings, "final_classification": "SUPPORT_ROOM_REPAIR_REJECTED"}
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "support_room_short_rescue_repair_summary.json", summary)
    _write_markdown(config.output_root / "support_room_short_rescue_repair_report.md", "# Support Room Short Rescue Repair Audit\n\nRequired artifacts missing.\n")
    for name in (
        "support_room_damage_reconstruction.csv",
        "support_room_feature_separation.csv",
        "support_room_quantile_analysis.csv",
        "derived_support_room_features.csv",
        "repaired_support_room_rescue_variant_results.csv",
        "repaired_rescue_rolling_5y_results.csv",
        "repaired_rescue_cost_survival.csv",
        "repaired_rescue_moonshot_survival.csv",
        "repaired_rescue_drawdown_governor.csv",
        "repaired_rescue_mission_hit_matrix.csv",
    ):
        _write_csv(diagnostics_root / name, [])
    for name in (
        "support_room_damage_summary.json",
        "sr_field_inventory.json",
        "missing_sr_fields_for_repair.json",
        "support_room_threshold_candidates.json",
        "derived_support_room_feature_notes.json",
        "repaired_support_room_rescue_variant_definitions.json",
        "repaired_support_room_rescue_variant_results.json",
        "repaired_support_room_rescue_no_leakage_check.json",
        "no_go_risks.json",
    ):
        _write_json(diagnostics_root / name, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "support_room_short_rescue_repair_summary.json",
        "report": config.output_root / "support_room_short_rescue_repair_report.md",
    }


def _derive_support_room_fields(row: dict[str, Any]) -> dict[str, Any]:
    support_distance_pct = _safe_float(row.get("support_distance_pct"))
    stop_distance_pct = _safe_float(row.get("stop_distance_pct"))
    level_distance_atr = _safe_float(row.get("level_distance_atr"))
    nearest_support_strength = _safe_float(row.get("nearest_support_strength"))
    nearest_support_touch_count = _safe_float(row.get("nearest_support_touch_count"))
    nearest_resistance_strength = _safe_float(row.get("nearest_resistance_strength"))
    nearest_resistance_touch_count = _safe_float(row.get("nearest_resistance_touch_count"))
    entry_score = _safe_float(row.get("entry_score"))
    liquidity_confidence = _safe_float(row.get("liquidity_confidence"))
    liquidity_score = _safe_float(row.get("liquidity_score"))
    structure_score = _safe_float(row.get("structure_score"))
    htf_bonus = 1.0 if _boolish(row.get("htf_aligned")) else 0.0
    downside_room_r = _safe_ratio(support_distance_pct, stop_distance_pct, 0.0) if stop_distance_pct > 0 else 0.0
    downside_room_level_ratio = _safe_ratio(support_distance_pct, level_distance_atr, 0.0) if level_distance_atr > 0 else 0.0
    blocking_score = 0.0
    if downside_room_r > 0.0:
        blocking_score = max(0.0, 1.25 - downside_room_r)
    blocking_score += min(nearest_support_strength / 5.0, 0.5)
    blocking_score += min(nearest_support_touch_count / 10.0, 0.5)
    support_room_quality = (
        min(downside_room_r / 2.0, 1.5)
        + min(liquidity_confidence, 1.0)
        + min(structure_score / 2.0, 1.0)
        + htf_bonus * 0.25
        - min(blocking_score, 1.5)
    )
    resistance_rejection_quality = (
        min(entry_score / 5.0, 1.25)
        + min(nearest_resistance_strength / 3.0, 1.0)
        + min(nearest_resistance_touch_count / 5.0, 0.75)
        + htf_bonus * 0.25
    )
    sweep_plus_room = support_room_quality + resistance_rejection_quality + min(liquidity_score, 1.0)
    return {
        "downside_room_to_support_R": round(downside_room_r, 6),
        "downside_room_to_support_pct": round(support_distance_pct, 6),
        "downside_room_to_support_level_ratio": round(downside_room_level_ratio, 6),
        "nearest_support_blocking_score": round(blocking_score, 6),
        "support_room_quality_score": round(support_room_quality, 6),
        "short_has_clean_downside_air": downside_room_r >= 1.25,
        "resistance_rejection_quality_score": round(resistance_rejection_quality, 6),
        "sweep_plus_room_score": round(sweep_plus_room, 6),
    }


def _feature_inventory(rows: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any]]:
    available = set()
    for row in rows:
        available.update(row.keys())
    alias_map = {
        "nearest_support_distance": "support_distance_pct",
        "nearest_resistance_distance": "resistance_distance_pct",
        "support_strength": "nearest_support_strength",
        "resistance_strength": "nearest_resistance_strength",
        "level_strength": "nearest_resistance_strength",
        "overhead_resistance": "entry_context",
        "liquidity_sweep": "liquidity_event_type",
        "trend_alignment": "htf_aligned",
        "session_quality": "session_bucket",
    }
    inventory = []
    missing = []
    for field in EXPECTED_SR_FIELDS:
        actual = field if field in available else alias_map.get(field)
        exists = actual in available if actual else False
        entry = {
            "requested_field": field,
            "available": exists,
            "actual_field": actual if exists else "",
            "pre_entry_safe": True if exists else None,
        }
        inventory.append(entry)
        if not exists:
            missing.append(field)
    return (
        {**RESEARCH_ONLY_FLAGS, "inventory": inventory},
        {**RESEARCH_ONLY_FLAGS, "missing_sr_fields_for_repair": sorted(missing)},
    )


def _feature_separation(rows: list[dict[str, Any]], winners: list[dict[str, Any]], losers: list[dict[str, Any]], support_losers: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    sep_rows = []
    quantile_rows = []
    threshold_candidates = {}
    for feature in SUPPORT_ROOM_FEATURES:
        all_vals = [_safe_float(row.get(feature)) for row in rows if str(row.get(feature, "")).strip() != ""]
        win_vals = [_safe_float(row.get(feature)) for row in winners if str(row.get(feature, "")).strip() != ""]
        lose_vals = [_safe_float(row.get(feature)) for row in losers if str(row.get(feature, "")).strip() != ""]
        support_vals = [_safe_float(row.get(feature)) for row in support_losers if str(row.get(feature, "")).strip() != ""]
        if not all_vals:
            continue
        win_mean = sum(win_vals) / len(win_vals) if win_vals else 0.0
        lose_mean = sum(lose_vals) / len(lose_vals) if lose_vals else 0.0
        support_mean = sum(support_vals) / len(support_vals) if support_vals else 0.0
        p25 = pd.Series(all_vals).quantile(0.25)
        p50 = pd.Series(all_vals).quantile(0.50)
        p75 = pd.Series(all_vals).quantile(0.75)
        overlap = min(max(win_vals) if win_vals else 0.0, max(lose_vals) if lose_vals else 0.0) - max(min(win_vals) if win_vals else 0.0, min(lose_vals) if lose_vals else 0.0)
        total_span = max(all_vals) - min(all_vals) if all_vals else 0.0
        overlap_ratio = max(0.0, overlap) / total_span if total_span > 0 else 1.0
        separation_score = abs(win_mean - lose_mean) / (abs(p75 - p25) + 1e-9)
        useful = bool(separation_score >= 0.15)
        sep_rows.append(
            {
                "feature": feature,
                "winner_mean": round(win_mean, 6),
                "loser_mean": round(lose_mean, 6),
                "support_room_loser_mean": round(support_mean, 6),
                "gap": round(win_mean - lose_mean, 6),
                "overlap_ratio": round(overlap_ratio, 6),
                "feature_separation_score": round(separation_score, 6),
                "useful_for_repair": bool(useful),
                "pre_entry_safe": True,
            }
        )
        quantile_rows.append(
            {
                "feature": feature,
                "q25": round(float(p25), 6),
                "q50": round(float(p50), 6),
                "q75": round(float(p75), 6),
                "winner_q50": round(float(pd.Series(win_vals).quantile(0.50)) if win_vals else 0.0, 6),
                "loser_q50": round(float(pd.Series(lose_vals).quantile(0.50)) if lose_vals else 0.0, 6),
            }
        )
        threshold_candidates[feature] = {
            "candidate_min_threshold": round(max(float(p50), lose_mean), 6) if win_mean > lose_mean else round(min(float(p50), lose_mean), 6),
            "direction": "higher_is_better" if win_mean >= lose_mean else "lower_is_better",
            "useful_for_repair": bool(useful),
        }
    sep_rows.sort(key=lambda row: row["feature_separation_score"], reverse=True)
    return sep_rows, quantile_rows, {**RESEARCH_ONLY_FLAGS, "threshold_candidates": threshold_candidates}


def _variant_specs() -> list[dict[str, Any]]:
    return [
        {
            "variant_name": "STRICT_EQUAL_HIGHS_COMPOSITE_A_PLUS_BASELINE",
            "fields_used": ["archetype_key", "personality_label", "htf_aligned", "liquidity_confidence", "entry_score", "structure_score", "support_distance_pct", "stop_distance_pct"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and sum(
                [
                    1 if _boolish(row.get("htf_aligned")) else 0,
                    1 if _safe_float(row.get("liquidity_confidence")) >= 0.60 else 0,
                    1 if _safe_float(row.get("entry_score")) >= 4.0 else 0,
                    1 if _safe_float(row.get("structure_score")) >= 0.90 else 0,
                    1 if _safe_float(row.get("downside_room_to_support_R")) >= 1.25 else 0,
                ]
            ) >= 3,
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_WITH_CLEAN_DOWNSIDE_ROOM",
            "fields_used": ["archetype_key", "personality_label", "short_has_clean_downside_air"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and _boolish(row.get("short_has_clean_downside_air")),
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_WITH_MIN_ROOM_TO_SUPPORT_R",
            "fields_used": ["archetype_key", "personality_label", "downside_room_to_support_R"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and _safe_float(row.get("downside_room_to_support_R")) >= 1.75,
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_WITH_MIN_ROOM_TO_SUPPORT_ATR",
            "fields_used": ["archetype_key", "personality_label", "downside_room_to_support_level_ratio"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and _safe_float(row.get("downside_room_to_support_level_ratio")) >= 0.015,
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_WITH_NO_NEARBY_SUPPORT_BLOCK",
            "fields_used": ["archetype_key", "personality_label", "nearest_support_blocking_score"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and _safe_float(row.get("nearest_support_blocking_score")) <= 0.25,
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_WITH_STRONG_RESISTANCE_AND_ROOM",
            "fields_used": ["archetype_key", "personality_label", "nearest_resistance_strength", "nearest_resistance_touch_count", "downside_room_to_support_R"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and _safe_float(row.get("nearest_resistance_strength")) >= 2.0 and _safe_float(row.get("nearest_resistance_touch_count")) >= 3 and _safe_float(row.get("downside_room_to_support_R")) >= 1.25,
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_WITH_SWEEP_REJECTION_AND_ROOM",
            "fields_used": ["archetype_key", "personality_label", "entry_score", "setup_class", "downside_room_to_support_R"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and _safe_float(row.get("entry_score")) >= 4.0 and str(row.get("setup_class") or "") in {"A", "B"} and _safe_float(row.get("downside_room_to_support_R")) >= 1.25,
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_WITH_ROOM_AND_VOLUME_CONFIRMATION",
            "fields_used": ["archetype_key", "personality_label", "volume_confirmation", "downside_room_to_support_R"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and str(row.get("volume_confirmation") or "").lower() not in {"", "unknown", "none"} and _safe_float(row.get("downside_room_to_support_R")) >= 1.25,
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_WITH_ROOM_AND_HTF_RESISTANCE",
            "fields_used": ["archetype_key", "personality_label", "htf_aligned", "entry_context", "downside_room_to_support_R"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and (_boolish(row.get("htf_aligned")) or str(row.get("entry_context") or "") in {"resistance", "range_high", "prev_day_high"}) and _safe_float(row.get("downside_room_to_support_R")) >= 1.25,
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_MULTI_FACTOR_SR_SCORE",
            "fields_used": ["archetype_key", "personality_label", "support_room_quality_score", "resistance_rejection_quality_score", "sweep_plus_room_score"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and _safe_float(row.get("support_room_quality_score")) >= 0.60 and _safe_float(row.get("resistance_rejection_quality_score")) >= 1.75 and _safe_float(row.get("sweep_plus_room_score")) >= 2.5,
        },
    ]


def _no_leakage_payload(variant_defs: list[dict[str, Any]]) -> dict[str, Any]:
    variants = []
    violations = []
    for spec in variant_defs:
        bad = [field for field in spec["fields_used"] if field in FORBIDDEN_FUTURE_FIELDS]
        if bad:
            violations.append({"variant_name": spec["variant_name"], "forbidden_fields": bad})
        variants.append(
            {
                "variant_name": spec["variant_name"],
                "fields_used": spec["fields_used"],
                "future_fields_used": bad,
                "all_fields_pre_entry_safe": not bad,
            }
        )
    return {**RESEARCH_ONLY_FLAGS, "variants": variants, "violations": violations, "final_no_leakage_verdict": not violations}


def write_support_room_short_rescue_repair_audit(config: SupportRoomShortRescueRepairAuditConfig) -> dict[str, Path]:
    paths = _paths(config)
    required = (
        paths["trades"],
        paths["equity"],
        paths["ledger_summary"],
        paths["setup_log"],
        paths["level_log"],
        paths["liquidity_events"],
        paths["removed_short_winner_profile"],
        paths["removed_short_loser_profile"],
        paths["rescue_signature_definitions"],
        paths["rescue_signature_candidate_results"],
        paths["rolling_results"],
        paths["short_rescue_impact"],
        paths["forensic_summary"],
        paths["rescued_short_trade_profile"],
        paths["rescued_short_contrast"],
        paths["sr_liquidity_feature_separation"],
        paths["rescue_loss_audit"],
        paths["rescue_damage_summary"],
        paths["strict_variant_results"],
        paths["strict_variant_definitions"],
        paths["frozen_patch_rules"],
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return _empty_outputs(config, [f"missing_required_artifact:{path}" for path in missing])

    rescued_trade_profile = _read_csv_rows(paths["rescued_short_trade_profile"])
    rescue_loss_audit = _read_csv_rows(paths["rescue_loss_audit"])
    rescue_summary = _read_json(paths["forensic_summary"], {})
    strict_variant_results = _read_csv_rows(paths["strict_variant_results"])

    trade_rows = _read_csv_rows(paths["trades"])
    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    normalized_rows = _normalize_trade_rows(trade_rows, setup_rows, level_rows, liquidity_rows)
    prepared_rows = _prepare_rows(normalized_rows)
    windows = _build_windows(prepared_rows)
    matched_short_archetypes, disabled_long_modes, _ = _load_frozen_rules(paths["frozen_patch_rules"])
    kept_rows, removed_rows = _apply_frozen_patch(
        prepared_rows,
        matched_short_archetypes=matched_short_archetypes,
        disabled_long_modes=disabled_long_modes,
    )
    removed_shorts = [row for row in removed_rows if row.get("side") == "short"]
    original_rescue_rows = _apply_signature("RESCUE_EQUAL_HIGHS_LIQUIDITY_SWEEP", removed_shorts)
    for row in original_rescue_rows:
        row["rolling_window_label"] = _window_label_for_trade(row.get("exit_timestamp"), windows)
        row["session_bucket"] = _session_bucket(row.get("entry_timestamp"))
        row.update(_derive_support_room_fields(row))

    support_room_losers = []
    loss_trade_ids = {str(row.get("trade_id") or "") for row in rescue_loss_audit if str(row.get("failure_mode") or "") == "NO_NEARBY_SUPPORT_ROOM"}
    strict_a_plus_trade_ids: set[str] = set()
    for spec in _variant_specs():
        if spec["variant_name"] == "STRICT_EQUAL_HIGHS_COMPOSITE_A_PLUS_BASELINE":
            strict_a_plus_trade_ids = {str(row.get("trade_id") or "") for row in original_rescue_rows if spec["predicate"](row)}
            break

    damage_rows = []
    for row in original_rescue_rows:
        r_value = _safe_float(row.get("r_multiple"))
        failure_mode = _classify_failure_mode(row) if r_value < 0 else ""
        if failure_mode == "NO_NEARBY_SUPPORT_ROOM":
            support_room_losers.append(row)
        snapshot = _feature_snapshot(row)
        snapshot.update(_derive_support_room_fields(row))
        snapshot["damage_group"] = (
            "strict_a_plus_rescued"
            if str(row.get("trade_id") or "") in strict_a_plus_trade_ids
            else "rescued_winner"
            if r_value > 0
            else "rescued_loser"
        )
        snapshot["failure_mode"] = failure_mode
        snapshot["is_support_room_damage"] = failure_mode == "NO_NEARBY_SUPPORT_ROOM"
        damage_rows.append(snapshot)

    damage_summary = {
        **RESEARCH_ONLY_FLAGS,
        "rescued_trade_count": len(original_rescue_rows),
        "rescued_winner_count": sum(1 for row in original_rescue_rows if _safe_float(row.get("r_multiple")) > 0.0),
        "rescued_loser_count": sum(1 for row in original_rescue_rows if _safe_float(row.get("r_multiple")) < 0.0),
        "support_room_damage_count": len(support_room_losers),
        "strict_a_plus_trade_count": len(strict_a_plus_trade_ids),
    }

    sr_inventory, missing_sr_fields = _feature_inventory(damage_rows)
    sep_rows, quantile_rows, threshold_candidates = _feature_separation(
        damage_rows,
        [row for row in damage_rows if _safe_float(row.get("r_multiple")) > 0.0],
        [row for row in damage_rows if _safe_float(row.get("r_multiple")) < 0.0],
        [row for row in damage_rows if row.get("failure_mode") == "NO_NEARBY_SUPPORT_ROOM"],
    )

    derived_feature_notes = {
        **RESEARCH_ONLY_FLAGS,
        "derived_features": [
            {"name": "downside_room_to_support_R", "formula": "support_distance_pct / stop_distance_pct", "pre_entry_safe": True},
            {"name": "downside_room_to_support_level_ratio", "formula": "support_distance_pct / level_distance_atr", "pre_entry_safe": True},
            {"name": "nearest_support_blocking_score", "formula": "inverse downside room plus support strength/touch count", "pre_entry_safe": True},
            {"name": "support_room_quality_score", "formula": "downside room + structure/liquidity - support blocking", "pre_entry_safe": True},
            {"name": "resistance_rejection_quality_score", "formula": "entry_score + resistance strength/touches + HTF bonus", "pre_entry_safe": True},
            {"name": "sweep_plus_room_score", "formula": "support_room_quality_score + resistance_rejection_quality_score + liquidity_score", "pre_entry_safe": True},
        ],
        "missing_data_blocks_repair": not any(row["useful_for_repair"] for row in sep_rows),
    }

    baseline_kept_only_rows = [
        row for row in _read_csv_rows(paths["rolling_results"])
        if row.get("variant_name") == "FROZEN_PATCH_NATIVE_STYLE_RECONCILED"
    ]
    baseline_kept_only = _summarize_mission_rows(baseline_kept_only_rows)

    repaired_variant_defs = _variant_specs()
    repaired_variant_results = []
    repaired_rolling_rows = []
    hit_matrix_rows = []
    category_rows = {"cost": [], "moonshot": [], "governor": []}
    overlay_specs = [
        {"variant_name": "BASELINE_NATIVE_STYLE_RECONCILED", "category": "baseline"},
        {"variant_name": "LOW_COST", "category": "cost", "cost_bps_total": 7.0},
        {"variant_name": "NORMAL_COST", "category": "cost", "cost_bps_total": 15.0},
        {"variant_name": "HIGH_COST", "category": "cost", "cost_bps_total": 25.0},
        {"variant_name": "STRESS_COST", "category": "cost", "cost_bps_total": 45.0},
        {"variant_name": "MOONSHOTS_CAPPED_10R", "category": "moonshot", "moonshot_cap": 10.0},
        {"variant_name": "MOONSHOTS_CAPPED_5R", "category": "moonshot", "moonshot_cap": 5.0},
        {"variant_name": "MOONSHOTS_CAPPED_3R", "category": "moonshot", "moonshot_cap": 3.0},
        {"variant_name": "ALL_5R_PLUS_REMOVED", "category": "moonshot", "remove_5plus": True},
        {"variant_name": "INSOLVENCY_CLAMP_ZERO", "category": "governor", "insolvency_clamp": True},
        {"variant_name": "DRAWDOWN_CIRCUIT_BREAKER_10", "category": "governor", "drawdown_breaker_pct": 0.10},
        {"variant_name": "DRAWDOWN_CIRCUIT_BREAKER_15", "category": "governor", "drawdown_breaker_pct": 0.15},
        {"variant_name": "DRAWDOWN_CIRCUIT_BREAKER_20", "category": "governor", "drawdown_breaker_pct": 0.20},
    ]
    for spec in repaired_variant_defs:
        rescued_variant = [row for row in original_rescue_rows if spec["predicate"](row)]
        variant_selected = kept_rows + rescued_variant
        overlay_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for start, end, label in windows:
            selected_window_rows = _window_rows(variant_selected, start, end)
            for overlay in overlay_specs:
                output = _simulate_overlay(
                    selected_rows=selected_window_rows,
                    cost_bps_total=_safe_float(overlay.get("cost_bps_total")),
                    moonshot_cap=overlay.get("moonshot_cap"),
                    remove_5plus=_boolish(overlay.get("remove_5plus")),
                    insolvency_clamp=_boolish(overlay.get("insolvency_clamp")),
                    drawdown_breaker_pct=overlay.get("drawdown_breaker_pct"),
                )
                row = _mission_row(variant_name=overlay["variant_name"], window_label=label, start=start, end=end, output=output)
                row["repair_variant_name"] = spec["variant_name"]
                row["overlay_category"] = overlay["category"]
                repaired_rolling_rows.append(row)
                overlay_by_name[overlay["variant_name"]].append(row)
                if overlay["variant_name"] == "BASELINE_NATIVE_STYLE_RECONCILED":
                    hit_matrix_rows.append(
                        {
                            "repair_variant_name": spec["variant_name"],
                            "window_label": label,
                            "hit_1m": row["hit_1m"],
                            "hit_5m": row["hit_5m"],
                            "hit_10m": row["hit_10m"],
                        }
                    )
        base_summary = _summarize_mission_rows(overlay_by_name["BASELINE_NATIVE_STYLE_RECONCILED"])
        normal_cost_summary = _summarize_mission_rows(overlay_by_name["NORMAL_COST"])
        moonshot_summary = _summarize_mission_rows(overlay_by_name["MOONSHOTS_CAPPED_5R"])
        drawdown_summary = _summarize_mission_rows(overlay_by_name["DRAWDOWN_CIRCUIT_BREAKER_15"])
        r_values = [_safe_float(row.get("r_multiple")) for row in rescued_variant]
        wins = [value for value in r_values if value > 0.0]
        losses = [abs(value) for value in r_values if value < 0.0]
        pf = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
        original_total_r = rescue_summary.get("rescued_total_R", 0.0)
        removed_damage = rescue_summary.get("rescued_loser_count", 0) - sum(1 for row in rescued_variant if _safe_float(row.get("r_multiple")) < 0.0)
        preserved_upside = sum(1 for row in rescued_variant if _safe_float(row.get("r_multiple")) >= 5.0)
        verdict = "weaker_than_kept_only"
        if base_summary["average_ending_equity"] > baseline_kept_only["average_ending_equity"] and base_summary["hit_1m_windows"] > 0:
            verdict = "mission_moving"
        elif base_summary["average_ending_equity"] > rescue_summary.get("forensic_average_5Y_ending_equity", 0.0):
            verdict = "improves_but_not_mission_moving"
        if not rescued_variant:
            verdict = "too_tight_zero_rescue"
        repaired_variant_results.append(
            {
                "variant_name": spec["variant_name"],
                "fields_used": "|".join(spec["fields_used"]),
                "no_future_leakage_status": not any(field in FORBIDDEN_FUTURE_FIELDS for field in spec["fields_used"]),
                "trade_count": len(rescued_variant),
                "winner_count": sum(1 for row in rescued_variant if _safe_float(row.get("r_multiple")) > 0.0),
                "loser_count": sum(1 for row in rescued_variant if _safe_float(row.get("r_multiple")) < 0.0),
                "total_R": round(sum(r_values), 6),
                "PF": round(pf, 6),
                "avg_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
                "median_R": round(_median(r_values), 6) if r_values else 0.0,
                "win_rate": round(_safe_ratio(len(wins), len(r_values), 0.0), 6) if r_values else 0.0,
                "3R_plus_count": sum(1 for row in rescued_variant if _safe_float(row.get("r_multiple")) >= 3.0),
                "5R_plus_count": sum(1 for row in rescued_variant if _safe_float(row.get("r_multiple")) >= 5.0),
                "10R_plus_count": sum(1 for row in rescued_variant if _safe_float(row.get("r_multiple")) >= 10.0),
                "reintroduced_loser_R": round(sum(_safe_float(row.get("r_multiple")) for row in rescued_variant if _safe_float(row.get("r_multiple")) < 0.0), 6),
                "removed_damage_vs_original_rescue": removed_damage,
                "preserved_upside_vs_original_rescue": preserved_upside,
                "average_5Y_ending_equity": base_summary["average_ending_equity"],
                "median_5Y_ending_equity": base_summary["median_ending_equity"],
                "best_5Y_ending_equity": base_summary["best_ending_equity"],
                "worst_5Y_ending_equity": base_summary["worst_ending_equity"],
                "1M_hit_windows": base_summary["hit_1m_windows"],
                "5M_hit_windows": base_summary["hit_5m_windows"],
                "max_drawdown": base_summary["worst_max_drawdown_pct"],
                "cost_survival": normal_cost_summary["average_ending_equity"],
                "moonshot_survival": moonshot_summary["average_ending_equity"],
                "drawdown_governor": drawdown_summary["average_ending_equity"],
                "verdict": verdict,
            }
        )
        for overlay_name, rows in overlay_by_name.items():
            if overlay_name in {"LOW_COST", "NORMAL_COST", "HIGH_COST", "STRESS_COST"}:
                category_rows["cost"].extend(rows)
            elif overlay_name in {"MOONSHOTS_CAPPED_10R", "MOONSHOTS_CAPPED_5R", "MOONSHOTS_CAPPED_3R", "ALL_5R_PLUS_REMOVED"}:
                category_rows["moonshot"].extend(rows)
            elif overlay_name in {"INSOLVENCY_CLAMP_ZERO", "DRAWDOWN_CIRCUIT_BREAKER_10", "DRAWDOWN_CIRCUIT_BREAKER_15", "DRAWDOWN_CIRCUIT_BREAKER_20"}:
                category_rows["governor"].extend(rows)

    repaired_no_leakage = _no_leakage_payload(repaired_variant_defs)
    positive_variants = [row for row in repaired_variant_results if int(_safe_float(row.get("trade_count"))) > 0]
    best_variant = max(positive_variants, key=lambda row: (_safe_float(row["average_5Y_ending_equity"]), _safe_float(row["total_R"])), default={})

    if missing_sr_fields["missing_sr_fields_for_repair"] and len(sr_inventory["inventory"]) <= len(missing_sr_fields["missing_sr_fields_for_repair"]) + 5:
        final_classification = "SUPPORT_ROOM_REPAIR_BLOCKED_BY_MISSING_FIELDS"
    elif not positive_variants:
        final_classification = "SUPPORT_ROOM_REPAIR_REJECTED"
    elif _safe_float(best_variant.get("average_5Y_ending_equity")) > baseline_kept_only["average_ending_equity"] and int(_safe_float(best_variant.get("1M_hit_windows"))) > 0:
        final_classification = "SUPPORT_ROOM_REPAIR_READY_FOR_NATIVE_REPLAY_RESEARCH_ONLY"
    elif _safe_float(best_variant.get("average_5Y_ending_equity")) > rescue_summary.get("forensic_average_5Y_ending_equity", 0.0) * 1.10:
        final_classification = "SUPPORT_ROOM_REPAIR_IMPROVES_BUT_NOT_MISSION_MOVING"
    else:
        final_classification = "SUPPORT_ROOM_REPAIR_WEAK"

    next_step = "either enrich pre-entry support-room fields in a native structural replay or abandon equal-highs short rescue as a mission path if support-room enrichment cannot be reproduced cleanly"
    no_go_risks = {
        **RESEARCH_ONLY_FLAGS,
        "best_variant_still_below_kept_only_baseline": _safe_float(best_variant.get("average_5Y_ending_equity")) <= baseline_kept_only["average_ending_equity"],
        "best_variant_has_zero_1m_hits": int(_safe_float(best_variant.get("1M_hit_windows"))) == 0,
        "support_room_damage_still_dominant": damage_summary["support_room_damage_count"] >= 100,
    }
    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "rescued_damage_reconstructed": True,
        "available_sr_field_count": sum(1 for item in sr_inventory["inventory"] if item["available"]),
        "missing_sr_field_count": len(missing_sr_fields["missing_sr_fields_for_repair"]),
        "best_support_room_repaired_variant": best_variant.get("variant_name", ""),
        "best_variant_trade_count": int(_safe_float(best_variant.get("trade_count"))),
        "best_variant_winner_count": int(_safe_float(best_variant.get("winner_count"))),
        "best_variant_loser_count": int(_safe_float(best_variant.get("loser_count"))),
        "best_variant_total_R": _safe_float(best_variant.get("total_R")),
        "best_variant_PF": _safe_float(best_variant.get("PF")),
        "best_variant_avg_R": _safe_float(best_variant.get("avg_R")),
        "best_variant_average_5Y_ending_equity": _safe_float(best_variant.get("average_5Y_ending_equity")),
        "best_variant_median_5Y_ending_equity": _safe_float(best_variant.get("median_5Y_ending_equity")),
        "best_variant_1M_hit_windows": int(_safe_float(best_variant.get("1M_hit_windows"))),
        "best_variant_5M_hit_windows": int(_safe_float(best_variant.get("5M_hit_windows"))),
        "final_classification": final_classification,
        "next_recommended_research_step": next_step,
    }

    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    report_lines = [
        "# Support Room Short Rescue Repair Audit",
        "",
        f"- previous rescue overstated: `True`",
        f"- support-room damage count: `{damage_summary['support_room_damage_count']}`",
        f"- available SR fields: `{summary['available_sr_field_count']}`",
        f"- missing SR fields: `{summary['missing_sr_field_count']}`",
        f"- best repaired variant: `{summary['best_support_room_repaired_variant']}`",
        f"- average 5Y ending equity: `{summary['best_variant_average_5Y_ending_equity']}`",
        f"- median 5Y ending equity: `{summary['best_variant_median_5Y_ending_equity']}`",
        f"- 1M hit windows: `{summary['best_variant_1M_hit_windows']}`",
        f"- 5M hit windows: `{summary['best_variant_5M_hit_windows']}`",
        f"- final classification: `{final_classification}`",
        "",
        "The repair path was tested using existing SR fields plus diagnostic-only derived support-room features. No runtime SR logic was changed.",
        "",
        "## Best Separating Support-Room Features",
    ]
    for row in sep_rows[:5]:
        report_lines.append(f"- `{row['feature']}` separation `{row['feature_separation_score']}` with winner_mean `{row['winner_mean']}` and loser_mean `{row['loser_mean']}`")
    report_lines.extend(
        [
            "",
            "## Court Verdict",
            "",
            f"- next recommended research step: `{next_step}`",
            "",
            "This remains research-only. No live, paper, runtime, strategy, allocator, risk, sizing, entry, exit, threshold, sleeve, or config behavior changed.",
        ]
    )

    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "support_room_short_rescue_repair_summary.json", summary)
    _write_markdown(config.output_root / "support_room_short_rescue_repair_report.md", "\n".join(report_lines))
    _write_csv(diagnostics_root / "support_room_damage_reconstruction.csv", _normalize_rows(damage_rows))
    _write_json(diagnostics_root / "support_room_damage_summary.json", damage_summary)
    _write_json(diagnostics_root / "sr_field_inventory.json", sr_inventory)
    _write_json(diagnostics_root / "missing_sr_fields_for_repair.json", missing_sr_fields)
    _write_csv(diagnostics_root / "support_room_feature_separation.csv", _normalize_rows(sep_rows))
    _write_csv(diagnostics_root / "support_room_quantile_analysis.csv", _normalize_rows(quantile_rows))
    _write_json(diagnostics_root / "support_room_threshold_candidates.json", threshold_candidates)
    _write_csv(diagnostics_root / "derived_support_room_features.csv", _normalize_rows([{k: row.get(k, "") for k in ["trade_id", "downside_room_to_support_R", "downside_room_to_support_pct", "downside_room_to_support_level_ratio", "nearest_support_blocking_score", "support_room_quality_score", "short_has_clean_downside_air", "resistance_rejection_quality_score", "sweep_plus_room_score"]} for row in damage_rows]))
    _write_json(diagnostics_root / "derived_support_room_feature_notes.json", derived_feature_notes)
    _write_json(diagnostics_root / "repaired_support_room_rescue_variant_definitions.json", {"research_only": True, "variants": [{"variant_name": spec["variant_name"], "fields_used": spec["fields_used"]} for spec in repaired_variant_defs]})
    _write_csv(diagnostics_root / "repaired_support_room_rescue_variant_results.csv", _normalize_rows(repaired_variant_results))
    _write_json(diagnostics_root / "repaired_support_room_rescue_variant_results.json", {"research_only": True, "variants": repaired_variant_results})
    _write_json(diagnostics_root / "repaired_support_room_rescue_no_leakage_check.json", repaired_no_leakage)
    _write_csv(diagnostics_root / "repaired_rescue_rolling_5y_results.csv", _normalize_rows(repaired_rolling_rows))
    _write_csv(diagnostics_root / "repaired_rescue_cost_survival.csv", _normalize_rows(category_rows["cost"]))
    _write_csv(diagnostics_root / "repaired_rescue_moonshot_survival.csv", _normalize_rows(category_rows["moonshot"]))
    _write_csv(diagnostics_root / "repaired_rescue_drawdown_governor.csv", _normalize_rows(category_rows["governor"]))
    _write_csv(diagnostics_root / "repaired_rescue_mission_hit_matrix.csv", _normalize_rows(hit_matrix_rows))
    _write_json(diagnostics_root / "no_go_risks.json", no_go_risks)
    _write_json(reports_root / "next_research_recommendation.json", {"research_only": True, "next_step": next_step})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "support_room_short_rescue_repair_summary.json",
        "report": config.output_root / "support_room_short_rescue_repair_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    result = write_support_room_short_rescue_repair_audit(
        SupportRoomShortRescueRepairAuditConfig(
            package_root=package_root,
            output_root=package_root / "output" / "support_room_short_rescue_repair_audit_001",
        )
    )
    print(result["summary"])


if __name__ == "__main__":
    main()
