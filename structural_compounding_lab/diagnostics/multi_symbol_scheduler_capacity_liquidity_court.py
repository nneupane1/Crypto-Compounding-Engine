from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path


COURT_NAME = "MULTI_SYMBOL_SCHEDULER_DRY_RUN_AND_CAPACITY_LIQUIDITY_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_symbol_scheduler_capacity_liquidity_court_001"

PASSED = "MULTI_SYMBOL_SCHEDULER_CAPACITY_LIQUIDITY_READY_RESEARCH_ONLY"
WARNING = "MULTI_SYMBOL_SCHEDULER_CAPACITY_LIQUIDITY_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_SYMBOL_SCHEDULER_CAPACITY_LIQUIDITY_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_SYMBOL_SCHEDULER_CAPACITY_LIQUIDITY_BLOCKED_RESEARCH_ONLY"

TRANSFER_ASSETS: tuple[str, ...] = (
    "ADAUSDT",
    "LINKUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "AVAXUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "SOLUSDT",
)

START_CAPITAL_EUR = 25_000.0
SELECTED_ACTIVE_CAP_EUR = 250_000.0
BASELINE_COST_BPS = 15.0
DEPTH_BPS_LEVELS: tuple[int, ...] = (10, 25, 50, 100)
PUBLIC_BINANCE_BASE_URL = "https://api.binance.com"
EUR_TO_USDT_FALLBACK = 1.10

MAX_NOTIONAL_BY_SYMBOL_EUR: dict[str, float] = {
    "ADAUSDT": 250_000.0,
    "LINKUSDT": 250_000.0,
    "BNBUSDT": 350_000.0,
    "XRPUSDT": 250_000.0,
    "AVAXUSDT": 250_000.0,
    "DOGEUSDT": 200_000.0,
    "ETHUSDT": 500_000.0,
    "SOLUSDT": 350_000.0,
}

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "paper_validation_ready": False,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "private_endpoint_used": False,
    "signed_endpoint_used": False,
    "account_endpoint_used": False,
    "trade_execution_endpoint_used": False,
    "no_order_path_created": True,
    "no_broker_path_created": True,
    "strategy_logic_changed": False,
    "thresholds_tuned": False,
    "entries_changed": False,
    "exits_changed": False,
    "sizing_changed": False,
}


@dataclass(frozen=True)
class SchedulerCapacityConfig:
    project_root: Path
    package_root: Path
    scanner_root: Path
    capital_cap_root: Path
    scheduler_root: Path
    runtime_root: Path
    output_root: Path
    fetch_public_market_data: bool = True


