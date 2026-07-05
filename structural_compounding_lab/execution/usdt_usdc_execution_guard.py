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
PATIENCE_PASSED = "USDT_TO_USDC_EXECUTION_PATIENCE_GUARD_PASSED_NO_ORDER_SENT"
PATIENCE_BLOCKED = "USDT_TO_USDC_EXECUTION_PATIENCE_GUARD_BLOCKED_NO_ORDER_SENT"

EXECUTION_QUALITY_RECHECK_REASONS = {
    "usdt_usdc_close_deviation_too_wide",
    "usdc_spread_too_wide",
    "usdc_orderbook_depth_insufficient",
}

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
class PatienceGuardConfig:
    patience_seconds: int = 300
    recheck_interval_seconds: int = 15
    max_attempts: int = 21


@dataclass(frozen=True)
class SymbolExecutionPolicy:
    tier: str
    max_signal_execution_close_deviation_bps: Decimal
    max_usdc_spread_bps: Decimal
    min_orderbook_quote_depth_multiplier: Decimal


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


def _default_symbol_policies() -> dict[str, SymbolExecutionPolicy]:
    core = SymbolExecutionPolicy(
        tier="core_deep",
        max_signal_execution_close_deviation_bps=Decimal("25"),
        max_usdc_spread_bps=Decimal("12"),
        min_orderbook_quote_depth_multiplier=Decimal("8"),
    )
    normal = SymbolExecutionPolicy(
        tier="normal",
        max_signal_execution_close_deviation_bps=Decimal("35"),
        max_usdc_spread_bps=Decimal("20"),
        min_orderbook_quote_depth_multiplier=Decimal("6"),
    )
    careful = SymbolExecutionPolicy(
        tier="careful",
        max_signal_execution_close_deviation_bps=Decimal("40"),
        max_usdc_spread_bps=Decimal("25"),
        min_orderbook_quote_depth_multiplier=Decimal("12"),
    )
    return {
        "BTCUSDC": core,
        "ETHUSDC": core,
        "BNBUSDC": core,
        "SOLUSDC": core,
        "ADAUSDC": normal,
        "XRPUSDC": normal,
        "LINKUSDC": normal,
        "AVAXUSDC": careful,
        "DOGEUSDC": careful,
    }


def _symbol_policy(execution_symbol: str, policies: dict[str, SymbolExecutionPolicy] | None = None) -> SymbolExecutionPolicy | None:
    return (policies or _default_symbol_policies()).get(execution_symbol.upper())


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


def _exchange_info_symbol(client: PublicMarketClient, symbol: str) -> dict[str, Any]:
    row = client.request("GET", "/v3/exchangeInfo", params={"symbol": symbol.upper()}, signed=False)
    symbols = row.get("symbols") or []
    if not symbols:
        raise RuntimeError(f"missing_exchange_info:{symbol}")
    info = symbols[0]
    if str(info.get("symbol", "")).upper() != symbol.upper():
        raise RuntimeError(f"exchange_info_symbol_mismatch:{symbol}")
    return info


def _filter_map(exchange_info_symbol: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(row.get("filterType", "")): row for row in exchange_info_symbol.get("filters", [])}


def _floor_to_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value // step) * step


def _is_multiple(value: Decimal, increment: Decimal) -> bool:
    if increment <= 0:
        return True
    return value == _floor_to_step(value, increment)


def _exchange_filter_checks(
    *,
    exchange_info_symbol: dict[str, Any],
    book_price: Decimal,
    order_notional_quote: Decimal,
) -> tuple[list[str], dict[str, Any]]:
    filters = _filter_map(exchange_info_symbol)
    lot_size = filters.get("LOT_SIZE", {})
    price_filter = filters.get("PRICE_FILTER", {})
    min_notional_filter = filters.get("MIN_NOTIONAL") or filters.get("NOTIONAL") or {}
    step_size = _decimal(lot_size.get("stepSize"), "0")
    min_qty = _decimal(lot_size.get("minQty"), "0")
    tick_size = _decimal(price_filter.get("tickSize"), "0")
    min_price = _decimal(price_filter.get("minPrice"), "0")
    min_notional = _decimal(min_notional_filter.get("minNotional"), "0")

    raw_qty = (order_notional_quote / book_price) if book_price > 0 else Decimal("0")
    rounded_qty = _floor_to_step(raw_qty, step_size)
    rounded_notional = rounded_qty * book_price

    reasons: list[str] = []
    if min_notional > 0 and order_notional_quote < min_notional:
        reasons.append("order_notional_below_exchange_min_notional")
    if rounded_qty <= 0 or (min_qty > 0 and rounded_qty < min_qty):
        reasons.append("order_quantity_below_exchange_lot_size")
    if step_size > 0 and not _is_multiple(rounded_qty, step_size):
        reasons.append("computed_quantity_not_step_size_aligned")
    if tick_size > 0 and not _is_multiple(book_price, tick_size):
        reasons.append("execution_book_price_not_tick_size_aligned")
    if min_price > 0 and book_price < min_price:
        reasons.append("execution_book_price_below_min_price")
    if min_notional > 0 and rounded_notional < min_notional:
        reasons.append("rounded_order_notional_below_exchange_min_notional")

    return reasons, {
        "exchange_status": exchange_info_symbol.get("status", ""),
        "base_asset": exchange_info_symbol.get("baseAsset", ""),
        "quote_asset": exchange_info_symbol.get("quoteAsset", ""),
        "min_notional": min_notional,
        "step_size": step_size,
        "min_qty": min_qty,
        "tick_size": tick_size,
        "min_price": min_price,
        "raw_quantity_for_notional": raw_qty,
        "step_aligned_quantity": rounded_qty,
        "step_aligned_quote_notional": rounded_notional,
        "book_price_checked_for_tick_size": book_price,
    }


