from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CooldownState:
    active: bool = False
    remaining_bars: int = 0
    elapsed_bars: int = 0
    minimum_bars: int = 0
    fast_resume_score: float = 0.0
    requires_danger_clear: bool = True
    reason: str = ""
    release_reason: str = ""

    @classmethod
    def from_dict(cls, payload: dict | None) -> "CooldownState":
        payload = payload or {}
        return cls(
            active=bool(payload.get("active", False)),
            remaining_bars=int(payload.get("remaining_bars", 0)),
            elapsed_bars=int(payload.get("elapsed_bars", 0)),
            minimum_bars=int(payload.get("minimum_bars", 0)),
            fast_resume_score=float(payload.get("fast_resume_score", 0.0)),
            requires_danger_clear=bool(payload.get("requires_danger_clear", True)),
            reason=str(payload.get("reason", "")),
            release_reason=str(payload.get("release_reason", "")),
        )


def start_cooldown(
    *,
    bars: int,
    reason: str,
    minimum_bars: int = 0,
    fast_resume_score: float = 0.0,
    requires_danger_clear: bool = True,
) -> CooldownState:
    return CooldownState(
        active=bars > 0,
        remaining_bars=max(0, bars),
        elapsed_bars=0,
        minimum_bars=max(0, minimum_bars),
        fast_resume_score=max(0.0, fast_resume_score),
        requires_danger_clear=requires_danger_clear,
        reason=reason,
        release_reason="",
    )


def update_cooldown(
    state: CooldownState,
    *,
    danger_cleared: bool,
    candidate_ready: bool = False,
    candidate_score: float = 0.0,
    aligned_setup: bool = False,
) -> CooldownState:
    if not state.active:
        return state
    elapsed = state.elapsed_bars + 1
    remaining = max(0, state.remaining_bars - 1)
    minimum_satisfied = elapsed >= state.minimum_bars
    danger_gate_open = danger_cleared or not state.requires_danger_clear
    fast_clear = (
        minimum_satisfied
        and danger_gate_open
        and candidate_ready
        and aligned_setup
        and candidate_score >= state.fast_resume_score
    )
    normal_clear = remaining == 0 and danger_gate_open
    still_active = not (fast_clear or normal_clear)
    release_reason = ""
    if fast_clear:
        release_reason = "fast_resumed_for_high_quality_setup"
    elif normal_clear:
        release_reason = "cooldown_completed"
    return CooldownState(
        active=still_active,
        remaining_bars=remaining,
        elapsed_bars=elapsed,
        minimum_bars=state.minimum_bars,
        fast_resume_score=state.fast_resume_score,
        requires_danger_clear=state.requires_danger_clear,
        reason=state.reason if still_active else "",
        release_reason=release_reason,
    )
