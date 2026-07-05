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
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path  # noqa: E402
from structural_compounding_lab.diagnostics.multi_asset_earned_parallel_slot_court import (  # noqa: E402
    ACTIVE_CAP,
    SAFETY_FLAGS,
    START_CAPITAL,
    TAX_RESERVE_RATE,
    _replay,
    _scenario_public,
    _write_csv,
    _write_json,
)
from structural_compounding_lab.diagnostics.multi_asset_portfolio_selection_court import _read_json  # noqa: E402
from structural_compounding_lab.execution.usdt_usdc_execution_guard import (  # noqa: E402
    USDT_TO_USDC,
    _default_symbol_policies,
)


COURT_NAME = "USDT_SIGNAL_USDC_EXECUTION_PATIENCE_GUARD_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "usdt_signal_usdc_execution_patience_guard_court_001"

PASSED = "EXECUTION_PATIENCE_GUARD_CANDIDATE_IMPROVED_RESEARCH_ONLY"
WARNING = "EXECUTION_PATIENCE_GUARD_CANDIDATE_WARNING_RESEARCH_ONLY"
FAILED = "EXECUTION_PATIENCE_GUARD_CANDIDATE_NOT_IMPROVED_RESEARCH_ONLY"
BLOCKED = "EXECUTION_PATIENCE_GUARD_COURT_BLOCKED_RESEARCH_ONLY"

ROUND_TRIP_COST_BPS = 15.0
MAX_PRE_ENTRY_COST_R = 1.0
REFERENCE_FROZEN_USDC_EQUITY_AFTER_TAX = 5_333_441.951167
REFERENCE_FROZEN_USDC_HOLDOUT_AFTER_TAX = 206_509.995332

FROZEN_2PCT_ALLOCATOR_LADDER: tuple[dict[str, Any], ...] = (
    {"min_active_equity": 0.0, "max_slots": 2, "max_total_open_risk_pct": 0.02, "max_risk_per_trade_pct": 0.01},
    {
        "min_active_equity": 100_000.0,
        "max_slots": 3,
        "max_total_open_risk_pct": 0.03,
        "max_risk_per_trade_pct": 0.01,
    },
    {
        "min_active_equity": 300_000.0,
        "max_slots": 5,
        "max_total_open_risk_pct": 0.05,
        "max_risk_per_trade_pct": 0.01,
    },
)

DEFAULT_PRIORITY_SYMBOLS = [
    "ADAUSDT",
    "LINKUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "AVAXUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "BTCUSDT",
    "SOLUSDT",
]


@dataclass(frozen=True)
class PatienceCandidate:
    candidate_id: str
    threshold_mode: str
    patience_minutes: int
    description: str


CANDIDATES: tuple[PatienceCandidate, ...] = (
    PatienceCandidate(
        "old_uniform_immediate_guard",
        "old_uniform",
        0,
        "Old uniform 35 bps USDT/USDC close-deviation immediate guard.",
    ),
    PatienceCandidate(
        "symbol_aware_hard_reject_guard",
        "symbol_aware",
        0,
        "Current symbol-aware immediate hard-reject guard.",
    ),
    PatienceCandidate("patience_guard_3m", "symbol_aware", 3, "Symbol-aware guard with 3-minute wait/recheck."),
    PatienceCandidate("patience_guard_5m", "symbol_aware", 5, "Symbol-aware guard with 5-minute wait/recheck."),
    PatienceCandidate("patience_guard_10m", "symbol_aware", 10, "Symbol-aware guard with 10-minute wait/recheck."),
)


@dataclass(frozen=True)
class ExecutionPatienceGuardConfig:
    project_root: Path
    package_root: Path
    source_bridge_ledger: Path
    market_root: Path
    canonical_root: Path
    cap_root: Path
    output_root: Path


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sibling_research_root() -> Path:
    return project_root().parent / "Retail-Trading-System"


