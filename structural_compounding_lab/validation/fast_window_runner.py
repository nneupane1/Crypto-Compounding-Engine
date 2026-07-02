from __future__ import annotations

from typing import Any


def resolve_fast_windows() -> dict[str, dict[str, Any]]:
    return {
        "smoke_window": {"start": "2026-05-31", "end": "2026-06-13", "auto_run": False},
        "diagnostic_fast_window": {"start": "2025-12-14", "end": "2026-06-13", "auto_run": False},
        "recent_holdout": {"start": "2025-06-14", "end": "2026-06-13", "auto_run": False},
    }
