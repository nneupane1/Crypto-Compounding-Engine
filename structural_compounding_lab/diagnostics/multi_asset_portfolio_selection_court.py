from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path


COURT_NAME = "MULTI_ASSET_PORTFOLIO_SELECTION_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_asset_portfolio_selection_court_001"

PASSED = "MULTI_ASSET_PORTFOLIO_SELECTION_VALIDATED_RESEARCH_ONLY"
WARNING = "MULTI_ASSET_PORTFOLIO_SELECTION_PROMISING_WITH_WARNINGS_RESEARCH_ONLY"
FAILED = "MULTI_ASSET_PORTFOLIO_SELECTION_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_ASSET_PORTFOLIO_SELECTION_BLOCKED_RESEARCH_ONLY"

START_CAPITAL = 25_000.0
RISK_PER_TRADE = 0.01
MISSION_TARGET_EUR = 1_000_000.0

TRANSFER_ASSETS: tuple[str, ...] = (
    "ETHUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "ADAUSDT",
    "LINKUSDT",
    "DOGEUSDT",
    "SOLUSDT",
    "AVAXUSDT",
)

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "paper_validation_ready": False,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "no_order_path_created": True,
    "no_broker_path_created": True,
    "private_endpoint_used": False,
    "signed_endpoint_used": False,
    "eur_25000_anchor_active": False,
}


@dataclass(frozen=True)
class PortfolioSelectionConfig:
    project_root: Path
    package_root: Path
    transfer_root: Path
    btc_reference_root: Path
    output_root: Path


def default_config() -> PortfolioSelectionConfig:
    pkg = package_root()
    return PortfolioSelectionConfig(
        project_root=project_root(),
        package_root=pkg,
        transfer_root=pkg / "output" / "multi_asset_frozen_transfer_court_001",
        btc_reference_root=pkg / "output" / "cost_aware_frozen_candidate_rebuild_court_001",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round_payload(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _round_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_payload(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_round_payload(payload), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in keys})


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return "" if math.isnan(value) or math.isinf(value) else round(value, 10)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is None:
        return ""
    return value


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_time(value: str) -> pd.Timestamp:
    return pd.Timestamp(value, tz="UTC") if pd.Timestamp(value).tzinfo is None else pd.Timestamp(value).tz_convert("UTC")


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def _profit_factor(values: list[float]) -> float:
    wins = sum(value for value in values if value > 0.0)
    losses = abs(sum(value for value in values if value < 0.0))
    return wins / losses if losses else float(wins > 0.0)


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0] if curve else 0.0
    worst = 0.0
    for value in curve:
        peak = max(peak, value)
        worst = max(worst, _safe_ratio(peak - value, peak, 0.0))
    return worst


def _load_trade_rows(path: Path, *, symbol_override: str | None = None, period: str) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            accepted_flag = str(row.get("candidate_guard_accepted", "true")).strip().lower()
            if accepted_flag in {"false", "0", "no"}:
                continue
            entry = row.get("entry_time") or row.get("entry_timestamp")
            exit_ = row.get("exit_time") or row.get("exit_timestamp") or entry
            if not entry:
                continue
            payload = dict(row)
            payload["symbol"] = symbol_override or str(row.get("symbol") or "").upper()
            payload["period"] = period
            payload["entry_timestamp"] = _parse_time(str(entry))
            payload["exit_timestamp"] = _parse_time(str(exit_))
            payload["net_r"] = float(row.get("net_r") or 0.0)
            payload["gross_r"] = float(row.get("gross_r") or 0.0)
            payload["net_cost_r"] = float(row.get("net_cost_r") or 0.0)
            payload["pre_entry_cost_r_at_15bps"] = float(row.get("pre_entry_cost_r_at_15bps") or 0.0)
            rows.append(payload)
    return sorted(rows, key=lambda item: (item["entry_timestamp"], item["exit_timestamp"], item["symbol"]))


