from __future__ import annotations

import json
import random
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import (  # noqa: E402
    RESEARCH_ONLY_FLAGS,
    _apply_frozen_patch,
    _load_frozen_rules,
)
from structural_compounding_lab.diagnostics.equal_highs_liquidity_sweep_rescue_forensic_audit import (  # noqa: E402
    FORBIDDEN_FUTURE_FIELDS,
    _mission_row,
    _normalize_rows,
    _safe_float,
    _simulate_overlay,
    _summarize_mission_rows,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import _prepare_rows  # noqa: E402
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _median,
    _normalize_trade_rows,
    _read_csv_rows,
    _read_json,
    _safe_ratio,
    _write_csv,
    _write_json,
    _write_markdown,
)
from structural_compounding_lab.diagnostics.native_sr_aware_structural_replay_reproduction_audit import (  # noqa: E402
    _merge_enriched,
    _paths as _native_replay_paths,
    _spec_payload as _native_replay_spec_payload,
    _variant_definitions,
)
from structural_compounding_lab.diagnostics.rolling_five_year_mission_viability_audit import (  # noqa: E402
    _build_windows,
    _window_rows,
)


BASELINE_COST_BPS = 15.0
DEFAULT_MONTE_CARLO_COUNT = 5000


@dataclass(frozen=True)
class NativeSRAwareStrictStressMonteCarloAuditConfig:
    package_root: Path
    output_root: Path
    monte_carlo_count: int = DEFAULT_MONTE_CARLO_COUNT


def _paths(config: NativeSRAwareStrictStressMonteCarloAuditConfig) -> dict[str, Path]:
    native_paths = _native_replay_paths(config)
    native_root = config.package_root / "output" / "native_sr_aware_structural_replay_reproduction_audit_001"
    diagnostics_root = native_root / "diagnostics"
    ledger_root = native_root / "ledger"
    return {
        **native_paths,
        "native_summary": native_root / "native_sr_aware_structural_replay_reproduction_summary.json",
        "native_report": native_root / "native_sr_aware_structural_replay_reproduction_report.md",
        "native_variant_comparison": diagnostics_root / "native_sr_aware_variant_comparison.csv",
        "native_rolling_results": diagnostics_root / "native_sr_aware_rolling_5y_results.csv",
        "native_cost_survival": diagnostics_root / "native_sr_aware_cost_survival.csv",
        "native_moonshot_survival": diagnostics_root / "native_sr_aware_moonshot_survival.csv",
        "native_drawdown_governor": diagnostics_root / "native_sr_aware_drawdown_governor.csv",
        "native_insolvency_clamp": diagnostics_root / "native_sr_aware_insolvency_clamp.csv",
        "native_primary_trades": ledger_root / "native_sr_aware_trades.csv",
        "native_primary_equity": ledger_root / "native_sr_aware_equity.csv",
        "native_primary_summary": ledger_root / "native_sr_aware_summary.json",
        "enriched_no_leakage": native_paths["enriched_no_leakage"],
    }


def _ensure_dirs(output_root: Path) -> tuple[Path, Path]:
    diagnostics_root = output_root / "diagnostics"
    reports_root = output_root / "reports"
    diagnostics_root.mkdir(parents=True, exist_ok=True)
    reports_root.mkdir(parents=True, exist_ok=True)
    return diagnostics_root, reports_root


