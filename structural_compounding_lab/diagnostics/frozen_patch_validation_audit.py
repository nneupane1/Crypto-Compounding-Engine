from __future__ import annotations

import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import (  # noqa: E402
    BAD_LONG_DISABLE_SET,
    _prepare_rows,
    _proven_short_archetypes,
    _simulate_variant,
)
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _normalize_trade_rows,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _timestamp,
    _write_csv,
    _write_json,
    _write_markdown,
)


TARGET_YEARS = list(range(2018, 2027))
RESEARCH_ONLY_FLAGS = {
    "research_only": True,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
}


@dataclass(frozen=True)
class FrozenPatchValidationAuditConfig:
    package_root: Path
    output_root: Path


def _artifact_paths(config: FrozenPatchValidationAuditConfig) -> dict[str, Path]:
    source_root = config.package_root / "output"
    patch_root = source_root / "long_damage_control_patch_audit_001"
    five_year_root = source_root / "five_year_compounding_audit_001"
    long_short_root = source_root / "long_short_edge_repair_audit_001"
    refined_root = source_root / "daily_opportunity_definition_refinement_001"
    return {
        "summary": source_root / "summary.json",
        "trades": source_root / "trades.csv",
        "setup_log": source_root / "setup_log.csv",
        "level_log": source_root / "level_log.csv",
        "liquidity_events": source_root / "liquidity_events.csv",
        "cooldown_log": source_root / "cooldown_log.csv",
        "pyramiding_log": source_root / "pyramiding_log.csv",
        "profit_vault": source_root / "profit_vault.json",
        "patch_summary": patch_root / "long_damage_control_patch_summary.json",
        "patch_best_candidate": patch_root / "diagnostics" / "best_patch_candidate.json",
        "patch_trade_replay": patch_root / "diagnostics" / "patch_variant_trade_replay.csv",
        "patch_variant_summary": patch_root / "diagnostics" / "patch_variant_summary.csv",
        "five_year_summary": five_year_root / "five_year_compounding_summary.json",
        "long_short_summary": long_short_root / "long_short_edge_repair_summary.json",
        "definition_refinement_summary": refined_root / "definition_refinement_summary.json",
    }


def _month_start(ts: pd.Timestamp) -> pd.Timestamp:
    return pd.Timestamp(year=ts.year, month=ts.month, day=1)


def _add_months(ts: pd.Timestamp, months: int) -> pd.Timestamp:
    return (ts + pd.DateOffset(months=months)).normalize()


def _label_for_summary(summary: dict[str, Any]) -> str:
    trade_count = int(summary.get("trade_count") or 0)
    total_r = float(summary.get("total_R") or 0.0)
    profit_factor = float(summary.get("profit_factor") or 0.0)
    max_drawdown_pct = float(summary.get("max_drawdown_pct") or 0.0)
    moonshot_dependency_label = str(summary.get("moonshot_dependency_label") or "")
    if trade_count == 0:
        return "INSUFFICIENT_DATA"
    if trade_count < 20:
        return "FAIL_TOO_FEW_TRADES"
    if not bool(summary.get("survives_full_active_capital_flag")):
        return "FAIL_DRAWDOWN"
    if max_drawdown_pct > 0.35:
        return "FAIL_DRAWDOWN"
    if profit_factor < 1.0 or total_r <= 0.0:
        return "FAIL_NO_EDGE"
    if moonshot_dependency_label == "NO_EDGE_WITHOUT_MOONSHOTS":
        return "FAIL_OVERFIT_LIKELY"
    if moonshot_dependency_label == "EXTREME_MOONSHOT_DEPENDENCY":
        return "PASS_BUT_MOONSHOT_DEPENDENT"
    if profit_factor > 1.25 and max_drawdown_pct <= 0.25:
        return "PASS_STRONG"
    return "PASS_ACCEPTABLE"


