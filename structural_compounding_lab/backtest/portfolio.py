from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from structural_compounding_lab.capital.profit_vault import ProfitVaultState
from structural_compounding_lab.exit.cooldown import CooldownState


@dataclass
class StructuralPortfolioState:
    profit_vault: ProfitVaultState
    cooldown: CooldownState = field(default_factory=CooldownState)
    open_trade: dict[str, Any] | None = None
    equity_curve: list[dict[str, Any]] = field(default_factory=list)
    trade_rows: list[dict[str, Any]] = field(default_factory=list)
    setup_rows: list[dict[str, Any]] = field(default_factory=list)
    level_rows: list[dict[str, Any]] = field(default_factory=list)
    liquidity_rows: list[dict[str, Any]] = field(default_factory=list)
    cooldown_rows: list[dict[str, Any]] = field(default_factory=list)
    pyramiding_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "profit_vault": self.profit_vault.to_dict(),
            "cooldown": asdict(self.cooldown),
            "open_trade": self.open_trade,
            "equity_curve": self.equity_curve,
            "trade_rows": self.trade_rows,
            "setup_rows": self.setup_rows,
            "level_rows": self.level_rows,
            "liquidity_rows": self.liquidity_rows,
            "cooldown_rows": self.cooldown_rows,
            "pyramiding_rows": self.pyramiding_rows,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, Any] | None) -> "StructuralPortfolioState":
        payload = payload or {}
        return cls(
            profit_vault=ProfitVaultState.from_dict(payload.get("profit_vault")),
            cooldown=CooldownState.from_dict(payload.get("cooldown")),
            open_trade=payload.get("open_trade"),
            equity_curve=list(payload.get("equity_curve", [])),
            trade_rows=list(payload.get("trade_rows", [])),
            setup_rows=list(payload.get("setup_rows", [])),
            level_rows=list(payload.get("level_rows", [])),
            liquidity_rows=list(payload.get("liquidity_rows", [])),
            cooldown_rows=list(payload.get("cooldown_rows", [])),
            pyramiding_rows=list(payload.get("pyramiding_rows", [])),
        )
