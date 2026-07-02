from __future__ import annotations

import argparse
import csv
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path
from structural_compounding_lab.diagnostics.multi_asset_portfolio_selection_court import (
    RISK_PER_TRADE,
    SAFETY_FLAGS,
    START_CAPITAL,
    TRANSFER_ASSETS,
    _asset_paths,
    _load_trade_rows,
    _max_drawdown,
    _profit_factor,
    _read_json,
    _safe_ratio,
    _select_non_overlapping_shared_pool,
    _write_csv,
    _write_json,
)


COURT_NAME = "MULTI_ASSET_EXECUTION_FEASIBILITY_SCANNER_REPLAY_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_asset_execution_feasibility_scanner_replay_court_001"

PASSED = "MULTI_ASSET_SCANNER_REPLAY_VALIDATED_RESEARCH_ONLY"
WARNING = "MULTI_ASSET_SCANNER_REPLAY_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_ASSET_SCANNER_REPLAY_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_ASSET_SCANNER_REPLAY_BLOCKED_RESEARCH_ONLY"

FREEZE_CANDIDATE = "MULTI_ASSET_RESEARCH_SPEC_FREEZE_CANDIDATE_NOT_LIVE"
FREEZE_BLOCKED = "MULTI_ASSET_RESEARCH_SPEC_FREEZE_BLOCKED_NEEDS_REVIEW"


@dataclass(frozen=True)
class ScannerReplayConfig:
    project_root: Path
    package_root: Path
    transfer_root: Path
    portfolio_root: Path
    output_root: Path