def default_config() -> SchedulerCapacityConfig:
    pkg = package_root()
    return SchedulerCapacityConfig(
        project_root=project_root(),
        package_root=pkg,
        scanner_root=pkg / "output" / "multi_asset_execution_feasibility_scanner_replay_court_001",
        capital_cap_root=pkg / "output" / "multi_asset_capital_cap_liquidity_realism_court_001",
        scheduler_root=pkg / "output" / "continuous_scheduler_forward_validation_court_001",
        runtime_root=pkg / "output" / "forward_validation_runtime",
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


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in keys})


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _parse_ts(value: str) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def _http_json(url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Crypto-Compounding-Engine-Research-Court/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _load_selected_trades(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            payload = dict(row)
            payload["symbol"] = str(row.get("symbol") or "").upper()
            payload["entry_timestamp"] = _parse_ts(str(row.get("entry_time")))
            payload["exit_timestamp"] = _parse_ts(str(row.get("exit_time")))
            payload["net_r"] = float(row.get("net_r") or 0.0)
            payload["risk_eur"] = float(row.get("risk_eur") or 0.0)
            rows.append(payload)
    return sorted(rows, key=lambda item: (item["entry_timestamp"], item["symbol"]))


def _event_load(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_hour: dict[str, int] = {}
    by_day: dict[str, int] = {}
    by_symbol: dict[str, int] = {}
    durations: list[float] = []
    for row in rows:
        hour = row["entry_timestamp"].floor("h").isoformat()
        day = row["entry_timestamp"].date().isoformat()
        by_hour[hour] = by_hour.get(hour, 0) + 1
        by_day[day] = by_day.get(day, 0) + 1
        by_symbol[row["symbol"]] = by_symbol.get(row["symbol"], 0) + 1
        durations.append(max(0.0, (row["exit_timestamp"] - row["entry_timestamp"]).total_seconds() / 3600.0))
    busiest_hours = sorted(by_hour.items(), key=lambda item: (-item[1], item[0]))[:10]
    busiest_days = sorted(by_day.items(), key=lambda item: (-item[1], item[0]))[:10]
    return {
        "selected_trades": len(rows),
        "symbol_count": len(by_symbol),
        "symbols": sorted(by_symbol),
        "selected_trades_by_symbol": dict(sorted(by_symbol.items())),
        "max_selected_entries_per_hour": max(by_hour.values()) if by_hour else 0,
        "max_selected_entries_per_day": max(by_day.values()) if by_day else 0,
        "busiest_hours": [{"hour": key, "selected_entries": value} for key, value in busiest_hours],
        "busiest_days": [{"day": key, "selected_entries": value} for key, value in busiest_days],
        "median_trade_duration_hours": statistics.median(durations) if durations else 0.0,
        "max_trade_duration_hours": max(durations) if durations else 0.0,
    }


def _scheduler_status(config: SchedulerCapacityConfig) -> dict[str, Any]:
    summary = _read_json(config.scheduler_root / "continuous_scheduler_forward_validation_summary.json")
    cockpit = _read_json(config.scheduler_root / "forward_validation_cockpit.json")
    runtime = _read_json(config.runtime_root / "latest_status.json")
    return {
        "scheduler_summary_path": str(config.scheduler_root / "continuous_scheduler_forward_validation_summary.json"),
        "runtime_latest_status_path": str(config.runtime_root / "latest_status.json"),
        "scheduler_classification": summary.get("final_classification"),
        "cockpit_status_color": cockpit.get("status_color"),
        "scheduler_health": cockpit.get("scheduler_health"),
        "scheduler_installed": bool(runtime.get("scheduler_installed", summary.get("scheduler_installed", False))),
        "scheduler_loaded": bool(runtime.get("scheduler_loaded", summary.get("scheduler_loaded", False))),
        "caught_up_to_realtime": bool(runtime.get("caught_up_to_realtime", False)),
        "runtime_final_reason": runtime.get("final_reason"),
        "latest_canonical_timestamp": runtime.get("latest_canonical_timestamp"),
        "paper_validation_ready": bool(runtime.get("paper_validation_ready", summary.get("paper_validation_ready", False))),
        "paper_allowed": bool(runtime.get("paper_allowed", summary.get("paper_allowed", False))),
        "live_allowed": bool(runtime.get("live_allowed", summary.get("live_allowed", False))),
        "order_path_exists": bool(runtime.get("order_path_exists", False)),
        "broker_path_exists": bool(runtime.get("broker_path_exists", False)),
    }


def _scheduler_dry_run_plan() -> dict[str, Any]:
    symbol_count = len(TRANSFER_ASSETS)
    return {
        "mode": "dry_run_plan_only",
        "multi_symbol_scheduler_installed_by_this_court": False,
        "symbols": list(TRANSFER_ASSETS),
        "symbol_count": symbol_count,
        "expected_public_1m_candles_per_hour": symbol_count * 60,
        "expected_15m_bars_per_hour": symbol_count * 4,
        "expected_1h_decision_slots_per_hour": symbol_count,
        "decision_boundary": "closed_1h_candle_only",
        "minimum_safe_cadence_minutes": 1,
        "hour_close_processing_expectation": "process missed closed candles once, then continue",
        "idempotency_requirement": "immediate rerun must produce zero duplicate candles and zero duplicate decisions",
        "private_or_signed_market_data_required": False,
        "broker_or_execution_connector_required": False,
    }


def _quote_volume_row(symbol: str) -> dict[str, Any]:
    payload = _http_json(f"{PUBLIC_BINANCE_BASE_URL}/api/v3/ticker/24hr?{urllib.parse.urlencode({'symbol': symbol})}")
    return {
        "symbol": symbol,
        "last_price": float(payload.get("lastPrice") or 0.0),
        "quote_volume_usdt_24h": float(payload.get("quoteVolume") or 0.0),
        "price_change_percent_24h": float(payload.get("priceChangePercent") or 0.0),
        "trade_count_24h": int(payload.get("count") or 0),
    }


def _depth_row(symbol: str, *, notional_usdt: float) -> dict[str, Any]:
    payload = _http_json(f"{PUBLIC_BINANCE_BASE_URL}/api/v3/depth?{urllib.parse.urlencode({'symbol': symbol, 'limit': 5000})}")
    bids = [(float(price), float(qty)) for price, qty in payload.get("bids", [])]
    asks = [(float(price), float(qty)) for price, qty in payload.get("asks", [])]
    best_bid = bids[0][0] if bids else 0.0
    best_ask = asks[0][0] if asks else 0.0
    mid = (best_bid + best_ask) / 2.0 if best_bid and best_ask else 0.0
    row: dict[str, Any] = {
        "symbol": symbol,
        "order_book_last_update_id": payload.get("lastUpdateId"),
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread_bps": _safe_ratio(best_ask - best_bid, mid, 0.0) * 10_000.0 if mid else None,
        "assumed_max_gross_notional_usdt": notional_usdt,
    }
    for bps in DEPTH_BPS_LEVELS:
        ask_limit = mid * (1.0 + bps / 10_000.0)
        bid_limit = mid * (1.0 - bps / 10_000.0)
        ask_depth = sum(price * qty for price, qty in asks if price <= ask_limit)
        bid_depth = sum(price * qty for price, qty in bids if price >= bid_limit)
        min_depth = min(ask_depth, bid_depth)
        row[f"ask_depth_usdt_{bps}bps"] = ask_depth
        row[f"bid_depth_usdt_{bps}bps"] = bid_depth
        row[f"min_two_sided_depth_usdt_{bps}bps"] = min_depth
        row[f"min_two_sided_depth_to_notional_ratio_{bps}bps"] = _safe_ratio(min_depth, notional_usdt, 0.0)
    return row


def _fetch_eur_to_usdt() -> dict[str, Any]:
    try:
        payload = _http_json("https://api.frankfurter.app/latest?from=EUR&to=USD", timeout=8.0)
        rate = float((payload.get("rates") or {}).get("USD") or 0.0)
        if rate > 0.0:
            return {"eur_to_usdt": rate, "source": "frankfurter_public_eur_usd_proxy", "fallback_used": False}
    except Exception as exc:  # noqa: BLE001 - diagnostic should degrade to explicit warning
        return {
            "eur_to_usdt": EUR_TO_USDT_FALLBACK,
            "source": "fallback_static_proxy",
            "fallback_used": True,
            "warning": f"{type(exc).__name__}: {exc}",
        }
    return {"eur_to_usdt": EUR_TO_USDT_FALLBACK, "source": "fallback_static_proxy", "fallback_used": True}


def _public_market_capacity(fetch: bool) -> dict[str, Any]:
    eur_rate = _fetch_eur_to_usdt() if fetch else {"eur_to_usdt": EUR_TO_USDT_FALLBACK, "source": "disabled_fallback", "fallback_used": True}
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    if fetch:
        for symbol in TRANSFER_ASSETS:
            max_notional_eur = min(SELECTED_ACTIVE_CAP_EUR, MAX_NOTIONAL_BY_SYMBOL_EUR[symbol])
            max_notional_usdt = max_notional_eur * float(eur_rate["eur_to_usdt"])
            try:
                quote = _quote_volume_row(symbol)
                time.sleep(0.05)
                depth = _depth_row(symbol, notional_usdt=max_notional_usdt)
                time.sleep(0.05)
                rows.append(
                    {
                        **quote,
                        **depth,
                        "assumed_max_gross_notional_eur": max_notional_eur,
                        "quote_volume_to_assumed_notional_ratio": _safe_ratio(quote["quote_volume_usdt_24h"], max_notional_usdt, 0.0),
                    }
                )
            except (urllib.error.URLError, TimeoutError, ValueError, KeyError, json.JSONDecodeError) as exc:
                errors.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
    else:
        for symbol in TRANSFER_ASSETS:
            max_notional_eur = min(SELECTED_ACTIVE_CAP_EUR, MAX_NOTIONAL_BY_SYMBOL_EUR[symbol])
            rows.append(
                {
                    "symbol": symbol,
                    "assumed_max_gross_notional_eur": max_notional_eur,
                    "assumed_max_gross_notional_usdt": max_notional_eur * float(eur_rate["eur_to_usdt"]),
                    "market_data_fetch_disabled": True,
                }
            )
    depth_25 = [float(row.get("min_two_sided_depth_to_notional_ratio_25bps") or 0.0) for row in rows]
    volume = [float(row.get("quote_volume_to_assumed_notional_ratio") or 0.0) for row in rows]
    spread = [float(row.get("spread_bps") or 0.0) for row in rows if row.get("spread_bps") is not None]
    return {
        "public_market_data_source": PUBLIC_BINANCE_BASE_URL,
        "public_unsigned_market_data_only": True,
        "fetched_at_utc": _now(),
        "eur_to_usdt_proxy": eur_rate,
        "assumption": {
            "true_position_notional_not_available_in_selected_trade_ledgers": True,
            "assumed_max_gross_notional_is_min_selected_active_cap_and_symbol_notional_cap": True,
            "selected_active_cap_eur": SELECTED_ACTIVE_CAP_EUR,
            "symbol_notional_caps_eur": MAX_NOTIONAL_BY_SYMBOL_EUR,
            "requires_future_exact_fill_simulation_before_real_money": True,
        },
        "rows": rows,
        "errors": errors,
        "market_data_fetch_complete": fetch and not errors and len(rows) == len(TRANSFER_ASSETS),
        "minimum_25bps_two_sided_depth_to_notional_ratio": min(depth_25) if depth_25 else 0.0,
        "minimum_24h_quote_volume_to_notional_ratio": min(volume) if volume else 0.0,
        "maximum_spread_bps": max(spread) if spread else None,
        "all_symbols_depth_25bps_covers_assumed_notional": bool(depth_25) and min(depth_25) >= 1.0,
        "all_symbols_24h_volume_at_least_25x_assumed_notional": bool(volume) and min(volume) >= 25.0,
    }


def _write_report(config: SchedulerCapacityConfig, summary: dict[str, Any]) -> None:
    capacity = summary["public_market_capacity"]
    selected = summary["capital_cap_reference"]["selected_planning_cap_result"]
    holdout = summary["capital_cap_reference"]["selected_planning_cap_holdout_result_no_tax"]
    lines = [
        "# Multi-Symbol Scheduler Capacity and Liquidity Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        "- Research-only. No paper/live/execution/broker path enabled.",
        "- Uses existing frozen scanner/capital-cap artifacts; strategy logic was not rerun or changed.",
        "- Public unsigned Binance market data only for current depth/volume proxy.",
        "",
        "## Scheduler dry-run",
        "",
        f"- Existing scheduler installed: `{str(summary['scheduler_status']['scheduler_installed']).lower()}`",
        f"- Existing scheduler loaded: `{str(summary['scheduler_status']['scheduler_loaded']).lower()}`",
        f"- Existing runtime caught up: `{str(summary['scheduler_status']['caught_up_to_realtime']).lower()}`",
        f"- Multi-symbol scheduler installed by this court: `{str(summary['scheduler_dry_run_plan']['multi_symbol_scheduler_installed_by_this_court']).lower()}`",
        f"- Symbols in dry-run plan: `{', '.join(summary['scheduler_dry_run_plan']['symbols'])}`",
        f"- Expected 1m candles processed per hour: `{summary['scheduler_dry_run_plan']['expected_public_1m_candles_per_hour']}`",
        f"- Expected 1H decision slots per hour: `{summary['scheduler_dry_run_plan']['expected_1h_decision_slots_per_hour']}`",
        "",
        "## Existing validated scanner/cap reference",
        "",
        f"- Scanner classification: `{summary['scanner_reference']['final_classification']}`",
        f"- Capital-cap classification: `{summary['capital_cap_reference']['final_classification']}`",
        f"- Selected planning cap ending after tax: `€{float(selected['ending_total_equity_after_tax']):,.2f}`",
        f"- Selected planning cap tax reserve: `€{float(selected['total_tax_reserved_or_withdrawn']):,.2f}`",
        f"- Sealed holdout at selected cap, no tax: `€{float(holdout['ending_total_equity_after_tax']):,.2f}`",
        "",
        "## Public liquidity proxy",
        "",
        f"- Market data fetch complete: `{str(capacity['market_data_fetch_complete']).lower()}`",
        f"- Minimum 25 bps two-sided depth / assumed notional: `{float(capacity['minimum_25bps_two_sided_depth_to_notional_ratio']):.2f}x`",
        f"- Minimum 24h quote volume / assumed notional: `{float(capacity['minimum_24h_quote_volume_to_notional_ratio']):.2f}x`",
        f"- Maximum current spread: `{capacity['maximum_spread_bps']}` bps",
        "",
        "| Symbol | Assumed max notional | 24h quote vol / notional | 25bps depth / notional | Spread bps |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for row in capacity["rows"]:
        lines.append(
            "| {symbol} | €{notional:,.0f} | {volume:.2f}x | {depth:.2f}x | {spread} |".format(
                symbol=row["symbol"],
                notional=float(row.get("assumed_max_gross_notional_eur") or 0.0),
                volume=float(row.get("quote_volume_to_assumed_notional_ratio") or 0.0),
                depth=float(row.get("min_two_sided_depth_to_notional_ratio_25bps") or 0.0),
                spread=row.get("spread_bps"),
            )
        )
    lines.extend(
        [
            "",
            "## Gate",
            "",
            f"- May freeze multi-asset scanner spec: `{str(summary['gate']['may_freeze_multi_asset_scanner_research_spec']).lower()}`",
            f"- May enable paper trading: `{str(summary['gate']['may_enable_paper_trading']).lower()}`",
            f"- May enable live trading: `{str(summary['gate']['may_enable_live_trading']).lower()}`",
            f"- Next required court: `{summary['gate']['next_required_court']}`",
        ]
    )
    (config.output_root / "multi_symbol_scheduler_capacity_liquidity_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: SchedulerCapacityConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)

    scanner_path = config.scanner_root / "multi_asset_execution_feasibility_scanner_replay_summary.json"
    cap_path = config.capital_cap_root / "multi_asset_capital_cap_liquidity_realism_summary.json"
    research_trades_path = config.scanner_root / "research_scanner_selected_trades.csv"
    holdout_trades_path = config.scanner_root / "sealed_holdout_scanner_selected_trades.csv"
    scanner = _read_json(scanner_path)
    cap = _read_json(cap_path)

    if not scanner or not cap or not research_trades_path.exists() or not holdout_trades_path.exists():
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_scanner_or_capital_cap_artifacts"],
            "source_scanner_summary": str(scanner_path),
            "source_capital_cap_summary": str(cap_path),
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_symbol_scheduler_capacity_liquidity_summary.json", summary)
        return summary

    research_rows = _load_selected_trades(research_trades_path)
    holdout_rows = _load_selected_trades(holdout_trades_path)
    scheduler = _scheduler_status(config)
    dry_run = _scheduler_dry_run_plan()
    capacity = _public_market_capacity(config.fetch_public_market_data)

    scanner_ok = scanner.get("final_classification") == "MULTI_ASSET_SCANNER_REPLAY_VALIDATED_RESEARCH_ONLY"
    cap_ok = cap.get("final_classification") == "MULTI_ASSET_CAPITAL_CAP_REALISM_VALIDATED_RESEARCH_ONLY"
    scheduler_ok = (
        scheduler["scheduler_installed"]
        and scheduler["scheduler_loaded"]
        and scheduler["caught_up_to_realtime"]
        and not scheduler["paper_validation_ready"]
        and not scheduler["paper_allowed"]
        and not scheduler["live_allowed"]
        and not scheduler["order_path_exists"]
        and not scheduler["broker_path_exists"]
    )
    capacity_ok = (
        capacity["market_data_fetch_complete"]
        and capacity["all_symbols_depth_25bps_covers_assumed_notional"]
        and capacity["all_symbols_24h_volume_at_least_25x_assumed_notional"]
    )
    safety_ok = all(
        [
            not SAFETY_FLAGS["paper_allowed"],
            not SAFETY_FLAGS["live_allowed"],
            not SAFETY_FLAGS["real_money_allowed"],
            not SAFETY_FLAGS["behavior_change_allowed"],
            SAFETY_FLAGS["no_order_path_created"],
            SAFETY_FLAGS["no_broker_path_created"],
            not SAFETY_FLAGS["private_endpoint_used"],
            not SAFETY_FLAGS["signed_endpoint_used"],
        ]
    )

    reasons: list[str] = []
    if scanner_ok and cap_ok and scheduler_ok and capacity_ok and safety_ok:
        classification = PASSED
        reasons.append("scanner_cap_scheduler_and_public_liquidity_proxy_passed")
    elif scanner_ok and cap_ok and scheduler_ok and safety_ok:
        classification = WARNING
        reasons.append("research_stack_passed_but_public_liquidity_proxy_needs_review")
        if capacity["errors"]:
            reasons.append("public_market_data_fetch_errors_present")
        if not capacity["all_symbols_depth_25bps_covers_assumed_notional"]:
            reasons.append("one_or_more_symbols_depth_25bps_below_assumed_notional")
        if not capacity["all_symbols_24h_volume_at_least_25x_assumed_notional"]:
            reasons.append("one_or_more_symbols_24h_volume_below_25x_assumed_notional")
    else:
        classification = FAILED
        if not scanner_ok:
            reasons.append("scanner_replay_not_validated")
        if not cap_ok:
            reasons.append("capital_cap_realism_not_validated")
        if not scheduler_ok:
            reasons.append("current_scheduler_health_or_safety_gate_failed")
        if not safety_ok:
            reasons.append("safety_gate_failed")

    selected_cap = cap.get("selected_planning_cap_result", {})
    selected_holdout = cap.get("selected_planning_cap_holdout_result_no_tax", {})
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_scanner_summary": str(scanner_path),
        "source_capital_cap_summary": str(cap_path),
        "source_research_scanner_trades": str(research_trades_path),
        "source_holdout_scanner_trades": str(holdout_trades_path),
        "scanner_reference": {
            "final_classification": scanner.get("final_classification"),
            "research_freeze_recommendation": scanner.get("research_freeze_recommendation"),
            "fixed_scanner_priority": scanner.get("fixed_scanner_priority"),
            "holdout_ending_equity": scanner.get("scanner_replay", {}).get("sealed_holdout", {}).get("simulation", {}).get("ending_equity"),
            "holdout_selected_trades": scanner.get("scanner_replay", {}).get("sealed_holdout", {}).get("simulation", {}).get("accepted_trades"),
            "holdout_max_drawdown": scanner.get("scanner_replay", {}).get("sealed_holdout", {}).get("simulation", {}).get("max_drawdown"),
        },
        "capital_cap_reference": {
            "final_classification": cap.get("final_classification"),
            "selected_planning_cap_result": selected_cap,
            "selected_planning_cap_holdout_result_no_tax": selected_holdout,
            "active_caps_reaching_1m_after_tax": cap.get("active_caps_reaching_1m_after_tax"),
            "interpretation_limits": cap.get("interpretation_limits"),
        },
        "scheduler_status": scheduler,
        "scheduler_dry_run_plan": dry_run,
        "operational_load_research": _event_load(research_rows),
        "operational_load_sealed_holdout": _event_load(holdout_rows),
        "public_market_capacity": {key: value for key, value in capacity.items() if key != "rows"},
        "public_market_capacity_rows_file": str(config.output_root / "public_binance_depth_volume_capacity_rows.csv"),
        "gate": {
            "may_freeze_multi_asset_scanner_research_spec": classification in {PASSED, WARNING} and scanner_ok and cap_ok and scheduler_ok,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_execution_or_broker_path": False,
            "paper_validation_ready": False,
            "next_required_court": "MULTI_SYMBOL_REALTIME_SCHEDULER_SHADOW_DRY_RUN_IDEMPOTENCY_COURT",
            "requires_future_exact_fill_simulation_before_real_money": True,
        },
        **SAFETY_FLAGS,
    }

    _write_json(config.output_root / "multi_symbol_scheduler_capacity_liquidity_summary.json", summary)
    _write_csv(config.output_root / "public_binance_depth_volume_capacity_rows.csv", capacity["rows"])
    _write_csv(
        config.output_root / "scheduler_operational_load_summary.csv",
        [
            {"period": "research", **summary["operational_load_research"]},
            {"period": "sealed_holdout", **summary["operational_load_sealed_holdout"]},
        ],
    )
    _write_report(config, {**summary, "public_market_capacity": capacity})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-symbol scheduler dry-run and capacity/liquidity research court.")
    parser.add_argument("--scanner-root", default="structural_compounding_lab/output/multi_asset_execution_feasibility_scanner_replay_court_001")
    parser.add_argument("--capital-cap-root", default="structural_compounding_lab/output/multi_asset_capital_cap_liquidity_realism_court_001")
    parser.add_argument("--scheduler-root", default="structural_compounding_lab/output/continuous_scheduler_forward_validation_court_001")
    parser.add_argument("--runtime-root", default="structural_compounding_lab/output/forward_validation_runtime")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    parser.add_argument("--no-public-market-fetch", action="store_true")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        SchedulerCapacityConfig(
            project_root=root,
            package_root=package_root(),
            scanner_root=resolve_project_path(args.scanner_root),
            capital_cap_root=resolve_project_path(args.capital_cap_root),
            scheduler_root=resolve_project_path(args.scheduler_root),
            runtime_root=resolve_project_path(args.runtime_root),
            output_root=resolve_project_path(args.output_dir),
            fetch_public_market_data=not args.no_public_market_fetch,
        )
    )
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
