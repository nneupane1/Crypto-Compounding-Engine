from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
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
from structural_compounding_lab.diagnostics.fx_dukascopy_data_quality_court import _minute_gap_classification  # noqa: E402


COURT_NAME = "FX_EURUSD_PRE_HOLDOUT_RESEARCH_REPLAY_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "fx_eurusd_pre_holdout_research_replay_001"
SOURCE_CSV = "data_storage/FX/EURUSD/1m/EURUSD_1m_2003-05-04_to_2026-06-29.csv"
VIRGIN_HOLDOUT_START = "2024-06-29T00:00:00+00:00"
RESEARCH_END = "2024-06-28T23:59:00+00:00"
RESEARCH_START = "2003-05-04T00:00:00+00:00"
LATEST_SIX_MONTHS_EXCLUDED_START = "2025-12-29T00:00:00+00:00"
LATEST_SIX_MONTHS_EXCLUDED_END = "2026-06-29T23:59:00+00:00"
START_CAPITAL_EUR = 25000.0

VALIDATION_WINDOWS: tuple[dict[str, str], ...] = (
    {
        "window_id": "virgin_6m_2025_06_29_to_2025_12_28",
        "start": "2025-06-29T00:00:00+00:00",
        "end": "2025-12-28T23:59:00+00:00",
        "label": "earlier_6m_window_1_excludes_latest_problem_window",
    },
    {
        "window_id": "virgin_6m_2024_12_29_to_2025_06_28",
        "start": "2024-12-29T00:00:00+00:00",
        "end": "2025-06-28T23:59:00+00:00",
        "label": "earlier_6m_window_2",
    },
    {
        "window_id": "virgin_6m_2024_06_29_to_2024_12_28",
        "start": "2024-06-29T00:00:00+00:00",
        "end": "2024-12-28T23:59:00+00:00",
        "label": "earlier_6m_window_3_oldest_window_after_research_boundary",
    },
)

SAFETY_FLAGS: dict[str, Any] = {
    "paper_validation_ready": False,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "broker_path_created": False,
    "order_path_created": False,
    "account_path_created": False,
    "private_endpoint_used": False,
    "signed_endpoint_used": False,
    "virgin_holdout_opened": False,
    "virgin_holdout_rows_used": False,
    "synthetic_candles_inserted": False,
    "forward_fill_inserted": False,
    "back_fill_inserted": False,
}


@dataclass(frozen=True)
class FxPreHoldoutReplayConfig:
    project_root: Path
    package_root: Path
    source_csv: Path
    output_root: Path
    research_start: str = RESEARCH_START
    research_end: str = RESEARCH_END
    virgin_holdout_start: str = VIRGIN_HOLDOUT_START
    checkpoint_every_bars: int = 2500
    max_bars: int | None = None


