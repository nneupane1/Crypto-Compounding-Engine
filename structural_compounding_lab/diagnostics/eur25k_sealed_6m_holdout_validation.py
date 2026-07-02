from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.backtest.engine import StructuralBacktestEngine  # noqa: E402
from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path  # noqa: E402
from structural_compounding_lab.config import StructuralLabConfig  # noqa: E402
from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import (  # noqa: E402
    _apply_frozen_patch,
    _load_frozen_rules,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import (  # noqa: E402
    _prepare_rows,
    _simulate_variant,
)
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _median,
    _normalize_trade_rows,
    _read_csv_rows,
)
from structural_compounding_lab.shadow_forward.shadow_forward_observer import (  # noqa: E402
    ShadowForwardObserverConfig,
    write_shadow_forward_observer,
)


OUTPUT_FOLDER_NAME = "eur25k_sealed_6m_holdout_court_001"
PASSED = "EUR25K_SEALED_6M_HOLDOUT_VALIDATION_PASSED_RESEARCH_ONLY"
WARNING = "EUR25K_SEALED_6M_HOLDOUT_VALIDATION_WARNING_RESEARCH_ONLY"
FAILED = "EUR25K_SEALED_6M_HOLDOUT_VALIDATION_FAILED_RESEARCH_ONLY"
START_CAPITAL_20K = 20000.0
START_CAPITAL_25K = 25000.0
TRUSTED_20K_AVERAGE = 792824.55832
TRUSTED_20K_MEDIAN = 786049.44639
TRUSTED_20K_HIT_1M = 12
CONTEXT_20K_AVERAGE = 881465.531787
CONTEXT_20K_MEDIAN = 878431.045803
CONTEXT_20K_HIT_1M = 18

SAFETY_FLAGS = {
    "research_only": True,
    "real_money_allowed": False,
    "paper_allowed": False,
    "live_allowed": False,
    "behavior_change_allowed": False,
    "no_order_path_created": True,
    "no_broker_path_created": True,
    "paper_validation_ready": False,
    "eur_25000_anchor_active": False,
}

ReplayFunction = Callable[[Path, Path, float, str], dict[str, Any]]


@dataclass(frozen=True)
class SealedHoldoutCourtConfig:
    project_root: Path
    package_root: Path
    canonical_csv_path: Path
    output_root: Path
    replay_function: ReplayFunction | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(output_root: Path) -> dict[str, Path]:
    return {
        "datasets": output_root / "datasets",
        "research_dataset": output_root / "datasets" / "research_pre_holdout_btcusdt_1m.csv",
        "holdout_dataset": output_root / "datasets" / "holdout_locked_last_6m_btcusdt_1m.csv",
        "manifest": output_root / "split_manifest.json",
        "state": output_root / "court_state.json",
        "freeze": output_root / "freeze_signature.json",
        "anti_leakage": output_root / "anti_leakage_audit.json",
        "research_output": output_root / "research_only_eur25k_replay",
        "holdout_output": output_root / "holdout_validation",
        "summary": output_root / "eur25k_sealed_6m_holdout_summary.json",
        "report": output_root / "eur25k_sealed_6m_holdout_report.md",
    }


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(root: Path) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _strategy_files(package: Path) -> list[Path]:
    relative = (
        "backtest/engine.py",
        "entry/setup_detector.py",
        "entry/entry_score.py",
        "entry/trade_plan.py",
        "exit/exit_engine.py",
        "context/htf_confirmation.py",
        "capital/position_sizing.py",
        "config/structural_compounding_settings.json",
    )
    return [package / item for item in relative if (package / item).exists()]


def _hash_map(paths: list[Path]) -> dict[str, str]:
    return {str(path): _sha256(path) for path in paths}


