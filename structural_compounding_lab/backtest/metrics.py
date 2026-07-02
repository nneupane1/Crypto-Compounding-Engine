from __future__ import annotations

from typing import Any


def summarize_trades(trades: list[dict[str, Any]], *, base_capital: float, ending_equity: float) -> dict[str, Any]:
    if not trades:
        return {
            "trade_count": 0,
            "win_rate": 0.0,
            "profit_factor": 0.0,
            "avg_r": 0.0,
            "total_return_pct": max(0.0, (ending_equity - base_capital) / max(base_capital, 1e-8)),
            "max_drawdown_pct": 0.0,
            "r_multiple_summary": "No trades yet.",
        }
    wins = [trade for trade in trades if float(trade.get("pnl", 0.0)) > 0.0]
    losses = [trade for trade in trades if float(trade.get("pnl", 0.0)) <= 0.0]
    gross_profit = sum(float(trade.get("pnl", 0.0)) for trade in wins)
    gross_loss = abs(sum(float(trade.get("pnl", 0.0)) for trade in losses))
    avg_r = sum(float(trade.get("r_multiple", 0.0)) for trade in trades) / max(len(trades), 1)
    return {
        "trade_count": len(trades),
        "win_rate": len(wins) / max(len(trades), 1),
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else float(len(wins) > 0),
        "avg_r": avg_r,
        "total_return_pct": (ending_equity - base_capital) / max(base_capital, 1e-8),
        "max_drawdown_pct": _max_drawdown_pct([float(trade.get("equity_after", base_capital)) for trade in trades], base_capital),
        "r_multiple_summary": (
            f"{len(wins)} winners / {len(losses)} losers / average R {avg_r:.2f}"
        ),
    }


def _max_drawdown_pct(points: list[float], base_capital: float) -> float:
    peak = base_capital
    max_drawdown = 0.0
    for point in points:
        peak = max(peak, point)
        if peak > 0:
            max_drawdown = max(max_drawdown, (peak - point) / peak)
    return max_drawdown
