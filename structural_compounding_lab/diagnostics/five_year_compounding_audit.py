from __future__ import annotations

import csv
import json
import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


@dataclass(frozen=True)
class FiveYearCompoundingAuditConfig:
    package_root: Path
    output_root: Path


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if ts.tzinfo is not None:
        return ts.tz_convert("UTC").tz_localize(None)
    return ts


def _date_text(ts: pd.Timestamp | None) -> str:
    if ts is None:
        return ""
    return ts.normalize().strftime("%Y-%m-%d")


def _month_text(ts: pd.Timestamp | None) -> str:
    if ts is None:
        return ""
    return ts.strftime("%Y-%m")


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0.0:
        return default
    return numerator / denominator


def _artifact_paths(config: FiveYearCompoundingAuditConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    return {
        "summary": output_root / "summary.json",
        "trades": output_root / "trades.csv",
        "equity": output_root / "equity.csv",
        "setup_log": output_root / "setup_log.csv",
        "cooldown_log": output_root / "cooldown_log.csv",
        "pyramiding_log": output_root / "pyramiding_log.csv",
        "profit_vault": output_root / "profit_vault.json",
        "daily_refined": output_root / "daily_opportunity_definition_refinement_001" / "definition_refinement_summary.json",
        "daily_legacy": output_root / "daily_structural_opportunity_001" / "daily_structural_opportunity_summary.json",
    }


def _normalize_trades(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    normalized: list[dict[str, Any]] = []
    warnings: list[str] = []
    missing_r = 0
    for index, row in enumerate(rows, start=1):
        trade_r = row.get("r_multiple")
        pnl = row.get("pnl")
        trade_r_value = None
        if trade_r is not None and str(trade_r).strip() != "":
            trade_r_value = _to_float(trade_r)
        elif pnl is not None and str(pnl).strip() != "":
            # Research-only fallback: use observed pnl in a normalized pseudo-R bucket if r is absent.
            trade_r_value = None
        if trade_r_value is None:
            missing_r += 1
            continue
        entry_time = _timestamp(row.get("entry_time"))
        exit_time = _timestamp(row.get("exit_time")) or entry_time
        event_time = exit_time or entry_time
        if event_time is None:
            missing_r += 1
            continue
        normalized.append(
            {
                "trade_number": index,
                "trade_id": str(row.get("trade_id") or f"trade-{index}"),
                "symbol": str(row.get("symbol") or "BTCUSDT").upper(),
                "side": str(row.get("side") or "flat").lower(),
                "entry_time": entry_time,
                "exit_time": exit_time,
                "event_time": event_time,
                "trade_r": trade_r_value,
                "observed_pnl": _to_float(pnl),
                "entry_reason": str(row.get("entry_reason") or ""),
                "exit_reason": str(row.get("exit_reason") or ""),
                "setup_class": str(row.get("setup_class") or ""),
                "strategy_type": str(row.get("strategy_type") or ""),
                "moonshot_state": str(row.get("moonshot_state") or ""),
            }
        )
    normalized.sort(key=lambda item: (item["event_time"], item["trade_number"]))
    if missing_r:
        warnings.append(f"ignored_trades_without_usable_r={missing_r}")
    return normalized, warnings


def _profit_lock_state(rows: list[dict[str, Any]]) -> tuple[dict[pd.Timestamp, dict[str, Any]], list[dict[str, Any]]]:
    by_time: dict[pd.Timestamp, dict[str, Any]] = {}
    periods: list[dict[str, Any]] = []
    current_start: dict[str, Any] | None = None
    for row in rows:
        ts = _timestamp(row.get("timestamp"))
        if ts is None:
            continue
        event_type = str(row.get("event_type") or "").lower()
        if event_type == "profit_lock":
            by_time[ts] = {
                "timestamp": ts,
                "locked_profit": _to_float(row.get("locked_profit")),
                "active_trading_capital": _to_float(row.get("active_trading_capital")),
                "reason": str(row.get("reason") or ""),
                "cycle_id": str(row.get("cycle_id") or ""),
            }
        elif event_type == "cooldown_start":
            current_start = {
                "cooldown_start": ts,
                "reason": str(row.get("reason") or ""),
                "minimum_bars": _to_float(row.get("minimum_bars")),
            }
        elif event_type == "cooldown_release" and current_start is not None:
            periods.append(
                {
                    **current_start,
                    "cooldown_release": ts,
                    "duration_hours": round((ts - current_start["cooldown_start"]).total_seconds() / 3600.0, 6),
                }
            )
            current_start = None
    if current_start is not None:
        periods.append({**current_start, "cooldown_release": None, "duration_hours": None})
    return by_time, periods


def _loss_bucket(trade_r: float) -> str:
    if trade_r < 0.0:
        return "loss"
    if trade_r < 1.0:
        return "small_win"
    if trade_r < 3.0:
        return "normal_win"
    if trade_r < 5.0:
        return "high_R_win"
    if trade_r >= 10.0:
        return "moonshot_10R_plus"
    if trade_r >= 8.0:
        return "moonshot_8R_plus"
    return "moonshot_5R_plus"


def _simulate_full_active_compounding(
    trades: list[dict[str, Any]],
    *,
    starting_capital: float,
    fixed_sl_pct: float,
    risk_per_trade_pct: float,
    profit_lock_events: dict[pd.Timestamp, dict[str, Any]],
    cooldown_periods: list[dict[str, Any]],
) -> dict[str, Any]:
    active_capital = starting_capital
    locked_profit = 0.0
    equity = starting_capital
    no_vault_active = starting_capital
    peak_equity = equity
    peak_active = active_capital
    max_drawdown_pct = 0.0
    max_drawdown_eur = 0.0
    longest_loss_streak = 0
    current_loss_streak = 0
    longest_stop_streak = 0
    current_stop_streak = 0
    trade_growth_rows: list[dict[str, Any]] = []
    daily_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    bucket_counts = Counter()
    bucket_r_totals = Counter()
    moonshot_rows: list[dict[str, Any]] = []
    side_totals = defaultdict(lambda: {"trade_count": 0, "wins": 0, "losses": 0, "total_r": 0.0, "gross_profit_r": 0.0, "gross_loss_r": 0.0, "best_r": float("-inf"), "worst_r": float("inf"), "pnl_eur": 0.0})
    cooldown_by_start_date = {
        _date_text(period.get("cooldown_start")): period
        for period in cooldown_periods
        if period.get("cooldown_start") is not None
    }
    cumulative_profit_lock_events = 0

    for idx, trade in enumerate(trades, start=1):
        event_time = trade["event_time"]
        date_key = _date_text(event_time)
        side = trade["side"]
        risk_eur = active_capital * risk_per_trade_pct
        trade_r = float(trade["trade_r"])
        pnl_eur = trade_r * risk_eur
        equity_before_trade = active_capital + locked_profit
        active_before_trade = active_capital
        no_vault_before = no_vault_active
        no_vault_risk = no_vault_active * risk_per_trade_pct
        no_vault_pnl = trade_r * no_vault_risk
        no_vault_active += no_vault_pnl

        provisional_active = active_capital + pnl_eur
        lock_event = profit_lock_events.get(event_time)
        cooldown_triggered = date_key in cooldown_by_start_date and cooldown_by_start_date[date_key]["cooldown_start"] == event_time
        if lock_event is not None:
            cumulative_profit_lock_events += 1
            locked_profit = max(locked_profit, _to_float(lock_event.get("locked_profit"), default=locked_profit))
            active_capital = _to_float(lock_event.get("active_trading_capital"), default=provisional_active)
        else:
            active_capital = provisional_active
        equity = active_capital + locked_profit
        peak_equity = max(peak_equity, equity)
        peak_active = max(peak_active, active_capital)
        drawdown_eur = peak_equity - equity
        drawdown_pct = _safe_ratio(drawdown_eur, peak_equity, 0.0)
        max_drawdown_eur = max(max_drawdown_eur, drawdown_eur)
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)

        if trade_r < 0.0:
            current_loss_streak += 1
            longest_loss_streak = max(longest_loss_streak, current_loss_streak)
        else:
            current_loss_streak = 0
        if trade_r <= -0.99:
            current_stop_streak += 1
            longest_stop_streak = max(longest_stop_streak, current_stop_streak)
        else:
            current_stop_streak = 0

        bucket = _loss_bucket(trade_r)
        bucket_counts[bucket] += 1
        bucket_r_totals[bucket] += trade_r
        side_row = side_totals[side]
        side_row["trade_count"] += 1
        side_row["wins"] += int(trade_r > 0.0)
        side_row["losses"] += int(trade_r < 0.0)
        side_row["total_r"] += trade_r
        side_row["gross_profit_r"] += max(trade_r, 0.0)
        side_row["gross_loss_r"] += min(trade_r, 0.0)
        side_row["best_r"] = max(side_row["best_r"], trade_r)
        side_row["worst_r"] = min(side_row["worst_r"], trade_r)
        side_row["pnl_eur"] += pnl_eur

        moonshot_flag = trade_r >= 5.0
        if moonshot_flag:
            moonshot_rows.append(
                {
                    "trade_number": idx,
                    "trade_id": trade["trade_id"],
                    "timestamp": event_time.isoformat(),
                    "side": side,
                    "trade_R": round(trade_r, 6),
                    "pnl_eur": round(pnl_eur, 6),
                    "entry_reason": trade["entry_reason"],
                    "exit_reason": trade["exit_reason"],
                    "moonshot_bucket": _loss_bucket(trade_r),
                }
            )

        daily_trade_number = len(daily_rows[date_key]) + 1
        trade_row = {
            "trade_number": idx,
            "timestamp": event_time.isoformat(),
            "side": side,
            "equity_before_trade": round(equity_before_trade, 6),
            "active_capital_before_trade": round(active_before_trade, 6),
            "position_notional": round(active_before_trade, 6),
            "fixed_sl_pct": fixed_sl_pct,
            "risk_eur": round(risk_eur, 6),
            "trade_R": round(trade_r, 6),
            "pnl_eur": round(pnl_eur, 6),
            "equity_after_trade": round(equity, 6),
            "locked_profit_after_trade": round(locked_profit, 6),
            "active_capital_after_trade": round(active_capital, 6),
            "daily_trade_number": daily_trade_number,
            "daily_realized_R": 0.0,
            "daily_realized_pnl": 0.0,
            "cooldown_active": date_key in cooldown_by_start_date,
            "cooldown_triggered": cooldown_triggered,
            "moonshot_flag": moonshot_flag,
            "trade_id": trade["trade_id"],
            "entry_reason": trade["entry_reason"],
            "exit_reason": trade["exit_reason"],
            "side_bucket": bucket,
            "no_vault_equity_after_trade": round(no_vault_active, 6),
        }
        daily_rows[date_key].append(trade_row)
        trade_growth_rows.append(trade_row)

    # Fill daily realized metrics after grouping.
    daily_risk_rows: list[dict[str, Any]] = []
    ordered_dates = sorted(daily_rows.keys())
    daily_curve: list[dict[str, Any]] = []
    previous_day_equity = starting_capital
    peak_daily_equity = starting_capital
    drawdown_periods: list[dict[str, Any]] = []
    dd_start: pd.Timestamp | None = None
    dd_peak_equity = starting_capital

    monthly_profit_locked: Counter[str] = Counter()
    previous_locked = 0.0
    for trade_row in trade_growth_rows:
        month_key = trade_row["timestamp"][:7]
        lock_after = _to_float(trade_row["locked_profit_after_trade"])
        delta_lock = max(0.0, lock_after - previous_locked)
        if delta_lock > 0.0:
            monthly_profit_locked[month_key] += delta_lock
        previous_locked = lock_after

    for date_key in ordered_dates:
        rows = daily_rows[date_key]
        start_equity = _to_float(rows[0]["equity_before_trade"])
        end_equity = _to_float(rows[-1]["equity_after_trade"])
        trade_count = len(rows)
        daily_r = sum(_to_float(row["trade_R"]) for row in rows)
        daily_pnl = sum(_to_float(row["pnl_eur"]) for row in rows)
        losses_in_a_row = 0
        current_losses = 0
        stops_in_a_row = 0
        current_stops = 0
        best_intraday = start_equity
        intraday_peak = start_equity
        max_intraday_drawdown_pct = 0.0
        for row in rows:
            trade_r = _to_float(row["trade_R"])
            if trade_r < 0.0:
                current_losses += 1
                losses_in_a_row = max(losses_in_a_row, current_losses)
            else:
                current_losses = 0
            if trade_r <= -0.99:
                current_stops += 1
                stops_in_a_row = max(stops_in_a_row, current_stops)
            else:
                current_stops = 0
            eq_after = _to_float(row["equity_after_trade"])
            intraday_peak = max(intraday_peak, eq_after)
            best_intraday = max(best_intraday, eq_after)
            max_intraday_drawdown_pct = max(
                max_intraday_drawdown_pct,
                _safe_ratio(intraday_peak - eq_after, intraday_peak, 0.0),
            )
        for row in rows:
            row["daily_realized_R"] = round(daily_r, 6)
            row["daily_realized_pnl"] = round(daily_pnl, 6)
        day_ts = pd.Timestamp(date_key)
        peak_daily_equity = max(peak_daily_equity, end_equity)
        daily_drawdown_pct = _safe_ratio(peak_daily_equity - end_equity, peak_daily_equity, 0.0)
        if daily_drawdown_pct > 0.0 and dd_start is None:
            dd_start = day_ts
            dd_peak_equity = peak_daily_equity
        if daily_drawdown_pct == 0.0 and dd_start is not None:
            drawdown_periods.append(
                {
                    "drawdown_start": dd_start.isoformat(),
                    "drawdown_trough": day_ts.isoformat(),
                    "drawdown_recovery": day_ts.isoformat(),
                    "drawdown_pct": round(_safe_ratio(dd_peak_equity - previous_day_equity, dd_peak_equity, 0.0), 6),
                    "drawdown_eur": round(dd_peak_equity - previous_day_equity, 6),
                    "duration_days": int((day_ts - dd_start).days),
                }
            )
            dd_start = None
        daily_row = {
            "date": date_key,
            "starting_equity": round(start_equity, 6),
            "ending_equity": round(end_equity, 6),
            "daily_trade_count": trade_count,
            "long_trade_count": sum(1 for row in rows if row["side"] == "long"),
            "short_trade_count": sum(1 for row in rows if row["side"] == "short"),
            "daily_R": round(daily_r, 6),
            "daily_pnl": round(daily_pnl, 6),
            "daily_return_pct": round(_safe_ratio(daily_pnl, start_equity, 0.0), 6),
            "max_intraday_drawdown_pct": round(max_intraday_drawdown_pct, 6),
            "losses_in_a_row": losses_in_a_row,
            "stops_in_a_row": stops_in_a_row,
            "daily_loss_if_3_stops_pct": -0.03,
            "daily_loss_if_5_stops_pct": -0.05,
            "moonshot_count": sum(1 for row in rows if row["moonshot_flag"]),
            "moonshot_R_total": round(sum(_to_float(row["trade_R"]) for row in rows if row["moonshot_flag"]), 6),
            "cooldown_triggered": any(bool(row["cooldown_triggered"]) for row in rows),
            "cooldown_reason": cooldown_by_start_date.get(date_key, {}).get("reason", ""),
            "survived_day_flag": end_equity > 0.0,
        }
        daily_risk_rows.append(daily_row)
        daily_curve.append(
            {
                "date": date_key,
                "equity": round(end_equity, 6),
                "active_capital": round(_to_float(rows[-1]["active_capital_after_trade"]), 6),
                "locked_profit": round(_to_float(rows[-1]["locked_profit_after_trade"]), 6),
                "daily_pnl": round(daily_pnl, 6),
                "daily_R": round(daily_r, 6),
                "trade_count": trade_count,
            }
        )
        previous_day_equity = end_equity
    if dd_start is not None and ordered_dates:
        final_day = pd.Timestamp(ordered_dates[-1])
        drawdown_periods.append(
            {
                "drawdown_start": dd_start.isoformat(),
                "drawdown_trough": final_day.isoformat(),
                "drawdown_recovery": "",
                "drawdown_pct": round(_safe_ratio(dd_peak_equity - previous_day_equity, dd_peak_equity, 0.0), 6),
                "drawdown_eur": round(dd_peak_equity - previous_day_equity, 6),
                "duration_days": int((final_day - dd_start).days),
            }
        )

    monthly_rows: list[dict[str, Any]] = []
    monthly_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in daily_risk_rows:
        monthly_bucket[row["date"][:7]].append(row)
    for month_key in sorted(monthly_bucket):
        rows = monthly_bucket[month_key]
        month_start_equity = _to_float(rows[0]["starting_equity"])
        month_end_equity = _to_float(rows[-1]["ending_equity"])
        month_trade_rows = [trade for trade in trade_growth_rows if trade["timestamp"][:7] == month_key]
        monthly_rows.append(
            {
                "month": month_key,
                "starting_equity": round(month_start_equity, 6),
                "ending_equity": round(month_end_equity, 6),
                "monthly_pnl": round(month_end_equity - month_start_equity, 6),
                "monthly_return_pct": round(_safe_ratio(month_end_equity - month_start_equity, month_start_equity, 0.0), 6),
                "trade_count": len(month_trade_rows),
                "long_trade_count": sum(1 for trade in month_trade_rows if trade["side"] == "long"),
                "short_trade_count": sum(1 for trade in month_trade_rows if trade["side"] == "short"),
                "win_rate": round(_safe_ratio(sum(1 for trade in month_trade_rows if _to_float(trade["trade_R"]) > 0.0), len(month_trade_rows), 0.0), 6),
                "long_win_rate": round(
                    _safe_ratio(
                        sum(1 for trade in month_trade_rows if trade["side"] == "long" and _to_float(trade["trade_R"]) > 0.0),
                        sum(1 for trade in month_trade_rows if trade["side"] == "long"),
                        0.0,
                    ),
                    6,
                ),
                "short_win_rate": round(
                    _safe_ratio(
                        sum(1 for trade in month_trade_rows if trade["side"] == "short" and _to_float(trade["trade_R"]) > 0.0),
                        sum(1 for trade in month_trade_rows if trade["side"] == "short"),
                        0.0,
                    ),
                    6,
                ),
                "avg_R": round(_mean([_to_float(trade["trade_R"]) for trade in month_trade_rows]), 6),
                "long_avg_R": round(_mean([_to_float(trade["trade_R"]) for trade in month_trade_rows if trade["side"] == "long"]), 6),
                "short_avg_R": round(_mean([_to_float(trade["trade_R"]) for trade in month_trade_rows if trade["side"] == "short"]), 6),
                "moonshot_count": sum(1 for trade in month_trade_rows if _to_float(trade["trade_R"]) >= 5.0),
                "moonshot_R_total": round(sum(_to_float(trade["trade_R"]) for trade in month_trade_rows if _to_float(trade["trade_R"]) >= 5.0), 6),
                "max_drawdown_pct": round(max(_to_float(row["max_intraday_drawdown_pct"]) for row in rows), 6),
                "cooldown_days": sum(1 for row in rows if row["cooldown_triggered"]),
                "profit_locked": round(monthly_profit_locked.get(month_key, 0.0), 6),
                "active_capital_end": round(_to_float(month_trade_rows[-1]["active_capital_after_trade"]) if month_trade_rows else month_end_equity, 6),
            }
        )

    overall_profit_r = sum(max(_to_float(trade["trade_R"]), 0.0) for trade in trade_growth_rows)
    overall_loss_r = sum(min(_to_float(trade["trade_R"]), 0.0) for trade in trade_growth_rows)
    survival_flag = all(_to_float(row["ending_equity"]) > 0.0 for row in daily_risk_rows) and active_capital > 0.0
    observed_ending_capital = equity
    no_vault_ending_equity = no_vault_active
    observed_monthly_returns = [_to_float(row["monthly_return_pct"]) for row in monthly_rows]
    observed_months = max(len(monthly_rows), 1)
    monthly_geometric_return = (observed_ending_capital / starting_capital) ** (1.0 / observed_months) - 1.0 if observed_ending_capital > 0 else -1.0
    avg_monthly_return = _mean(observed_monthly_returns)
    median_monthly_return = _median(observed_monthly_returns)
    conservative_monthly = avg_monthly_return * 0.4
    base_monthly = median_monthly_return
    aggressive_monthly = avg_monthly_return

    def project(rate: float) -> float:
        rate = max(-0.95, rate)
        return starting_capital * ((1.0 + rate) ** 60)

    moonshot_profit_eur = sum(_to_float(row["pnl_eur"]) for row in moonshot_rows)
    total_profit_eur = observed_ending_capital - starting_capital
    sorted_profit_rows = sorted(trade_growth_rows, key=lambda row: _to_float(row["pnl_eur"]), reverse=True)
    top_10_profit = sum(max(_to_float(row["pnl_eur"]), 0.0) for row in sorted_profit_rows[:10])
    rolling_blocks: list[dict[str, Any]] = []
    cover_events = 0
    seven_loss_three_win_profit = 0
    moonshot_saved_block = 0
    for start in range(0, max(0, len(trade_growth_rows) - 9)):
        block = trade_growth_rows[start:start + 10]
        winners = [row for row in block if _to_float(row["trade_R"]) > 0.0]
        losses = [row for row in block if _to_float(row["trade_R"]) < 0.0]
        net_r = sum(_to_float(row["trade_R"]) for row in block)
        event = {
            "start_trade_number": block[0]["trade_number"],
            "end_trade_number": block[-1]["trade_number"],
            "winner_count": len(winners),
            "loss_count": len(losses),
            "net_R": round(net_r, 6),
            "moonshot_count": sum(1 for row in block if row["moonshot_flag"]),
            "few_winners_overpowered_losses": len(winners) <= 3 and len(losses) >= 7 and net_r > 0.0,
        }
        if len(winners) <= 3 and len(losses) >= 7 and net_r > 0.0:
            cover_events += 1
            seven_loss_three_win_profit += 1
        if event["moonshot_count"] > 0 and net_r > 0:
            moonshot_saved_block += 1
        rolling_blocks.append(event)

    long_short_breakdown_rows: list[dict[str, Any]] = []
    for side in ("long", "short"):
        side_rows = [row for row in trade_growth_rows if row["side"] == side]
        side_months = defaultdict(list)
        side_equity = starting_capital
        side_peak = starting_capital
        side_max_dd = 0.0
        for row in side_rows:
            side_equity += _to_float(row["trade_R"]) * (side_equity * risk_per_trade_pct)
            side_peak = max(side_peak, side_equity)
            side_max_dd = max(side_max_dd, _safe_ratio(side_peak - side_equity, side_peak, 0.0))
            side_months[row["timestamp"][:7]].append(row)
        monthly_returns = []
        for month_rows in side_months.values():
            start_equity = starting_capital
            end_equity = start_equity
            for row in month_rows:
                end_equity += _to_float(row["trade_R"]) * (end_equity * risk_per_trade_pct)
            monthly_returns.append(_safe_ratio(end_equity - start_equity, start_equity, 0.0))
        totals = side_totals.get(side, {})
        gross_profit_r = _to_float(totals.get("gross_profit_r"))
        gross_loss_r = abs(_to_float(totals.get("gross_loss_r")))
        long_short_breakdown_rows.append(
            {
                "side": side,
                "trade_count": _to_int(totals.get("trade_count")),
                "win_rate": round(_safe_ratio(_to_int(totals.get("wins")), _to_int(totals.get("trade_count")), 0.0), 6),
                "avg_R": round(_safe_ratio(_to_float(totals.get("total_r")), _to_int(totals.get("trade_count")), 0.0), 6),
                "median_R": round(_median([_to_float(row["trade_R"]) for row in side_rows]), 6),
                "total_R": round(_to_float(totals.get("total_r")), 6),
                "profit_factor": round(_safe_ratio(gross_profit_r, gross_loss_r, 0.0), 6),
                "max_winner_R": round(max((_to_float(row["trade_R"]) for row in side_rows), default=0.0), 6),
                "max_loser_R": round(min((_to_float(row["trade_R"]) for row in side_rows), default=0.0), 6),
                "high_R_win_count": sum(1 for row in side_rows if 3.0 <= _to_float(row["trade_R"]) < 5.0),
                "moonshot_5R_plus_count": sum(1 for row in side_rows if _to_float(row["trade_R"]) >= 5.0),
                "moonshot_8R_plus_count": sum(1 for row in side_rows if _to_float(row["trade_R"]) >= 8.0),
                "moonshot_10R_plus_count": sum(1 for row in side_rows if _to_float(row["trade_R"]) >= 10.0),
                "profit_contribution_pct": round(_safe_ratio(_to_float(totals.get("pnl_eur")), total_profit_eur, 0.0), 6) if total_profit_eur else 0.0,
                "max_drawdown_pct": round(side_max_dd, 6),
                "best_month_pct": round(max(monthly_returns) if monthly_returns else 0.0, 6),
                "worst_month_pct": round(min(monthly_returns) if monthly_returns else 0.0, 6),
            }
        )

    long_short_monthly_rows: list[dict[str, Any]] = []
    for month_key in sorted({row["month"] for row in monthly_rows}):
        month_trade_rows = [row for row in trade_growth_rows if row["timestamp"][:7] == month_key]
        overall = next(row for row in monthly_rows if row["month"] == month_key)
        long_rows = [row for row in month_trade_rows if row["side"] == "long"]
        short_rows = [row for row in month_trade_rows if row["side"] == "short"]
        long_short_monthly_rows.append(
            {
                "month": month_key,
                "starting_equity": overall["starting_equity"],
                "ending_equity": overall["ending_equity"],
                "monthly_pnl": overall["monthly_pnl"],
                "monthly_return_pct": overall["monthly_return_pct"],
                "trade_count": overall["trade_count"],
                "long_trade_count": len(long_rows),
                "short_trade_count": len(short_rows),
                "win_rate": overall["win_rate"],
                "long_win_rate": round(_safe_ratio(sum(1 for row in long_rows if _to_float(row["trade_R"]) > 0.0), len(long_rows), 0.0), 6),
                "short_win_rate": round(_safe_ratio(sum(1 for row in short_rows if _to_float(row["trade_R"]) > 0.0), len(short_rows), 0.0), 6),
                "avg_R": overall["avg_R"],
                "long_avg_R": round(_mean([_to_float(row["trade_R"]) for row in long_rows]), 6),
                "short_avg_R": round(_mean([_to_float(row["trade_R"]) for row in short_rows]), 6),
                "moonshot_count": sum(1 for row in month_trade_rows if row["moonshot_flag"]),
                "moonshot_R_total": round(sum(_to_float(row["trade_R"]) for row in month_trade_rows if row["moonshot_flag"]), 6),
                "max_drawdown_pct": overall["max_drawdown_pct"],
                "cooldown_days": overall["cooldown_days"],
                "profit_locked": overall["profit_locked"],
                "active_capital_end": overall["active_capital_end"],
            }
        )

    yearly_projection_rows = []
    conservative_equity = starting_capital
    base_equity = starting_capital
    aggressive_equity = starting_capital
    for year in range(1, 6):
        conservative_equity *= (1.0 + max(-0.95, conservative_monthly)) ** 12
        base_equity *= (1.0 + max(-0.95, base_monthly)) ** 12
        aggressive_equity *= (1.0 + max(-0.95, aggressive_monthly)) ** 12
        yearly_projection_rows.append(
            {
                "year": year,
                "conservative_equity": round(conservative_equity, 6),
                "base_case_equity": round(base_equity, 6),
                "aggressive_equity": round(aggressive_equity, 6),
                "projected_drawdown_warning": "elevated" if max_drawdown_pct > 0.25 or abs(worst_day_r := min((_to_float(row["daily_R"]) for row in daily_risk_rows), default=0.0)) > 4.0 else "normal",
            }
        )

    cooldown_impact_rows = [
        {
            "cooldown_start": period.get("cooldown_start").isoformat() if period.get("cooldown_start") is not None else "",
            "cooldown_release": period.get("cooldown_release").isoformat() if period.get("cooldown_release") is not None else "",
            "duration_hours": period.get("duration_hours"),
            "reason": period.get("reason", ""),
        }
        for period in cooldown_periods
    ]

    profit_vault_impact_rows = [
        {
            "starting_capital": round(starting_capital, 6),
            "ending_equity_with_profit_vault": round(observed_ending_capital, 6),
            "ending_active_capital_with_profit_vault": round(active_capital, 6),
            "ending_locked_profit": round(locked_profit, 6),
            "ending_equity_without_profit_vault": round(no_vault_ending_equity, 6),
            "profit_vault_drag_eur": round(no_vault_ending_equity - observed_ending_capital, 6),
            "profit_vault_delta_vs_no_vault_eur": round(observed_ending_capital - no_vault_ending_equity, 6),
            "profit_vault_helped_curve": observed_ending_capital >= no_vault_ending_equity,
            "profit_lock_count": cumulative_profit_lock_events,
        }
    ]

    trade_frequency_by_month_rows = [
        {
            "month": row["month"],
            "trade_count": row["trade_count"],
            "long_trade_count": row["long_trade_count"],
            "short_trade_count": row["short_trade_count"],
            "moonshot_count": row["moonshot_count"],
        }
        for row in monthly_rows
    ]

    scaling_safety = {
        "research_only": True,
        "real_money_allowed": False,
        "full_active_capital_survives_observed_sequence": survival_flag,
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "max_drawdown_eur": round(max_drawdown_eur, 6),
        "longest_loss_streak": longest_loss_streak,
        "longest_stop_streak": longest_stop_streak,
        "max_trades_one_day": max((row["daily_trade_count"] for row in daily_risk_rows), default=0),
        "daily_loss_if_3_stops_pct": -0.03,
        "daily_loss_if_5_stops_pct": -0.05,
        "ending_equity_with_profit_vault": round(observed_ending_capital, 6),
        "ending_equity_without_profit_vault": round(no_vault_ending_equity, 6),
        "profit_vault_drag_eur": round(no_vault_ending_equity - observed_ending_capital, 6),
        "profit_vault_delta_vs_no_vault_eur": round(observed_ending_capital - no_vault_ending_equity, 6),
        "profit_vault_helped_curve": observed_ending_capital >= no_vault_ending_equity,
    }

    failure_modes = {
        "research_only": True,
        "real_money_allowed": False,
        "warnings": [],
    }
    if len(monthly_rows) < 12:
        failure_modes["warnings"].append("five_year_projection_is_extrapolation_from_less_than_12_months")
    if max_drawdown_pct > 0.30:
        failure_modes["warnings"].append("drawdown_exceeds_30pct")
    moonshot_profit_contribution_pct = _safe_ratio(moonshot_profit_eur, total_profit_eur, 0.0) if total_profit_eur else 0.0
    if moonshot_profit_contribution_pct > 0.75:
        failure_modes["warnings"].append("profit_is_highly_moonshot_dependent")

    bucket_summary = {
        "loss_count": bucket_counts["loss"],
        "small_win_count": bucket_counts["small_win"],
        "normal_win_count": bucket_counts["normal_win"],
        "high_R_win_count": bucket_counts["high_R_win"],
        "moonshot_5R_plus_count": bucket_counts["moonshot_5R_plus"] + bucket_counts["moonshot_8R_plus"] + bucket_counts["moonshot_10R_plus"],
        "moonshot_8R_plus_count": bucket_counts["moonshot_8R_plus"] + bucket_counts["moonshot_10R_plus"],
        "moonshot_10R_plus_count": bucket_counts["moonshot_10R_plus"],
        "loss_R_total": round(bucket_r_totals["loss"], 6),
        "small_win_R_total": round(bucket_r_totals["small_win"], 6),
        "normal_win_R_total": round(bucket_r_totals["normal_win"], 6),
        "high_R_win_R_total": round(bucket_r_totals["high_R_win"], 6),
        "moonshot_R_total": round(
            bucket_r_totals["moonshot_5R_plus"] + bucket_r_totals["moonshot_8R_plus"] + bucket_r_totals["moonshot_10R_plus"],
            6,
        ),
        "moonshot_profit_contribution_pct": round(moonshot_profit_contribution_pct, 6),
        "top_10_trade_profit_contribution_pct": round(_safe_ratio(top_10_profit, total_profit_eur, 0.0), 6) if total_profit_eur else 0.0,
        "can_3_winners_cover_7_losers": cover_events > 0,
        "average_winner_R": round(_mean([_to_float(row["trade_R"]) for row in trade_growth_rows if _to_float(row["trade_R"]) > 0.0]), 6),
        "average_loser_R": round(_mean([_to_float(row["trade_R"]) for row in trade_growth_rows if _to_float(row["trade_R"]) < 0.0]), 6),
        "payoff_ratio": round(
            abs(
                _safe_ratio(
                    _mean([_to_float(row["trade_R"]) for row in trade_growth_rows if _to_float(row["trade_R"]) > 0.0]),
                    _mean([_to_float(row["trade_R"]) for row in trade_growth_rows if _to_float(row["trade_R"]) < 0.0]),
                    0.0,
                )
            ),
            6,
        ),
        "break_even_win_rate": round(
            abs(
                _safe_ratio(
                    _mean([_to_float(row["trade_R"]) for row in trade_growth_rows if _to_float(row["trade_R"]) < 0.0]),
                    _mean([_to_float(row["trade_R"]) for row in trade_growth_rows if _to_float(row["trade_R"]) > 0.0]) - _mean([_to_float(row["trade_R"]) for row in trade_growth_rows if _to_float(row["trade_R"]) < 0.0]),
                    0.0,
                )
            ),
            6,
        ),
        "actual_win_rate_vs_break_even_win_rate": round(
            _safe_ratio(sum(1 for row in trade_growth_rows if _to_float(row["trade_R"]) > 0.0), len(trade_growth_rows), 0.0),
            6,
        ),
    }

    return {
        "trade_growth_rows": trade_growth_rows,
        "daily_risk_rows": daily_risk_rows,
        "daily_curve_rows": daily_curve,
        "monthly_rows": monthly_rows,
        "yearly_projection_rows": yearly_projection_rows,
        "drawdown_periods": drawdown_periods,
        "cooldown_impact_rows": cooldown_impact_rows,
        "profit_vault_impact_rows": profit_vault_impact_rows,
        "trade_frequency_by_month_rows": trade_frequency_by_month_rows,
        "scaling_safety": scaling_safety,
        "failure_modes": failure_modes,
        "long_short_breakdown_rows": long_short_breakdown_rows,
        "long_short_monthly_rows": long_short_monthly_rows,
        "long_short_r_distribution": {
            "by_side": {
                side: {
                    "trade_count": int(totals["trade_count"]),
                    "win_rate": round(_safe_ratio(totals["wins"], totals["trade_count"], 0.0), 6),
                    "avg_R": round(_safe_ratio(totals["total_r"], totals["trade_count"], 0.0), 6),
                    "total_R": round(totals["total_r"], 6),
                    "buckets": {
                        bucket_name: sum(
                            1
                            for row in trade_growth_rows
                            if row["side"] == side and _loss_bucket(_to_float(row["trade_R"])) == bucket_name
                        )
                        for bucket_name in (
                            "loss",
                            "small_win",
                            "normal_win",
                            "high_R_win",
                            "moonshot_5R_plus",
                            "moonshot_8R_plus",
                            "moonshot_10R_plus",
                        )
                    },
                }
                for side, totals in side_totals.items()
            }
        },
        "losses_vs_high_r_winners": bucket_summary,
        "moonshot_rows": moonshot_rows,
        "moonshot_contribution": {
            "moonshot_trade_count": len(moonshot_rows),
            "moonshot_profit_contribution_pct": round(moonshot_profit_contribution_pct, 6),
            "moonshot_R_total": bucket_summary["moonshot_R_total"],
            "top_10_trade_profit_contribution_pct": bucket_summary["top_10_trade_profit_contribution_pct"],
        },
        "asymmetric_payoff": {
            "rolling_blocks": rolling_blocks,
            "few_winners_cover_many_losses_count": cover_events,
            "seven_losses_three_wins_profit_count": seven_loss_three_win_profit,
            "moonshot_saved_block_count": moonshot_saved_block,
            "can_3_winners_cover_7_losers": cover_events > 0,
            "few_winner_cover_rate": round(_safe_ratio(cover_events, len(rolling_blocks), 0.0), 6),
            "moonshot_saved_rate": round(_safe_ratio(moonshot_saved_block, len(rolling_blocks), 0.0), 6),
            "edge_character": (
                "few_huge_winners"
                if bucket_summary["moonshot_profit_contribution_pct"] > 0.5
                else "mixed_high_r_and_normal_winners"
                if bucket_summary["high_R_win_count"] > 0
                else "small_wins_only"
            ),
        },
        "observed_ending_capital": observed_ending_capital,
        "ending_active_capital": active_capital,
        "ending_locked_profit": locked_profit,
        "ending_without_profit_vault": no_vault_ending_equity,
        "max_drawdown_pct": max_drawdown_pct,
        "max_drawdown_eur": max_drawdown_eur,
        "longest_drawdown_days": max((row["duration_days"] for row in drawdown_periods), default=0),
        "monthly_geometric_return": monthly_geometric_return,
        "avg_monthly_return": avg_monthly_return,
        "median_monthly_return": median_monthly_return,
        "conservative_projection": project(conservative_monthly),
        "base_projection": project(base_monthly),
        "aggressive_projection": project(aggressive_monthly),
        "same_monthly_projection": project(monthly_geometric_return),
        "survival_flag": survival_flag,
        "longest_loss_streak": longest_loss_streak,
        "longest_stop_streak": longest_stop_streak,
        "side_totals": side_totals,
        "bucket_summary": bucket_summary,
    }


def _build_summary(
    simulation: dict[str, Any],
    *,
    starting_capital: float,
    refined_daily_summary: dict[str, Any],
    legacy_daily_summary: dict[str, Any],
    summary_json: dict[str, Any],
    profit_lock_count: int,
    pyramiding_event_count: int,
    cooldown_count: int,
    research_warnings: list[str],
) -> dict[str, Any]:
    monthly_rows = simulation["monthly_rows"]
    daily_risk_rows = simulation["daily_risk_rows"]
    fixed_sl_pct = 0.01
    risk_per_trade_pct = 0.01
    long_totals = simulation["side_totals"].get("long", {})
    short_totals = simulation["side_totals"].get("short", {})
    long_profit_factor = _safe_ratio(_to_float(long_totals.get("gross_profit_r")), abs(_to_float(long_totals.get("gross_loss_r"))), 0.0)
    short_profit_factor = _safe_ratio(_to_float(short_totals.get("gross_profit_r")), abs(_to_float(short_totals.get("gross_loss_r"))), 0.0)
    overall_profit_factor = _safe_ratio(
        sum(max(_to_float(row["trade_R"]), 0.0) for row in simulation["trade_growth_rows"]),
        abs(sum(min(_to_float(row["trade_R"]), 0.0) for row in simulation["trade_growth_rows"])),
        0.0,
    )
    best_day = max(daily_risk_rows, key=lambda row: _to_float(row["daily_pnl"]), default={})
    worst_day = min(daily_risk_rows, key=lambda row: _to_float(row["daily_pnl"]), default={})
    trade_count = len(simulation["trade_growth_rows"])
    win_rate = _safe_ratio(sum(1 for row in simulation["trade_growth_rows"] if _to_float(row["trade_R"]) > 0.0), trade_count, 0.0)
    total_r = sum(_to_float(row["trade_R"]) for row in simulation["trade_growth_rows"])
    avg_r = _safe_ratio(total_r, trade_count, 0.0)
    monthly_returns = [_to_float(row["monthly_return_pct"]) for row in monthly_rows]
    monthly_return_pct = simulation["monthly_geometric_return"]
    bucket_summary = simulation["bucket_summary"]

    long_positive = _to_float(long_totals.get("total_r")) > 0.0
    short_positive = _to_float(short_totals.get("total_r")) > 0.0
    if not simulation["survival_flag"] or overall_profit_factor <= 1.0 or avg_r <= 0.0:
        classification = "NOT_READY_FOR_COMPOUNDING"
    elif simulation["max_drawdown_pct"] > 0.30 or not (long_positive and short_positive):
        classification = "READY_FOR_SMALL_COMPOUNDING"
    elif simulation["max_drawdown_pct"] <= 0.22 and overall_profit_factor >= 1.05 and bucket_summary["can_3_winners_cover_7_losers"]:
        classification = "READY_FOR_CONTROLLED_FULL_CAPITAL_COMPOUNDING"
    else:
        classification = "READY_FOR_AGGRESSIVE_RESEARCH_ONLY_COMPOUNDING"

    return {
        "stage_name": "5-Year Full Active Capital Long/Short Compounding Replay Audit 001",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "real_money_allowed": False,
        "compounding_model": "FULL_ACTIVE_CAPITAL_FIXED_1PCT_SL",
        "fixed_sl_pct": fixed_sl_pct,
        "risk_per_trade_pct": risk_per_trade_pct,
        "long_allowed": True,
        "short_allowed": True,
        "profit_reinvestment": True,
        "withdrawals": 0,
        "external_withdrawal_allowed": False,
        "profit_vault_internal_only": True,
        "position_notional_rule": "active_capital_before_trade",
        "starting_capital": starting_capital,
        "ending_capital_observed_period": round(_to_float(summary_json.get("ending_equity") or summary_json.get("current_equity")), 6),
        "ending_capital_under_full_active_capital_model": round(simulation["observed_ending_capital"], 6),
        "ending_active_capital_under_full_active_capital_model": round(simulation["ending_active_capital"], 6),
        "ending_locked_profit_under_full_active_capital_model": round(simulation["ending_locked_profit"], 6),
        "projected_5_year_capital_if_same_monthly_return": round(simulation["same_monthly_projection"], 6),
        "projected_5_year_capital_conservative": round(simulation["conservative_projection"], 6),
        "projected_5_year_capital_base_case": round(simulation["base_projection"], 6),
        "projected_5_year_capital_aggressive": round(simulation["aggressive_projection"], 6),
        "projection_is_extrapolation": len(monthly_rows) < 60,
        "total_return_pct": round(_safe_ratio(simulation["observed_ending_capital"] - starting_capital, starting_capital, 0.0), 6),
        "monthly_return_pct": round(monthly_return_pct, 6),
        "average_monthly_return_pct": round(simulation["avg_monthly_return"], 6),
        "median_monthly_return_pct": round(simulation["median_monthly_return"], 6),
        "best_month_pct": round(max(monthly_returns) if monthly_returns else 0.0, 6),
        "worst_month_pct": round(min(monthly_returns) if monthly_returns else 0.0, 6),
        "best_day_pnl": round(_to_float(best_day.get("daily_pnl")), 6),
        "worst_day_pnl": round(_to_float(worst_day.get("daily_pnl")), 6),
        "best_day_R": round(_to_float(best_day.get("daily_R")), 6),
        "worst_day_R": round(_to_float(worst_day.get("daily_R")), 6),
        "max_drawdown_pct": round(simulation["max_drawdown_pct"], 6),
        "max_drawdown_eur": round(simulation["max_drawdown_eur"], 6),
        "longest_drawdown_days": simulation["longest_drawdown_days"],
        "trade_count": trade_count,
        "long_trade_count": _to_int(long_totals.get("trade_count")),
        "short_trade_count": _to_int(short_totals.get("trade_count")),
        "trade_days": _to_int(refined_daily_summary.get("actual_trade_frequency", {}).get("actual_trade_days"), default=len({row["date"] for row in daily_risk_rows})),
        "zero_trade_days": _to_int(refined_daily_summary.get("actual_trade_frequency", {}).get("zero_trade_days")),
        "average_trades_per_day": _to_float(refined_daily_summary.get("actual_trade_frequency", {}).get("average_actual_trades_per_day")),
        "average_trades_per_active_day": _to_float(refined_daily_summary.get("actual_trade_frequency", {}).get("average_actual_trades_per_active_day")),
        "max_trades_one_day": _to_int(refined_daily_summary.get("actual_trade_frequency", {}).get("max_actual_trades_on_one_day")),
        "win_rate": round(win_rate, 6),
        "long_win_rate": round(_safe_ratio(_to_int(long_totals.get("wins")), _to_int(long_totals.get("trade_count")), 0.0), 6),
        "short_win_rate": round(_safe_ratio(_to_int(short_totals.get("wins")), _to_int(short_totals.get("trade_count")), 0.0), 6),
        "profit_factor": round(overall_profit_factor, 6),
        "long_profit_factor": round(long_profit_factor, 6),
        "short_profit_factor": round(short_profit_factor, 6),
        "avg_R": round(avg_r, 6),
        "long_avg_R": round(_safe_ratio(_to_float(long_totals.get("total_r")), _to_int(long_totals.get("trade_count")), 0.0), 6),
        "short_avg_R": round(_safe_ratio(_to_float(short_totals.get("total_r")), _to_int(short_totals.get("trade_count")), 0.0), 6),
        "total_R": round(total_r, 6),
        "long_total_R": round(_to_float(long_totals.get("total_r")), 6),
        "short_total_R": round(_to_float(short_totals.get("total_r")), 6),
        "average_R_per_trade": round(avg_r, 6),
        "average_R_per_day": round(_safe_ratio(total_r, _to_int(refined_daily_summary.get("actual_trade_frequency", {}).get("actual_trade_days"), default=1), 0.0), 6),
        "cooldown_count": cooldown_count,
        "profit_lock_count": profit_lock_count,
        "pyramiding_event_count": pyramiding_event_count,
        "whether_full_active_capital_model_survives_observed_trade_sequence": simulation["survival_flag"],
        "loss_count": bucket_summary["loss_count"],
        "small_win_count": bucket_summary["small_win_count"],
        "normal_win_count": bucket_summary["normal_win_count"],
        "high_R_win_count": bucket_summary["high_R_win_count"],
        "moonshot_5R_plus_count": bucket_summary["moonshot_5R_plus_count"],
        "moonshot_8R_plus_count": bucket_summary["moonshot_8R_plus_count"],
        "moonshot_10R_plus_count": bucket_summary["moonshot_10R_plus_count"],
        "loss_R_total": bucket_summary["loss_R_total"],
        "small_win_R_total": bucket_summary["small_win_R_total"],
        "normal_win_R_total": bucket_summary["normal_win_R_total"],
        "high_R_win_R_total": bucket_summary["high_R_win_R_total"],
        "moonshot_R_total": bucket_summary["moonshot_R_total"],
        "moonshot_profit_contribution_pct": bucket_summary["moonshot_profit_contribution_pct"],
        "top_10_trade_profit_contribution_pct": bucket_summary["top_10_trade_profit_contribution_pct"],
        "can_3_winners_cover_7_losers": bucket_summary["can_3_winners_cover_7_losers"],
        "average_winner_R": bucket_summary["average_winner_R"],
        "average_loser_R": bucket_summary["average_loser_R"],
        "payoff_ratio": bucket_summary["payoff_ratio"],
        "break_even_win_rate": bucket_summary["break_even_win_rate"],
        "actual_win_rate_vs_break_even_win_rate": bucket_summary["actual_win_rate_vs_break_even_win_rate"],
        "cooldown_protection_observed": cooldown_count > 0,
        "profit_vault_protection_observed": profit_lock_count > 0,
        "compounding_readiness_classification": classification,
        "daily_opportunity_refined_summary": {
            "missed_high_R_opportunity_count": refined_daily_summary.get("missed_high_R_opportunity_count"),
            "too_tight_day_count": refined_daily_summary.get("too_tight_day_count"),
        },
        "daily_opportunity_legacy_summary": {
            "missed_high_R_opportunity_count": legacy_daily_summary.get("missed_high_R_opportunity_count"),
            "too_tight_day_count": legacy_daily_summary.get("too_tight_day_count"),
        },
        "warnings": research_warnings,
    }


def _report_markdown(summary: dict[str, Any]) -> str:
    lines = [
        "# 5-Year Full Active Capital Long/Short Compounding Replay Audit",
        "",
        f"Classification: `{summary['compounding_readiness_classification']}`",
        "",
        "## Model",
        "",
        "- research_only: `true`",
        "- real_money_allowed: `false`",
        "- compounding_model: `FULL_ACTIVE_CAPITAL_FIXED_1PCT_SL`",
        "- starting_capital: `20000`",
        "- fixed_sl_pct: `1%`",
        "- risk_per_trade_pct: `1%`",
        "- long_allowed: `true`",
        "- short_allowed: `true`",
        "- withdrawals: `0`",
        "",
        "## Observed Sequence",
        "",
        f"- trade count: `{summary['trade_count']}`",
        f"- long trades: `{summary['long_trade_count']}`",
        f"- short trades: `{summary['short_trade_count']}`",
        f"- trade days: `{summary['trade_days']}`",
        f"- zero-trade days: `{summary['zero_trade_days']}`",
        f"- average trades/day: `{summary['average_trades_per_day']}`",
        f"- average trades/active day: `{summary['average_trades_per_active_day']}`",
        "",
        "## Compounding Outcome",
        "",
        f"- ending capital over observed period: `{summary['ending_capital_observed_period']}`",
        f"- ending capital under full-active-capital model: `{summary['ending_capital_under_full_active_capital_model']}`",
        f"- projected 5-year conservative: `{summary['projected_5_year_capital_conservative']}`",
        f"- projected 5-year base case: `{summary['projected_5_year_capital_base_case']}`",
        f"- projected 5-year aggressive: `{summary['projected_5_year_capital_aggressive']}`",
        f"- max drawdown pct: `{summary['max_drawdown_pct']}`",
        f"- max drawdown eur: `{summary['max_drawdown_eur']}`",
        "",
        "## Payoff Shape",
        "",
        f"- win rate: `{summary['win_rate']}`",
        f"- profit factor: `{summary['profit_factor']}`",
        f"- total R: `{summary['total_R']}`",
        f"- long total R: `{summary['long_total_R']}`",
        f"- short total R: `{summary['short_total_R']}`",
        f"- high-R wins: `{summary['high_R_win_count']}`",
        f"- moonshot 5R+: `{summary['moonshot_5R_plus_count']}`",
        f"- moonshot 8R+: `{summary['moonshot_8R_plus_count']}`",
        f"- moonshot 10R+: `{summary['moonshot_10R_plus_count']}`",
        f"- moonshot profit contribution pct: `{summary['moonshot_profit_contribution_pct']}`",
        f"- can 3 winners cover 7 losers: `{summary['can_3_winners_cover_7_losers']}`",
        "",
        "## Safety",
        "",
        f"- cooldown count: `{summary['cooldown_count']}`",
        f"- profit lock count: `{summary['profit_lock_count']}`",
        f"- full-active-capital sequence survives: `{summary['whether_full_active_capital_model_survives_observed_trade_sequence']}`",
        "",
        "This is extrapolation, not proof. No live, paper, config, allocator, or strategy behavior was changed.",
    ]
    return "\n".join(lines) + "\n"


def _empty_output(
    config: FiveYearCompoundingAuditConfig,
    *,
    warnings: list[str],
) -> dict[str, Path]:
    output_root = config.output_root
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    status = {
        "state": "empty",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "real_money_allowed": False,
        "warnings": warnings,
    }
    summary = {
        "stage_name": "5-Year Full Active Capital Long/Short Compounding Replay Audit 001",
        "resolved_at_utc": status["resolved_at_utc"],
        "research_only": True,
        "real_money_allowed": False,
        "compounding_model": "FULL_ACTIVE_CAPITAL_FIXED_1PCT_SL",
        "fixed_sl_pct": 0.01,
        "risk_per_trade_pct": 0.01,
        "long_allowed": True,
        "short_allowed": True,
        "profit_reinvestment": True,
        "withdrawals": 0,
        "external_withdrawal_allowed": False,
        "profit_vault_internal_only": True,
        "position_notional_rule": "active_capital_before_trade",
        "starting_capital": 20000,
        "warnings": warnings,
        "compounding_readiness_classification": "NOT_READY_FOR_COMPOUNDING",
    }
    _write_json(output_root / "status.json", status)
    _write_json(output_root / "five_year_compounding_summary.json", summary)
    _write_markdown(output_root / "five_year_compounding_report.md", "# 5-Year Full Active Capital Long/Short Compounding Replay Audit\n\nNo usable trade artifacts were available.\n")
    for name in (
        "compounding_equity_curve.csv",
        "monthly_compounding_summary.csv",
        "yearly_compounding_summary.csv",
        "trade_size_growth.csv",
        "drawdown_periods.csv",
        "cooldown_impact_report.csv",
        "profit_vault_impact_report.csv",
        "trade_frequency_by_month.csv",
        "full_active_capital_compounding_curve.csv",
        "full_active_capital_trade_growth.csv",
        "full_active_capital_daily_risk_report.csv",
        "full_active_capital_cooldown_report.csv",
        "long_short_compounding_breakdown.csv",
        "long_short_monthly_summary.csv",
        "moonshot_trade_report.csv",
    ):
        _write_csv(diagnostics_root / name, [])
    for name, payload in (
        ("scaling_safety_report.json", {"warnings": warnings, "research_only": True}),
        ("failure_modes_report.json", {"warnings": warnings, "research_only": True}),
        ("long_short_r_distribution.json", {"warnings": warnings, "research_only": True}),
        ("losses_vs_high_r_winners_report.json", {"warnings": warnings, "research_only": True}),
        ("moonshot_contribution_report.json", {"warnings": warnings, "research_only": True}),
        ("asymmetric_payoff_report.json", {"warnings": warnings, "research_only": True}),
    ):
        _write_json(diagnostics_root / name, payload)
    _write_json(reports_root / "next_research_recommendation.json", {"next_step": "supply_usable_trade_artifacts", "research_only": True})
    return {
        "status": output_root / "status.json",
        "summary": output_root / "five_year_compounding_summary.json",
        "report": output_root / "five_year_compounding_report.md",
    }


def write_five_year_compounding_audit(config: FiveYearCompoundingAuditConfig) -> dict[str, Path]:
    paths = _artifact_paths(config)
    summary_json = _read_json(paths["summary"], {})
    trades_rows = _read_csv_rows(paths["trades"])
    cooldown_rows = _read_csv_rows(paths["cooldown_log"])
    pyramiding_rows = _read_csv_rows(paths["pyramiding_log"])
    profit_vault = _read_json(paths["profit_vault"], {})
    refined_daily_summary = _read_json(paths["daily_refined"], {})
    legacy_daily_summary = _read_json(paths["daily_legacy"], {})

    starting_capital = 20000.0
    fixed_sl_pct = 0.01
    risk_per_trade_pct = 0.01
    warnings: list[str] = []
    normalized_trades, trade_warnings = _normalize_trades(trades_rows)
    warnings.extend(trade_warnings)
    if not normalized_trades:
        warnings.append("no_usable_trades_for_compounding_audit")
        return _empty_output(config, warnings=warnings)

    profit_lock_events, cooldown_periods = _profit_lock_state(pyramiding_rows + cooldown_rows)
    simulation = _simulate_full_active_compounding(
        normalized_trades,
        starting_capital=starting_capital,
        fixed_sl_pct=fixed_sl_pct,
        risk_per_trade_pct=risk_per_trade_pct,
        profit_lock_events=profit_lock_events,
        cooldown_periods=cooldown_periods,
    )
    summary = _build_summary(
        simulation,
        starting_capital=starting_capital,
        refined_daily_summary=refined_daily_summary,
        legacy_daily_summary=legacy_daily_summary,
        summary_json=summary_json,
        profit_lock_count=sum(1 for row in pyramiding_rows if str(row.get("event_type") or "").lower() == "profit_lock"),
        pyramiding_event_count=sum(1 for row in pyramiding_rows if str(row.get("event_type") or "").lower() != "profit_lock"),
        cooldown_count=sum(1 for row in cooldown_rows if str(row.get("event_type") or "").lower() == "cooldown_start"),
        research_warnings=warnings,
    )
    report = _report_markdown(summary)

    output_root = config.output_root
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    status = {
        "state": "complete",
        "resolved_at_utc": summary["resolved_at_utc"],
        "research_only": True,
        "real_money_allowed": False,
        "compounding_model": summary["compounding_model"],
        "classification": summary["compounding_readiness_classification"],
    }
    _write_json(output_root / "status.json", status)
    _write_json(output_root / "five_year_compounding_summary.json", summary)
    _write_markdown(output_root / "five_year_compounding_report.md", report)
    _write_csv(diagnostics_root / "compounding_equity_curve.csv", simulation["daily_curve_rows"])
    _write_csv(diagnostics_root / "monthly_compounding_summary.csv", simulation["monthly_rows"])
    _write_csv(diagnostics_root / "yearly_compounding_summary.csv", simulation["yearly_projection_rows"])
    _write_csv(diagnostics_root / "trade_size_growth.csv", simulation["trade_growth_rows"])
    _write_csv(diagnostics_root / "drawdown_periods.csv", simulation["drawdown_periods"])
    _write_csv(diagnostics_root / "cooldown_impact_report.csv", simulation["cooldown_impact_rows"])
    _write_csv(diagnostics_root / "profit_vault_impact_report.csv", simulation["profit_vault_impact_rows"])
    _write_csv(diagnostics_root / "trade_frequency_by_month.csv", simulation["trade_frequency_by_month_rows"])
    _write_json(diagnostics_root / "scaling_safety_report.json", simulation["scaling_safety"])
    _write_json(diagnostics_root / "failure_modes_report.json", simulation["failure_modes"])
    _write_csv(diagnostics_root / "full_active_capital_compounding_curve.csv", simulation["daily_curve_rows"])
    _write_csv(diagnostics_root / "full_active_capital_trade_growth.csv", simulation["trade_growth_rows"])
    _write_csv(diagnostics_root / "full_active_capital_daily_risk_report.csv", simulation["daily_risk_rows"])
    _write_csv(diagnostics_root / "full_active_capital_cooldown_report.csv", simulation["cooldown_impact_rows"])
    _write_csv(diagnostics_root / "long_short_compounding_breakdown.csv", simulation["long_short_breakdown_rows"])
    _write_csv(diagnostics_root / "long_short_monthly_summary.csv", simulation["long_short_monthly_rows"])
    _write_json(diagnostics_root / "long_short_r_distribution.json", simulation["long_short_r_distribution"])
    _write_json(diagnostics_root / "losses_vs_high_r_winners_report.json", simulation["losses_vs_high_r_winners"])
    _write_csv(diagnostics_root / "moonshot_trade_report.csv", simulation["moonshot_rows"])
    _write_json(diagnostics_root / "moonshot_contribution_report.json", simulation["moonshot_contribution"])
    _write_json(diagnostics_root / "asymmetric_payoff_report.json", simulation["asymmetric_payoff"])
    _write_json(
        reports_root / "next_research_recommendation.json",
        {
            "next_step": "review_full_active_capital_replay_before_any_runtime_change",
            "research_only": True,
            "real_money_allowed": False,
            "classification": summary["compounding_readiness_classification"],
        },
    )
    return {
        "status": output_root / "status.json",
        "summary": output_root / "five_year_compounding_summary.json",
        "report": output_root / "five_year_compounding_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    config = FiveYearCompoundingAuditConfig(
        package_root=package_root,
        output_root=package_root / "output" / "five_year_compounding_audit_001",
    )
    result = write_five_year_compounding_audit(config)
    print(result["summary"])


if __name__ == "__main__":
    main()
