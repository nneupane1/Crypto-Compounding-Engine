from __future__ import annotations

from decimal import Decimal

from structural_compounding_lab.execution.usdt_usdc_execution_guard import (
    BLOCKED,
    PATIENCE_BLOCKED,
    PATIENCE_PASSED,
    PASSED,
    ExecutionSignal,
    GuardThresholds,
    PatienceGuardConfig,
    evaluate_usdt_signal_to_usdc_execution_guard,
    evaluate_usdt_signal_to_usdc_execution_guard_with_patience,
    run_guard_report,
)


NOW_MS = 1_000_000
CLOSED_MS = 940_000


def _kline(close: str = "100", close_ms: int = CLOSED_MS) -> list[object]:
    return [close_ms - 59_999, close, close, close, close, "10", close_ms, "0", 0, "0", "0", "0"]


class FakePublicClient:
    def __init__(
        self,
        *,
        usdt_close: str = "100",
        usdc_close: str = "100.1",
        usdt_close_ms: int = CLOSED_MS,
        usdc_close_ms: int = CLOSED_MS,
        bid: str = "100.0",
        ask: str = "100.1",
        depth_qty: str = "1",
        min_notional: str = "5",
        step_size: str = "0.00001",
        tick_size: str = "0.01",
        min_qty: str = "0.00001",
    ) -> None:
        self.usdt_close = usdt_close
        self.usdc_close = usdc_close
        self.usdt_close_ms = usdt_close_ms
        self.usdc_close_ms = usdc_close_ms
        self.bid = bid
        self.ask = ask
        self.depth_qty = depth_qty
        self.min_notional = min_notional
        self.step_size = step_size
        self.tick_size = tick_size
        self.min_qty = min_qty
        self.calls: list[tuple[str, str, bool]] = []

    def request(self, method: str, path: str, *, params: dict | None = None, signed: bool = False):
        self.calls.append((method, path, signed))
        assert signed is False
        symbol = (params or {}).get("symbol", "")
        if path == "/v3/klines":
            if symbol.endswith("USDT"):
                return [_kline(self.usdt_close, self.usdt_close_ms)]
            if symbol.endswith("USDC"):
                return [_kline(self.usdc_close, self.usdc_close_ms)]
            raise RuntimeError(f"unexpected_symbol:{symbol}")
        if path == "/v3/ticker/bookTicker":
            return {"bidPrice": self.bid, "askPrice": self.ask}
        if path == "/v3/depth":
            return {"asks": [[self.ask, self.depth_qty]], "bids": [[self.bid, self.depth_qty]]}
        if path == "/v3/exchangeInfo":
            return {
                "symbols": [
                    {
                        "symbol": symbol,
                        "status": "TRADING",
                        "baseAsset": symbol.removesuffix("USDC"),
                        "quoteAsset": "USDC",
                        "filters": [
                            {"filterType": "PRICE_FILTER", "minPrice": "0.00000001", "tickSize": self.tick_size},
                            {"filterType": "LOT_SIZE", "minQty": self.min_qty, "stepSize": self.step_size},
                            {"filterType": "MIN_NOTIONAL", "minNotional": self.min_notional},
                        ],
                    }
                ]
            }
        raise RuntimeError(f"unexpected_path:{path}")


class RecoveringSpreadClient(FakePublicClient):
    def __init__(self) -> None:
        super().__init__(bid="99", ask="101", depth_qty="10")
        self.book_calls = 0

    def request(self, method: str, path: str, *, params: dict | None = None, signed: bool = False):
        if path == "/v3/ticker/bookTicker":
            self.book_calls += 1
            if self.book_calls >= 2:
                self.bid = "100.0"
                self.ask = "100.1"
        return super().request(method, path, params=params, signed=signed)


def _signal(side: str = "BUY", symbol: str = "BTCUSDT", notional: str = "10") -> ExecutionSignal:
    return ExecutionSignal(source_symbol=symbol, side=side, order_notional_eur=Decimal(notional), signal_id="test")


def _assert_public_only(client: FakePublicClient) -> None:
    assert all(signed is False for _, _, signed in client.calls)
    assert all(path != "/v3/order" for _, path, _ in client.calls)
    assert all(path != "/v3/account" for _, path, _ in client.calls)
    assert {path for _, path, _ in client.calls}.issubset(
        {"/v3/klines", "/v3/ticker/bookTicker", "/v3/depth", "/v3/exchangeInfo"}
    )


