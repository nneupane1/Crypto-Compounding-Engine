from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any


@dataclass(frozen=True)
class DetectorTighteningConfig:
    review_root: Path
    refinement_root: Path
    output_root: Path


@dataclass(frozen=True)
class ThresholdCalibrationConfig:
    review_root: Path
    refinement_root: Path
    stage2_root: Path
    output_root: Path


_WINDOWS = ("smoke", "diagnostic_fast", "holdout_recent_preview")
_ALLOWED_CLASSIFICATIONS = (
    "reject",
    "continue_research",
    "needs_more_detector_tightening",
    "eligible_for_second_fast_review",
)
_REJECT_TYPES = {"STRUCTURE_BREAK_DIP", "EXHAUSTION_DIP", "NO_VALID_PULLBACK", "NO_PULLBACK_SIGNAL"}
_QUALITY_ORDER = {"A": 5, "B": 4, "C": 3, "D": 2, "REJECT": 1}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _safe_mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _safe_median(values: list[float]) -> float | None:
    return median(values) if values else None


def _trimmed_mean(values: list[float], trim_fraction: float = 0.1) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    trim_count = int(len(ordered) * trim_fraction)
    if trim_count * 2 >= len(ordered):
        return _safe_mean(ordered)
    trimmed = ordered[trim_count : len(ordered) - trim_count]
    return _safe_mean(trimmed)


def _winsorized_mean(values: list[float], winsor_fraction: float = 0.1) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    edge_count = int(len(ordered) * winsor_fraction)
    if edge_count <= 0 or edge_count * 2 >= len(ordered):
        return _safe_mean(ordered)
    low = ordered[edge_count]
    high = ordered[-edge_count - 1]
    winsorized = [min(max(value, low), high) for value in ordered]
    return _safe_mean(winsorized)


def _fmt(value: float | None, spec: str = ".3f") -> str:
    if value is None:
        return "n/a"
    return format(value, spec)


