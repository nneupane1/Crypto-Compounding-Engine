from __future__ import annotations

import os
import subprocess
from pathlib import Path


PROJECT_ROOT_ENV_VAR = "STRUCTURAL_COMPOUNDING_LAB_ROOT"
PACKAGE_DIR_NAME = "structural_compounding_lab"


def _normalize_project_root(candidate: str | Path | None) -> Path | None:
    if candidate in {None, ""}:
        return None
    path = Path(str(candidate)).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    else:
        path = path.resolve()
    if path.name == PACKAGE_DIR_NAME:
        path = path.parent
    return path


def _is_project_root(path: Path) -> bool:
    return (path / PACKAGE_DIR_NAME).is_dir()


def _git_project_root(start: Path) -> Path | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(start), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return _normalize_project_root(result.stdout.strip())


def _parent_candidates(start: Path) -> list[Path]:
    resolved = start.resolve()
    return [resolved, *resolved.parents]


def project_root(start: str | Path | None = None) -> Path:
    """Resolve the active clone root without relying on an OS-specific path."""

    explicit_root = _normalize_project_root(os.getenv(PROJECT_ROOT_ENV_VAR))
    if explicit_root is not None:
        if not _is_project_root(explicit_root):
            raise RuntimeError(
                f"{PROJECT_ROOT_ENV_VAR} does not point to a project containing "
                f"{PACKAGE_DIR_NAME}/: {explicit_root}"
            )
        return explicit_root

    starts = [
        _normalize_project_root(start),
        Path.cwd().resolve(),
        Path(__file__).resolve(),
    ]
    for candidate_start in starts:
        if candidate_start is None:
            continue
        search_start = candidate_start if candidate_start.is_dir() else candidate_start.parent
        git_root = _git_project_root(search_start)
        if git_root is not None and _is_project_root(git_root):
            return git_root
        for candidate in _parent_candidates(search_start):
            if _is_project_root(candidate):
                return candidate

    raise RuntimeError(
        f"Unable to locate a project root containing {PACKAGE_DIR_NAME}/. "
        f"Run from the clone or set {PROJECT_ROOT_ENV_VAR}."
    )


def package_root(start: str | Path | None = None) -> Path:
    return project_root(start) / PACKAGE_DIR_NAME


def output_root(start: str | Path | None = None) -> Path:
    return package_root(start) / "output"


def resolve_project_path(path: str | Path, start: str | Path | None = None) -> Path:
    candidate = Path(path).expanduser()
    if candidate.is_absolute():
        return candidate.resolve()
    return (project_root(start) / candidate).resolve()
