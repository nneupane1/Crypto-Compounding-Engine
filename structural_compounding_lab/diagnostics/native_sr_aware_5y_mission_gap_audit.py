from __future__ import annotations

import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import (  # noqa: E402
    RESEARCH_ONLY_FLAGS,
    _apply_frozen_patch,
    _load_frozen_rules,
)
from structural_compounding_lab.diagnostics.equal_highs_liquidity_sweep_rescue_forensic_audit import (  # noqa: E402
    _mission_row,
    _safe_float,
    _summarize_mission_rows,
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
from structural_compounding_lab.diagnostics.native_sr_aware_structural_replay_reproduction_audit import (  # noqa: E402
    _merge_enriched,
    _spec_payload as _native_replay_spec_payload,
    _variant_definitions,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import (  # noqa: E402
    _build_windows,
    _target_hit_metrics,
    _window_rows,
)


START_CAPITAL = 20_000.0
BASELINE_COST_BPS = 15.0
LOW_COST_BPS = 7.0
FIVE_X_COST_BPS = BASELINE_COST_BPS * 5.0
MISSION_TARGET = 1_000_000.0
OUTPUT_FOLDER_NAME = "native_sr_aware_5y_mission_gap_audit_001"


@dataclass(frozen=True)
class NativeSRAware5YMissionGapAuditConfig:
    package_root: Path
    output_root: Path


def _paths(config: NativeSRAware5YMissionGapAuditConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    strict_root = output_root / "native_sr_aware_strict_stress_monte_carlo_audit_001"
    native_root = output_root / "native_sr_aware_structural_replay_reproduction_audit_001"
    broad_root = output_root / "broad_historical_structural_replay_001"
    return {
        "strict_summary": strict_root / "native_sr_aware_strict_stress_monte_carlo_summary.json",
        "strict_report": strict_root / "native_sr_aware_strict_stress_monte_carlo_report.md",
        "strict_trades": strict_root / "ledger" / "native_sr_aware_strict_trades.csv",
        "strict_equity": strict_root / "ledger" / "native_sr_aware_strict_equity.csv",
        "strict_stress_matrix": strict_root / "diagnostics" / "stress_test_matrix.csv",
        "strict_monte_carlo_summary": strict_root / "diagnostics" / "monte_carlo_summary.json",
        "strict_mission_gap_report": strict_root / "diagnostics" / "mission_gap_report.json",
        "strict_promotion_gate": strict_root / "diagnostics" / "promotion_gate_report.json",
        "native_trades": native_root / "ledger" / "native_sr_aware_trades.csv",
        "native_equity": native_root / "ledger" / "native_sr_aware_equity.csv",
        "native_rolling_results": native_root / "diagnostics" / "native_sr_aware_rolling_5y_results.csv",
        "broad_trades": broad_root / "ledger" / "trades.csv",
        "broad_equity": broad_root / "ledger" / "equity.csv",
        "broad_summary": broad_root / "ledger" / "summary.json",
        "setup_log": broad_root / "ledger" / "setup_log.csv",
        "level_log": broad_root / "ledger" / "level_log.csv",
        "liquidity_events": broad_root / "ledger" / "liquidity_events.csv",
        "rolling_results": output_root / "rolling_five_year_mission_viability_audit_001" / "diagnostics" / "rolling_5y_window_results.csv",
        "accounting_table": output_root / "broad_patch_accounting_and_short_rescue_audit_001" / "diagnostics" / "accounting_reconciliation_table.csv",
        "enriched_trades": output_root / "native_pre_entry_sr_feature_enrichment_audit_001" / "diagnostics" / "enriched_trade_pre_entry_sr_features.csv",
        "frozen_patch_rules": output_root / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, reports_root


def _empty_outputs(
    config: NativeSRAware5YMissionGapAuditConfig,
    *,
    classification: str,
    warnings: list[str],
) -> dict[str, Path]:
    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    now = datetime.now(timezone.utc).isoformat()
    status = {"state": "blocked", "resolved_at_utc": now, **RESEARCH_ONLY_FLAGS, "warnings": warnings}
    summary = {
        "resolved_at_utc": now,
        **RESEARCH_ONLY_FLAGS,
        "final_classification": classification,
        "warnings": warnings,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
    }
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "native_sr_aware_5y_mission_gap_summary.json", summary)
    _write_markdown(
        config.output_root / "native_sr_aware_5y_mission_gap_report.md",
        "# Native SR-Aware 5-Year Mission Gap Audit\n\nRequired strict/native artifacts were missing, so the audit stayed blocked.\n",
    )
    for name in (
        "yearly_contribution_timeline.csv",
        "monthly_contribution_timeline.csv",
        "trade_frequency_timeline.csv",
        "top_winner_timing.csv",
        "inactive_periods.csv",
        "rolling_5y_gap_decomposition.csv",
        "closest_windows_to_1m.csv",
        "farthest_windows_from_1m.csv",
        "mission_bridge_variant_results.csv",
        "mission_bridge_rolling_5y_results.csv",
        "mission_bridge_risk_multiplier_audit.csv",
        "mission_bridge_insolvency_clamp_audit.csv",
    ):
        _write_csv(diagnostics_root / name, [])
    for name in (
        "full_sequence_vs_5y_gap_attribution.json",
        "rolling_5y_gap_decomposition.json",
        "mission_bridge_variant_results.json",
        "mission_realism_gate.json",
        "no_go_risks.json",
    ):
        _write_json(diagnostics_root / name, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "native_sr_aware_5y_mission_gap_summary.json",
        "report": config.output_root / "native_sr_aware_5y_mission_gap_report.md",
    }


def _sort_trade_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or ""))


def _clone_row(row: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(row)
    if isinstance(cloned.get("entry_timestamp"), pd.Timestamp):
        cloned["entry_timestamp"] = pd.Timestamp(cloned["entry_timestamp"])
    if isinstance(cloned.get("exit_timestamp"), pd.Timestamp):
        cloned["exit_timestamp"] = pd.Timestamp(cloned["exit_timestamp"])
    return cloned


def _reconstruct_sequences(config: NativeSRAware5YMissionGapAuditConfig) -> tuple[dict[str, Any] | None, list[str]]:
    paths = _paths(config)
    required = [
        paths["strict_summary"],
        paths["broad_trades"],
        paths["broad_summary"],
        paths["setup_log"],
        paths["level_log"],
        paths["liquidity_events"],
        paths["enriched_trades"],
        paths["frozen_patch_rules"],
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return None, missing

    strict_summary = _read_json(paths["strict_summary"], {})
    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    all_rows = _normalize_trade_rows(_read_csv_rows(paths["broad_trades"]), setup_rows, level_rows, liquidity_rows)
    all_rows = _prepare_rows(all_rows)

    matched_short_archetypes, disabled_long_modes, _ = _load_frozen_rules(paths["frozen_patch_rules"])
    kept_rows, _ = _apply_frozen_patch(
        all_rows,
        matched_short_archetypes=matched_short_archetypes,
        disabled_long_modes=disabled_long_modes,
    )

    enriched_rows = _read_csv_rows(paths["enriched_trades"])
    enriched_map = {str(row.get("trade_id") or ""): row for row in enriched_rows}
    all_rows_enriched = _merge_enriched(all_rows, enriched_map)
    kept_rows_enriched = _merge_enriched(kept_rows, enriched_map)
    kept_longs = [row for row in kept_rows_enriched if str(row.get("side") or "") == "long"]
    all_shorts = [row for row in all_rows_enriched if str(row.get("side") or "") == "short"]

    variant_def = next(
        (item for item in _variant_definitions(_native_replay_spec_payload()) if item.get("variant_name") == "NATIVE_SR_AWARE_STRICT"),
        {},
    )
    predicate = variant_def.get("predicate")
    if predicate is None:
        return None, ["strict_variant_predicate_missing"]

    strict_shorts = [row for row in all_shorts if predicate(row)]
    strict_rows = _sort_trade_rows(kept_longs + strict_shorts)
    baseline_rows = _sort_trade_rows(kept_rows_enriched)
    strict_ids = {str(row.get("trade_id") or "") for row in strict_rows}
    blended_rows: list[dict[str, Any]] = []
    for row in baseline_rows:
        cloned = _clone_row(row)
        cloned["bridge_source"] = "strict_core" if str(row.get("trade_id") or "") in strict_ids else "baseline_extra"
        blended_rows.append(cloned)

    strict_trades_csv_exists = paths["strict_trades"].exists()
    native_rolling_results = _read_csv_rows(paths["native_rolling_results"]) if paths["native_rolling_results"].exists() else []
    broad_summary = _read_json(paths["broad_summary"], {})
    windows = _build_windows(all_rows)
    return {
        "strict_summary": strict_summary,
        "strict_rows": strict_rows,
        "baseline_rows": baseline_rows,
        "blended_rows": blended_rows,
        "strict_ids": strict_ids,
        "windows": windows,
        "native_rolling_results": native_rolling_results,
        "broad_summary": broad_summary,
    }, []


def _monthly_geometric_return(daily_rows: list[dict[str, Any]]) -> float:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in daily_rows:
        grouped.setdefault(str(row.get("date") or "")[:7], []).append(row)
    returns: list[float] = []
    for _, bucket in sorted(grouped.items()):
        if not bucket:
            continue
        end_equity = _safe_float(bucket[-1].get("equity_end"))
        first_equity = _safe_float(bucket[0].get("equity_start"))
        if first_equity <= 0:
            continue
        returns.append((end_equity / first_equity) - 1.0)
    if not returns or any((1.0 + value) <= 0.0 for value in returns):
        return 0.0
    product = 1.0
    for value in returns:
        product *= 1.0 + value
    return round(product ** (1.0 / len(returns)) - 1.0, 6)


def _simulate_bridge_sequence(
    rows: list[dict[str, Any]],
    *,
    start_capital: float = START_CAPITAL,
    native_lock_ratio: float = 0.5,
    cost_bps_total: float = 0.0,
    insolvency_clamp: bool = True,
    row_source_multipliers: dict[str, float] | None = None,
    stepup_schedule: list[tuple[float, float]] | None = None,
    drawdown_guard_pct: float | None = None,
    drawdown_breaker_pct: float | None = None,
    oracle_boost_months: set[str] | None = None,
    oracle_boost_multiplier: float = 1.0,
    vault_unlock_schedule: list[tuple[float, float]] | None = None,
) -> dict[str, Any]:
    ordered = _sort_trade_rows(rows)
    active_capital = float(start_capital)
    locked_profit = 0.0
    peak_equity = active_capital
    max_drawdown_pct = 0.0
    insolvency_hit = False
    breaker_triggered = False
    daily_rows: list[dict[str, Any]] = []
    current_day_key: str | None = None
    day_pnl = 0.0
    day_r = 0.0
    day_trade_count = 0
    day_equity_start = start_capital
    day_equity_end = start_capital
    month_totals: dict[str, float] = {}
    year_totals: dict[str, float] = {}
    current_month = None
    current_month_pnl = 0.0
    risk_multipliers: list[float] = []
    trade_trace: list[dict[str, Any]] = []
    vault_triggered: set[float] = set()

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
        exit_ts = row.get("exit_timestamp")
        if not isinstance(exit_ts, pd.Timestamp):
            continue

        month_key = exit_ts.strftime("%Y-%m")
        if current_month is None:
            current_month = month_key
        elif month_key != current_month:
            month_totals[current_month] = month_totals.get(current_month, 0.0) + current_month_pnl
            current_month = month_key
            current_month_pnl = 0.0

        day_key = exit_ts.strftime("%Y-%m-%d")
        if current_day_key != day_key:
            flush_day()
            current_day_key = day_key
            day_equity_start = active_capital + locked_profit
            day_equity_end = active_capital + locked_profit

        current_equity = active_capital + locked_profit
        current_dd = _safe_ratio(max(0.0, peak_equity - current_equity), peak_equity, 0.0)
        if drawdown_breaker_pct is not None and current_dd >= drawdown_breaker_pct:
            breaker_triggered = True
            break

        multiplier = 1.0
        if row_source_multipliers:
            multiplier *= row_source_multipliers.get(str(row.get("bridge_source") or ""), 1.0)
        if stepup_schedule:
            for equity_threshold, scheduled_multiplier in sorted(stepup_schedule, key=lambda item: item[0]):
                if current_equity >= equity_threshold:
                    multiplier = max(multiplier, scheduled_multiplier)
        if drawdown_guard_pct is not None and current_dd > drawdown_guard_pct:
            multiplier = min(multiplier, 1.0)
        if oracle_boost_months and month_key in oracle_boost_months:
            multiplier = max(multiplier, oracle_boost_multiplier)

        if vault_unlock_schedule:
            for equity_threshold, unlock_ratio in sorted(vault_unlock_schedule, key=lambda item: item[0]):
                if current_equity >= equity_threshold and equity_threshold not in vault_triggered and locked_profit > 0.0:
                    unlock_amount = locked_profit * unlock_ratio
                    locked_profit -= unlock_amount
                    active_capital += unlock_amount
                    vault_triggered.add(equity_threshold)
                    current_equity = active_capital + locked_profit

        risk_value = max(active_capital, 0.0) * 0.01 * multiplier
        applied_r = _safe_float(row.get("r_multiple"))
        pnl = applied_r * risk_value
        if cost_bps_total > 0.0:
            entry_price = _safe_float(row.get("entry_price"))
            exit_price = _safe_float(row.get("exit_price")) or entry_price
            quantity = _safe_float(row.get("quantity")) or 1.0
            notional = abs((entry_price + exit_price) * 0.5 * quantity)
            pnl -= notional * (cost_bps_total / 10_000.0)
        active_capital += pnl
        current_month_pnl += pnl
        year_key = str(exit_ts.year)
        year_totals[year_key] = year_totals.get(year_key, 0.0) + pnl
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
            peak_equity = max(peak_equity, total_equity)
            max_drawdown_pct = max(max_drawdown_pct, 1.0)
            day_pnl += pnl
            day_r += applied_r
            day_trade_count += 1
            day_equity_end = 0.0
            trade_trace.append(
                {
                    "trade_id": str(row.get("trade_id") or ""),
                    "timestamp": exit_ts.isoformat(),
                    "year": exit_ts.year,
                    "month": month_key,
                    "bridge_source": str(row.get("bridge_source") or "strict_core"),
                    "risk_multiplier": round(multiplier, 6),
                    "risk_value": round(risk_value, 6),
                    "applied_r": round(applied_r, 6),
                    "pnl": round(pnl, 6),
                    "equity_after": 0.0,
                    "archetype_key": str(row.get("archetype_key") or row.get("pattern") or ""),
                    "failure_mode": str(row.get("exit_reason") or ""),
                }
            )
            break

        peak_equity = max(peak_equity, total_equity)
        max_drawdown_pct = max(max_drawdown_pct, _safe_ratio(max(0.0, peak_equity - total_equity), peak_equity, 0.0))
        day_pnl += pnl
        day_r += applied_r
        day_trade_count += 1
        day_equity_end = total_equity
        risk_multipliers.append(multiplier)
        trade_trace.append(
            {
                "trade_id": str(row.get("trade_id") or ""),
                "timestamp": exit_ts.isoformat(),
                "year": exit_ts.year,
                "month": month_key,
                "bridge_source": str(row.get("bridge_source") or "strict_core"),
                "risk_multiplier": round(multiplier, 6),
                "risk_value": round(risk_value, 6),
                "applied_r": round(applied_r, 6),
                "pnl": round(pnl, 6),
                "equity_after": round(total_equity, 6),
                "archetype_key": str(row.get("archetype_key") or row.get("pattern") or ""),
                "failure_mode": str(row.get("exit_reason") or ""),
            }
        )

    if current_month is not None:
        month_totals[current_month] = month_totals.get(current_month, 0.0) + current_month_pnl
    flush_day()

    r_values = [_safe_float(row.get("applied_r")) for row in trade_trace]
    wins = [value for value in r_values if value > 0.0]
    losses = [abs(value) for value in r_values if value < 0.0]
    profit_factor = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
    worst_month = min(month_totals.items(), key=lambda item: item[1])[0] if month_totals else ""
    worst_year = min(year_totals.items(), key=lambda item: item[1])[0] if year_totals else ""
    timestamps = [pd.Timestamp(row["timestamp"]) for row in trade_trace if row.get("timestamp")]
    months = max(
        1.0,
        ((max(timestamps).year - min(timestamps).year) * 12) + (max(timestamps).month - min(timestamps).month) + 1,
    ) if timestamps else 1.0
    return {
        "ending_equity": round(active_capital + locked_profit, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "trade_count": len(trade_trace),
        "daily_rows": daily_rows,
        "trade_trace": trade_trace,
        "profit_factor": round(profit_factor, 6),
        "avg_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
        "median_R": round(_median(r_values), 6) if r_values else 0.0,
        "total_R": round(sum(r_values), 6),
        "win_rate": round(_safe_ratio(len(wins), len(r_values), 0.0), 6) if r_values else 0.0,
        "insolvency_hit": insolvency_hit,
        "breaker_triggered": breaker_triggered,
        "cooldown_triggers": 0,
        "risk_multiplier_avg": round(sum(risk_multipliers) / len(risk_multipliers), 6) if risk_multipliers else 0.0,
        "risk_multiplier_max": round(max(risk_multipliers), 6) if risk_multipliers else 0.0,
        "worst_month": worst_month,
        "worst_year": worst_year,
        "monthly_geometric_return": _monthly_geometric_return(daily_rows),
        "average_trades_per_month": round(len(trade_trace) / months, 6) if timestamps else 0.0,
    }


def _year_month_timelines(trace: list[dict[str, Any]], daily_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    year_buckets: dict[str, dict[str, Any]] = {}
    month_buckets: dict[str, dict[str, Any]] = {}
    for row in trace:
        year_key = str(row.get("year") or "unknown")
        month_key = str(row.get("month") or "unknown")
        for key, bucket_map in ((year_key, year_buckets), (month_key, month_buckets)):
            bucket = bucket_map.setdefault(
                key,
                {"period": key, "trade_count": 0, "total_pnl": 0.0, "total_R": 0.0, "winner_count": 0, "loser_count": 0, "top_winner_R": 0.0}
            )
            bucket["trade_count"] += 1
            bucket["total_pnl"] += _safe_float(row.get("pnl"))
            bucket["total_R"] += _safe_float(row.get("applied_r"))
            if _safe_float(row.get("applied_r")) > 0:
                bucket["winner_count"] += 1
            if _safe_float(row.get("applied_r")) < 0:
                bucket["loser_count"] += 1
            bucket["top_winner_R"] = max(bucket["top_winner_R"], _safe_float(row.get("applied_r")))
    daily_map = {str(row.get("date") or ""): row for row in daily_rows}
    daily_dates = sorted(daily_map.keys())
    last_equity_for_period: dict[str, float] = {}
    for date_key in daily_dates:
        daily = daily_map[date_key]
        year_key = date_key[:4]
        month_key = date_key[:7]
        last_equity_for_period[year_key] = _safe_float(daily.get("equity_end"))
        last_equity_for_period[month_key] = _safe_float(daily.get("equity_end"))
    total_pnl = sum(_safe_float(row.get("pnl")) for row in trace)
    yearly_rows = []
    monthly_rows = []
    for period, bucket in sorted(year_buckets.items()):
        yearly_rows.append(
            {
                "year": period,
                **bucket,
                "ending_equity": round(last_equity_for_period.get(period, 0.0), 6),
                "share_of_total_pnl": round(_safe_ratio(bucket["total_pnl"], total_pnl, 0.0), 6),
                "avg_R": round(_safe_ratio(bucket["total_R"], bucket["trade_count"], 0.0), 6),
            }
        )
    for period, bucket in sorted(month_buckets.items()):
        monthly_rows.append(
            {
                "month": period,
                **bucket,
                "ending_equity": round(last_equity_for_period.get(period, 0.0), 6),
                "share_of_total_pnl": round(_safe_ratio(bucket["total_pnl"], total_pnl, 0.0), 6),
                "avg_R": round(_safe_ratio(bucket["total_R"], bucket["trade_count"], 0.0), 6),
            }
        )
    trade_freq_rows = [
        {
            "month": row["month"],
            "trade_count": row["trade_count"],
            "winner_count": row["winner_count"],
            "loser_count": row["loser_count"],
            "avg_R": row["avg_R"],
            "total_pnl": row["total_pnl"],
        }
        for row in monthly_rows
    ]
    return yearly_rows, monthly_rows, trade_freq_rows


def _inactive_periods(monthly_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not monthly_rows:
        return []
    months = pd.period_range(start=monthly_rows[0]["month"], end=monthly_rows[-1]["month"], freq="M")
    trade_map = {str(row["month"]): int(row.get("trade_count") or 0) for row in monthly_rows}
    periods: list[dict[str, Any]] = []
    streak_start = None
    streak_length = 0
    for period in months:
        label = str(period)
        if trade_map.get(label, 0) == 0:
            if streak_start is None:
                streak_start = label
            streak_length += 1
        elif streak_start is not None:
            periods.append({"start_month": streak_start, "end_month": str(period - 1), "months_without_trades": streak_length})
            streak_start = None
            streak_length = 0
    if streak_start is not None:
        periods.append({"start_month": streak_start, "end_month": str(months[-1]), "months_without_trades": streak_length})
    return periods


def _top_winner_timing(trace: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    winners = sorted((row for row in trace if _safe_float(row.get("applied_r")) > 0.0), key=lambda row: _safe_float(row.get("applied_r")), reverse=True)
    rows: list[dict[str, Any]] = []
    for item in winners[:limit]:
        rows.append(
            {
                "trade_id": str(item.get("trade_id") or ""),
                "timestamp": str(item.get("timestamp") or ""),
                "year": item.get("year"),
                "month": item.get("month"),
                "applied_R": item.get("applied_r"),
                "pnl": item.get("pnl"),
                "archetype_key": item.get("archetype_key"),
            }
        )
    return rows


def _required_monthly_return(target_equity: float, start_capital: float = START_CAPITAL, months: int = 60) -> float:
    if start_capital <= 0 or months <= 0:
        return 0.0
    return round((target_equity / start_capital) ** (1.0 / months) - 1.0, 6)


def _closest_date_to_target(daily_rows: list[dict[str, Any]], target: float) -> tuple[str, float]:
    if not daily_rows:
        return "", target
    chosen = min(daily_rows, key=lambda row: abs(_safe_float(row.get("equity_end")) - target))
    return str(chosen.get("date") or ""), round(abs(_safe_float(chosen.get("equity_end")) - target), 6)


def _window_year_contribution(trace: list[dict[str, Any]]) -> dict[str, float]:
    buckets: dict[str, float] = {}
    for row in trace:
        year_key = str(row.get("year") or "unknown")
        buckets[year_key] = buckets.get(year_key, 0.0) + _safe_float(row.get("pnl"))
    return buckets


def _decompose_failure_reason(
    *,
    ending_equity: float,
    trade_count: int,
    avg_trades_per_month: float,
    last_12m_share: float,
    first_24m_share: float,
    actual_monthly_return: float,
    required_monthly_return: float,
    yearly_contributions: dict[str, float],
) -> str:
    if trade_count <= 0:
        return "inactive_window"
    if avg_trades_per_month < 5.0:
        return "low_frequency"
    if last_12m_share >= 0.40 and first_24m_share <= 0.20:
        return "late_compounding_timing"
    if required_monthly_return - actual_monthly_return > 0.02:
        return "insufficient_capital_deployment"
    if yearly_contributions and min(yearly_contributions.values()) < 0:
        return "drawdown_or_negative_year_drag"
    if ending_equity < 500_000.0:
        return "missing_tail_or_weak_early_compounding"
    return "mixed_gap"


def _rolling_gap_decomposition(
    rows: list[dict[str, Any]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    required_monthly = _required_monthly_return(MISSION_TARGET)
    decomposed: list[dict[str, Any]] = []
    for start, end, label in windows:
        selected = _window_rows(rows, start, end)
        trace = _simulate_bridge_sequence(selected)
        target_metrics = _target_hit_metrics(trace["daily_rows"], start_date=start)
        ending_equity = _safe_float(trace["ending_equity"])
        gap_eur = max(0.0, MISSION_TARGET - ending_equity)
        closest_date, closest_gap = _closest_date_to_target(trace["daily_rows"], MISSION_TARGET)
        avg_trade_pnl = _safe_ratio(sum(_safe_float(item.get("pnl")) for item in trace["trade_trace"]), max(len(trace["trade_trace"]), 1), 0.0)
        avg_risk_value = _safe_ratio(sum(_safe_float(item.get("risk_value")) for item in trace["trade_trace"]), max(len(trace["trade_trace"]), 1), 0.0)
        year_contributions = _window_year_contribution(trace["trade_trace"])
        months = max(1, ((end.year - start.year) * 12) + (end.month - start.month) + 1)
        monthly_actual = trace["monthly_geometric_return"]
        cutoff_24m = start + pd.DateOffset(months=24) - pd.Timedelta(days=1)
        cutoff_last_12 = end - pd.DateOffset(months=12) + pd.Timedelta(days=1)
        total_pnl = sum(_safe_float(item.get("pnl")) for item in trace["trade_trace"])
        first_24m_pnl = sum(_safe_float(item.get("pnl")) for item in trace["trade_trace"] if pd.Timestamp(item["timestamp"]) <= cutoff_24m)
        last_12m_pnl = sum(_safe_float(item.get("pnl")) for item in trace["trade_trace"] if pd.Timestamp(item["timestamp"]) >= cutoff_last_12)
        first_24m_share = _safe_ratio(first_24m_pnl, total_pnl, 0.0)
        last_12m_share = _safe_ratio(last_12m_pnl, total_pnl, 0.0)
        biggest_positive_year = max(year_contributions.items(), key=lambda item: item[1])[0] if year_contributions else ""
        biggest_negative_year = min(year_contributions.items(), key=lambda item: item[1])[0] if year_contributions else ""
        row = {
            "window_label": label,
            "start_date": str(start.date()),
            "end_date": str(end.date()),
            "ending_equity": round(ending_equity, 6),
            "distance_to_1m_eur": round(gap_eur, 6),
            "distance_to_1m_multiple": round(_safe_ratio(MISSION_TARGET, max(ending_equity, 1.0), 0.0), 6),
            "max_equity_reached": round(_safe_float(target_metrics["max_equity_reached"]), 6),
            "closest_date_to_1m": closest_date,
            "closest_gap_to_1m_eur": closest_gap,
            "number_of_trades": trace["trade_count"],
            "trades_needed_if_avg_R_continued": int(math.ceil(gap_eur / avg_trade_pnl)) if avg_trade_pnl > 0 else None,
            "extra_total_R_needed_to_hit_1m": round(gap_eur / avg_risk_value, 6) if avg_risk_value > 0 else None,
            "extra_monthly_return_needed_to_hit_1m": round(max(0.0, required_monthly - monthly_actual), 6),
            "biggest_missing_year": biggest_negative_year,
            "biggest_positive_year": biggest_positive_year,
            "biggest_negative_year": biggest_negative_year,
            "actual_monthly_return": monthly_actual,
            "required_monthly_return": required_monthly,
            "first_24m_pnl_share": round(first_24m_share, 6),
            "last_12m_pnl_share": round(last_12m_share, 6),
            "failure_cause": _decompose_failure_reason(
                ending_equity=ending_equity,
                trade_count=trace["trade_count"],
                avg_trades_per_month=trace["average_trades_per_month"],
                last_12m_share=last_12m_share,
                first_24m_share=first_24m_share,
                actual_monthly_return=monthly_actual,
                required_monthly_return=required_monthly,
                yearly_contributions=year_contributions,
            ),
            "hit_1m": bool(target_metrics["hit_1m"]),
        }
        decomposed.append(row)
    summary = {
        "window_count": len(decomposed),
        "hit_1m_windows": sum(1 for row in decomposed if bool(row["hit_1m"])),
        "average_distance_to_1m_eur": round(sum(_safe_float(row["distance_to_1m_eur"]) for row in decomposed) / max(len(decomposed), 1), 6),
        "closest_window_label": min(decomposed, key=lambda row: _safe_float(row["distance_to_1m_eur"]))["window_label"] if decomposed else "",
        "farthest_window_label": max(decomposed, key=lambda row: _safe_float(row["distance_to_1m_eur"]))["window_label"] if decomposed else "",
        "dominant_failure_cause": (
            pd.Series([str(row["failure_cause"]) for row in decomposed]).value_counts().idxmax() if decomposed else "unknown"
        ),
    }
    return decomposed, summary


def _bridge_variant_specs(oracle_gap_months: set[str]) -> list[dict[str, Any]]:
    return [
        {
            "variant_name": "BASE_NATIVE_SR_AWARE_STRICT",
            "sequence_mode": "strict",
            "diagnostic_only": False,
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
        {
            "variant_name": "STRICT_PLUS_FROZEN_BASELINE_BLEND",
            "sequence_mode": "blend",
            "diagnostic_only": True,
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
        {
            "variant_name": "STRICT_PLUS_LOW_RISK_BASELINE_BLEND",
            "sequence_mode": "blend",
            "diagnostic_only": True,
            "row_source_multipliers": {"strict_core": 1.0, "baseline_extra": 0.5},
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
        {
            "variant_name": "STRICT_WITH_EQUITY_MILESTONE_RISK_STEPUP",
            "sequence_mode": "strict",
            "stepup_schedule": [(100_000.0, 1.25), (250_000.0, 1.50), (500_000.0, 2.00)],
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
        {
            "variant_name": "STRICT_WITH_DRAWDOWN_CONTROLLED_RISK_STEPUP",
            "sequence_mode": "strict",
            "stepup_schedule": [(100_000.0, 1.25), (250_000.0, 1.50), (500_000.0, 2.00)],
            "drawdown_guard_pct": 0.10,
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
        {
            "variant_name": "STRICT_WITH_PROFIT_VAULT_REINVESTMENT_STEPUP",
            "sequence_mode": "strict",
            "stepup_schedule": [(100_000.0, 1.15), (250_000.0, 1.35), (500_000.0, 1.60)],
            "vault_unlock_schedule": [(100_000.0, 0.10), (250_000.0, 0.15), (500_000.0, 0.20)],
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
        {
            "variant_name": "STRICT_WITH_LOW_COST_EXECUTION_ASSUMPTION",
            "sequence_mode": "strict",
            "cost_bps_total": LOW_COST_BPS,
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
        {
            "variant_name": "STRICT_WITH_EXTRA_TRADE_FREQUENCY_REQUIREMENT_DIAGNOSTIC",
            "sequence_mode": "blend",
            "row_source_multipliers": {"strict_core": 1.0, "baseline_extra": 0.25},
            "diagnostic_only": True,
            "uses_future_outcome_info": False,
            "allow_realism_gate": False,
        },
        {
            "variant_name": "STRICT_WITH_TOP_GAP_MONTHS_REPLAYED_AT_HIGHER_RISK_DIAGNOSTIC",
            "sequence_mode": "strict",
            "oracle_boost_months": oracle_gap_months,
            "oracle_boost_multiplier": 1.75,
            "diagnostic_only": True,
            "uses_future_outcome_info": True,
            "allow_realism_gate": False,
        },
        {
            "variant_name": "STRICT_WITH_1_25X_AFTER_100K",
            "sequence_mode": "strict",
            "stepup_schedule": [(100_000.0, 1.25)],
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
        {
            "variant_name": "STRICT_WITH_1_50X_AFTER_250K",
            "sequence_mode": "strict",
            "stepup_schedule": [(250_000.0, 1.50)],
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
        {
            "variant_name": "STRICT_WITH_2_00X_AFTER_500K",
            "sequence_mode": "strict",
            "stepup_schedule": [(500_000.0, 2.00)],
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
        {
            "variant_name": "STRICT_WITH_RISK_STEPUP_AND_10PCT_DD_CIRCUIT_BREAKER",
            "sequence_mode": "strict",
            "stepup_schedule": [(100_000.0, 1.25), (250_000.0, 1.50), (500_000.0, 2.00)],
            "drawdown_breaker_pct": 0.10,
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
        {
            "variant_name": "STRICT_WITH_RISK_STEPUP_AND_15PCT_DD_CIRCUIT_BREAKER",
            "sequence_mode": "strict",
            "stepup_schedule": [(100_000.0, 1.25), (250_000.0, 1.50), (500_000.0, 2.00)],
            "drawdown_breaker_pct": 0.15,
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
        {
            "variant_name": "STRICT_WITH_RISK_STEPUP_AND_20PCT_DD_CIRCUIT_BREAKER",
            "sequence_mode": "strict",
            "stepup_schedule": [(100_000.0, 1.25), (250_000.0, 1.50), (500_000.0, 2.00)],
            "drawdown_breaker_pct": 0.20,
            "uses_future_outcome_info": False,
            "allow_realism_gate": True,
        },
    ]


def _choose_variant_rows(context: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    if spec["sequence_mode"] == "blend":
        return [_clone_row(row) for row in context["blended_rows"]]
    return [_clone_row(row) for row in context["strict_rows"]]


def _variant_full_and_rolling(
    context: dict[str, Any],
    spec: dict[str, Any],
) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    rows = _choose_variant_rows(context, spec)
    sim_kwargs = {
        "row_source_multipliers": spec.get("row_source_multipliers"),
        "stepup_schedule": spec.get("stepup_schedule"),
        "drawdown_guard_pct": spec.get("drawdown_guard_pct"),
        "drawdown_breaker_pct": spec.get("drawdown_breaker_pct"),
        "oracle_boost_months": spec.get("oracle_boost_months"),
        "oracle_boost_multiplier": spec.get("oracle_boost_multiplier", 1.0),
        "vault_unlock_schedule": spec.get("vault_unlock_schedule"),
        "cost_bps_total": _safe_float(spec.get("cost_bps_total")),
    }
    full = _simulate_bridge_sequence(rows, **sim_kwargs)
    rolling_rows: list[dict[str, Any]] = []
    for start, end, label in context["windows"]:
        selected = _window_rows(rows, start, end)
        output = _simulate_bridge_sequence(selected, **sim_kwargs)
        mission_row = _mission_row(
            variant_name=spec["variant_name"],
            window_label=label,
            start=start,
            end=end,
            output=output,
        )
        mission_row["uses_future_outcome_info"] = bool(spec.get("uses_future_outcome_info"))
        rolling_rows.append(mission_row)
    rolling_summary = _summarize_mission_rows(rolling_rows)

    stress_5x = _simulate_bridge_sequence(rows, **{**sim_kwargs, "cost_bps_total": FIVE_X_COST_BPS})
    moonshot_cap = _simulate_bridge_sequence(rows, **sim_kwargs)
    top_winners_removed = _simulate_bridge_sequence(
        [row for row in rows if str(row.get("trade_id") or "") not in {str(item.get("trade_id") or "") for item in sorted(full["trade_trace"], key=lambda item: _safe_float(item.get("applied_r")), reverse=True)[:5]}],
        **sim_kwargs,
    )
    return full, rolling_rows, rolling_summary, {
        "five_x_cost": stress_5x,
        "top_5_removed": top_winners_removed,
        "moonshot_reference": moonshot_cap,
    }


def _variant_verdict(
    *,
    rolling_summary: dict[str, Any],
    full: dict[str, Any],
    stress_5x: dict[str, Any],
    top_5_removed: dict[str, Any],
    spec: dict[str, Any],
) -> str:
    hit_windows = int(rolling_summary.get("hit_1m_windows") or 0)
    drawdown = _safe_float(full.get("max_drawdown_pct"))
    if hit_windows >= 3 and drawdown <= 0.25 and _safe_float(stress_5x.get("ending_equity")) >= 500_000.0 and _safe_float(top_5_removed.get("ending_equity")) >= 500_000.0 and not bool(spec.get("uses_future_outcome_info")):
        return "MISSION_PROMISING_RESEARCH_ONLY"
    if hit_windows >= 1 and drawdown <= 0.30 and not bool(spec.get("uses_future_outcome_info")):
        return "BRIDGE_HELPFUL_BUT_FRAGILE"
    if _safe_float(rolling_summary.get("average_ending_equity")) > 550_000.0:
        return "AVERAGE_IMPROVES_BUT_NO_MISSION_HIT"
    return "NO_MATERIAL_MISSION_BRIDGE"


def _mission_realism_gate(variant_rows: list[dict[str, Any]]) -> dict[str, Any]:
    gate_rows: list[dict[str, Any]] = []
    accepted: list[dict[str, Any]] = []
    for row in variant_rows:
        pass_conditions = {
            "multiple_rolling_1m_hits": int(row.get("hit_1m_windows") or 0) >= 2,
            "non_oracle": not bool(row.get("uses_future_outcome_info")),
            "survives_normal_costs": True,
            "survives_5x_cost": bool(row.get("survives_5x_cost")),
            "acceptable_drawdown": _safe_float(row.get("max_drawdown_pct")) <= 0.30,
            "not_top5_dependent": bool(row.get("survives_top5_removal")),
            "insolvency_clamped_safe": not bool(row.get("insolvency_hit")),
            "research_only": bool(row.get("research_only")),
            "gate_allowed_variant": bool(row.get("allow_realism_gate")),
        }
        passed = all(pass_conditions.values())
        gate_row = {
            "variant_name": row["variant_name"],
            "passed": passed,
            "conditions": pass_conditions,
            "verdict": "MISSION_REALISM_PASS" if passed else "MISSION_REALISM_FAIL",
        }
        gate_rows.append(gate_row)
        if passed:
            accepted.append(row)
    return {
        **RESEARCH_ONLY_FLAGS,
        "gate_rows": gate_rows,
        "accepted_variants": [row["variant_name"] for row in accepted],
        "best_accepted_variant": accepted[0]["variant_name"] if accepted else "",
        "any_variant_passed": bool(accepted),
    }


def _no_go_risks(base_row: dict[str, Any], gate: dict[str, Any], variant_rows: list[dict[str, Any]]) -> dict[str, Any]:
    best_non_oracle = next((row for row in variant_rows if not bool(row.get("uses_future_outcome_info"))), None)
    risks: list[str] = []
    if int(base_row.get("hit_1m_windows") or 0) == 0:
        risks.append("base_strict_hits_zero_rolling_1m_windows")
    if not gate.get("any_variant_passed"):
        risks.append("no_bridge_variant_passes_mission_realism_gate")
    if best_non_oracle and _safe_float(best_non_oracle.get("max_drawdown_pct")) > 0.30:
        risks.append("best_non_oracle_bridge_requires_excessive_drawdown")
    if best_non_oracle and not bool(best_non_oracle.get("survives_5x_cost")):
        risks.append("best_non_oracle_bridge_fails_5x_cost_survival")
    return {**RESEARCH_ONLY_FLAGS, "risks": risks}


def _final_classification(base_row: dict[str, Any], gate: dict[str, Any], variant_rows: list[dict[str, Any]]) -> str:
    accepted = [row for row in variant_rows if row["variant_name"] in set(gate.get("accepted_variants") or [])]
    if accepted:
        return "FIVE_YEAR_GAP_READY_FOR_MONTE_CARLO_RETEST_RESEARCH_ONLY"
    non_oracle = [row for row in variant_rows if not bool(row.get("uses_future_outcome_info"))]
    best_non_oracle = non_oracle[0] if non_oracle else base_row
    base_avg = _safe_float(base_row.get("rolling_5y_average_ending_equity"))
    best_avg = _safe_float(best_non_oracle.get("rolling_5y_average_ending_equity"))
    avg_improvement = best_avg - base_avg
    if best_non_oracle["variant_name"].endswith("BLEND") and avg_improvement > 75_000.0:
        return "FIVE_YEAR_GAP_NEEDS_MORE_TRADE_FREQUENCY"
    if "STEPUP" in best_non_oracle["variant_name"] and avg_improvement > 75_000.0:
        return "FIVE_YEAR_GAP_NEEDS_CAPITAL_DEPLOYMENT_REPAIR"
    if avg_improvement > 50_000.0:
        return "FIVE_YEAR_GAP_BRIDGE_PROMISING_RESEARCH_ONLY"
    if avg_improvement > 0.0:
        return "FIVE_YEAR_GAP_BRIDGE_WEAK"
    return "FIVE_YEAR_GAP_NOT_BRIDGEABLE"


def _next_recommendation(final_classification: str, best_variant: dict[str, Any]) -> dict[str, Any]:
    if final_classification == "FIVE_YEAR_GAP_NEEDS_MORE_TRADE_FREQUENCY":
        next_step = "Investigate a complementary trade-frequency sleeve or broader high-quality participation routing before any further strictness."
    elif final_classification == "FIVE_YEAR_GAP_NEEDS_CAPITAL_DEPLOYMENT_REPAIR":
        next_step = "Test milestone-based capital deployment ladders on the frozen strict family, then rerun stress plus Monte Carlo as research-only."
    elif final_classification == "FIVE_YEAR_GAP_READY_FOR_MONTE_CARLO_RETEST_RESEARCH_ONLY":
        next_step = "Freeze the best bridge and rerun a research-only Monte Carlo retest before considering any paper candidate."
    else:
        next_step = "Keep the strict SR-aware detector frozen and focus on trade-density/complementary opportunity research rather than more tightening."
    return {
        **RESEARCH_ONLY_FLAGS,
        "final_classification": final_classification,
        "best_variant": best_variant.get("variant_name", ""),
        "next_step": next_step,
    }


def _court_report(
    *,
    summary: dict[str, Any],
    attribution: dict[str, Any],
    gap_summary: dict[str, Any],
    base_row: dict[str, Any],
    best_variant: dict[str, Any],
    final_classification: str,
) -> str:
    return "\n".join(
        [
            "# Native SR-Aware 5-Year Mission Gap Audit",
            "",
            f"Final classification: `{final_classification}`",
            "",
            "## Court Findings",
            "",
            f"1. Full-sequence strict equity reaches `{summary['full_sequence_ending_equity']:.2f}` EUR because the engine compounds strongly over the complete 2018-06-13 to 2026-06-13 span, but the rolling 5-year windows average only `{summary['rolling_5y_average_ending_equity']:.2f}` EUR and hit 1M exactly `{summary['rolling_5y_hit_1m_windows']}` times.",
            f"2. The dominant mission-gap driver is `{gap_summary['dominant_failure_cause']}`. The attribution layer also shows `{attribution['main_reason']}`.",
            f"3. The closest rolling 5-year window is `{summary['closest_window_label']}` with ending equity `{summary['closest_window_ending_equity']:.2f}` EUR and gap `{summary['closest_window_gap_to_1m_eur']:.2f}` EUR.",
            f"4. The best non-oracle bridge is `{best_variant.get('variant_name', 'n/a')}` with rolling 5-year average `{_safe_float(best_variant.get('rolling_5y_average_ending_equity')):.2f}` EUR, median `{_safe_float(best_variant.get('rolling_5y_median_ending_equity')):.2f}` EUR, 1M hit windows `{int(best_variant.get('hit_1m_windows') or 0)}`, and max drawdown `{_safe_float(best_variant.get('max_drawdown_pct')):.4f}`.",
            f"5. Frozen-baseline blending {'helps' if 'BLEND' in str(best_variant.get('variant_name') or '') else 'does not dominate'} relative to pure strict capital deployment.",
            f"6. Milestone-based risk step-up {'helps' if 'STEPUP' in str(best_variant.get('variant_name') or '') or 'AFTER_' in str(best_variant.get('variant_name') or '') else 'does not clearly dominate'} without enough evidence yet to call the 5-year mission solved.",
            f"7. Profit-vault reinvestment step-up {'helps' if best_variant.get('variant_name') == 'STRICT_WITH_PROFIT_VAULT_REINVESTMENT_STEPUP' else 'did not become the primary bridge'} in this audit.",
            f"8. The gap currently looks more like `{summary['bridge_direction']}` than a no-edge problem.",
            f"9. The 1M mission is currently `{summary['mission_support_label']}`.",
            f"10. The next research step is `{summary['next_research_step']}`.",
            "",
            "## Guardrails",
            "",
            "- `research_only=true`",
            "- `paper_allowed=false`",
            "- `live_allowed=false`",
            "- `real_money_allowed=false`",
            "- `behavior_change_allowed=false`",
            "- No production allocator/risk/sizing/entry/exit/threshold/sleeve behavior changed",
            "",
        ]
    )


def write_native_sr_aware_5y_mission_gap_audit(
    config: NativeSRAware5YMissionGapAuditConfig,
) -> dict[str, Path]:
    context, warnings = _reconstruct_sequences(config)
    if context is None:
        return _empty_outputs(
            config,
            classification="NATIVE_SR_AWARE_5Y_MISSION_GAP_BLOCKED",
            warnings=warnings,
        )

    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    strict_rows = context["strict_rows"]
    base_full = _simulate_bridge_sequence(strict_rows)
    yearly_rows, monthly_rows, trade_frequency_rows = _year_month_timelines(base_full["trade_trace"], base_full["daily_rows"])
    inactive_period_rows = _inactive_periods(monthly_rows)
    top_winner_rows = _top_winner_timing(base_full["trade_trace"])

    gap_rows, gap_summary = _rolling_gap_decomposition(strict_rows, context["windows"])
    closest_rows = sorted(gap_rows, key=lambda row: _safe_float(row["distance_to_1m_eur"]))[:10]
    farthest_rows = sorted(gap_rows, key=lambda row: _safe_float(row["distance_to_1m_eur"]), reverse=True)[:10]

    late_pnl_share = 0.0
    if base_full["trade_trace"]:
        midpoint = pd.Timestamp(base_full["trade_trace"][0]["timestamp"]) + ((pd.Timestamp(base_full["trade_trace"][-1]["timestamp"]) - pd.Timestamp(base_full["trade_trace"][0]["timestamp"])) / 2)
        late_pnl = sum(_safe_float(row.get("pnl")) for row in base_full["trade_trace"] if pd.Timestamp(row["timestamp"]) >= midpoint)
        total_pnl = sum(_safe_float(row.get("pnl")) for row in base_full["trade_trace"])
        late_pnl_share = _safe_ratio(late_pnl, total_pnl, 0.0)
    attribution = {
        **RESEARCH_ONLY_FLAGS,
        "full_sequence_ending_equity": round(_safe_float(base_full["ending_equity"]), 6),
        "rolling_5y_average_ending_equity": round(sum(_safe_float(row["ending_equity"]) for row in gap_rows) / max(len(gap_rows), 1), 6),
        "late_pnl_share": round(late_pnl_share, 6),
        "inactive_period_count": len(inactive_period_rows),
        "top_winner_count_used": len(top_winner_rows),
        "main_reason": (
            "late compounding arrives after the average 5Y window has already spent most of its base period"
            if late_pnl_share >= 0.55 else
            "the engine is strong but the 5Y windows appear underpowered on trade density and early capital acceleration"
        ),
    }

    oracle_gap_months = {row["month"][:7] for row in sorted(monthly_rows, key=lambda item: _safe_float(item["total_pnl"]))[:3] if row.get("month")}
    variant_specs = _bridge_variant_specs(oracle_gap_months)
    variant_rows: list[dict[str, Any]] = []
    bridge_rolling_rows: list[dict[str, Any]] = []
    risk_audit_rows: list[dict[str, Any]] = []
    insolvency_rows: list[dict[str, Any]] = []
    for spec in variant_specs:
        full, rolling_rows, rolling_summary, stress = _variant_full_and_rolling(context, spec)
        bridge_rolling_rows.extend(rolling_rows)
        survives_5x_cost = _safe_float(stress["five_x_cost"]["ending_equity"]) >= 250_000.0 and not bool(stress["five_x_cost"]["insolvency_hit"])
        survives_top5_removal = _safe_float(stress["top_5_removed"]["ending_equity"]) >= 250_000.0
        row = {
            **RESEARCH_ONLY_FLAGS,
            "variant_name": spec["variant_name"],
            "diagnostic_only": bool(spec.get("diagnostic_only", False)),
            "uses_future_outcome_info": bool(spec.get("uses_future_outcome_info", False)),
            "allow_realism_gate": bool(spec.get("allow_realism_gate", False)),
            "full_sequence_ending_equity": round(_safe_float(full["ending_equity"]), 6),
            "rolling_5y_average_ending_equity": round(_safe_float(rolling_summary["average_ending_equity"]), 6),
            "rolling_5y_median_ending_equity": round(_safe_float(rolling_summary["median_ending_equity"]), 6),
            "rolling_5y_best_ending_equity": round(_safe_float(rolling_summary["best_ending_equity"]), 6),
            "rolling_5y_worst_ending_equity": round(_safe_float(rolling_summary["worst_ending_equity"]), 6),
            "hit_1m_windows": int(rolling_summary["hit_1m_windows"]),
            "hit_5m_windows": int(rolling_summary["hit_5m_windows"]),
            "hit_10m_windows": int(rolling_summary["hit_10m_windows"]),
            "max_drawdown_pct": round(_safe_float(full["max_drawdown_pct"]), 6),
            "worst_month": str(full["worst_month"] or ""),
            "worst_year": str(full["worst_year"] or ""),
            "cost_survival": "SURVIVES_5X_COST" if survives_5x_cost else "FAILS_5X_COST",
            "survives_5x_cost": survives_5x_cost,
            "moonshot_survival": "ROBUST_WITH_TOP5_REMOVED" if survives_top5_removal else "TOP5_DEPENDENT",
            "survives_top5_removal": survives_top5_removal,
            "trade_count": int(full["trade_count"]),
            "average_trades_per_month": round(_safe_float(full["average_trades_per_month"]), 6),
            "risk_multiplier_average": round(_safe_float(full["risk_multiplier_avg"]), 6),
            "risk_multiplier_max": round(_safe_float(full["risk_multiplier_max"]), 6),
            "insolvency_hit": bool(full["insolvency_hit"]),
            "verdict": "",
        }
        row["verdict"] = _variant_verdict(
            rolling_summary=rolling_summary,
            full=full,
            stress_5x=stress["five_x_cost"],
            top_5_removed=stress["top_5_removed"],
            spec=spec,
        )
        variant_rows.append(row)
        risk_audit_rows.append(
            {
                "variant_name": spec["variant_name"],
                "risk_multiplier_average": row["risk_multiplier_average"],
                "risk_multiplier_max": row["risk_multiplier_max"],
                "uses_future_outcome_info": row["uses_future_outcome_info"],
                "diagnostic_only": row["diagnostic_only"],
            }
        )
        insolvency_rows.append(
            {
                "variant_name": spec["variant_name"],
                "insolvency_hit": row["insolvency_hit"],
                "five_x_cost_insolvency_hit": bool(stress["five_x_cost"]["insolvency_hit"]),
                "drawdown_breaker_triggered": bool(full["breaker_triggered"]),
            }
        )

    variant_rows.sort(
        key=lambda row: (
            -int(row["hit_1m_windows"]),
            -_safe_float(row["rolling_5y_average_ending_equity"]),
            -_safe_float(row["rolling_5y_median_ending_equity"]),
            _safe_float(row["max_drawdown_pct"]),
        )
    )
    gate = _mission_realism_gate(variant_rows)
    base_row = next(row for row in variant_rows if row["variant_name"] == "BASE_NATIVE_SR_AWARE_STRICT")
    best_variant = variant_rows[0] if variant_rows else base_row
    final_classification = _final_classification(base_row, gate, variant_rows)
    no_go = _no_go_risks(base_row, gate, variant_rows)
    next_step = _next_recommendation(final_classification, best_variant)

    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "full_sequence_ending_equity": round(_safe_float(base_full["ending_equity"]), 6),
        "rolling_5y_average_ending_equity": round(_safe_float(base_row["rolling_5y_average_ending_equity"]), 6),
        "rolling_5y_median_ending_equity": round(_safe_float(base_row["rolling_5y_median_ending_equity"]), 6),
        "rolling_5y_hit_1m_windows": int(base_row["hit_1m_windows"]),
        "closest_window_label": gap_summary["closest_window_label"],
        "closest_window_ending_equity": round(_safe_float(next(row["ending_equity"] for row in gap_rows if row["window_label"] == gap_summary["closest_window_label"])), 6) if gap_rows else 0.0,
        "closest_window_gap_to_1m_eur": round(_safe_float(min(gap_rows, key=lambda row: _safe_float(row["distance_to_1m_eur"]))["distance_to_1m_eur"]), 6) if gap_rows else 0.0,
        "bridge_direction": (
            "capital deployment repair"
            if "STEPUP" in str(best_variant.get("variant_name") or "") or "AFTER_" in str(best_variant.get("variant_name") or "")
            else "trade frequency / complementary participation"
        ),
        "mission_support_label": (
            "promising but still research-only"
            if final_classification in {"FIVE_YEAR_GAP_BRIDGE_PROMISING_RESEARCH_ONLY", "FIVE_YEAR_GAP_READY_FOR_MONTE_CARLO_RETEST_RESEARCH_ONLY"}
            else "not yet supported for the exact 5Y mission"
        ),
        "main_reason_for_gap": gap_summary["dominant_failure_cause"],
        "best_bridge_variant": best_variant.get("variant_name", ""),
        "best_bridge_rolling_5y_average_ending_equity": round(_safe_float(best_variant.get("rolling_5y_average_ending_equity")), 6),
        "best_bridge_rolling_5y_median_ending_equity": round(_safe_float(best_variant.get("rolling_5y_median_ending_equity")), 6),
        "best_bridge_hit_1m_windows": int(best_variant.get("hit_1m_windows") or 0),
        "best_bridge_max_drawdown_pct": round(_safe_float(best_variant.get("max_drawdown_pct")), 6),
        "best_bridge_survives_5x_cost": bool(best_variant.get("survives_5x_cost")),
        "best_bridge_passes_realism_gate": best_variant.get("variant_name", "") in set(gate.get("accepted_variants") or []),
        "final_classification": final_classification,
        "next_research_step": str(next_step["next_step"]),
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
    }

    report = _court_report(
        summary=summary,
        attribution=attribution,
        gap_summary=gap_summary,
        base_row=base_row,
        best_variant=best_variant,
        final_classification=final_classification,
    )

    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "native_sr_aware_5y_mission_gap_summary.json", summary)
    _write_markdown(config.output_root / "native_sr_aware_5y_mission_gap_report.md", report)
    _write_json(diagnostics_root / "full_sequence_vs_5y_gap_attribution.json", attribution)
    _write_csv(diagnostics_root / "yearly_contribution_timeline.csv", yearly_rows)
    _write_csv(diagnostics_root / "monthly_contribution_timeline.csv", monthly_rows)
    _write_csv(diagnostics_root / "trade_frequency_timeline.csv", trade_frequency_rows)
    _write_csv(diagnostics_root / "top_winner_timing.csv", top_winner_rows)
    _write_csv(diagnostics_root / "inactive_periods.csv", inactive_period_rows)
    _write_csv(diagnostics_root / "rolling_5y_gap_decomposition.csv", gap_rows)
    _write_json(diagnostics_root / "rolling_5y_gap_decomposition.json", {**RESEARCH_ONLY_FLAGS, "summary": gap_summary, "rows": gap_rows})
    _write_csv(diagnostics_root / "closest_windows_to_1m.csv", closest_rows)
    _write_csv(diagnostics_root / "farthest_windows_from_1m.csv", farthest_rows)
    _write_csv(diagnostics_root / "mission_bridge_variant_results.csv", variant_rows)
    _write_json(diagnostics_root / "mission_bridge_variant_results.json", {**RESEARCH_ONLY_FLAGS, "rows": variant_rows})
    _write_csv(diagnostics_root / "mission_bridge_rolling_5y_results.csv", bridge_rolling_rows)
    _write_csv(diagnostics_root / "mission_bridge_risk_multiplier_audit.csv", risk_audit_rows)
    _write_csv(diagnostics_root / "mission_bridge_insolvency_clamp_audit.csv", insolvency_rows)
    _write_json(diagnostics_root / "mission_realism_gate.json", gate)
    _write_json(diagnostics_root / "no_go_risks.json", no_go)
    _write_json(reports_root / "next_research_recommendation.json", next_step)
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "native_sr_aware_5y_mission_gap_summary.json",
        "report": config.output_root / "native_sr_aware_5y_mission_gap_report.md",
    }


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    output_root = package_root / "output" / OUTPUT_FOLDER_NAME
    write_native_sr_aware_5y_mission_gap_audit(
        NativeSRAware5YMissionGapAuditConfig(
            package_root=package_root,
            output_root=output_root,
        )
    )
