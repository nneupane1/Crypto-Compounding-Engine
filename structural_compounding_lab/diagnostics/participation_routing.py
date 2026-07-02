from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any


_ALLOWED_CLASSIFICATIONS = (
    "reject",
    "continue_research",
    "needs_routing_refinement",
    "eligible_for_second_fast_review",
)
_PARTICIPATION_RISK = {
    "FULL_SIZE_CANDIDATE": 1.00,
    "REDUCED_SIZE_CANDIDATE": 0.50,
    "PROBE_CANDIDATE": 0.25,
    "WAIT_FOR_CONFIRMATION": 0.00,
    "NO_ADD_ON_MANAGEMENT": 0.50,
    "DE_RISK_FAST_MANAGEMENT": 0.25,
    "REJECT_INVALID": 0.00,
}
_PROMISING_ARCHETYPES = {
    "LIQUIDITY_SWEEP_RECLAIM",
    "HEALTHY_CONTINUATION_PULLBACK",
    "EMA_VWAP_RECLAIM_PULLBACK",
    "MICRO_PULLBACK_MOMENTUM",
    "BREAKOUT_RETEST_PULLBACK",
}


@dataclass(frozen=True)
class ParticipationRoutingConfig:
    evidence_review_root: Path
    evidence_refinement_root: Path
    detector_tightening_stage1_root: Path
    detector_tightening_stage2_root: Path
    archetype_root: Path
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


def _to_bool(value: Any) -> bool:
    return str(value).lower() == "true"


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _safe_mean(values: list[float]) -> float | None:
    return mean(values) if values else None


def _safe_median(values: list[float]) -> float | None:
    return median(values) if values else None


def _fmt(value: float | None, spec: str = ".3f") -> str:
    if value is None:
        return "n/a"
    return format(value, spec)


def _load_archetype_rows(archetype_root: Path) -> list[dict[str, Any]]:
    path = archetype_root / "diagnostics" / "archetype_candidates.csv"
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    bool_fields = {
        "pullback_detected",
        "missed_due_to_waiting",
        "tiny_stop_flag",
        "unrealistic_stop_flag",
        "noise_stop_flag",
        "cost_dominated_stop_flag",
        "survives_low_cost",
        "survives_normal_cost",
        "survives_high_cost",
        "survives_stress_cost",
        "cost_aware_pullback_candidate",
        "htf_aligned",
        "macd_confirmation_flag",
        "macd_warning_flag",
        "bb_compression",
        "bb_expansion",
        "bb_warning_flag",
        "micro_pullback_detected",
        "runner_eligible_candidate",
        "add_on_research_candidate",
        "archetype_detected",
        "cost_survival_low",
        "cost_survival_normal",
        "cost_survival_high",
        "cost_dominated_flag",
        "missed_winner_risk_flag",
        "archetype_pass",
        "soft_evidence_only",
    }
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
        "liquidity_event_age_bars",
        "level_distance_atr",
        "structure_validity_score",
        "archetype_score",
        "entry_candidate_price",
        "stop_price",
        "stop_distance",
        "stop_atr_fraction",
        "stop_cost_multiple",
        "confirmation_delay",
        "pullback_depth",
    }
    for row in rows:
        for key in bool_fields:
            if key in row:
                row[key] = _to_bool(row[key])
        for key in numeric_fields:
            if key in row:
                row[key] = _to_float(row[key])
    return rows


