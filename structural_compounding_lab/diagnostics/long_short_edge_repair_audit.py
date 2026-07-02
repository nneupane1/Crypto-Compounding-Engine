from __future__ import annotations

import csv
import json
import math
import re
from bisect import bisect_right
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd


LONG_FAILURE_MODES = [
    "LONG_CHOP_ENTRY",
    "LONG_WEAK_RECLAIM",
    "LONG_TINY_STOP_TRAP",
    "LONG_COUNTER_HTF",
    "LONG_OVERHEAD_RESISTANCE_TOO_CLOSE",
    "LONG_LOW_VOLUME_RECLAIM",
    "LONG_VWAP_FAKEOUT",
    "LONG_EMA_FAKEOUT",
    "LONG_LATE_AFTER_EXTENSION",
    "LONG_DANGER_TOO_HIGH",
    "LONG_COST_DOMINATED",
    "LONG_NO_REPEATABLE_EDGE",
]

SHORT_SUCCESS_MODES = [
    "SHORT_SWEEP_HIGH_REJECTION",
    "SHORT_FAILED_BREAKOUT",
    "SHORT_RANGE_HIGH_REJECTION",
    "SHORT_VWAP_LOSS",
    "SHORT_EMA_REJECTION",
    "SHORT_HTF_ALIGNED_BREAKDOWN",
    "SHORT_DISTRIBUTION_CONTINUATION",
    "SHORT_BREAKDOWN_RETEST",
    "SHORT_HIGH_R_MOONSHOT",
]

EXPECTANCY_LABELS = [
    "KEEP_AND_PRESERVE",
    "PROMISING_BUT_NEEDS_TIGHTENING",
    "DISABLE_IN_RESEARCH_ONLY",
    "REQUIRES_MORE_SAMPLE",
    "MOONSHOT_DEPENDENT",
    "NO_EDGE",
]


@dataclass(frozen=True)
class LongShortEdgeRepairAuditConfig:
    package_root: Path
    output_root: Path


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


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


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        ts = pd.Timestamp(value)
    except Exception:
        return None
    if ts.tzinfo is not None:
        return ts.tz_convert("UTC").tz_localize(None)
    return ts


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0.0:
        return default
    return numerator / denominator


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2 == 1:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2.0


def _artifact_paths(config: LongShortEdgeRepairAuditConfig) -> dict[str, Path]:
    source_root = config.package_root / "output"
    five_year_root = source_root / "five_year_compounding_audit_001"
    refined_root = source_root / "daily_opportunity_definition_refinement_001"
    daily_root = source_root / "daily_structural_opportunity_001"
    return {
        "summary": source_root / "summary.json",
        "trades": source_root / "trades.csv",
        "setup_log": source_root / "setup_log.csv",
        "level_log": source_root / "level_log.csv",
        "liquidity_events": source_root / "liquidity_events.csv",
        "cooldown_log": source_root / "cooldown_log.csv",
        "pyramiding_log": source_root / "pyramiding_log.csv",
        "profit_vault": source_root / "profit_vault.json",
        "five_year_summary": five_year_root / "five_year_compounding_summary.json",
        "five_year_trade_growth": five_year_root / "diagnostics" / "full_active_capital_trade_growth.csv",
        "definition_refinement_summary": refined_root / "definition_refinement_summary.json",
        "daily_structural_summary": daily_root / "daily_structural_opportunity_summary.json",
    }


def _parse_reason_fields(text: str) -> dict[str, Any]:
    reason = str(text or "")
    pattern_match = re.search(r"setup:\s*([a-zA-Z_]+)", reason)
    context_match = re.search(r"near\s+([a-zA-Z_]+)", reason)
    rr_match = re.search(r"RR\s+([0-9]+(?:\.[0-9]+)?)", reason)
    htf_match = re.search(r"HTF bias\s+([a-zA-Z_]+)", reason)
    return {
        "pattern_from_reason": pattern_match.group(1).lower() if pattern_match else "",
        "context_from_reason": context_match.group(1).lower() if context_match else "",
        "rr_from_reason": float(rr_match.group(1)) if rr_match else 0.0,
        "htf_bias_from_reason": htf_match.group(1).lower() if htf_match else "unknown",
    }


def _nearest_liquidity_context(
    liquidity_index: dict[str, list[dict[str, Any]]],
    *,
    symbol: str,
    entry_time: pd.Timestamp | None,
) -> dict[str, Any]:
    if entry_time is None:
        return {}
    candidates: list[tuple[float, dict[str, Any]]] = []
    for row in reversed(liquidity_index.get(symbol, [])):
        ts = row.get("_timestamp")
        if ts is None:
            continue
        if ts > entry_time:
            continue
        age_hours = (entry_time - ts).total_seconds() / 3600.0
        if age_hours > 12.0:
            break
        candidates.append((age_hours, row))
    if not candidates:
        return {}
    candidates.sort(key=lambda item: item[0])
    age_hours, row = candidates[0]
    return {
        "liquidity_event_type": str(row.get("type") or ""),
        "liquidity_side_implication": str(row.get("side_implication") or ""),
        "liquidity_source_timeframe": str(row.get("source_timeframe") or ""),
        "liquidity_confidence": _to_float(row.get("confidence")),
        "liquidity_age_hours": round(age_hours, 4),
    }


