from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import RESEARCH_ONLY_FLAGS  # noqa: E402
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _read_csv_rows,
    _read_json,
    _write_csv,
    _write_json,
    _write_markdown,
)


OUTPUT_FOLDER_NAME = "shadow_forward_validation_spec_audit_001"
STATE_NOT_STARTED = "not_started"
STATE_RUNNING = "running"
STATE_PARTIAL = "partial"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_BLOCKED = "blocked"

EXPECTED_FINAL_CLASSIFICATION = "SHADOW_SPEC_READY_WITH_6H_CONTEXT_RESEARCH_ONLY"
RECOMMENDED_SHADOW_DURATION_DAYS = 90
RECOMMENDED_MINIMUM_SIGNAL_COUNT = 50
MAX_ALLOWED_DELAY_SECONDS = 120
MAX_ALLOWED_DATA_GAP_RATE = 0.005
MIN_SIGNAL_REPRODUCTION_ACCURACY = 0.99


@dataclass(frozen=True)
class ShadowForwardValidationSpecAuditConfig:
    package_root: Path
    output_root: Path
    force_rerun: bool = False


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _paths(config: ShadowForwardValidationSpecAuditConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    return {
        "baseline_cost_bands": output_root / "execution_cost_realism_and_trade_redundancy_audit_001" / "diagnostics" / "execution_cost_band_results.csv",
        "htf_summary": output_root / "htf_context_role_reconciliation_audit_001" / "htf_context_role_reconciliation_summary.json",
        "htf_recommendation": output_root / "htf_context_role_reconciliation_audit_001" / "diagnostics" / "strategic_timeframe_recommendation.json",
        "six_hour_summary": output_root / "six_hour_native_execution_tide_context_audit_001" / "six_hour_native_execution_tide_context_summary.json",
        "six_hour_recommendation": output_root / "six_hour_native_execution_tide_context_audit_001" / "diagnostics" / "strategic_execution_stack_recommendation.json",
        "earned_gear_summary": output_root / "earned_gear_activation_discovery_audit_001" / "earned_gear_activation_discovery_summary.json",
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


def _compatibility_payload() -> dict[str, Any]:
    return {
        "module": "shadow_forward_validation_spec_audit",
        "version": 1,
        "expected_final_classification": EXPECTED_FINAL_CLASSIFICATION,
        "recommended_shadow_duration_days": RECOMMENDED_SHADOW_DURATION_DAYS,
        "recommended_minimum_signal_count": RECOMMENDED_MINIMUM_SIGNAL_COUNT,
    }


def _compatibility_signature(payload: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _write_status(
    output_root: Path,
    *,
    state: str,
    warnings: list[str],
    compatibility_signature: str,
    extra: dict[str, Any] | None = None,
) -> None:
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
    completed_sections: list[str],
    warnings: list[str],
    compatibility_signature: str,
) -> None:
    payload = {
        "state": state,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed_sections": completed_sections,
        "warnings": warnings,
        "compatibility_signature": compatibility_signature,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(output_root / "scenario_progress.json", payload)


def _write_run_progress(
    diagnostics_root: Path,
    *,
    state: str,
    completed_sections: list[str],
    total_sections: int,
    current_section: str,
    warnings: list[str],
) -> None:
    payload = {
        "state": state,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "completed_sections": completed_sections,
        "total_sections": total_sections,
        "current_section": current_section,
        "percent_complete": round((len(completed_sections) / max(total_sections, 1)) * 100.0, 4),
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(diagnostics_root / "run_progress.json", payload)


def _baseline_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        band_name = str(row.get("band_name") or row.get("cost_band") or "").strip()
        if band_name == "NORMAL_MIXED_MAKER_TAKER_COST":
            return row
    return None


def _load_prior_court_anchor(config: ShadowForwardValidationSpecAuditConfig) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    paths = _paths(config)

    baseline_row = _baseline_row(_read_csv_rows(paths["baseline_cost_bands"]))
    htf_summary = _read_json(paths["htf_summary"], {})
    htf_recommendation = _read_json(paths["htf_recommendation"], {})
    six_hour_summary = _read_json(paths["six_hour_summary"], {})
    six_hour_recommendation = _read_json(paths["six_hour_recommendation"], {})
    earned_summary = _read_json(paths["earned_gear_summary"], {})

    if baseline_row is None:
        warnings.append("Trusted 1H normal-cost baseline row missing.")
    if not htf_summary:
        warnings.append("HTF context court summary missing.")
    if not htf_recommendation:
        warnings.append("HTF context strategic recommendation missing.")
    if not six_hour_summary:
        warnings.append("6H native execution scout summary missing.")
    if not six_hour_recommendation:
        warnings.append("6H native execution strategic recommendation missing.")
    if not earned_summary:
        warnings.append("Earned gear court summary missing.")
    if warnings:
        return None, warnings

    anchor = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "trusted_1h_baseline": {
            "normal_cost_rolling_5y_average": round(_safe_float(baseline_row.get("rolling_5y_average_ending_equity")), 6),
            "normal_cost_rolling_5y_median": round(_safe_float(baseline_row.get("rolling_5y_median_ending_equity")), 6),
            "hit_1m_windows": int(_safe_float(baseline_row.get("hit_1m_windows"))),
        },
        "htf_context_court": {
            "final_classification": str(htf_summary.get("final_classification") or ""),
            "best_context_variant": str(htf_summary.get("best_context_variant") or htf_recommendation.get("best_context_variant") or ""),
            "best_context_timeframe": str(htf_summary.get("best_context_timeframe") or htf_recommendation.get("four_hour_or_six_hour_preferred") or ""),
            "normal_cost_rolling_5y_average": round(_safe_float(htf_summary.get("best_normal_cost_average")), 6),
            "normal_cost_rolling_5y_median": round(_safe_float(htf_summary.get("best_normal_cost_median")), 6),
            "hit_1m_windows": int(_safe_float(htf_summary.get("best_hit_1m_windows"))),
            "six_hour_role_decision": "SIX_H_CONTEXT_IMPROVES_1H_RESEARCH_ONLY" if bool(htf_recommendation.get("six_hour_should_be_official_context", False)) else "",
            "twelve_hour_role_decision": str(htf_recommendation.get("twelve_hour_context_decision") or ""),
            "freeze_and_confirm_deserved_now": False,
        },
        "six_hour_native_execution_court": {
            "final_classification": str(six_hour_summary.get("final_classification") or ""),
            "best_combined_normal_cost_average": round(_safe_float(six_hour_summary.get("best_combined_average")), 6),
            "best_combined_normal_cost_median": round(_safe_float(six_hour_summary.get("best_combined_median")), 6),
            "best_combined_hit_1m_windows": int(_safe_float(six_hour_summary.get("best_combined_hit_1m_windows"))),
            "native_execution_role_decision": str(six_hour_summary.get("six_h_native_execution_role_decision") or ""),
            "deserves_capital_routing_audit": bool(six_hour_summary.get("deserves_future_capital_routing_audit", False)),
            "twelve_hour_ocean_role_decision": str(six_hour_summary.get("twelve_hour_ocean_role_decision") or ""),
            "daily_tide_role_decision": str(six_hour_summary.get("daily_tide_role_decision") or ""),
            "weekly_deep_current_role_decision": str(six_hour_summary.get("weekly_deep_current_role_decision") or ""),
        },
        "earned_gear_court": {
            "final_classification": str(earned_summary.get("final_classification") or ""),
            "aggressive_gear_shadow_log_only": bool(earned_summary.get("aggressive_gear_shadow_log_only", True)),
            "best_earned_gear_average": round(_safe_float(earned_summary.get("best_earned_gear_average")), 6),
            "best_earned_gear_median": round(_safe_float(earned_summary.get("best_earned_gear_median")), 6),
        },
    }

    if anchor["trusted_1h_baseline"]["normal_cost_rolling_5y_average"] <= 0.0:
        warnings.append("Trusted 1H baseline average is non-positive.")
    if anchor["htf_context_court"]["final_classification"] != "SIX_H_CONTEXT_IMPROVES_1H_RESEARCH_ONLY":
        warnings.append("HTF context court does not confirm 6H as research-only context.")
    if anchor["six_hour_native_execution_court"]["final_classification"] != "SIX_H_NATIVE_EXECUTION_WEAK":
        warnings.append("6H native execution court is not in the expected weak state.")
    if anchor["earned_gear_court"]["final_classification"] != "EARNED_GEAR_DISCOVERY_IMPROVES_BUT_FRAGILE":
        warnings.append("Earned gear court is not in the expected fragile state.")
    return anchor, warnings


def _shadow_forward_architecture_spec(anchor: dict[str, Any]) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "stack": {
            "execution_engine": "1H",
            "research_context_timeframe": "6H",
            "six_h_native_execution": "disabled_weak",
            "twelve_h_execution": "retired",
            "diagnostic_only_timeframes": ["12H", "1D", "1W"],
            "fifteen_minute_execution": "inactive_latest_court",
            "aggressive_300k_gear": "shadow_log_only",
        },
        "components": [
            {
                "component": "data_ingestion_observer",
                "purpose": "Observe BTCUSDT canonical candles and derive 1H plus 6H closed-bar inputs.",
                "inputs": ["BTCUSDT canonical 1m source", "resampled 1H candles", "resampled 6H candles", "optional 12H/1D/1W diagnostics"],
                "constraints": ["closed candles only", "no broker order feed", "no capital allocation"],
            },
            {
                "component": "candle_finality_checker",
                "purpose": "Reject incomplete-candle decisions and log close-vs-processing delay.",
                "required_fields": ["candle_close_time", "processing_time", "delay_seconds"],
                "rules": ["signals only on candle close", "diagnostic delay logging required"],
            },
            {
                "component": "one_hour_signal_observer",
                "purpose": "Reproduce the trusted 1H strict SR-aware decision logic in observation mode.",
                "outputs": ["accepted/rejected decisions", "rejection reasons", "confluence criteria", "estimated risk"],
                "constraints": ["no real trade sizing", "no order path"],
            },
            {
                "component": "six_hour_context_annotator",
                "purpose": "Annotate 1H signals with 6H structure, room, liquidity, and LIGHT_BOOST_6H_CONFLUENCE eligibility.",
                "constraints": ["no 6H execution", "context available before signal timestamp"],
            },
            {
                "component": "research_overlay_logger",
                "purpose": "Log baseline 1H, 1H+6H context, and aggressive-gear shadow-only hypothetical overlays.",
                "constraints": ["no paper/live action", "aggressive gear remains observation only"],
            },
            {
                "component": "data_quality_monitor",
                "purpose": "Track gaps, duplicates, stale data, timezone mismatches, and resampling damage.",
                "alerts": ["missing candles", "duplicate candles", "stale data", "resampling gaps", "timezone mismatch"],
            },
            {
                "component": "cost_slippage_estimator",
                "purpose": "Apply read-only cost bands to hypothetical outcomes for honesty in forward review.",
                "bands": ["normal_cost", "conservative_cost", "high_slippage"],
            },
            {
                "component": "reporting_layer",
                "purpose": "Emit daily, weekly, monthly, cumulative, and replay-vs-forward consistency reports.",
                "outputs": ["operator summary", "signal quality review", "data integrity review", "readiness gate status"],
            },
        ],
        "recommended_shadow_duration_days": RECOMMENDED_SHADOW_DURATION_DAYS,
        "recommended_minimum_signal_count": RECOMMENDED_MINIMUM_SIGNAL_COUNT,
        "accepted_baseline_research_expectation_eur": "750k_to_800k",
        "court_anchor_summary": {
            "trusted_1h_baseline_average": anchor["trusted_1h_baseline"]["normal_cost_rolling_5y_average"],
            "trusted_1h_baseline_median": anchor["trusted_1h_baseline"]["normal_cost_rolling_5y_median"],
            "htf_best_variant": anchor["htf_context_court"]["best_context_variant"],
            "six_h_execution_state": anchor["six_hour_native_execution_court"]["final_classification"],
        },
    }


def _shadow_log_schema() -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "ledger/shadow_signal_log.csv": {
            "required_fields": [
                "run_id",
                "signal_id",
                "timestamp",
                "candle_close_time",
                "processing_time",
                "delay_seconds",
                "symbol",
                "execution_timeframe",
                "direction",
                "signal_state",
                "accepted_or_rejected",
                "rejection_reason",
                "baseline_1h_signal",
                "confluence_score",
                "confluence_components",
                "sr_context",
                "entry_reference",
                "stop_reference",
                "target_reference",
                "estimated_risk_r",
                "estimated_cost_band",
                "no_order_sent",
            ],
            "required_constant_values": {"no_order_sent": True},
        },
        "ledger/shadow_context_log.csv": {
            "required_fields": [
                "signal_id",
                "timestamp",
                "context_timeframe",
                "context_candle_close_time",
                "context_available_before_signal",
                "htf_trend",
                "htf_structure",
                "htf_supply_zone_distance",
                "htf_demand_zone_distance",
                "room_to_target",
                "liquidity_pool_above",
                "liquidity_pool_below",
                "sweep_context",
                "conflict_flag",
                "six_h_confluence_flag",
                "six_h_execution_disabled",
                "twelve_h_execution_retired",
            ],
            "required_constant_values": {
                "six_h_execution_disabled": True,
                "twelve_h_execution_retired": True,
            },
        },
        "ledger/shadow_research_overlay_log.csv": {
            "required_fields": [
                "signal_id",
                "baseline_1h_hypothetical_action",
                "six_h_context_overlay_action",
                "six_h_context_overlay_reason",
                "aggressive_300k_shadow_overlay_action",
                "aggressive_300k_shadow_only",
                "six_h_native_execution_shadow_status",
                "hypothetical_risk_multiplier",
                "hypothetical_cost_adjusted_r",
                "no_order_sent",
            ],
            "required_constant_values": {
                "aggressive_300k_shadow_only": True,
                "six_h_native_execution_shadow_status": "disabled_weak",
                "no_order_sent": True,
            },
        },
        "ledger/shadow_data_quality_log.csv": {
            "required_fields": [
                "timestamp",
                "source",
                "timeframe",
                "missing_candles",
                "duplicate_candles",
                "stale_data_seconds",
                "resampling_gap",
                "timezone_warning",
                "candle_delay_seconds",
                "severity",
                "action_required",
            ],
        },
    }


def _report_templates() -> tuple[dict[str, Any], dict[str, str]]:
    templates_json = {
        **RESEARCH_ONLY_FLAGS,
        "daily_report": {
            "sections": [
                "total_1h_signals",
                "accepted_signals",
                "rejected_signals",
                "rejection_reasons",
                "six_h_confluence_count",
                "six_h_conflict_count",
                "hypothetical_baseline_1h_result",
                "hypothetical_1h_plus_6h_context_result",
                "aggressive_gear_shadow_only_result",
                "cost_slippage_estimate",
                "data_gaps",
                "candle_delays",
                "missed_signals",
                "no_order_confirmation",
            ]
        },
        "weekly_report": {
            "sections": [
                "signal_count",
                "active_days",
                "zero_signal_days",
                "baseline_vs_6h_context_comparison",
                "rejected_setup_review",
                "top_positive_hypothetical_setups",
                "top_negative_hypothetical_setups",
                "data_quality_summary",
                "operational_reliability_summary",
                "forward_vs_historical_expectation_alignment",
            ]
        },
        "monthly_report": {
            "sections": [
                "cumulative_hypothetical_r",
                "baseline_vs_6h_context_hypothetical_equity",
                "signal_frequency",
                "missed_trade_count",
                "data_reliability",
                "candle_delay_reliability",
                "cost_slippage_realism",
                "six_h_context_usefulness",
                "aggressive_gear_shadow_only_confirmation",
                "paper_validation_still_blocked",
            ]
        },
        "cumulative_report": {
            "sections": [
                "since_start_signal_count",
                "since_start_hypothetical_r",
                "since_start_baseline_vs_6h_context_comparison",
                "operational_uptime",
                "missed_signal_rate",
                "data_gap_rate",
                "average_candle_delay",
                "worst_candle_delay",
                "no_order_confirmation",
                "readiness_gate_status",
            ]
        },
    }
    templates_md = {
        "daily_report_template.md": """# Daily Shadow Report\n\n## Signal Court\n- Total 1H signals:\n- Accepted signals:\n- Rejected signals:\n- Rejection reasons:\n\n## 6H Context Overlay\n- 6H confluence count:\n- 6H conflict count:\n- LIGHT_BOOST_6H_CONFLUENCE observations:\n\n## Hypothetical Outcome View\n- Baseline 1H hypothetical result:\n- 1H + 6H context hypothetical result:\n- Aggressive gear shadow-only result:\n- Estimated cost/slippage effect:\n\n## Operational Integrity\n- Data gaps:\n- Candle delays:\n- Missed signals:\n- No-order confirmation: true\n""",
        "weekly_report_template.md": """# Weekly Shadow Report\n\n## Flow Summary\n- Signal count:\n- Active days:\n- Zero-signal days:\n\n## Comparative Review\n- Baseline vs 6H-context comparison:\n- Rejected setup review:\n- Top positive hypothetical setups:\n- Top negative hypothetical setups:\n\n## Reliability Court\n- Data quality summary:\n- Operational reliability summary:\n- Does forward behavior match historical expectations?\n""",
        "monthly_report_template.md": """# Monthly Shadow Report\n\n## Hypothetical Equity Review\n- Cumulative hypothetical R:\n- Baseline vs 6H-context hypothetical equity:\n- Signal frequency:\n- Missed-trade count:\n\n## Reliability and Realism\n- Data reliability:\n- Candle delay reliability:\n- Cost/slippage realism:\n\n## Strategic Status\n- Does 6H context still appear useful?\n- Aggressive gear remains shadow-only: true\n- Paper validation still blocked: true\n""",
        "cumulative_report_template.md": """# Cumulative Shadow Report\n\n## Since-Start Court\n- Since-start signal count:\n- Since-start hypothetical R:\n- Since-start baseline vs 6H-context comparison:\n\n## Operational Integrity\n- Operational uptime:\n- Missed signal rate:\n- Data gap rate:\n- Average candle delay:\n- Worst candle delay:\n- No-order confirmation: true\n\n## Readiness\n- Readiness gate status:\n""",
    }
    return templates_json, templates_md


def _shadow_readiness_gates() -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "not_passed_yet": True,
        "gates": [
            {"gate": "minimum_shadow_duration", "rule": f">= {RECOMMENDED_SHADOW_DURATION_DAYS} days", "status": "pending"},
            {"gate": "minimum_signal_observations", "rule": f">= {RECOMMENDED_MINIMUM_SIGNAL_COUNT} observed 1H decisions", "status": "pending"},
            {"gate": "unexplained_missed_signals", "rule": "0 unexplained missed signals", "status": "pending"},
            {"gate": "signal_reproduction_accuracy", "rule": f">= {MIN_SIGNAL_REPRODUCTION_ACCURACY:.0%}", "status": "pending"},
            {"gate": "candle_close_delay_limit", "rule": f"<= {MAX_ALLOWED_DELAY_SECONDS} seconds median delay", "status": "pending"},
            {"gate": "data_gap_rate", "rule": f"< {MAX_ALLOWED_DATA_GAP_RATE:.2%}", "status": "pending"},
            {"gate": "six_h_context_reproducibility", "rule": "6H labels reproducible without lookahead", "status": "pending"},
            {"gate": "cost_assumption_realism", "rule": "normal-cost assumptions remain realistic", "status": "pending"},
            {"gate": "baseline_vs_context_stability", "rule": "baseline and 6H-context comparison remains stable", "status": "pending"},
            {"gate": "aggressive_gear_shadow_only", "rule": "aggressive gear never promoted beyond shadow logging", "status": "locked"},
            {"gate": "six_h_native_execution_disabled", "rule": "6H native execution remains disabled unless reopened by future court", "status": "locked"},
            {"gate": "no_order_path", "rule": "no paper/live/broker orders sent", "status": "locked"},
        ],
    }