def _asset_paths(config: PortfolioSelectionConfig, symbol: str) -> dict[str, Path]:
    root = config.transfer_root / "assets" / symbol
    return {
        "summary": root / "asset_transfer_summary.json",
        "split": root / "split_manifest.json",
        "freeze": root / "freeze_signature.json",
        "research_trades": root / "research_only_transfer_replay" / "cost_aware_candidate_trades.csv",
        "holdout_trades": root / "sealed_holdout_transfer_validation" / "cost_aware_candidate_trades.csv",
    }


def _btc_paths(config: PortfolioSelectionConfig) -> dict[str, Path]:
    return {
        "summary": config.btc_reference_root / "cost_aware_frozen_candidate_rebuild_summary.json",
        "research_trades": config.btc_reference_root / "candidate_full_history_results.csv",
        "holdout_trades": config.btc_reference_root / "candidate_holdout_results.csv",
    }


def _simulate_sequence(rows: list[dict[str, Any]], *, start_capital: float = START_CAPITAL) -> dict[str, Any]:
    equity = start_capital
    curve = [equity]
    trade_rows: list[dict[str, Any]] = []
    for index, row in enumerate(sorted(rows, key=lambda item: (item["entry_timestamp"], item["symbol"])), start=1):
        before = equity
        risk = before * RISK_PER_TRADE
        pnl = risk * float(row["net_r"])
        cost = risk * float(row.get("net_cost_r") or 0.0)
        equity = before + pnl
        curve.append(equity)
        trade_rows.append(
            {
                "portfolio_trade_number": index,
                "symbol": row["symbol"],
                "source_trade_id": row.get("trade_id"),
                "entry_time": row["entry_timestamp"].isoformat(),
                "exit_time": row["exit_timestamp"].isoformat(),
                "side": row.get("side"),
                "net_r": row["net_r"],
                "gross_r": row.get("gross_r"),
                "net_cost_r": row.get("net_cost_r"),
                "estimated_cost_eur": cost,
                "risk_eur": risk,
                "net_pnl_eur": pnl,
                "equity_before_trade": before,
                "equity_after_trade": equity,
                "selection_reason": row.get("selection_reason"),
                "selection_rank": row.get("selection_rank"),
            }
        )
    values = [float(row["net_r"]) for row in rows]
    return {
        "starting_equity": start_capital,
        "ending_equity": equity,
        "net_gain": equity - start_capital,
        "return_multiple": _safe_ratio(equity, start_capital, 0.0),
        "accepted_trades": len(rows),
        "net_total_R": sum(values),
        "average_R": sum(values) / len(values) if values else 0.0,
        "median_R": statistics.median(values) if values else 0.0,
        "profit_factor": _profit_factor(values),
        "win_rate": _safe_ratio(sum(1 for value in values if value > 0.0), len(values), 0.0),
        "max_drawdown": _max_drawdown(curve),
        "largest_loss_R": min(values) if values else 0.0,
        "ruin_or_negative_equity": any(value <= 0.0 for value in curve),
        "trade_rows": trade_rows,
    }


