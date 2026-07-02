from __future__ import annotations

from typing import Any

from structural_compounding_lab.candidates import (
    btc_micro_pullback_refinement,
    compression_breakout_research,
    exhaustion_risk_research,
    htf_structural_continuation,
    momentum_burst_research,
    runner_quality_research,
)


def load_candidate_registry() -> dict[str, Any]:
    candidates = [
        btc_micro_pullback_refinement,
        htf_structural_continuation,
        momentum_burst_research,
        compression_breakout_research,
        exhaustion_risk_research,
        runner_quality_research,
    ]
    return {
        "lab_name": "Structural Compounding Lab",
        "research_only": True,
        "authoritative": False,
        "candidate_count": len(candidates),
        "candidates": [candidate.to_dict() for candidate in candidates],
    }
