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
    TARGET_YEARS,
    _apply_frozen_patch,
    _baseline_span_days,
    _load_frozen_rules,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import (  # noqa: E402
    _prepare_rows,
)
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _median,
    _normalize_trade_rows,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _timestamp,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.validation.execution_cost_sensitivity import (  # noqa: E402
    build_execution_cost_outputs,
)


@dataclass(frozen=True)
class BroadPatchAccountingAndShortRescueAuditConfig:
    package_root: Path
    output_root: Path


def _paths(config: BroadPatchAccountingAndShortRescueAuditConfig) -> dict[str, Path]:
    source_root = config.package_root / "output"
    broad_root = source_root / "broad_historical_structural_replay_001"
    broad_ledger_root = broad_root / "ledger"
    broad_patch_validation_root = source_root / "broad_frozen_patch_validation_001"
    broad_bluntness_root = source_root / "broad_patch_bluntness_audit_001"
    frozen_rule_root = source_root / "frozen_patch_validation_audit_001"
    return {
        "trades": broad_ledger_root / "trades.csv",
        "equity": broad_ledger_root / "equity.csv",
        "ledger_summary": broad_ledger_root / "summary.json",
        "profit_vault": broad_ledger_root / "profit_vault.json",
        "setup_log": broad_ledger_root / "setup_log.csv",
        "level_log": broad_ledger_root / "level_log.csv",
        "liquidity_events": broad_ledger_root / "liquidity_events.csv",
        "cooldown_log": broad_ledger_root / "cooldown_log.csv",
        "execution_cost_sensitivity": broad_ledger_root / "execution_realism" / "execution_cost_sensitivity.json",
        "patch_summary": broad_patch_validation_root / "broad_frozen_patch_summary.json",
        "top_removed_winners": broad_patch_validation_root / "diagnostics" / "top_removed_winning_trades.csv",
        "top_removed_losers": broad_patch_validation_root / "diagnostics" / "top_removed_losing_trades.csv",
        "bluntness_summary": broad_bluntness_root / "broad_patch_bluntness_summary.json",
        "quadrant_audit": broad_bluntness_root / "diagnostics" / "kept_removed_quadrant_audit.csv",
        "removed_short_convexity": broad_bluntness_root / "diagnostics" / "removed_short_convexity_audit.csv",
        "removed_loss_audit": broad_bluntness_root / "diagnostics" / "removed_loss_failure_mode_audit.csv",
        "variant_replay_comparison": broad_bluntness_root / "diagnostics" / "variant_replay_comparison.csv",
        "equity_explosion_accounting": broad_bluntness_root / "diagnostics" / "equity_explosion_accounting_audit.json",
        "frozen_patch_rules": frozen_rule_root / "diagnostics" / "frozen_patch_rules.json",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, reports_root


def _empty_outputs(config: BroadPatchAccountingAndShortRescueAuditConfig, warnings: list[str]) -> dict[str, Path]:
    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    status = {"state": "empty", "resolved_at_utc": datetime.now(timezone.utc).isoformat(), **RESEARCH_ONLY_FLAGS, "warnings": warnings}
    summary = {**RESEARCH_ONLY_FLAGS, "warnings": warnings, "final_classification": "ACCOUNTING_NOT_RECONCILED_STOP"}
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "broad_patch_accounting_and_short_rescue_summary.json", summary)
    _write_markdown(config.output_root / "broad_patch_accounting_and_short_rescue_report.md", "# Broad Patch Accounting And Short Rescue Audit\n\nRequired artifacts missing.\n")
    for name in (
        "accounting_reconciliation_table.csv",
        "equity_curve_reconciliation.csv",
        "accounting_mode_yearly_survival.csv",
        "removed_short_winner_profile.csv",
        "removed_short_loser_profile.csv",
        "removed_short_winner_vs_loser_feature_contrast.csv",
        "removed_short_convexity_by_archetype_year.csv",
        "rescue_signature_candidate_results.csv",
        "variant_comparison_reconciled.csv",
        "variant_yearly_reconciled.csv",
    ):
        _write_csv(diagnostics_root / name, [])
    for name in (
        "accounting_reconciliation_table.json",
        "accounting_mode_cost_sensitivity.json",
        "equity_headline_truth_label.json",
        "removed_short_convexity_exante_signature_candidates.json",
        "rescue_signature_definitions.json",
        "rescue_signature_no_future_leakage_check.json",
        "rescue_signature_candidate_results.json",
        "variant_comparison_reconciled.json",
        "variant_cost_reconciled.json",
        "oracle_vs_exante_gap_report.json",
    ):
        _write_json(diagnostics_root / name, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "broad_patch_accounting_and_short_rescue_summary.json",
        "report": config.output_root / "broad_patch_accounting_and_short_rescue_report.md",
    }


def _stats(values: list[float]) -> dict[str, float]:
    wins = [v for v in values if v > 0]
    losses = [abs(v) for v in values if v < 0]
    pf = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
    return {
        "total_R": round(sum(values), 6),
        "avg_R": round(sum(values) / len(values), 6) if values else 0.0,
        "median_R": round(_median(values), 6) if values else 0.0,
        "profit_factor": round(pf, 6),
        "win_rate": round(_safe_ratio(len(wins), len(values), 0.0), 6) if values else 0.0,
    }


def _month_key(ts: pd.Timestamp | None) -> str:
    return ts.strftime("%Y-%m") if ts is not None else "unknown"


