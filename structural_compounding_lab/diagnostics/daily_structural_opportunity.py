from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from structural_compounding_lab.config import StructuralLabConfig
from structural_compounding_lab.data.data_adapter import StructuralDataAdapter


_OPPORTUNITY_LABELS = (
    "NO_OPPORTUNITY",
    "WEAK_OPPORTUNITY",
    "VALID_STRUCTURAL_OPPORTUNITY",
    "STRONG_STRUCTURAL_HILL",
    "EXCEPTIONAL_COMPOUNDING_OPPORTUNITY",
)
_PARTICIPATION_MODES = (
    "FULL_SIZE_CANDIDATE",
    "REDUCED_SIZE_CANDIDATE",
    "PROBE_CANDIDATE",
    "WAIT_FOR_CONFIRMATION",
    "NO_ADD_ON_MANAGEMENT",
    "DE_RISK_FAST_MANAGEMENT",
    "REJECT_INVALID",
)
_MISSED_HIGH_R_CATEGORIES = (
    "TRUE_MISSED_HIGH_R_OPPORTUNITY",
    "THEORETICAL_HIGH_R_ONLY",
    "COST_DOMINATED_NOT_TRADEABLE",
    "TINY_STOP_OR_NOISE",
    "STRUCTURE_WEAK_OR_BROKEN",
    "VALID_PROBE_NOT_MISSED",
    "VALID_DE_RISK_NOT_MISSED",
    "COOLDOWN_OR_RISK_BLOCKED",
    "INSUFFICIENT_EVIDENCE",
)
_SUPPORT_TYPES = {
    "support",
    "range_low",
    "prev_day_low",
    "prev_week_low",
    "prev_month_low",
    "pivot_low",
}
_RESISTANCE_TYPES = {
    "resistance",
    "range_high",
    "prev_day_high",
    "prev_week_high",
    "prev_month_high",
    "pivot_high",
}


@dataclass(frozen=True)
class DailyStructuralOpportunityConfig:
    package_root: Path
    output_root: Path
    source_history_path: Path | None = None


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or str(value).strip() == "":
            return float(default)
        return float(value)
    except (TypeError, ValueError):
        return float(default)


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value is None or str(value).strip() == "":
            return int(default)
        return int(float(value))
    except (TypeError, ValueError):
        return int(default)


def _to_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"true", "1", "yes"}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2.0


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0.0:
        return default
    return numerator / denominator


def _score_to_unit(value: float, ceiling: float) -> float:
    if ceiling <= 0.0:
        return 0.0
    return _clamp(value / ceiling)


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if ts.tzinfo is None:
        return ts
    return ts.tz_convert("UTC").tz_localize(None)


def _date_text(value: pd.Timestamp | None) -> str:
    if value is None:
        return ""
    return value.normalize().strftime("%Y-%m-%d")


def _artifact_paths(config: DailyStructuralOpportunityConfig) -> dict[str, Path]:
    output_root = config.package_root / "output"
    return {
        "settings": config.package_root / "config" / "structural_compounding_settings.json",
        "setup_log": output_root / "setup_log.csv",
        "level_log": output_root / "level_log.csv",
        "liquidity_events": output_root / "liquidity_events.csv",
        "trades": output_root / "trades.csv",
        "cooldown_log": output_root / "cooldown_log.csv",
        "pyramiding_log": output_root / "pyramiding_log.csv",
        "equity": output_root / "equity.csv",
        "profit_vault": output_root / "profit_vault.json",
        "participation_routing_summary": output_root / "participation_routing_001" / "participation_routing_summary.json",
        "routed_candidates": output_root / "participation_routing_001" / "diagnostics" / "routed_candidates.csv",
        "project_direction_summary": output_root / "project_direction_review_001" / "project_direction_summary.json",
        "legacy_summary": output_root / "daily_structural_opportunity_001" / "daily_structural_opportunity_summary.json",
        "legacy_report": output_root / "daily_structural_opportunity_001" / "daily_structural_opportunity_report.md",
    }


def _resolve_source_history_path(config: DailyStructuralOpportunityConfig, settings: dict[str, Any]) -> Path | None:
    if config.source_history_path is not None and config.source_history_path.exists():
        return config.source_history_path

    output_root = config.package_root / "output"
    symbol = str(settings.get("symbol", "BTCUSDT")).upper()
    interval = str(settings.get("data", {}).get("default_interval", "1m"))
    candidates = sorted(
        output_root.glob(f"*{symbol.lower()}*_{interval}_*.csv"),
        key=lambda candidate: candidate.stat().st_mtime_ns,
        reverse=True,
    )
    if not candidates:
        candidates = sorted(
            output_root.glob(f"*{symbol.upper()}*_{interval}_*.csv"),
            key=lambda candidate: candidate.stat().st_mtime_ns,
            reverse=True,
        )
    if candidates:
        return candidates[0]

    config_path = config.package_root / "config" / "structural_compounding_settings.json"
    try:
        adapter = StructuralDataAdapter(config=StructuralLabConfig.load(config_path))
        return adapter.resolve_history_file(symbol)
    except Exception:
        return None


def _load_history_daily_context(source_history_path: Path | None) -> pd.DataFrame:
    if source_history_path is None or not source_history_path.exists():
        return pd.DataFrame()
    frame = pd.read_csv(source_history_path)
    if "timestamp" not in frame.columns:
        return pd.DataFrame()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
    frame = frame.dropna(subset=["timestamp"])
    if frame.empty:
        return pd.DataFrame()
    frame["date"] = frame["timestamp"].dt.normalize()
    grouped = frame.groupby("date", sort=True).agg(
        candle_count=("close", "count"),
        high=("high", "max"),
        low=("low", "min"),
        close=("close", "last"),
        volume=("volume", "sum"),
        avg_intraday_volume=("volume", "mean"),
    )
    grouped["range_pct"] = ((grouped["high"] - grouped["low"]) / grouped["close"].replace(0.0, pd.NA)).fillna(0.0)
    grouped["volume_median_20"] = grouped["volume"].rolling(20, min_periods=1).median()
    grouped["range_median_20"] = grouped["range_pct"].rolling(20, min_periods=1).median()
    return grouped


def _active_days(
    history_context: pd.DataFrame,
    candidate_rows: list[dict[str, Any]],
    setup_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
) -> list[pd.Timestamp]:
    days: set[pd.Timestamp] = set()
    for day in history_context.index.tolist():
        days.add(pd.Timestamp(day).normalize())
    for row in candidate_rows:
        ts = _timestamp(row.get("time") or row.get("entry_candidate_time") or row.get("entry_time"))
        if ts is not None:
            days.add(ts.normalize())
    for row in setup_rows:
        ts = _timestamp(row.get("timestamp"))
        if ts is not None:
            days.add(ts.normalize())
    for row in trade_rows:
        ts = _timestamp(row.get("entry_time")) or _timestamp(row.get("exit_time"))
        if ts is not None:
            days.add(ts.normalize())
    return sorted(days)


def _make_lookup(rows: list[dict[str, Any]]) -> dict[tuple[str, str, str], list[dict[str, Any]]]:
    lookup: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ts = _timestamp(row.get("timestamp") or row.get("time") or row.get("entry_time"))
        if ts is None:
            continue
        key = (_date_text(ts), str(row.get("symbol", "")).upper(), str(row.get("side", "")).lower())
        row = dict(row)
        row["_timestamp"] = ts
        lookup[key].append(row)
    for bucket in lookup.values():
        bucket.sort(key=lambda row: row["_timestamp"])
    return lookup


def _select_setup_row(
    setup_lookup: dict[tuple[str, str, str], list[dict[str, Any]]],
    *,
    date_text: str,
    symbol: str,
    side: str,
    timestamp: pd.Timestamp,
) -> dict[str, Any]:
    rows = setup_lookup.get((date_text, symbol.upper(), side.lower()), [])
    if not rows:
        return {}
    exact = [row for row in rows if row["_timestamp"] == timestamp]
    if exact:
        return exact[0]
    prior = [row for row in rows if row["_timestamp"] <= timestamp]
    if prior:
        return prior[-1]
    return rows[0]


def _level_class(level_type: str) -> str:
    normalized = str(level_type or "").lower()
    if normalized in _SUPPORT_TYPES or "support" in normalized or normalized.endswith("_low"):
        return "support"
    if normalized in _RESISTANCE_TYPES or "resistance" in normalized or normalized.endswith("_high"):
        return "resistance"
    return "neutral"