def _window_row(
    *,
    window_name: str,
    start_date: pd.Timestamp | None,
    end_date: pd.Timestamp | None,
    summary: dict[str, Any],
) -> dict[str, Any]:
    return {
        "window_name": window_name,
        "start_date": start_date.date().isoformat() if start_date is not None else "",
        "end_date": end_date.date().isoformat() if end_date is not None else "",
        "trade_count": int(summary.get("trade_count") or 0),
        "long_trade_count": int(summary.get("long_trade_count") or 0),
        "short_trade_count": int(summary.get("short_trade_count") or 0),
        "total_R": float(summary.get("total_R") or 0.0),
        "long_total_R": float(summary.get("long_total_R") or 0.0),
        "short_total_R": float(summary.get("short_total_R") or 0.0),
        "ending_capital_from_20000": float(summary.get("ending_capital") or 20000.0),
        "profit_factor": float(summary.get("profit_factor") or 0.0),
        "win_rate": float(summary.get("win_rate") or 0.0),
        "avg_R": float(summary.get("avg_R") or 0.0),
        "max_drawdown_pct": float(summary.get("max_drawdown_pct") or 0.0),
        "worst_day_R": float(summary.get("worst_day_R") or 0.0),
        "best_day_R": float(summary.get("best_day_R") or 0.0),
        "moonshot_5R_plus_count": int(summary.get("moonshot_5R_plus_count") or 0),
        "moonshot_contribution_pct": float(summary.get("moonshot_profit_contribution_pct") or 0.0),
        "profit_without_moonshots": float(summary.get("profit_without_moonshots") or 0.0),
        "survived_full_active_capital_flag": bool(summary.get("survives_full_active_capital_flag")),
        "readiness_classification": str(summary.get("readiness_classification") or ""),
        "validation_label": _label_for_summary(summary),
    }


def _approximate_regime(rows: list[dict[str, Any]]) -> str:
    priced = [row for row in rows if float(row.get("entry_price") or 0.0) > 0.0 and float(row.get("exit_price") or 0.0) > 0.0]
    if len(priced) < 2:
        return "LOW_VOLATILITY"
    first_price = float(priced[0]["entry_price"])
    last_price = float(priced[-1]["exit_price"])
    if first_price <= 0.0:
        return "LOW_VOLATILITY"
    closes = [float(row["exit_price"]) for row in priced if float(row.get("exit_price") or 0.0) > 0.0]
    if len(closes) < 2:
        return "LOW_VOLATILITY"
    returns = []
    for left, right in zip(closes[:-1], closes[1:]):
        if left > 0.0:
            returns.append((right - left) / left)
    total_return = (last_price - first_price) / first_price
    volatility = float(pd.Series(returns).std()) if len(returns) > 1 else 0.0
    if total_return <= -0.35 and volatility >= 0.18:
        return "CRASH_OR_LIQUIDATION"
    if total_return >= 0.60:
        return "BULL_TREND"
    if total_return <= -0.25:
        return "BEAR_TREND"
    if abs(total_return) < 0.10 and volatility >= 0.12:
        return "SIDEWAYS_CHOP"
    if abs(total_return) < 0.08 and volatility < 0.08:
        return "LOW_VOLATILITY"
    if total_return > 0.12 and volatility < 0.10:
        return "SLOW_GRIND_UP"
    if total_return < -0.12 and volatility < 0.10:
        return "SLOW_GRIND_DOWN"
    if volatility >= 0.18:
        return "HIGH_VOLATILITY"
    return "BULL_TREND" if total_return >= 0.0 else "BEAR_TREND"


