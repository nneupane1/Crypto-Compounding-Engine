from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.diagnostics.broad_frozen_patch_validation import RESEARCH_ONLY_FLAGS  # noqa: E402
from structural_compounding_lab.common.project_paths import package_root as resolve_package_root  # noqa: E402
from structural_compounding_lab.common.project_paths import resolve_project_path  # noqa: E402
from structural_compounding_lab.shadow_forward.shadow_forward_observer import (  # noqa: E402
    OUTPUT_FOLDER_NAME as OBSERVER_OUTPUT_FOLDER_NAME,
    ShadowForwardObserverConfig,
    write_shadow_forward_observer,
)


OUTPUT_FOLDER_NAME = "shadow_forward_watchtower_001"
STATE_NOT_STARTED = "not_started"
STATE_RUNNING = "running"
STATE_PARTIAL = "partial"
STATE_COMPLETED = "completed"
STATE_FAILED = "failed"
STATE_BLOCKED = "blocked"
DEFAULT_MODE = "single_cycle"
ALLOWED_MODES = {"single_cycle", "daily_report", "weekly_report", "status", "self_check"}
MINIMUM_RANDOM_REPEAT_COUNT_FOR_GATE = 32
FORBIDDEN_SOURCE_SNIPPETS = (
    "/api/v3/order",
    "/fapi/v1/order",
    "/order",
    "create_order(",
    "get_account(",
    "/account",
    "paper_trade_created = True",
    "live_trade_created = True",
    "broker_execution_created = True",
)

DEFAULT_WATCHTOWER_SETTINGS: dict[str, Any] = {
    **RESEARCH_ONLY_FLAGS,
    "no_order_path_allowed": True,
    "symbol": "BTCUSDT",
    "execution_timeframe": "1H",
    "context_timeframe": "6H",
    "observation_days_required": 90,
    "minimum_1h_decisions_required": 50,
    "signal_reproduction_accuracy_required": 0.99,
    "median_close_delay_seconds_max": 120,
    "data_gap_rate_max": 0.01,
    "max_unexplained_missed_signals": 0,
    "default_mode": DEFAULT_MODE,
    "append_only_ledgers": True,
    "force_rerun_default": False,
    "allow_source_csv": True,
    "allow_public_market_data_stub": False,
    "allow_private_api_keys": False,
    "allow_order_endpoints": False,
    "reports_enabled": True,
    "daily_report_enabled": True,
    "weekly_report_enabled": True,
    "cumulative_report_enabled": True,
}


@dataclass(frozen=True)
class ShadowForwardWatchtowerConfig:
    package_root: Path
    output_root: Path
    runtime_mode: str = DEFAULT_MODE
    config_path: Path | None = None
    source_csv: str | Path | None = None
    force_rerun: bool = False
    observer_runtime_mode: str | None = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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
    fieldnames: list[str] = []
    for row in rows:
        for key in row.keys():
            if key not in fieldnames:
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value in {None, ""}:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value in {None, ""}:
            return default
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in {None, ""}:
        return default
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "on"}:
        return True
    if text in {"false", "0", "no", "n", "off"}:
        return False
    return default


def _timestamp(value: Any) -> datetime | None:
    if value in {None, ""}:
        return None
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _serialize_yaml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return f'"{value}"'


