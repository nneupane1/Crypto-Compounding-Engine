from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any


_RESEARCH_WINDOWS = ("smoke", "diagnostic_fast")
_HOLDOUT_WINDOW = "holdout_recent_preview"
_ALL_WINDOWS = _RESEARCH_WINDOWS + (_HOLDOUT_WINDOW,)
_FINAL_CLASSIFICATIONS = (
    "reject",
    "continue_research",
    "needs_archetype_refinement",
    "eligible_for_second_fast_review",
)
_ARCHETYPES = (
    "MICRO_PULLBACK_MOMENTUM",
    "BREAKOUT_RETEST_PULLBACK",
    "EMA_VWAP_RECLAIM_PULLBACK",
    "HEALTHY_CONTINUATION_PULLBACK",
    "LIQUIDITY_SWEEP_RECLAIM",
    "INSIDE_BAR_CONTINUATION",
    "FAILED_BREAKDOWN_REVERSAL",
    "STRUCTURE_BREAK_DIP",
)
_REJECTION_TYPES = {"STRUCTURE_BREAK_DIP", "EXHAUSTION_DIP", "NO_VALID_PULLBACK", "NO_PULLBACK_SIGNAL"}
_QUALITY_ORDER = {"A": 5, "B": 4, "C": 3, "D": 2, "REJECT": 1}


@dataclass(frozen=True)
class PullbackArchetypeRedesignConfig:
    review_root: Path
    refinement_root: Path
    output_root: Path


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


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
    return _safe_mean(ordered[trim_count : len(ordered) - trim_count])


def _winsorized_mean(values: list[float], winsor_fraction: float = 0.1) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    edge_count = int(len(ordered) * winsor_fraction)
    if edge_count <= 0 or edge_count * 2 >= len(ordered):
        return _safe_mean(ordered)
    low = ordered[edge_count]
    high = ordered[-edge_count - 1]
    return _safe_mean([min(max(value, low), high) for value in ordered])


def _fmt(value: float | None, spec: str = ".3f") -> str:
    if value is None:
        return "n/a"
    return format(value, spec)


def _to_bool(value: Any) -> bool:
    return str(value).lower() == "true"


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _load_refinement_rows(refinement_root: Path) -> list[dict[str, Any]]:
    path = refinement_root / "diagnostics" / "original_vs_pullback_entry_cost_aware.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
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
                row[key] = _safe_float(row[key])
        for key in bool_fields:
            if key in row:
                row[key] = _to_bool(row[key])
    return rows


def _load_setup_lookup(review_root: Path) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    lookup: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for window in _ALL_WINDOWS:
        path = review_root / window / "setup_log.csv"
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                key = (
                    window,
                    str(row.get("symbol", "")).upper(),
                    str(row.get("side", "")).lower(),
                    str(row.get("timestamp", "")),
                )
                lookup[key] = row
    return lookup


def _structure_validity_score(row: dict[str, Any]) -> float:
    quality = _safe_float(row.get("pullback_quality_score"))
    depth = _safe_float(row.get("pullback_depth_atr"))
    delay = _safe_float(row.get("liquidity_event_age_bars"))
    level_distance = _safe_float(row.get("level_distance_atr"))
    pullback_type = str(row.get("pullback_type", ""))
    pattern = str(row.get("pattern", ""))

    checks = [
        bool(row.get("htf_aligned", False)),
        quality >= 0.50,
        delay <= 6.0,
        level_distance <= 0.90 or pattern in {"retest_after_breakout", "retest_after_breakdown"},
        depth <= 1.75 or pullback_type == "DEEP_VALUE_PULLBACK",
        not bool(row.get("unrealistic_stop_flag", False)),
        not bool(row.get("cost_dominated_stop_flag", False)),
        pullback_type not in _REJECTION_TYPES,
    ]
    return sum(1.0 for check in checks if check) / len(checks)