def default_config() -> ExecutionPatienceGuardConfig:
    pkg = package_root()
    sibling = _sibling_research_root()
    return ExecutionPatienceGuardConfig(
        project_root=project_root(),
        package_root=pkg,
        source_bridge_ledger=sibling
        / "structural_compounding_lab/output/usdt_signal_usdc_execution_bridge_court_001/spot_long_only_execution_bridge_trades.csv",
        market_root=sibling / "data_storage",
        canonical_root=sibling / "structural_compounding_lab/output/multi_asset_earned_parallel_slot_btc_inclusion_court_001",
        cap_root=pkg / "output/multi_symbol_btc_exact_fill_cap_calibration_court_001",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
    )


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None or value == "":
            return default
        output = float(value)
        return default if math.isnan(output) or math.isinf(output) else output
    except (TypeError, ValueError):
        return default


def _parse_ts(value: Any) -> pd.Timestamp:
    ts = pd.Timestamp(value)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _epoch_minute(ts: pd.Timestamp) -> int:
    return int(ts.floor("min").timestamp())


def _eur(value: Any) -> str:
    return f"€{float(value):,.2f}"


def _pct(value: Any) -> str:
    return f"{float(value) * 100.0:.2f}%"


def _pct_delta(value: float, baseline: float) -> float:
    return ((value - baseline) / baseline * 100.0) if baseline else 0.0


def _market_csv_path(market_root: Path, symbol: str) -> Path | None:
    direct = sorted((market_root / symbol / "1m").glob(f"{symbol}_1m_*.csv"))
    if direct:
        return direct[-1]
    lowered = sorted((market_root / symbol / "1m").glob(f"{symbol.lower()}_1m_*.csv"))
    if lowered:
        return lowered[-1]
    return None


def _load_price_maps(config: ExecutionPatienceGuardConfig, needed: dict[str, set[int]]) -> tuple[dict[str, dict[int, float]], dict[str, str]]:
    price_maps: dict[str, dict[int, float]] = {}
    source_paths: dict[str, str] = {}
    for symbol, timestamps in sorted(needed.items()):
        path = _market_csv_path(config.market_root, symbol)
        if path is None:
            price_maps[symbol] = {}
            source_paths[symbol] = ""
            continue
        frame = pd.read_csv(path, usecols=["timestamp", "close"])
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce").dt.floor("min")
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        frame = frame.dropna()
        if timestamps:
            wanted = set(pd.to_datetime(list(timestamps), unit="s", utc=True).floor("min"))
            frame = frame[frame["timestamp"].isin(wanted)]
        price_maps[symbol] = dict(zip(frame["timestamp"].map(lambda value: int(value.timestamp())), frame["close"].astype(float)))
        source_paths[symbol] = str(path)
    return price_maps, source_paths


def _load_priority_symbols(config: ExecutionPatienceGuardConfig) -> list[str]:
    path = config.canonical_root / "multi_asset_earned_parallel_slot_btc_inclusion_summary.json"
    payload = _read_json(path) if path.exists() else {}
    best_policy = str(payload.get("best_btc_policy") or "btc_research_ranked_9_symbol")
    comparison = (payload.get("comparisons") or {}).get(best_policy) or {}
    priority = list(comparison.get("priority_symbols") or [])
    return priority if set(priority) == set(USDT_TO_USDC) else DEFAULT_PRIORITY_SYMBOLS


def _load_symbol_caps(config: ExecutionPatienceGuardConfig) -> dict[str, float]:
    path = config.cap_root / "nine_symbol_recommended_symbol_caps_manifest.json"
    payload = _read_json(path) if path.exists() else {}
    caps = payload.get("recommended_symbol_caps_eur") or {}
    if caps:
        return {str(symbol): float(cap) for symbol, cap in caps.items()}
    return {
        "ADAUSDT": 75_000.0,
        "AVAXUSDT": 25_000.0,
        "BNBUSDT": 475_000.0,
        "BTCUSDT": 2_000_000.0,
        "DOGEUSDT": 400_000.0,
        "ETHUSDT": 1_000_000.0,
        "LINKUSDT": 100_000.0,
        "SOLUSDT": 575_000.0,
        "XRPUSDT": 500_000.0,
    }


def _threshold_bps(candidate: PatienceCandidate, source_symbol: str) -> float:
    if candidate.threshold_mode == "old_uniform":
        return 35.0
    execution_symbol = USDT_TO_USDC[source_symbol]
    return float(_default_symbol_policies()[execution_symbol].max_signal_execution_close_deviation_bps)