def test_guard_passes_only_public_fresh_liquid_mapped_buy() -> None:
    client = FakePublicClient()
    decision = evaluate_usdt_signal_to_usdc_execution_guard(_signal(), client=client, now_ms=NOW_MS)
    assert decision.accepted is True
    assert decision.classification == PASSED
    assert decision.execution_symbol == "BTCUSDC"
    assert decision.metrics["symbol_execution_policy"]["tier"] == "core_deep"
    assert decision.order_allowed_after_guard is True
    assert decision.order_sent is False
    assert decision.real_money_allowed is False
    _assert_public_only(client)


def test_btc_high_price_and_doge_low_price_use_same_time_freshness_logic() -> None:
    btc_client = FakePublicClient(usdt_close="65000", usdc_close="65001", bid="65000.0", ask="65001.0", depth_qty="0.01")
    doge_client = FakePublicClient(
        usdt_close="0.1000",
        usdc_close="0.10001",
        bid="0.09999",
        ask="0.10000",
        depth_qty="2000",
        step_size="1",
        tick_size="0.00001",
        min_qty="1",
    )

    btc = evaluate_usdt_signal_to_usdc_execution_guard(_signal(symbol="BTCUSDT", notional="10"), client=btc_client, now_ms=NOW_MS)
    doge = evaluate_usdt_signal_to_usdc_execution_guard(_signal(symbol="DOGEUSDT", notional="10"), client=doge_client, now_ms=NOW_MS)

    assert btc.accepted is True
    assert doge.accepted is True
    assert btc.metrics["freshness_policy"] == doge.metrics["freshness_policy"]
    assert btc.metrics["source_candle_age_seconds"] == doge.metrics["source_candle_age_seconds"]
    assert btc.metrics["execution_candle_age_seconds"] == doge.metrics["execution_candle_age_seconds"]
    assert doge.metrics["symbol_execution_policy"]["tier"] == "careful"
    _assert_public_only(btc_client)
    _assert_public_only(doge_client)


def test_guard_rejects_non_buy_for_spot_long_only() -> None:
    decision = evaluate_usdt_signal_to_usdc_execution_guard(_signal(side="SELL"), client=FakePublicClient(), now_ms=NOW_MS)
    assert decision.accepted is False
    assert decision.classification == BLOCKED
    assert "spot_long_only_guard_rejects_non_buy_entry" in decision.reasons
    assert decision.order_sent is False


def test_guard_rejects_unsupported_source_symbol_without_order_or_signed_calls() -> None:
    client = FakePublicClient()
    decision = evaluate_usdt_signal_to_usdc_execution_guard(_signal(symbol="LTCUSDT"), client=client, now_ms=NOW_MS)
    assert decision.accepted is False
    assert "source_symbol_not_in_frozen_usdt_usdc_execution_map" in decision.reasons
    _assert_public_only(client)


def test_guard_rejects_stale_usdc_candle() -> None:
    decision = evaluate_usdt_signal_to_usdc_execution_guard(
        _signal(),
        client=FakePublicClient(usdc_close_ms=700_000),
        now_ms=NOW_MS,
    )
    assert decision.accepted is False
    assert "stale_usdc_execution_candle" in decision.reasons


def test_guard_rejects_stale_usdt_candle() -> None:
    decision = evaluate_usdt_signal_to_usdc_execution_guard(
        _signal(),
        client=FakePublicClient(usdt_close_ms=700_000),
        now_ms=NOW_MS,
    )
    assert decision.accepted is False
    assert "stale_usdt_signal_candle" in decision.reasons


def test_guard_rejects_wide_usdt_usdc_close_deviation() -> None:
    decision = evaluate_usdt_signal_to_usdc_execution_guard(
        _signal(),
        client=FakePublicClient(usdt_close="100", usdc_close="102"),
        now_ms=NOW_MS,
    )
    assert decision.accepted is False
    assert "usdt_usdc_close_deviation_too_wide" in decision.reasons


def test_guard_rejects_wide_spread() -> None:
    decision = evaluate_usdt_signal_to_usdc_execution_guard(
        _signal(),
        client=FakePublicClient(bid="99.0", ask="101.0", depth_qty="10"),
        now_ms=NOW_MS,
    )
    assert decision.accepted is False
    assert "usdc_spread_too_wide" in decision.reasons


def test_guard_rejects_shallow_depth() -> None:
    decision = evaluate_usdt_signal_to_usdc_execution_guard(
        _signal(),
        client=FakePublicClient(depth_qty="0.05"),
        now_ms=NOW_MS,
    )
    assert decision.accepted is False
    assert "usdc_orderbook_depth_insufficient" in decision.reasons


