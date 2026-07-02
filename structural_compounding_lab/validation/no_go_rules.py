from __future__ import annotations


def default_no_go_rules() -> list[str]:
    return [
        "no live or paper runtime mutation",
        "no full-history auto-run on import",
        "no hard gating from MACD/Bollinger by default",
        "no automatic promotion",
        "no 6H enablement",
        "no real-money permissions",
    ]
