from __future__ import annotations


def default_acceptance_criteria() -> list[str]:
    return [
        "holdout must remain positive after research-only costs",
        "average R should improve or remain stable",
        "drawdown must not worsen materially",
        "missed-winner rate from waiting for pullback must remain bounded",
        "candidate remains non-authoritative until manual promotion review",
    ]
