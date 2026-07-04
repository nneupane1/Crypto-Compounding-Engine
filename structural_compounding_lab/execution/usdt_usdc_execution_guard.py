from __future__ import annotations

import argparse
import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path


OUTPUT_FOLDER_NAME = "usdt_usdc_execution_guard"
COURT_NAME = "USDT_SIGNAL_TO_USDC_EXECUTION_GUARD_RESEARCH_ONLY"

PASSED = "USDT_TO_USDC_EXECUTION_GUARD_PASSED_NO_ORDER_SENT"
BLOCKED = "USDT_TO_USDC_EXECUTION_GUARD_BLOCKED_NO_ORDER_SENT"

USDT_TO_USDC = {
    "ADAUSDT": "ADAUSDC",
    "AVAXUSDT": "AVAXUSDC",
    "BNBUSDT": "BNBUSDC",
    "BTCUSDT": "BTCUSDC",
    "DOGEUSDT": "DOGEUSDC",
    "ETHUSDT": "ETHUSDC",
    "LINKUSDT": "LINKUSDC",
    "SOLUSDT": "SOLUSDC",
    "XRPUSDT": "XRPUSDC",
}

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "paper_validation_ready": False,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "order_path_created": False,
    "broker_path_created": False,
    "account_endpoint_used": False,
    "order_endpoint_used": False,
    "signed_endpoint_used": False,
    "private_endpoint_used": False,
    "strategy_logic_changed": False,
    "entries_changed": False,
    "exits_changed": False,
    "thresholds_tuned": False,
}


class PublicMarketClient(Protocol):
    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, signed: bool = False) -> Any:
        ...


@dataclass(frozen=True)
class GuardThresholds:
    max_candle_staleness_seconds: int = 180
    max_signal_execution_close_deviation_bps: Decimal = Decimal("35")
    max_usdc_spread_bps: Decimal = Decimal("20")
    min_orderbook_quote_depth_multiplier: Decimal = Decimal("5")
    depth_limit: int = 20
    max_order_notional_eur: Decimal = Decimal("10")


@dataclass(frozen=True)
class ExecutionSignal:
    source_symbol: str
    side: str
    order_notional_eur: Decimal
    source_signal_time: str = ""
    signal_id: str = ""


@dataclass(frozen=True)
class GuardDecision:
    accepted: bool
    classification: str
    source_symbol: str
    execution_symbol: str
    side: str
    reasons: list[str]
    metrics: dict[str, Any]
    order_allowed_after_guard: bool = False
    order_sent: bool = False
    real_money_allowed: bool = False


class BinancePublicClient:
    def __init__(self, base_url: str = "https://api.binance.com/api", timeout_seconds: int = 15) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None, signed: bool = False) -> Any:
        if signed:
            raise RuntimeError("USDT/USDC execution guard refuses signed/private requests")
        if not path.startswith("/"):
            path = "/" + path
        query = urllib.parse.urlencode(params or {})
        url = f"{self.base_url}{path}" + (f"?{query}" if query else "")
        req = urllib.request.Request(url, method=method.upper())
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, float):
        return None if math.isnan(value) or math.isinf(value) else round(value, 10)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    if hasattr(value, "__dataclass_fields__"):
        return _jsonable(asdict(value))
    return value


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _execution_symbol(source_symbol: str) -> str:
    source = source_symbol.upper()
    return USDT_TO_USDC.get(source, "")


def _latest_closed_1m(client: PublicMarketClient, symbol: str, *, now_ms: int | None = None) -> dict[str, Any]:
    now_ms = now_ms or int(time.time() * 1000)
    rows = client.request("GET", "/v3/klines", params={"symbol": symbol.upper(), "interval": "1m", "limit": 4}, signed=False)
    closed = [row for row in rows if int(row[6]) <= now_ms]
    if not closed:
        raise RuntimeError(f"no_closed_1m_candle:{symbol}")
    row = closed[-1]
    return {
        "symbol": symbol.upper(),
        "open_time_ms": int(row[0]),
        "close_time_ms": int(row[6]),
        "close": _decimal(row[4]),
        "volume": _decimal(row[5]),
    }


def _book_ticker(client: PublicMarketClient, symbol: str) -> dict[str, Decimal]:
    row = client.request("GET", "/v3/ticker/bookTicker", params={"symbol": symbol.upper()}, signed=False)
    bid = _decimal(row.get("bidPrice"))
    ask = _decimal(row.get("askPrice"))
    if bid <= 0 or ask <= 0 or ask < bid:
        raise RuntimeError(f"bad_book_ticker:{symbol}")
    mid = (bid + ask) / Decimal("2")
    return {
        "bid": bid,
        "ask": ask,
        "mid": mid,
        "spread_bps": ((ask - bid) / mid) * Decimal("10000"),
    }


def _depth_quote(client: PublicMarketClient, symbol: str, *, limit: int, side: str) -> Decimal:
    row = client.request("GET", "/v3/depth", params={"symbol": symbol.upper(), "limit": limit}, signed=False)
    levels = row.get("asks") if side.upper() == "BUY" else row.get("bids")
    total = Decimal("0")
    for price, qty, *_ in levels or []:
        total += _decimal(price) * _decimal(qty)
    return total


