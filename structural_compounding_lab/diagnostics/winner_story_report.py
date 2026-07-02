from __future__ import annotations

from typing import Any


def render_winner_story_report(trades: list[dict[str, Any]]) -> str:
    lines = ["# Winner Story Report", ""]
    winners = sorted(trades, key=lambda row: float(row.get("pnl", 0.0) or 0.0), reverse=True)
    if not winners:
        return "# Winner Story Report\n\nNo trades were closed yet.\n"
    for row in winners[:20]:
        lines.append(
            f"- `{row.get('trade_id')}` `{row.get('symbol')}` `{row.get('side')}` pnl=`{float(row.get('pnl', 0.0) or 0.0):.2f}` R=`{float(row.get('r_multiple', 0.0) or 0.0):.2f}` personality=`{row.get('personality_label', 'unknown')}`"
        )
    return "\n".join(lines) + "\n"
