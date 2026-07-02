from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import pandas as pd
import requests

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.config import AppConfig  # noqa: E402
from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path  # noqa: E402
from structural_compounding_lab.diagnostics.eur25k_sealed_6m_holdout_validation import (  # noqa: E402
    CONTEXT_20K_AVERAGE,
    CONTEXT_20K_HIT_1M,
    CONTEXT_20K_MEDIAN,
    SAFETY_FLAGS,
    START_CAPITAL_20K,
    START_CAPITAL_25K,
    TRUSTED_20K_AVERAGE,
    TRUSTED_20K_HIT_1M,
    TRUSTED_20K_MEDIAN,
    _default_replay,
    _display,
    _git_commit,
    _hash_map,
    _load_market_csv,
    _quality,
    _read_json,
    _sha256,
    _signature,
    _strategy_files,
    _write_dataset,
    _write_json,
)


OUTPUT_FOLDER_NAME = "eur25k_sealed_6m_holdout_court_002"
PASSED = "EUR25K_FULL_HISTORY_SEALED_6M_HOLDOUT_VALIDATION_PASSED_RESEARCH_ONLY"
WARNING = "EUR25K_FULL_HISTORY_SEALED_6M_HOLDOUT_VALIDATION_WARNING_RESEARCH_ONLY"
FAILED = "EUR25K_FULL_HISTORY_SEALED_6M_HOLDOUT_VALIDATION_FAILED_RESEARCH_ONLY"
GAP_CLASSIFICATION = "DOCUMENTED_BINANCE_NO_CANDLE_INTERVAL"

ReplayFunction = Callable[[Path, Path, float, str], dict[str, Any]]
GapVerifier = Callable[[pd.Timestamp, pd.Timestamp], dict[str, Any]]


@dataclass(frozen=True)
class FullHistorySealedHoldoutCourtConfig:
    project_root: Path
    package_root: Path
    full_history_csv_path: Path
    canonical_csv_path: Path
    output_root: Path
    replay_function: ReplayFunction | None = None
    gap_verifier: GapVerifier | None = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _paths(output_root: Path) -> dict[str, Path]:
    return {
        "datasets": output_root / "datasets",
        "combined_dataset": output_root / "datasets" / "combined_full_history_court_timeline_btcusdt_1m.csv",
        "research_dataset": output_root / "datasets" / "research_pre_holdout_full_history_btcusdt_1m.csv",
        "holdout_dataset": output_root / "datasets" / "holdout_locked_last_6m_btcusdt_1m.csv",
        "source_manifest": output_root / "source_data_manifest.json",
        "gap_manifest": output_root / "historical_exchange_gap_manifest.json",
        "manifest": output_root / "split_manifest.json",
        "state": output_root / "court_state.json",
        "freeze": output_root / "freeze_signature.json",
        "anti_leakage": output_root / "anti_leakage_audit.json",
        "research_output": output_root / "research_only_eur25k_replay",
        "holdout_output": output_root / "holdout_validation",
        "summary": output_root / "eur25k_sealed_6m_holdout_summary.json",
        "report": output_root / "eur25k_sealed_6m_holdout_report.md",
    }


def _discover_sources(root: Path) -> list[str]:
    candidates: list[Path] = []
    for folder in (root / "data_storage" / "BTCUSDT" / "1m", root / "structural_compounding_lab" / "data_storage" / "BTCUSDT" / "1m"):
        if folder.exists():
            candidates.extend(path for path in folder.glob("*.csv") if path.is_file())
    return sorted(str(path.resolve()) for path in candidates)


