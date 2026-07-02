from __future__ import annotations

from typing import Any


def build_promotion_packet(*, summary: dict[str, Any], candidate_registry: dict[str, Any], execution_costs: dict[str, Any]) -> dict[str, Any]:
    return {
        "research_only": True,
        "requires_manual_promotion": True,
        "automatic_promotion": False,
        "summary_metrics": summary.get("metrics", {}),
        "candidate_registry": candidate_registry,
        "execution_cost_sensitivity": execution_costs,
    }