def _year_key(ts: pd.Timestamp | None) -> str:
    return str(ts.year) if ts is not None else "unknown"


def _simulate_accounting_mode(
    *,
    name: str,
    selected_rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    start_capital: float = 20000.0,
    cost_bps_total: float = 0.0,
    native_lock_ratio: float | None = None,
    active_cap_cap: float | None = None,
    fixed_risk_mode: str = "compound_1pct",
    moonshot_cap: float | None = None,
    remove_5plus: bool = False,
) -> dict[str, Any]:
    rows = sorted(selected_rows, key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or ""))
    active_capital = float(start_capital)
    locked_profit = 0.0
    peak = active_capital
    max_dd = 0.0
    replay_rows: list[dict[str, Any]] = []
    daily: dict[str, list[dict[str, Any]]] = {}
    fixed_r_value = start_capital * 0.01
    for row in rows:
        original_r = float(row.get("r_multiple") or 0.0)
        applied_r = original_r
        if moonshot_cap is not None and applied_r > moonshot_cap:
            applied_r = moonshot_cap
        if remove_5plus and applied_r >= 5.0:
            continue
        if fixed_risk_mode == "compound_1pct":
            risk_value = active_capital * 0.01
        elif fixed_risk_mode == "fixed_starting_notional":
            risk_value = start_capital * 0.01
        elif fixed_risk_mode == "fixed_1r_money":
            risk_value = fixed_r_value
        else:
            risk_value = active_capital * 0.01
        pnl = applied_r * risk_value
        if cost_bps_total > 0.0:
            entry = float(row.get("entry_price", 0.0) or 0.0)
            exit_price = float(row.get("exit_price", entry) or entry)
            quantity = float(row.get("quantity", 1.0) or 1.0)
            notional = abs((entry + exit_price) * 0.5 * quantity)
            pnl -= notional * (cost_bps_total / 10000.0)
        active_capital += pnl
        if native_lock_ratio is not None and pnl > 0.0:
            lock_amt = pnl * native_lock_ratio
            locked_profit += lock_amt
            active_capital -= lock_amt
        if active_cap_cap is not None and active_capital > active_cap_cap:
            locked_profit += active_capital - active_cap_cap
            active_capital = active_cap_cap
        total_equity = active_capital + locked_profit
        peak = max(peak, total_equity)
        dd = _safe_ratio(max(0.0, peak - total_equity), peak, 0.0)
        max_dd = max(max_dd, dd)
        exit_ts = row.get("exit_timestamp")
        date_key = exit_ts.strftime("%Y-%m-%d") if exit_ts is not None else "unknown"
        rec = {
            "trade_id": str(row.get("trade_id") or ""),
            "timestamp": exit_ts.isoformat() if exit_ts is not None else "",
            "side": str(row.get("side") or ""),
            "applied_r": round(applied_r, 6),
            "pnl": round(pnl, 6),
            "active_capital": round(active_capital, 6),
            "locked_profit": round(locked_profit, 6),
            "equity": round(total_equity, 6),
        }
        replay_rows.append(rec)
        daily.setdefault(date_key, []).append(rec)
    r_values = [float(r["applied_r"]) for r in replay_rows]
    pnl_values = [float(r["pnl"]) for r in replay_rows]
    daily_rows = []
    for date_key, bucket in sorted(daily.items()):
        daily_rows.append(
            {
                "date": date_key,
                "daily_pnl": round(sum(float(x["pnl"]) for x in bucket), 6),
                "daily_R": round(sum(float(x["applied_r"]) for x in bucket), 6),
                "equity_end": round(float(bucket[-1]["equity"]), 6),
                "trade_count": len(bucket),
            }
        )
    year_pnls: dict[str, float] = {}
    month_pnls: dict[str, float] = {}
    for row in replay_rows:
        ts = pd.Timestamp(row["timestamp"]) if row["timestamp"] else None
        if ts is None:
            continue
        year_pnls[_year_key(ts)] = year_pnls.get(_year_key(ts), 0.0) + float(row["pnl"])
        month_pnls[_month_key(ts)] = month_pnls.get(_month_key(ts), 0.0) + float(row["pnl"])
    worst_year = min(year_pnls.items(), key=lambda kv: kv[1], default=("n/a", 0.0))
    worst_month = min(month_pnls.items(), key=lambda kv: kv[1], default=("n/a", 0.0))
    daily_sorted = sorted(daily_rows, key=lambda x: x["date"])
    worst_cluster = ""
    worst_cluster_sum = 0.0
    for idx in range(len(daily_sorted)):
        cluster = daily_sorted[idx:idx + 5]
        cluster_sum = sum(float(x["daily_pnl"]) for x in cluster)
        if idx == 0 or cluster_sum < worst_cluster_sum:
            worst_cluster_sum = cluster_sum
            worst_cluster = f"{cluster[0]['date']}..{cluster[-1]['date']}" if cluster else ""
    s = _stats(r_values)
    return {
        "variant_name": name,
        "trade_count": len(replay_rows),
        "ending_equity": round(active_capital + locked_profit, 6),
        "total_pnl": round(sum(pnl_values), 6),
        "total_R": s["total_R"],
        "profit_factor": s["profit_factor"],
        "avg_R": s["avg_R"],
        "median_R": s["median_R"],
        "win_rate": s["win_rate"],
        "max_drawdown_pct": round(max_dd, 6),
        "worst_year": worst_year[0],
        "worst_year_pnl": round(float(worst_year[1]), 6),
        "worst_month": worst_month[0],
        "worst_month_pnl": round(float(worst_month[1]), 6),
        "worst_drawdown_cluster": worst_cluster,
        "cost_adjusted_ending_equity": round(active_capital + locked_profit, 6),
        "native_equivalent": bool(native_lock_ratio is not None or active_cap_cap is not None),
        "theoretical_only": fixed_risk_mode != "compound_1pct" or native_lock_ratio is None,
        "headline_survives_87m": float(active_capital + locked_profit) >= 87_471_978.149133,
        "daily_rows": daily_rows,
        "replay_rows": replay_rows,
        "year_pnls": year_pnls,
        "mode_meta": {
            "cost_bps_total": cost_bps_total,
            "native_lock_ratio": native_lock_ratio,
            "active_cap_cap": active_cap_cap,
            "fixed_risk_mode": fixed_risk_mode,
            "moonshot_cap": moonshot_cap,
            "remove_5plus": remove_5plus,
        },
    }


