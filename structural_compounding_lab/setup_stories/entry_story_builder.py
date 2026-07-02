from __future__ import annotations

from typing import Any

from .condition_checklist import build_condition_checklist


def build_entry_story(
    *,
    candidate: dict[str, Any],
    ema_context: dict[str, Any],
    atr_context: dict[str, Any],
    volume_context: dict[str, Any],
    vwap_context: dict[str, Any],
    support_resistance: dict[str, Any],
    htf_context: dict[str, Any],
    macd_features: dict[str, Any],
    bollinger_features: dict[str, Any],
    pullback_features: dict[str, Any],
    personality: dict[str, Any],
    compounding: dict[str, Any],
    story_id: str | None = None,
) -> dict[str, Any]:
    story = {
        "story_id": story_id or f"{candidate.get('side', 'flat')}-{candidate.get('timestamp', 'unknown')}",
        "timestamp": candidate.get("timestamp"),
        "symbol": candidate.get("symbol", "BTCUSDT"),
        "setup": {
            "timeframe": candidate.get("execution_timeframe", "1h"),
            "side": candidate.get("side"),
            "pattern": candidate.get("pattern"),
            "entry_price": candidate.get("close_price"),
            "stop_price": candidate.get("stop_price"),
            "target_price": candidate.get("target_price"),
            "risk_reward": candidate.get("risk_reward"),
            "entry_reason": candidate.get("entry_reason"),
        },
        "htf": htf_context,
        "ema_context": ema_context,
        "atr_context": atr_context,
        "volume_context": volume_context,
        "vwap_context": vwap_context,
        "support_resistance": support_resistance,
        "macd": macd_features,
        "bollinger": bollinger_features,
        "pullback": pullback_features,
        "personality": personality,
        "compounding": compounding,
    }
    story["condition_checklist"] = build_condition_checklist(story)
    return story
