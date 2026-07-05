from __future__ import annotations

import argparse
import csv
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.execution_patience_guard_court import (  # noqa: E402
    FROZEN_2PCT_ALLOCATOR_LADDER,
    _load_symbol_caps,
)
from structural_compounding_lab.diagnostics.multi_asset_earned_parallel_slot_court import (  # noqa: E402
    ACTIVE_CAP,
    SAFETY_FLAGS,
    START_CAPITAL,
    TAX_RESERVE_RATE,
    _csv_value,
    _ladder_state,
    _max_drawdown,
    _profit_factor,
    _read_json,
    _safe_ratio,
    _write_csv,
    _write_json,
    _year_end_tax,
)


COURT_NAME = "A_PLUS_CONVICTION_SIZING_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "a_plus_conviction_sizing_court_001"

PASSED = "A_PLUS_CONVICTION_SIZING_FREEZE_CANDIDATE_PASSED_RESEARCH_ONLY"
WARNING = "A_PLUS_CONVICTION_SIZING_WARNING_RESEARCH_ONLY"
FAILED = "A_PLUS_CONVICTION_SIZING_FAILED_RESEARCH_ONLY"
BLOCKED = "A_PLUS_CONVICTION_SIZING_BLOCKED_RESEARCH_ONLY"

DEFAULT_PRIORITY_SYMBOLS = [
    "ADAUSDT",
    "LINKUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "AVAXUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "SOLUSDT",
    "BTCUSDT",
]


@dataclass(frozen=True)
class ConvictionProfile:
    profile_id: str
    description: str
    normal_risk_pct: float
    a_plus_risk_pct: float
    elite_risk_pct: float
    ladder: tuple[dict[str, Any], ...]


BASELINE_PROFILE = ConvictionProfile(
    profile_id="frozen_reference_1pct_each_trade",
    description="Frozen 9-symbol allocator: 1% risk per selected trade, 2/3/5% earned-slot portfolio risk.",
    normal_risk_pct=0.01,
    a_plus_risk_pct=0.01,
    elite_risk_pct=0.01,
    ladder=FROZEN_2PCT_ALLOCATOR_LADDER,
)

CONVICTION_PROFILES: tuple[ConvictionProfile, ...] = (
    BASELINE_PROFILE,
    ConvictionProfile(
        profile_id="a_plus_1p50_elite_2p00_total_3p00",
        description="Quality lift: normal 1.00%, A+ 1.50%, elite 2.00%, early total open risk 3%.",
        normal_risk_pct=0.01,
        a_plus_risk_pct=0.015,
        elite_risk_pct=0.02,
        ladder=(
            {"min_active_equity": 0.0, "max_slots": 2, "max_total_open_risk_pct": 0.03},
            {"min_active_equity": 100_000.0, "max_slots": 3, "max_total_open_risk_pct": 0.045},
            {"min_active_equity": 300_000.0, "max_slots": 5, "max_total_open_risk_pct": 0.06},
        ),
    ),
    ConvictionProfile(
        profile_id="a_plus_2p00_elite_2p50_total_4p00",
        description="Stronger quality lift: normal 1.00%, A+ 2.00%, elite 2.50%, early total open risk 4%.",
        normal_risk_pct=0.01,
        a_plus_risk_pct=0.02,
        elite_risk_pct=0.025,
        ladder=(
            {"min_active_equity": 0.0, "max_slots": 2, "max_total_open_risk_pct": 0.04},
            {"min_active_equity": 100_000.0, "max_slots": 3, "max_total_open_risk_pct": 0.06},
            {"min_active_equity": 300_000.0, "max_slots": 5, "max_total_open_risk_pct": 0.08},
        ),
    ),
    ConvictionProfile(
        profile_id="a_plus_2p50_elite_3p00_total_5p00",
        description="Aggressive diagnostic: normal 1.00%, A+ 2.50%, elite 3.00%, early total open risk 5%.",
        normal_risk_pct=0.01,
        a_plus_risk_pct=0.025,
        elite_risk_pct=0.03,
        ladder=(
            {"min_active_equity": 0.0, "max_slots": 2, "max_total_open_risk_pct": 0.05},
            {"min_active_equity": 100_000.0, "max_slots": 3, "max_total_open_risk_pct": 0.075},
            {"min_active_equity": 300_000.0, "max_slots": 5, "max_total_open_risk_pct": 0.10},
        ),
    ),
)