def route_participation_candidate(row: dict[str, Any]) -> dict[str, Any]:
    archetype = str(row.get("archetype", ""))
    personality = str(row.get("personality_label", "NO_PERSONALITY_EDGE"))
    structure_score = _to_float(row.get("structure_validity_score"))
    stop_atr = _to_float(row.get("stop_atr_fraction", row.get("refined_stop_atr_fraction")))
    stop_cost = _to_float(row.get("stop_cost_multiple", row.get("refined_stop_cost_multiple")))
    confirmation_delay = _to_float(row.get("confirmation_delay", row.get("liquidity_event_age_bars")))
    archetype_score = _to_float(row.get("archetype_score"))
    archetype_grade = str(row.get("archetype_grade", "REJECT"))
    survives_low = bool(row.get("cost_survival_low", row.get("survives_low_cost")))
    survives_normal = bool(row.get("cost_survival_normal", row.get("survives_normal_cost")))
    survives_high = bool(row.get("cost_survival_high", row.get("survives_high_cost")))
    tiny_stop = bool(row.get("tiny_stop_flag"))
    unrealistic_stop = bool(row.get("unrealistic_stop_flag"))
    cost_dominated = bool(row.get("cost_dominated_flag", row.get("cost_dominated_stop_flag")))
    missed_winner = bool(row.get("missed_winner_risk_flag"))
    exhaustion_warning = personality == "EXHAUSTION_RISK" or bool(row.get("macd_warning_flag")) and bool(row.get("bb_warning_flag"))
    choppy_warning = personality in {"CHOPPY_LOW_TRUST", "NO_PERSONALITY_EDGE"}
    core_structure_valid = (
        archetype != "STRUCTURE_BREAK_DIP"
        and structure_score >= 0.40
        and "structure_or_context_failed" not in str(row.get("reject_reasons", ""))
    )

    impossible_cost = (not survives_low and stop_cost < 0.50) or (_to_float(row.get("expected_cost_r")) > 3.5 and stop_cost < 0.50)
    impossible_stop = stop_atr < 0.05 and stop_cost < 0.20
    add_on_source_ok = bool(row.get("runner_eligible_candidate")) and bool(row.get("add_on_research_candidate", False) or str(row.get("runner_label")) != "tactical_scalp")
    runner_source_ok = bool(row.get("runner_eligible_candidate")) or str(row.get("runner_label")) in {"normal_swing", "moonshot_candidate"}

    wait_reason = ""
    reject_reason = ""
    add_on_allowed = False
    runner_allowed = False
    de_risk_fast = False

    participation_score = (
        structure_score * 42.0
        + min(archetype_score, 100.0) * 0.28
        + (12.0 if survives_normal else 0.0)
        + (4.0 if survives_high else 0.0)
        - (18.0 if cost_dominated else 0.0)
        - (16.0 if tiny_stop else 0.0)
        - (14.0 if unrealistic_stop else 0.0)
        - (6.0 if exhaustion_warning else 0.0)
        - (4.0 if choppy_warning else 0.0)
    )
    participation_score = max(0.0, min(participation_score, 100.0))

    if archetype == "STRUCTURE_BREAK_DIP" or not core_structure_valid or impossible_cost or impossible_stop:
        mode = "REJECT_INVALID"
        reject_reason = "invalid_structure_or_impossible_geometry"
        participation_score = min(participation_score, 15.0)
    elif (
        archetype_grade in {"A", "B"}
        and structure_score >= 0.72
        and survives_normal
        and survives_high
        and not cost_dominated
        and not tiny_stop
        and not unrealistic_stop
        and not exhaustion_warning
        and not choppy_warning
        and stop_cost >= 2.25
        and 0.24 <= stop_atr <= 1.30
    ):
        mode = "FULL_SIZE_CANDIDATE"
        add_on_allowed = add_on_source_ok
        runner_allowed = runner_source_ok
        participation_score = max(participation_score, 82.0)
    elif exhaustion_warning and survives_low:
        mode = "DE_RISK_FAST_MANAGEMENT"
        de_risk_fast = True
        add_on_allowed = False
        runner_allowed = False
        participation_score = min(max(participation_score, 38.0), 62.0)
    elif (
        core_structure_valid
        and survives_normal
        and structure_score >= 0.52
        and not unrealistic_stop
        and not cost_dominated
        and (choppy_warning or str(row.get("runner_label")) == "tactical_scalp" or not add_on_source_ok)
    ):
        mode = "NO_ADD_ON_MANAGEMENT"
        add_on_allowed = False
        runner_allowed = False
        participation_score = min(max(participation_score, 46.0), 68.0)
    elif (
        core_structure_valid
        and (survives_low or survives_normal or missed_winner or archetype in _PROMISING_ARCHETYPES)
        and (cost_dominated or tiny_stop or unrealistic_stop or stop_cost < 1.50 or stop_atr < 0.18)
    ):
        mode = "PROBE_CANDIDATE"
        add_on_allowed = False
        runner_allowed = False
        participation_score = min(max(participation_score, 28.0), 56.0)
    elif (
        core_structure_valid
        and survives_normal
        and structure_score >= 0.48
        and not impossible_stop
        and (
            cost_dominated
            or stop_cost < 2.25
            or archetype_grade in {"C", "D", "REJECT"}
            or confirmation_delay > 3.0
        )
    ):
        mode = "REDUCED_SIZE_CANDIDATE"
        add_on_allowed = False
        runner_allowed = runner_source_ok and not choppy_warning
        participation_score = min(max(participation_score, 40.0), 70.0)
    else:
        mode = "WAIT_FOR_CONFIRMATION"
        wait_reason = "confirmation_or_cost_not_clean_enough"
        add_on_allowed = False
        runner_allowed = False
        participation_score = min(max(participation_score, 20.0), 45.0)

    explanation = [
        f"mode={mode}",
        f"archetype={archetype}",
        f"personality={personality}",
        f"structure={structure_score:.2f}",
        f"stop_cost={stop_cost:.2f}",
        f"stop_atr={stop_atr:.2f}",
    ]
    if exhaustion_warning:
        explanation.append("exhaustion_warning_soft")
    if choppy_warning:
        explanation.append("choppy_warning_soft")
    if bool(row.get("macd_confirmation_flag")):
        explanation.append("MACD_supportive_soft")
    if bool(row.get("bb_compression")) or bool(row.get("bb_expansion")):
        explanation.append("Bollinger_context_soft")

    return {
        "symbol": str(row.get("symbol", "")),
        "time": str(row.get("entry_time", row.get("entry_candidate_time", ""))),
        "side": str(row.get("side", "")),
        "archetype": archetype,
        "personality": personality,
        "core_structure_valid": core_structure_valid,
        "archetype_score": archetype_score,
        "archetype_grade": archetype_grade,
        "structure_validity_score": structure_score,
        "cost_survival_low": survives_low,
        "cost_survival_normal": survives_normal,
        "cost_survival_high": survives_high,
        "tiny_stop_flag": tiny_stop,
        "unrealistic_stop_flag": unrealistic_stop,
        "cost_dominated_flag": cost_dominated,
        "missed_winner_risk_flag": missed_winner,
        "exhaustion_warning": exhaustion_warning,
        "choppy_warning": choppy_warning,
        "participation_mode": mode,
        "participation_score": round(participation_score, 4),
        "suggested_research_risk_fraction": _PARTICIPATION_RISK[mode],
        "add_on_allowed_research_flag": add_on_allowed,
        "runner_allowed_research_flag": runner_allowed,
        "de_risk_fast_research_flag": de_risk_fast,
        "wait_reason": wait_reason,
        "reject_reason": reject_reason,
        "explanation": "; ".join(explanation),
        "scope": str(row.get("scope", "")),
        "soft_evidence_only": True,
    }


