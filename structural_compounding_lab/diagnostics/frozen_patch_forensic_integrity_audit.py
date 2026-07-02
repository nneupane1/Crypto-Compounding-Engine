from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.frozen_patch_validation_audit import (  # noqa: E402
    TARGET_YEARS,
)
from structural_compounding_lab.diagnostics.long_damage_control_patch_audit import (  # noqa: E402
    BAD_LONG_DISABLE_SET,
    _prepare_rows,
    _proven_short_archetypes,
)
from structural_compounding_lab.diagnostics.long_short_edge_repair_audit import (  # noqa: E402
    _normalize_trade_rows,
    _read_csv_rows,
    _read_json,
    _timestamp,
    _write_json,
    _write_markdown,
)


RESEARCH_ONLY_FLAGS = {
    "research_only": True,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
}

_FILE_RANGE_PATTERN = re.compile(
    r"_(?P<start>\d{4}-\d{2}-\d{2}(?:T\d{2}\.\d{2}\.\d{2})?)_to_(?P<end>\d{4}-\d{2}-\d{2}(?:T\d{2}\.\d{2}\.\d{2})?)$"
)


@dataclass(frozen=True)
class FrozenPatchForensicIntegrityAuditConfig:
    package_root: Path
    output_root: Path


def _artifact_paths(config: FrozenPatchForensicIntegrityAuditConfig) -> dict[str, Path]:
    source_root = config.package_root / "output"
    long_short_root = source_root / "long_short_edge_repair_audit_001"
    long_damage_root = source_root / "long_damage_control_patch_audit_001"
    frozen_validation_root = source_root / "frozen_patch_validation_audit_001"
    five_year_root = source_root / "five_year_compounding_audit_001"
    daily_refinement_root = source_root / "daily_opportunity_definition_refinement_001"
    daily_structural_root = source_root / "daily_structural_opportunity_001"
    config_root = config.package_root / "config"
    output_root = config.output_root
    return {
        "summary": source_root / "summary.json",
        "report": source_root / "report.md",
        "trades": source_root / "trades.csv",
        "setup_log": source_root / "setup_log.csv",
        "equity": source_root / "equity.csv",
        "level_log": source_root / "level_log.csv",
        "liquidity_events": source_root / "liquidity_events.csv",
        "cooldown_log": source_root / "cooldown_log.csv",
        "pyramiding_log": source_root / "pyramiding_log.csv",
        "profit_vault": source_root / "profit_vault.json",
        "btc_6m_source": source_root / "btcusdt_6m_1m_2025-12-13_to_2026-06-13.csv",
        "long_short_status": long_short_root / "status.json",
        "long_short_summary": long_short_root / "long_short_edge_repair_summary.json",
        "long_short_recommendation": long_short_root / "diagnostics" / "edge_repair_recommendation.json",
        "long_short_archetypes": long_short_root / "diagnostics" / "archetype_expectancy_breakdown.csv",
        "long_damage_status": long_damage_root / "status.json",
        "long_damage_summary": long_damage_root / "long_damage_control_patch_summary.json",
        "long_damage_best_candidate": long_damage_root / "diagnostics" / "best_patch_candidate.json",
        "long_damage_variant_summary": long_damage_root / "diagnostics" / "patch_variant_summary.csv",
        "frozen_validation_status": frozen_validation_root / "status.json",
        "frozen_validation_summary": frozen_validation_root / "frozen_patch_validation_summary.json",
        "frozen_validation_report": frozen_validation_root / "frozen_patch_validation_report.md",
        "frozen_validation_rules": frozen_validation_root / "diagnostics" / "frozen_patch_rules.json",
        "frozen_validation_year_by_year": frozen_validation_root / "diagnostics" / "year_by_year_validation.csv",
        "frozen_validation_windows": frozen_validation_root / "diagnostics" / "validation_window_summary.csv",
        "frozen_validation_walk_forward": frozen_validation_root / "diagnostics" / "walk_forward_validation.csv",
        "frozen_validation_promotion_gate": frozen_validation_root / "diagnostics" / "promotion_gate_report.json",
        "five_year_summary": five_year_root / "five_year_compounding_summary.json",
        "daily_refinement_summary": daily_refinement_root / "definition_refinement_summary.json",
        "daily_structural_summary": daily_structural_root / "daily_structural_opportunity_summary.json",
        "settings_json": config_root / "structural_compounding_settings.json",
        "settings_yaml": config_root / "structural_compounding_settings.yaml",
        "symbols_json": config_root / "symbols.json",
        "validation_ladder": config_root / "validation_ladder.json",
        "data_adapter": config.package_root / "data" / "data_adapter.py",
        "legacy_data_adapter": config.package_root / "data_adapter.py",
        "status": output_root / "status.json",
        "summary_out": output_root / "forensic_integrity_summary.json",
        "report_out": output_root / "forensic_integrity_report.md",
        "artifact_lineage_out": output_root / "diagnostics" / "artifact_lineage_report.json",
        "data_coverage_out": output_root / "diagnostics" / "data_coverage_report.json",
        "sample_reuse_out": output_root / "diagnostics" / "sample_reuse_report.json",
        "leakage_risk_out": output_root / "diagnostics" / "leakage_risk_report.json",
        "frozen_rule_origin_out": output_root / "diagnostics" / "frozen_rule_origin_report.json",
        "source_history_availability_out": output_root / "diagnostics" / "source_history_availability_report.json",
        "validation_gap_out": output_root / "diagnostics" / "validation_gap_report.json",
        "required_next_replay_plan_out": output_root / "diagnostics" / "required_next_replay_plan.json",
        "no_go_risks_out": output_root / "diagnostics" / "no_go_risks.json",
        "next_research_recommendation_out": output_root / "reports" / "next_research_recommendation.json",
    }


