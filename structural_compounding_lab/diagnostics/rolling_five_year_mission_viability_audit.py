from __future__ import annotations

import json
import statistics
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
from structural_compounding_lab.diagnostics.broad_patch_accounting_and_short_rescue_audit import (  # noqa: E402
    _apply_signature,
    _feature_row,
    _signature_definitions,
    _simulate_accounting_mode,
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


@dataclass(frozen=True)
class RollingFiveYearMissionViabilityAuditConfig:
    package_root: Path
    output_root: Path


def _paths(config: RollingFiveYearMissionViabilityAuditConfig) -> dict[str, Path]:
    source_root = config.package_root / "output"
    broad_root = source_root / "broad_historical_structural_replay_001"
    broad_ledger_root = broad_root / "ledger"
    frozen_root = source_root / "frozen_patch_validation_audit_001"
    patch_root = source_root / "broad_frozen_patch_validation_001"
    blunt_root = source_root / "broad_patch_bluntness_audit_001"
    accounting_root = source_root / "broad_patch_accounting_and_short_rescue_audit_001"
    return {
        "trades": broad_ledger_root / "trades.csv",
        "equity": broad_ledger_root / "equity.csv",
        "ledger_summary": broad_ledger_root / "summary.json",
        "setup_log": broad_ledger_root / "setup_log.csv",
        "level_log": broad_ledger_root / "level_log.csv",
        "liquidity_events": broad_ledger_root / "liquidity_events.csv",
        "cooldown_log": broad_ledger_root / "cooldown_log.csv",
        "patch_summary": patch_root / "broad_frozen_patch_summary.json",
        "blunt_summary": blunt_root / "broad_patch_bluntness_summary.json",
        "blunt_variants": blunt_root / "diagnostics" / "variant_replay_comparison.csv",
        "accounting_summary": accounting_root / "broad_patch_accounting_and_short_rescue_summary.json",
        "accounting_table": accounting_root / "diagnostics" / "accounting_reconciliation_table.csv",
        "variant_reconciled": accounting_root / "diagnostics" / "variant_comparison_reconciled.csv",
        "rescue_results": accounting_root / "diagnostics" / "rescue_signature_candidate_results.csv",
        "truth_label": accounting_root / "diagnostics" / "equity_headline_truth_label.json",
        "oracle_gap": accounting_root / "diagnostics" / "oracle_vs_exante_gap_report.json",
        "frozen_patch_rules": frozen_root / "diagnostics" / "frozen_patch_rules.json",
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, reports_root


def _empty_outputs(config: RollingFiveYearMissionViabilityAuditConfig, warnings: list[str]) -> dict[str, Path]:
    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    status = {"state": "empty", "resolved_at_utc": datetime.now(timezone.utc).isoformat(), **RESEARCH_ONLY_FLAGS, "warnings": warnings}
    summary = {**RESEARCH_ONLY_FLAGS, "warnings": warnings, "final_classification": "FIVE_YEAR_MISSION_ACCOUNTING_UNCLEAR"}
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "rolling_five_year_mission_summary.json", summary)
    _write_markdown(config.output_root / "rolling_five_year_mission_report.md", "# Rolling 5-Year Mission Viability Audit\n\nRequired artifacts missing.\n")
    for name in (
        "rolling_5y_window_results.csv",
        "mission_target_hit_matrix.csv",
        "window_equity_curves.csv",
        "variant_mission_ranking.csv",
        "cost_stress_mission_survival.csv",
        "moonshot_cap_mission_survival.csv",
        "short_rescue_mission_impact.csv",
        "a_plus_capital_deployment_sensitivity.csv",
        "vault_unlock_impact.csv",
        "worst_case_5y_windows.csv",
        "best_case_5y_windows.csv",
    ):
        _write_csv(diagnostics_root / name, [])
    for name in (
        "rolling_5y_window_results.json",
        "mission_target_hit_matrix.json",
        "variant_mission_ranking.json",
        "mission_failure_attribution.json",
        "mission_success_attribution.json",
        "no_go_risks.json",
        "a_plus_capital_deployment_sensitivity.json",
        "capital_multiplier_risk_report.json",
    ):
        _write_json(diagnostics_root / name, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "rolling_five_year_mission_summary.json",
        "report": config.output_root / "rolling_five_year_mission_report.md",
    }


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _monthly_geometric_return(daily_rows: list[dict[str, Any]]) -> float:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in daily_rows:
        grouped.setdefault(str(row.get("date", ""))[:7], []).append(row)
    returns: list[float] = []
    for _, bucket in sorted(grouped.items()):
        if not bucket:
            continue
        start_equity = float(bucket[0].get("equity_end") or 0.0) - float(bucket[0].get("daily_pnl") or 0.0)
        end_equity = float(bucket[-1].get("equity_end") or 0.0)
        if start_equity > 0:
            returns.append((end_equity / start_equity) - 1.0)
    if not returns:
        return 0.0
    if any((1.0 + value) <= 0.0 for value in returns):
        return -1.0
    product = 1.0
    for value in returns:
        product *= 1.0 + value
    return round(product ** (1.0 / len(returns)) - 1.0, 6)


def _target_hit_metrics(daily_rows: list[dict[str, Any]], *, start_date: pd.Timestamp) -> dict[str, Any]:
    targets = {1_000_000.0: None, 5_000_000.0: None, 10_000_000.0: None}
    max_equity = 0.0
    for row in daily_rows:
        equity = float(row.get("equity_end") or 0.0)
        max_equity = max(max_equity, equity)
        date_value = pd.Timestamp(str(row.get("date")))
        for target in list(targets.keys()):
            if targets[target] is None and equity >= target:
                targets[target] = (date_value - start_date).days
    return {
        "hit_1m": targets[1_000_000.0] is not None,
        "hit_5m": targets[5_000_000.0] is not None,
        "hit_10m": targets[10_000_000.0] is not None,
        "days_to_1m": targets[1_000_000.0],
        "days_to_5m": targets[5_000_000.0],
        "days_to_10m": targets[10_000_000.0],
        "max_equity_reached": round(max_equity, 6),
    }


def _worst_cluster(daily_rows: list[dict[str, Any]]) -> str:
    if not daily_rows:
        return ""
    worst_sum = None
    worst_label = ""
    for idx in range(len(daily_rows)):
        cluster = daily_rows[idx:idx + 5]
        if not cluster:
            continue
        cluster_sum = sum(_safe_float(row.get("daily_pnl")) for row in cluster)
        if worst_sum is None or cluster_sum < worst_sum:
            worst_sum = cluster_sum
            worst_label = f"{cluster[0]['date']}..{cluster[-1]['date']}"
    return worst_label


def _mission_verdict(ending_equity: float, hit_1m: bool, hit_5m: bool, hit_10m: bool) -> str:
    if hit_10m:
        return "MISSION_REACHES_10M_DREAM_CASE"
    if hit_5m:
        return "MISSION_REACHES_5M_OPTIMISTICALLY"
    if hit_1m:
        return "MISSION_REACHES_1M_ONCE"
    if ending_equity >= 250_000.0:
        return "MISSION_SURVIVES_BUT_BELOW_1M"
    return "MISSION_FAILS"


def _window_rows(rows: list[dict[str, Any]], start: pd.Timestamp, end: pd.Timestamp) -> list[dict[str, Any]]:
    return [
        row for row in rows
        if row.get("exit_timestamp") is not None and start <= row["exit_timestamp"] <= end
    ]


def _build_windows(prepared_rows: list[dict[str, Any]]) -> list[tuple[pd.Timestamp, pd.Timestamp, str]]:
    timestamps = [row["exit_timestamp"] for row in prepared_rows if row.get("exit_timestamp") is not None]
    if not timestamps:
        return []
    min_ts = min(timestamps).normalize()
    max_ts = max(timestamps).normalize()
    explicit = [
        (pd.Timestamp("2018-01-01"), pd.Timestamp("2022-12-31"), "2018-01-01_to_2022-12-31"),
        (pd.Timestamp("2019-01-01"), pd.Timestamp("2023-12-31"), "2019-01-01_to_2023-12-31"),
        (pd.Timestamp("2020-01-01"), pd.Timestamp("2024-12-31"), "2020-01-01_to_2024-12-31"),
        (pd.Timestamp("2021-01-01"), pd.Timestamp("2025-12-31"), "2021-01-01_to_2025-12-31"),
        (pd.Timestamp("2021-06-13"), pd.Timestamp("2026-06-13"), "2021-06-13_to_2026-06-13"),
    ]
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]] = []
    seen: set[str] = set()
    for start, end, label in explicit:
        if start >= min_ts and end <= max_ts + pd.Timedelta(days=1):
            windows.append((start, end, label))
            seen.add(label)
    current = min_ts.replace(day=1)
    while current + pd.DateOffset(years=5) - pd.Timedelta(days=1) <= max_ts:
        end = current + pd.DateOffset(years=5) - pd.Timedelta(days=1)
        label = f"{current.date()}_to_{end.date()}"
        if label not in seen:
            windows.append((current, end, label))
            seen.add(label)
        current = current + pd.DateOffset(months=1)
    if not windows:
        windows.append((min_ts, max_ts, f"{min_ts.date()}_to_{max_ts.date()}_full_span_fallback"))
    windows.sort(key=lambda item: item[0])
    return windows


