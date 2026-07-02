from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any, Callable

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import package_root, project_root  # noqa: E402
from structural_compounding_lab.diagnostics.cost_aware_frozen_candidate_rebuild import (  # noqa: E402
    CANDIDATE_NAME,
    MAX_PRE_ENTRY_COST_R,
    RISK_PER_TRADE,
    ROUND_TRIP_COST_BPS,
    SAFETY_FLAGS,
    START_CAPITAL_25K,
    CostAwareCandidateConfig,
    _candidate_rows,
    _full_and_holdout,
    _period_growth,
    _rolling_windows,
    default_config as candidate_default_config,
)
from structural_compounding_lab.diagnostics.court_002_net_cost_restatement import (  # noqa: E402
    _max_drawdown,
    _profit_factor,
    _safe_ratio,
)


COURT_NAME = "BITPANDA_2X_LEVERAGE_STRESS_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "bitpanda_2x_leverage_stress_court_001"

LEVERAGE = 2.0
BITPANDA_MARGIN_OPEN_FEE_BPS = 0.0
BITPANDA_MARGIN_CLOSE_FEE_BPS = 30.0
BITPANDA_MARGIN_FUNDING_DAILY_BPS = 18.0
BITPANDA_MARGIN_LIQUIDATION_FEE_BPS = 100.0
ADDITIONAL_SPREAD_SLIPPAGE_BPS = 5.0

BASELINE_NORMAL_ROUND_TRIP_BPS = ROUND_TRIP_COST_BPS
MISSION_TARGET_EUR = 1_000_000.0

PASSED = "BITPANDA_2X_LEVERAGE_STRESS_PASSED_RESEARCH_ONLY"
WARNING = "BITPANDA_2X_LEVERAGE_STRESS_WARNING_RESEARCH_ONLY"
FAILED = "BITPANDA_2X_LEVERAGE_STRESS_FAILED_RESEARCH_ONLY"
BLOCKED = "BITPANDA_2X_LEVERAGE_STRESS_BLOCKED_RESEARCH_ONLY"


@dataclass(frozen=True)
class LeverageCourtConfig:
    project_root: Path
    package_root: Path
    candidate_config: CostAwareCandidateConfig
    output_root: Path


