from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import math
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
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
    START_CAPITAL_20K,
    START_CAPITAL_25K,
    _hash_map,
    _quality,
    _read_json,
    _sha256,
    _signature,
    _strategy_files,
    _write_json,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import _prepare_rows, _simulate_variant  # noqa: E402
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import _normalize_trade_rows, _read_csv_rows  # noqa: E402


COURT_NAME = "MULTI_ASSET_FROZEN_TRANSFER_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_asset_frozen_transfer_court_001"
PASSED = "MULTI_ASSET_FROZEN_TRANSFER_VALIDATED_RESEARCH_ONLY"
WARNING = "MULTI_ASSET_FROZEN_TRANSFER_PROMISING_WITH_WARNINGS_RESEARCH_ONLY"
FAILED = "MULTI_ASSET_FROZEN_TRANSFER_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_ASSET_FROZEN_TRANSFER_BLOCKED_RESEARCH_ONLY"

SYMBOL_SPECS: tuple[tuple[str, str], ...] = (
    ("ETHUSDT", "2018-01-01"),
    ("BNBUSDT", "2018-01-01"),
    ("XRPUSDT", "2018-05-04"),
    ("ADAUSDT", "2018-04-17"),
    ("LINKUSDT", "2019-01-16"),
    ("DOGEUSDT", "2019-07-05"),
    ("SOLUSDT", "2020-08-11"),
    ("AVAXUSDT", "2020-09-22"),
)


@dataclass(frozen=True)
class MultiAssetTransferConfig:
    project_root: Path
    package_root: Path
    data_root: Path
    output_root: Path
    end_date: str = "2026-06-27"


def default_config() -> MultiAssetTransferConfig:
    root = project_root()
    return MultiAssetTransferConfig(
        project_root=root,
        package_root=package_root(),
        data_root=root / "data_storage",
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


def _write_json_round(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_round_payload(payload), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in keys})


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