def default_config() -> FxPreHoldoutReplayConfig:
    root = project_root()
    pkg = package_root()
    return FxPreHoldoutReplayConfig(
        project_root=root,
        package_root=pkg,
        source_csv=root / SOURCE_CSV,
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _git_commit(root: Path) -> str:
    try:
        return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
    except Exception:
        return "unknown"


def _paths(config: FxPreHoldoutReplayConfig) -> dict[str, Path]:
    return {
        "source_manifest": config.output_root / "source_split_manifest.json",
        "pre_holdout_source": config.output_root / "source" / "EURUSD_1m_2003-05-04_to_2024-06-28_pre_holdout_only.csv",
        "source_checkpoint": config.output_root / "source" / "_checkpoints" / "pre_holdout_source_build_checkpoint.json",
        "raw_engine_root": config.output_root / "raw_engine",
        "supervisor_status": config.output_root / "latest_status.json",
        "run_pid": config.output_root / "run.pid",
        "validation_plan": config.output_root / "validation_windows" / "three_six_month_virgin_validation_plan.json",
        "validation_summary": config.output_root / "validation_windows" / "three_six_month_virgin_validation_summary.json",
    }


def _same_or_newer(path: Path, source: Path) -> bool:
    return path.exists() and path.stat().st_size > 0 and path.stat().st_mtime >= source.stat().st_mtime


def build_pre_holdout_source(config: FxPreHoldoutReplayConfig) -> dict[str, Any]:
    paths = _paths(config)
    paths["pre_holdout_source"].parent.mkdir(parents=True, exist_ok=True)
    checkpoint = _read_json(paths["source_checkpoint"], {})
    if _same_or_newer(paths["pre_holdout_source"], config.source_csv):
        existing = _read_json(paths["source_manifest"], {})
        if existing.get("pre_holdout_source_complete"):
            return existing

    tmp_path = paths["pre_holdout_source"].with_suffix(".csv.partial")
    if tmp_path.exists():
        tmp_path.unlink()
    rows_seen = 0
    rows_written = 0
    first_timestamp = ""
    last_timestamp = ""
    stopped_at_virgin_boundary = False
    started = time.time()
    holdout_date = config.virgin_holdout_start[:10]
    with config.source_csv.open(newline="", encoding="utf-8") as src, tmp_path.open("w", newline="", encoding="utf-8") as dst:
        reader = csv.DictReader(src)
        required = ["timestamp", "open", "high", "low", "close", "volume"]
        fieldnames = [name for name in reader.fieldnames or [] if name in required]
        if fieldnames != required:
            missing = [name for name in required if name not in fieldnames]
            raise ValueError(f"source_missing_required_columns:{missing}")
        writer = csv.DictWriter(dst, fieldnames=required)
        writer.writeheader()
        for row in reader:
            rows_seen += 1
            ts = row.get("timestamp", "")
            if ts[:10] >= holdout_date:
                stopped_at_virgin_boundary = True
                break
            writer.writerow({key: row.get(key, "") for key in required})
            rows_written += 1
            first_timestamp = first_timestamp or ts
            last_timestamp = ts
            if rows_written % 250000 == 0:
                _write_json(
                    paths["source_checkpoint"],
                    {
                        "state": "building_pre_holdout_source",
                        "updated_at": _now(),
                        "rows_seen": rows_seen,
                        "rows_written": rows_written,
                        "first_timestamp": first_timestamp,
                        "last_timestamp": last_timestamp,
                        "virgin_holdout_start": config.virgin_holdout_start,
                        **SAFETY_FLAGS,
                    },
                )
    tmp_path.replace(paths["pre_holdout_source"])
    manifest = {
        "court_name": COURT_NAME,
        "created_at": _now(),
        "source_csv": str(config.source_csv),
        "pre_holdout_source": str(paths["pre_holdout_source"]),
        "pre_holdout_source_complete": True,
        "rows_seen_until_boundary": rows_seen,
        "rows_written": rows_written,
        "first_timestamp": first_timestamp,
        "last_timestamp": last_timestamp,
        "research_start": config.research_start,
        "research_end": config.research_end,
        "virgin_holdout_start": config.virgin_holdout_start,
        "virgin_holdout_definition": "last_2_years_reserved_unopened_for_future_validation",
        "stopped_at_virgin_boundary": stopped_at_virgin_boundary,
        "elapsed_seconds": time.time() - started,
        "git_commit_hash": _git_commit(config.project_root),
        **SAFETY_FLAGS,
    }
    _write_json(paths["source_manifest"], manifest)
    _write_json(paths["source_checkpoint"], {**manifest, "state": "pre_holdout_source_complete"})
    return manifest


def _engine_config(config: FxPreHoldoutReplayConfig) -> StructuralLabConfig:
    base = StructuralLabConfig.load()
    payload = json.loads(json.dumps(base.data))
    payload["symbol"] = "EURUSD"
    payload["base_capital"] = START_CAPITAL_EUR
    payload["data"]["analysis_start_date"] = config.research_start
    payload["data"]["analysis_end_date"] = config.research_end
    payload["engine"]["resume_enabled"] = True
    payload["engine"]["checkpoint_every_bars"] = config.checkpoint_every_bars
    payload["engine"]["write_partial_artifacts"] = True
    return StructuralLabConfig(data=payload, config_path=base.config_path, root_dir=base.root_dir)


def _engine_config_for_window(config: FxPreHoldoutReplayConfig, *, start: str, end: str) -> StructuralLabConfig:
    base = StructuralLabConfig.load()
    payload = json.loads(json.dumps(base.data))
    payload["symbol"] = "EURUSD"
    payload["base_capital"] = START_CAPITAL_EUR
    payload["data"]["analysis_start_date"] = start
    payload["data"]["analysis_end_date"] = end
    payload["engine"]["resume_enabled"] = True
    payload["engine"]["checkpoint_every_bars"] = config.checkpoint_every_bars
    payload["engine"]["write_partial_artifacts"] = True
    return StructuralLabConfig(data=payload, config_path=base.config_path, root_dir=base.root_dir)


def build_validation_window_plan(config: FxPreHoldoutReplayConfig) -> dict[str, Any]:
    paths = _paths(config)
    windows: list[dict[str, Any]] = []
    for item in VALIDATION_WINDOWS:
        source_path = _validation_source_path(config, item["window_id"])
        window_start = item["start"]
        may_validate = window_start >= config.virgin_holdout_start and window_start > config.research_end
        windows.append(
            {
                **item,
                "symbol": "EURUSD",
                "source_csv": str(source_path),
                "raw_engine_root": str(_validation_engine_root(config, item["window_id"])),
                "research_boundary_respected": may_validate,
                "opened_for_research": False,
                "opened_for_validation": False,
                "validation_source_created": source_path.exists(),
                "validation_executed": (_validation_engine_root(config, item["window_id"]) / "summary.json").exists(),
                "may_validate_after_research_replay_completion": may_validate,
                "requires_clean_window_quality": True,
                "synthetic_candles_inserted": False,
                "forward_fill_inserted": False,
                "back_fill_inserted": False,
            }
        )
    plan = {
        "court_name": COURT_NAME,
        "created_at": _now(),
        "plan_name": "EURUSD_THREE_EARLIER_SIX_MONTH_VIRGIN_VALIDATION_WINDOWS",
        "source_csv": str(config.source_csv),
        "pre_holdout_research_start": config.research_start,
        "pre_holdout_research_end": config.research_end,
        "two_year_virgin_pool_start": config.virgin_holdout_start,
        "latest_six_months_excluded_start": LATEST_SIX_MONTHS_EXCLUDED_START,
        "latest_six_months_excluded_end": LATEST_SIX_MONTHS_EXCLUDED_END,
        "latest_six_months_excluded_reason": "latest_6m_fx_holdout_has_documented_data_quality_issue",
        "window_count": len(windows),
        "windows": windows,
        "validation_window_data_opened_by_plan": False,
        "run_guard": "prepare_validation_sources and run_validation_windows refuse to run until pre-holdout research replay is completed",
        "classification_options": [
            "FX_EURUSD_THREE_6M_VIRGIN_VALIDATION_READY_RESEARCH_ONLY",
            "FX_EURUSD_THREE_6M_VIRGIN_VALIDATION_PARTIAL_WARNING_RESEARCH_ONLY",
            "FX_EURUSD_THREE_6M_VIRGIN_VALIDATION_FAILED_RESEARCH_ONLY",
            "FX_EURUSD_THREE_6M_VIRGIN_VALIDATION_BLOCKED_RESEARCH_NOT_COMPLETE",
        ],
        **SAFETY_FLAGS,
    }
    _write_json(paths["validation_plan"], plan)
    return plan


def _validation_source_path(config: FxPreHoldoutReplayConfig, window_id: str) -> Path:
    return config.output_root / "validation_windows" / window_id / "source" / f"EURUSD_1m_{window_id}.csv"


def _validation_engine_root(config: FxPreHoldoutReplayConfig, window_id: str) -> Path:
    return config.output_root / "validation_windows" / window_id / "raw_engine"


def _research_replay_completed(config: FxPreHoldoutReplayConfig) -> bool:
    paths = _paths(config)
    latest = _read_json(paths["supervisor_status"], {})
    return latest.get("final_classification") == "FX_EURUSD_PRE_HOLDOUT_RESEARCH_REPLAY_COMPLETED_RESEARCH_ONLY"


def _require_research_replay_completed(config: FxPreHoldoutReplayConfig) -> None:
    if _research_replay_completed(config):
        return
    paths = _paths(config)
    raw_status = _read_json(paths["raw_engine_root"] / "status.json", {})
    raise RuntimeError(
        "fx_eurusd_validation_blocked_research_replay_not_complete:"
        f"state={raw_status.get('state')};"
        f"current_index={raw_status.get('current_index')};"
        f"total_bars={raw_status.get('total_bars')};"
        f"progress_pct={raw_status.get('progress_pct')}"
    )


def _date_part(timestamp_text: str) -> str:
    return timestamp_text.strip()[:10]


def _window_dates(window: dict[str, str]) -> tuple[str, str]:
    return _date_part(window["start"]), _date_part(window["end"])


def _quality_for_validation_source(source_path: Path) -> dict[str, Any]:
    frame = pd.read_csv(source_path)
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"validation_source_missing_columns:{missing}")
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    for column in required:
        if column != "timestamp":
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    frame = frame.dropna(subset=required).sort_values("timestamp").reset_index(drop=True)
    duplicate_count = int(frame["timestamp"].duplicated().sum())
    ohlc_failures = int(
        (
            (frame["high"] < frame[["open", "close", "low"]].max(axis=1))
            | (frame["low"] > frame[["open", "close", "high"]].min(axis=1))
        ).sum()
    )
    deltas = frame["timestamp"].diff().dropna()
    gap_indices = deltas[deltas > pd.Timedelta(minutes=1)].index.tolist()
    gaps = []
    for idx in gap_indices:
        prev_ts = frame.loc[idx - 1, "timestamp"]
        curr_ts = frame.loc[idx, "timestamp"]
        gaps.append(_minute_gap_classification(prev_ts + pd.Timedelta(minutes=1), curr_ts - pd.Timedelta(minutes=1)))
    unexpected = sum(int(gap["unexpected_in_session_minutes"]) for gap in gaps)
    return {
        "rows": int(len(frame)),
        "first_timestamp": frame["timestamp"].min().isoformat() if not frame.empty else "",
        "last_timestamp": frame["timestamp"].max().isoformat() if not frame.empty else "",
        "duplicate_count": duplicate_count,
        "ohlc_sanity_failures": ohlc_failures,
        "total_gaps": len(gaps),
        "total_missing_minutes": sum(int(gap["missing_minutes"]) for gap in gaps),
        "expected_fx_market_closure_minutes": sum(int(gap["expected_market_closure_minutes"]) for gap in gaps),
        "unexpected_in_session_missing_minutes": unexpected,
        "gaps": gaps,
        "session_clean": duplicate_count == 0 and ohlc_failures == 0 and unexpected == 0,
        "weekend_market_closures_allowed": True,
        "synthetic_candles_inserted": False,
        "forward_fill_inserted": False,
        "back_fill_inserted": False,
    }


