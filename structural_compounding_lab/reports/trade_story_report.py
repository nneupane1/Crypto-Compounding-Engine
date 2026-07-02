from __future__ import annotations

from typing import Any


def render_trade_story_report(stories: list[dict[str, Any]]) -> str:
    lines = ["# Structural Trade Story Report", ""]
    if not stories:
        return "# Structural Trade Story Report\n\nNo stories built yet.\n"
    for story in stories[:20]:
        lines.append(f"## {story.get('story_id')}")
        lines.append("")
        lines.append(f"- symbol: `{story.get('symbol')}`")
        lines.append(f"- setup: `{story.get('setup', {}).get('pattern')}`")
        lines.append(f"- personality: `{story.get('personality', {}).get('personality_label')}`")
        lines.append(f"- pullback: `{story.get('pullback', {}).get('pullback_type')}`")
        lines.append(f"- compounding readiness: `{story.get('compounding', {}).get('compounding_readiness_score')}`")
        lines.append("")
    return "\n".join(lines) + "\n"
