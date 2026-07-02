from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class SimulatedTrade:
    symbol: str
    side: str
    entry_time: str
    entry_price: float
    quantity: float
    stop_price: float
    active_stop_price: float
    risk_per_unit: float
    initial_target: float
    strategy_type: str
    setup_class: str
    entry_reason: str
    max_hold_bars: int
    add_on_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