def prepare_validation_sources(config: FxPreHoldoutReplayConfig) -> dict[str, Any]:
    _require_research_replay_completed(config)
    plan = build_validation_window_plan(config)
    required = ["timestamp", "open", "high", "low", "close", "volume"]
    handles: dict[str, Any] = {}
    writers: dict[str, csv.DictWriter] = {}
    counts: dict[str, int] = {item["window_id"]: 0 for item in VALIDATION_WINDOWS}
    temp_paths: dict[str, Path] = {}
    try:
        for window in VALIDATION_WINDOWS:
            path = _validation_source_path(config, window["window_id"])
            path.parent.mkdir(parents=True, exist_ok=True)
            temp = path.with_suffix(".csv.partial")
            if temp.exists():
                temp.unlink()
            temp_paths[window["window_id"]] = temp
            handle = temp.open("w", newline="", encoding="utf-8")
            handles[window["window_id"]] = handle
            writer = csv.DictWriter(handle, fieldnames=required)
            writer.writeheader()
            writers[window["window_id"]] = writer
        with config.source_csv.open(newline="", encoding="utf-8") as src:
            reader = csv.DictReader(src)
            missing = [name for name in required if name not in (reader.fieldnames or [])]
            if missing:
                raise ValueError(f"source_missing_required_columns:{missing}")
            for row in reader:
                row_date = _date_part(row.get("timestamp", ""))
                for window in VALIDATION_WINDOWS:
                    start_date, end_date = _window_dates(window)
                    if start_date <= row_date <= end_date:
                        writers[window["window_id"]].writerow({key: row.get(key, "") for key in required})
                        counts[window["window_id"]] += 1
                        break
    finally:
        for handle in handles.values():
            handle.close()

    window_payloads: list[dict[str, Any]] = []
    for window in VALIDATION_WINDOWS:
        window_id = window["window_id"]
        final_path = _validation_source_path(config, window_id)
        temp_paths[window_id].replace(final_path)
        quality = _quality_for_validation_source(final_path)
        payload = {
            **window,
            "source_csv": str(final_path),
            "rows_written": counts[window_id],
            "source_created_at": _now(),
            "quality": quality,
            "opened_for_research": False,
            "opened_for_validation_source_preparation": True,
            "validation_executed": False,
            "may_run_validation": bool(quality["session_clean"] and counts[window_id] > 0),
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "validation_windows" / window_id / "validation_source_manifest.json", payload)
        window_payloads.append(payload)

    summary = {
        "court_name": COURT_NAME,
        "created_at": _now(),
        "final_classification": "FX_EURUSD_THREE_6M_VIRGIN_VALIDATION_SOURCES_READY_RESEARCH_ONLY"
        if all(item["may_run_validation"] for item in window_payloads)
        else "FX_EURUSD_THREE_6M_VIRGIN_VALIDATION_SOURCE_QUALITY_WARNING_RESEARCH_ONLY",
        "plan": plan,
        "windows": window_payloads,
        "latest_six_months_excluded": True,
        "latest_six_months_excluded_start": LATEST_SIX_MONTHS_EXCLUDED_START,
        "latest_six_months_excluded_end": LATEST_SIX_MONTHS_EXCLUDED_END,
        "opened_for_research": False,
        "synthetic_candles_inserted": False,
        "forward_fill_inserted": False,
        "back_fill_inserted": False,
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "validation_windows" / "validation_source_summary.json", summary)
    return summary


