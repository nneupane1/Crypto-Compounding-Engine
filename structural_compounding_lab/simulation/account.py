from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AccountState:
    equity: float
    locked_profit: float
    active_capital: float