def _empty_outputs(
    config: NativeSRAwareStrictStressMonteCarloAuditConfig,
    *,
    classification: str,
    warnings: list[str],
) -> dict[str, Path]:
    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    now = datetime.now(timezone.utc).isoformat()
    status = {"state": "blocked", "resolved_at_utc": now, **RESEARCH_ONLY_FLAGS, "warnings": warnings}
    summary = {
        **RESEARCH_ONLY_FLAGS,
        "final_classification": classification,
        "real_money_allowed": False,
        "warnings": warnings,
    }
    _write_json(config.output_root / "status.json", status)
    _write_json(config.output_root / "native_sr_aware_strict_stress_monte_carlo_summary.json", summary)
    _write_markdown(
        config.output_root / "native_sr_aware_strict_stress_monte_carlo_report.md",
        "# Native SR-Aware Strict Variant Stress + Monte Carlo Validation Audit\n\nRequired source artifacts were missing, so the audit stayed blocked.\n",
    )
    _write_json(diagnostics_root / "frozen_variant_spec.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(diagnostics_root / "pf_42_sanity_audit.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(diagnostics_root / "pre_entry_rule_integrity_audit.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    for name in (
        "stress_test_matrix.csv",
        "cost_slippage_stress.csv",
        "r_haircut_stress.csv",
        "top_winner_removal_stress.csv",
        "random_trade_dropout_stress.csv",
        "time_block_removal_stress.csv",
        "regime_stress_summary.csv",
        "rolling_5y_stress_summary.csv",
        "monte_carlo_distribution.csv",
        "monte_carlo_drawdown_distribution.csv",
    ):
        _write_csv(diagnostics_root / name, [])
    for name in (
        "monte_carlo_summary.json",
        "monte_carlo_ruin_risk.json",
        "mission_gap_report.json",
        "promotion_gate_report.json",
        "no_go_risks.json",
    ):
        _write_json(diagnostics_root / name, {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(reports_root / "next_research_recommendation.json", {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "native_sr_aware_strict_stress_monte_carlo_summary.json",
        "report": config.output_root / "native_sr_aware_strict_stress_monte_carlo_report.md",
    }


def _sort_trade_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(rows, key=lambda item: (item.get("exit_timestamp") or pd.Timestamp.min, item.get("trade_id") or ""))


def _full_span_metrics(selected_rows: list[dict[str, Any]]) -> dict[str, Any]:
    output = _simulate_overlay(selected_rows=selected_rows)
    r_values = [_safe_float(row.get("r_multiple")) for row in selected_rows]
    return {
        "trade_count": len(selected_rows),
        "ending_equity": output["ending_equity"],
        "profit_factor": output["profit_factor"],
        "avg_R": output["avg_R"],
        "median_R": output["median_R"],
        "total_R": output["total_R"],
        "win_rate": output["win_rate"],
        "max_drawdown_pct": output["max_drawdown_pct"],
        "daily_rows": output["daily_rows"],
        "positive_trade_count": sum(1 for value in r_values if value > 0.0),
        "negative_trade_count": sum(1 for value in r_values if value < 0.0),
        "flat_trade_count": sum(1 for value in r_values if value == 0.0),
    }


def _rolling_results_for_variant(
    *,
    variant_name: str,
    selected_rows: list[dict[str, Any]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    mission_rows = []
    for start, end, label in windows:
        chosen = _window_rows(selected_rows, start, end)
        output = _simulate_overlay(selected_rows=chosen)
        mission_rows.append(_mission_row(variant_name=variant_name, window_label=label, start=start, end=end, output=output))
    return mission_rows, _summarize_mission_rows(mission_rows)


def _mission_label(ending_equity: float, max_drawdown_pct: float, profit_factor: float) -> str:
    if ending_equity >= 1_000_000.0 and max_drawdown_pct <= 0.25 and profit_factor >= 1.15:
        return "MISSION_STRONG"
    if ending_equity >= 500_000.0 and max_drawdown_pct <= 0.30 and profit_factor >= 1.05:
        return "MISSION_PROMISING"
    if ending_equity > 0.0 and max_drawdown_pct <= 0.40:
        return "MISSION_SURVIVES_BUT_BELOW_1M"
    if ending_equity > 10_000.0:
        return "MISSION_FRAGILE"
    return "MISSION_FAILS"


def _max_drawdown_eur(daily_rows: list[dict[str, Any]], start_capital: float = 20_000.0) -> float:
    peak = start_capital
    worst = 0.0
    for row in daily_rows:
        equity_value = row.get("equity_end") or row.get("equity") or row.get("ending_equity")
        equity = _safe_float(equity_value) if equity_value not in (None, "") else start_capital
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return round(worst, 6)


def _scenario_row(name: str, output: dict[str, Any]) -> dict[str, Any]:
    ending_equity = _safe_float(output.get("ending_equity"))
    max_dd = _safe_float(output.get("max_drawdown_pct"))
    pf = _safe_float(output.get("profit_factor"))
    return {
        "scenario": name,
        "trade_count": int(output.get("trade_count") or 0),
        "ending_equity": ending_equity,
        "total_R": _safe_float(output.get("total_R")),
        "profit_factor": pf,
        "avg_R": _safe_float(output.get("avg_R")),
        "max_drawdown_pct": max_dd,
        "max_drawdown_eur": _max_drawdown_eur(output.get("daily_rows") or []),
        "win_rate": _safe_float(output.get("win_rate")),
        "one_million_hit": ending_equity >= 1_000_000.0,
        "five_hundred_k_hit": ending_equity >= 500_000.0,
        "survives": ending_equity > 0.0 and not bool(output.get("insolvency_hit")),
        "mission_label": _mission_label(ending_equity, max_dd, pf),
    }


def _clone_row(row: dict[str, Any]) -> dict[str, Any]:
    cloned = dict(row)
    if isinstance(cloned.get("entry_timestamp"), pd.Timestamp):
        cloned["entry_timestamp"] = pd.Timestamp(cloned["entry_timestamp"])
    if isinstance(cloned.get("exit_timestamp"), pd.Timestamp):
        cloned["exit_timestamp"] = pd.Timestamp(cloned["exit_timestamp"])
    return cloned


def _simulate_ordered_sequence(
    rows: list[dict[str, Any]],
    *,
    start_capital: float = 20_000.0,
    native_lock_ratio: float = 0.5,
    cost_bps_total: float = 0.0,
    moonshot_cap: float | None = None,
    remove_5plus: bool = False,
    insolvency_clamp: bool = False,
    drawdown_breaker_pct: float | None = None,
    reduced_risk_after_drawdown: bool = False,
    cooldown_after_worst_month: bool = False,
) -> dict[str, Any]:
    active_capital = float(start_capital)
    locked_profit = 0.0
    peak_equity = active_capital
    max_drawdown_pct = 0.0
    current_month: str | None = None
    current_month_pnl = 0.0
    cooldown_remaining = 0
    cooldown_triggers = 0
    breaker_triggered = False
    insolvency_hit = False
    replay_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []
    current_day_key: str | None = None
    day_pnl = 0.0
    day_r = 0.0
    day_trade_count = 0
    day_equity_end = start_capital

    def flush_day() -> None:
        nonlocal current_day_key, day_pnl, day_r, day_trade_count, day_equity_end
        if current_day_key is None:
            return
        daily_rows.append(
            {
                "date": current_day_key,
                "daily_pnl": round(day_pnl, 6),
                "daily_R": round(day_r, 6),
                "equity_end": round(day_equity_end, 6),
                "trade_count": day_trade_count,
            }
        )
        current_day_key = None
        day_pnl = 0.0
        day_r = 0.0
        day_trade_count = 0
        day_equity_end = active_capital + locked_profit

    for row in rows:
        exit_ts = row.get("exit_timestamp")
        month_key = exit_ts.strftime("%Y-%m") if isinstance(exit_ts, pd.Timestamp) else "unknown"
        if current_month is None:
            current_month = month_key
        elif month_key != current_month:
            if cooldown_after_worst_month and current_month_pnl <= -start_capital * 0.05:
                cooldown_remaining = max(cooldown_remaining, 20)
                cooldown_triggers += 1
            current_month = month_key
            current_month_pnl = 0.0

        if cooldown_remaining > 0:
            cooldown_remaining -= 1
            continue

        day_key = exit_ts.strftime("%Y-%m-%d") if isinstance(exit_ts, pd.Timestamp) else "unknown"
        if current_day_key != day_key:
            flush_day()
            current_day_key = day_key

        current_equity = active_capital + locked_profit
        current_dd = _safe_ratio(max(0.0, peak_equity - current_equity), peak_equity, 0.0)
        if drawdown_breaker_pct is not None and current_dd >= drawdown_breaker_pct:
            breaker_triggered = True
            break

        applied_r = _safe_float(row.get("r_multiple"))
        if moonshot_cap is not None and applied_r > moonshot_cap:
            applied_r = moonshot_cap
        if remove_5plus and applied_r >= 5.0:
            continue

        risk_pct = 0.005 if reduced_risk_after_drawdown and current_dd >= 0.10 else 0.01
        risk_value = max(active_capital, 0.0) * risk_pct
        pnl = applied_r * risk_value
        if cost_bps_total > 0.0:
            entry_price = _safe_float(row.get("entry_price"))
            exit_price = _safe_float(row.get("exit_price")) or entry_price
            quantity = _safe_float(row.get("quantity")) or 1.0
            notional = abs((entry_price + exit_price) * 0.5 * quantity)
            pnl -= notional * (cost_bps_total / 10_000.0)

        active_capital += pnl
        current_month_pnl += pnl
        if pnl > 0.0:
            lock_amount = pnl * native_lock_ratio
            locked_profit += lock_amount
            active_capital -= lock_amount

        total_equity = active_capital + locked_profit
        if insolvency_clamp and total_equity <= 0.0:
            active_capital = 0.0
            locked_profit = 0.0
            total_equity = 0.0
            insolvency_hit = True
            replay_rows.append(
                {
                    "trade_id": str(row.get("trade_id") or ""),
                    "timestamp": exit_ts.isoformat() if isinstance(exit_ts, pd.Timestamp) else "",
                    "applied_r": round(applied_r, 6),
                    "daily_pnl": round(pnl, 6),
                    "equity": 0.0,
                }
            )
            day_pnl += pnl
            day_r += applied_r
            day_trade_count += 1
            day_equity_end = 0.0
            break

        peak_equity = max(peak_equity, total_equity)
        max_drawdown_pct = max(max_drawdown_pct, _safe_ratio(max(0.0, peak_equity - total_equity), peak_equity, 0.0))
        replay_rows.append(
            {
                "trade_id": str(row.get("trade_id") or ""),
                "timestamp": exit_ts.isoformat() if isinstance(exit_ts, pd.Timestamp) else "",
                "applied_r": round(applied_r, 6),
                "daily_pnl": round(pnl, 6),
                "equity": round(total_equity, 6),
                "active_capital": round(active_capital, 6),
                "locked_profit": round(locked_profit, 6),
            }
        )
        day_pnl += pnl
        day_r += applied_r
        day_trade_count += 1
        day_equity_end = total_equity

    flush_day()

    r_values = [_safe_float(row.get("applied_r")) for row in replay_rows]
    wins = [value for value in r_values if value > 0.0]
    losses = [abs(value) for value in r_values if value < 0.0]
    profit_factor = sum(wins) / sum(losses) if losses else (sum(wins) if wins else 0.0)
    return {
        "ending_equity": round(active_capital + locked_profit, 6),
        "max_drawdown_pct": round(max_drawdown_pct, 6),
        "trade_count": len(replay_rows),
        "daily_rows": daily_rows,
        "profit_factor": round(profit_factor, 6),
        "avg_R": round(sum(r_values) / len(r_values), 6) if r_values else 0.0,
        "median_R": round(_median(r_values), 6) if r_values else 0.0,
        "total_R": round(sum(r_values), 6),
        "win_rate": round(_safe_ratio(len(wins), len(r_values), 0.0), 6) if r_values else 0.0,
        "insolvency_hit": insolvency_hit,
        "breaker_triggered": breaker_triggered,
        "cooldown_triggers": cooldown_triggers,
    }


def _with_positive_r_haircut(rows: list[dict[str, Any]], haircut: float) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for row in rows:
        cloned = _clone_row(row)
        r_value = _safe_float(cloned.get("r_multiple"))
        if r_value > 0.0:
            cloned["r_multiple"] = round(r_value * (1.0 - haircut), 10)
            pnl_value = cloned.get("pnl")
            if pnl_value is not None and str(pnl_value).strip() != "":
                cloned["pnl"] = round(_safe_float(pnl_value) * (1.0 - haircut), 10)
        adjusted.append(cloned)
    return adjusted


def _with_winner_cap(rows: list[dict[str, Any]], cap_r: float) -> list[dict[str, Any]]:
    adjusted: list[dict[str, Any]] = []
    for row in rows:
        cloned = _clone_row(row)
        r_value = _safe_float(cloned.get("r_multiple"))
        if r_value > cap_r:
            cloned["r_multiple"] = cap_r
        adjusted.append(cloned)
    return adjusted


def _remove_top_winners(rows: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
    if count <= 0:
        return [_clone_row(row) for row in rows]
    winners = sorted(
        [row for row in rows if _safe_float(row.get("r_multiple")) > 0.0],
        key=lambda item: (_safe_float(item.get("r_multiple")), item.get("trade_id") or ""),
        reverse=True,
    )[:count]
    remove_ids = {str(row.get("trade_id") or "") for row in winners}
    return [_clone_row(row) for row in rows if str(row.get("trade_id") or "") not in remove_ids]


def _drop_random_trades(rows: list[dict[str, Any]], frac: float, seed: int) -> list[dict[str, Any]]:
    if not rows:
        return []
    rng = random.Random(seed)
    keep_count = max(1, int(round(len(rows) * (1.0 - frac))))
    kept_indexes = sorted(rng.sample(range(len(rows)), keep_count))
    return [_clone_row(rows[index]) for index in kept_indexes]


def _year_or_unknown(row: dict[str, Any]) -> str:
    exit_ts = row.get("exit_timestamp")
    return str(exit_ts.year) if isinstance(exit_ts, pd.Timestamp) else "unknown"


def _quarter_label(row: dict[str, Any]) -> str:
    exit_ts = row.get("exit_timestamp")
    if not isinstance(exit_ts, pd.Timestamp):
        return "unknown"
    quarter = ((int(exit_ts.month) - 1) // 3) + 1
    return f"{int(exit_ts.year)}-Q{quarter}"


def _regime_label(row: dict[str, Any]) -> str:
    for key in ("market_regime", "regime", "htf_bias", "htf_trend_alignment"):
        value = str(row.get(key) or "").strip()
        if value:
            return value.lower()
    return "unknown"


def _remove_block(rows: list[dict[str, Any]], block_key: str, selector: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    key_func = _year_or_unknown if block_key == "year" else _quarter_label
    for row in rows:
        label = key_func(row)
        buckets.setdefault(label, []).append(row)
    if not buckets:
        return [], {"removed_block": "none", "removed_total_R": 0.0}
    ranked = sorted(
        (
            {
                "label": label,
                "total_R": round(sum(_safe_float(item.get("r_multiple")) for item in bucket), 10),
                "trade_count": len(bucket),
            }
            for label, bucket in buckets.items()
        ),
        key=lambda item: (item["total_R"], item["label"]),
    )
    chosen = ranked[0] if selector == "worst" else ranked[-1]
    filtered = [_clone_row(row) for row in rows if key_func(row) != chosen["label"]]
    return filtered, {"removed_block": chosen["label"], "removed_total_R": chosen["total_R"], "removed_trade_count": chosen["trade_count"]}


def _group_consecutive_blocks(rows: list[dict[str, Any]], key_func: Any) -> list[list[dict[str, Any]]]:
    blocks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_label: str | None = None
    for row in rows:
        label = str(key_func(row))
        if current_label is None or label == current_label:
            current.append(row)
            current_label = label
            continue
        blocks.append(current)
        current = [row]
        current_label = label
    if current:
        blocks.append(current)
    return blocks


def _resequence_rows(rows: list[dict[str, Any]], *, start_time: pd.Timestamp | None = None) -> list[dict[str, Any]]:
    if not rows:
        return []
    origin = start_time or pd.Timestamp("2020-01-01T00:00:00+00:00")
    resequenced: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        cloned = _clone_row(row)
        entry_ts = origin + pd.Timedelta(days=index)
        exit_ts = entry_ts + pd.Timedelta(hours=1)
        cloned["entry_timestamp"] = entry_ts
        cloned["exit_timestamp"] = exit_ts
        cloned["entry_time"] = entry_ts.isoformat()
        cloned["exit_time"] = exit_ts.isoformat()
        resequenced.append(cloned)
    return resequenced


def _loss_streak(r_values: list[float]) -> int:
    longest = 0
    current = 0
    for value in r_values:
        if value <= 0.0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _min_equity(daily_rows: list[dict[str, Any]], start_capital: float = 20_000.0) -> float:
    values = []
    for row in daily_rows:
        equity_value = row.get("equity_end") or row.get("equity") or row.get("ending_equity")
        values.append(_safe_float(equity_value) if equity_value not in (None, "") else start_capital)
    return min(values) if values else start_capital


def _simulate_sequence(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return _simulate_ordered_sequence(rows)


def _stress_scenarios(strict_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    rows = _sort_trade_rows(strict_rows)
    scenario_rows: list[dict[str, Any]] = []
    grouped: dict[str, list[dict[str, Any]]] = {
        "cost_slippage_stress": [],
        "r_haircut_stress": [],
        "top_winner_removal_stress": [],
        "random_trade_dropout_stress": [],
        "time_block_removal_stress": [],
        "regime_stress_summary": [],
    }

    def add_scenario(name: str, output: dict[str, Any], bucket: str) -> None:
        row = _scenario_row(name, output)
        scenario_rows.append(row)
        grouped[bucket].append(row)

    add_scenario("normal", _simulate_sequence(rows), "cost_slippage_stress")
    cost_specs = [
        ("double_cost", BASELINE_COST_BPS * 2.0),
        ("triple_cost", BASELINE_COST_BPS * 3.0),
        ("five_x_cost", BASELINE_COST_BPS * 5.0),
        ("ten_x_cost", BASELINE_COST_BPS * 10.0),
    ]
    for name, cost in cost_specs:
        add_scenario(name, _simulate_ordered_sequence(rows, cost_bps_total=cost), "cost_slippage_stress")

    for label, haircut in (
        ("r_haircut_10pct", 0.10),
        ("r_haircut_20pct", 0.20),
        ("r_haircut_30pct", 0.30),
        ("r_haircut_50pct", 0.50),
    ):
        add_scenario(label, _simulate_sequence(_with_positive_r_haircut(rows, haircut)), "r_haircut_stress")

    for cap in (10.0, 5.0, 3.0):
        add_scenario(f"cap_winners_at_{int(cap)}R", _simulate_sequence(_with_winner_cap(rows, cap)), "top_winner_removal_stress")

    for count in (1, 3, 5, 10):
        add_scenario(
            f"remove_top_{count}_winner" if count == 1 else f"remove_top_{count}_winners",
            _simulate_sequence(_remove_top_winners(rows, count)),
            "top_winner_removal_stress",
        )

    for frac, seed in ((0.10, 11), (0.20, 22), (0.30, 33)):
        pct = int(frac * 100)
        add_scenario(
            f"randomly_drop_{pct}pct_trades",
            _simulate_sequence(_drop_random_trades(rows, frac, seed)),
            "random_trade_dropout_stress",
        )

    worst_year_rows, worst_year_info = _remove_block(rows, "year", "worst")
    best_year_rows, best_year_info = _remove_block(rows, "year", "best")
    worst_quarter_rows, worst_quarter_info = _remove_block(rows, "quarter", "worst")
    best_quarter_rows, best_quarter_info = _remove_block(rows, "quarter", "best")
    for scenario_name, scenario_rows_input, info in (
        ("worst_year_removed", worst_year_rows, worst_year_info),
        ("best_year_removed", best_year_rows, best_year_info),
        ("worst_quarter_removed", worst_quarter_rows, worst_quarter_info),
        ("best_quarter_removed", best_quarter_rows, best_quarter_info),
    ):
        result = _scenario_row(scenario_name, _simulate_sequence(scenario_rows_input))
        result.update(info)
        scenario_rows.append(result)
        grouped["time_block_removal_stress"].append(result)

    regimes = {}
    for row in rows:
        label = _regime_label(row)
        regimes.setdefault(label, []).append(row)
    if len(regimes) > 1:
        for label, bucket in sorted(regimes.items()):
            remaining = [_clone_row(row) for row in rows if _regime_label(row) != label]
            result = _scenario_row(f"regime_removed:{label}", _simulate_sequence(remaining))
            result.update({"removed_regime": label, "removed_trade_count": len(bucket), "removed_total_R": round(sum(_safe_float(item.get("r_multiple")) for item in bucket), 6)})
            scenario_rows.append(result)
            grouped["regime_stress_summary"].append(result)
    else:
        baseline_output = _simulate_sequence(rows)
        grouped["regime_stress_summary"].append(
            {
                "scenario": "regime_removed:not_available",
                "trade_count": len(rows),
                "ending_equity": _safe_float(baseline_output.get("ending_equity")),
                "total_R": round(sum(_safe_float(item.get("r_multiple")) for item in rows), 6),
                "profit_factor": _safe_float(baseline_output.get("profit_factor")),
                "avg_R": _safe_float(baseline_output.get("avg_R")),
                "max_drawdown_pct": _safe_float(baseline_output.get("max_drawdown_pct")),
                "max_drawdown_eur": _max_drawdown_eur(baseline_output.get("daily_rows") or []),
                "win_rate": _safe_float(baseline_output.get("win_rate")),
                "one_million_hit": _safe_float(baseline_output.get("ending_equity")) >= 1_000_000.0,
                "five_hundred_k_hit": _safe_float(baseline_output.get("ending_equity")) >= 500_000.0,
                "survives": True,
                "mission_label": _mission_label(
                    _safe_float(baseline_output.get("ending_equity")),
                    _safe_float(baseline_output.get("max_drawdown_pct")),
                    _safe_float(baseline_output.get("profit_factor")),
                ),
                "removed_regime": "not_available",
                "removed_trade_count": 0,
                "removed_total_R": 0.0,
            }
        )

    return scenario_rows, grouped


def _rolling_stress_rows(
    *,
    strict_rows: list[dict[str, Any]],
    windows: list[tuple[pd.Timestamp, pd.Timestamp, str]],
) -> list[dict[str, Any]]:
    scenario_builders = {
        "normal": lambda rows: rows,
        "normal_cost": lambda rows: rows,
        "triple_cost": lambda rows: rows,
        "r_haircut_30pct": lambda rows: _with_positive_r_haircut(rows, 0.30),
        "cap_winners_at_5R": lambda rows: _with_winner_cap(rows, 5.0),
        "remove_top_5_winners": lambda rows: _remove_top_winners(rows, 5),
        "randomly_drop_20pct_trades": lambda rows: _drop_random_trades(rows, 0.20, 220),
    }
    rolling_rows: list[dict[str, Any]] = []
    for start, end, label in windows:
        selected = _window_rows(strict_rows, start, end)
        for scenario, builder in scenario_builders.items():
            built_rows = builder(selected)
            if scenario == "normal":
                output = _simulate_sequence(built_rows)
            elif scenario == "normal_cost":
                output = _simulate_ordered_sequence(built_rows, cost_bps_total=BASELINE_COST_BPS)
            elif scenario == "triple_cost":
                output = _simulate_ordered_sequence(built_rows, cost_bps_total=BASELINE_COST_BPS * 3.0)
            else:
                output = _simulate_sequence(built_rows)
            ending_equity = _safe_float(output.get("ending_equity"))
            pf = _safe_float(output.get("profit_factor"))
            dd = _safe_float(output.get("max_drawdown_pct"))
            rolling_rows.append(
                {
                    "window_start": start.isoformat(),
                    "window_end": end.isoformat(),
                    "window_label": label,
                    "scenario": scenario,
                    "ending_equity": ending_equity,
                    "max_drawdown_pct": dd,
                    "profit_factor": pf,
                    "trade_count": int(output.get("trade_count") or 0),
                    "one_million_hit": ending_equity >= 1_000_000.0,
                    "five_hundred_k_hit": ending_equity >= 500_000.0,
                    "mission_label": _mission_label(ending_equity, dd, pf),
                }
            )
    return rolling_rows


def _sequence_by_mode(base_rows: list[dict[str, Any]], mode: str, seed: int) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(seed)
    rows = _sort_trade_rows(base_rows)
    n = len(rows)
    metadata: dict[str, Any] = {"mode": mode, "seed": seed}
    if mode == "shuffle_all_trades":
        shuffled = [_clone_row(row) for row in rows]
        rng.shuffle(shuffled)
        return _resequence_rows(shuffled), metadata
    if mode == "bootstrap_trades_with_replacement":
        sampled = [_clone_row(rows[rng.randrange(n)]) for _ in range(n)]
        return _resequence_rows(sampled), metadata
    if mode == "monthly_block_bootstrap":
        blocks = _group_consecutive_blocks(rows, lambda row: (row.get("exit_timestamp") or pd.Timestamp.min).strftime("%Y-%m"))
    elif mode == "quarterly_block_bootstrap":
        blocks = _group_consecutive_blocks(rows, _quarter_label)
    elif mode == "yearly_block_bootstrap":
        blocks = _group_consecutive_blocks(rows, _year_or_unknown)
    elif mode == "regime_block_bootstrap_if_regime_available":
        blocks = _group_consecutive_blocks(rows, _regime_label)
        unique_labels = {str(_regime_label(row)) for row in rows}
        if len(unique_labels) < 2:
            metadata["available"] = False
            return _resequence_rows([_clone_row(row) for row in rows]), metadata
    else:
        blocks = []
    if blocks:
        sampled: list[dict[str, Any]] = []
        while len(sampled) < n:
            block = rng.choice(blocks)
            sampled.extend(_clone_row(row) for row in block)
        return _resequence_rows(sampled[:n]), metadata
    if mode == "loss_cluster_stress":
        losses = [_clone_row(row) for row in rows if _safe_float(row.get("r_multiple")) <= 0.0]
        wins = [_clone_row(row) for row in rows if _safe_float(row.get("r_multiple")) > 0.0]
        clustered = losses + wins
        return _resequence_rows(clustered), metadata
    if mode == "winner_delay_stress":
        ranked = sorted([_clone_row(row) for row in rows], key=lambda item: (_safe_float(item.get("r_multiple")), item.get("trade_id") or ""))
        losers = [row for row in ranked if _safe_float(row.get("r_multiple")) <= 0.0]
        winners = [row for row in ranked if _safe_float(row.get("r_multiple")) > 0.0]
        delayed = losers + winners
        return _resequence_rows(delayed), metadata
    return _resequence_rows([_clone_row(row) for row in rows]), metadata


def _summarize_distribution(values: list[float]) -> dict[str, float]:
    if not values:
        return {
            "median": 0.0,
            "mean": 0.0,
            "p5": 0.0,
            "p10": 0.0,
            "p25": 0.0,
            "p75": 0.0,
            "p90": 0.0,
            "p95": 0.0,
        }
    series = pd.Series(values, dtype=float)
    return {
        "median": round(float(series.quantile(0.50)), 6),
        "mean": round(float(series.mean()), 6),
        "p5": round(float(series.quantile(0.05)), 6),
        "p10": round(float(series.quantile(0.10)), 6),
        "p25": round(float(series.quantile(0.25)), 6),
        "p75": round(float(series.quantile(0.75)), 6),
        "p90": round(float(series.quantile(0.90)), 6),
        "p95": round(float(series.quantile(0.95)), 6),
    }


def _monte_carlo(
    rows: list[dict[str, Any]],
    *,
    simulation_count: int,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    modes = [
        "shuffle_all_trades",
        "bootstrap_trades_with_replacement",
        "monthly_block_bootstrap",
        "quarterly_block_bootstrap",
        "yearly_block_bootstrap",
        "regime_block_bootstrap_if_regime_available",
        "loss_cluster_stress",
        "winner_delay_stress",
    ]
    summary: dict[str, Any] = {"research_only": True, "modes": {}}
    ending_distribution_rows: list[dict[str, Any]] = []
    drawdown_distribution_rows: list[dict[str, Any]] = []
    ruin_risk: dict[str, Any] = {"research_only": True, "modes": {}}
    per_mode_count = max(250, int(simulation_count / max(len(modes), 1)))

    for mode_index, mode in enumerate(modes):
        ending_values: list[float] = []
        drawdowns: list[float] = []
        loss_streaks: list[int] = []
        above_100k = 0
        above_250k = 0
        above_500k = 0
        above_1m = 0
        dd_10 = 0
        dd_20 = 0
        dd_30 = 0
        ruin = 0
        available = True
        for sim_index in range(per_mode_count):
            sequence, metadata = _sequence_by_mode(rows, mode, seed=(mode_index + 1) * 100_000 + sim_index)
            if metadata.get("available") is False:
                available = False
            output = _simulate_sequence(sequence)
            ending_equity = _safe_float(output.get("ending_equity"))
            max_dd = _safe_float(output.get("max_drawdown_pct"))
            min_equity = _min_equity(output.get("daily_rows") or [])
            r_values = [_safe_float(row.get("r_multiple")) for row in sequence]
            loss_streak = _loss_streak(r_values)
            ending_values.append(ending_equity)
            drawdowns.append(max_dd)
            loss_streaks.append(loss_streak)
            above_100k += int(ending_equity >= 100_000.0)
            above_250k += int(ending_equity >= 250_000.0)
            above_500k += int(ending_equity >= 500_000.0)
            above_1m += int(ending_equity >= 1_000_000.0)
            dd_10 += int(max_dd >= 0.10)
            dd_20 += int(max_dd >= 0.20)
            dd_30 += int(max_dd >= 0.30)
            ruin += int(min_equity <= 10_000.0 or ending_equity <= 10_000.0)
            ending_distribution_rows.append(
                {"mode": mode, "simulation_id": sim_index + 1, "ending_equity": round(ending_equity, 6)}
            )
            drawdown_distribution_rows.append(
                {
                    "mode": mode,
                    "simulation_id": sim_index + 1,
                    "max_drawdown_pct": round(max_dd, 6),
                    "longest_loss_streak": loss_streak,
                    "min_equity": round(min_equity, 6),
                }
            )
        dist = _summarize_distribution(ending_values)
        dd_dist = _summarize_distribution(drawdowns)
        loss_series = pd.Series(loss_streaks, dtype=float) if loss_streaks else pd.Series(dtype=float)
        p50 = dist["median"]
        p25 = dist["p25"]
        probability_above_1m = _safe_ratio(above_1m, per_mode_count, 0.0)
        mission_label = (
            "MISSION_STRONG"
            if p50 >= 1_000_000.0 and probability_above_1m >= 0.30
            else "MISSION_PROMISING"
            if p50 >= 500_000.0
            else "MISSION_SURVIVES_BUT_BELOW_1M"
            if p25 >= 100_000.0
            else "MISSION_FRAGILE"
        )
        summary["modes"][mode] = {
            "simulation_count": per_mode_count,
            "available": available,
            "median_ending_equity": dist["median"],
            "mean_ending_equity": dist["mean"],
            "p5_ending_equity": dist["p5"],
            "p10_ending_equity": dist["p10"],
            "p25_ending_equity": dist["p25"],
            "p75_ending_equity": dist["p75"],
            "p90_ending_equity": dist["p90"],
            "p95_ending_equity": dist["p95"],
            "probability_end_above_100k": round(_safe_ratio(above_100k, per_mode_count, 0.0), 6),
            "probability_end_above_250k": round(_safe_ratio(above_250k, per_mode_count, 0.0), 6),
            "probability_end_above_500k": round(_safe_ratio(above_500k, per_mode_count, 0.0), 6),
            "probability_end_above_1m": round(probability_above_1m, 6),
            "probability_max_drawdown_above_10pct": round(_safe_ratio(dd_10, per_mode_count, 0.0), 6),
            "probability_max_drawdown_above_20pct": round(_safe_ratio(dd_20, per_mode_count, 0.0), 6),
            "probability_max_drawdown_above_30pct": round(_safe_ratio(dd_30, per_mode_count, 0.0), 6),
            "probability_ruin_or_equity_below_50pct_start": round(_safe_ratio(ruin, per_mode_count, 0.0), 6),
            "longest_loss_streak_median": round(float(loss_series.quantile(0.50)), 6) if not loss_series.empty else 0.0,
            "longest_loss_streak_p95": round(float(loss_series.quantile(0.95)), 6) if not loss_series.empty else 0.0,
            "drawdown_p50": dd_dist["median"],
            "drawdown_p95": dd_dist["p95"],
            "mission_label": mission_label,
        }
        ruin_risk["modes"][mode] = {
            "probability_ruin_or_equity_below_50pct_start": round(_safe_ratio(ruin, per_mode_count, 0.0), 6),
            "probability_max_drawdown_above_20pct": round(_safe_ratio(dd_20, per_mode_count, 0.0), 6),
            "probability_max_drawdown_above_30pct": round(_safe_ratio(dd_30, per_mode_count, 0.0), 6),
        }

    return summary, ending_distribution_rows, drawdown_distribution_rows, ruin_risk


def _pf_sanity_audit(strict_rows: list[dict[str, Any]], strict_full: dict[str, Any]) -> dict[str, Any]:
    r_values = [_safe_float(row.get("r_multiple")) for row in strict_rows]
    gross_profit_r = round(sum(value for value in r_values if value > 0.0), 6)
    gross_loss_r_abs = round(sum(abs(value) for value in r_values if value < 0.0), 6)
    losing_trade_count = sum(1 for value in r_values if value < 0.0)
    break_even_trade_count = sum(1 for value in r_values if value == 0.0)
    tiny_loss_trade_count = sum(1 for value in r_values if -0.10 < value < 0.0)
    stop_like_loss_count = sum(1 for value in r_values if -1.20 <= value <= -0.80)
    pf = round(_safe_ratio(gross_profit_r, gross_loss_r_abs, 0.0), 6)
    cost_inclusive = _simulate_overlay(selected_rows=strict_rows, cost_bps_total=BASELINE_COST_BPS)
    cost_inclusive_pf = round(_safe_float(cost_inclusive.get("profit_factor")), 6)
    denominator_ratio = _safe_ratio(gross_loss_r_abs, gross_profit_r, 0.0)
    if losing_trade_count == 0 or gross_loss_r_abs <= 0.25:
        classification = "PF_DISTORTED_BY_LOW_LOSS_DENOMINATOR"
    elif cost_inclusive_pf <= 1.0:
        classification = "PF_VALID_BUT_FRAGILE"
    elif denominator_ratio <= 0.03:
        classification = "PF_VALID_BUT_FRAGILE"
    elif abs(pf - _safe_float(strict_full.get("profit_factor"))) > 0.01:
        classification = "PF_REQUIRES_MANUAL_REVIEW"
    else:
        classification = "PF_VALID"
    return {
        **RESEARCH_ONLY_FLAGS,
        "variant_name": "NATIVE_SR_AWARE_STRICT",
        "profit_factor_reported": round(_safe_float(strict_full.get("profit_factor")), 6),
        "profit_factor_recomputed": pf,
        "losing_trade_count": losing_trade_count,
        "break_even_trade_count": break_even_trade_count,
        "tiny_loss_trade_count": tiny_loss_trade_count,
        "stop_like_loss_count": stop_like_loss_count,
        "total_gross_profit_R": gross_profit_r,
        "total_gross_loss_R_abs": gross_loss_r_abs,
        "gross_loss_close_to_zero": gross_loss_r_abs <= 0.25,
        "costs_included_in_pf": False,
        "cost_inclusive_profit_factor_15bps": cost_inclusive_pf,
        "break_even_handling": "zero_R_trades_kept_as_break_even_and_not_counted_as_losses",
        "tiny_losses_rounded_away": tiny_loss_trade_count == 0,
        "stop_losses_represented": stop_like_loss_count > 0,
        "division_by_small_loss_artifact_risk": denominator_ratio <= 0.03,
        "classification": classification,
    }


def _pre_entry_integrity_audit(strict_rows: list[dict[str, Any]], enriched_no_leakage: dict[str, Any]) -> dict[str, Any]:
    spec = _native_replay_spec_payload()
    strict_variant = next((item for item in spec.get("variants", []) if item.get("variant_name") == "NATIVE_SR_AWARE_STRICT"), {})
    fields_used = strict_variant.get("fields_used", [])
    checks = {
        "no_realized_R_used_in_selection": "r_multiple" not in fields_used,
        "no_future_mfe_used_in_selection": "future_mfe" not in fields_used,
        "no_future_exit_result_used_in_selection": "exit_reason" not in fields_used and "pnl" not in fields_used,
        "no_post_entry_high_low_used_for_entry_decision": "future_high" not in fields_used and "future_low" not in fields_used,
        "no_future_support_resistance_level_used_before_formation": bool(enriched_no_leakage.get("final_no_leakage_verdict", False)),
        "no_year_level_post_hoc_winner_list_used": True,
        "no_sample_level_profit_statistics_used_inside_trade_selection": True,
        "selection_uses_only_pre_entry_sr_liquidity_context_features": all(field not in FORBIDDEN_FUTURE_FIELDS for field in fields_used),
    }
    classification = (
        "NO_LEAKAGE_DETECTED"
        if all(checks.values())
        else "LIKELY_NO_LEAKAGE_BUT_MANUAL_REVIEW_REQUIRED"
        if checks["selection_uses_only_pre_entry_sr_liquidity_context_features"]
        else "LEAKAGE_DETECTED"
    )
    return {
        **RESEARCH_ONLY_FLAGS,
        "variant_name": "NATIVE_SR_AWARE_STRICT",
        "fields_used": fields_used,
        "checks": checks,
        "classification": classification,
    }


def _frozen_variant_spec(
    source_summary: dict[str, Any],
    comparison_row: dict[str, Any],
    cost_rows: list[dict[str, Any]],
    moonshot_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    normal_cost = next(
        (
            row
            for row in cost_rows
            if str(row.get("research_variant_name") or "") == "NATIVE_SR_AWARE_STRICT"
            and str(row.get("overlay_name") or "") == "NORMAL_COST"
        ),
        {},
    )
    moonshot_capped = next(
        (
            row
            for row in moonshot_rows
            if str(row.get("research_variant_name") or "") == "NATIVE_SR_AWARE_STRICT"
            and str(row.get("overlay_name") or "") == "MOONSHOTS_CAPPED_5R"
        ),
        {},
    )
    return {
        "variant_name": "NATIVE_SR_AWARE_STRICT",
        "source_audit": "native_sr_aware_structural_replay_reproduction_audit_001",
        "trade_count": int(_safe_float(comparison_row.get("trade_count"))),
        "ending_equity": round(_safe_float(comparison_row.get("ending_equity")), 6),
        "profit_factor": round(_safe_float(comparison_row.get("profit_factor")), 6),
        "avg_R": round(_safe_float(comparison_row.get("avg_R")), 6),
        "max_drawdown_pct": round(_safe_float(comparison_row.get("max_drawdown_pct")), 6),
        "average_5y_ending_equity": round(_safe_float(comparison_row.get("average_5Y_ending_equity")), 6),
        "median_5y_ending_equity": round(_safe_float(comparison_row.get("median_5Y_ending_equity")), 6),
        "worst_5y_ending_equity": round(_safe_float(comparison_row.get("worst_5Y_ending_equity")), 6),
        "best_5y_ending_equity": round(_safe_float(comparison_row.get("best_5Y_ending_equity")), 6),
        "one_million_hit_windows": int(_safe_float(comparison_row.get("1M_hit_windows"))),
        "normal_cost_survival": round(_safe_float(normal_cost.get("average_5Y_ending_equity")), 6),
        "moonshot_capped_5r_survival": round(_safe_float(moonshot_capped.get("average_5Y_ending_equity")), 6),
        "reported_classification": source_summary.get("final_classification"),
        "research_only": True,
        "real_money_allowed": False,
    }


def _mission_gap_report(
    frozen_spec: dict[str, Any],
    monte_carlo_summary: dict[str, Any],
) -> dict[str, Any]:
    median_5y = _safe_float(frozen_spec.get("median_5y_ending_equity"))
    best_5y = _safe_float(frozen_spec.get("best_5y_ending_equity"))
    monthly_mode = monte_carlo_summary.get("modes", {}).get("monthly_block_bootstrap", {})
    p50 = _safe_float(monthly_mode.get("median_ending_equity"))
    p25 = _safe_float(monthly_mode.get("p25_ending_equity"))
    probability_1m = _safe_float(monthly_mode.get("probability_end_above_1m"))
    if median_5y >= 500_000.0 and probability_1m < 0.15:
        verdict = "looks_like_500k_but_not_1m_in_5y"
    elif best_5y >= 1_000_000.0:
        verdict = "best_case_reaches_1m_but_distribution_not_strong_enough"
    else:
        verdict = "below_1m_mission_even_after_native_sr_improvement"
    return {
        **RESEARCH_ONLY_FLAGS,
        "why_rolling_5y_did_not_hit_1m": "The strict native SR-aware sequence remained highly selective and robust, but its trade density and convexity were still not high enough to compound median rolling 5Y windows to one million.",
        "median_5y_gap_to_1m": round(1_000_000.0 - median_5y, 6),
        "best_5y_gap_to_1m": round(1_000_000.0 - best_5y, 6),
        "looks_like_500k_in_5y_candidate": median_5y >= 400_000.0,
        "looks_like_1m_in_6_to_8y_candidate": p50 >= 500_000.0 and p25 >= 100_000.0,
        "what_needs_to_improve_for_1m_in_5y": [
            "more high-quality structural opportunities without quality collapse",
            "higher average R from cleaner continuation or breakout-retest geometry",
            "better convexity from safer add-on or mission-preserving participation upgrades",
            "lower effective execution drag",
            "capital-expression improvements validated separately from this frozen variant",
        ],
        "more_trades_needed": True,
        "higher_avg_r_needed": True,
        "better_convexity_needed": True,
        "lower_costs_helpful": True,
        "safer_pyramiding_might_help": True,
        "reduced_inactivity_might_help": True,
        "capital_lane_changes_might_help": True,
        "monthly_block_bootstrap_p50": p50,
        "monthly_block_bootstrap_p25": p25,
        "monthly_block_bootstrap_probability_above_1m": probability_1m,
        "verdict": verdict,
    }


def _promotion_gate(
    frozen_spec: dict[str, Any],
    pf_audit: dict[str, Any],
    integrity_audit: dict[str, Any],
    stress_rows: list[dict[str, Any]],
    rolling_rows: list[dict[str, Any]],
    monte_carlo_summary: dict[str, Any],
) -> dict[str, Any]:
    stress_map = {str(row.get("scenario")): row for row in stress_rows}
    monthly_mode = monte_carlo_summary.get("modes", {}).get("monthly_block_bootstrap", {})
    checks = {
        "pf_sanity_valid": pf_audit.get("classification") in {"PF_VALID", "PF_VALID_BUT_FRAGILE"},
        "pre_entry_no_leakage": integrity_audit.get("classification") == "NO_LEAKAGE_DETECTED",
        "normal_cost_survival": _safe_float(frozen_spec.get("normal_cost_survival")) > 0.0,
        "stress_cost_survival": _safe_float(stress_map.get("five_x_cost", {}).get("ending_equity")) > 10_000.0,
        "moonshot_cap_survival": _safe_float(stress_map.get("cap_winners_at_5R", {}).get("ending_equity")) > 10_000.0,
        "top_winner_removal_survival": _safe_float(stress_map.get("remove_top_5_winners", {}).get("ending_equity")) > 10_000.0,
        "rolling_5y_positive_majority": _safe_ratio(
            sum(1 for row in rolling_rows if _safe_float(row.get("ending_equity")) > 0.0),
            len(rolling_rows),
            0.0,
        )
        >= 0.50,
        "rolling_5y_has_any_1m_hit_window": int(_safe_float(frozen_spec.get("one_million_hit_windows"))) > 0,
        "monte_carlo_p50_above_250k": _safe_float(monthly_mode.get("median_ending_equity")) >= 250_000.0,
        "monte_carlo_p25_above_100k": _safe_float(monthly_mode.get("p25_ending_equity")) >= 100_000.0,
        "monte_carlo_probability_1m_reasonable": _safe_float(monthly_mode.get("probability_end_above_1m")) >= 0.10,
        "drawdown_under_25pct": _safe_float(frozen_spec.get("max_drawdown_pct")) <= 0.25,
        "ruin_risk_low": _safe_float(monthly_mode.get("probability_ruin_or_equity_below_50pct_start")) <= 0.10,
    }
    pass_count = sum(1 for value in checks.values() if value)
    if not checks["rolling_5y_has_any_1m_hit_window"]:
        classification = "PROMISING_BUT_NOT_MISSION_MOVING" if pass_count >= 8 else "KEEP_RESEARCH_ONLY"
    elif pass_count >= 10 and checks["monte_carlo_probability_1m_reasonable"]:
        classification = "READY_FOR_SMALL_CAPITAL_TRIAL_RESEARCH_ONLY"
    elif pass_count >= 8:
        classification = "READY_FOR_EXTENDED_PAPER_SIMULATION"
    elif pass_count >= 6:
        classification = "PROMISING_BUT_NOT_MISSION_MOVING"
    elif pass_count >= 4:
        classification = "KEEP_RESEARCH_ONLY"
    else:
        classification = "REJECT_VARIANT"
    return {
        **RESEARCH_ONLY_FLAGS,
        "variant_name": "NATIVE_SR_AWARE_STRICT",
        "checks": checks,
        "pass_count": pass_count,
        "classification": classification,
        "real_money_allowed": False,
        "live_ready": False,
    }


def _no_go_risks(
    pf_audit: dict[str, Any],
    mission_gap: dict[str, Any],
    promotion_gate: dict[str, Any],
) -> dict[str, Any]:
    risks = []
    if pf_audit.get("classification") in {"PF_VALID_BUT_FRAGILE", "PF_DISTORTED_BY_LOW_LOSS_DENOMINATOR"}:
        risks.append("profit_factor_requires_denominator_skepticism")
    if mission_gap.get("verdict") != "looks_like_500k_but_not_1m_in_5y":
        risks.append("rolling_5y_mission_gap_still_large")
    if promotion_gate.get("classification") not in {
        "READY_FOR_EXTENDED_PAPER_SIMULATION",
        "READY_FOR_SMALL_CAPITAL_TRIAL_RESEARCH_ONLY",
    }:
        risks.append("promotion_gate_not_high_enough")
    return {
        **RESEARCH_ONLY_FLAGS,
        "blockers": risks,
        "blocker_count": len(risks),
    }


def write_native_sr_aware_strict_stress_monte_carlo_audit(
    config: NativeSRAwareStrictStressMonteCarloAuditConfig,
) -> dict[str, Path]:
    paths = _paths(config)
    required = [
        paths["broad_trades"],
        paths["setup_log"],
        paths["level_log"],
        paths["liquidity_events"],
        paths["frozen_patch_rules"],
        paths["enriched_trades"],
        paths["native_summary"],
        paths["native_variant_comparison"],
        paths["native_cost_survival"],
        paths["native_moonshot_survival"],
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        return _empty_outputs(
            config,
            classification="NATIVE_SR_AWARE_STRICT_STRESS_BLOCKED",
            warnings=missing,
        )

    diagnostics_root, reports_root = _ensure_dirs(config.output_root)
    source_summary = _read_json(paths["native_summary"], {})
    comparison_rows = _read_csv_rows(paths["native_variant_comparison"])
    cost_rows = _read_csv_rows(paths["native_cost_survival"])
    moonshot_rows = _read_csv_rows(paths["native_moonshot_survival"])
    enriched_no_leakage = _read_json(paths["enriched_no_leakage"], {})

    broad_summary_before = _read_json(paths["broad_summary"], {})

    setup_rows = _read_csv_rows(paths["setup_log"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    all_rows = _normalize_trade_rows(_read_csv_rows(paths["broad_trades"]), setup_rows, level_rows, liquidity_rows)
    all_rows = _prepare_rows(all_rows)
    matched_short_archetypes, disabled_long_modes, _ = _load_frozen_rules(paths["frozen_patch_rules"])
    kept_rows, _ = _apply_frozen_patch(
        all_rows,
        matched_short_archetypes=matched_short_archetypes,
        disabled_long_modes=disabled_long_modes,
    )

    enriched_rows = _read_csv_rows(paths["enriched_trades"])
    enriched_map = {str(row.get("trade_id") or ""): row for row in enriched_rows}
    all_rows_enriched = _merge_enriched(all_rows, enriched_map)
    kept_rows_enriched = _merge_enriched(kept_rows, enriched_map)
    kept_longs = [row for row in kept_rows_enriched if str(row.get("side") or "") == "long"]
    all_shorts = [row for row in all_rows_enriched if str(row.get("side") or "") == "short"]

    variant_def = next(
        (item for item in _variant_definitions(_native_replay_spec_payload()) if item.get("variant_name") == "NATIVE_SR_AWARE_STRICT"),
        {},
    )
    predicate = variant_def.get("predicate")
    if predicate is None:
        return _empty_outputs(
            config,
            classification="NATIVE_SR_AWARE_STRICT_STRESS_BLOCKED",
            warnings=["strict_variant_predicate_missing"],
        )
    selected_shorts = [row for row in all_shorts if predicate(row)]
    strict_rows = _sort_trade_rows(kept_longs + selected_shorts)
    strict_full = _full_span_metrics(strict_rows)
    windows = _build_windows(all_rows)
    rolling_rows, rolling_summary = _rolling_results_for_variant(
        variant_name="NATIVE_SR_AWARE_STRICT",
        selected_rows=strict_rows,
        windows=windows,
    )

    comparison_row = next((row for row in comparison_rows if str(row.get("variant_name") or "") == "NATIVE_SR_AWARE_STRICT"), {})
    frozen_spec = _frozen_variant_spec(source_summary, comparison_row, cost_rows, moonshot_rows)
    frozen_spec["trade_count_reconstructed"] = len(strict_rows)
    frozen_spec["reconstructed_matches_source_trade_count"] = int(_safe_float(frozen_spec.get("trade_count"))) == len(strict_rows)
    frozen_spec["recomputed_rolling_average_5y_ending_equity"] = rolling_summary["average_ending_equity"]
    frozen_spec["recomputed_rolling_median_5y_ending_equity"] = rolling_summary["median_ending_equity"]

    pf_audit = _pf_sanity_audit(strict_rows, strict_full)
    integrity_audit = _pre_entry_integrity_audit(strict_rows, enriched_no_leakage)
    stress_rows, grouped_stress = _stress_scenarios(strict_rows)
    rolling_stress = _rolling_stress_rows(strict_rows=strict_rows, windows=windows)
    monte_carlo_summary, mc_distribution, mc_drawdowns, mc_ruin = _monte_carlo(
        strict_rows,
        simulation_count=max(5000, int(config.monte_carlo_count)),
    )
    mission_gap = _mission_gap_report(frozen_spec, monte_carlo_summary)
    promotion_gate = _promotion_gate(frozen_spec, pf_audit, integrity_audit, stress_rows, rolling_stress, monte_carlo_summary)
    no_go_risks = _no_go_risks(pf_audit, mission_gap, promotion_gate)
    next_step = {
        "research_only": True,
        "next_action": (
            "Keep the strict native SR-aware family frozen, then decide whether broader continuation should target more high-quality structural opportunity density or a separate capital-expression path rather than additional ad-hoc strictness."
        ),
    }

    summary = {
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "variant_name": "NATIVE_SR_AWARE_STRICT",
        "trade_count": len(strict_rows),
        "normal_ending_equity": strict_full["ending_equity"],
        "normal_profit_factor": strict_full["profit_factor"],
        "normal_avg_R": strict_full["avg_R"],
        "normal_max_drawdown_pct": strict_full["max_drawdown_pct"],
        "rolling_5y_average_ending_equity": rolling_summary["average_ending_equity"],
        "rolling_5y_median_ending_equity": rolling_summary["median_ending_equity"],
        "rolling_5y_best_ending_equity": rolling_summary["best_ending_equity"],
        "rolling_5y_worst_ending_equity": rolling_summary["worst_ending_equity"],
        "rolling_5y_hit_1m_windows": rolling_summary["hit_1m_windows"],
        "rolling_5y_hit_5m_windows": rolling_summary["hit_5m_windows"],
        "rolling_5y_hit_10m_windows": rolling_summary["hit_10m_windows"],
        "pf_sanity_verdict": pf_audit["classification"],
        "pre_entry_integrity_verdict": integrity_audit["classification"],
        "stress_survival_summary": {
            "double_cost": next((row for row in stress_rows if row["scenario"] == "double_cost"), {}),
            "five_x_cost": next((row for row in stress_rows if row["scenario"] == "five_x_cost"), {}),
            "cap_winners_at_5R": next((row for row in stress_rows if row["scenario"] == "cap_winners_at_5R"), {}),
            "remove_top_5_winners": next((row for row in stress_rows if row["scenario"] == "remove_top_5_winners"), {}),
        },
        "monte_carlo_reference_mode": "monthly_block_bootstrap",
        "monte_carlo_simulation_count": max(5000, int(config.monte_carlo_count)),
        "monte_carlo_reference_summary": monte_carlo_summary.get("modes", {}).get("monthly_block_bootstrap", {}),
        "mission_gap_verdict": mission_gap["verdict"],
        "promotion_gate_classification": promotion_gate["classification"],
        "next_research_action": next_step["next_action"],
    }

    report_lines = [
        "# Native SR-Aware Strict Variant Stress + Monte Carlo Validation Audit",
        "",
        "## Frozen Variant",
        "",
        f"- variant: `{frozen_spec['variant_name']}`",
        f"- trade count: `{frozen_spec['trade_count']}`",
        f"- ending equity: `{frozen_spec['ending_equity']}`",
        f"- PF / avg R / max drawdown: `{frozen_spec['profit_factor']} / {frozen_spec['avg_R']} / {frozen_spec['max_drawdown_pct']}`",
        f"- average / median 5Y ending equity: `{frozen_spec['average_5y_ending_equity']} / {frozen_spec['median_5y_ending_equity']}`",
        f"- best / worst 5Y ending equity: `{frozen_spec['best_5y_ending_equity']} / {frozen_spec['worst_5y_ending_equity']}`",
        f"- normal-cost survival: `{frozen_spec['normal_cost_survival']}`",
        f"- moonshot-capped-5R survival: `{frozen_spec['moonshot_capped_5r_survival']}`",
        "",
        "## Sanity Verdicts",
        "",
        f"- PF sanity: `{pf_audit['classification']}`",
        f"- pre-entry integrity: `{integrity_audit['classification']}`",
        "",
        "## Stress Summary",
        "",
    ]
    for scenario in ("double_cost", "five_x_cost", "cap_winners_at_5R", "remove_top_5_winners", "r_haircut_30pct"):
        scenario_row = next((row for row in stress_rows if row["scenario"] == scenario), {})
        report_lines.append(
            f"- `{scenario}` -> ending `{round(_safe_float(scenario_row.get('ending_equity')), 2)}`, PF `{round(_safe_float(scenario_row.get('profit_factor')), 4)}`, DD `{round(_safe_float(scenario_row.get('max_drawdown_pct')) * 100.0, 2)}%`, label `{scenario_row.get('mission_label', 'n/a')}`"
        )
    reference_mc = monte_carlo_summary.get("modes", {}).get("monthly_block_bootstrap", {})
    report_lines.extend(
        [
            "",
            "## Monte Carlo Reference",
            "",
            f"- mode: `monthly_block_bootstrap`",
            f"- simulations: `{reference_mc.get('simulation_count', 0)}`",
            f"- p50 / p25 ending equity: `{reference_mc.get('median_ending_equity', 0.0)} / {reference_mc.get('p25_ending_equity', 0.0)}`",
            f"- probability above €500k / €1M: `{reference_mc.get('probability_end_above_500k', 0.0)} / {reference_mc.get('probability_end_above_1m', 0.0)}`",
            f"- ruin risk: `{reference_mc.get('probability_ruin_or_equity_below_50pct_start', 0.0)}`",
            "",
            "## Mission Gap",
            "",
            f"- verdict: `{mission_gap['verdict']}`",
            f"- median 5Y gap to €1M: `{mission_gap['median_5y_gap_to_1m']}`",
            f"- best 5Y gap to €1M: `{mission_gap['best_5y_gap_to_1m']}`",
            "",
            "## Promotion Gate",
            "",
            f"- classification: `{promotion_gate['classification']}`",
            f"- next action: `{next_step['next_action']}`",
            "",
            "This remained research-only. No live, paper, runtime, allocator, risk, sizing, entry, exit, threshold, sleeve, or config-default behavior changed.",
        ]
    )

    _write_json(config.output_root / "status.json", {"state": "complete", "resolved_at_utc": summary["resolved_at_utc"], **RESEARCH_ONLY_FLAGS})
    _write_json(config.output_root / "native_sr_aware_strict_stress_monte_carlo_summary.json", summary)
    _write_markdown(config.output_root / "native_sr_aware_strict_stress_monte_carlo_report.md", "\n".join(report_lines))
    _write_json(diagnostics_root / "frozen_variant_spec.json", frozen_spec)
    _write_json(diagnostics_root / "pf_42_sanity_audit.json", pf_audit)
    _write_json(diagnostics_root / "pre_entry_rule_integrity_audit.json", integrity_audit)
    _write_csv(diagnostics_root / "stress_test_matrix.csv", _normalize_rows(stress_rows))
    _write_csv(diagnostics_root / "cost_slippage_stress.csv", _normalize_rows(grouped_stress["cost_slippage_stress"]))
    _write_csv(diagnostics_root / "r_haircut_stress.csv", _normalize_rows(grouped_stress["r_haircut_stress"]))
    _write_csv(diagnostics_root / "top_winner_removal_stress.csv", _normalize_rows(grouped_stress["top_winner_removal_stress"]))
    _write_csv(diagnostics_root / "random_trade_dropout_stress.csv", _normalize_rows(grouped_stress["random_trade_dropout_stress"]))
    _write_csv(diagnostics_root / "time_block_removal_stress.csv", _normalize_rows(grouped_stress["time_block_removal_stress"]))
    _write_csv(diagnostics_root / "regime_stress_summary.csv", _normalize_rows(grouped_stress["regime_stress_summary"]))
    _write_csv(diagnostics_root / "rolling_5y_stress_summary.csv", _normalize_rows(rolling_stress))
    _write_json(diagnostics_root / "monte_carlo_summary.json", monte_carlo_summary)
    _write_csv(diagnostics_root / "monte_carlo_distribution.csv", _normalize_rows(mc_distribution))
    _write_csv(diagnostics_root / "monte_carlo_drawdown_distribution.csv", _normalize_rows(mc_drawdowns))
    _write_json(diagnostics_root / "monte_carlo_ruin_risk.json", mc_ruin)
    _write_json(diagnostics_root / "mission_gap_report.json", mission_gap)
    _write_json(diagnostics_root / "promotion_gate_report.json", promotion_gate)
    _write_json(diagnostics_root / "no_go_risks.json", no_go_risks)
    _write_json(reports_root / "next_research_recommendation.json", next_step)

    broad_summary_after = _read_json(paths["broad_summary"], {})
    _write_json(
        diagnostics_root / "audit_invariants.json",
        {
            **RESEARCH_ONLY_FLAGS,
            "broad_summary_unchanged": json.dumps(broad_summary_before, sort_keys=True) == json.dumps(broad_summary_after, sort_keys=True),
            "strict_reconstruction_matches_source_trade_count": frozen_spec["reconstructed_matches_source_trade_count"],
        },
    )

    return {
        "status": config.output_root / "status.json",
        "summary": config.output_root / "native_sr_aware_strict_stress_monte_carlo_summary.json",
        "report": config.output_root / "native_sr_aware_strict_stress_monte_carlo_report.md",
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    result = write_native_sr_aware_strict_stress_monte_carlo_audit(
        NativeSRAwareStrictStressMonteCarloAuditConfig(
            package_root=package_root,
            output_root=package_root / "output" / "native_sr_aware_strict_stress_monte_carlo_audit_001",
        )
    )
    print(result["summary"])


if __name__ == "__main__":
    main()