def _join_context_rows(config: PullbackArchetypeRedesignConfig) -> list[dict[str, Any]]:
    rows = _load_refinement_rows(config.refinement_root)
    setup_lookup = _load_setup_lookup(config.review_root)
    enriched_rows: list[dict[str, Any]] = []
    for row in rows:
        setup = setup_lookup.get(
            (
                str(row.get("window", "")),
                str(row.get("symbol", "")).upper(),
                str(row.get("side", "")).lower(),
                str(row.get("entry_time", "")),
            ),
            {},
        )
        enriched = dict(row)
        enriched["pattern"] = str(setup.get("pattern", "") or "")
        enriched["liquidity_event_type"] = str(setup.get("liquidity_event_type", "") or "")
        enriched["liquidity_event_age_bars"] = _safe_float(setup.get("liquidity_event_age_bars"), default=0.0)
        enriched["level_distance_atr"] = _safe_float(setup.get("level_distance_atr"), default=0.0)
        enriched["htf_aligned"] = _to_bool(setup.get("htf_aligned"))
        enriched["execution_timeframe"] = str(setup.get("execution_timeframe", "") or "")
        enriched["macd_confirmation_flag"] = _to_bool(setup.get("macd_confirmation_flag"))
        enriched["macd_warning_flag"] = _to_bool(setup.get("macd_warning_flag"))
        enriched["bb_compression"] = _to_bool(setup.get("bb_compression"))
        enriched["bb_expansion"] = _to_bool(setup.get("bb_expansion"))
        enriched["bb_warning_flag"] = _to_bool(setup.get("bb_warning_flag"))
        enriched["micro_pullback_detected"] = _to_bool(setup.get("micro_pullback_detected"))
        enriched["runner_eligible_candidate"] = _to_bool(setup.get("runner_eligible_candidate"))
        enriched["add_on_research_candidate"] = _to_bool(setup.get("add_on_research_candidate"))
        enriched["structure_validity_score"] = _structure_validity_score(enriched)
        enriched_rows.append(enriched)
    return enriched_rows


def _grade(score: float, reject: bool) -> str:
    if reject:
        return "REJECT"
    if score >= 80.0:
        return "A"
    if score >= 68.0:
        return "B"
    if score >= 56.0:
        return "C"
    if score >= 45.0:
        return "D"
    return "REJECT"


def _choose_archetype(row: dict[str, Any]) -> tuple[str, list[str]]:
    pullback_type = str(row.get("pullback_type", ""))
    pattern = str(row.get("pattern", ""))
    liquidity = str(row.get("liquidity_event_type", ""))
    personality = str(row.get("personality_label", ""))
    depth = _safe_float(row.get("pullback_depth_atr"))
    quality = _safe_float(row.get("pullback_quality_score"))
    delay = _safe_float(row.get("liquidity_event_age_bars"))
    level_distance = _safe_float(row.get("level_distance_atr"))
    structure_score = _safe_float(row.get("structure_validity_score"))

    reasons: list[str] = []

    if (
        pullback_type == "STRUCTURE_BREAK_DIP"
        or pattern == "structure_breakdown"
        or (pullback_type == "EXHAUSTION_DIP" and quality < 0.45)
        or (structure_score < 0.35 and depth > 1.35)
    ):
        reasons.append("structure_or_context_failed")
        return "STRUCTURE_BREAK_DIP", reasons

    if pullback_type == "BREAKOUT_RETEST_PULLBACK" or pattern == "retest_after_breakout" or liquidity == "retest_after_breakout":
        reasons.append("breakout_retest_signature")
        return "BREAKOUT_RETEST_PULLBACK", reasons

    if pattern == "retest_after_breakdown" or liquidity == "retest_after_breakdown":
        reasons.append("failed_breakdown_reclaim_signature")
        return "FAILED_BREAKDOWN_REVERSAL", reasons

    if liquidity in {"sweep_low", "equal_lows"} and delay <= 4.0 and quality >= 0.45:
        reasons.append("liquidity_sweep_reclaim_signature")
        return "LIQUIDITY_SWEEP_RECLAIM", reasons

    if (bool(row.get("bb_compression")) or personality == "COMPRESSION_BREAKOUT") and depth <= 0.75:
        reasons.append("compression_continuation_signature")
        return "INSIDE_BAR_CONTINUATION", reasons

    if (
        pullback_type == "MICRO_PULLBACK_MOMENTUM"
        or bool(row.get("micro_pullback_detected"))
        or personality == "MOMENTUM_BURST"
    ) and depth <= 0.60 and delay <= 5.0:
        reasons.append("micro_momentum_signature")
        return "MICRO_PULLBACK_MOMENTUM", reasons

    if level_distance <= 0.55 and quality >= 0.50 and pullback_type in {"HEALTHY_CONTINUATION_PULLBACK", "DEEP_VALUE_PULLBACK", "MICRO_PULLBACK_MOMENTUM"}:
        reasons.append("ema_vwap_proxy_reclaim_signature")
        return "EMA_VWAP_RECLAIM_PULLBACK", reasons

    if pullback_type in {"HEALTHY_CONTINUATION_PULLBACK", "DEEP_VALUE_PULLBACK"} and structure_score >= 0.40:
        reasons.append("healthy_continuation_signature")
        return "HEALTHY_CONTINUATION_PULLBACK", reasons

    reasons.append("fallback_structure_reject")
    return "STRUCTURE_BREAK_DIP", reasons


