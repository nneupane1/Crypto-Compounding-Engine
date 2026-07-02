from __future__ import annotations

from pathlib import Path
from typing import Any


def artifact_paths(*args: Any, **kwargs: Any) -> dict[str, Path]:
    from .paths import artifact_paths as _artifact_paths

    return _artifact_paths(*args, **kwargs)


def ensure_output_dirs(*args: Any, **kwargs: Any) -> Path:
    from .paths import ensure_output_dirs as _ensure_output_dirs

    return _ensure_output_dirs(*args, **kwargs)


def lab_root(*args: Any, **kwargs: Any) -> Path:
    from .paths import lab_root as _lab_root

    return _lab_root(*args, **kwargs)


def output_root(*args: Any, **kwargs: Any) -> Path:
    from .paths import output_root as _output_root

    return _output_root(*args, **kwargs)

__all__ = ["artifact_paths", "ensure_output_dirs", "lab_root", "output_root"]