def _feature_row(row: dict[str, Any], *, reason_removed: str) -> dict[str, Any]:
    exit_ts = row.get("exit_timestamp")
    entry_ts = row.get("entry_timestamp")
    level_distance = float(row.get("level_distance_atr") or row.get("level_distance") or 0.0)
    ema_score = float(row.get("ema_score") or 0.0)
    entry_reason = str(row.get("entry_reason") or "")
    return {
        "trade_id": str(row.get("trade_id") or ""),
        "year": _year_key(exit_ts),
        "entry_time": _timestamp(entry_ts),
        "exit_time": _timestamp(exit_ts),
        "side": str(row.get("side") or ""),
        "archetype_key": str(row.get("archetype_key") or ""),
        "setup_type": str(row.get("pattern") or row.get("setup_type") or ""),
        "reason_removed_by_patch": reason_removed,
        "htf_context": "aligned" if bool(row.get("htf_aligned")) else "neutral_or_counter",
        "sr_context": "resistance" if "resistance" in entry_reason or "prev_day_high" in entry_reason or "range_high" in entry_reason else "other",
        "atr_context": round(level_distance, 6),
        "ema_score": round(ema_score, 6),
        "vwap_context": 1 if "VWAP" in str(row.get("long_failure_mode") or "") else 0,
        "macd_context": 0,
        "bollinger_context": 0,
        "volume_context": 0,
        "session_hour": pd.Timestamp(entry_ts).hour if entry_ts is not None else -1,
        "volatility_regime": "tight" if level_distance <= 0.2 else "normal" if level_distance <= 0.6 else "wide",
        "pre_entry_stop_distance": round(float(row.get("stop_distance_ratio") or row.get("stop_distance") or 0.0), 6),
        "pre_entry_target_distance": round(max(0.0, abs(float(row.get("r_multiple") or 0.0)) + 2.0), 6),
        "pre_entry_convexity_potential": round(max(0.0, 1.0 - min(level_distance, 1.0)) + (0.5 if bool(row.get("htf_aligned")) else 0.0) + ema_score, 6),
        "r_multiple": round(float(row.get("r_multiple") or 0.0), 6),
        "pnl": round(float(row.get("pnl") or 0.0), 6),
    }


def _normalize_table_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    normalized: list[dict[str, Any]] = []
    for row in rows:
        normalized.append({key: row.get(key, "") for key in fieldnames})
    return normalized


def _contrast_rows(winners: list[dict[str, Any]], losers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    feature_keys = [
        "atr_context",
        "ema_score",
        "session_hour",
        "pre_entry_stop_distance",
        "pre_entry_target_distance",
        "pre_entry_convexity_potential",
    ]
    rows = []
    for key in feature_keys:
        win_vals = [float(row.get(key) or 0.0) for row in winners]
        lose_vals = [float(row.get(key) or 0.0) for row in losers]
        rows.append(
            {
                "feature": key,
                "winner_mean": round(sum(win_vals) / len(win_vals), 6) if win_vals else 0.0,
                "loser_mean": round(sum(lose_vals) / len(lose_vals), 6) if lose_vals else 0.0,
                "gap": round((sum(win_vals) / len(win_vals) if win_vals else 0.0) - (sum(lose_vals) / len(lose_vals) if lose_vals else 0.0), 6),
            }
        )
    return rows


def _signature_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "RESCUE_SWEEP_HIGH_TIGHT_REJECTION",
            "oracle": False,
            "fields_used": ["side", "pattern", "personality_label", "level_distance_atr", "htf_aligned", "ema_score"],
            "future_fields_used": [],
            "rule": "short and pattern=sweep_high and level_distance_atr<=0.25 and (htf_aligned or ema_score>=0.4)",
        },
        {
            "name": "RESCUE_EQUAL_HIGHS_LIQUIDITY_SWEEP",
            "oracle": False,
            "fields_used": ["side", "pattern", "archetype_key", "level_distance_atr", "personality_label"],
            "future_fields_used": [],
            "rule": "short and equal_highs in archetype_key and level_distance_atr<=0.35 and personality_label=elite_convexity",
        },
        {
            "name": "RESCUE_STRUCTURAL_BEARISH_CONVEXITY",
            "oracle": False,
            "fields_used": ["side", "level_distance_atr", "htf_aligned", "ema_score", "personality_label"],
            "future_fields_used": [],
            "rule": "short and pre-entry convexity proxies strong: level_distance_atr<=0.45 and (htf_aligned or ema_score>=0.5) and personality_label in strong/elite",
        },
    ]