def _safe_float_value(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def build_detector_tightening_thresholds() -> dict[str, float]:
    return {
        "minimum_refined_stop_atr_fraction": 0.30,
        "minimum_refined_stop_cost_multiple": 2.50,
        "minimum_noise_multiple": 0.55,
        "minimum_wick_multiple": 1.10,
        "maximum_pullback_depth_atr": 1.80,
        "maximum_pullback_depth_impulse_fraction": 0.45,
        "max_confirmation_delay_candles": 6.0,
        "max_late_confirmation_candles": 10.0,
        "minimum_structure_validity_score": 0.72,
        "minimum_net_reward_to_cost_ratio": 3.00,
        "maximum_expected_cost_r": 0.35,
        "require_low_cost_prefilter": 1.0,
        "require_normal_cost_prefilter": 1.0,
    }


def build_threshold_profiles() -> dict[str, dict[str, float]]:
    strict = build_detector_tightening_thresholds()
    return {
        "strict": strict,
        "balanced": {
            **strict,
            "minimum_refined_stop_atr_fraction": 0.24,
            "minimum_refined_stop_cost_multiple": 1.95,
            "minimum_noise_multiple": 0.42,
            "minimum_wick_multiple": 0.92,
            "maximum_pullback_depth_atr": 2.00,
            "maximum_pullback_depth_impulse_fraction": 0.50,
            "max_confirmation_delay_candles": 8.0,
            "max_late_confirmation_candles": 12.0,
        },
        "relaxed": {
            **strict,
            "minimum_refined_stop_atr_fraction": 0.18,
            "minimum_refined_stop_cost_multiple": 1.45,
            "minimum_noise_multiple": 0.28,
            "minimum_wick_multiple": 0.72,
            "maximum_pullback_depth_atr": 2.35,
            "maximum_pullback_depth_impulse_fraction": 0.60,
            "max_confirmation_delay_candles": 10.0,
            "max_late_confirmation_candles": 14.0,
            "require_normal_cost_prefilter": 0.0,
        },
        "cost_first": {
            **strict,
            "minimum_refined_stop_atr_fraction": 0.26,
            "minimum_refined_stop_cost_multiple": 2.75,
            "minimum_noise_multiple": 0.40,
            "minimum_wick_multiple": 0.90,
            "maximum_pullback_depth_atr": 1.95,
            "maximum_pullback_depth_impulse_fraction": 0.48,
            "max_confirmation_delay_candles": 8.0,
            "max_late_confirmation_candles": 11.0,
        },
        "noise_first": {
            **strict,
            "minimum_refined_stop_atr_fraction": 0.22,
            "minimum_refined_stop_cost_multiple": 1.80,
            "minimum_noise_multiple": 0.64,
            "minimum_wick_multiple": 1.28,
            "maximum_pullback_depth_atr": 2.10,
            "maximum_pullback_depth_impulse_fraction": 0.52,
            "max_confirmation_delay_candles": 9.0,
            "max_late_confirmation_candles": 13.0,
        },
    }


def _load_refinement_rows(refinement_root: Path) -> list[dict[str, Any]]:
    with (refinement_root / "diagnostics" / "original_vs_pullback_entry_cost_aware.csv").open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    numeric_fields = {
        "trade_pnl",
        "trade_r_multiple",
        "entry_score",
        "original_entry_price",
        "original_stop",
        "refined_entry_price",
        "refined_stop",
        "target_price_same",
        "original_risk_distance",
        "refined_stop_distance",
        "refined_stop_atr_fraction",
        "refined_stop_cost_multiple",
        "atr_value",
        "recent_candle_noise",
        "local_wick_noise",
        "tick_size_estimate",
        "original_gross_r",
        "refined_gross_r",
        "original_net_r_after_fees",
        "refined_net_r_after_fees",
        "original_net_r_after_fees_slippage",
        "refined_net_r_after_fees_slippage",
        "cost_drag_in_r",
        "minimum_required_move_after_costs",
        "net_reward_to_cost_ratio",
        "expected_cost_r",
        "improved_r_delta",
        "pullback_depth_atr",
        "pullback_quality_score",
    }
    bool_fields = {
        "pullback_detected",
        "missed_due_to_waiting",
        "tiny_stop_flag",
        "unrealistic_stop_flag",
        "noise_stop_flag",
        "cost_dominated_stop_flag",
        "refined_improves_after_costs",
        "cost_destroys_refined_advantage",
        "survives_low_cost",
        "survives_normal_cost",
        "survives_high_cost",
        "survives_stress_cost",
        "cost_aware_pullback_candidate",
        "tiny_stop_outlier",
    }
    for row in rows:
        for key in numeric_fields:
            if key in row:
                row[key] = float(row[key] or 0.0)
        for key in bool_fields:
            if key in row:
                row[key] = str(row[key]).lower() == "true"
    return rows


def _load_setup_lookup(review_root: Path) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for window in _WINDOWS:
        path = review_root / window / "setup_log.csv"
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                lookup[(window, str(row.get("symbol", "")).upper(), str(row.get("side", "")).lower(), str(row.get("timestamp")))] = row
    return lookup


def _to_bool(value: Any) -> bool:
    return str(value).lower() == "true"


def grade_tightened_candidate(row: dict[str, Any], thresholds: dict[str, float]) -> dict[str, Any]:
    pullback_depth = float(row["pullback_depth_atr"]) * float(row["atr_value"])
    target_move = abs(float(row["target_price_same"]) - float(row["original_entry_price"]))
    pullback_depth_impulse_fraction = (pullback_depth / target_move) if target_move > 0 else 0.0

    too_deep_flag = (
        float(row["pullback_depth_atr"]) > thresholds["maximum_pullback_depth_atr"]
        or pullback_depth_impulse_fraction > thresholds["maximum_pullback_depth_impulse_fraction"]
    )
    structure_damage_flag = str(row["pullback_type"]) in _REJECT_TYPES or too_deep_flag
    confirmation_delay_candles = float(row.get("liquidity_event_age_bars", 0.0) or 0.0)
    confirmation_delay_minutes = confirmation_delay_candles * 60.0
    stale_confirmation_flag = confirmation_delay_candles > thresholds["max_confirmation_delay_candles"]
    late_confirmation_flag = (
        confirmation_delay_candles > thresholds["max_late_confirmation_candles"]
        or (stale_confirmation_flag and float(row["pullback_quality_score"]) < 0.60)
    )

    support_hold_flag = not structure_damage_flag and float(row["refined_stop_distance"]) >= max(float(row["tick_size_estimate"]) * 4.0, 0.0)
    breakout_retest_hold_flag = (
        str(row["pullback_type"]) != "BREAKOUT_RETEST_PULLBACK"
        or (support_hold_flag and not too_deep_flag)
    )
    ema_context_intact = (
        float(row.get("level_distance_atr", 0.0) or 0.0) <= 1.0
        and str(row["pullback_type"]) not in {"STRUCTURE_BREAK_DIP", "EXHAUSTION_DIP"}
    )
    vwap_context_intact = float(row["pullback_quality_score"]) >= 0.50
    higher_low_intact = str(row["pullback_type"]) not in {"STRUCTURE_BREAK_DIP"} and not too_deep_flag
    pullback_volume_dryup = float(row["pullback_quality_score"]) >= 0.45 and float(row["pullback_depth_atr"]) <= 1.6
    confirmation_volume_return = float(row["pullback_quality_score"]) >= 0.65

    structure_validity_components = [
        support_hold_flag,
        breakout_retest_hold_flag,
        ema_context_intact,
        vwap_context_intact,
        higher_low_intact,
        pullback_volume_dryup,
        confirmation_volume_return,
    ]
    structure_validity_score = sum(1.0 for flag in structure_validity_components if flag) / len(structure_validity_components)

    survives_low_cost_prefilter = bool(row["survives_low_cost"])
    survives_normal_cost_prefilter = bool(row["survives_normal_cost"])
    require_low_cost_prefilter = bool(round(float(thresholds.get("require_low_cost_prefilter", 1.0))))
    require_normal_cost_prefilter = bool(round(float(thresholds.get("require_normal_cost_prefilter", 1.0))))
    cost_prefilter_pass = (
        (survives_low_cost_prefilter or not require_low_cost_prefilter)
        and (survives_normal_cost_prefilter or not require_normal_cost_prefilter)
        and float(row["net_reward_to_cost_ratio"]) >= thresholds["minimum_net_reward_to_cost_ratio"]
        and float(row["expected_cost_r"]) <= thresholds["maximum_expected_cost_r"]
    )

    score = 100.0
    reject_reasons: list[str] = []

    def penalize(flag: bool, penalty: float, reason: str) -> None:
        nonlocal score
        if flag:
            score -= penalty
            reject_reasons.append(reason)

    penalize(float(row["refined_stop_atr_fraction"]) < thresholds["minimum_refined_stop_atr_fraction"], 20.0, "stop_atr_too_small")
    penalize(float(row["refined_stop_cost_multiple"]) < thresholds["minimum_refined_stop_cost_multiple"], 18.0, "stop_cost_multiple_too_small")
    penalize(float(row["refined_stop_distance"]) < (float(row["recent_candle_noise"]) * thresholds["minimum_noise_multiple"]), 12.0, "recent_noise_too_large")
    penalize(float(row["refined_stop_distance"]) < (float(row["local_wick_noise"]) * thresholds["minimum_wick_multiple"]), 14.0, "wick_noise_too_large")
    penalize(bool(row["tiny_stop_flag"]), 18.0, "tiny_stop_flag")
    penalize(bool(row["unrealistic_stop_flag"]), 18.0, "unrealistic_stop_flag")
    penalize(bool(row["noise_stop_flag"]), 14.0, "noise_stop_flag")
    penalize(bool(row["cost_dominated_stop_flag"]), 22.0, "cost_dominated_stop_flag")
    penalize(too_deep_flag, 20.0, "too_deep_pullback")
    penalize(structure_damage_flag, 25.0, "structure_damage")
    penalize(stale_confirmation_flag, 10.0, "stale_confirmation")
    penalize(late_confirmation_flag, 16.0, "late_confirmation")
    penalize(not cost_prefilter_pass, 22.0, "fails_cost_prefilter")
    penalize(structure_validity_score < thresholds["minimum_structure_validity_score"], 18.0, "weak_structure_validity")

    score = max(0.0, min(100.0, score))

    hard_reject = (
        structure_damage_flag
        or late_confirmation_flag
        or bool(row["unrealistic_stop_flag"]) and bool(row["cost_dominated_stop_flag"])
        or float(row["refined_stop_cost_multiple"]) < 1.0
        or str(row["pullback_type"]) in _REJECT_TYPES
    )
    if hard_reject:
        grade = "REJECT"
    elif score >= 85.0 and cost_prefilter_pass:
        grade = "A"
    elif score >= 72.0 and cost_prefilter_pass:
        grade = "B"
    elif score >= 58.0:
        grade = "C"
    elif score >= 42.0:
        grade = "D"
    else:
        grade = "REJECT"

    tightened_candidate_pass = grade in {"A", "B", "C"} and not hard_reject
    return {
        "pullback_depth": pullback_depth,
        "expected_cost_R": float(row["expected_cost_r"]),
        "pullback_depth_impulse_fraction": pullback_depth_impulse_fraction,
        "too_deep_flag": too_deep_flag,
        "structure_damage_flag": structure_damage_flag,
        "confirmation_delay_candles": confirmation_delay_candles,
        "confirmation_delay_minutes": confirmation_delay_minutes,
        "stale_confirmation_flag": stale_confirmation_flag,
        "late_confirmation_flag": late_confirmation_flag,
        "survives_low_cost_prefilter": survives_low_cost_prefilter,
        "survives_normal_cost_prefilter": survives_normal_cost_prefilter,
        "cost_prefilter_pass": cost_prefilter_pass,
        "support_hold_flag": support_hold_flag,
        "breakout_retest_hold_flag": breakout_retest_hold_flag,
        "ema_context_intact": ema_context_intact,
        "vwap_context_intact": vwap_context_intact,
        "higher_low_intact": higher_low_intact,
        "pullback_volume_dryup": pullback_volume_dryup,
        "confirmation_volume_return": confirmation_volume_return,
        "structure_validity_score": structure_validity_score,
        "tightened_pullback_grade": grade,
        "tightened_pullback_score": score,
        "tightened_reject_reasons": "|".join(reject_reasons),
        "tightened_candidate_pass": tightened_candidate_pass,
    }


def _build_tightened_rows(config: DetectorTighteningConfig, thresholds: dict[str, float]) -> list[dict[str, Any]]:
    rows = _load_refinement_rows(config.refinement_root)
    setup_lookup = _load_setup_lookup(config.review_root)
    tightened_rows: list[dict[str, Any]] = []
    for row in rows:
        setup = setup_lookup.get((str(row["window"]), str(row["symbol"]), str(row["side"]), str(row["entry_time"])), {})
        enriched = dict(row)
        enriched["pattern"] = str(setup.get("pattern") or "")
        enriched["level_distance_atr"] = float(setup.get("level_distance_atr", 0.0) or 0.0)
        enriched["liquidity_event_age_bars"] = float(setup.get("liquidity_event_age_bars", 0.0) or 0.0)
        enriched["macd_confirmation_flag"] = _to_bool(setup.get("macd_confirmation_flag"))
        enriched["macd_warning_flag"] = _to_bool(setup.get("macd_warning_flag"))
        enriched["bb_compression"] = _to_bool(setup.get("bb_compression"))
        enriched["bb_expansion"] = _to_bool(setup.get("bb_expansion"))
        enriched["bb_warning_flag"] = _to_bool(setup.get("bb_warning_flag"))
        enriched.update(grade_tightened_candidate(enriched, thresholds))
        tightened_rows.append(enriched)
    return tightened_rows


def _apply_profile(rows: list[dict[str, Any]], thresholds: dict[str, float], *, profile_name: str) -> list[dict[str, Any]]:
    profiled_rows: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        enriched["profile_name"] = profile_name
        enriched.update(grade_tightened_candidate(enriched, thresholds))
        profiled_rows.append(enriched)
    return profiled_rows


def _report_rates(rows: list[dict[str, Any]]) -> dict[str, float]:
    total = len(rows) or 1
    return {
        "candidate_count": len(rows),
        "tiny_stop_rate": sum(1 for row in rows if bool(row["tiny_stop_flag"])) / total,
        "unrealistic_stop_rate": sum(1 for row in rows if bool(row["unrealistic_stop_flag"])) / total,
        "cost_dominated_stop_rate": sum(1 for row in rows if bool(row["cost_dominated_stop_flag"])) / total,
        "normal_cost_survival_rate": sum(1 for row in rows if bool(row["survives_normal_cost"])) / total,
        "cost_aware_candidate_rate": sum(1 for row in rows if bool(row["cost_aware_pullback_candidate"])) / total,
        "median_improved_r_delta": _safe_median([float(row["improved_r_delta"]) for row in rows]) or 0.0,
        "missed_winner_risk_rate": sum(1 for row in rows if bool(row["missed_due_to_waiting"]) and float(row["trade_r_multiple"]) > 0.0) / total,
    }


def _build_old_vs_tightened_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    old_rates = _report_rates(rows)
    tightened = [row for row in rows if bool(row["tightened_candidate_pass"])]
    tightened_rates = _report_rates(tightened)
    return {
        "old": old_rates,
        "tightened": tightened_rates,
        "candidate_reduction_pct": (
            1.0 - (tightened_rates["candidate_count"] / old_rates["candidate_count"])
            if old_rates["candidate_count"] > 0
            else 0.0
        ),
        "tiny_stop_reduction": old_rates["tiny_stop_rate"] - tightened_rates["tiny_stop_rate"],
        "unrealistic_stop_reduction": old_rates["unrealistic_stop_rate"] - tightened_rates["unrealistic_stop_rate"],
        "cost_dominated_reduction": old_rates["cost_dominated_stop_rate"] - tightened_rates["cost_dominated_stop_rate"],
        "normal_cost_survival_change": tightened_rates["normal_cost_survival_rate"] - old_rates["normal_cost_survival_rate"],
        "cost_aware_candidate_rate_change": tightened_rates["cost_aware_candidate_rate"] - old_rates["cost_aware_candidate_rate"],
        "missed_winner_risk_change": tightened_rates["missed_winner_risk_rate"] - old_rates["missed_winner_risk_rate"],
    }


def _build_quality_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grades = Counter(str(row["tightened_pullback_grade"]) for row in rows)
    pass_rows = [row for row in rows if bool(row["tightened_candidate_pass"])]
    return {
        "grade_distribution": dict(grades),
        "pass_count": len(pass_rows),
        "pass_rate": (len(pass_rows) / len(rows)) if rows else 0.0,
        "pass_median_score": _safe_median([float(row["tightened_pullback_score"]) for row in pass_rows]),
        "pass_median_improved_r_delta": _safe_median([float(row["improved_r_delta"]) for row in pass_rows]),
    }


def _build_cost_survival_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    pass_rows = [row for row in rows if bool(row["tightened_candidate_pass"])]
    total = len(rows) or 1
    return {
        "all_rows": {
            "survives_low_cost_rate": sum(1 for row in rows if bool(row["survives_low_cost_prefilter"])) / total,
            "survives_normal_cost_rate": sum(1 for row in rows if bool(row["survives_normal_cost_prefilter"])) / total,
            "cost_prefilter_pass_rate": sum(1 for row in rows if bool(row["cost_prefilter_pass"])) / total,
        },
        "tightened_pass_rows": {
            "count": len(pass_rows),
            "survives_low_cost_rate": sum(1 for row in pass_rows if bool(row["survives_low_cost_prefilter"])) / len(pass_rows) if pass_rows else 0.0,
            "survives_normal_cost_rate": sum(1 for row in pass_rows if bool(row["survives_normal_cost_prefilter"])) / len(pass_rows) if pass_rows else 0.0,
            "cost_prefilter_pass_rate": sum(1 for row in pass_rows if bool(row["cost_prefilter_pass"])) / len(pass_rows) if pass_rows else 0.0,
        },
    }


def _build_tightened_missed_winner_risk_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rejected = [row for row in rows if not bool(row["tightened_candidate_pass"])]
    missed_winners = [row for row in rejected if bool(row["missed_due_to_waiting"]) and float(row["trade_r_multiple"]) > 0.0]
    return {
        "rejected_candidate_count": len(rejected),
        "rejected_missed_winner_count": len(missed_winners),
        "tightened_missed_winner_risk_rate": (len(missed_winners) / len(rows)) if rows else 0.0,
        "average_missed_winner_r": _safe_mean([float(row["trade_r_multiple"]) for row in missed_winners]),
        "median_missed_winner_r": _safe_median([float(row["trade_r_multiple"]) for row in missed_winners]),
        "reject_reason_distribution_for_missed_winners": dict(
            Counter(reason for row in missed_winners for reason in str(row["tightened_reject_reasons"]).split("|") if reason)
        ),
    }


def _build_reject_reason_distribution(rows: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter[str] = Counter()
    for row in rows:
        for reason in str(row["tightened_reject_reasons"]).split("|"):
            if reason:
                counter[reason] += 1
    return dict(counter)


def _profile_summary_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    passed = [row for row in rows if bool(row["tightened_candidate_pass"])]
    rejected = [row for row in rows if not bool(row["tightened_candidate_pass"])]
    total = len(rows) or 1
    passed_total = len(passed) or 1
    improved_values = [float(row["improved_r_delta"]) for row in passed]
    rejected_missed_winners = [
        row
        for row in rejected
        if bool(row["missed_due_to_waiting"]) and float(row["trade_r_multiple"]) > 0.0
    ]
    return {
        "candidate_count": len(passed),
        "candidate_pass_rate": len(passed) / total,
        "tiny_stop_rate": sum(1 for row in passed if bool(row["tiny_stop_flag"])) / passed_total if passed else 0.0,
        "unrealistic_stop_rate": sum(1 for row in passed if bool(row["unrealistic_stop_flag"])) / passed_total if passed else 0.0,
        "noise_stop_rate": sum(1 for row in passed if bool(row["noise_stop_flag"])) / passed_total if passed else 0.0,
        "cost_dominated_stop_rate": sum(1 for row in passed if bool(row["cost_dominated_stop_flag"])) / passed_total if passed else 0.0,
        "cost_aware_candidate_rate": sum(1 for row in passed if bool(row["cost_aware_pullback_candidate"])) / passed_total if passed else 0.0,
        "low_cost_survival_rate": sum(1 for row in passed if bool(row["survives_low_cost"])) / passed_total if passed else 0.0,
        "normal_cost_survival_rate": sum(1 for row in passed if bool(row["survives_normal_cost"])) / passed_total if passed else 0.0,
        "high_cost_survival_rate": sum(1 for row in passed if bool(row["survives_high_cost"])) / passed_total if passed else 0.0,
        "median_improved_r_delta": _safe_median(improved_values),
        "trimmed_mean_improved_r_delta": _trimmed_mean(improved_values),
        "winsorized_mean_improved_r_delta": _winsorized_mean(improved_values),
        "median_refined_stop_atr_fraction": _safe_median([float(row["refined_stop_atr_fraction"]) for row in passed]),
        "median_refined_stop_cost_multiple": _safe_median([float(row["refined_stop_cost_multiple"]) for row in passed]),
        "missed_winner_risk_estimate": (len(rejected_missed_winners) / total) if rows else 0.0,
        "reject_reason_distribution": _build_reject_reason_distribution(rejected),
    }


def _stage1_metrics_from_refinement_summary(refinement_summary: dict[str, Any]) -> dict[str, Any]:
    robust = dict(refinement_summary.get("robust_r_summary", {}).get("combined", {}) or {})
    outliers = dict(refinement_summary.get("tiny_stop_outlier_summary", {}).get("combined", {}) or {})
    net_costs = dict(refinement_summary.get("net_r_after_costs_summary", {}) or {})
    missed = dict(refinement_summary.get("missed_winner_penalty_summary", {}).get("combined", {}) or {})
    return {
        "candidate_count": int(robust.get("count", 0)),
        "candidate_pass_rate": 1.0,
        "tiny_stop_rate": float(outliers.get("tiny_stop_flag_rate", 0.0)),
        "unrealistic_stop_rate": float(outliers.get("unrealistic_stop_flag_rate", 0.0)),
        "noise_stop_rate": float(outliers.get("noise_stop_flag_rate", 0.0)),
        "cost_dominated_stop_rate": float(outliers.get("cost_dominated_stop_flag_rate", 0.0)),
        "cost_aware_candidate_rate": float(net_costs.get("combined_cost_aware_candidate_rate", 0.0)),
        "low_cost_survival_rate": None,
        "normal_cost_survival_rate": float(net_costs.get("combined_normal_survival_rate", 0.0)),
        "high_cost_survival_rate": None,
        "median_improved_r_delta": _safe_float_value(robust.get("median_improved_r_delta"), default=0.0),
        "trimmed_mean_improved_r_delta": _safe_float_value(robust.get("trimmed_mean_improved_r_delta"), default=0.0),
        "winsorized_mean_improved_r_delta": _safe_float_value(robust.get("winsorized_mean_improved_r_delta"), default=0.0),
        "median_refined_stop_atr_fraction": _safe_float_value(outliers.get("median_refined_stop_atr_fraction"), default=0.0),
        "median_refined_stop_cost_multiple": _safe_float_value(outliers.get("median_refined_stop_cost_multiple"), default=0.0),
        "missed_winner_risk_estimate": _safe_float_value(missed.get("missed_winner_rate"), default=0.0),
        "reject_reason_distribution": dict(missed.get("miss_reason_distribution", {}) or {}),
    }


def _write_csv(path: Path, source_rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not source_rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(source_rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(source_rows)


def write_threshold_calibration(config: ThresholdCalibrationConfig) -> dict[str, Path]:
    base_rows = _build_tightened_rows(
        DetectorTighteningConfig(
            review_root=config.review_root,
            refinement_root=config.refinement_root,
            output_root=config.output_root,
        ),
        build_detector_tightening_thresholds(),
    )
    profiles = build_threshold_profiles()
    profile_rows: dict[str, list[dict[str, Any]]] = {
        profile_name: _apply_profile(base_rows, thresholds, profile_name=profile_name)
        for profile_name, thresholds in profiles.items()
    }
    profile_metrics = {
        profile_name: {
            "profile_name": profile_name,
            "thresholds": thresholds,
            **_profile_summary_rows(rows),
        }
        for profile_name, (thresholds, rows) in (
            (profile_name, (profiles[profile_name], profile_rows[profile_name]))
            for profile_name in profiles
        )
    }

    stage1_summary = {}
    stage1_path = config.refinement_root / "refinement_summary.json"
    if stage1_path.exists():
        stage1_summary = _read_json(stage1_path)
    stage2_summary = {}
    stage2_path = config.stage2_root / "detector_tightening_summary.json"
    if stage2_path.exists():
        stage2_summary = _read_json(stage2_path)
    stage1_metrics = _stage1_metrics_from_refinement_summary(stage1_summary)
    stage2_metrics = dict(stage2_summary.get("old_vs_tightened_detector", {}).get("tightened", {}) or {})

    balanced_metrics = profile_metrics["balanced"]
    balanced_is_viable = (
        balanced_metrics["candidate_count"] >= max(30, int(stage2_metrics.get("candidate_count", 14)) * 3)
        and balanced_metrics["tiny_stop_rate"] <= stage1_metrics["tiny_stop_rate"] * 0.45
        and balanced_metrics["cost_dominated_stop_rate"] <= stage1_metrics["cost_dominated_stop_rate"] * 0.45
        and balanced_metrics["normal_cost_survival_rate"] >= 0.70
        and balanced_metrics["cost_aware_candidate_rate"] >= max(0.15, stage1_metrics["cost_aware_candidate_rate"] * 4.0)
        and balanced_metrics["missed_winner_risk_estimate"] <= 0.22
    )

    recommended_profile_name = "balanced" if balanced_is_viable else max(
        profile_metrics,
        key=lambda name: (
            min(profile_metrics[name]["candidate_count"], 120) * 0.5
            + (1.0 - profile_metrics[name]["cost_dominated_stop_rate"]) * 45.0
            + profile_metrics[name]["normal_cost_survival_rate"] * 35.0
            + profile_metrics[name]["cost_aware_candidate_rate"] * 20.0
            - abs(profile_metrics[name]["candidate_count"] - 60) * 0.15
        ),
    )
    recommended_metrics = profile_metrics[recommended_profile_name]

    if (
        recommended_profile_name == "balanced"
        and balanced_is_viable
        and recommended_metrics["candidate_count"] >= 40
        and recommended_metrics["candidate_pass_rate"] >= 0.04
    ):
        classification = "eligible_for_second_fast_review"
    elif recommended_metrics["candidate_count"] >= 20 and recommended_metrics["normal_cost_survival_rate"] >= 0.70:
        classification = "continue_research"
    else:
        classification = "needs_more_detector_tightening"

    comparison_rows = []
    for profile_name in ("strict", "balanced", "relaxed", "cost_first", "noise_first"):
        metrics = profile_metrics[profile_name]
        comparison_rows.append(
            {
                "profile_name": profile_name,
                "candidate_count": metrics["candidate_count"],
                "candidate_pass_rate": metrics["candidate_pass_rate"],
                "tiny_stop_rate": metrics["tiny_stop_rate"],
                "unrealistic_stop_rate": metrics["unrealistic_stop_rate"],
                "noise_stop_rate": metrics["noise_stop_rate"],
                "cost_dominated_stop_rate": metrics["cost_dominated_stop_rate"],
                "cost_aware_candidate_rate": metrics["cost_aware_candidate_rate"],
                "low_cost_survival_rate": metrics["low_cost_survival_rate"],
                "normal_cost_survival_rate": metrics["normal_cost_survival_rate"],
                "high_cost_survival_rate": metrics["high_cost_survival_rate"],
                "median_improved_r_delta": metrics["median_improved_r_delta"],
                "trimmed_mean_improved_r_delta": metrics["trimmed_mean_improved_r_delta"],
                "winsorized_mean_improved_r_delta": metrics["winsorized_mean_improved_r_delta"],
                "median_refined_stop_atr_fraction": metrics["median_refined_stop_atr_fraction"],
                "median_refined_stop_cost_multiple": metrics["median_refined_stop_cost_multiple"],
                "missed_winner_risk_estimate": metrics["missed_winner_risk_estimate"],
            }
        )

    output_root = config.output_root
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    _write_json(
        diagnostics_root / "profile_comparison.json",
        {
            "profiles": profile_metrics,
            "recommended_profile": recommended_profile_name,
        },
    )
    _write_csv(diagnostics_root / "profile_comparison.csv", comparison_rows)
    _write_csv(
        diagnostics_root / "calibrated_pullback_candidates.csv",
        [row for row in profile_rows[recommended_profile_name] if bool(row["tightened_candidate_pass"])],
    )
    _write_json(
        diagnostics_root / "calibrated_reject_reason_distribution.json",
        dict(recommended_metrics["reject_reason_distribution"]),
    )
    _write_json(
        diagnostics_root / "stage1_vs_stage2_vs_stage3_comparison.json",
        {
            "stage1": stage1_metrics,
            "stage2_strict": stage2_metrics,
            "stage3_recommended": {
                "profile_name": recommended_profile_name,
                **recommended_metrics,
            },
        },
    )

    summary = {
        "threshold_calibration_name": "Structural Compounding Lab Detector Tightening 002",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "real_money_allowed": False,
        "classification": classification,
        "recommended_profile": recommended_profile_name,
        "balanced_profile_viable": balanced_is_viable,
        "review_scope": {
            "full_history_started": False,
            "stress_windows_started": False,
            "monte_carlo_started": False,
            "live_behavior_changed": False,
            "paper_behavior_changed": False,
            "strategy_behavior_changed": False,
            "allocator_behavior_changed": False,
            "risk_behavior_changed": False,
            "sizing_behavior_changed": False,
            "entry_behavior_changed": False,
            "exit_behavior_changed": False,
            "config_settings_changed": False,
            "macd_bollinger_hard_gates_enabled": False,
            "pullback_buying_runtime_enabled": False,
            "replay_started": False,
        },
        "profiles": profile_metrics,
        "stage1_vs_stage2_vs_stage3": {
            "stage1": stage1_metrics,
            "stage2_strict": stage2_metrics,
            "stage3_recommended": {
                "profile_name": recommended_profile_name,
                **recommended_metrics,
            },
        },
        "soft_evidence_only": {"macd_bollinger": True},
    }
    recommendation = {
        "classification": classification,
        "recommended_profile": recommended_profile_name,
        "balanced_profile_viable": balanced_is_viable,
        "notes": [
            "threshold calibration varied stop, cost, noise, depth, and confirmation gates only",
            "no new indicators or strategy rules were added",
            "dashboard/runtime/live-paper behavior remains unchanged",
        ],
        "forbidden": [
            "no_live_runtime_changes",
            "no_paper_runtime_changes",
            "no_stress_windows",
            "no_full_history_replay",
            "no_real_money_enablement",
            "no_macd_bollinger_hard_gates",
        ],
    }

    _write_json(
        output_root / "status.json",
        {
            "state": "complete",
            "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
            "classification": classification,
            "recommended_profile": recommended_profile_name,
            "research_only": True,
            "real_money_allowed": False,
        },
    )
    _write_json(output_root / "threshold_calibration_summary.json", summary)
    _write_markdown(
        output_root / "threshold_calibration_report.md",
        "\n".join(
            [
                "# Detector Tightening 002",
                "",
                f"Classification: `{classification}`",
                f"Recommended profile: `{recommended_profile_name}`",
                "",
                "| Profile | Candidates | Pass rate | Tiny-stop | Unrealistic | Cost-dominated | Cost-aware | Normal-cost survival | Missed-winner risk |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
                *[
                    f"| {row['profile_name']} | {row['candidate_count']} | {row['candidate_pass_rate']:.3%} | {row['tiny_stop_rate']:.3%} | {row['unrealistic_stop_rate']:.3%} | {row['cost_dominated_stop_rate']:.3%} | {row['cost_aware_candidate_rate']:.3%} | {row['normal_cost_survival_rate']:.3%} | {row['missed_winner_risk_estimate']:.3%} |"
                    for row in comparison_rows
                ],
                "",
                "Research-only. No replay, no live change, no paper change.",
            ]
        )
        + "\n",
    )
    _write_json(reports_root / "next_research_recommendation.json", recommendation)
    _write_markdown(
        reports_root / "next_research_recommendation.md",
        "\n".join(
            [
                "# Next Research Recommendation",
                "",
                f"Classification: `{classification}`",
                f"Recommended profile: `{recommended_profile_name}`",
                "",
                "Keep the detector calibration research-only and use the recommended profile only as the next passive evidence lens.",
            ]
        )
        + "\n",
    )

    return {
        "summary": output_root / "threshold_calibration_summary.json",
        "report": output_root / "threshold_calibration_report.md",
    }


def write_detector_tightening(config: DetectorTighteningConfig) -> dict[str, Path]:
    thresholds = build_detector_tightening_thresholds()
    rows = _build_tightened_rows(config, thresholds)
    diagnostics_root = config.output_root / "diagnostics"
    reports_root = config.output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    tightened_rows = [row for row in rows if bool(row["tightened_candidate_pass"])]
    old_vs_tightened = _build_old_vs_tightened_report(rows)
    quality_report = _build_quality_report(rows)
    cost_survival_report = _build_cost_survival_report(rows)
    missed_winner_risk_report = _build_tightened_missed_winner_risk_report(rows)
    reject_reason_distribution = _build_reject_reason_distribution(rows)

    if (
        old_vs_tightened["tiny_stop_reduction"] >= 0.20
        and old_vs_tightened["unrealistic_stop_reduction"] >= 0.20
        and old_vs_tightened["cost_dominated_reduction"] >= 0.25
        and old_vs_tightened["normal_cost_survival_change"] >= 0.05
        and old_vs_tightened["cost_aware_candidate_rate_change"] >= 0.05
        and old_vs_tightened["tightened"]["candidate_count"] >= max(25, int(old_vs_tightened["old"]["candidate_count"] * 0.08))
        and missed_winner_risk_report["tightened_missed_winner_risk_rate"] <= 0.08
    ):
        classification = "eligible_for_second_fast_review"
    elif (
        old_vs_tightened["tiny_stop_reduction"] > 0.0
        or old_vs_tightened["unrealistic_stop_reduction"] > 0.0
        or old_vs_tightened["cost_dominated_reduction"] > 0.0
    ):
        classification = "needs_more_detector_tightening"
    else:
        classification = "continue_research"

    summary = {
        "detector_tightening_name": "Structural Compounding Lab Detector Tightening 001",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "real_money_allowed": False,
        "classification": classification,
        "allowed_classifications": list(_ALLOWED_CLASSIFICATIONS),
        "review_scope": {
            "full_history_started": False,
            "stress_windows_started": False,
            "monte_carlo_started": False,
            "live_behavior_changed": False,
            "paper_behavior_changed": False,
            "config_settings_changed": False,
            "macd_bollinger_hard_gates_enabled": False,
            "pullback_buying_runtime_enabled": False,
        },
        "research_thresholds": thresholds,
        "old_vs_tightened_detector": old_vs_tightened,
        "tightened_pullback_quality_report": quality_report,
        "tightened_cost_survival_report": cost_survival_report,
        "tightened_missed_winner_risk_report": missed_winner_risk_report,
        "reject_reason_distribution": reject_reason_distribution,
        "soft_evidence_only": {
            "macd_bollinger": True,
        },
    }
    recommendation = {
        "classification": classification,
        "recommendation": "keep detector tightening research-only and evaluate whether a second fast review is justified only after tiny-stop and cost-dominated rates fall materially",
        "forbidden": [
            "no_live_runtime_changes",
            "no_paper_runtime_changes",
            "no_stress_windows",
            "no_real_money_enablement",
            "no_macd_bollinger_hard_gates",
        ],
    }

    _write_json(config.output_root / "status.json", {
        "state": "complete",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "classification": classification,
        "research_only": True,
        "real_money_allowed": False,
    })
    _write_json(config.output_root / "detector_tightening_summary.json", summary)
    _write_markdown(
        config.output_root / "detector_tightening_report.md",
        "\n".join(
            [
                "# Detector Tightening 001",
                "",
                f"Classification: `{classification}`",
                "",
                f"- old candidate count: `{old_vs_tightened['old']['candidate_count']}`",
                f"- tightened candidate count: `{old_vs_tightened['tightened']['candidate_count']}`",
                f"- tiny-stop reduction: `{old_vs_tightened['tiny_stop_reduction']:.3%}`",
                f"- unrealistic-stop reduction: `{old_vs_tightened['unrealistic_stop_reduction']:.3%}`",
                f"- cost-dominated reduction: `{old_vs_tightened['cost_dominated_reduction']:.3%}`",
                f"- normal-cost survival change: `{old_vs_tightened['normal_cost_survival_change']:.3%}`",
                f"- cost-aware candidate rate change: `{old_vs_tightened['cost_aware_candidate_rate_change']:.3%}`",
                "",
                "Research-only. No runtime behavior changed.",
            ]
        )
        + "\n",
    )

    _write_csv(diagnostics_root / "tightened_pullback_candidates.csv", tightened_rows)
    _write_json(diagnostics_root / "tightened_pullback_quality_report.json", quality_report)
    _write_json(diagnostics_root / "old_vs_tightened_detector_report.json", old_vs_tightened)
    _write_json(diagnostics_root / "tightened_cost_survival_report.json", cost_survival_report)
    _write_json(diagnostics_root / "tightened_missed_winner_risk_report.json", missed_winner_risk_report)
    _write_json(diagnostics_root / "reject_reason_distribution.json", reject_reason_distribution)
    _write_json(reports_root / "next_research_recommendation.json", recommendation)
    _write_markdown(
        reports_root / "next_research_recommendation.md",
        "\n".join(
            [
                "# Next Research Recommendation",
                "",
                f"Classification: `{classification}`",
                "",
                "Keep detector tightening passive and research-only.",
            ]
        )
        + "\n",
    )
    return {
        "summary": config.output_root / "detector_tightening_summary.json",
        "report": config.output_root / "detector_tightening_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    config = DetectorTighteningConfig(
        review_root=root / "structural_compounding_lab" / "output" / "evidence_review_001",
        refinement_root=root / "structural_compounding_lab" / "output" / "evidence_refinement_001",
        output_root=root / "structural_compounding_lab" / "output" / "detector_tightening_001",
    )
    write_detector_tightening(config)
    print(f"Detector tightening artifacts written to: {config.output_root}")


if __name__ == "__main__":
    main()