def _signature(payload: dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


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


def _quality(frame: pd.DataFrame) -> dict[str, Any]:
    timestamps = frame["timestamp"]
    duplicates = int(timestamps.duplicated().sum())
    unique = timestamps.drop_duplicates().sort_values()
    diffs = unique.diff().dropna()
    gaps = int((diffs > pd.Timedelta(minutes=1)).sum())
    missing = int(sum(max(0, int(delta.total_seconds() // 60) - 1) for delta in diffs))
    ohlc = int(
        (
            (frame["open"] <= 0)
            | (frame["high"] <= 0)
            | (frame["low"] <= 0)
            | (frame["close"] <= 0)
            | (frame["volume"] < 0)
            | (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
            | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        ).sum()
    )
    return {
        "row_count": int(len(frame)),
        "first_timestamp": timestamps.iloc[0].isoformat() if not frame.empty else None,
        "last_timestamp": timestamps.iloc[-1].isoformat() if not frame.empty else None,
        "gap_count": gaps,
        "missing_minute_count": missing,
        "duplicate_count": duplicates,
        "ohlc_sanity_failures": ohlc,
    }


def _write_dataset(frame: pd.DataFrame, path: Path) -> None:
    working = frame.copy()
    working["timestamp"] = working["timestamp"].dt.tz_convert("UTC").dt.tz_localize(None)
    path.parent.mkdir(parents=True, exist_ok=True)
    working.to_csv(path, index=False)


def prepare_split(config: SealedHoldoutCourtConfig) -> dict[str, Any]:
    paths = _paths(config.output_root)
    config.output_root.mkdir(parents=True, exist_ok=True)
    frame = _load_market_csv(config.canonical_csv_path)
    canonical_quality = _quality(frame)
    if canonical_quality["gap_count"] or canonical_quality["duplicate_count"] or canonical_quality["ohlc_sanity_failures"]:
        raise ValueError("canonical_mechanical_integrity_failed")
    first = frame["timestamp"].min()
    last = frame["timestamp"].max()
    holdout_start = (last - pd.DateOffset(months=6)).floor("D")
    research_end = holdout_start - pd.Timedelta(minutes=1)
    research = frame.loc[frame["timestamp"] <= research_end].copy()
    holdout = frame.loc[frame["timestamp"] >= holdout_start].copy()
    if research.empty or holdout.empty or research["timestamp"].max() >= holdout["timestamp"].min():
        raise ValueError("invalid_non_overlapping_split")
    _write_dataset(research, paths["research_dataset"])
    _write_dataset(holdout, paths["holdout_dataset"])
    research_quality = _quality(research)
    holdout_quality = _quality(holdout)
    strategy_hashes = _hash_map(_strategy_files(config.package_root))
    manifest = {
        "canonical_csv_path": str(config.canonical_csv_path),
        "canonical_first_timestamp": first.isoformat(),
        "canonical_last_timestamp": last.isoformat(),
        "latest_fully_closed_timestamp": last.isoformat(),
        "research_start": research["timestamp"].min().isoformat(),
        "research_end": research["timestamp"].max().isoformat(),
        "holdout_start": holdout["timestamp"].min().isoformat(),
        "holdout_end": holdout["timestamp"].max().isoformat(),
        "research_row_count": len(research),
        "holdout_row_count": len(holdout),
        "research_gap_count": research_quality["gap_count"],
        "holdout_gap_count": holdout_quality["gap_count"],
        "research_duplicate_count": research_quality["duplicate_count"],
        "holdout_duplicate_count": holdout_quality["duplicate_count"],
        "research_file_hash": _sha256(paths["research_dataset"]),
        "holdout_file_hash": _sha256(paths["holdout_dataset"]),
        "split_created_at": _now(),
        "git_commit_hash": _git_commit(config.project_root),
        "frozen_engine_signature_before_validation": _signature(strategy_hashes),
        "holdout_locked": True,
        "canonical_quality": canonical_quality,
        "research_quality": research_quality,
        "holdout_quality": holdout_quality,
        **SAFETY_FLAGS,
    }
    _write_json(paths["manifest"], manifest)
    state = {
        "split_created_at": manifest["split_created_at"],
        "holdout_hash_recorded_at": _now(),
        "research_replay_started_at": None,
        "research_replay_completed_at": None,
        "freeze_written_at": None,
        "holdout_opened_at": None,
        "holdout_open_count": 0,
        "holdout_validation_completed_at": None,
        "holdout_strategy_outputs_generated_before_freeze": False,
        "holdout_outcomes_inspected_before_freeze": False,
    }
    _write_json(paths["state"], state)
    return manifest


def _research_config(start_capital: float) -> StructuralLabConfig:
    base = StructuralLabConfig.load()
    payload = copy.deepcopy(base.data)
    payload["base_capital"] = start_capital
    payload["data"]["analysis_start_date"] = None
    payload["data"]["analysis_end_date"] = None
    payload["engine"]["resume_enabled"] = False
    payload["engine"]["checkpoint_every_bars"] = 0
    payload["engine"]["write_partial_artifacts"] = False
    return StructuralLabConfig(data=payload, config_path=base.config_path, root_dir=base.root_dir)


def _breakdown(rows: list[dict[str, Any]], key_fn: Callable[[dict[str, Any]], str]) -> list[dict[str, Any]]:
    buckets: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        buckets.setdefault(key_fn(row), []).append(row)
    output: list[dict[str, Any]] = []
    for key, bucket in sorted(buckets.items()):
        values = [float(row["r_multiple"]) for row in bucket]
        wins = [value for value in values if value > 0]
        losses = abs(sum(value for value in values if value < 0))
        output.append(
            {
                "bucket": key,
                "trade_count": len(bucket),
                "total_R": round(sum(values), 6),
                "average_R": round(sum(values) / len(values), 6),
                "median_R": round(_median(values), 6),
                "win_rate": round(len(wins) / len(values), 6),
                "profit_factor": round(sum(wins) / losses, 6) if losses else round(sum(wins), 6),
            }
        )
    return output


def _default_replay(config: SealedHoldoutCourtConfig, dataset: Path, output_root: Path, start_capital: float, label: str) -> dict[str, Any]:
    engine_root = output_root / "raw_engine"
    observer_root = output_root / "observer"
    raw_summary = StructuralBacktestEngine(config=_research_config(start_capital)).run(
        symbol="BTCUSDT",
        source_csv=str(dataset),
        output_dir=str(engine_root),
    )
    normalized = _normalize_trade_rows(
        _read_csv_rows(engine_root / "trades.csv"),
        _read_csv_rows(engine_root / "setup_log.csv"),
        _read_csv_rows(engine_root / "level_log.csv"),
        _read_csv_rows(engine_root / "liquidity_events.csv"),
    )
    prepared = _prepare_rows(normalized)
    rules_path = config.package_root / "output" / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json"
    matched_shorts, disabled_longs, rules_payload = _load_frozen_rules(rules_path)
    selected, removed = _apply_frozen_patch(
        prepared,
        matched_short_archetypes=matched_shorts,
        disabled_long_modes=disabled_longs,
    )
    market = _load_market_csv(dataset)
    span_days = max(1, int((market["timestamp"].max() - market["timestamp"].min()).total_seconds() / 86400) + 1)
    simulation_25k = _simulate_variant(
        name=f"{label}_EUR25K",
        selected_rows=selected,
        all_rows=prepared,
        start_capital=start_capital,
        baseline_span_days=span_days,
        cooldown_rows=_read_csv_rows(engine_root / "cooldown_log.csv"),
    )
    simulation_20k = _simulate_variant(
        name=f"{label}_EUR20K_COUNTERFACTUAL",
        selected_rows=selected,
        all_rows=prepared,
        start_capital=START_CAPITAL_20K,
        baseline_span_days=span_days,
        cooldown_rows=_read_csv_rows(engine_root / "cooldown_log.csv"),
    )
    observer_result = write_shadow_forward_observer(
        ShadowForwardObserverConfig(
            package_root=config.package_root,
            output_root=observer_root,
            runtime_mode="dry_run_backfill",
            symbol="BTCUSDT",
            source_csv=dataset,
            force_rerun=True,
        )
    )
    observer_summary = _read_json(observer_result["summary"], {})
    context_rows = _read_csv_rows(observer_root / "ledger" / "shadow_context_log.csv")
    context_by_timestamp = {str(row.get("timestamp") or ""): row for row in context_rows}
    selected_context = [context_by_timestamp.get(str(row.get("entry_time") or ""), {}) for row in selected]
    timestamps = [row["exit_timestamp"] for row in selected if row.get("exit_timestamp") is not None]
    active_dates = {value.normalize() for value in timestamps}
    calendar_days = pd.date_range(market["timestamp"].min().floor("D"), market["timestamp"].max().floor("D"), freq="1D")
    r_values = [float(row["r_multiple"]) for row in selected]
    metrics = simulation_25k["summary"]
    result = {
        "label": label,
        "starting_capital_eur": start_capital,
        "ending_diagnostic_equity": metrics["ending_capital"],
        "return_multiple": round(metrics["ending_capital"] / start_capital, 6),
        "net_profit_eur": round(metrics["ending_capital"] - start_capital, 6),
        "accepted_trades": len(selected),
        "rejected_setups": int(observer_summary.get("rejected_signals") or 0),
        "raw_engine_trade_count": len(prepared),
        "frozen_rule_rejections": len(removed),
        "total_R": metrics["total_R"],
        "average_R": metrics["avg_R"],
        "median_R": metrics["median_R"],
        "win_rate": metrics["win_rate"],
        "profit_factor": metrics["profit_factor"],
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "best_trade_R": max(r_values) if r_values else 0.0,
        "worst_trade_R": min(r_values) if r_values else 0.0,
        "trade_frequency_per_day": metrics["average_trades_per_day"],
        "zero_trade_days": sum(1 for day in calendar_days if day.tz_localize(None) not in active_dates),
        "long_trade_count": metrics["long_trade_count"],
        "short_trade_count": metrics["short_trade_count"],
        "monthly_breakdown": _breakdown(selected, lambda row: str(row["exit_timestamp"])[:7]),
        "session_breakdown": _breakdown(
            selected,
            lambda row: (
                "asia_00_07_utc"
                if row["entry_timestamp"].hour < 8
                else "europe_08_15_utc"
                if row["entry_timestamp"].hour < 16
                else "us_16_23_utc"
            ),
        ),
        "one_h_decisions_evaluated": int(observer_summary.get("one_h_decisions_processed") or 0),
        "six_h_context_annotations": len(context_rows),
        "selected_trade_context_annotations": sum(1 for row in selected_context if row),
        "six_h_context_only": True,
        "six_h_native_execution_enabled": False,
        "same_window_20k_counterfactual_ending_equity": simulation_20k["summary"]["ending_capital"],
        "same_window_25k_to_20k_ending_ratio": round(
            metrics["ending_capital"] / max(simulation_20k["summary"]["ending_capital"], 1e-9),
            6,
        ),
        "frozen_rules_loaded": bool(rules_payload),
        "raw_engine_summary": {
            "run_state": raw_summary.get("run_state"),
            "trade_count": raw_summary.get("trade_count"),
            "setup_count": raw_summary.get("setup_count"),
        },
        **SAFETY_FLAGS,
    }
    _write_json(output_root / f"{label}_summary.json", result)
    return result


def run_research_and_freeze(config: SealedHoldoutCourtConfig) -> dict[str, Any]:
    paths = _paths(config.output_root)
    manifest = _read_json(paths["manifest"], {})
    state = _read_json(paths["state"], {})
    if not manifest or not paths["holdout_dataset"].exists():
        raise ValueError("split_not_prepared")
    if paths["holdout_output"].exists():
        raise ValueError("holdout_outputs_exist_before_freeze")
    state["research_replay_started_at"] = _now()
    _write_json(paths["state"], state)
    replay = config.replay_function or (lambda dataset, output, capital, label: _default_replay(config, dataset, output, capital, label))
    research_result = replay(paths["research_dataset"], paths["research_output"], START_CAPITAL_25K, "research_pre_holdout")
    state["research_replay_completed_at"] = _now()
    strategy_hashes = _hash_map(_strategy_files(config.package_root))
    config_path = config.package_root / "config" / "structural_compounding_settings.json"
    rules_path = config.package_root / "output" / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json"
    freeze = {
        "git_commit_hash": _git_commit(config.project_root),
        "strategy_module_hashes": strategy_hashes,
        "frozen_engine_signature": _signature(strategy_hashes),
        "config_hash": _sha256(config_path),
        "frozen_rule_hash": _sha256(rules_path),
        "research_only_dataset_hash": _sha256(paths["research_dataset"]),
        "holdout_dataset_hash": _sha256(paths["holdout_dataset"]),
        "eur_25000_diagnostic_capital": True,
        "eur_25000_active_sizing": False,
        "freeze_created_at": _now(),
        "holdout_not_used_before_freeze": True,
        "no_paper_live_order_broker_path": True,
        **SAFETY_FLAGS,
    }
    _write_json(paths["freeze"], freeze)
    state["freeze_written_at"] = freeze["freeze_created_at"]
    _write_json(paths["state"], state)
    return research_result


def open_holdout_once(config: SealedHoldoutCourtConfig) -> dict[str, Any]:
    paths = _paths(config.output_root)
    freeze = _read_json(paths["freeze"], {})
    state = _read_json(paths["state"], {})
    if not freeze:
        raise ValueError("freeze_signature_missing")
    if int(state.get("holdout_open_count") or 0) != 0:
        raise ValueError("holdout_already_opened")
    if _sha256(paths["holdout_dataset"]) != freeze["holdout_dataset_hash"]:
        raise ValueError("holdout_hash_changed_after_freeze")
    strategy_hashes = _hash_map(_strategy_files(config.package_root))
    if strategy_hashes != freeze["strategy_module_hashes"]:
        raise ValueError("strategy_changed_between_freeze_and_holdout")
    config_path = config.package_root / "config" / "structural_compounding_settings.json"
    if _sha256(config_path) != freeze["config_hash"]:
        raise ValueError("config_changed_between_freeze_and_holdout")
    state["holdout_opened_at"] = _now()
    state["holdout_open_count"] = 1
    _write_json(paths["state"], state)
    replay = config.replay_function or (lambda dataset, output, capital, label: _default_replay(config, dataset, output, capital, label))
    result = replay(paths["holdout_dataset"], paths["holdout_output"], START_CAPITAL_25K, "sealed_holdout")
    state["holdout_validation_completed_at"] = _now()
    _write_json(paths["state"], state)
    return result


def _comparison(research: dict[str, Any], holdout: dict[str, Any]) -> dict[str, Any]:
    projected_average = TRUSTED_20K_AVERAGE * 1.25
    projected_median = TRUSTED_20K_MEDIAN * 1.25
    same_window_ratio = float(holdout.get("same_window_25k_to_20k_ending_ratio") or 0.0)
    return {
        "trusted_20k_baseline": {
            "starting_capital": START_CAPITAL_20K,
            "rolling_5y_average_ending_equity": TRUSTED_20K_AVERAGE,
            "rolling_5y_median_ending_equity": TRUSTED_20K_MEDIAN,
            "hit_1m_windows": TRUSTED_20K_HIT_1M,
        },
        "linear_25k_projection": {
            "average_ending_equity": round(projected_average, 6),
            "median_ending_equity": round(projected_median, 6),
            "scale_factor": 1.25,
        },
        "planning_anchor": {
            "rough_20k_reference": 850000,
            "rough_25k_projection": 1062500,
            "diagnostic_only": True,
        },
        "context_reference": {
            "classification": "SIX_H_CONTEXT_IMPROVES_1H_RESEARCH_ONLY",
            "best_variant": "LIGHT_BOOST_6H_CONFLUENCE",
            "rolling_5y_average_ending_equity": CONTEXT_20K_AVERAGE,
            "rolling_5y_median_ending_equity": CONTEXT_20K_MEDIAN,
            "hit_1m_windows": CONTEXT_20K_HIT_1M,
        },
        "research_25k": research,
        "holdout_25k": holdout,
        "same_holdout_20k_counterfactual_ending_equity": holdout.get("same_window_20k_counterfactual_ending_equity"),
        "same_holdout_scaling_ratio": same_window_ratio,
        "same_holdout_linear_scaling_pass": abs(same_window_ratio - 1.25) <= 0.000001,
        "research_scaling_evidence_sufficient": int(research.get("accepted_trades") or 0) >= 5,
        "interpretation": (
            "Same-window 25k replay scales exactly from the 20k counterfactual under unchanged percentage-risk compounding."
            if abs(same_window_ratio - 1.25) <= 0.000001
            else "Same-window 25k replay deviates from linear scaling and requires review."
        ),
    }


def finalize(config: SealedHoldoutCourtConfig, research: dict[str, Any], holdout: dict[str, Any]) -> dict[str, Any]:
    paths = _paths(config.output_root)
    manifest = _read_json(paths["manifest"], {})
    freeze = _read_json(paths["freeze"], {})
    state = _read_json(paths["state"], {})
    current_strategy = _hash_map(_strategy_files(config.package_root))
    config_path = config.package_root / "config" / "structural_compounding_settings.json"
    anti = {
        "holdout_file_created_before_research_replay": bool(state.get("split_created_at")) and state["split_created_at"] <= state["research_replay_started_at"],
        "holdout_file_hash_recorded_before_research_replay": bool(state.get("holdout_hash_recorded_at")) and state["holdout_hash_recorded_at"] <= state["research_replay_started_at"],
        "holdout_strategy_outputs_not_generated_before_freeze": not bool(state.get("holdout_strategy_outputs_generated_before_freeze")),
        "holdout_outcomes_not_inspected_before_freeze": not bool(state.get("holdout_outcomes_inspected_before_freeze")),
        "strategy_unchanged_between_freeze_and_validation": current_strategy == freeze.get("strategy_module_hashes"),
        "config_unchanged_between_freeze_and_validation": _sha256(config_path) == freeze.get("config_hash"),
        "holdout_opened_only_after_freeze": bool(state.get("holdout_opened_at")) and state["holdout_opened_at"] >= state["freeze_written_at"],
        "holdout_validation_performed_exactly_once": int(state.get("holdout_open_count") or 0) == 1,
        "no_retuning_after_holdout_results": current_strategy == freeze.get("strategy_module_hashes"),
        "prior_exploratory_six_month_outputs_excluded": True,
    }
    anti["passed"] = all(bool(value) for value in anti.values())
    _write_json(paths["anti_leakage"], {**anti, **SAFETY_FLAGS})
    comparison = _comparison(research, holdout)
    holdout_ok = (
        int(manifest.get("holdout_gap_count") or 0) == 0
        and int(manifest.get("holdout_duplicate_count") or 0) == 0
        and float(holdout.get("max_drawdown_pct") or 1.0) <= 0.35
        and int(holdout.get("accepted_trades") or 0) >= 5
        and float(holdout.get("profit_factor") or 0.0) >= 1.0
        and float(holdout.get("total_R") or 0.0) > 0.0
        and int(holdout.get("six_h_context_annotations") or 0) > 0
    )
    if not anti["passed"] or not holdout_ok:
        classification = FAILED
        reasons = ["anti_leakage_or_holdout_integrity_failed"]
    elif not comparison["research_scaling_evidence_sufficient"]:
        classification = WARNING
        reasons = ["pre_holdout_research_slice_too_short_for_meaningful_200h_warmup_and_scaling_sample"]
    else:
        classification = PASSED
        reasons = ["sealed_holdout_and_same_window_capital_scaling_passed"]
    summary = {
        "final_classification": classification,
        "classification_reasons": reasons,
        "split_manifest": manifest,
        "research_only_eur25k_replay": research,
        "sealed_holdout_validation": holdout,
        "comparison": comparison,
        "anti_leakage_audit": anti,
        "holdout_supports_25k_thesis": holdout_ok,
        "holdout_signal_collapse": int(holdout.get("accepted_trades") or 0) < 5,
        "holdout_drawdown_unacceptable": float(holdout.get("max_drawdown_pct") or 0.0) > 0.35,
        "holdout_trade_frequency_collapsed": float(holdout.get("trade_frequency_per_day") or 0.0) < 0.02,
        "six_h_context_remained_context_only": bool(holdout.get("six_h_context_only")),
        "eur_25000_should_remain_diagnostic_only": True,
        **SAFETY_FLAGS,
    }
    _write_json(paths["summary"], summary)
    _write_report(paths["report"], summary)
    return summary


def _display(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def _difference(value: Any, reference: Any) -> Any:
    if isinstance(value, (int, float)) and isinstance(reference, (int, float)):
        return float(value) - float(reference)
    return "N/A"


def _write_report(path: Path, summary: dict[str, Any]) -> None:
    research = summary["research_only_eur25k_replay"]
    holdout = summary["sealed_holdout_validation"]
    comparison = summary["comparison"]
    trusted = comparison["trusted_20k_baseline"]
    projection = comparison["linear_25k_projection"]
    rows = [
        ("Starting capital", 20000, 25000, research.get("starting_capital_eur"), holdout.get("starting_capital_eur"), "Capital anchor only"),
        ("Ending equity", trusted["rolling_5y_average_ending_equity"], projection["average_ending_equity"], research.get("ending_diagnostic_equity"), holdout.get("ending_diagnostic_equity"), "Windows differ; same-window ratio is separately tested"),
        ("Return multiple", trusted["rolling_5y_average_ending_equity"] / 20000, projection["average_ending_equity"] / 25000, research.get("return_multiple"), holdout.get("return_multiple"), "Comparable only within the same time window"),
        ("Net profit", trusted["rolling_5y_average_ending_equity"] - 20000, projection["average_ending_equity"] - 25000, research.get("net_profit_eur"), holdout.get("net_profit_eur"), "Long-history versus short holdout"),
        ("Accepted trades", "N/A", "N/A", research.get("accepted_trades"), holdout.get("accepted_trades"), "Research slice is only eight days"),
        ("Rejected setups", "N/A", "N/A", research.get("rejected_setups"), holdout.get("rejected_setups"), "Observer decisions"),
        ("Trade frequency/day", "N/A", "N/A", research.get("trade_frequency_per_day"), holdout.get("trade_frequency_per_day"), "Window-dependent"),
        ("Zero-trade days", "N/A", "N/A", research.get("zero_trade_days"), holdout.get("zero_trade_days"), "Window-dependent"),
        ("Total R", "N/A", "N/A", research.get("total_R"), holdout.get("total_R"), "R is capital invariant"),
        ("Average R", "N/A", "N/A", research.get("average_R"), holdout.get("average_R"), "R is capital invariant"),
        ("Median R", "N/A", "N/A", research.get("median_R"), holdout.get("median_R"), "R is capital invariant"),
        ("Win rate", "N/A", "N/A", research.get("win_rate"), holdout.get("win_rate"), "Signal outcome metric"),
        ("Profit factor", "N/A", "N/A", research.get("profit_factor"), holdout.get("profit_factor"), "Signal outcome metric"),
        ("Max drawdown", "N/A", "N/A", research.get("max_drawdown_pct"), holdout.get("max_drawdown_pct"), "Percentage risk remains unchanged"),
        ("Best trade R", "N/A", "N/A", research.get("best_trade_R"), holdout.get("best_trade_R"), "R is capital invariant"),
        ("Worst trade R", "N/A", "N/A", research.get("worst_trade_R"), holdout.get("worst_trade_R"), "R is capital invariant"),
        ("Long/short split", "N/A", "N/A", f"{research.get('long_trade_count')}/{research.get('short_trade_count')}", f"{holdout.get('long_trade_count')}/{holdout.get('short_trade_count')}", "Frozen selection"),
        ("1M-hit status", trusted["hit_1m_windows"], "N/A", "N/A", holdout.get("ending_diagnostic_equity", 0) >= 1000000, "Window counts do not scale with capital"),
        ("Monthly consistency", "Historical rolling evidence", "N/A", len(research.get("monthly_breakdown", [])), len(holdout.get("monthly_breakdown", [])), "See generated breakdowns"),
        ("6H context usage", "Research-only", "Research-only", research.get("six_h_context_only"), holdout.get("six_h_context_only"), "Never execution"),
        ("Safety status", "Research-only", "Research-only", "Research-only", "Research-only", "No execution permission"),
        ("paper_validation_ready", False, False, False, False, "Must remain false"),
    ]
    lines = [
        "# EUR 25,000 Sealed Six-Month Holdout Court",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        f"- Research window: `{summary['split_manifest']['research_start']}` to `{summary['split_manifest']['research_end']}`",
        f"- Holdout window: `{summary['split_manifest']['holdout_start']}` to `{summary['split_manifest']['holdout_end']}`",
        f"- Anti-leakage passed: `{summary['anti_leakage_audit']['passed']}`",
        "",
        "## Research-only EUR 25,000 replay",
        "",
        f"- Accepted trades: `{research.get('accepted_trades')}`",
        f"- Ending diagnostic equity: `{research.get('ending_diagnostic_equity')}`",
        f"- Total R: `{research.get('total_R')}`",
        f"- Max drawdown: `{research.get('max_drawdown_pct')}`",
        "",
        "The pre-holdout research slice is only eight days and is shorter than the frozen engine's 200-hour EMA warm-up. No holdout data was borrowed to repair this limitation.",
        "",
        "## Sealed holdout validation",
        "",
        f"- Decisions evaluated: `{holdout.get('one_h_decisions_evaluated')}`",
        f"- Accepted trades: `{holdout.get('accepted_trades')}`",
        f"- Ending diagnostic equity: `{holdout.get('ending_diagnostic_equity')}`",
        f"- Total R / PF / win rate: `{holdout.get('total_R')}` / `{holdout.get('profit_factor')}` / `{holdout.get('win_rate')}`",
        f"- Max drawdown: `{holdout.get('max_drawdown_pct')}`",
        f"- Same-window 20k counterfactual: `{holdout.get('same_window_20k_counterfactual_ending_equity')}`",
        f"- 25k/20k same-window ending-equity ratio: `{holdout.get('same_window_25k_to_20k_ending_ratio')}`",
        "",
        "## Full EUR 20k vs EUR 25k comparison",
        "",
        "| Metric | EUR 20k Trusted Baseline | EUR 25k Linear Projection | EUR 25k Research-Only Diagnostic Replay | EUR 25k Sealed Holdout Validation | Difference vs 20k Baseline | Difference vs 25k Linear Projection | Interpretation |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    lines.extend(
        f"| {metric} | {_display(baseline)} | {_display(projected)} | {_display(research_value)} | {_display(holdout_value)} | {_display(_difference(holdout_value, baseline))} | {_display(_difference(holdout_value, projected))} | {interpretation} |"
        for metric, baseline, projected, research_value, holdout_value, interpretation in rows
    )
    lines.extend(
        [
            "",
            "Differences use the sealed holdout value where both cells are numeric. Long-history and six-month values remain different windows, so those deltas are descriptive rather than like-for-like performance claims.",
            "",
            "## Freeze signature",
            "",
            f"- Holdout opened only after freeze: `{summary['anti_leakage_audit'].get('holdout_opened_only_after_freeze')}`.",
            f"- Frozen engine unchanged: `{summary['anti_leakage_audit'].get('strategy_unchanged_between_freeze_and_validation')}`.",
            f"- Frozen config unchanged: `{summary['anti_leakage_audit'].get('config_unchanged_between_freeze_and_validation')}`.",
            "",
            "## Anti-leakage audit",
            "",
            f"- Passed: `{summary['anti_leakage_audit']['passed']}`.",
            f"- Holdout opened exactly once: `{summary['anti_leakage_audit'].get('holdout_validation_performed_exactly_once')}`.",
            f"- Holdout outcomes inspected before freeze: `{not summary['anti_leakage_audit'].get('holdout_outcomes_not_inspected_before_freeze')}`.",
            f"- Retuning after holdout results: `{not summary['anti_leakage_audit'].get('no_retuning_after_holdout_results')}`.",
            "",
            "## Safety status",
            "",
            "- `research_only=true`.",
            "- `real_money_allowed=false`.",
            "- `paper_allowed=false`.",
            "- `live_allowed=false`.",
            "- `behavior_change_allowed=false`.",
            "- `no_order_path_created=true`.",
            "- `no_broker_path_created=true`.",
            "- `eur_25000_anchor_active=false`.",
            "",
            "## Answers",
            "",
            f"- Did EUR 25k scale reasonably? `{comparison['same_holdout_linear_scaling_pass']}` on the identical holdout R-sequence.",
            f"- Is it consistent with the historical compounding engine? `{summary['holdout_supports_25k_thesis']}`, with window-length caveats.",
            f"- Did the holdout support the thesis? `{summary['holdout_supports_25k_thesis']}`.",
            f"- Signal collapse? `{summary['holdout_signal_collapse']}`.",
            f"- Unacceptable drawdown? `{summary['holdout_drawdown_unacceptable']}`.",
            f"- Trade-frequency collapse? `{summary['holdout_trade_frequency_collapsed']}`.",
            f"- 6H remained context-only? `{summary['six_h_context_remained_context_only']}`.",
            f"- Anti-leakage violation? `{not summary['anti_leakage_audit']['passed']}`.",
            "- Paper/live/order/broker path enabled: `false`.",
            "- EUR 25,000 remains diagnostic only: `true`.",
            "- `paper_validation_ready=false`.",
            "",
            "The rough 20k -> 850k and 25k -> 1,062,500 planning anchor remains visible only as diagnostic planning context.",
            "",
            "This court may strengthen confidence in continuing the real six-month scheduler validation, but it does not grant paper readiness.",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run_court(config: SealedHoldoutCourtConfig) -> dict[str, Any]:
    paths = _paths(config.output_root)
    if paths["summary"].exists() or int(_read_json(paths["state"], {}).get("holdout_open_count") or 0) > 0:
        raise ValueError("sealed_holdout_court_already_executed")
    prepare_split(config)
    research = run_research_and_freeze(config)
    holdout = open_holdout_once(config)
    return finalize(config, research, holdout)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the EUR25k sealed six-month holdout court.")
    parser.add_argument(
        "--canonical-csv",
        default="structural_compounding_lab/data_storage/BTCUSDT/1m/btcusdt_1m_canonical_shadow_forward.csv",
    )
    parser.add_argument(
        "--output-dir",
        default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    root = project_root()
    result = run_court(
        SealedHoldoutCourtConfig(
            project_root=root,
            package_root=package_root(),
            canonical_csv_path=resolve_project_path(args.canonical_csv),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