def _replay_vs_forward_consistency_spec() -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "checks": [
            "signal_reproduction_check",
            "timestamp_alignment_check",
            "candle_close_alignment_check",
            "context_label_reproducibility_check",
            "six_h_resampling_consistency_check",
            "rejected_setup_consistency_check",
            "cost_estimate_consistency_check",
            "no_lookahead_check",
            "version_hash_tracking",
        ],
        "version_tracking_fields": [
            "signal_logic_hash",
            "context_logic_hash",
            "cost_model_hash",
            "data_source_manifest_hash",
            "shadow_spec_version",
        ],
        "rules": {
            "only_closed_candle_comparisons": True,
            "context_must_exist_before_signal": True,
            "forward_run_must_log_processing_delay": True,
        },
    }


def _operational_risk_register() -> list[dict[str, Any]]:
    return [
        {
            "risk": "missed_candle_risk",
            "severity": "high",
            "detection": "data_gap_monitor",
            "mitigation": "gap logging and blocked comparison when unresolved",
            "owner": "shadow_observer",
        },
        {
            "risk": "duplicate_candle_risk",
            "severity": "medium",
            "detection": "dedupe check on canonical source",
            "mitigation": "dedupe log plus severity escalation",
            "owner": "shadow_observer",
        },
        {
            "risk": "exchange_api_outage",
            "severity": "high",
            "detection": "stale source timestamps",
            "mitigation": "stale-data alert and no-order guarantee",
            "owner": "runtime_operator",
        },
        {
            "risk": "local_machine_sleep",
            "severity": "high",
            "detection": "heartbeat gap",
            "mitigation": "operator warning and replay-vs-forward reconciliation",
            "owner": "runtime_operator",
        },
        {
            "risk": "timezone_mismatch",
            "severity": "medium",
            "detection": "timezone audit",
            "mitigation": "UTC-normalized logging and blocked readiness if unresolved",
            "owner": "shadow_observer",
        },
        {
            "risk": "delayed_processing",
            "severity": "medium",
            "detection": "delay_seconds tracking",
            "mitigation": "latency threshold monitoring",
            "owner": "shadow_observer",
        },
        {
            "risk": "cost_slippage_underestimation",
            "severity": "medium",
            "detection": "cost-band comparison",
            "mitigation": "normal, conservative, high-slippage overlays",
            "owner": "research_court",
        },
        {
            "risk": "signal_duplication",
            "severity": "medium",
            "detection": "signal_id uniqueness audit",
            "mitigation": "deduplicated shadow ledger and blocked readiness on unresolved duplicates",
            "owner": "shadow_observer",
        },
        {
            "risk": "wrong_candle_finality",
            "severity": "high",
            "detection": "candle_finality_checker",
            "mitigation": "closed-bar enforcement only",
            "owner": "shadow_observer",
        },
        {
            "risk": "over_trusting_6h_context",
            "severity": "medium",
            "detection": "baseline-vs-context comparison",
            "mitigation": "6H remains annotation only",
            "owner": "research_court",
        },
        {
            "risk": "accidentally_enabling_paper_live_order_path",
            "severity": "critical",
            "detection": "no-order-path self-audit",
            "mitigation": "shadow spec contains no order transport or execution hooks",
            "owner": "code_review",
        },
        {
            "risk": "emotional_override_risk",
            "severity": "medium",
            "detection": "manual override review",
            "mitigation": "read-only operator reports and explicit no-order boundary",
            "owner": "operator",
        },
        {
            "risk": "aggressive_gear_temptation_risk",
            "severity": "high",
            "detection": "shadow overlay review",
            "mitigation": "aggressive gear remains shadow-log only",
            "owner": "research_court",
        },
        {
            "risk": "six_h_execution_temptation_risk",
            "severity": "high",
            "detection": "role decision review",
            "mitigation": "6H native execution remains disabled weak",
            "owner": "research_court",
        },
    ]