def run_validation_windows(config: FxPreHoldoutReplayConfig) -> dict[str, Any]:
    _require_research_replay_completed(config)
    source_summary = prepare_validation_sources(config)
    results: list[dict[str, Any]] = []
    for window in source_summary["windows"]:
        window_id = window["window_id"]
        if not window.get("may_run_validation"):
            results.append(
                {
                    **window,
                    "validation_executed": False,
                    "final_classification": "FX_EURUSD_6M_VIRGIN_VALIDATION_FAILED_DATA_QUALITY_RESEARCH_ONLY",
                }
            )
            continue
        engine_root = _validation_engine_root(config, window_id)
        summary = StructuralBacktestEngine(config=_engine_config_for_window(config, start=window["start"], end=window["end"])).run(
            symbol="EURUSD",
            source_csv=window["source_csv"],
            output_dir=str(engine_root),
        )
        results.append(
            {
                **window,
                "validation_executed": True,
                "raw_engine_root": str(engine_root),
                "raw_engine_summary": summary,
                "final_classification": "FX_EURUSD_6M_VIRGIN_VALIDATION_COMPLETED_RESEARCH_ONLY"
                if summary.get("run_state") == "completed"
                else "FX_EURUSD_6M_VIRGIN_VALIDATION_PARTIAL_CHECKPOINTED_RESEARCH_ONLY",
                "opened_for_research": False,
                "opened_for_validation": True,
                **SAFETY_FLAGS,
            }
        )
    completed = [item for item in results if item.get("final_classification") == "FX_EURUSD_6M_VIRGIN_VALIDATION_COMPLETED_RESEARCH_ONLY"]
    failed = [item for item in results if "FAILED" in str(item.get("final_classification", ""))]
    classification = (
        "FX_EURUSD_THREE_6M_VIRGIN_VALIDATION_FAILED_RESEARCH_ONLY"
        if failed
        else (
            "FX_EURUSD_THREE_6M_VIRGIN_VALIDATION_READY_RESEARCH_ONLY"
            if len(completed) == len(VALIDATION_WINDOWS)
            else "FX_EURUSD_THREE_6M_VIRGIN_VALIDATION_PARTIAL_WARNING_RESEARCH_ONLY"
        )
    )
    final = {
        "court_name": COURT_NAME,
        "completed_at": _now(),
        "final_classification": classification,
        "latest_six_months_excluded": True,
        "latest_six_months_excluded_start": LATEST_SIX_MONTHS_EXCLUDED_START,
        "latest_six_months_excluded_end": LATEST_SIX_MONTHS_EXCLUDED_END,
        "windows": results,
        "opened_for_research": False,
        "opened_for_validation": True,
        "paper_validation_ready": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "synthetic_candles_inserted": False,
        "forward_fill_inserted": False,
        "back_fill_inserted": False,
        **SAFETY_FLAGS,
    }
    _write_json(_paths(config)["validation_summary"], final)
    return final