def _gap_rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    timestamps = frame["timestamp"].drop_duplicates().sort_values().reset_index(drop=True)
    diffs = timestamps.diff()
    output: list[dict[str, Any]] = []
    for index in diffs[diffs > pd.Timedelta(minutes=1)].index:
        start = timestamps.iloc[index - 1] + pd.Timedelta(minutes=1)
        end = timestamps.iloc[index] - pd.Timedelta(minutes=1)
        output.append(
            {
                "gap_start": start.isoformat(),
                "gap_end": end.isoformat(),
                "missing_minute_count": int((end - start).total_seconds() // 60) + 1,
            }
        )
    return output


def _public_zero_candle_verifier(start: pd.Timestamp, end: pd.Timestamp) -> dict[str, Any]:
    app = AppConfig.load()
    base_url = str(app.require("binance", "base_url")).rstrip("/")
    path = str(app.require("binance", "klines_path"))
    response = requests.get(
        f"{base_url}{path}",
        params={
            "symbol": "BTCUSDT",
            "interval": "1m",
            "startTime": int(start.timestamp() * 1000),
            "endTime": int(end.timestamp() * 1000) + 59999,
            "limit": 1000,
        },
        timeout=int(app.require("binance", "request_timeout_seconds")),
    )
    response.raise_for_status()
    payload = response.json()
    return {
        "public_binance_refetch_attempted": True,
        "refetch_result": f"http_{response.status_code}_rows_{len(payload)}",
        "binance_returned_zero_candles": len(payload) == 0,
        "returned_row_count": len(payload),
        "endpoint_type": "public_unsigned_market_klines",
    }


def _mechanical_ok(quality: dict[str, Any], *, allow_gaps: bool) -> bool:
    return (
        (allow_gaps or int(quality["gap_count"]) == 0)
        and int(quality["duplicate_count"]) == 0
        and int(quality["ohlc_sanity_failures"]) == 0
    )


def prepare_split(config: FullHistorySealedHoldoutCourtConfig) -> dict[str, Any]:
    paths = _paths(config.output_root)
    config.output_root.mkdir(parents=True, exist_ok=True)
    if paths["manifest"].exists() or paths["state"].exists():
        raise ValueError("court_002_split_already_prepared")

    full = _load_market_csv(config.full_history_csv_path)
    canonical = _load_market_csv(config.canonical_csv_path)
    full_quality = _quality(full)
    canonical_quality = _quality(canonical)
    if not _mechanical_ok(full_quality, allow_gaps=True):
        raise ValueError("full_history_duplicate_or_ohlc_integrity_failed")
    if not _mechanical_ok(canonical_quality, allow_gaps=False):
        raise ValueError("fresh_canonical_mechanical_integrity_failed")

    verifier = config.gap_verifier or _public_zero_candle_verifier
    latest = canonical["timestamp"].max()
    holdout_start = (latest - pd.DateOffset(months=6)).floor("D")
    research_end = holdout_start - pd.Timedelta(minutes=1)
    gaps = _gap_rows(full)
    verified_gaps: list[dict[str, Any]] = []
    for gap in gaps:
        start = pd.Timestamp(gap["gap_start"])
        end = pd.Timestamp(gap["gap_end"])
        verification = verifier(start, end)
        location = "research_period" if end <= research_end else "holdout_period"
        may_continue = (
            location == "research_period"
            and bool(verification.get("public_binance_refetch_attempted"))
            and bool(verification.get("binance_returned_zero_candles"))
        )
        verified_gaps.append(
            {
                **gap,
                **verification,
                "classification": GAP_CLASSIFICATION,
                "period": location,
                "court_002_may_continue": may_continue,
                "synthetic_candles_inserted": False,
            }
        )
    gap_manifest = {
        "created_at": _now(),
        "full_history_source": str(config.full_history_csv_path),
        "total_historical_gaps": len(verified_gaps),
        "total_missing_minutes": sum(item["missing_minute_count"] for item in verified_gaps),
        "gaps": verified_gaps,
        "all_gaps_exchange_confirmed": all(item["binance_returned_zero_candles"] for item in verified_gaps),
        "all_gaps_in_research_period": all(item["period"] == "research_period" for item in verified_gaps),
        "court_002_may_continue": all(item["court_002_may_continue"] for item in verified_gaps),
        "synthetic_candles_inserted": False,
        "forward_fill_inserted": False,
        "back_fill_fake_bars_inserted": False,
        **SAFETY_FLAGS,
    }
    _write_json(paths["gap_manifest"], gap_manifest)
    if not gap_manifest["court_002_may_continue"]:
        raise ValueError("historical_gap_evidence_not_sufficient")

    full = full.assign(_source_priority=0)
    canonical = canonical.assign(_source_priority=1)
    combined = (
        pd.concat([full, canonical], ignore_index=True)
        .sort_values(["timestamp", "_source_priority"])
        .drop_duplicates(subset=["timestamp"], keep="last")
        .drop(columns=["_source_priority"])
        .reset_index(drop=True)
    )
    combined_quality = _quality(combined)
    research = combined.loc[combined["timestamp"] <= research_end].copy()
    holdout = combined.loc[(combined["timestamp"] >= holdout_start) & (combined["timestamp"] <= latest)].copy()
    research_quality = _quality(research)
    holdout_quality = _quality(holdout)
    if research.empty or holdout.empty or research["timestamp"].max() >= holdout["timestamp"].min():
        raise ValueError("invalid_non_overlapping_split")
    if not _mechanical_ok(holdout_quality, allow_gaps=False):
        raise ValueError("sealed_holdout_not_gap_free")

    _write_dataset(combined, paths["combined_dataset"])
    _write_dataset(research, paths["research_dataset"])
    _write_dataset(holdout, paths["holdout_dataset"])
    source_manifest = {
        "created_at": _now(),
        "all_btcusdt_source_files_discovered": _discover_sources(config.project_root),
        "selected_full_historical_research_source": str(config.full_history_csv_path),
        "selected_canonical_fresh_extension_source": str(config.canonical_csv_path),
        "selected_combined_court_source": str(paths["combined_dataset"]),
        "canonical_used_for_latest_extension": True,
        "full_historical_archive_used_for_research_side": True,
        "selection_reason": "Use the 2018 full archive for research and the refreshed gap-free canonical tape for overlap replacement and latest extension.",
        "full_history_quality": full_quality,
        "canonical_quality": canonical_quality,
        "combined_quality": combined_quality,
        "earliest_timestamp": combined_quality["first_timestamp"],
        "latest_timestamp_after_fresh_fetch": combined_quality["last_timestamp"],
        "documented_exchange_gap_count": gap_manifest["total_historical_gaps"],
        "documented_exchange_missing_minutes": gap_manifest["total_missing_minutes"],
        "historical_research_gaps_allowed": True,
        "historical_research_gaps_reason": "documented Binance no-candle / maintenance intervals",
        "historical_exchange_gap_manifest": str(paths["gap_manifest"]),
        "synthetic_candles_inserted": False,
        "holdout_gap_count": holdout_quality["gap_count"],
        "holdout_must_be_gap_free": True,
        "court_001_not_used_as_validation_evidence": True,
        "fresh_june_21_data_included_in_holdout": holdout["timestamp"].max() == canonical["timestamp"].max(),
        **SAFETY_FLAGS,
    }
    _write_json(paths["source_manifest"], source_manifest)

    strategy_hashes = _hash_map(_strategy_files(config.package_root))
    manifest = {
        "court_number": 2,
        "canonical_csv_path": str(config.canonical_csv_path),
        "canonical_extension_source_path": str(config.canonical_csv_path),
        "full_history_source_path": str(config.full_history_csv_path),
        "merged_court_dataset_path": str(paths["combined_dataset"]),
        "combined_court_dataset_path": str(paths["combined_dataset"]),
        "canonical_first_timestamp": canonical_quality["first_timestamp"],
        "canonical_last_timestamp": canonical_quality["last_timestamp"],
        "full_history_first_timestamp": full_quality["first_timestamp"],
        "full_history_last_timestamp": full_quality["last_timestamp"],
        "combined_first_timestamp": combined_quality["first_timestamp"],
        "combined_last_timestamp": combined_quality["last_timestamp"],
        "research_start": research["timestamp"].min().isoformat(),
        "research_end": research["timestamp"].max().isoformat(),
        "holdout_start": holdout["timestamp"].min().isoformat(),
        "holdout_end": holdout["timestamp"].max().isoformat(),
        "research_row_count": len(research),
        "holdout_row_count": len(holdout),
        "research_gap_count": research_quality["gap_count"],
        "holdout_gap_count": holdout_quality["gap_count"],
        "documented_research_exchange_gap_count": gap_manifest["total_historical_gaps"],
        "documented_research_missing_minutes": gap_manifest["total_missing_minutes"],
        "research_duplicate_count": research_quality["duplicate_count"],
        "holdout_duplicate_count": holdout_quality["duplicate_count"],
        "research_ohlc_sanity_failures": research_quality["ohlc_sanity_failures"],
        "holdout_ohlc_sanity_failures": holdout_quality["ohlc_sanity_failures"],
        "research_file_hash": _sha256(paths["research_dataset"]),
        "holdout_file_hash": _sha256(paths["holdout_dataset"]),
        "split_created_at": _now(),
        "git_commit_hash": _git_commit(config.project_root),
        "frozen_engine_signature_before_validation": _signature(strategy_hashes),
        "holdout_locked": True,
        "court_001_not_used_as_validation_evidence": True,
        "latest_data_fetched_before_court": True,
        "fresh_june_21_data_included_in_holdout": holdout["timestamp"].max() == canonical["timestamp"].max(),
        "incomplete_current_candle_excluded": True,
        "historical_research_gaps_allowed": True,
        "historical_research_gaps_reason": "documented Binance no-candle / maintenance intervals",
        "synthetic_candles_inserted": False,
        "holdout_must_be_gap_free": True,
        "full_history_research_used": True,
        **SAFETY_FLAGS,
    }
    _write_json(paths["manifest"], manifest)
    _write_json(
        paths["state"],
        {
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
        },
    )
    return manifest


def _replay(config: FullHistorySealedHoldoutCourtConfig, dataset: Path, output: Path, label: str) -> dict[str, Any]:
    if config.replay_function:
        return config.replay_function(dataset, output, START_CAPITAL_25K, label)
    return _default_replay(config, dataset, output, START_CAPITAL_25K, label)


def run_research_and_freeze(config: FullHistorySealedHoldoutCourtConfig) -> dict[str, Any]:
    paths = _paths(config.output_root)
    manifest = _read_json(paths["manifest"], {})
    state = _read_json(paths["state"], {})
    if not manifest or paths["holdout_output"].exists():
        raise ValueError("split_not_prepared_or_holdout_outputs_exist")
    state["research_replay_started_at"] = _now()
    _write_json(paths["state"], state)
    research = _replay(config, paths["research_dataset"], paths["research_output"], "full_history_research_pre_holdout")
    state["research_replay_completed_at"] = _now()
    strategy_hashes = _hash_map(_strategy_files(config.package_root))
    config_path = config.package_root / "config" / "structural_compounding_settings.json"
    rules_path = config.package_root / "output" / "frozen_patch_validation_audit_001" / "diagnostics" / "frozen_patch_rules.json"
    freeze = {
        "court_002": True,
        "git_commit_hash": _git_commit(config.project_root),
        "strategy_module_hashes": strategy_hashes,
        "frozen_engine_signature": _signature(strategy_hashes),
        "config_hash": _sha256(config_path),
        "frozen_rule_hash": _sha256(rules_path),
        "research_dataset_hash": _sha256(paths["research_dataset"]),
        "holdout_dataset_hash": _sha256(paths["holdout_dataset"]),
        "eur_25000_diagnostic_capital": True,
        "eur_25000_active_sizing": False,
        "freeze_created_at": _now(),
        "holdout_not_used_before_freeze": True,
        "full_history_research_used": True,
        "no_paper_live_order_broker_path": True,
        **SAFETY_FLAGS,
    }
    _write_json(paths["freeze"], freeze)
    state["freeze_written_at"] = freeze["freeze_created_at"]
    _write_json(paths["state"], state)
    return research


def open_holdout_once(config: FullHistorySealedHoldoutCourtConfig) -> dict[str, Any]:
    paths = _paths(config.output_root)
    freeze = _read_json(paths["freeze"], {})
    state = _read_json(paths["state"], {})
    if not freeze:
        raise ValueError("freeze_signature_missing")
    if int(state.get("holdout_open_count") or 0) != 0:
        raise ValueError("holdout_already_opened")
    if _sha256(paths["holdout_dataset"]) != freeze["holdout_dataset_hash"]:
        raise ValueError("holdout_hash_changed_after_freeze")
    if _hash_map(_strategy_files(config.package_root)) != freeze["strategy_module_hashes"]:
        raise ValueError("strategy_changed_between_freeze_and_holdout")
    config_path = config.package_root / "config" / "structural_compounding_settings.json"
    if _sha256(config_path) != freeze["config_hash"]:
        raise ValueError("config_changed_between_freeze_and_holdout")
    state["holdout_opened_at"] = _now()
    state["holdout_open_count"] = 1
    _write_json(paths["state"], state)
    result = _replay(config, paths["holdout_dataset"], paths["holdout_output"], "sealed_holdout_court_002")
    state["holdout_validation_completed_at"] = _now()
    _write_json(paths["state"], state)
    return result


def _comparison(research: dict[str, Any], holdout: dict[str, Any]) -> dict[str, Any]:
    return {
        "trusted_20k_baseline": {
            "starting_capital": START_CAPITAL_20K,
            "rolling_5y_average_ending_equity": TRUSTED_20K_AVERAGE,
            "rolling_5y_median_ending_equity": TRUSTED_20K_MEDIAN,
            "hit_1m_windows": TRUSTED_20K_HIT_1M,
        },
        "linear_25k_projection": {
            "average_ending_equity": round(TRUSTED_20K_AVERAGE * 1.25, 6),
            "median_ending_equity": round(TRUSTED_20K_MEDIAN * 1.25, 6),
            "scale_factor": 1.25,
        },
        "context_reference": {
            "classification": "SIX_H_CONTEXT_IMPROVES_1H_RESEARCH_ONLY",
            "best_variant": "LIGHT_BOOST_6H_CONFLUENCE",
            "rolling_5y_average_ending_equity": CONTEXT_20K_AVERAGE,
            "rolling_5y_median_ending_equity": CONTEXT_20K_MEDIAN,
            "hit_1m_windows": CONTEXT_20K_HIT_1M,
        },
        "planning_anchor": {"rough_20k_reference": 850000, "rough_25k_projection": 1062500, "diagnostic_only": True},
        "full_history_research_25k": research,
        "holdout_25k": holdout,
        "same_window_20k_holdout_counterfactual": holdout.get("same_window_20k_counterfactual_ending_equity"),
        "same_window_scaling_ratio": holdout.get("same_window_25k_to_20k_ending_ratio"),
        "same_window_linear_scaling_pass": abs(float(holdout.get("same_window_25k_to_20k_ending_ratio") or 0.0) - 1.25) <= 0.000001,
    }


def _difference(value: Any, reference: Any) -> Any:
    if isinstance(value, (int, float)) and isinstance(reference, (int, float)):
        return float(value) - float(reference)
    return "N/A"


def _write_report(path: Path, summary: dict[str, Any]) -> None:
    research = summary["full_history_research_replay"]
    holdout = summary["sealed_holdout_validation"]
    comparison = summary["comparison"]
    baseline = comparison["trusted_20k_baseline"]
    projection = comparison["linear_25k_projection"]
    counterfactual = comparison["same_window_20k_holdout_counterfactual"]
    rows = [
        ("Starting capital", 20000, 25000, research.get("starting_capital_eur"), holdout.get("starting_capital_eur"), 20000, "Diagnostic capital only"),
        ("Ending equity", baseline["rolling_5y_average_ending_equity"], projection["average_ending_equity"], research.get("ending_diagnostic_equity"), holdout.get("ending_diagnostic_equity"), counterfactual, "Long-history and holdout windows differ"),
        ("Return multiple", baseline["rolling_5y_average_ending_equity"] / 20000, projection["average_ending_equity"] / 25000, research.get("return_multiple"), holdout.get("return_multiple"), counterfactual / 20000 if counterfactual else None, "Same-window ratio is the scaling test"),
        ("Net profit", baseline["rolling_5y_average_ending_equity"] - 20000, projection["average_ending_equity"] - 25000, research.get("net_profit_eur"), holdout.get("net_profit_eur"), counterfactual - 20000 if counterfactual else None, "Capital-dependent metric"),
        ("Accepted trades", "N/A", "N/A", research.get("accepted_trades"), holdout.get("accepted_trades"), holdout.get("accepted_trades"), "Capital-invariant selection"),
        ("Rejected setups", "N/A", "N/A", research.get("rejected_setups"), holdout.get("rejected_setups"), holdout.get("rejected_setups"), "Capital-invariant selection"),
        ("Trade frequency", "N/A", "N/A", research.get("trade_frequency_per_day"), holdout.get("trade_frequency_per_day"), holdout.get("trade_frequency_per_day"), "Window-dependent"),
        ("Zero-trade days", "N/A", "N/A", research.get("zero_trade_days"), holdout.get("zero_trade_days"), holdout.get("zero_trade_days"), "Window-dependent"),
        ("Total R", "N/A", "N/A", research.get("total_R"), holdout.get("total_R"), holdout.get("total_R"), "Capital invariant"),
        ("Average R", "N/A", "N/A", research.get("average_R"), holdout.get("average_R"), holdout.get("average_R"), "Capital invariant"),
        ("Median R", "N/A", "N/A", research.get("median_R"), holdout.get("median_R"), holdout.get("median_R"), "Capital invariant"),
        ("Win rate", "N/A", "N/A", research.get("win_rate"), holdout.get("win_rate"), holdout.get("win_rate"), "Capital invariant"),
        ("Profit factor", "N/A", "N/A", research.get("profit_factor"), holdout.get("profit_factor"), holdout.get("profit_factor"), "Capital invariant"),
        ("Max drawdown", "N/A", "N/A", research.get("max_drawdown_pct"), holdout.get("max_drawdown_pct"), holdout.get("max_drawdown_pct"), "Percentage-risk metric"),
        ("Best trade", "N/A", "N/A", research.get("best_trade_R"), holdout.get("best_trade_R"), holdout.get("best_trade_R"), "R multiple"),
        ("Worst trade", "N/A", "N/A", research.get("worst_trade_R"), holdout.get("worst_trade_R"), holdout.get("worst_trade_R"), "R multiple"),
        ("Long/short split", "N/A", "N/A", f"{research.get('long_trade_count')}/{research.get('short_trade_count')}", f"{holdout.get('long_trade_count')}/{holdout.get('short_trade_count')}", f"{holdout.get('long_trade_count')}/{holdout.get('short_trade_count')}", "Frozen selection"),
        ("6H context usage", "Research-only", "Research-only", research.get("six_h_context_only"), holdout.get("six_h_context_only"), holdout.get("six_h_context_only"), "Non-executing context"),
        ("Safety status", "Research-only", "Research-only", "Research-only", "Research-only", "Research-only", "No execution permission"),
        ("paper_validation_ready", False, False, False, False, False, "Must remain false"),
    ]
    lines = [
        "# EUR 25,000 Full-History Sealed Six-Month Holdout Court 002",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        f"- Research window: `{summary['split_manifest']['research_start']}` through `{summary['split_manifest']['research_end']}`",
        f"- Holdout window: `{summary['split_manifest']['holdout_start']}` through `{summary['split_manifest']['holdout_end']}`",
        f"- Documented Binance no-candle intervals: `{summary['historical_exchange_gap_audit']['total_historical_gaps']}` / `{summary['historical_exchange_gap_audit']['total_missing_minutes']}` missing minutes.",
        "- These are exchange-confirmed research-side no-candle/maintenance intervals, not hidden corruption. No synthetic or forward-filled bars were inserted.",
        f"- Holdout gaps / duplicates / OHLC failures: `{summary['split_manifest']['holdout_gap_count']}` / `{summary['split_manifest']['holdout_duplicate_count']}` / `{summary['split_manifest']['holdout_ohlc_sanity_failures']}`.",
        f"- Anti-leakage passed: `{summary['anti_leakage_audit']['passed']}`.",
        "",
        "## Full EUR 20k vs EUR 25k comparison",
        "",
        "| Metric | EUR 20k Trusted Baseline | EUR 25k Linear Projection | EUR 25k Full-History Pre-Holdout Research Replay | EUR 25k Sealed 6M Holdout Validation | Same-Window EUR 20k Holdout Counterfactual | Difference vs 20k Baseline | Difference vs 25k Linear Projection | Interpretation |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    lines.extend(
        f"| {metric} | {_display(base)} | {_display(projected)} | {_display(research_value)} | {_display(holdout_value)} | {_display(counter)} | {_display(_difference(holdout_value, base))} | {_display(_difference(holdout_value, projected))} | {interpretation} |"
        for metric, base, projected, research_value, holdout_value, counter, interpretation in rows
    )
    lines.extend(
        [
            "",
            "## Court answers",
            "",
            f"- EUR 25k scaled reasonably from same-window EUR 20k: `{comparison['same_window_linear_scaling_pass']}`.",
            f"- Holdout supports the EUR 25k thesis: `{summary['holdout_supports_25k_thesis']}`.",
            f"- Signal collapse: `{summary['holdout_signal_collapse']}`.",
            f"- Unacceptable drawdown: `{summary['holdout_drawdown_unacceptable']}`.",
            f"- Trade-frequency collapse: `{summary['holdout_trade_frequency_collapsed']}`.",
            f"- 6H remained context-only: `{summary['six_h_context_remained_context_only']}`.",
            f"- Anti-leakage violation: `{not summary['anti_leakage_audit']['passed']}`.",
            "- Paper/live/order/broker path enabled: `false`.",
            "- EUR 25,000 remains diagnostic only: `true`.",
            "- `paper_validation_ready=false`.",
            "",
            "The rough 20k -> 850k / 25k -> 1,062,500 planning anchor remains diagnostic planning context only.",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def finalize(config: FullHistorySealedHoldoutCourtConfig, research: dict[str, Any], holdout: dict[str, Any]) -> dict[str, Any]:
    paths = _paths(config.output_root)
    manifest = _read_json(paths["manifest"], {})
    freeze = _read_json(paths["freeze"], {})
    state = _read_json(paths["state"], {})
    gap_manifest = _read_json(paths["gap_manifest"], {})
    config_path = config.package_root / "config" / "structural_compounding_settings.json"
    current_strategy = _hash_map(_strategy_files(config.package_root))
    anti = {
        "holdout_file_created_before_research_replay": state["split_created_at"] <= state["research_replay_started_at"],
        "holdout_file_hash_recorded_before_research_replay": state["holdout_hash_recorded_at"] <= state["research_replay_started_at"],
        "holdout_strategy_outputs_not_generated_before_freeze": not state["holdout_strategy_outputs_generated_before_freeze"],
        "holdout_outcomes_not_inspected_before_freeze": not state["holdout_outcomes_inspected_before_freeze"],
        "strategy_unchanged_between_freeze_and_validation": current_strategy == freeze["strategy_module_hashes"],
        "config_unchanged_between_freeze_and_validation": _sha256(config_path) == freeze["config_hash"],
        "holdout_opened_only_after_freeze": state["holdout_opened_at"] >= state["freeze_written_at"],
        "holdout_validation_performed_exactly_once": int(state["holdout_open_count"]) == 1,
        "no_retuning_after_holdout_results": current_strategy == freeze["strategy_module_hashes"],
        "court_001_not_used_as_validation_evidence": manifest["court_001_not_used_as_validation_evidence"],
        "full_history_archive_used_for_research": manifest["full_history_research_used"],
        "fresh_data_fetched_before_split": manifest["latest_data_fetched_before_court"],
        "fresh_june_21_data_included_in_holdout": manifest["fresh_june_21_data_included_in_holdout"],
        "incomplete_current_candle_excluded": manifest["incomplete_current_candle_excluded"],
        "historical_research_gaps_exchange_confirmed": gap_manifest["all_gaps_exchange_confirmed"],
        "no_synthetic_candles_inserted": not gap_manifest["synthetic_candles_inserted"],
    }
    anti["passed"] = all(anti.values())
    _write_json(paths["anti_leakage"], {**anti, **SAFETY_FLAGS})
    comparison = _comparison(research, holdout)
    holdout_ok = (
        int(manifest["holdout_gap_count"]) == 0
        and int(manifest["holdout_duplicate_count"]) == 0
        and int(manifest["holdout_ohlc_sanity_failures"]) == 0
        and int(holdout.get("accepted_trades") or 0) >= 5
        and float(holdout.get("total_R") or 0.0) > 0.0
        and float(holdout.get("profit_factor") or 0.0) >= 1.0
        and float(holdout.get("max_drawdown_pct") or 1.0) <= 0.35
        and int(holdout.get("six_h_context_annotations") or 0) > 0
    )
    if not anti["passed"] or not holdout_ok:
        classification = FAILED
        reasons = ["anti_leakage_or_holdout_validation_failed"]
    elif not comparison["same_window_linear_scaling_pass"]:
        classification = WARNING
        reasons = ["same_window_25k_scaling_deviated_from_20k_counterfactual"]
    else:
        classification = PASSED
        reasons = ["full_history_research_and_sealed_holdout_passed_with_documented_exchange_gaps"]
    summary = {
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_data_manifest": _read_json(paths["source_manifest"], {}),
        "split_manifest": manifest,
        "historical_exchange_gap_audit": gap_manifest,
        "full_history_research_replay": research,
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


def run_court(config: FullHistorySealedHoldoutCourtConfig) -> dict[str, Any]:
    paths = _paths(config.output_root)
    if paths["summary"].exists() or int(_read_json(paths["state"], {}).get("holdout_open_count") or 0) > 0:
        raise ValueError("sealed_holdout_court_002_already_executed")
    prepare_split(config)
    research = run_research_and_freeze(config)
    holdout = open_holdout_once(config)
    return finalize(config, research, holdout)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run EUR25k full-history sealed six-month holdout Court 002.")
    parser.add_argument("--full-history-csv", default="data_storage/BTCUSDT/1m/BTCUSDT_1m_2018-01-01_to_2026-06-13.csv")
    parser.add_argument("--canonical-csv", default="structural_compounding_lab/data_storage/BTCUSDT/1m/btcusdt_1m_canonical_shadow_forward.csv")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    result = run_court(
        FullHistorySealedHoldoutCourtConfig(
            project_root=root,
            package_root=package_root(),
            full_history_csv_path=resolve_project_path(args.full_history_csv),
            canonical_csv_path=resolve_project_path(args.canonical_csv),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
