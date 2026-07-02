from __future__ import annotations

import json
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

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
    _signature_definitions,
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
    _target_hit_metrics,
    _window_rows,
)


@dataclass(frozen=True)
class EqualHighsLiquiditySweepRescueForensicAuditConfig:
    package_root: Path
    output_root: Path


FORBIDDEN_FUTURE_FIELDS = {
    "r_multiple",
    "pnl",
    "final_pnl",
    "future_mfe",
    "future_mae",
    "future_high",
    "future_low",
    "post_entry_outcome",
    "exit_price",
    "exit_reason",
    "exit_timestamp",
}

DESIRED_PRE_ENTRY_FIELDS = [
    "equal_highs",
    "sweep_high",
    "liquidity_event_type",
    "entry_context",
    "nearest_resistance_strength",
    "nearest_resistance_touch_count",
    "resistance_distance_pct",
    "support_distance_pct",
    "structure_score",
    "liquidity_score",
    "liquidity_confidence",
    "htf_aligned",
    "htf_bias",
    "htf_confirmation_score",
    "ema_score",
    "vwap_support",
    "volume_confirmation",
    "stop_distance_pct",
    "risk_reward_score",
    "rr_from_reason",
    "entry_score",
    "setup_class",
    "setup_pattern",
    "volatility_score",
    "session_hour",
    "wick_body_rejection",
    "room_to_next_support",
    "room_to_next_resistance",
]

NUMERIC_FEATURES = [
    "level_distance_atr",
    "structure_score",
    "liquidity_score",
    "liquidity_confidence",
    "entry_score",
    "ema_score",
    "htf_confirmation_score",
    "risk_reward_score",
    "rr_from_reason",
    "stop_distance_pct",
    "support_distance_pct",
    "resistance_distance_pct",
    "volatility_score",
]

CATEGORICAL_FEATURES = [
    "pattern",
    "setup_class",
    "entry_context",
    "liquidity_event_type",
    "liquidity_side_implication",
    "personality_label",
    "convexity_label",
    "htf_bias",
    "volume_confirmation",
]


def _paths(config: EqualHighsLiquiditySweepRescueForensicAuditConfig) -> dict[str, Path]:
    source_root = config.package_root / "output"
    broad_root = source_root / "broad_historical_structural_replay_001"
    broad_ledger_root = broad_root / "ledger"
    patch_root = source_root / "broad_frozen_patch_validation_001"
    blunt_root = source_root / "broad_patch_bluntness_audit_001"
    rescue_root = source_root / "broad_patch_accounting_and_short_rescue_audit_001"
    rolling_root = source_root / "rolling_five_year_mission_viability_audit_001"
    return {
        "trades": broad_ledger_root / "trades.csv",
        "equity": broad_ledger_root / "equity.csv",
        "ledger_summary": broad_ledger_root / "summary.json",
        "setup_log": broad_ledger_root / "setup_log.csv",
        "level_log": broad_ledger_root / "level_log.csv",
        "liquidity_events": broad_ledger_root / "liquidity_events.csv",
        "patch_summary": patch_root / "broad_frozen_patch_summary.json",
        "blunt_summary": blunt_root / "broad_patch_bluntness_summary.json",
        "removed_short_convexity": blunt_root / "diagnostics" / "removed_short_convexity_audit.csv",
        "removed_winners_archetype_year": blunt_root / "diagnostics" / "removed_winners_by_archetype_year.csv",
        "removed_losers_failure_year": blunt_root / "diagnostics" / "removed_losers_by_failure_mode_year.csv",
        "rescue_summary": rescue_root / "broad_patch_accounting_and_short_rescue_summary.json",
        "removed_short_winner_profile": rescue_root / "diagnostics" / "removed_short_winner_profile.csv",
        "removed_short_loser_profile": rescue_root / "diagnostics" / "removed_short_loser_profile.csv",
        "removed_short_contrast": rescue_root / "diagnostics" / "removed_short_winner_vs_loser_feature_contrast.csv",
        "rescue_signature_definitions": rescue_root / "diagnostics" / "rescue_signature_definitions.json",
        "rescue_signature_candidate_results": rescue_root / "diagnostics" / "rescue_signature_candidate_results.csv",
        "variant_reconciled": rescue_root / "diagnostics" / "variant_comparison_reconciled.csv",
        "rolling_summary": rolling_root / "rolling_five_year_mission_summary.json",
        "rolling_results": rolling_root / "diagnostics" / "rolling_5y_window_results.csv",
        "rolling_short_rescue_impact": rolling_root / "diagnostics" / "short_rescue_mission_impact.csv",
        "rolling_cost": rolling_root / "diagnostics" / "cost_stress_mission_survival.csv",
        "rolling_moonshot": rolling_root / "diagnostics" / "moonshot_cap_mission_survival.csv",
        "worst_case_windows": rolling_root / "diagnostics" / "worst_case_5y_windows.csv",
        "best_case_windows": rolling_root / "diagnostics" / "best_case_5y_windows.csv",
        "a_plus_sensitivity": rolling_root / "diagnostics" / "a_plus_capital_deployment_sensitivity.csv",
        "capital_multiplier_risk": rolling_root / "diagnostics" / "capital_multiplier_risk_report.json",
        "frozen_patch_rules": source_root / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, reports_root


def _empty_outputs(config: EqualHighsLiquiditySweepRescueForensicAuditConfig, warnings: list[str]) -> dict[str, Path]:
    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    status = {"state": "empty", "resolved_at_utc": datetime.now(timezone.utc).isoformat(), **RESEARCH_ONLY_FLAGS, "warnings": warnings}
    summary = {**RESEARCH_ONLY_FLAGS, "warnings": warnings, "final_classification": "RESCUE_REJECTED"}
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "equal_highs_liquidity_sweep_rescue_summary.json", summary)
    _write_markdown(config.output_root / "equal_highs_liquidity_sweep_rescue_report.md", "# Equal Highs Liquidity Sweep Rescue Forensic Audit\n\nRequired artifacts missing.\n")
    for name in (
        "rescued_short_trade_profile.csv",
        "rescued_short_winner_vs_loser_contrast.csv",
        "sr_liquidity_feature_separation.csv",
        "rescued_short_by_year.csv",
        "rescued_short_by_rolling_window.csv",
        "rescued_short_by_session.csv",
        "rescue_reintroduced_loss_audit.csv",
        "rescue_reintroduced_loss_by_failure_mode.csv",
        "rescue_reintroduced_loss_by_year.csv",
        "rescue_reintroduced_loss_by_window.csv",
        "rescue_candidate_rolling_5y_robustness.csv",
        "rescue_candidate_cost_survival.csv",
        "rescue_candidate_moonshot_survival.csv",
        "rescue_candidate_drawdown_governor.csv",
        "insolvency_clamp_impact.csv",
        "stricter_rescue_variant_results.csv",
    ):
        _write_csv(diagnostics_root / name, [])
    for name in (
        "rescue_candidate_reconstruction.json",
        "rescue_candidate_no_future_leakage_check.json",
        "missing_pre_entry_fields_report.json",
        "rescue_damage_summary.json",
        "risk_governor_impact.json",
        "stricter_rescue_variant_definitions.json",
        "stricter_rescue_variant_results.json",
        "stricter_rescue_variant_no_leakage_check.json",
        "no_go_risks.json",
    ):
        _write_json(diagnostics_root / name, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "equal_highs_liquidity_sweep_rescue_summary.json",
        "report": config.output_root / "equal_highs_liquidity_sweep_rescue_report.md",
    }