def run_replay(config: FxPreHoldoutReplayConfig) -> dict[str, Any]:
    paths = _paths(config)
    config.output_root.mkdir(parents=True, exist_ok=True)
    paths["run_pid"].write_text(str(os.getpid()), encoding="utf-8")
    manifest = build_pre_holdout_source(config)
    status = {
        "court_name": COURT_NAME,
        "state": "running_raw_engine",
        "updated_at": _now(),
        "source_split_manifest": str(paths["source_manifest"]),
        "raw_engine_root": str(paths["raw_engine_root"]),
        "checkpoint": str(paths["raw_engine_root"] / "_checkpoints" / "structural_backtest.checkpoint.json"),
        "research_start": config.research_start,
        "research_end": config.research_end,
        "virgin_holdout_start": config.virgin_holdout_start,
        **SAFETY_FLAGS,
    }
    _write_json(paths["supervisor_status"], status)
    summary = StructuralBacktestEngine(config=_engine_config(config)).run(
        symbol="EURUSD",
        source_csv=str(paths["pre_holdout_source"]),
        output_dir=str(paths["raw_engine_root"]),
        max_bars=config.max_bars,
    )
    final = {
        "court_name": COURT_NAME,
        "final_classification": "FX_EURUSD_PRE_HOLDOUT_RESEARCH_REPLAY_COMPLETED_RESEARCH_ONLY"
        if summary.get("run_state") == "completed"
        else "FX_EURUSD_PRE_HOLDOUT_RESEARCH_REPLAY_PARTIAL_CHECKPOINTED_RESEARCH_ONLY",
        "completed_at": _now(),
        "source_manifest": manifest,
        "raw_engine_summary": summary,
        "raw_engine_root": str(paths["raw_engine_root"]),
        "checkpoint": str(paths["raw_engine_root"] / "_checkpoints" / "structural_backtest.checkpoint.json"),
        "can_resume": True,
        "resume_command": "python -m structural_compounding_lab.diagnostics.fx_eurusd_pre_holdout_research_replay --mode run",
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "fx_eurusd_pre_holdout_research_replay_summary.json", final)
    _write_json(paths["supervisor_status"], final)
    return final


