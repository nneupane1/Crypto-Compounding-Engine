from __future__ import annotations

import csv
import json
import traceback
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from structural_compounding_lab.backtest.engine import StructuralBacktestEngine
from structural_compounding_lab.config import StructuralLabConfig
from structural_compounding_lab.data.data_adapter import StructuralDataAdapter


RESEARCH_ONLY_FLAGS = {
    "research_only": True,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "runtime_strategy_changed": False,
    "config_defaults_changed": False,
}

TARGET_START = pd.Timestamp("2018-01-01 00:00:00")

LEDGER_FILES = (
    "trades.csv",
    "setup_log.csv",
    "equity.csv",
    "level_log.csv",
    "liquidity_events.csv",
    "cooldown_log.csv",
    "pyramiding_log.csv",
    "profit_vault.json",
    "summary.json",
)

SHORT_WINDOW_SENTINELS = (
    "summary.json",
    "trades.csv",
    "setup_log.csv",
    "equity.csv",
    "level_log.csv",
    "liquidity_events.csv",
    "cooldown_log.csv",
    "pyramiding_log.csv",
    "profit_vault.json",
)


@dataclass(frozen=True)
class BroadHistoricalStructuralReplayConfig:
    package_root: Path
    output_root: Path
    source_history_path: Path | None = None
    config_path: Path | None = None
    symbol: str = "BTCUSDT"


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_markdown(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _timestamp(value: Any) -> pd.Timestamp | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        stamp = pd.Timestamp(value)
    except Exception:
        return None
    if stamp.tzinfo is None:
        return stamp
    return stamp.tz_convert("UTC").tz_localize(None)


def _iso(value: Any) -> str | None:
    stamp = _timestamp(value)
    return stamp.isoformat() if stamp is not None else None


def _artifact_paths(config: BroadHistoricalStructuralReplayConfig) -> dict[str, Path]:
    root = config.output_root
    ledger_root = root / "ledger"
    diagnostics_root = root / "diagnostics"
    reports_root = root / "reports"
    runtime_root = root / "_runtime"
    return {
        "root": root,
        "ledger_root": ledger_root,
        "diagnostics_root": diagnostics_root,
        "reports_root": reports_root,
        "runtime_root": runtime_root,
        "status": root / "status.json",
        "summary": root / "broad_historical_replay_summary.json",
        "report": root / "broad_historical_replay_report.md",
        "source_data_coverage": diagnostics_root / "source_data_coverage.json",
        "replay_window_manifest": diagnostics_root / "replay_window_manifest.json",
        "yearly_trade_counts": diagnostics_root / "yearly_trade_counts.csv",
        "monthly_trade_counts": diagnostics_root / "monthly_trade_counts.csv",
        "replay_health_report": diagnostics_root / "replay_health_report.json",
        "replay_failure_report": diagnostics_root / "replay_failure_report.json",
        "data_gap_report": diagnostics_root / "data_gap_report.json",
        "no_future_leakage_checks": diagnostics_root / "no_future_leakage_checks.json",
        "generated_ledger_manifest": diagnostics_root / "generated_ledger_manifest.json",
        "next_research_recommendation": reports_root / "next_research_recommendation.json",
        "runtime_config": runtime_root / "broad_historical_structural_replay.runtime_config.json",
    }


def _load_source_frame(path: Path) -> tuple[pd.DataFrame, pd.DataFrame, int]:
    raw = pd.read_csv(path, parse_dates=["timestamp"])
    raw = raw.dropna(subset=["timestamp"]).copy()
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], errors="coerce")
    raw = raw.dropna(subset=["timestamp"]).copy()
    raw = raw.sort_values("timestamp")
    duplicate_count = int(raw["timestamp"].duplicated(keep="last").sum())
    working = raw.drop_duplicates(subset=["timestamp"], keep="last").copy()
    working = working.set_index("timestamp")
    for column in ("open", "high", "low", "close", "volume"):
        if column in working.columns:
            working[column] = pd.to_numeric(working[column], errors="coerce")
    cleaned = working.dropna(subset=[column for column in ("open", "high", "low", "close", "volume") if column in working.columns]).copy()
    return raw, cleaned.sort_index(), duplicate_count