def _select_non_overlapping_shared_pool(
    rows: list[dict[str, Any]],
    *,
    allowed_symbols: list[str],
    symbol_priority: dict[str, int],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    allowed = set(allowed_symbols)
    candidates = [row for row in rows if row["symbol"] in allowed]
    candidates.sort(
        key=lambda row: (
            row["entry_timestamp"],
            symbol_priority.get(row["symbol"], 999),
            row.get("pre_entry_cost_r_at_15bps") or 999.0,
            row["exit_timestamp"],
        )
    )
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    active_until: pd.Timestamp | None = None
    for row in candidates:
        enriched = dict(row)
        enriched["selection_rank"] = symbol_priority.get(row["symbol"], 999)
        if active_until is not None and row["entry_timestamp"] <= active_until:
            enriched["selection_reason"] = "rejected_overlap_existing_active_trade"
            rejected.append(enriched)
            continue
        enriched["selection_reason"] = "selected_highest_rank_available_non_overlapping_trade"
        selected.append(enriched)
        active_until = row["exit_timestamp"]
    return selected, rejected


def _equal_sleeve_result(asset_sims: dict[str, dict[str, Any]], symbols: list[str], *, start_capital: float = START_CAPITAL) -> dict[str, Any]:
    if not symbols:
        return {"starting_equity": start_capital, "ending_equity": start_capital, "accepted_trades": 0}
    sleeve = start_capital / len(symbols)
    ending = 0.0
    trades = 0
    for symbol in symbols:
        sim = asset_sims[symbol]
        ending += sleeve * _safe_ratio(float(sim["ending_equity"]), START_CAPITAL, 0.0)
        trades += int(sim["accepted_trades"])
    return {
        "starting_equity": start_capital,
        "ending_equity": ending,
        "net_gain": ending - start_capital,
        "return_multiple": _safe_ratio(ending, start_capital, 0.0),
        "accepted_trades": trades,
        "sleeve_count": len(symbols),
        "sleeve_starting_equity": sleeve,
    }


def _month_start_after(ts: pd.Timestamp) -> pd.Timestamp:
    base = pd.Timestamp(year=ts.year, month=ts.month, day=1, tz="UTC")
    if ts == base:
        return base
    return base + pd.DateOffset(months=1)


def _rolling_5y(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"window_count": 0, "windows_above_1m": 0}
    rows = sorted(rows, key=lambda item: item["entry_timestamp"])
    start = _month_start_after(rows[0]["entry_timestamp"])
    last = rows[-1]["entry_timestamp"]
    windows: list[dict[str, Any]] = []
    current = start
    number = 1
    while True:
        end = current + pd.DateOffset(years=5) - pd.Timedelta(minutes=1)
        if end > last:
            break
        bucket = [row for row in rows if current <= row["entry_timestamp"] <= end]
        sim = _simulate_sequence(bucket)
        slim = {key: value for key, value in sim.items() if key != "trade_rows"}
        slim.update(
            {
                "window_number": number,
                "start_date": current.isoformat(),
                "end_date": end.isoformat(),
                "above_1m": sim["ending_equity"] >= MISSION_TARGET_EUR,
            }
        )
        windows.append(slim)
        current = current + pd.DateOffset(months=1)
        number += 1
    endings = [float(row["ending_equity"]) for row in windows]
    return {
        "window_count": len(windows),
        "windows_above_1m": sum(1 for row in windows if row["above_1m"]),
        "average_ending_equity": sum(endings) / len(endings) if endings else 0.0,
        "median_ending_equity": statistics.median(endings) if endings else 0.0,
        "minimum_ending_equity": min(endings) if endings else 0.0,
        "maximum_ending_equity": max(endings) if endings else 0.0,
        "best_window": max(windows, key=lambda row: float(row["ending_equity"])) if windows else None,
        "worst_window": min(windows, key=lambda row: float(row["ending_equity"])) if windows else None,
        "windows": windows,
    }


def _monthly_returns(rows: list[dict[str, Any]]) -> pd.Series:
    if not rows:
        return pd.Series(dtype=float)
    equity = START_CAPITAL
    month_end: dict[pd.Timestamp, float] = {}
    for row in sorted(rows, key=lambda item: item["entry_timestamp"]):
        equity += equity * RISK_PER_TRADE * float(row["net_r"])
        month = pd.Timestamp(year=row["entry_timestamp"].year, month=row["entry_timestamp"].month, day=1, tz="UTC")
        month_end[month] = equity
    series = pd.Series(month_end).sort_index()
    return series.pct_change().dropna()


def _correlation_matrix(asset_rows: dict[str, list[dict[str, Any]]], symbols: list[str]) -> tuple[dict[str, dict[str, float | None]], dict[str, Any]]:
    returns = {symbol: _monthly_returns(asset_rows.get(symbol, [])) for symbol in symbols}
    frame = pd.DataFrame(returns).dropna(how="all")
    corr = frame.corr(min_periods=6)
    matrix: dict[str, dict[str, float | None]] = {}
    for left in symbols:
        matrix[left] = {}
        for right in symbols:
            value = corr.loc[left, right] if left in corr.index and right in corr.columns else float("nan")
            matrix[left][right] = None if pd.isna(value) else float(value)
    pair_values = [
        float(corr.loc[left, right])
        for i, left in enumerate(symbols)
        for right in symbols[i + 1 :]
        if left in corr.index and right in corr.columns and not pd.isna(corr.loc[left, right])
    ]
    return matrix, {
        "average_pairwise_monthly_return_correlation": sum(pair_values) / len(pair_values) if pair_values else None,
        "median_pairwise_monthly_return_correlation": statistics.median(pair_values) if pair_values else None,
        "pair_count": len(pair_values),
    }


def _load_transfer_assets(config: PortfolioSelectionConfig) -> dict[str, dict[str, Any]]:
    payload: dict[str, dict[str, Any]] = {}
    for symbol in TRANSFER_ASSETS:
        paths = _asset_paths(config, symbol)
        if not paths["summary"].exists():
            continue
        summary = _read_json(paths["summary"])
        payload[symbol] = {
            "summary": summary,
            "split": _read_json(paths["split"]) if paths["split"].exists() else {},
            "freeze": _read_json(paths["freeze"]) if paths["freeze"].exists() else {},
            "research_rows": _load_trade_rows(paths["research_trades"], symbol_override=symbol, period="research"),
            "holdout_rows": _load_trade_rows(paths["holdout_trades"], symbol_override=symbol, period="holdout"),
        }
    return payload


def _load_btc_reference(config: PortfolioSelectionConfig) -> dict[str, Any] | None:
    paths = _btc_paths(config)
    if not paths["summary"].exists() or not paths["research_trades"].exists() or not paths["holdout_trades"].exists():
        return None
    return {
        "summary": _read_json(paths["summary"]),
        "research_rows": _load_trade_rows(paths["research_trades"], symbol_override="BTCUSDT", period="research"),
        "holdout_rows": _load_trade_rows(paths["holdout_trades"], symbol_override="BTCUSDT", period="holdout"),
        "source_artifact": str(config.btc_reference_root),
    }


def _asset_scorecard(asset_payload: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, payload in sorted(asset_payload.items()):
        summary = payload["summary"]
        research = summary.get("research_pre_holdout", {}).get("cost_aware_candidate", {})
        holdout = summary.get("sealed_holdout", {}).get("cost_aware_candidate", {})
        rolling = _rolling_5y(payload["research_rows"])
        rows.append(
            {
                "symbol": symbol,
                "classification": summary.get("final_classification"),
                "transfer_supported_after_costs": bool(summary.get("transfer_supported_after_costs")),
                "research_ending_equity": float(research.get("ending_equity") or 0.0),
                "research_trades": int(research.get("accepted_trades") or 0),
                "research_profit_factor": float(research.get("profit_factor") or 0.0),
                "research_win_rate": float(research.get("win_rate") or 0.0),
                "research_max_drawdown": float(research.get("max_drawdown") or 0.0),
                "holdout_ending_equity": float(holdout.get("ending_equity") or 0.0),
                "holdout_trades": int(holdout.get("accepted_trades") or 0),
                "holdout_profit_factor": float(holdout.get("profit_factor") or 0.0),
                "holdout_win_rate": float(holdout.get("win_rate") or 0.0),
                "holdout_max_drawdown": float(holdout.get("max_drawdown") or 0.0),
                "rolling_5y_windows": rolling["window_count"],
                "rolling_5y_windows_above_1m": rolling["windows_above_1m"],
                "rolling_5y_median_ending_equity": rolling["median_ending_equity"],
                "rolling_5y_worst_ending_equity": rolling["minimum_ending_equity"],
                "rolling_5y_best_ending_equity": rolling["maximum_ending_equity"],
                "holdout_clean": bool(payload.get("split", {}).get("holdout_clean")),
                "holdout_opened_once": bool(summary.get("anti_leakage_audit", {}).get("holdout_opened_once")),
                "strategy_unchanged_between_freeze_and_holdout": bool(
                    summary.get("anti_leakage_audit", {}).get("strategy_unchanged_between_freeze_and_holdout")
                ),
            }
        )
    return rows


def _policy_rows(
    *,
    policy_name: str,
    symbols: list[str],
    research_rows_by_symbol: dict[str, list[dict[str, Any]]],
    holdout_rows_by_symbol: dict[str, list[dict[str, Any]]],
    priority: dict[str, int],
) -> dict[str, Any]:
    research_all = [row for symbol in symbols for row in research_rows_by_symbol.get(symbol, [])]
    holdout_all = [row for symbol in symbols for row in holdout_rows_by_symbol.get(symbol, [])]
    research_selected, research_rejected = _select_non_overlapping_shared_pool(research_all, allowed_symbols=symbols, symbol_priority=priority)
    holdout_selected, holdout_rejected = _select_non_overlapping_shared_pool(holdout_all, allowed_symbols=symbols, symbol_priority=priority)
    research_sim = _simulate_sequence(research_selected)
    holdout_sim = _simulate_sequence(holdout_selected)
    rolling = _rolling_5y(research_selected)
    return {
        "policy_name": policy_name,
        "policy_type": "shared_pool_max_one_active_trade",
        "asset_universe": symbols,
        "asset_priority": priority,
        "asset_selection_basis": "research_period_metrics_only_no_holdout_selection",
        "research": {key: value for key, value in research_sim.items() if key != "trade_rows"},
        "sealed_holdout": {key: value for key, value in holdout_sim.items() if key != "trade_rows"},
        "rolling_5y": {key: value for key, value in rolling.items() if key != "windows"},
        "research_rejected_overlap_count": len(research_rejected),
        "holdout_rejected_overlap_count": len(holdout_rejected),
        "research_selected_trades": research_sim["trade_rows"],
        "holdout_selected_trades": holdout_sim["trade_rows"],
    }


def _write_report(config: PortfolioSelectionConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# Multi-Asset Portfolio Selection Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        "- Research-only diagnostic. No paper/live/order/broker path enabled.",
        "- Inputs are completed cost-aware frozen-transfer ledgers; strategy logic was not rerun or changed.",
        "- Portfolio policies use research-period ranking only before sealed-holdout evaluation.",
        "",
        "## Asset scorecard",
        "",
        "| Symbol | Research ending | Holdout ending | Rolling 5Y > €1M | Median rolling 5Y | Holdout PF | Holdout max DD |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summary["asset_scorecard"]:
        lines.append(
            "| {symbol} | €{research:,.2f} | €{holdout:,.2f} | {above}/{windows} | €{median:,.2f} | {pf:.2f} | {dd:.2%} |".format(
                symbol=row["symbol"],
                research=float(row["research_ending_equity"]),
                holdout=float(row["holdout_ending_equity"]),
                above=int(row["rolling_5y_windows_above_1m"]),
                windows=int(row["rolling_5y_windows"]),
                median=float(row["rolling_5y_median_ending_equity"]),
                pf=float(row["holdout_profit_factor"]),
                dd=float(row["holdout_max_drawdown"]),
            )
        )
    lines.extend(
        [
            "",
            "## Shared-pool policies",
            "",
            "| Policy | Assets | Research ending | Holdout ending | Rolling 5Y > €1M | Median rolling 5Y | Holdout trades |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for policy in summary["portfolio_policies"]:
        roll = policy["rolling_5y"]
        lines.append(
            "| `{name}` | {assets} | €{research:,.2f} | €{holdout:,.2f} | {above}/{windows} | €{median:,.2f} | {trades} |".format(
                name=policy["policy_name"],
                assets=", ".join(policy["asset_universe"]),
                research=float(policy["research"]["ending_equity"]),
                holdout=float(policy["sealed_holdout"]["ending_equity"]),
                above=int(roll.get("windows_above_1m") or 0),
                windows=int(roll.get("window_count") or 0),
                median=float(roll.get("median_ending_equity") or 0.0),
                trades=int(policy["sealed_holdout"]["accepted_trades"]),
            )
        )
    lines.extend(
        [
            "",
            "## BTC reference comparison",
            "",
            "BTC is included only where explicitly relevant for ADA/BTC portfolio comparison.",
        ]
    )
    for item in summary.get("btc_reference_comparison", {}).get("policies", []):
        lines.append(
            f"- `{item['policy_name']}`: research €{float(item['research']['ending_equity']):,.2f}, "
            f"holdout €{float(item['sealed_holdout']['ending_equity']):,.2f}"
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- `paper_validation_ready`: `{summary['paper_validation_ready']}`",
            f"- `paper_allowed`: `{summary['paper_allowed']}`",
            f"- `live_allowed`: `{summary['live_allowed']}`",
            f"- `real_money_allowed`: `{summary['real_money_allowed']}`",
            f"- `no_order_path_created`: `{summary['no_order_path_created']}`",
            f"- `no_broker_path_created`: `{summary['no_broker_path_created']}`",
        ]
    )
    (config.output_root / "multi_asset_portfolio_selection_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: PortfolioSelectionConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    transfer_summary_path = config.transfer_root / "multi_asset_frozen_transfer_summary.json"
    if not transfer_summary_path.exists():
        summary = {"court_name": COURT_NAME, "final_classification": BLOCKED, "classification_reasons": ["missing_multi_asset_transfer_summary"], **SAFETY_FLAGS}
        _write_json(config.output_root / "multi_asset_portfolio_selection_summary.json", summary)
        return summary
    transfer_summary = _read_json(transfer_summary_path)
    assets = _load_transfer_assets(config)
    missing = [symbol for symbol in TRANSFER_ASSETS if symbol not in assets]
    if missing:
        summary = {"court_name": COURT_NAME, "final_classification": BLOCKED, "classification_reasons": [f"missing_assets:{','.join(missing)}"], **SAFETY_FLAGS}
        _write_json(config.output_root / "multi_asset_portfolio_selection_summary.json", summary)
        return summary

    scorecard = _asset_scorecard(assets)
    research_rank = sorted(scorecard, key=lambda row: float(row["research_ending_equity"]), reverse=True)
    holdout_rank_observation_only = sorted(scorecard, key=lambda row: float(row["holdout_ending_equity"]), reverse=True)
    research_priority_symbols = [row["symbol"] for row in research_rank]
    priority = {symbol: index for index, symbol in enumerate(research_priority_symbols, start=1)}
    research_rows_by_symbol = {symbol: payload["research_rows"] for symbol, payload in assets.items()}
    holdout_rows_by_symbol = {symbol: payload["holdout_rows"] for symbol, payload in assets.items()}
    asset_sims_research = {symbol: _simulate_sequence(rows) for symbol, rows in research_rows_by_symbol.items()}
    asset_sims_holdout = {symbol: _simulate_sequence(rows) for symbol, rows in holdout_rows_by_symbol.items()}

    policies: list[dict[str, Any]] = []
    for count in (1, 3, 5, 8):
        selected = research_priority_symbols[:count]
        policies.append(
            _policy_rows(
                policy_name=f"research_rank_top_{count}_shared_pool",
                symbols=selected,
                research_rows_by_symbol=research_rows_by_symbol,
                holdout_rows_by_symbol=holdout_rows_by_symbol,
                priority=priority,
            )
        )
    equal_sleeves = [
        {
            "policy_name": f"research_rank_top_{count}_equal_sleeves_observation",
            "policy_type": "equal_sleeves_independent_asset_simulation",
            "asset_universe": research_priority_symbols[:count],
            "asset_selection_basis": "research_period_metrics_only_no_holdout_selection",
            "research": _equal_sleeve_result(asset_sims_research, research_priority_symbols[:count]),
            "sealed_holdout": _equal_sleeve_result(asset_sims_holdout, research_priority_symbols[:count]),
        }
        for count in (3, 5, 8)
    ]

    correlation_matrix, correlation_summary = _correlation_matrix(research_rows_by_symbol, list(TRANSFER_ASSETS))
    btc_reference = _load_btc_reference(config)
    btc_comparison: dict[str, Any] = {
        "included_because_user_asked_about_ADA_plus_BTC": bool(btc_reference),
        "note": "BTC reference comes from cost-aware frozen candidate artifacts, not the 8-asset transfer court.",
    }
    if btc_reference:
        with_btc_research = dict(research_rows_by_symbol)
        with_btc_holdout = dict(holdout_rows_by_symbol)
        with_btc_research["BTCUSDT"] = btc_reference["research_rows"]
        with_btc_holdout["BTCUSDT"] = btc_reference["holdout_rows"]
        btc_priority = {
            "ADAUSDT": 1,
            "BTCUSDT": 2,
            "LINKUSDT": 3,
            "BNBUSDT": 4,
            "DOGEUSDT": 5,
        }
        btc_policies = [
            _policy_rows(
                policy_name="btc_reference_only_shared_pool",
                symbols=["BTCUSDT"],
                research_rows_by_symbol=with_btc_research,
                holdout_rows_by_symbol=with_btc_holdout,
                priority={"BTCUSDT": 1},
            ),
            _policy_rows(
                policy_name="ada_plus_btc_shared_pool",
                symbols=["ADAUSDT", "BTCUSDT"],
                research_rows_by_symbol=with_btc_research,
                holdout_rows_by_symbol=with_btc_holdout,
                priority=btc_priority,
            ),
            _policy_rows(
                policy_name="ada_btc_link_bnb_shared_pool",
                symbols=["ADAUSDT", "BTCUSDT", "LINKUSDT", "BNBUSDT"],
                research_rows_by_symbol=with_btc_research,
                holdout_rows_by_symbol=with_btc_holdout,
                priority=btc_priority,
            ),
        ]
        btc_corr_matrix, btc_corr_summary = _correlation_matrix(with_btc_research, ["BTCUSDT", "ADAUSDT", "LINKUSDT", "BNBUSDT"])
        btc_only = btc_policies[0]
        ada_btc = btc_policies[1]
        btc_comparison.update(
            {
                "btc_source_artifact": btc_reference["source_artifact"],
                "policies": [{key: value for key, value in policy.items() if key not in {"research_selected_trades", "holdout_selected_trades"}} for policy in btc_policies],
                "monthly_return_correlation_matrix": btc_corr_matrix,
                "monthly_return_correlation_summary": btc_corr_summary,
                "ada_plus_btc_improves_btc_research_ending": ada_btc["research"]["ending_equity"] > btc_only["research"]["ending_equity"],
                "ada_plus_btc_improves_btc_holdout_ending": ada_btc["sealed_holdout"]["ending_equity"] > btc_only["sealed_holdout"]["ending_equity"],
            }
        )
        for policy in btc_policies:
            _write_csv(config.output_root / f"{policy['policy_name']}_research_trades.csv", policy["research_selected_trades"])
            _write_csv(config.output_root / f"{policy['policy_name']}_holdout_trades.csv", policy["holdout_selected_trades"])

    top_policy = max(policies, key=lambda item: float(item["sealed_holdout"]["ending_equity"]))
    all_assets_clean = all(bool(row["holdout_clean"]) and bool(row["holdout_opened_once"]) for row in scorecard)
    classification_reasons: list[str] = []
    if transfer_summary.get("final_classification") != "MULTI_ASSET_FROZEN_TRANSFER_VALIDATED_RESEARCH_ONLY":
        final_classification = WARNING
        classification_reasons.append("source_transfer_court_not_clean_pass")
    elif not all_assets_clean:
        final_classification = WARNING
        classification_reasons.append("one_or_more_assets_failed_holdout_cleanliness_audit")
    elif top_policy["sealed_holdout"]["ending_equity"] > START_CAPITAL and top_policy["rolling_5y"].get("windows_above_1m", 0) > 0:
        final_classification = PASSED
        classification_reasons.append("research_ranked_shared_pool_profitable_in_holdout_and_has_rolling_5y_million_windows")
    elif top_policy["sealed_holdout"]["ending_equity"] > START_CAPITAL:
        final_classification = WARNING
        classification_reasons.append("research_ranked_shared_pool_profitable_in_holdout_but_rolling_5y_million_evidence_weak")
    else:
        final_classification = FAILED
        classification_reasons.append("research_ranked_shared_pool_not_profitable_in_holdout")

    slim_policies = [{key: value for key, value in policy.items() if key not in {"research_selected_trades", "holdout_selected_trades"}} for policy in policies]
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": final_classification,
        "classification_reasons": classification_reasons,
        "source_transfer_summary": str(transfer_summary_path),
        "asset_scorecard": scorecard,
        "research_rank_by_ending_equity": research_priority_symbols,
        "holdout_rank_observation_only_not_used_for_selection": [row["symbol"] for row in holdout_rank_observation_only],
        "portfolio_policies": slim_policies,
        "equal_sleeve_observations": equal_sleeves,
        "best_shared_pool_policy_by_holdout": top_policy["policy_name"],
        "monthly_return_correlation_matrix": correlation_matrix,
        "monthly_return_correlation_summary": correlation_summary,
        "btc_reference_comparison": btc_comparison,
        "methodology": {
            "strategy_logic_changed": False,
            "thresholds_tuned": False,
            "entries_changed": False,
            "exits_changed": False,
            "position_sizing_changed_in_source_engine": False,
            "uses_existing_cost_aware_trade_ledgers": True,
            "normal_round_trip_cost_bps": 15.0,
            "max_pre_entry_cost_r": 1.0,
            "shared_pool_rule": "max_one_active_trade_at_a_time",
            "shared_pool_risk_per_trade": RISK_PER_TRADE,
            "asset_selection_for_holdout": "fixed_from_research_ranking_before_holdout_scoring",
            "holdout_rank_is_observation_only": True,
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_asset_portfolio_selection_summary.json", summary)
    _write_csv(config.output_root / "multi_asset_portfolio_asset_scorecard.csv", scorecard)
    _write_csv(
        config.output_root / "multi_asset_portfolio_policy_scorecard.csv",
        [
            {
                "policy_name": policy["policy_name"],
                "policy_type": policy["policy_type"],
                "asset_universe": ",".join(policy["asset_universe"]),
                "research_ending_equity": policy["research"]["ending_equity"],
                "research_trades": policy["research"]["accepted_trades"],
                "research_max_drawdown": policy["research"]["max_drawdown"],
                "holdout_ending_equity": policy["sealed_holdout"]["ending_equity"],
                "holdout_trades": policy["sealed_holdout"]["accepted_trades"],
                "holdout_max_drawdown": policy["sealed_holdout"]["max_drawdown"],
                "rolling_5y_windows_above_1m": policy["rolling_5y"].get("windows_above_1m"),
                "rolling_5y_window_count": policy["rolling_5y"].get("window_count"),
                "rolling_5y_median_ending_equity": policy["rolling_5y"].get("median_ending_equity"),
                "research_rejected_overlap_count": policy["research_rejected_overlap_count"],
                "holdout_rejected_overlap_count": policy["holdout_rejected_overlap_count"],
            }
            for policy in policies
        ],
    )
    for policy in policies:
        _write_csv(config.output_root / f"{policy['policy_name']}_research_trades.csv", policy["research_selected_trades"])
        _write_csv(config.output_root / f"{policy['policy_name']}_holdout_trades.csv", policy["holdout_selected_trades"])
    _write_report(config, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the multi-asset portfolio selection court from completed frozen-transfer artifacts.")
    parser.add_argument("--transfer-root", default=f"structural_compounding_lab/output/multi_asset_frozen_transfer_court_001")
    parser.add_argument("--btc-reference-root", default=f"structural_compounding_lab/output/cost_aware_frozen_candidate_rebuild_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        PortfolioSelectionConfig(
            project_root=root,
            package_root=package_root(),
            transfer_root=resolve_project_path(args.transfer_root),
            btc_reference_root=resolve_project_path(args.btc_reference_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