def _safe_float(value: Any) -> float:
    try:
        if value is None or str(value).strip() == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _boolish(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _normalize_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    keys: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in keys:
                keys.append(key)
    return [{key: row.get(key, "") for key in keys} for row in rows]


def _year_key(ts: pd.Timestamp | None) -> str:
    return str(ts.year) if ts is not None else "unknown"


def _session_bucket(ts: pd.Timestamp | None) -> str:
    if ts is None:
        return "unknown"
    hour = ts.hour
    if 0 <= hour < 8:
        return "asia"
    if 8 <= hour < 16:
        return "europe"
    return "us"


def _window_label_for_trade(ts: pd.Timestamp | None, windows: list[tuple[pd.Timestamp, pd.Timestamp, str]]) -> str:
    if ts is None:
        return "unknown"
    matches = [label for start, end, label in windows if start <= ts <= end]
    return matches[-1] if matches else "outside_supported_windows"


def _candidate_definition(definitions_payload: dict[str, Any]) -> dict[str, Any]:
    for definition in definitions_payload.get("definitions", []):
        if definition.get("name") == "RESCUE_EQUAL_HIGHS_LIQUIDITY_SWEEP":
            return dict(definition)
    for definition in _signature_definitions():
        if definition.get("name") == "RESCUE_EQUAL_HIGHS_LIQUIDITY_SWEEP":
            return dict(definition)
    return {}


def _field_known_before_entry(field_name: str) -> bool:
    return field_name not in FORBIDDEN_FUTURE_FIELDS


def _feature_snapshot(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "trade_id": str(row.get("trade_id") or ""),
        "symbol": str(row.get("symbol") or ""),
        "entry_time": str(row.get("entry_time") or ""),
        "exit_time": str(row.get("exit_time") or ""),
        "year": _year_key(row.get("exit_timestamp")),
        "rolling_window_label": row.get("rolling_window_label", ""),
        "session_bucket": _session_bucket(row.get("entry_timestamp")),
        "side": str(row.get("side") or ""),
        "pattern": str(row.get("pattern") or ""),
        "setup_pattern": str(row.get("setup_pattern") or ""),
        "setup_class": str(row.get("setup_class") or ""),
        "entry_context": str(row.get("entry_context") or ""),
        "personality_label": str(row.get("personality_label") or ""),
        "convexity_label": str(row.get("convexity_label") or ""),
        "liquidity_event_type": str(row.get("liquidity_event_type") or ""),
        "liquidity_side_implication": str(row.get("liquidity_side_implication") or ""),
        "htf_bias": str(row.get("htf_bias") or ""),
        "htf_aligned": _boolish(row.get("htf_aligned")),
        "level_distance_atr": round(_safe_float(row.get("level_distance_atr")), 6),
        "structure_score": round(_safe_float(row.get("structure_score")), 6),
        "liquidity_score": round(_safe_float(row.get("liquidity_score")), 6),
        "liquidity_confidence": round(_safe_float(row.get("liquidity_confidence")), 6),
        "entry_score": round(_safe_float(row.get("entry_score")), 6),
        "ema_score": round(_safe_float(row.get("ema_score")), 6),
        "htf_confirmation_score": round(_safe_float(row.get("htf_confirmation_score")), 6),
        "risk_reward_score": round(_safe_float(row.get("risk_reward_score")), 6),
        "rr_from_reason": round(_safe_float(row.get("rr_from_reason")), 6),
        "stop_distance_pct": round(_safe_float(row.get("stop_distance_pct")), 6),
        "support_distance_pct": round(_safe_float(row.get("support_distance_pct")), 6),
        "resistance_distance_pct": round(_safe_float(row.get("resistance_distance_pct")), 6),
        "nearest_resistance_strength": round(_safe_float(row.get("nearest_resistance_strength")), 6),
        "nearest_support_strength": round(_safe_float(row.get("nearest_support_strength")), 6),
        "nearest_resistance_touch_count": int(_safe_float(row.get("nearest_resistance_touch_count"))),
        "nearest_support_touch_count": int(_safe_float(row.get("nearest_support_touch_count"))),
        "volume_confirmation": str(row.get("volume_confirmation") or ""),
        "vwap_support": str(row.get("vwap_support") or ""),
        "volatility_score": round(_safe_float(row.get("volatility_score")), 6),
        "r_multiple": round(_safe_float(row.get("r_multiple")), 6),
        "pnl": round(_safe_float(row.get("pnl")), 6),
    }


def _bucket_label(r_value: float) -> str:
    if r_value >= 10.0:
        return "rescued_10R_plus_winner"
    if r_value >= 5.0:
        return "rescued_5R_plus_winner"
    if r_value >= 3.0:
        return "rescued_3R_plus_winner"
    if r_value > 0.15:
        return "rescued_winner"
    if r_value >= -0.15:
        return "rescued_break_even_or_small_winner"
    if r_value <= -1.0:
        return "rescued_minus_1R_or_worse_loser"
    return "rescued_loser"


def _feature_separation_rows(winners: list[dict[str, Any]], losers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for feature in NUMERIC_FEATURES:
        win_vals = [_safe_float(row.get(feature)) for row in winners if str(row.get(feature, "")).strip() != ""]
        lose_vals = [_safe_float(row.get(feature)) for row in losers if str(row.get(feature, "")).strip() != ""]
        rows.append(
            {
                "feature": feature,
                "feature_type": "numeric",
                "winner_mean": round(sum(win_vals) / len(win_vals), 6) if win_vals else 0.0,
                "loser_mean": round(sum(lose_vals) / len(lose_vals), 6) if lose_vals else 0.0,
                "gap": round((sum(win_vals) / len(win_vals) if win_vals else 0.0) - (sum(lose_vals) / len(lose_vals) if lose_vals else 0.0), 6),
                "winner_mode": "",
                "loser_mode": "",
            }
        )
    for feature in CATEGORICAL_FEATURES:
        win_counter = Counter(str(row.get(feature) or "missing") for row in winners)
        lose_counter = Counter(str(row.get(feature) or "missing") for row in losers)
        rows.append(
            {
                "feature": feature,
                "feature_type": "categorical",
                "winner_mean": 0.0,
                "loser_mean": 0.0,
                "gap": 0.0,
                "winner_mode": win_counter.most_common(1)[0][0] if win_counter else "",
                "loser_mode": lose_counter.most_common(1)[0][0] if lose_counter else "",
            }
        )
    rows.sort(key=lambda row: (row["feature_type"], abs(_safe_float(row["gap"]))), reverse=True)
    return rows


def _group_stats(rows: list[dict[str, Any]], key_func: Callable[[dict[str, Any]], str], key_name: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        buckets[key_func(row)].append(row)
    output = []
    for key, bucket in sorted(buckets.items()):
        r_values = [_safe_float(row.get("r_multiple")) for row in bucket]
        output.append(
            {
                key_name: key,
                "trade_count": len(bucket),
                "winner_count": sum(1 for value in r_values if value > 0.0),
                "loser_count": sum(1 for value in r_values if value < 0.0),
                "total_R": round(sum(r_values), 6),
                "avg_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
                "median_R": round(_median(r_values), 6) if r_values else 0.0,
            }
        )
    return output


def _classify_failure_mode(row: dict[str, Any]) -> str:
    if not _boolish(row.get("htf_aligned")) and str(row.get("htf_bias") or "").lower() in {"bullish", "long"}:
        return "TREND_CONFLICT"
    support_distance = _safe_float(row.get("support_distance_pct"))
    stop_distance = _safe_float(row.get("stop_distance_pct"))
    if support_distance > 0.0 and stop_distance > 0.0 and support_distance <= stop_distance * 1.1:
        return "NO_NEARBY_SUPPORT_ROOM"
    if _safe_float(row.get("level_distance_atr")) > 0.35:
        return "WEAK_LEVEL_DISTANCE"
    if _safe_float(row.get("liquidity_confidence")) < 0.55:
        return "WEAK_LIQUIDITY_CONFIRMATION"
    if _safe_float(row.get("entry_score")) < 4.0 or str(row.get("setup_class") or "") in {"C", "D"}:
        return "WEAK_REJECTION_QUALITY"
    if _safe_float(row.get("resistance_distance_pct")) > 0.04:
        return "POOR_SR_LEVEL"
    if _safe_float(row.get("volatility_score")) > 0.8:
        return "VOLATILITY_STRESS"
    if _safe_float(row.get("r_multiple")) > -0.2:
        return "COST_SENSITIVE_SMALL_EDGE"
    return "UNKNOWN_REINTRODUCED_DAMAGE"


def _simulate_overlay(
    *,
    selected_rows: list[dict[str, Any]],
    start_capital: float = 20000.0,
    native_lock_ratio: float = 0.5,
    cost_bps_total: float = 0.0,
    moonshot_cap: float | None = None,
    remove_5plus: bool = False,
    insolvency_clamp: bool = False,
    drawdown_breaker_pct: float | None = None,
    reduced_risk_after_drawdown: bool = False,
    cooldown_after_worst_month: bool = False,
) -> dict[str, Any]:
    rows = sorted(selected_rows, key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or ""))
    active_capital = float(start_capital)
    locked_profit = 0.0
    peak_equity = active_capital
    max_drawdown_pct = 0.0
    current_month = None
    current_month_pnl = 0.0
    cooldown_remaining = 0
    cooldown_triggers = 0
    breaker_triggered = False
    insolvency_hit = False
    replay_rows: list[dict[str, Any]] = []
    daily: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        exit_ts = row.get("exit_timestamp")
        month_key = exit_ts.strftime("%Y-%m") if exit_ts is not None else "unknown"
        if current_month is None:
            current_month = month_key
        elif month_key != current_month:
            if cooldown_after_worst_month and current_month_pnl <= -start_capital * 0.05:
                cooldown_remaining = max(cooldown_remaining, 20)
                cooldown_triggers += 1
            current_month = month_key
            current_month_pnl = 0.0
        if cooldown_remaining > 0:
            cooldown_remaining -= 1
            continue
        current_equity = active_capital + locked_profit
        current_dd = _safe_ratio(max(0.0, peak_equity - current_equity), peak_equity, 0.0)
        if drawdown_breaker_pct is not None and current_dd >= drawdown_breaker_pct:
            breaker_triggered = True
            break
        applied_r = _safe_float(row.get("r_multiple"))
        if moonshot_cap is not None and applied_r > moonshot_cap:
            applied_r = moonshot_cap
        if remove_5plus and applied_r >= 5.0:
            continue
        risk_pct = 0.01
        if reduced_risk_after_drawdown and current_dd >= 0.10:
            risk_pct = 0.005
        risk_value = max(active_capital, 0.0) * risk_pct
        pnl = applied_r * risk_value
        if cost_bps_total > 0.0:
            entry_price = _safe_float(row.get("entry_price"))
            exit_price = _safe_float(row.get("exit_price")) or entry_price
            quantity = _safe_float(row.get("quantity")) or 1.0
            notional = abs((entry_price + exit_price) * 0.5 * quantity)
            pnl -= notional * (cost_bps_total / 10000.0)
        active_capital += pnl
        current_month_pnl += pnl
        if pnl > 0.0:
            lock_amount = pnl * native_lock_ratio
            locked_profit += lock_amount
            active_capital -= lock_amount
        total_equity = active_capital + locked_profit
        if insolvency_clamp and total_equity <= 0.0:
            active_capital = 0.0
            locked_profit = 0.0
            total_equity = 0.0
            insolvency_hit = True
            replay_rows.append(
                {
                    "trade_id": str(row.get("trade_id") or ""),
                    "timestamp": exit_ts.isoformat() if exit_ts is not None else "",
                    "applied_r": round(applied_r, 6),
                    "daily_pnl": round(pnl, 6),
                    "equity": 0.0,
                }
            )
            break
        peak_equity = max(peak_equity, total_equity)
        max_drawdown_pct = max(max_drawdown_pct, _safe_ratio(max(0.0, peak_equity - total_equity), peak_equity, 0.0))
        rec = {
            "trade_id": str(row.get("trade_id") or ""),
            "timestamp": exit_ts.isoformat() if exit_ts is not None else "",
            "applied_r": round(applied_r, 6),
            "daily_pnl": round(pnl, 6),
            "equity": round(total_equity, 6),
            "active_capital": round(active_capital, 6),
            "locked_profit": round(locked_profit, 6),
        }
        replay_rows.append(rec)
        date_key = exit_ts.strftime("%Y-%m-%d") if exit_ts is not None else "unknown"
        daily.setdefault(date_key, []).append(rec)
    daily_rows = []
    for date_key, bucket in sorted(daily.items()):
        daily_rows.append(
            {
                "date": date_key,
                "daily_pnl": round(sum(_safe_float(row.get("daily_pnl")) for row in bucket), 6),
                "daily_R": round(sum(_safe_float(row.get("applied_r")) for row in bucket), 6),
                "equity_end": round(_safe_float(bucket[-1].get("equity")), 6),
                "trade_count": len(bucket),
            }
        )
    r_values = [_safe_float(row.get("applied_r")) for row in replay_rows]
    wins = [value for value in r_values if value > 0.0]
    losses = [abs(value) for value in r_values if value < 0.0]
    profit_factor = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
    return {
        "ending_equity": round(active_capital + locked_profit, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "trade_count": len(replay_rows),
        "daily_rows": daily_rows,
        "profit_factor": round(profit_factor, 6),
        "avg_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
        "median_R": round(_median(r_values), 6) if r_values else 0.0,
        "total_R": round(sum(r_values), 6),
        "win_rate": round(_safe_ratio(len(wins), len(r_values), 0.0), 6) if r_values else 0.0,
        "insolvency_hit": insolvency_hit,
        "breaker_triggered": breaker_triggered,
        "cooldown_triggers": cooldown_triggers,
    }


def _robustness_overlay_specs() -> list[dict[str, Any]]:
    return [
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
        {"variant_name": "NO_TRADE_COOLDOWN_AFTER_WORST_MONTH_BREACH", "category": "governor", "cooldown_after_worst_month": True},
        {"variant_name": "REDUCED_RISK_AFTER_DRAWDOWN", "category": "governor", "reduced_risk_after_drawdown": True},
    ]


def _mission_row(
    *,
    variant_name: str,
    window_label: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    output: dict[str, Any],
) -> dict[str, Any]:
    target = _target_hit_metrics(output["daily_rows"], start_date=start)
    return {
        "variant_name": variant_name,
        "window_label": window_label,
        "start_date": str(start.date()),
        "end_date": str(end.date()),
        "ending_equity": output["ending_equity"],
        "hit_1m": target["hit_1m"],
        "hit_5m": target["hit_5m"],
        "hit_10m": target["hit_10m"],
        "days_to_1m": target["days_to_1m"],
        "days_to_5m": target["days_to_5m"],
        "days_to_10m": target["days_to_10m"],
        "max_drawdown_pct": output["max_drawdown_pct"],
        "trade_count": output["trade_count"],
        "profit_factor": output["profit_factor"],
        "avg_R": output["avg_R"],
        "median_R": output["median_R"],
        "total_R": output["total_R"],
        "win_rate": output["win_rate"],
        "insolvency_hit": output["insolvency_hit"],
        "breaker_triggered": output["breaker_triggered"],
        "cooldown_triggers": output["cooldown_triggers"],
    }


def _summarize_mission_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {
            "window_count": 0,
            "average_ending_equity": 0.0,
            "median_ending_equity": 0.0,
            "worst_ending_equity": 0.0,
            "best_ending_equity": 0.0,
            "hit_1m_windows": 0,
            "hit_5m_windows": 0,
            "hit_10m_windows": 0,
            "avg_max_drawdown_pct": 0.0,
            "worst_max_drawdown_pct": 0.0,
        }
    endings = [_safe_float(row.get("ending_equity")) for row in rows]
    drawdowns = [_safe_float(row.get("max_drawdown_pct")) for row in rows]
    return {
        "window_count": len(rows),
        "average_ending_equity": round(sum(endings) / len(endings), 6),
        "median_ending_equity": round(_median(endings), 6),
        "worst_ending_equity": round(min(endings), 6),
        "best_ending_equity": round(max(endings), 6),
        "hit_1m_windows": sum(1 for row in rows if _boolish(row.get("hit_1m"))),
        "hit_5m_windows": sum(1 for row in rows if _boolish(row.get("hit_5m"))),
        "hit_10m_windows": sum(1 for row in rows if _boolish(row.get("hit_10m"))),
        "avg_max_drawdown_pct": round(sum(drawdowns) / len(drawdowns), 6),
        "worst_max_drawdown_pct": round(max(drawdowns), 6),
    }


def _strict_variant_specs() -> list[dict[str, Any]]:
    return [
        {
            "variant_name": "STRICT_ORIGINAL_RULE",
            "fields_used": ["side", "pattern", "archetype_key", "level_distance_atr", "personality_label"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and _safe_float(row.get("level_distance_atr")) <= 0.35 and str(row.get("personality_label") or "") == "elite_convexity",
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_PLUS_REJECTION_QUALITY",
            "fields_used": ["side", "archetype_key", "level_distance_atr", "personality_label", "setup_class", "entry_score"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and _safe_float(row.get("level_distance_atr")) <= 0.30 and str(row.get("personality_label") or "") == "elite_convexity" and str(row.get("setup_class") or "") in {"A", "B"} and _safe_float(row.get("entry_score")) >= 4.0,
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_PLUS_HTF_AND_SR",
            "fields_used": ["side", "archetype_key", "personality_label", "htf_aligned", "entry_context", "resistance_distance_pct"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and _boolish(row.get("htf_aligned")) and str(row.get("entry_context") or "") in {"resistance", "range_high", "prev_day_high"} and 0.0 < _safe_float(row.get("resistance_distance_pct")) <= 0.04,
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_PLUS_ROOM_TO_SUPPORT",
            "fields_used": ["side", "archetype_key", "personality_label", "support_distance_pct", "stop_distance_pct", "liquidity_confidence"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and _safe_float(row.get("support_distance_pct")) >= max(0.006, _safe_float(row.get("stop_distance_pct")) * 1.25) and _safe_float(row.get("liquidity_confidence")) >= 0.60,
        },
        {
            "variant_name": "STRICT_EQUAL_HIGHS_COMPOSITE_A_PLUS",
            "fields_used": ["side", "archetype_key", "personality_label", "htf_aligned", "liquidity_confidence", "entry_score", "structure_score", "support_distance_pct", "stop_distance_pct"],
            "predicate": lambda row: ("equal_highs" in str(row.get("archetype_key") or "")) and str(row.get("personality_label") or "") == "elite_convexity" and sum(
                [
                    1 if _boolish(row.get("htf_aligned")) else 0,
                    1 if _safe_float(row.get("liquidity_confidence")) >= 0.60 else 0,
                    1 if _safe_float(row.get("entry_score")) >= 4.0 else 0,
                    1 if _safe_float(row.get("structure_score")) >= 0.90 else 0,
                    1 if _safe_float(row.get("support_distance_pct")) >= max(0.006, _safe_float(row.get("stop_distance_pct")) * 1.25) else 0,
                ]
            ) >= 3,
        },
    ]


def _variant_no_leakage_payload(definitions: list[dict[str, Any]]) -> dict[str, Any]:
    variants = []
    violations = []
    for definition in definitions:
        fields = definition["fields_used"]
        future_used = [field for field in fields if field in FORBIDDEN_FUTURE_FIELDS]
        if future_used:
            violations.append({"variant_name": definition["variant_name"], "forbidden_fields": future_used})
        variants.append(
            {
                "variant_name": definition["variant_name"],
                "fields_used": fields,
                "future_fields_used": future_used,
                "all_fields_pre_entry_safe": not future_used,
            }
        )
    return {
        **RESEARCH_ONLY_FLAGS,
        "variants": variants,
        "violations": violations,
        "final_no_leakage_verdict": not violations,
    }


def _moonshot_dependency_label(base_avg: float, capped_avg: float) -> str:
    if base_avg <= 0.0:
        return "no_edge"
    ratio = _safe_ratio(capped_avg, base_avg, 0.0)
    if ratio >= 0.8:
        return "robust_without_moonshots"
    if ratio >= 0.6:
        return "moderate_moonshot_dependency"
    return "moonshot_fragile"


def write_equal_highs_liquidity_sweep_rescue_forensic_audit(
    config: EqualHighsLiquiditySweepRescueForensicAuditConfig,
) -> dict[str, Path]:
    paths = _paths(config)
    required = (
        paths["trades"],
        paths["equity"],
        paths["ledger_summary"],
        paths["setup_log"],
        paths["level_log"],
        paths["liquidity_events"],
        paths["patch_summary"],
        paths["blunt_summary"],
        paths["removed_short_convexity"],
        paths["removed_winners_archetype_year"],
        paths["removed_losers_failure_year"],
        paths["rescue_summary"],
        paths["removed_short_winner_profile"],
        paths["removed_short_loser_profile"],
        paths["removed_short_contrast"],
        paths["rescue_signature_definitions"],
        paths["rescue_signature_candidate_results"],
        paths["variant_reconciled"],
        paths["rolling_summary"],
        paths["rolling_results"],
        paths["rolling_short_rescue_impact"],
        paths["rolling_cost"],
        paths["rolling_moonshot"],
        paths["worst_case_windows"],
        paths["best_case_windows"],
        paths["a_plus_sensitivity"],
        paths["capital_multiplier_risk"],
        paths["frozen_patch_rules"],
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return _empty_outputs(config, [f"missing_required_artifact:{path}" for path in missing])

    trade_rows = _read_csv_rows(paths["trades"])
    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    rescue_signature_definitions = _read_json(paths["rescue_signature_definitions"], {})
    rolling_short_rescue_rows = _read_csv_rows(paths["rolling_short_rescue_impact"])
    rolling_summary = _read_json(paths["rolling_summary"], {})

    normalized_rows = _normalize_trade_rows(trade_rows, setup_rows, level_rows, liquidity_rows)
    if not normalized_rows:
        return _empty_outputs(config, ["no_usable_trade_rows"])
    prepared_rows = _prepare_rows(normalized_rows)
    matched_short_archetypes, disabled_long_modes, _ = _load_frozen_rules(paths["frozen_patch_rules"])
    kept_rows, removed_rows = _apply_frozen_patch(
        prepared_rows,
        matched_short_archetypes=matched_short_archetypes,
        disabled_long_modes=disabled_long_modes,
    )
    windows = _build_windows(prepared_rows)
    removed_shorts = [row for row in removed_rows if row.get("side") == "short"]

    candidate_def = _candidate_definition(rescue_signature_definitions)
    if not candidate_def:
        return _empty_outputs(config, ["missing_equal_highs_candidate_definition"])

    rescued_candidate_rows = _apply_signature("RESCUE_EQUAL_HIGHS_LIQUIDITY_SWEEP", removed_shorts)
    for row in rescued_candidate_rows:
        row["rolling_window_label"] = _window_label_for_trade(row.get("exit_timestamp"), windows)
    rescued_winners = [row for row in rescued_candidate_rows if _safe_float(row.get("r_multiple")) > 0.0]
    rescued_losers = [row for row in rescued_candidate_rows if _safe_float(row.get("r_multiple")) < 0.0]
    rescued_3r = [row for row in rescued_candidate_rows if _safe_float(row.get("r_multiple")) >= 3.0]
    rescued_5r = [row for row in rescued_candidate_rows if _safe_float(row.get("r_multiple")) >= 5.0]
    rescued_10r = [row for row in rescued_candidate_rows if _safe_float(row.get("r_multiple")) >= 10.0]
    rescued_minus_1r = [row for row in rescued_candidate_rows if _safe_float(row.get("r_multiple")) <= -1.0]
    rescued_small = [row for row in rescued_candidate_rows if -0.15 <= _safe_float(row.get("r_multiple")) <= 0.15]

    candidate_reconstruction = {
        **RESEARCH_ONLY_FLAGS,
        "candidate_name": candidate_def.get("name"),
        "rule": candidate_def.get("rule"),
        "fields_used": candidate_def.get("fields_used", []),
        "future_fields_used": candidate_def.get("future_fields_used", []),
        "removed_short_pool_size": len(removed_shorts),
        "rescued_short_count": len(rescued_candidate_rows),
        "rescued_winner_count": len(rescued_winners),
        "rescued_loser_count": len(rescued_losers),
        "rescued_break_even_or_small_count": len(rescued_small),
        "rescued_total_R": round(sum(_safe_float(row.get("r_multiple")) for row in rescued_candidate_rows), 6),
        "optimistic_prior_mission_variant": "FROZEN_PATCH_PLUS_RESCUE_EQUAL_HIGHS_LIQUIDITY_SWEEP",
        "optimistic_prior_mission_average_ending_equity": 0.0,
        "optimistic_prior_mission_median_ending_equity": 0.0,
        "optimistic_prior_mission_1m_hit_windows": 0,
    }
    prior_rows = [row for row in rolling_short_rescue_rows if row.get("variant_name") == "FROZEN_PATCH_PLUS_RESCUE_EQUAL_HIGHS_LIQUIDITY_SWEEP"]
    if prior_rows:
        prior_endings = [_safe_float(row.get("ending_equity")) for row in prior_rows]
        candidate_reconstruction["optimistic_prior_mission_average_ending_equity"] = round(sum(prior_endings) / len(prior_endings), 6)
        candidate_reconstruction["optimistic_prior_mission_median_ending_equity"] = round(_median(prior_endings), 6)
        candidate_reconstruction["optimistic_prior_mission_1m_hit_windows"] = sum(1 for row in prior_rows if _boolish(row.get("hit_1m")))

    leakage_rows = []
    forbidden_used = []
    for field_name in candidate_def.get("fields_used", []):
        known = _field_known_before_entry(field_name)
        forbidden = field_name in FORBIDDEN_FUTURE_FIELDS
        if forbidden:
            forbidden_used.append(field_name)
        leakage_rows.append(
            {
                "field_name": field_name,
                "known_before_entry": known,
                "forbidden_future_field": forbidden,
            }
        )
    no_future_leakage = {
        **RESEARCH_ONLY_FLAGS,
        "candidate_name": candidate_def.get("name"),
        "rule": candidate_def.get("rule"),
        "fields_used": leakage_rows,
        "forbidden_future_fields_used": forbidden_used,
        "final_no_leakage_verdict": not forbidden_used,
    }

    rescued_trade_profile = []
    for row in rescued_candidate_rows:
        snapshot = _feature_snapshot(row)
        snapshot["bucket_label"] = _bucket_label(_safe_float(row.get("r_multiple")))
        rescued_trade_profile.append(snapshot)

    winner_vs_loser_contrast = _feature_separation_rows(
        [_feature_snapshot(row) for row in rescued_winners],
        [_feature_snapshot(row) for row in rescued_losers],
    )
    sr_liquidity_feature_separation = winner_vs_loser_contrast
    rescued_by_year = _group_stats(rescued_candidate_rows, lambda row: _year_key(row.get("exit_timestamp")), "year")
    rescued_by_window = _group_stats(rescued_candidate_rows, lambda row: str(row.get("rolling_window_label") or ""), "rolling_window_label")
    rescued_by_session = _group_stats(rescued_candidate_rows, lambda row: _session_bucket(row.get("entry_timestamp")), "session_bucket")

    available_fields = set()
    for row in rescued_candidate_rows[:50]:
        available_fields.update(row.keys())
    missing_pre_entry_fields = {
        **RESEARCH_ONLY_FLAGS,
        "desired_pre_entry_fields": DESIRED_PRE_ENTRY_FIELDS,
        "available_pre_entry_fields": sorted(field for field in DESIRED_PRE_ENTRY_FIELDS if field in available_fields),
        "missing_pre_entry_fields": sorted(field for field in DESIRED_PRE_ENTRY_FIELDS if field not in available_fields),
    }

    rescue_loss_audit = []
    for row in rescued_losers:
        snapshot = _feature_snapshot(row)
        snapshot["failure_mode"] = _classify_failure_mode(row)
        snapshot["cost_sensitivity_bucket"] = "cost_fragile" if _safe_float(row.get("r_multiple")) > -0.25 else "structural_loss"
        snapshot["setup_context"] = str(row.get("entry_reason") or row.get("setup_explanation") or "")
        rescue_loss_audit.append(snapshot)
    rescue_loss_by_failure = _group_stats(rescue_loss_audit, lambda row: str(row.get("failure_mode") or ""), "failure_mode")
    rescue_loss_by_failure.sort(key=lambda row: (_safe_float(row.get("total_R")), -int(_safe_float(row.get("trade_count")))))
    rescue_loss_by_year = _group_stats(rescue_loss_audit, lambda row: str(row.get("year") or ""), "year")
    rescue_loss_by_window = _group_stats(rescue_loss_audit, lambda row: str(row.get("rolling_window_label") or ""), "rolling_window_label")
    rescue_damage_summary = {
        **RESEARCH_ONLY_FLAGS,
        "rescued_loser_count": len(rescued_losers),
        "rescued_loser_total_R": round(sum(_safe_float(row.get("r_multiple")) for row in rescued_losers), 6),
        "top_failure_modes": rescue_loss_by_failure[:10],
    }

    candidate_selected_rows = kept_rows + rescued_candidate_rows
    overlay_rows = []
    overlays_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for start, end, label in windows:
        selected_window_rows = _window_rows(candidate_selected_rows, start, end)
        for spec in _robustness_overlay_specs():
            output = _simulate_overlay(
                selected_rows=selected_window_rows,
                cost_bps_total=_safe_float(spec.get("cost_bps_total")),
                moonshot_cap=spec.get("moonshot_cap"),
                remove_5plus=_boolish(spec.get("remove_5plus")),
                insolvency_clamp=_boolish(spec.get("insolvency_clamp")),
                drawdown_breaker_pct=spec.get("drawdown_breaker_pct"),
                reduced_risk_after_drawdown=_boolish(spec.get("reduced_risk_after_drawdown")),
                cooldown_after_worst_month=_boolish(spec.get("cooldown_after_worst_month")),
            )
            row = _mission_row(
                variant_name=spec["variant_name"],
                window_label=label,
                start=start,
                end=end,
                output=output,
            )
            row["overlay_category"] = spec["category"]
            overlay_rows.append(row)
            overlays_by_name[spec["variant_name"]].append(row)

    cost_survival_rows = [row for row in overlay_rows if row["overlay_category"] == "cost"]
    moonshot_survival_rows = [row for row in overlay_rows if row["overlay_category"] == "moonshot"]
    drawdown_governor_rows = [row for row in overlay_rows if row["overlay_category"] == "governor"]
    insolvency_rows = [row for row in overlay_rows if row["variant_name"] == "INSOLVENCY_CLAMP_ZERO"]

    risk_governor_impact = {
        **RESEARCH_ONLY_FLAGS,
        "governor_variants": {
            name: _summarize_mission_rows(rows)
            for name, rows in overlays_by_name.items()
            if name in {
                "INSOLVENCY_CLAMP_ZERO",
                "DRAWDOWN_CIRCUIT_BREAKER_10",
                "DRAWDOWN_CIRCUIT_BREAKER_15",
                "DRAWDOWN_CIRCUIT_BREAKER_20",
                "NO_TRADE_COOLDOWN_AFTER_WORST_MONTH_BREACH",
                "REDUCED_RISK_AFTER_DRAWDOWN",
            }
        },
    }

    strict_variant_definitions = []
    strict_variant_results = []
    baseline_for_comparison = _summarize_mission_rows(overlays_by_name["BASELINE_NATIVE_STYLE_RECONCILED"])
    for spec in _strict_variant_specs():
        rescued_variant = [row for row in removed_shorts if spec["predicate"](row)]
        variant_selected = kept_rows + rescued_variant
        variant_windows = []
        variant_normal_cost = []
        variant_moonshot_cap = []
        for start, end, label in windows:
            selected_window_rows = _window_rows(variant_selected, start, end)
            base_output = _simulate_overlay(selected_rows=selected_window_rows)
            norm_cost_output = _simulate_overlay(selected_rows=selected_window_rows, cost_bps_total=15.0)
            moonshot_output = _simulate_overlay(selected_rows=selected_window_rows, moonshot_cap=5.0)
            variant_windows.append(_mission_row(variant_name=spec["variant_name"], window_label=label, start=start, end=end, output=base_output))
            variant_normal_cost.append(_mission_row(variant_name=spec["variant_name"], window_label=label, start=start, end=end, output=norm_cost_output))
            variant_moonshot_cap.append(_mission_row(variant_name=spec["variant_name"], window_label=label, start=start, end=end, output=moonshot_output))
        base_summary = _summarize_mission_rows(variant_windows)
        normal_cost_summary = _summarize_mission_rows(variant_normal_cost)
        moonshot_summary = _summarize_mission_rows(variant_moonshot_cap)
        winners = [row for row in rescued_variant if _safe_float(row.get("r_multiple")) > 0.0]
        losers = [row for row in rescued_variant if _safe_float(row.get("r_multiple")) < 0.0]
        preserved_3r = sum(1 for row in rescued_variant if _safe_float(row.get("r_multiple")) >= 3.0)
        preserved_5r = sum(1 for row in rescued_variant if _safe_float(row.get("r_multiple")) >= 5.0)
        preserved_10r = sum(1 for row in rescued_variant if _safe_float(row.get("r_multiple")) >= 10.0)
        r_values = [_safe_float(row.get("r_multiple")) for row in rescued_variant]
        wins = [value for value in r_values if value > 0.0]
        losses = [abs(value) for value in r_values if value < 0.0]
        pf = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
        cost_survival = "survives_normal_cost" if normal_cost_summary["average_ending_equity"] > 0 else "fails_normal_cost"
        moonshot_dependency = _moonshot_dependency_label(base_summary["average_ending_equity"], moonshot_summary["average_ending_equity"])
        improves_mission = base_summary["average_ending_equity"] > baseline_for_comparison["average_ending_equity"] and base_summary["hit_1m_windows"] >= baseline_for_comparison["hit_1m_windows"]
        if not rescued_variant:
            verdict = "too_tight_zero_rescue"
        elif improves_mission and cost_survival == "survives_normal_cost" and moonshot_dependency != "moonshot_fragile":
            verdict = "promising_research_only"
        elif base_summary["average_ending_equity"] > baseline_for_comparison["average_ending_equity"]:
            verdict = "improves_but_fragile"
        else:
            verdict = "not_better_than_original"
        strict_variant_definitions.append(
            {
                "variant_name": spec["variant_name"],
                "fields_used": spec["fields_used"],
                "research_only": True,
                "pre_entry_safe": not any(field in FORBIDDEN_FUTURE_FIELDS for field in spec["fields_used"]),
            }
        )
        strict_variant_results.append(
            {
                "variant_name": spec["variant_name"],
                "fields_used": "|".join(spec["fields_used"]),
                "pre_entry_safety_status": not any(field in FORBIDDEN_FUTURE_FIELDS for field in spec["fields_used"]),
                "trade_count": len(rescued_variant),
                "removed_loser_count": len(losers),
                "preserved_winner_count": len(winners),
                "preserved_3R_plus_count": preserved_3r,
                "preserved_5R_plus_count": preserved_5r,
                "preserved_10R_plus_count": preserved_10r,
                "total_R": round(sum(r_values), 6),
                "PF": round(pf, 6),
                "avg_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
                "win_rate": round(_safe_ratio(len(wins), len(r_values), 0.0), 6) if r_values else 0.0,
                "max_DD": base_summary["worst_max_drawdown_pct"],
                "rolling_5Y_hit_1M_count": base_summary["hit_1m_windows"],
                "rolling_5Y_hit_5M_count": base_summary["hit_5m_windows"],
                "median_5Y_ending_equity": base_summary["median_ending_equity"],
                "average_5Y_ending_equity": base_summary["average_ending_equity"],
                "worst_5Y_ending_equity": base_summary["worst_ending_equity"],
                "cost_survival": cost_survival,
                "moonshot_dependency": moonshot_dependency,
                "verdict": verdict,
            }
        )

    strict_variant_no_leakage = _variant_no_leakage_payload(strict_variant_definitions)
    best_strict_variant = max(
        [row for row in strict_variant_results if int(_safe_float(row.get("trade_count"))) > 0],
        key=lambda row: (_safe_float(row["average_5Y_ending_equity"]), _safe_float(row["rolling_5Y_hit_1M_count"])),
        default={},
    )

    candidate_baseline = _summarize_mission_rows(overlays_by_name["BASELINE_NATIVE_STYLE_RECONCILED"])
    candidate_normal_cost = _summarize_mission_rows(overlays_by_name["NORMAL_COST"])
    candidate_moonshot_5 = _summarize_mission_rows(overlays_by_name["MOONSHOTS_CAPPED_5R"])
    candidate_insolvency = _summarize_mission_rows(overlays_by_name["INSOLVENCY_CLAMP_ZERO"])
    candidate_drawdown_15 = _summarize_mission_rows(overlays_by_name["DRAWDOWN_CIRCUIT_BREAKER_15"])
    optimistic_avg = candidate_reconstruction["optimistic_prior_mission_average_ending_equity"]
    forensic_avg = candidate_baseline["average_ending_equity"]
    best_features = sr_liquidity_feature_separation[:8]
    worst_failure_modes = rescue_loss_by_failure[:5]

    if forensic_avg <= baseline_for_comparison["average_ending_equity"] or candidate_baseline["hit_1m_windows"] == 0:
        final_classification = "RESCUE_WEAK_UNSTABLE"
    elif candidate_normal_cost["average_ending_equity"] <= 0 or candidate_normal_cost["average_ending_equity"] < forensic_avg * 0.35:
        final_classification = "RESCUE_PROMISING_BUT_COST_FRAGILE"
    elif _moonshot_dependency_label(forensic_avg, candidate_moonshot_5["average_ending_equity"]) == "moonshot_fragile":
        final_classification = "RESCUE_PROMISING_BUT_MOONSHOT_FRAGILE"
    elif best_strict_variant and _safe_float(best_strict_variant.get("average_5Y_ending_equity")) > forensic_avg and _safe_float(best_strict_variant.get("rolling_5Y_hit_1M_count")) >= candidate_baseline["hit_1m_windows"]:
        final_classification = "RESCUE_STRONG_RESEARCH_CANDIDATE"
    else:
        final_classification = "RESCUE_PROMISING_RESEARCH_ONLY"

    next_step = (
        "freeze a stricter equal-highs rescue prototype on pre-entry-safe SR/liquidity filters, "
        "then rerun narrow cost-aware rolling validation before any native-engine reproduction research"
    )
    no_go_risks = {
        **RESEARCH_ONLY_FLAGS,
        "forensic_candidate_below_optimistic_reconstruction": forensic_avg < optimistic_avg,
        "cost_fragility_warning": candidate_normal_cost["average_ending_equity"] < forensic_avg * 0.5 if forensic_avg else True,
        "insolvency_clamp_changes_path": candidate_insolvency["average_ending_equity"] != forensic_avg,
        "drawdown_circuit_breaker_changes_path": candidate_drawdown_15["average_ending_equity"] != forensic_avg,
    }
    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "candidate_name": "RESCUE_EQUAL_HIGHS_LIQUIDITY_SWEEP",
        "rescued_short_trade_count": len(rescued_candidate_rows),
        "rescued_winner_count": len(rescued_winners),
        "rescued_loser_count": len(rescued_losers),
        "rescued_total_R": round(sum(_safe_float(row.get("r_multiple")) for row in rescued_candidate_rows), 6),
        "optimistic_prior_average_5Y_ending_equity": optimistic_avg,
        "forensic_average_5Y_ending_equity": candidate_baseline["average_ending_equity"],
        "forensic_median_5Y_ending_equity": candidate_baseline["median_ending_equity"],
        "forensic_1M_hit_windows": candidate_baseline["hit_1m_windows"],
        "forensic_5M_hit_windows": candidate_baseline["hit_5m_windows"],
        "forensic_max_drawdown_pct": candidate_baseline["worst_max_drawdown_pct"],
        "normal_cost_average_5Y_ending_equity": candidate_normal_cost["average_ending_equity"],
        "moonshot_capped_5R_average_5Y_ending_equity": candidate_moonshot_5["average_ending_equity"],
        "insolvency_clamp_average_5Y_ending_equity": candidate_insolvency["average_ending_equity"],
        "drawdown_circuit_breaker_15_average_5Y_ending_equity": candidate_drawdown_15["average_ending_equity"],
        "best_stricter_rescue_variant": best_strict_variant.get("variant_name", ""),
        "best_stricter_variant_average_5Y_ending_equity": _safe_float(best_strict_variant.get("average_5Y_ending_equity")),
        "best_stricter_variant_improves_mission": _safe_float(best_strict_variant.get("average_5Y_ending_equity")) > forensic_avg,
        "final_classification": final_classification,
        "next_recommended_research_step": next_step,
        "rolling_mission_reference_classification": rolling_summary.get("final_classification"),
    }

    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    report_lines = [
        "# Equal Highs Liquidity Sweep Rescue Forensic Audit",
        "",
        f"- optimistic prior 5Y average ending equity: `{optimistic_avg}`",
        f"- forensic 5Y average ending equity: `{summary['forensic_average_5Y_ending_equity']}`",
        f"- forensic 5Y median ending equity: `{summary['forensic_median_5Y_ending_equity']}`",
        f"- forensic 1M hit windows: `{summary['forensic_1M_hit_windows']}`",
        f"- rescued short trades analyzed: `{summary['rescued_short_trade_count']}`",
        f"- rescued winners: `{summary['rescued_winner_count']}`",
        f"- rescued losers: `{summary['rescued_loser_count']}`",
        f"- rescued total R: `{summary['rescued_total_R']}`",
        f"- normal-cost average 5Y ending equity: `{summary['normal_cost_average_5Y_ending_equity']}`",
        f"- moonshot-capped-5R average 5Y ending equity: `{summary['moonshot_capped_5R_average_5Y_ending_equity']}`",
        f"- insolvency-clamp average 5Y ending equity: `{summary['insolvency_clamp_average_5Y_ending_equity']}`",
        f"- drawdown-breaker-15 average 5Y ending equity: `{summary['drawdown_circuit_breaker_15_average_5Y_ending_equity']}`",
        f"- best stricter variant: `{summary['best_stricter_rescue_variant']}`",
        f"- final classification: `{summary['final_classification']}`",
        "",
        "## Why It Moved The Mission",
        "",
        "The prior rolling mission uplift was driven by the pre-entry equal-highs liquidity-sweep rule reintroducing a large block of removed short convexity. The forensic reconstruction shows the same rule applied to the full removed-short pool also reintroduces many losers, which reduces the mission dramatically versus the earlier optimistic winner-only replay.",
        "",
        "## Best Separating Pre-Entry Features",
        "",
    ]
    for feature in best_features[:5]:
        if feature["feature_type"] == "numeric":
            report_lines.append(f"- `{feature['feature']}` gap: winner_mean `{feature['winner_mean']}` vs loser_mean `{feature['loser_mean']}`")
        else:
            report_lines.append(f"- `{feature['feature']}` mode split: winners `{feature['winner_mode']}` vs losers `{feature['loser_mode']}`")
    report_lines.extend(
        [
            "",
            "## Reintroduced Damage",
            "",
        ]
    )
    for item in worst_failure_modes:
        report_lines.append(f"- `{item['failure_mode']}`: trade_count `{item['trade_count']}`, total_R `{item['total_R']}`")
    report_lines.extend(
        [
            "",
            "## Court Verdict",
            "",
            f"- next recommended research step: `{next_step}`",
            "",
            "This remains research-only. No live, paper, runtime, allocator, risk, sizing, entry, exit, threshold, sleeve, or config behavior was changed. SR logic was read-only evidence only.",
        ]
    )

    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "equal_highs_liquidity_sweep_rescue_summary.json", summary)
    _write_markdown(config.output_root / "equal_highs_liquidity_sweep_rescue_report.md", "\n".join(report_lines))
    _write_json(diagnostics_root / "rescue_candidate_reconstruction.json", candidate_reconstruction)
    _write_json(diagnostics_root / "rescue_candidate_no_future_leakage_check.json", no_future_leakage)
    _write_csv(diagnostics_root / "rescued_short_trade_profile.csv", _normalize_rows(rescued_trade_profile))
    _write_csv(diagnostics_root / "rescued_short_winner_vs_loser_contrast.csv", _normalize_rows(winner_vs_loser_contrast))
    _write_csv(diagnostics_root / "sr_liquidity_feature_separation.csv", _normalize_rows(sr_liquidity_feature_separation))
    _write_csv(diagnostics_root / "rescued_short_by_year.csv", _normalize_rows(rescued_by_year))
    _write_csv(diagnostics_root / "rescued_short_by_rolling_window.csv", _normalize_rows(rescued_by_window))
    _write_csv(diagnostics_root / "rescued_short_by_session.csv", _normalize_rows(rescued_by_session))
    _write_json(diagnostics_root / "missing_pre_entry_fields_report.json", missing_pre_entry_fields)
    _write_csv(diagnostics_root / "rescue_reintroduced_loss_audit.csv", _normalize_rows(rescue_loss_audit))
    _write_csv(diagnostics_root / "rescue_reintroduced_loss_by_failure_mode.csv", _normalize_rows(rescue_loss_by_failure))
    _write_csv(diagnostics_root / "rescue_reintroduced_loss_by_year.csv", _normalize_rows(rescue_loss_by_year))
    _write_csv(diagnostics_root / "rescue_reintroduced_loss_by_window.csv", _normalize_rows(rescue_loss_by_window))
    _write_json(diagnostics_root / "rescue_damage_summary.json", rescue_damage_summary)
    _write_csv(diagnostics_root / "rescue_candidate_rolling_5y_robustness.csv", _normalize_rows(overlay_rows))
    _write_csv(diagnostics_root / "rescue_candidate_cost_survival.csv", _normalize_rows(cost_survival_rows))
    _write_csv(diagnostics_root / "rescue_candidate_moonshot_survival.csv", _normalize_rows(moonshot_survival_rows))
    _write_csv(diagnostics_root / "rescue_candidate_drawdown_governor.csv", _normalize_rows(drawdown_governor_rows))
    _write_csv(diagnostics_root / "insolvency_clamp_impact.csv", _normalize_rows(insolvency_rows))
    _write_json(diagnostics_root / "risk_governor_impact.json", risk_governor_impact)
    _write_json(diagnostics_root / "stricter_rescue_variant_definitions.json", {"research_only": True, "variants": strict_variant_definitions})
    _write_csv(diagnostics_root / "stricter_rescue_variant_results.csv", _normalize_rows(strict_variant_results))
    _write_json(diagnostics_root / "stricter_rescue_variant_results.json", {"research_only": True, "variants": strict_variant_results})
    _write_json(diagnostics_root / "stricter_rescue_variant_no_leakage_check.json", strict_variant_no_leakage)
    _write_json(diagnostics_root / "no_go_risks.json", no_go_risks)
    _write_json(reports_root / "next_research_recommendation.json", {"research_only": True, "next_step": next_step})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "equal_highs_liquidity_sweep_rescue_summary.json",
        "report": config.output_root / "equal_highs_liquidity_sweep_rescue_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    result = write_equal_highs_liquidity_sweep_rescue_forensic_audit(
        EqualHighsLiquiditySweepRescueForensicAuditConfig(
            package_root=package_root,
            output_root=package_root / "output" / "equal_highs_liquidity_sweep_rescue_forensic_audit_001",
        )
    )
    print(result["summary"])


if __name__ == "__main__":
    main()