def classify_pullback_archetype(row: dict[str, Any]) -> dict[str, Any]:
    archetype, detection_notes = _choose_archetype(row)
    quality = _safe_float(row.get("pullback_quality_score"))
    depth = _safe_float(row.get("pullback_depth_atr"))
    delay = _safe_float(row.get("liquidity_event_age_bars"))
    stop_atr = _safe_float(row.get("refined_stop_atr_fraction"))
    stop_cost = _safe_float(row.get("refined_stop_cost_multiple"))
    structure_score = _safe_float(row.get("structure_validity_score"))

    reject_reasons: list[str] = []
    score = 38.0 + quality * 24.0 + structure_score * 18.0

    if bool(row.get("survives_normal_cost")):
        score += 8.0
    else:
        score -= 16.0
        reject_reasons.append("fails_normal_cost")
    if bool(row.get("survives_high_cost")):
        score += 4.0
    else:
        score -= 6.0
    if 0.25 <= stop_atr <= 1.30:
        score += 6.0
    elif stop_atr < 0.18:
        score -= 14.0
        reject_reasons.append("stop_atr_too_small")
    elif stop_atr > 2.20:
        score -= 6.0
        reject_reasons.append("stop_atr_too_wide")
    if stop_cost >= 3.0:
        score += 7.0
    elif stop_cost < 1.50:
        score -= 14.0
        reject_reasons.append("stop_cost_multiple_too_small")
    elif stop_cost < 2.0:
        score -= 6.0
        reject_reasons.append("stop_cost_multiple_thin")
    if bool(row.get("tiny_stop_flag")):
        score -= 16.0
        reject_reasons.append("tiny_stop_flag")
    if bool(row.get("unrealistic_stop_flag")):
        score -= 16.0
        reject_reasons.append("unrealistic_stop_flag")
    if bool(row.get("cost_dominated_stop_flag")):
        score -= 18.0
        reject_reasons.append("cost_dominated_flag")
    if bool(row.get("noise_stop_flag")):
        score -= 9.0
        reject_reasons.append("noise_stop_flag")

    if archetype == "MICRO_PULLBACK_MOMENTUM":
        score += 8.0 if depth <= 0.30 else 4.0 if depth <= 0.55 else -10.0
        score += 6.0 if delay <= 3.0 else -6.0
        score += 4.0 if str(row.get("personality_label")) == "MOMENTUM_BURST" else 0.0
    elif archetype == "BREAKOUT_RETEST_PULLBACK":
        score += 10.0 if str(row.get("pattern")) == "retest_after_breakout" else 6.0
        score += 6.0 if _safe_float(row.get("level_distance_atr")) <= 0.50 else 0.0
        score += 4.0 if quality >= 0.60 else -4.0
    elif archetype == "EMA_VWAP_RECLAIM_PULLBACK":
        score += 8.0 if _safe_float(row.get("level_distance_atr")) <= 0.35 else 3.0
        score += 3.0 if not bool(row.get("bb_warning_flag")) else -2.0
        score += 2.0 if not bool(row.get("macd_warning_flag")) else 0.0
    elif archetype == "HEALTHY_CONTINUATION_PULLBACK":
        score += 6.0 if 0.35 <= depth <= 1.20 else 3.0 if depth <= 1.60 else -7.0
        score += 5.0 if bool(row.get("htf_aligned")) else -3.0
        score += 4.0 if bool(row.get("runner_eligible_candidate")) else 0.0
    elif archetype == "LIQUIDITY_SWEEP_RECLAIM":
        score += 10.0 if str(row.get("liquidity_event_type")) in {"sweep_low", "equal_lows"} else 4.0
        score += 5.0 if delay <= 2.0 else -4.0
        score += 3.0 if quality >= 0.55 else 0.0
    elif archetype == "INSIDE_BAR_CONTINUATION":
        score += 10.0 if bool(row.get("bb_compression")) or str(row.get("personality_label")) == "COMPRESSION_BREAKOUT" else 0.0
        score += 4.0 if depth <= 0.45 else -3.0
        score += 4.0 if delay <= 4.0 else -2.0
    elif archetype == "FAILED_BREAKDOWN_REVERSAL":
        score += 10.0 if str(row.get("pattern")) == "retest_after_breakdown" else 6.0
        score += 5.0 if bool(row.get("htf_aligned")) else -5.0
        score -= 3.0
        if depth > 1.20:
            score -= 5.0
            reject_reasons.append("failed_breakdown_too_deep")
    elif archetype == "STRUCTURE_BREAK_DIP":
        score = min(score, 28.0)
        if "structure_or_context_failed" not in reject_reasons:
            reject_reasons.append("structure_or_context_failed")

    score = max(0.0, min(score, 100.0))
    hard_reject = (
        archetype == "STRUCTURE_BREAK_DIP"
        or (bool(row.get("unrealistic_stop_flag")) and bool(row.get("cost_dominated_stop_flag")))
        or (not bool(row.get("survives_normal_cost")) and stop_cost < 1.5)
        or structure_score < 0.30
    )
    grade = _grade(score, hard_reject)
    archetype_pass = (
        grade in {"A", "B", "C"}
        and archetype != "STRUCTURE_BREAK_DIP"
        and bool(row.get("survives_normal_cost"))
        and not bool(row.get("cost_dominated_stop_flag"))
        and not bool(row.get("unrealistic_stop_flag"))
        and structure_score >= 0.45
    )

    missed_winner_risk_flag = bool(row.get("missed_due_to_waiting")) and _safe_float(row.get("trade_r_multiple")) > 0.0
    explanation_parts = [
        f"{archetype} via {', '.join(detection_notes)}",
        f"quality={quality:.2f}",
        f"structure={structure_score:.2f}",
        f"stop_atr={stop_atr:.2f}",
        f"stop_cost={stop_cost:.2f}",
    ]
    if bool(row.get("macd_confirmation_flag")):
        explanation_parts.append("MACD supportive (soft)")
    if bool(row.get("bb_compression")) or bool(row.get("bb_expansion")):
        explanation_parts.append("Bollinger context supportive (soft)")

    return {
        "archetype": archetype,
        "archetype_detected": True,
        "archetype_score": round(score, 4),
        "archetype_grade": grade,
        "entry_candidate_time": str(row.get("entry_time", "")),
        "entry_candidate_price": _safe_float(row.get("refined_entry_price")),
        "stop_price": _safe_float(row.get("refined_stop")),
        "stop_distance": _safe_float(row.get("refined_stop_distance")),
        "stop_atr_fraction": stop_atr,
        "stop_cost_multiple": stop_cost,
        "confirmation_delay": delay,
        "pullback_depth": depth,
        "structure_validity_score": round(structure_score, 4),
        "cost_survival_low": bool(row.get("survives_low_cost")),
        "cost_survival_normal": bool(row.get("survives_normal_cost")),
        "cost_survival_high": bool(row.get("survives_high_cost")),
        "tiny_stop_flag": bool(row.get("tiny_stop_flag")),
        "unrealistic_stop_flag": bool(row.get("unrealistic_stop_flag")),
        "cost_dominated_flag": bool(row.get("cost_dominated_stop_flag")),
        "missed_winner_risk_flag": missed_winner_risk_flag,
        "reject_reasons": "|".join(dict.fromkeys(reject_reasons)),
        "explanation": "; ".join(explanation_parts),
        "archetype_pass": archetype_pass,
        "soft_evidence_only": True,
    }