def _nearest_level_context(
    level_index: dict[str, dict[str, Any]],
    *,
    symbol: str,
    entry_time: pd.Timestamp | None,
    entry_price: float,
) -> dict[str, Any]:
    if entry_time is None or entry_price <= 0.0:
        return {}
    bundle = level_index.get(symbol)
    if not bundle:
        return {}
    rows = bundle["rows"]
    timestamps = bundle["timestamps"]
    cutoff_index = bisect_right(timestamps, entry_time)
    candidates: list[dict[str, Any]] = []
    for idx in range(cutoff_index - 1, -1, -1):
        row = rows[idx]
        ts = row.get("_timestamp")
        if ts is None:
            continue
        age_hours = (entry_time - ts).total_seconds() / 3600.0
        if age_hours > 72.0:
            break
        price = float(row["_price"])
        if price <= 0.0:
            continue
        candidates.append(
            {
                "price": price,
                "type": str(row.get("type") or ""),
                "timeframe_source": str(row.get("timeframe_source") or ""),
                "strength": _to_float(row.get("strength")),
                "touch_count": _to_int(row.get("touch_count")),
                "age_hours": age_hours,
            }
        )
    below = [row for row in candidates if row["price"] <= entry_price]
    above = [row for row in candidates if row["price"] >= entry_price]
    support = min(below, key=lambda row: abs(entry_price - row["price"])) if below else None
    resistance = min(above, key=lambda row: abs(row["price"] - entry_price)) if above else None
    return {
        "nearest_support_type": support["type"] if support else "",
        "nearest_support_timeframe": support["timeframe_source"] if support else "",
        "nearest_support_strength": support["strength"] if support else 0.0,
        "nearest_support_touch_count": support["touch_count"] if support else 0,
        "support_distance_pct": round(abs(entry_price - support["price"]) / entry_price, 6) if support else None,
        "nearest_resistance_type": resistance["type"] if resistance else "",
        "nearest_resistance_timeframe": resistance["timeframe_source"] if resistance else "",
        "nearest_resistance_strength": resistance["strength"] if resistance else 0.0,
        "nearest_resistance_touch_count": resistance["touch_count"] if resistance else 0,
        "resistance_distance_pct": round(abs(resistance["price"] - entry_price) / entry_price, 6) if resistance else None,
    }


def _match_setup(trade: dict[str, Any], setup_rows: list[dict[str, Any]]) -> dict[str, Any]:
    symbol = str(trade.get("symbol") or "").upper()
    side = str(trade.get("side") or "").lower()
    trade_reason = str(trade.get("entry_reason") or "")
    entry_time = _timestamp(trade.get("entry_time"))
    best_row: dict[str, Any] | None = None
    best_score: tuple[int, int, float] | None = None
    for row in setup_rows:
        if str(row.get("side") or "").lower() != side:
            continue
        setup_time = row.get("_timestamp")
        if setup_time is None or entry_time is None:
            continue
        age_hours = abs((entry_time - setup_time).total_seconds()) / 3600.0
        if age_hours > 4.0:
            continue
        reason_match = int(str(row.get("entry_reason") or row.get("explanation") or "") == trade_reason)
        before_or_equal = int(setup_time <= entry_time)
        score = (reason_match, before_or_equal, -age_hours)
        if best_score is None or score > best_score:
            best_row = row
            best_score = score
    return best_row or {}