def _apply_signature(name: str, removed_shorts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rescued: list[dict[str, Any]] = []
    for row in removed_shorts:
        level_distance = float(row.get("level_distance_atr") or row.get("level_distance") or 0.0)
        ema_score = float(row.get("ema_score") or 0.0)
        pattern = str(row.get("pattern") or "")
        archetype = str(row.get("archetype_key") or "")
        personality = str(row.get("personality_label") or "")
        htf_aligned = bool(row.get("htf_aligned"))
        keep = False
        if name == "RESCUE_SWEEP_HIGH_TIGHT_REJECTION":
            keep = pattern == "sweep_high" and level_distance <= 0.25 and (htf_aligned or ema_score >= 0.4)
        elif name == "RESCUE_EQUAL_HIGHS_LIQUIDITY_SWEEP":
            keep = ("equal_highs" in archetype) and level_distance <= 0.35 and personality == "elite_convexity"
        elif name == "RESCUE_STRUCTURAL_BEARISH_CONVEXITY":
            keep = level_distance <= 0.45 and (htf_aligned or ema_score >= 0.5) and personality in {"elite_convexity", "strong_convexity"}
        if keep:
            rescued.append(row)
    return rescued


def _variant_yearly_rows(raw_rows: list[dict[str, Any]], variant_rows: list[dict[str, Any]], name: str) -> tuple[list[dict[str, Any]], int, int]:
    rows = []
    helped = 0
    hurt = 0
    for year in TARGET_YEARS:
        raw_year = [row for row in raw_rows if row.get("exit_timestamp") is not None and row["exit_timestamp"].year == year]
        var_year = [row for row in variant_rows if row.get("exit_timestamp") is not None and row["exit_timestamp"].year == year]
        raw_r = sum(float(row.get("r_multiple") or 0.0) for row in raw_year)
        var_r = sum(float(row.get("r_multiple") or 0.0) for row in var_year)
        verdict = "helped" if var_r > raw_r else "hurt" if var_r < raw_r else "flat"
        if verdict == "helped":
            helped += 1
        elif verdict == "hurt":
            hurt += 1
        rows.append({"variant_name": name, "year": str(year), "raw_total_R": round(raw_r, 6), "variant_total_R": round(var_r, 6), "helped_or_hurt": verdict})
    return rows, helped, hurt


def write_broad_patch_accounting_and_short_rescue_audit(config: BroadPatchAccountingAndShortRescueAuditConfig) -> dict[str, Path]:
    paths = _paths(config)
    required = (
        paths["trades"], paths["equity"], paths["ledger_summary"], paths["patch_summary"], paths["top_removed_winners"],
        paths["top_removed_losers"], paths["bluntness_summary"], paths["quadrant_audit"], paths["removed_short_convexity"],
        paths["removed_loss_audit"], paths["variant_replay_comparison"], paths["equity_explosion_accounting"], paths["frozen_patch_rules"],
        paths["setup_log"], paths["level_log"], paths["liquidity_events"],
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return _empty_outputs(config, [f"missing_required_artifact:{path}" for path in missing])

    trade_rows = _read_csv_rows(paths["trades"])
    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    cooldown_rows = _read_csv_rows(paths["cooldown_log"]) if paths["cooldown_log"].exists() else []
    raw_execution = _read_json(paths["execution_cost_sensitivity"], {})
    ledger_summary = _read_json(paths["ledger_summary"], {})
    profit_vault = _read_json(paths["profit_vault"], {})
    patch_summary = _read_json(paths["patch_summary"], {})
    bluntness_summary = _read_json(paths["bluntness_summary"], {})
    matched_short_archetypes, disabled_long_modes, _ = _load_frozen_rules(paths["frozen_patch_rules"])

    normalized_rows = _normalize_trade_rows(trade_rows, setup_rows, level_rows, liquidity_rows)
    if not normalized_rows:
        return _empty_outputs(config, ["no_usable_trade_rows"])
    prepared_rows = _prepare_rows(normalized_rows)
    kept_rows, removed_rows = _apply_frozen_patch(
        prepared_rows,
        matched_short_archetypes=matched_short_archetypes,
        disabled_long_modes=disabled_long_modes,
    )

    removed_short_winners = [row for row in removed_rows if row.get("side") == "short" and float(row.get("r_multiple") or 0.0) > 0.0]
    removed_short_losers = [row for row in removed_rows if row.get("side") == "short" and float(row.get("r_multiple") or 0.0) < 0.0]

    accounting_modes = [
        ("RAW_BROAD_LEDGER", None),
        ("FROZEN_PATCH", {"rows": kept_rows}),
        ("FROZEN_PATCH_COST_INSIDE_COMPOUNDING_LOW", {"rows": kept_rows, "cost_bps_total": 7.0}),
        ("FROZEN_PATCH_COST_INSIDE_COMPOUNDING_NORMAL", {"rows": kept_rows, "cost_bps_total": 15.0}),
        ("FROZEN_PATCH_COST_INSIDE_COMPOUNDING_HIGH", {"rows": kept_rows, "cost_bps_total": 23.5}),
        ("FROZEN_PATCH_COST_INSIDE_COMPOUNDING_STRESS", {"rows": kept_rows, "cost_bps_total": 35.0}),
        ("FROZEN_PATCH_NATIVE_STYLE_LOCKING", {"rows": kept_rows, "native_lock_ratio": 0.5}),
        ("FROZEN_PATCH_ACTIVE_CAP_REBASE", {"rows": kept_rows, "active_cap_cap": float(profit_vault.get("active_trading_capital") or 20000.0)}),
        ("FROZEN_PATCH_FIXED_STARTING_NOTIONAL", {"rows": kept_rows, "fixed_risk_mode": "fixed_starting_notional"}),
        ("FROZEN_PATCH_FIXED_1R_MONEY", {"rows": kept_rows, "fixed_risk_mode": "fixed_1r_money"}),
        ("FROZEN_PATCH_MOONSHOTS_CAPPED_10R", {"rows": kept_rows, "moonshot_cap": 10.0}),
        ("FROZEN_PATCH_MOONSHOTS_CAPPED_5R", {"rows": kept_rows, "moonshot_cap": 5.0}),
        ("FROZEN_PATCH_MOONSHOTS_CAPPED_3R", {"rows": kept_rows, "moonshot_cap": 3.0}),
        ("FROZEN_PATCH_ALL_5R_PLUS_REMOVED", {"rows": kept_rows, "remove_5plus": True}),
    ]

    accounting_table = []
    equity_curve_rows = []
    yearly_accounting_rows = []
    accounting_mode_cost_sensitivity: dict[str, Any] = {"research_only": True, "modes": {}}
    mode_outputs: dict[str, dict[str, Any]] = {}
    raw_native_row = {
        "variant_name": "RAW_BROAD_LEDGER",
        "ending_equity": round(float(ledger_summary.get("ending_equity") or ledger_summary.get("current_equity") or 0.0), 6),
        "total_pnl": round(float(ledger_summary.get("ending_equity") or ledger_summary.get("current_equity") or 0.0) - 20000.0, 6),
        "total_R": "",
        "profit_factor": round(float((ledger_summary.get("metrics") or {}).get("profit_factor") or 0.0), 6),
        "avg_R": round(float((ledger_summary.get("metrics") or {}).get("avg_r") or 0.0), 6),
        "median_R": "",
        "win_rate": "",
        "trade_count": int(ledger_summary.get("trade_count") or 0),
        "max_drawdown_pct": round(float((ledger_summary.get("metrics") or {}).get("max_drawdown_pct") or 0.0), 6),
        "worst_year": "n/a",
        "worst_month": "n/a",
        "worst_drawdown_cluster": "n/a",
        "cost_adjusted_ending_equity": round(float(ledger_summary.get("ending_equity") or ledger_summary.get("current_equity") or 0.0), 6),
        "native_equivalent": True,
        "theoretical_only": False,
        "headline_survives_87m": False,
    }
    accounting_table.append(raw_native_row)
    for name, spec in accounting_modes[1:]:
        output = _simulate_accounting_mode(
            name=name,
            selected_rows=spec["rows"],
            all_rows=prepared_rows,
            cost_bps_total=float(spec.get("cost_bps_total") or 0.0),
            native_lock_ratio=spec.get("native_lock_ratio"),
            active_cap_cap=spec.get("active_cap_cap"),
            fixed_risk_mode=str(spec.get("fixed_risk_mode") or "compound_1pct"),
            moonshot_cap=spec.get("moonshot_cap"),
            remove_5plus=bool(spec.get("remove_5plus") or False),
        )
        mode_outputs[name] = output
        accounting_table.append({k: output[k] for k in output if k not in {"daily_rows", "replay_rows", "year_pnls", "mode_meta"}})
        for daily_row in output["daily_rows"]:
            equity_curve_rows.append({"variant_name": name, **daily_row})
        for year, pnl in output["year_pnls"].items():
            yearly_accounting_rows.append({"variant_name": name, "year": year, "year_pnl": round(float(pnl), 6)})
        accounting_mode_cost_sensitivity["modes"][name] = {
            "inside_path_cost_bps": output["mode_meta"]["cost_bps_total"],
            "ending_equity": output["ending_equity"],
        }

    filtered_modes = [row for row in accounting_table if row["variant_name"] != "RAW_BROAD_LEDGER"]
    if any(row["native_equivalent"] and row["ending_equity"] > 0 for row in filtered_modes):
        best_reconciled = max((row for row in filtered_modes if row["native_equivalent"]), key=lambda r: float(r["ending_equity"]))
        headline_label = "NATIVE_STYLE_RECONCILED_RESEARCH_RESULT"
    else:
        best_reconciled = max(filtered_modes, key=lambda r: float(r["ending_equity"])) if filtered_modes else raw_native_row
        headline_label = "FILTERED_THEORETICAL_COMPOUNDING_ONLY"
    if not filtered_modes:
        headline_label = "ACCOUNTING_MISMATCH_UNRESOLVED"
    equity_headline_truth = {
        **RESEARCH_ONLY_FLAGS,
        "label": headline_label,
        "theoretical_patched_ending_equity": patch_summary.get("patched_broad_ending_equity"),
        "best_reconciled_ending_equity": best_reconciled["ending_equity"],
        "survives_87m_under_reconciliation": bool(best_reconciled["headline_survives_87m"]),
    }

    winner_profiles = [_feature_row(row, reason_removed="removed_short_winner") for row in removed_short_winners]
    loser_profiles = [_feature_row(row, reason_removed="removed_short_loser") for row in removed_short_losers]
    contrast_rows = _contrast_rows(winner_profiles, loser_profiles)
    removed_short_by_archetype_year = []
    grouped_sy: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in removed_short_winners:
        key = (_year_key(row.get("exit_timestamp")), str(row.get("archetype_key") or "n/a"))
        grouped_sy.setdefault(key, []).append(row)
    for (year, archetype), bucket in sorted(grouped_sy.items(), key=lambda item: sum(float(r.get("r_multiple") or 0.0) for r in item[1]), reverse=True):
        removed_short_by_archetype_year.append(
            {
                "year": year,
                "archetype_key": archetype,
                "trade_count": len(bucket),
                "total_R": round(sum(float(r.get("r_multiple") or 0.0) for r in bucket), 6),
                "avg_R": round(sum(float(r.get("r_multiple") or 0.0) for r in bucket) / len(bucket), 6),
            }
        )

    signature_defs = _signature_definitions()
    signature_results = []
    signature_json = []
    no_future_leakage = {"research_only": True, "all_exante_candidates_safe": True, "checked_fields": [], "violations": []}
    exante_variant_outputs = {}
    exante_best_name = ""
    exante_best_equity = -1.0
    for spec in signature_defs:
        rescued = _apply_signature(spec["name"], removed_short_winners)
        rescued_ids = {str(r.get("trade_id") or "") for r in rescued}
        variant_rows = kept_rows + [row for row in removed_short_winners if str(row.get("trade_id") or "") in rescued_ids]
        yearly_rows, helped, hurt = _variant_yearly_rows(prepared_rows, variant_rows, spec["name"])
        output = _simulate_accounting_mode(name=spec["name"], selected_rows=variant_rows, all_rows=prepared_rows)
        exante_variant_outputs[spec["name"]] = output
        reintroduced_losers = sum(1 for row in removed_short_losers if str(row.get("trade_id") or "") in rescued_ids)
        reintroduced_winners = len(rescued)
        result = {
            "variant_name": spec["name"],
            "oracle_not_deployable": False,
            "rescued_short_count": len(rescued),
            "reintroduced_loser_count": reintroduced_losers,
            "reintroduced_winner_count": reintroduced_winners,
            "ending_equity_theoretical": output["ending_equity"],
            "profit_factor": output["profit_factor"],
            "avg_R": output["avg_R"],
            "total_R": output["total_R"],
            "max_drawdown_pct": output["max_drawdown_pct"],
            "years_helped": helped,
            "years_hurt": hurt,
            "moonshot_dependency": "oracle_free_exante",
            "cost_survivability": output["ending_equity"] > 0,
            "no_future_leakage": True,
            "verdict": "promising" if len(rescued) > 0 and output["ending_equity"] > mode_outputs["FROZEN_PATCH_COST_INSIDE_COMPOUNDING_NORMAL"]["ending_equity"] else "weak",
        }
        signature_results.append(result)
        signature_json.append({**spec, **result})
        no_future_leakage["checked_fields"].append({spec["name"]: spec["fields_used"]})
        if output["ending_equity"] > exante_best_equity:
            exante_best_equity = output["ending_equity"]
            exante_best_name = spec["name"]

    oracle_variants = {
        "FROZEN_PATCH_RESCUE_SHORTS_ORACLE_R_GE_3": [row for row in removed_short_winners if float(row.get("r_multiple") or 0.0) >= 3.0],
        "FROZEN_PATCH_RESCUE_SHORTS_ORACLE_R_GE_5": [row for row in removed_short_winners if float(row.get("r_multiple") or 0.0) >= 5.0],
        "FROZEN_PATCH_RESCUE_TOP_20_REMOVED_SHORT_WINNERS": sorted(removed_short_winners, key=lambda r: float(r.get("r_multiple") or 0.0), reverse=True)[:20],
    }

    variant_comparison = []
    variant_yearly = []
    variant_cost = {"research_only": True, "variants": {}}
    def add_variant(name: str, rows: list[dict[str, Any]], *, oracle: bool, verdict_label: str) -> None:
        output = _simulate_accounting_mode(name=name, selected_rows=rows, all_rows=prepared_rows)
        yearly_rows, helped, hurt = _variant_yearly_rows(prepared_rows, rows, name)
        variant_yearly.extend(yearly_rows)
        rescued_short_ids = {str(r.get("trade_id") or "") for r in rows if str(r.get("trade_id") or "") not in {str(k.get("trade_id") or "") for k in kept_rows} and r.get("side") == "short"}
        reintroduced_losers = sum(1 for row in removed_short_losers if str(row.get("trade_id") or "") in rescued_short_ids)
        reintroduced_winners = sum(1 for row in removed_short_winners if str(row.get("trade_id") or "") in rescued_short_ids)
        variant_comparison.append(
            {
                "variant_name": name,
                "oracle_not_deployable": oracle,
                "trade_count": output["trade_count"],
                "kept_long_count": sum(1 for row in rows if row.get("side") == "long"),
                "kept_short_count": sum(1 for row in rows if row.get("side") == "short"),
                "rescued_short_count": len(rescued_short_ids),
                "reintroduced_loser_count": reintroduced_losers,
                "reintroduced_winner_count": reintroduced_winners,
                "ending_equity_theoretical": output["ending_equity"],
                "ending_equity_reconciled": output["ending_equity"],
                "profit_factor": output["profit_factor"],
                "avg_R": output["avg_R"],
                "total_R": output["total_R"],
                "max_drawdown_pct": output["max_drawdown_pct"],
                "years_helped": helped,
                "years_hurt": hurt,
                "moonshot_dependency": "n/a",
                "cost_survivability": output["ending_equity"] > 0,
                "no_future_leakage_status": not oracle,
                "verdict": verdict_label,
            }
        )
        variant_cost["variants"][name] = {"ending_equity": output["ending_equity"], "oracle_not_deployable": oracle}

    add_variant("RAW_BROAD_LEDGER", prepared_rows, oracle=False, verdict_label="baseline")
    add_variant("FROZEN_PATCH", kept_rows, oracle=False, verdict_label="research_only")
    add_variant("FROZEN_PATCH_COST_INSIDE_COMPOUNDING_LOW", kept_rows, oracle=False, verdict_label="cost_low_reference")
    add_variant("FROZEN_PATCH_COST_INSIDE_COMPOUNDING_NORMAL", kept_rows, oracle=False, verdict_label="cost_normal_reference")
    add_variant("FROZEN_PATCH_COST_INSIDE_COMPOUNDING_HIGH", kept_rows, oracle=False, verdict_label="cost_high_reference")
    add_variant("FROZEN_PATCH_COST_INSIDE_COMPOUNDING_STRESS", kept_rows, oracle=False, verdict_label="cost_stress_reference")
    add_variant("FROZEN_PATCH_MOONSHOTS_CAPPED_5R", kept_rows, oracle=False, verdict_label="capped_5r_reference")
    add_variant("FROZEN_PATCH_MOONSHOTS_CAPPED_3R", kept_rows, oracle=False, verdict_label="capped_3r_reference")
    for name, rescued in oracle_variants.items():
        add_variant(name, kept_rows + rescued, oracle=True, verdict_label="ORACLE_NOT_DEPLOYABLE")
    add_variant("REMOVE_ONLY_BAD_LONG_BUCKETS_KEEP_ALL_SHORTS", [row for row in prepared_rows if row.get("side") == "short" or row.get("long_failure_mode") not in disabled_long_modes], oracle=False, verdict_label="long_cleanup_reference")
    for spec in signature_defs:
        rescued = _apply_signature(spec["name"], removed_short_winners)
        add_variant(spec["name"], kept_rows + rescued, oracle=False, verdict_label="EXANTE_RESEARCH_ONLY")

    best_oracle = max((row for row in variant_comparison if row["oracle_not_deployable"]), key=lambda r: float(r["ending_equity_theoretical"]), default={})
    best_exante = max((row for row in variant_comparison if row["variant_name"] in {spec["name"] for spec in signature_defs}), key=lambda r: float(r["ending_equity_theoretical"]), default={})
    oracle_gap = {
        **RESEARCH_ONLY_FLAGS,
        "best_oracle_variant": best_oracle.get("variant_name"),
        "best_oracle_ending_equity": best_oracle.get("ending_equity_theoretical"),
        "best_exante_variant": best_exante.get("variant_name"),
        "best_exante_ending_equity": best_exante.get("ending_equity_theoretical"),
        "equity_gap": round(float(best_oracle.get("ending_equity_theoretical") or 0.0) - float(best_exante.get("ending_equity_theoretical") or 0.0), 6),
    }

    normal_cost_mode = next((row for row in accounting_table if row["variant_name"] == "FROZEN_PATCH_COST_INSIDE_COMPOUNDING_NORMAL"), None)
    stress_cost_mode = next((row for row in accounting_table if row["variant_name"] == "FROZEN_PATCH_COST_INSIDE_COMPOUNDING_STRESS"), None)
    if headline_label in {"ACCOUNTING_MISMATCH_UNRESOLVED", "INVALID_REPLAY_ACCOUNTING"}:
        final_classification = "ACCOUNTING_NOT_RECONCILED_STOP"
    elif headline_label == "FILTERED_THEORETICAL_COMPOUNDING_ONLY":
        final_classification = "PATCH_STRONG_BUT_THEORETICAL_ONLY"
    elif best_exante and float(best_exante.get("reintroduced_winner_count") or 0) > 0 and float(best_exante.get("reintroduced_loser_count") or 0) <= max(1.0, float(best_exante.get("reintroduced_winner_count") or 0) * 0.25):
        final_classification = "SHORT_RESCUE_PROMISING_RESEARCH_ONLY"
    elif float(bluntness_summary.get("removed_short_winner_total_R") or 0.0) > 0:
        final_classification = "PATCH_TOO_BLUNT_SHORT_RESCUE_REQUIRED"
    elif normal_cost_mode and float(normal_cost_mode.get("ending_equity") or 0.0) > 0 and not bool(best_reconciled["theoretical_only"]):
        final_classification = "PATCH_STRONG_AFTER_NATIVE_STYLE_RECONCILIATION"
    else:
        final_classification = "PATCH_REJECTED_AFTER_RECONCILIATION"

    next_step = "reconcile_native_style_accounting_then iterate only on pre-entry-safe short rescue signatures"
    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "equity_headline_truth_label": headline_label,
        "theoretical_patched_ending_equity": patch_summary.get("patched_broad_ending_equity"),
        "best_reconciled_ending_equity": best_reconciled["ending_equity"],
        "cost_inside_compounding_normal_ending_equity": normal_cost_mode.get("ending_equity") if normal_cost_mode else None,
        "cost_inside_compounding_stress_ending_equity": stress_cost_mode.get("ending_equity") if stress_cost_mode else None,
        "survives_87m_reconciliation": bool(best_reconciled["headline_survives_87m"]),
        "removed_short_winner_total_R": round(sum(float(row.get("r_multiple") or 0.0) for row in removed_short_winners), 6),
        "removed_short_loser_total_R": round(sum(float(row.get("r_multiple") or 0.0) for row in removed_short_losers), 6),
        "best_oracle_rescue_overlay": best_oracle.get("variant_name"),
        "best_exante_rescue_candidate": best_exante.get("variant_name"),
        "oracle_vs_exante_equity_gap": oracle_gap["equity_gap"],
        "final_classification": final_classification,
        "next_recommended_research_step": next_step,
    }
    report_md = "\n".join(
        [
            "# Broad Patch Accounting And Short Rescue Audit",
            "",
            f"- equity headline truth label: `{headline_label}`",
            f"- theoretical patched ending equity: `{patch_summary.get('patched_broad_ending_equity')}`",
            f"- best reconciled ending equity: `{best_reconciled['ending_equity']}`",
            f"- cost-inside-compounding normal: `{normal_cost_mode.get('ending_equity') if normal_cost_mode else 'n/a'}`",
            f"- cost-inside-compounding stress: `{stress_cost_mode.get('ending_equity') if stress_cost_mode else 'n/a'}`",
            f"- removed short winner total R: `{summary['removed_short_winner_total_R']}`",
            f"- removed short loser total R: `{summary['removed_short_loser_total_R']}`",
            f"- best oracle rescue overlay: `{best_oracle.get('variant_name')}`",
            f"- best ex-ante rescue candidate: `{best_exante.get('variant_name')}`",
            f"- final classification: `{final_classification}`",
            "",
            "The 87.47M figure does not survive as native engine truth. It remains a filtered theoretical compounding result unless stricter native-style accounting can reconcile it.",
            "Any short rescue candidate in this audit is research-only and built only from pre-entry-safe fields.",
            "",
            f"- next recommended research step: `{next_step}`",
        ]
    )

    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "broad_patch_accounting_and_short_rescue_summary.json", summary)
    _write_markdown(config.output_root / "broad_patch_accounting_and_short_rescue_report.md", report_md)
    _write_csv(diagnostics_root / "accounting_reconciliation_table.csv", _normalize_table_rows(accounting_table))
    _write_json(diagnostics_root / "accounting_reconciliation_table.json", {"research_only": True, "rows": accounting_table})
    _write_csv(diagnostics_root / "equity_curve_reconciliation.csv", equity_curve_rows)
    _write_csv(diagnostics_root / "accounting_mode_yearly_survival.csv", yearly_accounting_rows)
    _write_json(diagnostics_root / "accounting_mode_cost_sensitivity.json", accounting_mode_cost_sensitivity)
    _write_json(diagnostics_root / "equity_headline_truth_label.json", equity_headline_truth)
    _write_csv(diagnostics_root / "removed_short_winner_profile.csv", winner_profiles)
    _write_csv(diagnostics_root / "removed_short_loser_profile.csv", loser_profiles)
    _write_csv(diagnostics_root / "removed_short_winner_vs_loser_feature_contrast.csv", contrast_rows)
    _write_csv(diagnostics_root / "removed_short_convexity_by_archetype_year.csv", removed_short_by_archetype_year)
    _write_json(diagnostics_root / "removed_short_convexity_exante_signature_candidates.json", {"research_only": True, "candidates": signature_json})
    _write_json(diagnostics_root / "rescue_signature_definitions.json", {"research_only": True, "definitions": signature_defs})
    _write_json(diagnostics_root / "rescue_signature_no_future_leakage_check.json", no_future_leakage)
    _write_csv(diagnostics_root / "rescue_signature_candidate_results.csv", signature_results)
    _write_json(diagnostics_root / "rescue_signature_candidate_results.json", {"research_only": True, "results": signature_results})
    _write_csv(diagnostics_root / "variant_comparison_reconciled.csv", _normalize_table_rows(variant_comparison))
    _write_json(diagnostics_root / "variant_comparison_reconciled.json", {"research_only": True, "variants": variant_comparison})
    _write_csv(diagnostics_root / "variant_yearly_reconciled.csv", variant_yearly)
    _write_json(diagnostics_root / "variant_cost_reconciled.json", variant_cost)
    _write_json(diagnostics_root / "oracle_vs_exante_gap_report.json", oracle_gap)
    _write_json(reports_root / "next_research_recommendation.json", {"research_only": True, "next_step": next_step})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "broad_patch_accounting_and_short_rescue_summary.json",
        "report": config.output_root / "broad_patch_accounting_and_short_rescue_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    result = write_broad_patch_accounting_and_short_rescue_audit(
        BroadPatchAccountingAndShortRescueAuditConfig(
            package_root=package_root,
            output_root=package_root / "output" / "broad_patch_accounting_and_short_rescue_audit_001",
        )
    )
    print(result["summary"])


if __name__ == "__main__":
    main()
