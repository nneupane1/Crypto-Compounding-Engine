from __future__ import annotations

import argparse
import copy
import csv
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.backtest.engine import StructuralBacktestEngine  # noqa: E402
from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path  # noqa: E402
from structural_compounding_lab.config import StructuralLabConfig  # noqa: E402
from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import _apply_frozen_patch, _load_frozen_rules  # noqa: E402
from structural_compounding_lab.diagnostics.cost_aware_frozen_candidate_rebuild import (  # noqa: E402
    CANDIDATE_NAME,
    MAX_PRE_ENTRY_COST_R,
    ROUND_TRIP_COST_BPS,
    _candidate_rows,
    _simulate as _simulate_cost_aware,
)
from structural_compounding_lab.diagnostics.eur25k_sealed_6m_holdout_validation import (  # noqa: E402
    SAFETY_FLAGS,
    START_CAPITAL_25K,
    _quality,
    _read_json,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import _prepare_rows  # noqa: E402
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import _normalize_trade_rows, _read_csv_rows  # noqa: E402
from structural_compounding_lab.diagnostics.multi_asset_earned_parallel_slot_court import (  # noqa: E402
    ACTIVE_CAP,
    START_CAPITAL,
    TAX_RESERVE_RATE,
    USER_LITERAL_SLOT_LADDER,
    _replay,
    _scenario_public,
    _write_csv,
    _write_json,
)
from structural_compounding_lab.diagnostics.multi_asset_earned_parallel_slot_btc_inclusion_court import (  # noqa: E402
    BTC_SYMBOL,
    _load_btc_rows,
)
from structural_compounding_lab.diagnostics.multi_asset_execution_feasibility_scanner_replay_court import _load_assets  # noqa: E402
from structural_compounding_lab.diagnostics.multi_asset_frozen_transfer_court import (  # noqa: E402
    SYMBOL_SPECS,
    _asset_paths,
    _load_market_csv,
)
from structural_compounding_lab.diagnostics.multi_asset_portfolio_selection_court import (  # noqa: E402
    _load_trade_rows,
)


COURT_NAME = "MULTI_SYMBOL_SEALED_HOLDOUT_WARM_STARTED_CONTEXT_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_symbol_sealed_holdout_warm_started_context_court_001"

PASSED = "MULTI_SYMBOL_SEALED_HOLDOUT_WARM_START_VALIDATED_RESEARCH_ONLY"
WARNING = "MULTI_SYMBOL_SEALED_HOLDOUT_WARM_START_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_SYMBOL_SEALED_HOLDOUT_WARM_START_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_SYMBOL_SEALED_HOLDOUT_WARM_START_BLOCKED_RESEARCH_ONLY"

WARMUP_DAYS = 30


@dataclass(frozen=True)
class WarmStartedHoldoutConfig:
    project_root: Path
    package_root: Path
    data_root: Path
    transfer_root: Path
    btc_reference_root: Path
    btc_court_002_root: Path
    btc_cap_root: Path
    nine_symbol_root: Path
    output_root: Path


def default_config() -> WarmStartedHoldoutConfig:
    root = project_root()
    pkg = package_root()
    return WarmStartedHoldoutConfig(
        project_root=root,
        package_root=pkg,
        data_root=root / "data_storage",
        transfer_root=pkg / "output" / "multi_asset_frozen_transfer_court_001",
        btc_reference_root=pkg / "output" / "cost_aware_frozen_candidate_rebuild_court_001",
        btc_court_002_root=pkg / "output" / "eur25k_sealed_6m_holdout_court_002",
        btc_cap_root=pkg / "output" / "multi_symbol_btc_exact_fill_cap_calibration_court_001",
        nine_symbol_root=pkg / "output" / "multi_asset_earned_parallel_slot_btc_inclusion_court_001",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
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


def _read_raw_rows(root: Path, filename: str) -> list[dict[str, Any]]:
    path = root / filename
    if not path.exists() or path.stat().st_size == 0:
        return []
    return _read_csv_rows(path)


def _warm_config(*, analysis_start: str, analysis_end: str, decision_start: str) -> StructuralLabConfig:
    base = StructuralLabConfig.load()
    payload = copy.deepcopy(base.data)
    payload["base_capital"] = START_CAPITAL_25K
    payload["data"]["analysis_start_date"] = analysis_start
    payload["data"]["analysis_end_date"] = analysis_end
    payload["engine"]["decision_start_date"] = decision_start
    payload["engine"]["resume_enabled"] = False
    payload["engine"]["checkpoint_every_bars"] = 0
    payload["engine"]["write_partial_artifacts"] = False
    return StructuralLabConfig(data=payload, config_path=base.config_path, root_dir=base.root_dir)


def _quality_for_range(frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    working = frame.loc[(frame["timestamp"] >= start) & (frame["timestamp"] <= end)].copy()
    return _quality(working.reset_index(drop=True))


def _utc_timestamp(value: Any) -> pd.Timestamp:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        return timestamp.tz_localize("UTC")
    return timestamp.tz_convert("UTC")


def _warm_replay_symbol(
    *,
    config: WarmStartedHoldoutConfig,
    symbol: str,
    source_csv: Path,
    holdout_start: str,
    holdout_end: str,
    output_root: Path,
) -> dict[str, Any]:
    holdout_start_ts = pd.Timestamp(holdout_start)
    holdout_end_ts = pd.Timestamp(holdout_end)
    if holdout_start_ts.tzinfo is None:
        holdout_start_ts = holdout_start_ts.tz_localize("UTC")
    else:
        holdout_start_ts = holdout_start_ts.tz_convert("UTC")
    if holdout_end_ts.tzinfo is None:
        holdout_end_ts = holdout_end_ts.tz_localize("UTC")
    else:
        holdout_end_ts = holdout_end_ts.tz_convert("UTC")
    warmup_start_ts = holdout_start_ts - pd.Timedelta(days=WARMUP_DAYS)

    frame = _load_market_csv(source_csv)
    warmup_quality = _quality_for_range(frame, warmup_start_ts, holdout_start_ts - pd.Timedelta(minutes=1))
    holdout_quality = _quality_for_range(frame, holdout_start_ts, holdout_end_ts)
    raw_engine_root = output_root / "raw_engine"
    raw_engine_root.mkdir(parents=True, exist_ok=True)

    raw_summary = StructuralBacktestEngine(
        config=_warm_config(
            analysis_start=warmup_start_ts.isoformat(),
            analysis_end=holdout_end_ts.isoformat(),
            decision_start=holdout_start_ts.isoformat(),
        )
    ).run(symbol=symbol, source_csv=str(source_csv), output_dir=str(raw_engine_root))

    normalized = _normalize_trade_rows(
        _read_raw_rows(raw_engine_root, "trades.csv"),
        _read_raw_rows(raw_engine_root, "setup_log.csv"),
        _read_raw_rows(raw_engine_root, "level_log.csv"),
        _read_raw_rows(raw_engine_root, "liquidity_events.csv"),
    )
    prepared = _prepare_rows(normalized) if normalized else []
    leaked_rows = [
        row for row in prepared
        if _utc_timestamp(row.get("entry_timestamp") or row.get("entry_time")) < holdout_start_ts
    ]
    prepared = [
        row for row in prepared
        if _utc_timestamp(row.get("entry_timestamp") or row.get("entry_time")) >= holdout_start_ts
    ]

    rules_path = config.package_root / "output" / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json"
    matched_shorts, disabled_longs, rules_payload = _load_frozen_rules(rules_path)
    selected, removed = _apply_frozen_patch(
        prepared,
        matched_short_archetypes=matched_shorts,
        disabled_long_modes=disabled_longs,
    )
    cost_candidate_rows, cost_rejected = _candidate_rows(selected, net_cost_bps=ROUND_TRIP_COST_BPS)
    cost_sim = _simulate_cost_aware(cost_candidate_rows, start_capital=START_CAPITAL_25K)
    _write_csv(output_root / "selected_frozen_rule_trades.csv", selected)
    _write_csv(output_root / "cost_aware_candidate_trades.csv", cost_sim.get("trade_rows", []))
    _write_csv(output_root / "cost_guard_rejected_trades.csv", cost_rejected)

    summary = {
        "symbol": symbol,
        "source_csv": str(source_csv),
        "warmup_days": WARMUP_DAYS,
        "warmup_start": warmup_start_ts.isoformat(),
        "decision_start": holdout_start_ts.isoformat(),
        "holdout_end": holdout_end_ts.isoformat(),
        "decision_gate": {
            "pre_holdout_context_allowed": True,
            "pre_holdout_entries_blocked": True,
            "pre_holdout_pnl_blocked": True,
            "leaked_pre_holdout_trade_count": len(leaked_rows),
            "holdout_entries_only": len(leaked_rows) == 0,
        },
        "quality": {
            "warmup_context": warmup_quality,
            "sealed_holdout": holdout_quality,
            "warmup_context_clean": warmup_quality["gap_count"] == 0
            and warmup_quality["duplicate_count"] == 0
            and warmup_quality["ohlc_sanity_failures"] == 0,
            "sealed_holdout_clean": holdout_quality["gap_count"] == 0
            and holdout_quality["duplicate_count"] == 0
            and holdout_quality["ohlc_sanity_failures"] == 0,
        },
        "raw_engine": {
            "run_state": raw_summary.get("run_state"),
            "trade_count": raw_summary.get("trade_count"),
            "setup_count": raw_summary.get("setup_count"),
            "decision_start_date": holdout_start_ts.isoformat(),
        },
        "frozen_rules": {
            "rules_loaded": bool(rules_payload),
            "raw_engine_trade_count_after_holdout_filter": len(prepared),
            "accepted_trades": len(selected),
            "frozen_rule_rejections": len(removed),
        },
        "cost_aware_candidate": {
            "candidate_name": CANDIDATE_NAME,
            "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "max_pre_entry_cost_r": MAX_PRE_ENTRY_COST_R,
            "accepted_after_cost_guard": len(cost_candidate_rows),
            "rejected_by_cost_guard": len(cost_rejected),
            "gross_selected_before_cost_guard": len(selected),
            **{key: value for key, value in cost_sim.items() if key not in {"equity_curve", "trade_rows", "worst_trade", "best_trade"}},
        },
        **SAFETY_FLAGS,
        "paper_validation_ready": False,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "order_path_created": False,
        "broker_path_created": False,
        "strategy_logic_changed": False,
        "entries_changed": False,
        "exits_changed": False,
        "thresholds_tuned": False,
    }
    _write_json(output_root / "warm_started_holdout_summary.json", summary)
    return _round_payload(summary)


def _first_time(rows: list[dict[str, Any]]) -> pd.Timestamp | None:
    if not rows:
        return None
    return min(_utc_timestamp(row["entry_timestamp"]) for row in rows)


def _symbol_comparison(symbol: str, cold_summary: dict[str, Any], cold_rows: list[dict[str, Any]], warm_summary: dict[str, Any], warm_rows: list[dict[str, Any]]) -> dict[str, Any]:
    cold_first = _first_time(cold_rows)
    warm_first = _first_time(warm_rows)
    cold_equity = float(cold_summary.get("ending_equity") or 0.0)
    warm_equity = float(warm_summary.get("cost_aware_candidate", {}).get("ending_equity") or 0.0)
    early_before_cold = [
        row for row in warm_rows
        if cold_first is not None and _utc_timestamp(row["entry_timestamp"]) < cold_first
    ]
    return {
        "symbol": symbol,
        "cold_first_trade": cold_first.isoformat() if cold_first is not None else None,
        "warm_first_trade": warm_first.isoformat() if warm_first is not None else None,
        "warm_first_trade_hours_vs_cold": (
            (warm_first - cold_first).total_seconds() / 3600.0
            if cold_first is not None and warm_first is not None
            else None
        ),
        "warm_extra_trades_before_cold_first": len(early_before_cold),
        "cold_accepted_after_cost_guard": len(cold_rows),
        "warm_accepted_after_cost_guard": len(warm_rows),
        "cold_symbol_ending_equity_eur": cold_equity,
        "warm_symbol_ending_equity_eur": warm_equity,
        "warm_minus_cold_symbol_equity_eur": warm_equity - cold_equity,
        "warm_vs_cold_symbol_equity_pct": ((warm_equity - cold_equity) / cold_equity * 100.0) if cold_equity else None,
    }


def _load_symbol_caps(config: WarmStartedHoldoutConfig) -> dict[str, float]:
    cap_path = config.btc_cap_root / "nine_symbol_recommended_symbol_caps_manifest.json"
    payload = _read_json(cap_path, {}) if cap_path.exists() else {}
    caps = payload.get("recommended_symbol_caps_eur") or {}
    return {str(symbol): float(value) for symbol, value in caps.items()}


def run(config: WarmStartedHoldoutConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)

    required = [
        config.transfer_root / "multi_asset_frozen_transfer_summary.json",
        config.nine_symbol_root / "multi_asset_earned_parallel_slot_btc_inclusion_summary.json",
        config.btc_reference_root / "candidate_holdout_results.csv",
        config.btc_court_002_root / "split_manifest.json",
        config.btc_cap_root / "nine_symbol_recommended_symbol_caps_manifest.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_required_source_artifacts"],
            "missing_artifacts": missing,
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_symbol_sealed_holdout_warm_started_context_summary.json", summary)
        return _round_payload(summary)

    assets = _load_assets(type("ScannerConfig", (), {"transfer_root": config.transfer_root})())
    btc_rows = _load_btc_rows(type("BTCConfig", (), {"btc_reference_root": config.btc_reference_root})())
    existing_9 = _read_json(config.nine_symbol_root / "multi_asset_earned_parallel_slot_btc_inclusion_summary.json", {})
    best_policy = str(existing_9.get("best_btc_policy") or "btc_research_ranked_9_symbol")
    best_variant = str(existing_9.get("best_btc_variant") or "user_literal_1pct_each_slot")
    priority_symbols = list((existing_9.get("comparisons") or {}).get(best_policy, {}).get("priority_symbols") or [])
    if not priority_symbols:
        priority_symbols = ["ADAUSDT", "LINKUSDT", "BNBUSDT", "XRPUSDT", "AVAXUSDT", "DOGEUSDT", "ETHUSDT", "BTCUSDT", "SOLUSDT"]
    symbol_caps = _load_symbol_caps(config)

    warm_rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
    cold_rows_by_symbol: dict[str, list[dict[str, Any]]] = {}
    symbol_rows: list[dict[str, Any]] = []

    for symbol, _start_date in SYMBOL_SPECS:
        paths = _asset_paths(type("TransferConfig", (), {"output_root": config.transfer_root})(), symbol)
        split = _read_json(paths["split_manifest"], {})
        cold_summary = _read_json(paths["holdout_root"] / "sealed_holdout_summary.json", {}).get("cost_aware_candidate", {})
        cold_rows = _load_trade_rows(paths["holdout_root"] / "cost_aware_candidate_trades.csv", symbol_override=symbol, period="holdout")
        source_csv = Path(str(split["source_csv"]))
        warm_root = config.output_root / "assets" / symbol / "warm_started_sealed_holdout"
        warm_summary = _warm_replay_symbol(
            config=config,
            symbol=symbol,
            source_csv=source_csv,
            holdout_start=str(split["holdout_start"]),
            holdout_end=str(split["holdout_end"]),
            output_root=warm_root,
        )
        warm_rows = _load_trade_rows(warm_root / "cost_aware_candidate_trades.csv", symbol_override=symbol, period="holdout")
        cold_rows_by_symbol[symbol] = cold_rows
        warm_rows_by_symbol[symbol] = warm_rows
        symbol_rows.append(_symbol_comparison(symbol, cold_summary, cold_rows, warm_summary, warm_rows))

    btc_split = _read_json(config.btc_court_002_root / "split_manifest.json", {})
    btc_source = Path(str(btc_split.get("combined_court_dataset_path") or btc_split.get("merged_court_dataset_path")))
    btc_cold_summary = _read_json(config.btc_reference_root / "cost_aware_frozen_candidate_rebuild_summary.json", {}).get("sealed_holdout", {})
    btc_cold_rows = btc_rows["holdout_rows"]
    btc_warm_root = config.output_root / "assets" / BTC_SYMBOL / "warm_started_sealed_holdout"
    btc_warm_summary = _warm_replay_symbol(
        config=config,
        symbol=BTC_SYMBOL,
        source_csv=btc_source,
        holdout_start=str(btc_split["holdout_start"]),
        holdout_end=str(btc_split["holdout_end"]),
        output_root=btc_warm_root,
    )
    btc_warm_rows = _load_trade_rows(btc_warm_root / "cost_aware_candidate_trades.csv", symbol_override=BTC_SYMBOL, period="holdout")
    cold_rows_by_symbol[BTC_SYMBOL] = btc_cold_rows
    warm_rows_by_symbol[BTC_SYMBOL] = btc_warm_rows
    symbol_rows.append(_symbol_comparison(BTC_SYMBOL, btc_cold_summary, btc_cold_rows, btc_warm_summary, btc_warm_rows))

    cold_portfolio_rows = sorted(
        [row for symbol in priority_symbols for row in cold_rows_by_symbol.get(symbol, [])],
        key=lambda row: (row["entry_timestamp"], row["symbol"], str(row.get("trade_id") or "")),
    )
    warm_portfolio_rows = sorted(
        [row for symbol in priority_symbols for row in warm_rows_by_symbol.get(symbol, [])],
        key=lambda row: (row["entry_timestamp"], row["symbol"], str(row.get("trade_id") or "")),
    )
    cold_portfolio = _replay(
        cold_portfolio_rows,
        scenario_id="cold_start_9_symbol_holdout:user_literal_1pct_each_slot",
        period="holdout",
        priority_symbols=priority_symbols,
        symbol_caps=symbol_caps,
        ladder=USER_LITERAL_SLOT_LADDER,
        active_cap=ACTIVE_CAP,
        tax_rate=TAX_RESERVE_RATE,
    )
    warm_portfolio = _replay(
        warm_portfolio_rows,
        scenario_id="warm_started_9_symbol_holdout:user_literal_1pct_each_slot",
        period="holdout",
        priority_symbols=priority_symbols,
        symbol_caps=symbol_caps,
        ladder=USER_LITERAL_SLOT_LADDER,
        active_cap=ACTIVE_CAP,
        tax_rate=TAX_RESERVE_RATE,
    )

    first_cold = _first_time(cold_portfolio_rows)
    first_warm = _first_time(warm_portfolio_rows)
    warm_better = float(warm_portfolio["ending_total_equity_after_tax"]) >= float(cold_portfolio["ending_total_equity_after_tax"])
    holdout_starts: dict[str, pd.Timestamp] = {}
    for symbol, _start_date in SYMBOL_SPECS:
        split = _read_json(_asset_paths(type("TransferConfig", (), {"output_root": config.transfer_root})(), symbol)["split_manifest"], {})
        holdout_starts[symbol] = _utc_timestamp(split["holdout_start"])
    holdout_starts[BTC_SYMBOL] = _utc_timestamp(btc_split["holdout_start"])
    no_leakage = all(
        row.get("warm_first_trade") is None
        or _utc_timestamp(row["warm_first_trade"]) >= holdout_starts[row["symbol"]]
        for row in symbol_rows
    )
    all_clean = all(
        _read_json(config.output_root / "assets" / row["symbol"] / "warm_started_sealed_holdout" / "warm_started_holdout_summary.json", {})
        .get("quality", {})
        .get("sealed_holdout_clean")
        for row in symbol_rows
    )
    if no_leakage and all_clean and warm_better:
        classification = PASSED
        reasons = ["warm_started_holdout_context_preserved_or_improved_net_after_tax_pnl_without_leakage"]
    elif no_leakage and all_clean:
        classification = WARNING
        reasons = ["warm_started_holdout_context_valid_but_pnl_changed_lower_than_cold_start"]
    else:
        classification = FAILED
        reasons = ["warm_started_holdout_context_failed_quality_or_leakage_gate"]

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "warmup_days": WARMUP_DAYS,
        "source_9_symbol_freeze_root": str(config.nine_symbol_root),
        "source_transfer_root": str(config.transfer_root),
        "source_btc_reference_root": str(config.btc_reference_root),
        "source_btc_court_002_root": str(config.btc_court_002_root),
        "best_policy_retested": best_policy,
        "best_variant_retested": best_variant,
        "priority_symbols": priority_symbols,
        "symbol_caps_eur": symbol_caps,
        "method": {
            "pre_holdout_context_allowed": True,
            "decision_start_date_blocks_pre_holdout_entries": True,
            "pre_holdout_pnl_counted": False,
            "holdout_pnl_counted_only_after_entry_inside_holdout": True,
            "future_holdout_candles_available_before_arrival": False,
            "strategy_logic_changed": False,
            "entries_changed": False,
            "exits_changed": False,
            "thresholds_tuned": False,
            "scheduler_changed": False,
            "cost_model": "existing 15bps net-cost guard plus yearly tax reserve in portfolio replay",
        },
        "portfolio_comparison": {
            "cold_start": _scenario_public(cold_portfolio),
            "warm_started": _scenario_public(warm_portfolio),
            "first_cold_trade": first_cold.isoformat() if first_cold is not None else None,
            "first_warm_trade": first_warm.isoformat() if first_warm is not None else None,
            "warm_first_trade_hours_vs_cold": (
                (first_warm - first_cold).total_seconds() / 3600.0
                if first_cold is not None and first_warm is not None
                else None
            ),
            "warm_minus_cold_ending_total_after_tax_eur": float(warm_portfolio["ending_total_equity_after_tax"])
            - float(cold_portfolio["ending_total_equity_after_tax"]),
            "warm_vs_cold_ending_total_after_tax_pct": (
                (float(warm_portfolio["ending_total_equity_after_tax"]) - float(cold_portfolio["ending_total_equity_after_tax"]))
                / float(cold_portfolio["ending_total_equity_after_tax"])
                * 100.0
            )
            if float(cold_portfolio["ending_total_equity_after_tax"])
            else None,
        },
        "symbol_comparison": symbol_rows,
        **SAFETY_FLAGS,
        "paper_validation_ready": False,
        "paper_allowed": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "order_path_created": False,
        "broker_path_created": False,
        "private_endpoint_used": False,
        "signed_endpoint_used": False,
    }
    _write_json(config.output_root / "multi_symbol_sealed_holdout_warm_started_context_summary.json", summary)
    _write_csv(config.output_root / "multi_symbol_sealed_holdout_warm_started_context_symbol_comparison.csv", symbol_rows)
    _write_csv(config.output_root / "warm_started_9_symbol_holdout_trade_ledger.csv", warm_portfolio["trade_rows"])
    _write_csv(config.output_root / "cold_start_9_symbol_holdout_trade_ledger.csv", cold_portfolio["trade_rows"])
    return _round_payload(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    base = default_config()
    summary = run(
        WarmStartedHoldoutConfig(
            project_root=base.project_root,
            package_root=base.package_root,
            data_root=base.data_root,
            transfer_root=base.transfer_root,
            btc_reference_root=base.btc_reference_root,
            btc_court_002_root=base.btc_court_002_root,
            btc_cap_root=base.btc_cap_root,
            nine_symbol_root=base.nine_symbol_root,
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