def evaluate_usdt_signal_to_usdc_execution_guard(
    signal: ExecutionSignal,
    *,
    client: PublicMarketClient | None = None,
    thresholds: GuardThresholds | None = None,
    symbol_policies: dict[str, SymbolExecutionPolicy] | None = None,
    now_ms: int | None = None,
) -> GuardDecision:
    client = client or BinancePublicClient()
    thresholds = thresholds or GuardThresholds()
    reasons: list[str] = []
    metrics: dict[str, Any] = {"created_at_utc": _now(), "thresholds": asdict(thresholds)}

    source_symbol = signal.source_symbol.upper()
    execution_symbol = _execution_symbol(source_symbol)
    side = signal.side.upper()
    policy = _symbol_policy(execution_symbol, symbol_policies) if execution_symbol else None
    metrics.update(
        {
            "approved_source_symbols": sorted(USDT_TO_USDC),
            "approved_execution_symbols": sorted(_default_symbol_policies()),
            "source_symbol": source_symbol,
            "execution_symbol": execution_symbol,
            "order_notional_eur": signal.order_notional_eur,
            "freshness_policy": {
                "same_for_all_symbols": True,
                "max_candle_staleness_seconds": thresholds.max_candle_staleness_seconds,
                "price_level_dependent": False,
            },
            "symbol_execution_policy": asdict(policy) if policy else None,
        }
    )

    if not execution_symbol:
        reasons.append("source_symbol_not_in_frozen_usdt_usdc_execution_map")
    if execution_symbol and policy is None:
        reasons.append("execution_symbol_missing_symbol_aware_policy")
    if side != "BUY":
        reasons.append("spot_long_only_guard_rejects_non_buy_entry")
    if signal.order_notional_eur <= 0:
        reasons.append("non_positive_order_notional")
    if signal.order_notional_eur > thresholds.max_order_notional_eur:
        reasons.append("order_notional_exceeds_tiny_smoke_cap")

    try:
        if not execution_symbol or policy is None:
            raise RuntimeError("symbol_policy_unavailable")
        source_candle = _latest_closed_1m(client, source_symbol, now_ms=now_ms)
        execution_candle = _latest_closed_1m(client, execution_symbol, now_ms=now_ms)
        book = _book_ticker(client, execution_symbol)
        depth_quote = _depth_quote(client, execution_symbol, limit=thresholds.depth_limit, side=side)
        exchange_info_symbol = _exchange_info_symbol(client, execution_symbol)
        filter_reasons, filter_metrics = _exchange_filter_checks(
            exchange_info_symbol=exchange_info_symbol,
            book_price=book["ask"] if side == "BUY" else book["bid"],
            order_notional_quote=signal.order_notional_eur,
        )
        reasons.extend(filter_reasons)
        now_ms_effective = now_ms or int(time.time() * 1000)
        source_age = max(0, (now_ms_effective - int(source_candle["close_time_ms"])) / 1000)
        execution_age = max(0, (now_ms_effective - int(execution_candle["close_time_ms"])) / 1000)
        close_dev_bps = abs((execution_candle["close"] - source_candle["close"]) / source_candle["close"]) * Decimal("10000")
        required_depth = signal.order_notional_eur * policy.min_orderbook_quote_depth_multiplier
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
                "exchange_filters": filter_metrics,
            }
        )
        if source_age > thresholds.max_candle_staleness_seconds:
            reasons.append("stale_usdt_signal_candle")
        if execution_age > thresholds.max_candle_staleness_seconds:
            reasons.append("stale_usdc_execution_candle")
        if close_dev_bps > policy.max_signal_execution_close_deviation_bps:
            reasons.append("usdt_usdc_close_deviation_too_wide")
        if book["spread_bps"] > policy.max_usdc_spread_bps:
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


def _is_retryable_execution_quality_block(decision: GuardDecision) -> bool:
    if decision.accepted:
        return False
    reasons = set(decision.reasons)
    return bool(reasons) and reasons.issubset(EXECUTION_QUALITY_RECHECK_REASONS)


