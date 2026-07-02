from __future__ import annotations

from typing import Any


def build_candidate_stub_result(candidate_id: str) -> dict[str, Any]:
    return {
        "candidate_id": candidate_id,
        "run_state": "spec_only",
        "authoritative": False,
        "paper_allowed": False,
        "real_money_allowed": False,
        "note": "This candidate is registered for research only. No backtest ladder was auto-started.",
    }