def _prepare_level_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ts = _timestamp(row.get("timestamp") or row.get("last_touched") or row.get("first_seen"))
        if ts is None:
            continue
        grouped[str(row.get("symbol", "BTCUSDT")).upper()].append(
            {
                "timestamp": ts,
                "price": _to_float(row.get("price")),
                "type": str(row.get("type", "")),
                "class": _level_class(str(row.get("type", ""))),
                "touch_count": _to_float(row.get("touch_count")),
                "strength": _to_float(row.get("strength"), default=1.0),
                "timeframe_source": str(row.get("timeframe_source", "")),
            }
        )
    for values in grouped.values():
        values.sort(key=lambda item: item["timestamp"])
    return grouped


def _prepare_liquidity_rows(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        ts = _timestamp(row.get("timestamp"))
        if ts is None:
            continue
        grouped[str(row.get("symbol", "BTCUSDT")).upper()].append(
            {
                "timestamp": ts,
                "price": _to_float(row.get("price")),
                "type": str(row.get("type", "")),
                "side_implication": str(row.get("side_implication", "")),
                "source_timeframe": str(row.get("source_timeframe", "")),
                "confidence": _to_float(row.get("confidence")),
            }
        )
    for values in grouped.values():
        values.sort(key=lambda item: item["timestamp"])
    return grouped


def _nearest_structural_levels(
    level_rows: dict[str, list[dict[str, Any]]],
    *,
    timestamp: pd.Timestamp,
    symbol: str,
    price: float,
    side: str,
    atr_value: float,
) -> dict[str, Any]:
    lookback_start = timestamp - pd.Timedelta(days=5)
    levels: list[dict[str, Any]] = []
    for row in reversed(level_rows.get(symbol.upper(), [])):
        row_time = row["timestamp"]
        if row_time > timestamp:
            continue
        if row_time < lookback_start:
            break
        levels.append(row)
    support_levels = [row for row in levels if row["class"] == "support" and row["price"] <= price * 1.004]
    resistance_levels = [row for row in levels if row["class"] == "resistance" and row["price"] >= price * 0.996]
    support_levels.sort(key=lambda row: (abs(row["price"] - price), -row["strength"], -row["touch_count"]))
    resistance_levels.sort(key=lambda row: (abs(row["price"] - price), -row["strength"], -row["touch_count"]))
    support = support_levels[0] if support_levels else None
    resistance = resistance_levels[0] if resistance_levels else None
    support_distance_atr = abs(price - support["price"]) / atr_value if support and atr_value > 0 else None
    resistance_distance_atr = abs(resistance["price"] - price) / atr_value if resistance and atr_value > 0 else None
    near_support = bool(support and (support_distance_atr or 99.0) <= 1.35)
    near_resistance = bool(resistance and (resistance_distance_atr or 99.0) <= 1.35)
    zone_quality_inputs: list[float] = []
    for level, distance_atr in ((support, support_distance_atr), (resistance, resistance_distance_atr)):
        if level is None:
            continue
        zone_quality_inputs.append(
            _clamp(
                0.45 * _score_to_unit(level["strength"], 2.5)
                + 0.25 * _score_to_unit(level["touch_count"], 5.0)
                + 0.30 * (1.0 - _clamp((distance_atr or 3.0) / 2.0)),
            )
        )
    if side == "long":
        room = (resistance["price"] - price) if resistance else None
        overhead_risk = 1.0 - _clamp((room or 0.0) / max(atr_value * 4.0, 1e-9))
    else:
        room = (price - support["price"]) if support else None
        overhead_risk = 1.0 - _clamp((room or 0.0) / max(atr_value * 4.0, 1e-9))
    return {
        "support": support,
        "resistance": resistance,
        "near_support": near_support,
        "near_resistance": near_resistance,
        "support_to_resistance_room": round(room, 6) if room is not None else None,
        "resistance_overhead_risk": round(_clamp(overhead_risk), 6),
        "zone_quality_score": round(_mean(zone_quality_inputs), 6),
    }


def _liquidity_context(
    liquidity_rows: dict[str, list[dict[str, Any]]],
    *,
    timestamp: pd.Timestamp,
    symbol: str,
) -> dict[str, Any]:
    lookback_start = timestamp - pd.Timedelta(days=3)
    recent: list[dict[str, Any]] = []
    for row in reversed(liquidity_rows.get(symbol.upper(), [])):
        row_time = row["timestamp"]
        if row_time > timestamp:
            continue
        if row_time < lookback_start:
            break
        recent.append(row)
    if not recent:
        return {
            "breakout_level": None,
            "retest_level": None,
            "failed_breakout": False,
            "breakout_retest_hold": False,
            "breakout_score": 0.0,
            "retest_score": 0.0,
            "liquidity_reclaim_score": 0.0,
        }
    latest_breakout = next((row for row in reversed(recent) if row["type"] in {"retest_after_breakout", "retest_after_breakdown"}), None)
    latest_failed = next((row for row in reversed(recent) if row["type"] in {"failed_breakout", "failed_breakdown"}), None)
    latest_sweep = next((row for row in reversed(recent) if row["type"] in {"sweep_low", "sweep_high"}), None)
    breakout_score = 0.86 if latest_breakout else 0.28 if latest_sweep else 0.0
    retest_score = 0.80 if latest_breakout else 0.0
    reclaim_score = 0.92 if latest_sweep else 0.56 if latest_breakout else 0.16
    return {
        "breakout_level": latest_breakout["price"] if latest_breakout else None,
        "retest_level": latest_breakout["price"] if latest_breakout else None,
        "failed_breakout": latest_failed is not None,
        "breakout_retest_hold": latest_breakout is not None and latest_failed is None,
        "breakout_score": round(_clamp(breakout_score), 6),
        "retest_score": round(_clamp(retest_score), 6),
        "liquidity_reclaim_score": round(_clamp(reclaim_score), 6),
    }


def _volume_context_score(day: pd.Timestamp, history_context: pd.DataFrame) -> float:
    if history_context.empty or day not in history_context.index:
        return 0.5
    row = history_context.loc[day]
    volume = _to_float(row.get("volume"))
    median = _to_float(row.get("volume_median_20"), default=volume or 1.0)
    if median <= 0.0:
        return 0.5
    ratio = volume / median
    if 0.85 <= ratio <= 1.8:
        return round(_clamp(0.52 + (ratio - 0.85) * 0.25), 6)
    if ratio > 1.8:
        return round(_clamp(0.78 - min((ratio - 1.8) * 0.08, 0.24)), 6)
    return round(_clamp(0.32 + ratio * 0.26), 6)


def _daily_noise_context(day: pd.Timestamp, history_context: pd.DataFrame) -> tuple[float, bool]:
    if history_context.empty or day not in history_context.index:
        return 0.5, False
    row = history_context.loc[day]
    range_pct = _to_float(row.get("range_pct"))
    rolling_median = _to_float(row.get("range_median_20"), default=range_pct or 1.0)
    ratio = _safe_ratio(range_pct, rolling_median, default=1.0)
    compressed = ratio < 0.70
    chop_score = 0.70 if compressed else 0.55 if ratio < 0.95 else 0.40
    return round(_clamp(chop_score), 6), compressed


def _atr_tradability_score(stop_atr_fraction: float, stop_cost_multiple: float, tiny_stop_flag: bool) -> float:
    stop_atr_score = 1.0 - abs(stop_atr_fraction - 0.9) / 1.2
    cost_score = _clamp((stop_cost_multiple - 0.8) / 3.2)
    penalty = 0.28 if tiny_stop_flag else 0.0
    return round(_clamp(0.58 * stop_atr_score + 0.42 * cost_score - penalty), 6)


def _cost_realism_score(row: dict[str, Any], stop_cost_multiple: float) -> float:
    score = 0.18
    score += 0.16 if _to_bool(row.get("survives_low_cost") or row.get("cost_survival_low")) else 0.0
    score += 0.20 if _to_bool(row.get("survives_normal_cost") or row.get("cost_survival_normal")) else 0.0
    score += 0.16 if _to_bool(row.get("survives_high_cost") or row.get("cost_survival_high")) else 0.0
    score += 0.10 if _to_bool(row.get("survives_stress_cost")) else 0.0
    score += 0.12 * _clamp(stop_cost_multiple / 4.0)
    score -= min(_to_float(row.get("expected_cost_r")) / 4.0, 0.24)
    if _to_bool(row.get("cost_dominated_flag")) or _to_bool(row.get("cost_dominated_stop_flag")):
        score -= 0.24
    return round(_clamp(score), 6)


def _opportunity_label(score: float, *, tiny_wiggle_flag: bool, noise_chasing_flag: bool) -> str:
    if tiny_wiggle_flag or (noise_chasing_flag and score < 58.0):
        return "NO_OPPORTUNITY"
    if score >= 84.0:
        return "EXCEPTIONAL_COMPOUNDING_OPPORTUNITY"
    if score >= 72.0:
        return "STRONG_STRUCTURAL_HILL"
    if score >= 58.0:
        return "VALID_STRUCTURAL_OPPORTUNITY"
    if score >= 38.0:
        return "WEAK_OPPORTUNITY"
    return "NO_OPPORTUNITY"


def _build_candidate_row(
    row: dict[str, Any],
    *,
    setup_lookup: dict[tuple[str, str, str], list[dict[str, Any]]],
    level_rows: dict[str, list[dict[str, Any]]],
    liquidity_rows: dict[str, list[dict[str, Any]]],
    history_context: pd.DataFrame,
) -> dict[str, Any]:
    ts = _timestamp(row.get("time") or row.get("entry_candidate_time") or row.get("entry_time"))
    if ts is None:
        ts = pd.Timestamp("1970-01-01")
    symbol = str(row.get("symbol", "BTCUSDT")).upper()
    side = str(row.get("side", "long")).lower()
    day_text = _date_text(ts)
    setup_row = _select_setup_row(setup_lookup, date_text=day_text, symbol=symbol, side=side, timestamp=ts)
    price = _to_float(row.get("entry_candidate_price") or row.get("refined_entry_price") or row.get("original_entry_price"))
    atr_value = max(_to_float(row.get("atr_value"), default=0.0), 1e-9)
    stop_atr_fraction = _to_float(row.get("stop_atr_fraction") or row.get("refined_stop_atr_fraction"))
    stop_cost_multiple = _to_float(row.get("stop_cost_multiple") or row.get("refined_stop_cost_multiple"))
    structure_validity = _to_float(row.get("structure_validity_score"))
    setup_structure = _score_to_unit(_to_float(setup_row.get("structure_score")), 1.35)
    setup_liquidity = _score_to_unit(_to_float(setup_row.get("liquidity_score")), 1.0)
    setup_ema = _score_to_unit(_to_float(setup_row.get("ema_score")), 1.0)
    setup_htf = _score_to_unit(_to_float(setup_row.get("htf_confirmation_score")), 0.35)
    structural_hill_score = round(
        _clamp(
            0.42 * structure_validity
            + 0.20 * setup_structure
            + 0.14 * setup_liquidity
            + 0.12 * setup_ema
            + 0.12 * setup_htf,
        ),
        6,
    )
    level_context = _nearest_structural_levels(
        level_rows,
        timestamp=ts,
        symbol=symbol,
        price=price,
        side=side,
        atr_value=atr_value,
    )
    liquidity_context = _liquidity_context(liquidity_rows, timestamp=ts, symbol=symbol)
    volume_context_score = _volume_context_score(ts.normalize(), history_context)
    base_chop_score, compressed_day = _daily_noise_context(ts.normalize(), history_context)
    tiny_wiggle_flag = (
        _to_bool(row.get("tiny_stop_flag"))
        or _to_bool(row.get("unrealistic_stop_flag"))
        or _to_bool(row.get("noise_stop_flag"))
        or stop_atr_fraction < 0.25
        or stop_cost_multiple < 1.2
    )
    atr_tradability_score = _atr_tradability_score(stop_atr_fraction, stop_cost_multiple, tiny_wiggle_flag)
    cost_realism = _cost_realism_score(row, stop_cost_multiple)
    expected_r = _to_float(
        row.get("refined_net_r_after_fees_slippage")
        or row.get("refined_net_r_after_fees")
        or row.get("refined_gross_r")
        or row.get("trade_r_multiple")
        or row.get("original_gross_r")
    )
    room_to_target_score = round(
        _clamp(
            0.58 * _clamp(_to_float(row.get("net_reward_to_cost_ratio")) / 10.0)
            + 0.42 * (1.0 - _to_float(level_context.get("resistance_overhead_risk"))),
        ),
        6,
    )
    danger_score = round(
        _clamp(
            0.20
            + (0.18 if _to_bool(row.get("exhaustion_warning")) else 0.0)
            + (0.14 if _to_bool(row.get("macd_warning_flag")) else 0.0)
            + (0.10 if _to_bool(row.get("bb_warning_flag")) else 0.0)
            + (0.16 if _to_bool(row.get("cost_dominated_flag")) else 0.0)
            + (0.15 if _to_bool(liquidity_context.get("failed_breakout")) else 0.0)
            + (0.10 if level_context.get("near_resistance") and side == "long" else 0.0)
            + (0.10 if level_context.get("near_support") and side == "short" else 0.0),
        ),
        6,
    )
    chop_score = round(
        _clamp(
            0.45 * base_chop_score
            + (0.25 if _to_bool(row.get("choppy_warning")) else 0.0)
            + (0.14 if _to_bool(row.get("bb_compression")) else 0.0)
            + (0.12 if compressed_day else 0.0)
            + (0.08 if tiny_wiggle_flag else 0.0),
        ),
        6,
    )
    noise_chasing_flag = (
        tiny_wiggle_flag
        or chop_score > 0.60
        or (_to_float(row.get("recent_candle_noise")) > atr_value * 0.65 and atr_value > 0)
        or (_to_float(row.get("local_wick_noise")) > atr_value * 0.35 and atr_value > 0)
    )
    breakout_score = _to_float(liquidity_context["breakout_score"])
    retest_score = _to_float(liquidity_context["retest_score"])
    liquidity_reclaim_score = _to_float(liquidity_context["liquidity_reclaim_score"])
    sr_zone_score = round(
        _clamp(
            0.60 * _to_float(level_context["zone_quality_score"])
            + 0.20 * (1.0 if level_context["near_support"] or level_context["near_resistance"] else 0.0)
            + 0.20 * room_to_target_score,
        ),
        6,
    )
    pullback_score = round(
        _clamp(
            0.48 * _clamp(_to_float(row.get("pullback_quality_score")))
            + 0.24 * _clamp(_to_float(row.get("pullback_depth_atr")) / 2.0)
            + 0.28 * (1.0 if _to_bool(row.get("pullback_detected")) else 0.0),
        ),
        6,
    )
    ema_vwap_context_score = round(
        _clamp(
            0.52 * setup_ema
            + 0.24 * setup_htf
            + 0.24 * (1.0 if _to_bool(setup_row.get("htf_aligned")) or _to_bool(row.get("htf_aligned")) else 0.0),
        ),
        6,
    )
    runner_potential = round(
        _clamp(
            0.55 * (1.0 if _to_bool(row.get("runner_eligible_candidate")) else 0.0)
            + 0.45 * _clamp(expected_r / 8.0),
        ),
        6,
    )
    add_on_potential = round(
        _clamp(
            0.55 * (1.0 if _to_bool(row.get("add_on_research_candidate")) else 0.0)
            + 0.45 * structural_hill_score,
        ),
        6,
    )
    opportunity_unit = _clamp(
        (
            0.24 * structural_hill_score
            + 0.12 * sr_zone_score
            + 0.07 * breakout_score
            + 0.07 * retest_score
            + 0.08 * pullback_score
            + 0.07 * liquidity_reclaim_score
            + 0.09 * ema_vwap_context_score
            + 0.07 * volume_context_score
            + 0.09 * atr_tradability_score
            + 0.10 * room_to_target_score
            + 0.10 * cost_realism
        )
        - (0.08 * danger_score + 0.06 * chop_score)
    )
    opportunity_score = round(opportunity_unit * 100.0, 2)
    label = _opportunity_label(
        opportunity_score,
        tiny_wiggle_flag=tiny_wiggle_flag,
        noise_chasing_flag=noise_chasing_flag,
    )
    explanation = (
        str(row.get("explanation") or "").strip()
        or str(setup_row.get("explanation") or setup_row.get("entry_reason") or "").strip()
        or "Research-only routed candidate."
    )
    return {
        "date": day_text,
        "timestamp": ts.isoformat(),
        "symbol": symbol,
        "side": side,
        "opportunity_label": label,
        "opportunity_score": opportunity_score,
        "structural_hill_score": structural_hill_score,
        "sr_zone_score": sr_zone_score,
        "breakout_score": breakout_score,
        "retest_score": retest_score,
        "pullback_score": pullback_score,
        "liquidity_reclaim_score": liquidity_reclaim_score,
        "ema_vwap_context_score": ema_vwap_context_score,
        "volume_context_score": volume_context_score,
        "atr_tradability_score": atr_tradability_score,
        "room_to_target_score": room_to_target_score,
        "cost_realism_score": cost_realism,
        "expected_R_potential": round(expected_r, 6),
        "runner_potential": runner_potential,
        "add_on_potential": add_on_potential,
        "danger_score": danger_score,
        "chop_score": chop_score,
        "exhaustion_score": round(_clamp(danger_score * 0.85), 6),
        "best_archetype": str(row.get("archetype") or row.get("pullback_type") or "none"),
        "best_personality": str(row.get("personality") or row.get("personality_label") or "none"),
        "best_entry_style": str(row.get("entry_style") or row.get("runner_label") or "research_entry"),
        "participation_mode": str(row.get("participation_mode") or "REJECT_INVALID"),
        "suggested_research_risk_fraction": round(
            _to_float(row.get("suggested_research_risk_fraction")),
            6,
        ),
        "noise_chasing_flag": noise_chasing_flag,
        "tiny_wiggle_flag": tiny_wiggle_flag,
        "near_support": bool(level_context["near_support"]),
        "near_resistance": bool(level_context["near_resistance"]),
        "breakout_level": liquidity_context["breakout_level"],
        "retest_level": liquidity_context["retest_level"],
        "failed_breakout": bool(liquidity_context["failed_breakout"]),
        "breakout_retest_hold": bool(liquidity_context["breakout_retest_hold"]),
        "support_to_resistance_room": level_context["support_to_resistance_room"],
        "resistance_overhead_risk": level_context["resistance_overhead_risk"],
        "zone_quality_score": level_context["zone_quality_score"],
        "raw_reject_reason": str(row.get("reject_reason") or ""),
        "raw_wait_reason": str(row.get("wait_reason") or ""),
        "raw_reject_reasons": str(row.get("reject_reasons") or ""),
        "cost_dominated_flag": _to_bool(row.get("cost_dominated_flag")) or _to_bool(row.get("cost_dominated_stop_flag")),
        "runner_allowed_research_flag": _to_bool(row.get("runner_allowed_research_flag")) or _to_bool(row.get("runner_eligible_candidate")),
        "add_on_allowed_research_flag": _to_bool(row.get("add_on_allowed_research_flag")) or _to_bool(row.get("add_on_research_candidate")),
        "explanation": explanation,
    }


def _day_counts(rows: list[dict[str, Any]], time_fields: tuple[str, ...], *, symbol: str) -> dict[str, list[dict[str, Any]]]:
    bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if str(row.get("symbol", symbol)).upper() != symbol.upper():
            continue
        ts = None
        for field in time_fields:
            ts = _timestamp(row.get(field))
            if ts is not None:
                break
        if ts is None:
            continue
        bucket[_date_text(ts)].append(dict(row))
    return bucket


def _opened_setup_count(rows: list[dict[str, Any]]) -> int:
    count = 0
    for row in rows:
        decision = str(row.get("decision") or "").lower()
        accepted = _to_bool(row.get("accepted"))
        if decision == "opened" or accepted:
            count += 1
    return count


def _candidate_cooldown_blocks(rows: list[dict[str, Any]]) -> int:
    total = 0
    for row in rows:
        blob = " ".join(
            [
                str(row.get("raw_wait_reason") or ""),
                str(row.get("raw_reject_reason") or ""),
                str(row.get("raw_reject_reasons") or ""),
            ]
        ).lower()
        if "cooldown" in blob or "risk_block" in blob:
            total += 1
    return total


def _top_candidate_for_day(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {}
    return max(
        rows,
        key=lambda row: (
            _to_float(row.get("opportunity_score")),
            _to_float(row.get("expected_R_potential")),
            _to_float(row.get("structural_hill_score")),
        ),
    )


def _synthetic_no_opportunity_row(day: pd.Timestamp, symbol: str, history_context: pd.DataFrame) -> dict[str, Any]:
    chop_score, compressed_day = _daily_noise_context(day.normalize(), history_context)
    return {
        "date": _date_text(day),
        "timestamp": day.isoformat(),
        "symbol": symbol,
        "side": "flat",
        "opportunity_label": "NO_OPPORTUNITY",
        "opportunity_score": 0.0,
        "structural_hill_score": 0.0,
        "sr_zone_score": 0.0,
        "breakout_score": 0.0,
        "retest_score": 0.0,
        "pullback_score": 0.0,
        "liquidity_reclaim_score": 0.0,
        "ema_vwap_context_score": 0.0,
        "volume_context_score": _volume_context_score(day.normalize(), history_context),
        "atr_tradability_score": 0.0,
        "room_to_target_score": 0.0,
        "cost_realism_score": 0.0,
        "expected_R_potential": 0.0,
        "runner_potential": 0.0,
        "add_on_potential": 0.0,
        "danger_score": round(chop_score * 0.45, 6),
        "chop_score": chop_score,
        "exhaustion_score": 0.0,
        "best_archetype": "none",
        "best_personality": "none",
        "best_entry_style": "no_trade_day",
        "participation_mode": "REJECT_INVALID",
        "suggested_research_risk_fraction": 0.0,
        "noise_chasing_flag": compressed_day,
        "tiny_wiggle_flag": compressed_day,
        "near_support": False,
        "near_resistance": False,
        "breakout_level": None,
        "retest_level": None,
        "failed_breakout": False,
        "breakout_retest_hold": False,
        "support_to_resistance_room": None,
        "resistance_overhead_risk": 0.0,
        "zone_quality_score": 0.0,
        "raw_reject_reason": "",
        "raw_wait_reason": "",
        "raw_reject_reasons": "",
        "cost_dominated_flag": False,
        "runner_allowed_research_flag": False,
        "add_on_allowed_research_flag": False,
        "explanation": "No routed candidate achieved structural relevance on this active day.",
    }


def _audit_category(day_row: dict[str, Any]) -> str:
    actual_trade_count = _to_int(day_row.get("actual_trade_count"))
    participation_mode = str(day_row.get("participation_mode") or "")
    if actual_trade_count > 0:
        if participation_mode in {"DE_RISK_FAST_MANAGEMENT", "NO_ADD_ON_MANAGEMENT"}:
            return "VALID_DE_RISK_NOT_MISSED"
        if participation_mode == "PROBE_CANDIDATE":
            return "VALID_PROBE_NOT_MISSED"
    if _to_bool(day_row.get("tiny_wiggle_flag")) or _to_bool(day_row.get("noise_chasing_flag")):
        return "TINY_STOP_OR_NOISE"
    if _to_bool(day_row.get("cost_dominated_flag")) or _to_float(day_row.get("cost_realism_score")) < 0.55:
        return "COST_DOMINATED_NOT_TRADEABLE"
    if (
        _to_float(day_row.get("structural_hill_score")) < 0.62
        or _to_float(day_row.get("danger_score")) > 0.55
        or _to_float(day_row.get("chop_score")) > 0.60
        or _to_bool(day_row.get("failed_breakout"))
    ):
        return "STRUCTURE_WEAK_OR_BROKEN"
    if _to_int(day_row.get("cooldown_blocked_count")) > 0:
        return "COOLDOWN_OR_RISK_BLOCKED"
    if participation_mode == "PROBE_CANDIDATE":
        return "VALID_PROBE_NOT_MISSED"
    if participation_mode in {"DE_RISK_FAST_MANAGEMENT", "NO_ADD_ON_MANAGEMENT"}:
        return "VALID_DE_RISK_NOT_MISSED"
    if _to_bool(day_row.get("missed_high_R_opportunity_flag")):
        return "TRUE_MISSED_HIGH_R_OPPORTUNITY"
    if _to_float(day_row.get("expected_R_potential")) >= 4.0:
        return "THEORETICAL_HIGH_R_ONLY"
    return "INSUFFICIENT_EVIDENCE"


def _actual_trade_backfill(
    day_row: dict[str, Any],
    *,
    setup_day_rows: list[dict[str, Any]],
    entry_trade_rows: list[dict[str, Any]],
    exit_trade_rows: list[dict[str, Any]],
) -> None:
    if not entry_trade_rows and not setup_day_rows:
        return
    best_setup_score = max(
        [_to_float(row.get("total_score") or row.get("score")) for row in setup_day_rows],
        default=0.0,
    )
    best_trade_r = max(
        [_to_float(row.get("r_multiple")) for row in [*entry_trade_rows, *exit_trade_rows] if str(row.get("r_multiple", "")).strip() != ""],
        default=0.0,
    )
    best_entry_score = max(
        [_to_float(row.get("entry_score")) for row in entry_trade_rows if str(row.get("entry_score", "")).strip() != ""],
        default=0.0,
    )
    setup_quality = max(_score_to_unit(best_setup_score, 4.5), _score_to_unit(best_entry_score, 4.5))
    trade_quality = max(setup_quality, _clamp(best_trade_r / 5.0))
    if day_row.get("opportunity_label") == "NO_OPPORTUNITY" or _to_float(day_row.get("opportunity_score")) < 58.0:
        opportunity_score = max(_to_float(day_row.get("opportunity_score")), 58.0 + 24.0 * trade_quality)
        day_row["opportunity_score"] = round(opportunity_score, 2)
        if best_trade_r >= 4.0 or opportunity_score >= 76.0:
            day_row["opportunity_label"] = "STRONG_STRUCTURAL_HILL"
        else:
            day_row["opportunity_label"] = "VALID_STRUCTURAL_OPPORTUNITY"
    day_row["structural_hill_score"] = round(max(_to_float(day_row.get("structural_hill_score")), 0.56 + 0.26 * setup_quality), 6)
    day_row["atr_tradability_score"] = round(max(_to_float(day_row.get("atr_tradability_score")), 0.55), 6)
    day_row["cost_realism_score"] = round(max(_to_float(day_row.get("cost_realism_score")), 0.55), 6)
    day_row["room_to_target_score"] = round(max(_to_float(day_row.get("room_to_target_score")), 0.50 + 0.18 * trade_quality), 6)
    day_row["expected_R_potential"] = round(max(_to_float(day_row.get("expected_R_potential")), best_trade_r, 2.5 + 2.5 * trade_quality), 6)
    explanation = str(day_row.get("explanation") or "").strip()
    trade_note = "actual structural trade(s) opened on this day"
    if trade_note not in explanation.lower():
        day_row["explanation"] = (
            f"{explanation} "
            f"Daily backfill: actual structural trade(s) opened on this day, so the opportunity definition treats it as executable structure."
        ).strip()


def _build_daily_rows(
    *,
    symbol: str,
    active_days: list[pd.Timestamp],
    history_context: pd.DataFrame,
    candidate_rows: list[dict[str, Any]],
    setup_rows: list[dict[str, Any]],
    trade_rows: list[dict[str, Any]],
    cooldown_rows: list[dict[str, Any]],
    pyramiding_rows: list[dict[str, Any]],
    level_rows: list[dict[str, Any]],
    liquidity_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    candidate_by_day = _day_counts(candidate_rows, ("timestamp", "time"), symbol=symbol)
    setup_by_day = _day_counts(setup_rows, ("timestamp",), symbol=symbol)
    trade_entry_by_day = _day_counts(trade_rows, ("entry_time",), symbol=symbol)
    trade_exit_by_day = _day_counts(trade_rows, ("exit_time", "entry_time"), symbol=symbol)
    cooldown_by_day = _day_counts(cooldown_rows, ("timestamp",), symbol=symbol)
    pyramiding_by_day = _day_counts(pyramiding_rows, ("timestamp",), symbol=symbol)
    level_by_day = _day_counts(level_rows, ("timestamp", "last_touched", "first_seen"), symbol=symbol)
    liquidity_by_day = _day_counts(liquidity_rows, ("timestamp",), symbol=symbol)

    rows: list[dict[str, Any]] = []
    valid_labels = {"VALID_STRUCTURAL_OPPORTUNITY", "STRONG_STRUCTURAL_HILL", "EXCEPTIONAL_COMPOUNDING_OPPORTUNITY"}

    for day in active_days:
        day_key = _date_text(day)
        top_candidate = _top_candidate_for_day(candidate_by_day.get(day_key, []))
        if not top_candidate:
            top_candidate = _synthetic_no_opportunity_row(day, symbol, history_context)
        day_row = dict(top_candidate)
        setup_day_rows = setup_by_day.get(day_key, [])
        entry_trade_rows = trade_entry_by_day.get(day_key, [])
        exit_trade_rows = trade_exit_by_day.get(day_key, [])
        candidate_day_rows = candidate_by_day.get(day_key, [])
        cooldown_day_rows = cooldown_by_day.get(day_key, [])
        pyramiding_day_rows = pyramiding_by_day.get(day_key, [])
        actual_trade_count = len(entry_trade_rows)
        opened_setup_count = _opened_setup_count(setup_day_rows)
        qualified_setup_count = sum(1 for row in setup_day_rows if _to_bool(row.get("accepted")))
        _actual_trade_backfill(
            day_row,
            setup_day_rows=setup_day_rows,
            entry_trade_rows=entry_trade_rows,
            exit_trade_rows=exit_trade_rows,
        )
        day_pnl_values = [_to_float(row.get("pnl")) for row in exit_trade_rows]
        day_r_values = [_to_float(row.get("r_multiple")) for row in exit_trade_rows if str(row.get("r_multiple", "")).strip() != ""]
        wins = sum(1 for value in day_pnl_values if value > 0.0)
        participation_mode = str(day_row.get("participation_mode") or "")
        valid_or_strong = day_row.get("opportunity_label") in valid_labels
        day_row.update(
            {
                "actual_trade_count": actual_trade_count,
                "setup_candidate_count": len(setup_day_rows),
                "qualified_setup_count": qualified_setup_count,
                "routed_candidate_count": len(candidate_day_rows),
                "opened_setup_count": opened_setup_count,
                "cooldown_blocked_count": _candidate_cooldown_blocks(candidate_day_rows),
                "level_count": len(level_by_day.get(day_key, [])),
                "liquidity_event_count": len(liquidity_by_day.get(day_key, [])),
                "pyramiding_event_count": sum(1 for row in pyramiding_day_rows if str(row.get("event_type") or "").lower() != "profit_lock"),
                "profit_lock_count": sum(1 for row in pyramiding_day_rows if str(row.get("event_type") or "").lower() == "profit_lock"),
                "cooldown_event_count": len(cooldown_day_rows),
                "day_total_pnl": round(sum(day_pnl_values), 6),
                "day_total_r": round(sum(day_r_values), 6),
                "day_avg_r": round(_mean(day_r_values), 6),
                "day_win_rate": round(_safe_ratio(wins, len(exit_trade_rows), 0.0), 6),
                "participation_mode_distribution_for_day": json.dumps(Counter(row.get("participation_mode") for row in candidate_day_rows)),
            }
        )
        day_row["missed_high_R_opportunity_flag"] = (
            _to_float(day_row.get("expected_R_potential")) >= 4.0
            and _to_float(day_row.get("structural_hill_score")) >= 0.62
            and _to_float(day_row.get("cost_realism_score")) >= 0.55
            and _to_float(day_row.get("atr_tradability_score")) >= 0.50
            and _to_float(day_row.get("danger_score")) <= 0.55
            and _to_float(day_row.get("chop_score")) <= 0.60
            and not _to_bool(day_row.get("tiny_wiggle_flag"))
            and not _to_bool(day_row.get("noise_chasing_flag"))
            and participation_mode in {"WAIT_FOR_CONFIRMATION", "REJECT_INVALID"}
            and actual_trade_count == 0
        )
        day_row["high_R_probe_day_flag"] = (
            _to_float(day_row.get("expected_R_potential")) >= 4.0
            and _to_float(day_row.get("structural_hill_score")) >= 0.62
            and _to_float(day_row.get("cost_realism_score")) >= 0.50
            and _to_float(day_row.get("atr_tradability_score")) >= 0.45
            and not _to_bool(day_row.get("tiny_wiggle_flag"))
            and not _to_bool(day_row.get("noise_chasing_flag"))
            and participation_mode == "PROBE_CANDIDATE"
            and actual_trade_count == 0
        )
        day_row["too_tight_day_flag"] = (
            valid_or_strong
            and actual_trade_count == 0
            and opened_setup_count == 0
            and not _to_bool(day_row.get("tiny_wiggle_flag"))
            and not _to_bool(day_row.get("noise_chasing_flag"))
            and _to_float(day_row.get("cost_realism_score")) >= 0.45
            and _to_float(day_row.get("atr_tradability_score")) >= 0.45
            and participation_mode in {"WAIT_FOR_CONFIRMATION", "REJECT_INVALID"}
        )
        day_row["missed_valid_opportunity_flag"] = (
            valid_or_strong
            and actual_trade_count == 0
            and opened_setup_count == 0
            and participation_mode in {"WAIT_FOR_CONFIRMATION", "REJECT_INVALID"}
            and not _to_bool(day_row.get("tiny_wiggle_flag"))
        )
        day_row["missed_high_r_audit_category"] = _audit_category(day_row)
        rows.append(day_row)
    return rows


def _actual_trade_frequency_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    trade_counts = [_to_int(row.get("actual_trade_count")) for row in rows]
    actual_trade_days = sum(1 for count in trade_counts if count > 0)
    active_trade_counts = [count for count in trade_counts if count > 0]
    return {
        "actual_trade_count": int(sum(trade_counts)),
        "actual_trade_days": actual_trade_days,
        "zero_trade_days": len(rows) - actual_trade_days,
        "average_actual_trades_per_day": round(_mean([float(count) for count in trade_counts]), 6),
        "average_actual_trades_per_active_day": round(_mean([float(count) for count in active_trade_counts]), 6),
        "max_actual_trades_on_one_day": max(trade_counts) if trade_counts else 0,
        "setup_candidate_days": sum(1 for row in rows if _to_int(row.get("setup_candidate_count")) > 0),
        "routed_candidate_days": sum(1 for row in rows if _to_int(row.get("routed_candidate_count")) > 0),
        "opened_setup_days": sum(1 for row in rows if _to_int(row.get("opened_setup_count")) > 0),
    }


def _confusion_matrix(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_mode: dict[str, dict[str, int]] = {}
    for mode in _PARTICIPATION_MODES:
        by_mode[mode] = {label: 0 for label in _OPPORTUNITY_LABELS}
    by_label_trade_presence: dict[str, dict[str, int]] = {
        label: {"trade_day": 0, "no_trade_day": 0} for label in _OPPORTUNITY_LABELS
    }
    high_r_categories = {category: 0 for category in _MISSED_HIGH_R_CATEGORIES}
    for row in rows:
        mode = str(row.get("participation_mode") or "REJECT_INVALID")
        label = str(row.get("opportunity_label") or "NO_OPPORTUNITY")
        if mode not in by_mode:
            by_mode[mode] = {name: 0 for name in _OPPORTUNITY_LABELS}
        if label not in by_mode[mode]:
            by_mode[mode][label] = 0
        by_mode[mode][label] += 1
        presence_key = "trade_day" if _to_int(row.get("actual_trade_count")) > 0 else "no_trade_day"
        by_label_trade_presence.setdefault(label, {"trade_day": 0, "no_trade_day": 0})
        by_label_trade_presence[label][presence_key] += 1
        category = str(row.get("missed_high_r_audit_category") or "INSUFFICIENT_EVIDENCE")
        high_r_categories.setdefault(category, 0)
        high_r_categories[category] += 1
    return {
        "by_participation_mode": by_mode,
        "by_opportunity_label_trade_presence": by_label_trade_presence,
        "high_r_audit_categories": high_r_categories,
    }


def _sensitivity(rows: list[dict[str, Any]]) -> dict[str, Any]:
    scenarios = {
        "broad": {"structural": 0.58, "cost": 0.50, "atr": 0.45, "danger": 0.60, "chop": 0.65},
        "baseline": {"structural": 0.62, "cost": 0.55, "atr": 0.50, "danger": 0.55, "chop": 0.60},
        "strict": {"structural": 0.68, "cost": 0.60, "atr": 0.55, "danger": 0.50, "chop": 0.55},
    }
    payload: dict[str, Any] = {}
    for name, thresholds in scenarios.items():
        missed = 0
        too_tight = 0
        for row in rows:
            base_gate = (
                _to_float(row.get("expected_R_potential")) >= 4.0
                and _to_float(row.get("structural_hill_score")) >= thresholds["structural"]
                and _to_float(row.get("cost_realism_score")) >= thresholds["cost"]
                and _to_float(row.get("atr_tradability_score")) >= thresholds["atr"]
                and _to_float(row.get("danger_score")) <= thresholds["danger"]
                and _to_float(row.get("chop_score")) <= thresholds["chop"]
                and not _to_bool(row.get("tiny_wiggle_flag"))
                and not _to_bool(row.get("noise_chasing_flag"))
                and _to_int(row.get("actual_trade_count")) == 0
            )
            if base_gate and str(row.get("participation_mode")) in {"WAIT_FOR_CONFIRMATION", "REJECT_INVALID"}:
                missed += 1
            if (
                row.get("opportunity_label") in {"VALID_STRUCTURAL_OPPORTUNITY", "STRONG_STRUCTURAL_HILL", "EXCEPTIONAL_COMPOUNDING_OPPORTUNITY"}
                and _to_int(row.get("actual_trade_count")) == 0
                and _to_int(row.get("opened_setup_count")) == 0
                and _to_float(row.get("cost_realism_score")) >= max(0.45, thresholds["cost"] - 0.05)
                and _to_float(row.get("atr_tradability_score")) >= max(0.45, thresholds["atr"] - 0.05)
                and not _to_bool(row.get("tiny_wiggle_flag"))
                and not _to_bool(row.get("noise_chasing_flag"))
                and str(row.get("participation_mode")) in {"WAIT_FOR_CONFIRMATION", "REJECT_INVALID"}
            ):
                too_tight += 1
        payload[name] = {
            "thresholds": thresholds,
            "missed_high_r_count": missed,
            "too_tight_count": too_tight,
        }
    return payload


def _recommended_patch() -> dict[str, Any]:
    return {
        "stage_name": "daily_opportunity_definition_refinement_001",
        "research_only": True,
        "changes": {
            "missed_high_r_definition": {
                "expected_R_potential_gte": 4.0,
                "structural_hill_score_gte": 0.62,
                "cost_realism_score_gte": 0.55,
                "atr_tradability_score_gte": 0.50,
                "danger_score_lte": 0.55,
                "chop_score_lte": 0.60,
                "tiny_wiggle_flag": False,
                "noise_chasing_flag": False,
                "participation_modes": ["WAIT_FOR_CONFIRMATION", "REJECT_INVALID"],
                "actual_trade_count": 0,
            },
            "too_tight_definition": {
                "valid_or_strong_opportunity": True,
                "actual_trade_count": 0,
                "opened_setup_count": 0,
                "tiny_wiggle_flag": False,
                "noise_chasing_flag": False,
                "cost_realism_score_gte": 0.45,
                "atr_tradability_score_gte": 0.45,
                "participation_modes": ["WAIT_FOR_CONFIRMATION", "REJECT_INVALID"],
            },
            "high_r_probe_day_rule": {
                "participation_mode": "PROBE_CANDIDATE",
                "count_as_missed_high_r": False,
                "tracked_separately": True,
            },
        },
        "diagnostic_only": True,
        "runtime_behavior_changed": False,
        "strategy_behavior_changed": False,
    }


def _summary(
    rows: list[dict[str, Any]],
    *,
    candidate_rows: list[dict[str, Any]],
    source_files: list[str],
    previous_summary: dict[str, Any],
) -> dict[str, Any]:
    valid_labels = {"VALID_STRUCTURAL_OPPORTUNITY", "STRONG_STRUCTURAL_HILL", "EXCEPTIONAL_COMPOUNDING_OPPORTUNITY"}
    strong_labels = {"STRONG_STRUCTURAL_HILL", "EXCEPTIONAL_COMPOUNDING_OPPORTUNITY"}
    participation_counts = Counter(str(row.get("participation_mode") or "REJECT_INVALID") for row in rows)
    valid_days = [row for row in rows if row.get("opportunity_label") in valid_labels]
    strong_days = [row for row in rows if row.get("opportunity_label") in strong_labels]
    no_opportunity_days = [row for row in rows if row.get("opportunity_label") == "NO_OPPORTUNITY"]
    too_tight_days = [row for row in rows if _to_bool(row.get("too_tight_day_flag"))]
    refined_missed_high_r = [row for row in rows if _to_bool(row.get("missed_high_R_opportunity_flag"))]
    high_r_probe_days = [row for row in rows if _to_bool(row.get("high_R_probe_day_flag"))]
    noise_avoided_days = [
        row for row in rows
        if _to_bool(row.get("noise_chasing_flag")) and str(row.get("participation_mode")) in {"REJECT_INVALID", "WAIT_FOR_CONFIRMATION"}
    ]
    frequency = _actual_trade_frequency_summary(rows)
    top_archetypes = Counter(
        str(row.get("best_archetype"))
        for row in valid_days
        if str(row.get("best_archetype") or "").lower() not in {"", "none"}
    ).most_common(5)
    old_missed_high_r = _to_int(previous_summary.get("missed_high_R_opportunity_count"))
    old_too_tight = _to_int(previous_summary.get("too_tight_day_count"))
    return {
        "stage_name": "Daily Structural Opportunity Definition Refinement 001",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "diagnostic_only": True,
        "real_money_allowed": False,
        "full_history_started": False,
        "stress_windows_started": False,
        "monte_carlo_started": False,
        "live_behavior_changed": False,
        "paper_behavior_changed": False,
        "strategy_behavior_changed": False,
        "allocator_behavior_changed": False,
        "risk_behavior_changed": False,
        "sizing_behavior_changed": False,
        "entry_behavior_changed": False,
        "exit_behavior_changed": False,
        "config_settings_changed": False,
        "classification": "definition_refined_research_only",
        "days_analyzed": len(rows),
        "valid_opportunity_days": len(valid_days),
        "strong_structural_hill_days": len(strong_days),
        "no_opportunity_days": len(no_opportunity_days),
        "too_tight_day_count": len(too_tight_days),
        "missed_valid_opportunity_count": sum(1 for row in rows if _to_bool(row.get("missed_valid_opportunity_flag"))),
        "missed_high_R_opportunity_count": len(refined_missed_high_r),
        "high_R_probe_day_count": len(high_r_probe_days),
        "noise_chasing_avoided_count": len(noise_avoided_days),
        "full_size_count": participation_counts.get("FULL_SIZE_CANDIDATE", 0),
        "reduced_size_count": participation_counts.get("REDUCED_SIZE_CANDIDATE", 0),
        "probe_count": participation_counts.get("PROBE_CANDIDATE", 0),
        "reject_invalid_count": participation_counts.get("REJECT_INVALID", 0),
        "wait_for_confirmation_count": participation_counts.get("WAIT_FOR_CONFIRMATION", 0),
        "actual_trade_frequency": frequency,
        "candidate_row_count": len(candidate_rows),
        "old_daily_opportunity_baseline": {
            "missed_high_R_opportunity_count": old_missed_high_r,
            "too_tight_day_count": old_too_tight,
        },
        "delta_vs_previous_daily_opportunity": {
            "missed_high_r_delta": len(refined_missed_high_r) - old_missed_high_r,
            "too_tight_delta": len(too_tight_days) - old_too_tight,
        },
        "best_opportunity_archetypes": [{"archetype": label, "count": count} for label, count in top_archetypes],
        "top_opportunity_mean_score": round(_mean([_to_float(row.get("opportunity_score")) for row in rows]), 6),
        "top_opportunity_median_score": round(_median([_to_float(row.get("opportunity_score")) for row in rows]), 6),
        "source_files": source_files,
        "soft_evidence_only": {"macd_bollinger": True},
    }


def _diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    missed_high_r_rows = [row for row in rows if _to_float(row.get("expected_R_potential")) >= 4.0]
    too_tight_rows = [row for row in rows if _to_bool(row.get("too_tight_day_flag"))]
    probe_rows = [row for row in rows if str(row.get("participation_mode")) == "PROBE_CANDIDATE"]
    reject_rows = [row for row in rows if str(row.get("participation_mode")) == "REJECT_INVALID"]
    return {
        "missed_high_r_audit_rows": missed_high_r_rows,
        "too_tight_rows": too_tight_rows,
        "probe_rows": probe_rows,
        "reject_rows": reject_rows,
        "actual_trade_frequency_rows": [
            {
                "date": row.get("date"),
                "actual_trade_count": row.get("actual_trade_count"),
                "setup_candidate_count": row.get("setup_candidate_count"),
                "qualified_setup_count": row.get("qualified_setup_count"),
                "routed_candidate_count": row.get("routed_candidate_count"),
                "opened_setup_count": row.get("opened_setup_count"),
                "cooldown_blocked_count": row.get("cooldown_blocked_count"),
                "pyramiding_event_count": row.get("pyramiding_event_count"),
                "profit_lock_count": row.get("profit_lock_count"),
                "cooldown_event_count": row.get("cooldown_event_count"),
                "day_total_pnl": row.get("day_total_pnl"),
                "day_total_r": row.get("day_total_r"),
                "day_avg_r": row.get("day_avg_r"),
                "day_win_rate": row.get("day_win_rate"),
            }
            for row in rows
        ],
        "confusion_matrix": _confusion_matrix(rows),
        "sensitivity": _sensitivity(rows),
        "noise_chasing_avoided_count": sum(
            1
            for row in rows
            if _to_bool(row.get("noise_chasing_flag")) and str(row.get("participation_mode")) in {"REJECT_INVALID", "WAIT_FOR_CONFIRMATION"}
        ),
        "high_r_day_count": sum(1 for row in rows if _to_float(row.get("expected_R_potential")) >= 4.0),
    }


def _report_markdown(
    summary: dict[str, Any],
    diagnostics: dict[str, Any],
    recommendation: dict[str, Any],
) -> str:
    frequency = summary["actual_trade_frequency"]
    confusion = diagnostics["confusion_matrix"]["high_r_audit_categories"]
    lines = [
        "# Daily Opportunity Definition Refinement 001",
        "",
        f"Classification: `{summary['classification']}`",
        "",
        "## Why This Exists",
        "",
        "The previous Daily Structural Opportunity layer overstated missed high-R days because it treated routed research candidates as if they were actual trade opportunities. This refinement rewrites the audit around true day-level activity: actual trades, setup formation, routed candidates, probe days, and explicit noise rejection.",
        "",
        "## Coverage",
        "",
        f"- days analyzed: `{summary['days_analyzed']}`",
        f"- valid opportunity days: `{summary['valid_opportunity_days']}`",
        f"- strong structural hill days: `{summary['strong_structural_hill_days']}`",
        f"- no-opportunity days: `{summary['no_opportunity_days']}`",
        "",
        "## Actual Trading Activity",
        "",
        f"- actual trades: `{frequency['actual_trade_count']}`",
        f"- actual trade days: `{frequency['actual_trade_days']}`",
        f"- zero-trade days: `{frequency['zero_trade_days']}`",
        f"- average actual trades per day: `{frequency['average_actual_trades_per_day']}`",
        f"- average actual trades per active day: `{frequency['average_actual_trades_per_active_day']}`",
        f"- max actual trades on one day: `{frequency['max_actual_trades_on_one_day']}`",
        "",
        "## Refined Opportunity Truth",
        "",
        f"- refined missed high-R opportunities: `{summary['missed_high_R_opportunity_count']}`",
        f"- high-R probe days: `{summary['high_R_probe_day_count']}`",
        f"- too-tight days: `{summary['too_tight_day_count']}`",
        f"- noise avoided days: `{summary['noise_chasing_avoided_count']}`",
        "",
        "## Delta Vs Previous Daily Layer",
        "",
        f"- previous missed high-R count: `{summary['old_daily_opportunity_baseline']['missed_high_R_opportunity_count']}`",
        f"- refined missed high-R count: `{summary['missed_high_R_opportunity_count']}`",
        f"- missed high-R delta: `{summary['delta_vs_previous_daily_opportunity']['missed_high_r_delta']}`",
        f"- previous too-tight count: `{summary['old_daily_opportunity_baseline']['too_tight_day_count']}`",
        f"- refined too-tight count: `{summary['too_tight_day_count']}`",
        "",
        "## High-R Audit Categories",
        "",
        *[f"- {category}: `{count}`" for category, count in confusion.items()],
        "",
        "## Recommendation",
        "",
        f"- next step: `{recommendation['next_step']}`",
        f"- current best insight: {recommendation['current_best_insight']}",
        "",
        "This remains research-only. No live, paper, allocator, risk, sizing, entry, exit, threshold, or config behavior was changed.",
    ]
    return "\n".join(lines) + "\n"


def _recommendation(summary: dict[str, Any], project_direction_summary: dict[str, Any]) -> dict[str, Any]:
    next_step = "continue_definition_refinement_and_shadow_review"
    if summary["missed_high_R_opportunity_count"] <= 3 and summary["too_tight_day_count"] <= 6:
        next_step = "ready_for_next_fast_review_on_definition_only"
    return {
        "classification": summary["classification"],
        "next_step": next_step,
        "current_best_insight": project_direction_summary.get(
            "current_best_insight",
            "Daily structural opportunity should lead; pullback logic remains downstream and research-only.",
        ),
        "hard_stops": [
            "no_full_history_validation",
            "no_stress_windows",
            "no_monte_carlo",
            "no_live_or_paper_runtime_change",
            "no_real_money_enablement",
        ],
    }


def write_daily_structural_opportunity(config: DailyStructuralOpportunityConfig) -> dict[str, Path]:
    paths = _artifact_paths(config)
    settings = _read_json(paths["settings"], {})
    symbol = str(settings.get("symbol", "BTCUSDT")).upper()
    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    trade_rows = _read_csv_rows(paths["trades"])
    cooldown_rows = _read_csv_rows(paths["cooldown_log"])
    pyramiding_rows = _read_csv_rows(paths["pyramiding_log"])
    routed_rows = _read_csv_rows(paths["routed_candidates"])
    project_direction_summary = _read_json(paths["project_direction_summary"], {})
    previous_summary = _read_json(paths["legacy_summary"], {})
    source_history_path = _resolve_source_history_path(config, settings)
    history_context = _load_history_daily_context(source_history_path)
    setup_lookup = _make_lookup(setup_rows)
    prepared_levels = _prepare_level_rows(level_rows)
    prepared_liquidity = _prepare_liquidity_rows(liquidity_rows)

    candidate_rows = [
        _build_candidate_row(
            row,
            setup_lookup=setup_lookup,
            level_rows=prepared_levels,
            liquidity_rows=prepared_liquidity,
            history_context=history_context,
        )
        for row in routed_rows
    ]
    active_days = _active_days(history_context, routed_rows, setup_rows, trade_rows)
    daily_rows = _build_daily_rows(
        symbol=symbol,
        active_days=active_days,
        history_context=history_context,
        candidate_rows=candidate_rows,
        setup_rows=setup_rows,
        trade_rows=trade_rows,
        cooldown_rows=cooldown_rows,
        pyramiding_rows=pyramiding_rows,
        level_rows=level_rows,
        liquidity_rows=liquidity_rows,
    )

    source_files = [
        str(paths["setup_log"]),
        str(paths["level_log"]),
        str(paths["liquidity_events"]),
        str(paths["trades"]),
        str(paths["cooldown_log"]),
        str(paths["pyramiding_log"]),
        str(paths["equity"]),
        str(paths["profit_vault"]),
        str(paths["routed_candidates"]),
    ]
    if source_history_path is not None:
        source_files.append(str(source_history_path))

    summary = _summary(
        daily_rows,
        candidate_rows=candidate_rows,
        source_files=source_files,
        previous_summary=previous_summary,
    )
    diagnostics = _diagnostics(daily_rows)
    recommendation = _recommendation(summary, project_direction_summary)
    report_markdown = _report_markdown(summary, diagnostics, recommendation)
    recommended_patch = _recommended_patch()

    output_root = config.output_root
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)

    status_payload = {
        "state": "complete",
        "classification": summary["classification"],
        "resolved_at_utc": summary["resolved_at_utc"],
        "research_only": True,
        "diagnostic_only": True,
        "real_money_allowed": False,
    }
    _write_json(output_root / "status.json", status_payload)
    _write_json(output_root / "definition_refinement_summary.json", summary)
    _write_markdown(output_root / "definition_refinement_report.md", report_markdown)

    _write_csv(diagnostics_root / "missed_high_r_audit.csv", diagnostics["missed_high_r_audit_rows"])
    _write_csv(diagnostics_root / "too_tight_audit.csv", diagnostics["too_tight_rows"])
    _write_csv(diagnostics_root / "probe_candidate_audit.csv", diagnostics["probe_rows"])
    _write_csv(diagnostics_root / "reject_invalid_audit.csv", diagnostics["reject_rows"])
    _write_csv(diagnostics_root / "actual_trade_frequency_by_day.csv", diagnostics["actual_trade_frequency_rows"])
    _write_json(diagnostics_root / "opportunity_label_confusion_matrix.json", diagnostics["confusion_matrix"])
    _write_json(diagnostics_root / "opportunity_definition_sensitivity.json", diagnostics["sensitivity"])
    _write_json(diagnostics_root / "recommended_definition_patch.json", recommended_patch)

    # Compatibility artifacts for the dashboard shell and existing read-only telemetry.
    _write_csv(diagnostics_root / "top_opportunity_by_day.csv", daily_rows)
    _write_csv(diagnostics_root / "participation_routed_daily_candidates.csv", candidate_rows)
    _write_json(
        diagnostics_root / "participation_mode_distribution.json",
        {
            "total_days": len(daily_rows),
            "counts": Counter(str(row.get("participation_mode") or "REJECT_INVALID") for row in daily_rows),
        },
    )
    _write_json(
        diagnostics_root / "sr_zone_opportunity_report.json",
        {
            "breakout_retest_hold_days": sum(1 for row in daily_rows if _to_bool(row.get("breakout_retest_hold"))),
            "failed_breakout_days": sum(1 for row in daily_rows if _to_bool(row.get("failed_breakout"))),
            "average_zone_quality_score": round(_mean([_to_float(row.get("zone_quality_score")) for row in daily_rows]), 6),
        },
    )
    _write_json(
        diagnostics_root / "breakout_retest_report.json",
        {
            "breakout_supportive_days": sum(1 for row in daily_rows if _to_float(row.get("breakout_score")) >= 0.65),
            "retest_supportive_days": sum(1 for row in daily_rows if _to_float(row.get("retest_score")) >= 0.65),
            "liquidity_reclaim_days": sum(1 for row in daily_rows if _to_float(row.get("liquidity_reclaim_score")) >= 0.70),
        },
    )
    _write_json(
        diagnostics_root / "missed_daily_opportunity_report.json",
        {
            "missed_valid_opportunities": [row for row in daily_rows if _to_bool(row.get("missed_valid_opportunity_flag"))],
            "missed_high_r_opportunities": [row for row in daily_rows if _to_bool(row.get("missed_high_R_opportunity_flag"))],
            "high_r_probe_days": [row for row in daily_rows if _to_bool(row.get("high_R_probe_day_flag"))],
        },
    )
    _write_json(
        diagnostics_root / "too_tight_inactivity_report.json",
        {
            "too_tight_day_count": summary["too_tight_day_count"],
            "too_tight_days": diagnostics["too_tight_rows"],
        },
    )
    _write_json(
        diagnostics_root / "noise_chasing_guard_report.json",
        {
            "noise_chasing_avoided_count": diagnostics["noise_chasing_avoided_count"],
            "noise_chasing_days": [row for row in daily_rows if _to_bool(row.get("noise_chasing_flag"))],
        },
    )
    _write_json(
        diagnostics_root / "high_r_opportunity_report.json",
        {
            "high_r_day_count": diagnostics["high_r_day_count"],
            "missed_high_r_count": summary["missed_high_R_opportunity_count"],
            "high_r_probe_day_count": summary["high_R_probe_day_count"],
        },
    )
    _write_json(reports_root / "next_research_recommendation.json", recommendation)
    _write_markdown(
        reports_root / "next_research_recommendation.md",
        "\n".join(
            [
                "# Next Research Recommendation",
                "",
                f"Classification: `{summary['classification']}`",
                "",
                f"Next step: `{recommendation['next_step']}`",
                "",
                recommendation["current_best_insight"],
            ]
        )
        + "\n",
    )
    return {
        "status": output_root / "status.json",
        "summary": output_root / "definition_refinement_summary.json",
        "report": output_root / "definition_refinement_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    config = DailyStructuralOpportunityConfig(
        package_root=package_root,
        output_root=package_root / "output" / "daily_opportunity_definition_refinement_001",
    )
    write_daily_structural_opportunity(config)
    print(f"Daily opportunity definition refinement artifacts written to: {config.output_root}")


if __name__ == "__main__":
    main()