def _annotate_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        enriched.update(classify_pullback_archetype(enriched))
        enriched["scope"] = "development" if str(enriched.get("window")) in _RESEARCH_WINDOWS else "holdout_recent_preview"
        annotated.append(enriched)
    return annotated


def _best_and_worst_personalities(rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    by_personality: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        label = str(row.get("personality_label", "UNKNOWN"))
        by_personality[label].append(_safe_float(row.get("improved_r_delta")))
    scored = [
        (label, _safe_mean(values) or 0.0, len(values))
        for label, values in by_personality.items()
    ]
    scored.sort(key=lambda item: (item[1], item[2]))
    worst = [label for label, _, _ in scored[:2]]
    best = [label for label, _, _ in scored[-2:]][::-1]
    return best, worst


def _recommendation_for_archetype(summary: dict[str, Any]) -> str:
    if summary["candidate_count"] < 5:
        return "insufficient_sample"
    if (
        summary["pass_count"] >= 3
        and summary["pass_rate"] >= 0.25
        and summary["normal_cost_survival_rate"] >= 0.55
        and summary["cost_dominated_rate"] <= 0.35
        and summary["missed_winner_risk"] <= 0.25
    ):
        return "carry_forward_for_second_fast_review"
    if summary["pass_count"] > 0:
        return "continue_refinement"
    return "reject_or_redefine"


def _summarize_archetype_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    passed = [row for row in rows if bool(row.get("archetype_pass"))]
    score_source = passed if passed else rows
    best_personalities, worst_personalities = _best_and_worst_personalities(score_source if score_source else rows)
    reject_counter = Counter()
    for row in rows:
        for reason in filter(None, str(row.get("reject_reasons", "")).split("|")):
            reject_counter[reason] += 1
    summary = {
        "candidate_count": total,
        "pass_count": len(passed),
        "pass_rate": (len(passed) / total) if total else 0.0,
        "median_improved_R_delta": _safe_median([_safe_float(row.get("improved_r_delta")) for row in score_source]),
        "trimmed_mean_improved_R_delta": _trimmed_mean([_safe_float(row.get("improved_r_delta")) for row in score_source]),
        "winsorized_mean_improved_R_delta": _winsorized_mean([_safe_float(row.get("improved_r_delta")) for row in score_source]),
        "normal_cost_survival_rate": sum(1 for row in rows if bool(row.get("cost_survival_normal"))) / total if total else 0.0,
        "high_cost_survival_rate": sum(1 for row in rows if bool(row.get("cost_survival_high"))) / total if total else 0.0,
        "tiny_stop_rate": sum(1 for row in rows if bool(row.get("tiny_stop_flag"))) / total if total else 0.0,
        "unrealistic_stop_rate": sum(1 for row in rows if bool(row.get("unrealistic_stop_flag"))) / total if total else 0.0,
        "cost_dominated_rate": sum(1 for row in rows if bool(row.get("cost_dominated_flag"))) / total if total else 0.0,
        "missed_winner_risk": sum(1 for row in rows if bool(row.get("missed_winner_risk_flag"))) / total if total else 0.0,
        "average_stop_atr_fraction": _safe_mean([_safe_float(row.get("stop_atr_fraction")) for row in rows]),
        "median_stop_cost_multiple": _safe_median([_safe_float(row.get("stop_cost_multiple")) for row in rows]),
        "best_personality_labels": best_personalities,
        "worst_personality_labels": worst_personalities,
        "reject_reason_distribution": dict(reject_counter),
    }
    summary["recommendation"] = _recommendation_for_archetype(summary)
    return summary


def _build_scope_summaries(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("archetype"))].append(row)
    return {
        archetype: _summarize_archetype_rows(grouped.get(archetype, []))
        for archetype in _ARCHETYPES
    }