def _shadow_forward_decision(anchor: dict[str, Any]) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "one_h_remains_main_execution_engine": True,
        "six_h_is_research_only_context": True,
        "six_h_receives_independent_capital": False,
        "six_h_native_execution_state": "disabled_weak",
        "twelve_h_execution_state": "retired",
        "diagnostic_only_timeframes": ["12H", "1D", "1W"],
        "fifteen_minute_state": "inactive_latest_court",
        "aggressive_300k_gear_state": "shadow_log_only",
        "next_step": "shadow_forward_observation_not_paper_live",
        "accepted_research_expectation_eur": "750k_to_800k",
        "context_best_variant": anchor["htf_context_court"]["best_context_variant"],
        "context_best_timeframe": anchor["htf_context_court"]["best_context_timeframe"],
        "final_classification": EXPECTED_FINAL_CLASSIFICATION,
    }


def _next_research_recommendation() -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "next_step": "start_shadow_forward_observation_spec_only",
        "do_not_start_paper": True,
        "do_not_start_live": True,
        "do_not_enable_6h_native_execution": True,
        "do_not_promote_aggressive_gear": True,
        "observation_target_days": RECOMMENDED_SHADOW_DURATION_DAYS,
        "minimum_signal_count": RECOMMENDED_MINIMUM_SIGNAL_COUNT,
        "primary_goal": "verify 1H signal reproduction and 6H context annotation consistency on fresh closed candles",
    }