def _apply_frozen_patch(
    rows: list[dict[str, Any]],
    *,
    proven_shorts: set[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        if row["side"] == "short" and row["archetype_key"] in proven_shorts:
            selected.append(row)
        elif row["side"] == "long" and row.get("long_failure_mode") not in BAD_LONG_DISABLE_SET:
            selected.append(row)
    selected.sort(key=lambda item: (item["exit_timestamp"] or pd.Timestamp.min, item["trade_id"]))
    return selected


def _window_rows(
    rows: list[dict[str, Any]],
    *,
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        ts = row.get("exit_timestamp")
        if ts is None:
            continue
        if start is not None and ts < start:
            continue
        if end is not None and ts > end:
            continue
        output.append(row)
    return output


def _simulate_window(
    *,
    window_name: str,
    all_rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    cooldown_rows: list[dict[str, Any]],
    start: pd.Timestamp | None,
    end: pd.Timestamp | None,
) -> dict[str, Any]:
    payload = _simulate_variant(
        name=window_name,
        selected_rows=selected_rows,
        all_rows=all_rows,
        start_capital=20000.0,
        baseline_span_days=max(1, ((end or start or pd.Timestamp.utcnow()) - (start or end or pd.Timestamp.utcnow())).days + 1),
        cooldown_rows=cooldown_rows,
    )
    summary = payload["summary"]
    row = _window_row(window_name=window_name, start_date=start, end_date=end, summary=summary)
    return {
        "summary": summary,
        "row": row,
        "trade_replay_rows": payload["trade_replay_rows"],
        "daily_rows": payload["daily_rows"],
    }


def _moonshot_validation_payload(window_rows: list[dict[str, Any]], summary_row: dict[str, Any]) -> dict[str, Any]:
    return {
        "normal_result": {
            "ending_capital": summary_row["ending_capital_from_20000"],
            "profit_factor": summary_row["profit_factor"],
            "total_R": summary_row["total_R"],
        },
        "result_without_5R_plus": summary_row["profit_without_moonshots"],
        "result_with_10R_plus_capped_to_5R": float(window_rows[0]["profit_with_10R_plus_capped_to_5R"]) if window_rows else 0.0,
        "result_with_all_5R_plus_capped_to_3R": float(window_rows[0]["profit_with_all_5R_plus_capped_to_3R"]) if window_rows else 0.0,
        "moonshot_dependency_label": summary_row["validation_label"]
        if summary_row["validation_label"] == "FAIL_OVERFIT_LIKELY"
        else (
            "NO_EDGE_WITHOUT_MOONSHOTS"
            if summary_row["profit_without_moonshots"] <= 0.0
            else (
                "EXTREME_MOONSHOT_DEPENDENCY"
                if summary_row["moonshot_contribution_pct"] > 1.0
                else (
                    "MODERATE_MOONSHOT_DEPENDENCY"
                    if summary_row["moonshot_contribution_pct"] > 0.5
                    else "HEALTHY_MOONSHOT_SUPPORT"
                )
            )
        ),
    }


def _year_range(year: int) -> tuple[pd.Timestamp, pd.Timestamp]:
    return pd.Timestamp(year=year, month=1, day=1), pd.Timestamp(year=year, month=12, day=31, hour=23, minute=59, second=59)


def _aggregate_regime_rows(year_rows: list[dict[str, Any]], year_to_regime: dict[str, str]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in year_rows:
        regime = year_to_regime.get(row["window_name"], "LOW_VOLATILITY")
        grouped.setdefault(regime, []).append(row)
    out: list[dict[str, Any]] = []
    for regime, rows in sorted(grouped.items()):
        trade_count = sum(int(row["trade_count"]) for row in rows)
        out.append(
            {
                "regime": regime,
                "trade_count": trade_count,
                "total_R": round(sum(float(row["total_R"]) for row in rows), 6),
                "profit_factor": round(sum(float(row["profit_factor"]) for row in rows) / len(rows), 6) if rows else 0.0,
                "max_drawdown_pct": round(max(float(row["max_drawdown_pct"]) for row in rows), 6) if rows else 0.0,
                "long_total_R": round(sum(float(row["long_total_R"]) for row in rows), 6),
                "short_total_R": round(sum(float(row["short_total_R"]) for row in rows), 6),
                "moonshot_dependency": round(sum(float(row["moonshot_contribution_pct"]) for row in rows) / len(rows), 6) if rows else 0.0,
                "validation_label": "PASS_STRONG" if rows and all(str(row["validation_label"]).startswith("PASS") for row in rows) else "FAIL_OVERFIT_LIKELY",
            }
        )
    return out


def _walk_forward_rows(
    *,
    rows: list[dict[str, Any]],
    selected_rows: list[dict[str, Any]],
    cooldown_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not rows:
        return []
    start = min(row["exit_timestamp"] for row in rows if row["exit_timestamp"] is not None)
    end = max(row["exit_timestamp"] for row in rows if row["exit_timestamp"] is not None)
    if start is None or end is None:
        return []
    rows_out: list[dict[str, Any]] = []
    month_start = _month_start(start)
    for test_months in (6, 12):
        cursor = _add_months(month_start, test_months)
        while cursor < end:
            train_start = month_start
            train_end = cursor - pd.Timedelta(days=1)
            test_start = cursor
            test_end = min(_add_months(cursor, test_months) - pd.Timedelta(seconds=1), end)
            test_all = _window_rows(rows, start=test_start, end=test_end)
            test_selected = _window_rows(selected_rows, start=test_start, end=test_end)
            if not test_all:
                cursor = _add_months(cursor, test_months)
                continue
            payload = _simulate_window(
                window_name=f"ROLLING_{test_months}M_{test_start.date().isoformat()}",
                all_rows=test_all,
                selected_rows=test_selected,
                cooldown_rows=cooldown_rows,
                start=test_start,
                end=test_end,
            )
            rows_out.append(
                {
                    "train_start": train_start.date().isoformat(),
                    "train_end": train_end.date().isoformat(),
                    "test_start": test_start.date().isoformat(),
                    "test_end": test_end.date().isoformat(),
                    "test_trade_count": payload["row"]["trade_count"],
                    "test_total_R": payload["row"]["total_R"],
                    "test_profit_factor": payload["row"]["profit_factor"],
                    "test_max_drawdown_pct": payload["row"]["max_drawdown_pct"],
                    "test_ending_capital": payload["row"]["ending_capital_from_20000"],
                    "test_validation_label": payload["row"]["validation_label"],
                    "frozen_rules_applied_unchanged": True,
                }
            )
            cursor = _add_months(cursor, test_months)

    for year in sorted({row["exit_timestamp"].year for row in rows if row["exit_timestamp"] is not None})[1:]:
        test_start, test_end = _year_range(year)
        train_start = month_start
        train_end = test_start - pd.Timedelta(days=1)
        test_all = _window_rows(rows, start=test_start, end=test_end)
        test_selected = _window_rows(selected_rows, start=test_start, end=test_end)
        if not test_all:
            continue
        payload = _simulate_window(
            window_name=f"YEAR_FORWARD_{year}",
            all_rows=test_all,
            selected_rows=test_selected,
            cooldown_rows=cooldown_rows,
            start=test_start,
            end=test_end,
        )
        rows_out.append(
            {
                "train_start": train_start.date().isoformat(),
                "train_end": train_end.date().isoformat(),
                "test_start": test_start.date().isoformat(),
                "test_end": test_end.date().isoformat(),
                "test_trade_count": payload["row"]["trade_count"],
                "test_total_R": payload["row"]["total_R"],
                "test_profit_factor": payload["row"]["profit_factor"],
                "test_max_drawdown_pct": payload["row"]["max_drawdown_pct"],
                "test_ending_capital": payload["row"]["ending_capital_from_20000"],
                "test_validation_label": payload["row"]["validation_label"],
                "frozen_rules_applied_unchanged": True,
            }
        )
    return rows_out


def _empty_outputs(config: FrozenPatchValidationAuditConfig, *, warnings: list[str]) -> dict[str, Path]:
    output_root = config.output_root
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    status = {
        "state": "empty",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "warnings": warnings,
    }
    summary = {
        **RESEARCH_ONLY_FLAGS,
        "warnings": warnings,
        "promotion_gate_classification": "KEEP_RESEARCH_ONLY",
    }
    _write_json(output_root / "status.json", status)
    _write_json(output_root / "frozen_patch_validation_summary.json", summary)
    _write_markdown(output_root / "frozen_patch_validation_report.md", "# Frozen Patch Multi-Year Validation Audit\n\nNo usable structural validation artifacts were available.\n")
    for name in (
        "validation_window_summary.csv",
        "year_by_year_validation.csv",
        "regime_validation_summary.csv",
        "walk_forward_validation.csv",
        "out_of_sample_validation.csv",
        "frozen_patch_trade_replay.csv",
        "full_active_capital_validation_curve.csv",
        "drawdown_validation_report.csv",
        "long_short_validation_breakdown.csv",
        "validation_failure_modes.csv",
    ):
        _write_csv(diagnostics_root / name, [])
    for name in (
        "frozen_patch_rules.json",
        "moonshot_dependency_validation.json",
        "promotion_gate_report.json",
    ):
        _write_json(diagnostics_root / name, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": output_root / "status.json",
        "summary": output_root / "frozen_patch_validation_summary.json",
        "report": output_root / "frozen_patch_validation_report.md",
    }


def write_frozen_patch_validation_audit(config: FrozenPatchValidationAuditConfig) -> dict[str, Path]:
    paths = _artifact_paths(config)
    trade_rows = _read_csv_rows(paths["trades"])
    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    cooldown_rows = _read_csv_rows(paths["cooldown_log"])
    patch_summary = _read_json(paths["patch_summary"], {})
    best_candidate = _read_json(paths["patch_best_candidate"], {})
    five_year_summary = _read_json(paths["five_year_summary"], {})
    long_short_summary = _read_json(paths["long_short_summary"], {})
    definition_refinement_summary = _read_json(paths["definition_refinement_summary"], {})

    normalized_rows = _normalize_trade_rows(trade_rows, setup_rows, level_rows, liquidity_rows)
    if not normalized_rows:
        return _empty_outputs(config, warnings=["no_usable_trades_for_frozen_patch_validation"])
    if str(best_candidate.get("variant_name") or patch_summary.get("best_patch_candidate") or "") != "BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT":
        return _empty_outputs(config, warnings=["best_patch_candidate_missing_or_not_freezable"])

    prepared_rows = _prepare_rows(normalized_rows)
    proven_shorts = _proven_short_archetypes(prepared_rows)
    selected_rows = _apply_frozen_patch(prepared_rows, proven_shorts=proven_shorts)

    available_years = sorted({row["exit_timestamp"].year for row in prepared_rows if row["exit_timestamp"] is not None})
    all_start = min((row["exit_timestamp"] for row in prepared_rows if row["exit_timestamp"] is not None), default=None)
    all_end = max((row["exit_timestamp"] for row in prepared_rows if row["exit_timestamp"] is not None), default=None)
    full_history = _simulate_window(
        window_name="FULL_AVAILABLE_HISTORY_FROZEN_PATCH",
        all_rows=prepared_rows,
        selected_rows=selected_rows,
        cooldown_rows=cooldown_rows,
        start=all_start,
        end=all_end,
    )

    validation_window_rows = [full_history["row"]]
    year_rows: list[dict[str, Any]] = []
    year_to_regime: dict[str, str] = {}
    full_curve_rows = list(full_history["daily_rows"])
    full_trade_replay_rows = list(full_history["trade_replay_rows"])
    drawdown_rows = [
        {
            "window_name": full_history["row"]["window_name"],
            "ending_capital": full_history["row"]["ending_capital_from_20000"],
            "max_drawdown_pct": full_history["row"]["max_drawdown_pct"],
            "worst_day_R": full_history["row"]["worst_day_R"],
            "best_day_R": full_history["row"]["best_day_R"],
            "validation_label": full_history["row"]["validation_label"],
        }
    ]
    long_short_rows = [
        {
            "window_name": full_history["row"]["window_name"],
            "side": "long",
            "trade_count": full_history["row"]["long_trade_count"],
            "total_R": full_history["row"]["long_total_R"],
            "profit_factor": float(full_history["summary"].get("long_profit_factor") or 0.0),
        },
        {
            "window_name": full_history["row"]["window_name"],
            "side": "short",
            "trade_count": full_history["row"]["short_trade_count"],
            "total_R": full_history["row"]["short_total_R"],
            "profit_factor": float(full_history["summary"].get("short_profit_factor") or 0.0),
        },
    ]
    moonshot_validation: dict[str, Any] = {
        full_history["row"]["window_name"]: _moonshot_validation_payload([full_history["summary"]], full_history["row"])
    }

    for year in TARGET_YEARS:
        start, end = _year_range(year)
        all_year_rows = _window_rows(prepared_rows, start=start, end=end)
        selected_year_rows = _window_rows(selected_rows, start=start, end=end)
        if not all_year_rows:
            row = {
                "window_name": str(year),
                "start_date": start.date().isoformat(),
                "end_date": end.date().isoformat(),
                "trade_count": 0,
                "long_trade_count": 0,
                "short_trade_count": 0,
                "total_R": 0.0,
                "long_total_R": 0.0,
                "short_total_R": 0.0,
                "ending_capital_from_20000": 20000.0,
                "profit_factor": 0.0,
                "win_rate": 0.0,
                "avg_R": 0.0,
                "max_drawdown_pct": 0.0,
                "worst_day_R": 0.0,
                "best_day_R": 0.0,
                "moonshot_5R_plus_count": 0,
                "moonshot_contribution_pct": 0.0,
                "profit_without_moonshots": 0.0,
                "survived_full_active_capital_flag": False,
                "readiness_classification": "NOT_READY_FOR_COMPOUNDING",
                "validation_label": "INSUFFICIENT_DATA",
            }
            year_rows.append(row)
            year_to_regime[str(year)] = "LOW_VOLATILITY"
            continue
        payload = _simulate_window(
            window_name=str(year),
            all_rows=all_year_rows,
            selected_rows=selected_year_rows,
            cooldown_rows=cooldown_rows,
            start=start,
            end=end,
        )
        year_rows.append(payload["row"])
        year_to_regime[str(year)] = _approximate_regime(all_year_rows)
        full_curve_rows.extend(payload["daily_rows"])
        full_trade_replay_rows.extend(payload["trade_replay_rows"])
        drawdown_rows.append(
            {
                "window_name": payload["row"]["window_name"],
                "ending_capital": payload["row"]["ending_capital_from_20000"],
                "max_drawdown_pct": payload["row"]["max_drawdown_pct"],
                "worst_day_R": payload["row"]["worst_day_R"],
                "best_day_R": payload["row"]["best_day_R"],
                "validation_label": payload["row"]["validation_label"],
            }
        )
        long_short_rows.extend(
            [
                {
                    "window_name": payload["row"]["window_name"],
                    "side": "long",
                    "trade_count": payload["row"]["long_trade_count"],
                    "total_R": payload["row"]["long_total_R"],
                    "profit_factor": float(payload["summary"].get("long_profit_factor") or 0.0),
                },
                {
                    "window_name": payload["row"]["window_name"],
                    "side": "short",
                    "trade_count": payload["row"]["short_trade_count"],
                    "total_R": payload["row"]["short_total_R"],
                    "profit_factor": float(payload["summary"].get("short_profit_factor") or 0.0),
                },
            ]
        )
        moonshot_validation[payload["row"]["window_name"]] = _moonshot_validation_payload([payload["summary"]], payload["row"])

    if all_end is not None:
        recent_12m_start = all_end - pd.DateOffset(months=12)
        recent_6m_start = all_end - pd.DateOffset(months=6)
        for name, start in (("RECENT_12M_RETROSPECTIVE", recent_12m_start), ("RECENT_6M_RETROSPECTIVE", recent_6m_start)):
            all_window_rows = _window_rows(prepared_rows, start=start, end=all_end)
            selected_window_rows = _window_rows(selected_rows, start=start, end=all_end)
            payload = _simulate_window(
                window_name=name,
                all_rows=all_window_rows,
                selected_rows=selected_window_rows,
                cooldown_rows=cooldown_rows,
                start=start,
                end=all_end,
            )
            validation_window_rows.append(payload["row"])
            moonshot_validation[name] = _moonshot_validation_payload([payload["summary"]], payload["row"])

    walk_forward_rows = _walk_forward_rows(rows=prepared_rows, selected_rows=selected_rows, cooldown_rows=cooldown_rows)
    out_of_sample_rows = [
        {
            "window_name": "RETROSPECTIVE_LAST_12M",
            "test_start": validation_window_rows[1]["start_date"] if len(validation_window_rows) > 1 else "",
            "test_end": validation_window_rows[1]["end_date"] if len(validation_window_rows) > 1 else "",
            "test_trade_count": validation_window_rows[1]["trade_count"] if len(validation_window_rows) > 1 else 0,
            "test_total_R": validation_window_rows[1]["total_R"] if len(validation_window_rows) > 1 else 0.0,
            "test_profit_factor": validation_window_rows[1]["profit_factor"] if len(validation_window_rows) > 1 else 0.0,
            "test_max_drawdown_pct": validation_window_rows[1]["max_drawdown_pct"] if len(validation_window_rows) > 1 else 0.0,
            "test_validation_label": validation_window_rows[1]["validation_label"] if len(validation_window_rows) > 1 else "INSUFFICIENT_DATA",
            "note": "retrospective_holdout_using_frozen_patch_rules",
        }
    ]

    regime_rows = _aggregate_regime_rows([row for row in year_rows if row["validation_label"] != "INSUFFICIENT_DATA"], year_to_regime)
    pass_rows = [row for row in year_rows if str(row["validation_label"]).startswith("PASS")]
    fail_rows = [row for row in year_rows if str(row["validation_label"]).startswith("FAIL")]
    walk_forward_actionable = [row for row in walk_forward_rows if row["test_validation_label"] != "INSUFFICIENT_DATA"]
    walk_forward_pass_rate = _safe_ratio(
        sum(1 for row in walk_forward_actionable if str(row["test_validation_label"]).startswith("PASS")),
        len(walk_forward_actionable),
        0.0,
    )

    promotion_checks = {
        "multi_year_profit_factor_gt_1_25": float(full_history["row"]["profit_factor"]) > 1.25,
        "max_drawdown_pct_le_25": float(full_history["row"]["max_drawdown_pct"]) <= 0.25,
        "at_least_3_profitable_windows": len([row for row in year_rows if float(row["total_R"]) > 0.0]) >= 3,
        "not_single_moonshot_dependent": moonshot_validation[full_history["row"]["window_name"]]["moonshot_dependency_label"] not in {"EXTREME_MOONSHOT_DEPENDENCY", "NO_EDGE_WITHOUT_MOONSHOTS"},
        "profit_without_moonshots_positive_or_acceptable": float(full_history["row"]["profit_without_moonshots"]) > 0.0,
        "short_edge_positive": float(full_history["row"]["short_total_R"]) > 0.0,
        "long_damage_controlled": float(full_history["row"]["long_total_R"]) >= -5.0,
        "walk_forward_majority_pass": walk_forward_pass_rate >= 0.5 if walk_forward_actionable else False,
        "trade_count_sufficient": int(full_history["row"]["trade_count"]) >= 100,
        "full_active_capital_sequence_survives": bool(full_history["row"]["survived_full_active_capital_flag"]),
    }
    passed_gate_count = sum(1 for value in promotion_checks.values() if value)
    if promotion_checks["multi_year_profit_factor_gt_1_25"] and promotion_checks["max_drawdown_pct_le_25"] and promotion_checks["walk_forward_majority_pass"] and promotion_checks["trade_count_sufficient"] and promotion_checks["full_active_capital_sequence_survives"]:
        gate_classification = "READY_FOR_SMALL_CAPITAL_TRIAL_RESEARCH_ONLY"
    elif promotion_checks["multi_year_profit_factor_gt_1_25"] and promotion_checks["trade_count_sufficient"]:
        gate_classification = "READY_FOR_EXTENDED_PAPER_TEST"
    elif passed_gate_count >= 5:
        gate_classification = "PROMISING_NEEDS_WALK_FORWARD"
    elif float(full_history["row"]["profit_factor"]) < 1.0 or moonshot_validation[full_history["row"]["window_name"]]["moonshot_dependency_label"] in {"EXTREME_MOONSHOT_DEPENDENCY", "NO_EDGE_WITHOUT_MOONSHOTS"}:
        gate_classification = "REJECT_PATCH_OVERFIT"
    else:
        gate_classification = "KEEP_RESEARCH_ONLY"

    recommended_next_action = (
        "continue_research_only_with_frozen_patch_and_collect_truer_out_of_sample_evidence"
        if gate_classification in {"KEEP_RESEARCH_ONLY", "PROMISING_NEEDS_WALK_FORWARD"}
        else "prepare_extended_paper_candidate_only_after_additional_manual_review"
    )

    validation_failure_modes = []
    for row in year_rows:
        if not str(row["validation_label"]).startswith("FAIL"):
            continue
        validation_failure_modes.append(
            {
                "window_name": row["window_name"],
                "validation_label": row["validation_label"],
                "reason": (
                    "moonshot_dependency_or_no_edge"
                    if row["validation_label"] == "FAIL_OVERFIT_LIKELY"
                    else "drawdown_excessive"
                    if row["validation_label"] == "FAIL_DRAWDOWN"
                    else "insufficient_trade_density"
                    if row["validation_label"] == "FAIL_TOO_FEW_TRADES"
                    else "expectancy_failed"
                ),
                "trade_count": row["trade_count"],
                "profit_factor": row["profit_factor"],
                "total_R": row["total_R"],
            }
        )

    frozen_rules = {
        "frozen_patch_candidate": "BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT",
        "source_best_patch_candidate": best_candidate.get("variant_name"),
        "source_recommendation": patch_summary.get("recommended_research_only_patch"),
        "disabled_long_failure_modes": sorted(BAD_LONG_DISABLE_SET),
        "short_bucket_rule": {
            "trade_count_min": 20,
            "total_R_gt": 0.0,
            "profit_factor_gt": 1.10,
            "avg_R_gt": 0.0,
            "matched_archetype_keys": sorted(proven_shorts),
        },
        "long_bucket_rule": {
            "selection_mode": "keep_longs_not_in_disabled_failure_modes",
            "no_new_logic_added": True,
        },
        "frozen_without_retuning": True,
        **RESEARCH_ONLY_FLAGS,
    }

    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "frozen_patch_candidate": "BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT",
        "recommended_research_only_patch": patch_summary.get("recommended_research_only_patch"),
        "available_years": available_years,
        "validation_window_count": len(validation_window_rows),
        "year_window_pass_count": len(pass_rows),
        "year_window_fail_count": len(fail_rows),
        "walk_forward_pass_rate": round(walk_forward_pass_rate, 6),
        "best_validation_window": max(year_rows + validation_window_rows, key=lambda row: (float(row["total_R"]), float(row["profit_factor"])), default={}).get("window_name", ""),
        "worst_validation_window": min([row for row in year_rows + validation_window_rows if row["trade_count"] > 0], key=lambda row: (float(row["total_R"]), float(row["profit_factor"])), default={}).get("window_name", ""),
        "validation_ending_capital": full_history["row"]["ending_capital_from_20000"],
        "max_validation_drawdown": full_history["row"]["max_drawdown_pct"],
        "moonshot_dependency_in_validation": moonshot_validation[full_history["row"]["window_name"]]["moonshot_dependency_label"],
        "profit_without_moonshots_in_validation": full_history["row"]["profit_without_moonshots"],
        "promotion_gate_classification": gate_classification,
        "patch_appears_overfit": gate_classification == "REJECT_PATCH_OVERFIT" or moonshot_validation[full_history["row"]["window_name"]]["moonshot_dependency_label"] in {"EXTREME_MOONSHOT_DEPENDENCY", "NO_EDGE_WITHOUT_MOONSHOTS"},
        "recommended_next_action": recommended_next_action,
        "retrospective_validation_only": True,
        "true_unseen_proof_available": False,
        "five_year_compounding_readiness": five_year_summary.get("compounding_readiness_classification"),
        "long_short_edge_repair_recommendation": long_short_summary.get("recommended_next_research_patch"),
        "definition_refinement_classification": definition_refinement_summary.get("classification"),
    }

    report = "\n".join(
        [
            "# Frozen Patch Multi-Year Validation Audit",
            "",
            "This audit freezes the previously discovered long-damage-control / short-preservation patch and applies it retrospectively across all available structural trade windows without retuning.",
            "",
            "## Frozen patch",
            "",
            f"- candidate: `{summary['frozen_patch_candidate']}`",
            f"- recommendation: `{summary['recommended_research_only_patch']}`",
            "",
            "## Validation outcome",
            "",
            f"- validation windows tested: `{summary['validation_window_count']}`",
            f"- yearly pass count: `{summary['year_window_pass_count']}`",
            f"- yearly fail count: `{summary['year_window_fail_count']}`",
            f"- walk-forward pass rate: `{summary['walk_forward_pass_rate']}`",
            f"- validation ending capital: `{summary['validation_ending_capital']}`",
            f"- max validation drawdown: `{summary['max_validation_drawdown']}`",
            f"- moonshot dependency: `{summary['moonshot_dependency_in_validation']}`",
            f"- profit without moonshots: `{summary['profit_without_moonshots_in_validation']}`",
            f"- promotion gate classification: `{summary['promotion_gate_classification']}`",
            "",
            "## Important note",
            "",
            "This is still retrospective validation over the existing structural trade ledger. It is useful evidence, but it is not equivalent to fresh unseen live proof.",
            "",
            "No live, paper, runtime, allocator, sizing, entry, exit, or config behavior was changed.",
        ]
    ) + "\n"

    promotion_gate_report = {
        **RESEARCH_ONLY_FLAGS,
        "frozen_patch_candidate": summary["frozen_patch_candidate"],
        "classification": gate_classification,
        "checks": promotion_checks,
        "passed_check_count": passed_gate_count,
        "required_check_count": len(promotion_checks),
        "recommended_next_action": recommended_next_action,
        "retrospective_validation_only": True,
        "true_unseen_proof_available": False,
    }

    output_root = config.output_root
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    status = {
        "state": "complete",
        "resolved_at_utc": summary["resolved_at_utc"],
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(output_root / "status.json", status)
    _write_json(output_root / "frozen_patch_validation_summary.json", summary)
    _write_markdown(output_root / "frozen_patch_validation_report.md", report)
    _write_json(diagnostics_root / "frozen_patch_rules.json", frozen_rules)
    _write_csv(diagnostics_root / "validation_window_summary.csv", validation_window_rows)
    _write_csv(diagnostics_root / "year_by_year_validation.csv", year_rows)
    _write_csv(diagnostics_root / "regime_validation_summary.csv", regime_rows)
    _write_csv(diagnostics_root / "walk_forward_validation.csv", walk_forward_rows)
    _write_csv(diagnostics_root / "out_of_sample_validation.csv", out_of_sample_rows)
    _write_csv(diagnostics_root / "frozen_patch_trade_replay.csv", full_trade_replay_rows)
    _write_csv(diagnostics_root / "full_active_capital_validation_curve.csv", full_curve_rows)
    _write_csv(diagnostics_root / "drawdown_validation_report.csv", drawdown_rows)
    _write_json(diagnostics_root / "moonshot_dependency_validation.json", moonshot_validation)
    _write_csv(diagnostics_root / "long_short_validation_breakdown.csv", long_short_rows)
    _write_csv(diagnostics_root / "validation_failure_modes.csv", validation_failure_modes)
    _write_json(diagnostics_root / "promotion_gate_report.json", promotion_gate_report)
    _write_json(reports_root / "next_research_recommendation.json", {"recommended_next_action": recommended_next_action, **RESEARCH_ONLY_FLAGS})
    return {
        "status": output_root / "status.json",
        "summary": output_root / "frozen_patch_validation_summary.json",
        "report": output_root / "frozen_patch_validation_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    config = FrozenPatchValidationAuditConfig(
        package_root=package_root,
        output_root=package_root / "output" / "frozen_patch_validation_audit_001",
    )
    result = write_frozen_patch_validation_audit(config)
    print(result["summary"])


if __name__ == "__main__":
    main()
