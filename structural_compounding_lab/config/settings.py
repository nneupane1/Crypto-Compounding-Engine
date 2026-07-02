from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from structural_compounding_lab.common.project_paths import project_root


_DEFAULTS: dict[str, Any] = {
    "lab_name": "Structural Compounding Lab",
    "research_only": True,
    "read_only_frontend": True,
    "symbol": "BTCUSDT",
    "execution_timeframe": "1h",
    "confirmation_timeframes": ["12h", "1d", "1w"],
    "visual_timeframes": ["1h", "4h", "12h", "1d"],
    "data": {
        "base_path": "../data_storage",
        "default_interval": "1m",
        "history_start_date": "2018-01-01",
        "history_end_date": "2026-06-13",
        "analysis_start_date": None,
        "analysis_end_date": None,
    },
    "engine": {
        "structure_window_bars": 240,
        "liquidity_window_bars": 160,
        "setup_window_bars": 96,
        "resume_enabled": True,
        "checkpoint_every_bars": 250,
        "write_partial_artifacts": True,
    },
    "risk": {
        "risk_per_trade_pct": 0.01,
        "max_concurrent_positions": 1,
        "max_hold_bars": 72,
        "minimum_rr": 1.5,
    },
    "base_capital": 20000.0,
    "ema": {"fast": 20, "mid": 50, "slow": 200},
    "atr": {"period": 14, "shock_multiple": 2.4},
    "sr": {
        "pivot_left": 3,
        "pivot_right": 3,
        "touch_tolerance_pct": 0.002,
        "rolling_range_bars": 48,
        "zone_width_pct": 0.0015,
    },
    "liquidity": {
        "equal_level_tolerance_pct": 0.0012,
        "sweep_lookback_bars": 20,
        "reclaim_tolerance_pct": 0.0008,
    },
    "momentum_personality": {
        "enabled": True,
        "research_only": True,
        "hard_gate": False,
    },
    "pullback_research": {
        "enabled": True,
        "research_only": True,
        "micro_pullback_lower_timeframe": "5m",
        "fallback_lower_timeframe": "1m",
        "micro_max_depth_atr": 0.8,
        "healthy_max_depth_atr": 1.6,
        "deep_max_depth_atr": 2.6,
    },
    "setup": {
        "recent_liquidity_bars": 16,
        "max_level_distance_atr": 1.25,
        "min_level_strength": 1.0,
        "target_buffer_atr": 0.2,
        "fallback_without_liquidity": True,
    },
    "pyramiding": {
        "enabled": True,
        "max_add_ons": 2,
        "add_on_trigger_r": 1.0,
        "size_fraction": 0.25,
    },
    "convexity": {
        "enabled": True,
        "min_risk_multiplier": 0.7,
        "max_risk_multiplier": 1.35,
        "strong_score_threshold": 3.6,
        "elite_score_threshold": 4.1,
    },
    "cooldown": {
        "enabled": True,
        "bars": 6,
        "minimum_bars": 2,
        "requires_danger_clear": True,
        "fast_resume_score": 3.55,
    },
    "profit_vault": {
        "enabled": True,
        "lock_on_danger": True,
        "reset_active_capital_to_base": True,
        "minimum_lock_profit": 0.0,
        "lock_after_r": 1.1,
    },
    "output": {"path": "output"},
}


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _normalize_legacy_schema(raw: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(raw)

    if "primary_execution_timeframe" in normalized and "execution_timeframe" not in normalized:
        normalized["execution_timeframe"] = normalized["primary_execution_timeframe"]

    indicators = normalized.get("indicators")
    if isinstance(indicators, dict):
        normalized.setdefault(
            "ema",
            {
                "fast": indicators.get("ema_fast", _DEFAULTS["ema"]["fast"]),
                "mid": indicators.get("ema_mid", _DEFAULTS["ema"]["mid"]),
                "slow": indicators.get("ema_slow", _DEFAULTS["ema"]["slow"]),
            },
        )
        normalized.setdefault(
            "atr",
            {
                "period": indicators.get("atr_period", _DEFAULTS["atr"]["period"]),
                "shock_multiple": _DEFAULTS["atr"]["shock_multiple"],
            },
        )

    cooldown = normalized.get("cooldown")
    if isinstance(cooldown, dict) and "bars" not in cooldown and "minimum_bars" in cooldown:
        cooldown = dict(cooldown)
        cooldown["bars"] = cooldown["minimum_bars"]
        normalized["cooldown"] = cooldown

    if "market_structure" in normalized and "sr" not in normalized:
        normalized["sr"] = dict(_DEFAULTS["sr"])

    data = normalized.get("data")
    if isinstance(data, dict):
        data = dict(data)
        if "run_start_date" in data and "analysis_start_date" not in data:
            data["analysis_start_date"] = data["run_start_date"]
        if "run_end_date" in data and "analysis_end_date" not in data:
            data["analysis_end_date"] = data["run_end_date"]
        normalized["data"] = data

    return normalized


def _load_yaml_fallback(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            f"YAML config requested but PyYAML is not installed: {path}"
        ) from exc
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"Expected mapping in YAML config: {path}")
    return payload


@dataclass(frozen=True)
class StructuralLabConfig:
    data: dict[str, Any]
    config_path: Path
    root_dir: Path = field(default_factory=project_root)

    @classmethod
    def load(cls, config_path: str | Path | None = None) -> "StructuralLabConfig":
        root_dir = project_root()
        default_json = root_dir / "structural_compounding_lab" / "config" / "structural_compounding_settings.json"
        candidate = Path(config_path) if config_path is not None else default_json
        if not candidate.is_absolute():
            candidate = root_dir / candidate
        if not candidate.exists():
            merged = dict(_DEFAULTS)
            return cls(data=merged, config_path=default_json, root_dir=root_dir)

        if candidate.suffix.lower() in {".yaml", ".yml"}:
            raw = _load_yaml_fallback(candidate)
        else:
            raw = json.loads(candidate.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"Expected object config in {candidate}")
        merged = _deep_merge(_DEFAULTS, _normalize_legacy_schema(raw))
        return cls(data=merged, config_path=candidate, root_dir=root_dir)

    def get(self, *keys: str, default: Any = None) -> Any:
        value: Any = self.data
        for key in keys:
            if not isinstance(value, dict) or key not in value:
                return default
            value = value[key]
        return value

    def require(self, *keys: str) -> Any:
        value = self.get(*keys, default=None)
        if value is None:
            raise KeyError(f"Missing structural lab config key: {'.'.join(keys)}")
        return value

    def path(self, *keys: str, default: Any = None) -> Path | None:
        value = self.get(*keys, default=default)
        if value is None:
            return None
        path = Path(str(value))
        if path.is_absolute():
            return path
        return self.lab_root / path

    @property
    def lab_root(self) -> Path:
        return self.root_dir / "structural_compounding_lab"

    @property
    def output_root(self) -> Path:
        return self.path("output", "path") or (self.lab_root / "output")


def load_structural_lab_config(config_path: str | Path | None = None) -> StructuralLabConfig:
    return StructuralLabConfig.load(config_path=config_path)