def default_config() -> LeverageCourtConfig:
    candidate_config = candidate_default_config()
    return LeverageCourtConfig(
        project_root=project_root(),
        package_root=package_root(),
        candidate_config=candidate_config,
        output_root=package_root() / "output" / OUTPUT_FOLDER_NAME,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round_payload(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _round_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_payload(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_round_payload(payload), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return "" if math.isnan(value) or math.isinf(value) else round(value, 10)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if value is None:
        return ""
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in keys})


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _to_timestamp(value: Any) -> pd.Timestamp:
    return pd.to_datetime(value, utc=True, errors="coerce")


def _holding_days(row: dict[str, Any]) -> float:
    entry = _to_timestamp(row.get("entry_timestamp") or row.get("entry_time"))
    exit_ = _to_timestamp(row.get("exit_timestamp") or row.get("exit_time"))
    if pd.isna(entry) or pd.isna(exit_) or exit_ < entry:
        bars = float(row.get("holding_bars") or 1.0)
        return max(bars, 1.0) / 24.0
    seconds = max((exit_ - entry).total_seconds(), 60.0)
    return seconds / 86_400.0


def _entry_timestamp(row: dict[str, Any]) -> pd.Timestamp:
    return _to_timestamp(row.get("entry_timestamp") or row.get("entry_time"))


def _setup_quality(row: dict[str, Any]) -> dict[str, Any]:
    entry_score = float(row.get("entry_score") or 0.0)
    compounding_score = float(row.get("compounding_readiness_score") or 0.0)
    setup_class = str(row.get("setup_class") or "")
    convexity = str(row.get("convexity_label") or "")
    pullback_quality = float(row.get("pullback_quality_score") or 0.0)
    high_confluence = (
        setup_class in {"A", "B"}
        and convexity in {"elite_convexity", "strong_convexity"}
        and entry_score >= 4.0
        and compounding_score >= 0.45
    )
    elite_only = setup_class == "A" and convexity == "elite_convexity" and entry_score >= 4.5 and pullback_quality >= 0.75
    return {
        "entry_score": entry_score,
        "compounding_readiness_score": compounding_score,
        "setup_class": setup_class,
        "convexity_label": convexity,
        "pullback_quality_score": pullback_quality,
        "high_confluence": high_confluence,
        "elite_only": elite_only,
    }


def _enrich_candidate_rows(candidate_rows: list[dict[str, Any]], raw_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    raw_by_trade_id = {str(row.get("trade_id")): row for row in raw_rows if row.get("trade_id")}
    passthrough_fields = (
        "entry_score",
        "risk_multiplier",
        "convexity_label",
        "personality_label",
        "personality_confidence",
        "pullback_type",
        "pullback_quality_score",
        "compounding_readiness_score",
        "patience_score",
        "de_risk_score",
        "holding_bars",
        "entry_reason",
        "exit_reason",
    )
    enriched: list[dict[str, Any]] = []
    for row in candidate_rows:
        raw = raw_by_trade_id.get(str(row.get("trade_id")), {})
        payload = dict(row)
        for field in passthrough_fields:
            if raw.get(field) not in {None, ""}:
                payload[field] = raw.get(field)
        enriched.append(payload)
    return enriched


def _activation_start(rows: list[dict[str, Any]], *, years_after_first_trade: int | None) -> pd.Timestamp | None:
    if years_after_first_trade is None:
        return None
    timestamps = [_entry_timestamp(row) for row in rows]
    timestamps = [ts for ts in timestamps if pd.notna(ts)]
    if not timestamps:
        return None
    return min(timestamps) + pd.DateOffset(years=years_after_first_trade)


def _leverage_cost_components(row: dict[str, Any]) -> dict[str, float]:
    stop_fraction = float(row.get("stop_distance_fraction") or 0.0)
    holding_days = _holding_days(row)
    if stop_fraction <= 0.0:
        return {
            "holding_days": holding_days,
            "base_normal_cost_r": 0.0,
            "bitpanda_open_fee_r": 0.0,
            "bitpanda_close_fee_r": 0.0,
            "bitpanda_funding_r": 0.0,
            "additional_spread_slippage_r": 0.0,
            "total_leverage_cost_r": 0.0,
        }
    open_fee_r = LEVERAGE * (BITPANDA_MARGIN_OPEN_FEE_BPS / 10_000.0) / stop_fraction
    close_fee_r = LEVERAGE * (BITPANDA_MARGIN_CLOSE_FEE_BPS / 10_000.0) / stop_fraction
    funding_r = LEVERAGE * (BITPANDA_MARGIN_FUNDING_DAILY_BPS / 10_000.0) * holding_days / stop_fraction
    slippage_r = LEVERAGE * (ADDITIONAL_SPREAD_SLIPPAGE_BPS / 10_000.0) / stop_fraction
    base_normal_cost_r = float(row.get("net_cost_r") or 0.0)
    return {
        "holding_days": holding_days,
        "base_normal_cost_r": base_normal_cost_r,
        "bitpanda_open_fee_r": open_fee_r,
        "bitpanda_close_fee_r": close_fee_r,
        "bitpanda_funding_r": funding_r,
        "additional_spread_slippage_r": slippage_r,
        "total_leverage_cost_r": open_fee_r + close_fee_r + funding_r + slippage_r,
    }


def _risk_flags(row: dict[str, Any], *, leverage_enabled: bool) -> dict[str, Any]:
    stop_fraction = float(row.get("stop_distance_fraction") or 0.0)
    leveraged_stop_loss_pct_of_equity = LEVERAGE * stop_fraction if leverage_enabled else stop_fraction
    conservative_liquidation_distance = max(0.0, (1.0 / LEVERAGE) - 0.05)
    stop_inside_conservative_liquidation_buffer = stop_fraction < conservative_liquidation_distance if leverage_enabled else True
    return {
        "leveraged_stop_loss_pct_of_equity": leveraged_stop_loss_pct_of_equity,
        "conservative_liquidation_distance_used": conservative_liquidation_distance if leverage_enabled else None,
        "stop_inside_conservative_liquidation_buffer": stop_inside_conservative_liquidation_buffer,
    }


def _simulate_policy(
    rows: list[dict[str, Any]],
    *,
    policy_id: str,
    should_leverage: Callable[[dict[str, Any]], bool],
    start_capital: float = START_CAPITAL_25K,
) -> dict[str, Any]:
    equity = start_capital
    curve = [equity]
    trade_rows: list[dict[str, Any]] = []
    total_cost_eur = 0.0
    leveraged_count = 0
    liquid_buffer_breaches = 0
    net_r_values: list[float] = []
    base_net_r_values: list[float] = []

    for idx, row in enumerate(rows, start=1):
        base_net_r = float(row.get("net_r") or 0.0)
        gross_r = float(row.get("gross_r") or 0.0)
        quality = _setup_quality(row)
        leverage_enabled = bool(should_leverage(row))
        components = _leverage_cost_components(row)

        if leverage_enabled:
            net_r = (LEVERAGE * gross_r) - components["total_leverage_cost_r"]
            leveraged_count += 1
        else:
            net_r = base_net_r

        before = equity
        risk_eur = before * RISK_PER_TRADE
        pnl_eur = net_r * risk_eur
        equity = before + pnl_eur
        curve.append(equity)
        net_r_values.append(net_r)
        base_net_r_values.append(base_net_r)

        cost_r_used = components["total_leverage_cost_r"] if leverage_enabled else float(row.get("net_cost_r") or 0.0)
        total_cost_eur += cost_r_used * risk_eur
        flags = _risk_flags(row, leverage_enabled=leverage_enabled)
        if leverage_enabled and not flags["stop_inside_conservative_liquidation_buffer"]:
            liquid_buffer_breaches += 1

        trade_rows.append(
            {
                "policy_id": policy_id,
                "candidate_trade_number": idx,
                "trade_id": row.get("trade_id"),
                "symbol": row.get("symbol", "BTCUSDT"),
                "side": row.get("side"),
                "entry_time": row.get("entry_time"),
                "exit_time": row.get("exit_time"),
                "entry_price": row.get("entry_price"),
                "exit_price": row.get("exit_price"),
                "initial_stop": row.get("initial_stop"),
                "setup_class": quality["setup_class"],
                "convexity_label": quality["convexity_label"],
                "entry_score": quality["entry_score"],
                "compounding_readiness_score": quality["compounding_readiness_score"],
                "pullback_quality_score": quality["pullback_quality_score"],
                "high_confluence": quality["high_confluence"],
                "elite_only": quality["elite_only"],
                "leverage_enabled": leverage_enabled,
                "leverage": LEVERAGE if leverage_enabled else 1.0,
                "gross_r": gross_r,
                "base_normal_net_r": base_net_r,
                "leveraged_net_r": net_r,
                "incremental_net_r_vs_base": net_r - base_net_r,
                "stop_distance_fraction": row.get("stop_distance_fraction"),
                **components,
                **flags,
                "equity_before_trade": before,
                "risk_eur": risk_eur,
                "cost_eur": cost_r_used * risk_eur,
                "net_pnl_eur": pnl_eur,
                "equity_after_trade": equity,
            }
        )

    ending_equity = equity
    above_1m = ending_equity >= MISSION_TARGET_EUR
    return {
        "policy_id": policy_id,
        "starting_equity": start_capital,
        "ending_equity": ending_equity,
        "net_gain": ending_equity - start_capital,
        "return_multiple": _safe_ratio(ending_equity, start_capital, 0.0),
        "accepted_trades": len(rows),
        "leveraged_trades": leveraged_count,
        "unleveraged_trades": len(rows) - leveraged_count,
        "average_net_R": sum(net_r_values) / len(net_r_values) if net_r_values else 0.0,
        "median_net_R": median(net_r_values) if net_r_values else 0.0,
        "net_total_R": sum(net_r_values),
        "base_normal_net_total_R": sum(base_net_r_values),
        "incremental_net_R_vs_base": sum(net_r_values) - sum(base_net_r_values),
        "win_rate": _safe_ratio(sum(1 for value in net_r_values if value > 0.0), len(net_r_values), 0.0),
        "profit_factor": _profit_factor(net_r_values),
        "max_drawdown": _max_drawdown(curve),
        "largest_loss_R": min(net_r_values) if net_r_values else 0.0,
        "best_trade_R": max(net_r_values) if net_r_values else 0.0,
        "trades_flipped_win_to_loss_vs_base": sum(
            1 for row in trade_rows if float(row["base_normal_net_r"]) > 0.0 and float(row["leveraged_net_r"]) <= 0.0
        ),
        "trades_improved_vs_base": sum(1 for row in trade_rows if float(row["incremental_net_r_vs_base"]) > 0.0),
        "trades_damaged_vs_base": sum(1 for row in trade_rows if float(row["incremental_net_r_vs_base"]) < 0.0),
        "total_cost_eur": total_cost_eur,
        "liquidation_buffer_breaches": liquid_buffer_breaches,
        "ruin_or_negative_equity": any(value <= 0.0 for value in curve),
        "above_1m": above_1m,
        "equity_curve": curve,
        "trade_rows": trade_rows,
    }


def _policy_specs(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    activation_3y = _activation_start(rows, years_after_first_trade=3)

    def immediate(_row: dict[str, Any]) -> bool:
        return True

    def after_3y(row: dict[str, Any]) -> bool:
        ts = _entry_timestamp(row)
        return activation_3y is not None and pd.notna(ts) and ts >= activation_3y

    def after_3y_high_confluence(row: dict[str, Any]) -> bool:
        return after_3y(row) and bool(_setup_quality(row)["high_confluence"])

    def after_3y_elite_only(row: dict[str, Any]) -> bool:
        return after_3y(row) and bool(_setup_quality(row)["elite_only"])

    return {
        "immediate_2x_all_trades": {
            "description": "2x applied to every accepted candidate trade from the first trade.",
            "activation_start": None,
            "should_leverage": immediate,
        },
        "after_3y_2x_all_trades": {
            "description": "2x applied to every accepted candidate trade only after three years of chronological evidence.",
            "activation_start": activation_3y.isoformat() if activation_3y is not None else None,
            "should_leverage": after_3y,
        },
        "after_3y_2x_high_confluence": {
            "description": "2x after three years only for A/B, elite/strong convexity, entry_score>=4.0, compounding_readiness>=0.45.",
            "activation_start": activation_3y.isoformat() if activation_3y is not None else None,
            "should_leverage": after_3y_high_confluence,
        },
        "after_3y_2x_elite_only": {
            "description": "2x after three years only for setup A, elite convexity, entry_score>=4.5, pullback_quality>=0.75.",
            "activation_start": activation_3y.isoformat() if activation_3y is not None else None,
            "should_leverage": after_3y_elite_only,
        },
    }


def _rolling(rows: list[dict[str, Any]], policy_id: str, should_leverage_factory: Callable[[list[dict[str, Any]]], Callable[[dict[str, Any]], bool]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rolling_rows: list[dict[str, Any]] = []
    for idx, (start, end) in enumerate(_rolling_windows(), start=1):
        selected = [row for row in rows if pd.notna(_entry_timestamp(row)) and start <= _entry_timestamp(row) <= end]
        should_leverage = should_leverage_factory(selected)
        sim = _simulate_policy(selected, policy_id=policy_id, should_leverage=should_leverage)
        monthly, cagr = _period_growth(START_CAPITAL_25K, sim["ending_equity"], start.isoformat(), end.isoformat())
        rolling_rows.append(
            {
                "window_number": idx,
                "policy_id": policy_id,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "starting_equity": START_CAPITAL_25K,
                "ending_equity": sim["ending_equity"],
                "return_multiple": sim["return_multiple"],
                "monthly_growth": monthly,
                "cagr": cagr,
                "max_drawdown": sim["max_drawdown"],
                "profit_factor": sim["profit_factor"],
                "win_rate": sim["win_rate"],
                "accepted_trades": sim["accepted_trades"],
                "leveraged_trades": sim["leveraged_trades"],
                "net_total_R": sim["net_total_R"],
                "largest_loss_R": sim["largest_loss_R"],
                "above_1m": sim["ending_equity"] >= MISSION_TARGET_EUR,
                "ruin_or_negative_equity": sim["ruin_or_negative_equity"],
            }
        )
    endings = [float(row["ending_equity"]) for row in rolling_rows]
    dds = [float(row["max_drawdown"]) for row in rolling_rows]
    return rolling_rows, {
        "policy_id": policy_id,
        "window_count": len(rolling_rows),
        "average_ending_equity": sum(endings) / len(endings) if endings else 0.0,
        "median_ending_equity": median(endings) if endings else 0.0,
        "minimum_ending_equity": min(endings) if endings else 0.0,
        "maximum_ending_equity": max(endings) if endings else 0.0,
        "windows_above_1m": sum(1 for value in endings if value >= MISSION_TARGET_EUR),
        "worst_max_drawdown": max(dds) if dds else 0.0,
        "median_max_drawdown": median(dds) if dds else 0.0,
        "ruin_windows": sum(1 for row in rolling_rows if row["ruin_or_negative_equity"]),
        "best_window": max(rolling_rows, key=lambda row: float(row["ending_equity"])) if rolling_rows else None,
        "worst_window": min(rolling_rows, key=lambda row: float(row["ending_equity"])) if rolling_rows else None,
    }


def _rolling_policy_factory(policy_id: str) -> Callable[[list[dict[str, Any]]], Callable[[dict[str, Any]], bool]]:
    def factory(window_rows: list[dict[str, Any]]) -> Callable[[dict[str, Any]], bool]:
        return _policy_specs(window_rows)[policy_id]["should_leverage"]

    return factory


def _summary_policy_view(sim: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in sim.items() if key not in {"equity_curve", "trade_rows"}}


def _classify(best_policy: dict[str, Any], baseline: dict[str, Any], rolling_best: dict[str, Any], holdout_best: dict[str, Any]) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if best_policy["ruin_or_negative_equity"] or rolling_best["ruin_windows"] > 0:
        reasons.append("At least one tested path reached ruin or negative equity.")
        return FAILED, reasons
    if best_policy["max_drawdown"] > 0.20 or rolling_best["worst_max_drawdown"] > 0.20:
        reasons.append("2x leverage created drawdown above the 20% research safety threshold.")
        return FAILED, reasons
    if best_policy["ending_equity"] <= baseline["ending_equity"]:
        reasons.append("Best active 2x policy did not improve full-history equity after Bitpanda-style costs.")
        return WARNING, reasons
    if holdout_best["ending_equity"] <= START_CAPITAL_25K:
        reasons.append("Best 2x policy failed to remain profitable on sealed holdout.")
        return WARNING, reasons
    if rolling_best["windows_above_1m"] == 0:
        reasons.append("No rolling 5-year window reached EUR 1M after Bitpanda-style 2x costs.")
        return WARNING, reasons
    reasons.append("At least one 2x policy improved full-history and produced rolling EUR 1M evidence without ruin.")
    return PASSED, reasons


def _report(summary: dict[str, Any]) -> str:
    best = summary["best_policy"]
    return "\n".join(
        [
            "# Bitpanda 2x Leverage Stress Court 001",
            "",
            f"- Final classification: `{summary['final_classification']}`",
            f"- Candidate tested: `{summary['candidate_name']}`",
            f"- Best policy by full-history ending equity: `{best['policy_id']}`",
            f"- Full-history ending equity: `€{best['ending_equity']:,.2f}`",
            f"- Full-history max drawdown: `{best['max_drawdown']:.2%}`",
            f"- Sealed holdout ending equity under best policy: `€{summary['sealed_holdout_best_policy']['ending_equity']:,.2f}`",
            f"- Rolling 5Y windows above €1M under best policy: `{summary['rolling_5y_best_policy']['windows_above_1m']} / {summary['rolling_5y_best_policy']['window_count']}`",
            "",
            "## Cost model",
            "",
            f"- Leverage: `{LEVERAGE}x`",
            f"- Open fee: `{BITPANDA_MARGIN_OPEN_FEE_BPS} bps`",
            f"- Close fee: `{BITPANDA_MARGIN_CLOSE_FEE_BPS} bps`",
            f"- Funding: `{BITPANDA_MARGIN_FUNDING_DAILY_BPS} bps/day`, prorated by holding time",
            f"- Extra spread/slippage stress: `{ADDITIONAL_SPREAD_SLIPPAGE_BPS} bps`",
            "",
            "## Safety",
            "",
            "- Research-only diagnostic.",
            "- No strategy entries changed.",
            "- No strategy exits changed.",
            "- No paper/live/order/broker path enabled.",
            "- `paper_validation_ready=false`.",
        ]
    )


def run(config: LeverageCourtConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)

    candidate = _full_and_holdout(config.candidate_config)
    full_raw_engine_rows = _read_csv_rows(config.candidate_config.court_002_root / "research_only_eur25k_replay" / "raw_engine" / "trades.csv")
    holdout_raw_engine_rows = _read_csv_rows(config.candidate_config.court_002_root / "holdout_validation" / "raw_engine" / "trades.csv")
    full_rows = _enrich_candidate_rows(candidate["full_candidate"], full_raw_engine_rows)
    holdout_rows = _enrich_candidate_rows(candidate["holdout_candidate"], holdout_raw_engine_rows)
    baseline_full = _simulate_policy(full_rows, policy_id="baseline_normal_mixed_maker_taker_cost", should_leverage=lambda _row: False)
    baseline_holdout = _simulate_policy(holdout_rows, policy_id="baseline_normal_mixed_maker_taker_cost", should_leverage=lambda _row: False)

    full_policy_rows: list[dict[str, Any]] = []
    holdout_policy_rows: list[dict[str, Any]] = []
    rolling_summary_rows: list[dict[str, Any]] = []
    rolling_detail_rows: list[dict[str, Any]] = []
    policy_summaries: list[dict[str, Any]] = []

    specs = _policy_specs(full_rows)
    for policy_id, spec in specs.items():
        full_sim = _simulate_policy(full_rows, policy_id=policy_id, should_leverage=spec["should_leverage"])
        holdout_sim = _simulate_policy(holdout_rows, policy_id=policy_id, should_leverage=spec["should_leverage"])
        rolling_rows, rolling_summary = _rolling(full_rows, policy_id, _rolling_policy_factory(policy_id))
        full_policy_rows.extend(full_sim["trade_rows"])
        holdout_policy_rows.extend(holdout_sim["trade_rows"])
        rolling_detail_rows.extend(rolling_rows)
        rolling_summary_rows.append(rolling_summary)
        policy_summaries.append(
            {
                "policy_id": policy_id,
                "description": spec["description"],
                "activation_start": spec["activation_start"],
                "full_history": _summary_policy_view(full_sim),
                "sealed_holdout": _summary_policy_view(holdout_sim),
                "rolling_5y": rolling_summary,
            }
        )

    active_policy_summaries = [item for item in policy_summaries if int(item["full_history"]["leveraged_trades"]) > 0]
    best = max(active_policy_summaries or policy_summaries, key=lambda row: float(row["full_history"]["ending_equity"]))
    best_policy = best["full_history"]
    best_holdout = best["sealed_holdout"]
    best_rolling = best["rolling_5y"]
    final_classification, reasons = _classify(best_policy, _summary_policy_view(baseline_full), best_rolling, best_holdout)

    immediate_policy = next(item for item in policy_summaries if item["policy_id"] == "immediate_2x_all_trades")
    immediate_full = immediate_policy["full_history"]

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": final_classification,
        "classification_reasons": reasons,
        "candidate_name": CANDIDATE_NAME,
        "cost_model": {
            "model_name": "BITPANDA_STYLE_2X_MARGIN_STRESS_MODEL_RESEARCH_ONLY",
            "leverage": LEVERAGE,
            "open_fee_bps": BITPANDA_MARGIN_OPEN_FEE_BPS,
            "close_fee_bps": BITPANDA_MARGIN_CLOSE_FEE_BPS,
            "funding_daily_bps": BITPANDA_MARGIN_FUNDING_DAILY_BPS,
            "liquidation_fee_bps_reference_only": BITPANDA_MARGIN_LIQUIDATION_FEE_BPS,
            "additional_spread_slippage_bps": ADDITIONAL_SPREAD_SLIPPAGE_BPS,
            "funding_prorated_by_holding_time": True,
            "costs_applied_to_leveraged_notional": True,
            "baseline_normal_round_trip_bps": BASELINE_NORMAL_ROUND_TRIP_BPS,
            "source_note": "Bitpanda public margin fee schedule should be re-verified before any live work; this court is research-only.",
            "platform_feasibility_warning": (
                "Bitpanda support documentation currently says Margin Trading short positions are not yet available; "
                "2x results on short trades are therefore theoretical unless short-margin access is confirmed in the live account."
            ),
        },
        "baseline_normal_cost_candidate": {
            "full_history": _summary_policy_view(baseline_full),
            "sealed_holdout": _summary_policy_view(baseline_holdout),
        },
        "policy_results": policy_summaries,
        "best_policy": best_policy,
        "sealed_holdout_best_policy": best_holdout,
        "rolling_5y_best_policy": best_rolling,
        "interpretation": {
            "two_x_on_every_trade_is_safe": (
                immediate_full["ending_equity"] > baseline_full["ending_equity"]
                and immediate_full["max_drawdown"] <= 0.20
                and not immediate_full["ruin_or_negative_equity"]
            ),
            "two_x_every_trade_drawdown_under_20pct": immediate_full["max_drawdown"] <= 0.20,
            "two_x_every_trade_damages_equity_vs_baseline": immediate_full["ending_equity"] < baseline_full["ending_equity"],
            "two_x_every_trade_reaches_1m": immediate_full["ending_equity"] >= MISSION_TARGET_EUR,
            "best_policy_improves_full_history": best_policy["ending_equity"] > baseline_full["ending_equity"],
            "best_policy_preserves_profitable_holdout": best_holdout["ending_equity"] > START_CAPITAL_25K,
            "best_policy_restores_rolling_5y_1m": best_rolling["windows_above_1m"] > 0,
            "requires_new_forward_validation_before_live": True,
            "paper_validation_ready": False,
        },
        "strategy_changes": {
            "entries_changed": False,
            "exits_changed": False,
            "thresholds_tuned": False,
            "sizing_changed_in_live_scheduler": False,
            "leverage_is_diagnostic_overlay_only": True,
            "candidate_guard_changed": False,
            "candidate_guard_max_pre_entry_cost_r": MAX_PRE_ENTRY_COST_R,
        },
        "input_artifacts": {
            "candidate_summary": str(
                config.package_root
                / "output"
                / "cost_aware_frozen_candidate_rebuild_court_001"
                / "cost_aware_frozen_candidate_rebuild_summary.json"
            ),
            "court_002_full_history_trades": str(
                config.candidate_config.court_002_root / "research_only_eur25k_replay" / "raw_engine" / "trades.csv"
            ),
            "court_002_holdout_trades": str(config.candidate_config.court_002_root / "holdout_validation" / "raw_engine" / "trades.csv"),
        },
        "files_created": [
            str(config.output_root / "bitpanda_2x_leverage_stress_summary.json"),
            str(config.output_root / "bitpanda_2x_leverage_stress_report.md"),
            str(config.output_root / "policy_summary.csv"),
            str(config.output_root / "rolling_5y_policy_windows.csv"),
            str(config.output_root / "full_history_policy_trade_ledger.csv"),
            str(config.output_root / "holdout_policy_trade_ledger.csv"),
        ],
        **SAFETY_FLAGS,
    }

    _write_json(config.output_root / "bitpanda_2x_leverage_stress_summary.json", summary)
    (config.output_root / "bitpanda_2x_leverage_stress_report.md").write_text(_report(summary), encoding="utf-8")
    _write_csv(
        config.output_root / "policy_summary.csv",
        [
            {
                "policy_id": item["policy_id"],
                "description": item["description"],
                "activation_start": item["activation_start"],
                "full_history_ending_equity": item["full_history"]["ending_equity"],
                "full_history_max_drawdown": item["full_history"]["max_drawdown"],
                "full_history_profit_factor": item["full_history"]["profit_factor"],
                "full_history_win_rate": item["full_history"]["win_rate"],
                "full_history_leveraged_trades": item["full_history"]["leveraged_trades"],
                "holdout_ending_equity": item["sealed_holdout"]["ending_equity"],
                "holdout_max_drawdown": item["sealed_holdout"]["max_drawdown"],
                "holdout_leveraged_trades": item["sealed_holdout"]["leveraged_trades"],
                "rolling_average_ending_equity": item["rolling_5y"]["average_ending_equity"],
                "rolling_median_ending_equity": item["rolling_5y"]["median_ending_equity"],
                "rolling_max_ending_equity": item["rolling_5y"]["maximum_ending_equity"],
                "rolling_windows_above_1m": item["rolling_5y"]["windows_above_1m"],
                "rolling_worst_max_drawdown": item["rolling_5y"]["worst_max_drawdown"],
                "ruin_windows": item["rolling_5y"]["ruin_windows"],
            }
            for item in policy_summaries
        ],
    )
    _write_csv(config.output_root / "rolling_5y_policy_windows.csv", rolling_detail_rows)
    _write_csv(config.output_root / "full_history_policy_trade_ledger.csv", full_policy_rows)
    _write_csv(config.output_root / "holdout_policy_trade_ledger.csv", holdout_policy_rows)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Bitpanda-style 2x leverage stress court.")
    parser.parse_args()
    summary = run()
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