def _patience_metrics(
    *,
    config: PatienceGuardConfig,
    attempts: list[GuardDecision],
    accepted_after_wait: bool,
    delay_seconds: int,
) -> dict[str, Any]:
    return {
        "enabled": True,
        "patience_seconds": config.patience_seconds,
        "recheck_interval_seconds": config.recheck_interval_seconds,
        "max_attempts": config.max_attempts,
        "attempts": len(attempts),
        "accepted_after_wait": accepted_after_wait,
        "delay_seconds": delay_seconds,
        "initial_reasons": attempts[0].reasons if attempts else [],
        "final_reasons": attempts[-1].reasons if attempts else [],
        "attempt_reasons": [decision.reasons for decision in attempts],
        "retryable_reasons": sorted(EXECUTION_QUALITY_RECHECK_REASONS),
        "decision_rule": "prefer_first_safe_usdc_execution_window_within_5m",
        "no_order_sent_by_guard": True,
    }


def _with_patience_decision(
    decision: GuardDecision,
    *,
    classification: str,
    patience: dict[str, Any],
) -> GuardDecision:
    metrics = dict(decision.metrics)
    metrics["execution_patience_guard"] = patience
    return GuardDecision(
        accepted=decision.accepted,
        classification=classification,
        source_symbol=decision.source_symbol,
        execution_symbol=decision.execution_symbol,
        side=decision.side,
        reasons=decision.reasons,
        metrics=metrics,
        order_allowed_after_guard=decision.accepted,
        order_sent=False,
        real_money_allowed=False,
    )


def evaluate_usdt_signal_to_usdc_execution_guard_with_patience(
    signal: ExecutionSignal,
    *,
    client: PublicMarketClient | None = None,
    thresholds: GuardThresholds | None = None,
    symbol_policies: dict[str, SymbolExecutionPolicy] | None = None,
    patience_config: PatienceGuardConfig | None = None,
    now_ms: int | None = None,
) -> GuardDecision:
    """Public-market USDT->USDC guard with bounded execution-quality rechecks.

    The strategy signal remains frozen and immediate. This function only waits
    for temporary USDC execution conditions to become safe: spread, USDT/USDC
    close deviation, or orderbook depth. Stale candles, unsupported symbols,
    exchange filters, side violations, and cap violations are never retried.
    """

    client = client or BinancePublicClient()
    thresholds = thresholds or GuardThresholds()
    config = patience_config or PatienceGuardConfig()
    attempts: list[GuardDecision] = []
    started = time.monotonic()
    elapsed = 0

    while True:
        decision = evaluate_usdt_signal_to_usdc_execution_guard(
            signal,
            client=client,
            thresholds=thresholds,
            symbol_policies=symbol_policies,
            now_ms=now_ms,
        )
        attempts.append(decision)

        if decision.accepted:
            return _with_patience_decision(
                decision,
                classification=PATIENCE_PASSED,
                patience=_patience_metrics(
                    config=config,
                    attempts=attempts,
                    accepted_after_wait=len(attempts) > 1,
                    delay_seconds=elapsed,
                ),
            )

        if not _is_retryable_execution_quality_block(decision):
            return _with_patience_decision(
                decision,
                classification=PATIENCE_BLOCKED,
                patience=_patience_metrics(
                    config=config,
                    attempts=attempts,
                    accepted_after_wait=False,
                    delay_seconds=elapsed,
                ),
            )

        if elapsed >= config.patience_seconds or len(attempts) >= config.max_attempts:
            return _with_patience_decision(
                decision,
                classification=PATIENCE_BLOCKED,
                patience=_patience_metrics(
                    config=config,
                    attempts=attempts,
                    accepted_after_wait=False,
                    delay_seconds=elapsed,
                ),
            )

        sleep_seconds = min(config.recheck_interval_seconds, config.patience_seconds - elapsed)
        if sleep_seconds > 0:
            time.sleep(sleep_seconds)
        elapsed = int(round(time.monotonic() - started))


def run_guard_report(
    signal: ExecutionSignal,
    *,
    output_root: Path | None = None,
    client: PublicMarketClient | None = None,
    thresholds: GuardThresholds | None = None,
    patience_config: PatienceGuardConfig | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    output_root = output_root or package_root() / "output" / OUTPUT_FOLDER_NAME
    if patience_config is None:
        decision = evaluate_usdt_signal_to_usdc_execution_guard(signal, client=client, thresholds=thresholds, now_ms=now_ms)
    else:
        decision = evaluate_usdt_signal_to_usdc_execution_guard_with_patience(
            signal,
            client=client,
            thresholds=thresholds,
            patience_config=patience_config,
            now_ms=now_ms,
        )
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
    parser.add_argument("--patience", action="store_true")
    parser.add_argument("--patience-seconds", type=int, default=300)
    parser.add_argument("--recheck-interval-seconds", type=int, default=15)
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
        patience_config=PatienceGuardConfig(args.patience_seconds, args.recheck_interval_seconds) if args.patience else None,
    )
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
