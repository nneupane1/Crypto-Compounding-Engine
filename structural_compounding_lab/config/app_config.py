from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT_ENV_VAR = "STRUCTURAL_COMPOUNDING_LAB_ROOT"
PACKAGE_DIR_NAME = "structural_compounding_lab"


def _project_root() -> Path:
    explicit = os.getenv(PROJECT_ROOT_ENV_VAR)
    if explicit:
        candidate = Path(explicit).expanduser().resolve()
        if candidate.name == PACKAGE_DIR_NAME:
            candidate = candidate.parent
        if (candidate / PACKAGE_DIR_NAME).is_dir():
            return candidate
        raise RuntimeError(f"{PROJECT_ROOT_ENV_VAR} does not contain {PACKAGE_DIR_NAME}/: {candidate}")

    try:
        result = subprocess.run(
            ["git", "-C", str(Path.cwd()), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
        )
        candidate = Path(result.stdout.strip()).expanduser().resolve()
        if (candidate / PACKAGE_DIR_NAME).is_dir():
            return candidate
    except (OSError, subprocess.CalledProcessError):
        pass

    current = Path.cwd().resolve()
    for candidate in [current, *current.parents, Path(__file__).resolve().parents[2]]:
        if (candidate / PACKAGE_DIR_NAME).is_dir():
            return candidate

    raise RuntimeError(f"Unable to locate project root containing {PACKAGE_DIR_NAME}/")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class EnvLoader:
    """Minimal project-root .env loader used by legacy-compatible utilities."""

    def __init__(self, env_path: str | Path | None = None, root_dir: str | Path | None = None) -> None:
        self.root_dir = Path(root_dir).resolve() if root_dir is not None else _project_root()
        self.env_path = Path(env_path) if env_path is not None else self.root_dir / ".env"

    def load(self) -> None:
        if not self.env_path.exists():
            return

        for raw_line in self.env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)


class AppConfig:
    """
    Project-root JSON config loader for compounding-runtime compatibility.

    This mirrors the old top-level ``config.AppConfig`` behavior while resolving
    the clone root without importing old root config helpers.
    Keeping it inside the package prevents current compounding/runtime modules
    from depending on the old Retail Trading System root package.
    """

    def __init__(self, data: dict[str, Any], config_path: str | Path, root_dir: str | Path | None = None) -> None:
        self.data = data
        self.config_path = Path(config_path)
        self.root_dir = Path(root_dir).resolve() if root_dir is not None else _project_root()

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "AppConfig":
        root = _project_root()
        EnvLoader(root_dir=root).load()
        configured_path = config_path or os.getenv("TRADING_SYSTEM_CONFIG", "config/settings.json")
        path = Path(configured_path)
        if not path.is_absolute():
            path = root / path
        with path.open(encoding="utf-8") as handle:
            data = json.load(handle)
        return cls(data=data, config_path=path, root_dir=root)

    def get(self, *keys: str, default: Any = None) -> Any:
        value: Any = self.data
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
        return self._resolve_special_value(keys, value)

    def require(self, *keys: str) -> Any:
        value = self.get(*keys)
        if value is None:
            joined = ".".join(keys)
            raise KeyError(f"Missing required config value: {joined}")
        return value

    def path(self, *keys: str, default: Any = None) -> Path | None:
        value = self.get(*keys, default=default)
        if value is None:
            return None
        path = Path(value)
        if path.is_absolute():
            return path
        return self.root_dir / path

    @staticmethod
    def _resolve_special_value(keys: tuple[str, ...], value: Any) -> Any:
        if not isinstance(value, str):
            return value

        normalized_keys = tuple(str(key) for key in keys)
        token = value.strip().lower()

        if normalized_keys == ("history", "end_date"):
            if token in {
                "auto",
                "latest_closed_day",
                "latest_closed_day_utc",
                "yesterday",
                "utc_yesterday",
            }:
                return (_utc_now().date() - timedelta(days=1)).isoformat()
            if token in {"today", "utc_today"}:
                return _utc_now().date().isoformat()

        return value
