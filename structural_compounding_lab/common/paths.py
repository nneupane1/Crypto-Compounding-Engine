from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from structural_compounding_lab.config import StructuralLabConfig


def lab_root(config: StructuralLabConfig | None = None) -> Path:
    cfg = config or StructuralLabConfig.load()
    return cfg.lab_root


def output_root(config: StructuralLabConfig | None = None) -> Path:
    cfg = config or StructuralLabConfig.load()
    return cfg.output_root


def ensure_output_dirs(config: StructuralLabConfig | None = None) -> Path:
    root = output_root(config)
    root.mkdir(parents=True, exist_ok=True)
    return root


def resolve_output_root(config: StructuralLabConfig | None = None, output_dir: str | Path | None = None) -> Path:
    if output_dir is None:
        return ensure_output_dirs(config)
    cfg = config or StructuralLabConfig.load()
    candidate = Path(output_dir)
    root = candidate if candidate.is_absolute() else (cfg.lab_root / candidate)
    root.mkdir(parents=True, exist_ok=True)
    return root


def artifact_paths(config: StructuralLabConfig | None = None, output_dir: str | Path | None = None) -> dict[str, Path]:
    root = resolve_output_root(config, output_dir=output_dir)
    return {
        "summary": root / "summary.json",
        "master_lab_plan_json": root / "master_lab_plan.json",
        "master_lab_plan_md": root / "master_lab_plan.md",
        "candidate_registry": root / "candidate_registry.json",
        "candidate_report": root / "candidate_report.md",
        "feature_flags": root / "feature_flags.json",
        "equity": root / "equity.csv",
        "trades": root / "trades.csv",
        "setup_log": root / "setup_log.csv",
        "level_log": root / "level_log.csv",
        "liquidity_events": root / "liquidity_events.csv",
        "profit_vault": root / "profit_vault.json",
        "cooldown_log": root / "cooldown_log.csv",
        "pyramiding_log": root / "pyramiding_log.csv",
        "report": root / "report.md",
        "trade_story_report": root / "reports" / "trade_story_report.md",
        "winner_story_report": root / "diagnostics" / "winner_story_report.md",
        "rejected_signal_story_report": root / "diagnostics" / "rejected_signal_story_report.md",
        "entry_quality_report": root / "diagnostics" / "entry_quality_report.json",
        "pullback_quality_report": root / "diagnostics" / "pullback_quality_report.json",
        "original_vs_refined_entry": root / "diagnostics" / "original_vs_refined_entry.csv",
        "original_vs_pullback_entry": root / "diagnostics" / "original_vs_pullback_entry.csv",
        "pullback_type_performance_report": root / "diagnostics" / "pullback_type_performance_report.json",
        "missed_due_to_waiting_report": root / "diagnostics" / "missed_due_to_waiting_report.csv",
        "pullback_compounding_readiness_report": root / "diagnostics" / "pullback_compounding_readiness_report.json",
        "personality_performance_report": root / "diagnostics" / "personality_performance_report.json",
        "indicator_confluence_report": root / "diagnostics" / "indicator_confluence_report.json",
        "promotion_packet": root / "reports" / "promotion_packet.json",
        "execution_cost_model": root / "execution_realism" / "execution_cost_model.json",
        "execution_cost_assumptions": root / "execution_realism" / "execution_cost_assumptions.md",
        "execution_cost_sensitivity": root / "execution_realism" / "execution_cost_sensitivity.json",
        "execution_cost_sensitivity_md": root / "execution_realism" / "execution_cost_sensitivity.md",
        "status": root / "status.json",
        "scenario_progress": root / "scenario_progress.json",
        "checkpoint": root / "_checkpoints" / "structural_backtest.checkpoint.json",
    }


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