def _to_iso(value: Any) -> str | None:
    timestamp = _timestamp(value)
    if timestamp is None:
        return None
    return timestamp.isoformat()


def _artifact_symbols(rows: list[dict[str, Any]]) -> list[str]:
    symbols = sorted({str(row.get("symbol") or "").upper() for row in rows if str(row.get("symbol") or "").strip()})
    return [symbol for symbol in symbols if symbol]


def _artifact_timeframe(rows: list[dict[str, Any]], path: Path) -> str | None:
    for key in ("execution_timeframe", "timeframe", "timeframe_source", "source_timeframe", "execution_frame"):
        values = sorted({str(row.get(key) or "").strip() for row in rows if str(row.get(key) or "").strip()})
        if len(values) == 1:
            return values[0]
        if len(values) > 1:
            return "mixed"
    match = re.search(r"_(1m|3m|5m|15m|1h|4h|12h|1d|1w)_", path.name, flags=re.IGNORECASE)
    return match.group(1) if match else None


def _row_timestamp_values(rows: list[dict[str, Any]], timestamp_keys: tuple[str, ...]) -> list[pd.Timestamp]:
    timestamps: list[pd.Timestamp] = []
    for row in rows:
        for key in timestamp_keys:
            ts = _timestamp(row.get(key))
            if ts is not None:
                timestamps.append(ts)
                break
    return timestamps


def _parse_file_range_from_name(path: Path) -> tuple[str | None, str | None]:
    match = _FILE_RANGE_PATTERN.search(path.stem)
    if not match:
        return None, None
    start_text = match.group("start").replace("T", " ").replace(".", ":")
    end_text = match.group("end").replace("T", " ").replace(".", ":")
    return _to_iso(start_text), _to_iso(end_text)


def _created_by_module(name: str) -> str | None:
    mapping = {
        "trades.csv": "structural_compounding_lab.backtest.engine.StructuralBacktestEngine",
        "setup_log.csv": "structural_compounding_lab.backtest.engine.StructuralBacktestEngine",
        "equity.csv": "structural_compounding_lab.backtest.engine.StructuralBacktestEngine",
        "level_log.csv": "structural_compounding_lab.market_structure",
        "liquidity_events.csv": "structural_compounding_lab.market_structure",
        "long_short_edge_repair_summary.json": "structural_compounding_lab.diagnostics.long_short_edge_repair_audit",
        "long_damage_control_patch_summary.json": "structural_compounding_lab.diagnostics.long_damage_control_patch_audit",
        "frozen_patch_validation_summary.json": "structural_compounding_lab.diagnostics.frozen_patch_validation_audit",
    }
    return mapping.get(name)


def _artifact_entry(
    *,
    artifact_path: Path,
    rows: list[dict[str, Any]] | None,
    json_payload: Any = None,
    timestamp_keys: tuple[str, ...] = ("timestamp",),
    notes: list[str] | None = None,
    used_for_patch_discovery: bool = False,
    used_for_patch_validation: bool = False,
    same_sample_as_discovery: bool = False,
    input_source_if_detectable: str | None = None,
) -> dict[str, Any]:
    notes = list(notes or [])
    exists = artifact_path.exists()
    row_count: int | None = None
    min_timestamp: str | None = None
    max_timestamp: str | None = None
    symbols: list[str] = []
    if rows is not None:
        row_count = len(rows)
        timestamps = _row_timestamp_values(rows, timestamp_keys)
        if timestamps:
            min_timestamp = min(timestamps).isoformat()
            max_timestamp = max(timestamps).isoformat()
        symbols = _artifact_symbols(rows)
    elif isinstance(json_payload, dict):
        for count_key in ("trade_count", "setup_count", "level_count", "liquidity_event_count", "row_count"):
            if count_key in json_payload:
                try:
                    row_count = int(json_payload.get(count_key) or 0)
                    break
                except (TypeError, ValueError):
                    pass
        for key in ("replay_checkpoint_timestamp", "resolved_at_utc"):
            if key in json_payload:
                value = _to_iso(json_payload.get(key))
                if value and min_timestamp is None:
                    min_timestamp = value
                if value:
                    max_timestamp = value
        symbol_value = str(json_payload.get("symbol") or "").upper()
        if symbol_value:
            symbols = [symbol_value]

    timeframe = _artifact_timeframe(rows or [], artifact_path) if rows is not None else None
    return {
        "artifact_path": str(artifact_path),
        "exists": exists,
        "row_count": row_count,
        "min_timestamp": min_timestamp,
        "max_timestamp": max_timestamp,
        "symbol_count": len(symbols),
        "symbols": symbols,
        "timeframe_if_detectable": timeframe,
        "created_by_module_if_detectable": _created_by_module(artifact_path.name),
        "input_source_if_detectable": input_source_if_detectable,
        "used_for_patch_discovery": used_for_patch_discovery,
        "used_for_patch_validation": used_for_patch_validation,
        "same_sample_as_discovery": same_sample_as_discovery,
        "notes": notes,
    }


def _settings_data(paths: dict[str, Path]) -> dict[str, Any]:
    return _read_json(paths["settings_json"], {})


def _resolved_data_base_path(package_root: Path, settings_data: dict[str, Any]) -> Path | None:
    data_block = settings_data.get("data", {}) if isinstance(settings_data.get("data"), dict) else {}
    raw_path = data_block.get("base_path", "../data_storage")
    if raw_path in (None, ""):
        return None
    path = Path(str(raw_path))
    if path.is_absolute():
        return path
    return (package_root / path).resolve()


