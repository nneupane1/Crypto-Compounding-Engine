from __future__ import annotations

from typing import Any


def render_rejected_signal_story_report(setup_rows: list[dict[str, Any]]) -> str:
    lines = ["# Rejected Structural Signal Stories", ""]
    rejected = [row for row in setup_rows if str(row.get("decision")) not in {"opened", "pending_open"}]
    if not rejected:
        return "# Rejected Structural Signal Stories\n\nNo rejected stories were logged.\n"
    for row in rejected[:25]:
        lines.append(
            f"- `{row.get('timestamp')}` `{row.get('symbol', 'BTCUSDT')}` `{row.get('side')}` -> `{row.get('decision')}` | {row.get('explanation') or row.get('entry_reason')}"
        )
    return "\n".join(lines) + "\n"