def _route_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    routed_rows: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        enriched.update(route_participation_candidate(enriched))
        routed_rows.append(enriched)
    return routed_rows


def _mode_distribution(rows: list[dict[str, Any]]) -> dict[str, Any]:
    counter = Counter(str(row.get("participation_mode")) for row in rows)
    total = len(rows) or 1
    return {
        "total_candidates": len(rows),
        "counts": dict(counter),
        "rates": {mode: counter.get(mode, 0) / total for mode in _PARTICIPATION_RISK},
    }


def _archetype_to_participation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("archetype"))].append(row)
    payload: dict[str, Any] = {}
    for archetype, items in grouped.items():
        counter = Counter(str(item.get("participation_mode")) for item in items)
        payload[archetype] = {
            "candidate_count": len(items),
            "mode_counts": dict(counter),
            "full_size_rate": counter.get("FULL_SIZE_CANDIDATE", 0) / len(items),
            "reduced_rate": counter.get("REDUCED_SIZE_CANDIDATE", 0) / len(items),
            "probe_rate": counter.get("PROBE_CANDIDATE", 0) / len(items),
            "wait_rate": counter.get("WAIT_FOR_CONFIRMATION", 0) / len(items),
            "de_risk_rate": counter.get("DE_RISK_FAST_MANAGEMENT", 0) / len(items),
            "reject_rate": counter.get("REJECT_INVALID", 0) / len(items),
        }
    return payload


def _personality_to_participation(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("personality"))].append(row)
    payload: dict[str, Any] = {}
    for label, items in grouped.items():
        counter = Counter(str(item.get("participation_mode")) for item in items)
        payload[label] = {
            "candidate_count": len(items),
            "mode_counts": dict(counter),
            "de_risk_rate": counter.get("DE_RISK_FAST_MANAGEMENT", 0) / len(items),
            "full_size_rate": counter.get("FULL_SIZE_CANDIDATE", 0) / len(items),
            "reduced_or_probe_rate": (
                counter.get("REDUCED_SIZE_CANDIDATE", 0) + counter.get("PROBE_CANDIDATE", 0)
            ) / len(items),
        }
    return payload


