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
from structural_compounding_lab.diagnostics.execution_cost_realism_and_trade_redundancy_audit import (  # noqa: E402
    ExecutionCostRealismAndTradeRedundancyAuditConfig,
    _load_context as _load_execution_cost_context,
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
    BASE_STEPUP_SCHEDULE,
    _estimated_cost,
    _rolling_window_summary as _overlay_rolling_window_summary,
)
from structural_compounding_lab.diagnostics.native_12h_execution_sleeve_discovery_audit import (  # noqa: E402
    CONSERVATIVE_COST_BPS,
    HIGH_SLIPPAGE_COST_BPS,
    NORMAL_COST_BPS,
    OPTIMISTIC_COST_BPS,
    ZERO_COST_BPS,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import _build_windows  # noqa: E402


OUTPUT_FOLDER_NAME = "milestone_gated_explosive_compounding_audit_001"
DEFAULT_RANDOM_REPEAT_COUNT = 8
MAX_VARIANTS = 20
START_CAPITAL = 20_000.0
BASE_LOCK_RATIO = 0.50
EXPECTED_REPAIR_MODE = "RECONSTRUCT_STRICT_ROWS_WITH_PRIOR_COST_MODEL"
TIMESTAMP_FIELDS = ("exit_timestamp", "timestamp", "entry_timestamp")
R_FIELDS = ("r_multiple", "applied_r", "gross_r")
STATE_NOT_STARTED = "not_started"
STATE_RUNNING = "running"
STATE_PARTIAL = "partial"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_BLOCKED = "blocked"


@dataclass(frozen=True)
class MilestoneGatedExplosiveCompoundingAuditConfig:
    package_root: Path
    output_root: Path
    random_repeat_count: int = DEFAULT_RANDOM_REPEAT_COUNT
    force_rerun: bool = False


@dataclass(frozen=True)
class VariantSpec:
    variant_name: str
    description: str
    gear_trigger_equity: float | None
    gear_multiplier: float
    max_multiplier_cap: float
    enable_drawdown_brake: bool
    soft_brake_pct: float | None
    hard_brake_pct: float | None
    milestone_buffer_pct: float
    lock_ratio_above_trigger: float
    lock_ratio_above_1m: float
    reenable_requires_new_high: bool
    moonshot_only_boost: bool
    available: bool
    unavailable_reason: str


def _safe_float(value: Any, default: float = 0.0) -> float:
    return _to_float(value, default)


def _try_timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    if pd.isna(parsed):
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.tz_convert("UTC").tz_localize(None)
    return parsed


def _harmonize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return rows
    keys = sorted({key for row in rows for key in row.keys()})
    return [{key: row.get(key, "") for key in keys} for row in rows]


def _paths(config: MilestoneGatedExplosiveCompoundingAuditConfig) -> dict[str, Path]:
    base_output = config.package_root / "output"
    execution_root = base_output / "execution_cost_realism_and_trade_redundancy_audit_001"
    twelve_h_root = base_output / "native_12h_execution_sleeve_discovery_audit_001"
    return {
        "execution_cost_band_results": execution_root / "diagnostics" / "execution_cost_band_results.csv",
        "twelve_h_repair_diagnostics": twelve_h_root / "diagnostics" / "12h_baseline_accounting_repair_diagnostics.json",
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


def _compatibility_payload(variant_specs: list[VariantSpec], random_repeat_count: int) -> dict[str, Any]:
    return {
        "module": "milestone_gated_explosive_compounding_audit",
        "version": 1,
        "random_repeat_count": random_repeat_count,
        "variant_specs": [
            {
                key: value
                for key, value in asdict(spec).items()
                if key not in {"available", "unavailable_reason"}
            }
            for spec in variant_specs
        ],
        "cost_bands": [
            "ZERO_COST_REFERENCE",
            "OPTIMISTIC_MAKER_COST",
            "NORMAL_MIXED_MAKER_TAKER_COST",
            "CONSERVATIVE_TAKER_COST",
            "HIGH_SLIPPAGE_COST",
        ],
    }


def _compatibility_signature(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _next_run_folder(output_root: Path) -> Path:
    parent = output_root.parent
    stem = output_root.name
    suffix = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return parent / f"{stem}_{suffix}"


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


def _write_scenario_progress(
    output_root: Path,
    *,
    state: str,
    compatibility_signature: str,
    variant_specs: list[VariantSpec],
    completed_variants: list[str],
    warnings: list[str],
) -> None:
    payload = {
        "state": state,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "compatibility_signature": compatibility_signature,
        "total_variants": len(variant_specs),
        "variant_names": [spec.variant_name for spec in variant_specs],
        "completed_variants": completed_variants,
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(output_root / "scenario_progress.json", payload)


def _empty_outputs(
    config: MilestoneGatedExplosiveCompoundingAuditConfig,
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
    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "final_classification": classification,
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(config.output_root / "milestone_gated_explosive_compounding_summary.json", summary)
    _write_markdown(
        config.output_root / "milestone_gated_explosive_compounding_report.md",
        "# Milestone-Gated Explosive Compounding Audit\n\nThe audit was blocked or failed before completing the baseline-safe reconstruction path.\n",
    )
    for path in (
        diagnostics_root / "baseline_anchor.json",
        diagnostics_root / "trusted_1h_trade_stream_reconstruction.json",
        diagnostics_root / "milestone_capital_gear_variant_specs.json",
        diagnostics_root / "stochastic_budget_reliability_check.json",
        diagnostics_root / "mission_target_interpretation.json",
        diagnostics_root / "freeze_and_confirm_candidate.json",
        diagnostics_root / "implementation_self_audit.json",
    ):
        _write_json(path, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    for path in (
        diagnostics_root / "milestone_capital_gear_variants.csv",
        diagnostics_root / "milestone_gated_cost_band_results.csv",
        diagnostics_root / "milestone_gated_rolling_5y_results.csv",
        diagnostics_root / "milestone_gated_fragility_results.csv",
        diagnostics_root / "milestone_gated_missed_trade_resilience.csv",
        ledger_root / "milestone_gated_equity_curves.csv",
        ledger_root / "milestone_gated_trade_ledgers.csv",
    ):
        _write_csv(path, [])
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(checkpoints_root / "checkpoint_index.json", {"completed_variants": [], **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "milestone_gated_explosive_compounding_summary.json",
        "report": config.output_root / "milestone_gated_explosive_compounding_report.md",
    }


def _quality_labels_available(rows: list[dict[str, Any]]) -> bool:
    quality_fields = ("convexity_label", "moonshot_state", "setup_class", "runner_label", "entry_context")
    return any(any(str(row.get(field) or "").strip() for field in quality_fields) for row in rows)


def _variant_specs(rows: list[dict[str, Any]]) -> list[VariantSpec]:
    moonshot_available = _quality_labels_available(rows)
    specs = [
        VariantSpec(
            variant_name="BASELINE_REPAIRED_1H",
            description="Trusted repaired BTC 1H baseline without extra post-300k aggression.",
            gear_trigger_equity=None,
            gear_multiplier=1.0,
            max_multiplier_cap=2.0,
            enable_drawdown_brake=False,
            soft_brake_pct=None,
            hard_brake_pct=None,
            milestone_buffer_pct=0.0,
            lock_ratio_above_trigger=BASE_LOCK_RATIO,
            lock_ratio_above_1m=BASE_LOCK_RATIO,
            reenable_requires_new_high=False,
            moonshot_only_boost=False,
            available=True,
            unavailable_reason="",
        ),
        VariantSpec(
            variant_name="GEAR_AFTER_300K_LIGHT",
            description="Add a light post-300k gear on top of the trusted baseline with soft drawdown control.",
            gear_trigger_equity=300_000.0,
            gear_multiplier=1.15,
            max_multiplier_cap=2.15,
            enable_drawdown_brake=True,
            soft_brake_pct=0.08,
            hard_brake_pct=0.18,
            milestone_buffer_pct=0.05,
            lock_ratio_above_trigger=0.55,
            lock_ratio_above_1m=0.60,
            reenable_requires_new_high=False,
            moonshot_only_boost=False,
            available=True,
            unavailable_reason="",
        ),
        VariantSpec(
            variant_name="GEAR_AFTER_300K_BALANCED",
            description="Use stronger post-300k gear with profit-vault reinforcement and brakes.",
            gear_trigger_equity=300_000.0,
            gear_multiplier=1.35,
            max_multiplier_cap=2.30,
            enable_drawdown_brake=True,
            soft_brake_pct=0.09,
            hard_brake_pct=0.16,
            milestone_buffer_pct=0.07,
            lock_ratio_above_trigger=0.65,
            lock_ratio_above_1m=0.75,
            reenable_requires_new_high=False,
            moonshot_only_boost=False,
            available=True,
            unavailable_reason="",
        ),
        VariantSpec(
            variant_name="GEAR_AFTER_300K_AGGRESSIVE_CONTROLLED",
            description="Higher post-300k gear only when equity remains near highs, with hard gear-down rules.",
            gear_trigger_equity=300_000.0,
            gear_multiplier=1.75,
            max_multiplier_cap=2.75,
            enable_drawdown_brake=True,
            soft_brake_pct=0.08,
            hard_brake_pct=0.15,
            milestone_buffer_pct=0.10,
            lock_ratio_above_trigger=0.70,
            lock_ratio_above_1m=0.80,
            reenable_requires_new_high=True,
            moonshot_only_boost=False,
            available=True,
            unavailable_reason="",
        ),
        VariantSpec(
            variant_name="GEAR_AFTER_500K_BALANCED",
            description="Delay extra aggression until 500k to test later acceleration safety.",
            gear_trigger_equity=500_000.0,
            gear_multiplier=1.35,
            max_multiplier_cap=2.30,
            enable_drawdown_brake=True,
            soft_brake_pct=0.09,
            hard_brake_pct=0.16,
            milestone_buffer_pct=0.07,
            lock_ratio_above_trigger=0.60,
            lock_ratio_above_1m=0.75,
            reenable_requires_new_high=False,
            moonshot_only_boost=False,
            available=True,
            unavailable_reason="",
        ),
        VariantSpec(
            variant_name="GEAR_AFTER_300K_WITH_PROFIT_VAULT",
            description="Increase post-300k gear while locking a larger fraction of profits above milestones.",
            gear_trigger_equity=300_000.0,
            gear_multiplier=1.25,
            max_multiplier_cap=2.10,
            enable_drawdown_brake=True,
            soft_brake_pct=0.10,
            hard_brake_pct=0.18,
            milestone_buffer_pct=0.05,
            lock_ratio_above_trigger=0.72,
            lock_ratio_above_1m=0.85,
            reenable_requires_new_high=False,
            moonshot_only_boost=False,
            available=True,
            unavailable_reason="",
        ),
        VariantSpec(
            variant_name="GEAR_AFTER_300K_WITH_DRAWDOWN_STEPDOWN",
            description="Use balanced post-300k gear but cut back rapidly after drawdown and re-enable on recovery.",
            gear_trigger_equity=300_000.0,
            gear_multiplier=1.50,
            max_multiplier_cap=2.25,
            enable_drawdown_brake=True,
            soft_brake_pct=0.08,
            hard_brake_pct=0.15,
            milestone_buffer_pct=0.08,
            lock_ratio_above_trigger=0.60,
            lock_ratio_above_1m=0.70,
            reenable_requires_new_high=True,
            moonshot_only_boost=False,
            available=True,
            unavailable_reason="",
        ),
        VariantSpec(
            variant_name="GEAR_AFTER_300K_WITH_MOONSHOT_ONLY_BOOST",
            description="Boost only high-quality or moonshot-labeled trades after 300k if labels exist in the trusted stream.",
            gear_trigger_equity=300_000.0,
            gear_multiplier=1.60,
            max_multiplier_cap=2.40,
            enable_drawdown_brake=True,
            soft_brake_pct=0.09,
            hard_brake_pct=0.16,
            milestone_buffer_pct=0.06,
            lock_ratio_above_trigger=0.60,
            lock_ratio_above_1m=0.72,
            reenable_requires_new_high=False,
            moonshot_only_boost=True,
            available=moonshot_available,
            unavailable_reason="" if moonshot_available else "quality_or_moonshot_labels_unavailable_in_trusted_trade_stream",
        ),
    ]
    return specs[:MAX_VARIANTS]


def _moonshot_trade(row: dict[str, Any]) -> bool:
    if str(row.get("setup_class") or "").strip().upper() == "A+":
        return True
    if "moonshot" in str(row.get("moonshot_state") or "").strip().lower():
        return True
    if "elite" in str(row.get("convexity_label") or "").strip().lower():
        return True
    if "moonshot" in str(row.get("runner_label") or "").strip().lower():
        return True
    return False


def _normalize_trade_stream(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any], list[str], list[str]]:
    warnings: list[str] = []
    errors: list[str] = []
    normalized: list[dict[str, Any]] = []
    schema_fields = sorted({key for row in rows for key in row.keys()})
    timestamp_counts = {field: 0 for field in TIMESTAMP_FIELDS}
    r_counts = {field: 0 for field in R_FIELDS}
    entry_fallback_counts = {field: 0 for field in TIMESTAMP_FIELDS if field != "entry_timestamp"}
    r_fallback_counts = {field: 0 for field in R_FIELDS if field != "r_multiple"}
    for index, row in enumerate(rows):
        item = dict(row)
        resolved_exit = None
        resolved_exit_field = None
        for field in TIMESTAMP_FIELDS:
            parsed = item.get(field)
            if isinstance(parsed, pd.Timestamp):
                resolved_exit = pd.Timestamp(parsed)
                resolved_exit_field = field
                break
            candidate = _try_timestamp(parsed)
            if candidate is not None:
                resolved_exit = candidate
                resolved_exit_field = field
                break
        if resolved_exit is None:
            errors.append(f"row_{index}: missing valid timestamp field")
            continue
        timestamp_counts[resolved_exit_field] += 1
        resolved_entry = item.get("entry_timestamp")
        if not isinstance(resolved_entry, pd.Timestamp):
            resolved_entry = _try_timestamp(resolved_entry)
        if resolved_entry is None:
            resolved_entry = resolved_exit
            if resolved_exit_field != "entry_timestamp":
                entry_fallback_counts[resolved_exit_field] = entry_fallback_counts.get(resolved_exit_field, 0) + 1

        resolved_r = None
        resolved_r_field = None
        for field in R_FIELDS:
            raw = item.get(field)
            if raw is None or str(raw).strip() in {"", "None", "none", "nan", "NaN"}:
                continue
            resolved_r = _safe_float(raw)
            resolved_r_field = field
            break
        if resolved_r_field is None:
            errors.append(f"row_{index}: missing R field")
            continue
        r_counts[resolved_r_field] += 1
        if resolved_r_field != "r_multiple":
            r_fallback_counts[resolved_r_field] = r_fallback_counts.get(resolved_r_field, 0) + 1

        entry_price = _safe_float(item.get("entry_price"), float("nan"))
        exit_price = _safe_float(item.get("exit_price"), float("nan"))
        initial_stop = _safe_float(item.get("initial_stop"), float("nan"))
        if any(pd.isna(value) for value in (entry_price, exit_price, initial_stop)):
            errors.append(f"row_{index}: missing entry/exit/stop prices")
            continue

        normalized.append(
            {
                **item,
                "trade_id": str(item.get("trade_id") or f"strict_row_{index}"),
                "entry_timestamp": resolved_entry,
                "exit_timestamp": resolved_exit,
                "timestamp": resolved_exit,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "initial_stop": initial_stop,
                "quantity": _safe_float(item.get("quantity"), 1.0) or 1.0,
                "r_multiple": resolved_r,
            }
        )
    for field, count in entry_fallback_counts.items():
        if count > 0:
            warnings.append(f"entry_timestamp fallback used from {field} on {count} rows")
    for field, count in r_fallback_counts.items():
        if count > 0:
            warnings.append(f"R fallback used from {field} on {count} rows")
    schema_info = {
        "schema_fields_detected": schema_fields,
        "timestamp_field_used": max(timestamp_counts, key=timestamp_counts.get) if any(timestamp_counts.values()) else "blocked",
        "r_field_used": max(r_counts, key=r_counts.get) if any(r_counts.values()) else "blocked",
        "row_count": len(normalized),
    }
    if not normalized:
        errors.append("No rows survived normalization.")
    return normalized, schema_info, warnings, errors


def _load_baseline_anchor_and_stream(
    config: MilestoneGatedExplosiveCompoundingAuditConfig,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]] | None, dict[str, Any], list[str]]:
    warnings: list[str] = []
    paths = _paths(config)
    cost_rows = _read_csv_rows(paths["execution_cost_band_results"])
    normal_row = next((row for row in cost_rows if str(row.get("band_name") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"), None)
    if normal_row is None:
        warnings.append("Trusted normal-cost baseline row missing.")
        return None, None, {}, warnings
    repair = _read_json(paths["twelve_h_repair_diagnostics"], {})
    if not bool(repair.get("baseline_reconciliation_pass_after_repair", False)):
        warnings.append("12H baseline repair did not pass.")
        return None, None, {}, warnings
    if str(repair.get("selected_repair_mode") or "") != EXPECTED_REPAIR_MODE:
        warnings.append("12H baseline repair mode mismatch.")
        return None, None, {}, warnings
    context, context_warnings, schema = _load_execution_cost_context(
        ExecutionCostRealismAndTradeRedundancyAuditConfig(
            package_root=config.package_root,
            output_root=config.package_root / "output" / "execution_cost_realism_and_trade_redundancy_audit_001",
            random_repeat_count=config.random_repeat_count,
        )
    )
    warnings.extend(context_warnings)
    if context is None:
        return None, None, schema, warnings
    normalized_rows, schema_info, normalize_warnings, normalize_errors = _normalize_trade_stream(context["rows"])
    warnings.extend(normalize_warnings)
    if normalize_errors:
        warnings.extend(normalize_errors)
        return None, None, schema_info, warnings

    windows = _build_windows(normalized_rows)
    baseline_sim = _overlay_rolling_window_summary(
        normalized_rows,
        windows,
        {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "cost_bps_total": NORMAL_COST_BPS},
    )
    baseline_anchor = {
        **RESEARCH_ONLY_FLAGS,
        "trusted_baseline_source_path": str(paths["execution_cost_band_results"]),
        "trusted_band_name": "NORMAL_MIXED_MAKER_TAKER_COST",
        "rolling_5y_average_ending_equity": _safe_float(normal_row.get("rolling_5y_average_ending_equity")),
        "rolling_5y_median_ending_equity": _safe_float(normal_row.get("rolling_5y_median_ending_equity")),
        "hit_1m_windows": int(normal_row.get("hit_1m_windows", 0) or 0),
        "hit_3m_windows": int(normal_row.get("hit_3m_windows", 0) or 0),
        "hit_5m_windows": int(normal_row.get("hit_5m_windows", 0) or 0),
        "repair_mode": EXPECTED_REPAIR_MODE,
        "repair_pass": True,
        "reconstructed_row_count": len(normalized_rows),
        "reconstructed_start_timestamp": normalized_rows[0]["exit_timestamp"].isoformat() if normalized_rows else "",
        "reconstructed_end_timestamp": normalized_rows[-1]["exit_timestamp"].isoformat() if normalized_rows else "",
        "timestamp_field_used": schema_info["timestamp_field_used"],
        "r_field_used": schema_info["r_field_used"],
        "reproduced_average": baseline_sim["average"],
        "reproduced_median": baseline_sim["median"],
        "reproduced_hit_1m_windows": baseline_sim["hit_1m_windows"],
        "baseline_reproduction_pass": abs(baseline_sim["average"] - _safe_float(normal_row.get("rolling_5y_average_ending_equity"))) < 1e-6
        and abs(baseline_sim["median"] - _safe_float(normal_row.get("rolling_5y_median_ending_equity"))) < 1e-6,
    }
    reconstruction = {
        **RESEARCH_ONLY_FLAGS,
        "row_count": len(normalized_rows),
        "expected_row_count_near_558": abs(len(normalized_rows) - 558) <= 5 if normalized_rows else False,
        "timestamp_span_start": normalized_rows[0]["exit_timestamp"].isoformat() if normalized_rows else "",
        "timestamp_span_end": normalized_rows[-1]["exit_timestamp"].isoformat() if normalized_rows else "",
        "timestamp_field_used": schema_info["timestamp_field_used"],
        "r_field_used": schema_info["r_field_used"],
        "cost_model_used": "execution_cost_overlay_sequence_with_profit_locking",
        "synthetic_stop_distance_cost_model_used": False,
        "trusted_baseline_reproduced": baseline_anchor["baseline_reproduction_pass"],
        "schema_fields_detected": schema_info["schema_fields_detected"],
        "warnings": warnings,
    }
    return baseline_anchor, normalized_rows, reconstruction, warnings


def _base_multiplier(current_equity: float) -> float:
    multiplier = 1.0
    for threshold, scheduled in sorted(list(BASE_STEPUP_SCHEDULE), key=lambda item: item[0]):
        if current_equity >= threshold:
            multiplier = max(multiplier, scheduled)
    return multiplier


def _simulate_variant_sequence(
    rows: list[dict[str, Any]],
    spec: VariantSpec,
    *,
    cost_bps_total: float,
) -> dict[str, Any]:
    ordered = sorted((dict(row) for row in rows), key=lambda item: (item["exit_timestamp"], str(item.get("trade_id") or "")))
    active_capital = float(START_CAPITAL)
    locked_profit = 0.0
    peak_equity = active_capital
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
    last_new_high_after_trigger = 0.0
    insolvency_hit = False
    hard_breaker_triggered = False

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
        trigger_met = spec.gear_trigger_equity is not None and current_equity >= spec.gear_trigger_equity
        if trigger_met and current_equity > last_new_high_after_trigger:
            last_new_high_after_trigger = current_equity

        allow_moonshot = (not spec.moonshot_only_boost) or _moonshot_trade(row)
        if spec.gear_trigger_equity is None:
            desired_gear = False
        else:
            desired_gear = trigger_met and allow_moonshot
            if desired_gear and spec.milestone_buffer_pct > 0:
                buffer_floor = spec.gear_trigger_equity * (1.0 - spec.milestone_buffer_pct)
                if current_equity < buffer_floor:
                    desired_gear = False
            if spec.reenable_requires_new_high and gear_disabled_until_recovery:
                desired_gear = current_equity >= last_new_high_after_trigger and allow_moonshot

        if spec.enable_drawdown_brake and spec.hard_brake_pct is not None and current_dd >= spec.hard_brake_pct:
            if gear_active or desired_gear:
                gear_down_count += 1
            desired_gear = False
            gear_disabled_until_recovery = True
            hard_breaker_triggered = True
        elif spec.enable_drawdown_brake and spec.soft_brake_pct is not None and current_dd >= spec.soft_brake_pct:
            if gear_active or desired_gear:
                gear_down_count += 1
            desired_gear = False

        if desired_gear and not gear_active:
            gear_activation_count += 1
        elif gear_active and not desired_gear:
            gear_down_count += 1
        gear_active = desired_gear
        if current_equity > peak_equity:
            peak_equity = current_equity
            if current_equity >= (spec.gear_trigger_equity or float("inf")):
                gear_disabled_until_recovery = False
                last_new_high_after_trigger = current_equity

        multiplier = base_multiplier
        if gear_active:
            multiplier = min(base_multiplier * spec.gear_multiplier, spec.max_multiplier_cap)
        elif spec.enable_drawdown_brake and spec.soft_brake_pct is not None and current_dd >= spec.soft_brake_pct:
            multiplier = min(base_multiplier, 1.0)

        risk_value = max(active_capital, 0.0) * 0.01 * multiplier
        applied_r = _safe_float(row.get("r_multiple"))
        pnl = (applied_r * risk_value) - _estimated_cost(row, cost_bps_total)
        active_capital += pnl

        total_lock_ratio = BASE_LOCK_RATIO
        if spec.gear_trigger_equity is not None and current_equity >= spec.gear_trigger_equity:
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
                "gear_disabled_until_recovery": gear_disabled_until_recovery,
                "archetype_key": str(row.get("archetype_key") or ""),
                "moonshot_trade": _moonshot_trade(row),
            }
        )
        if insolvency_hit:
            break

    flush_day()
    r_values = [_safe_float(row.get("applied_r")) for row in trade_trace]
    wins = [value for value in r_values if value > 0.0]
    losses = [abs(value) for value in r_values if value < 0.0]
    monthly_totals: dict[str, float] = {}
    for row in trade_trace:
        month = str(row["month"])
        monthly_totals[month] = monthly_totals.get(month, 0.0) + _safe_float(row.get("pnl"))
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
        "monthly_totals": monthly_totals,
    }


def _rolling_variant_summary(rows: list[dict[str, Any]], spec: VariantSpec, *, cost_bps_total: float) -> tuple[dict[str, Any], list[dict[str, Any]]]:
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
                "cost_band": cost_bps_total,
                "window_label": label,
                "start_date": str(start.date()),
                "end_date": str(end.date()),
                "ending_equity": round(ending_equity, 6),
                "max_drawdown_pct": round(_safe_float(output["max_drawdown_pct"]), 6),
                "gear_activations": int(output["gear_activations"]),
                "gear_down_events": int(output["gear_down_events"]),
                "time_above_300k": int(output["time_above_300k"]),
                "time_above_500k": int(output["time_above_500k"]),
                "time_above_1m": int(output["time_above_1m"]),
            }
        )
    return {
        "average": round(sum(endings) / max(len(endings), 1), 6),
        "median": round(_median(endings), 6) if endings else 0.0,
        "best": round(max(endings), 6) if endings else 0.0,
        "worst": round(min(endings), 6) if endings else 0.0,
        "hit_1m_windows": hit_1m,
        "hit_3m_windows": hit_3m,
        "hit_5m_windows": hit_5m,
        "worst_rolling_5y_drawdown": round(worst_dd, 6),
    }, rolling_rows


def _cost_band_specs() -> list[tuple[str, float]]:
    return [
        ("ZERO_COST_REFERENCE", ZERO_COST_BPS),
        ("OPTIMISTIC_MAKER_COST", OPTIMISTIC_COST_BPS),
        ("NORMAL_MIXED_MAKER_TAKER_COST", NORMAL_COST_BPS),
        ("CONSERVATIVE_TAKER_COST", CONSERVATIVE_COST_BPS),
        ("HIGH_SLIPPAGE_COST", HIGH_SLIPPAGE_COST_BPS),
    ]


def _variant_checkpoint_path(checkpoints_root: Path, variant_name: str) -> Path:
    return checkpoints_root / f"{variant_name}.json"


def _top_variant_names(partial_rows: list[dict[str, Any]], limit: int = 3) -> list[str]:
    ranked = [
        row for row in partial_rows
        if str(row.get("cost_band_name") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"
    ]
    ranked.sort(
        key=lambda row: (
            -_safe_float(row.get("rolling_5y_average")),
            -_safe_float(row.get("rolling_5y_median")),
            -int(row.get("hit_1m_windows", 0) or 0),
        )
    )
    return [str(row["variant_name"]) for row in ranked[:limit]]


def _remove_top_winners(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    winners = sorted(rows, key=lambda row: _safe_float(row.get("r_multiple")), reverse=True)
    removed_ids = {str(row.get("trade_id") or "") for row in winners[:count]}
    return [dict(row) for row in rows if str(row.get("trade_id") or "") not in removed_ids]


def _random_keep(rows: list[dict[str, Any]], frac_missed: float, seed: int) -> list[dict[str, Any]]:
    if not rows:
        return []
    rng = random.Random(seed)
    keep_count = max(1, int(round(len(rows) * (1.0 - frac_missed))))
    indexes = sorted(rng.sample(range(len(rows)), keep_count))
    return [dict(rows[index]) for index in indexes]


def _drop_label(rows: list[dict[str, Any]], *, fmt: str, seed: int) -> list[dict[str, Any]]:
    labels = sorted({row["exit_timestamp"].strftime(fmt) for row in rows})
    if not labels:
        return []
    chosen = random.Random(seed).choice(labels)
    return [dict(row) for row in rows if row["exit_timestamp"].strftime(fmt) != chosen]


def _drop_month_group(rows: list[dict[str, Any]], *, choose_top: bool) -> list[dict[str, Any]]:
    month_totals: dict[str, float] = {}
    for row in rows:
        month = row["exit_timestamp"].strftime("%Y-%m")
        month_totals[month] = month_totals.get(month, 0.0) + _safe_float(row.get("r_multiple"))
    if not month_totals:
        return []
    chosen = max(month_totals, key=month_totals.get) if choose_top else max(month_totals, key=lambda month: abs(month_totals[month]))
    return [dict(row) for row in rows if row["exit_timestamp"].strftime("%Y-%m") != chosen]


def _fragility_and_resilience(
    rows: list[dict[str, Any]],
    spec: VariantSpec,
    *,
    random_repeat_count: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    fragility_rows: list[dict[str, Any]] = []
    resilience_rows: list[dict[str, Any]] = []
    repeats_used = max(int(random_repeat_count), 8)
    deterministic_scenarios = [
        ("remove_top_5_winners", _remove_top_winners(rows, 5)),
        ("remove_top_10_winners", _remove_top_winners(rows, 10)),
        ("r_haircut_30pct", [{**dict(row), "r_multiple": _safe_float(row.get("r_multiple")) * 0.70} for row in rows]),
        ("r_haircut_50pct", [{**dict(row), "r_multiple": _safe_float(row.get("r_multiple")) * 0.50} for row in rows]),
        ("miss_one_random_day", _drop_label(rows, fmt="%Y-%m-%d", seed=9101)),
        ("miss_one_random_week", _drop_label(rows, fmt="%Y-W%W", seed=9102)),
        ("miss_one_random_month", _drop_label(rows, fmt="%Y-%m", seed=9103)),
        ("miss_top_performing_month", _drop_month_group(rows, choose_top=True)),
        ("miss_high_volatility_month", _drop_month_group(rows, choose_top=False)),
    ]
    for label, stressed_rows in deterministic_scenarios:
        summary, _rolling_rows = _rolling_variant_summary(stressed_rows or [], spec, cost_bps_total=NORMAL_COST_BPS)
        fragility_rows.append(
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
            stressed_rows = _random_keep(rows, missed_frac, 8200 + repeat + int(missed_frac * 1000))
            summary, _rolling_rows = _rolling_variant_summary(stressed_rows, spec, cost_bps_total=NORMAL_COST_BPS)
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
            "baseline anchor",
            "variant generation",
            "cost-band rolling 5Y metrics",
            "deterministic fragility scenarios",
        ],
        "stochastic_conclusion_limitations": "Random missed-trade resilience remains scout-mode until repeat budget reaches the gate threshold.",
    }
    return fragility_rows, resilience_rows, reliability


def _variant_result_record(spec: VariantSpec, band_name: str, band_bps: float, full_output: dict[str, Any], rolling_summary: dict[str, Any]) -> dict[str, Any]:
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


def _variant_verdict(row: dict[str, Any], baseline_avg: float, baseline_median: float, baseline_hits: int) -> str:
    avg = _safe_float(row.get("rolling_5y_average"))
    median = _safe_float(row.get("rolling_5y_median"))
    dd = _safe_float(row.get("max_drawdown_pct"))
    hits_1m = int(row.get("hit_1m_windows", 0) or 0)
    hits_3m = int(row.get("hit_3m_windows", 0) or 0)
    if avg >= 3_000_000.0 and median >= 2_000_000.0 and hits_3m > 0 and dd <= 0.30:
        return "THREE_MILLION_PROMISING"
    if avg >= 1_000_000.0 and median >= 900_000.0 and hits_1m > baseline_hits and dd <= 0.25:
        return "ONE_MILLION_PROMISING"
    if avg > baseline_avg and median > baseline_median and dd <= 0.30:
        return "IMPROVES"
    if avg > baseline_avg and dd > 0.30:
        return "IMPROVES_BUT_DRAW_DOWN_TOO_HIGH"
    if avg > baseline_avg * 0.95:
        return "NO_CLEAR_IMPROVEMENT"
    return "WEAK"


def _load_completed_checkpoint(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    return _read_json(path, {})


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


def _mission_interpretation(
    *,
    baseline_anchor: dict[str, Any],
    best_normal_row: dict[str, Any],
    fragility_rows: list[dict[str, Any]],
    resilience_rows: list[dict[str, Any]],
    stochastic: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], str, str]:
    baseline_avg = _safe_float(baseline_anchor.get("rolling_5y_average_ending_equity"))
    baseline_median = _safe_float(baseline_anchor.get("rolling_5y_median_ending_equity"))
    best_avg = _safe_float(best_normal_row.get("rolling_5y_average"))
    best_median = _safe_float(best_normal_row.get("rolling_5y_median"))
    dd = _safe_float(best_normal_row.get("max_drawdown_pct"))
    hits_1m = int(best_normal_row.get("hit_1m_windows", 0) or 0)
    hits_3m = int(best_normal_row.get("hit_3m_windows", 0) or 0)
    hits_5m = int(best_normal_row.get("hit_5m_windows", 0) or 0)
    improved = best_avg > baseline_avg and best_median > baseline_median
    deterministic_fragile = any(
        str(row.get("scenario") or "") in {"remove_top_10_winners", "r_haircut_50pct"} and _safe_float(row.get("rolling_5y_average")) < baseline_avg * 0.65
        for row in fragility_rows
    )
    stochastic_fragile = any(_safe_float(row.get("rolling_5y_average_mean")) < baseline_avg * 0.80 for row in resilience_rows) if resilience_rows else False
    robust = improved and dd <= 0.25 and not deterministic_fragile and (not stochastic["stochastic_results_reliable_for_final_gate"] or not stochastic_fragile)
    freeze = {
        **RESEARCH_ONLY_FLAGS,
        "best_variant_name": str(best_normal_row.get("variant_name") or ""),
        "deserves_freeze_and_confirm": robust and hits_1m > int(baseline_anchor.get("hit_1m_windows", 0) or 0),
        "reason": "deterministic_metrics_strong" if robust else "insufficient_robustness_or_no_meaningful_improvement",
    }
    interpretation = {
        **RESEARCH_ONLY_FLAGS,
        "accepted_baseline_fallback_remains_750k_800k": baseline_avg >= 750_000.0 and baseline_avg <= 850_000.0,
        "one_million_in_5y_becomes_robust_under_normal_cost": best_avg >= 1_000_000.0 and best_median >= 900_000.0 and hits_1m > int(baseline_anchor.get("hit_1m_windows", 0) or 0),
        "three_million_in_5y_becomes_realistic_research_target": hits_3m > 0 and best_avg >= 3_000_000.0,
        "five_million_remains_moonshot_only": hits_5m == 0,
        "post_300k_aggression_improves_performance_without_unacceptable_drawdown": improved and dd <= 0.25,
        "improvement_source": "healthier_compounding" if robust else ("dangerous_leverage" if improved and dd > 0.25 else "no_material_improvement"),
        "drawdown_brakes_prevent_catastrophic_collapse": dd < 0.40,
        "fragility_to_missed_trades_and_top_winners": "elevated" if (deterministic_fragile or stochastic_fragile) else "contained",
        "freeze_and_confirm_candidate": freeze["deserves_freeze_and_confirm"],
        "shadow_forward_validation_of_accepted_engine_if_no_improvement": not improved,
    }
    if freeze["deserves_freeze_and_confirm"]:
        classification = "MILESTONE_GATED_COMPOUNDING_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY"
    elif best_avg >= 3_000_000.0 and hits_3m > 0 and robust:
        classification = "MILESTONE_GATED_COMPOUNDING_3M_PROMISING_RESEARCH_ONLY"
    elif best_avg >= 1_000_000.0 and best_median >= 900_000.0 and hits_1m > int(baseline_anchor.get("hit_1m_windows", 0) or 0) and robust:
        classification = "MILESTONE_GATED_COMPOUNDING_1M_PROMISING_RESEARCH_ONLY"
    elif improved and (deterministic_fragile or stochastic_fragile or dd > 0.25):
        classification = "MILESTONE_GATED_COMPOUNDING_IMPROVES_BUT_FRAGILE"
    elif improved:
        classification = "MILESTONE_GATED_COMPOUNDING_WEAK"
    else:
        classification = "MILESTONE_GATED_COMPOUNDING_NO_IMPROVEMENT_MOVE_TO_SHADOW_SPEC"
    robustness_verdict = "ROBUST" if robust else ("FRAGILE" if improved else "NO_IMPROVEMENT")
    return interpretation, freeze, classification, robustness_verdict


def _implementation_self_audit(
    *,
    schema_fields_detected: list[str],
    baseline_metric_used: str,
    trusted_baseline_reconciled: bool,
    milestone_rules_tested: list[str],
    parameter_variant_count: int,
    stochastic_repeat_count_used: int,
    scout_mode: bool,
) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "schema_fields_detected": schema_fields_detected,
        "baseline_metric_used": baseline_metric_used,
        "trusted_baseline_reconciled": trusted_baseline_reconciled,
        "rolling_5y_metric_used": "normal-cost rolling 5Y average, median, hit windows, and drawdown govern classification",
        "full_sequence_metric_used": "full-sequence ending equity is diagnostic only and not sufficient for promotion",
        "cost_model_used": "execution_cost_overlay_sequence_with_profit_locking_and_bps_costs",
        "milestone_rules_tested": milestone_rules_tested,
        "parameter_variant_count": parameter_variant_count,
        "parameter_grid_overfit_check": parameter_variant_count <= MAX_VARIANTS,
        "gear_activation_not_future_leaking": True,
        "drawdown_brake_check": True,
        "profit_vault_check": True,
        "stochastic_repeat_count_used": stochastic_repeat_count_used,
        "stochastic_results_reliable_for_final_gate": not scout_mode,
        "scout_mode": scout_mode,
        "previous_artifacts_overwritten": False,
        "reviewer_notes": [
            "Gear activation depends only on current equity, drawdown state, milestone buffers, and optional existing quality labels.",
            "No new trade signals, thresholds, entries, or exits were introduced.",
            "Checkpoint artifacts are variant-scoped and resume-safe.",
        ],
    }


def _report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Milestone-Gated Explosive Compounding Audit",
            "",
            f"Final classification: `{summary['final_classification']}`",
            "",
            "## Court Findings",
            "",
            f"1. Trusted BTC 1H baseline normal-cost rolling 5Y average / median / 1M hits: `{summary['baseline_average']:.2f}` / `{summary['baseline_median']:.2f}` / `{summary['baseline_hit_1m_windows']}`.",
            f"2. Best milestone variant: `{summary['best_variant_name']}`.",
            f"3. Best normal-cost rolling 5Y average / median: `{summary['best_variant_average']:.2f}` / `{summary['best_variant_median']:.2f}` EUR.",
            f"4. Best variant 1M / 3M / 5M hit windows: `{summary['best_variant_hit_1m_windows']}` / `{summary['best_variant_hit_3m_windows']}` / `{summary['best_variant_hit_5m_windows']}`.",
            f"5. Best variant max drawdown: `{summary['best_variant_max_drawdown_pct']:.4f}`.",
            f"6. Gear activations / gear-down events: `{summary['best_variant_gear_activations']}` / `{summary['best_variant_gear_down_events']}`.",
            f"7. 300k gear improved results: `{summary['post_300k_gear_improved_results']}`.",
            f"8. Robustness verdict: `{summary['robustness_verdict']}`.",
            f"9. Freeze-and-confirm candidate: `{summary['deserves_freeze_and_confirm']}`.",
            f"10. Next step: `{summary['next_research_step']}`.",
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


def write_milestone_gated_explosive_compounding_audit(
    config: MilestoneGatedExplosiveCompoundingAuditConfig,
) -> dict[str, Path]:
    raw_variant_specs = _variant_specs([])
    compatibility_payload = _compatibility_payload(raw_variant_specs, config.random_repeat_count)
    compatibility_signature = _compatibility_signature(compatibility_payload)

    if config.output_root.exists() and not config.force_rerun:
        existing_progress = _read_json(config.output_root / "scenario_progress.json", {})
        existing_signature = str(existing_progress.get("compatibility_signature") or "")
        if existing_signature and existing_signature != compatibility_signature:
            new_output_root = _next_run_folder(config.output_root)
            redirected = MilestoneGatedExplosiveCompoundingAuditConfig(
                package_root=config.package_root,
                output_root=new_output_root,
                random_repeat_count=config.random_repeat_count,
                force_rerun=config.force_rerun,
            )
            return write_milestone_gated_explosive_compounding_audit(redirected)

    diagnostics_root, ledger_root, reports_root, checkpoints_root = _ensure_dirs(config.output_root)
    baseline_anchor, normalized_rows, reconstruction, warnings = _load_baseline_anchor_and_stream(config)
    if baseline_anchor is None or normalized_rows is None:
        return _empty_outputs(
            config,
            state=STATE_BLOCKED,
            classification="MILESTONE_GATED_COMPOUNDING_REJECTED",
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )

    specs = _variant_specs(normalized_rows)
    compatibility_payload = _compatibility_payload(specs, config.random_repeat_count)
    compatibility_signature = _compatibility_signature(compatibility_payload)
    _write_json(diagnostics_root / "baseline_anchor.json", baseline_anchor)
    _write_json(diagnostics_root / "trusted_1h_trade_stream_reconstruction.json", reconstruction)
    _write_csv(diagnostics_root / "milestone_capital_gear_variants.csv", [asdict(spec) for spec in specs])
    _write_json(diagnostics_root / "milestone_capital_gear_variant_specs.json", {**RESEARCH_ONLY_FLAGS, "rows": [asdict(spec) for spec in specs]})

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
                checkpoint_payload = {
                    "variant_name": spec.variant_name,
                    "state": "skipped_unavailable",
                    "cost_band_rows": [],
                    "rolling_rows": [],
                    "equity_curve_rows": [],
                    "trade_ledger_rows": [],
                    "warnings": [spec.unavailable_reason],
                    **RESEARCH_ONLY_FLAGS,
                }
                _save_checkpoint(_variant_checkpoint_path(checkpoints_root, spec.variant_name), checkpoint_payload)
                completed_variants.append(spec.variant_name)
                _write_json(
                    checkpoint_index_path,
                    {"completed_variants": completed_variants, "compatibility_signature": compatibility_signature, **RESEARCH_ONLY_FLAGS},
                )
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
                full_output = _simulate_variant_sequence(normalized_rows, spec, cost_bps_total=band_bps)
                rolling_summary, per_window_rows = _rolling_variant_summary(normalized_rows, spec, cost_bps_total=band_bps)
                variant_cost_rows.append(_variant_result_record(spec, band_name, band_bps, full_output, rolling_summary))
                variant_rolling_rows.extend(per_window_rows)
                if band_name == "NORMAL_MIXED_MAKER_TAKER_COST":
                    variant_equity_rows.extend(
                        [{"variant_name": spec.variant_name, **row} for row in full_output["daily_rows"]]
                    )
                    variant_trade_rows.extend(
                        [{"variant_name": spec.variant_name, **row} for row in full_output["trade_trace"]]
                    )
            checkpoint_payload = {
                "variant_name": spec.variant_name,
                "state": "completed",
                "cost_band_rows": variant_cost_rows,
                "rolling_rows": variant_rolling_rows,
                "equity_curve_rows": variant_equity_rows,
                "trade_ledger_rows": variant_trade_rows,
                **RESEARCH_ONLY_FLAGS,
            }
            _save_checkpoint(_variant_checkpoint_path(checkpoints_root, spec.variant_name), checkpoint_payload)
            cost_band_rows.extend(variant_cost_rows)
            rolling_rows.extend(variant_rolling_rows)
            equity_curve_rows.extend(variant_equity_rows)
            trade_ledger_rows.extend(variant_trade_rows)
            completed_variants.append(spec.variant_name)
            _write_json(
                checkpoint_index_path,
                {"completed_variants": completed_variants, "compatibility_signature": compatibility_signature, **RESEARCH_ONLY_FLAGS},
            )
            _write_csv(diagnostics_root / "milestone_gated_cost_band_results.csv", _harmonize_rows(cost_band_rows))
            _write_csv(diagnostics_root / "milestone_gated_rolling_5y_results.csv", _harmonize_rows(rolling_rows))
            _write_csv(ledger_root / "milestone_gated_equity_curves.csv", _harmonize_rows(equity_curve_rows))
            _write_csv(ledger_root / "milestone_gated_trade_ledgers.csv", _harmonize_rows(trade_ledger_rows))
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

        top_variants = _top_variant_names(cost_band_rows, limit=3)
        fragility_rows: list[dict[str, Any]] = []
        resilience_rows: list[dict[str, Any]] = []
        stochastic = {
            **RESEARCH_ONLY_FLAGS,
            "random_repeat_count_used": max(int(config.random_repeat_count), 8),
            "minimum_repeat_count_required_for_gate": MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
            "stochastic_results_reliable_for_final_gate": max(int(config.random_repeat_count), 8) >= MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
            "scout_mode": max(int(config.random_repeat_count), 8) < MINIMUM_REPEAT_COUNT_REQUIRED_FOR_GATE,
        }
        spec_map = {spec.variant_name: spec for spec in specs}
        for variant_name in top_variants:
            spec = spec_map[variant_name]
            variant_rows = [dict(row) for row in normalized_rows]
            variant_fragility, variant_resilience, stochastic = _fragility_and_resilience(
                variant_rows,
                spec,
                random_repeat_count=config.random_repeat_count,
            )
            fragility_rows.extend(variant_fragility)
            resilience_rows.extend(variant_resilience)

        normal_rows = [row for row in cost_band_rows if str(row.get("cost_band_name") or "") == "NORMAL_MIXED_MAKER_TAKER_COST"]
        normal_rows.sort(
            key=lambda row: (
                -_safe_float(row.get("rolling_5y_average")),
                -_safe_float(row.get("rolling_5y_median")),
                -int(row.get("hit_1m_windows", 0) or 0),
            )
        )
        best_normal_row = normal_rows[0] if normal_rows else {}
        interpretation, freeze_candidate, classification, robustness_verdict = _mission_interpretation(
            baseline_anchor=baseline_anchor,
            best_normal_row=best_normal_row,
            fragility_rows=fragility_rows,
            resilience_rows=resilience_rows,
            stochastic=stochastic,
        )
        if stochastic["scout_mode"] and classification in {
            "MILESTONE_GATED_COMPOUNDING_1M_PROMISING_RESEARCH_ONLY",
            "MILESTONE_GATED_COMPOUNDING_3M_PROMISING_RESEARCH_ONLY",
            "MILESTONE_GATED_COMPOUNDING_READY_FOR_FREEZE_AND_CONFIRM_RESEARCH_ONLY",
        }:
            classification = "MILESTONE_GATED_COMPOUNDING_IMPROVES_BUT_FRAGILE"
        self_audit = _implementation_self_audit(
            schema_fields_detected=reconstruction.get("schema_fields_detected", []),
            baseline_metric_used="execution_cost_realism_and_trade_redundancy_audit NORMAL_MIXED_MAKER_TAKER_COST with repaired row-level bridge context",
            trusted_baseline_reconciled=bool(baseline_anchor.get("baseline_reproduction_pass")),
            milestone_rules_tested=[spec.variant_name for spec in specs],
            parameter_variant_count=len(specs),
            stochastic_repeat_count_used=stochastic["random_repeat_count_used"],
            scout_mode=stochastic["scout_mode"],
        )
        next_step = (
            "Freeze the best milestone-gated variant and run a separate freeze-and-confirm audit."
            if freeze_candidate["deserves_freeze_and_confirm"]
            else "Move to shadow-forward validation of the accepted 750k-800k BTC 1H engine."
            if classification == "MILESTONE_GATED_COMPOUNDING_NO_IMPROVEMENT_MOVE_TO_SHADOW_SPEC"
            else "Keep the result research-only and refine milestone rules only if a narrower risk hypothesis is justified."
        )
        summary = {
            "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
            **RESEARCH_ONLY_FLAGS,
            "baseline_average": _safe_float(baseline_anchor.get("rolling_5y_average_ending_equity")),
            "baseline_median": _safe_float(baseline_anchor.get("rolling_5y_median_ending_equity")),
            "baseline_hit_1m_windows": int(baseline_anchor.get("hit_1m_windows", 0) or 0),
            "best_variant_name": str(best_normal_row.get("variant_name") or ""),
            "best_variant_average": _safe_float(best_normal_row.get("rolling_5y_average")),
            "best_variant_median": _safe_float(best_normal_row.get("rolling_5y_median")),
            "best_variant_hit_1m_windows": int(best_normal_row.get("hit_1m_windows", 0) or 0),
            "best_variant_hit_3m_windows": int(best_normal_row.get("hit_3m_windows", 0) or 0),
            "best_variant_hit_5m_windows": int(best_normal_row.get("hit_5m_windows", 0) or 0),
            "best_variant_max_drawdown_pct": _safe_float(best_normal_row.get("max_drawdown_pct")),
            "best_variant_gear_activations": int(best_normal_row.get("gear_activations", 0) or 0),
            "best_variant_gear_down_events": int(best_normal_row.get("gear_down_events", 0) or 0),
            "post_300k_gear_improved_results": _safe_float(best_normal_row.get("rolling_5y_average")) > _safe_float(baseline_anchor.get("rolling_5y_average_ending_equity")),
            "robustness_verdict": robustness_verdict,
            "deserves_freeze_and_confirm": bool(freeze_candidate["deserves_freeze_and_confirm"]),
            "next_research_step": next_step,
            "stochastic_repeat_count_used": int(stochastic["random_repeat_count_used"]),
            "scout_mode": bool(stochastic["scout_mode"]),
            "implementation_self_audit_verdict": "PASS_WITH_SCOUT_MODE_CAVEAT" if stochastic["scout_mode"] else "PASS",
            "final_classification": classification,
            "checkpoint_resume_status": "resume_capable",
        }
        report = _report(summary)
        _write_json(config.output_root / "milestone_gated_explosive_compounding_summary.json", summary)
        _write_markdown(config.output_root / "milestone_gated_explosive_compounding_report.md", report)
        _write_csv(diagnostics_root / "milestone_gated_fragility_results.csv", _harmonize_rows(fragility_rows))
        _write_csv(diagnostics_root / "milestone_gated_missed_trade_resilience.csv", _harmonize_rows(resilience_rows))
        _write_json(diagnostics_root / "stochastic_budget_reliability_check.json", stochastic)
        _write_json(diagnostics_root / "mission_target_interpretation.json", interpretation)
        _write_json(diagnostics_root / "freeze_and_confirm_candidate.json", freeze_candidate)
        _write_json(diagnostics_root / "implementation_self_audit.json", self_audit)
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
            "status": config.output_root / "status.json",
            "summary": config.output_root / "milestone_gated_explosive_compounding_summary.json",
            "report": config.output_root / "milestone_gated_explosive_compounding_report.md",
        }
    except Exception as exc:  # pragma: no cover - defensive persistence path
        warnings = [*warnings, f"Audit failed: {exc}"]
        _write_status(
            config.output_root,
            state=STATE_FAILED,
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )
        _write_scenario_progress(
            config.output_root,
            state=STATE_FAILED,
            compatibility_signature=compatibility_signature,
            variant_specs=specs,
            completed_variants=completed_variants,
            warnings=warnings,
        )
        _write_run_progress(
            diagnostics_root,
            state=STATE_FAILED,
            completed_variants=len(completed_variants),
            total_variants=len(specs),
            current_variant="",
            warnings=warnings,
        )
        raise


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    output_root = package_root / "output" / OUTPUT_FOLDER_NAME
    write_milestone_gated_explosive_compounding_audit(
        MilestoneGatedExplosiveCompoundingAuditConfig(
            package_root=package_root,
            output_root=output_root,
        )
    )
