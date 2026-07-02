from __future__ import annotations

from typing import Any


def build_lab_summary_payload(summary: dict[str, Any], diagnostics: dict[str, Any]) -> dict[str, Any]:
    return {
        "research_only": True,
        "summary": summary,
        "diagnostics": diagnostics,
    }