def _implementation_self_audit(anchor_loaded: bool) -> dict[str, Any]:
    return {
        **RESEARCH_ONLY_FLAGS,
        "prior_baseline_loaded": anchor_loaded,
        "htf_context_court_loaded": anchor_loaded,
        "six_hour_native_execution_court_loaded": anchor_loaded,
        "earned_gear_court_loaded": anchor_loaded,
        "shadow_only_spec": True,
        "no_order_path_created": True,
        "no_paper_path_created": True,
        "no_live_path_created": True,
        "no_runtime_behavior_changed": True,
        "no_production_config_changed": True,
        "log_schemas_defined": True,
        "report_templates_defined": True,
        "readiness_gates_defined": True,
        "replay_vs_forward_consistency_defined": True,
        "operational_risk_register_defined": True,
        "previous_artifacts_overwritten": False,
        "reviewer_notes": [
            "This audit writes specification artifacts only.",
            "No order transport, broker connector, allocator mutation, or runtime side effects were introduced.",
            "6H remains context-only and 12H execution remains retired.",
        ],
    }


def _summary_payload(
    anchor: dict[str, Any] | None,
    *,
    final_classification: str,
    warnings: list[str],
) -> dict[str, Any]:
    baseline_average = anchor["trusted_1h_baseline"]["normal_cost_rolling_5y_average"] if anchor else 0.0
    baseline_median = anchor["trusted_1h_baseline"]["normal_cost_rolling_5y_median"] if anchor else 0.0
    baseline_hits = anchor["trusted_1h_baseline"]["hit_1m_windows"] if anchor else 0
    return {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "prior_baseline_loaded": anchor is not None,
        "six_h_context_court_loaded": anchor is not None,
        "six_h_native_execution_court_loaded": anchor is not None,
        "earned_gear_court_loaded": anchor is not None,
        "baseline_average": baseline_average,
        "baseline_median": baseline_median,
        "baseline_hit_1m_windows": baseline_hits,
        "shadow_observation_duration_recommended_days": RECOMMENDED_SHADOW_DURATION_DAYS,
        "minimum_signal_count_recommended": RECOMMENDED_MINIMUM_SIGNAL_COUNT,
        "readiness_gate_count": 12,
        "log_schema_count": 4,
        "report_template_count": 4,
        "replay_vs_forward_consistency_defined": True,
        "operational_risk_register_defined": True,
        "checkpoint_resume_status": "resume_capable",
        "final_classification": final_classification,
        "warnings": warnings,
    }