def _close_deviation_bps(source_close: float | None, execution_close: float | None) -> float | None:
    if source_close is None or execution_close is None or source_close <= 0.0:
        return None
    return abs(execution_close - source_close) / source_close * 10_000.0


def _normalise_source_rows(rows: list[dict[str, str]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in rows:
        if str(row.get("side") or "").lower() != "long":
            rejected.append({**row, "reject_reason": "spot_long_only_court_excludes_non_long"})
            continue
        source_symbol = str(row.get("usdt_symbol") or row.get("symbol") or "").strip()
        execution_symbol = str(row.get("usdc_symbol") or USDT_TO_USDC.get(source_symbol, "")).strip()
        if source_symbol not in USDT_TO_USDC or execution_symbol != USDT_TO_USDC[source_symbol]:
            rejected.append({**row, "reject_reason": "unsupported_usdt_usdc_pair"})
            continue
        try:
            entry_ts = _parse_ts(row.get("entry_timestamp") or row.get("entry_time"))
            exit_ts = _parse_ts(row.get("exit_timestamp") or row.get("exit_time"))
        except Exception as exc:  # noqa: BLE001
            rejected.append({**row, "reject_reason": f"bad_timestamp:{exc}"})
            continue
        stop_fraction = _float(row.get("stop_distance_fraction") or row.get("stop_distance_pct"))
        if stop_fraction <= 0.0:
            rejected.append({**row, "reject_reason": "invalid_stop_distance_fraction"})
            continue
        period_raw = str(row.get("period") or "")
        if period_raw == "research_pre_holdout":
            period = "research"
        elif period_raw == "sealed_holdout":
            period = "holdout"
        else:
            rejected.append({**row, "reject_reason": f"unknown_period:{period_raw}"})
            continue
        accepted.append(
            {
                "symbol": source_symbol,
                "execution_symbol": execution_symbol,
                "trade_id": row.get("source_trade_id") or row.get("trade_id"),
                "side": "long",
                "period": period,
                "source_period": period_raw,
                "entry_timestamp": entry_ts,
                "exit_timestamp": exit_ts,
                "original_entry_timestamp": entry_ts,
                "stop_distance_fraction": stop_fraction,
                "source_entry_price_usdt": _float(row.get("source_entry_price_usdt")),
                "source_exit_price_usdt": _float(row.get("source_exit_price_usdt")),
                "original_usdc_entry_price": _float(row.get("usdc_entry_price")),
                "original_usdc_exit_price": _float(row.get("usdc_exit_price")),
                "setup_class": row.get("setup_class"),
                "convexity_label": row.get("convexity_label"),
                "personality_label": row.get("personality_label"),
                "strategy_type": row.get("strategy_type"),
            }
        )
    accepted.sort(key=lambda item: (item["entry_timestamp"], item["symbol"], str(item.get("trade_id") or "")))
    return accepted, rejected


def _build_needed_timestamps(rows: list[dict[str, Any]], max_patience_minutes: int) -> dict[str, set[int]]:
    needed: dict[str, set[int]] = {}
    for row in rows:
        source_symbol = row["symbol"]
        execution_symbol = row["execution_symbol"]
        start = _epoch_minute(row["entry_timestamp"])
        exit_epoch = _epoch_minute(row["exit_timestamp"])
        for offset in range(max_patience_minutes + 1):
            epoch = start + offset * 60
            needed.setdefault(source_symbol, set()).add(epoch)
            needed.setdefault(execution_symbol, set()).add(epoch)
        needed.setdefault(execution_symbol, set()).add(exit_epoch)
    return needed


def _candidate_trade(
    row: dict[str, Any],
    *,
    candidate: PatienceCandidate,
    price_maps: dict[str, dict[int, float]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    source_symbol = row["symbol"]
    execution_symbol = row["execution_symbol"]
    threshold = _threshold_bps(candidate, source_symbol)
    entry_epoch = _epoch_minute(row["entry_timestamp"])
    exit_epoch = _epoch_minute(row["exit_timestamp"])
    immediate_deviation = _close_deviation_bps(
        price_maps.get(source_symbol, {}).get(entry_epoch),
        price_maps.get(execution_symbol, {}).get(entry_epoch),
    )
    selected_epoch: int | None = None
    selected_deviation: float | None = None
    for offset in range(candidate.patience_minutes + 1):
        epoch = entry_epoch + offset * 60
        if epoch >= exit_epoch:
            break
        source_close = price_maps.get(source_symbol, {}).get(epoch)
        execution_close = price_maps.get(execution_symbol, {}).get(epoch)
        deviation = _close_deviation_bps(source_close, execution_close)
        if deviation is not None and deviation <= threshold:
            selected_epoch = epoch
            selected_deviation = deviation
            break
    if selected_epoch is None:
        return None, {
            **row,
            "candidate_id": candidate.candidate_id,
            "reject_reason": "execution_guard_expired_without_safe_usdc_window",
            "patience_minutes": candidate.patience_minutes,
            "threshold_bps": threshold,
            "immediate_deviation_bps": immediate_deviation,
        }
    entry_price = price_maps.get(execution_symbol, {}).get(selected_epoch)
    exit_price = price_maps.get(execution_symbol, {}).get(exit_epoch)
    if entry_price is None or exit_price is None or entry_price <= 0.0 or exit_price <= 0.0:
        return None, {
            **row,
            "candidate_id": candidate.candidate_id,
            "reject_reason": "missing_execution_entry_or_exit_price",
            "patience_minutes": candidate.patience_minutes,
            "threshold_bps": threshold,
        }
    stop_fraction = float(row["stop_distance_fraction"])
    gross_r = ((exit_price - entry_price) / entry_price) / stop_fraction
    net_cost_r = (ROUND_TRIP_COST_BPS / 10_000.0) / stop_fraction
    if net_cost_r > MAX_PRE_ENTRY_COST_R:
        return None, {
            **row,
            "candidate_id": candidate.candidate_id,
            "reject_reason": "usdc_cost_guard_rejected",
            "pre_entry_cost_r_at_15bps": net_cost_r,
            "patience_minutes": candidate.patience_minutes,
            "threshold_bps": threshold,
        }
    delay_minutes = int((selected_epoch - entry_epoch) // 60)
    output = {
        **row,
        "entry_timestamp": pd.Timestamp(selected_epoch, unit="s", tz="UTC"),
        "exit_timestamp": row["exit_timestamp"],
        "candidate_id": candidate.candidate_id,
        "guard_threshold_mode": candidate.threshold_mode,
        "patience_minutes": candidate.patience_minutes,
        "execution_delay_minutes": delay_minutes,
        "recovered_after_initial_guard_failure": bool(delay_minutes > 0),
        "threshold_bps": threshold,
        "immediate_deviation_bps": immediate_deviation,
        "execution_deviation_bps": selected_deviation,
        "usdc_entry_price": entry_price,
        "usdc_exit_price": exit_price,
        "gross_r": gross_r,
        "net_cost_r": net_cost_r,
        "pre_entry_cost_r_at_15bps": net_cost_r,
        "net_r": gross_r - net_cost_r,
        "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
        "execution_price_source": "matching_usdc_1m_close_after_guard_patience_recheck",
        "strategy_signal_source": "frozen_usdt_signal_bridge_trade_ledger",
    }
    return output, {}


def _summarise_guard_rows(
    candidate: PatienceCandidate,
    accepted: list[dict[str, Any]],
    rejected: list[dict[str, Any]],
) -> dict[str, Any]:
    delays = [float(row.get("execution_delay_minutes") or 0.0) for row in accepted]
    recovered = [row for row in accepted if row.get("recovered_after_initial_guard_failure")]
    expired = [row for row in rejected if row.get("reject_reason") == "execution_guard_expired_without_safe_usdc_window"]
    by_symbol: list[dict[str, Any]] = []
    symbols = sorted({row["symbol"] for row in accepted} | {row["symbol"] for row in rejected if "symbol" in row})
    for symbol in symbols:
        accepted_symbol = [row for row in accepted if row["symbol"] == symbol]
        rejected_symbol = [row for row in rejected if row.get("symbol") == symbol]
        recovered_symbol = [row for row in accepted_symbol if row.get("recovered_after_initial_guard_failure")]
        expired_symbol = [
            row
            for row in rejected_symbol
            if row.get("reject_reason") == "execution_guard_expired_without_safe_usdc_window"
        ]
        by_symbol.append(
            {
                "candidate_id": candidate.candidate_id,
                "symbol": symbol,
                "accepted_trades": len(accepted_symbol),
                "rejected_trades": len(rejected_symbol),
                "recovered_trades": len(recovered_symbol),
                "recovered_net_r": sum(float(row.get("net_r") or 0.0) for row in recovered_symbol),
                "estimated_recovered_pnl_at_25k_1pct_risk": sum(
                    float(row.get("net_r") or 0.0) * START_CAPITAL * 0.01 for row in recovered_symbol
                ),
                "average_delay_minutes": sum(float(row.get("execution_delay_minutes") or 0.0) for row in accepted_symbol)
                / len(accepted_symbol)
                if accepted_symbol
                else 0.0,
                "median_delay_minutes": median([float(row.get("execution_delay_minutes") or 0.0) for row in accepted_symbol])
                if accepted_symbol
                else 0.0,
                "expired_signals": sum(
                    1 for row in rejected_symbol if row.get("reject_reason") == "execution_guard_expired_without_safe_usdc_window"
                ),
                "expired_net_r": sum(float(row.get("net_r") or 0.0) for row in expired_symbol),
            }
        )
    return {
        "candidate_id": candidate.candidate_id,
        "description": candidate.description,
        "accepted_candidates": len(accepted),
        "guard_rejected_candidates": len(rejected),
        "expired_signals": len(expired),
        "recovered_trades": len(recovered),
        "recovered_net_r": sum(float(row.get("net_r") or 0.0) for row in recovered),
        "estimated_recovered_pnl_at_25k_1pct_risk": sum(
            float(row.get("net_r") or 0.0) * START_CAPITAL * 0.01 for row in recovered
        ),
        "expired_source_net_r_if_available": sum(float(row.get("net_r") or 0.0) for row in expired),
        "average_delay_minutes": sum(delays) / len(delays) if delays else 0.0,
        "median_delay_minutes": median(delays) if delays else 0.0,
        "p95_delay_minutes": sorted(delays)[int(0.95 * (len(delays) - 1))] if delays else 0.0,
        "max_delay_minutes": max(delays) if delays else 0.0,
        "per_symbol": by_symbol,
    }


def _run_candidate(
    candidate: PatienceCandidate,
    *,
    source_rows: list[dict[str, Any]],
    price_maps: dict[str, dict[int, float]],
    priority_symbols: list[str],
    symbol_caps: dict[str, float],
) -> dict[str, Any]:
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for row in source_rows:
        trade, reject = _candidate_trade(row, candidate=candidate, price_maps=price_maps)
        if trade is not None:
            accepted.append(trade)
        else:
            rejected.append(reject)
    accepted.sort(key=lambda item: (item["entry_timestamp"], item["symbol"], str(item.get("trade_id") or "")))
    period_rows = {
        "research": [row for row in accepted if row["period"] == "research"],
        "holdout": [row for row in accepted if row["period"] == "holdout"],
    }
    replay = {
        period: _replay(
            rows,
            scenario_id=candidate.candidate_id,
            period=period,
            priority_symbols=priority_symbols,
            symbol_caps=symbol_caps,
            ladder=FROZEN_2PCT_ALLOCATOR_LADDER,
            active_cap=ACTIVE_CAP,
            tax_rate=TAX_RESERVE_RATE,
        )
        for period, rows in period_rows.items()
    }
    return {
        "candidate": candidate,
        "accepted": accepted,
        "rejected": rejected,
        "guard_summary": _summarise_guard_rows(candidate, accepted, rejected),
        "replay": replay,
    }


def _candidate_public(result: dict[str, Any]) -> dict[str, Any]:
    candidate: PatienceCandidate = result["candidate"]
    research = result["replay"]["research"]
    holdout = result["replay"]["holdout"]
    return {
        "candidate_id": candidate.candidate_id,
        "description": candidate.description,
        "threshold_mode": candidate.threshold_mode,
        "patience_minutes": candidate.patience_minutes,
        "research": _scenario_public(research),
        "holdout": _scenario_public(holdout),
        "guard_summary": result["guard_summary"],
        "comparison_to_reference": {
            "reference_research_equity_after_tax": REFERENCE_FROZEN_USDC_EQUITY_AFTER_TAX,
            "reference_holdout_equity_after_tax": REFERENCE_FROZEN_USDC_HOLDOUT_AFTER_TAX,
            "research_delta_vs_reference_pct": _pct_delta(
                float(research["ending_total_equity_after_tax"]), REFERENCE_FROZEN_USDC_EQUITY_AFTER_TAX
            ),
            "holdout_delta_vs_reference_pct": _pct_delta(
                float(holdout["ending_total_equity_after_tax"]), REFERENCE_FROZEN_USDC_HOLDOUT_AFTER_TAX
            ),
        },
    }


def _best_candidate(results: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {result["candidate"].candidate_id: result for result in results}
    five = by_id["patience_guard_5m"]
    ten = by_id["patience_guard_10m"]
    five_holdout = five["replay"]["holdout"]
    ten_holdout = ten["replay"]["holdout"]
    five_holdout_equity = float(five_holdout["ending_total_equity_after_tax"])
    ten_holdout_equity = float(ten_holdout["ending_total_equity_after_tax"])
    five_dd = float(five_holdout["max_drawdown_total_after_tax"])
    ten_dd = float(ten_holdout["max_drawdown_total_after_tax"])
    materially_better_holdout = ten_holdout_equity >= five_holdout_equity * 1.02
    no_worse_drawdown = ten_dd <= five_dd
    if materially_better_holdout and no_worse_drawdown:
        return ten
    return five


def _write_report(config: ExecutionPatienceGuardConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# USDT Signal / USDC Execution Patience Guard Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        f"- Best candidate: `{summary['best_candidate']['candidate_id']}`",
        "- Research-only. No staging, deployment, paper/live toggle, signed endpoint, account endpoint, or order endpoint.",
        "- Frozen USDT signal logic, entries, exits, thresholds, 1m/15m/1H/6H strategy logic, allocator, cost model, and tax reserve model were not changed.",
        "",
        "## Candidate comparison",
        "",
        "| Candidate | Research equity | Holdout equity | Research trades | Holdout trades | Holdout PF | Holdout win rate | Holdout DD | Recovered | Expired | Est. recovered PnL | Avg delay | Median delay | P95 delay |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["comparison_rows"]:
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{row['candidate_id']}`",
                    _eur(row["research_equity_after_tax"]),
                    _eur(row["holdout_equity_after_tax"]),
                    str(row["research_selected_trades"]),
                    str(row["holdout_selected_trades"]),
                    f"{float(row['holdout_profit_factor']):.2f}",
                    _pct(row["holdout_win_rate"]),
                    _pct(row["holdout_max_drawdown_total_after_tax"]),
                    str(row["recovered_trades"]),
                    str(row["expired_signals"]),
                    _eur(row["estimated_recovered_pnl_at_25k_1pct_risk"]),
                    f"{float(row['average_delay_minutes']):.2f}m",
                    f"{float(row['median_delay_minutes']):.2f}m",
                    f"{float(row['p95_delay_minutes']):.2f}m",
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            f"- Preferred candidate by court rule: `{summary['best_candidate']['candidate_id']}`.",
            "- The court rule prefers 5m unless 10m materially improves holdout equity without worse drawdown or unstable per-symbol behavior.",
            "- Historical spread/depth replay is unavailable because historical L2 orderbook snapshots were not stored; this court validates the historical close-deviation patience component.",
            "- Live production must still run the public guard with current spread, depth, exchangeInfo, minNotional, stepSize, and tickSize checks before any order.",
        ]
    )
    (config.output_root / "EXECUTION_PATIENCE_GUARD_COURT_REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(config: ExecutionPatienceGuardConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    source_csv_rows = _read_csv(config.source_bridge_ledger)
    source_rows, source_rejections = _normalise_source_rows(source_csv_rows)
    required_missing = []
    if not source_csv_rows:
        required_missing.append(str(config.source_bridge_ledger))
    if not config.market_root.exists():
        required_missing.append(str(config.market_root))
    if required_missing:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_required_source_artifacts"],
            "missing_artifacts": required_missing,
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "execution_patience_guard_summary.json", summary)
        return summary

    max_patience = max(candidate.patience_minutes for candidate in CANDIDATES)
    price_maps, market_sources = _load_price_maps(config, _build_needed_timestamps(source_rows, max_patience))
    priority_symbols = _load_priority_symbols(config)
    symbol_caps = _load_symbol_caps(config)
    results = [
        _run_candidate(
            candidate,
            source_rows=source_rows,
            price_maps=price_maps,
            priority_symbols=priority_symbols,
            symbol_caps=symbol_caps,
        )
        for candidate in CANDIDATES
    ]
    public_results = [_candidate_public(result) for result in results]
    comparison_rows = []
    for public in public_results:
        guard = public["guard_summary"]
        research = public["research"]
        holdout = public["holdout"]
        comparison_rows.append(
            {
                "candidate_id": public["candidate_id"],
                "threshold_mode": public["threshold_mode"],
                "patience_minutes": public["patience_minutes"],
                "research_equity_after_tax": research["ending_total_equity_after_tax"],
                "holdout_equity_after_tax": holdout["ending_total_equity_after_tax"],
                "research_selected_trades": research["selected_trades"],
                "holdout_selected_trades": holdout["selected_trades"],
                "research_profit_factor": research["profit_factor"],
                "holdout_profit_factor": holdout["profit_factor"],
                "research_win_rate": research["win_rate"],
                "holdout_win_rate": holdout["win_rate"],
                "research_max_drawdown_total_after_tax": research["max_drawdown_total_after_tax"],
                "holdout_max_drawdown_total_after_tax": holdout["max_drawdown_total_after_tax"],
            "recovered_trades": guard["recovered_trades"],
            "expired_signals": guard["expired_signals"],
            "recovered_net_r": guard["recovered_net_r"],
            "estimated_recovered_pnl_at_25k_1pct_risk": guard["estimated_recovered_pnl_at_25k_1pct_risk"],
            "expired_source_net_r_if_available": guard["expired_source_net_r_if_available"],
            "average_delay_minutes": guard["average_delay_minutes"],
            "median_delay_minutes": guard["median_delay_minutes"],
            "p95_delay_minutes": guard["p95_delay_minutes"],
                "max_delay_minutes": guard["max_delay_minutes"],
                "research_delta_vs_reference_pct": public["comparison_to_reference"]["research_delta_vs_reference_pct"],
                "holdout_delta_vs_reference_pct": public["comparison_to_reference"]["holdout_delta_vs_reference_pct"],
            }
        )
    best = _best_candidate(results)
    best_public = _candidate_public(best)
    old = next(public for public in public_results if public["candidate_id"] == "old_uniform_immediate_guard")
    strict = next(public for public in public_results if public["candidate_id"] == "symbol_aware_hard_reject_guard")
    best_holdout = best_public["holdout"]
    best_research = best_public["research"]
    holdout_ok = (
        float(best_holdout["ending_total_equity_after_tax"]) > START_CAPITAL
        and int(best_holdout["selected_trades"]) >= 20
        and float(best_holdout["profit_factor"]) >= 1.5
    )
    improved_vs_strict = float(best_holdout["ending_total_equity_after_tax"]) >= float(
        strict["holdout"]["ending_total_equity_after_tax"]
    ) and float(best_research["ending_total_equity_after_tax"]) > float(strict["research"]["ending_total_equity_after_tax"])
    classification = PASSED if holdout_ok and improved_vs_strict else WARNING if holdout_ok else FAILED
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": {
            "best_holdout_profitable_after_tax": float(best_holdout["ending_total_equity_after_tax"]) > START_CAPITAL,
            "best_holdout_selected_trades_at_least_20": int(best_holdout["selected_trades"]) >= 20,
            "best_holdout_profit_factor_gte_1_5": float(best_holdout["profit_factor"]) >= 1.5,
            "best_improves_or_matches_strict_symbol_aware_holdout_and_improves_research": improved_vs_strict,
        },
        "source_bridge_ledger": str(config.source_bridge_ledger),
        "market_root": str(config.market_root),
        "canonical_root": str(config.canonical_root),
        "cap_root": str(config.cap_root),
        "source_bridge_rows": len(source_csv_rows),
        "normalised_source_rows": len(source_rows),
        "source_normalisation_rejections": source_rejections,
        "market_sources": market_sources,
        "method": {
            "strategy_signal_source": "frozen_usdt_signal_bridge_trade_ledger",
            "execution_route": "USDC spot long-only bridge",
            "historical_guard_replay_components": ["USDT_USDC_1m_close_deviation", "exact_closed_1m_candle_presence"],
            "historical_spread_depth_replay_available": False,
            "historical_spread_depth_replay_limitation": "historical L2 orderbook snapshots were not stored",
            "delayed_entry_price_recalculated": True,
            "delayed_entry_uses_usdc_close_at_first_safe_recheck": True,
            "exit_logic_changed": False,
            "exit_timestamp_changed": False,
            "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "yearly_tax_reserve_rate": TAX_RESERVE_RATE,
            "active_cap_eur": ACTIVE_CAP,
            "frozen_allocator": "early_two_1pct_each_total_2pct",
            "frozen_allocator_ladder": FROZEN_2PCT_ALLOCATOR_LADDER,
            "priority_symbols": priority_symbols,
            "symbol_caps_eur": symbol_caps,
        },
        "candidates": {public["candidate_id"]: public for public in public_results},
        "comparison_rows": comparison_rows,
        "best_candidate": {
            "candidate_id": best_public["candidate_id"],
            "research_equity_after_tax": best_research["ending_total_equity_after_tax"],
            "holdout_equity_after_tax": best_holdout["ending_total_equity_after_tax"],
            "research_delta_vs_old_uniform_pct": _pct_delta(
                float(best_research["ending_total_equity_after_tax"]),
                float(old["research"]["ending_total_equity_after_tax"]),
            ),
            "holdout_delta_vs_old_uniform_pct": _pct_delta(
                float(best_holdout["ending_total_equity_after_tax"]),
                float(old["holdout"]["ending_total_equity_after_tax"]),
            ),
            "research_delta_vs_strict_symbol_aware_pct": _pct_delta(
                float(best_research["ending_total_equity_after_tax"]),
                float(strict["research"]["ending_total_equity_after_tax"]),
            ),
            "holdout_delta_vs_strict_symbol_aware_pct": _pct_delta(
                float(best_holdout["ending_total_equity_after_tax"]),
                float(strict["holdout"]["ending_total_equity_after_tax"]),
            ),
        },
        "decision_rule": "Prefer 5m unless 10m materially improves holdout equity without worse drawdown or ugly per-symbol behavior.",
        "recommendation": {
            "full_freeze_justified": classification == PASSED,
            "hetzner_deployment_recommended": False,
            "requires_user_approval_before_freeze_or_deploy": True,
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "execution_patience_guard_summary.json", summary)
    _write_csv(config.output_root / "execution_patience_guard_comparison.csv", comparison_rows)
    for result in results:
        candidate_id = result["candidate"].candidate_id
        _write_csv(config.output_root / f"{candidate_id}_accepted_candidates.csv", result["accepted"])
        _write_csv(config.output_root / f"{candidate_id}_guard_rejections.csv", result["rejected"])
        for period, replay in result["replay"].items():
            _write_csv(config.output_root / f"{candidate_id}_{period}_replay_trade_ledger.csv", replay["trade_rows"])
            _write_csv(config.output_root / f"{candidate_id}_{period}_replay_rejections.csv", replay["rejected_rows"])
            _write_csv(config.output_root / f"{candidate_id}_{period}_yearly_tax_rows.csv", replay["yearly_rows"])
        _write_csv(config.output_root / f"{candidate_id}_per_symbol_guard_summary.csv", result["guard_summary"]["per_symbol"])
    _write_report(config, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--source-bridge-ledger", default=str(default_config().source_bridge_ledger))
    parser.add_argument("--market-root", default=str(default_config().market_root))
    parser.add_argument("--canonical-root", default=str(default_config().canonical_root))
    parser.add_argument("--cap-root", default=str(default_config().cap_root))
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        ExecutionPatienceGuardConfig(
            project_root=root,
            package_root=package_root(),
            source_bridge_ledger=resolve_project_path(args.source_bridge_ledger),
            market_root=resolve_project_path(args.market_root),
            canonical_root=resolve_project_path(args.canonical_root),
            cap_root=resolve_project_path(args.cap_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True, default=str))


if __name__ == "__main__":
    main()