def default_config() -> ScannerReplayConfig:
    pkg = package_root()
    return ScannerReplayConfig(
        project_root=project_root(),
        package_root=pkg,
        transfer_root=pkg / "output" / "multi_asset_frozen_transfer_court_001",
        portfolio_root=pkg / "output" / "multi_asset_portfolio_selection_court_001",
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


def _load_assets(config: ScannerReplayConfig) -> dict[str, dict[str, Any]]:
    assets: dict[str, dict[str, Any]] = {}
    for symbol in TRANSFER_ASSETS:
        paths = _asset_paths(
            type(
                "PathsConfig",
                (),
                {
                    "transfer_root": config.transfer_root,
                },
            )(),
            symbol,
        )
        if not paths["summary"].exists():
            continue
        assets[symbol] = {
            "summary": _read_json(paths["summary"]),
            "split": _read_json(paths["split"]) if paths["split"].exists() else {},
            "freeze": _read_json(paths["freeze"]) if paths["freeze"].exists() else {},
            "research_rows": _load_trade_rows(paths["research_trades"], symbol_override=symbol, period="research"),
            "holdout_rows": _load_trade_rows(paths["holdout_trades"], symbol_override=symbol, period="holdout"),
        }
    return assets


def _timestamp_alignment(rows: list[dict[str, Any]]) -> dict[str, Any]:
    bad: list[dict[str, Any]] = []
    for row in rows:
        entry = row["entry_timestamp"]
        exit_ = row["exit_timestamp"]
        if entry.minute != 0 or entry.second != 0 or entry.microsecond != 0:
            bad.append({"symbol": row["symbol"], "trade_id": row.get("trade_id"), "entry_time": entry.isoformat(), "reason": "entry_not_1h_aligned"})
        if exit_ < entry:
            bad.append({"symbol": row["symbol"], "trade_id": row.get("trade_id"), "entry_time": entry.isoformat(), "exit_time": exit_.isoformat(), "reason": "exit_before_entry"})
    return {
        "checked_trades": len(rows),
        "bad_timestamp_count": len(bad),
        "bad_timestamps": bad[:50],
        "all_entries_1h_aligned": len([item for item in bad if item["reason"] == "entry_not_1h_aligned"]) == 0,
        "all_exits_after_entries": len([item for item in bad if item["reason"] == "exit_before_entry"]) == 0,
    }


def _overlap_audit(selected_rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows = sorted(selected_rows, key=lambda row: (row["entry_timestamp"], row["exit_timestamp"], row["symbol"]))
    overlaps: list[dict[str, Any]] = []
    active_until: pd.Timestamp | None = None
    active_symbol = ""
    active_trade = ""
    for row in rows:
        if active_until is not None and row["entry_timestamp"] <= active_until:
            overlaps.append(
                {
                    "active_symbol": active_symbol,
                    "active_trade_id": active_trade,
                    "active_until": active_until.isoformat(),
                    "overlap_symbol": row["symbol"],
                    "overlap_trade_id": row.get("trade_id"),
                    "overlap_entry_time": row["entry_timestamp"].isoformat(),
                }
            )
        if active_until is None or row["exit_timestamp"] > active_until:
            active_until = row["exit_timestamp"]
            active_symbol = row["symbol"]
            active_trade = str(row.get("trade_id") or "")
    return {
        "selected_trades": len(rows),
        "overlap_violation_count": len(overlaps),
        "overlap_violations": overlaps[:50],
        "max_one_active_trade_respected": len(overlaps) == 0,
    }


def _simulate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    equity = START_CAPITAL
    curve = [equity]
    trade_rows: list[dict[str, Any]] = []
    for index, row in enumerate(sorted(rows, key=lambda item: (item["entry_timestamp"], item["symbol"])), start=1):
        before = equity
        risk = before * RISK_PER_TRADE
        pnl = risk * float(row["net_r"])
        equity = before + pnl
        curve.append(equity)
        trade_rows.append(
            {
                "scanner_trade_number": index,
                "symbol": row["symbol"],
                "trade_id": row.get("trade_id"),
                "entry_time": row["entry_timestamp"].isoformat(),
                "exit_time": row["exit_timestamp"].isoformat(),
                "side": row.get("side"),
                "net_r": row["net_r"],
                "net_cost_r": row.get("net_cost_r"),
                "selection_rank": row.get("selection_rank"),
                "selection_reason": row.get("selection_reason"),
                "equity_before_trade": before,
                "risk_eur": risk,
                "net_pnl_eur": pnl,
                "equity_after_trade": equity,
            }
        )
    values = [float(row["net_r"]) for row in rows]
    return {
        "starting_equity": START_CAPITAL,
        "ending_equity": equity,
        "net_gain": equity - START_CAPITAL,
        "return_multiple": _safe_ratio(equity, START_CAPITAL, 0.0),
        "accepted_trades": len(rows),
        "net_total_R": sum(values),
        "profit_factor": _profit_factor(values),
        "win_rate": _safe_ratio(sum(1 for value in values if value > 0.0), len(values), 0.0),
        "max_drawdown": _max_drawdown(curve),
        "largest_loss_R": min(values) if values else 0.0,
        "trade_rows": trade_rows,
    }


def _symbol_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_symbol.setdefault(row["symbol"], []).append(row)
    output: list[dict[str, Any]] = []
    for symbol, bucket in sorted(by_symbol.items()):
        values = [float(row["net_r"]) for row in bucket]
        output.append(
            {
                "symbol": symbol,
                "selected_trades": len(bucket),
                "net_total_R": sum(values),
                "profit_factor": _profit_factor(values),
                "win_rate": _safe_ratio(sum(1 for value in values if value > 0.0), len(values), 0.0),
            }
        )
    return output


def _candidate_event_audit(rows: list[dict[str, Any]], selected: list[dict[str, Any]], rejected: list[dict[str, Any]]) -> dict[str, Any]:
    by_time: dict[str, set[str]] = {}
    for row in rows:
        by_time.setdefault(row["entry_timestamp"].isoformat(), set()).add(row["symbol"])
    simultaneous_events = {time: sorted(symbols) for time, symbols in by_time.items() if len(symbols) > 1}
    return {
        "candidate_trade_count": len(rows),
        "selected_trade_count": len(selected),
        "rejected_overlap_count": len(rejected),
        "simultaneous_candidate_event_count": len(simultaneous_events),
        "simultaneous_candidate_event_examples": [
            {"entry_time": time, "symbols": symbols} for time, symbols in list(sorted(simultaneous_events.items()))[:25]
        ],
        "selection_uses_future_return": False,
        "selection_uses_future_exit": False,
        "selection_inputs": ["entry_timestamp", "fixed_research_rank_priority", "active_trade_until", "pre_entry_cost_r_tiebreak"],
    }


def _data_readiness_audit(assets: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for symbol, payload in sorted(assets.items()):
        summary = payload["summary"]
        split = payload["split"]
        freeze = payload["freeze"]
        anti = summary.get("anti_leakage_audit", {})
        rows.append(
            {
                "symbol": symbol,
                "source_csv": split.get("source_csv"),
                "source_file_unchanged": bool(anti.get("source_file_unchanged")),
                "holdout_clean": bool(split.get("holdout_clean")),
                "holdout_gap_violations": len(split.get("holdout_gap_violations") or []),
                "holdout_opened_once": bool(anti.get("holdout_opened_once")),
                "holdout_opened_after_freeze": bool(anti.get("holdout_opened_after_freeze")),
                "strategy_unchanged_between_freeze_and_holdout": bool(anti.get("strategy_unchanged_between_freeze_and_holdout")),
                "no_synthetic_candles_inserted": bool(anti.get("no_synthetic_candles_inserted")),
                "historical_research_gaps_exchange_confirmed": bool(anti.get("historical_research_gaps_exchange_confirmed")),
                "eur_25000_diagnostic_capital": bool(freeze.get("eur_25000_diagnostic_capital")),
                "eur_25000_active_sizing": bool(freeze.get("eur_25000_active_sizing")),
            }
        )
    return rows


def _write_report(config: ScannerReplayConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# Multi-Asset Execution Feasibility Scanner Replay Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        f"- Freeze recommendation: `{summary['research_freeze_recommendation']}`",
        "- Research-only. No paper/live/order/broker path enabled.",
        "- Scanner replay uses fixed research ranking and max-one-active-trade execution.",
        "",
        "## Fixed scanner universe",
        "",
        f"- Rank: `{', '.join(summary['fixed_scanner_priority'])}`",
        f"- Selection inputs: `{', '.join(summary['scanner_methodology']['selection_inputs'])}`",
        "- Future return / exit data used for selection: `false`",
        "",
        "## Replay results",
        "",
        "| Period | Candidates | Selected | Rejected overlaps | Ending equity | Max DD | Timestamp aligned | Max-one-active |",
        "| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for period in ("research", "sealed_holdout"):
        replay = summary["scanner_replay"][period]
        lines.append(
            "| {period} | {candidates} | {selected} | {rejected} | €{ending:,.2f} | {dd:.2%} | {aligned} | {one_active} |".format(
                period=period,
                candidates=int(replay["candidate_event_audit"]["candidate_trade_count"]),
                selected=int(replay["simulation"]["accepted_trades"]),
                rejected=int(replay["candidate_event_audit"]["rejected_overlap_count"]),
                ending=float(replay["simulation"]["ending_equity"]),
                dd=float(replay["simulation"]["max_drawdown"]),
                aligned=str(bool(replay["timestamp_alignment"]["all_entries_1h_aligned"])).lower(),
                one_active=str(bool(replay["overlap_audit"]["max_one_active_trade_respected"])).lower(),
            )
        )
    lines.extend(
        [
            "",
            "## Holdout selected symbol breakdown",
            "",
            "| Symbol | Selected trades | Net total R | PF | Win rate |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in summary["scanner_replay"]["sealed_holdout"]["symbol_breakdown"]:
        lines.append(
            "| {symbol} | {trades} | {r:.2f} | {pf:.2f} | {wr:.2%} |".format(
                symbol=row["symbol"],
                trades=int(row["selected_trades"]),
                r=float(row["net_total_R"]),
                pf=float(row["profit_factor"]),
                wr=float(row["win_rate"]),
            )
        )
    lines.extend(
        [
            "",
            "## Freeze note",
            "",
            "- This court supports freezing a research scanner specification.",
            "- It does not authorize paper/live/broker/order execution.",
            "- Before real capital, the next evidence needed is scheduler-integrated multi-symbol dry-run and capacity/liquidity stress.",
        ]
    )
    (config.output_root / "multi_asset_execution_feasibility_scanner_replay_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: ScannerReplayConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    portfolio_summary_path = config.portfolio_root / "multi_asset_portfolio_selection_summary.json"
    transfer_summary_path = config.transfer_root / "multi_asset_frozen_transfer_summary.json"
    if not portfolio_summary_path.exists() or not transfer_summary_path.exists():
        summary = {
            "court_name": COURT_NAME,
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_portfolio_or_transfer_summary"],
            "research_freeze_recommendation": FREEZE_BLOCKED,
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_asset_execution_feasibility_scanner_replay_summary.json", summary)
        return summary

    portfolio = _read_json(portfolio_summary_path)
    transfer = _read_json(transfer_summary_path)
    assets = _load_assets(config)
    missing = [symbol for symbol in TRANSFER_ASSETS if symbol not in assets]
    if missing:
        summary = {
            "court_name": COURT_NAME,
            "final_classification": BLOCKED,
            "classification_reasons": [f"missing_asset_artifacts:{','.join(missing)}"],
            "research_freeze_recommendation": FREEZE_BLOCKED,
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_asset_execution_feasibility_scanner_replay_summary.json", summary)
        return summary

    priority_symbols = list(portfolio.get("research_rank_by_ending_equity") or [])
    if set(priority_symbols) != set(TRANSFER_ASSETS):
        priority_symbols = list(TRANSFER_ASSETS)
    priority = {symbol: index for index, symbol in enumerate(priority_symbols, start=1)}

    data_readiness = _data_readiness_audit(assets)
    readiness_ok = all(
        row["source_file_unchanged"]
        and row["holdout_clean"]
        and row["holdout_gap_violations"] == 0
        and row["holdout_opened_once"]
        and row["holdout_opened_after_freeze"]
        and row["strategy_unchanged_between_freeze_and_holdout"]
        and row["no_synthetic_candles_inserted"]
        and row["historical_research_gaps_exchange_confirmed"]
        and row["eur_25000_diagnostic_capital"]
        and not row["eur_25000_active_sizing"]
        for row in data_readiness
    )

    replay: dict[str, Any] = {}
    selected_files: dict[str, Path] = {}
    for period, row_key in (("research", "research_rows"), ("sealed_holdout", "holdout_rows")):
        all_rows = [row for symbol in priority_symbols for row in assets[symbol][row_key]]
        selected, rejected = _select_non_overlapping_shared_pool(all_rows, allowed_symbols=priority_symbols, symbol_priority=priority)
        sim = _simulate(selected)
        timestamp = _timestamp_alignment(all_rows)
        selected_timestamp = _timestamp_alignment(selected)
        overlap = _overlap_audit(selected)
        candidate_audit = _candidate_event_audit(all_rows, selected, rejected)
        selected_files[f"{period}_selected"] = config.output_root / f"{period}_scanner_selected_trades.csv"
        selected_files[f"{period}_rejected"] = config.output_root / f"{period}_scanner_rejected_overlaps.csv"
        _write_csv(selected_files[f"{period}_selected"], sim["trade_rows"])
        _write_csv(
            selected_files[f"{period}_rejected"],
            [
                {
                    "symbol": row["symbol"],
                    "trade_id": row.get("trade_id"),
                    "entry_time": row["entry_timestamp"].isoformat(),
                    "exit_time": row["exit_timestamp"].isoformat(),
                    "selection_reason": row.get("selection_reason"),
                    "selection_rank": row.get("selection_rank"),
                }
                for row in rejected
            ],
        )
        replay[period] = {
            "simulation": {key: value for key, value in sim.items() if key != "trade_rows"},
            "candidate_event_audit": candidate_audit,
            "timestamp_alignment": timestamp,
            "selected_timestamp_alignment": selected_timestamp,
            "overlap_audit": overlap,
            "symbol_breakdown": _symbol_breakdown(selected),
            "selected_trades_file": str(selected_files[f"{period}_selected"]),
            "rejected_overlaps_file": str(selected_files[f"{period}_rejected"]),
        }

    methodology_ok = (
        transfer.get("strategy_changes", {}).get("entries_changed") is False
        and transfer.get("strategy_changes", {}).get("exits_changed") is False
        and transfer.get("strategy_changes", {}).get("thresholds_tuned") is False
        and portfolio.get("methodology", {}).get("strategy_logic_changed") is False
        and portfolio.get("methodology", {}).get("holdout_rank_is_observation_only") is True
    )
    replay_ok = all(
        replay[period]["timestamp_alignment"]["all_entries_1h_aligned"]
        and replay[period]["timestamp_alignment"]["all_exits_after_entries"]
        and replay[period]["selected_timestamp_alignment"]["all_entries_1h_aligned"]
        and replay[period]["overlap_audit"]["max_one_active_trade_respected"]
        for period in ("research", "sealed_holdout")
    )
    holdout_profitable = replay["sealed_holdout"]["simulation"]["ending_equity"] > START_CAPITAL
    holdout_trade_count_ok = replay["sealed_holdout"]["simulation"]["accepted_trades"] >= 50
    holdout_drawdown_ok = replay["sealed_holdout"]["simulation"]["max_drawdown"] <= 0.10

    reasons: list[str] = []
    if readiness_ok and methodology_ok and replay_ok and holdout_profitable and holdout_trade_count_ok and holdout_drawdown_ok:
        classification = PASSED
        freeze_recommendation = FREEZE_CANDIDATE
        reasons.append("fixed_priority_scanner_replay_passed_research_and_sealed_holdout")
    elif readiness_ok and methodology_ok and replay_ok and holdout_profitable:
        classification = WARNING
        freeze_recommendation = FREEZE_BLOCKED
        reasons.append("scanner_replay_profitable_but_trade_count_or_drawdown_warning")
    else:
        classification = FAILED
        freeze_recommendation = FREEZE_BLOCKED
        if not readiness_ok:
            reasons.append("data_or_holdout_readiness_audit_failed")
        if not methodology_ok:
            reasons.append("methodology_audit_failed")
        if not replay_ok:
            reasons.append("scanner_replay_alignment_or_overlap_audit_failed")
        if not holdout_profitable:
            reasons.append("sealed_holdout_scanner_replay_not_profitable")

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "research_freeze_recommendation": freeze_recommendation,
        "source_portfolio_summary": str(portfolio_summary_path),
        "source_transfer_summary": str(transfer_summary_path),
        "fixed_scanner_priority": priority_symbols,
        "scanner_methodology": {
            "universe_fixed_before_replay": True,
            "priority_fixed_from_research_rank_only": True,
            "holdout_rank_used_for_selection": False,
            "selection_inputs": ["entry_timestamp", "fixed_research_rank_priority", "active_trade_until", "pre_entry_cost_r_tiebreak"],
            "uses_future_return": False,
            "uses_future_exit": False,
            "max_one_active_trade": True,
            "risk_per_trade": RISK_PER_TRADE,
            "source_timeframe": "1H accepted trade events from completed cost-aware ledgers",
            "strategy_logic_changed": False,
            "entries_changed": False,
            "exits_changed": False,
            "thresholds_tuned": False,
        },
        "data_readiness_audit": data_readiness,
        "data_readiness_passed": readiness_ok,
        "methodology_audit_passed": methodology_ok,
        "scanner_replay_passed": replay_ok,
        "scanner_replay": replay,
        "freeze_gate": {
            "may_freeze_research_scanner_spec": freeze_recommendation == FREEZE_CANDIDATE,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "next_required_court_before_real_capital": "MULTI_SYMBOL_SCHEDULER_DRY_RUN_AND_CAPACITY_LIQUIDITY_COURT",
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_asset_execution_feasibility_scanner_replay_summary.json", summary)
    _write_csv(config.output_root / "multi_asset_scanner_data_readiness_audit.csv", data_readiness)
    _write_report(config, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run multi-asset scanner replay feasibility court from completed portfolio artifacts.")
    parser.add_argument("--transfer-root", default=f"structural_compounding_lab/output/multi_asset_frozen_transfer_court_001")
    parser.add_argument("--portfolio-root", default=f"structural_compounding_lab/output/multi_asset_portfolio_selection_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        ScannerReplayConfig(
            project_root=root,
            package_root=package_root(),
            transfer_root=resolve_project_path(args.transfer_root),
            portfolio_root=resolve_project_path(args.portfolio_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
