from __future__ import annotations

from typing import Any


def build_missed_pullback_report(original_vs_refined_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in original_vs_refined_rows if bool(row.get("missed_due_to_no_pullback"))]
