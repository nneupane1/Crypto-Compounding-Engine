from __future__ import annotations

from decimal import Decimal

from structural_compounding_lab.execution.usdt_usdc_execution_guard import (
    BLOCKED,
    PASSED,
    ExecutionSignal,
    GuardThresholds,
    evaluate_usdt_signal_to_usdc_execution_guard,
    run_guard_report,
)


NOW_MS = 1_000_000
CLOSED_MS = 940_000


def _kline(symbol: str, close: str = "100", close_ms: int = CLOSED_MS) -> list[object]:
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
    ) -> None:
        self.usdt_close = usdt_close
        self.usdc_close = usdc_close
        self.usdt_close_ms = usdt_close_ms
        self.usdc_close_ms = usdc_close_ms
        self.bid = bid
        self.ask = ask
        self.depth_qty = depth_qty
        self.calls: list[tuple[str, str, bool]] = []

    def request(self, method: str, path: str, *, params: dict | None = None, signed: bool = False):
        self.calls.append((method, path, signed))
        assert signed is False
        symbol = (params or {}).get("symbol", "")
        if path == "/v3/klines":
            if symbol.endswith("USDT"):
                return [_kline(symbol, self.usdt_close, self.usdt_close_ms)]
            if symbol.endswith("USDC"):
                return [_kline(symbol, self.usdc_close, self.usdc_close_ms)]
            raise RuntimeError(f"unexpected_symbol:{symbol}")
        if path == "/v3/ticker/bookTicker":
            return {"bidPrice": self.bid, "askPrice": self.ask}
        if path == "/v3/depth":
            return {"asks": [[self.ask, self.depth_qty]], "bids": [[self.bid, self.depth_qty]]}
        raise RuntimeError(f"unexpected_path:{path}")


def _signal(side: str = "BUY", symbol: str = "BTCUSDT", notional: str = "10") -> ExecutionSignal:
    return ExecutionSignal(source_symbol=symbol, side=side, order_notional_eur=Decimal(notional), signal_id="test")


def test_guard_passes_only_public_fresh_liquid_mapped_buy() -> None:
    client = FakePublicClient()
    decision = evaluate_usdt_signal_to_usdc_execution_guard(_signal(), client=client, now_ms=NOW_MS)
    assert decision.accepted is True
    assert decision.classification == PASSED
    assert decision.execution_symbol == "BTCUSDC"
    assert decision.order_allowed_after_guard is True
    assert decision.order_sent is False
    assert decision.real_money_allowed is False
    assert {path for _, path, _ in client.calls} == {"/v3/klines", "/v3/ticker/bookTicker", "/v3/depth"}


def test_guard_rejects_non_buy_for_spot_long_only() -> None:
    decision = evaluate_usdt_signal_to_usdc_execution_guard(_signal(side="SELL"), client=FakePublicClient(), now_ms=NOW_MS)
    assert decision.accepted is False
    assert decision.classification == BLOCKED
    assert "spot_long_only_guard_rejects_non_buy_entry" in decision.reasons
    assert decision.order_sent is False


def test_guard_rejects_unsupported_source_symbol() -> None:
    decision = evaluate_usdt_signal_to_usdc_execution_guard(_signal(symbol="LTCUSDT"), client=FakePublicClient(), now_ms=NOW_MS)
    assert decision.accepted is False
    assert "source_symbol_not_in_frozen_usdt_usdc_execution_map" in decision.reasons


def test_guard_rejects_stale_candles() -> None:
    decision = evaluate_usdt_signal_to_usdc_execution_guard(
        _signal(),
        client=FakePublicClient(usdc_close_ms=700_000),
        now_ms=NOW_MS,
    )
    assert decision.accepted is False
    assert "stale_usdc_execution_candle" in decision.reasons


def test_guard_rejects_wide_usdt_usdc_close_deviation() -> None:
    decision = evaluate_usdt_signal_to_usdc_execution_guard(
        _signal(),
        client=FakePublicClient(usdt_close="100", usdc_close="102"),
        now_ms=NOW_MS,
    )
    assert decision.accepted is False
    assert "usdt_usdc_close_deviation_too_wide" in decision.reasons


def test_guard_rejects_wide_spread_and_shallow_depth() -> None:
    decision = evaluate_usdt_signal_to_usdc_execution_guard(
        _signal(),
        client=FakePublicClient(bid="99", ask="101", depth_qty="0.1"),
        thresholds=GuardThresholds(max_signal_execution_close_deviation_bps=Decimal("500")),
        now_ms=NOW_MS,
    )
    assert decision.accepted is False
    assert "usdc_spread_too_wide" in decision.reasons
    assert "usdc_orderbook_depth_insufficient" in decision.reasons


def test_guard_report_writes_research_only_payload(tmp_path) -> None:
    payload = run_guard_report(_signal(), output_root=tmp_path, client=FakePublicClient(), now_ms=NOW_MS)
    assert payload["decision"]["classification"] == PASSED
    assert payload["real_money_allowed"] is False
    assert payload["order_endpoint_used"] is False
    assert (tmp_path / "usdt_usdc_execution_guard_report.json").exists()