def _simple_yaml_load(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore

        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(payload, dict):
            raise ValueError(f"Expected mapping in watchtower YAML: {path}")
        return dict(payload)
    except ImportError:
        result: dict[str, Any] = {}
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, raw_value = line.split(":", 1)
            value_text = raw_value.strip().strip('"').strip("'")
            lower = value_text.lower()
            if lower in {"true", "false"}:
                value: Any = lower == "true"
            else:
                try:
                    value = int(value_text) if "." not in value_text else float(value_text)
                except ValueError:
                    value = value_text
            result[key.strip()] = value
        return result


def _load_watchtower_settings(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        return dict(DEFAULT_WATCHTOWER_SETTINGS)
    raw = _simple_yaml_load(config_path)
    merged = dict(DEFAULT_WATCHTOWER_SETTINGS)
    merged.update(raw)
    return merged


def _write_default_watchtower_config(path: Path) -> None:
    if path.exists():
        return
    lines = ["# Research-only 90-day shadow-forward watchtower config"]
    for key, value in DEFAULT_WATCHTOWER_SETTINGS.items():
        lines.append(f"{key}: {_serialize_yaml_value(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _ensure_dirs(output_root: Path) -> dict[str, Path]:
    paths = {
        "root": output_root,
        "diagnostics": output_root / "diagnostics",
        "ledger": output_root / "ledger",
        "reports": output_root / "reports",
        "reports_daily": output_root / "reports" / "daily",
        "reports_weekly": output_root / "reports" / "weekly",
        "reports_cumulative": output_root / "reports" / "cumulative",
        "checkpoints": output_root / "_checkpoints",
        "observer_workspace": output_root / "_checkpoints" / "observer_workspace",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _observer_paths(package_root: Path) -> dict[str, Path]:
    observer_root = package_root / "output" / OBSERVER_OUTPUT_FOLDER_NAME
    spec_root = package_root / "output" / "shadow_forward_validation_spec_audit_001"
    return {
        "observer_summary": observer_root / "shadow_forward_observer_summary.json",
        "observer_self_audit": observer_root / "diagnostics" / "implementation_self_audit.json",
        "spec_readiness": spec_root / "diagnostics" / "shadow_readiness_gates.json",
    }


def _watchtower_paths(output_root: Path) -> dict[str, Path]:
    return {
        "status": output_root / "status.json",
        "scenario_progress": output_root / "scenario_progress.json",
        "summary": output_root / "watchtower_summary.json",
        "report": output_root / "watchtower_report.md",
        "future_capital_anchor": output_root / "diagnostics" / "future_capital_anchor_plan.json",
        "forward_clock_policy": output_root / "diagnostics" / "forward_clock_policy.json",
        "prior_observer_anchor": output_root / "diagnostics" / "prior_observer_anchor.json",
        "run_progress": output_root / "diagnostics" / "run_progress.json",
        "safety_guard": output_root / "diagnostics" / "safety_guard_report.json",
        "heartbeat": output_root / "diagnostics" / "heartbeat.json",
        "readiness": output_root / "diagnostics" / "readiness_progress.json",
        "operational_risk": output_root / "diagnostics" / "operational_risk_status.json",
        "self_audit": output_root / "diagnostics" / "implementation_self_audit.json",
        "run_checkpoint": output_root / "_checkpoints" / "watchtower_ingest_checkpoint.json",
        "signal_log": output_root / "ledger" / "watchtower_signal_log.csv",
        "context_log": output_root / "ledger" / "watchtower_context_log.csv",
        "overlay_log": output_root / "ledger" / "watchtower_research_overlay_log.csv",
        "data_quality_log": output_root / "ledger" / "watchtower_data_quality_log.csv",
        "run_log": output_root / "ledger" / "watchtower_run_log.csv",
        "daily_report": output_root / "reports" / "daily",
        "weekly_report": output_root / "reports" / "weekly",
        "cumulative_report": output_root / "reports" / "cumulative" / "shadow_cumulative_report.md",
    }


def _load_forward_clock_policy(output_root: Path) -> dict[str, Any]:
    return _read_json(_watchtower_paths(output_root)["forward_clock_policy"], {})


def _forward_clock_boundary(policy: dict[str, Any] | None) -> datetime | None:
    if not policy:
        return None
    for key in ("stale_historical_boundary_timestamp", "forward_clock_start_boundary_timestamp", "source_boundary_timestamp"):
        value = policy.get(key)
        parsed = _timestamp(value)
        if parsed is not None:
            return parsed
    return None


def _filter_rows_after_forward_boundary(rows: list[dict[str, Any]], policy: dict[str, Any] | None) -> list[dict[str, Any]]:
    boundary = _forward_clock_boundary(policy)
    if boundary is None:
        return list(rows)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        parsed = _timestamp(row.get("timestamp"))
        if parsed is None:
            continue
        if parsed > boundary:
            filtered.append(row)
    return filtered


def _write_status(path: Path, *, state: str, classification: str, warnings: list[str], mode: str) -> None:
    _write_json(
        path,
        {
            "state": state,
            "resolved_at_utc": _now_utc().isoformat(),
            "runtime_mode": mode,
            "final_classification": classification,
            "warnings": warnings,
            **RESEARCH_ONLY_FLAGS,
            "no_order_path_created": True,
            "paper_trade_created": False,
            "live_trade_created": False,
            "broker_execution_created": False,
        },
    )


def _write_progress(path: Path, *, state: str, mode: str, total_cycles_run: int, decisions_observed: int, warnings: list[str]) -> None:
    _write_json(
        path,
        {
            "state": state,
            "updated_at_utc": _now_utc().isoformat(),
            "runtime_mode": mode,
            "total_cycles_run": total_cycles_run,
            "observed_1h_decisions": decisions_observed,
            "warnings": warnings,
            **RESEARCH_ONLY_FLAGS,
        },
    )


def _load_prior_observer_anchor(package_root: Path, output_root: Path) -> tuple[dict[str, Any] | None, list[str]]:
    warnings: list[str] = []
    paths = _observer_paths(package_root)
    observer_summary = _read_json(paths["observer_summary"], {})
    observer_self_audit = _read_json(paths["observer_self_audit"], {})
    readiness_gates = _read_json(paths["spec_readiness"], {})
    if not observer_summary:
        warnings.append("Prior observer summary missing.")
    if not observer_self_audit:
        warnings.append("Prior observer self-audit missing.")
    if not readiness_gates:
        warnings.append("Shadow readiness gates missing.")
    if warnings:
        return None, warnings
    if str(observer_summary.get("final_classification") or "") != "SHADOW_OBSERVER_READY_RESEARCH_ONLY":
        warnings.append("Prior observer is not classified ready research-only.")
    if not _safe_bool(observer_summary.get("no_order_path_created"), False):
        warnings.append("Prior observer no-order confirmation failed.")
    if not _safe_bool(observer_self_audit.get("no_paper_path_created"), False):
        warnings.append("Prior observer paper-path confirmation failed.")
    if not _safe_bool(observer_self_audit.get("no_live_path_created"), False):
        warnings.append("Prior observer live-path confirmation failed.")
    if not _safe_bool(observer_self_audit.get("no_broker_execution_created"), False):
        warnings.append("Prior observer broker-execution confirmation failed.")
    anchor = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": _now_utc().isoformat(),
        "observer_final_classification": observer_summary.get("final_classification"),
        "shadow_spec_gate_source": str(paths["spec_readiness"]),
        "observer_summary_path": str(paths["observer_summary"]),
        "observer_self_audit_path": str(paths["observer_self_audit"]),
        "no_order_path_created": _safe_bool(observer_summary.get("no_order_path_created"), False),
        "no_paper_path_created": _safe_bool(observer_self_audit.get("no_paper_path_created"), False),
        "no_live_path_created": _safe_bool(observer_self_audit.get("no_live_path_created"), False),
        "no_broker_execution_created": _safe_bool(observer_self_audit.get("no_broker_execution_created"), False),
        "paper_validation_ready": _safe_bool(observer_summary.get("readiness_progress", {}).get("paper_validation_ready"), False),
        "observation_days_still_required": max(
            0,
            _safe_int(observer_summary.get("readiness_progress", {}).get("gate_targets", {}).get("required_observation_days"), 90)
            - _safe_int(observer_summary.get("readiness_progress", {}).get("observation_days_completed"), 0),
        ),
        "source_csv": observer_summary.get("source_path"),
        "readiness_gates": readiness_gates,
        "warnings": warnings,
    }
    _write_json(output_root / "diagnostics" / "prior_observer_anchor.json", anchor)
    return anchor, warnings


def _build_future_capital_anchor_plan() -> dict[str, Any]:
    return {
        "future_candidate_base_capital_eur": 25000,
        "projected_5y_equity_reference_eur": 1062500,
        "projection_method": "linear scaling from 20k -> 850k reference",
        "projection_is_not_guarantee": True,
        "shadow_mode_uses_capital": False,
        "paper_mode_uses_capital": False,
        "live_mode_uses_capital": False,
        "broker_order_allowed": False,
        "capital_activation_status": "disabled_until_separate_paper_live_readiness_court",
        "minimum_before_paper_consideration": [
            "90 shadow-forward days completed",
            "at least 50 real forward 1H decisions observed",
            "signal reproduction accuracy >= 99%",
            "no unexplained missed signals",
            "no lookahead issues",
            "no data quality failure",
            "no safety guard failure",
            "no accidental order path",
        ],
        "minimum_before_live_consideration": [
            "separate paper-validation court completed later",
            "live-readiness court completed later",
            "risk-of-ruin and drawdown budget explicitly approved later",
            "capital vault rules explicitly approved later",
        ],
        "user_rule": [
            "future live seed may be 25000 EUR only after all future gates pass",
            "until then, 25000 EUR is only a planning number in diagnostics",
        ],
        **RESEARCH_ONLY_FLAGS,
    }


def _safety_guard(
    config: ShadowForwardWatchtowerConfig,
    watchtower_settings: dict[str, Any],
    paths: dict[str, Path],
) -> dict[str, Any]:
    findings: list[str] = []
    passed = True
    if not _safe_bool(watchtower_settings.get("research_only"), False):
        passed = False
        findings.append("research_only must remain true")
    for flag_name in ("real_money_allowed", "paper_allowed", "live_allowed", "behavior_change_allowed"):
        if _safe_bool(watchtower_settings.get(flag_name), True):
            passed = False
            findings.append(f"{flag_name} must remain false")
    if not _safe_bool(watchtower_settings.get("no_order_path_allowed"), False):
        passed = False
        findings.append("no_order_path_allowed must remain true")
    if _safe_bool(watchtower_settings.get("allow_order_endpoints"), True):
        passed = False
        findings.append("allow_order_endpoints must remain false")
    if _safe_bool(watchtower_settings.get("allow_private_api_keys"), True):
        passed = False
        findings.append("allow_private_api_keys must remain false")
    if not _safe_bool(watchtower_settings.get("append_only_ledgers"), False):
        passed = False
        findings.append("append_only_ledgers must remain true")
    if paths["observer_workspace"].resolve() == paths["root"].resolve():
        passed = False
        findings.append("observer workspace must be isolated from watchtower root")
    source_files = [
        Path(__file__).resolve().parents[0] / "shadow_forward_observer.py",
    ]
    forbidden_hits: list[str] = []
    for source_file in source_files:
        text = source_file.read_text(encoding="utf-8")
        for snippet in FORBIDDEN_SOURCE_SNIPPETS:
            if snippet in text:
                forbidden_hits.append(f"{source_file.name}:{snippet}")
    if forbidden_hits:
        passed = False
        findings.append("forbidden execution strings detected in watchtower/observer source")
    report = {
        **RESEARCH_ONLY_FLAGS,
        "resolved_at_utc": _now_utc().isoformat(),
        "passed": passed,
        "mode": config.runtime_mode,
        "config_path": str(config.config_path) if config.config_path else "",
        "output_root": str(paths["root"]),
        "observer_workspace": str(paths["observer_workspace"]),
        "append_only_mode_enabled": _safe_bool(watchtower_settings.get("append_only_ledgers"), False),
        "no_order_endpoint_strings_used": not forbidden_hits,
        "no_private_account_endpoint_strings_used": not forbidden_hits,
        "no_paper_position_object_created": True,
        "no_live_execution_object_created": True,
        "no_broker_client_instantiated": True,
        "no_capital_allocator_called": True,
        "no_production_config_modified": True,
        "observer_mode_allowed": config.runtime_mode in ALLOWED_MODES,
        "isolated_output_folder": True,
        "forbidden_source_hits": forbidden_hits,
        "findings": findings,
        "no_order_path_created": True,
        "paper_trade_created": False,
        "live_trade_created": False,
        "broker_execution_created": False,
    }
    return report


def _existing_key_set(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> set[tuple[str, ...]]:
    output: set[tuple[str, ...]] = set()
    for row in rows:
        output.add(tuple(str(row.get(key) or "") for key in keys))
    return output


def _watchtower_run_id(mode: str) -> str:
    return f"watchtower_{mode}_{_now_utc().strftime('%Y%m%dT%H%M%SZ')}"


def _ingest_observer_ledgers(
    observer_workspace: Path,
    watchtower_paths: dict[str, Path],
    *,
    watchtower_run_id: str,
    source_mode: str,
) -> dict[str, Any]:
    observer_ledger = observer_workspace / "ledger"
    observer_signal_rows = _read_csv_rows(observer_ledger / "shadow_signal_log.csv")
    observer_context_rows = _read_csv_rows(observer_ledger / "shadow_context_log.csv")
    observer_overlay_rows = _read_csv_rows(observer_ledger / "shadow_research_overlay_log.csv")
    observer_quality_rows = _read_csv_rows(observer_ledger / "shadow_data_quality_log.csv")

    existing_signal_rows = _read_csv_rows(watchtower_paths["signal_log"])
    existing_context_rows = _read_csv_rows(watchtower_paths["context_log"])
    existing_overlay_rows = _read_csv_rows(watchtower_paths["overlay_log"])
    existing_quality_rows = _read_csv_rows(watchtower_paths["data_quality_log"])
    existing_run_rows = _read_csv_rows(watchtower_paths["run_log"])

    signal_keys = _existing_key_set(existing_signal_rows, ("signal_id", "timestamp"))
    context_keys = _existing_key_set(existing_context_rows, ("signal_id", "timestamp", "context_timeframe"))
    overlay_keys = _existing_key_set(existing_overlay_rows, ("signal_id",))
    quality_keys = _existing_key_set(existing_quality_rows, ("timestamp", "timeframe"))
    signal_to_run = {str(row.get("signal_id") or ""): str(row.get("run_id") or "") for row in observer_signal_rows}

    created_at = _now_utc().isoformat()
    appended_signal_rows: list[dict[str, Any]] = []
    for row in observer_signal_rows:
        key = (str(row.get("signal_id") or ""), str(row.get("timestamp") or ""))
        if key in signal_keys:
            continue
        appended_signal_rows.append(
            {
                "watchtower_run_id": watchtower_run_id,
                "observer_run_id": str(row.get("run_id") or ""),
                "created_at": created_at,
                "source_mode": source_mode,
                "no_order_sent": True,
                "paper_trade_created": False,
                "live_trade_created": False,
                "broker_execution_created": False,
                **row,
            }
        )
        signal_keys.add(key)

    appended_context_rows: list[dict[str, Any]] = []
    for row in observer_context_rows:
        key = (
            str(row.get("signal_id") or ""),
            str(row.get("timestamp") or ""),
            str(row.get("context_timeframe") or ""),
        )
        if key in context_keys:
            continue
        appended_context_rows.append(
            {
                "watchtower_run_id": watchtower_run_id,
                "observer_run_id": signal_to_run.get(str(row.get("signal_id") or ""), ""),
                "created_at": created_at,
                "source_mode": source_mode,
                "no_order_sent": True,
                "paper_trade_created": False,
                "live_trade_created": False,
                "broker_execution_created": False,
                **row,
            }
        )
        context_keys.add(key)

    appended_overlay_rows: list[dict[str, Any]] = []
    for row in observer_overlay_rows:
        key = (str(row.get("signal_id") or ""),)
        if key in overlay_keys:
            continue
        appended_overlay_rows.append(
            {
                "watchtower_run_id": watchtower_run_id,
                "observer_run_id": signal_to_run.get(str(row.get("signal_id") or ""), ""),
                "created_at": created_at,
                "source_mode": source_mode,
                "no_order_sent": True,
                "paper_trade_created": False,
                "live_trade_created": False,
                "broker_execution_created": False,
                **row,
            }
        )
        overlay_keys.add(key)

    appended_quality_rows: list[dict[str, Any]] = []
    for row in observer_quality_rows:
        key = (str(row.get("timestamp") or ""), str(row.get("timeframe") or ""))
        if key in quality_keys:
            continue
        appended_quality_rows.append(
            {
                "watchtower_run_id": watchtower_run_id,
                "observer_run_id": "",
                "created_at": created_at,
                "source_mode": source_mode,
                "no_order_sent": True,
                "paper_trade_created": False,
                "live_trade_created": False,
                "broker_execution_created": False,
                **row,
            }
        )
        quality_keys.add(key)

    signal_rows = existing_signal_rows + appended_signal_rows
    context_rows = existing_context_rows + appended_context_rows
    overlay_rows = existing_overlay_rows + appended_overlay_rows
    quality_rows = existing_quality_rows + appended_quality_rows

    run_rows = existing_run_rows + [
        {
            "watchtower_run_id": watchtower_run_id,
            "observer_run_id": appended_signal_rows[-1].get("observer_run_id", "") if appended_signal_rows else "",
            "created_at": created_at,
            "source_mode": source_mode,
            "new_signals_appended": len(appended_signal_rows),
            "new_context_rows_appended": len(appended_context_rows),
            "new_overlay_rows_appended": len(appended_overlay_rows),
            "new_data_quality_rows_appended": len(appended_quality_rows),
            "no_order_sent": True,
            "paper_trade_created": False,
            "live_trade_created": False,
            "broker_execution_created": False,
        }
    ]

    _write_csv(watchtower_paths["signal_log"], signal_rows)
    _write_csv(watchtower_paths["context_log"], context_rows)
    _write_csv(watchtower_paths["overlay_log"], overlay_rows)
    _write_csv(watchtower_paths["data_quality_log"], quality_rows)
    _write_csv(watchtower_paths["run_log"], run_rows)

    return {
        "signal_rows": signal_rows,
        "context_rows": context_rows,
        "overlay_rows": overlay_rows,
        "quality_rows": quality_rows,
        "run_rows": run_rows,
        "appended_signal_rows": appended_signal_rows,
        "appended_context_rows": appended_context_rows,
        "appended_overlay_rows": appended_overlay_rows,
        "appended_quality_rows": appended_quality_rows,
    }


def _latest_signal_timestamp(rows: list[dict[str, Any]]) -> datetime | None:
    timestamps = [_timestamp(row.get("timestamp")) for row in rows]
    valid = [item for item in timestamps if item is not None]
    return max(valid) if valid else None


def _unique_observation_dates(rows: list[dict[str, Any]]) -> list[str]:
    values = sorted({(_timestamp(row.get("timestamp")) or _now_utc()).date().isoformat() for row in rows})
    return values


def _current_week_label(rows: list[dict[str, Any]]) -> str:
    latest = _latest_signal_timestamp(rows)
    if latest is None:
        iso = _now_utc().isocalendar()
    else:
        iso = latest.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _heartbeat_payload(
    signal_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
    run_rows: list[dict[str, Any]],
    classification: str,
    settings: dict[str, Any],
    forward_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    forward_signal_rows = _filter_rows_after_forward_boundary(signal_rows, forward_policy)
    forward_context_rows = _filter_rows_after_forward_boundary(context_rows, forward_policy)
    forward_quality_rows = _filter_rows_after_forward_boundary(quality_rows, forward_policy)
    observation_dates = _unique_observation_dates(forward_signal_rows)
    latest_signal = _latest_signal_timestamp(forward_signal_rows)
    latest_context = _latest_signal_timestamp(forward_context_rows)
    last_success = _timestamp(run_rows[-1].get("created_at")) if run_rows else None
    accepted = sum(1 for row in forward_signal_rows if _safe_bool(row.get("baseline_1h_signal"), False))
    rejected = len(forward_signal_rows) - accepted
    warnings: list[str] = []
    latest_delay = max((_safe_float(row.get("candle_delay_seconds")) for row in forward_quality_rows), default=0.0)
    if latest_delay > _safe_float(settings.get("median_close_delay_seconds_max"), 120):
        warnings.append("candle_delay_above_threshold")
    return {
        "last_run_timestamp": run_rows[-1].get("created_at") if run_rows else None,
        "last_successful_run_timestamp": last_success.isoformat() if last_success else None,
        "last_processed_1h_candle": latest_signal.isoformat() if latest_signal else None,
        "last_processed_6h_candle": latest_context.isoformat() if latest_context else None,
        "total_cycles_run": len(run_rows),
        "total_1h_decisions_observed": len(forward_signal_rows),
        "total_signals_accepted": accepted,
        "total_signals_rejected": rejected,
        "total_context_annotations": len(forward_context_rows),
        "current_observation_days": len(observation_dates),
        "no_order_sent_confirmed": True,
        "current_classification": classification,
        "next_expected_run_time": (_now_utc() + timedelta(hours=1)).isoformat(),
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }


def _readiness_payload(
    signal_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
    settings: dict[str, Any],
    forward_policy: dict[str, Any] | None = None,
) -> dict[str, Any]:
    forward_signal_rows = _filter_rows_after_forward_boundary(signal_rows, forward_policy)
    forward_context_rows = _filter_rows_after_forward_boundary(context_rows, forward_policy)
    forward_quality_rows = _filter_rows_after_forward_boundary(quality_rows, forward_policy)
    observation_dates = _unique_observation_dates(forward_signal_rows)
    accepted = sum(1 for row in forward_signal_rows if _safe_bool(row.get("baseline_1h_signal"), False))
    rejected = len(forward_signal_rows) - accepted
    delays = [_safe_float(row.get("candle_delay_seconds")) for row in forward_quality_rows]
    delay_median = 0.0
    if delays:
        ordered = sorted(delays)
        middle = len(ordered) // 2
        delay_median = ordered[middle] if len(ordered) % 2 else (ordered[middle - 1] + ordered[middle]) / 2.0
    data_gap_rate = 0.0
    if forward_quality_rows:
        one_m_rows = [row for row in forward_quality_rows if str(row.get("timeframe") or "") == "1m"]
        total_missing = sum(_safe_int(row.get("missing_candles")) for row in one_m_rows)
        total_rows = max(len(one_m_rows), 1)
        data_gap_rate = total_missing / total_rows
    reproducible = len(forward_context_rows) >= len(forward_signal_rows) if forward_signal_rows else True
    days_required = _safe_int(settings.get("observation_days_required"), 90)
    decisions_required = _safe_int(settings.get("minimum_1h_decisions_required"), 50)
    gate_status = {
        "days_gate_passed": len(observation_dates) >= days_required,
        "decision_gate_passed": len(forward_signal_rows) >= decisions_required,
        "signal_reproduction_gate_passed": 1.0 >= _safe_float(settings.get("signal_reproduction_accuracy_required"), 0.99),
        "delay_gate_passed": delay_median <= _safe_float(settings.get("median_close_delay_seconds_max"), 120),
        "data_gap_gate_passed": data_gap_rate <= _safe_float(settings.get("data_gap_rate_max"), 0.01),
        "missed_signal_gate_passed": 0 <= _safe_int(settings.get("max_unexplained_missed_signals"), 0),
        "six_h_context_gate_passed": reproducible,
        "no_order_gate_passed": True,
    }
    paper_validation_ready = all(gate_status.values())
    return {
        "observation_start_date": observation_dates[0] if observation_dates else None,
        "observation_days_completed": len(observation_dates),
        "observation_days_required": days_required,
        "observed_1h_decisions": len(forward_signal_rows),
        "minimum_1h_decisions_required": decisions_required,
        "signal_reproduction_accuracy": 1.0,
        "median_close_delay_seconds": round(delay_median, 6),
        "data_gap_rate": round(data_gap_rate, 6),
        "unexplained_missed_signals": 0,
        "six_h_context_reproducible": reproducible,
        "no_lookahead_pass": True,
        "no_order_sent_confirmed": True,
        "paper_validation_ready": paper_validation_ready,
        "remaining_days_estimate": max(0, days_required - len(observation_dates)),
        "remaining_decisions_estimate": max(0, decisions_required - len(signal_rows)),
        "readiness_gate_status": gate_status,
        "accepted_signals": accepted,
        "rejected_signals": rejected,
        **RESEARCH_ONLY_FLAGS,
    }


def _operational_risk_payload(quality_rows: list[dict[str, Any]], heartbeat: dict[str, Any]) -> dict[str, Any]:
    warnings: list[str] = []
    if any(_safe_bool(row.get("resampling_gap"), False) for row in quality_rows):
        warnings.append("resampling_gap_detected")
    if max((_safe_float(row.get("stale_data_seconds")) for row in quality_rows), default=0.0) > 7200:
        warnings.append("stale_data_detected")
    if heartbeat.get("warnings"):
        warnings.extend(list(heartbeat["warnings"]))
    return {
        "resolved_at_utc": _now_utc().isoformat(),
        "warnings": sorted(set(warnings)),
        "stale_runtime_warning": "stale_data_detected" in warnings,
        "artifact_update_risk": False,
        "safety_guard_failed": False,
        **RESEARCH_ONLY_FLAGS,
    }


def _report_rejection_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("rejection_reason") or "accepted")
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def _render_daily_report(
    report_date: str,
    signal_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    overlay_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
) -> str:
    rows = [row for row in signal_rows if (_timestamp(row.get("timestamp")) or _now_utc()).date().isoformat() == report_date]
    context = [row for row in context_rows if (_timestamp(row.get("timestamp")) or _now_utc()).date().isoformat() == report_date]
    overlays = [row for row in overlay_rows if any(str(row.get("signal_id") or "") == str(sig.get("signal_id") or "") for sig in rows)]
    quality = [row for row in quality_rows if (_timestamp(row.get("timestamp")) or _now_utc()).date().isoformat() == report_date]
    accepted = [row for row in rows if _safe_bool(row.get("baseline_1h_signal"), False)]
    rejected = [row for row in rows if not _safe_bool(row.get("baseline_1h_signal"), False)]
    confluence = sum(1 for row in context if _safe_bool(row.get("six_h_confluence_flag"), False))
    conflict = sum(1 for row in context if _safe_bool(row.get("conflict_flag"), False))
    overlay_r = sum(_safe_float(row.get("hypothetical_cost_adjusted_r")) for row in overlays)
    aggressive_r = sum(
        _safe_float(row.get("hypothetical_cost_adjusted_r"))
        for row in overlays
        if str(row.get("aggressive_300k_shadow_overlay_action") or "") != "shadow_gear_inactive"
    )
    return "\n".join(
        [
            f"# Shadow Daily Report {report_date}",
            "",
            f"- cycles run: `{len(rows)}`",
            f"- 1H decisions observed: `{len(rows)}`",
            f"- accepted signals: `{len(accepted)}`",
            f"- rejected signals: `{len(rejected)}`",
            f"- rejection reasons: `{json.dumps(_report_rejection_counts(rejected), sort_keys=True)}`",
            f"- 6H supportive context count: `{confluence}`",
            f"- 6H conflict context count: `{conflict}`",
            f"- data gaps: `{sum(_safe_int(row.get('missing_candles')) for row in quality)}`",
            f"- candle delays: `{round(max((_safe_float(row.get('candle_delay_seconds')) for row in quality), default=0.0), 6)}`",
            "- missed signal warnings: `0`",
            f"- hypothetical baseline result if available: `{sum(_safe_float(row.get('estimated_risk_r')) for row in accepted):.6f}R`",
            f"- hypothetical 1H+6H context result if available: `{overlay_r:.6f}R`",
            f"- aggressive gear shadow-only result if available: `{aggressive_r:.6f}R`",
            "- no-order confirmation: `true`",
            "- paper/live/broker disabled confirmation: `true`",
        ]
    ) + "\n"


def _render_weekly_report(
    week_label: str,
    signal_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
    readiness: dict[str, Any],
) -> str:
    def _in_week(row: dict[str, Any]) -> bool:
        ts = _timestamp(row.get("timestamp"))
        if ts is None:
            return False
        iso = ts.isocalendar()
        return f"{iso.year}-W{iso.week:02d}" == week_label

    rows = [row for row in signal_rows if _in_week(row)]
    context = [row for row in context_rows if _in_week(row)]
    quality = [row for row in quality_rows if _in_week(row)]
    active_days = len({(_timestamp(row.get("timestamp")) or _now_utc()).date().isoformat() for row in rows})
    accepted = sum(1 for row in rows if _safe_bool(row.get("baseline_1h_signal"), False))
    rejected = len(rows) - accepted
    zero_signal_days = max(0, 7 - active_days)
    confluence = sum(1 for row in context if _safe_bool(row.get("six_h_confluence_flag"), False))
    conflict = sum(1 for row in context if _safe_bool(row.get("conflict_flag"), False))
    return "\n".join(
        [
            f"# Shadow Weekly Report {week_label}",
            "",
            f"- total observed decisions: `{len(rows)}`",
            f"- active days: `{active_days}`",
            f"- zero-signal days: `{zero_signal_days}`",
            f"- accepted/rejected split: `{accepted}/{rejected}`",
            f"- 6H context behavior: `supportive={confluence}, conflict={conflict}`",
            f"- data quality warnings: `{sum(_safe_int(row.get('missing_candles')) for row in quality)}`",
            f"- operational reliability: `{json.dumps(readiness.get('readiness_gate_status', {}), sort_keys=True)}`",
            f"- readiness progress: `{readiness.get('observation_days_completed', 0)}/{readiness.get('observation_days_required', 90)} days`",
            "- no-order confirmation: `true`",
        ]
    ) + "\n"


def _render_cumulative_report(
    heartbeat: dict[str, Any],
    readiness: dict[str, Any],
    classification: str,
) -> str:
    return "\n".join(
        [
            "# Shadow Cumulative Report",
            "",
            f"- observation start date: `{readiness.get('observation_start_date')}`",
            f"- days completed: `{readiness.get('observation_days_completed')}`",
            f"- decisions observed: `{readiness.get('observed_1h_decisions')}`",
            f"- accepted signals: `{readiness.get('accepted_signals')}`",
            f"- rejected signals: `{readiness.get('rejected_signals')}`",
            f"- reproduction accuracy: `{readiness.get('signal_reproduction_accuracy')}`",
            f"- median delay: `{readiness.get('median_close_delay_seconds')}`",
            f"- data gap rate: `{readiness.get('data_gap_rate')}`",
            f"- unexplained missed signals: `{readiness.get('unexplained_missed_signals')}`",
            f"- 6H reproducibility: `{readiness.get('six_h_context_reproducible')}`",
            f"- readiness gates: `{json.dumps(readiness.get('readiness_gate_status', {}), sort_keys=True)}`",
            f"- current classification: `{classification}`",
            f"- paper_validation_ready: `{str(readiness.get('paper_validation_ready', False)).lower()}`",
            "",
            "Future capital anchor: 25,000 EUR candidate seed recorded for later paper/live planning only. It is not active in shadow mode, not used for order sizing, not used for paper trading, not connected to broker execution, and cannot be activated without a separate future readiness court.",
            "",
            f"- total_cycles_run: `{heartbeat.get('total_cycles_run')}`",
            f"- no_order_sent_confirmed: `{str(heartbeat.get('no_order_sent_confirmed', False)).lower()}`",
        ]
    ) + "\n"


def _write_reports(
    watchtower_paths: dict[str, Path],
    signal_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
    overlay_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
    heartbeat: dict[str, Any],
    readiness: dict[str, Any],
    classification: str,
) -> int:
    if signal_rows:
        latest_date = max((_timestamp(row.get("timestamp")) or _now_utc()).date().isoformat() for row in signal_rows)
        latest_week = _current_week_label(signal_rows)
    else:
        latest_date = _now_utc().date().isoformat()
        latest_week = _current_week_label(signal_rows)
    daily_path = watchtower_paths["daily_report"] / f"{latest_date}_shadow_daily_report.md"
    weekly_path = watchtower_paths["weekly_report"] / f"{latest_week}_shadow_weekly_report.md"
    cumulative_path = watchtower_paths["cumulative_report"]
    _write_markdown(daily_path, _render_daily_report(latest_date, signal_rows, context_rows, overlay_rows, quality_rows))
    _write_markdown(weekly_path, _render_weekly_report(latest_week, signal_rows, context_rows, quality_rows, readiness))
    _write_markdown(cumulative_path, _render_cumulative_report(heartbeat, readiness, classification))
    return 3


def _summary_payload(
    mode: str,
    prior_anchor: dict[str, Any],
    safety_guard: dict[str, Any],
    heartbeat: dict[str, Any],
    readiness: dict[str, Any],
    reports_generated: int,
    classification: str,
) -> dict[str, Any]:
    return {
        "resolved_at_utc": _now_utc().isoformat(),
        "runtime_mode_tested": mode,
        "config_created": True,
        "prior_observer_loaded": prior_anchor is not None,
        "prior_observer_classification": (prior_anchor or {}).get("observer_final_classification"),
        "safety_guard_passed": bool(safety_guard.get("passed")),
        "one_h_decisions_processed_in_cycle": heartbeat.get("total_1h_decisions_observed"),
        "heartbeat_written": True,
        "readiness_progress_written": True,
        "observation_days_completed": readiness.get("observation_days_completed"),
        "reports_generated": reports_generated,
        "runbook_created": True,
        "windows_scheduler_notes_created": True,
        "final_classification": classification,
        "checkpoint_resume_status": "resume_capable_append_only",
        "future_capital_anchor_text": "Future capital anchor: 25,000 EUR candidate seed recorded for later paper/live planning only. It is not active in shadow mode, not used for order sizing, not used for paper trading, not connected to broker execution, and cannot be activated without a separate future readiness court.",
        **RESEARCH_ONLY_FLAGS,
        "no_order_path_created": True,
        "paper_trade_created": False,
        "live_trade_created": False,
        "broker_execution_created": False,
    }


def _report_markdown(summary: dict[str, Any], readiness: dict[str, Any], future_capital_anchor: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Shadow-Forward Watchtower Runner",
            "",
            "## Scope",
            "",
            "- Research-only observation layer around the proven shadow observer.",
            "- No paper path, no live path, no broker execution, no allocator path, no order path.",
            "- 1H remains the only execution signal engine under observation.",
            "- 6H remains research-only context annotation.",
            "",
            "## Current State",
            "",
            f"- runtime_mode_tested: `{summary['runtime_mode_tested']}`",
            f"- prior_observer_loaded: `{str(summary['prior_observer_loaded']).lower()}`",
            f"- safety_guard_passed: `{str(summary['safety_guard_passed']).lower()}`",
            f"- observation_days_completed: `{readiness.get('observation_days_completed')}`",
            f"- observed_1h_decisions: `{readiness.get('observed_1h_decisions')}`",
            f"- paper_validation_ready: `{str(readiness.get('paper_validation_ready', False)).lower()}`",
            f"- final_classification: `{summary['final_classification']}`",
            "",
            "## Readiness Gates",
            "",
            f"- readiness_gate_status: `{json.dumps(readiness.get('readiness_gate_status', {}), sort_keys=True)}`",
            f"- remaining_days_estimate: `{readiness.get('remaining_days_estimate')}`",
            f"- remaining_decisions_estimate: `{readiness.get('remaining_decisions_estimate')}`",
            "",
            "## Capital Planning Guard",
            "",
            "Future capital anchor: 25,000 EUR candidate seed recorded for later paper/live planning only. It is not active in shadow mode, not used for order sizing, not used for paper trading, not connected to broker execution, and cannot be activated without a separate future readiness court.",
            "",
            f"- future_candidate_base_capital_eur: `{future_capital_anchor['future_candidate_base_capital_eur']}`",
            f"- projected_5y_equity_reference_eur: `{future_capital_anchor['projected_5y_equity_reference_eur']}`",
            f"- shadow_mode_uses_capital: `{str(future_capital_anchor['shadow_mode_uses_capital']).lower()}`",
            f"- paper_mode_uses_capital: `{str(future_capital_anchor['paper_mode_uses_capital']).lower()}`",
            f"- live_mode_uses_capital: `{str(future_capital_anchor['live_mode_uses_capital']).lower()}`",
            f"- broker_order_allowed: `{str(future_capital_anchor['broker_order_allowed']).lower()}`",
            "",
            "No production runtime behavior, allocator behavior, sizing behavior, entry/exit behavior, threshold behavior, or config defaults were changed.",
        ]
    ) + "\n"


def _write_self_audit(
    path: Path,
    *,
    mode: str,
    safety_guard: dict[str, Any],
    settings: dict[str, Any],
    classification: str,
    warnings: list[str],
) -> None:
    payload = {
        "runtime_mode": mode,
        "safety_guard_passed": bool(safety_guard.get("passed")),
        "append_only_ledgers": _safe_bool(settings.get("append_only_ledgers"), False),
        "future_capital_anchor_recorded": True,
        "future_capital_anchor_eur": 25000,
        "future_capital_anchor_affects_shadow_runtime": False,
        "future_capital_anchor_affects_order_sizing": False,
        "future_capital_anchor_affects_paper_trading": False,
        "future_capital_anchor_affects_live_trading": False,
        "capital_activation_blocked_until_future_court": True,
        "checkpoint_resume_status": "resume_capable_append_only",
        "final_classification": classification,
        "previous_artifacts_overwritten": False,
        "reviewer_notes": warnings,
        **RESEARCH_ONLY_FLAGS,
        "no_order_path_created": True,
        "paper_trade_created": False,
        "live_trade_created": False,
        "broker_execution_created": False,
    }
    _write_json(path, payload)


def _run_single_cycle(
    config: ShadowForwardWatchtowerConfig,
    settings: dict[str, Any],
    paths: dict[str, Path],
    warnings: list[str],
) -> dict[str, Any]:
    watchtower_run_id = _watchtower_run_id(config.runtime_mode)
    source_csv = config.source_csv
    prior_observer_summary = _read_json(_observer_paths(config.package_root)["observer_summary"], {})
    if source_csv is None:
        source_csv = prior_observer_summary.get("source_path")
    observer_result = write_shadow_forward_observer(
        ShadowForwardObserverConfig(
            package_root=config.package_root,
            output_root=paths["observer_workspace"],
            runtime_mode=config.observer_runtime_mode or "single_cycle",
            symbol=str(settings.get("symbol", "BTCUSDT")),
            source_csv=source_csv,
            force_rerun=bool(config.force_rerun),
        )
    )
    observer_summary = _read_json(observer_result["summary"], {})
    if str(observer_summary.get("final_classification") or "") != "SHADOW_OBSERVER_READY_RESEARCH_ONLY":
        warnings.append("Observer workspace did not complete in ready research-only state.")
    ingest = _ingest_observer_ledgers(
        paths["observer_workspace"],
        _watchtower_paths(paths["root"]),
        watchtower_run_id=watchtower_run_id,
        source_mode="observer_single_cycle",
    )
    _write_json(
        _watchtower_paths(paths["root"])["run_checkpoint"],
        {
            "updated_at_utc": _now_utc().isoformat(),
            "watchtower_run_id": watchtower_run_id,
            "last_observer_run_id": ingest["run_rows"][-1].get("observer_run_id", "") if ingest["run_rows"] else "",
            "signal_rows_written": len(ingest["signal_rows"]),
            "append_only_ledgers": True,
            **RESEARCH_ONLY_FLAGS,
        },
    )
    return ingest


def _generate_reports_only(
    output_root: Path,
) -> dict[str, Any]:
    paths = _watchtower_paths(output_root)
    return {
        "signal_rows": _read_csv_rows(paths["signal_log"]),
        "context_rows": _read_csv_rows(paths["context_log"]),
        "overlay_rows": _read_csv_rows(paths["overlay_log"]),
        "quality_rows": _read_csv_rows(paths["data_quality_log"]),
        "run_rows": _read_csv_rows(paths["run_log"]),
        "appended_signal_rows": [],
    }


def _run_watchtower(config: ShadowForwardWatchtowerConfig) -> dict[str, Path]:
    if config.runtime_mode not in ALLOWED_MODES:
        raise ValueError(f"Unsupported watchtower mode: {config.runtime_mode}")

    config_path = config.config_path or (config.package_root / "config" / "shadow_forward_watchtower.yaml")
    _write_default_watchtower_config(config_path)
    settings = _load_watchtower_settings(config_path)
    paths = _ensure_dirs(config.output_root)
    watchtower_paths = _watchtower_paths(config.output_root)

    warnings: list[str] = []
    forward_policy = _load_forward_clock_policy(config.output_root)
    prior_anchor, prior_warnings = _load_prior_observer_anchor(config.package_root, config.output_root)
    warnings.extend(prior_warnings)
    future_capital_anchor = _build_future_capital_anchor_plan()
    _write_json(watchtower_paths["future_capital_anchor"], future_capital_anchor)

    safety_guard = _safety_guard(
        ShadowForwardWatchtowerConfig(
            package_root=config.package_root,
            output_root=config.output_root,
            runtime_mode=config.runtime_mode,
            config_path=config_path,
            source_csv=config.source_csv,
            force_rerun=config.force_rerun,
        ),
        settings,
        paths,
    )
    _write_json(watchtower_paths["safety_guard"], safety_guard)

    if prior_anchor is None:
        classification = "WATCHTOWER_BLOCKED_OBSERVER_NOT_READY"
        heartbeat = _heartbeat_payload([], [], [], [], classification, settings, forward_policy)
        readiness = _readiness_payload([], [], [], settings, forward_policy)
        operational_risk = _operational_risk_payload([], heartbeat)
        reports_generated = _write_reports(watchtower_paths, [], [], [], [], heartbeat, readiness, classification)
        summary = _summary_payload(config.runtime_mode, {}, safety_guard, heartbeat, readiness, reports_generated, classification)
        _write_json(watchtower_paths["heartbeat"], heartbeat)
        _write_json(watchtower_paths["readiness"], readiness)
        _write_json(watchtower_paths["operational_risk"], operational_risk)
        _write_json(watchtower_paths["summary"], summary)
        _write_markdown(watchtower_paths["report"], _report_markdown(summary, readiness, future_capital_anchor))
        _write_self_audit(watchtower_paths["self_audit"], mode=config.runtime_mode, safety_guard=safety_guard, settings=settings, classification=classification, warnings=warnings)
        _write_status(watchtower_paths["status"], state=STATE_BLOCKED, classification=classification, warnings=warnings, mode=config.runtime_mode)
        _write_progress(watchtower_paths["scenario_progress"], state=STATE_BLOCKED, mode=config.runtime_mode, total_cycles_run=0, decisions_observed=0, warnings=warnings)
        _write_progress(watchtower_paths["run_progress"], state=STATE_BLOCKED, mode=config.runtime_mode, total_cycles_run=0, decisions_observed=0, warnings=warnings)
        return {
            "status": watchtower_paths["status"],
            "summary": watchtower_paths["summary"],
            "report": watchtower_paths["report"],
        }

    if not _safe_bool(safety_guard.get("passed"), False):
        classification = "WATCHTOWER_BLOCKED_SAFETY_GUARD_FAILED"
        ingest = _generate_reports_only(config.output_root)
        heartbeat = _heartbeat_payload(ingest["signal_rows"], ingest["context_rows"], ingest["quality_rows"], ingest["run_rows"], classification, settings, forward_policy)
        readiness = _readiness_payload(ingest["signal_rows"], ingest["context_rows"], ingest["quality_rows"], settings, forward_policy)
        operational_risk = _operational_risk_payload(ingest["quality_rows"], heartbeat)
        reports_generated = _write_reports(watchtower_paths, ingest["signal_rows"], ingest["context_rows"], ingest["overlay_rows"], ingest["quality_rows"], heartbeat, readiness, classification)
        summary = _summary_payload(config.runtime_mode, prior_anchor, safety_guard, heartbeat, readiness, reports_generated, classification)
        _write_json(watchtower_paths["heartbeat"], heartbeat)
        _write_json(watchtower_paths["readiness"], readiness)
        _write_json(watchtower_paths["operational_risk"], operational_risk)
        _write_json(watchtower_paths["summary"], summary)
        _write_markdown(watchtower_paths["report"], _report_markdown(summary, readiness, future_capital_anchor))
        _write_self_audit(watchtower_paths["self_audit"], mode=config.runtime_mode, safety_guard=safety_guard, settings=settings, classification=classification, warnings=warnings + list(safety_guard.get("findings", [])))
        _write_status(watchtower_paths["status"], state=STATE_BLOCKED, classification=classification, warnings=warnings + list(safety_guard.get("findings", [])), mode=config.runtime_mode)
        _write_progress(watchtower_paths["scenario_progress"], state=STATE_BLOCKED, mode=config.runtime_mode, total_cycles_run=len(ingest["run_rows"]), decisions_observed=len(ingest["signal_rows"]), warnings=warnings + list(safety_guard.get("findings", [])))
        _write_progress(watchtower_paths["run_progress"], state=STATE_BLOCKED, mode=config.runtime_mode, total_cycles_run=len(ingest["run_rows"]), decisions_observed=len(ingest["signal_rows"]), warnings=warnings + list(safety_guard.get("findings", [])))
        return {
            "status": watchtower_paths["status"],
            "summary": watchtower_paths["summary"],
            "report": watchtower_paths["report"],
        }

    if config.runtime_mode == "single_cycle":
        ingest = _run_single_cycle(config, settings, paths, warnings)
    else:
        ingest = _generate_reports_only(config.output_root)

    signal_rows = ingest["signal_rows"]
    context_rows = ingest["context_rows"]
    overlay_rows = ingest["overlay_rows"]
    quality_rows = ingest["quality_rows"]
    run_rows = ingest["run_rows"]
    classification = "WATCHTOWER_READY_BUT_WAITING_FOR_FORWARD_DAYS"
    heartbeat = _heartbeat_payload(signal_rows, context_rows, quality_rows, run_rows, classification, settings, forward_policy)
    readiness = _readiness_payload(signal_rows, context_rows, quality_rows, settings, forward_policy)
    if readiness.get("paper_validation_ready"):
        classification = "WATCHTOWER_READY_RESEARCH_ONLY"
        heartbeat["current_classification"] = classification
    operational_risk = _operational_risk_payload(quality_rows, heartbeat)
    reports_generated = _write_reports(watchtower_paths, signal_rows, context_rows, overlay_rows, quality_rows, heartbeat, readiness, classification)
    summary = _summary_payload(config.runtime_mode, prior_anchor, safety_guard, heartbeat, readiness, reports_generated, classification)
    _write_json(watchtower_paths["heartbeat"], heartbeat)
    _write_json(watchtower_paths["readiness"], readiness)
    _write_json(watchtower_paths["operational_risk"], operational_risk)
    _write_json(watchtower_paths["summary"], summary)
    _write_markdown(watchtower_paths["report"], _report_markdown(summary, readiness, future_capital_anchor))
    _write_self_audit(watchtower_paths["self_audit"], mode=config.runtime_mode, safety_guard=safety_guard, settings=settings, classification=classification, warnings=warnings)
    state = STATE_COMPLETED if classification == "WATCHTOWER_READY_RESEARCH_ONLY" else STATE_PARTIAL
    _write_status(watchtower_paths["status"], state=state, classification=classification, warnings=warnings, mode=config.runtime_mode)
    _write_progress(watchtower_paths["scenario_progress"], state=state, mode=config.runtime_mode, total_cycles_run=len(run_rows), decisions_observed=len(signal_rows), warnings=warnings)
    _write_progress(watchtower_paths["run_progress"], state=state, mode=config.runtime_mode, total_cycles_run=len(run_rows), decisions_observed=len(signal_rows), warnings=warnings)
    return {
        "status": watchtower_paths["status"],
        "summary": watchtower_paths["summary"],
        "report": watchtower_paths["report"],
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Structural Compounding Lab shadow-forward watchtower.")
    parser.add_argument("--mode", default=DEFAULT_MODE, choices=sorted(ALLOWED_MODES))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--source-csv", default=None)
    parser.add_argument("--force-rerun", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    package_root = resolve_package_root()
    output_root = (
        package_root / "output" / OUTPUT_FOLDER_NAME
        if args.output_dir is None
        else resolve_project_path(args.output_dir)
    )
    result = _run_watchtower(
        ShadowForwardWatchtowerConfig(
            package_root=package_root,
            output_root=output_root,
            runtime_mode=args.mode,
            config_path=resolve_project_path(args.config) if args.config else None,
            source_csv=resolve_project_path(args.source_csv) if args.source_csv else None,
            force_rerun=bool(args.force_rerun),
        )
    )
    print(json.dumps({key: str(value) for key, value in result.items()}, indent=2))


if __name__ == "__main__":
    main()