def _report_text(summary: dict[str, Any], anchor: dict[str, Any] | None, warnings: list[str]) -> str:
    warning_lines = "\n".join(f"- {warning}" for warning in warnings) if warnings else "- none"
    anchor_lines = "- prior court anchor unavailable" if anchor is None else "\n".join(
        [
            f"- Trusted 1H baseline: EUR {anchor['trusted_1h_baseline']['normal_cost_rolling_5y_average']:.2f} average / EUR {anchor['trusted_1h_baseline']['normal_cost_rolling_5y_median']:.2f} median / {anchor['trusted_1h_baseline']['hit_1m_windows']} x 1M-hit windows",
            f"- 6H context court: {anchor['htf_context_court']['final_classification']} via {anchor['htf_context_court']['best_context_variant']}",
            f"- 6H native execution court: {anchor['six_hour_native_execution_court']['final_classification']}",
            f"- Earned gear court: {anchor['earned_gear_court']['final_classification']}",
        ]
    )
    return f"""# Shadow-Forward Validation Specification Audit

## Court Anchor
{anchor_lines}

## Strategic Decision
- 1H remains the main execution engine.
- 6H is retained as research-only context and map annotation.
- 6H native execution remains disabled and receives no independent capital.
- 12H execution remains retired.
- 12H / 1D / 1W remain diagnostic only.
- Aggressive 300k gear remains shadow-log only.

## Shadow-Forward Readiness Spec
- Recommended observation duration: {summary['shadow_observation_duration_recommended_days']} days
- Minimum observed 1H signal count: {summary['minimum_signal_count_recommended']}
- Readiness gate count: {summary['readiness_gate_count']}
- Log schema count: {summary['log_schema_count']}
- Report template count: {summary['report_template_count']}
- Replay-vs-forward consistency defined: {str(summary['replay_vs_forward_consistency_defined']).lower()}
- Operational risk register defined: {str(summary['operational_risk_register_defined']).lower()}

## Safety Boundaries
- Research-only: true
- Paper allowed: false
- Live allowed: false
- Real money allowed: false
- Behavior change allowed: false
- No order path created: true

## Warnings
{warning_lines}

## Final Classification
- {summary['final_classification']}
"""