@dataclass(frozen=True)
class CourtConfig:
    source_bridge_ledger: Path
    cap_root: Path
    canonical_root: Path
    output_dir: Path
    max_rows: int | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_bool(value: Any) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def _parse_timestamp(value: str) -> pd.Timestamp:
    return pd.to_datetime(value, utc=True)


def _period_name(value: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"research", "research_pre_holdout", "pre_holdout"}:
        return "research"
    if normalized in {"holdout", "sealed_holdout", "virgin_holdout"}:
        return "holdout"
    return normalized or "unknown"


def _load_priority_symbols(config: CourtConfig) -> list[str]:
    path = config.canonical_root / "multi_asset_earned_parallel_slot_btc_inclusion_summary.json"
    payload = _read_json(path) if path.exists() else {}
    best_policy = str(payload.get("best_btc_policy") or "btc_research_ranked_9_symbol")
    comparison = (payload.get("comparisons") or {}).get(best_policy) or {}
    priority = list(comparison.get("priority_symbols") or [])
    return priority if set(priority) == set(DEFAULT_PRIORITY_SYMBOLS) else DEFAULT_PRIORITY_SYMBOLS


def _load_bridge_rows(path: Path, max_rows: int | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing bridge ledger: {path}")

    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for raw in reader:
            if not _parse_bool(raw.get("candidate_guard_accepted")):
                continue
            if str(raw.get("side") or "").lower() != "long":
                continue
            symbol = str(raw.get("usdt_symbol") or raw.get("symbol") or "").strip().upper()
            if not symbol:
                continue
            row = dict(raw)
            row["symbol"] = symbol
            row["trade_id"] = raw.get("source_trade_id") or raw.get("trade_id") or raw.get("portfolio_trade_number")
            row["entry_timestamp"] = _parse_timestamp(raw.get("entry_timestamp") or raw.get("entry_time"))
            row["exit_timestamp"] = _parse_timestamp(raw.get("exit_timestamp") or raw.get("exit_time"))
            row["period"] = _period_name(str(raw.get("period") or ""))
            row["side"] = "long"
            row["net_r"] = float(raw.get("net_r") or 0.0)
            row["net_cost_r"] = float(raw.get("net_cost_r") or 0.0)
            row["stop_distance_fraction"] = float(raw.get("stop_distance_fraction") or 0.01)
            row["setup_class"] = str(raw.get("setup_class") or "").strip().upper()
            row["convexity_label"] = str(raw.get("convexity_label") or raw.get("personality_label") or "").strip().lower()
            row["personality_label"] = str(raw.get("personality_label") or "").strip().lower()
            rows.append(row)
            if max_rows is not None and len(rows) >= max_rows:
                break

    return sorted(rows, key=lambda item: (item["entry_timestamp"], item["symbol"], str(item.get("trade_id") or "")))


def _conviction_tier(row: dict[str, Any]) -> str:
    convexity = str(row.get("convexity_label") or row.get("personality_label") or "").lower()
    setup_class = str(row.get("setup_class") or "").upper()
    if convexity == "elite_convexity":
        return "elite"
    if setup_class == "A" or convexity == "strong_convexity":
        return "a_plus"
    return "normal"


def _risk_pct(row: dict[str, Any], profile: ConvictionProfile) -> float:
    tier = _conviction_tier(row)
    if tier == "elite":
        return profile.elite_risk_pct
    if tier == "a_plus":
        return profile.a_plus_risk_pct
    return profile.normal_risk_pct


def _profile_ladder_state(active_equity: float, profile: ConvictionProfile) -> dict[str, Any]:
    state = _ladder_state(active_equity, profile.ladder)
    return {
        "min_active_equity": float(state["min_active_equity"]),
        "max_slots": int(state["max_slots"]),
        "max_total_open_risk_pct": float(state["max_total_open_risk_pct"]),
    }


def _empty_replay(profile: ConvictionProfile, period: str) -> dict[str, Any]:
    return {
        "profile_id": profile.profile_id,
        "period": period,
        "starting_equity": START_CAPITAL,
        "active_cap": ACTIVE_CAP,
        "ending_total_equity_after_tax": START_CAPITAL,
        "ending_active_capital_after_tax": START_CAPITAL,
        "ending_profit_vault_after_tax": 0.0,
        "return_multiple_after_tax": 1.0,
        "net_gain_after_tax": 0.0,
        "tax_reserved_or_withdrawn": 0.0,
        "candidate_trades": 0,
        "selected_trades": 0,
        "rejected_trades": 0,
        "rejected_by_reason": {},
        "selected_by_tier": {},
        "selected_by_symbol": {},
        "pnl_by_symbol": {},
        "max_concurrent_positions": 0,
        "notional_limited_trades": 0,
        "sum_net_r": 0.0,
        "profit_factor": 0.0,
        "win_rate": 0.0,
        "max_drawdown_total_after_tax": 0.0,
        "max_drawdown_active": 0.0,
        "trade_rows": [],
        "rejected_rows": [],
        "yearly_rows": [],
    }


def _replay_conviction(
    rows: list[dict[str, Any]],
    *,
    profile: ConvictionProfile,
    period: str,
    priority_symbols: list[str],
    symbol_caps: dict[str, float],
) -> dict[str, Any]:
    if not rows:
        return _empty_replay(profile, period)

    priority = {symbol: index for index, symbol in enumerate(priority_symbols, start=1)}
    grouped: dict[pd.Timestamp, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row["entry_timestamp"], []).append(row)
    entry_times = sorted(grouped)

    active = START_CAPITAL
    vault = 0.0
    open_positions: list[dict[str, Any]] = []
    selected: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    trade_rows: list[dict[str, Any]] = []
    yearly_rows: list[dict[str, Any]] = []
    curve = [active + vault]
    active_curve = [active]
    values: list[float] = []
    rejected_by_reason: dict[str, int] = {}
    selected_by_tier: dict[str, int] = {}
    selected_by_symbol: dict[str, int] = {}
    pnl_by_symbol: dict[str, float] = {}
    notional_limited = 0
    max_concurrent = 0
    current_year: int | None = None
    year_pnl = 0.0
    tax_total = 0.0

    def reject(row: dict[str, Any], reason: str) -> None:
        rejected_by_reason[reason] = rejected_by_reason.get(reason, 0) + 1
        rejected.append(
            {
                "profile_id": profile.profile_id,
                "period": period,
                "symbol": row["symbol"],
                "trade_id": row.get("trade_id"),
                "entry_time": row["entry_timestamp"].isoformat(),
                "exit_time": row["exit_timestamp"].isoformat(),
                "side": row.get("side"),
                "conviction_tier": _conviction_tier(row),
                "requested_risk_pct": _risk_pct(row, profile),
                "reject_reason": reason,
                "active_equity": active,
                "open_positions": len(open_positions),
            }
        )

    def process_exit(position: dict[str, Any]) -> None:
        nonlocal active, vault, year_pnl, tax_total, current_year
        row = position["row"]
        exit_year = int(row["exit_timestamp"].year)
        if current_year is None:
            current_year = exit_year
        while current_year is not None and exit_year > current_year:
            active, vault, tax = _year_end_tax(active, vault, year_pnl, TAX_RESERVE_RATE)
            tax_total += tax
            yearly_rows.append(
                {
                    "profile_id": profile.profile_id,
                    "period": period,
                    "year": current_year,
                    "realized_net_pnl_before_tax": year_pnl,
                    "tax_reserved_or_withdrawn": tax,
                    "ending_active_capital_after_tax": active,
                    "ending_profit_vault_after_tax": vault,
                    "ending_total_equity_after_tax": active + vault,
                }
            )
            curve.append(active + vault)
            current_year += 1
            year_pnl = 0.0

        pnl = float(position["risk_eur"]) * float(row["net_r"])
        active_before = active
        vault_before = vault
        active += pnl
        if active < 0.0:
            active = 0.0
        if active > ACTIVE_CAP:
            vault += active - ACTIVE_CAP
            active = ACTIVE_CAP
        year_pnl += pnl
        selected.append(row)
        values.append(float(row["net_r"]))
        curve.append(active + vault)
        active_curve.append(active)

        symbol = str(row["symbol"])
        tier = str(position["conviction_tier"])
        selected_by_tier[tier] = selected_by_tier.get(tier, 0) + 1
        selected_by_symbol[symbol] = selected_by_symbol.get(symbol, 0) + 1
        pnl_by_symbol[symbol] = pnl_by_symbol.get(symbol, 0.0) + pnl

        trade_rows.append(
            {
                "profile_id": profile.profile_id,
                "period": period,
                "trade_number": len(trade_rows) + 1,
                "symbol": symbol,
                "trade_id": row.get("trade_id"),
                "side": row.get("side"),
                "entry_time": row["entry_timestamp"].isoformat(),
                "exit_time": row["exit_timestamp"].isoformat(),
                "setup_class": row.get("setup_class"),
                "convexity_label": row.get("convexity_label"),
                "conviction_tier": tier,
                "net_r": float(row["net_r"]),
                "net_cost_r": float(row.get("net_cost_r") or 0.0),
                "requested_risk_pct": float(position["requested_risk_pct"]),
                "risk_eur": float(position["risk_eur"]),
                "pnl_eur": pnl,
                "active_before_exit": active_before,
                "vault_before_exit": vault_before,
                "active_after_exit": active,
                "vault_after_exit": vault,
                "total_after_exit_before_year_tax": active + vault,
                "concurrent_slots_at_entry": int(position["concurrent_slots_at_entry"]),
                "max_slots_at_entry": int(position["max_slots_at_entry"]),
                "max_total_open_risk_pct_at_entry": float(position["max_total_open_risk_pct_at_entry"]),
                "symbol_cap_eur": position.get("symbol_cap_eur"),
                "symbol_risk_cap_eur": position.get("symbol_risk_cap_eur"),
                "notional_limited": bool(position["notional_limited"]),
            }
        )

    for entry_time in entry_times:
        due = [position for position in open_positions if position["row"]["exit_timestamp"] < entry_time]
        for position in sorted(due, key=lambda item: (item["row"]["exit_timestamp"], item["row"]["symbol"])):
            process_exit(position)
        open_positions = [position for position in open_positions if position not in due]

        state = _profile_ladder_state(active, profile)
        max_slots = int(state["max_slots"])
        max_total_risk = float(state["max_total_open_risk_pct"]) * max(0.0, min(active, ACTIVE_CAP))
        current_open_risk = sum(float(position["risk_eur"]) for position in open_positions)
        existing_symbols = {position["row"]["symbol"] for position in open_positions}
        bucket = sorted(
            grouped[entry_time],
            key=lambda row: (
                priority.get(row["symbol"], 999),
                {"elite": 0, "a_plus": 1, "normal": 2}.get(_conviction_tier(row), 9),
                float(row.get("net_cost_r") or 999.0),
                str(row.get("trade_id") or ""),
            ),
        )

        for row in bucket:
            if row["symbol"] in existing_symbols:
                reject(row, "symbol_already_open")
                continue
            if len(open_positions) >= max_slots:
                reject(row, "earned_slot_limit_reached")
                continue
            remaining_risk = max(0.0, max_total_risk - current_open_risk)
            if remaining_risk <= 0.0:
                reject(row, "portfolio_open_risk_limit_reached")
                continue

            requested_risk_pct = _risk_pct(row, profile)
            risk_base = max(0.0, min(active, ACTIVE_CAP))
            requested_risk = risk_base * requested_risk_pct
            symbol_cap = symbol_caps.get(str(row["symbol"]), float("inf"))
            symbol_risk_cap = symbol_cap * requested_risk_pct if math.isfinite(symbol_cap) else float("inf")
            risk_eur = min(requested_risk, remaining_risk, symbol_risk_cap)
            if risk_eur <= 0.0:
                reject(row, "zero_risk_after_caps")
                continue

            limited = risk_eur < min(requested_risk, remaining_risk)
            notional_limited += int(limited)
            open_positions.append(
                {
                    "row": row,
                    "risk_eur": risk_eur,
                    "requested_risk_pct": requested_risk_pct,
                    "conviction_tier": _conviction_tier(row),
                    "concurrent_slots_at_entry": len(open_positions) + 1,
                    "max_slots_at_entry": max_slots,
                    "max_total_open_risk_pct_at_entry": state["max_total_open_risk_pct"],
                    "symbol_cap_eur": symbol_cap if math.isfinite(symbol_cap) else None,
                    "symbol_risk_cap_eur": symbol_risk_cap if math.isfinite(symbol_risk_cap) else None,
                    "notional_limited": limited,
                }
            )
            current_open_risk += risk_eur
            existing_symbols.add(row["symbol"])
            max_concurrent = max(max_concurrent, len(open_positions))

    for position in sorted(open_positions, key=lambda item: (item["row"]["exit_timestamp"], item["row"]["symbol"])):
        process_exit(position)

    if current_year is not None:
        active, vault, tax = _year_end_tax(active, vault, year_pnl, TAX_RESERVE_RATE)
        tax_total += tax
        yearly_rows.append(
            {
                "profile_id": profile.profile_id,
                "period": period,
                "year": current_year,
                "realized_net_pnl_before_tax": year_pnl,
                "tax_reserved_or_withdrawn": tax,
                "ending_active_capital_after_tax": active,
                "ending_profit_vault_after_tax": vault,
                "ending_total_equity_after_tax": active + vault,
            }
        )
        curve.append(active + vault)

    return {
        "profile_id": profile.profile_id,
        "period": period,
        "starting_equity": START_CAPITAL,
        "active_cap": ACTIVE_CAP,
        "ending_total_equity_after_tax": active + vault,
        "ending_active_capital_after_tax": active,
        "ending_profit_vault_after_tax": vault,
        "return_multiple_after_tax": _safe_ratio(active + vault, START_CAPITAL, 0.0),
        "net_gain_after_tax": active + vault - START_CAPITAL,
        "tax_reserved_or_withdrawn": tax_total,
        "candidate_trades": len(rows),
        "selected_trades": len(selected),
        "rejected_trades": len(rejected),
        "rejected_by_reason": rejected_by_reason,
        "selected_by_tier": selected_by_tier,
        "selected_by_symbol": selected_by_symbol,
        "pnl_by_symbol": pnl_by_symbol,
        "max_concurrent_positions": max_concurrent,
        "notional_limited_trades": notional_limited,
        "sum_net_r": sum(values),
        "profit_factor": _profit_factor(values),
        "win_rate": _safe_ratio(sum(1 for value in values if value > 0.0), len(values), 0.0),
        "max_drawdown_total_after_tax": _max_drawdown(curve),
        "max_drawdown_active": _max_drawdown(active_curve),
        "trade_rows": trade_rows,
        "rejected_rows": rejected,
        "yearly_rows": yearly_rows,
    }


def _public_replay(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key not in {"trade_rows", "rejected_rows", "yearly_rows"}}


def _run_profile(
    profile: ConvictionProfile,
    *,
    rows: list[dict[str, Any]],
    priority_symbols: list[str],
    symbol_caps: dict[str, float],
) -> dict[str, Any]:
    research_rows = [row for row in rows if row["period"] == "research"]
    holdout_rows = [row for row in rows if row["period"] == "holdout"]
    research = _replay_conviction(
        research_rows,
        profile=profile,
        period="research",
        priority_symbols=priority_symbols,
        symbol_caps=symbol_caps,
    )
    holdout = _replay_conviction(
        holdout_rows,
        profile=profile,
        period="holdout",
        priority_symbols=priority_symbols,
        symbol_caps=symbol_caps,
    )
    return {
        "profile": profile,
        "research": research,
        "holdout": holdout,
    }


def _pct_delta(value: float, reference: float) -> float:
    return _safe_ratio(value - reference, reference, 0.0)


def _comparison_rows(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    baseline = next(item for item in results if item["profile"].profile_id == BASELINE_PROFILE.profile_id)
    baseline_research = float(baseline["research"]["ending_total_equity_after_tax"])
    baseline_holdout = float(baseline["holdout"]["ending_total_equity_after_tax"])
    rows: list[dict[str, Any]] = []
    for item in results:
        profile: ConvictionProfile = item["profile"]
        research = item["research"]
        holdout = item["holdout"]
        rows.append(
            {
                "profile_id": profile.profile_id,
                "description": profile.description,
                "normal_risk_pct": profile.normal_risk_pct,
                "a_plus_risk_pct": profile.a_plus_risk_pct,
                "elite_risk_pct": profile.elite_risk_pct,
                "research_equity_after_tax": research["ending_total_equity_after_tax"],
                "research_net_gain_after_tax": research["net_gain_after_tax"],
                "research_delta_vs_baseline_pct": _pct_delta(
                    float(research["ending_total_equity_after_tax"]), baseline_research
                ),
                "research_selected_trades": research["selected_trades"],
                "research_profit_factor": research["profit_factor"],
                "research_win_rate": research["win_rate"],
                "research_max_drawdown": research["max_drawdown_total_after_tax"],
                "holdout_equity_after_tax": holdout["ending_total_equity_after_tax"],
                "holdout_net_gain_after_tax": holdout["net_gain_after_tax"],
                "holdout_delta_vs_baseline_pct": _pct_delta(
                    float(holdout["ending_total_equity_after_tax"]), baseline_holdout
                ),
                "holdout_selected_trades": holdout["selected_trades"],
                "holdout_profit_factor": holdout["profit_factor"],
                "holdout_win_rate": holdout["win_rate"],
                "holdout_max_drawdown": holdout["max_drawdown_total_after_tax"],
                "research_rejected_by_reason": research["rejected_by_reason"],
                "holdout_rejected_by_reason": holdout["rejected_by_reason"],
            }
        )
    return rows


def _choose_best(results: list[dict[str, Any]]) -> dict[str, Any]:
    baseline = next(item for item in results if item["profile"].profile_id == BASELINE_PROFILE.profile_id)
    baseline_holdout_equity = float(baseline["holdout"]["ending_total_equity_after_tax"])
    baseline_research_equity = float(baseline["research"]["ending_total_equity_after_tax"])
    baseline_holdout_dd = float(baseline["holdout"]["max_drawdown_total_after_tax"])
    baseline_research_dd = float(baseline["research"]["max_drawdown_total_after_tax"])
    viable = [
        item
        for item in results
        if item["profile"].profile_id != BASELINE_PROFILE.profile_id
        and float(item["holdout"]["ending_total_equity_after_tax"]) >= baseline_holdout_equity
        and float(item["research"]["ending_total_equity_after_tax"]) >= baseline_research_equity
        and float(item["holdout"]["max_drawdown_total_after_tax"]) <= min(0.55, baseline_holdout_dd + 0.10)
        and float(item["research"]["max_drawdown_total_after_tax"]) <= min(0.55, baseline_research_dd + 0.10)
    ]
    if not viable:
        return baseline
    return sorted(
        viable,
        key=lambda item: (
            float(item["holdout"]["ending_total_equity_after_tax"]),
            float(item["research"]["ending_total_equity_after_tax"]),
            -float(item["holdout"]["max_drawdown_total_after_tax"]),
        ),
        reverse=True,
    )[0]


def run_court(config: CourtConfig) -> dict[str, Any]:
    rows = _load_bridge_rows(config.source_bridge_ledger, max_rows=config.max_rows)
    if not rows:
        return {
            "court_name": COURT_NAME,
            "created_at": _now(),
            "final_classification": BLOCKED,
            "reason": "no_accepted_long_bridge_rows_found",
            "source_bridge_ledger": str(config.source_bridge_ledger),
        }

    priority_symbols = _load_priority_symbols(config)
    symbol_caps = _load_symbol_caps(config)  # type: ignore[arg-type]
    if not symbol_caps:
        raise RuntimeError("Missing symbol caps.")

    results = [
        _run_profile(
            profile,
            rows=rows,
            priority_symbols=priority_symbols,
            symbol_caps=symbol_caps,
        )
        for profile in CONVICTION_PROFILES
    ]
    best = _choose_best(results)
    baseline = next(item for item in results if item["profile"].profile_id == BASELINE_PROFILE.profile_id)
    comparison = _comparison_rows(results)

    best_is_baseline = best["profile"].profile_id == BASELINE_PROFILE.profile_id
    best_research = best["research"]
    best_holdout = best["holdout"]
    baseline_research = baseline["research"]
    baseline_holdout = baseline["holdout"]

    if best_is_baseline:
        final_classification = WARNING
    elif (
        float(best_research["ending_total_equity_after_tax"])
        > float(baseline_research["ending_total_equity_after_tax"])
        and float(best_holdout["ending_total_equity_after_tax"])
        > float(baseline_holdout["ending_total_equity_after_tax"])
        and float(best_holdout["max_drawdown_total_after_tax"])
        <= min(0.55, float(baseline_holdout["max_drawdown_total_after_tax"]) + 0.10)
        and float(best_research["max_drawdown_total_after_tax"])
        <= min(0.55, float(baseline_research["max_drawdown_total_after_tax"]) + 0.10)
    ):
        final_classification = PASSED
    else:
        final_classification = WARNING

    output = config.output_dir
    output.mkdir(parents=True, exist_ok=True)

    for item in results:
        profile_id = item["profile"].profile_id
        _write_csv(output / f"{profile_id}_research_trades.csv", item["research"]["trade_rows"])
        _write_csv(output / f"{profile_id}_holdout_trades.csv", item["holdout"]["trade_rows"])
        _write_csv(output / f"{profile_id}_research_rejections.csv", item["research"]["rejected_rows"])
        _write_csv(output / f"{profile_id}_holdout_rejections.csv", item["holdout"]["rejected_rows"])
        _write_csv(output / f"{profile_id}_yearly_tax_rows.csv", item["research"]["yearly_rows"] + item["holdout"]["yearly_rows"])

    _write_csv(output / "conviction_sizing_comparison.csv", comparison)

    tier_counts: dict[str, int] = {}
    period_counts: dict[str, int] = {}
    for row in rows:
        tier = _conviction_tier(row)
        tier_counts[tier] = tier_counts.get(tier, 0) + 1
        period_counts[row["period"]] = period_counts.get(row["period"], 0) + 1

    summary = {
        "court_name": COURT_NAME,
        "created_at": _now(),
        "final_classification": final_classification,
        "source_bridge_ledger": str(config.source_bridge_ledger),
        "cap_root": str(config.cap_root),
        "canonical_root": str(config.canonical_root),
        "output_dir": str(config.output_dir),
        "rows_loaded": len(rows),
        "max_rows": config.max_rows,
        "period_counts": period_counts,
        "conviction_tier_counts": tier_counts,
        "priority_symbols": priority_symbols,
        "symbol_caps_eur": symbol_caps,
        "accounting": {
            "starting_capital_eur": START_CAPITAL,
            "active_cap_eur": ACTIVE_CAP,
            "yearly_tax_reserve_rate": TAX_RESERVE_RATE,
            "costs_already_embedded_in_net_r": True,
            "tax_reserve_applied": True,
        },
        "conviction_classification_rule": {
            "elite": "convexity_label == elite_convexity",
            "a_plus": "setup_class == A OR convexity_label == strong_convexity",
            "normal": "all other accepted long-only bridge rows",
            "uses_future_pnl_for_classification": False,
        },
        "profiles": [
            {
                "profile_id": profile.profile_id,
                "description": profile.description,
                "normal_risk_pct": profile.normal_risk_pct,
                "a_plus_risk_pct": profile.a_plus_risk_pct,
                "elite_risk_pct": profile.elite_risk_pct,
                "ladder": profile.ladder,
            }
            for profile in CONVICTION_PROFILES
        ],
        "comparison": comparison,
        "baseline_profile_id": BASELINE_PROFILE.profile_id,
        "best_profile_id": best["profile"].profile_id,
        "best_research": _public_replay(best_research),
        "best_holdout": _public_replay(best_holdout),
        "baseline_research": _public_replay(baseline_research),
        "baseline_holdout": _public_replay(baseline_holdout),
        "decision": {
            "freeze_justified": final_classification == PASSED,
            "deployment_recommended_now": False,
            "requires_full_review_before_live": True,
            "pnl_priority": True,
            "safety_note": "Research-only sizing replay. No Binance endpoints, no orders, no paper/live scheduler mutation.",
        },
        "safety": {
            **SAFETY_FLAGS,
            "research_only": True,
            "paper_validation_ready": False,
            "paper_allowed": False,
            "live_allowed": False,
            "real_money_allowed": False,
            "order_path_created": False,
            "broker_path_created": False,
            "private_endpoint_used": False,
            "signed_endpoint_used": False,
            "strategy_logic_changed": False,
            "entries_changed": False,
            "exits_changed": False,
            "thresholds_tuned": False,
        },
    }
    _write_json(output / "a_plus_conviction_sizing_summary.json", summary)
    return summary


def _print_summary(summary: dict[str, Any]) -> None:
    print("A+ CONVICTION SIZING COURT")
    print(f"classification: {summary.get('final_classification')}")
    print(f"rows loaded: {summary.get('rows_loaded')}")
    print(f"best profile: {summary.get('best_profile_id')}")
    baseline_research = summary.get("baseline_research") or {}
    baseline_holdout = summary.get("baseline_holdout") or {}
    best_research = summary.get("best_research") or {}
    best_holdout = summary.get("best_holdout") or {}
    print(
        "baseline research equity after tax: "
        f"€{float(baseline_research.get('ending_total_equity_after_tax') or 0.0):,.2f}"
    )
    print(
        "best research equity after tax: "
        f"€{float(best_research.get('ending_total_equity_after_tax') or 0.0):,.2f}"
    )
    print(
        "baseline holdout equity after tax: "
        f"€{float(baseline_holdout.get('ending_total_equity_after_tax') or 0.0):,.2f}"
    )
    print(
        "best holdout equity after tax: "
        f"€{float(best_holdout.get('ending_total_equity_after_tax') or 0.0):,.2f}"
    )
    print(f"output: {summary.get('output_dir')}")
    print("orders sent: 0")
    print("live/paper changed: false")


def parse_args() -> CourtConfig:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument(
        "--source-bridge-ledger",
        type=Path,
        default=Path(
            "/Users/mac/Documents/Retail-Trading-System/structural_compounding_lab/output/"
            "usdt_signal_usdc_execution_bridge_court_001/spot_long_only_execution_bridge_trades.csv"
        ),
    )
    parser.add_argument(
        "--cap-root",
        type=Path,
        default=Path("structural_compounding_lab/output/multi_symbol_btc_exact_fill_cap_calibration_court_001"),
    )
    parser.add_argument(
        "--canonical-root",
        type=Path,
        default=Path(
            "/Users/mac/Documents/Retail-Trading-System/structural_compounding_lab/output/"
            "multi_asset_earned_parallel_slot_btc_inclusion_court_001"
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("structural_compounding_lab/output") / OUTPUT_FOLDER_NAME,
    )
    parser.add_argument("--max-rows", type=int, default=None)
    args = parser.parse_args()
    return CourtConfig(
        source_bridge_ledger=args.source_bridge_ledger.expanduser().resolve(),
        cap_root=args.cap_root.expanduser().resolve(),
        canonical_root=args.canonical_root.expanduser().resolve(),
        output_dir=args.output_dir.expanduser().resolve(),
        max_rows=args.max_rows,
    )


def main() -> None:
    summary = run_court(parse_args())
    _print_summary(summary)


if __name__ == "__main__":
    main()
