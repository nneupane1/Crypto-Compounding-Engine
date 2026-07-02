from __future__ import annotations

import json
from pathlib import Path
from typing import Any


_SCENARIOS = {
    "low_cost": {"fee_bps": 4.0, "slippage_bps": 2.0, "spread_bps": 1.0, "stop_stress_bps": 4.0},
    "normal_cost": {"fee_bps": 8.0, "slippage_bps": 5.0, "spread_bps": 2.0, "stop_stress_bps": 8.0},
    "high_cost": {"fee_bps": 12.0, "slippage_bps": 8.0, "spread_bps": 3.5, "stop_stress_bps": 12.0},
    "stress_cost": {"fee_bps": 16.0, "slippage_bps": 14.0, "spread_bps": 5.0, "stop_stress_bps": 18.0},
}


def _trade_notional(row: dict[str, Any]) -> float:
    entry = float(row.get("entry_price", 0.0) or 0.0)
    exit_price = float(row.get("exit_price", entry) or entry)
    quantity = float(row.get("quantity", 1.0) or 1.0)
    return abs((entry + exit_price) * 0.5 * quantity)


def _apply_costs(trades: list[dict[str, Any]], scenario: dict[str, float]) -> dict[str, Any]:
    total_fees = 0.0
    total_slippage = 0.0
    gross_pnl = 0.0
    net_pnl = 0.0
    gross_r = 0.0
    net_r = 0.0
    gross_profit = 0.0
    gross_loss = 0.0
    net_profit = 0.0
    net_loss = 0.0
    drawdown_penalty = 0.0
    for row in trades:
        pnl = float(row.get("pnl", 0.0) or 0.0)
        r_multiple = float(row.get("r_multiple", 0.0) or 0.0)
        notional = _trade_notional(row)
        stop_like = str(row.get("exit_reason", "")).lower() in {"stop_hit", "hard_exit", "danger_sniffed"}
        fee_cost = notional * (scenario["fee_bps"] / 10000.0) * 2.0
        slip_bps = scenario["slippage_bps"] + (scenario["stop_stress_bps"] if stop_like else 0.0)
        slippage_cost = notional * ((scenario["spread_bps"] + slip_bps) / 10000.0)
        net_trade_pnl = pnl - fee_cost - slippage_cost
        risk_value = abs(pnl / r_multiple) if abs(r_multiple) > 1e-8 else max(abs(pnl), 1.0)
        net_trade_r = net_trade_pnl / risk_value if risk_value > 0 else 0.0
        total_fees += fee_cost
        total_slippage += slippage_cost
        gross_pnl += pnl
        net_pnl += net_trade_pnl
        gross_r += r_multiple
        net_r += net_trade_r
        if pnl >= 0:
            gross_profit += pnl
        else:
            gross_loss += abs(pnl)
        if net_trade_pnl >= 0:
            net_profit += net_trade_pnl
        else:
            net_loss += abs(net_trade_pnl)
        drawdown_penalty += max(0.0, slippage_cost / max(notional, 1.0))
    trade_count = len(trades)
    return {
        "trade_count": trade_count,
        "gross_pnl": gross_pnl,
        "net_pnl_after_costs": net_pnl,
        "gross_r": gross_r,
        "net_r_after_costs": net_r,
        "profit_factor_before_costs": (gross_profit / gross_loss) if gross_loss > 0 else float(gross_profit > 0),
        "profit_factor_after_costs": (net_profit / net_loss) if net_loss > 0 else float(net_profit > 0),
        "average_cost_per_trade": ((total_fees + total_slippage) / trade_count) if trade_count else 0.0,
        "total_fees": total_fees,
        "total_estimated_slippage": total_slippage,
        "max_drawdown_penalty_proxy": drawdown_penalty,
    }


def build_execution_cost_outputs(*, trades: list[dict[str, Any]], output_root: Path) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    scenario_metrics = {
        name: _apply_costs(trades, scenario)
        for name, scenario in _SCENARIOS.items()
    }
    model_payload = {
        "research_only": True,
        "scenarios": _SCENARIOS,
        "notes": "Execution realism is backtest research only and does not alter live or paper execution behavior.",
    }
    sensitivity_payload = {
        "research_only": True,
        "scenario_metrics": scenario_metrics,
        "acceptance_rule": "A candidate is weak if it only works before costs and fails after realistic cost assumptions.",
    }
    (output_root / "execution_cost_model.json").write_text(json.dumps(model_payload, indent=2), encoding="utf-8")
    (output_root / "execution_cost_sensitivity.json").write_text(json.dumps(sensitivity_payload, indent=2), encoding="utf-8")
    assumptions = [
        "# Execution Cost Assumptions",
        "",
        "Research-only fee, spread, slippage, and stop-stress assumptions for structural-compounding validation.",
        "",
    ]
    for name, scenario in _SCENARIOS.items():
        assumptions.append(f"- `{name}`: {scenario}")
    (output_root / "execution_cost_assumptions.md").write_text("\n".join(assumptions) + "\n", encoding="utf-8")
    sensitivity_lines = ["# Execution Cost Sensitivity", ""]
    for name, metrics in scenario_metrics.items():
        sensitivity_lines.append(
            f"- `{name}` gross_pnl={metrics['gross_pnl']:.2f} net_pnl={metrics['net_pnl_after_costs']:.2f} pf_after={metrics['profit_factor_after_costs']:.2f}"
        )
    (output_root / "execution_cost_sensitivity.md").write_text("\n".join(sensitivity_lines) + "\n", encoding="utf-8")
    return sensitivity_payload
