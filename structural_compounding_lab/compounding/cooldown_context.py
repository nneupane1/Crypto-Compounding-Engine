from __future__ import annotations


def derive_cooldown_context(*, cooldown_active: bool, fast_clear_eligible: bool) -> dict[str, object]:
    return {
        "cooldown_active": cooldown_active,
        "cooldown_fast_clear_candidate": bool(cooldown_active and fast_clear_eligible),
    }