def evaluate_usdt_signal_to_usdc_execution_guard(
    signal: ExecutionSignal,
    *,
    client: PublicMarketClient | None = None,
    thresholds: GuardThresholds | None = None,
    now_ms: int | None = None,
) -> GuardDecision:
    client = client or BinancePublicClient()
    thresholds = thresholds or GuardThresholds()
    reasons: list[str] = []
    metrics: dict[str, Any] = {"created_at_utc": _now(), "thresholds": asdict(thresholds)}

    source_symbol = signal.source_symbol.upper()
    execution_symbol = _execution_symbol(source_symbol)
    side = signal.side.upper()
    metrics.update(
        {
            "approved_source_symbols": sorted(USDT_TO_USDC),
            "source_symbol": source_symbol,
            "execution_symbol": execution_symbol,
            "order_notional_eur": signal.order_notional_eur,
        }
    )

    if not execution_symbol:
        reasons.append("source_symbol_not_in_frozen_usdt_usdc_execution_map")
    if side != "BUY":
        reasons.append("spot_long_only_guard_rejects_non_buy_entry")
    if signal.order_notional_eur <= 0:
        reasons.append("non_positive_order_notional")
    if signal.order_notional_eur > thresholds.max_order_notional_eur:
        reasons.append("order_notional_exceeds_tiny_smoke_cap")

    try:
        source_candle = _latest_closed_1m(client, source_symbol, now_ms=now_ms)
        execution_candle = _latest_closed_1m(client, execution_symbol, now_ms=now_ms)
        book = _book_ticker(client, execution_symbol)
        depth_quote = _depth_quote(client, execution_symbol, limit=thresholds.depth_limit, side=side)
        now_ms_effective = now_ms or int(time.time() * 1000)
        source_age = max(0, (now_ms_effective - int(source_candle["close_time_ms"])) / 1000)
        execution_age = max(0, (now_ms_effective - int(execution_candle["close_time_ms"])) / 1000)
        close_dev_bps = abs((execution_candle["close"] - source_candle["close"]) / source_candle["close"]) * Decimal("10000")
        required_depth = signal.order_notional_eur * thresholds.min_orderbook_quote_depth_multiplier
        metrics.update(
            {
                "source_candle": source_candle,
                "execution_candle": execution_candle,
                "source_candle_age_seconds": source_age,
                "execution_candle_age_seconds": execution_age,
                "close_deviation_bps": close_dev_bps,
                "execution_book": book,
                "execution_orderbook_quote_depth": depth_quote,
                "required_orderbook_quote_depth": required_depth,
            }
        )
        if source_age > thresholds.max_candle_staleness_seconds:
            reasons.append("stale_usdt_signal_candle")
        if execution_age > thresholds.max_candle_staleness_seconds:
            reasons.append("stale_usdc_execution_candle")
        if close_dev_bps > thresholds.max_signal_execution_close_deviation_bps:
            reasons.append("usdt_usdc_close_deviation_too_wide")
        if book["spread_bps"] > thresholds.max_usdc_spread_bps:
            reasons.append("usdc_spread_too_wide")
        if depth_quote < required_depth:
            reasons.append("usdc_orderbook_depth_insufficient")
    except Exception as exc:  # noqa: BLE001
        reasons.append(f"market_guard_fetch_failed:{exc}")

    accepted = not reasons
    return GuardDecision(
        accepted=accepted,
        classification=PASSED if accepted else BLOCKED,
        source_symbol=source_symbol,
        execution_symbol=execution_symbol,
        side=side,
        reasons=reasons,
        metrics=metrics,
        order_allowed_after_guard=accepted,
        order_sent=False,
        real_money_allowed=False,
    )


def run_guard_report(
    signal: ExecutionSignal,
    *,
    output_root: Path | None = None,
    client: PublicMarketClient | None = None,
    thresholds: GuardThresholds | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    output_root = output_root or package_root() / "output" / OUTPUT_FOLDER_NAME
    decision = evaluate_usdt_signal_to_usdc_execution_guard(signal, client=client, thresholds=thresholds, now_ms=now_ms)
    payload = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "decision": decision,
        "safety": SAFETY_FLAGS,
        **SAFETY_FLAGS,
    }
    _write_json(output_root / "usdt_usdc_execution_guard_report.json", payload)
    return _jsonable(payload)


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--source-symbol", default="BTCUSDT")
    parser.add_argument("--side", default="BUY")
    parser.add_argument("--order-notional-eur", default="10")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    payload = run_guard_report(
        ExecutionSignal(
            source_symbol=args.source_symbol,
            side=args.side,
            order_notional_eur=Decimal(str(args.order_notional_eur)),
            signal_id=f"manual_guard_check:{args.source_symbol}:{args.side}",
        ),
        output_root=resolve_project_path(args.output_dir),
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
