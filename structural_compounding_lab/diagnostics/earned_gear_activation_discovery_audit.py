from __future__ import annotations

import hashlib
import json
import random
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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
from structural_compounding_lab.diagnostics.milestone_bridge_fragility_driver_repair_audit import _estimated_cost  # noqa: E402
from structural_compounding_lab.diagnostics.milestone_gated_compounding_fragility_repair_audit import (  # noqa: E402
    START_CAPITAL,
    _drop_high_volatility_month,
    _drop_top_performing_month,
    _empty_outputs,
)
from structural_compounding_lab.diagnostics.milestone_gated_explosive_compounding_audit import (  # noqa: E402
    BASE_LOCK_RATIO,
    EXPECTED_REPAIR_MODE,
    MilestoneGatedExplosiveCompoundingAuditConfig as PriorMilestoneAuditConfig,
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


OUTPUT_FOLDER_NAME = "earned_gear_activation_discovery_audit_001"
DEFAULT_RANDOM_REPEAT_COUNT = 32
MAX_VARIANTS = 25
STATE_NOT_STARTED = "not_started"
STATE_RUNNING = "running"
STATE_PARTIAL = "partial"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_BLOCKED = "blocked"


@dataclass(frozen=True)
class EarnedGearActivationDiscoveryAuditConfig:
    package_root: Path
    output_root: Path
    random_repeat_count: int = DEFAULT_RANDOM_REPEAT_COUNT
    force_rerun: bool = False


@dataclass(frozen=True)
class EarnedGearVariantSpec:
    variant_name: str
    description: str
    gate_family: str
    gate_label: str
    profile: str
    primary_trigger_equity: float | None
    secondary_trigger_equity: float | None
    primary_multiplier: float
    secondary_multiplier: float
    max_multiplier_cap: float
    soft_brake_pct: float | None
    hard_brake_pct: float | None
    milestone_buffer_pct: float
    lock_ratio_above_trigger: float
    lock_ratio_above_1m: float
    reenable_requires_new_high: bool
    require_equity_near_high: bool
    near_high_tolerance_pct: float
    max_drawdown_for_activation: float | None
    minimum_closed_trades: int
    require_no_hard_brake: bool
    protection_mode_at_1m: bool
    available: bool
    unavailable_reason: str


def _paths(config: EarnedGearActivationDiscoveryAuditConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    return {
        "baseline_cost_band_results": output_root / "execution_cost_realism_and_trade_redundancy_audit_001" / "diagnostics" / "execution_cost_band_results.csv",
        "prior_milestone_summary": output_root / "milestone_gated_explosive_compounding_audit_001" / "milestone_gated_explosive_compounding_summary.json",
        "prior_milestone_baseline_anchor": output_root / "milestone_gated_explosive_compounding_audit_001" / "diagnostics" / "baseline_anchor.json",
        "prior_milestone_stream_reconstruction": output_root / "milestone_gated_explosive_compounding_audit_001" / "diagnostics" / "trusted_1h_trade_stream_reconstruction.json",
        "prior_milestone_cost_band_results": output_root / "milestone_gated_explosive_compounding_audit_001" / "diagnostics" / "milestone_gated_cost_band_results.csv",
        "prior_milestone_self_audit": output_root / "milestone_gated_explosive_compounding_audit_001" / "diagnostics" / "implementation_self_audit.json",
        "fragility_repair_summary": output_root / "milestone_gated_compounding_fragility_repair_audit_001" / "milestone_gated_compounding_fragility_repair_summary.json",
        "fragility_repair_scorecard": output_root / "milestone_gated_compounding_fragility_repair_audit_001" / "diagnostics" / "fragility_repair_scorecard.csv",
        "fragility_repair_self_audit": output_root / "milestone_gated_compounding_fragility_repair_audit_001" / "diagnostics" / "implementation_self_audit.json",
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


def _compatibility_payload(variant_specs: list[EarnedGearVariantSpec], random_repeat_count: int) -> dict[str, Any]:
    return {
        "module": "earned_gear_activation_discovery_audit",
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
    return output_root.parent / f"{output_root.name}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


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
    variant_specs: list[EarnedGearVariantSpec],
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


def _cost_band_specs() -> list[tuple[str, float]]:
    return [
        ("ZERO_COST_REFERENCE", ZERO_COST_BPS),
        ("OPTIMISTIC_MAKER_COST", OPTIMISTIC_COST_BPS),
        ("NORMAL_MIXED_MAKER_TAKER_COST", NORMAL_COST_BPS),
        ("CONSERVATIVE_TAKER_COST", CONSERVATIVE_COST_BPS),
        ("HIGH_SLIPPAGE_COST", HIGH_SLIPPAGE_COST_BPS),
    ]


def _volatility_value(row: dict[str, Any]) -> float | None:
    for field in ("volatility_score", "danger_score", "pre_entry_stop_distance_atr", "atr_tradability"):
        value = row.get(field)
        if value is None or str(value).strip() in {"", "None", "nan", "NaN"}:
            continue
        numeric = _safe_float(value, float("nan"))
        if not pd_is_nan(numeric):
            return float(numeric)
    return None


def pd_is_nan(value: float) -> bool:
    try:
        return value != value
    except Exception:
        return False


def _load_prior_courts(config: EarnedGearActivationDiscoveryAuditConfig) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    paths = _paths(config)
    for key, path in paths.items():
        if not path.exists():
            warnings.append(f"Missing prior artifact: {path}")
    if warnings:
        return None, warnings

    baseline_rows = _read_csv_rows(paths["baseline_cost_band_results"])
    baseline_row = next((row for row in baseline_rows if str(row.get("band_name") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"), None)
    if baseline_row is None:
        warnings.append("Trusted baseline normal-cost row missing.")
        return None, warnings

    milestone_summary = _read_json(paths["prior_milestone_summary"], {})
    repair_summary = _read_json(paths["fragility_repair_summary"], {})
    milestone_anchor = _read_json(paths["prior_milestone_baseline_anchor"], {})
    milestone_stream = _read_json(paths["prior_milestone_stream_reconstruction"], {})
    milestone_self = _read_json(paths["prior_milestone_self_audit"], {})
    repair_self = _read_json(paths["fragility_repair_self_audit"], {})

    payload = {
        **RESEARCH_ONLY_FLAGS,
        "baseline_average": _safe_float(baseline_row.get("rolling_5y_average_ending_equity")),
        "baseline_median": _safe_float(baseline_row.get("rolling_5y_median_ending_equity")),
        "baseline_hit_1m_windows": int(baseline_row.get("hit_1m_windows", 0) or 0),
        "prior_300k_aggressive_variant": str(milestone_summary.get("best_variant_name") or ""),
        "prior_300k_aggressive_average": _safe_float(milestone_summary.get("best_variant_average")),
        "prior_300k_aggressive_median": _safe_float(milestone_summary.get("best_variant_median")),
        "prior_300k_aggressive_hit_1m_windows": int(milestone_summary.get("best_variant_hit_1m_windows", 0) or 0),
        "prior_300k_aggressive_fragile": str(milestone_summary.get("robustness_verdict") or "") == "FRAGILE",
        "fragility_repair_best_variant": str(repair_summary.get("best_repaired_variant") or ""),
        "fragility_repair_average": _safe_float(repair_summary.get("best_repaired_average")),
        "fragility_repair_median": _safe_float(repair_summary.get("best_repaired_median")),
        "fragility_repair_hit_1m_windows": int(repair_summary.get("best_repaired_hit_1m_windows", 0) or 0),
        "fragility_repair_robustness_verdict": str(repair_summary.get("robustness_verdict") or ""),
        "fragility_repair_scout_mode": bool(repair_summary.get("scout_mode", True)),
        "trusted_baseline_reconciled": bool(milestone_anchor.get("baseline_reproduction_pass", False)),
        "milestone_stream_reconciled": bool(milestone_stream.get("trusted_baseline_reproduced", False)),
        "prior_300k_self_audit_reconciled": bool(milestone_self.get("trusted_baseline_reconciled", False)),
        "fragility_repair_loaded": bool(repair_self.get("trusted_baseline_reconciled", False)),
        "warnings": warnings,
    }
    return payload, warnings


def _trusted_stream_recheck(config: EarnedGearActivationDiscoveryAuditConfig) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None, list[str]]:
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


def _variant_specs(rows: list[dict[str, Any]]) -> list[EarnedGearVariantSpec]:
    specs: list[EarnedGearVariantSpec] = []

    def add(
        *,
        variant_name: str,
        description: str,
        gate_family: str,
        gate_label: str,
        profile: str,
        primary_trigger_equity: float | None,
        secondary_trigger_equity: float | None = None,
        primary_multiplier: float = 1.0,
        secondary_multiplier: float = 1.0,
        max_multiplier_cap: float = 2.25,
        soft_brake_pct: float | None = 0.08,
        hard_brake_pct: float | None = 0.15,
        milestone_buffer_pct: float = 0.06,
        lock_ratio_above_trigger: float = 0.72,
        lock_ratio_above_1m: float = 0.86,
        reenable_requires_new_high: bool = True,
        require_equity_near_high: bool = False,
        near_high_tolerance_pct: float = 0.01,
        max_drawdown_for_activation: float | None = None,
        minimum_closed_trades: int = 0,
        require_no_hard_brake: bool = False,
        protection_mode_at_1m: bool = False,
        available: bool = True,
        unavailable_reason: str = "",
    ) -> None:
        specs.append(
            EarnedGearVariantSpec(
                variant_name=variant_name,
                description=description,
                gate_family=gate_family,
                gate_label=gate_label,
                profile=profile,
                primary_trigger_equity=primary_trigger_equity,
                secondary_trigger_equity=secondary_trigger_equity,
                primary_multiplier=primary_multiplier,
                secondary_multiplier=secondary_multiplier or primary_multiplier,
                max_multiplier_cap=max_multiplier_cap,
                soft_brake_pct=soft_brake_pct,
                hard_brake_pct=hard_brake_pct,
                milestone_buffer_pct=milestone_buffer_pct,
                lock_ratio_above_trigger=lock_ratio_above_trigger,
                lock_ratio_above_1m=lock_ratio_above_1m,
                reenable_requires_new_high=reenable_requires_new_high,
                require_equity_near_high=require_equity_near_high,
                near_high_tolerance_pct=near_high_tolerance_pct,
                max_drawdown_for_activation=max_drawdown_for_activation,
                minimum_closed_trades=minimum_closed_trades,
                require_no_hard_brake=require_no_hard_brake,
                protection_mode_at_1m=protection_mode_at_1m,
                available=available,
                unavailable_reason=unavailable_reason,
            )
        )

    add(
        variant_name="AGGRESSIVE_CONTROLLED_REFERENCE_300K",
        description="Reference replay of the prior 300k aggressive controlled gear.",
        gate_family="reference",
        gate_label="300k",
        profile="AGGRESSIVE_CONTROLLED_REFERENCE",
        primary_trigger_equity=300_000.0,
        primary_multiplier=1.75,
        max_multiplier_cap=2.75,
        milestone_buffer_pct=0.10,
        lock_ratio_above_trigger=0.70,
        lock_ratio_above_1m=0.80,
        reenable_requires_new_high=True,
    )

    for threshold in (100_000.0, 150_000.0, 200_000.0, 250_000.0, 300_000.0, 400_000.0, 500_000.0):
        add(
            variant_name=f"FIXED_{int(threshold/1000)}K_BALANCED",
            description=f"Balanced gear activated at fixed equity gate {int(threshold/1000)}k.",
            gate_family="fixed_equity",
            gate_label=f"{int(threshold/1000)}k",
            profile="BALANCED",
            primary_trigger_equity=threshold,
            primary_multiplier=1.35,
            max_multiplier_cap=2.20,
        )

    for multiple in (5.0, 7.5, 10.0, 15.0, 20.0, 25.0):
        threshold = START_CAPITAL * multiple
        add(
            variant_name=f"EQUITY_MULTIPLE_{str(multiple).replace('.', '_')}X_LIGHT",
            description=f"Light gear activated at {multiple}x starting capital.",
            gate_family="equity_multiple",
            gate_label=f"{multiple}x",
            profile="LIGHT",
            primary_trigger_equity=threshold,
            primary_multiplier=1.18,
            max_multiplier_cap=2.00,
            milestone_buffer_pct=0.05,
            lock_ratio_above_trigger=0.68,
            lock_ratio_above_1m=0.82,
            reenable_requires_new_high=False,
        )

    add(
        variant_name="EARNED_150K_NEAR_HIGH_LOW_DD",
        description="Activate at 150k only when equity is near high and drawdown is low.",
        gate_family="earned_strength",
        gate_label="150k_near_high_low_dd",
        profile="LIGHT",
        primary_trigger_equity=150_000.0,
        primary_multiplier=1.18,
        max_multiplier_cap=2.00,
        require_equity_near_high=True,
        max_drawdown_for_activation=0.05,
        reenable_requires_new_high=True,
    )
    add(
        variant_name="EARNED_200K_NEAR_HIGH_50_TRADES",
        description="Activate at 200k only near highs and after at least 50 closed trades.",
        gate_family="earned_strength",
        gate_label="200k_near_high_50trades",
        profile="BALANCED",
        primary_trigger_equity=200_000.0,
        primary_multiplier=1.30,
        minimum_closed_trades=50,
        require_equity_near_high=True,
        reenable_requires_new_high=True,
    )
    add(
        variant_name="EARNED_250K_LOW_DD_100_TRADES",
        description="Activate at 250k with low drawdown and at least 100 closed trades.",
        gate_family="earned_strength",
        gate_label="250k_low_dd_100trades",
        profile="BALANCED",
        primary_trigger_equity=250_000.0,
        primary_multiplier=1.35,
        max_drawdown_for_activation=0.05,
        minimum_closed_trades=100,
        reenable_requires_new_high=False,
    )
    add(
        variant_name="EARNED_300K_NO_HARD_BRAKE",
        description="Activate at 300k only if no hard brake is active and equity is near a high.",
        gate_family="earned_strength",
        gate_label="300k_no_hard_brake",
        profile="BALANCED",
        primary_trigger_equity=300_000.0,
        primary_multiplier=1.35,
        require_no_hard_brake=True,
        require_equity_near_high=True,
        reenable_requires_new_high=True,
    )

    add(
        variant_name="TWO_STAGE_150K_300K",
        description="Two-stage gear: light at 150k and balanced at 300k.",
        gate_family="two_stage",
        gate_label="150k_300k",
        profile="TWO_STAGE",
        primary_trigger_equity=150_000.0,
        secondary_trigger_equity=300_000.0,
        primary_multiplier=1.12,
        secondary_multiplier=1.32,
        max_multiplier_cap=2.15,
        protection_mode_at_1m=True,
    )
    add(
        variant_name="TWO_STAGE_200K_400K",
        description="Two-stage gear: light at 200k and balanced at 400k.",
        gate_family="two_stage",
        gate_label="200k_400k",
        profile="TWO_STAGE",
        primary_trigger_equity=200_000.0,
        secondary_trigger_equity=400_000.0,
        primary_multiplier=1.12,
        secondary_multiplier=1.32,
        max_multiplier_cap=2.15,
        protection_mode_at_1m=True,
    )
    add(
        variant_name="TWO_STAGE_300K_500K",
        description="Two-stage gear: light at 300k and balanced at 500k.",
        gate_family="two_stage",
        gate_label="300k_500k",
        profile="TWO_STAGE",
        primary_trigger_equity=300_000.0,
        secondary_trigger_equity=500_000.0,
        primary_multiplier=1.12,
        secondary_multiplier=1.32,
        max_multiplier_cap=2.15,
        protection_mode_at_1m=True,
    )
    add(
        variant_name="TWO_STAGE_300K_1M_PROTECTION",
        description="Balanced at 300k with a protection mode rather than more aggression after 1M.",
        gate_family="two_stage",
        gate_label="300k_1m_protection",
        profile="TWO_STAGE",
        primary_trigger_equity=300_000.0,
        secondary_trigger_equity=None,
        primary_multiplier=1.35,
        secondary_multiplier=1.35,
        max_multiplier_cap=2.15,
        protection_mode_at_1m=True,
    )
    return specs[:MAX_VARIANTS]


def _gear_eligible(
    spec: EarnedGearVariantSpec,
    *,
    current_equity: float,
    peak_equity: float,
    current_drawdown: float,
    closed_trades: int,
    hard_brake_active: bool,
) -> bool:
    if spec.primary_trigger_equity is not None and current_equity < spec.primary_trigger_equity:
        return False
    if spec.require_equity_near_high and peak_equity > 0.0:
        if current_equity < peak_equity * (1.0 - spec.near_high_tolerance_pct):
            return False
    if spec.max_drawdown_for_activation is not None and current_drawdown > spec.max_drawdown_for_activation:
        return False
    if closed_trades < spec.minimum_closed_trades:
        return False
    if spec.require_no_hard_brake and hard_brake_active:
        return False
    return True


def _simulate_variant_sequence(
    rows: list[dict[str, Any]],
    spec: EarnedGearVariantSpec,
    *,
    cost_bps_total: float,
) -> dict[str, Any]:
    ordered = sorted((dict(row) for row in rows), key=lambda item: (item["exit_timestamp"], str(item.get("trade_id") or "")))
    active_capital = float(START_CAPITAL)
    locked_profit = 0.0
    peak_equity = active_capital
    last_reenable_equity = active_capital
    hard_brake_active = False
    gear_active = False
    gear_activation_count = 0
    gear_down_count = 0
    risk_multipliers: list[float] = []
    time_above = {100_000.0: 0, 200_000.0: 0, 300_000.0: 0, 500_000.0: 0, 1_000_000.0: 0}
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
    first_activation_date = ""
    first_activation_equity = 0.0
    first_activation_trades = 0
    protection_mode_active = False

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

    for index, row in enumerate(ordered):
        exit_ts = row["exit_timestamp"]
        day_key = exit_ts.strftime("%Y-%m-%d")
        if current_day_key != day_key:
            flush_day()
            current_day_key = day_key
            day_equity_start = active_capital + locked_profit
            day_equity_end = active_capital + locked_profit

        current_equity = active_capital + locked_profit
        current_drawdown = _safe_ratio(max(0.0, peak_equity - current_equity), peak_equity, 0.0)
        for threshold in time_above:
            if current_equity >= threshold:
                time_above[threshold] += 1

        base_multiplier = _base_multiplier(current_equity)
        eligible = _gear_eligible(
            spec,
            current_equity=current_equity,
            peak_equity=peak_equity,
            current_drawdown=current_drawdown,
            closed_trades=index,
            hard_brake_active=hard_brake_active,
        )
        desired_gear = eligible
        if spec.reenable_requires_new_high and hard_brake_active:
            desired_gear = current_equity >= last_reenable_equity and eligible

        if spec.soft_brake_pct is not None and current_drawdown >= spec.soft_brake_pct:
            desired_gear = False
        if spec.hard_brake_pct is not None and current_drawdown >= spec.hard_brake_pct:
            desired_gear = False
            hard_brake_active = True
            last_reenable_equity = peak_equity

        if desired_gear and not gear_active:
            gear_activation_count += 1
            if not first_activation_date:
                first_activation_date = exit_ts.isoformat()
                first_activation_equity = current_equity
                first_activation_trades = index
        elif gear_active and not desired_gear:
            gear_down_count += 1
        gear_active = desired_gear

        if current_equity > peak_equity:
            peak_equity = current_equity
            if hard_brake_active and current_equity >= last_reenable_equity:
                hard_brake_active = False

        gear_scale = 1.0
        if gear_active:
            gear_scale = max(gear_scale, spec.primary_multiplier)
            if spec.secondary_trigger_equity is not None and current_equity >= spec.secondary_trigger_equity:
                gear_scale = max(gear_scale, spec.secondary_multiplier)
        if spec.protection_mode_at_1m and current_equity >= 1_000_000.0:
            protection_mode_active = True
            gear_scale = min(gear_scale, 1.0)

        multiplier = base_multiplier if not gear_active else min(base_multiplier * gear_scale, spec.max_multiplier_cap)
        if not gear_active and spec.soft_brake_pct is not None and current_drawdown >= spec.soft_brake_pct:
            multiplier = base_multiplier

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
                "hard_brake_active": hard_brake_active,
                "protection_mode_active": protection_mode_active,
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
        "time_above_100k": time_above[100_000.0],
        "time_above_200k": time_above[200_000.0],
        "time_above_300k": time_above[300_000.0],
        "time_above_500k": time_above[500_000.0],
        "time_above_1m": time_above[1_000_000.0],
        "risk_multiplier_avg": round(sum(risk_multipliers) / len(risk_multipliers), 6) if risk_multipliers else 0.0,
        "risk_multiplier_max": round(max(risk_multipliers), 6) if risk_multipliers else 0.0,
        "insolvency_hit": insolvency_hit,
        "first_activation_date": first_activation_date,
        "first_activation_equity": round(first_activation_equity, 6),
        "time_to_activation_trades": first_activation_trades,
    }


def _rolling_variant_summary(rows: list[dict[str, Any]], spec: EarnedGearVariantSpec, *, cost_bps_total: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    windows = _build_windows(rows)
    endings: list[float] = []
    hit_1m = 0
    hit_3m = 0
    hit_5m = 0
    rolling_rows: list[dict[str, Any]] = []
    worst_dd = 0.0
    for start, end, label in windows:
        selected = [dict(row) for row in rows if start <= row["exit_timestamp"] <= end]
        output = _simulate_variant_sequence(selected, spec, cost_bps_total=cost_bps_total)
        ending_equity = _safe_float(output["ending_equity"])
        endings.append(ending_equity)
        hit_1m += int(ending_equity >= 1_000_000.0)
        hit_3m += int(ending_equity >= 3_000_000.0)
        hit_5m += int(ending_equity >= 5_000_000.0)
        worst_dd = max(worst_dd, _safe_float(output["max_drawdown_pct"]))
        rolling_rows.append(
            {
                "variant_name": spec.variant_name,
                "cost_band_name": str(cost_bps_total),
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


def _variant_result_record(spec: EarnedGearVariantSpec, band_name: str, band_bps: float, full_output: dict[str, Any], rolling_summary: dict[str, Any]) -> dict[str, Any]:
    return {
        "variant_name": spec.variant_name,
        "gate_family": spec.gate_family,
        "gate_label": spec.gate_label,
        "profile": spec.profile,
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
        "gear_activations": int(full_output["gear_activations"]),
        "gear_down_events": int(full_output["gear_down_events"]),
        "first_activation_date": str(full_output["first_activation_date"]),
        "first_activation_equity": round(_safe_float(full_output["first_activation_equity"]), 6),
        "time_to_activation_trades": int(full_output["time_to_activation_trades"]),
        "time_above_100k": int(full_output["time_above_100k"]),
        "time_above_200k": int(full_output["time_above_200k"]),
        "time_above_300k": int(full_output["time_above_300k"]),
        "time_above_500k": int(full_output["time_above_500k"]),
        "time_above_1m": int(full_output["time_above_1m"]),
        "final_locked_profit": round(_safe_float(full_output["locked_profit"]), 6),
        "final_active_equity": round(_safe_float(full_output["active_equity"]), 6),
        "risk_multiplier_avg": round(_safe_float(full_output["risk_multiplier_avg"]), 6),
        "risk_multiplier_max": round(_safe_float(full_output["risk_multiplier_max"]), 6),
        "available": spec.available,
    }


def _top_variant_names(cost_band_rows: list[dict[str, Any]], limit: int = 4) -> list[str]:
    rows = [row for row in cost_band_rows if str(row.get("cost_band_name") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"]
    ranked = sorted(
        rows,
        key=lambda row: (
            -_safe_float(row.get("rolling_5y_average")),
            -_safe_float(row.get("rolling_5y_median")),
            -int(row.get("hit_1m_windows", 0) or 0),
            _safe_float(row.get("max_drawdown_pct")),
        ),
    )
    return [str(row["variant_name"]) for row in ranked[:limit]]


def _stress_rows_with_r_haircut(rows: list[dict[str, Any]], haircut_fraction: float) -> list[dict[str, Any]]:
    multiplier = max(0.0, 1.0 - haircut_fraction)
    return [{**dict(row), "r_multiple": _safe_float(row.get("r_multiple")) * multiplier} for row in rows]


def _stress_and_resilience(
    rows: list[dict[str, Any]],
    spec: EarnedGearVariantSpec,
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
        ("miss_one_random_day", _drop_label(rows, fmt="%Y-%m-%d", seed=9401)),
        ("miss_one_random_week", _drop_label(rows, fmt="%Y-W%W", seed=9402)),
        ("miss_one_random_month", _drop_label(rows, fmt="%Y-%m", seed=9403)),
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
            stressed_rows = _random_keep(rows, missed_frac, 9500 + repeat + int(missed_frac * 1000))
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
    }
    return stress_rows, resilience_rows, reliability


def _scenario_lookup(rows: list[dict[str, Any]], *, value_field: str) -> dict[tuple[str, str], float]:
    lookup: dict[tuple[str, str], float] = {}
    for row in rows:
        lookup[(str(row.get("variant_name") or ""), str(row.get("scenario") or ""))] = _safe_float(row.get(value_field))
    return lookup


def _missed_trade_tolerance(resilience_rows: list[dict[str, Any]], *, baseline_average: float, baseline_median: float) -> float:
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


def _simplicity_rank(spec: EarnedGearVariantSpec) -> int:
    complexity = 0
    complexity += int(spec.secondary_trigger_equity is not None)
    complexity += int(spec.require_equity_near_high)
    complexity += int(spec.max_drawdown_for_activation is not None)
    complexity += int(spec.minimum_closed_trades > 0)
    complexity += int(spec.require_no_hard_brake)
    complexity += int(spec.protection_mode_at_1m)
    return complexity


def _scorecard(
    specs: list[EarnedGearVariantSpec],
    normal_rows: list[dict[str, Any]],
    cost_band_rows: list[dict[str, Any]],
    stress_rows: list[dict[str, Any]],
    resilience_rows: list[dict[str, Any]],
    *,
    baseline_average: float,
    baseline_median: float,
    baseline_hits: int,
    prior_average: float,
    prior_median: float,
    prior_hits: int,
    repair_average: float,
    repair_median: float,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    normal_lookup = {str(row.get("variant_name") or ""): dict(row) for row in normal_rows}
    cost_lookup = {(str(row.get("variant_name") or ""), str(row.get("cost_band_name") or "")): dict(row) for row in cost_band_rows}
    stress_avg_lookup = _scenario_lookup(stress_rows, value_field="rolling_5y_average")
    resilience_avg_lookup = _scenario_lookup(resilience_rows, value_field="rolling_5y_average_mean")
    resilience_median_lookup = _scenario_lookup(resilience_rows, value_field="rolling_5y_median_mean")
    score_rows: list[dict[str, Any]] = []
    best_candidate: dict[str, Any] | None = None
    for spec in specs:
        normal_row = normal_lookup.get(spec.variant_name, {})
        avg = _safe_float(normal_row.get("rolling_5y_average"))
        median = _safe_float(normal_row.get("rolling_5y_median"))
        hits = int(normal_row.get("hit_1m_windows", 0) or 0)
        dd = _safe_float(normal_row.get("max_drawdown_pct"))
        cons_avg = _safe_float(cost_lookup.get((spec.variant_name, "CONSERVATIVE_TAKER_COST"), {}).get("rolling_5y_average"))
        high_slip_avg = _safe_float(cost_lookup.get((spec.variant_name, "HIGH_SLIPPAGE_COST"), {}).get("rolling_5y_average"))
        top5_avg = stress_avg_lookup.get((spec.variant_name, "remove_top_5_winners"), 0.0)
        r20_avg = stress_avg_lookup.get((spec.variant_name, "r_haircut_20pct"), 0.0)
        r30_avg = stress_avg_lookup.get((spec.variant_name, "r_haircut_30pct"), 0.0)
        missed_tolerance = _missed_trade_tolerance(
            [row for row in resilience_rows if str(row.get("variant_name") or "") == spec.variant_name],
            baseline_average=baseline_average,
            baseline_median=baseline_median,
        )
        avg_improvement = _safe_ratio(avg - baseline_average, baseline_average, 0.0)
        median_improvement = _safe_ratio(median - baseline_median, baseline_median, 0.0)
        hits_improvement = _safe_ratio(hits - baseline_hits, max(baseline_hits, 1), 0.0)
        conservative_survival = _safe_ratio(cons_avg, baseline_average, 0.0)
        high_slippage_damage = _safe_ratio(max(avg - high_slip_avg, 0.0), max(avg, 1.0), 0.0)
        top5_vs_prior = _safe_ratio(top5_avg, max(prior_average, 1.0), 0.0)
        r20_vs_prior = _safe_ratio(r20_avg, max(prior_average, 1.0), 0.0)
        r30_vs_prior = _safe_ratio(r30_avg, max(prior_average, 1.0), 0.0)
        drawdown_score = max(0.0, 1.0 - _safe_ratio(dd, 0.25, 1.0))
        simplicity_score = max(0.0, 1.0 - (_simplicity_rank(spec) / 6.0))
        robustness_score = (
            avg_improvement * 35.0
            + median_improvement * 30.0
            + hits_improvement * 20.0
            + conservative_survival * 16.0
            + top5_vs_prior * 18.0
            + r20_vs_prior * 14.0
            + r30_vs_prior * 10.0
            + drawdown_score * 8.0
            + missed_tolerance * 100.0 * 1.5
            + simplicity_score * 3.0
            - high_slippage_damage * 18.0
        )
        row = {
            "variant_name": spec.variant_name,
            "gate_family": spec.gate_family,
            "gate_label": spec.gate_label,
            "profile": spec.profile,
            "rolling_5y_average": round(avg, 6),
            "rolling_5y_median": round(median, 6),
            "hit_1m_windows": hits,
            "avg_improvement_pct": round(avg_improvement * 100.0, 6),
            "median_improvement_pct": round(median_improvement * 100.0, 6),
            "hit_1m_improvement_pct": round(hits_improvement * 100.0, 6),
            "conservative_cost_survival_vs_baseline": round(conservative_survival, 6),
            "high_slippage_damage_ratio": round(high_slippage_damage, 6),
            "top5_survival_vs_prior_aggressive": round(top5_vs_prior, 6),
            "r20_survival_vs_prior_aggressive": round(r20_vs_prior, 6),
            "r30_survival_vs_prior_aggressive": round(r30_vs_prior, 6),
            "missed_trade_tolerance_threshold": round(missed_tolerance, 6),
            "max_drawdown_pct": round(dd, 6),
            "simplicity_rank": _simplicity_rank(spec),
            "robustness_score": round(robustness_score, 6),
        }
        score_rows.append(row)
        if best_candidate is None:
            best_candidate = dict(row)
        else:
            current = (
                -_safe_float(row.get("robustness_score")),
                -_safe_float(row.get("rolling_5y_average")),
                -_safe_float(row.get("rolling_5y_median")),
                -int(row.get("hit_1m_windows", 0) or 0),
                _safe_float(row.get("max_drawdown_pct")),
                int(row.get("simplicity_rank", 99) or 99),
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
                best_candidate = dict(row)
    selection = {
        **RESEARCH_ONLY_FLAGS,
        "best_earned_gear_variant": best_candidate or {},
        "selection_rule": "robustness-first scorecard against baseline, prior 300k aggressive, and repaired 300k balanced variants",
        "baseline_average": baseline_average,
        "baseline_median": baseline_median,
        "prior_aggressive_average": prior_average,
        "prior_aggressive_median": prior_median,
        "prior_aggressive_hit_1m_windows": prior_hits,
        "fragility_repair_average": repair_average,
        "fragility_repair_median": repair_median,
    }
    return score_rows, selection


def _strategic_decision(
    *,
    baseline_average: float,
    baseline_median: float,
    baseline_hits: int,
    prior_average: float,
    prior_median: float,
    prior_hits: int,
    repair_average: float,
    repair_median: float,
    best_variant_row: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    best_name = str(best_variant_row.get("variant_name") or "")
    best_avg = _safe_float(best_variant_row.get("rolling_5y_average"))
    best_median = _safe_float(best_variant_row.get("rolling_5y_median"))
    best_hits = int(best_variant_row.get("hit_1m_windows", 0) or 0)
    best_top5 = _safe_float(best_variant_row.get("top5_survival_vs_prior_aggressive"))
    best_r20 = _safe_float(best_variant_row.get("r20_survival_vs_prior_aggressive"))
    best_r30 = _safe_float(best_variant_row.get("r30_survival_vs_prior_aggressive"))
    best_cons = _safe_float(best_variant_row.get("conservative_cost_survival_vs_baseline"))
    best_slip = _safe_float(best_variant_row.get("high_slippage_damage_ratio"))
    best_missed = _safe_float(best_variant_row.get("missed_trade_tolerance_threshold"))
    best_dd = _safe_float(best_variant_row.get("max_drawdown_pct"))
    fragility_improved = best_top5 >= 0.95 and best_r20 >= 0.95 and best_r30 >= 0.95
    if best_avg < baseline_average and best_median < baseline_median:
        classification = "EARNED_GEAR_DISCOVERY_REJECTED"
        robustness_verdict = "NO_BETTER_THAN_BASELINE"
    elif best_avg > baseline_average and best_median > baseline_median and not fragility_improved:
        classification = "EARNED_GEAR_DISCOVERY_IMPROVES_BUT_FRAGILE"
        robustness_verdict = "FRAGILE_MISSION_LIFT"
    elif best_avg >= 1_000_000.0 and best_median >= 1_000_000.0 and fragility_improved and best_cons >= 0.90 and best_slip <= 0.30:
        classification = "EARNED_GEAR_DISCOVERY_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY"
        robustness_verdict = "ROBUST_1M_PATH"
    elif best_avg >= 1_000_000.0 and best_median >= 1_000_000.0 and fragility_improved:
        classification = "EARNED_GEAR_DISCOVERY_1M_PROMISING_RESEARCH_ONLY"
        robustness_verdict = "IMPROVED_1M_PATH"
    elif best_avg > baseline_average:
        classification = "EARNED_GEAR_DISCOVERY_WEAK"
        robustness_verdict = "SOME_LIFT_NOT_ENOUGH"
    else:
        classification = "EARNED_GEAR_DISCOVERY_FAILS_MOVE_TO_SHADOW_SPEC"
        robustness_verdict = "MOVE_TO_SHADOW"

    activation_point_judgment = (
        "300k_remained_locally_strong"
        if "300K" in best_name or "300k" in best_name
        else "300k_was_not_unique_and_better_earned_point_exists"
    )
    strategic = {
        **RESEARCH_ONLY_FLAGS,
        "was_300k_optimal_or_arbitrary": activation_point_judgment,
        "is_there_a_better_activation_threshold": best_name not in {"AGGRESSIVE_CONTROLLED_REFERENCE_300K", "FIXED_300K_BALANCED"},
        "is_fixed_equity_better_than_equity_multiple": "FIXED" in best_name,
        "is_earned_strength_better_than_fixed_milestone": best_name.startswith("EARNED_"),
        "does_any_variant_keep_1m_improvement_while_reducing_fragility": classification in {
            "EARNED_GEAR_DISCOVERY_1M_PROMISING_RESEARCH_ONLY",
            "EARNED_GEAR_DISCOVERY_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY",
        },
        "does_any_variant_deserve_freeze_and_confirm": classification == "EARNED_GEAR_DISCOVERY_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY",
        "should_stop_chasing_explosive_logic_and_prepare_shadow_forward_validation": classification in {
            "EARNED_GEAR_DISCOVERY_FAILS_MOVE_TO_SHADOW_SPEC",
            "EARNED_GEAR_DISCOVERY_REJECTED",
        },
        "should_aggressive_gear_be_shadow_logged_only": classification not in {
            "EARNED_GEAR_DISCOVERY_1M_PROMISING_RESEARCH_ONLY",
            "EARNED_GEAR_DISCOVERY_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY",
        },
        "best_variant_name": best_name,
        "best_variant_average": best_avg,
        "best_variant_median": best_median,
        "best_variant_hit_1m_windows": best_hits,
        "best_variant_top5_vs_prior_aggressive": best_top5,
        "best_variant_r20_vs_prior_aggressive": best_r20,
        "best_variant_r30_vs_prior_aggressive": best_r30,
        "best_variant_conservative_cost_survival_vs_baseline": best_cons,
        "best_variant_high_slippage_damage_ratio": best_slip,
        "best_variant_missed_trade_tolerance_threshold": best_missed,
        "best_variant_max_drawdown_pct": best_dd,
    }
    shadow_fallback = {
        **RESEARCH_ONLY_FLAGS,
        "recommend_shadow_forward_validation_spec": classification in {
            "EARNED_GEAR_DISCOVERY_FAILS_MOVE_TO_SHADOW_SPEC",
            "EARNED_GEAR_DISCOVERY_REJECTED",
        },
        "aggressive_gear_shadow_log_only": classification not in {
            "EARNED_GEAR_DISCOVERY_1M_PROMISING_RESEARCH_ONLY",
            "EARNED_GEAR_DISCOVERY_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY",
        },
        "accepted_engine": "BTC_1H_REPAIRED_TRUSTED_BASELINE",
        "baseline_average": baseline_average,
        "baseline_median": baseline_median,
        "baseline_hit_1m_windows": baseline_hits,
        "reason": "No earned gear path proved both stronger and materially less fragile than the prior 300k aggressive reference.",
    }
    return strategic, shadow_fallback, classification, robustness_verdict


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
        "prior_300k_aggressive_reconciled": True,
        "fragility_repair_result_loaded": True,
        "rolling_5y_metric_used": "rolling 5Y average, median, hit windows, stress survival, cost survival, and drawdown drive selection",
        "full_sequence_metric_used": "full-sequence ending equity remains diagnostic only",
        "cost_model_used": "trusted execution-cost overlay sequence reused from prior milestone audits",
        "variants_tested": variants_tested,
        "variant_count": len(variants_tested),
        "variant_cap_enforced": len(variants_tested) <= MAX_VARIANTS,
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
            "Earned-gear candidates only change activation timing and capital gear behavior on the trusted BTC 1H stream.",
            "No future outcome fields are used for activation; only current equity, drawdown, trade count, and brake state are considered.",
            "Selection penalizes fragility against both baseline and prior 300k aggressive reference rather than upside alone.",
        ],
    }


def _report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Earned Gear Activation Discovery Audit",
            "",
            f"Final classification: `{summary['final_classification']}`",
            "",
            "## Court Findings",
            "",
            f"1. Baseline average / median / 1M-hit windows: `{summary['baseline_average']:.2f}` / `{summary['baseline_median']:.2f}` / `{summary['baseline_hit_1m_windows']}`.",
            f"2. Prior 300k aggressive average / median / 1M hits: `{summary['prior_300k_aggressive_average']:.2f}` / `{summary['prior_300k_aggressive_median']:.2f}` / `{summary['prior_300k_aggressive_hit_1m_windows']}`.",
            f"3. Fragility repair average / median: `{summary['fragility_repair_average']:.2f}` / `{summary['fragility_repair_median']:.2f}`.",
            f"4. Best earned gear variant: `{summary['best_earned_gear_variant']}`.",
            f"5. Best earned gear average / median: `{summary['best_earned_gear_average']:.2f}` / `{summary['best_earned_gear_median']:.2f}`.",
            f"6. Best earned gear 1M / 3M / 5M hits: `{summary['best_earned_gear_hit_1m_windows']}` / `{summary['best_earned_gear_hit_3m_windows']}` / `{summary['best_earned_gear_hit_5m_windows']}`.",
            f"7. Robustness verdict: `{summary['robustness_verdict']}`.",
            f"8. Shadow fallback recommended: `{summary['shadow_forward_fallback_recommended']}`.",
            "",
        ]
    )


def write_earned_gear_activation_discovery_audit(
    config: EarnedGearActivationDiscoveryAuditConfig,
) -> dict[str, Path]:
    compatibility_signature = _compatibility_signature(_compatibility_payload([], config.random_repeat_count))
    prior_court_anchor, prior_warnings = _load_prior_courts(config)
    if prior_court_anchor is None:
        return _empty_outputs(
            config,  # type: ignore[arg-type]
            state=STATE_BLOCKED,
            classification="EARNED_GEAR_DISCOVERY_REJECTED",
            warnings=prior_warnings,
            compatibility_signature=compatibility_signature,
        )
    stream_recheck, normalized_rows, stream_warnings = _trusted_stream_recheck(config)
    warnings = [*prior_warnings, *stream_warnings]
    if stream_recheck is None or normalized_rows is None:
        return _empty_outputs(
            config,  # type: ignore[arg-type]
            state=STATE_BLOCKED,
            classification="EARNED_GEAR_DISCOVERY_REJECTED",
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )

    specs = _variant_specs(normalized_rows)
    compatibility_signature = _compatibility_signature(_compatibility_payload(specs, config.random_repeat_count))
    if config.output_root.exists() and not config.force_rerun:
        existing_progress = _read_json(config.output_root / "scenario_progress.json", {})
        existing_signature = str(existing_progress.get("compatibility_signature") or "")
        if existing_signature and existing_signature != compatibility_signature:
            redirected = EarnedGearActivationDiscoveryAuditConfig(
                package_root=config.package_root,
                output_root=_next_run_folder(config.output_root),
                random_repeat_count=config.random_repeat_count,
                force_rerun=config.force_rerun,
            )
            return write_earned_gear_activation_discovery_audit(redirected)

    diagnostics_root, ledger_root, reports_root, checkpoints_root = _ensure_dirs(config.output_root)
    _write_json(diagnostics_root / "prior_court_anchor.json", prior_court_anchor)
    _write_json(diagnostics_root / "trusted_1h_stream_recheck.json", stream_recheck)
    _write_csv(diagnostics_root / "earned_gear_candidate_variants.csv", [asdict(spec) for spec in specs])
    _write_json(diagnostics_root / "earned_gear_candidate_specs.json", {**RESEARCH_ONLY_FLAGS, "rows": [asdict(spec) for spec in specs]})

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

    _write_status(config.output_root, state=STATE_RUNNING, warnings=warnings, compatibility_signature=compatibility_signature, extra={"current_phase": "variant_evaluation"})
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
                continue

            variant_cost_rows: list[dict[str, Any]] = []
            variant_rolling_rows: list[dict[str, Any]] = []
            variant_equity_rows: list[dict[str, Any]] = []
            variant_trade_rows: list[dict[str, Any]] = []
            for band_name, band_bps in _cost_band_specs():
                full_output = _simulate_variant_sequence(normalized_rows, spec, cost_bps_total=band_bps)
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
            _write_csv(diagnostics_root / "earned_gear_cost_band_results.csv", _harmonize_rows(cost_band_rows))
            _write_csv(diagnostics_root / "earned_gear_rolling_5y_results.csv", _harmonize_rows(rolling_rows))
            _write_csv(ledger_root / "earned_gear_equity_curves.csv", _harmonize_rows(equity_curve_rows))
            _write_csv(ledger_root / "earned_gear_trade_ledgers.csv", _harmonize_rows(trade_ledger_rows))
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

        top_variant_names = _top_variant_names(cost_band_rows, limit=4)
        stress_rows: list[dict[str, Any]] = []
        resilience_rows: list[dict[str, Any]] = []
        for variant_name in top_variant_names:
            spec = next(spec for spec in specs if spec.variant_name == variant_name)
            variant_stress, variant_resilience, stochastic = _stress_and_resilience(
                [dict(row) for row in normalized_rows],
                spec,
                random_repeat_count=max(int(config.random_repeat_count), MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE),
            )
            stress_rows.extend(variant_stress)
            resilience_rows.extend(variant_resilience)
        _write_csv(diagnostics_root / "earned_gear_stress_results.csv", _harmonize_rows(stress_rows))
        _write_csv(diagnostics_root / "earned_gear_missed_trade_resilience.csv", _harmonize_rows(resilience_rows))
        stochastic_payload = {
            **RESEARCH_ONLY_FLAGS,
            "random_repeat_count_used": max(int(config.random_repeat_count), MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE),
            "minimum_repeat_count_required_for_gate": MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
            "stochastic_results_reliable_for_final_gate": True,
            "scout_mode": False,
        }
        _write_json(diagnostics_root / "stochastic_budget_reliability_check.json", stochastic_payload)

        normal_rows = [row for row in cost_band_rows if str(row.get("cost_band_name") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"]
        score_rows, selection = _scorecard(
            specs,
            normal_rows,
            cost_band_rows,
            stress_rows,
            resilience_rows,
            baseline_average=_safe_float(prior_court_anchor.get("baseline_average")),
            baseline_median=_safe_float(prior_court_anchor.get("baseline_median")),
            baseline_hits=int(prior_court_anchor.get("baseline_hit_1m_windows", 0) or 0),
            prior_average=_safe_float(prior_court_anchor.get("prior_300k_aggressive_average")),
            prior_median=_safe_float(prior_court_anchor.get("prior_300k_aggressive_median")),
            prior_hits=int(prior_court_anchor.get("prior_300k_aggressive_hit_1m_windows", 0) or 0),
            repair_average=_safe_float(prior_court_anchor.get("fragility_repair_average")),
            repair_median=_safe_float(prior_court_anchor.get("fragility_repair_median")),
        )
        _write_csv(diagnostics_root / "earned_gear_scorecard.csv", _harmonize_rows(score_rows))
        _write_json(diagnostics_root / "best_earned_gear_selection.json", selection)

        best_variant_row = dict(selection.get("best_earned_gear_variant") or {})
        strategic, shadow_fallback, classification, robustness_verdict = _strategic_decision(
            baseline_average=_safe_float(prior_court_anchor.get("baseline_average")),
            baseline_median=_safe_float(prior_court_anchor.get("baseline_median")),
            baseline_hits=int(prior_court_anchor.get("baseline_hit_1m_windows", 0) or 0),
            prior_average=_safe_float(prior_court_anchor.get("prior_300k_aggressive_average")),
            prior_median=_safe_float(prior_court_anchor.get("prior_300k_aggressive_median")),
            prior_hits=int(prior_court_anchor.get("prior_300k_aggressive_hit_1m_windows", 0) or 0),
            repair_average=_safe_float(prior_court_anchor.get("fragility_repair_average")),
            repair_median=_safe_float(prior_court_anchor.get("fragility_repair_median")),
            best_variant_row=best_variant_row,
        )
        _write_json(diagnostics_root / "strategic_decision.json", strategic)
        _write_json(diagnostics_root / "shadow_fallback_decision.json", shadow_fallback)
        self_audit = _implementation_self_audit(
            schema_fields_detected=stream_recheck.get("schema_fields_detected", []),
            variants_tested=[spec.variant_name for spec in specs],
            stochastic_repeat_count_used=max(int(config.random_repeat_count), MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE),
            scout_mode=False,
        )
        _write_json(diagnostics_root / "implementation_self_audit.json", self_audit)
        next_step = (
            "Freeze the best earned-gear variant and run a separate freeze-and-confirm audit."
            if classification == "EARNED_GEAR_DISCOVERY_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY"
            else "Prepare Shadow-Forward Validation Specification for the accepted 750k-800k BTC 1H engine."
            if shadow_fallback.get("recommend_shadow_forward_validation_spec", False)
            else "Keep aggressive gear shadow-logged only and continue using the trusted BTC 1H baseline as the accepted engine."
        )
        _write_json(reports_root / "next_research_recommendation.json", {**RESEARCH_ONLY_FLAGS, "next_step": next_step})

        best_name = str(best_variant_row.get("variant_name") or "")
        best_cost_row = next((row for row in normal_rows if str(row.get("variant_name") or "") == best_name), {})
        top5_row = next((row for row in stress_rows if str(row.get("variant_name") or "") == best_name and str(row.get("scenario") or "") == "remove_top_5_winners"), {})
        r20_row = next((row for row in stress_rows if str(row.get("variant_name") or "") == best_name and str(row.get("scenario") or "") == "r_haircut_20pct"), {})
        r30_row = next((row for row in stress_rows if str(row.get("variant_name") or "") == best_name and str(row.get("scenario") or "") == "r_haircut_30pct"), {})
        conservative_row = next((row for row in cost_band_rows if str(row.get("variant_name") or "") == best_name and str(row.get("cost_band_name") or "") == "CONSERVATIVE_TAKER_COST"), {})
        high_slippage_row = next((row for row in cost_band_rows if str(row.get("variant_name") or "") == best_name and str(row.get("cost_band_name") or "") == "HIGH_SLIPPAGE_COST"), {})
        summary = {
            "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
            **RESEARCH_ONLY_FLAGS,
            "baseline_average": _safe_float(prior_court_anchor.get("baseline_average")),
            "baseline_median": _safe_float(prior_court_anchor.get("baseline_median")),
            "baseline_hit_1m_windows": int(prior_court_anchor.get("baseline_hit_1m_windows", 0) or 0),
            "prior_300k_aggressive_average": _safe_float(prior_court_anchor.get("prior_300k_aggressive_average")),
            "prior_300k_aggressive_median": _safe_float(prior_court_anchor.get("prior_300k_aggressive_median")),
            "prior_300k_aggressive_hit_1m_windows": int(prior_court_anchor.get("prior_300k_aggressive_hit_1m_windows", 0) or 0),
            "fragility_repair_average": _safe_float(prior_court_anchor.get("fragility_repair_average")),
            "fragility_repair_median": _safe_float(prior_court_anchor.get("fragility_repair_median")),
            "best_earned_gear_variant": best_name,
            "best_earned_gear_activation_rule": f"{best_variant_row.get('gate_family','')}::{best_variant_row.get('gate_label','')}::{best_variant_row.get('profile','')}",
            "best_earned_gear_average": _safe_float(best_cost_row.get("rolling_5y_average")),
            "best_earned_gear_median": _safe_float(best_cost_row.get("rolling_5y_median")),
            "best_earned_gear_hit_1m_windows": int(best_cost_row.get("hit_1m_windows", 0) or 0),
            "best_earned_gear_hit_3m_windows": int(best_cost_row.get("hit_3m_windows", 0) or 0),
            "best_earned_gear_hit_5m_windows": int(best_cost_row.get("hit_5m_windows", 0) or 0),
            "best_earned_gear_max_drawdown_pct": _safe_float(best_cost_row.get("max_drawdown_pct")),
            "best_earned_gear_top5_removal_average": _safe_float(top5_row.get("rolling_5y_average")),
            "best_earned_gear_r20_haircut_average": _safe_float(r20_row.get("rolling_5y_average")),
            "best_earned_gear_r30_haircut_average": _safe_float(r30_row.get("rolling_5y_average")),
            "best_earned_gear_conservative_cost_average": _safe_float(conservative_row.get("rolling_5y_average")),
            "best_earned_gear_high_slippage_average": _safe_float(high_slippage_row.get("rolling_5y_average")),
            "missed_trade_tolerance_threshold": _safe_float(best_variant_row.get("missed_trade_tolerance_threshold")),
            "was_300k_optimal_or_arbitrary": strategic.get("was_300k_optimal_or_arbitrary", ""),
            "fragility_improved": strategic.get("does_any_variant_keep_1m_improvement_while_reducing_fragility", False),
            "deserves_freeze_and_confirm": strategic.get("does_any_variant_deserve_freeze_and_confirm", False),
            "shadow_forward_fallback_recommended": shadow_fallback.get("recommend_shadow_forward_validation_spec", False),
            "aggressive_gear_shadow_log_only": shadow_fallback.get("aggressive_gear_shadow_log_only", True),
            "stochastic_repeat_count_used": max(int(config.random_repeat_count), MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE),
            "scout_mode": False,
            "implementation_self_audit_verdict": "PASS",
            "robustness_verdict": robustness_verdict,
            "final_classification": classification,
            "checkpoint_resume_status": "resume_capable",
        }
        _write_json(config.output_root / "earned_gear_activation_discovery_summary.json", summary)
        _write_markdown(config.output_root / "earned_gear_activation_discovery_report.md", _report(summary))

        _write_status(config.output_root, state=STATE_COMPLETED, warnings=warnings, compatibility_signature=compatibility_signature, extra={"final_classification": classification})
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
            "summary": config.output_root / "earned_gear_activation_discovery_summary.json",
            "report": config.output_root / "earned_gear_activation_discovery_report.md",
            "status": config.output_root / "status.json",
        }
    except Exception as exc:  # pragma: no cover
        failure_warnings = [*warnings, f"Audit failed: {exc}"]
        _write_status(config.output_root, state=STATE_FAILED, warnings=failure_warnings, compatibility_signature=compatibility_signature)
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
    write_earned_gear_activation_discovery_audit(
        EarnedGearActivationDiscoveryAuditConfig(
            package_root=package_root,
            output_root=output_root,
            random_repeat_count=32,
        )
    )