def _git_commit(root: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def _source_path(config: MultiAssetTransferConfig, symbol: str, start_date: str) -> Path:
    return config.data_root / symbol / "1m" / f"{symbol}_1m_{start_date}_to_{config.end_date}.csv"


def _load_market_csv(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"missing_columns:{','.join(missing)}")
    frame = frame[required].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in required[1:]:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.dropna(subset=required).sort_values("timestamp").reset_index(drop=True)


def _quality_for_window(frame: pd.DataFrame, start: pd.Timestamp | None, end: pd.Timestamp | None) -> dict[str, Any]:
    working = frame
    if start is not None:
        working = working.loc[working["timestamp"] >= start]
    if end is not None:
        working = working.loc[working["timestamp"] <= end]
    return _quality(working.reset_index(drop=True))


def _hash_text(payload: Any) -> str:
    return hashlib.sha256(json.dumps(_round_payload(payload), sort_keys=True).encode("utf-8")).hexdigest()


def _research_config(start_capital: float, *, analysis_start: str, analysis_end: str) -> StructuralLabConfig:
    base = StructuralLabConfig.load()
    payload = copy.deepcopy(base.data)
    payload["base_capital"] = start_capital
    payload["data"]["analysis_start_date"] = analysis_start
    payload["data"]["analysis_end_date"] = analysis_end
    payload["engine"]["resume_enabled"] = True
    payload["engine"]["checkpoint_every_bars"] = 2500
    payload["engine"]["write_partial_artifacts"] = False
    return StructuralLabConfig(data=payload, config_path=base.config_path, root_dir=base.root_dir)


def _safe_ratio(numerator: float, denominator: float, default: float = 0.0) -> float:
    return numerator / denominator if denominator else default


def _profit_factor(values: list[float]) -> float:
    wins = sum(value for value in values if value > 0.0)
    losses = abs(sum(value for value in values if value < 0.0))
    return wins / losses if losses else float(wins > 0.0)


def _strip_cost_sim(sim: dict[str, Any]) -> dict[str, Any]:
    output = {key: value for key, value in sim.items() if key not in {"equity_curve", "trade_rows", "worst_trade", "best_trade"}}
    worst = sim.get("worst_trade")
    best = sim.get("best_trade")
    if worst:
        output["worst_trade"] = {
            "trade_id": worst.get("trade_id"),
            "side": worst.get("side"),
            "entry_time": worst.get("entry_time"),
            "net_r": worst.get("net_r"),
            "gross_r": worst.get("gross_r"),
            "net_cost_r": worst.get("net_cost_r"),
        }
    if best:
        output["best_trade"] = {
            "trade_id": best.get("trade_id"),
            "side": best.get("side"),
            "entry_time": best.get("entry_time"),
            "net_r": best.get("net_r"),
            "gross_r": best.get("gross_r"),
            "net_cost_r": best.get("net_cost_r"),
        }
    return output


def _breakdown(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(str(row.get(key) or ""), []).append(row)
    output: list[dict[str, Any]] = []
    for name, bucket in sorted(buckets.items()):
        values = [float(row["r_multiple"]) for row in bucket]
        output.append(
            {
                "bucket": name,
                "trade_count": len(bucket),
                "total_R": sum(values),
                "average_R": sum(values) / len(values) if values else 0.0,
                "median_R": median(values) if values else 0.0,
                "win_rate": _safe_ratio(sum(1 for value in values if value > 0.0), len(values), 0.0),
                "profit_factor": _profit_factor(values),
            }
        )
    return output


def _read_raw_rows(root: Path, filename: str) -> list[dict[str, Any]]:
    path = root / filename
    if not path.exists() or path.stat().st_size == 0:
        return []
    return _read_csv_rows(path)


def _replay_period(
    config: MultiAssetTransferConfig,
    *,
    symbol: str,
    source_csv: Path,
    period_root: Path,
    label: str,
    analysis_start: str,
    analysis_end: str,
) -> dict[str, Any]:
    raw_engine_root = period_root / "raw_engine"
    raw_summary = StructuralBacktestEngine(
        config=_research_config(START_CAPITAL_25K, analysis_start=analysis_start, analysis_end=analysis_end)
    ).run(symbol=symbol, source_csv=str(source_csv), output_dir=str(raw_engine_root))

    normalized = _normalize_trade_rows(
        _read_raw_rows(raw_engine_root, "trades.csv"),
        _read_raw_rows(raw_engine_root, "setup_log.csv"),
        _read_raw_rows(raw_engine_root, "level_log.csv"),
        _read_raw_rows(raw_engine_root, "liquidity_events.csv"),
    )
    prepared = _prepare_rows(normalized) if normalized else []
    rules_path = config.package_root / "output" / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json"
    matched_shorts, disabled_longs, rules_payload = _load_frozen_rules(rules_path)
    selected, removed = _apply_frozen_patch(
        prepared,
        matched_short_archetypes=matched_shorts,
        disabled_long_modes=disabled_longs,
    )

    start_ts = pd.Timestamp(analysis_start)
    end_ts = pd.Timestamp(analysis_end)
    span_days = max(1, int((end_ts - start_ts).total_seconds() / 86400) + 1)
    gross_25k = _simulate_variant(
        name=f"{symbol}_{label}_EUR25K_FROZEN_RULES",
        selected_rows=selected,
        all_rows=prepared,
        start_capital=START_CAPITAL_25K,
        baseline_span_days=span_days,
        cooldown_rows=_read_raw_rows(raw_engine_root, "cooldown_log.csv"),
    )
    gross_20k = _simulate_variant(
        name=f"{symbol}_{label}_EUR20K_COUNTERFACTUAL_FROZEN_RULES",
        selected_rows=selected,
        all_rows=prepared,
        start_capital=START_CAPITAL_20K,
        baseline_span_days=span_days,
        cooldown_rows=_read_raw_rows(raw_engine_root, "cooldown_log.csv"),
    )
    cost_candidate_rows, cost_rejected = _candidate_rows(selected, net_cost_bps=ROUND_TRIP_COST_BPS)
    cost_sim = _simulate_cost_aware(cost_candidate_rows, start_capital=START_CAPITAL_25K)
    cost_20k = _simulate_cost_aware(cost_candidate_rows, start_capital=START_CAPITAL_20K)
    r_values = [float(row["r_multiple"]) for row in selected]
    cost_values = [float(row["net_r"]) for row in cost_candidate_rows]
    result = {
        "symbol": symbol,
        "label": label,
        "analysis_start": analysis_start,
        "analysis_end": analysis_end,
        "starting_capital_eur": START_CAPITAL_25K,
        "raw_engine": {
            "run_state": raw_summary.get("run_state"),
            "trade_count": raw_summary.get("trade_count"),
            "setup_count": raw_summary.get("setup_count"),
            "ending_equity": raw_summary.get("ending_equity"),
            "progress": raw_summary.get("progress"),
            "resumed_from_checkpoint": raw_summary.get("resumed_from_checkpoint"),
        },
        "frozen_rules": {
            "rules_loaded": bool(rules_payload),
            "accepted_trades": len(selected),
            "raw_engine_trade_count": len(prepared),
            "frozen_rule_rejections": len(removed),
            "ending_diagnostic_equity": gross_25k["summary"]["ending_capital"],
            "return_multiple": _safe_ratio(gross_25k["summary"]["ending_capital"], START_CAPITAL_25K, 0.0),
            "net_profit_eur": gross_25k["summary"]["ending_capital"] - START_CAPITAL_25K,
            "total_R": gross_25k["summary"]["total_R"],
            "average_R": gross_25k["summary"]["avg_R"],
            "median_R": gross_25k["summary"]["median_R"],
            "win_rate": gross_25k["summary"]["win_rate"],
            "profit_factor": gross_25k["summary"]["profit_factor"],
            "max_drawdown_pct": gross_25k["summary"]["max_drawdown_pct"],
            "best_trade_R": max(r_values) if r_values else 0.0,
            "worst_trade_R": min(r_values) if r_values else 0.0,
            "long_trade_count": gross_25k["summary"]["long_trade_count"],
            "short_trade_count": gross_25k["summary"]["short_trade_count"],
            "same_window_20k_counterfactual_ending_equity": gross_20k["summary"]["ending_capital"],
            "same_window_25k_to_20k_ending_ratio": _safe_ratio(
                gross_25k["summary"]["ending_capital"],
                max(gross_20k["summary"]["ending_capital"], 1e-9),
                0.0,
            ),
        },
        "cost_aware_candidate": {
            "candidate_name": CANDIDATE_NAME,
            "round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "max_pre_entry_cost_r": MAX_PRE_ENTRY_COST_R,
            "accepted_after_cost_guard": len(cost_candidate_rows),
            "rejected_by_cost_guard": len(cost_rejected),
            "gross_selected_before_cost_guard": len(selected),
            **_strip_cost_sim(cost_sim),
            "same_window_20k_counterfactual_ending_equity": cost_20k["ending_equity"],
            "same_window_25k_to_20k_ending_ratio": _safe_ratio(cost_sim["ending_equity"], max(cost_20k["ending_equity"], 1e-9), 0.0),
            "best_net_R": max(cost_values) if cost_values else 0.0,
            "worst_net_R": min(cost_values) if cost_values else 0.0,
        },
        "gross_side_breakdown": _breakdown(selected, "side"),
        "gross_setup_class_breakdown": _breakdown(selected, "setup_class"),
        "raw_engine_root": str(raw_engine_root),
        **SAFETY_FLAGS,
    }
    _write_json_round(period_root / f"{label}_summary.json", result)
    _write_csv(period_root / "selected_frozen_rule_trades.csv", selected)
    _write_csv(period_root / "cost_aware_candidate_trades.csv", cost_sim.get("trade_rows", []))
    return result


def _load_gap_manifest(config: MultiAssetTransferConfig) -> dict[str, Any]:
    path = config.package_root / "output" / "multi_asset_public_data_quality_manifest_001" / "multi_asset_historical_exchange_gap_manifest.json"
    return _read_json(path, {})


def _gaps_for_symbol(gap_manifest: dict[str, Any], symbol: str) -> dict[str, Any]:
    for item in gap_manifest.get("symbols", []):
        if str(item.get("symbol")) == symbol:
            return item
    return {}


def _asset_paths(config: MultiAssetTransferConfig, symbol: str) -> dict[str, Path]:
    root = config.output_root / "assets" / symbol
    return {
        "root": root,
        "split_manifest": root / "split_manifest.json",
        "court_state": root / "court_state.json",
        "freeze": root / "freeze_signature.json",
        "research_root": root / "research_only_transfer_replay",
        "holdout_root": root / "sealed_holdout_transfer_validation",
        "asset_summary": root / "asset_transfer_summary.json",
    }


def _prepare_asset_split(
    config: MultiAssetTransferConfig,
    *,
    symbol: str,
    source_csv: Path,
    gap_payload: dict[str, Any],
) -> dict[str, Any]:
    paths = _asset_paths(config, symbol)
    paths["root"].mkdir(parents=True, exist_ok=True)
    if paths["split_manifest"].exists():
        return _read_json(paths["split_manifest"], {})
    frame = _load_market_csv(source_csv)
    full_quality = _quality(frame)
    latest = frame["timestamp"].max()
    holdout_start = (latest - pd.DateOffset(months=6)).floor("D")
    research_end = holdout_start - pd.Timedelta(minutes=1)
    research_quality = _quality_for_window(frame, None, research_end)
    holdout_quality = _quality_for_window(frame, holdout_start, latest)
    gap_violations = []
    for gap in gap_payload.get("gaps", []):
        gap_end = pd.Timestamp(gap.get("missing_end"))
        if gap_end >= holdout_start:
            gap_violations.append(gap)
    strategy_hashes = _hash_map(_strategy_files(config.package_root))
    manifest = {
        "symbol": symbol,
        "source_csv": str(source_csv),
        "source_file_hash": _sha256(source_csv),
        "full_quality": full_quality,
        "research_start": full_quality["first_timestamp"],
        "research_end": research_end.isoformat(),
        "holdout_start": holdout_start.isoformat(),
        "holdout_end": latest.isoformat(),
        "research_quality": research_quality,
        "holdout_quality": holdout_quality,
        "documented_historical_gap_count": int(gap_payload.get("total_gaps") or 0),
        "documented_historical_missing_minutes": int(gap_payload.get("total_missing_minutes") or 0),
        "all_documented_gaps_returned_zero_candles": bool(gap_payload.get("all_gaps_returned_zero_candles")),
        "documented_gap_manifest_source": str(
            config.package_root
            / "output"
            / "multi_asset_public_data_quality_manifest_001"
            / "multi_asset_historical_exchange_gap_manifest.json"
        ),
        "holdout_gap_violations": gap_violations,
        "holdout_must_be_gap_free": True,
        "holdout_clean": holdout_quality["gap_count"] == 0
        and holdout_quality["duplicate_count"] == 0
        and holdout_quality["ohlc_sanity_failures"] == 0
        and not gap_violations,
        "historical_research_gaps_allowed": True,
        "historical_research_gaps_reason": "documented Binance no-candle / maintenance intervals",
        "synthetic_candles_inserted": False,
        "forward_fill_inserted": False,
        "back_fill_inserted": False,
        "split_created_at": _now(),
        "git_commit_hash": _git_commit(config.project_root),
        "frozen_engine_signature_before_validation": _signature(strategy_hashes),
        **SAFETY_FLAGS,
    }
    _write_json_round(paths["split_manifest"], manifest)
    _write_json_round(
        paths["court_state"],
        {
            "symbol": symbol,
            "split_created_at": manifest["split_created_at"],
            "research_replay_started_at": None,
            "research_replay_completed_at": None,
            "freeze_written_at": None,
            "holdout_opened_at": None,
            "holdout_open_count": 0,
            "holdout_validation_completed_at": None,
            "holdout_outcomes_inspected_before_freeze": False,
            "holdout_strategy_outputs_generated_before_freeze": False,
        },
    )
    return manifest


def _write_freeze(config: MultiAssetTransferConfig, symbol: str, manifest: dict[str, Any]) -> dict[str, Any]:
    paths = _asset_paths(config, symbol)
    if paths["freeze"].exists():
        return _read_json(paths["freeze"], {})
    strategy_hashes = _hash_map(_strategy_files(config.package_root))
    config_path = config.package_root / "config" / "structural_compounding_settings.json"
    rules_path = config.package_root / "output" / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json"
    freeze = {
        "symbol": symbol,
        "git_commit_hash": _git_commit(config.project_root),
        "strategy_module_hashes": strategy_hashes,
        "frozen_engine_signature": _signature(strategy_hashes),
        "config_hash": _sha256(config_path),
        "frozen_rule_hash": _sha256(rules_path),
        "source_file_hash": manifest["source_file_hash"],
        "split_manifest_hash": _sha256(paths["split_manifest"]),
        "holdout_bounds_hash": _hash_text(
            {
                "holdout_start": manifest["holdout_start"],
                "holdout_end": manifest["holdout_end"],
                "holdout_quality": manifest["holdout_quality"],
            }
        ),
        "eur_25000_diagnostic_capital": True,
        "eur_25000_active_sizing": False,
        "freeze_created_at": _now(),
        "holdout_not_used_before_freeze": True,
        "no_paper_live_order_broker_path": True,
        **SAFETY_FLAGS,
    }
    _write_json_round(paths["freeze"], freeze)
    return freeze


def _current_strategy_signature(config: MultiAssetTransferConfig) -> dict[str, str]:
    return _hash_map(_strategy_files(config.package_root))


def _run_asset(config: MultiAssetTransferConfig, *, symbol: str, source_csv: Path, gap_payload: dict[str, Any]) -> dict[str, Any]:
    paths = _asset_paths(config, symbol)
    if paths["asset_summary"].exists():
        return _read_json(paths["asset_summary"], {})
    manifest = _prepare_asset_split(config, symbol=symbol, source_csv=source_csv, gap_payload=gap_payload)
    if not manifest.get("holdout_clean"):
        summary = {
            "symbol": symbol,
            "final_classification": FAILED,
            "classification_reasons": ["sealed_holdout_not_clean"],
            "split_manifest": manifest,
            **SAFETY_FLAGS,
        }
        _write_json_round(paths["asset_summary"], summary)
        return summary
    state = _read_json(paths["court_state"], {})
    state["research_replay_started_at"] = state.get("research_replay_started_at") or _now()
    _write_json_round(paths["court_state"], state)
    research = _replay_period(
        config,
        symbol=symbol,
        source_csv=source_csv,
        period_root=paths["research_root"],
        label="research_pre_holdout",
        analysis_start=manifest["research_start"],
        analysis_end=manifest["research_end"],
    )
    state["research_replay_completed_at"] = _now()
    _write_json_round(paths["court_state"], state)
    freeze = _write_freeze(config, symbol, manifest)
    state["freeze_written_at"] = freeze["freeze_created_at"]
    _write_json_round(paths["court_state"], state)
    if _current_strategy_signature(config) != freeze["strategy_module_hashes"]:
        raise ValueError(f"{symbol}:strategy_changed_before_holdout")
    state["holdout_opened_at"] = _now()
    state["holdout_open_count"] = int(state.get("holdout_open_count") or 0) + 1
    if state["holdout_open_count"] != 1:
        raise ValueError(f"{symbol}:holdout_opened_more_than_once")
    _write_json_round(paths["court_state"], state)
    holdout = _replay_period(
        config,
        symbol=symbol,
        source_csv=source_csv,
        period_root=paths["holdout_root"],
        label="sealed_holdout",
        analysis_start=manifest["holdout_start"],
        analysis_end=manifest["holdout_end"],
    )
    state["holdout_validation_completed_at"] = _now()
    _write_json_round(paths["court_state"], state)
    anti = {
        "symbol": symbol,
        "holdout_clean_before_validation": bool(manifest["holdout_clean"]),
        "holdout_opened_after_freeze": state["holdout_opened_at"] >= state["freeze_written_at"],
        "holdout_opened_once": state["holdout_open_count"] == 1,
        "strategy_unchanged_between_freeze_and_holdout": _current_strategy_signature(config) == freeze["strategy_module_hashes"],
        "source_file_unchanged": _sha256(source_csv) == freeze["source_file_hash"],
        "historical_research_gaps_exchange_confirmed": bool(manifest["all_documented_gaps_returned_zero_candles"]),
        "no_synthetic_candles_inserted": not bool(manifest["synthetic_candles_inserted"]),
        "holdout_outcomes_not_inspected_before_freeze": not bool(state.get("holdout_outcomes_inspected_before_freeze")),
        "holdout_strategy_outputs_not_generated_before_freeze": not bool(state.get("holdout_strategy_outputs_generated_before_freeze")),
    }
    anti["passed"] = all(anti.values())
    holdout_cost = holdout["cost_aware_candidate"]
    research_cost = research["cost_aware_candidate"]
    holdout_profitable = float(holdout_cost.get("ending_equity") or 0.0) > START_CAPITAL_25K
    holdout_trade_count_ok = int(holdout_cost.get("accepted_trades") or 0) >= 3
    holdout_drawdown_ok = float(holdout_cost.get("max_drawdown") or 1.0) <= 0.35
    transfer_supported = anti["passed"] and holdout_profitable and holdout_trade_count_ok and holdout_drawdown_ok
    if transfer_supported and float(research_cost.get("ending_equity") or 0.0) > START_CAPITAL_25K:
        classification = PASSED
        reasons = ["cost_aware_research_and_sealed_holdout_profitable_under_frozen_transfer_rules"]
    elif anti["passed"] and holdout_profitable:
        classification = WARNING
        reasons = ["sealed_holdout_profitable_but_research_or_trade_count_warning"]
    else:
        classification = FAILED
        reasons = ["sealed_holdout_transfer_not_supported_after_costs"]
    summary = {
        "symbol": symbol,
        "final_classification": classification,
        "classification_reasons": reasons,
        "split_manifest": manifest,
        "freeze_signature": freeze,
        "anti_leakage_audit": anti,
        "research_pre_holdout": research,
        "sealed_holdout": holdout,
        "transfer_supported_after_costs": transfer_supported,
        "paper_validation_ready": False,
        **SAFETY_FLAGS,
    }
    _write_json_round(paths["asset_summary"], summary)
    return summary


def _portfolio_view(asset_summaries: list[dict[str, Any]]) -> dict[str, Any]:
    supported = [item for item in asset_summaries if item.get("transfer_supported_after_costs")]
    holdout_endings = [
        float(item.get("sealed_holdout", {}).get("cost_aware_candidate", {}).get("ending_equity") or 0.0)
        for item in asset_summaries
    ]
    research_endings = [
        float(item.get("research_pre_holdout", {}).get("cost_aware_candidate", {}).get("ending_equity") or 0.0)
        for item in asset_summaries
    ]
    return {
        "asset_count": len(asset_summaries),
        "supported_asset_count": len(supported),
        "supported_symbols": [item["symbol"] for item in supported],
        "failed_or_warning_symbols": [item["symbol"] for item in asset_summaries if not item.get("transfer_supported_after_costs")],
        "average_holdout_ending_equity": sum(holdout_endings) / len(holdout_endings) if holdout_endings else 0.0,
        "median_holdout_ending_equity": median(holdout_endings) if holdout_endings else 0.0,
        "best_holdout_asset": max(
            asset_summaries,
            key=lambda item: float(item.get("sealed_holdout", {}).get("cost_aware_candidate", {}).get("ending_equity") or 0.0),
        )["symbol"]
        if asset_summaries
        else "",
        "worst_holdout_asset": min(
            asset_summaries,
            key=lambda item: float(item.get("sealed_holdout", {}).get("cost_aware_candidate", {}).get("ending_equity") or 0.0),
        )["symbol"]
        if asset_summaries
        else "",
        "average_research_ending_equity": sum(research_endings) / len(research_endings) if research_endings else 0.0,
        "median_research_ending_equity": median(research_endings) if research_endings else 0.0,
    }


def _classification(asset_summaries: list[dict[str, Any]]) -> tuple[str, list[str]]:
    if not asset_summaries:
        return BLOCKED, ["no_asset_summaries"]
    passed = sum(1 for item in asset_summaries if item.get("final_classification") == PASSED)
    warnings = sum(1 for item in asset_summaries if item.get("final_classification") == WARNING)
    if passed >= 4:
        return PASSED, [f"{passed}_assets_validated_after_costs"]
    if passed >= 2 or (passed >= 1 and warnings >= 2):
        return WARNING, [f"{passed}_assets_passed_and_{warnings}_assets_warned"]
    return FAILED, [f"only_{passed}_assets_passed_after_costs"]


def _write_report(config: MultiAssetTransferConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# Multi-Asset Frozen Transfer Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        f"- Assets evaluated: `{len(summary['assets'])}`",
        f"- Supported assets after cost-aware frozen transfer: `{summary['portfolio_view']['supported_asset_count']}`",
        "- Research-only. No paper/live/order/broker path enabled.",
        "- Historical gaps are documented Binance no-candle intervals. No synthetic candles were inserted.",
        "",
        "| Symbol | Classification | Research net €25k ending | Holdout net €25k ending | Holdout trades | Holdout PF | Holdout max DD | Supported |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for asset in summary["assets"]:
        research = asset.get("research_pre_holdout", {}).get("cost_aware_candidate", {})
        holdout = asset.get("sealed_holdout", {}).get("cost_aware_candidate", {})
        lines.append(
            "| {symbol} | `{classification}` | €{research_end:,.2f} | €{holdout_end:,.2f} | {trades} | {pf:.2f} | {dd:.2%} | {supported} |".format(
                symbol=asset["symbol"],
                classification=asset["final_classification"],
                research_end=float(research.get("ending_equity") or 0.0),
                holdout_end=float(holdout.get("ending_equity") or 0.0),
                trades=int(holdout.get("accepted_trades") or 0),
                pf=float(holdout.get("profit_factor") or 0.0),
                dd=float(holdout.get("max_drawdown") or 0.0),
                supported=str(bool(asset.get("transfer_supported_after_costs"))).lower(),
            )
        )
    lines.extend(
        [
            "",
            "## Safety",
            "",
            f"- `paper_validation_ready`: `{summary['paper_validation_ready']}`",
            f"- `paper_allowed`: `{summary['paper_allowed']}`",
            f"- `live_allowed`: `{summary['live_allowed']}`",
            f"- `no_order_path_created`: `{summary['no_order_path_created']}`",
            f"- `no_broker_path_created`: `{summary['no_broker_path_created']}`",
            "- EUR 25,000 remains diagnostic only.",
        ]
    )
    (config.output_root / "multi_asset_frozen_transfer_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: MultiAssetTransferConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    gap_manifest = _load_gap_manifest(config)
    if not gap_manifest:
        summary = {"court_name": COURT_NAME, "final_classification": BLOCKED, "classification_reasons": ["missing_gap_manifest"], **SAFETY_FLAGS}
        _write_json_round(config.output_root / "multi_asset_frozen_transfer_summary.json", summary)
        return summary
    asset_summaries: list[dict[str, Any]] = []
    for symbol, start_date in SYMBOL_SPECS:
        source_csv = _source_path(config, symbol, start_date)
        if not source_csv.exists():
            asset_summaries.append(
                {
                    "symbol": symbol,
                    "final_classification": FAILED,
                    "classification_reasons": [f"missing_source_csv:{source_csv}"],
                    **SAFETY_FLAGS,
                }
            )
            continue
        print(f"[{_now()}] {symbol}: starting sealed transfer court", flush=True)
        asset_summaries.append(_run_asset(config, symbol=symbol, source_csv=source_csv, gap_payload=_gaps_for_symbol(gap_manifest, symbol)))
        print(f"[{_now()}] {symbol}: completed {asset_summaries[-1]['final_classification']}", flush=True)
    final_classification, reasons = _classification(asset_summaries)
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": final_classification,
        "classification_reasons": reasons,
        "source_gap_manifest": str(
            config.package_root / "output" / "multi_asset_public_data_quality_manifest_001" / "multi_asset_historical_exchange_gap_manifest.json"
        ),
        "assets": asset_summaries,
        "portfolio_view": _portfolio_view(asset_summaries),
        "strategy_changes": {
            "entries_changed": False,
            "exits_changed": False,
            "thresholds_tuned": False,
            "asset_specific_rules_added": False,
            "frozen_btc_rules_reused": True,
            "cost_aware_candidate_guard_reused": True,
        },
        "cost_model": {
            "candidate_name": CANDIDATE_NAME,
            "normal_round_trip_cost_bps": ROUND_TRIP_COST_BPS,
            "max_pre_entry_cost_r": MAX_PRE_ENTRY_COST_R,
        },
        **SAFETY_FLAGS,
    }
    _write_json_round(config.output_root / "multi_asset_frozen_transfer_summary.json", summary)
    _write_csv(
        config.output_root / "multi_asset_frozen_transfer_scorecard.csv",
        [
            {
                "symbol": asset["symbol"],
                "classification": asset["final_classification"],
                "research_cost_ending_equity": asset.get("research_pre_holdout", {}).get("cost_aware_candidate", {}).get("ending_equity"),
                "holdout_cost_ending_equity": asset.get("sealed_holdout", {}).get("cost_aware_candidate", {}).get("ending_equity"),
                "holdout_cost_accepted_trades": asset.get("sealed_holdout", {}).get("cost_aware_candidate", {}).get("accepted_trades"),
                "holdout_cost_profit_factor": asset.get("sealed_holdout", {}).get("cost_aware_candidate", {}).get("profit_factor"),
                "holdout_cost_max_drawdown": asset.get("sealed_holdout", {}).get("cost_aware_candidate", {}).get("max_drawdown"),
                "transfer_supported_after_costs": asset.get("transfer_supported_after_costs"),
            }
            for asset in asset_summaries
        ],
    )
    _write_report(config, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the multi-asset frozen transfer court.")
    parser.add_argument("--end-date", default="2026-06-27")
    parser.add_argument("--data-root", default="data_storage")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        MultiAssetTransferConfig(
            project_root=root,
            package_root=package_root(),
            data_root=resolve_project_path(args.data_root),
            output_root=resolve_project_path(args.output_dir),
            end_date=args.end_date,
        )
    )
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