def _source_history_rows(package_root: Path, settings_data: dict[str, Any]) -> list[dict[str, Any]]:
    base_path = _resolved_data_base_path(package_root, settings_data)
    if base_path is None:
        return []
    rows: list[dict[str, Any]] = []
    for candidate in base_path.rglob("BTC*.csv"):
        if not candidate.is_file():
            continue
        if "live_runtime" in candidate.name.lower():
            continue
        start_iso, end_iso = _parse_file_range_from_name(candidate)
        repo_root = package_root.parent
        relative = candidate.relative_to(repo_root) if candidate.is_relative_to(repo_root) else candidate
        parts = candidate.parts
        timeframe = None
        symbol = None
        if len(parts) >= 2:
            try:
                symbol_index = parts.index("data_storage") + 1
                symbol = parts[symbol_index]
                timeframe = parts[symbol_index + 1] if len(parts) > symbol_index + 1 else None
            except ValueError:
                symbol = None
        rows.append(
            {
                "path": str(relative),
                "symbol": symbol,
                "timeframe": timeframe,
                "start_timestamp": start_iso,
                "end_timestamp": end_iso,
            }
        )
    rows.sort(key=lambda item: (str(item.get("symbol") or ""), str(item.get("timeframe") or ""), str(item.get("path") or "")))
    return rows


def _years_from_range(start_iso: str | None, end_iso: str | None) -> list[int]:
    if start_iso is None or end_iso is None:
        return []
    start_ts = _timestamp(start_iso)
    end_ts = _timestamp(end_iso)
    if start_ts is None or end_ts is None:
        return []
    return list(range(start_ts.year, end_ts.year + 1))


def _history_year_flags(years: list[int]) -> dict[str, bool]:
    available = set(years)
    return {f"has_{year}_data": year in available for year in TARGET_YEARS}


def _proof_status_flags(*, raw_source_sufficient: bool, same_sample: bool, true_unseen: bool, trade_years: list[int]) -> list[str]:
    flags = ["CURRENT_SAMPLE_REPLAY_ONLY", "RETROSPECTIVE_PATCH_VALIDATION"]
    if len(trade_years) < len(TARGET_YEARS):
        flags.append("PARTIAL_YEAR_VALIDATION")
    elif raw_source_sufficient:
        flags.append("MULTI_YEAR_VALIDATION_AVAILABLE")
    if true_unseen:
        flags.append("TRUE_UNSEEN_WALK_FORWARD_AVAILABLE")
    return flags


def _write_empty_outputs(config: FrozenPatchForensicIntegrityAuditConfig, *, warnings: list[str]) -> dict[str, Path]:
    paths = _artifact_paths(config)
    status = {
        "state": "empty",
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        **RESEARCH_ONLY_FLAGS,
        "warnings": warnings,
    }
    summary = {
        **RESEARCH_ONLY_FLAGS,
        "warnings": warnings,
        "current_proof_status": ["CURRENT_SAMPLE_REPLAY_ONLY"],
        "current_proof_status_label": "CURRENT_SAMPLE_REPLAY_ONLY",
        "true_unseen_proof_available": False,
        "sample_reuse_risk": "HIGH",
        "leakage_overfit_risk": "HIGH",
        "promotion_blocker_count": len(warnings),
    }
    report = "# Frozen Patch Forensic Validation Integrity Audit\n\nNo usable artifacts were available for forensic validation integrity review.\n"
    _write_json(paths["status"], status)
    _write_json(paths["summary_out"], summary)
    _write_markdown(paths["report_out"], report)
    for output_key in (
        "artifact_lineage_out",
        "data_coverage_out",
        "sample_reuse_out",
        "leakage_risk_out",
        "frozen_rule_origin_out",
        "source_history_availability_out",
        "validation_gap_out",
        "required_next_replay_plan_out",
        "no_go_risks_out",
        "next_research_recommendation_out",
    ):
        _write_json(paths[output_key], {"warnings": warnings, **RESEARCH_ONLY_FLAGS})
    return {
        "status": paths["status"],
        "summary": paths["summary_out"],
        "report": paths["report_out"],
    }