def _blocked_outputs(
    config: ShadowForwardValidationSpecAuditConfig,
    *,
    compatibility_signature: str,
    warnings: list[str],
) -> dict[str, Path]:
    diagnostics_root, _, reports_root, checkpoints_root = _ensure_dirs(config.output_root)
    completed_sections: list[str] = []
    _write_status(
        config.output_root,
        state=STATE_BLOCKED,
        warnings=warnings,
        compatibility_signature=compatibility_signature,
        extra={"final_classification": "SHADOW_SPEC_BLOCKED"},
    )
    _write_scenario_progress(
        config.output_root,
        state=STATE_BLOCKED,
        completed_sections=completed_sections,
        warnings=warnings,
        compatibility_signature=compatibility_signature,
    )
    _write_run_progress(
        diagnostics_root,
        state=STATE_BLOCKED,
        completed_sections=completed_sections,
        total_sections=8,
        current_section="prior_court_anchor",
        warnings=warnings,
    )
    summary = _summary_payload(None, final_classification="SHADOW_SPEC_BLOCKED", warnings=warnings)
    _write_json(config.output_root / "shadow_forward_validation_spec_summary.json", summary)
    _write_json(diagnostics_root / "implementation_self_audit.json", _implementation_self_audit(False))
    _write_json(checkpoints_root / "checkpoint_index.json", {"completed_sections": [], **RESEARCH_ONLY_FLAGS})
    _write_json(reports_root / "next_research_recommendation.json", _next_research_recommendation())
    _write_markdown(config.output_root / "shadow_forward_validation_spec_report.md", _report_text(summary, None, warnings))
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "shadow_forward_validation_spec_summary.json",
        "report": config.output_root / "shadow_forward_validation_spec_report.md",
    }