def _probe_candidate_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    probes = [row for row in rows if str(row.get("participation_mode")) == "PROBE_CANDIDATE"]
    return {
        "candidate_count": len(probes),
        "archetype_distribution": dict(Counter(str(row.get("archetype")) for row in probes)),
        "personality_distribution": dict(Counter(str(row.get("personality")) for row in probes)),
        "missed_winner_risk_count": sum(1 for row in probes if bool(row.get("missed_winner_risk_flag"))),
        "median_participation_score": _safe_median([_to_float(row.get("participation_score")) for row in probes]),
    }


def _de_risk_candidate_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = [row for row in rows if str(row.get("participation_mode")) == "DE_RISK_FAST_MANAGEMENT"]
    return {
        "candidate_count": len(items),
        "exhaustion_warning_rate": sum(1 for row in items if bool(row.get("exhaustion_warning"))) / len(items) if items else 0.0,
        "archetype_distribution": dict(Counter(str(row.get("archetype")) for row in items)),
        "personality_distribution": dict(Counter(str(row.get("personality")) for row in items)),
    }


def _reject_invalid_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    items = [row for row in rows if str(row.get("participation_mode")) == "REJECT_INVALID"]
    return {
        "candidate_count": len(items),
        "archetype_distribution": dict(Counter(str(row.get("archetype")) for row in items)),
        "reject_reason_distribution": dict(Counter(str(row.get("reject_reason")) for row in items)),
        "missed_winner_risk_rate": sum(1 for row in items if bool(row.get("missed_winner_risk_flag"))) / len(items) if items else 0.0,
    }


def _missed_winner_participation_estimate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    risky = [row for row in rows if bool(row.get("missed_winner_risk_flag"))]
    recovered = [
        row for row in risky
        if str(row.get("participation_mode")) in {"PROBE_CANDIDATE", "REDUCED_SIZE_CANDIDATE", "NO_ADD_ON_MANAGEMENT", "DE_RISK_FAST_MANAGEMENT"}
    ]
    return {
        "missed_winner_flagged_count": len(risky),
        "recovered_participation_count": len(recovered),
        "recovered_participation_rate": (len(recovered) / len(risky)) if risky else 0.0,
        "recovered_mode_distribution": dict(Counter(str(row.get("participation_mode")) for row in recovered)),
        "recovered_archetype_distribution": dict(Counter(str(row.get("archetype")) for row in recovered)),
    }


def _classification(rows: list[dict[str, Any]]) -> str:
    distribution = _mode_distribution(rows)
    counts = distribution["counts"]
    total = distribution["total_candidates"] or 1
    full_count = counts.get("FULL_SIZE_CANDIDATE", 0)
    reduced_count = counts.get("REDUCED_SIZE_CANDIDATE", 0)
    probe_count = counts.get("PROBE_CANDIDATE", 0)
    reject_count = counts.get("REJECT_INVALID", 0)
    non_reject_rate = 1.0 - (reject_count / total)
    full_rows = [row for row in rows if str(row.get("participation_mode")) == "FULL_SIZE_CANDIDATE"]
    reduced_probe_rows = [
        row for row in rows if str(row.get("participation_mode")) in {"REDUCED_SIZE_CANDIDATE", "PROBE_CANDIDATE"}
    ]
    full_clean = all(not bool(row.get("cost_dominated_flag")) for row in full_rows)
    recovered = _missed_winner_participation_estimate(rows)["recovered_participation_rate"]

    if (
        full_count >= 10
        and reduced_count + probe_count >= 50
        and non_reject_rate >= 0.55
        and full_clean
        and recovered >= 0.25
    ):
        return "eligible_for_second_fast_review"
    if non_reject_rate >= 0.35 and reduced_count + probe_count >= 25:
        return "continue_research"
    if reduced_count + probe_count > 0:
        return "needs_routing_refinement"
    return "reject"