def _comparison_rows(scope_name: str, summaries: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for archetype, summary in summaries.items():
        rows.append(
            {
                "scope": scope_name,
                "archetype": archetype,
                "candidate_count": summary["candidate_count"],
                "pass_count": summary["pass_count"],
                "pass_rate": summary["pass_rate"],
                "median_improved_R_delta": summary["median_improved_R_delta"],
                "trimmed_mean_improved_R_delta": summary["trimmed_mean_improved_R_delta"],
                "winsorized_mean_improved_R_delta": summary["winsorized_mean_improved_R_delta"],
                "normal_cost_survival_rate": summary["normal_cost_survival_rate"],
                "high_cost_survival_rate": summary["high_cost_survival_rate"],
                "tiny_stop_rate": summary["tiny_stop_rate"],
                "unrealistic_stop_rate": summary["unrealistic_stop_rate"],
                "cost_dominated_rate": summary["cost_dominated_rate"],
                "missed_winner_risk": summary["missed_winner_risk"],
                "average_stop_atr_fraction": summary["average_stop_atr_fraction"],
                "median_stop_cost_multiple": summary["median_stop_cost_multiple"],
                "recommendation": summary["recommendation"],
            }
        )
    return rows


def _pick_best_and_worst(scope_summaries: dict[str, dict[str, Any]]) -> tuple[str, str]:
    scored = []
    for archetype, summary in scope_summaries.items():
        signal = (
            summary["pass_count"] * 2.0
            + summary["pass_rate"] * 20.0
            + summary["normal_cost_survival_rate"] * 10.0
            - summary["cost_dominated_rate"] * 8.0
            - summary["tiny_stop_rate"] * 6.0
            - summary["missed_winner_risk"] * 6.0
        )
        scored.append((signal, archetype))
    scored.sort()
    return scored[-1][1], scored[0][1]


def _final_classification(
    development: dict[str, dict[str, Any]],
    holdout: dict[str, dict[str, Any]],
) -> str:
    eligible = []
    exploratory = []
    for archetype in _ARCHETYPES:
        dev = development[archetype]
        hod = holdout[archetype]
        if (
            dev["candidate_count"] >= 15
            and dev["pass_count"] >= 5
            and dev["pass_rate"] >= 0.22
            and dev["normal_cost_survival_rate"] >= 0.58
            and dev["cost_dominated_rate"] <= 0.30
            and dev["tiny_stop_rate"] <= 0.25
            and dev["missed_winner_risk"] <= 0.22
            and hod["candidate_count"] >= 10
            and hod["pass_count"] >= 3
            and hod["normal_cost_survival_rate"] >= 0.52
            and hod["cost_dominated_rate"] <= 0.35
        ):
            eligible.append(archetype)
        elif dev["candidate_count"] >= 8 and dev["pass_count"] >= 2:
            exploratory.append(archetype)

    if eligible:
        return "eligible_for_second_fast_review"
    if exploratory:
        return "continue_research"
    total_dev_passes = sum(summary["pass_count"] for summary in development.values())
    if total_dev_passes == 0:
        return "reject"
    return "needs_archetype_refinement"


def write_pullback_archetype_redesign(config: PullbackArchetypeRedesignConfig) -> dict[str, Path]:
    rows = _annotate_rows(_join_context_rows(config))
    development_rows = [row for row in rows if str(row.get("scope")) == "development"]
    holdout_rows = [row for row in rows if str(row.get("scope")) == "holdout_recent_preview"]

    development_summaries = _build_scope_summaries(development_rows)
    holdout_summaries = _build_scope_summaries(holdout_rows)
    best_archetype, worst_archetype = _pick_best_and_worst(development_summaries)
    classification = _final_classification(development_summaries, holdout_summaries)

    output_root = config.output_root
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    comparison_rows = _comparison_rows("development", development_summaries) + _comparison_rows(
        "holdout_recent_preview",
        holdout_summaries,
    )
    reject_reason_distribution = {
        "development": {
            archetype: development_summaries[archetype]["reject_reason_distribution"] for archetype in _ARCHETYPES
        },
        "holdout_recent_preview": {
            archetype: holdout_summaries[archetype]["reject_reason_distribution"] for archetype in _ARCHETYPES
        },
    }
    cost_survival_report = {
        "development": {
            archetype: {
                "candidate_count": development_summaries[archetype]["candidate_count"],
                "pass_count": development_summaries[archetype]["pass_count"],
                "normal_cost_survival_rate": development_summaries[archetype]["normal_cost_survival_rate"],
                "high_cost_survival_rate": development_summaries[archetype]["high_cost_survival_rate"],
                "cost_dominated_rate": development_summaries[archetype]["cost_dominated_rate"],
            }
            for archetype in _ARCHETYPES
        },
        "holdout_recent_preview": {
            archetype: {
                "candidate_count": holdout_summaries[archetype]["candidate_count"],
                "pass_count": holdout_summaries[archetype]["pass_count"],
                "normal_cost_survival_rate": holdout_summaries[archetype]["normal_cost_survival_rate"],
                "high_cost_survival_rate": holdout_summaries[archetype]["high_cost_survival_rate"],
                "cost_dominated_rate": holdout_summaries[archetype]["cost_dominated_rate"],
            }
            for archetype in _ARCHETYPES
        },
    }
    missed_winner_report = {
        "development": {
            archetype: {
                "candidate_count": development_summaries[archetype]["candidate_count"],
                "missed_winner_risk": development_summaries[archetype]["missed_winner_risk"],
                "recommendation": development_summaries[archetype]["recommendation"],
            }
            for archetype in _ARCHETYPES
        },
        "holdout_recent_preview": {
            archetype: {
                "candidate_count": holdout_summaries[archetype]["candidate_count"],
                "missed_winner_risk": holdout_summaries[archetype]["missed_winner_risk"],
                "recommendation": holdout_summaries[archetype]["recommendation"],
            }
            for archetype in _ARCHETYPES
        },
    }
    personality_report = {
        "development": {
            archetype: {
                "best_personality_labels": development_summaries[archetype]["best_personality_labels"],
                "worst_personality_labels": development_summaries[archetype]["worst_personality_labels"],
            }
            for archetype in _ARCHETYPES
        },
        "holdout_recent_preview": {
            archetype: {
                "best_personality_labels": holdout_summaries[archetype]["best_personality_labels"],
                "worst_personality_labels": holdout_summaries[archetype]["worst_personality_labels"],
            }
            for archetype in _ARCHETYPES
        },
        "soft_evidence_only": True,
    }

    next_research = {
        "classification": classification,
        "best_archetype": best_archetype,
        "worst_archetype": worst_archetype,
        "development_winner": development_summaries[best_archetype],
        "holdout_preview_winner": holdout_summaries[best_archetype],
        "allowed_next_step": "second_fast_review_only_if_stage4_classification_is_eligible",
        "forbidden": [
            "no_full_history_confirmation",
            "no_stress_windows",
            "no_monte_carlo",
            "no_paper_candidate",
            "no_live_runtime_change",
            "no_paper_runtime_change",
            "no_real_money_enablement",
            "no_macd_bollinger_hard_gates",
        ],
    }

    summary = {
        "stage_name": "Structural Compounding Lab Pullback Archetype Redesign 001",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "real_money_allowed": False,
        "classification": classification,
        "allowed_classifications": list(_FINAL_CLASSIFICATIONS),
        "development_windows": list(_RESEARCH_WINDOWS),
        "holdout_preview_window": _HOLDOUT_WINDOW,
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
        "archetypes_implemented": list(_ARCHETYPES),
        "development_summary": development_summaries,
        "holdout_recent_preview_summary": holdout_summaries,
        "best_archetype": best_archetype,
        "worst_archetype": worst_archetype,
        "soft_evidence_only": {"macd_bollinger": True},
    }

    report_lines = [
        "# Structural Compounding Lab Pullback Archetype Redesign 001",
        "",
        f"Classification: `{classification}`",
        "",
        "## Scope",
        "",
        "- research-only",
        "- development windows: `smoke`, `diagnostic_fast`",
        "- holdout preview: `holdout_recent_preview`",
        "- no full-history run",
        "- no stress windows",
        "- no Monte Carlo",
        "",
        "## Archetype Comparison (Development)",
        "",
        "| Archetype | Candidates | Pass | Pass rate | Normal cost survival | Cost-dominated | Tiny-stop | Missed winner risk | Recommendation |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for archetype in _ARCHETYPES:
        item = development_summaries[archetype]
        report_lines.append(
            f"| {archetype} | {item['candidate_count']} | {item['pass_count']} | {item['pass_rate']:.3%} | {item['normal_cost_survival_rate']:.3%} | {item['cost_dominated_rate']:.3%} | {item['tiny_stop_rate']:.3%} | {item['missed_winner_risk']:.3%} | {item['recommendation']} |"
        )
    report_lines.extend(
        [
            "",
            f"Best archetype: `{best_archetype}`",
            f"Worst archetype: `{worst_archetype}`",
            "",
            "## Research Notes",
            "",
            "- MACD and Bollinger are classification hints only, not hard gates.",
            "- Pullback buying remains research-only and does not alter runtime entries.",
            "- Full-history confirmation, stress windows, and paper candidate remain blocked.",
        ]
    )

    _write_json(
        output_root / "status.json",
        {
            "state": "complete",
            "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
            "classification": classification,
            "research_only": True,
            "real_money_allowed": False,
            "artifacts": {
                "summary": str((output_root / "archetype_redesign_summary.json").resolve()),
                "report": str((output_root / "archetype_redesign_report.md").resolve()),
                "candidates_csv": str((diagnostics_root / "archetype_candidates.csv").resolve()),
            },
        },
    )
    _write_json(output_root / "archetype_redesign_summary.json", summary)
    _write_markdown(output_root / "archetype_redesign_report.md", "\n".join(report_lines) + "\n")
    _write_csv(diagnostics_root / "archetype_candidates.csv", rows)
    _write_json(
        diagnostics_root / "archetype_profile_comparison.json",
        {
            "development": development_summaries,
            "holdout_recent_preview": holdout_summaries,
            "best_archetype": best_archetype,
            "worst_archetype": worst_archetype,
        },
    )
    _write_csv(diagnostics_root / "archetype_profile_comparison.csv", comparison_rows)
    _write_json(diagnostics_root / "archetype_reject_reason_distribution.json", reject_reason_distribution)
    _write_json(diagnostics_root / "archetype_cost_survival_report.json", cost_survival_report)
    _write_json(diagnostics_root / "archetype_missed_winner_risk_report.json", missed_winner_report)
    _write_json(diagnostics_root / "archetype_personality_report.json", personality_report)
    _write_json(reports_root / "next_research_recommendation.json", next_research)
    _write_markdown(
        reports_root / "next_research_recommendation.md",
        "\n".join(
            [
                "# Next Research Recommendation",
                "",
                f"Classification: `{classification}`",
                f"Best archetype: `{best_archetype}`",
                f"Worst archetype: `{worst_archetype}`",
                "",
                "Stage 4 remains passive. Freeze these archetype definitions before any second fast review, and keep live/paper behavior unchanged.",
            ]
        )
        + "\n",
    )
    return {
        "status": output_root / "status.json",
        "summary": output_root / "archetype_redesign_summary.json",
        "report": output_root / "archetype_redesign_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    config = PullbackArchetypeRedesignConfig(
        review_root=root / "structural_compounding_lab" / "output" / "evidence_review_001",
        refinement_root=root / "structural_compounding_lab" / "output" / "evidence_refinement_001",
        output_root=root / "structural_compounding_lab" / "output" / "pullback_archetype_redesign_001",
    )
    write_pullback_archetype_redesign(config)
    print(f"Pullback archetype redesign artifacts written to: {config.output_root}")


if __name__ == "__main__":
    main()
