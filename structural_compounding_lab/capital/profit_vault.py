from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class ProfitVaultState:
    base_capital: float
    active_trading_capital: float
    locked_profit: float = 0.0
    floating_profit: float = 0.0
    cooldown_active: bool = False
    cooldown_until: str | None = None
    current_compounding_cycle_id: str = "cycle-0"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "ProfitVaultState":
        payload = payload or {}
        return cls(
            base_capital=float(payload.get("base_capital", 0.0)),
            active_trading_capital=float(payload.get("active_trading_capital", 0.0)),
            locked_profit=float(payload.get("locked_profit", 0.0)),
            floating_profit=float(payload.get("floating_profit", 0.0)),
            cooldown_active=bool(payload.get("cooldown_active", False)),
            cooldown_until=payload.get("cooldown_until"),
            current_compounding_cycle_id=str(payload.get("current_compounding_cycle_id", "cycle-0")),
        )

    @property
    def total_equity(self) -> float:
        return self.active_trading_capital + self.locked_profit + self.floating_profit

    def apply_realized_pnl(self, pnl: float) -> None:
        self.active_trading_capital += float(pnl)

    def mark_floating_profit(self, pnl: float) -> None:
        self.floating_profit = float(pnl)

    def lock_profit_and_reset(self, *, reason: str = "danger_sniffed") -> dict[str, Any]:
        profit = max(0.0, self.active_trading_capital - self.base_capital)
        if profit > 0.0:
            self.locked_profit += profit
        self.active_trading_capital = float(self.base_capital)
        self.floating_profit = 0.0
        cycle_number = int(self.current_compounding_cycle_id.split("-")[-1]) + 1
        self.current_compounding_cycle_id = f"cycle-{cycle_number}"
        return {
            "event_type": "profit_lock",
            "reason": reason,
            "locked_profit": self.locked_profit,
            "active_trading_capital": self.active_trading_capital,
            "cycle_id": self.current_compounding_cycle_id,
        }
