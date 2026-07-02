"""Loads local environment variables and JSON-backed application configuration."""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path


def _utc_now():
    return datetime.now(timezone.utc)


class EnvLoader:
    """
    Minimal .env loader for local secrets.
    Values already present in the environment are not overwritten.
    """

    def __init__(self, env_path=None):
        self.root_dir = Path(__file__).resolve().parents[1]
        self.env_path = Path(env_path) if env_path else self.root_dir / ".env"

    def load(self):
        if not self.env_path.exists():
            return

        for line in self.env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            if key:
                os.environ.setdefault(key, value)


class AppConfig:
    """
    JSON-backed application configuration.
    """

    def __init__(self, data, config_path, root_dir=None):
        self.data = data
        self.config_path = Path(config_path)
        self.root_dir = (
            Path(root_dir).resolve()
            if root_dir is not None
            else Path(__file__).resolve().parents[1]
        )

    @classmethod
    def load(cls, config_path=None):
        EnvLoader().load()

        root_dir = Path(__file__).resolve().parents[1]
        configured_path = config_path or os.getenv(
            "TRADING_SYSTEM_CONFIG",
            "config/settings.json"
        )

        path = Path(configured_path)
        if not path.is_absolute():
            path = root_dir / path

        with path.open() as f:
            data = json.load(f)

        return cls(data=data, config_path=path, root_dir=root_dir)

    def get(self, *keys, default=None):
        value = self.data

        for key in keys:
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]

        return self._resolve_special_value(keys, value)

    def require(self, *keys):
        value = self.get(*keys)
        if value is None:
            joined = ".".join(keys)
            raise KeyError(f"Missing required config value: {joined}")
        return value

    def path(self, *keys, default=None):
        value = self.get(*keys, default=default)
        if value is None:
            return None

        path = Path(value)
        if path.is_absolute():
            return path

        return self.root_dir / path

    @staticmethod
    def _resolve_special_value(keys, value):
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
