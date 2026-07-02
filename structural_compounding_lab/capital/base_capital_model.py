from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BaseCapitalModel:
    base_capital: float

    def reset_value(self) -> float:
        return float(self.base_capital)