def _best_exante_candidates(rescue_results_path: Path) -> list[str]:
    rows = _read_csv_rows(rescue_results_path)
    ranked = sorted(rows, key=lambda row: _safe_float(row.get("ending_equity_theoretical")), reverse=True)
    return [str(row.get("variant_name") or "") for row in ranked[:3] if str(row.get("variant_name") or "").strip()]


def _normalize_csv_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not rows:
        return []
    keys: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in keys:
                keys.append(key)
    return [{key: row.get(key, "") for key in keys} for row in rows]


def _is_a_plus_setup(row: dict[str, Any]) -> bool:
    personality = str(row.get("personality_label") or "")
    pattern = str(row.get("pattern") or "")
    archetype = str(row.get("archetype_key") or "")
    htf_aligned = bool(row.get("htf_aligned"))
    ema_score = _safe_float(row.get("ema_score"))
    level_distance = _safe_float(row.get("level_distance_atr") or row.get("level_distance"))
    strong_sr = any(token in archetype for token in ("equal_highs", "sweep_high", "resistance", "prev_day_high", "range_high"))
    return (
        personality == "elite_convexity"
        and level_distance <= 0.35
        and (htf_aligned or ema_score >= 0.5)
        and (strong_sr or pattern in {"equal_highs", "sweep_high", "retest_after_breakdown"})
    )