def status(config: FxPreHoldoutReplayConfig) -> dict[str, Any]:
    paths = _paths(config)
    current = _read_json(paths["supervisor_status"], {})
    raw_status = _read_json(paths["raw_engine_root"] / "status.json", {})
    checkpoint = _read_json(paths["raw_engine_root"] / "_checkpoints" / "structural_backtest.checkpoint.json", {})
    return {
        "court_name": COURT_NAME,
        "output_root": str(config.output_root),
        "latest_status": current,
        "raw_engine_status": raw_status,
        "checkpoint_exists": bool(checkpoint),
        "checkpoint_next_index": checkpoint.get("next_index"),
        "checkpoint_total_bars": checkpoint.get("total_bars"),
        "validation_plan": str(paths["validation_plan"]),
        "validation_plan_exists": paths["validation_plan"].exists(),
        "validation_summary": str(paths["validation_summary"]),
        "validation_summary_exists": paths["validation_summary"].exists(),
        "paper_validation_ready": False,
        "live_allowed": False,
        "real_money_allowed": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument(
        "--mode",
        choices=[
            "prepare_source",
            "run",
            "status",
            "plan_validation_windows",
            "prepare_validation_sources",
            "run_validation_windows",
        ],
        default="run",
    )
    parser.add_argument("--output-dir", default=str(package_root() / "output" / OUTPUT_FOLDER_NAME))
    parser.add_argument("--max-bars", type=int, default=None)
    args = parser.parse_args()
    config = FxPreHoldoutReplayConfig(
        project_root=project_root(),
        package_root=package_root(),
        source_csv=project_root() / SOURCE_CSV,
        output_root=resolve_project_path(args.output_dir),
        max_bars=args.max_bars,
    )
    if args.mode == "prepare_source":
        payload = build_pre_holdout_source(config)
    elif args.mode == "status":
        payload = status(config)
    elif args.mode == "plan_validation_windows":
        payload = build_validation_window_plan(config)
    elif args.mode == "prepare_validation_sources":
        payload = prepare_validation_sources(config)
    elif args.mode == "run_validation_windows":
        payload = run_validation_windows(config)
    else:
        payload = run_replay(config)
    print(json.dumps(_jsonable(payload), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
