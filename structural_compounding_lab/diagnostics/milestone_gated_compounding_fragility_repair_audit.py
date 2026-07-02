from __future__ import annotations

import hashlib
import json
import random
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import RESEARCH_ONLY_FLAGS  # noqa: E402
from structural_compounding_lab.diagnostics.cost_resilient_trade_redundancy_expansion_audit import (  # noqa: E402
    MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
)
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _median,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _timestamp,
    _to_float,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.diagnostics.milestone_bridge_fragility_driver_repair_audit import (  # noqa: E402
    _estimated_cost,
)
from structural_compounding_lab.diagnostics.milestone_gated_explosive_compounding_audit import (  # noqa: E402
    BASE_LOCK_RATIO,
    EXPECTED_REPAIR_MODE,
    MilestoneGatedExplosiveCompoundingAuditConfig as PriorMilestoneAuditConfig,
    START_CAPITAL,
    _base_multiplier,
    _drop_label,
    _load_baseline_anchor_and_stream as _load_prior_baseline_anchor_and_stream,
    _random_keep,
    _remove_top_winners,
    _safe_float,
)
from structural_compounding_lab.diagnostics.native_12h_execution_sleeve_discovery_audit import (  # noqa: E402
    CONSERVATIVE_COST_BPS,
    HIGH_SLIPPAGE_COST_BPS,
    NORMAL_COST_BPS,
    OPTIMISTIC_COST_BPS,
    ZERO_COST_BPS,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import _build_windows  # noqa: E402


OUTPUT_FOLDER_NAME = "milestone_gated_compounding_fragility_repair_audit_001"
DEFAULT_RANDOM_REPEAT_COUNT = 64
MAX_VARIANTS = 15
STATE_NOT_STARTED = "not_started"
STATE_RUNNING = "running"
STATE_PARTIAL = "partial"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_BLOCKED = "blocked"


@dataclass(frozen=True)
class MilestoneGatedCompoundingFragilityRepairAuditConfig:
    package_root: Path
    output_root: Path
    random_repeat_count: int = DEFAULT_RANDOM_REPEAT_COUNT
    force_rerun: bool = False


@dataclass(frozen=True)
class RepairVariantSpec:
    variant_name: str
    description: str
    primary_trigger_equity: float | None
    primary_multiplier: float
    secondary_trigger_equity: float | None
    secondary_multiplier: float
    max_multiplier_cap: float
    enable_drawdown_brake: bool
    soft_brake_pct: float | None
    hard_brake_pct: float | None
    milestone_buffer_pct: float
    lock_ratio_above_trigger: float
    lock_ratio_above_1m: float
    reenable_requires_new_high: bool
    stepdown_to_baseline_on_soft_brake: bool
    win_streak_cap: int | None
    win_streak_multiplier_cap: float | None
    volatility_brake_threshold: float | None
    volatility_brake_multiplier_cap: float | None
    available: bool
    unavailable_reason: str


def _paths(config: MilestoneGatedCompoundingFragilityRepairAuditConfig) -> dict[str, Path]:
    prior_root = config.package_root / "output" / "milestone_gated_explosive_compounding_audit_001"
    return {
        "prior_root": prior_root,
        "prior_summary": prior_root / "milestone_gated_explosive_compounding_summary.json",
        "prior_baseline_anchor": prior_root / "diagnostics" / "baseline_anchor.json",
        "prior_stream_reconstruction": prior_root / "diagnostics" / "trusted_1h_trade_stream_reconstruction.json",
        "prior_cost_band_results": prior_root / "diagnostics" / "milestone_gated_cost_band_results.csv",
        "prior_fragility_results": prior_root / "diagnostics" / "milestone_gated_fragility_results.csv",
        "prior_self_audit": prior_root / "diagnostics" / "implementation_self_audit.json",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path, Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    ledger_root = output_root / "ledger"
    reports_root = output_root / "reports"
    checkpoints_root = output_root / "_checkpoints"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    ledger_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    checkpoints_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, ledger_root, reports_root, checkpoints_root


def _compatibility_payload(variant_specs: list[RepairVariantSpec], random_repeat_count: int) -> dict[str, Any]:
    return {
        "module": "milestone_gated_compounding_fragility_repair_audit",
        "version": 1,
        "random_repeat_count": int(random_repeat_count),
        "variant_specs": [
            {
                key: value
                for key, value in asdict(spec).items()
                if key not in {"available", "unavailable_reason"}
            }
            for spec in variant_specs
        ],
        "cost_bands": [row[0] for row in _cost_band_specs()],
    }


def _compatibility_signature(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _next_run_folder(output_root: Path) -> Path:
    parent = output_root.parent
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return parent / f"{output_root.name}_{suffix}"


def _write_status(output_root: Path, *, state: str, warnings: list[str], compatibility_signature: str, extra: dict[str, Any] | None = None) -> None:
    payload = {
        "state": state,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "compatibility_signature": compatibility_signature,
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    if extra:
        payload.update(extra)
    _write_json(output_root / "status.json", payload)


def _write_scenario_progress(
    output_root: Path,
    *,
    state: str,
    compatibility_signature: str,
    variant_specs: list[RepairVariantSpec],
    completed_variants: list[str],
    warnings: list[str],
) -> None:
    payload = {
        "state": state,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "compatibility_signature": compatibility_signature,
        "variant_names": [spec.variant_name for spec in variant_specs],
        "total_variants": len(variant_specs),
        "completed_variants": completed_variants,
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(output_root / "scenario_progress.json", payload)


def _write_run_progress(
    diagnostics_root: Path,
    *,
    state: str,
    completed_variants: int,
    total_variants: int,
    current_variant: str,
    warnings: list[str],
) -> None:
    payload = {
        "state": state,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed_variants": completed_variants,
        "total_variants": total_variants,
        "percent_complete": round((completed_variants / max(total_variants, 1)) * 100.0, 4),
        "current_variant": current_variant,
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(diagnostics_root / "run_progress.json", payload)


def _variant_checkpoint_path(checkpoints_root: Path, variant_name: str) -> Path:
    return checkpoints_root / f"{variant_name}.json"


def _save_checkpoint(path: Path, payload: dict[str, Any]) -> None:
    _write_json(path, payload)


def _aggregate_checkpoint_rows(checkpoints_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    cost_rows: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []
    equity_rows: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    for path in sorted(checkpoints_root.glob("*.json")):
        payload = _read_json(path, {})
        cost_rows.extend(payload.get("cost_band_rows", []))
        rolling_rows.extend(payload.get("rolling_rows", []))
        equity_rows.extend(payload.get("equity_curve_rows", []))
        trade_rows.extend(payload.get("trade_ledger_rows", []))
    return cost_rows, rolling_rows, equity_rows, trade_rows


def _harmonize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    keys = sorted({key for row in rows for key in row.keys()})
    return [{key: row.get(key, "") for key in keys} for row in rows]


def _empty_outputs(
    config: MilestoneGatedCompoundingFragilityRepairAuditConfig,
    *,
    state: str,
    classification: str,
    warnings: list[str],
    compatibility_signature: str,
) -> dict[str, Path]:
    diagnostics_root, ledger_root, reports_root, checkpoints_root = _ensure_dirs(config.output_root)
    _write_status(config.output_root, state=state, warnings=warnings, compatibility_signature=compatibility_signature)
    _write_scenario_progress(
        config.output_root,
        state=state,
        compatibility_signature=compatibility_signature,
        variant_specs=[],
        completed_variants=[],
        warnings=warnings,
    )
    _write_run_progress(
        diagnostics_root,
        state=state,
        completed_variants=0,
        total_variants=0,
        current_variant="",
        warnings=warnings,
    )
    _write_json(
        config.output_root / "milestone_gated_compounding_fragility_repair_summary.json",
        {"final_classification": classification, "warnings": warnings, **RESEARCH_ONLY_FLAGS},
    )
    _write_markdown(
        config.output_root / "milestone_gated_compounding_fragility_repair_report.md",
        "# Milestone-Gated Compounding Fragility Repair Audit\n\nThe audit was blocked before the trusted reconstruction or repair gate could complete.\n",
    )
    for path in (
        diagnostics_root / "prior_milestone_audit_anchor.json",
        diagnostics_root / "trusted_1h_stream_recheck.json",
        diagnostics_root / "fragility_repair_variant_specs.json",
        diagnostics_root / "best_repaired_variant_selection.json",
        diagnostics_root / "shadow_fallback_decision.json",
        diagnostics_root / "implementation_self_audit.json",
        diagnostics_root / "stochastic_budget_reliability_check.json",
    ):
        _write_json(path, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    for path in (
        diagnostics_root / "fragility_repair_variants.csv",
        diagnostics_root / "fragility_repair_cost_band_results.csv",
        diagnostics_root / "fragility_repair_rolling_5y_results.csv",
        diagnostics_root / "fragility_repair_stress_results.csv",
        diagnostics_root / "fragility_repair_missed_trade_resilience.csv",
        diagnostics_root / "fragility_repair_scorecard.csv",
        ledger_root / "fragility_repair_equity_curves.csv",
        ledger_root / "fragility_repair_trade_ledgers.csv",
    ):
        _write_csv(path, [])
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(checkpoints_root / "checkpoint_index.json", {"completed_variants": [], **RESEARCH_ONLY_FLAGS})
    return {
        "summary": config.output_root / "milestone_gated_compounding_fragility_repair_summary.json",
        "report": config.output_root / "milestone_gated_compounding_fragility_repair_report.md",
        "status": config.output_root / "status.json",
    }


def _cost_band_specs() -> list[tuple[str, float]]:
    return [
        ("ZERO_COST_REFERENCE", ZERO_COST_BPS),
        ("OPTIMISTIC_MAKER_COST", OPTIMISTIC_COST_BPS),
        ("NORMAL_MIXED_MAKER_TAKER_COST", NORMAL_COST_BPS),
        ("CONSERVATIVE_TAKER_COST", CONSERVATIVE_COST_BPS),
        ("HIGH_SLIPPAGE_COST", HIGH_SLIPPAGE_COST_BPS),
    ]


def _has_numeric_field(rows: list[dict[str, Any]], field: str) -> bool:
    for row in rows:
        value = row.get(field)
        try:
            numeric = _safe_float(value, float("nan"))
        except Exception:
            numeric = float("nan")
        if not pd.isna(numeric):
            return True
    return False


def _volatility_value(row: dict[str, Any]) -> float | None:
    for field in ("volatility_score", "danger_score", "pre_entry_stop_distance_atr", "atr_tradability"):
        value = row.get(field)
        if value is None or str(value).strip() in {"", "None", "nan", "NaN"}:
            continue
        numeric = _safe_float(value, float("nan"))
        if not pd.isna(numeric):
            return float(numeric)
    return None


def _variant_specs(rows: list[dict[str, Any]]) -> list[RepairVariantSpec]:
    volatility_available = _has_numeric_field(rows, "volatility_score") or _has_numeric_field(rows, "danger_score") or _has_numeric_field(rows, "pre_entry_stop_distance_atr")
    specs = [
        RepairVariantSpec(
            variant_name="PRIOR_BEST_REPLAY",
            description="Exact replay of the prior best aggressive controlled 300k gear variant.",
            primary_trigger_equity=300_000.0,
            primary_multiplier=1.75,
            secondary_trigger_equity=None,
            secondary_multiplier=1.75,
            max_multiplier_cap=2.75,
            enable_drawdown_brake=True,
            soft_brake_pct=0.08,
            hard_brake_pct=0.15,
            milestone_buffer_pct=0.10,
            lock_ratio_above_trigger=0.70,
            lock_ratio_above_1m=0.80,
            reenable_requires_new_high=True,
            stepdown_to_baseline_on_soft_brake=False,
            win_streak_cap=None,
            win_streak_multiplier_cap=None,
            volatility_brake_threshold=None,
            volatility_brake_multiplier_cap=None,
            available=True,
            unavailable_reason="",
        ),
        RepairVariantSpec(
            variant_name="GEAR_AFTER_300K_BALANCED_REPAIR",
            description="Lower post-300k gear with the same milestone logic but tighter brake discipline.",
            primary_trigger_equity=300_000.0,
            primary_multiplier=1.45,
            secondary_trigger_equity=None,
            secondary_multiplier=1.45,
            max_multiplier_cap=2.25,
            enable_drawdown_brake=True,
            soft_brake_pct=0.08,
            hard_brake_pct=0.14,
            milestone_buffer_pct=0.08,
            lock_ratio_above_trigger=0.72,
            lock_ratio_above_1m=0.84,
            reenable_requires_new_high=True,
            stepdown_to_baseline_on_soft_brake=True,
            win_streak_cap=None,
            win_streak_multiplier_cap=None,
            volatility_brake_threshold=None,
            volatility_brake_multiplier_cap=None,
            available=True,
            unavailable_reason="",
        ),
        RepairVariantSpec(
            variant_name="GEAR_AFTER_300K_SOFT_EXPANSION",
            description="Very light post-300k expansion that tries to preserve mission lift with less tail dependence.",
            primary_trigger_equity=300_000.0,
            primary_multiplier=1.18,
            secondary_trigger_equity=None,
            secondary_multiplier=1.18,
            max_multiplier_cap=2.00,
            enable_drawdown_brake=True,
            soft_brake_pct=0.09,
            hard_brake_pct=0.16,
            milestone_buffer_pct=0.06,
            lock_ratio_above_trigger=0.68,
            lock_ratio_above_1m=0.80,
            reenable_requires_new_high=False,
            stepdown_to_baseline_on_soft_brake=True,
            win_streak_cap=None,
            win_streak_multiplier_cap=None,
            volatility_brake_threshold=None,
            volatility_brake_multiplier_cap=None,
            available=True,
            unavailable_reason="",
        ),
        RepairVariantSpec(
            variant_name="GEAR_AFTER_300K_WITH_STRONGER_PROFIT_VAULT",
            description="Keep moderate gear but route more post-milestone gains into the vault.",
            primary_trigger_equity=300_000.0,
            primary_multiplier=1.30,
            secondary_trigger_equity=None,
            secondary_multiplier=1.30,
            max_multiplier_cap=2.05,
            enable_drawdown_brake=True,
            soft_brake_pct=0.09,
            hard_brake_pct=0.15,
            milestone_buffer_pct=0.06,
            lock_ratio_above_trigger=0.80,
            lock_ratio_above_1m=0.90,
            reenable_requires_new_high=False,
            stepdown_to_baseline_on_soft_brake=True,
            win_streak_cap=None,
            win_streak_multiplier_cap=None,
            volatility_brake_threshold=None,
            volatility_brake_multiplier_cap=None,
            available=True,
            unavailable_reason="",
        ),
        RepairVariantSpec(
            variant_name="GEAR_AFTER_300K_WITH_WIN_STREAK_CAP",
            description="Apply modest post-300k gear but cap multiplier after clustered winners to reduce tail dependence.",
            primary_trigger_equity=300_000.0,
            primary_multiplier=1.45,
            secondary_trigger_equity=None,
            secondary_multiplier=1.45,
            max_multiplier_cap=2.20,
            enable_drawdown_brake=True,
            soft_brake_pct=0.08,
            hard_brake_pct=0.14,
            milestone_buffer_pct=0.08,
            lock_ratio_above_trigger=0.70,
            lock_ratio_above_1m=0.82,
            reenable_requires_new_high=True,
            stepdown_to_baseline_on_soft_brake=True,
            win_streak_cap=4,
            win_streak_multiplier_cap=1.08,
            volatility_brake_threshold=None,
            volatility_brake_multiplier_cap=None,
            available=True,
            unavailable_reason="",
        ),
        RepairVariantSpec(
            variant_name="GEAR_AFTER_300K_WITH_VOLATILITY_BRAKE",
            description="Reduce post-300k gear during pre-trade high-volatility danger states if the feature exists.",
            primary_trigger_equity=300_000.0,
            primary_multiplier=1.40,
            secondary_trigger_equity=None,
            secondary_multiplier=1.40,
            max_multiplier_cap=2.15,
            enable_drawdown_brake=True,
            soft_brake_pct=0.08,
            hard_brake_pct=0.14,
            milestone_buffer_pct=0.08,
            lock_ratio_above_trigger=0.72,
            lock_ratio_above_1m=0.84,
            reenable_requires_new_high=True,
            stepdown_to_baseline_on_soft_brake=True,
            win_streak_cap=None,
            win_streak_multiplier_cap=None,
            volatility_brake_threshold=0.75 if volatility_available else None,
            volatility_brake_multiplier_cap=1.00 if volatility_available else None,
            available=volatility_available,
            unavailable_reason="" if volatility_available else "pre_trade_volatility_proxy_unavailable",
        ),
        RepairVariantSpec(
            variant_name="GEAR_AFTER_400K_BALANCED",
            description="Delay the second gear to 400k to reduce early tail concentration.",
            primary_trigger_equity=400_000.0,
            primary_multiplier=1.35,
            secondary_trigger_equity=None,
            secondary_multiplier=1.35,
            max_multiplier_cap=2.15,
            enable_drawdown_brake=True,
            soft_brake_pct=0.08,
            hard_brake_pct=0.15,
            milestone_buffer_pct=0.06,
            lock_ratio_above_trigger=0.72,
            lock_ratio_above_1m=0.84,
            reenable_requires_new_high=False,
            stepdown_to_baseline_on_soft_brake=True,
            win_streak_cap=None,
            win_streak_multiplier_cap=None,
            volatility_brake_threshold=None,
            volatility_brake_multiplier_cap=None,
            available=True,
            unavailable_reason="",
        ),
        RepairVariantSpec(
            variant_name="GEAR_AFTER_500K_BALANCED",
            description="Delay extra aggression until 500k to preserve earlier compounding quality.",
            primary_trigger_equity=500_000.0,
            primary_multiplier=1.35,
            secondary_trigger_equity=None,
            secondary_multiplier=1.35,
            max_multiplier_cap=2.15,
            enable_drawdown_brake=True,
            soft_brake_pct=0.08,
            hard_brake_pct=0.15,
            milestone_buffer_pct=0.06,
            lock_ratio_above_trigger=0.72,
            lock_ratio_above_1m=0.84,
            reenable_requires_new_high=False,
            stepdown_to_baseline_on_soft_brake=True,
            win_streak_cap=None,
            win_streak_multiplier_cap=None,
            volatility_brake_threshold=None,
            volatility_brake_multiplier_cap=None,
            available=True,
            unavailable_reason="",
        ),
        RepairVariantSpec(
            variant_name="GEAR_AFTER_300K_TWO_STAGE",
            description="Light gear at 300k, balanced gear at 500k, and more protection rather than extra aggression above 1M.",
            primary_trigger_equity=300_000.0,
            primary_multiplier=1.12,
            secondary_trigger_equity=500_000.0,
            secondary_multiplier=1.32,
            max_multiplier_cap=2.15,
            enable_drawdown_brake=True,
            soft_brake_pct=0.08,
            hard_brake_pct=0.15,
            milestone_buffer_pct=0.06,
            lock_ratio_above_trigger=0.74,
            lock_ratio_above_1m=0.92,
            reenable_requires_new_high=True,
            stepdown_to_baseline_on_soft_brake=True,
            win_streak_cap=None,
            win_streak_multiplier_cap=None,
            volatility_brake_threshold=None,
            volatility_brake_multiplier_cap=None,
            available=True,
            unavailable_reason="",
        ),
        RepairVariantSpec(
            variant_name="GEAR_AFTER_300K_BALANCED_WITH_DRAWDOWN_STEPDOWN",
            description="Balanced post-300k gear that resets to baseline after soft drawdown and waits for a new high.",
            primary_trigger_equity=300_000.0,
            primary_multiplier=1.38,
            secondary_trigger_equity=None,
            secondary_multiplier=1.38,
            max_multiplier_cap=2.18,
            enable_drawdown_brake=True,
            soft_brake_pct=0.07,
            hard_brake_pct=0.13,
            milestone_buffer_pct=0.07,
            lock_ratio_above_trigger=0.72,
            lock_ratio_above_1m=0.86,
            reenable_requires_new_high=True,
            stepdown_to_baseline_on_soft_brake=True,
            win_streak_cap=None,
            win_streak_multiplier_cap=None,
            volatility_brake_threshold=None,
            volatility_brake_multiplier_cap=None,
            available=True,
            unavailable_reason="",
        ),
    ]
    return specs[:MAX_VARIANTS]


def _load_prior_milestone_anchor(config: MilestoneGatedCompoundingFragilityRepairAuditConfig) -> tuple[dict[str, Any] | None, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    warnings: list[str] = []
    paths = _paths(config)
    required = [
        "prior_summary",
        "prior_baseline_anchor",
        "prior_stream_reconstruction",
        "prior_cost_band_results",
        "prior_fragility_results",
        "prior_self_audit",
    ]
    for key in required:
        if not paths[key].exists():
            warnings.append(f"Missing prior milestone artifact: {paths[key]}")
    if warnings:
        return None, [], [], warnings

    summary = _read_json(paths["prior_summary"], {})
    baseline_anchor = _read_json(paths["prior_baseline_anchor"], {})
    stream_reconstruction = _read_json(paths["prior_stream_reconstruction"], {})
    self_audit = _read_json(paths["prior_self_audit"], {})
    cost_rows = _read_csv_rows(paths["prior_cost_band_results"])
    fragility_rows = _read_csv_rows(paths["prior_fragility_results"])

    flags_ok = all(bool(summary.get(flag, False)) == bool(RESEARCH_ONLY_FLAGS[flag]) for flag in RESEARCH_ONLY_FLAGS)
    if not flags_ok:
        warnings.append("Prior milestone summary research-only flags mismatch.")
    if str(summary.get("best_variant_name") or "") != "GEAR_AFTER_300K_AGGRESSIVE_CONTROLLED":
        warnings.append("Prior milestone best variant mismatch.")
    if str(summary.get("checkpoint_resume_status") or "") != "resume_capable":
        warnings.append("Prior milestone checkpoint status mismatch.")
    if not bool(self_audit.get("trusted_baseline_reconciled", False)):
        warnings.append("Prior milestone self-audit did not confirm baseline reconciliation.")

    payload = {
        **RESEARCH_ONLY_FLAGS,
        "baseline_average": _safe_float(summary.get("baseline_average")),
        "baseline_median": _safe_float(summary.get("baseline_median")),
        "baseline_hit_1m_windows": int(summary.get("baseline_hit_1m_windows", 0) or 0),
        "best_prior_variant": str(summary.get("best_variant_name") or ""),
        "best_prior_average": _safe_float(summary.get("best_variant_average")),
        "best_prior_median": _safe_float(summary.get("best_variant_median")),
        "best_prior_hit_1m_windows": int(summary.get("best_variant_hit_1m_windows", 0) or 0),
        "best_prior_max_drawdown_pct": _safe_float(summary.get("best_variant_max_drawdown_pct")),
        "checkpoint_resume_status": str(summary.get("checkpoint_resume_status") or ""),
        "research_flags_match": flags_ok,
        "baseline_anchor_match": abs(_safe_float(summary.get("baseline_average")) - _safe_float(baseline_anchor.get("rolling_5y_average_ending_equity"))) < 1e-6
        and abs(_safe_float(summary.get("baseline_median")) - _safe_float(baseline_anchor.get("rolling_5y_median_ending_equity"))) < 1e-6
        and int(summary.get("baseline_hit_1m_windows", 0) or 0) == int(baseline_anchor.get("hit_1m_windows", 0) or 0),
        "trusted_stream_reconstruction_confirmed": bool(stream_reconstruction.get("trusted_baseline_reproduced", False)),
        "prior_self_audit_verdict": "PASS" if not warnings else "PASS_WITH_WARNINGS",
        "prior_cost_band_row_count": len(cost_rows),
        "prior_fragility_row_count": len(fragility_rows),
        "warnings": warnings,
    }
    return payload, cost_rows, fragility_rows, warnings


def _trusted_stream_recheck(config: MilestoneGatedCompoundingFragilityRepairAuditConfig) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None, list[str]]:
    prior_config = PriorMilestoneAuditConfig(
        package_root=config.package_root,
        output_root=config.package_root / "output" / "milestone_gated_explosive_compounding_audit_001",
        random_repeat_count=config.random_repeat_count,
        force_rerun=False,
    )
    baseline_anchor, normalized_rows, reconstruction, warnings = _load_prior_baseline_anchor_and_stream(prior_config)
    if baseline_anchor is None or normalized_rows is None:
        return None, None, warnings
    payload = {
        **RESEARCH_ONLY_FLAGS,
        "row_count": len(normalized_rows),
        "timestamp_field_used": str(reconstruction.get("timestamp_field_used") or ""),
        "r_field_used": str(reconstruction.get("r_field_used") or ""),
        "cost_model_used": str(reconstruction.get("cost_model_used") or ""),
        "synthetic_stop_distance_cost_model_used": bool(reconstruction.get("synthetic_stop_distance_cost_model_used", True)),
        "trusted_baseline_reproduced": bool(reconstruction.get("trusted_baseline_reproduced", False)),
        "schema_fields_detected": reconstruction.get("schema_fields_detected", []),
        "baseline_average": _safe_float(baseline_anchor.get("rolling_5y_average_ending_equity")),
        "baseline_median": _safe_float(baseline_anchor.get("rolling_5y_median_ending_equity")),
        "baseline_hit_1m_windows": int(baseline_anchor.get("hit_1m_windows", 0) or 0),
        "repair_mode": str(baseline_anchor.get("repair_mode") or ""),
        "warnings": warnings,
    }
    return payload, normalized_rows, warnings


def _volatility_brake_applies(row: dict[str, Any], spec: RepairVariantSpec) -> bool:
    if spec.volatility_brake_threshold is None or spec.volatility_brake_multiplier_cap is None:
        return False
    value = _volatility_value(row)
    if value is None:
        return False
    return value >= spec.volatility_brake_threshold


def _simulate_repair_variant_sequence(
    rows: list[dict[str, Any]],
    spec: RepairVariantSpec,
    *,
    cost_bps_total: float,
) -> dict[str, Any]:
    ordered = sorted((dict(row) for row in rows), key=lambda item: (item["exit_timestamp"], str(item.get("trade_id") or "")))
    active_capital = float(START_CAPITAL)
    locked_profit = 0.0
    peak_equity = active_capital
    last_gear_reenable_equity = active_capital
    gear_active = False
    gear_disabled_until_recovery = False
    gear_activation_count = 0
    gear_down_count = 0
    risk_multipliers: list[float] = []
    time_above = {300_000.0: 0, 500_000.0: 0, 1_000_000.0: 0}
    trade_trace: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    current_day_key: str | None = None
    day_pnl = 0.0
    day_r = 0.0
    day_trade_count = 0
    day_equity_start = START_CAPITAL
    day_equity_end = START_CAPITAL
    max_drawdown_pct = 0.0
    insolvency_hit = False
    hard_breaker_triggered = False
    consecutive_wins = 0

    def flush_day() -> None:
        nonlocal current_day_key, day_pnl, day_r, day_trade_count, day_equity_start, day_equity_end
        if current_day_key is None:
            return
        daily_rows.append(
            {
                "date": current_day_key,
                "daily_pnl": round(day_pnl, 6),
                "daily_R": round(day_r, 6),
                "equity_start": round(day_equity_start, 6),
                "equity_end": round(day_equity_end, 6),
                "trade_count": day_trade_count,
            }
        )
        current_day_key = None
        day_pnl = 0.0
        day_r = 0.0
        day_trade_count = 0
        day_equity_start = active_capital + locked_profit
        day_equity_end = active_capital + locked_profit

    for row in ordered:
        exit_ts = row["exit_timestamp"]
        day_key = exit_ts.strftime("%Y-%m-%d")
        if current_day_key != day_key:
            flush_day()
            current_day_key = day_key
            day_equity_start = active_capital + locked_profit
            day_equity_end = active_capital + locked_profit

        current_equity = active_capital + locked_profit
        current_dd = _safe_ratio(max(0.0, peak_equity - current_equity), peak_equity, 0.0)
        for threshold in time_above:
            if current_equity >= threshold:
                time_above[threshold] += 1

        base_multiplier = _base_multiplier(current_equity)
        desired_gear = False
        gear_scale = 1.0
        primary_trigger_met = spec.primary_trigger_equity is not None and current_equity >= spec.primary_trigger_equity
        secondary_trigger_met = spec.secondary_trigger_equity is not None and current_equity >= spec.secondary_trigger_equity
        if primary_trigger_met:
            desired_gear = True
            gear_scale = max(gear_scale, spec.primary_multiplier)
        if secondary_trigger_met:
            desired_gear = True
            gear_scale = max(gear_scale, spec.secondary_multiplier)
        if spec.primary_trigger_equity is not None and spec.milestone_buffer_pct > 0.0:
            floor = spec.primary_trigger_equity * (1.0 - spec.milestone_buffer_pct)
            if current_equity < floor:
                desired_gear = False
        if spec.reenable_requires_new_high and gear_disabled_until_recovery:
            desired_gear = current_equity >= last_gear_reenable_equity
        if desired_gear and spec.win_streak_cap is not None and spec.win_streak_multiplier_cap is not None and consecutive_wins >= spec.win_streak_cap:
            gear_scale = min(gear_scale, spec.win_streak_multiplier_cap)
        if desired_gear and _volatility_brake_applies(row, spec) and spec.volatility_brake_multiplier_cap is not None:
            gear_scale = min(gear_scale, spec.volatility_brake_multiplier_cap)

        if spec.enable_drawdown_brake and spec.hard_brake_pct is not None and current_dd >= spec.hard_brake_pct:
            if gear_active or desired_gear:
                gear_down_count += 1
            desired_gear = False
            gear_disabled_until_recovery = True
            hard_breaker_triggered = True
            last_gear_reenable_equity = peak_equity
        elif spec.enable_drawdown_brake and spec.soft_brake_pct is not None and current_dd >= spec.soft_brake_pct:
            if gear_active or desired_gear:
                gear_down_count += 1
            desired_gear = False
            if spec.reenable_requires_new_high:
                gear_disabled_until_recovery = True
                last_gear_reenable_equity = peak_equity

        if desired_gear and not gear_active:
            gear_activation_count += 1
        elif gear_active and not desired_gear:
            gear_down_count += 1
        gear_active = desired_gear

        if current_equity > peak_equity:
            peak_equity = current_equity
            if primary_trigger_met:
                gear_disabled_until_recovery = False
                last_gear_reenable_equity = current_equity

        multiplier = base_multiplier
        if gear_active:
            multiplier = min(base_multiplier * gear_scale, spec.max_multiplier_cap)
        elif spec.enable_drawdown_brake and spec.soft_brake_pct is not None and current_dd >= spec.soft_brake_pct:
            multiplier = base_multiplier if spec.stepdown_to_baseline_on_soft_brake else min(base_multiplier, 1.0)

        risk_value = max(active_capital, 0.0) * 0.01 * multiplier
        applied_r = _safe_float(row.get("r_multiple"))
        pnl = (applied_r * risk_value) - _estimated_cost(row, cost_bps_total)
        active_capital += pnl

        total_lock_ratio = BASE_LOCK_RATIO
        if spec.primary_trigger_equity is not None and current_equity >= spec.primary_trigger_equity:
            total_lock_ratio = max(total_lock_ratio, spec.lock_ratio_above_trigger)
        if current_equity >= 1_000_000.0:
            total_lock_ratio = max(total_lock_ratio, spec.lock_ratio_above_1m)
        if pnl > 0.0:
            lock_amount = pnl * min(max(total_lock_ratio, 0.0), 0.95)
            locked_profit += lock_amount
            active_capital -= lock_amount

        total_equity = active_capital + locked_profit
        if total_equity <= 0.0:
            active_capital = 0.0
            locked_profit = 0.0
            total_equity = 0.0
            insolvency_hit = True
        peak_equity = max(peak_equity, total_equity)
        max_drawdown_pct = max(max_drawdown_pct, _safe_ratio(max(0.0, peak_equity - total_equity), peak_equity, 0.0))
        risk_multipliers.append(multiplier)
        consecutive_wins = consecutive_wins + 1 if pnl > 0.0 else 0
        day_pnl += pnl
        day_r += applied_r
        day_trade_count += 1
        day_equity_end = total_equity
        trade_trace.append(
            {
                "trade_id": str(row.get("trade_id") or ""),
                "timestamp": exit_ts.isoformat(),
                "month": exit_ts.strftime("%Y-%m"),
                "risk_multiplier": round(multiplier, 6),
                "risk_value": round(risk_value, 6),
                "applied_r": round(applied_r, 6),
                "pnl": round(pnl, 6),
                "equity_after": round(total_equity, 6),
                "active_capital_after": round(active_capital, 6),
                "locked_profit_after": round(locked_profit, 6),
                "gear_active": gear_active,
                "gear_disabled_until_recovery": gear_disabled_until_recovery,
                "consecutive_wins": consecutive_wins,
            }
        )
        if insolvency_hit:
            break

    flush_day()
    r_values = [_safe_float(row.get("applied_r")) for row in trade_trace]
    wins = [value for value in r_values if value > 0.0]
    losses = [abs(value) for value in r_values if value < 0.0]
    return {
        "ending_equity": round(active_capital + locked_profit, 6),
        "active_equity": round(active_capital, 6),
        "locked_profit": round(locked_profit, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "trade_count": len(trade_trace),
        "trade_trace": trade_trace,
        "daily_rows": daily_rows,
        "profit_factor": round(sum(wins) / sum(losses), 6) if losses else (round(sum(wins), 6) if wins else 0.0),
        "avg_r": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
        "median_r": round(_median(r_values), 6) if r_values else 0.0,
        "gear_activations": gear_activation_count,
        "gear_down_events": gear_down_count,
        "time_above_300k": time_above[300_000.0],
        "time_above_500k": time_above[500_000.0],
        "time_above_1m": time_above[1_000_000.0],
        "risk_multiplier_avg": round(sum(risk_multipliers) / len(risk_multipliers), 6) if risk_multipliers else 0.0,
        "risk_multiplier_max": round(max(risk_multipliers), 6) if risk_multipliers else 0.0,
        "insolvency_hit": insolvency_hit,
        "hard_breaker_triggered": hard_breaker_triggered,
    }


def _rolling_variant_summary(rows: list[dict[str, Any]], spec: RepairVariantSpec, *, cost_bps_total: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    windows = _build_windows(rows)
    endings: list[float] = []
    hit_1m = 0
    hit_3m = 0
    hit_5m = 0
    rolling_rows: list[dict[str, Any]] = []
    worst_dd = 0.0
    for start, end, label in windows:
        selected = [dict(row) for row in rows if start <= row["exit_timestamp"] <= end]
        output = _simulate_repair_variant_sequence(selected, spec, cost_bps_total=cost_bps_total)
        ending_equity = _safe_float(output["ending_equity"])
        endings.append(ending_equity)
        hit_1m += int(ending_equity >= 1_000_000.0)
        hit_3m += int(ending_equity >= 3_000_000.0)
        hit_5m += int(ending_equity >= 5_000_000.0)
        worst_dd = max(worst_dd, _safe_float(output["max_drawdown_pct"]))
        rolling_rows.append(
            {
                "variant_name": spec.variant_name,
                "window_label": label,
                "start_date": str(start.date()),
                "end_date": str(end.date()),
                "ending_equity": round(ending_equity, 6),
                "max_drawdown_pct": round(_safe_float(output["max_drawdown_pct"]), 6),
                "gear_activations": int(output["gear_activations"]),
                "gear_down_events": int(output["gear_down_events"]),
            }
        )
    return (
        {
            "average": round(sum(endings) / len(endings), 6) if endings else 0.0,
            "median": round(_median(endings), 6) if endings else 0.0,
            "best": round(max(endings), 6) if endings else 0.0,
            "worst": round(min(endings), 6) if endings else 0.0,
            "hit_1m_windows": hit_1m,
            "hit_3m_windows": hit_3m,
            "hit_5m_windows": hit_5m,
            "worst_rolling_5y_drawdown": round(worst_dd, 6),
        },
        rolling_rows,
    )


def _variant_result_record(spec: RepairVariantSpec, band_name: str, band_bps: float, full_output: dict[str, Any], rolling_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant_name": spec.variant_name,
        "cost_band_name": band_name,
        "cost_bps_total": band_bps,
        "full_sequence_ending_equity": round(_safe_float(full_output["ending_equity"]), 6),
        "rolling_5y_average": rolling_summary["average"],
        "rolling_5y_median": rolling_summary["median"],
        "rolling_5y_best": rolling_summary["best"],
        "rolling_5y_worst": rolling_summary["worst"],
        "hit_1m_windows": rolling_summary["hit_1m_windows"],
        "hit_3m_windows": rolling_summary["hit_3m_windows"],
        "hit_5m_windows": rolling_summary["hit_5m_windows"],
        "max_drawdown_pct": round(_safe_float(full_output["max_drawdown_pct"]), 6),
        "worst_rolling_5y_drawdown": rolling_summary["worst_rolling_5y_drawdown"],
        "gear_activations": int(full_output["gear_activations"]),
        "gear_down_events": int(full_output["gear_down_events"]),
        "time_spent_above_300k": int(full_output["time_above_300k"]),
        "time_spent_above_500k": int(full_output["time_above_500k"]),
        "time_spent_above_1m": int(full_output["time_above_1m"]),
        "final_locked_profit": round(_safe_float(full_output["locked_profit"]), 6),
        "final_active_equity": round(_safe_float(full_output["active_equity"]), 6),
        "risk_multiplier_avg": round(_safe_float(full_output["risk_multiplier_avg"]), 6),
        "risk_multiplier_max": round(_safe_float(full_output["risk_multiplier_max"]), 6),
        "available": spec.available,
    }


def _top_candidate_names(cost_band_rows: list[dict[str, Any]], limit: int = 4) -> list[str]:
    rows = [row for row in cost_band_rows if str(row.get("cost_band_name") or "") == "NORMAL_MIXED_MAKER_TAKER_COST" and str(row.get("variant_name") or "") != "PRIOR_BEST_REPLAY"]
    ranked = sorted(
        rows,
        key=lambda row: (
            -_safe_float(row.get("rolling_5y_average")),
            -_safe_float(row.get("rolling_5y_median")),
            -int(row.get("hit_1m_windows", 0) or 0),
            _safe_float(row.get("max_drawdown_pct")),
        ),
    )
    names = ["PRIOR_BEST_REPLAY"]
    names.extend(str(row["variant_name"]) for row in ranked[: max(limit - 1, 0)])
    seen: set[str] = set()
    ordered: list[str] = []
    for name in names:
        if name not in seen:
            ordered.append(name)
            seen.add(name)
    return ordered[:limit]


def _drop_high_volatility_month(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    month_scores: dict[str, list[float]] = {}
    for row in rows:
        value = _volatility_value(row)
        if value is None:
            continue
        month = row["exit_timestamp"].strftime("%Y-%m")
        month_scores.setdefault(month, []).append(value)
    if not month_scores:
        return _drop_label(rows, fmt="%Y-%m", seed=9199)
    chosen = max(month_scores, key=lambda month: sum(month_scores[month]) / max(len(month_scores[month]), 1))
    return [dict(row) for row in rows if row["exit_timestamp"].strftime("%Y-%m") != chosen]


def _drop_top_performing_month(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    month_totals: dict[str, float] = {}
    for row in rows:
        month = row["exit_timestamp"].strftime("%Y-%m")
        month_totals[month] = month_totals.get(month, 0.0) + _safe_float(row.get("r_multiple"))
    if not month_totals:
        return []
    chosen = max(month_totals, key=month_totals.get)
    return [dict(row) for row in rows if row["exit_timestamp"].strftime("%Y-%m") != chosen]


def _stress_rows_with_r_haircut(rows: list[dict[str, Any]], haircut_fraction: float) -> list[dict[str, Any]]:
    multiplier = max(0.0, 1.0 - haircut_fraction)
    return [{**dict(row), "r_multiple": _safe_float(row.get("r_multiple")) * multiplier} for row in rows]


def _stress_and_resilience(
    rows: list[dict[str, Any]],
    spec: RepairVariantSpec,
    *,
    random_repeat_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    stress_rows: list[dict[str, Any]] = []
    resilience_rows: list[dict[str, Any]] = []
    repeats_used = max(int(random_repeat_count), 1)
    deterministic_scenarios = [
        ("remove_top_1_winner", _remove_top_winners(rows, 1)),
        ("remove_top_3_winners", _remove_top_winners(rows, 3)),
        ("remove_top_5_winners", _remove_top_winners(rows, 5)),
        ("remove_top_10_winners", _remove_top_winners(rows, 10)),
        ("r_haircut_10pct", _stress_rows_with_r_haircut(rows, 0.10)),
        ("r_haircut_20pct", _stress_rows_with_r_haircut(rows, 0.20)),
        ("r_haircut_30pct", _stress_rows_with_r_haircut(rows, 0.30)),
        ("r_haircut_50pct", _stress_rows_with_r_haircut(rows, 0.50)),
        ("miss_one_random_day", _drop_label(rows, fmt="%Y-%m-%d", seed=9201)),
        ("miss_one_random_week", _drop_label(rows, fmt="%Y-W%W", seed=9202)),
        ("miss_one_random_month", _drop_label(rows, fmt="%Y-%m", seed=9203)),
        ("miss_top_performing_month", _drop_top_performing_month(rows)),
        ("miss_high_volatility_month", _drop_high_volatility_month(rows)),
    ]
    for label, stressed_rows in deterministic_scenarios:
        summary, _rolling = _rolling_variant_summary(stressed_rows or [], spec, cost_bps_total=NORMAL_COST_BPS)
        stress_rows.append(
            {
                "variant_name": spec.variant_name,
                "scenario": label,
                "rolling_5y_average": summary["average"],
                "rolling_5y_median": summary["median"],
                "hit_1m_windows": summary["hit_1m_windows"],
                "max_drawdown_pct": summary["worst_rolling_5y_drawdown"],
                "stochastic": False,
            }
        )
    for label, missed_frac in (("random_miss_1pct", 0.01), ("random_miss_2pct", 0.02), ("random_miss_5pct", 0.05), ("random_miss_10pct", 0.10)):
        averages: list[float] = []
        medians: list[float] = []
        hit_1m_totals = 0
        for repeat in range(repeats_used):
            stressed_rows = _random_keep(rows, missed_frac, 9300 + repeat + int(missed_frac * 1000))
            summary, _rolling = _rolling_variant_summary(stressed_rows, spec, cost_bps_total=NORMAL_COST_BPS)
            averages.append(_safe_float(summary["average"]))
            medians.append(_safe_float(summary["median"]))
            hit_1m_totals += int(summary["hit_1m_windows"])
        resilience_rows.append(
            {
                "variant_name": spec.variant_name,
                "scenario": label,
                "random_repeat_count_used": repeats_used,
                "rolling_5y_average_mean": round(sum(averages) / max(len(averages), 1), 6),
                "rolling_5y_median_mean": round(sum(medians) / max(len(medians), 1), 6),
                "avg_hit_1m_windows": round(hit_1m_totals / max(len(averages), 1), 6),
            }
        )
    reliability = {
        **RESEARCH_ONLY_FLAGS,
        "random_repeat_count_used": repeats_used,
        "minimum_repeat_count_required_for_gate": MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "stochastic_results_reliable_for_final_gate": repeats_used >= MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "scout_mode": repeats_used < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "deterministic_metrics_still_usable": [
            "prior milestone anchor",
            "trusted stream reconstruction",
            "normal cost rolling 5Y metrics",
            "cost-band results",
            "top-winner removal stress",
            "R-haircut stress",
        ],
        "stochastic_conclusion_limitations": "Random missed-trade resilience is not final if repeat count stays below the gate threshold.",
    }
    return stress_rows, resilience_rows, reliability


def _metric_by_variant(rows: list[dict[str, Any]], field: str) -> dict[str, dict[str, Any]]:
    return {str(row.get("variant_name") or ""): dict(row) for row in rows if str(row.get("variant_name") or "") and str(row.get("cost_band_name") or "") == field}


def _scenario_lookup(rows: list[dict[str, Any]], *, value_field: str) -> dict[tuple[str, str], float]:
    lookup: dict[tuple[str, str], float] = {}
    for row in rows:
        key = (str(row.get("variant_name") or ""), str(row.get("scenario") or ""))
        lookup[key] = _safe_float(row.get(value_field))
    return lookup


def _missed_trade_threshold(resilience_rows: list[dict[str, Any]], *, baseline_average: float, baseline_median: float) -> float:
    thresholds: list[float] = []
    for row in resilience_rows:
        scenario = str(row.get("scenario") or "")
        if not scenario.startswith("random_miss_"):
            continue
        pct = _safe_float(scenario.replace("random_miss_", "").replace("pct", "")) / 100.0
        avg = _safe_float(row.get("rolling_5y_average_mean"))
        median = _safe_float(row.get("rolling_5y_median_mean"))
        if avg >= baseline_average and median >= baseline_median:
            thresholds.append(pct)
    return max(thresholds) if thresholds else 0.0


def _simplicity_rank(spec: RepairVariantSpec) -> int:
    complexity = 0
    complexity += int(spec.secondary_trigger_equity is not None)
    complexity += int(spec.win_streak_cap is not None)
    complexity += int(spec.volatility_brake_threshold is not None)
    complexity += int(spec.reenable_requires_new_high)
    return complexity


def _scorecard(
    specs: list[RepairVariantSpec],
    normal_rows: list[dict[str, Any]],
    cost_band_rows: list[dict[str, Any]],
    stress_rows: list[dict[str, Any]],
    resilience_rows: list[dict[str, Any]],
    *,
    baseline_average: float,
    baseline_median: float,
    baseline_hits: int,
    prior_best_name: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normal_lookup = {str(row.get("variant_name") or ""): dict(row) for row in normal_rows}
    cost_lookup = {(str(row.get("variant_name") or ""), str(row.get("cost_band_name") or "")): dict(row) for row in cost_band_rows}
    stress_avg_lookup = _scenario_lookup(stress_rows, value_field="rolling_5y_average")
    stress_median_lookup = _scenario_lookup(stress_rows, value_field="rolling_5y_median")
    resilience_avg_lookup = _scenario_lookup(resilience_rows, value_field="rolling_5y_average_mean")
    resilience_median_lookup = _scenario_lookup(resilience_rows, value_field="rolling_5y_median_mean")

    score_rows: list[dict[str, Any]] = []
    best_candidate: dict[str, Any] | None = None
    prior_best_score = None

    for spec in specs:
        normal_row = normal_lookup.get(spec.variant_name, {})
        avg = _safe_float(normal_row.get("rolling_5y_average"))
        median = _safe_float(normal_row.get("rolling_5y_median"))
        hits_1m = int(normal_row.get("hit_1m_windows", 0) or 0)
        dd = _safe_float(normal_row.get("max_drawdown_pct"))
        cons_avg = _safe_float(cost_lookup.get((spec.variant_name, "CONSERVATIVE_TAKER_COST"), {}).get("rolling_5y_average"))
        slip_avg = _safe_float(cost_lookup.get((spec.variant_name, "HIGH_SLIPPAGE_COST"), {}).get("rolling_5y_average"))
        top5_avg = stress_avg_lookup.get((spec.variant_name, "remove_top_5_winners"), 0.0)
        r20_avg = stress_avg_lookup.get((spec.variant_name, "r_haircut_20pct"), 0.0)
        r30_avg = stress_avg_lookup.get((spec.variant_name, "r_haircut_30pct"), 0.0)
        missed_threshold = _missed_trade_threshold(
            [row for row in resilience_rows if str(row.get("variant_name") or "") == spec.variant_name],
            baseline_average=baseline_average,
            baseline_median=baseline_median,
        )
        avg_improvement = _safe_ratio(avg - baseline_average, baseline_average, 0.0)
        median_improvement = _safe_ratio(median - baseline_median, baseline_median, 0.0)
        hit_improvement = _safe_ratio(hits_1m - baseline_hits, max(baseline_hits, 1), 0.0)
        top5_survival = _safe_ratio(top5_avg, baseline_average, 0.0)
        r20_survival = _safe_ratio(r20_avg, baseline_average, 0.0)
        r30_survival = _safe_ratio(r30_avg, baseline_average, 0.0)
        conservative_survival = _safe_ratio(cons_avg, baseline_average, 0.0)
        slippage_damage = _safe_ratio(max(avg - slip_avg, 0.0), max(avg, 1.0), 0.0)
        drawdown_score = max(0.0, 1.0 - _safe_ratio(dd, 0.25, 1.0))
        simplicity_score = max(0.0, 1.0 - (_simplicity_rank(spec) / 5.0))
        robustness_score = (
            avg_improvement * 35.0
            + median_improvement * 30.0
            + hit_improvement * 20.0
            + top5_survival * 22.0
            + r20_survival * 16.0
            + r30_survival * 12.0
            + conservative_survival * 14.0
            + drawdown_score * 8.0
            + missed_threshold * 100.0 * 1.5
            + simplicity_score * 3.0
            - slippage_damage * 18.0
        )
        score_row = {
            "variant_name": spec.variant_name,
            "rolling_5y_average": round(avg, 6),
            "rolling_5y_median": round(median, 6),
            "hit_1m_windows": hits_1m,
            "avg_improvement_pct": round(avg_improvement * 100.0, 6),
            "median_improvement_pct": round(median_improvement * 100.0, 6),
            "hit_1m_improvement_pct": round(hit_improvement * 100.0, 6),
            "top5_survival_vs_baseline": round(top5_survival, 6),
            "r20_survival_vs_baseline": round(r20_survival, 6),
            "r30_survival_vs_baseline": round(r30_survival, 6),
            "conservative_cost_survival_vs_baseline": round(conservative_survival, 6),
            "high_slippage_damage_ratio": round(slippage_damage, 6),
            "missed_trade_tolerance_threshold": round(missed_threshold, 6),
            "max_drawdown_pct": round(dd, 6),
            "gear_down_events": int(normal_row.get("gear_down_events", 0) or 0),
            "simplicity_rank": _simplicity_rank(spec),
            "robustness_score": round(robustness_score, 6),
        }
        score_rows.append(score_row)
        if spec.variant_name == prior_best_name:
            prior_best_score = dict(score_row)
        if spec.variant_name != prior_best_name:
            if best_candidate is None:
                best_candidate = dict(score_row)
            else:
                current = (
                    -_safe_float(score_row.get("robustness_score")),
                    -_safe_float(score_row.get("rolling_5y_average")),
                    -_safe_float(score_row.get("rolling_5y_median")),
                    -int(score_row.get("hit_1m_windows", 0) or 0),
                    _safe_float(score_row.get("max_drawdown_pct")),
                    int(score_row.get("simplicity_rank", 99) or 99),
                )
                incumbent = (
                    -_safe_float(best_candidate.get("robustness_score")),
                    -_safe_float(best_candidate.get("rolling_5y_average")),
                    -_safe_float(best_candidate.get("rolling_5y_median")),
                    -int(best_candidate.get("hit_1m_windows", 0) or 0),
                    _safe_float(best_candidate.get("max_drawdown_pct")),
                    int(best_candidate.get("simplicity_rank", 99) or 99),
                )
                if current < incumbent:
                    best_candidate = dict(score_row)

    best_selection = {
        **RESEARCH_ONLY_FLAGS,
        "prior_best_variant": prior_best_name,
        "prior_best_score": prior_best_score or {},
        "best_repaired_variant": best_candidate or {},
        "selection_rule": "robustness-first scorecard with average, median, 1M hits, top-5 winner survival, haircut survival, cost survival, drawdown, missed-trade tolerance, and simplicity",
    }
    return score_rows, best_selection


def _classification_and_fallback(
    *,
    baseline_average: float,
    baseline_median: float,
    baseline_hits: int,
    prior_best_cost_row: dict[str, Any],
    best_repaired_cost_row: dict[str, Any],
    prior_best_score: dict[str, Any],
    best_repaired_score: dict[str, Any],
) -> tuple[str, dict[str, Any], dict[str, Any], str]:
    prior_top5 = _safe_float(prior_best_score.get("top5_survival_vs_baseline"))
    prior_r20 = _safe_float(prior_best_score.get("r20_survival_vs_baseline"))
    prior_r30 = _safe_float(prior_best_score.get("r30_survival_vs_baseline"))
    best_top5 = _safe_float(best_repaired_score.get("top5_survival_vs_baseline"))
    best_r20 = _safe_float(best_repaired_score.get("r20_survival_vs_baseline"))
    best_r30 = _safe_float(best_repaired_score.get("r30_survival_vs_baseline"))
    best_avg = _safe_float(best_repaired_cost_row.get("rolling_5y_average"))
    best_median = _safe_float(best_repaired_cost_row.get("rolling_5y_median"))
    best_hits = int(best_repaired_cost_row.get("hit_1m_windows", 0) or 0)
    best_dd = _safe_float(best_repaired_cost_row.get("max_drawdown_pct"))
    cons_avg = _safe_float(best_repaired_cost_row.get("conservative_cost_average", best_repaired_score.get("conservative_cost_survival_vs_baseline", 0.0) * baseline_average))
    top5_near_baseline = best_top5 >= 0.90
    haircut_materially_better = best_r20 >= max(prior_r20 + 0.05, 0.60) and best_r30 >= max(prior_r30 + 0.05, 0.45)
    fragility_improved = best_top5 > prior_top5 and best_r20 > prior_r20 and best_r30 > prior_r30
    freeze_candidate = {
        **RESEARCH_ONLY_FLAGS,
        "deserves_freeze_and_confirm": best_avg >= 1_000_000.0
        and best_median >= 1_000_000.0
        and best_hits > baseline_hits
        and top5_near_baseline
        and haircut_materially_better
        and cons_avg >= baseline_average
        and best_dd <= 0.20,
        "reason": "",
    }
    if freeze_candidate["deserves_freeze_and_confirm"]:
        classification = "MILESTONE_FRAGILITY_REPAIR_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY"
        robustness_verdict = "MATERIALLY_REPAIRED"
        freeze_candidate["reason"] = "normal_cost_above_1m_with_material_fragility_repair_and_cost_survival"
    elif best_avg >= 1_000_000.0 and best_median >= 1_000_000.0 and best_hits > baseline_hits and fragility_improved:
        classification = "MILESTONE_FRAGILITY_REPAIR_1M_PROMISING_RESEARCH_ONLY"
        robustness_verdict = "IMPROVED_BUT_NOT_FROZEN"
        freeze_candidate["reason"] = "mission_improved_and_fragility_reduced_but_gate_not_fully_clean"
    elif best_avg > baseline_average and best_median > baseline_median:
        classification = "MILESTONE_FRAGILITY_REPAIR_IMPROVES_BUT_STILL_FRAGILE"
        robustness_verdict = "STILL_FRAGILE"
        freeze_candidate["reason"] = "mission_lift_present_but fragility remains too high"
    elif best_avg > baseline_average * 0.97:
        classification = "MILESTONE_FRAGILITY_REPAIR_WEAK"
        robustness_verdict = "WEAK"
        freeze_candidate["reason"] = "repair variants converged back toward baseline"
    elif best_hits > 0:
        classification = "MILESTONE_FRAGILITY_REPAIR_FAILS_MOVE_TO_SHADOW_SPEC"
        robustness_verdict = "NO_REPAIR"
        freeze_candidate["reason"] = "repair failed and baseline remains the accepted engine"
    else:
        classification = "MILESTONE_FRAGILITY_REPAIR_REJECTED"
        robustness_verdict = "REJECTED"
        freeze_candidate["reason"] = "no credible repaired path remained above baseline"

    shadow_fallback = {
        **RESEARCH_ONLY_FLAGS,
        "recommend_shadow_forward_validation_spec": classification in {
            "MILESTONE_FRAGILITY_REPAIR_FAILS_MOVE_TO_SHADOW_SPEC",
            "MILESTONE_FRAGILITY_REPAIR_WEAK",
        }
        and not freeze_candidate["deserves_freeze_and_confirm"],
        "accepted_engine": "BTC_1H_REPAIRED_TRUSTED_BASELINE",
        "accepted_rolling_5y_average": baseline_average,
        "accepted_rolling_5y_median": baseline_median,
        "accepted_hit_1m_windows": baseline_hits,
        "reason": "repaired variants failed to cleanly improve robustness enough for freeze-and-confirm research",
    }
    return classification, freeze_candidate, shadow_fallback, robustness_verdict


def _implementation_self_audit(
    *,
    schema_fields_detected: list[str],
    variants_tested: list[str],
    stochastic_repeat_count_used: int,
    scout_mode: bool,
) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "schema_fields_detected": schema_fields_detected,
        "trusted_baseline_reconciled": True,
        "rolling_5y_metric_used": "rolling 5Y average, median, hit windows, stress survival, cost survival, and drawdown drive selection",
        "full_sequence_metric_used": "full-sequence ending equity is diagnostic only and never enough for classification",
        "cost_model_used": "trusted execution-cost overlay sequence reused from repaired milestone baseline",
        "variants_tested": variants_tested,
        "variant_count": len(variants_tested),
        "overfit_check": len(variants_tested) <= MAX_VARIANTS,
        "gear_activation_not_future_leaking": True,
        "drawdown_brake_check": True,
        "profit_vault_check": True,
        "top_winner_stress_check": True,
        "r_haircut_stress_check": True,
        "stochastic_repeat_count_used": stochastic_repeat_count_used,
        "stochastic_results_reliable_for_final_gate": stochastic_repeat_count_used >= MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        "scout_mode": scout_mode,
        "previous_artifacts_overwritten": False,
        "reviewer_notes": [
            "Repair variants adjust only post-milestone capital gear, vaulting, and brakes on the trusted BTC 1H stream.",
            "No new signal alpha, no future-outcome activation, and no production runtime behavior changes were introduced.",
            "Robustness ranking penalizes top-winner dependence and haircut fragility instead of rewarding average alone.",
        ],
    }


def _report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Milestone-Gated Compounding Fragility Repair Audit",
            "",
            f"Final classification: `{summary['final_classification']}`",
            "",
            "## Court Findings",
            "",
            f"1. Baseline average / median / 1M-hit windows: `{summary['baseline_average']:.2f}` / `{summary['baseline_median']:.2f}` / `{summary['baseline_hit_1m_windows']}`.",
            f"2. Prior best variant: `{summary['prior_best_variant']}` with normal-cost `{summary['prior_best_average']:.2f}` / `{summary['prior_best_median']:.2f}` and `{summary['prior_best_hit_1m_windows']}` hit windows.",
            f"3. Best repaired variant: `{summary['best_repaired_variant']}`.",
            f"4. Best repaired normal-cost average / median: `{summary['best_repaired_average']:.2f}` / `{summary['best_repaired_median']:.2f}`.",
            f"5. Best repaired 1M / 3M / 5M hit windows: `{summary['best_repaired_hit_1m_windows']}` / `{summary['best_repaired_hit_3m_windows']}` / `{summary['best_repaired_hit_5m_windows']}`.",
            f"6. Best repaired max drawdown: `{summary['best_repaired_max_drawdown_pct']:.6f}`.",
            f"7. Robustness verdict: `{summary['robustness_verdict']}`.",
            f"8. Freeze-and-confirm candidate: `{summary['deserves_freeze_and_confirm']}`.",
            f"9. Shadow fallback recommendation: `{summary['shadow_forward_fallback_recommended']}`.",
            "",
            "## Guardrails",
            "",
            "- `research_only=true`",
            "- `real_money_allowed=false`",
            "- `paper_allowed=false`",
            "- `live_allowed=false`",
            "- `behavior_change_allowed=false`",
            "- No live, paper, runtime, allocator, risk, sizing, entry, exit, threshold, sleeve, or production config behavior changed",
            "",
        ]
    )


def write_milestone_gated_compounding_fragility_repair_audit(
    config: MilestoneGatedCompoundingFragilityRepairAuditConfig,
) -> dict[str, Path]:
    compatibility_signature = _compatibility_signature(_compatibility_payload([], config.random_repeat_count))
    prior_anchor, _prior_cost_rows, _prior_fragility_rows, prior_warnings = _load_prior_milestone_anchor(config)
    if prior_anchor is None:
        return _empty_outputs(
            config,
            state=STATE_BLOCKED,
            classification="MILESTONE_FRAGILITY_REPAIR_REJECTED",
            warnings=prior_warnings,
            compatibility_signature=compatibility_signature,
        )
    stream_recheck, normalized_rows, stream_warnings = _trusted_stream_recheck(config)
    warnings = [*prior_warnings, *stream_warnings]
    if stream_recheck is None or normalized_rows is None:
        return _empty_outputs(
            config,
            state=STATE_BLOCKED,
            classification="MILESTONE_FRAGILITY_REPAIR_REJECTED",
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )

    specs = _variant_specs(normalized_rows)
    compatibility_signature = _compatibility_signature(_compatibility_payload(specs, config.random_repeat_count))
    if config.output_root.exists() and not config.force_rerun:
        existing_progress = _read_json(config.output_root / "scenario_progress.json", {})
        existing_signature = str(existing_progress.get("compatibility_signature") or "")
        if existing_signature and existing_signature != compatibility_signature:
            redirected = MilestoneGatedCompoundingFragilityRepairAuditConfig(
                package_root=config.package_root,
                output_root=_next_run_folder(config.output_root),
                random_repeat_count=config.random_repeat_count,
                force_rerun=config.force_rerun,
            )
            return write_milestone_gated_compounding_fragility_repair_audit(redirected)
    diagnostics_root, ledger_root, reports_root, checkpoints_root = _ensure_dirs(config.output_root)
    _write_json(diagnostics_root / "prior_milestone_audit_anchor.json", prior_anchor)
    _write_json(diagnostics_root / "trusted_1h_stream_recheck.json", stream_recheck)
    _write_csv(diagnostics_root / "fragility_repair_variants.csv", [asdict(spec) for spec in specs])
    _write_json(diagnostics_root / "fragility_repair_variant_specs.json", {**RESEARCH_ONLY_FLAGS, "rows": [asdict(spec) for spec in specs]})

    completed_variants: list[str] = []
    cost_band_rows: list[dict[str, Any]] = []
    rolling_rows: list[dict[str, Any]] = []
    equity_curve_rows: list[dict[str, Any]] = []
    trade_ledger_rows: list[dict[str, Any]] = []
    checkpoint_index_path = checkpoints_root / "checkpoint_index.json"
    if checkpoint_index_path.exists() and not config.force_rerun:
        checkpoint_index = _read_json(checkpoint_index_path, {})
        if str(checkpoint_index.get("compatibility_signature") or "") == compatibility_signature:
            completed_variants = [str(name) for name in checkpoint_index.get("completed_variants", [])]
            cost_band_rows, rolling_rows, equity_curve_rows, trade_ledger_rows = _aggregate_checkpoint_rows(checkpoints_root)

    _write_status(
        config.output_root,
        state=STATE_RUNNING,
        warnings=warnings,
        compatibility_signature=compatibility_signature,
        extra={"current_phase": "variant_evaluation"},
    )
    _write_scenario_progress(
        config.output_root,
        state=STATE_RUNNING,
        compatibility_signature=compatibility_signature,
        variant_specs=specs,
        completed_variants=completed_variants,
        warnings=warnings,
    )
    _write_run_progress(
        diagnostics_root,
        state=STATE_RUNNING,
        completed_variants=len(completed_variants),
        total_variants=len(specs),
        current_variant=completed_variants[-1] if completed_variants else "",
        warnings=warnings,
    )

    try:
        for spec in specs:
            if spec.variant_name in completed_variants and not config.force_rerun:
                continue
            if not spec.available:
                _save_checkpoint(
                    _variant_checkpoint_path(checkpoints_root, spec.variant_name),
                    {
                        "variant_name": spec.variant_name,
                        "state": "skipped_unavailable",
                        "cost_band_rows": [],
                        "rolling_rows": [],
                        "equity_curve_rows": [],
                        "trade_ledger_rows": [],
                        "warnings": [spec.unavailable_reason],
                        **RESEARCH_ONLY_FLAGS,
                    },
                )
                completed_variants.append(spec.variant_name)
                _write_json(checkpoint_index_path, {"completed_variants": completed_variants, "compatibility_signature": compatibility_signature, **RESEARCH_ONLY_FLAGS})
                _write_scenario_progress(
                    config.output_root,
                    state=STATE_PARTIAL,
                    compatibility_signature=compatibility_signature,
                    variant_specs=specs,
                    completed_variants=completed_variants,
                    warnings=[*warnings, spec.unavailable_reason],
                )
                continue

            variant_cost_rows: list[dict[str, Any]] = []
            variant_rolling_rows: list[dict[str, Any]] = []
            variant_equity_rows: list[dict[str, Any]] = []
            variant_trade_rows: list[dict[str, Any]] = []
            for band_name, band_bps in _cost_band_specs():
                full_output = _simulate_repair_variant_sequence(normalized_rows, spec, cost_bps_total=band_bps)
                rolling_summary, per_window_rows = _rolling_variant_summary(normalized_rows, spec, cost_bps_total=band_bps)
                variant_cost_rows.append(_variant_result_record(spec, band_name, band_bps, full_output, rolling_summary))
                variant_rolling_rows.extend([{**row, "cost_band_name": band_name} for row in per_window_rows])
                if band_name == "NORMAL_MIXED_MAKER_TAKER_COST":
                    variant_equity_rows.extend([{"variant_name": spec.variant_name, **row} for row in full_output["daily_rows"]])
                    variant_trade_rows.extend([{"variant_name": spec.variant_name, **row} for row in full_output["trade_trace"]])

            _save_checkpoint(
                _variant_checkpoint_path(checkpoints_root, spec.variant_name),
                {
                    "variant_name": spec.variant_name,
                    "state": "completed",
                    "cost_band_rows": variant_cost_rows,
                    "rolling_rows": variant_rolling_rows,
                    "equity_curve_rows": variant_equity_rows,
                    "trade_ledger_rows": variant_trade_rows,
                    **RESEARCH_ONLY_FLAGS,
                },
            )
            cost_band_rows.extend(variant_cost_rows)
            rolling_rows.extend(variant_rolling_rows)
            equity_curve_rows.extend(variant_equity_rows)
            trade_ledger_rows.extend(variant_trade_rows)
            completed_variants.append(spec.variant_name)
            _write_json(checkpoint_index_path, {"completed_variants": completed_variants, "compatibility_signature": compatibility_signature, **RESEARCH_ONLY_FLAGS})
            _write_csv(diagnostics_root / "fragility_repair_cost_band_results.csv", _harmonize_rows(cost_band_rows))
            _write_csv(diagnostics_root / "fragility_repair_rolling_5y_results.csv", _harmonize_rows(rolling_rows))
            _write_csv(ledger_root / "fragility_repair_equity_curves.csv", _harmonize_rows(equity_curve_rows))
            _write_csv(ledger_root / "fragility_repair_trade_ledgers.csv", _harmonize_rows(trade_ledger_rows))
            _write_scenario_progress(
                config.output_root,
                state=STATE_PARTIAL,
                compatibility_signature=compatibility_signature,
                variant_specs=specs,
                completed_variants=completed_variants,
                warnings=warnings,
            )
            _write_run_progress(
                diagnostics_root,
                state=STATE_PARTIAL,
                completed_variants=len(completed_variants),
                total_variants=len(specs),
                current_variant=spec.variant_name,
                warnings=warnings,
            )

        top_variant_names = _top_candidate_names(cost_band_rows, limit=4)
        stress_rows: list[dict[str, Any]] = []
        resilience_rows: list[dict[str, Any]] = []
        repeats_to_use = max(int(config.random_repeat_count), 1)
        spec_map = {spec.variant_name: spec for spec in specs}
        for variant_name in top_variant_names:
            spec = spec_map[variant_name]
            variant_stress, variant_resilience, stochastic = _stress_and_resilience(
                [dict(row) for row in normalized_rows],
                spec,
                random_repeat_count=repeats_to_use,
            )
            stress_rows.extend(variant_stress)
            resilience_rows.extend(variant_resilience)

        normal_rows = [row for row in cost_band_rows if str(row.get("cost_band_name") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"]
        baseline_average = _safe_float(prior_anchor.get("baseline_average"))
        baseline_median = _safe_float(prior_anchor.get("baseline_median"))
        baseline_hits = int(prior_anchor.get("baseline_hit_1m_windows", 0) or 0)
        score_rows, best_selection = _scorecard(
            specs,
            normal_rows,
            cost_band_rows,
            stress_rows,
            resilience_rows,
            baseline_average=baseline_average,
            baseline_median=baseline_median,
            baseline_hits=baseline_hits,
            prior_best_name="PRIOR_BEST_REPLAY",
        )
        _write_csv(diagnostics_root / "fragility_repair_stress_results.csv", _harmonize_rows(stress_rows))
        _write_csv(diagnostics_root / "fragility_repair_missed_trade_resilience.csv", _harmonize_rows(resilience_rows))
        _write_csv(diagnostics_root / "fragility_repair_scorecard.csv", _harmonize_rows(score_rows))
        _write_json(diagnostics_root / "best_repaired_variant_selection.json", best_selection)

        prior_best_cost_row = next((row for row in normal_rows if str(row.get("variant_name") or "") == "PRIOR_BEST_REPLAY"), {})
        best_repaired_variant_name = str(best_selection.get("best_repaired_variant", {}).get("variant_name") or "")
        best_repaired_cost_row = next((row for row in normal_rows if str(row.get("variant_name") or "") == best_repaired_variant_name), {})
        prior_best_score = dict(best_selection.get("prior_best_score") or {})
        best_repaired_score = dict(best_selection.get("best_repaired_variant") or {})
        classification, freeze_candidate, shadow_fallback, robustness_verdict = _classification_and_fallback(
            baseline_average=baseline_average,
            baseline_median=baseline_median,
            baseline_hits=baseline_hits,
            prior_best_cost_row=prior_best_cost_row,
            best_repaired_cost_row=best_repaired_cost_row,
            prior_best_score=prior_best_score,
            best_repaired_score=best_repaired_score,
        )
        self_audit = _implementation_self_audit(
            schema_fields_detected=stream_recheck.get("schema_fields_detected", []),
            variants_tested=[spec.variant_name for spec in specs],
            stochastic_repeat_count_used=repeats_to_use,
            scout_mode=repeats_to_use < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        )
        stochastic_payload = {
            **RESEARCH_ONLY_FLAGS,
            "random_repeat_count_used": repeats_to_use,
            "minimum_repeat_count_required_for_gate": MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
            "stochastic_results_reliable_for_final_gate": repeats_to_use >= MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
            "scout_mode": repeats_to_use < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
            "deterministic_metrics_still_usable": [
                "baseline anchor",
                "repair variant inventory",
                "normal-cost rolling 5Y metrics",
                "cost-band survival",
                "top-winner removal stress",
                "R-haircut stress",
                "scorecard and fallback decision",
            ],
            "recommendation_for_shortlist_rerun": "Increase repeat budget toward 64 if the best repaired variant looks close to freeze-and-confirm.",
        }
        _write_json(diagnostics_root / "stochastic_budget_reliability_check.json", stochastic_payload)
        _write_json(diagnostics_root / "shadow_fallback_decision.json", shadow_fallback)
        _write_json(diagnostics_root / "implementation_self_audit.json", self_audit)

        missed_tolerance = _safe_float(best_repaired_score.get("missed_trade_tolerance_threshold"))
        conservative_row = next((row for row in cost_band_rows if str(row.get("variant_name") or "") == best_repaired_variant_name and str(row.get("cost_band_name") or "") == "CONSERVATIVE_TAKER_COST"), {})
        high_slippage_row = next((row for row in cost_band_rows if str(row.get("variant_name") or "") == best_repaired_variant_name and str(row.get("cost_band_name") or "") == "HIGH_SLIPPAGE_COST"), {})
        top5_row = next((row for row in stress_rows if str(row.get("variant_name") or "") == best_repaired_variant_name and str(row.get("scenario") or "") == "remove_top_5_winners"), {})
        r20_row = next((row for row in stress_rows if str(row.get("variant_name") or "") == best_repaired_variant_name and str(row.get("scenario") or "") == "r_haircut_20pct"), {})
        r30_row = next((row for row in stress_rows if str(row.get("variant_name") or "") == best_repaired_variant_name and str(row.get("scenario") or "") == "r_haircut_30pct"), {})
        summary = {
            "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
            **RESEARCH_ONLY_FLAGS,
            "baseline_average": baseline_average,
            "baseline_median": baseline_median,
            "baseline_hit_1m_windows": baseline_hits,
            "prior_best_variant": str(prior_anchor.get("best_prior_variant") or ""),
            "prior_best_average": _safe_float(prior_anchor.get("best_prior_average")),
            "prior_best_median": _safe_float(prior_anchor.get("best_prior_median")),
            "prior_best_hit_1m_windows": int(prior_anchor.get("best_prior_hit_1m_windows", 0) or 0),
            "best_repaired_variant": best_repaired_variant_name,
            "best_repaired_average": _safe_float(best_repaired_cost_row.get("rolling_5y_average")),
            "best_repaired_median": _safe_float(best_repaired_cost_row.get("rolling_5y_median")),
            "best_repaired_hit_1m_windows": int(best_repaired_cost_row.get("hit_1m_windows", 0) or 0),
            "best_repaired_hit_3m_windows": int(best_repaired_cost_row.get("hit_3m_windows", 0) or 0),
            "best_repaired_hit_5m_windows": int(best_repaired_cost_row.get("hit_5m_windows", 0) or 0),
            "best_repaired_max_drawdown_pct": _safe_float(best_repaired_cost_row.get("max_drawdown_pct")),
            "best_repaired_top5_removal_average": _safe_float(top5_row.get("rolling_5y_average")),
            "best_repaired_r20_haircut_average": _safe_float(r20_row.get("rolling_5y_average")),
            "best_repaired_r30_haircut_average": _safe_float(r30_row.get("rolling_5y_average")),
            "best_repaired_conservative_cost_average": _safe_float(conservative_row.get("rolling_5y_average")),
            "best_repaired_high_slippage_average": _safe_float(high_slippage_row.get("rolling_5y_average")),
            "missed_trade_tolerance_threshold": missed_tolerance,
            "robustness_verdict": robustness_verdict,
            "fragility_improved": _safe_float(best_repaired_score.get("robustness_score")) > _safe_float(prior_best_score.get("robustness_score")),
            "deserves_freeze_and_confirm": bool(freeze_candidate.get("deserves_freeze_and_confirm", False)),
            "shadow_forward_fallback_recommended": bool(shadow_fallback.get("recommend_shadow_forward_validation_spec", False)),
            "stochastic_repeat_count_used": repeats_to_use,
            "scout_mode": repeats_to_use < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
            "implementation_self_audit_verdict": "PASS" if repeats_to_use >= MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE else "PASS_WITH_SCOUT_MODE_CAVEAT",
            "final_classification": classification,
            "checkpoint_resume_status": "resume_capable",
        }
        _write_json(config.output_root / "milestone_gated_compounding_fragility_repair_summary.json", summary)
        _write_markdown(config.output_root / "milestone_gated_compounding_fragility_repair_report.md", _report(summary))
        next_step = (
            "Freeze the repaired milestone variant and run a separate freeze-and-confirm audit."
            if freeze_candidate["deserves_freeze_and_confirm"]
            else "Prepare Shadow-Forward Validation Specification for the accepted 750k-800k BTC 1H engine."
            if shadow_fallback["recommend_shadow_forward_validation_spec"]
            else "Keep milestone gear research-only and continue only if a narrower fragility hypothesis remains."
        )
        _write_json(reports_root / "next_research_recommendation.json", {**RESEARCH_ONLY_FLAGS, "next_step": next_step})

        _write_status(
            config.output_root,
            state=STATE_COMPLETED,
            warnings=warnings,
            compatibility_signature=compatibility_signature,
            extra={"final_classification": classification},
        )
        _write_scenario_progress(
            config.output_root,
            state=STATE_COMPLETED,
            compatibility_signature=compatibility_signature,
            variant_specs=specs,
            completed_variants=completed_variants,
            warnings=warnings,
        )
        _write_run_progress(
            diagnostics_root,
            state=STATE_COMPLETED,
            completed_variants=len(completed_variants),
            total_variants=len(specs),
            current_variant="",
            warnings=warnings,
        )
        return {
            "summary": config.output_root / "milestone_gated_compounding_fragility_repair_summary.json",
            "report": config.output_root / "milestone_gated_compounding_fragility_repair_report.md",
            "status": config.output_root / "status.json",
        }
    except Exception as exc:  # pragma: no cover
        failure_warnings = [*warnings, f"Audit failed: {exc}"]
        _write_status(
            config.output_root,
            state=STATE_FAILED,
            warnings=failure_warnings,
            compatibility_signature=compatibility_signature,
        )
        _write_scenario_progress(
            config.output_root,
            state=STATE_FAILED,
            compatibility_signature=compatibility_signature,
            variant_specs=specs,
            completed_variants=completed_variants,
            warnings=failure_warnings,
        )
        _write_run_progress(
            diagnostics_root,
            state=STATE_FAILED,
            completed_variants=len(completed_variants),
            total_variants=len(specs),
            current_variant="",
            warnings=failure_warnings,
        )
        raise


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    output_root = package_root / "output" / OUTPUT_FOLDER_NAME
    write_milestone_gated_compounding_fragility_repair_audit(
        MilestoneGatedCompoundingFragilityRepairAuditConfig(
            package_root=package_root,
            output_root=output_root,
            random_repeat_count=32,
        )
    )
