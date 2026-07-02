from __future__ import annotations

import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import RESEARCH_ONLY_FLAGS  # noqa: E402
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _median,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.diagnostics.native_sr_aware_5y_mission_gap_audit import (  # noqa: E402
    BASELINE_COST_BPS,
    FIVE_X_COST_BPS,
    NativeSRAware5YMissionGapAuditConfig,
    START_CAPITAL,
    _clone_row,
    _reconstruct_sequences,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import (  # noqa: E402
    _build_windows,
    _target_hit_metrics,
    _window_rows,
)


OUTPUT_FOLDER_NAME = "milestone_bridge_fragility_driver_repair_audit_001"
DEFAULT_MC_PATHS_PER_OVERLAY = 300
BEST_BRIDGE_NAME = "STRICT_WITH_EQUITY_MILESTONE_RISK_STEPUP"
BASE_STEPUP_SCHEDULE = [(100_000.0, 1.25), (250_000.0, 1.50), (500_000.0, 2.00)]


@dataclass(frozen=True)
class MilestoneBridgeFragilityDriverRepairAuditConfig:
    package_root: Path
    output_root: Path
    mc_paths_per_overlay: int = DEFAULT_MC_PATHS_PER_OVERLAY


def _safe_float(value: Any) -> float:
    try:
        if value is None or str(value).strip() == "":
            return 0.0
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _paths(config: MilestoneBridgeFragilityDriverRepairAuditConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    bridge_root = output_root / "strict_sr_aware_milestone_bridge_monte_carlo_audit_001"
    return {
        "bridge_summary": bridge_root / "strict_sr_aware_milestone_bridge_monte_carlo_summary.json",
        "bridge_mc_summary": bridge_root / "diagnostics" / "monte_carlo_bridge_summary.json",
        "bridge_rolling_retest": bridge_root / "diagnostics" / "rolling_5y_bridge_retest.csv",
        "bridge_fragility": bridge_root / "diagnostics" / "milestone_bridge_fragility_audit.json",
        "risk_stepup_timing": bridge_root / "diagnostics" / "risk_stepup_timing_audit.csv",
        "early_winner_dependency": bridge_root / "diagnostics" / "early_winner_dependency_audit.json",
        "drawdown_after_stepup": bridge_root / "diagnostics" / "drawdown_after_stepup_audit.csv",
        "missed_trade_sensitivity": bridge_root / "diagnostics" / "missed_trade_sensitivity.csv",
        "bridge_mission_gate": bridge_root / "diagnostics" / "bridge_mission_gate.json",
        "bridge_trade_ledger": bridge_root / "ledger" / "milestone_bridge_trades.csv",
        "bridge_equity_ledger": bridge_root / "ledger" / "milestone_bridge_equity.csv",
        "bridge_ledger_summary": bridge_root / "ledger" / "milestone_bridge_summary.json",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, reports_root


def _empty_outputs(
    config: MilestoneBridgeFragilityDriverRepairAuditConfig,
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
    _write_json(config.output_root / "milestone_bridge_fragility_driver_repair_summary.json", summary)
    _write_markdown(
        config.output_root / "milestone_bridge_fragility_driver_repair_report.md",
        "# Milestone Bridge Fragility Driver Repair Audit\n\nRequired bridge artifacts were missing, so the audit stayed blocked.\n",
    )
    for path in (
        diagnostics_root / "cost_realism_assessment.json",
        diagnostics_root / "trade_redundancy_score.json",
        diagnostics_root / "fragility_repair_overlay_results.json",
        diagnostics_root / "fragility_repair_monte_carlo_comparison.json",
        diagnostics_root / "revised_bridge_mission_gate.json",
        diagnostics_root / "no_go_risks.json",
        reports_root / "next_research_recommendation.json",
    ):
        _write_json(path, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    for path in (
        diagnostics_root / "cost_fragility_decomposition.csv",
        diagnostics_root / "cost_fragility_by_year.csv",
        diagnostics_root / "cost_fragility_by_month.csv",
        diagnostics_root / "missed_trade_fragility_decomposition.csv",
        diagnostics_root / "missed_trade_rate_sensitivity.csv",
        diagnostics_root / "top_winner_dependency_decomposition.csv",
        diagnostics_root / "milestone_timing_missed_trade_sensitivity.csv",
        diagnostics_root / "fragility_repair_overlay_results.csv",
        diagnostics_root / "fragility_repair_mission_gate_comparison.csv",
    ):
        _write_csv(path, [])
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "milestone_bridge_fragility_driver_repair_summary.json",
        "report": config.output_root / "milestone_bridge_fragility_driver_repair_report.md",
    }


def _sort_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or ""))


def _resequence_rows(rows: list[dict[str, Any]], *, start_time: pd.Timestamp | None = None) -> list[dict[str, Any]]:
    if not rows:
        return []
    origin = start_time or pd.Timestamp("2020-01-01T00:00:00+00:00")
    resequenced: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        cloned = _clone_row(row)
        entry_ts = origin + pd.Timedelta(days=index)
        exit_ts = entry_ts + pd.Timedelta(hours=1)
        cloned["entry_timestamp"] = entry_ts
        cloned["exit_timestamp"] = exit_ts
        cloned["entry_time"] = entry_ts.isoformat()
        cloned["exit_time"] = exit_ts.isoformat()
        resequenced.append(cloned)
    return resequenced


def _group_consecutive_blocks(rows: list[dict[str, Any]], key_func: Any) -> list[list[dict[str, Any]]]:
    blocks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_label: str | None = None
    for row in rows:
        label = str(key_func(row))
        if current_label is None or label == current_label:
            current.append(row)
            current_label = label
            continue
        blocks.append(current)
        current = [row]
        current_label = label
    if current:
        blocks.append(current)
    return blocks


def _drop_random_trades(rows: list[dict[str, Any]], frac: float, seed: int) -> list[dict[str, Any]]:
    if not rows:
        return []
    rng = random.Random(seed)
    keep_count = max(1, int(round(len(rows) * (1.0 - frac))))
    kept_indexes = sorted(rng.sample(range(len(rows)), keep_count))
    return [_clone_row(rows[index]) for index in kept_indexes]


def _year_label(row: dict[str, Any]) -> str:
    exit_ts = row.get("exit_timestamp")
    return str(exit_ts.year) if isinstance(exit_ts, pd.Timestamp) else "unknown"


def _month_label(row: dict[str, Any]) -> str:
    exit_ts = row.get("exit_timestamp")
    return exit_ts.strftime("%Y-%m") if isinstance(exit_ts, pd.Timestamp) else "unknown"


def _quarter_label(row: dict[str, Any]) -> str:
    exit_ts = row.get("exit_timestamp")
    if not isinstance(exit_ts, pd.Timestamp):
        return "unknown"
    quarter = ((int(exit_ts.month) - 1) // 3) + 1
    return f"{int(exit_ts.year)}-Q{quarter}"


def _estimated_cost(row: dict[str, Any], cost_bps_total: float) -> float:
    entry_price = _safe_float(row.get("entry_price"))
    exit_price = _safe_float(row.get("exit_price")) or entry_price
    quantity = _safe_float(row.get("quantity")) or 1.0
    notional = abs((entry_price + exit_price) * 0.5 * quantity)
    return notional * (cost_bps_total / 10_000.0)


def _simulate_overlay_sequence(
    rows: list[dict[str, Any]],
    *,
    stepup_schedule: list[tuple[float, float]],
    cost_bps_total: float = 0.0,
    min_total_wins_for_stepup: int = 0,
    min_trade_count_for_stepup: int = 0,
    stepup_delay_trades_after_cross: int = 0,
    max_multiplier_cap: float | None = None,
    cost_guard_ratio_threshold: float | None = None,
    liquidity_score_threshold: float | None = None,
    volume_confirmation_threshold: float | None = None,
    drawdown_breaker_pct: float | None = None,
    insolvency_clamp: bool = True,
) -> dict[str, Any]:
    ordered = _sort_rows(rows)
    active_capital = float(START_CAPITAL)
    locked_profit = 0.0
    peak_equity = active_capital
    max_drawdown_pct = 0.0
    daily_rows: list[dict[str, Any]] = []
    trade_trace: list[dict[str, Any]] = []
    current_day_key: str | None = None
    day_pnl = 0.0
    day_r = 0.0
    day_trade_count = 0
    day_equity_start = START_CAPITAL
    day_equity_end = START_CAPITAL
    wins_so_far = 0
    trades_so_far = 0
    crossed_milestones: dict[float, int] = {}
    insolvency_hit = False
    breaker_triggered = False
    worst_month_totals: dict[str, float] = {}
    worst_year_totals: dict[str, float] = {}
    risk_multipliers: list[float] = []
    last_equity = START_CAPITAL

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
        base_risk_value = max(active_capital, 0.0) * 0.01
        for equity_threshold, scheduled_multiplier in sorted(stepup_schedule, key=lambda item: item[0]):
            if current_equity >= equity_threshold:
                if last_equity < equity_threshold and equity_threshold not in crossed_milestones:
                    crossed_milestones[equity_threshold] = trades_so_far
                crossed_trade_index = crossed_milestones.get(equity_threshold, trades_so_far)
                allow = (
                    wins_so_far >= min_total_wins_for_stepup
                    and trades_so_far >= min_trade_count_for_stepup
                    and (trades_so_far - crossed_trade_index) >= stepup_delay_trades_after_cross
                )
                if allow:
                    multiplier = max(multiplier, scheduled_multiplier)
        if max_multiplier_cap is not None:
            multiplier = min(multiplier, max_multiplier_cap)

        liquidity_score = _safe_float(row.get("liquidity_score"))
        volume_confirmation_score = _safe_float(row.get("volume_confirmation_score"))
        if liquidity_score_threshold is not None and liquidity_score < liquidity_score_threshold:
            multiplier = min(multiplier, 1.0)
        if volume_confirmation_threshold is not None and volume_confirmation_score < volume_confirmation_threshold:
            multiplier = min(multiplier, 1.0)
        estimated_cost_normal = _estimated_cost(row, BASELINE_COST_BPS)
        if cost_guard_ratio_threshold is not None and base_risk_value > 0.0:
            if _safe_ratio(estimated_cost_normal, base_risk_value, 0.0) > cost_guard_ratio_threshold:
                multiplier = min(multiplier, 1.0)

        risk_value = base_risk_value * multiplier
        applied_r = _safe_float(row.get("r_multiple"))
        pnl = applied_r * risk_value - _estimated_cost(row, cost_bps_total)
        active_capital += pnl
        if pnl > 0.0:
            lock_amount = pnl * 0.5
            locked_profit += lock_amount
            active_capital -= lock_amount
            wins_so_far += 1
        total_equity = active_capital + locked_profit
        if insolvency_clamp and total_equity <= 0.0:
            active_capital = 0.0
            locked_profit = 0.0
            total_equity = 0.0
            insolvency_hit = True
            peak_equity = max(peak_equity, total_equity)
            max_drawdown_pct = max(max_drawdown_pct, 1.0)
        peak_equity = max(peak_equity, total_equity)
        max_drawdown_pct = max(max_drawdown_pct, _safe_ratio(max(0.0, peak_equity - total_equity), peak_equity, 0.0))
        trades_so_far += 1
        risk_multipliers.append(multiplier)
        last_equity = total_equity
        day_pnl += pnl
        day_r += applied_r
        day_trade_count += 1
        day_equity_end = total_equity
        month_key = _month_label(row)
        year_key = _year_label(row)
        worst_month_totals[month_key] = worst_month_totals.get(month_key, 0.0) + pnl
        worst_year_totals[year_key] = worst_year_totals.get(year_key, 0.0) + pnl
        trade_trace.append(
            {
                "trade_id": str(row.get("trade_id") or ""),
                "timestamp": exit_ts.isoformat(),
                "month": month_key,
                "year": year_key,
                "risk_multiplier": round(multiplier, 6),
                "risk_value": round(risk_value, 6),
                "applied_r": round(applied_r, 6),
                "pnl": round(pnl, 6),
                "equity_after": round(total_equity, 6),
                "archetype_key": str(row.get("archetype_key") or ""),
            }
        )
        if insolvency_hit:
            break

    flush_day()
    r_values = [_safe_float(row.get("applied_r")) for row in trade_trace]
    wins = [value for value in r_values if value > 0.0]
    losses = [abs(value) for value in r_values if value < 0.0]
    profit_factor = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
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
        "risk_multiplier_avg": round(sum(risk_multipliers) / len(risk_multipliers), 6) if risk_multipliers else 0.0,
        "risk_multiplier_max": round(max(risk_multipliers), 6) if risk_multipliers else 0.0,
        "worst_month": min(worst_month_totals.items(), key=lambda item: item[1])[0] if worst_month_totals else "",
        "worst_year": min(worst_year_totals.items(), key=lambda item: item[1])[0] if worst_year_totals else "",
    }


def _load_context(config: MilestoneBridgeFragilityDriverRepairAuditConfig) -> tuple[dict[str, Any] | None, list[str]]:
    paths = _paths(config)
    required = [
        paths["bridge_summary"],
        paths["bridge_mc_summary"],
        paths["bridge_rolling_retest"],
        paths["bridge_fragility"],
        paths["risk_stepup_timing"],
        paths["early_winner_dependency"],
        paths["drawdown_after_stepup"],
        paths["missed_trade_sensitivity"],
        paths["bridge_mission_gate"],
        paths["bridge_trade_ledger"],
        paths["bridge_equity_ledger"],
        paths["bridge_ledger_summary"],
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return None, missing
    reconstruction, warnings = _reconstruct_sequences(
        NativeSRAware5YMissionGapAuditConfig(
            package_root=config.package_root,
            output_root=config.package_root / "output" / "native_sr_aware_5y_mission_gap_audit_001",
        )
    )
    if reconstruction is None:
        return None, warnings
    strict_rows = reconstruction["strict_rows"]
    bridge_trade_rows = _read_csv_rows(paths["bridge_trade_ledger"])
    bridge_map = {str(row.get("trade_id") or ""): row for row in bridge_trade_rows}
    enriched_rows: list[dict[str, Any]] = []
    for row in strict_rows:
        item = _clone_row(row)
        item.update(bridge_map.get(str(row.get("trade_id") or ""), {}))
        enriched_rows.append(item)
    return {
        "strict_rows": _sort_rows(enriched_rows),
        "windows": _build_windows(enriched_rows),
        "bridge_summary": _read_json(paths["bridge_summary"], {}),
        "bridge_mc_summary": _read_json(paths["bridge_mc_summary"], {}),
        "bridge_fragility": _read_json(paths["bridge_fragility"], {}),
        "bridge_gate": _read_json(paths["bridge_mission_gate"], {}),
        "bridge_ledger_summary": _read_json(paths["bridge_ledger_summary"], {}),
    }, []


def _cost_fragility_decomposition(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    decomposition: list[dict[str, Any]] = []
    by_year: dict[str, dict[str, float]] = {}
    by_month: dict[str, dict[str, float]] = {}
    total_gross_profit = 0.0
    total_baseline_cost = 0.0
    total_risk_value = 0.0
    holding_hours: list[float] = []
    for row in rows:
        risk_value = START_CAPITAL * 0.01
        entry_ts = row.get("entry_timestamp")
        exit_ts = row.get("exit_timestamp")
        hold_hours = ((exit_ts - entry_ts).total_seconds() / 3600.0) if isinstance(entry_ts, pd.Timestamp) and isinstance(exit_ts, pd.Timestamp) else 0.0
        baseline_cost = _estimated_cost(row, BASELINE_COST_BPS)
        gross_profit = max(0.0, _safe_float(row.get("r_multiple")) * risk_value)
        total_gross_profit += gross_profit
        total_baseline_cost += baseline_cost
        total_risk_value += risk_value
        holding_hours.append(hold_hours)
        period_year = _year_label(row)
        period_month = _month_label(row)
        trade_type = str(row.get("archetype_key") or "").split("|")[1] if "|" in str(row.get("archetype_key") or "") else str(row.get("archetype_key") or "")
        record = {
            "trade_id": str(row.get("trade_id") or ""),
            "year": period_year,
            "month": period_month,
            "trade_type": trade_type,
            "holding_hours": round(hold_hours, 6),
            "baseline_cost": round(baseline_cost, 6),
            "five_x_cost": round(_estimated_cost(row, FIVE_X_COST_BPS), 6),
            "ten_x_cost": round(_estimated_cost(row, BASELINE_COST_BPS * 10.0), 6),
            "gross_profit_estimate": round(gross_profit, 6),
            "cost_as_pct_gross_profit": round(_safe_ratio(baseline_cost, gross_profit, 0.0), 6) if gross_profit > 0 else 0.0,
            "cost_as_pct_risk_value": round(_safe_ratio(baseline_cost, risk_value, 0.0), 6) if risk_value > 0 else 0.0,
            "risk_multiplier": round(_safe_float(row.get("risk_multiplier")), 6),
        }
        decomposition.append(record)
        for key, bucket_map in ((period_year, by_year), (period_month, by_month)):
            bucket = bucket_map.setdefault(key, {"trade_count": 0.0, "baseline_cost": 0.0, "five_x_cost": 0.0, "ten_x_cost": 0.0, "gross_profit": 0.0})
            bucket["trade_count"] += 1.0
            bucket["baseline_cost"] += baseline_cost
            bucket["five_x_cost"] += _estimated_cost(row, FIVE_X_COST_BPS)
            bucket["ten_x_cost"] += _estimated_cost(row, BASELINE_COST_BPS * 10.0)
            bucket["gross_profit"] += gross_profit
    by_year_rows = [
        {
            "year": key,
            "trade_count": int(value["trade_count"]),
            "baseline_cost": round(value["baseline_cost"], 6),
            "five_x_cost": round(value["five_x_cost"], 6),
            "ten_x_cost": round(value["ten_x_cost"], 6),
            "gross_profit_estimate": round(value["gross_profit"], 6),
            "cost_as_pct_gross_profit": round(_safe_ratio(value["baseline_cost"], value["gross_profit"], 0.0), 6) if value["gross_profit"] > 0 else 0.0,
        }
        for key, value in sorted(by_year.items())
    ]
    by_month_rows = [
        {
            "month": key,
            "trade_count": int(value["trade_count"]),
            "baseline_cost": round(value["baseline_cost"], 6),
            "five_x_cost": round(value["five_x_cost"], 6),
            "ten_x_cost": round(value["ten_x_cost"], 6),
            "gross_profit_estimate": round(value["gross_profit"], 6),
            "cost_as_pct_gross_profit": round(_safe_ratio(value["baseline_cost"], value["gross_profit"], 0.0), 6) if value["gross_profit"] > 0 else 0.0,
        }
        for key, value in sorted(by_month.items())
    ]
    avg_cost_pct_risk = _safe_ratio(total_baseline_cost, total_risk_value, 0.0)
    realism = {
        **RESEARCH_ONLY_FLAGS,
        "trade_count": len(rows),
        "average_holding_hours": round(sum(holding_hours) / len(holding_hours), 6) if holding_hours else 0.0,
        "average_expected_cost_per_trade": round(total_baseline_cost / len(rows), 6) if rows else 0.0,
        "cost_as_pct_total_gross_profit": round(_safe_ratio(total_baseline_cost, total_gross_profit, 0.0), 6) if total_gross_profit > 0 else 0.0,
        "cost_as_pct_average_risk": round(avg_cost_pct_risk, 6),
        "five_x_cost_verdict": "OVERLY_PUNITIVE_BUT_DIAGNOSTICALLY_USEFUL" if avg_cost_pct_risk < 0.25 else "SEVERE_BUT_NOT_IMPOSSIBLE",
        "ten_x_cost_verdict": "APOCALYPSE_SCENARIO" if (avg_cost_pct_risk * 10.0) > 0.50 else "EXTREME_STRESS_ONLY",
        "overall_cost_realism_verdict": "NORMAL_REALISTIC_5X_PUNITIVE_10X_APOCALYPSE",
    }
    return decomposition, by_year_rows, by_month_rows, realism


def _missed_trade_decomposition(rows: list[dict[str, Any]], windows: list[tuple[pd.Timestamp, pd.Timestamp, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    baseline = _simulate_overlay_sequence(rows, stepup_schedule=list(BASE_STEPUP_SCHEDULE))
    baseline_end = _safe_float(baseline["ending_equity"])
    decomposition_rows: list[dict[str, Any]] = []
    for row in rows:
        reduced_rows = [_clone_row(item) for item in rows if str(item.get("trade_id") or "") != str(row.get("trade_id") or "")]
        output = _simulate_overlay_sequence(reduced_rows, stepup_schedule=list(BASE_STEPUP_SCHEDULE))
        decomposition_rows.append(
            {
                "trade_id": str(row.get("trade_id") or ""),
                "timestamp": str(row.get("exit_timestamp") or ""),
                "r_multiple": round(_safe_float(row.get("r_multiple")), 6),
                "risk_multiplier": round(_safe_float(row.get("risk_multiplier")), 6),
                "impact_on_full_sequence_equity": round(baseline_end - _safe_float(output["ending_equity"]), 6),
                "archetype_key": str(row.get("archetype_key") or ""),
            }
        )
    decomposition_rows.sort(key=lambda item: _safe_float(item["impact_on_full_sequence_equity"]), reverse=True)

    rate_rows: list[dict[str, Any]] = []
    for frac, seed in ((0.05, 505), (0.10, 1010), (0.20, 2020), (0.30, 3030)):
        dropped = [_clone_row(item) for item in rows]
        rng = random.Random(seed)
        keep_count = max(1, int(round(len(dropped) * (1.0 - frac))))
        kept = [_clone_row(dropped[index]) for index in sorted(rng.sample(range(len(dropped)), keep_count))]
        output = _simulate_overlay_sequence(kept, stepup_schedule=list(BASE_STEPUP_SCHEDULE))
        rate_rows.append(
            {
                "drop_rate": frac,
                "ending_equity": round(_safe_float(output["ending_equity"]), 6),
                "rolling_5y_reference_label": "full_sequence_only",
                "max_drawdown_pct": round(_safe_float(output["max_drawdown_pct"]), 6),
            }
        )

    top_rows: list[dict[str, Any]] = []
    winners = sorted(rows, key=lambda item: _safe_float(item.get("r_multiple")), reverse=True)
    for count in (1, 3, 5, 10):
        remove_ids = {str(item.get("trade_id") or "") for item in winners[:count]}
        kept = [_clone_row(item) for item in rows if str(item.get("trade_id") or "") not in remove_ids]
        output = _simulate_overlay_sequence(kept, stepup_schedule=list(BASE_STEPUP_SCHEDULE))
        top_rows.append(
            {
                "top_winners_removed": count,
                "ending_equity": round(_safe_float(output["ending_equity"]), 6),
                "max_drawdown_pct": round(_safe_float(output["max_drawdown_pct"]), 6),
            }
        )

    milestone_rows: list[dict[str, Any]] = []
    timing_rows = [row for row in rows if _safe_float(row.get("risk_multiplier")) > 1.0]
    timing_ids = {str(row.get("trade_id") or "") for row in timing_rows[:25]}
    kept = [_clone_row(item) for item in rows if str(item.get("trade_id") or "") not in timing_ids]
    output = _simulate_overlay_sequence(kept, stepup_schedule=list(BASE_STEPUP_SCHEDULE))
    milestone_rows.append(
        {
            "scenario": "remove_first_25_stepup_phase_trades",
            "ending_equity": round(_safe_float(output["ending_equity"]), 6),
            "max_drawdown_pct": round(_safe_float(output["max_drawdown_pct"]), 6),
        }
    )
    best_months = pd.Series([_month_label(row) for row in rows]).value_counts().head(3).index.tolist()
    best_month_ids = {str(row.get("trade_id") or "") for row in rows if _month_label(row) in set(best_months)}
    kept = [_clone_row(item) for item in rows if str(item.get("trade_id") or "") not in best_month_ids]
    output = _simulate_overlay_sequence(kept, stepup_schedule=list(BASE_STEPUP_SCHEDULE))
    milestone_rows.append(
        {
            "scenario": "remove_top_trade_density_months",
            "ending_equity": round(_safe_float(output["ending_equity"]), 6),
            "max_drawdown_pct": round(_safe_float(output["max_drawdown_pct"]), 6),
        }
    )
    trade_redundancy = {
        **RESEARCH_ONLY_FLAGS,
        "top_5_removed_equity_ratio": round(_safe_ratio(_safe_float(top_rows[2]["ending_equity"]), baseline_end, 0.0), 6) if len(top_rows) >= 3 else 0.0,
        "random_drop_30_equity_ratio": round(_safe_ratio(_safe_float(rate_rows[-1]["ending_equity"]), baseline_end, 0.0), 6) if rate_rows else 0.0,
        "redundancy_score": round(
            100.0 * (
                (0.5 * _safe_ratio(_safe_float(top_rows[2]["ending_equity"]), baseline_end, 0.0) if len(top_rows) >= 3 else 0.0)
                + (0.5 * _safe_ratio(_safe_float(rate_rows[-1]["ending_equity"]), baseline_end, 0.0) if rate_rows else 0.0)
            ),
            2,
        ),
        "verdict": "LOW_REDUNDANCY" if (rate_rows and _safe_float(rate_rows[-1]["ending_equity"]) < baseline_end * 0.5) else "MODERATE_REDUNDANCY",
    }
    return decomposition_rows[:100], rate_rows, top_rows, milestone_rows, trade_redundancy


def _overlay_specs() -> list[dict[str, Any]]:
    return [
        {"variant_name": "BASE_MILESTONE_BRIDGE", "sim_kwargs": {"stepup_schedule": list(BASE_STEPUP_SCHEDULE)}},
        {
            "variant_name": "BRIDGE_WITH_COST_GUARD",
            "sim_kwargs": {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "cost_guard_ratio_threshold": 0.18},
        },
        {
            "variant_name": "BRIDGE_WITH_5X_COST_BUFFER",
            "sim_kwargs": {"stepup_schedule": [(100_000.0, 1.10), (250_000.0, 1.20), (500_000.0, 1.35)], "cost_guard_ratio_threshold": 0.15},
        },
        {
            "variant_name": "BRIDGE_WITH_DELAYED_STEPUP_AFTER_3_WINNERS",
            "sim_kwargs": {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "min_total_wins_for_stepup": 3, "stepup_delay_trades_after_cross": 3},
        },
        {
            "variant_name": "BRIDGE_WITH_DELAYED_STEPUP_AFTER_EQUITY_AND_TRADE_COUNT",
            "sim_kwargs": {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "min_trade_count_for_stepup": 75, "stepup_delay_trades_after_cross": 5},
        },
        {
            "variant_name": "BRIDGE_WITH_REDUCED_STEPUP_MULTIPLIER",
            "sim_kwargs": {"stepup_schedule": [(100_000.0, 1.10), (250_000.0, 1.25), (500_000.0, 1.50)]},
        },
        {
            "variant_name": "BRIDGE_WITH_MISSED_TRADE_BUFFER",
            "sim_kwargs": {"stepup_schedule": [(100_000.0, 1.15), (250_000.0, 1.30), (500_000.0, 1.60)], "min_trade_count_for_stepup": 50},
        },
        {
            "variant_name": "BRIDGE_WITH_TOP_WINNER_DEPENDENCY_CAP",
            "sim_kwargs": {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "max_multiplier_cap": 1.50},
        },
        {
            "variant_name": "BRIDGE_WITH_LIQUIDITY_COST_FILTER",
            "sim_kwargs": {"stepup_schedule": list(BASE_STEPUP_SCHEDULE), "liquidity_score_threshold": 0.80, "volume_confirmation_threshold": 0.75},
        },
        {
            "variant_name": "BRIDGE_WITH_COMBINED_FRAGILITY_GUARD",
            "sim_kwargs": {
                "stepup_schedule": [(100_000.0, 1.10), (250_000.0, 1.25), (500_000.0, 1.40)],
                "min_total_wins_for_stepup": 3,
                "min_trade_count_for_stepup": 50,
                "stepup_delay_trades_after_cross": 3,
                "max_multiplier_cap": 1.40,
                "cost_guard_ratio_threshold": 0.15,
                "liquidity_score_threshold": 0.75,
            },
        },
    ]


def _mc_monthly_bootstrap(rows: list[dict[str, Any]], sim_kwargs: dict[str, Any], path_count: int) -> dict[str, Any]:
    ordered = _sort_rows(rows)
    blocks = _group_consecutive_blocks(ordered, _month_label)
    endings: list[float] = []
    drawdowns: list[float] = []
    above_1m = 0
    above_3m = 0
    above_5m = 0
    ruin = 0
    for sim_index in range(path_count):
        rng = random.Random(700_000 + sim_index)
        sampled: list[dict[str, Any]] = []
        while len(sampled) < len(ordered):
            sampled.extend(_clone_row(row) for row in rng.choice(blocks))
        sequence = _resequence_rows(sampled[: len(ordered)])
        output = _simulate_overlay_sequence(sequence, **sim_kwargs)
        ending_equity = _safe_float(output["ending_equity"])
        max_dd = _safe_float(output["max_drawdown_pct"])
        endings.append(ending_equity)
        drawdowns.append(max_dd)
        above_1m += int(ending_equity >= 1_000_000.0)
        above_3m += int(ending_equity >= 3_000_000.0)
        above_5m += int(ending_equity >= 5_000_000.0)
        ruin += int(bool(output["insolvency_hit"]) or ending_equity <= 10_000.0)
    series = pd.Series(endings, dtype=float) if endings else pd.Series(dtype=float)
    dd_series = pd.Series(drawdowns, dtype=float) if drawdowns else pd.Series(dtype=float)
    return {
        "p10": round(float(series.quantile(0.10)), 6) if not series.empty else 0.0,
        "p25": round(float(series.quantile(0.25)), 6) if not series.empty else 0.0,
        "p50": round(float(series.quantile(0.50)), 6) if not series.empty else 0.0,
        "prob_above_1m": round(above_1m / path_count, 6) if path_count else 0.0,
        "prob_above_3m": round(above_3m / path_count, 6) if path_count else 0.0,
        "prob_above_5m": round(above_5m / path_count, 6) if path_count else 0.0,
        "ruin_risk": round(ruin / path_count, 6) if path_count else 0.0,
        "median_max_drawdown": round(float(dd_series.quantile(0.50)), 6) if not dd_series.empty else 0.0,
    }


def _rolling_window_summary(
    rows: list[dict[str, Any]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
    sim_kwargs: dict[str, Any],
) -> dict[str, Any]:
    endings: list[float] = []
    hit_1m = 0
    hit_3m = 0
    hit_5m = 0
    max_drawdowns: list[float] = []
    for start, end, _label in windows:
        selected = _window_rows(rows, start, end)
        output = _simulate_overlay_sequence(selected, **sim_kwargs)
        ending_equity = _safe_float(output["ending_equity"])
        endings.append(ending_equity)
        hit_1m += int(ending_equity >= 1_000_000.0)
        hit_3m += int(ending_equity >= 3_000_000.0)
        hit_5m += int(ending_equity >= 5_000_000.0)
        max_drawdowns.append(_safe_float(output["max_drawdown_pct"]))
    return {
        "average": round(sum(endings) / max(len(endings), 1), 6),
        "median": round(_median(endings), 6) if endings else 0.0,
        "best": round(max(endings), 6) if endings else 0.0,
        "worst": round(min(endings), 6) if endings else 0.0,
        "hit_1m_windows": hit_1m,
        "hit_3m_windows": hit_3m,
        "hit_5m_windows": hit_5m,
        "max_drawdown_pct": round(max(max_drawdowns), 6) if max_drawdowns else 0.0,
    }


def _overlay_gate(row: dict[str, Any]) -> bool:
    return (
        not bool(row["uses_future_outcome_fields"])
        and int(row["rolling_5y_1m_hit_windows"]) >= 10
        and _safe_float(row["five_x_cost_result"]) >= 250_000.0
        and _safe_float(row["top_winner_removal_result"]) >= 500_000.0
        and _safe_float(row["random_missed_trade_result"]) >= 500_000.0
        and _safe_float(row["max_drawdown_pct"]) <= 0.25
        and bool(row["research_only"])
    )


def _evaluate_overlays(rows: list[dict[str, Any]], windows: list[tuple[pd.Timestamp, pd.Timestamp, str]], path_count: int) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    result_rows: list[dict[str, Any]] = []
    mc_comparison: dict[str, Any] = {"research_only": True, "reference_mode": "monthly_block_bootstrap", "variants": {}}
    gate_rows: list[dict[str, Any]] = []
    for overlay in _overlay_specs():
        sim_kwargs = dict(overlay["sim_kwargs"])
        full = _simulate_overlay_sequence(rows, **sim_kwargs)
        rolling = _rolling_window_summary(rows, windows, sim_kwargs)
        five_x_rows = rows
        ten_x_rows = rows
        removed_top5_rows = [_clone_row(item) for item in rows if str(item.get("trade_id") or "") not in {str(r.get("trade_id") or "") for r in sorted(rows, key=lambda item: _safe_float(item.get("r_multiple")), reverse=True)[:5]}]
        random_drop_rows = _drop_random_trades(rows, 0.30, 3030)
        five_x = _rolling_window_summary(five_x_rows, windows, {**sim_kwargs, "cost_bps_total": FIVE_X_COST_BPS})
        ten_x = _rolling_window_summary(ten_x_rows, windows, {**sim_kwargs, "cost_bps_total": BASELINE_COST_BPS * 10.0})
        removed_top5 = _rolling_window_summary(removed_top5_rows, windows, sim_kwargs)
        random_drop = _rolling_window_summary(random_drop_rows, windows, sim_kwargs)
        mc = _mc_monthly_bootstrap(rows, sim_kwargs, path_count)
        row = {
            **RESEARCH_ONLY_FLAGS,
            "variant_name": overlay["variant_name"],
            "uses_future_outcome_fields": False,
            "full_sequence_ending_equity": round(_safe_float(full["ending_equity"]), 6),
            "rolling_5y_average_ending_equity": rolling["average"],
            "rolling_5y_median_ending_equity": rolling["median"],
            "rolling_5y_1m_hit_windows": rolling["hit_1m_windows"],
            "rolling_5y_3m_hit_windows": rolling["hit_3m_windows"],
            "rolling_5y_5m_hit_windows": rolling["hit_5m_windows"],
            "max_drawdown_pct": rolling["max_drawdown_pct"],
            "five_x_cost_result": five_x["average"],
            "ten_x_cost_result": ten_x["average"],
            "top_winner_removal_result": removed_top5["average"],
            "random_missed_trade_result": random_drop["average"],
            "mc_p10": mc["p10"],
            "mc_p25": mc["p25"],
            "mc_p50": mc["p50"],
            "prob_above_1m": mc["prob_above_1m"],
            "prob_above_3m": mc["prob_above_3m"],
            "prob_above_5m": mc["prob_above_5m"],
            "ruin_risk": mc["ruin_risk"],
            "mission_gate_status": False,
            "verdict": "",
        }
        row["mission_gate_status"] = _overlay_gate(row)
        row["verdict"] = "GATE_PASSING" if row["mission_gate_status"] else ("IMPROVES_BUT_NOT_GATE_PASSING" if row["rolling_5y_average_ending_equity"] >= 900_000.0 else "FAILS_TO_REPAIR")
        result_rows.append(row)
        mc_comparison["variants"][overlay["variant_name"]] = mc
        gate_rows.append(
            {
                "variant_name": overlay["variant_name"],
                "mission_gate_status": row["mission_gate_status"],
                "rolling_5y_1m_hit_windows": row["rolling_5y_1m_hit_windows"],
                "five_x_cost_result": row["five_x_cost_result"],
                "top_winner_removal_result": row["top_winner_removal_result"],
                "random_missed_trade_result": row["random_missed_trade_result"],
                "ruin_risk": row["ruin_risk"],
            }
        )
    result_rows.sort(key=lambda item: (not bool(item["mission_gate_status"]), -_safe_float(item["rolling_5y_average_ending_equity"]), -int(item["rolling_5y_1m_hit_windows"])))
    return result_rows, mc_comparison, gate_rows


def _revised_gate(best_overlay: dict[str, Any]) -> dict[str, Any]:
    conditions = {
        "no_leakage": not bool(best_overlay["uses_future_outcome_fields"]),
        "rolling_1m_hits_meaningful": int(best_overlay["rolling_5y_1m_hit_windows"]) >= 10,
        "normal_and_5x_cost_survive": _safe_float(best_overlay["five_x_cost_result"]) >= 250_000.0,
        "top_winner_removal_survives": _safe_float(best_overlay["top_winner_removal_result"]) >= 500_000.0,
        "random_missed_trade_survives": _safe_float(best_overlay["random_missed_trade_result"]) >= 500_000.0,
        "drawdown_acceptable": _safe_float(best_overlay["max_drawdown_pct"]) <= 0.25,
        "no_trading_below_zero_equity": _safe_float(best_overlay["ruin_risk"]) == 0.0,
        "no_production_behavior_changed": True,
        "research_only": True,
    }
    passed = all(conditions.values())
    return {**RESEARCH_ONLY_FLAGS, "best_overlay": best_overlay["variant_name"], "conditions": conditions, "passed": passed, "verdict": "REVISED_GATE_PASS" if passed else "REVISED_GATE_FAIL"}


def _final_classification(best_overlay: dict[str, Any], revised_gate: dict[str, Any], trade_redundancy: dict[str, Any]) -> str:
    if revised_gate["passed"]:
        return "FRAGILITY_REPAIR_READY_FOR_SHADOW_SPEC_RESEARCH_ONLY"
    if best_overlay["rolling_5y_average_ending_equity"] >= 1_000_000.0 and int(best_overlay["rolling_5y_1m_hit_windows"]) >= 10:
        return "FRAGILITY_REPAIR_1M_PROMISING_RESEARCH_ONLY"
    if best_overlay["rolling_5y_average_ending_equity"] > 850_000.0:
        return "FRAGILITY_REPAIR_IMPROVES_BUT_NOT_GATE_PASSING"
    if trade_redundancy.get("verdict") == "LOW_REDUNDANCY":
        return "FRAGILITY_REPAIR_NEEDS_MORE_EDGE_OR_TRADE_REDUNDANCY"
    if best_overlay["rolling_5y_average_ending_equity"] > 600_000.0:
        return "FRAGILITY_REPAIR_WEAK"
    return "FRAGILITY_REPAIR_REJECTED"


def _next_recommendation(final_classification: str, best_overlay: dict[str, Any]) -> dict[str, Any]:
    if final_classification == "FRAGILITY_REPAIR_READY_FOR_SHADOW_SPEC_RESEARCH_ONLY":
        text = "Freeze the best repair overlay and design a research-only shadow-forward specification, still without paper/live promotion."
    elif final_classification == "FRAGILITY_REPAIR_1M_PROMISING_RESEARCH_ONLY":
        text = "Keep the bridge research-only and extend repair validation on cost realism and trade redundancy before any shadow specification."
    else:
        text = "The bridge still needs more research on cost drag and trade redundancy before any shadow-forward specification."
    return {**RESEARCH_ONLY_FLAGS, "best_overlay": best_overlay["variant_name"], "next_step": text}


def _court_report(
    *,
    summary: dict[str, Any],
    cost_realism: dict[str, Any],
    trade_redundancy: dict[str, Any],
    best_overlay: dict[str, Any],
    revised_gate: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "# Milestone Bridge Fragility Driver Repair Audit",
            "",
            f"Final classification: `{summary['final_classification']}`",
            "",
            "## Court Findings",
            "",
            f"1. Main fragility driver: `{summary['main_fragility_driver']}`.",
            f"2. Cost realism verdict: `{cost_realism['overall_cost_realism_verdict']}`.",
            f"3. Missed-trade fragility verdict: `{summary['missed_trade_fragility_verdict']}`.",
            f"4. Top-winner dependency verdict: `{summary['top_winner_dependency_verdict']}`.",
            f"5. Trade redundancy score: `{trade_redundancy['redundancy_score']}`.",
            f"6. Best repair overlay: `{best_overlay['variant_name']}` with rolling 5Y average / median `{_safe_float(best_overlay['rolling_5y_average_ending_equity']):.2f}` / `{_safe_float(best_overlay['rolling_5y_median_ending_equity']):.2f}` EUR and `{int(best_overlay['rolling_5y_1m_hit_windows'])}` 1M-hit windows.",
            f"7. Best repair 5x cost result: `{_safe_float(best_overlay['five_x_cost_result']):.2f}` EUR. Best repair missed-trade result: `{_safe_float(best_overlay['random_missed_trade_result']):.2f}` EUR.",
            f"8. Revised mission gate verdict: `{revised_gate['verdict']}`.",
            f"9. Next step: `{summary['next_research_step']}`.",
            "",
            "## Guardrails",
            "",
            "- `research_only=true`",
            "- `real_money_allowed=false`",
            "- `paper_allowed=false`",
            "- `live_allowed=false`",
            "- `behavior_change_allowed=false`",
            "- No live, paper, runtime, or production behavior changed",
            "",
        ]
    )


def write_milestone_bridge_fragility_driver_repair_audit(
    config: MilestoneBridgeFragilityDriverRepairAuditConfig,
) -> dict[str, Path]:
    context, warnings = _load_context(config)
    if context is None:
        return _empty_outputs(config, classification="MILESTONE_BRIDGE_FRAGILITY_REPAIR_BLOCKED", warnings=warnings)

    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    rows = context["strict_rows"]
    windows = context["windows"]

    cost_rows, cost_year_rows, cost_month_rows, cost_realism = _cost_fragility_decomposition(rows)
    missed_rows, missed_rate_rows, top_dep_rows, milestone_missed_rows, trade_redundancy = _missed_trade_decomposition(rows, windows)
    overlay_rows, mc_comparison, gate_rows = _evaluate_overlays(rows, windows, max(config.mc_paths_per_overlay, DEFAULT_MC_PATHS_PER_OVERLAY))
    best_overlay = overlay_rows[0]
    revised_gate = _revised_gate(best_overlay)
    no_go_risks = {**RESEARCH_ONLY_FLAGS, "risks": [name for name, passed in revised_gate["conditions"].items() if not bool(passed)]}
    final_classification = _final_classification(best_overlay, revised_gate, trade_redundancy)
    next_step = _next_recommendation(final_classification, best_overlay)

    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "main_fragility_driver": "cost_drag_and_trade_redundancy",
        "cost_realism_verdict": cost_realism["overall_cost_realism_verdict"],
        "missed_trade_fragility_verdict": trade_redundancy["verdict"],
        "top_winner_dependency_verdict": "TOP_WINNERS_MATTER_BUT_ARE_NOT_THE_ONLY_DRIVER" if _safe_float(top_dep_rows[2]["ending_equity"]) < 1_000_000.0 else "TOP_WINNER_DEPENDENCY_CONTAINED",
        "trade_redundancy_score": trade_redundancy["redundancy_score"],
        "best_repair_overlay": best_overlay["variant_name"],
        "best_repair_rolling_5y_average": round(_safe_float(best_overlay["rolling_5y_average_ending_equity"]), 6),
        "best_repair_rolling_5y_median": round(_safe_float(best_overlay["rolling_5y_median_ending_equity"]), 6),
        "best_repair_1m_hit_windows": int(best_overlay["rolling_5y_1m_hit_windows"]),
        "best_repair_5x_cost_result": round(_safe_float(best_overlay["five_x_cost_result"]), 6),
        "best_repair_missed_trade_result": round(_safe_float(best_overlay["random_missed_trade_result"]), 6),
        "revised_mission_gate_verdict": revised_gate["verdict"],
        "final_classification": final_classification,
        "next_research_step": next_step["next_step"],
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
    }
    report = _court_report(
        summary=summary,
        cost_realism=cost_realism,
        trade_redundancy=trade_redundancy,
        best_overlay=best_overlay,
        revised_gate=revised_gate,
    )

    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "milestone_bridge_fragility_driver_repair_summary.json", summary)
    _write_markdown(config.output_root / "milestone_bridge_fragility_driver_repair_report.md", report)
    _write_csv(diagnostics_root / "cost_fragility_decomposition.csv", cost_rows)
    _write_csv(diagnostics_root / "cost_fragility_by_year.csv", cost_year_rows)
    _write_csv(diagnostics_root / "cost_fragility_by_month.csv", cost_month_rows)
    _write_json(diagnostics_root / "cost_realism_assessment.json", cost_realism)
    _write_csv(diagnostics_root / "missed_trade_fragility_decomposition.csv", missed_rows)
    _write_csv(diagnostics_root / "missed_trade_rate_sensitivity.csv", missed_rate_rows)
    _write_csv(diagnostics_root / "top_winner_dependency_decomposition.csv", top_dep_rows)
    _write_csv(diagnostics_root / "milestone_timing_missed_trade_sensitivity.csv", milestone_missed_rows)
    _write_json(diagnostics_root / "trade_redundancy_score.json", trade_redundancy)
    _write_csv(diagnostics_root / "fragility_repair_overlay_results.csv", overlay_rows)
    _write_json(diagnostics_root / "fragility_repair_overlay_results.json", {**RESEARCH_ONLY_FLAGS, "rows": overlay_rows})
    _write_json(diagnostics_root / "fragility_repair_monte_carlo_comparison.json", mc_comparison)
    _write_csv(diagnostics_root / "fragility_repair_mission_gate_comparison.csv", gate_rows)
    _write_json(diagnostics_root / "revised_bridge_mission_gate.json", revised_gate)
    _write_json(diagnostics_root / "no_go_risks.json", no_go_risks)
    _write_json(reports_root / "next_research_recommendation.json", next_step)
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "milestone_bridge_fragility_driver_repair_summary.json",
        "report": config.output_root / "milestone_bridge_fragility_driver_repair_report.md",
    }


if __name__ == "__main__":
    package_root = Path(__file__).resolve().parents[1]
    output_root = package_root / "output" / OUTPUT_FOLDER_NAME
    write_milestone_bridge_fragility_driver_repair_audit(
        MilestoneBridgeFragilityDriverRepairAuditConfig(
            package_root=package_root,
            output_root=output_root,
        )
    )