def test_exchange_filters_min_notional_step_size_and_tick_size_are_respected() -> None:
    low_notional = evaluate_usdt_signal_to_usdc_execution_guard(
        _signal(notional="4"),
        client=FakePublicClient(min_notional="5"),
        thresholds=GuardThresholds(max_order_notional_eur=Decimal("10")),
        now_ms=NOW_MS,
    )
    assert low_notional.accepted is False
    assert "order_notional_below_exchange_min_notional" in low_notional.reasons
    assert "rounded_order_notional_below_exchange_min_notional" in low_notional.reasons

    tiny_qty = evaluate_usdt_signal_to_usdc_execution_guard(
        _signal(notional="10"),
        client=FakePublicClient(ask="100.1", bid="100.0", min_qty="1", step_size="1"),
        now_ms=NOW_MS,
    )
    assert tiny_qty.accepted is False
    assert "order_quantity_below_exchange_lot_size" in tiny_qty.reasons

    bad_tick = evaluate_usdt_signal_to_usdc_execution_guard(
        _signal(notional="10"),
        client=FakePublicClient(ask="100.105", bid="100.0", tick_size="0.01"),
        now_ms=NOW_MS,
    )
    assert bad_tick.accepted is False
    assert "execution_book_price_not_tick_size_aligned" in bad_tick.reasons


def test_doge_and_avax_use_careful_depth_policy() -> None:
    doge_client = FakePublicClient(
        usdt_close="0.10",
        usdc_close="0.10001",
        bid="0.09999",
        ask="0.10000",
        depth_qty="1000",
        step_size="1",
        tick_size="0.00001",
        min_qty="1",
    )
    avax_client = FakePublicClient(usdt_close="20", usdc_close="20.01", bid="20.00", ask="20.01", depth_qty="5")

    doge = evaluate_usdt_signal_to_usdc_execution_guard(_signal(symbol="DOGEUSDT"), client=doge_client, now_ms=NOW_MS)
    avax = evaluate_usdt_signal_to_usdc_execution_guard(_signal(symbol="AVAXUSDT"), client=avax_client, now_ms=NOW_MS)

    assert doge.metrics["symbol_execution_policy"]["tier"] == "careful"
    assert doge.metrics["required_orderbook_quote_depth"] == Decimal("120")
    assert doge.accepted is False
    assert "usdc_orderbook_depth_insufficient" in doge.reasons
    assert avax.metrics["symbol_execution_policy"]["tier"] == "careful"
    assert avax.metrics["required_orderbook_quote_depth"] == Decimal("120")
    assert avax.accepted is False
    assert "usdc_orderbook_depth_insufficient" in avax.reasons


def test_guard_report_writes_research_only_payload(tmp_path) -> None:
    payload = run_guard_report(_signal(), output_root=tmp_path, client=FakePublicClient(), now_ms=NOW_MS)
    assert payload["decision"]["classification"] == PASSED
    assert payload["decision"]["metrics"]["symbol_execution_policy"]["tier"] == "core_deep"
    assert payload["real_money_allowed"] is False
    assert payload["order_endpoint_used"] is False
    assert (tmp_path / "usdt_usdc_execution_guard_report.json").exists()


def test_patience_guard_recovers_temporary_spread_block_without_order_calls() -> None:
    client = RecoveringSpreadClient()
    decision = evaluate_usdt_signal_to_usdc_execution_guard_with_patience(
        _signal(),
        client=client,
        now_ms=NOW_MS,
        patience_config=PatienceGuardConfig(patience_seconds=1, recheck_interval_seconds=0, max_attempts=3),
    )

    assert decision.accepted is True
    assert decision.classification == PATIENCE_PASSED
    assert decision.metrics["execution_patience_guard"]["attempts"] == 2
    assert decision.metrics["execution_patience_guard"]["accepted_after_wait"] is True
    assert "usdc_spread_too_wide" in decision.metrics["execution_patience_guard"]["initial_reasons"]
    _assert_public_only(client)


def test_patience_guard_does_not_retry_stale_candles() -> None:
    client = FakePublicClient(usdc_close_ms=700_000)
    decision = evaluate_usdt_signal_to_usdc_execution_guard_with_patience(
        _signal(),
        client=client,
        now_ms=NOW_MS,
        patience_config=PatienceGuardConfig(patience_seconds=1, recheck_interval_seconds=0, max_attempts=3),
    )

    assert decision.accepted is False
    assert decision.classification == PATIENCE_BLOCKED
    assert decision.metrics["execution_patience_guard"]["attempts"] == 1
    assert "stale_usdc_execution_candle" in decision.reasons
    _assert_public_only(client)