def _prepare_rows_by_symbol(rows: list[dict[str, Any]], *, time_keys: tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
    output: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        parsed = None
        for key in time_keys:
            parsed = _timestamp(row.get(key))
            if parsed is not None:
                break
        symbol = str(row.get("symbol") or "").upper()
        if not symbol:
            continue
        enriched = dict(row)
        enriched["_timestamp"] = parsed
        enriched["_price"] = _to_float(row.get("price"))
        output[symbol].append(enriched)
    for symbol_rows in output.values():
        symbol_rows.sort(key=lambda item: item.get("_timestamp") or pd.Timestamp.min)
    return output


def _prepare_level_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    by_symbol = _prepare_rows_by_symbol(rows, time_keys=("timestamp", "last_touched", "first_seen"))
    output: dict[str, dict[str, Any]] = {}
    for symbol, symbol_rows in by_symbol.items():
        valid_rows = [row for row in symbol_rows if row.get("_timestamp") is not None]
        output[symbol] = {
            "rows": valid_rows,
            "timestamps": [row["_timestamp"] for row in valid_rows],
        }
    return output


def _moonshot_bucket(r_value: float) -> str:
    if r_value >= 10.0:
        return "moonshot_10R_plus"
    if r_value >= 8.0:
        return "moonshot_8R_plus"
    if r_value >= 5.0:
        return "moonshot_5R_plus"
    if r_value >= 3.0:
        return "high_R_win"
    if r_value > 0.0:
        return "win"
    return "loss"


def _repeatability_label(score: float) -> str:
    if score >= 0.75:
        return "REPEATABLE_STRUCTURAL_MOONSHOT"
    if score >= 0.55:
        return "POSSIBLY_REPEATABLE"
    if score > 0.0:
        return "LUCKY_OUTLIER"
    return "DATA_INSUFFICIENT"


def _profit_factor(r_values: list[float]) -> float:
    gross_profit = sum(value for value in r_values if value > 0.0)
    gross_loss = abs(sum(value for value in r_values if value < 0.0))
    if gross_loss == 0.0:
        return gross_profit if gross_profit > 0.0 else 0.0
    return gross_profit / gross_loss


def _aggregate_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    r_values = [float(row["r_multiple"]) for row in rows]
    pnl_values = [float(row["pnl"]) for row in rows]
    gross_profit = sum(value for value in r_values if value > 0.0)
    gross_loss = abs(sum(value for value in r_values if value < 0.0))
    wins = [value for value in r_values if value > 0.0]
    losses = [value for value in r_values if value < 0.0]
    moonshots = [value for value in r_values if value >= 5.0]
    return {
        "trade_count": len(rows),
        "win_rate": round(_safe_ratio(len(wins), len(rows), 0.0), 6),
        "avg_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
        "median_R": round(_median(r_values), 6) if r_values else 0.0,
        "total_R": round(sum(r_values), 6),
        "profit_factor": round(_profit_factor(r_values), 6),
        "max_winner_R": round(max(wins), 6) if wins else 0.0,
        "max_loser_R": round(min(losses), 6) if losses else 0.0,
        "loss_count": len(losses),
        "loss_R_total": round(sum(losses), 6) if losses else 0.0,
        "high_R_win_count": sum(1 for value in r_values if value >= 3.0),
        "moonshot_count": len(moonshots),
        "moonshot_R_total": round(sum(moonshots), 6) if moonshots else 0.0,
        "drawdown_contribution": round(abs(sum(losses)), 6),
        "gross_pnl": round(sum(pnl_values), 6),
        "gross_profit_R": round(gross_profit, 6),
        "gross_loss_R_abs": round(gross_loss, 6),
    }


def _expectancy_label(metrics: dict[str, Any]) -> str:
    trade_count = int(metrics["trade_count"])
    total_r = float(metrics["total_R"])
    avg_r = float(metrics["avg_R"])
    profit_factor = float(metrics["profit_factor"])
    moonshot_count = int(metrics["moonshot_count"])
    high_r_count = int(metrics["high_R_win_count"])
    if trade_count < 5:
        return "REQUIRES_MORE_SAMPLE"
    if total_r <= 0.0 or profit_factor < 1.0:
        return "NO_EDGE"
    if moonshot_count > 0 and total_r > 0.0 and float(metrics["moonshot_R_total"]) / max(total_r, 1e-9) > 0.75:
        return "MOONSHOT_DEPENDENT"
    if profit_factor >= 1.2 and avg_r >= 0.08 and high_r_count >= 2:
        return "KEEP_AND_PRESERVE"
    if profit_factor >= 1.0 and avg_r > 0.0:
        return "PROMISING_BUT_NEEDS_TIGHTENING"
    return "DISABLE_IN_RESEARCH_ONLY"


def _recommended_action(label: str, side: str) -> str:
    mapping = {
        "KEEP_AND_PRESERVE": f"preserve_{side}_archetype_and_avoid_runtime_changes",
        "PROMISING_BUT_NEEDS_TIGHTENING": f"research_only_filtering_for_{side}",
        "DISABLE_IN_RESEARCH_ONLY": f"disable_{side}_archetype_in_future_research_candidate_only",
        "REQUIRES_MORE_SAMPLE": f"collect_more_{side}_sample_before_any_change",
        "MOONSHOT_DEPENDENT": f"stress_test_{side}_moonshot_dependency_before_promotion",
        "NO_EDGE": f"remove_{side}_archetype_from_next_research_patch",
    }
    return mapping.get(label, "continue_research_only")


def _classify_long_failure(row: dict[str, Any]) -> str:
    r_value = float(row["r_multiple"])
    stop_pct = float(row.get("stop_distance_pct") or 0.0)
    holding_bars = int(row.get("holding_bars") or 0)
    htf_aligned = bool(row.get("htf_aligned"))
    context = str(row.get("entry_context") or "")
    resistance_distance_pct = row.get("resistance_distance_pct")
    ema_score = float(row.get("ema_score") or 0.0)
    pattern = str(row.get("pattern") or "")
    exit_reason = str(row.get("exit_reason") or "")
    if r_value > 0.0 and r_value <= 0.15:
        return "LONG_COST_DOMINATED"
    if r_value < 0.0 and stop_pct <= 0.004 and holding_bars <= 2:
        return "LONG_TINY_STOP_TRAP"
    if r_value < 0.0 and resistance_distance_pct is not None and resistance_distance_pct <= max(stop_pct * 1.5, 0.0035):
        return "LONG_OVERHEAD_RESISTANCE_TOO_CLOSE"
    if r_value < 0.0 and not htf_aligned:
        return "LONG_COUNTER_HTF"
    if r_value < 0.0 and context in {"resistance", "range_high", "prev_day_high"}:
        return "LONG_OVERHEAD_RESISTANCE_TOO_CLOSE"
    if r_value < 0.0 and exit_reason == "danger_sniffed" and holding_bars <= 2:
        return "LONG_CHOP_ENTRY"
    if r_value < 0.0 and ema_score <= 0.0:
        return "LONG_EMA_FAKEOUT"
    if r_value < 1.0 and pattern == "retest_after_breakout":
        return "LONG_LATE_AFTER_EXTENSION"
    if r_value < 1.0 and pattern == "sweep_low":
        return "LONG_WEAK_RECLAIM"
    return "LONG_NO_REPEATABLE_EDGE"


def _classify_short_success(row: dict[str, Any]) -> str:
    pattern = str(row.get("pattern") or "")
    context = str(row.get("entry_context") or "")
    side_implication = str(row.get("liquidity_side_implication") or "")
    r_value = float(row["r_multiple"])
    if r_value >= 5.0:
        return "SHORT_HIGH_R_MOONSHOT"
    if pattern == "retest_after_breakdown":
        return "SHORT_BREAKDOWN_RETEST"
    if pattern == "retest_or_breakdown":
        return "SHORT_FAILED_BREAKOUT"
    if pattern == "sweep_high" and context in {"range_high", "prev_day_high"}:
        return "SHORT_RANGE_HIGH_REJECTION"
    if pattern == "sweep_high" and context in {"resistance", "midpoint"}:
        return "SHORT_SWEEP_HIGH_REJECTION"
    if "bearish" in side_implication or "short" in side_implication:
        return "SHORT_DISTRIBUTION_CONTINUATION"
    if float(row.get("ema_score") or 0.0) > 0.0:
        return "SHORT_EMA_REJECTION"
    return "SHORT_SWEEP_HIGH_REJECTION"


def _risk_eur(row: dict[str, Any]) -> float:
    pnl = float(row["pnl"])
    r_value = float(row["r_multiple"])
    if r_value == 0.0:
        return 0.0
    return abs(pnl / r_value)


def _moonshot_repeatability_score(row: dict[str, Any], archetype_counts: Counter[str]) -> float:
    score = 0.0
    if str(row.get("setup_class") or "").upper() == "A":
        score += 0.2
    if str(row.get("convexity_label") or "") in {"elite_convexity", "strong_convexity"}:
        score += 0.15
    if float(row.get("setup_score") or 0.0) >= 4.0:
        score += 0.15
    if str(row.get("pattern") or "") in {"retest_after_breakdown", "sweep_high", "sweep_low"}:
        score += 0.15
    if float(row.get("liquidity_confidence") or 0.0) >= 0.6:
        score += 0.1
    if str(row.get("entry_context") or "") in {"support", "resistance", "range_low", "range_high"}:
        score += 0.1
    if str(row.get("exit_reason") or "") in {"danger_sniffed", "moonshot_capture"}:
        score += 0.05
    if archetype_counts.get(str(row.get("archetype_key") or ""), 0) > 1:
        score += 0.1
    if float(row["r_multiple"]) >= 10.0:
        score += 0.05
    return round(min(score, 1.0), 4)


def _trade_archetype_key(row: dict[str, Any]) -> str:
    pieces = [
        str(row.get("side") or "n/a"),
        str(row.get("pattern") or "n/a"),
        str(row.get("personality_label") or "n/a"),
        str(row.get("entry_context") or "n/a"),
        str(row.get("liquidity_event_type") or "n/a"),
    ]
    return "|".join(pieces)


def _normalize_trade_rows(
    trade_rows: list[dict[str, Any]],
    setup_rows: list[dict[str, Any]],
    level_rows: list[dict[str, Any]],
    liquidity_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    prepared_setups = _prepare_rows_by_symbol(setup_rows, time_keys=("timestamp",))
    prepared_liquidity = _prepare_rows_by_symbol(liquidity_rows, time_keys=("timestamp",))
    prepared_levels = _prepare_level_index(level_rows)
    for trade in trade_rows:
        side = str(trade.get("side") or "").lower()
        if side not in {"long", "short"}:
            continue
        entry_time = _timestamp(trade.get("entry_time"))
        exit_time = _timestamp(trade.get("exit_time"))
        entry_price = _to_float(trade.get("entry_price"))
        initial_stop = _to_float(trade.get("initial_stop"))
        stop_distance_pct = abs(entry_price - initial_stop) / entry_price if entry_price > 0.0 else 0.0
        reason_fields = _parse_reason_fields(str(trade.get("entry_reason") or ""))
        symbol = str(trade.get("symbol") or "").upper()
        setup = _match_setup(trade, prepared_setups.get(symbol, []))
        liquidity_context = _nearest_liquidity_context(prepared_liquidity, symbol=symbol, entry_time=entry_time)
        level_context = _nearest_level_context(
            prepared_levels,
            symbol=symbol,
            entry_time=entry_time,
            entry_price=entry_price,
        )
        row = {
            "trade_id": str(trade.get("trade_id") or ""),
            "symbol": symbol,
            "side": side,
            "entry_time": entry_time.isoformat() if entry_time is not None else "",
            "exit_time": exit_time.isoformat() if exit_time is not None else "",
            "entry_timestamp": entry_time,
            "exit_timestamp": exit_time,
            "entry_price": entry_price,
            "exit_price": _to_float(trade.get("exit_price")),
            "initial_stop": initial_stop,
            "trail_stop": _to_float(trade.get("trail_stop")),
            "stop_distance_pct": round(stop_distance_pct, 6),
            "pnl": _to_float(trade.get("pnl")),
            "r_multiple": _to_float(trade.get("r_multiple")),
            "entry_reason": str(trade.get("entry_reason") or ""),
            "exit_reason": str(trade.get("exit_reason") or ""),
            "holding_bars": _to_int(trade.get("holding_bars")),
            "setup_class": str(trade.get("setup_class") or setup.get("setup_class") or ""),
            "strategy_type": str(trade.get("strategy_type") or ""),
            "moonshot_state": str(trade.get("moonshot_state") or ""),
            "entry_score": _to_float(trade.get("entry_score")),
            "risk_multiplier": _to_float(trade.get("risk_multiplier"), default=1.0),
            "convexity_label": str(trade.get("convexity_label") or setup.get("convexity_label") or ""),
            "cooldown_fast_clear_eligible": str(trade.get("cooldown_fast_clear_eligible") or setup.get("cooldown_fast_clear_eligible") or ""),
            "cycle_id": str(trade.get("cycle_id") or ""),
            "pattern": str(setup.get("pattern") or reason_fields["pattern_from_reason"] or ""),
            "entry_context": str(reason_fields["context_from_reason"] or ""),
            "rr_from_reason": reason_fields["rr_from_reason"],
            "htf_bias": str(reason_fields["htf_bias_from_reason"] or ""),
            "setup_score": _to_float(setup.get("score") or setup.get("total_score")),
            "structure_score": _to_float(setup.get("structure_score")),
            "liquidity_score": _to_float(setup.get("liquidity_score")),
            "ema_score": _to_float(setup.get("ema_score")),
            "htf_confirmation_score": _to_float(setup.get("htf_confirmation_score")),
            "volatility_score": _to_float(setup.get("volatility_score")),
            "risk_reward_score": _to_float(setup.get("risk_reward_score")),
            "htf_aligned": str(setup.get("htf_aligned") or "").lower() == "true",
            "execution_timeframe": str(setup.get("execution_timeframe") or ""),
            "setup_pattern": str(setup.get("pattern") or reason_fields["pattern_from_reason"] or ""),
            "setup_explanation": str(setup.get("explanation") or setup.get("entry_reason") or ""),
            "personality_label": str(trade.get("convexity_label") or setup.get("convexity_label") or ""),
            "vwap_support": "unknown",
            "volume_confirmation": "unknown",
            "atr_tradability": "acceptable" if _to_float(setup.get("volatility_score")) >= 0.4 else "unknown",
            "cost_realism": "not_modeled_runtime",
            "danger_score": None,
            "chop_score": None,
            **liquidity_context,
            **level_context,
        }
        row["archetype_key"] = _trade_archetype_key(row)
        normalized.append(row)
    return normalized


def _breakdown_rows(
    rows: list[dict[str, Any]],
    *,
    group_fields: list[str],
) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = tuple(row.get(field) for field in group_fields)
        grouped[key].append(row)
    output_rows: list[dict[str, Any]] = []
    for key, bucket in sorted(grouped.items(), key=lambda item: (-len(item[1]), tuple(str(value) for value in item[0]))):
        metrics = _aggregate_metrics(bucket)
        payload = {field: key[index] for index, field in enumerate(group_fields)}
        payload.update(metrics)
        output_rows.append(payload)
    return output_rows


def _mode_report_rows(
    rows: list[dict[str, Any]],
    *,
    modes: list[str],
    mode_field: str,
    recommendation_prefix: str,
) -> list[dict[str, Any]]:
    output_rows: list[dict[str, Any]] = []
    for mode in modes:
        bucket = [row for row in rows if row.get(mode_field) == mode]
        metrics = _aggregate_metrics(bucket)
        evidence_columns = [
            "pattern",
            "entry_context",
            "setup_class",
            "personality_label",
            "stop_distance_pct",
            "ema_score",
            "liquidity_event_type",
            "nearest_support_type",
            "nearest_resistance_type",
        ]
        examples = sorted(bucket, key=lambda row: float(row["r_multiple"]))[:3] if "failure" in mode_field else sorted(bucket, key=lambda row: float(row["r_multiple"]), reverse=True)[:3]
        output_rows.append(
            {
                "failure_mode" if "failure" in mode_field else "success_mode": mode,
                "trade_count": metrics["trade_count"],
                "total_R": metrics["total_R"],
                "avg_R": metrics["avg_R"],
                "win_rate": metrics["win_rate"],
                "profit_factor": metrics["profit_factor"],
                "evidence_columns": ",".join(evidence_columns),
                "example_trade_ids": ",".join(row["trade_id"] for row in examples),
                "recommended_research_action": f"{recommendation_prefix}:{mode.lower()}",
            }
        )
    return output_rows


def _archetype_expectancy_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    group_fields = ["side", "pattern", "personality_label", "setup_pattern", "liquidity_event_type"]
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(row.get(field) for field in group_fields)].append(row)
    output_rows: list[dict[str, Any]] = []
    for key, bucket in grouped.items():
        metrics = _aggregate_metrics(bucket)
        label = _expectancy_label(metrics)
        output_rows.append(
            {
                "side": key[0] or "",
                "pullback_type": key[1] or "",
                "personality_label": key[2] or "",
                "setup_pattern": key[3] or "",
                "liquidity_event_type": key[4] or "",
                "trade_count": metrics["trade_count"],
                "win_rate": metrics["win_rate"],
                "avg_R": metrics["avg_R"],
                "median_R": metrics["median_R"],
                "total_R": metrics["total_R"],
                "profit_factor": metrics["profit_factor"],
                "max_winner_R": metrics["max_winner_R"],
                "max_loser_R": metrics["max_loser_R"],
                "high_R_win_count": metrics["high_R_win_count"],
                "moonshot_5R_plus_count": sum(1 for row in bucket if float(row["r_multiple"]) >= 5.0),
                "moonshot_8R_plus_count": sum(1 for row in bucket if float(row["r_multiple"]) >= 8.0),
                "moonshot_10R_plus_count": sum(1 for row in bucket if float(row["r_multiple"]) >= 10.0),
                "expectancy_label": label,
                "recommended_action": _recommended_action(label, str(key[0] or "archetype")),
            }
        )
    output_rows.sort(key=lambda row: (row["side"], row["total_R"], row["profit_factor"]), reverse=True)
    return output_rows


def _moonshot_rows(
    rows: list[dict[str, Any]],
    pyramiding_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    moonshots = [row for row in rows if float(row["r_multiple"]) >= 5.0]
    archetype_counts = Counter(row["archetype_key"] for row in moonshots)
    profit_lock_cycles = {
        str(row.get("cycle_id") or "")
        for row in pyramiding_rows
        if str(row.get("event_type") or "") == "profit_lock"
    }
    output_rows: list[dict[str, Any]] = []
    total_net_profit = sum(float(row["pnl"]) for row in rows)
    total_net_r = sum(float(row["r_multiple"]) for row in rows)
    risk_eur_by_trade = {row["trade_id"]: _risk_eur(row) for row in rows}
    pnl_without_moonshots = sum(float(row["pnl"]) for row in rows if float(row["r_multiple"]) < 5.0)
    r_without_moonshots = sum(float(row["r_multiple"]) for row in rows if float(row["r_multiple"]) < 5.0)
    pnl_cap_10_to_5 = 0.0
    pnl_cap_5_to_3 = 0.0
    r_cap_10_to_5 = 0.0
    r_cap_5_to_3 = 0.0
    for row in rows:
        r_value = float(row["r_multiple"])
        risk_eur = risk_eur_by_trade[row["trade_id"]]
        capped_10 = min(r_value, 5.0) if r_value > 0.0 else r_value
        capped_5 = min(r_value, 3.0) if r_value > 0.0 else r_value
        pnl_cap_10_to_5 += capped_10 * risk_eur
        pnl_cap_5_to_3 += capped_5 * risk_eur
        r_cap_10_to_5 += capped_10
        r_cap_5_to_3 += capped_5
    for row in moonshots:
        repeatability_score = _moonshot_repeatability_score(row, archetype_counts)
        output_rows.append(
            {
                "trade_id": row["trade_id"],
                "timestamp": row["exit_time"] or row["entry_time"],
                "side": row["side"],
                "R": round(float(row["r_multiple"]), 6),
                "pnl": round(float(row["pnl"]), 6),
                "setup_pattern": row["setup_pattern"],
                "pullback_type": row["pattern"],
                "personality_label": row["personality_label"],
                "liquidity_event_type": row.get("liquidity_event_type") or "",
                "HTF_context": row.get("htf_bias") or "",
                "support_resistance_context": row.get("entry_context") or "",
                "volume_context": row.get("volume_confirmation") or "unknown",
                "VWAP_context": row.get("vwap_support") or "unknown",
                "EMA_context": "aligned" if float(row.get("ema_score") or 0.0) > 0.0 else "not_confirmed",
                "ATR_context": row.get("atr_tradability") or "unknown",
                "candle_rejection_evidence": row.get("entry_reason") or "",
                "was_add_on_used": int(_to_int(row.get("add_on_count")) > 0),
                "was_trailing_used": int(str(row.get("exit_reason") or "") in {"slow_grind_exit", "moonshot_capture"}),
                "was_profit_lock_used": int(str(row.get("cycle_id") or "") in profit_lock_cycles),
                "repeatability_score": repeatability_score,
                "moonshot_quality_label": _repeatability_label(repeatability_score),
            }
        )
    output_rows.sort(key=lambda row: (row["R"], row["timestamp"]), reverse=True)
    dependency_report = {
        "research_only": True,
        "real_money_allowed": False,
        "moonshot_5R_plus_count": len(moonshots),
        "moonshot_side_counts": dict(Counter(row["side"] for row in moonshots)),
        "moonshot_profit_contribution_pct_of_net": round(_safe_ratio(sum(float(row["pnl"]) for row in moonshots), total_net_profit, 0.0), 6) if total_net_profit else 0.0,
        "net_profit_original": round(total_net_profit, 6),
        "net_R_original": round(total_net_r, 6),
        "net_profit_without_moonshots": round(pnl_without_moonshots, 6),
        "net_R_without_moonshots": round(r_without_moonshots, 6),
        "net_profit_with_10R_plus_capped_to_5R": round(pnl_cap_10_to_5, 6),
        "net_R_with_10R_plus_capped_to_5R": round(r_cap_10_to_5, 6),
        "net_profit_with_all_5R_plus_capped_to_3R": round(pnl_cap_5_to_3, 6),
        "net_R_with_all_5R_plus_capped_to_3R": round(r_cap_5_to_3, 6),
        "moonshot_repeatable_count": sum(1 for row in output_rows if row["moonshot_quality_label"] == "REPEATABLE_STRUCTURAL_MOONSHOT"),
        "moonshot_possible_repeatable_count": sum(1 for row in output_rows if row["moonshot_quality_label"] == "POSSIBLY_REPEATABLE"),
        "moonshot_lucky_outlier_count": sum(1 for row in output_rows if row["moonshot_quality_label"] == "LUCKY_OUTLIER"),
    }
    return output_rows, dependency_report


def _best_worst_archetype(rows: list[dict[str, Any]], side: str) -> tuple[str, str]:
    side_rows = [row for row in rows if row["side"] == side]
    if not side_rows:
        return "n/a", "n/a"
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in side_rows:
        grouped[row["archetype_key"]].append(row)
    scored = []
    for key, bucket in grouped.items():
        metrics = _aggregate_metrics(bucket)
        scored.append((key, metrics["total_R"], metrics["profit_factor"], len(bucket)))
    scored.sort(key=lambda item: (item[1], item[2], item[3]))
    worst = scored[0][0]
    best = scored[-1][0]
    return best, worst


def _long_filter_candidates(long_rows: list[dict[str, Any]]) -> dict[str, Any]:
    failure_counts = Counter(row["failure_mode"] for row in long_rows)
    return {
        "research_only": True,
        "real_money_allowed": False,
        "filters": [
            {
                "filter_name": "minimum_long_stop_distance_guard",
                "trigger": "stop_distance_pct < 0.004 and holding_bars <= 2",
                "diagnosis": "LONG_TINY_STOP_TRAP",
                "observed_trade_count": failure_counts.get("LONG_TINY_STOP_TRAP", 0),
            },
            {
                "filter_name": "avoid_long_against_nearby_overhead_resistance",
                "trigger": "resistance_distance_pct <= max(stop_distance_pct * 1.5, 0.0035)",
                "diagnosis": "LONG_OVERHEAD_RESISTANCE_TOO_CLOSE",
                "observed_trade_count": failure_counts.get("LONG_OVERHEAD_RESISTANCE_TOO_CLOSE", 0),
            },
            {
                "filter_name": "require_better_long_reclaim_confirmation",
                "trigger": "pattern == sweep_low and ema_score <= 0.0",
                "diagnosis": "LONG_WEAK_RECLAIM / LONG_EMA_FAKEOUT",
                "observed_trade_count": failure_counts.get("LONG_WEAK_RECLAIM", 0) + failure_counts.get("LONG_EMA_FAKEOUT", 0),
            },
        ],
    }


def _short_preservation_rules(short_rows: list[dict[str, Any]]) -> dict[str, Any]:
    success_counts = Counter(row["success_mode"] for row in short_rows)
    return {
        "research_only": True,
        "real_money_allowed": False,
        "rules": [
            {
                "rule_name": "preserve_sweep_high_short_engine",
                "mode": "SHORT_SWEEP_HIGH_REJECTION",
                "observed_trade_count": success_counts.get("SHORT_SWEEP_HIGH_REJECTION", 0),
            },
            {
                "rule_name": "preserve_breakdown_retest_short_engine",
                "mode": "SHORT_BREAKDOWN_RETEST",
                "observed_trade_count": success_counts.get("SHORT_BREAKDOWN_RETEST", 0),
            },
            {
                "rule_name": "do_not_touch_short_moonshot_release_logic",
                "mode": "SHORT_HIGH_R_MOONSHOT",
                "observed_trade_count": success_counts.get("SHORT_HIGH_R_MOONSHOT", 0),
            },
        ],
    }


def _edge_repair_recommendation(
    *,
    long_metrics: dict[str, Any],
    short_metrics: dict[str, Any],
    dependency_report: dict[str, Any],
    best_long_archetype: str,
    worst_long_archetype: str,
    best_short_archetype: str,
    worst_short_archetype: str,
) -> dict[str, Any]:
    if float(long_metrics["total_R"]) < 0.0 and float(short_metrics["total_R"]) > 0.0:
        patch = "PRESERVE_SHORTS_AND_DISABLE_BAD_LONG_ARCHETYPES"
    elif dependency_report["moonshot_profit_contribution_pct_of_net"] > 1.0:
        patch = "MOONSHOT_QUALITY_FILTER"
    else:
        patch = "TIGHTEN_LONGS_ONLY"
    return {
        "research_only": True,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
        "current_problem": "longs_negative_shorts_positive_and_net_edge_is_thin",
        "long_side_diagnosis": {
            "total_R": long_metrics["total_R"],
            "profit_factor": long_metrics["profit_factor"],
            "best_long_archetype": best_long_archetype,
            "worst_long_archetype": worst_long_archetype,
        },
        "short_side_diagnosis": {
            "total_R": short_metrics["total_R"],
            "profit_factor": short_metrics["profit_factor"],
            "best_short_archetype": best_short_archetype,
            "worst_short_archetype": worst_short_archetype,
        },
        "moonshot_dependency_diagnosis": dependency_report,
        "recommended_next_research_patch": patch,
        "do_not_touch_rules": [
            "do_not_change_live_or_paper_runtime",
            "do_not_change_short_side_release_logic_before_research_candidate_proves_it",
            "do_not_promote_any_filter_without_fast_holdout_stress_confirmation",
        ],
        "expected_improvement_target": {
            "long_total_R_to_non_negative": True,
            "short_total_R_preserved_positive": True,
            "moonshot_dependency_pct_below_1.0": True,
            "profit_factor_target": 1.1,
        },
        "future_module_candidate": "candle_anatomy_rejection_quality.py",
        "candle_anatomy_needed": True,
        "candle_anatomy_goal": [
            "distinguish_real_reclaim_from_fake_wick",
            "separate_tiny_noisy_long_candles_from_displacement_reclaims",
            "preserve_strong_upper_wick_short_rejections",
        ],
    }


def _report_markdown(
    *,
    summary: dict[str, Any],
    recommendation: dict[str, Any],
    dependency_report: dict[str, Any],
) -> str:
    lines = [
        "# Long vs Short Edge Repair Audit",
        "",
        "## Research Scope",
        "",
        "- research_only: `true`",
        "- paper_allowed: `false`",
        "- live_allowed: `false`",
        "- real_money_allowed: `false`",
        "- behavior_change_allowed: `false`",
        "",
        "## Core Finding",
        "",
        f"- long total R: `{summary['long_total_R']}`",
        f"- short total R: `{summary['short_total_R']}`",
        f"- long profit factor: `{summary['long_profit_factor']}`",
        f"- short profit factor: `{summary['short_profit_factor']}`",
        f"- moonshot 5R+ count: `{summary['moonshot_5R_plus_count']}`",
        f"- moonshot contribution of net profit: `{summary['moonshot_profit_contribution_pct_of_net']}`",
        "",
        "## Interpretation",
        "",
        "- Longs are the main expectancy drag. Shorts are the main expectancy carrier.",
        "- The current compounding curve survives, but it survives on thin edge and moonshot help.",
        "- The next patch must be research-only and asymmetric: repair longs while preserving shorts.",
        "",
        "## Recommendation",
        "",
        f"- recommended_next_research_patch: `{recommendation['recommended_next_research_patch']}`",
        f"- best_long_archetype: `{summary['best_long_archetype']}`",
        f"- worst_long_archetype: `{summary['worst_long_archetype']}`",
        f"- best_short_archetype: `{summary['best_short_archetype']}`",
        f"- worst_short_archetype: `{summary['worst_short_archetype']}`",
        "",
        "## Moonshot Stress",
        "",
        f"- net profit original: `{dependency_report['net_profit_original']}`",
        f"- net profit without moonshots: `{dependency_report['net_profit_without_moonshots']}`",
        f"- net profit with 10R+ capped to 5R: `{dependency_report['net_profit_with_10R_plus_capped_to_5R']}`",
        f"- net profit with all 5R+ capped to 3R: `{dependency_report['net_profit_with_all_5R_plus_capped_to_3R']}`",
        "",
        "No runtime, strategy, sizing, risk, allocator, or config defaults were changed.",
    ]
    return "\n".join(lines) + "\n"


def _empty_outputs(config: LongShortEdgeRepairAuditConfig, *, warnings: list[str]) -> dict[str, Path]:
    output_root = config.output_root
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    status = {
        "state": "empty",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
        "warnings": warnings,
    }
    summary = {
        "research_only": True,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
        "warnings": warnings,
        "long_trade_count": 0,
        "short_trade_count": 0,
        "long_total_R": 0.0,
        "short_total_R": 0.0,
        "recommended_next_research_patch": "NO_CHANGE_EDGE_TOO_THIN",
    }
    _write_json(output_root / "status.json", status)
    _write_json(output_root / "long_short_edge_repair_summary.json", summary)
    _write_markdown(output_root / "long_short_edge_repair_report.md", "# Long vs Short Edge Repair Audit\n\nNo usable structural trade artifacts were available.\n")
    for name in (
        "long_edge_breakdown.csv",
        "short_edge_breakdown.csv",
        "archetype_expectancy_breakdown.csv",
        "personality_expectancy_breakdown.csv",
        "long_failure_modes.csv",
        "short_success_modes.csv",
        "moonshot_repeatability_report.csv",
    ):
        _write_csv(diagnostics_root / name, [])
    for name in (
        "moonshot_dependency_report.json",
        "long_filters_research_candidates.json",
        "short_preservation_rules.json",
        "edge_repair_recommendation.json",
    ):
        _write_json(diagnostics_root / name, {"research_only": True, "warnings": warnings})
    _write_json(reports_root / "next_research_recommendation.json", {"research_only": True, "warnings": warnings})
    return {
        "status": output_root / "status.json",
        "summary": output_root / "long_short_edge_repair_summary.json",
        "report": output_root / "long_short_edge_repair_report.md",
    }


def write_long_short_edge_repair_audit(config: LongShortEdgeRepairAuditConfig) -> dict[str, Path]:
    paths = _artifact_paths(config)
    trade_rows = _read_csv_rows(paths["trades"])
    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    cooldown_rows = _read_csv_rows(paths["cooldown_log"])
    pyramiding_rows = _read_csv_rows(paths["pyramiding_log"])
    profit_vault = _read_json(paths["profit_vault"], {})
    five_year_summary = _read_json(paths["five_year_summary"], {})
    five_year_trade_growth = _read_csv_rows(paths["five_year_trade_growth"])
    definition_refinement_summary = _read_json(paths["definition_refinement_summary"], {})
    daily_structural_summary = _read_json(paths["daily_structural_summary"], {})

    normalized_rows = _normalize_trade_rows(trade_rows, setup_rows, level_rows, liquidity_rows)
    if not normalized_rows:
        return _empty_outputs(config, warnings=["no_usable_trades_for_long_short_edge_repair"])

    long_rows = [row for row in normalized_rows if row["side"] == "long"]
    short_rows = [row for row in normalized_rows if row["side"] == "short"]

    for row in long_rows:
        row["failure_mode"] = _classify_long_failure(row)
    positive_short_rows = [row for row in short_rows if float(row["r_multiple"]) > 0.0]
    for row in positive_short_rows:
        row["success_mode"] = _classify_short_success(row)

    long_metrics = _aggregate_metrics(long_rows)
    short_metrics = _aggregate_metrics(short_rows)
    overall_trade_count = len(normalized_rows)
    moonshot_repeatability_rows, moonshot_dependency_report = _moonshot_rows(normalized_rows, pyramiding_rows)

    long_breakdown = _breakdown_rows(long_rows, group_fields=["setup_pattern", "personality_label", "entry_context", "liquidity_event_type"])
    short_breakdown = _breakdown_rows(short_rows, group_fields=["setup_pattern", "personality_label", "entry_context", "liquidity_event_type"])
    archetype_expectancy = _archetype_expectancy_rows(normalized_rows)
    personality_expectancy = _breakdown_rows(normalized_rows, group_fields=["side", "personality_label"])
    long_failure_rows = _mode_report_rows(long_rows, modes=LONG_FAILURE_MODES, mode_field="failure_mode", recommendation_prefix="long_repair")
    short_success_rows = _mode_report_rows(positive_short_rows, modes=SHORT_SUCCESS_MODES, mode_field="success_mode", recommendation_prefix="short_preserve")

    best_long_archetype, worst_long_archetype = _best_worst_archetype(long_rows, "long")
    best_short_archetype, worst_short_archetype = _best_worst_archetype(short_rows, "short")

    recommendation = _edge_repair_recommendation(
        long_metrics=long_metrics,
        short_metrics=short_metrics,
        dependency_report=moonshot_dependency_report,
        best_long_archetype=best_long_archetype,
        worst_long_archetype=worst_long_archetype,
        best_short_archetype=best_short_archetype,
        worst_short_archetype=worst_short_archetype,
    )
    long_filter_candidates = _long_filter_candidates(long_rows)
    short_preservation_rules = _short_preservation_rules(positive_short_rows)

    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_only": True,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
        "trade_count": overall_trade_count,
        "long_trade_count": len(long_rows),
        "short_trade_count": len(short_rows),
        "long_total_R": long_metrics["total_R"],
        "short_total_R": short_metrics["total_R"],
        "long_profit_factor": long_metrics["profit_factor"],
        "short_profit_factor": short_metrics["profit_factor"],
        "long_win_rate": long_metrics["win_rate"],
        "short_win_rate": short_metrics["win_rate"],
        "best_long_archetype": best_long_archetype,
        "worst_long_archetype": worst_long_archetype,
        "best_short_archetype": best_short_archetype,
        "worst_short_archetype": worst_short_archetype,
        "moonshot_5R_plus_count": moonshot_dependency_report["moonshot_5R_plus_count"],
        "moonshot_side_counts": moonshot_dependency_report["moonshot_side_counts"],
        "moonshot_profit_contribution_pct_of_net": moonshot_dependency_report["moonshot_profit_contribution_pct_of_net"],
        "profit_without_moonshots": moonshot_dependency_report["net_profit_without_moonshots"],
        "profit_with_10R_plus_capped_to_5R": moonshot_dependency_report["net_profit_with_10R_plus_capped_to_5R"],
        "profit_with_all_5R_plus_capped_to_3R": moonshot_dependency_report["net_profit_with_all_5R_plus_capped_to_3R"],
        "recommended_next_research_patch": recommendation["recommended_next_research_patch"],
        "five_year_readiness_classification": five_year_summary.get("compounding_readiness_classification"),
        "five_year_moonshot_contribution_pct": five_year_summary.get("moonshot_profit_contribution_pct"),
        "daily_definition_classification": definition_refinement_summary.get("classification") or daily_structural_summary.get("classification"),
        "profit_vault_cycle": profit_vault.get("current_compounding_cycle_id"),
        "cooldown_event_count": len(cooldown_rows),
        "profit_lock_event_count": sum(1 for row in pyramiding_rows if str(row.get("event_type") or "") == "profit_lock"),
        "five_year_trade_growth_rows": len(five_year_trade_growth),
    }

    next_research_recommendation = {
        "research_only": True,
        "real_money_allowed": False,
        "recommended_next_patch": recommendation["recommended_next_research_patch"],
        "recommended_scope": [
            "repair_negative_long_archetypes_only",
            "preserve_positive_short_archetypes",
            "stress_test_moonshot_dependency_before_any_promotion",
        ],
        "do_not_touch": recommendation["do_not_touch_rules"],
    }

    report = _report_markdown(summary=summary, recommendation=recommendation, dependency_report=moonshot_dependency_report)

    output_root = config.output_root
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    status = {
        "state": "complete",
        "resolved_at_utc": summary["resolved_at_utc"],
        "research_only": True,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "behavior_change_allowed": False,
    }
    _write_json(output_root / "status.json", status)
    _write_json(output_root / "long_short_edge_repair_summary.json", summary)
    _write_markdown(output_root / "long_short_edge_repair_report.md", report)
    _write_csv(diagnostics_root / "long_edge_breakdown.csv", long_breakdown)
    _write_csv(diagnostics_root / "short_edge_breakdown.csv", short_breakdown)
    _write_csv(diagnostics_root / "archetype_expectancy_breakdown.csv", archetype_expectancy)
    _write_csv(diagnostics_root / "personality_expectancy_breakdown.csv", personality_expectancy)
    _write_csv(diagnostics_root / "long_failure_modes.csv", long_failure_rows)
    _write_csv(diagnostics_root / "short_success_modes.csv", short_success_rows)
    _write_csv(diagnostics_root / "moonshot_repeatability_report.csv", moonshot_repeatability_rows)
    _write_json(diagnostics_root / "moonshot_dependency_report.json", moonshot_dependency_report)
    _write_json(diagnostics_root / "long_filters_research_candidates.json", long_filter_candidates)
    _write_json(diagnostics_root / "short_preservation_rules.json", short_preservation_rules)
    _write_json(diagnostics_root / "edge_repair_recommendation.json", recommendation)
    _write_json(reports_root / "next_research_recommendation.json", next_research_recommendation)
    return {
        "status": output_root / "status.json",
        "summary": output_root / "long_short_edge_repair_summary.json",
        "report": output_root / "long_short_edge_repair_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    config = LongShortEdgeRepairAuditConfig(
        package_root=package_root,
        output_root=package_root / "output" / "long_short_edge_repair_audit_001",
    )
    result = write_long_short_edge_repair_audit(config)
    print(result["summary"])


if __name__ == "__main__":
    main()
