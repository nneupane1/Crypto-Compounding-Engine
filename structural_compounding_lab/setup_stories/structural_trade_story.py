from __future__ import annotations

from typing import Any


def render_trade_story_markdown(story: dict[str, Any]) -> str:
    setup = story.get("setup", {})
    personality = story.get("personality", {})
    pullback = story.get("pullback", {})
    compounding = story.get("compounding", {})
    checklist = story.get("condition_checklist", [])
    lines = [
        f"## {story.get('symbol', 'BTCUSDT')} {setup.get('side', 'flat')} @ {story.get('timestamp')}",
        "",
        f"- Pattern: `{setup.get('pattern')}`",
        f"- Entry / stop / target: `{setup.get('entry_price')}` / `{setup.get('stop_price')}` / `{setup.get('target_price')}`",
        f"- Risk/reward: `{setup.get('risk_reward')}`",
        f"- Personality: `{personality.get('personality_label')}` at `{personality.get('personality_confidence')}` confidence",
        f"- Pullback type: `{pullback.get('pullback_type')}`",
        f"- Pullback R improvement: `{pullback.get('r_improvement_vs_original')}`",
        f"- Compounding readiness: `{compounding.get('compounding_readiness_score')}`",
        "",
        "### Checklist",
        "",
    ]
    for item in checklist:
        status = "pass" if item.get("passed") else "warn"
        lines.append(f"- `{status}` {item.get('label')}")
    lines.extend(
        [
            "",
            "### Explanation",
            "",
            f"{personality.get('explanation_text')}",
        ]
    )
    return "\n".join(lines) + "\n"
