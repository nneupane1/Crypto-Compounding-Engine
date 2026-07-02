from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from structural_compounding_lab.config.candidate_registry import load_candidate_registry
from structural_compounding_lab.config.feature_flags import load_feature_flags
from structural_compounding_lab.diagnostics import (
    build_entry_quality_report,
    build_indicator_confluence_report,
    build_missed_pullback_report,
    build_original_vs_refined_entry_rows,
    build_personality_performance_report,
    render_rejected_signal_story_report,
    render_winner_story_report,
)
from structural_compounding_lab.reports.candidate_report import render_candidate_report
from structural_compounding_lab.reports.promotion_packet import build_promotion_packet
from structural_compounding_lab.reports.trade_story_report import render_trade_story_report
from structural_compounding_lab.validation.execution_cost_sensitivity import build_execution_cost_outputs
from structural_compounding_lab.validation.lab_validation_ladder import write_master_lab_plan


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _group_pullback_types(original_vs_refined_rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in original_vs_refined_rows:
        pullback_type = str(row.get("pullback_type") or "UNKNOWN")
        bucket = grouped.setdefault(
            pullback_type,
            {"count": 0, "avg_improved_r_delta": 0.0, "avg_refined_r": 0.0, "avg_original_r": 0.0},
        )
        bucket["count"] += 1
        bucket["avg_improved_r_delta"] += float(row.get("improved_R_delta", 0.0) or 0.0)
        bucket["avg_refined_r"] += float(row.get("refined_R_to_same_target", 0.0) or 0.0)
        bucket["avg_original_r"] += float(row.get("original_R_to_same_target", 0.0) or 0.0)
    for bucket in grouped.values():
        count = max(bucket["count"], 1)
        bucket["avg_improved_r_delta"] /= count
        bucket["avg_refined_r"] /= count
        bucket["avg_original_r"] /= count
    return grouped


def write_research_artifacts(
    *,
    paths: dict[str, Path],
    summary: dict[str, Any],
    trades: list[dict[str, Any]],
    setup_rows: list[dict[str, Any]],
    stories: list[dict[str, Any]],
) -> dict[str, Any]:
    for key in (
        "feature_flags",
        "candidate_registry",
        "candidate_report",
        "entry_quality_report",
        "pullback_quality_report",
        "pullback_type_performance_report",
        "pullback_compounding_readiness_report",
        "personality_performance_report",
        "indicator_confluence_report",
        "winner_story_report",
        "rejected_signal_story_report",
        "trade_story_report",
        "promotion_packet",
    ):
        paths[key].parent.mkdir(parents=True, exist_ok=True)
    write_master_lab_plan(
        json_path=paths["master_lab_plan_json"],
        markdown_path=paths["master_lab_plan_md"],
    )

    feature_flags = load_feature_flags()
    paths["feature_flags"].write_text(json.dumps(feature_flags, indent=2), encoding="utf-8")

    candidate_registry = load_candidate_registry()
    paths["candidate_registry"].write_text(json.dumps(candidate_registry, indent=2), encoding="utf-8")
    paths["candidate_report"].write_text(render_candidate_report(candidate_registry), encoding="utf-8")

    original_vs_refined_rows = build_original_vs_refined_entry_rows(trades, setup_rows)
    _write_csv(paths["original_vs_refined_entry"], original_vs_refined_rows)
    _write_csv(paths["original_vs_pullback_entry"], original_vs_refined_rows)

    entry_quality = build_entry_quality_report(original_vs_refined_rows)
    pullback_type_report = _group_pullback_types(original_vs_refined_rows)
    missed_pullbacks = build_missed_pullback_report(original_vs_refined_rows)
    personality_report = build_personality_performance_report(trades)
    confluence_report = build_indicator_confluence_report(setup_rows)
    compounding_readiness = {
        "average_compounding_readiness": (
            sum(float(row.get("compounding_readiness_score", 0.0) or 0.0) for row in setup_rows) / max(len(setup_rows), 1)
        ),
        "runner_candidate_rate": (
            sum(1 for row in setup_rows if str(row.get("runner_label", "")) in {"structural_runner", "moonshot_candidate", "normal_swing"}) / max(len(setup_rows), 1)
        ),
    }
    paths["entry_quality_report"].write_text(json.dumps(entry_quality, indent=2), encoding="utf-8")
    paths["pullback_quality_report"].write_text(json.dumps(entry_quality, indent=2), encoding="utf-8")
    paths["pullback_type_performance_report"].write_text(json.dumps(pullback_type_report, indent=2), encoding="utf-8")
    _write_csv(paths["missed_due_to_waiting_report"], missed_pullbacks)
    paths["pullback_compounding_readiness_report"].write_text(json.dumps(compounding_readiness, indent=2), encoding="utf-8")
    paths["personality_performance_report"].write_text(json.dumps(personality_report, indent=2), encoding="utf-8")
    paths["indicator_confluence_report"].write_text(json.dumps(confluence_report, indent=2), encoding="utf-8")
    paths["winner_story_report"].parent.mkdir(parents=True, exist_ok=True)
    paths["winner_story_report"].write_text(render_winner_story_report(trades), encoding="utf-8")
    paths["rejected_signal_story_report"].parent.mkdir(parents=True, exist_ok=True)
    paths["rejected_signal_story_report"].write_text(render_rejected_signal_story_report(setup_rows), encoding="utf-8")
    paths["trade_story_report"].parent.mkdir(parents=True, exist_ok=True)
    paths["trade_story_report"].write_text(render_trade_story_report(stories), encoding="utf-8")

    execution_costs = build_execution_cost_outputs(
        trades=trades,
        output_root=paths["execution_cost_model"].parent,
    )
    promotion_packet = build_promotion_packet(
        summary=summary,
        candidate_registry=candidate_registry,
        execution_costs=execution_costs,
    )
    paths["promotion_packet"].parent.mkdir(parents=True, exist_ok=True)
    paths["promotion_packet"].write_text(json.dumps(promotion_packet, indent=2), encoding="utf-8")

    return {
        "feature_flags": feature_flags,
        "candidate_registry": candidate_registry,
        "entry_quality": entry_quality,
        "pullback_type_report": pullback_type_report,
        "missed_pullbacks": len(missed_pullbacks),
        "personality_report": personality_report,
        "confluence_report": confluence_report,
        "compounding_readiness": compounding_readiness,
        "execution_costs": execution_costs,
    }
