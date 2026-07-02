from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Literal


DemoMode = Literal["spot_testnet", "usdm_futures_testnet"]
OrderSide = Literal["BUY", "SELL"]
OrderType = Literal["MARKET", "LIMIT"]


@dataclass(frozen=True)
class DemoOrderIntent:
    signal_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None = None
    time_in_force: str | None = None
    reason: str = "demo_execution_reliability_test"


@dataclass(frozen=True)
class SymbolExecutionRules:
    symbol: str
    base_asset: str
    quote_asset: str
    min_qty: Decimal
    step_size: Decimal
    tick_size: Decimal
    min_notional: Decimal


@dataclass
class DemoOrderRecord:
    signal_id: str
    client_order_id: str
    symbol: str
    side: str
    order_type: str
    quantity: str
    price: str
    status: str
    exchange_order_id: str = ""
    submitted: bool = False
    canceled: bool = False
    filled_qty: str = "0"
    quote_filled: str = "0"
    error: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


SAFETY_FLAGS: dict[str, Any] = {
    "demo_paper_api_test_allowed": True,
    "binance_demo_testnet_only": True,
    "testnet_order_path_allowed": True,
    "real_money_allowed": False,
    "live_allowed": False,
    "production_order_path_allowed": False,
    "production_broker_path_allowed": False,
    "real_exchange_mainnet_allowed": False,
    "mainnet_order_allowed": False,
    "withdrawal_allowed": False,
    "deposit_allowed": False,
    "margin_borrow_allowed": False,
    "account_transfer_allowed": False,
    "paper_validation_ready": False,
    "scheduler_changed": False,
    "candidate_deployed_to_scheduler": False,
    "strategy_changed": False,
}