def write_participation_routing(config: ParticipationRoutingConfig) -> dict[str, Path]:
    rows = _route_rows(_load_archetype_rows(config.archetype_root))
    output_root = config.output_root
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    distribution = _mode_distribution(rows)
    archetype_report = _archetype_to_participation(rows)
    personality_report = _personality_to_participation(rows)
    probe_report = _probe_candidate_report(rows)
    de_risk_report = _de_risk_candidate_report(rows)
    reject_report = _reject_invalid_report(rows)
    missed_winner_estimate = _missed_winner_participation_estimate(rows)
    classification = _classification(rows)

    summary = {
        "stage_name": "Structural Compounding Lab Participation Routing 001",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "real_money_allowed": False,
        "classification": classification,
        "allowed_classifications": list(_ALLOWED_CLASSIFICATIONS),
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
        "participation_mode_distribution": distribution,
        "archetype_to_participation_report": archetype_report,
        "personality_to_participation_report": personality_report,
        "probe_candidate_report": probe_report,
        "de_risk_candidate_report": de_risk_report,
        "reject_invalid_report": reject_report,
        "missed_winner_participation_estimate": missed_winner_estimate,
        "soft_evidence_only": {"macd_bollinger": True},
        "allowed_input_roots": [
            str(config.evidence_review_root.resolve()),
            str(config.evidence_refinement_root.resolve()),
            str(config.detector_tightening_stage1_root.resolve()),
            str(config.detector_tightening_stage2_root.resolve()),
            str(config.archetype_root.resolve()),
        ],
    }
    next_research = {
        "classification": classification,
        "notes": [
            "Stage 5 converts detector output into participation routing rather than hard gating.",
            "Reduced-size and probe labels are research-only and do not modify runtime sizing.",
            "STRUCTURE_BREAK_DIP remains invalid and routes to reject.",
        ],
        "forbidden": [
            "no_full_history_confirmation",
            "no_stress_windows",
            "no_monte_carlo",
            "no_live_runtime_change",
            "no_paper_runtime_change",
            "no_real_money_enablement",
            "no_macd_bollinger_hard_gates",
            "no_pullback_activation",
        ],
    }

    report_lines = [
        "# Structural Compounding Lab Participation Routing 001",
        "",
        f"Classification: `{classification}`",
        "",
        "## Participation Mode Distribution",
        "",
        f"- total candidates: `{distribution['total_candidates']}`",
    ]
    for mode in _PARTICIPATION_RISK:
        report_lines.append(
            f"- {mode}: `{distribution['counts'].get(mode, 0)}` ({distribution['rates'].get(mode, 0.0):.3%})"
        )
    report_lines.extend(
        [
            "",
            "## Missed Winner Participation Estimate",
            "",
            f"- missed-winner flagged count: `{missed_winner_estimate['missed_winner_flagged_count']}`",
            f"- recovered participation count: `{missed_winner_estimate['recovered_participation_count']}`",
            f"- recovered participation rate: `{missed_winner_estimate['recovered_participation_rate']:.3%}`",
            "",
            "Routing remains research-only. No live/paper behavior changed.",
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
        },
    )
    _write_json(output_root / "participation_routing_summary.json", summary)
    _write_markdown(output_root / "participation_routing_report.md", "\n".join(report_lines) + "\n")
    _write_csv(diagnostics_root / "routed_candidates.csv", rows)
    _write_json(diagnostics_root / "participation_mode_distribution.json", distribution)
    _write_json(diagnostics_root / "archetype_to_participation_report.json", archetype_report)
    _write_json(diagnostics_root / "personality_to_participation_report.json", personality_report)
    _write_json(diagnostics_root / "probe_candidate_report.json", probe_report)
    _write_json(diagnostics_root / "de_risk_candidate_report.json", de_risk_report)
    _write_json(diagnostics_root / "reject_invalid_report.json", reject_report)
    _write_json(diagnostics_root / "missed_winner_participation_estimate.json", missed_winner_estimate)
    _write_json(reports_root / "next_research_recommendation.json", next_research)
    _write_markdown(
        reports_root / "next_research_recommendation.md",
        "\n".join(
            [
                "# Next Research Recommendation",
                "",
                f"Classification: `{classification}`",
                "",
                "Participation routing should remain passive and research-only until a later second fast review justifies anything stronger.",
            ]
        )
        + "\n",
    )
    return {
        "status": output_root / "status.json",
        "summary": output_root / "participation_routing_summary.json",
        "report": output_root / "participation_routing_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    config = ParticipationRoutingConfig(
        evidence_review_root=root / "structural_compounding_lab" / "output" / "evidence_review_001",
        evidence_refinement_root=root / "structural_compounding_lab" / "output" / "evidence_refinement_001",
        detector_tightening_stage1_root=root / "structural_compounding_lab" / "output" / "detector_tightening_001",
        detector_tightening_stage2_root=root / "structural_compounding_lab" / "output" / "detector_tightening_002",
        archetype_root=root / "structural_compounding_lab" / "output" / "pullback_archetype_redesign_001",
        output_root=root / "structural_compounding_lab" / "output" / "participation_routing_001",
    )
    write_participation_routing(config)
    print(f"Participation routing artifacts written to: {config.output_root}")


if __name__ == "__main__":
    main()