def _simulate_a_plus_mode(
    *,
    name: str,
    selected_rows: list[dict[str, Any]],
    start_capital: float = 20000.0,
    native_lock_ratio: float = 0.5,
    a_plus_multiplier: float = 1.0,
    allow_vault_unlock: bool = False,
    drawdown_circuit_breaker: bool = False,
    cost_bps_total: float = 15.0,
) -> dict[str, Any]:
    rows = sorted(selected_rows, key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or ""))
    active_capital = float(start_capital)
    locked_profit = 0.0
    peak_equity = active_capital
    max_drawdown_pct = 0.0
    a_plus_trade_count = 0
    multipliers_used: list[float] = []
    vault_unlocked_total = 0.0
    replay_rows: list[dict[str, Any]] = []
    daily: dict[str, list[dict[str, Any]]] = {}
    accelerator_enabled = True
    for row in rows:
        if drawdown_circuit_breaker and peak_equity > 0:
            current_dd = _safe_ratio(max(0.0, peak_equity - (active_capital + locked_profit)), peak_equity, 0.0)
            accelerator_enabled = current_dd <= 0.18
        base_risk = active_capital * 0.01
        a_plus_flag = _is_a_plus_setup(row) and accelerator_enabled
        multiplier = a_plus_multiplier if a_plus_flag else 1.0
        if allow_vault_unlock and a_plus_flag and locked_profit > 0.0:
            unlock_amt = min(locked_profit * 0.25, base_risk * (multiplier - 1.0))
            locked_profit -= unlock_amt
            active_capital += unlock_amt
            vault_unlocked_total += unlock_amt
        risk_value = base_risk * multiplier
        pnl = _safe_float(row.get("r_multiple")) * risk_value
        if cost_bps_total > 0.0:
            entry = _safe_float(row.get("entry_price"))
            exit_price = _safe_float(row.get("exit_price")) or entry
            quantity = _safe_float(row.get("quantity") or 1.0)
            notional = abs((entry + exit_price) * 0.5 * quantity)
            pnl -= notional * (cost_bps_total / 10000.0)
        active_capital += pnl
        if pnl > 0.0:
            lock_amt = pnl * native_lock_ratio
            locked_profit += lock_amt
            active_capital -= lock_amt
        total_equity = active_capital + locked_profit
        peak_equity = max(peak_equity, total_equity)
        max_drawdown_pct = max(max_drawdown_pct, _safe_ratio(max(0.0, peak_equity - total_equity), peak_equity, 0.0))
        if a_plus_flag:
            a_plus_trade_count += 1
        multipliers_used.append(multiplier)
        ts = row.get("exit_timestamp")
        rec = {
            "trade_id": str(row.get("trade_id") or ""),
            "timestamp": ts.isoformat() if ts is not None else "",
            "applied_r": _safe_float(row.get("r_multiple")),
            "equity": round(total_equity, 6),
            "active_capital": round(active_capital, 6),
            "locked_profit": round(locked_profit, 6),
            "daily_pnl": round(pnl, 6),
            "capital_multiplier_used": round(multiplier, 6),
            "a_plus_flag": a_plus_flag,
        }
        replay_rows.append(rec)
        date_key = ts.strftime("%Y-%m-%d") if ts is not None else "unknown"
        daily.setdefault(date_key, []).append(rec)
    daily_rows: list[dict[str, Any]] = []
    for date_key, bucket in sorted(daily.items()):
        daily_rows.append(
            {
                "date": date_key,
                "daily_pnl": round(sum(_safe_float(x["daily_pnl"]) for x in bucket), 6),
                "daily_R": round(sum(_safe_float(x["applied_r"]) for x in bucket), 6),
                "equity_end": round(_safe_float(bucket[-1]["equity"]), 6),
                "trade_count": len(bucket),
            }
        )
    values = [_safe_float(row.get("applied_r")) for row in replay_rows]
    wins = [v for v in values if v > 0.0]
    losses = [abs(v) for v in values if v < 0.0]
    pf = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
    return {
        "variant_name": name,
        "trade_count": len(replay_rows),
        "ending_equity": round(active_capital + locked_profit, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "daily_rows": daily_rows,
        "replay_rows": replay_rows,
        "a_plus_trade_count": a_plus_trade_count,
        "average_capital_multiplier_used": round(sum(multipliers_used) / len(multipliers_used), 6) if multipliers_used else 1.0,
        "maximum_capital_multiplier_used": round(max(multipliers_used), 6) if multipliers_used else 1.0,
        "vault_amount_unlocked": round(vault_unlocked_total, 6),
        "locked_profit_end": round(locked_profit, 6),
        "active_capital_end": round(active_capital, 6),
        "profit_factor": round(pf, 6),
        "avg_R": round(sum(values) / len(values), 6) if values else 0.0,
        "median_R": round(_median(values), 6) if values else 0.0,
        "total_R": round(sum(values), 6),
        "win_rate": round(_safe_ratio(len(wins), len(values), 0.0), 6) if values else 0.0,
        "capital_accelerator_label": "RESEARCH_ONLY_CAPITAL_ACCELERATOR",
        "sr_fields_used_read_only": True,
        "sr_logic_modified": False,
    }


def write_rolling_five_year_mission_viability_audit(config: RollingFiveYearMissionViabilityAuditConfig) -> dict[str, Path]:
    paths = _paths(config)
    required = (
        paths["trades"], paths["equity"], paths["ledger_summary"], paths["setup_log"], paths["level_log"],
        paths["liquidity_events"], paths["patch_summary"], paths["blunt_summary"], paths["blunt_variants"],
        paths["accounting_summary"], paths["accounting_table"], paths["variant_reconciled"], paths["rescue_results"],
        paths["truth_label"], paths["oracle_gap"], paths["frozen_patch_rules"],
    )
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return _empty_outputs(config, [f"missing_required_artifact:{path}" for path in missing])

    trade_rows = _read_csv_rows(paths["trades"])
    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    cooldown_rows = _read_csv_rows(paths["cooldown_log"]) if paths["cooldown_log"].exists() else []
    ledger_summary = _read_json(paths["ledger_summary"], {})
    variant_reconciled_rows = _read_csv_rows(paths["variant_reconciled"])
    truth_label = _read_json(paths["truth_label"], {})
    oracle_gap = _read_json(paths["oracle_gap"], {})
    accounting_summary = _read_json(paths["accounting_summary"], {})
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
    removed_short_winners = [row for row in removed_rows if row.get("side") == "short" and _safe_float(row.get("r_multiple")) > 0.0]

    exante_candidates = _best_exante_candidates(paths["rescue_results"])
    rescue_rows_map = {name: _apply_signature(name, removed_short_winners) for name in exante_candidates}

    windows = _build_windows(prepared_rows)
    if not windows:
        return _empty_outputs(config, ["no_supported_five_year_windows"])

    variant_specs: list[tuple[str, str, list[dict[str, Any]], dict[str, Any]]] = [
        ("RAW_BROAD_NATIVE_REPORTED", "native_raw", prepared_rows, {"native_equivalent": True, "risk_mode": "raw_proxy"}),
        ("FROZEN_PATCH_NATIVE_STYLE_RECONCILED", "patch", kept_rows, {"native_lock_ratio": 0.5}),
        ("FROZEN_PATCH_NATIVE_STYLE_WITH_LOW_COST_INSIDE", "patch", kept_rows, {"native_lock_ratio": 0.5, "cost_bps_total": 7.0}),
        ("FROZEN_PATCH_NATIVE_STYLE_WITH_NORMAL_COST_INSIDE", "patch", kept_rows, {"native_lock_ratio": 0.5, "cost_bps_total": 15.0}),
        ("FROZEN_PATCH_NATIVE_STYLE_WITH_HIGH_COST_INSIDE", "patch", kept_rows, {"native_lock_ratio": 0.5, "cost_bps_total": 23.5}),
        ("FROZEN_PATCH_NATIVE_STYLE_WITH_STRESS_COST_INSIDE", "patch", kept_rows, {"native_lock_ratio": 0.5, "cost_bps_total": 35.0}),
        ("FROZEN_PATCH_NATIVE_STYLE_MOONSHOTS_CAPPED_10R", "patch", kept_rows, {"native_lock_ratio": 0.5, "moonshot_cap": 10.0}),
        ("FROZEN_PATCH_NATIVE_STYLE_MOONSHOTS_CAPPED_5R", "patch", kept_rows, {"native_lock_ratio": 0.5, "moonshot_cap": 5.0}),
        ("FROZEN_PATCH_NATIVE_STYLE_MOONSHOTS_CAPPED_3R", "patch", kept_rows, {"native_lock_ratio": 0.5, "moonshot_cap": 3.0}),
        ("FROZEN_PATCH_NATIVE_STYLE_ALL_5R_PLUS_REMOVED", "patch", kept_rows, {"native_lock_ratio": 0.5, "remove_5plus": True}),
        ("FROZEN_PATCH_ACTIVE_CAP_REBASE", "patch", kept_rows, {"active_cap_cap": 13675.433529920501}),
        ("FROZEN_PATCH_FIXED_1R_MONEY", "patch", kept_rows, {"fixed_risk_mode": "fixed_1r_money"}),
    ]
    for idx, name in enumerate(exante_candidates[:3], start=1):
        variant_specs.append((f"FROZEN_PATCH_PLUS_{name}", "patch_rescue", kept_rows + rescue_rows_map.get(name, []), {"native_lock_ratio": 0.5, "rescue_name": name, "rescue_rank": idx}))

    output_rows: list[dict[str, Any]] = []
    target_matrix: list[dict[str, Any]] = []
    equity_curve_rows: list[dict[str, Any]] = []
    cost_stress_rows: list[dict[str, Any]] = []
    moonshot_cap_rows: list[dict[str, Any]] = []
    short_rescue_rows: list[dict[str, Any]] = []
    a_plus_rows: list[dict[str, Any]] = []
    vault_unlock_rows: list[dict[str, Any]] = []
    capital_risk_rows: list[dict[str, Any]] = []

    a_plus_specs = [
        ("BASELINE_NATIVE_STYLE_RECONCILED", 1.0, False, False),
        ("A_PLUS_1_25X_ACTIVE_CAPITAL", 1.25, False, False),
        ("A_PLUS_1_50X_ACTIVE_CAPITAL", 1.50, False, False),
        ("A_PLUS_2_00X_ACTIVE_CAPITAL", 2.00, False, False),
        ("A_PLUS_1_50X_WITH_VAULT_UNLOCK", 1.50, True, False),
        ("A_PLUS_2_00X_WITH_VAULT_UNLOCK", 2.00, True, False),
        ("A_PLUS_2_00X_WITH_DRAWDOWN_CIRCUIT_BREAKER", 2.00, True, True),
    ]

    for start, end, label in windows:
        raw_window_rows = _window_rows(prepared_rows, start, end)
        if not raw_window_rows:
            continue
        for variant_name, variant_type, source_rows, params in variant_specs:
            variant_window_rows = _window_rows(source_rows, start, end)
            if not variant_window_rows:
                continue
            if variant_name == "RAW_BROAD_NATIVE_REPORTED":
                output = _simulate_accounting_mode(
                    name=variant_name,
                    selected_rows=variant_window_rows,
                    all_rows=raw_window_rows,
                    start_capital=20000.0,
                )
            else:
                output = _simulate_accounting_mode(
                    name=variant_name,
                    selected_rows=variant_window_rows,
                    all_rows=raw_window_rows,
                    start_capital=20000.0,
                    cost_bps_total=_safe_float(params.get("cost_bps_total")),
                    native_lock_ratio=params.get("native_lock_ratio"),
                    active_cap_cap=params.get("active_cap_cap"),
                    fixed_risk_mode=str(params.get("fixed_risk_mode") or "compound_1pct"),
                    moonshot_cap=params.get("moonshot_cap"),
                    remove_5plus=bool(params.get("remove_5plus") or False),
                )
            daily_rows = output["daily_rows"]
            target = _target_hit_metrics(daily_rows, start_date=start)
            ending_equity = _safe_float(output.get("ending_equity"))
            total_return_multiple = round(_safe_ratio(ending_equity, 20000.0, 0.0), 6)
            duration_days = max(1, (end - start).days + 1)
            cagr = round((ending_equity / 20000.0) ** (365.0 / duration_days) - 1.0, 6) if ending_equity > 0 else -1.0
            monthly_geo = _monthly_geometric_return(daily_rows)
            years = {}
            months = {}
            for row in daily_rows:
                year_key = str(row["date"])[:4]
                month_key = str(row["date"])[:7]
                years[year_key] = years.get(year_key, 0.0) + _safe_float(row.get("daily_pnl"))
                months[month_key] = months.get(month_key, 0.0) + _safe_float(row.get("daily_pnl"))
            worst_year = min(years.items(), key=lambda kv: kv[1], default=("n/a", 0.0))
            worst_month = min(months.items(), key=lambda kv: kv[1], default=("n/a", 0.0))
            month_count = max(1, len(set(str(row["date"])[:7] for row in daily_rows)))
            values = [_safe_float(row.get("applied_r")) for row in output["replay_rows"]]
            wins = [v for v in values if v > 0.0]
            losses = [abs(v) for v in values if v < 0.0]
            pf = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
            mission_verdict = _mission_verdict(ending_equity, target["hit_1m"], target["hit_5m"], target["hit_10m"])
            row = {
                "variant_name": variant_name,
                "window_label": label,
                "start_date": str(start.date()),
                "end_date": str(end.date()),
                "starting_capital": 20000.0,
                "ending_equity": round(ending_equity, 6),
                "total_return_multiple": total_return_multiple,
                "hit_1m": target["hit_1m"],
                "hit_5m": target["hit_5m"],
                "hit_10m": target["hit_10m"],
                "max_equity_reached": target["max_equity_reached"],
                "days_to_1m": target["days_to_1m"],
                "days_to_5m": target["days_to_5m"],
                "days_to_10m": target["days_to_10m"],
                "CAGR": cagr,
                "monthly_geometric_return": monthly_geo,
                "max_drawdown_pct": round(_safe_float(output.get("max_drawdown_pct")), 6),
                "max_drawdown_eur": round(max(0.0, target["max_equity_reached"] - ending_equity), 6),
                "worst_month": worst_month[0],
                "worst_year": worst_year[0],
                "worst_drawdown_cluster": _worst_cluster(daily_rows),
                "trade_count": int(output.get("trade_count") or 0),
                "average_trades_per_month": round(_safe_ratio(int(output.get("trade_count") or 0), month_count, 0.0), 6),
                "win_rate": round(_safe_ratio(len(wins), len(values), 0.0), 6) if values else 0.0,
                "PF": round(pf, 6),
                "avg_R": round(sum(values) / len(values), 6) if values else 0.0,
                "median_R": round(_median(values), 6) if values else 0.0,
                "total_R": round(sum(values), 6),
                "5R_plus_count": sum(1 for v in values if v >= 5.0),
                "10R_plus_count": sum(1 for v in values if v >= 10.0),
                "moonshot_dependency_label": "NO_EDGE_WITHOUT_MOONSHOTS" if sum(v for v in values if v < 5.0 and v > 0.0) <= 0 else ("MODERATE_MOONSHOT_DEPENDENCY" if sum(v for v in values if v >= 5.0) / max(sum(values), 1e-9) > 0.35 else "ROBUST_WITHOUT_MOONSHOTS"),
                "cost_survival_label": "cost_inside" if "COST_INSIDE" in variant_name else "base",
                "profit_vault_locked_total": round(ending_equity - min(ending_equity, _safe_float(output["replay_rows"][-1]["active_capital"]) if output["replay_rows"] else ending_equity), 6),
                "active_capital_end": round(_safe_float(output["replay_rows"][-1]["active_capital"]) if output["replay_rows"] else ending_equity, 6),
                "locked_profit_end": round(_safe_float(output["replay_rows"][-1]["locked_profit"]) if output["replay_rows"] else 0.0, 6),
                "mission_verdict": mission_verdict,
                "oracle_not_deployable": False,
            }
            output_rows.append(row)
            target_matrix.append(
                {
                    "variant_name": variant_name,
                    "window_label": label,
                    "hit_1m": target["hit_1m"],
                    "hit_5m": target["hit_5m"],
                    "hit_10m": target["hit_10m"],
                    "mission_verdict": mission_verdict,
                }
            )
            for daily_row in daily_rows:
                equity_curve_rows.append({"variant_name": variant_name, "window_label": label, **daily_row})
            if "COST_INSIDE" in variant_name:
                cost_stress_rows.append(row)
            if "MOONSHOTS_CAPPED" in variant_name or "ALL_5R_PLUS_REMOVED" in variant_name:
                moonshot_cap_rows.append(row)
            if "FROZEN_PATCH_PLUS_" in variant_name:
                short_rescue_rows.append(row)

        patch_window_rows = _window_rows(kept_rows, start, end)
        if patch_window_rows:
            baseline_patch_window = next(
                (
                    row for row in output_rows
                    if row["window_label"] == label and row["variant_name"] == "FROZEN_PATCH_NATIVE_STYLE_RECONCILED"
                ),
                None,
            )
            for a_name, multiplier, unlock_flag, breaker_flag in a_plus_specs:
                a_output = _simulate_a_plus_mode(
                    name=a_name,
                    selected_rows=patch_window_rows,
                    start_capital=20000.0,
                    native_lock_ratio=0.5,
                    a_plus_multiplier=multiplier,
                    allow_vault_unlock=unlock_flag,
                    drawdown_circuit_breaker=breaker_flag,
                    cost_bps_total=15.0,
                )
                a_target = _target_hit_metrics(a_output["daily_rows"], start_date=start)
                worst_month = min(
                    ((str(row["date"])[:7], _safe_float(row["daily_pnl"])) for row in a_output["daily_rows"]),
                    key=lambda item: item[1],
                    default=("n/a", 0.0),
                )[0]
                worst_year = min(
                    ((str(row["date"])[:4], _safe_float(row["daily_pnl"])) for row in a_output["daily_rows"]),
                    key=lambda item: item[1],
                    default=("n/a", 0.0),
                )[0]
                a_row = {
                    "variant_name": a_name,
                    "window_label": label,
                    "start_date": str(start.date()),
                    "end_date": str(end.date()),
                    "ending_equity": a_output["ending_equity"],
                    "hit_1m": a_target["hit_1m"],
                    "hit_5m": a_target["hit_5m"],
                    "hit_10m": a_target["hit_10m"],
                    "max_drawdown_pct": a_output["max_drawdown_pct"],
                    "worst_month": worst_month,
                    "worst_year": worst_year,
                    "trade_count": a_output["trade_count"],
                    "a_plus_trade_count": a_output["a_plus_trade_count"],
                    "average_capital_multiplier_used": a_output["average_capital_multiplier_used"],
                    "maximum_capital_multiplier_used": a_output["maximum_capital_multiplier_used"],
                    "vault_amount_unlocked": a_output["vault_amount_unlocked"],
                    "locked_profit_remaining": a_output["locked_profit_end"],
                    "active_capital_end": a_output["active_capital_end"],
                    "improves_1m_mission": bool(baseline_patch_window and (not baseline_patch_window["hit_1m"]) and a_target["hit_1m"]),
                    "improves_5m_mission": bool(baseline_patch_window and (not baseline_patch_window["hit_5m"]) and a_target["hit_5m"]),
                    "drawdown_unacceptable": a_output["max_drawdown_pct"] > 0.25,
                    "improvement_robust": a_output["a_plus_trade_count"] >= 5 and a_output["max_drawdown_pct"] <= 0.22,
                    "capital_accelerator_label": a_output["capital_accelerator_label"],
                    "sr_fields_used_read_only": a_output["sr_fields_used_read_only"],
                    "sr_logic_modified": a_output["sr_logic_modified"],
                }
                a_plus_rows.append(a_row)
                capital_risk_rows.append(
                    {
                        "variant_name": a_name,
                        "window_label": label,
                        "capital_accelerator_label": a_output["capital_accelerator_label"],
                        "average_capital_multiplier_used": a_output["average_capital_multiplier_used"],
                        "maximum_capital_multiplier_used": a_output["maximum_capital_multiplier_used"],
                        "max_drawdown_pct": a_output["max_drawdown_pct"],
                        "vault_amount_unlocked": a_output["vault_amount_unlocked"],
                        "sr_fields_used_read_only": a_output["sr_fields_used_read_only"],
                        "sr_logic_modified": a_output["sr_logic_modified"],
                    }
                )
                if unlock_flag:
                    vault_unlock_rows.append(a_row)

    if not output_rows:
        return _empty_outputs(config, ["no_window_outputs_generated"])

    realistic_rows = [row for row in output_rows if row["variant_name"] != "RAW_BROAD_NATIVE_REPORTED"]
    best_realistic = max(realistic_rows, key=lambda row: _safe_float(row["ending_equity"]))
    worst_realistic = min(realistic_rows, key=lambda row: _safe_float(row["ending_equity"]))
    median_realistic = statistics.median(_safe_float(row["ending_equity"]) for row in realistic_rows)
    hit_1m_count = sum(1 for row in realistic_rows if row["hit_1m"])
    hit_5m_count = sum(1 for row in realistic_rows if row["hit_5m"])
    hit_10m_count = sum(1 for row in realistic_rows if row["hit_10m"])

    variant_groups: dict[str, list[dict[str, Any]]] = {}
    for row in output_rows:
        variant_groups.setdefault(str(row["variant_name"]), []).append(row)
    variant_ranking = []
    for variant_name, rows in variant_groups.items():
        avg_ending = sum(_safe_float(row["ending_equity"]) for row in rows) / len(rows)
        hits_1m = sum(1 for row in rows if row["hit_1m"])
        hits_5m = sum(1 for row in rows if row["hit_5m"])
        variant_ranking.append(
            {
                "variant_name": variant_name,
                "window_count": len(rows),
                "avg_ending_equity": round(avg_ending, 6),
                "median_ending_equity": round(_median([_safe_float(row["ending_equity"]) for row in rows]), 6),
                "max_ending_equity": round(max(_safe_float(row["ending_equity"]) for row in rows), 6),
                "min_ending_equity": round(min(_safe_float(row["ending_equity"]) for row in rows), 6),
                "hit_1m_windows": hits_1m,
                "hit_5m_windows": hits_5m,
                "hit_10m_windows": sum(1 for row in rows if row["hit_10m"]),
                "avg_max_drawdown_pct": round(sum(_safe_float(row["max_drawdown_pct"]) for row in rows) / len(rows), 6),
                "mission_rank_score": round(avg_ending + hits_1m * 100000 + hits_5m * 500000, 6),
            }
        )
    variant_ranking.sort(key=lambda row: (_safe_float(row["mission_rank_score"]), _safe_float(row["avg_ending_equity"])), reverse=True)

    realistic_non_oracle = [row for row in output_rows if not row["oracle_not_deployable"] and row["variant_name"] != "RAW_BROAD_NATIVE_REPORTED"]
    consistent_1m_variants = [row for row in variant_ranking if row["hit_1m_windows"] >= 2 and "ORACLE" not in row["variant_name"]]
    if truth_label.get("label") not in {"NATIVE_STYLE_RECONCILED_RESEARCH_RESULT", "NATIVE_ENGINE_TRUTH"}:
        final_classification = "FIVE_YEAR_MISSION_ACCOUNTING_UNCLEAR"
    elif any(row["hit_10m"] for row in realistic_non_oracle):
        final_classification = "FIVE_YEAR_10M_DREAM_CASE_ONLY"
    elif any(row["hit_5m"] for row in realistic_non_oracle):
        final_classification = "FIVE_YEAR_5M_OPTIMISTIC_CASE_RESEARCH_ONLY"
    elif consistent_1m_variants:
        final_classification = "FIVE_YEAR_1M_MISSION_PROMISING_RESEARCH_ONLY"
    elif any(row["hit_1m"] for row in realistic_non_oracle):
        final_classification = "FIVE_YEAR_1M_MISSION_POSSIBLE_RESEARCH_ONLY"
    elif max(_safe_float(row["ending_equity"]) for row in realistic_non_oracle) >= 250_000.0:
        final_classification = "FIVE_YEAR_MISSION_WEAKLY_SUPPORTED"
    else:
        final_classification = "FIVE_YEAR_MISSION_NOT_SUPPORTED"

    mission_failure_attribution = {
        **RESEARCH_ONLY_FLAGS,
        "dominant_failure_factors": {
            "cost_stress": sum(1 for row in cost_stress_rows if row["mission_verdict"] == "MISSION_FAILS"),
            "moonshot_capping": sum(1 for row in moonshot_cap_rows if row["mission_verdict"] == "MISSION_FAILS"),
            "short_convexity_amputation": accounting_summary.get("removed_short_winner_total_R"),
            "oracle_gap": oracle_gap.get("equity_gap"),
        },
    }
    mission_success_attribution = {
        **RESEARCH_ONLY_FLAGS,
        "best_variant": variant_ranking[0]["variant_name"] if variant_ranking else "",
        "best_realistic_window": {
            "variant_name": best_realistic["variant_name"],
            "window_label": best_realistic["window_label"],
            "ending_equity": best_realistic["ending_equity"],
        },
        "best_exante_rescue_candidate": accounting_summary.get("best_exante_rescue_candidate"),
    }
    no_go_risks = {
        **RESEARCH_ONLY_FLAGS,
        "flags": {
            "five_year_goal_not_consistent": not bool(consistent_1m_variants),
            "five_year_5m_goal_still_optimistic": not any(row["hit_5m"] for row in realistic_non_oracle),
            "five_year_10m_goal_still_dream_case": not any(row["hit_10m"] for row in realistic_non_oracle),
            "a_plus_accelerator_not_allowed_to_upgrade_final_classification": True,
        },
    }
    next_step = {
        **RESEARCH_ONLY_FLAGS,
        "next_step": "prove native-style accounting and retest top ex-ante short rescue signatures on narrower reconciled windows before any paper consideration",
    }

    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "rolling_window_count": len({row["window_label"] for row in output_rows}),
        "best_realistic_5y_ending_equity": best_realistic["ending_equity"],
        "worst_realistic_5y_ending_equity": worst_realistic["ending_equity"],
        "median_realistic_5y_ending_equity": round(median_realistic, 6),
        "windows_reaching_1m": hit_1m_count,
        "windows_reaching_5m": hit_5m_count,
        "windows_reaching_10m": hit_10m_count,
        "best_variant": variant_ranking[0]["variant_name"] if variant_ranking else "",
        "worst_variant": variant_ranking[-1]["variant_name"] if variant_ranking else "",
        "best_exante_short_rescue_candidate": accounting_summary.get("best_exante_rescue_candidate"),
        "best_a_plus_variant": "",
        "best_a_plus_ending_equity": 0.0,
        "best_vault_unlock_variant": "",
        "final_classification": final_classification,
        "next_recommended_research_step": next_step["next_step"],
    }
    if a_plus_rows:
        best_a_plus = max(a_plus_rows, key=lambda row: _safe_float(row["ending_equity"]))
        summary["best_a_plus_variant"] = best_a_plus["variant_name"]
        summary["best_a_plus_ending_equity"] = best_a_plus["ending_equity"]
    if vault_unlock_rows:
        best_vault_unlock = max(vault_unlock_rows, key=lambda row: _safe_float(row["ending_equity"]))
        summary["best_vault_unlock_variant"] = best_vault_unlock["variant_name"]

    report_lines = [
        "# Rolling 5-Year Mission Viability Audit",
        "",
        f"- rolling windows tested: `{summary['rolling_window_count']}`",
        f"- best realistic 5-year ending equity: `{summary['best_realistic_5y_ending_equity']}`",
        f"- worst realistic 5-year ending equity: `{summary['worst_realistic_5y_ending_equity']}`",
        f"- median realistic 5-year ending equity: `{summary['median_realistic_5y_ending_equity']}`",
        f"- windows reaching 1M: `{summary['windows_reaching_1m']}`",
        f"- windows reaching 5M: `{summary['windows_reaching_5m']}`",
        f"- windows reaching 10M: `{summary['windows_reaching_10m']}`",
        f"- best variant: `{summary['best_variant']}`",
        f"- worst variant: `{summary['worst_variant']}`",
        f"- best ex-ante short rescue candidate: `{summary['best_exante_short_rescue_candidate']}`",
        f"- best A+ capital deployment variant: `{summary['best_a_plus_variant']}`",
        f"- best A+ ending equity: `{summary['best_a_plus_ending_equity']}`",
        f"- best vault-unlock variant: `{summary['best_vault_unlock_variant']}`",
        f"- final classification: `{final_classification}`",
        "",
        "This remains research-only. No oracle overlay is used for the final mission verdict.",
        "A+ capital deployment overlays remain RESEARCH_ONLY_CAPITAL_ACCELERATOR diagnostics and do not upgrade the final mission classification.",
        "The 1M mission should not be called promising unless multiple non-oracle reconciled windows support it.",
        "",
        f"- next recommended research step: `{next_step['next_step']}`",
    ]

    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "rolling_five_year_mission_summary.json", summary)
    _write_markdown(config.output_root / "rolling_five_year_mission_report.md", "\n".join(report_lines))
    _write_csv(diagnostics_root / "rolling_5y_window_results.csv", output_rows)
    _write_json(diagnostics_root / "rolling_5y_window_results.json", {"research_only": True, "rows": output_rows})
    _write_csv(diagnostics_root / "mission_target_hit_matrix.csv", target_matrix)
    _write_json(diagnostics_root / "mission_target_hit_matrix.json", {"research_only": True, "rows": target_matrix})
    _write_csv(diagnostics_root / "window_equity_curves.csv", equity_curve_rows)
    _write_csv(diagnostics_root / "variant_mission_ranking.csv", variant_ranking)
    _write_json(diagnostics_root / "variant_mission_ranking.json", {"research_only": True, "rows": variant_ranking})
    _write_csv(diagnostics_root / "cost_stress_mission_survival.csv", cost_stress_rows)
    _write_csv(diagnostics_root / "moonshot_cap_mission_survival.csv", moonshot_cap_rows)
    _write_csv(diagnostics_root / "short_rescue_mission_impact.csv", short_rescue_rows)
    _write_csv(diagnostics_root / "a_plus_capital_deployment_sensitivity.csv", _normalize_csv_rows(a_plus_rows))
    _write_json(diagnostics_root / "a_plus_capital_deployment_sensitivity.json", {"research_only": True, "rows": a_plus_rows})
    _write_csv(diagnostics_root / "vault_unlock_impact.csv", _normalize_csv_rows(vault_unlock_rows))
    _write_json(
        diagnostics_root / "capital_multiplier_risk_report.json",
        {
            **RESEARCH_ONLY_FLAGS,
            "best_a_plus_variant": summary["best_a_plus_variant"],
            "best_a_plus_ending_equity": summary["best_a_plus_ending_equity"],
            "best_vault_unlock_variant": summary["best_vault_unlock_variant"],
            "sr_fields_used_read_only": True,
            "sr_logic_modified": False,
            "rows": capital_risk_rows,
        },
    )
    _write_csv(diagnostics_root / "worst_case_5y_windows.csv", sorted(realistic_rows, key=lambda row: _safe_float(row["ending_equity"]))[:20])
    _write_csv(diagnostics_root / "best_case_5y_windows.csv", sorted(realistic_rows, key=lambda row: _safe_float(row["ending_equity"]), reverse=True)[:20])
    _write_json(diagnostics_root / "mission_failure_attribution.json", mission_failure_attribution)
    _write_json(diagnostics_root / "mission_success_attribution.json", mission_success_attribution)
    _write_json(diagnostics_root / "no_go_risks.json", no_go_risks)
    _write_json(reports_root / "next_research_recommendation.json", next_step)
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "rolling_five_year_mission_summary.json",
        "report": config.output_root / "rolling_five_year_mission_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    result = write_rolling_five_year_mission_viability_audit(
        RollingFiveYearMissionViabilityAuditConfig(
            package_root=package_root,
            output_root=package_root / "output" / "rolling_five_year_mission_viability_audit_001",
        )
    )
    print(result["summary"])


if __name__ == "__main__":
    main()