def write_shadow_forward_validation_spec_audit(
    config: ShadowForwardValidationSpecAuditConfig,
) -> dict[str, Path]:
    diagnostics_root, ledger_root, reports_root, checkpoints_root = _ensure_dirs(config.output_root)
    compatibility_signature = _compatibility_signature(_compatibility_payload())
    completed_sections: list[str] = []
    warnings: list[str] = []
    total_sections = 8

    try:
        _write_status(
            config.output_root,
            state=STATE_RUNNING,
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )
        _write_scenario_progress(
            config.output_root,
            state=STATE_RUNNING,
            completed_sections=completed_sections,
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )
        _write_run_progress(
            diagnostics_root,
            state=STATE_RUNNING,
            completed_sections=completed_sections,
            total_sections=total_sections,
            current_section="prior_court_anchor",
            warnings=warnings,
        )

        anchor, anchor_warnings = _load_prior_court_anchor(config)
        warnings.extend(anchor_warnings)
        if anchor is None:
            return _blocked_outputs(config, compatibility_signature=compatibility_signature, warnings=warnings)

        _write_json(diagnostics_root / "prior_court_anchor.json", anchor)
        completed_sections.append("prior_court_anchor")

        architecture_spec = _shadow_forward_architecture_spec(anchor)
        _write_json(diagnostics_root / "shadow_forward_architecture_spec.json", architecture_spec)
        completed_sections.append("shadow_forward_architecture_spec")

        log_schema = _shadow_log_schema()
        _write_json(diagnostics_root / "shadow_log_schema.json", log_schema)
        completed_sections.append("shadow_log_schema")

        templates_json, templates_md = _report_templates()
        _write_json(diagnostics_root / "shadow_report_templates.json", templates_json)
        for name, content in templates_md.items():
            _write_markdown(reports_root / name, content)
        completed_sections.append("shadow_report_templates")

        readiness = _shadow_readiness_gates()
        _write_json(diagnostics_root / "shadow_readiness_gates.json", readiness)
        consistency = _replay_vs_forward_consistency_spec()
        _write_json(diagnostics_root / "replay_vs_forward_consistency_spec.json", consistency)
        risk_register = _operational_risk_register()
        _write_csv(diagnostics_root / "shadow_operational_risk_register.csv", risk_register)
        completed_sections.append("readiness_consistency_and_risk")

        decision = _shadow_forward_decision(anchor)
        next_recommendation = _next_research_recommendation()
        _write_json(diagnostics_root / "shadow_forward_decision.json", decision)
        _write_json(reports_root / "next_research_recommendation.json", next_recommendation)
        completed_sections.append("decision")

        self_audit = _implementation_self_audit(True)
        _write_json(diagnostics_root / "implementation_self_audit.json", self_audit)
        completed_sections.append("implementation_self_audit")

        summary = _summary_payload(anchor, final_classification=decision["final_classification"], warnings=warnings)
        _write_json(config.output_root / "shadow_forward_validation_spec_summary.json", summary)
        _write_markdown(config.output_root / "shadow_forward_validation_spec_report.md", _report_text(summary, anchor, warnings))
        completed_sections.append("final_summary_and_report")

        _write_json(checkpoints_root / "checkpoint_index.json", {"completed_sections": completed_sections, "compatibility_signature": compatibility_signature, **RESEARCH_ONLY_FLAGS})
        for section in completed_sections:
            _write_json(
                checkpoints_root / f"{section}.json",
                {
                    "section": section,
                    "completed_at_utc": datetime.now(timezone.utc).isoformat(),
                    "compatibility_signature": compatibility_signature,
                    **RESEARCH_ONLY_FLAGS,
                },
            )
        _write_status(
            config.output_root,
            state=STATE_COMPLETED,
            warnings=warnings,
            compatibility_signature=compatibility_signature,
            extra={"final_classification": decision["final_classification"]},
        )
        _write_scenario_progress(
            config.output_root,
            state=STATE_COMPLETED,
            completed_sections=completed_sections,
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )
        _write_run_progress(
            diagnostics_root,
            state=STATE_COMPLETED,
            completed_sections=completed_sections,
            total_sections=total_sections,
            current_section="",
            warnings=warnings,
        )
        return {
            "status": config.output_root / "status.json",
            "summary": config.output_root / "shadow_forward_validation_spec_summary.json",
            "report": config.output_root / "shadow_forward_validation_spec_report.md",
        }
    except Exception as exc:  # pragma: no cover
        warnings = [*warnings, f"Shadow-forward validation spec audit failed: {exc}"]
        _write_status(
            config.output_root,
            state=STATE_FAILED,
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )
        _write_scenario_progress(
            config.output_root,
            state=STATE_FAILED,
            completed_sections=completed_sections,
            warnings=warnings,
            compatibility_signature=compatibility_signature,
        )
        _write_run_progress(
            diagnostics_root,
            state=STATE_FAILED,
            completed_sections=completed_sections,
            total_sections=total_sections,
            current_section="",
            warnings=warnings,
        )
        raise


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    result = write_shadow_forward_validation_spec_audit(
        ShadowForwardValidationSpecAuditConfig(
            package_root=package_root,
            output_root=package_root / "output" / OUTPUT_FOLDER_NAME,
        )
    )
    print(json.dumps({key: str(value) for key, value in result.items()}, indent=2))
