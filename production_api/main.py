from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware


SYMBOLS = (
    "ADAUSDT",
    "LINKUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "AVAXUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "BTCUSDT",
    "SOLUSDT",
)
TIMEFRAME_RULES = {
    "1m": ("1min", 1),
    "5m": ("5min", 5),
    "15m": ("15min", 15),
    "1h": ("1h", 60),
    "4h": ("4h", 240),
    "6h": ("6h", 360),
    "12h": ("12h", 720),
    "1d": ("1d", 1440),
}


def _project_root() -> Path:
    return Path(os.getenv("RTS_PROJECT_ROOT", Path(__file__).resolve().parents[1])).resolve()


def _output_root() -> Path:
    return Path(
        os.getenv(
            "RTS_RUNTIME_OUTPUT_ROOT",
            _project_root() / "structural_compounding_lab" / "output" / "multi_symbol_forward_runtime_earned_parallel_slots",
        )
    ).resolve()


def _demo_root() -> Path:
    return Path(
        os.getenv(
            "RTS_DEMO_OUTPUT_ROOT",
            _project_root() / "structural_compounding_lab" / "output" / "binance_demo_walk_forward_six_month_court_001",
        )
    ).resolve()


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_csv(path: Path, limit: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    return rows[-limit:] if limit and len(rows) > limit else rows


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except Exception:
        return default


def _runtime_copy(symbol: str) -> Path:
    return _output_root() / "symbol_runtime_snapshots" / symbol.upper() / "runtime_1m_copy.csv"


def _normalize_frame(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame = pd.read_csv(path)
    if "timestamp" not in frame.columns:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    frame = frame.dropna(subset=["timestamp"]).sort_values("timestamp")
    for column in ("open", "high", "low", "close", "volume"):
        frame[column] = pd.to_numeric(frame.get(column), errors="coerce")
    return frame.dropna(subset=["open", "high", "low", "close"])


def _resample(frame: pd.DataFrame, timeframe: str) -> pd.DataFrame:
    if frame.empty:
        return frame
    rule, minutes = TIMEFRAME_RULES.get(timeframe, TIMEFRAME_RULES["1m"])
    if timeframe == "1m":
        return frame
    indexed = frame.set_index("timestamp")
    bars = indexed.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    )
    counts = indexed["close"].resample(rule, label="left", closed="left").count()
    bars = bars[counts >= minutes].dropna().reset_index()
    return bars


def _public_visual_extension(symbol: str, frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or os.getenv("RTS_DASHBOARD_PUBLIC_VISUAL_EXTENSION", "true").lower() not in {"1", "true", "yes"}:
        return pd.DataFrame(columns=frame.columns)
    latest = pd.Timestamp(frame["timestamp"].max()).tz_convert("UTC")
    safe_now = pd.Timestamp(datetime.now(timezone.utc).replace(second=0, microsecond=0)) - pd.Timedelta(minutes=1)
    start = latest + pd.Timedelta(minutes=1)
    if start > safe_now:
        return pd.DataFrame(columns=frame.columns)
    try:
        response = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={
                "symbol": symbol.upper(),
                "interval": "1m",
                "startTime": int(start.timestamp() * 1000),
                "endTime": int(safe_now.timestamp() * 1000) + 59999,
                "limit": 1000,
            },
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return pd.DataFrame(columns=frame.columns)
    rows = []
    for item in payload if isinstance(payload, list) else []:
        rows.append(
            {
                "timestamp": pd.to_datetime(int(item[0]), unit="ms", utc=True),
                "open": float(item[1]),
                "high": float(item[2]),
                "low": float(item[3]),
                "close": float(item[4]),
                "volume": float(item[5]),
            }
        )
    return pd.DataFrame(rows)


def _candle_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in frame.itertuples(index=False):
        timestamp = pd.Timestamp(row.timestamp)
        rows.append(
            {
                "time": int(timestamp.timestamp()),
                "timestamp": timestamp.isoformat(),
                "open": float(row.open),
                "high": float(row.high),
                "low": float(row.low),
                "close": float(row.close),
                "volume": float(getattr(row, "volume", 0.0)),
            }
        )
    return rows


def _markers(symbol: str, timeframe: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    selected = _read_csv(_output_root() / "ledger" / "forward_strategy_selected_trades.csv")
    marker_rows: list[dict[str, Any]] = []
    trade_events: list[dict[str, Any]] = []
    for trade in selected:
        if str(trade.get("symbol", "")).upper() != symbol.upper():
            continue
        side = str(trade.get("side", "long")).lower()
        entry_time = pd.to_datetime(trade.get("entry_time"), utc=True, errors="coerce")
        exit_time = pd.to_datetime(trade.get("exit_time"), utc=True, errors="coerce")
        trade_event = {
            "kind": "trade",
            "trade_id": trade.get("trade_id"),
            "symbol": symbol.upper(),
            "side": side,
            "strategy_type": "frozen_multi_symbol_long_only",
            "entry_time": "" if pd.isna(entry_time) else entry_time.isoformat(),
            "entry_time_unix": None if pd.isna(entry_time) else int(entry_time.timestamp()),
            "exit_time": "" if pd.isna(exit_time) else exit_time.isoformat(),
            "exit_time_unix": None if pd.isna(exit_time) else int(exit_time.timestamp()),
            "pnl": _safe_float(trade.get("pnl_eur")),
            "pnl_r": _safe_float(trade.get("net_r")),
            "explanation": "Frozen long-only multi-symbol forward research selection.",
        }
        trade_events.append(trade_event)
        if not pd.isna(entry_time):
            marker_rows.append(
                {
                    "time": int(entry_time.timestamp()),
                    "position": "belowBar",
                    "color": "#22c55e",
                    "shape": "arrowUp",
                    "text": f"{symbol} long entry",
                }
            )
        if not pd.isna(exit_time):
            marker_rows.append(
                {
                    "time": int(exit_time.timestamp()),
                    "position": "aboveBar",
                    "color": "#38bdf8",
                    "shape": "circle",
                    "text": f"exit {float(_safe_float(trade.get('pnl_eur'))):+.2f} EUR",
                }
            )
    return marker_rows, trade_events


app = FastAPI(title="RTS Production Telemetry API", version="1.0.0", docs_url="/docs", redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("RTS_DASHBOARD_CORS_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "created_at_utc": _iso_now(), "runtime_output_root": str(_output_root())}


@app.get("/api/structural-lab/snapshot")
def structural_lab_snapshot() -> dict[str, Any]:
    output = _output_root()
    runtime = _read_json(output / "latest_status.json", {})
    strategy = _read_json(output / "diagnostics" / "strategy_evaluator_summary.json", {})
    demo = _read_json(_demo_root() / "latest_status.json", {})
    decisions = _read_csv(output / "ledger" / "multi_symbol_forward_decision_ledger.csv", limit=500)
    selected = _read_csv(output / "ledger" / "forward_strategy_selected_trades.csv", limit=500)
    rejected_shorts = _read_csv(output / "ledger" / "forward_strategy_spot_long_only_rejected_shorts.csv", limit=200)
    portfolio = strategy.get("portfolio_summary") or {}
    latest_symbol_times = {
        row.get("symbol"): (row.get("quality") or {}).get("last_timestamp")
        for row in runtime.get("symbol_results", [])
        if row.get("symbol")
    }
    return {
        "lab": {
            "name": "Retail Trading System Production Runtime",
            "root_path": str(_project_root()),
            "output_path": str(output),
            "has_run": bool(runtime),
        },
        "summary": {
            "status_color": runtime.get("status_color", "UNKNOWN"),
            "created_at_utc": runtime.get("created_at_utc"),
            "latest_safe_1m_timestamp": runtime.get("latest_safe_1m_timestamp"),
            "symbols_checked": runtime.get("symbols_checked", 0),
            "symbols_clean": runtime.get("symbols_clean", 0),
            "total_appended_rows": runtime.get("total_appended_rows", 0),
        },
        "summary_metrics": {
            "current_equity": portfolio.get("ending_total_equity_after_tax", 0),
            "net_gain_after_tax": portfolio.get("net_gain_after_tax", 0),
            "selected_trades": portfolio.get("selected_trades", 0),
            "profit_factor": portfolio.get("profit_factor", 0),
            "win_rate": portfolio.get("win_rate", 0),
            "max_drawdown": portfolio.get("max_drawdown_total_after_tax", 0),
        },
        "available_symbols": list(SYMBOLS),
        "available_timeframes": list(TIMEFRAME_RULES),
        "multi_symbol_forward": {
            "mode": "production_shadow_forward_long_only",
            "runtime_status": runtime,
            "decisions": {
                "ledger_path": str(output / "ledger" / "multi_symbol_forward_decision_ledger.csv"),
                "recent_rows": decisions,
                "selected_trade_rows": selected,
                "rejected_short_rows": rejected_shorts,
            },
            "pnl_reference": portfolio,
            "safety": {
                "paper_validation_ready": False,
                "live_allowed": False,
                "real_money_allowed": False,
                "order_path_created": False,
                "short_selling_allowed": False,
                "spot_compatible_long_only": True,
            },
            "operator_tape": {
                "latest_symbol_timestamps": latest_symbol_times,
            },
        },
        "execution_readiness": {
            "mode": "binance_spot_testnet_or_disabled",
            "paper_ready": False,
            "live_ready": False,
            "paper_validation_ready": False,
            "live_allowed": False,
            "real_money_allowed": False,
            "demo_status": demo,
        },
        "trade_rows": selected,
        "setup_rows": [],
        "level_rows": [],
        "liquidity_rows": [],
        "cooldown_rows": [],
        "pyramiding_rows": [],
        "equity_rows": [],
        "overview": {
            "base_capital": 25000,
            "active_trading_capital": portfolio.get("ending_active_capital_after_tax", 0),
            "locked_profit": portfolio.get("ending_profit_vault_after_tax", 0),
            "floating_profit": 0,
            "current_equity": portfolio.get("ending_total_equity_after_tax", 0),
            "current_compounding_cycle": "production-forward-observation",
            "cooldown_state": "n/a",
            "total_return_pct": (float(portfolio.get("return_multiple_after_tax", 1) or 1) - 1) * 100,
            "max_drawdown_pct": float(portfolio.get("max_drawdown_total_after_tax", 0) or 0) * 100,
            "win_rate": float(portfolio.get("win_rate", 0) or 0) * 100,
            "profit_factor": portfolio.get("profit_factor", 0),
            "r_multiple_summary": str(portfolio.get("sum_net_r", "")),
        },
        "chart_points": {"equity": [], "locked_profit": []},
        "settings": {},
        "symbols_config": {},
        "profit_vault": {},
        "report_markdown": "",
        "artifact_freshness": {},
    }


@app.get("/api/structural-lab/candles")
def structural_lab_candles(
    symbol: str,
    timeframe: str = Query("1m"),
    limit: int = Query(500, ge=50, le=5000),
    until_time: str | None = Query(None),
) -> dict[str, Any]:
    symbol = symbol.upper()
    timeframe = timeframe.lower()
    base = _normalize_frame(_runtime_copy(symbol))
    public_extension = _public_visual_extension(symbol, base)
    if not public_extension.empty:
        base = pd.concat([base, public_extension], ignore_index=True).drop_duplicates("timestamp").sort_values("timestamp")
    bars = _resample(base, timeframe)
    if until_time:
        until = pd.to_datetime(until_time, utc=True, errors="coerce")
        if not pd.isna(until):
            bars = bars[bars["timestamp"] <= until]
    bars = bars.tail(limit)
    markers, trade_events = _markers(symbol, timeframe)
    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "source_path": str(_runtime_copy(symbol)),
        "source_role": "active_runtime_copy_plus_optional_public_visual_extension",
        "closed_candle_policy": "closed public Binance 1m candles; public visual extension is display-only",
        "candles": _candle_rows(bars),
        "markers": markers,
        "trade_events": trade_events,
        "decision_events": [],
        "indicators": {"ema_20": [], "ema_50": [], "vwap_display": []},
        "structure_levels": [],
        "liquidity_levels": [],
        "visual_live_extension": {
            "enabled": os.getenv("RTS_DASHBOARD_PUBLIC_VISUAL_EXTENSION", "true").lower() in {"1", "true", "yes"},
            "rows": int(len(public_extension)),
        },
        "window_start_timestamp": None if bars.empty else pd.Timestamp(bars["timestamp"].min()).isoformat(),
        "window_end_timestamp": None if bars.empty else pd.Timestamp(bars["timestamp"].max()).isoformat(),
        "debug": {
            "runtime_output_root": str(_output_root()),
            "row_count": int(len(bars)),
        },
    }