def write_frozen_patch_forensic_integrity_audit(
    config: FrozenPatchForensicIntegrityAuditConfig,
) -> dict[str, Path]:
    paths = _artifact_paths(config)
    settings = _settings_data(paths)
    summary = _read_json(paths["summary"], {})
    trades = _read_csv_rows(paths["trades"])
    setups = _read_csv_rows(paths["setup_log"])
    equity_rows = _read_csv_rows(paths["equity"])
    level_rows = _read_csv_rows(paths["level_log"])
    liquidity_rows = _read_csv_rows(paths["liquidity_events"])
    cooldown_rows = _read_csv_rows(paths["cooldown_log"])
    pyramiding_rows = _read_csv_rows(paths["pyramiding_log"])
    long_short_summary = _read_json(paths["long_short_summary"], {})
    long_short_recommendation = _read_json(paths["long_short_recommendation"], {})
    long_short_archetypes = _read_csv_rows(paths["long_short_archetypes"])
    long_damage_summary = _read_json(paths["long_damage_summary"], {})
    long_damage_best_candidate = _read_json(paths["long_damage_best_candidate"], {})
    long_damage_variant_summary = _read_csv_rows(paths["long_damage_variant_summary"])
    frozen_validation_summary = _read_json(paths["frozen_validation_summary"], {})
    frozen_validation_status = _read_json(paths["frozen_validation_status"], {})
    frozen_validation_rules = _read_json(paths["frozen_validation_rules"], {})
    frozen_validation_years = _read_csv_rows(paths["frozen_validation_year_by_year"])
    frozen_validation_windows = _read_csv_rows(paths["frozen_validation_windows"])
    frozen_validation_walk_forward = _read_csv_rows(paths["frozen_validation_walk_forward"])
    frozen_validation_promotion_gate = _read_json(paths["frozen_validation_promotion_gate"], {})
    five_year_summary = _read_json(paths["five_year_summary"], {})
    daily_refinement_summary = _read_json(paths["daily_refinement_summary"], {})
    daily_structural_summary = _read_json(paths["daily_structural_summary"], {})

    if not trades:
        return _write_empty_outputs(config, warnings=["no_structural_trades_available_for_forensic_integrity_audit"])

    trade_entry_times = _row_timestamp_values(trades, ("entry_time", "opened_at", "entry_timestamp", "timestamp"))
    trade_exit_times = _row_timestamp_values(trades, ("exit_time", "closed_at", "exit_timestamp", "timestamp"))
    trade_start = min(trade_entry_times).isoformat() if trade_entry_times else None
    trade_end = max(trade_exit_times or trade_entry_times).isoformat() if (trade_exit_times or trade_entry_times) else None
    trade_years = sorted({ts.year for ts in (trade_exit_times or trade_entry_times)})
    trade_months = sorted({ts.strftime("%Y-%m") for ts in (trade_exit_times or trade_entry_times)})
    unique_trade_days = sorted({ts.strftime("%Y-%m-%d") for ts in (trade_exit_times or trade_entry_times)})
    calendar_days_covered = 0
    if trade_start and trade_end:
        trade_start_ts = _timestamp(trade_start)
        trade_end_ts = _timestamp(trade_end)
        if trade_start_ts is not None and trade_end_ts is not None:
            calendar_days_covered = int((trade_end_ts.normalize() - trade_start_ts.normalize()).days) + 1

    source_history = _source_history_rows(config.package_root, settings)
    source_ranges = [
        (_timestamp(item["start_timestamp"]), _timestamp(item["end_timestamp"]), item)
        for item in source_history
        if item.get("start_timestamp") and item.get("end_timestamp")
    ]
    source_starts = [item[0] for item in source_ranges if item[0] is not None]
    source_ends = [item[1] for item in source_ranges if item[1] is not None]
    source_years = sorted({year for start, end, _ in source_ranges for year in _years_from_range(start.isoformat() if start is not None else None, end.isoformat() if end is not None else None)})
    earliest_source_timestamp = min(source_starts).isoformat() if source_starts else None
    latest_source_timestamp = max(source_ends).isoformat() if source_ends else None
    source_year_flags = _history_year_flags(source_years)

    likely_6m_source = paths["btc_6m_source"] if paths["btc_6m_source"].exists() else None
    likely_source_note = []
    if likely_6m_source is not None:
        likely_source_note.append("structural output folder contains a dedicated 6m BTC 1m source file")
    if trade_start == "2025-12-14T02:00:00" and trade_end == "2026-06-13T00:00:00":
        likely_source_note.append("trade ledger date range tightly matches the trailing 6m BTC structural source span")
    explicit_source_lineage = "source_csv" in summary or "source_path" in summary
    inferred_source_path = str(likely_6m_source) if likely_6m_source is not None else None

    lineage_entries = {
        "trades_csv": _artifact_entry(
            artifact_path=paths["trades"],
            rows=trades,
            timestamp_keys=("entry_time", "exit_time", "timestamp"),
            notes=[
                "primary structural trade ledger",
                "consumed by long/short edge repair, long damage control patch, and frozen patch validation audits",
                *likely_source_note,
            ],
            used_for_patch_discovery=True,
            used_for_patch_validation=True,
            same_sample_as_discovery=True,
            input_source_if_detectable=inferred_source_path,
        ),
        "setup_log_csv": _artifact_entry(
            artifact_path=paths["setup_log"],
            rows=setups,
            timestamp_keys=("timestamp", "setup_time"),
            notes=["setup explanation ledger reused across downstream research audits"],
            used_for_patch_discovery=True,
            used_for_patch_validation=True,
            same_sample_as_discovery=True,
            input_source_if_detectable=inferred_source_path,
        ),
        "equity_csv": _artifact_entry(
            artifact_path=paths["equity"],
            rows=equity_rows,
            timestamp_keys=("timestamp", "date"),
            notes=["top-level structural equity curve for the same current run"],
            used_for_patch_discovery=False,
            used_for_patch_validation=False,
            same_sample_as_discovery=True,
            input_source_if_detectable=inferred_source_path,
        ),
        "level_log_csv": _artifact_entry(
            artifact_path=paths["level_log"],
            rows=level_rows,
            timestamp_keys=("timestamp", "first_seen", "last_touched"),
            notes=["structure reference ledger produced by the same structural backtest run"],
            used_for_patch_discovery=True,
            used_for_patch_validation=True,
            same_sample_as_discovery=True,
            input_source_if_detectable=inferred_source_path,
        ),
        "liquidity_events_csv": _artifact_entry(
            artifact_path=paths["liquidity_events"],
            rows=liquidity_rows,
            timestamp_keys=("timestamp", "event_time"),
            notes=["liquidity event ledger produced by the same structural backtest run"],
            used_for_patch_discovery=True,
            used_for_patch_validation=True,
            same_sample_as_discovery=True,
            input_source_if_detectable=inferred_source_path,
        ),
        "long_short_edge_repair_summary": _artifact_entry(
            artifact_path=paths["long_short_summary"],
            rows=None,
            json_payload=long_short_summary,
            notes=[
                "patch discovery source audit",
                "derived from trades.csv, setup_log.csv, level_log.csv, liquidity_events.csv",
            ],
            used_for_patch_discovery=True,
            used_for_patch_validation=False,
            same_sample_as_discovery=True,
            input_source_if_detectable=str(paths["trades"]),
        ),
        "long_damage_control_patch_summary": _artifact_entry(
            artifact_path=paths["long_damage_summary"],
            rows=None,
            json_payload=long_damage_summary,
            notes=[
                "selected frozen candidate source audit",
                "variant selection performed on the same structural trade ledger",
            ],
            used_for_patch_discovery=True,
            used_for_patch_validation=True,
            same_sample_as_discovery=True,
            input_source_if_detectable=str(paths["trades"]),
        ),
        "frozen_patch_validation_summary": _artifact_entry(
            artifact_path=paths["frozen_validation_summary"],
            rows=None,
            json_payload=frozen_validation_summary,
            notes=[
                "validation was applied retrospectively to previously generated structural trades",
                "summary already declares retrospective_validation_only=true and true_unseen_proof_available=false",
            ],
            used_for_patch_discovery=False,
            used_for_patch_validation=True,
            same_sample_as_discovery=True,
            input_source_if_detectable=str(paths["trades"]),
        ),
    }

    same_sample_validation = True
    validation_only_replay_over_existing_trades = True
    truly_unseen_trade_sequence_used = False
    artifact_lineage_report = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "artifacts": lineage_entries,
        "same_trade_artifact_used_for_discovery_and_validation": same_sample_validation,
        "frozen_validation_only_replayed_previously_generated_trades": validation_only_replay_over_existing_trades,
        "truly_unseen_trade_sequence_used": truly_unseen_trade_sequence_used,
        "explicit_source_lineage_recorded_in_summary": explicit_source_lineage,
        "likely_structural_source_path": inferred_source_path,
        "lineage_confidence": "HIGH" if inferred_source_path else "MODERATE",
        "notes": [
            "Long/short edge repair, long damage control patch, and frozen patch validation all read from the same top-level structural trade ledger.",
            "Frozen validation windows collapse onto the currently generated 2025-2026 trade sample rather than an independently regenerated multi-year trade sequence.",
        ],
    }

    raw_source_history_sufficient = bool(source_years and min(source_years) <= 2018 and max(source_years) >= 2026)
    coverage_is_sufficient_for_multi_year_validation = False
    data_coverage_report = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "available_trade_start": trade_start,
        "available_trade_end": trade_end,
        "available_trade_years": trade_years,
        "available_trade_months": trade_months,
        "calendar_days_covered": calendar_days_covered,
        "trade_days_covered": len(unique_trade_days),
        "zero_trade_days_covered": max(calendar_days_covered - len(unique_trade_days), 0),
        "available_source_files": [item["path"] for item in source_history],
        "source_file_min_timestamp": earliest_source_timestamp,
        "source_file_max_timestamp": latest_source_timestamp,
        "source_file_years": source_years,
        **source_year_flags,
        "raw_source_history_sufficient_to_regenerate": raw_source_history_sufficient,
        "coverage_is_sufficient_for_multi_year_validation": coverage_is_sufficient_for_multi_year_validation,
        "coverage_gap_reason": (
            "Raw BTC source history appears available from 2018-2026, but the currently generated structural trade artifacts only cover 2025-12-14 through 2026-06-13. "
            "True multi-year proof requires regenerating structural outputs over the broader raw BTC source span."
        ),
    }

    validation_window_metrics = [
        (
            row.get("trade_count"),
            row.get("total_R"),
            row.get("profit_factor"),
            row.get("ending_capital_from_20000"),
        )
        for row in frozen_validation_windows
    ]
    unique_window_metric_tuples = {tuple(item) for item in validation_window_metrics}
    validation_windows_collapse = len(unique_window_metric_tuples) <= 1 and bool(validation_window_metrics)
    walk_forward_genuinely_unseen = False
    sample_reuse_report = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "patch_discovery_window": {
            "trade_artifact_start": trade_start,
            "trade_artifact_end": trade_end,
            "trade_years": trade_years,
        },
        "frozen_validation_window_rows": frozen_validation_windows,
        "patch_discovery_window_equals_frozen_validation_window": same_sample_validation,
        "same_trades_used_for_long_short_edge_repair_and_patch_validation": True,
        "same_archetype_statistics_used_to_select_and_validate_patch": True,
        "frozen_patch_was_tested_on_unseen_windows": False,
        "walk_forward_result_used_genuinely_unseen_trade_windows": walk_forward_genuinely_unseen,
        "current_validation_is_retrospective_only": bool(frozen_validation_summary.get("retrospective_validation_only", True)),
        "validation_windows_effectively_collapse_to_same_available_sample": validation_windows_collapse,
        "notes": [
            "The frozen candidate was selected from long/short and patch diagnostics built on the same top-level trade ledger.",
            "The frozen validation report itself already states true_unseen_proof_available=false.",
            "Window names differ, but the available trade sequence is still the same limited 2025-2026 ledger.",
        ],
    }

    leakage_level = "HIGH"
    if not same_sample_validation and walk_forward_genuinely_unseen and raw_source_history_sufficient:
        leakage_level = "LOW"
    elif not same_sample_validation:
        leakage_level = "MODERATE"
    elif not explicit_source_lineage and validation_windows_collapse:
        leakage_level = "HIGH"
    leakage_risk_report = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "risk_level": leakage_level,
        "true_unseen_proof_available": bool(frozen_validation_summary.get("true_unseen_proof_available", False)),
        "retrospective_validation_only": bool(frozen_validation_summary.get("retrospective_validation_only", True)),
        "same_sample_validation": same_sample_validation,
        "same_archetype_statistics_reused": True,
        "validation_windows_effectively_independent": not validation_windows_collapse,
        "walk_forward_genuinely_unseen": walk_forward_genuinely_unseen,
        "broad_raw_data_available_but_not_replayed": raw_source_history_sufficient and trade_years != TARGET_YEARS,
        "rationale": [
            "The rule was discovered and validated on artifacts derived from the same current structural run.",
            "No independent multi-year structural trade sequence has been generated yet.",
            "Walk-forward labels exist, but they still operate on a ledger built from the same limited source sample.",
        ],
    }

    normalized_rows = _normalize_trade_rows(trades, setups, level_rows, liquidity_rows)
    prepared_rows = _prepare_rows(normalized_rows)
    proven_short_archetypes = sorted(_proven_short_archetypes(prepared_rows))
    all_short_archetypes = sorted({row["archetype_key"] for row in prepared_rows if row.get("side") == "short"})
    long_failure_modes = sorted({str(row.get("long_failure_mode") or "") for row in prepared_rows if str(row.get("side") or "") == "long"})
    long_failure_modes = [mode for mode in long_failure_modes if mode]
    long_buckets_kept = sorted(set(long_failure_modes) - set(BAD_LONG_DISABLE_SET))
    long_buckets_removed = sorted(set(long_failure_modes) & set(BAD_LONG_DISABLE_SET))
    short_buckets_removed = sorted(set(all_short_archetypes) - set(proven_short_archetypes))
    selected_variant_row = next(
        (
            row
            for row in long_damage_variant_summary
            if str(row.get("variant_name") or "") == str(long_damage_best_candidate.get("variant_name") or long_damage_summary.get("best_patch_candidate") or "")
        ),
        {},
    )
    frozen_rule_origin_report = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "selected_variant": str(long_damage_best_candidate.get("variant_name") or long_damage_summary.get("best_patch_candidate") or frozen_validation_summary.get("frozen_patch_candidate") or ""),
        "source_audit": "long_damage_control_patch_audit_001",
        "selection_metric": {
            "best_patch_ending_capital": long_damage_summary.get("best_patch_ending_capital"),
            "best_patch_profit_factor": long_damage_summary.get("best_patch_profit_factor"),
            "best_patch_max_drawdown_pct": long_damage_summary.get("best_patch_max_drawdown_pct"),
            "variant_row": selected_variant_row,
        },
        "rules_kept": [
            "keep shorts only in proven positive archetype buckets",
            "keep longs only when their failure mode is not in BAD_LONG_DISABLE_SET",
        ],
        "rules_removed": [
            "remove long trades from disabled failure-mode buckets",
            "remove short trades outside proven short buckets",
        ],
        "long_buckets_kept": long_buckets_kept,
        "long_buckets_removed": long_buckets_removed,
        "short_buckets_kept": proven_short_archetypes,
        "short_buckets_removed": short_buckets_removed,
        "moonshot_handling": {
            "patch_summary_dependency_label": long_damage_summary.get("moonshot_dependency_after_patch"),
            "validation_dependency_label": frozen_validation_summary.get("moonshot_dependency_in_validation"),
        },
        "was_rule_selected_using_current_sample": True,
        "can_rule_be_applied_without_current_sample_statistics": False,
        "notes": [
            "The frozen rule depends on sample-derived short bucket proof statistics and sample-derived long failure-mode labels.",
            "The rule can be reapplied unchanged, but its original selection logic still came from the current sample.",
        ],
    }

    configured_data_paths = [
        str(path)
        for path in (
            _resolved_data_base_path(config.package_root, settings),
            paths["settings_json"],
            paths["settings_yaml"],
            paths["symbols_json"],
            paths["validation_ladder"],
        )
        if path is not None
    ]
    source_files_by_symbol: dict[str, list[str]] = {}
    source_files_by_timeframe: dict[str, list[str]] = {}
    for item in source_history:
        symbol_key = str(item.get("symbol") or "UNKNOWN")
        timeframe_key = str(item.get("timeframe") or "UNKNOWN")
        source_files_by_symbol.setdefault(symbol_key, []).append(item["path"])
        source_files_by_timeframe.setdefault(timeframe_key, []).append(item["path"])
    source_history_availability_report = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "data_adapter_available": paths["data_adapter"].exists() or paths["legacy_data_adapter"].exists(),
        "configured_data_paths": configured_data_paths,
        "resolved_source_files": [item["path"] for item in source_history],
        "source_files_by_symbol": source_files_by_symbol,
        "source_files_by_timeframe": source_files_by_timeframe,
        "earliest_available_timestamp": earliest_source_timestamp,
        "latest_available_timestamp": latest_source_timestamp,
        "missing_years": [year for year in TARGET_YEARS if year not in source_years],
        "required_download_or_generation_steps": [
            "No BTC download appears necessary if the existing 2018-2026 1m archive is authoritative.",
            "Generate a broad structural replay ledger from the raw BTC source history instead of relying on the current 6m structural artifacts.",
        ],
        "safe_replay_possible_now": raw_source_history_sufficient and (paths["data_adapter"].exists() or paths["legacy_data_adapter"].exists()),
        "estimated_replay_scope": {
            "symbol": settings.get("symbol", "BTCUSDT"),
            "execution_timeframe": settings.get("execution_timeframe", "1h"),
            "confirmation_timeframes": settings.get("confirmation_timeframes", ["12h", "1d", "1w"]),
            "history_start_date": (settings.get("data", {}) if isinstance(settings.get("data"), dict) else {}).get("history_start_date"),
            "history_end_date": (settings.get("data", {}) if isinstance(settings.get("data"), dict) else {}).get("history_end_date"),
        },
    }

    proof_status_flags = _proof_status_flags(
        raw_source_sufficient=raw_source_history_sufficient,
        same_sample=same_sample_validation,
        true_unseen=bool(frozen_validation_summary.get("true_unseen_proof_available", False)),
        trade_years=trade_years,
    )
    what_is_proven = [
        "The frozen patch candidate performs strongly on the currently generated 2025-2026 structural trade ledger.",
        "Within the current sample, the patch is not purely moonshot-dependent and survives the observed full active capital sequence.",
        "The candidate can be reapplied unchanged to the same currently available trade artifacts.",
    ]
    what_is_not_proven = [
        "There is no independently generated multi-year 2018-2026 structural trade sequence under the frozen rules.",
        "There is no truly unseen validation set or genuinely independent walk-forward proof.",
        "The current evidence does not prove the structural compounding lab can support a euro-1M target.",
    ]
    exact_next_artifact = (
        "A broad BTCUSDT structural replay output set covering 2018-01-01 through 2026-06-13 (or latest closed day), "
        "including regenerated trades.csv, setup_log.csv, equity.csv, level_log.csv, liquidity_events.csv, cooldown_log.csv, pyramiding_log.csv, profit_vault.json, and summary.json."
    )
    minimum_next_validation = (
        "Run one frozen-rule-only BTCUSDT broad historical structural replay, then rerun year-by-year, walk-forward, and moonshot robustness audits on the regenerated trade ledger without retuning."
    )
    validation_gap_report = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "current_proof_status": proof_status_flags,
        "what_is_proven": what_is_proven,
        "what_is_not_proven": what_is_not_proven,
        "why_1m_target_is_not_yet_proven": (
            "The current frozen-patch result is still based on a narrow 2025-2026 structural sample with same-sample rule discovery and retrospective validation. "
            "That is promising research evidence, not broad capital-proof evidence."
        ),
        "what_exact_artifact_is_needed_next": exact_next_artifact,
        "minimum_next_validation_needed": minimum_next_validation,
    }

    required_next_replay_plan = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "stage_1_generate_broad_historical_structural_outputs": {
            "purpose": "Generate the missing broad BTC structural trade ledger from raw 1m history rather than the current 6m structural sample.",
            "inputs_needed": [
                "BTCUSDT 1m raw source history covering 2018-01-01 through the latest configured end date",
                "current structural_compounding_settings.json",
                "current structural market-structure backtest engine",
            ],
            "outputs_expected": [
                "broad structural trades.csv",
                "setup_log.csv",
                "equity.csv",
                "level_log.csv",
                "liquidity_events.csv",
                "cooldown_log.csv",
                "pyramiding_log.csv",
                "profit_vault.json",
                "summary.json",
            ],
            "estimated_risk": "medium_runtime_cost",
            "run_command_if_known": "python -m structural_compounding_lab.backtest.run_structural_backtest --symbol BTCUSDT --output-dir output/full_history_btcusdt_2018_2026",
            "do_not_run_automatically": True,
        },
        "stage_2_apply_frozen_patch_without_retuning": {
            "purpose": "Apply the already frozen candidate rules to the regenerated broad trade ledger without altering the patch.",
            "inputs_needed": [
                "broad structural trades.csv",
                "existing BAD_LONGS_DISABLED_ONLY_PROVEN_SHORTS_KEPT rule definition",
            ],
            "outputs_expected": [
                "regenerated frozen patch trade replay",
                "updated frozen patch validation summary",
            ],
            "estimated_risk": "low_logic_risk",
            "run_command_if_known": "python -m structural_compounding_lab.diagnostics.frozen_patch_validation_audit",
            "do_not_run_automatically": True,
        },
        "stage_3_year_by_year_validation": {
            "purpose": "Replace empty 2018-2024 placeholders with real yearly frozen-patch results.",
            "inputs_needed": ["regenerated broad frozen trade ledger"],
            "outputs_expected": ["year_by_year_validation.csv with real yearly windows"],
            "estimated_risk": "low",
            "run_command_if_known": "python -m structural_compounding_lab.diagnostics.frozen_patch_validation_audit",
            "do_not_run_automatically": True,
        },
        "stage_4_walk_forward_validation": {
            "purpose": "Measure the frozen candidate on genuinely later trade windows generated from the broad ledger.",
            "inputs_needed": ["broad frozen trade ledger with multi-year coverage"],
            "outputs_expected": ["walk_forward_validation.csv with materially independent windows"],
            "estimated_risk": "medium_sample_quality_risk",
            "run_command_if_known": "python -m structural_compounding_lab.diagnostics.frozen_patch_validation_audit",
            "do_not_run_automatically": True,
        },
        "stage_5_moonshot_robustness": {
            "purpose": "Confirm the broad-history candidate remains healthy after moonshot stress on regenerated multi-year data.",
            "inputs_needed": ["regenerated broad frozen validation outputs"],
            "outputs_expected": ["updated moonshot dependency diagnostics"],
            "estimated_risk": "low",
            "run_command_if_known": "python -m structural_compounding_lab.diagnostics.frozen_patch_validation_audit",
            "do_not_run_automatically": True,
        },
        "stage_6_paper_candidate_gate": {
            "purpose": "Decide whether the frozen patch deserves a research-only paper candidate classification after broad proof exists.",
            "inputs_needed": [
                "broad year-by-year validation",
                "broad walk-forward validation",
                "moonshot robustness on regenerated data",
            ],
            "outputs_expected": ["new paper-candidate review artifact, if justified"],
            "estimated_risk": "promotion_risk_if_done_early",
            "run_command_if_known": None,
            "do_not_run_automatically": True,
        },
    }

    no_go_blockers = [
        "only_2025_2026_real_trade_coverage",
        "same_sample_validation",
        "true_unseen_proof_available_false",
        "insufficient_yearly_windows",
        "possible_regime_specific_edge",
        "sample_derived_patch_rules",
        "worktree_noisy_unrelated_files_present",
    ]
    if str(frozen_validation_summary.get("moonshot_dependency_in_validation") or "").strip():
        no_go_blockers.append("moonshot_sensitivity_still_requires_broader_confirmation")
    no_go_risks = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "blockers": no_go_blockers,
        "promotion_blocker_count": len(no_go_blockers),
    }

    next_research_recommendation = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "readme_note_recommendation": (
            "Research windows remain discovery and diagnostics only. Proof windows remain multi-year validation and walk-forward. "
            "The current frozen patch is a promising candidate, but it is not yet proven for the euro-1M target. "
            "The next requirement is a broad historical BTC structural replay with the frozen rules applied unchanged."
        ),
        "next_step": "generate_broad_btc_structural_outputs_then_reapply_frozen_patch_without_retuning",
        "do_not_do_yet": [
            "do_not_promote_to_live_or_real_money",
            "do_not_reclassify_as_true_unseen_proof",
            "do_not_tune_the_patch_before_broad_replay",
        ],
    }

    proof_status_label = " / ".join(proof_status_flags)
    summary_out = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": datetime.now(timezone.utc).isoformat(),
        "frozen_patch_candidate": str(
            frozen_validation_summary.get("frozen_patch_candidate")
            or frozen_rule_origin_report["selected_variant"]
        ),
        "current_proof_status": proof_status_flags,
        "current_proof_status_label": proof_status_label,
        "trade_artifact_date_range": {
            "start": trade_start,
            "end": trade_end,
        },
        "available_trade_years": trade_years,
        "available_source_years": source_years,
        "true_unseen_proof_available": bool(frozen_validation_summary.get("true_unseen_proof_available", False)),
        "current_validation_reused_discovery_sample": same_sample_validation,
        "sample_reuse_risk": "HIGH" if same_sample_validation else "LOW",
        "leakage_overfit_risk": leakage_level,
        "raw_source_history_available": raw_source_history_sufficient,
        "coverage_is_sufficient_for_multi_year_validation": coverage_is_sufficient_for_multi_year_validation,
        "next_required_validation": minimum_next_validation,
        "promotion_blockers": no_go_blockers,
        "promotion_blocker_count": len(no_go_blockers),
        "what_is_proven": what_is_proven,
        "what_is_not_proven": what_is_not_proven,
    }

    report = "\n".join(
        [
            "# Frozen Patch Forensic Validation Integrity Audit",
            "",
            "## Current verdict",
            "",
            f"- frozen patch candidate: `{summary_out['frozen_patch_candidate']}`",
            f"- current proof status: `{proof_status_label}`",
            f"- trade artifact range: `{trade_start}` -> `{trade_end}`",
            f"- available trade years with real trades: `{trade_years}`",
            f"- available raw BTC source years: `{source_years}`",
            f"- true unseen proof available: `{summary_out['true_unseen_proof_available']}`",
            f"- sample reuse risk: `{summary_out['sample_reuse_risk']}`",
            f"- leakage / overfit risk: `{summary_out['leakage_overfit_risk']}`",
            "",
            "## What this audit proves",
            "",
            "- The frozen patch result is currently a strong retrospective replay over a narrow structural trade sample.",
            "- The repository appears to contain broader raw BTC history than the trade artifacts currently used by the frozen validation audit.",
            "- The validation gap is therefore mainly a missing replay-generation gap, not obviously a missing raw-data gap.",
            "",
            "## What it does not prove",
            "",
            "- It does not prove true unseen validation.",
            "- It does not prove a broad 2018-2026 structural edge.",
            "- It does not prove readiness for a euro-1M target or promotion beyond research-only paper consideration.",
            "",
            "## Exact next replay required",
            "",
            minimum_next_validation,
            "",
            "## Promotion blockers",
            "",
            *[f"- `{blocker}`" for blocker in no_go_blockers],
            "",
            "No live, paper, runtime, allocator, config, strategy, risk, sizing, entry, or exit behavior was changed by this audit.",
        ]
    ) + "\n"

    status = {
        "state": "complete",
        "resolved_at_utc": summary_out["resolved_at_utc"],
        **RESEARCH_ONLY_FLAGS,
    }

    _write_json(paths["status"], status)
    _write_json(paths["summary_out"], summary_out)
    _write_markdown(paths["report_out"], report)
    _write_json(paths["artifact_lineage_out"], artifact_lineage_report)
    _write_json(paths["data_coverage_out"], data_coverage_report)
    _write_json(paths["sample_reuse_out"], sample_reuse_report)
    _write_json(paths["leakage_risk_out"], leakage_risk_report)
    _write_json(paths["frozen_rule_origin_out"], frozen_rule_origin_report)
    _write_json(paths["source_history_availability_out"], source_history_availability_report)
    _write_json(paths["validation_gap_out"], validation_gap_report)
    _write_json(paths["required_next_replay_plan_out"], required_next_replay_plan)
    _write_json(paths["no_go_risks_out"], no_go_risks)
    _write_json(paths["next_research_recommendation_out"], next_research_recommendation)
    return {
        "status": paths["status"],
        "summary": paths["summary_out"],
        "report": paths["report_out"],
    }


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    package_root = root / "structural_compounding_lab"
    config = FrozenPatchForensicIntegrityAuditConfig(
        package_root=package_root,
        output_root=package_root / "output" / "frozen_patch_forensic_integrity_audit_001",
    )
    result = write_frozen_patch_forensic_integrity_audit(config)
    print(result["summary"])


if __name__ == "__main__":
    main()