def _count_missing_minutes(index: pd.DatetimeIndex) -> int:
    if len(index) < 2:
        return 0
    sorted_index = index.sort_values()
    diffs = sorted_index.to_series().diff().dropna()
    missing = 0
    for delta in diffs:
        steps = int(delta.total_seconds() // 60)
        if steps > 1:
            missing += steps - 1
    return int(missing)


def _extract_gap_segments(index: pd.DatetimeIndex, limit: int = 250) -> list[dict[str, Any]]:
    if len(index) < 2:
        return []
    sorted_index = index.sort_values()
    diffs = sorted_index.to_series().diff().dropna()
    gaps: list[dict[str, Any]] = []
    previous_values = sorted_index[:-1]
    current_values = sorted_index[1:]
    for previous, current, delta in zip(previous_values, current_values, diffs):
        minutes = int(delta.total_seconds() // 60)
        if minutes <= 1:
            continue
        gaps.append(
            {
                "gap_start": pd.Timestamp(previous).isoformat(),
                "gap_end": pd.Timestamp(current).isoformat(),
                "missing_minutes": minutes - 1,
            }
        )
        if len(gaps) >= limit:
            break
    return gaps


def _year_windows(start: pd.Timestamp, end: pd.Timestamp) -> list[dict[str, Any]]:
    windows: list[dict[str, Any]] = []
    for year in range(start.year, end.year + 1):
        window_start = max(start, pd.Timestamp(f"{year}-01-01 00:00:00"))
        window_end = min(end, pd.Timestamp(f"{year}-12-31 23:59:00"))
        windows.append(
            {
                "window_name": str(year),
                "start_timestamp": window_start.isoformat(),
                "end_timestamp": window_end.isoformat(),
            }
        )
    return windows


def _rows_for_period(rows: list[dict[str, Any]], *, timestamp_keys: tuple[str, ...], start: pd.Timestamp, end: pd.Timestamp) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        stamp = None
        for key in timestamp_keys:
            stamp = _timestamp(row.get(key))
            if stamp is not None:
                break
        if stamp is None:
            continue
        if start <= stamp <= end:
            selected.append(row)
    return selected


def _trade_timestamp(row: dict[str, Any]) -> pd.Timestamp | None:
    return _timestamp(row.get("exit_time")) or _timestamp(row.get("entry_time")) or _timestamp(row.get("timestamp"))


def _group_trade_counts(trades: list[dict[str, Any]], *, freq: str) -> list[dict[str, Any]]:
    counts: dict[str, dict[str, int]] = {}
    for row in trades:
        stamp = _trade_timestamp(row)
        if stamp is None:
            continue
        if freq == "year":
            label = stamp.strftime("%Y")
        else:
            label = stamp.strftime("%Y-%m")
        bucket = counts.setdefault(label, {"trade_count": 0, "long_trade_count": 0, "short_trade_count": 0})
        bucket["trade_count"] += 1
        side = str(row.get("side") or "").lower()
        if side == "long":
            bucket["long_trade_count"] += 1
        elif side == "short":
            bucket["short_trade_count"] += 1
    rows = []
    for label in sorted(counts):
        rows.append({"period": label, **counts[label]})
    return rows


def _capture_short_window_mtimes(package_root: Path) -> dict[str, int | None]:
    root = package_root / "output"
    captured: dict[str, int | None] = {}
    for name in SHORT_WINDOW_SENTINELS:
        path = root / name
        captured[name] = path.stat().st_mtime_ns if path.exists() else None
    return captured


def _short_window_untouched(package_root: Path, before: dict[str, int | None]) -> bool:
    root = package_root / "output"
    for name, previous in before.items():
        path = root / name
        current = path.stat().st_mtime_ns if path.exists() else None
        if current != previous:
            return False
    return True


def _csv_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        try:
            next(reader)
        except StopIteration:
            return 0
        return sum(1 for _ in reader)


def _csv_time_range(path: Path, columns: tuple[str, ...]) -> tuple[str | None, str | None]:
    rows = _read_csv_rows(path)
    timestamps: list[pd.Timestamp] = []
    for row in rows:
        for column in columns:
            stamp = _timestamp(row.get(column))
            if stamp is not None:
                timestamps.append(stamp)
                break
    if not timestamps:
        return None, None
    return min(timestamps).isoformat(), max(timestamps).isoformat()


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _generated_ledger_manifest(paths: dict[str, Path]) -> dict[str, Any]:
    ledger_root = paths["ledger_root"]
    file_specs = {
        "trades.csv": ("entry_time", "exit_time", "timestamp"),
        "setup_log.csv": ("timestamp",),
        "equity.csv": ("timestamp",),
        "level_log.csv": ("timestamp", "first_seen", "last_touched"),
        "liquidity_events.csv": ("timestamp",),
        "cooldown_log.csv": ("timestamp",),
        "pyramiding_log.csv": ("timestamp",),
    }
    files: dict[str, Any] = {}
    for filename in LEDGER_FILES:
        file_path = ledger_root / filename
        payload: dict[str, Any] = {
            "path": str(file_path),
            "exists": file_path.exists(),
            "size_bytes": file_path.stat().st_size if file_path.exists() else 0,
        }
        if filename.endswith(".csv"):
            payload["row_count"] = _csv_row_count(file_path)
            start_iso, end_iso = _csv_time_range(file_path, file_specs.get(filename, ("timestamp",)))
            payload["start_timestamp"] = start_iso
            payload["end_timestamp"] = end_iso
        elif filename.endswith(".json") and file_path.exists():
            payload["json_keys"] = sorted((_read_json(file_path, {}) or {}).keys())
        files[filename] = payload
    return {
        **RESEARCH_ONLY_FLAGS,
        "ledger_output_root": str(ledger_root),
        "files": files,
    }


def _build_no_future_checks(config: BroadHistoricalStructuralReplayConfig, trades: list[dict[str, Any]]) -> dict[str, Any]:
    package_root = Path(__file__).resolve().parents[1]
    pivot_source = (package_root / "market_structure" / "pivots.py").read_text(encoding="utf-8")
    sr_source = (package_root / "market_structure" / "support_resistance.py").read_text(encoding="utf-8")
    liquidity_source = (package_root / "market_structure" / "liquidity.py").read_text(encoding="utf-8")
    engine_source = (package_root / "backtest" / "engine.py").read_text(encoding="utf-8")

    trade_order_valid = all(
        (_timestamp(row.get("exit_time")) or _timestamp(row.get("entry_time")) or pd.Timestamp.min)
        >= (_timestamp(row.get("entry_time")) or pd.Timestamp.min)
        for row in trades
    )

    checks = {
        "pivot_confirmation_delay": {
            "status": "passed"
            if "range(left_bars, len(working) - right_bars)" in pivot_source and "no_future_data: bool = True" in pivot_source
            else "UNKNOWN_REQUIRES_MANUAL_REVIEW",
            "evidence": "Pivot detection confirms highs/lows only after the declared right_bars delay.",
        },
        "support_resistance_prior_only": {
            "status": "passed"
            if "working = working.loc[index <= cutoff]" in sr_source and "detect_pivots(" in sr_source
            else "UNKNOWN_REQUIRES_MANUAL_REVIEW",
            "evidence": "Structural levels are formed from candles available at or before the replay cutoff.",
        },
        "liquidity_events_timestamp_aligned": {
            "status": "passed"
            if 'timestamp = str(pd.Timestamp(working.index[index]).isoformat())' in liquidity_source
            else "UNKNOWN_REQUIRES_MANUAL_REVIEW",
            "evidence": "Liquidity events are stamped on the bar that actually triggers the sweep/reclaim logic.",
        },
        "entry_decisions_no_future_exit_data": {
            "status": "passed"
            if "history = execution.iloc[: position + 1]" in engine_source and "if portfolio.open_trade is not None:" in engine_source
            else "UNKNOWN_REQUIRES_MANUAL_REVIEW",
            "evidence": "Setup detection uses a forward-growing history slice inside the main replay loop.",
        },
        "exit_outcomes_after_entry_only": {
            "status": "passed" if trade_order_valid else "failed",
            "evidence": "Every persisted trade row has exit_time >= entry_time.",
        },
        "patch_rules_not_used_during_base_replay_generation": {
            "status": "passed"
            if "BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT" not in engine_source and "frozen_patch_validation_audit" not in engine_source
            else "failed",
            "evidence": "The broad replay uses the base structural engine, not the frozen patch audit layer.",
        },
        "yearly_chunks_do_not_leak_future_year_statistics_backward": {
            "status": "UNKNOWN_REQUIRES_MANUAL_REVIEW",
            "evidence": "The replay is executed as one chronological pass and then partitioned by year for reporting; no independent per-year chunk optimizer is used.",
        },
    }
    counts = {
        "passed": sum(1 for item in checks.values() if item["status"] == "passed"),
        "failed": sum(1 for item in checks.values() if item["status"] == "failed"),
        "unknown": sum(1 for item in checks.values() if item["status"] == "UNKNOWN_REQUIRES_MANUAL_REVIEW"),
    }
    return {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "counts": counts,
    }


def _report_markdown(summary: dict[str, Any], health: dict[str, Any], coverage: dict[str, Any], leakage: dict[str, Any]) -> str:
    warning_lines = [f"- {warning}" for warning in health.get("warnings", [])] if health.get("warnings") else ["- none"]
    return "\n".join(
        [
            "# Broad Historical Structural Replay 001",
            "",
            "## Research-only status",
            "",
            "- This replay regenerates structural lab artifacts from raw BTC history without tuning strategy rules or mutating runtime behavior.",
            f"- research_only: `{summary['research_only']}`",
            f"- real_money_allowed: `{summary['real_money_allowed']}`",
            f"- paper_allowed: `{summary['paper_allowed']}`",
            f"- live_allowed: `{summary['live_allowed']}`",
            "",
            "## Source coverage",
            "",
            f"- symbol used: `{coverage.get('symbol_used')}`",
            f"- source file: `{coverage.get('source_path')}`",
            f"- source range: `{coverage.get('source_data_start')}` -> `{coverage.get('source_data_end')}`",
            f"- cleaned rows: `{coverage.get('cleaned_rows')}`",
            f"- duplicate timestamps removed: `{coverage.get('duplicate_timestamp_count')}`",
            f"- missing minute count: `{coverage.get('missing_timestamp_count')}`",
            "",
            "## Generated ledger",
            "",
            f"- ledger output path: `{summary.get('ledger_output_path')}`",
            f"- generated ledger range: `{summary.get('generated_ledger_start')}` -> `{summary.get('generated_ledger_end')}`",
            f"- generated trade range: `{health.get('generated_trade_start')}` -> `{health.get('generated_trade_end')}`",
            f"- years generated: `{summary.get('years_generated')}`",
            f"- trade count: `{summary.get('trade_count')}`",
            f"- long trades: `{summary.get('long_trade_count')}`",
            f"- short trades: `{summary.get('short_trade_count')}`",
            "",
            "## Frozen patch readiness",
            "",
            f"- coverage sufficient for frozen patch validation: `{summary.get('coverage_sufficient_for_frozen_patch_validation')}`",
            f"- next required step: `{summary.get('next_required_step')}`",
            "",
            "## Leakage audit",
            "",
            f"- passed: `{leakage.get('counts', {}).get('passed', 0)}`",
            f"- failed: `{leakage.get('counts', {}).get('failed', 0)}`",
            f"- unknown/manual review: `{leakage.get('counts', {}).get('unknown', 0)}`",
            "",
            "## Replay health warnings",
            "",
            *warning_lines,
            "",
            "No live, paper, allocator, risk, sizing, entry, exit, threshold, or config-default behavior was changed by this generator.",
        ]
    ) + "\n"


def _ensure_empty_ledger(paths: dict[str, Path]) -> None:
    paths["ledger_root"].mkdir(parents=True, exist_ok=True)
    for filename in ("trades.csv", "setup_log.csv", "equity.csv", "level_log.csv", "liquidity_events.csv", "cooldown_log.csv", "pyramiding_log.csv"):
        (paths["ledger_root"] / filename).write_text("", encoding="utf-8")
    _write_json(paths["ledger_root"] / "profit_vault.json", {})
    _write_json(paths["ledger_root"] / "summary.json", {})


def _write_insufficient_outputs(
    config: BroadHistoricalStructuralReplayConfig,
    *,
    status_state: str,
    warnings: list[str],
    source_path: Path | None = None,
    source_coverage: dict[str, Any] | None = None,
    failure_payload: dict[str, Any] | None = None,
) -> dict[str, Path]:
    paths = _artifact_paths(config)
    _ensure_empty_ledger(paths)
    coverage_payload = source_coverage or {
        **RESEARCH_ONLY_FLAGS,
        "symbol_used": config.symbol,
        "source_path": str(source_path) if source_path is not None else None,
        "warnings": warnings,
    }
    yearly_counts: list[dict[str, Any]] = []
    monthly_counts: list[dict[str, Any]] = []
    manifest_payload = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "windows": [],
        "warnings": warnings,
    }
    failure_payload = failure_payload or {
        **RESEARCH_ONLY_FLAGS,
        "failed_stage": status_state,
        "exception_type": None,
        "exception_message": " / ".join(warnings),
        "partial_outputs_written": True,
        "last_successful_window": None,
        "next_safe_resume_window": "2018",
        "manual_fix_needed": True,
    }
    summary = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_data_start": coverage_payload.get("source_data_start"),
        "source_data_end": coverage_payload.get("source_data_end"),
        "generated_ledger_start": None,
        "generated_ledger_end": None,
        "years_generated": [],
        "trade_count": 0,
        "long_trade_count": 0,
        "short_trade_count": 0,
        "coverage_sufficient_for_frozen_patch_validation": False,
        "ledger_output_path": str(paths["ledger_root"]),
        "next_required_step": "APPLY_FROZEN_PATCH_TO_BROAD_HISTORICAL_LEDGER",
        "warnings": warnings,
    }
    health_payload = {
        **RESEARCH_ONLY_FLAGS,
        "source_start": coverage_payload.get("source_data_start"),
        "source_end": coverage_payload.get("source_data_end"),
        "generated_trade_start": None,
        "generated_trade_end": None,
        "generated_trade_years": [],
        "generated_trade_count": 0,
        "long_trade_count": 0,
        "short_trade_count": 0,
        "zero_trade_windows": [],
        "missing_years": [],
        "row_count_by_year": {},
        "trade_count_by_year": {},
        "successful_replay": False,
        "safe_for_frozen_patch_validation": False,
        "warnings": warnings,
    }
    leakage = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "checks": {},
        "counts": {"passed": 0, "failed": 0, "unknown": 0},
    }
    manifest = _generated_ledger_manifest(paths)
    report = _report_markdown(summary, health_payload, coverage_payload, leakage)
    recommendation = {
        **RESEARCH_ONLY_FLAGS,
        "next_step": "APPLY_FROZEN_PATCH_TO_BROAD_HISTORICAL_LEDGER",
        "warnings": warnings,
    }
    status_payload = {
        "state": status_state,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "warnings": warnings,
    }
    _write_json(paths["status"], status_payload)
    _write_json(paths["summary"], summary)
    _write_markdown(paths["report"], report)
    _write_json(paths["source_data_coverage"], coverage_payload)
    _write_json(paths["replay_window_manifest"], manifest_payload)
    _write_csv(paths["yearly_trade_counts"], yearly_counts)
    _write_csv(paths["monthly_trade_counts"], monthly_counts)
    _write_json(paths["replay_health_report"], health_payload)
    _write_json(paths["replay_failure_report"], failure_payload)
    _write_json(paths["data_gap_report"], {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    _write_json(paths["no_future_leakage_checks"], leakage)
    _write_json(paths["generated_ledger_manifest"], manifest)
    _write_json(paths["next_research_recommendation"], recommendation)
    return {
        "status": paths["status"],
        "summary": paths["summary"],
        "report": paths["report"],
    }


def write_broad_historical_structural_replay(
    config: BroadHistoricalStructuralReplayConfig,
) -> dict[str, Path]:
    paths = _artifact_paths(config)
    package_root = config.package_root
    paths["root"].mkdir(parents=True, exist_ok=True)
    _write_json(
        paths["status"],
        {
            "state": "running",
            "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
            **RESEARCH_ONLY_FLAGS,
        },
    )

    config_path = config.config_path or (package_root / "config" / "structural_compounding_settings.json")
    base_cfg = StructuralLabConfig.load(config_path)
    adapter = StructuralDataAdapter(base_cfg)
    symbol = str(config.symbol or base_cfg.get("symbol") or "BTCUSDT").upper()

    resolved_source = Path(config.source_history_path).expanduser().resolve() if config.source_history_path else adapter.resolve_history_file(symbol)
    if not resolved_source.exists():
        return _write_insufficient_outputs(
            config,
            status_state="insufficient_data",
            warnings=[f"source_history_missing:{resolved_source}"],
            source_path=resolved_source,
        )

    raw_frame, cleaned_frame, duplicate_count = _load_source_frame(resolved_source)
    if cleaned_frame.empty:
        return _write_insufficient_outputs(
            config,
            status_state="insufficient_data",
            warnings=["source_history_empty_after_cleaning"],
            source_path=resolved_source,
        )

    source_start = pd.Timestamp(cleaned_frame.index.min()).tz_localize(None) if getattr(cleaned_frame.index.min(), "tzinfo", None) else pd.Timestamp(cleaned_frame.index.min())
    source_end = pd.Timestamp(cleaned_frame.index.max()).tz_localize(None) if getattr(cleaned_frame.index.max(), "tzinfo", None) else pd.Timestamp(cleaned_frame.index.max())
    resolved_end = source_end.normalize()
    if source_start > TARGET_START:
        source_coverage = {
            **RESEARCH_ONLY_FLAGS,
            "symbol_used": symbol,
            "base_timeframe_used": str(base_cfg.require("data", "default_interval")),
            "source_path": str(resolved_source),
            "requested_start": TARGET_START.isoformat(),
            "requested_end": resolved_end.isoformat(),
            "source_data_start": source_start.isoformat(),
            "source_data_end": source_end.isoformat(),
            "raw_rows": int(len(raw_frame)),
            "cleaned_rows": int(len(cleaned_frame)),
            "duplicate_timestamp_count": int(duplicate_count),
            "missing_timestamp_count": int(_count_missing_minutes(pd.DatetimeIndex(cleaned_frame.index))),
            "coverage_sufficient": False,
            "warnings": ["source_does_not_reach_2018_start_boundary"],
        }
        return _write_insufficient_outputs(
            config,
            status_state="insufficient_data",
            warnings=["source_does_not_reach_2018_start_boundary"],
            source_path=resolved_source,
            source_coverage=source_coverage,
        )

    data_settings = dict(base_cfg.get("data", default={}) or {})
    data_base_path = base_cfg.path("data", "base_path")
    runtime_payload = dict(base_cfg.data)
    runtime_payload["data"] = dict(data_settings)
    runtime_payload["data"]["base_path"] = str(data_base_path) if data_base_path is not None else str(resolved_source.parent.parent.parent)
    runtime_payload["data"]["history_start_date"] = TARGET_START.strftime("%Y-%m-%d")
    runtime_payload["data"]["history_end_date"] = resolved_end.strftime("%Y-%m-%d")
    runtime_payload["data"]["analysis_start_date"] = TARGET_START.strftime("%Y-%m-%d")
    runtime_payload["data"]["analysis_end_date"] = resolved_end.strftime("%Y-%m-%d")
    _write_json(paths["runtime_config"], runtime_payload)

    short_window_mtimes = _capture_short_window_mtimes(package_root)
    source_coverage = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol_used": symbol,
        "base_timeframe_used": str(base_cfg.require("data", "default_interval")),
        "source_path": str(resolved_source),
        "requested_start": TARGET_START.isoformat(),
        "requested_end": resolved_end.isoformat(),
        "source_data_start": source_start.isoformat(),
        "source_data_end": source_end.isoformat(),
        "raw_rows": int(len(raw_frame)),
        "cleaned_rows": int(len(cleaned_frame)),
        "duplicate_timestamp_count": int(duplicate_count),
        "missing_timestamp_count": int(_count_missing_minutes(pd.DatetimeIndex(cleaned_frame.index))),
        "coverage_sufficient": True,
    }
    _write_json(paths["source_data_coverage"], source_coverage)

    try:
        runtime_cfg = StructuralLabConfig.load(paths["runtime_config"])
        engine = StructuralBacktestEngine(config=runtime_cfg)
        engine.run(
            symbol=symbol,
            source_csv=str(resolved_source),
            output_dir=str(paths["ledger_root"]),
        )
    except Exception as exc:
        partial_outputs = any((paths["ledger_root"] / filename).exists() for filename in LEDGER_FILES)
        failure_payload = {
            **RESEARCH_ONLY_FLAGS,
            "failed_stage": "engine_run",
            "exception_type": type(exc).__name__,
            "exception_message": str(exc),
            "partial_outputs_written": partial_outputs,
            "last_successful_window": None,
            "next_safe_resume_window": "2018",
            "manual_fix_needed": True,
            "traceback": traceback.format_exc(),
        }
        _write_json(paths["replay_failure_report"], failure_payload)
        return _write_insufficient_outputs(
            config,
            status_state="failed",
            warnings=[f"engine_run_failed:{type(exc).__name__}", str(exc)],
            source_path=resolved_source,
            source_coverage=source_coverage,
            failure_payload=failure_payload,
        )

    ledger_summary = _read_json(paths["ledger_root"] / "summary.json", {})
    trades = _read_csv_rows(paths["ledger_root"] / "trades.csv")
    setups = _read_csv_rows(paths["ledger_root"] / "setup_log.csv")

    year_windows = _year_windows(TARGET_START, resolved_end)
    yearly_rows: list[dict[str, Any]] = []
    monthly_rows = _group_trade_counts(trades, freq="month")
    yearly_trade_counts = _group_trade_counts(trades, freq="year")
    yearly_lookup = {row["period"]: row for row in yearly_trade_counts}

    index = pd.DatetimeIndex(cleaned_frame.index)
    replay_manifest_windows: list[dict[str, Any]] = []
    row_count_by_year: dict[str, int] = {}
    trade_count_by_year: dict[str, int] = {}
    zero_trade_windows: list[str] = []
    for window in year_windows:
        start = pd.Timestamp(window["start_timestamp"])
        end = pd.Timestamp(window["end_timestamp"])
        raw_mask = (raw_frame["timestamp"] >= start) & (raw_frame["timestamp"] <= end)
        clean_mask = (index >= start) & (index <= end)
        year_raw_rows = int(raw_mask.sum())
        year_clean_rows = int(clean_mask.sum())
        year_index = index[clean_mask]
        trade_rows = _rows_for_period(trades, timestamp_keys=("exit_time", "entry_time", "timestamp"), start=start, end=end)
        setup_rows = _rows_for_period(setups, timestamp_keys=("timestamp",), start=start, end=end)
        long_trades = sum(1 for row in trade_rows if str(row.get("side") or "").lower() == "long")
        short_trades = sum(1 for row in trade_rows if str(row.get("side") or "").lower() == "short")
        missing_timestamp_count = _count_missing_minutes(year_index)
        duplicate_timestamp_count = int(raw_frame.loc[raw_mask, "timestamp"].duplicated(keep="last").sum()) if year_raw_rows else 0
        manifest_row = {
            **window,
            "raw_rows": year_raw_rows,
            "bars_after_cleaning": year_clean_rows,
            "setups_detected": len(setup_rows),
            "trades_generated": len(trade_rows),
            "long_trades": long_trades,
            "short_trades": short_trades,
            "failed_rows": max(year_raw_rows - year_clean_rows, 0),
            "missing_timestamp_count": missing_timestamp_count,
            "duplicate_timestamp_count": duplicate_timestamp_count,
            "min_timestamp": pd.Timestamp(year_index.min()).isoformat() if len(year_index) else None,
            "max_timestamp": pd.Timestamp(year_index.max()).isoformat() if len(year_index) else None,
            "status": "completed" if year_clean_rows else "missing_source_rows",
        }
        replay_manifest_windows.append(manifest_row)
        row_count_by_year[window["window_name"]] = year_clean_rows
        trade_count_by_year[window["window_name"]] = len(trade_rows)
        if len(trade_rows) == 0:
            zero_trade_windows.append(window["window_name"])
        yearly_rows.append(
            {
                "period": window["window_name"],
                "trade_count": len(trade_rows),
                "long_trade_count": long_trades,
                "short_trade_count": short_trades,
                "setup_count": len(setup_rows),
            }
        )

    gap_segments = _extract_gap_segments(pd.DatetimeIndex(cleaned_frame.index))
    data_gap_report = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_path": str(resolved_source),
        "total_missing_minutes": int(_count_missing_minutes(pd.DatetimeIndex(cleaned_frame.index))),
        "gap_segment_count": len(gap_segments),
        "largest_gap_minutes": max((segment["missing_minutes"] for segment in gap_segments), default=0),
        "sample_gap_segments": gap_segments[:100],
    }
    _write_json(paths["data_gap_report"], data_gap_report)

    replay_window_manifest = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "symbol_used": symbol,
        "source_path": str(resolved_source),
        "windows": replay_manifest_windows,
    }
    _write_json(paths["replay_window_manifest"], replay_window_manifest)
    _write_csv(paths["yearly_trade_counts"], yearly_rows)
    _write_csv(paths["monthly_trade_counts"], monthly_rows)

    long_trade_count = sum(1 for row in trades if str(row.get("side") or "").lower() == "long")
    short_trade_count = sum(1 for row in trades if str(row.get("side") or "").lower() == "short")
    trade_timestamps = [_trade_timestamp(row) for row in trades]
    trade_timestamps = [stamp for stamp in trade_timestamps if stamp is not None]
    leakage = _build_no_future_checks(config, trades)
    missing_years = [str(year) for year in range(TARGET_START.year, resolved_end.year + 1) if str(year) not in row_count_by_year]
    safe_for_frozen_patch_validation = (
        bool(ledger_summary)
        and ledger_summary.get("run_state") == "completed"
        and source_coverage["coverage_sufficient"]
        and leakage["counts"]["failed"] == 0
    )
    health_payload = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_start": source_start.isoformat(),
        "source_end": source_end.isoformat(),
        "generated_trade_start": min(trade_timestamps).isoformat() if trade_timestamps else None,
        "generated_trade_end": max(trade_timestamps).isoformat() if trade_timestamps else None,
        "generated_trade_years": sorted({stamp.year for stamp in trade_timestamps}),
        "generated_trade_count": len(trades),
        "long_trade_count": long_trade_count,
        "short_trade_count": short_trade_count,
        "zero_trade_windows": zero_trade_windows,
        "missing_years": missing_years,
        "row_count_by_year": row_count_by_year,
        "trade_count_by_year": trade_count_by_year,
        "successful_replay": ledger_summary.get("run_state") == "completed",
        "safe_for_frozen_patch_validation": safe_for_frozen_patch_validation,
        "warnings": (
            [f"zero_trade_windows:{','.join(zero_trade_windows)}"] if zero_trade_windows else []
        ),
    }
    _write_json(paths["replay_health_report"], health_payload)
    _write_json(
        paths["replay_failure_report"],
        {
            **RESEARCH_ONLY_FLAGS,
            "failed_stage": None,
            "exception_type": None,
            "exception_message": None,
            "partial_outputs_written": False,
            "last_successful_window": replay_manifest_windows[-1]["window_name"] if replay_manifest_windows else None,
            "next_safe_resume_window": None,
            "manual_fix_needed": False,
        },
    )
    _write_json(paths["no_future_leakage_checks"], leakage)

    ledger_manifest = _generated_ledger_manifest(paths)
    ledger_manifest["current_short_window_artifacts_untouched"] = _short_window_untouched(package_root, short_window_mtimes)
    ledger_manifest["broad_replay_isolated"] = True
    _write_json(paths["generated_ledger_manifest"], ledger_manifest)

    summary_payload = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_data_start": source_start.isoformat(),
        "source_data_end": source_end.isoformat(),
        "generated_ledger_start": ledger_summary.get("run_context", {}).get("loaded_history_start"),
        "generated_ledger_end": ledger_summary.get("run_context", {}).get("loaded_history_end"),
        "years_generated": [window["window_name"] for window in replay_manifest_windows if window["bars_after_cleaning"] > 0],
        "trade_count": len(trades),
        "long_trade_count": long_trade_count,
        "short_trade_count": short_trade_count,
        "coverage_sufficient_for_frozen_patch_validation": safe_for_frozen_patch_validation,
        "ledger_output_path": str(paths["ledger_root"]),
        "next_required_step": "APPLY_FROZEN_PATCH_TO_BROAD_HISTORICAL_LEDGER",
    }
    _write_json(paths["summary"], summary_payload)

    recommendation = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "next_step": "APPLY_FROZEN_PATCH_TO_BROAD_HISTORICAL_LEDGER",
        "reason": "Broad structural ledger now exists in an isolated path and is ready for unchanged frozen-patch validation.",
    }
    _write_json(paths["next_research_recommendation"], recommendation)
    _write_markdown(paths["report"], _report_markdown(summary_payload, health_payload, source_coverage, leakage))
    _write_json(
        paths["status"],
        {
            "state": "complete",
            "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
            **RESEARCH_ONLY_FLAGS,
            "symbol_used": symbol,
            "source_path": str(resolved_source),
            "ledger_output_path": str(paths["ledger_root"]),
        },
    )
    return {
        "status": paths["status"],
        "summary": paths["summary"],
        "report": paths["report"],
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    result = write_broad_historical_structural_replay(
        BroadHistoricalStructuralReplayConfig(
            package_root=package_root,
            output_root=package_root / "output" / "broad_historical_structural_replay_001",
        )
    )
    print(result["summary"])


if __name__ == "__main__":
    main()
