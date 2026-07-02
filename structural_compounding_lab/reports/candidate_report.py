from __future__ import annotations

from typing import Any


def render_candidate_report(candidate_registry: dict[str, Any]) -> str:
    lines = ["# Structural Compounding Candidate Registry", ""]
    for candidate in candidate_registry.get("candidates", []):
        lines.append(f"## {candidate.get('candidate_id')}")
        lines.append("")
        lines.append(candidate.get("hypothesis", ""))
        lines.append("")
        lines.append(f"- authoritative: `{candidate.get('authoritative')}`")
        lines.append(f"- paper_allowed: `{candidate.get('paper_allowed')}`")
        lines.append(f"- real_money_allowed: `{candidate.get('real_money_allowed')}`")
        lines.append("")
    return "\n".join(lines) + "\n"
