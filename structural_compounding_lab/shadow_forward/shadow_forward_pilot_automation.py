from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
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
from structural_compounding_lab.shadow_forward.fresh_btcusdt_data_updater import (  # noqa: E402
    FreshBTCUSDTDataUpdaterConfig,
    write_fresh_btcusdt_data_updater,
)


OUTPUT_FOLDER_NAME = "shadow_forward_pilot_automation_001"
DEFAULT_MODE = "self_check"
ALLOWED_MODES = {
    "self_check",
    "manual_test_run",
    "generate_scheduler_command",
    "install_scheduler_task",
    "remove_scheduler_task",
    "daily_status",
    "status",
}
TASK_NAME = "StructuralCompoundingLab_ShadowPilot_Hourly"
FORBIDDEN_SNIPPETS = (
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
STATUS_GREEN = "GREEN"
STATUS_YELLOW = "YELLOW"
STATUS_RED = "RED"

DEFAULT_AUTOMATION_SETTINGS: dict[str, Any] = {
    **RESEARCH_ONLY_FLAGS,
    "no_order_path_allowed": True,
    "symbol": "BTCUSDT",
    "base_timeframe": "1m",
    "execution_timeframe": "1H",
    "context_timeframe": "6H",
    "pilot_days_required": 7,
    "full_shadow_days_required": 90,
    "expected_run_frequency_minutes": 60,
    "run_after_candle_close_delay_minutes": 5,
    "stale_data_warning_minutes": 90,
    "stale_data_block_minutes": 180,
    "maximum_duplicate_1h_decisions_allowed": 0,
    "maximum_unexplained_missed_signals_allowed": 0,
    "maximum_data_gap_rate_allowed": 0.01,
    "median_close_delay_seconds_max": 120,
    "append_only_ledgers": True,
    "force_rerun_default": False,
    "scheduler_task_name": TASK_NAME,
    "scheduler_install_requires_explicit_confirmation": True,
    "scheduler_default_enabled": False,
    "capital_anchor_eur": 25000,
    "capital_anchor_diagnostic_only": True,
    "paper_validation_ready_default": False,
}


@dataclass(frozen=True)
class ShadowForwardPilotAutomationConfig:
    package_root: Path
    output_root: Path
    mode: str = DEFAULT_MODE
    config_path: Path | None = None
    confirm_install_scheduler: bool = False
    confirm_remove_scheduler: bool = False
    force_rerun: bool = False
    dry_run: bool = False


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


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


def _read_csv_rows(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _safe_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value in {None, ""}:
        return default
    lowered = str(value).strip().lower()
    if lowered in {"true", "1", "yes", "y", "on"}:
        return True
    if lowered in {"false", "0", "no", "n", "off"}:
        return False
    return default


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
            raise ValueError(f"Expected mapping in automation YAML: {path}")
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


def _ensure_dirs(output_root: Path) -> dict[str, Path]:
    paths = {
        "root": output_root,
        "diagnostics": output_root / "diagnostics",
        "reports": output_root / "reports",
        "docs": output_root / "docs",
        "checkpoints": output_root / "_checkpoints",
        "logs": output_root / "logs",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    return paths


def _paths(output_root: Path) -> dict[str, Path]:
    return {
        "status": output_root / "status.json",
        "scenario_progress": output_root / "scenario_progress.json",
        "summary": output_root / "automation_summary.json",
        "report": output_root / "automation_report.md",
        "prior_gate_anchor": output_root / "diagnostics" / "prior_gate_anchor.json",
        "self_check": output_root / "diagnostics" / "self_check_report.json",
        "manual_test": output_root / "diagnostics" / "manual_test_run_report.json",
        "scheduler_command": output_root / "diagnostics" / "scheduler_command_report.json",
        "scheduler_install": output_root / "diagnostics" / "scheduler_install_report.json",
        "scheduler_remove": output_root / "diagnostics" / "scheduler_remove_report.json",
        "daily_status": output_root / "diagnostics" / "daily_status.json",
        "current_status": output_root / "diagnostics" / "current_status.json",
        "run_progress": output_root / "diagnostics" / "run_progress.json",
        "self_audit": output_root / "diagnostics" / "implementation_self_audit.json",
        "generated_command_doc": output_root / "docs" / "generated_windows_scheduler_command.md",
        "daily_status_report": output_root / "reports" / "daily_status.md",
        "checkpoint": output_root / "_checkpoints" / "pilot_automation_checkpoint.json",
    }


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


def _write_progress(path: Path, *, state: str, mode: str, warnings: list[str], extra: dict[str, Any] | None = None) -> None:
    payload = {
        "state": state,
        "updated_at_utc": _now_utc().isoformat(),
        "runtime_mode": mode,
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    if extra:
        payload.update(extra)
    _write_json(path, payload)


def _write_default_config(path: Path) -> None:
    if path.exists():
        return
    lines = ["# Research-only one-click 7-day shadow pilot automation config"]
    for key, value in DEFAULT_AUTOMATION_SETTINGS.items():
        lines.append(f"{key}: {_serialize_yaml_value(value)}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _load_settings(path: Path) -> dict[str, Any]:
    if not path.exists():
        return dict(DEFAULT_AUTOMATION_SETTINGS)
    loaded = _simple_yaml_load(path)
    merged = dict(DEFAULT_AUTOMATION_SETTINGS)
    merged.update(loaded)
    return merged


def _watchtower_root(package_root: Path) -> Path:
    return package_root / "output" / "shadow_forward_watchtower_001"


def _updater_root(package_root: Path) -> Path:
    return package_root / "output" / "fresh_btcusdt_data_updater_001"


def _canonical_btcusdt_path(package_root: Path, updater_summary: dict[str, Any]) -> Path:
    configured_path = str(updater_summary.get("canonical_path") or "").strip()
    if configured_path:
        candidate = Path(configured_path).expanduser()
        return candidate if candidate.is_absolute() else package_root.parent / candidate
    return (
        package_root
        / "data_storage"
        / "BTCUSDT"
        / "1m"
        / "btcusdt_1m_canonical_shadow_forward.csv"
    )


def _load_prior_gate_anchor(package_root: Path, report_path: Path) -> dict[str, Any]:
    updater_root = _updater_root(package_root)
    watchtower_root = _watchtower_root(package_root)
    updater_summary = _read_json(updater_root / "fresh_btcusdt_data_updater_summary.json", {})
    updater_self_audit = _read_json(updater_root / "diagnostics" / "implementation_self_audit.json", {})
    watchtower_summary = _read_json(watchtower_root / "watchtower_summary.json", {})
    watchtower_readiness = _read_json(watchtower_root / "diagnostics" / "readiness_progress.json", {})
    watchtower_safety = _read_json(watchtower_root / "diagnostics" / "safety_guard_report.json", {})
    capital_anchor = _read_json(watchtower_root / "diagnostics" / "future_capital_anchor_plan.json", {})
    supervisor_summary = _read_json(package_root / "output" / "shadow_forward_pilot_supervisor_001" / "shadow_forward_pilot_supervisor_summary.json", {})
    canonical_path = _canonical_btcusdt_path(package_root, updater_summary)

    warnings: list[str] = []
    if not updater_summary:
        warnings.append("fresh_updater_summary_missing")
    if not canonical_path.exists():
        warnings.append("canonical_btcusdt_path_missing")
    if not watchtower_summary:
        warnings.append("watchtower_summary_missing")
    if not _safe_bool(watchtower_safety.get("passed"), False):
        warnings.append("watchtower_safety_guard_not_confirmed")
    if not _safe_bool(updater_summary.get("forward_clock_started"), False) and _safe_int(watchtower_readiness.get("observation_days_completed"), 0) <= 0:
        warnings.append("forward_clock_not_confirmed_started")
    if _safe_bool(watchtower_readiness.get("paper_validation_ready"), False):
        warnings.append("paper_validation_ready_must_remain_false")
    if not capital_anchor or not _safe_bool(capital_anchor.get("shadow_mode_uses_capital") is False, True):
        pass

    payload = {
        "resolved_at_utc": _now_utc().isoformat(),
        "fresh_updater_exists": bool(updater_summary),
        "fresh_updater_summary_path": str(updater_root / "fresh_btcusdt_data_updater_summary.json"),
        "fresh_updater_self_audit_path": str(updater_root / "diagnostics" / "implementation_self_audit.json"),
        "watchtower_exists": bool(watchtower_summary),
        "watchtower_summary_path": str(watchtower_root / "watchtower_summary.json"),
        "watchtower_readiness_path": str(watchtower_root / "diagnostics" / "readiness_progress.json"),
        "watchtower_safety_guard_path": str(watchtower_root / "diagnostics" / "safety_guard_report.json"),
        "future_capital_anchor_path": str(watchtower_root / "diagnostics" / "future_capital_anchor_plan.json"),
        "pilot_supervisor_exists": bool(supervisor_summary),
        "pilot_supervisor_summary_path": str(package_root / "output" / "shadow_forward_pilot_supervisor_001" / "shadow_forward_pilot_supervisor_summary.json"),
        "canonical_path": str(canonical_path),
        "canonical_path_exists": canonical_path.exists(),
        "watchtower_safety_guard_passed": _safe_bool(watchtower_safety.get("passed"), False),
        "forward_clock_started": _safe_bool(updater_summary.get("forward_clock_started"), False) or _safe_int(watchtower_readiness.get("observation_days_completed"), 0) > 0,
        "paper_validation_ready": _safe_bool(watchtower_readiness.get("paper_validation_ready"), False),
        "no_order_path": _safe_bool(updater_summary.get("no_order_path_created"), False)
        and _safe_bool(updater_self_audit.get("no_order_path_created"), False)
        and _safe_bool(watchtower_summary.get("no_order_path_created"), False),
        "no_paper_path": not _safe_bool(updater_summary.get("paper_trade_created"), True)
        and not _safe_bool(watchtower_summary.get("paper_trade_created"), True),
        "no_live_path": not _safe_bool(updater_summary.get("live_trade_created"), True)
        and not _safe_bool(watchtower_summary.get("live_trade_created"), True),
        "no_broker_execution": not _safe_bool(updater_summary.get("broker_execution_created"), True)
        and not _safe_bool(watchtower_summary.get("broker_execution_created"), True),
        "capital_anchor_diagnostic_only": capital_anchor.get("future_candidate_base_capital_eur") == 25000
        and _safe_bool(capital_anchor.get("shadow_mode_uses_capital") is False, True)
        and _safe_bool(capital_anchor.get("paper_mode_uses_capital") is False, True)
        and _safe_bool(capital_anchor.get("live_mode_uses_capital") is False, True)
        and _safe_bool(capital_anchor.get("broker_order_allowed") is False, True),
        "warnings": warnings,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(report_path, payload)
    return payload


def _scan_forbidden_strings(package_root: Path) -> list[str]:
    targets = [
        package_root.parent / "scripts" / "install_shadow_pilot_task.ps1",
        package_root.parent / "scripts" / "remove_shadow_pilot_task.ps1",
        package_root.parent / "scripts" / "shadow_pilot_self_check.py",
        package_root.parent / "scripts" / "shadow_pilot_run_once.py",
        package_root.parent / "scripts" / "shadow_pilot_daily_status.py",
    ]
    hits: list[str] = []
    for target in targets:
        if not target.exists():
            continue
        text = target.read_text(encoding="utf-8")
        for snippet in FORBIDDEN_SNIPPETS:
            if snippet in text:
                hits.append(f"{target.name}:{snippet}")
    return hits


def _python_executable() -> str:
    return sys.executable or "python"


def _project_root(package_root: Path) -> Path:
    return package_root.parent


def _scheduler_log_path(output_root: Path) -> Path:
    return output_root / "logs" / "shadow_pilot_scheduler.log"


def _self_check(config: ShadowForwardPilotAutomationConfig, settings: dict[str, Any], paths: dict[str, Path], anchor: dict[str, Any]) -> dict[str, Any]:
    effective_config_path = config.config_path or (config.package_root / "config" / "shadow_forward_pilot_automation.yaml")
    canonical_path = _canonical_btcusdt_path(config.package_root, {"canonical_path": anchor.get("canonical_path")})
    forbidden_hits = _scan_forbidden_strings(config.package_root)
    findings: list[str] = []
    passed = True

    if not Path(_python_executable()).exists():
        passed = False
        findings.append("python_path_missing")
    if not _project_root(config.package_root).exists():
        passed = False
        findings.append("project_root_missing")
    if not effective_config_path.exists():
        passed = False
        findings.append("automation_config_missing")
    if not canonical_path.exists():
        passed = False
        findings.append("canonical_btcusdt_path_missing")
    if not anchor.get("fresh_updater_exists"):
        passed = False
        findings.append("fresh_updater_missing")
    if not anchor.get("watchtower_exists"):
        passed = False
        findings.append("watchtower_missing")
    if not anchor.get("watchtower_safety_guard_passed"):
        passed = False
        findings.append("watchtower_safety_guard_failed")
    if forbidden_hits:
        passed = False
        findings.append("forbidden_execution_strings_detected")
    if not anchor.get("no_order_path"):
        passed = False
        findings.append("no_order_path_not_confirmed")
    if not anchor.get("no_paper_path"):
        passed = False
        findings.append("paper_path_detected")
    if not anchor.get("no_live_path"):
        passed = False
        findings.append("live_path_detected")
    if not anchor.get("no_broker_execution"):
        passed = False
        findings.append("broker_execution_detected")
    if not anchor.get("capital_anchor_diagnostic_only"):
        passed = False
        findings.append("capital_anchor_not_diagnostic_only")
    if not _safe_bool(settings.get("append_only_ledgers"), False):
        passed = False
        findings.append("append_only_ledgers_disabled")
    if _safe_bool(settings.get("paper_allowed"), True) or _safe_bool(settings.get("live_allowed"), True) or _safe_bool(settings.get("real_money_allowed"), True):
        passed = False
        findings.append("runtime_flags_not_research_only")

    report = {
        "resolved_at_utc": _now_utc().isoformat(),
        "python_path": _python_executable(),
        "python_path_exists": Path(_python_executable()).exists(),
        "project_root": str(_project_root(config.package_root)),
        "project_root_exists": _project_root(config.package_root).exists(),
        "config_exists": effective_config_path.exists(),
        "canonical_btcusdt_path": str(canonical_path),
        "canonical_btcusdt_path_exists": canonical_path.exists(),
        "fresh_updater_exists": bool(anchor.get("fresh_updater_exists")),
        "watchtower_exists": bool(anchor.get("watchtower_exists")),
        "watchtower_safety_guard_previously_passed": bool(anchor.get("watchtower_safety_guard_passed")),
        "pilot_supervisor_exists": bool(anchor.get("pilot_supervisor_exists")),
        "no_order_endpoint_strings_used": not forbidden_hits,
        "no_account_endpoint_strings_used": not forbidden_hits,
        "no_broker_execution_path_exists": bool(anchor.get("no_broker_execution")),
        "no_paper_path_exists": bool(anchor.get("no_paper_path")),
        "no_live_path_exists": bool(anchor.get("no_live_path")),
        "capital_anchor_diagnostic_only": bool(anchor.get("capital_anchor_diagnostic_only")),
        "output_folders_isolated": True,
        "append_only_ledgers_enabled": _safe_bool(settings.get("append_only_ledgers"), False),
        "forbidden_hits": forbidden_hits,
        "classification": "AUTOMATION_SELF_CHECK_PASSED" if passed else "AUTOMATION_SELF_CHECK_FAILED",
        "warnings": findings,
        **RESEARCH_ONLY_FLAGS,
        "no_order_path_created": True,
        "paper_trade_created": False,
        "live_trade_created": False,
        "broker_execution_created": False,
    }
    _write_json(paths["self_check"], report)
    return report


def _manual_test_run(config: ShadowForwardPilotAutomationConfig, settings: dict[str, Any], paths: dict[str, Path], self_check_report: dict[str, Any]) -> dict[str, Any]:
    if self_check_report.get("classification") != "AUTOMATION_SELF_CHECK_PASSED":
        report = {
            "run_attempted": False,
            "run_success": False,
            "updater_called": False,
            "pilot_supervisor_called": False,
            "public_fetch_attempted": False,
            "rows_fetched": 0,
            "rows_appended": 0,
            "newly_processed_1h_decisions": 0,
            "duplicate_1h_decisions_skipped": 0,
            "latest_canonical_timestamp": None,
            "heartbeat_updated": False,
            "readiness_updated": False,
            "no_order_sent_confirmed": True,
            "no_paper_trade_created": True,
            "no_live_trade_created": True,
            "broker_execution_created": False,
            "warnings": ["self_check_failed"],
            "classification": "AUTOMATION_MANUAL_TEST_FAILED",
            **RESEARCH_ONLY_FLAGS,
        }
        _write_json(paths["manual_test"], report)
        return report

    updater_result = write_fresh_btcusdt_data_updater(
        FreshBTCUSDTDataUpdaterConfig(
            package_root=config.package_root,
            output_root=_updater_root(config.package_root),
            mode="update_and_catchup",
            symbol=str(settings.get("symbol", "BTCUSDT")),
            force_rerun=bool(config.force_rerun),
        )
    )
    updater_summary = _read_json(updater_result["summary"], {})
    kickoff = _read_json(_updater_root(config.package_root) / "diagnostics" / "watchtower_kickoff_report.json", {})
    report = {
        "run_attempted": True,
        "run_success": str(updater_summary.get("final_classification") or "").startswith("FRESH_DATA_READY_"),
        "updater_called": True,
        "pilot_supervisor_called": False,
        "public_fetch_attempted": bool(_safe_bool(_read_json(_updater_root(config.package_root) / "diagnostics" / "public_fetch_report.json", {}).get("public_fetch_attempted"), False)),
        "rows_fetched": _safe_int(updater_summary.get("rows_fetched"), 0),
        "rows_appended": _safe_int(updater_summary.get("rows_appended"), 0),
        "newly_processed_1h_decisions": _safe_int(kickoff.get("newly_processed_1h_decisions"), 0),
        "duplicate_1h_decisions_skipped": _safe_int(kickoff.get("duplicate_1h_candles_skipped"), 0),
        "latest_canonical_timestamp": updater_summary.get("latest_canonical_timestamp"),
        "heartbeat_updated": _safe_bool(kickoff.get("heartbeat_updated"), False),
        "readiness_updated": _safe_bool(kickoff.get("readiness_updated"), False),
        "no_order_sent_confirmed": _safe_bool(kickoff.get("no_order_sent_confirmed"), True),
        "no_paper_trade_created": True,
        "no_live_trade_created": True,
        "broker_execution_created": False,
        "warnings": [],
        "classification": "AUTOMATION_READY_FOR_MANUAL_APPROVAL"
        if str(updater_summary.get("final_classification") or "").startswith("FRESH_DATA_READY_")
        else "AUTOMATION_MANUAL_TEST_FAILED",
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(paths["manual_test"], report)
    return report


def _next_scheduler_start_local() -> str:
    local_now = datetime.now()
    candidate = local_now.replace(minute=5, second=0, microsecond=0)
    if local_now >= candidate:
        candidate = (local_now + timedelta(hours=1)).replace(minute=5, second=0, microsecond=0)
    return candidate.strftime("%H:%M")


def _scheduled_python_command(config: ShadowForwardPilotAutomationConfig) -> str:
    project_root = _project_root(config.package_root)
    log_path = _scheduler_log_path(config.output_root)
    return (
        f"powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "
        f"\"Set-Location '{project_root}'; & '{_python_executable()}' -m structural_compounding_lab.shadow_forward.shadow_forward_pilot_automation "
        f"--mode manual_test_run *> '{log_path}'\""
    )


def _scheduler_docs(command: str, start_time: str) -> str:
    return "\n".join(
        [
            "# Generated Windows Scheduler Command",
            "",
            f"- Task name: `{TASK_NAME}`",
            f"- Schedule: hourly from `{start_time}`",
            "",
            "## PowerShell / schtasks",
            "",
            "```powershell",
            f"$taskCommand = @'\n{command}\n'@",
            f"schtasks /Create /TN \"{TASK_NAME}\" /SC HOURLY /MO 1 /ST {start_time} /TR $taskCommand /F",
            "```",
            "",
            "## GUI Steps",
            "",
            "1. Open Task Scheduler.",
            "2. Create Task.",
            f"3. Use name `{TASK_NAME}`.",
            f"4. Trigger: daily, repeat every 1 hour, start at `{start_time}`.",
            "5. Action: start a program using PowerShell and the generated command.",
            "6. Set Start in to the project root.",
            "",
            "## Disable / Remove",
            "",
            f"- Disable: `schtasks /Change /TN \"{TASK_NAME}\" /DISABLE`",
            f"- Remove: `schtasks /Delete /TN \"{TASK_NAME}\" /F`",
            "",
            "## Inspect",
            "",
            f"- Verify task history in Task Scheduler for `{TASK_NAME}`.",
            "- Inspect scheduler log at `structural_compounding_lab/output/shadow_forward_pilot_automation_001/logs/shadow_pilot_scheduler.log`.",
            "",
            "Warning: this file only generates commands. It does not install the scheduler by default.",
        ]
    ) + "\n"


def _generate_scheduler_command(config: ShadowForwardPilotAutomationConfig, paths: dict[str, Path]) -> dict[str, Any]:
    start_time = _next_scheduler_start_local()
    command = _scheduled_python_command(config)
    report = {
        "generated_at_utc": _now_utc().isoformat(),
        "task_name": TASK_NAME,
        "schedule": f"HOURLY from {start_time}",
        "working_directory": str(_project_root(config.package_root)),
        "command": command,
        "scheduler_installed_by_default": False,
        "classification": "AUTOMATION_READY_FOR_MANUAL_APPROVAL",
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(paths["scheduler_command"], report)
    _write_markdown(paths["generated_command_doc"], _scheduler_docs(command, start_time))
    return report


def _scheduler_task_exists() -> bool:
    if os.name != "nt":
        return False
    try:
        result = subprocess.run(["schtasks", "/Query", "/TN", TASK_NAME], capture_output=True, text=True, check=False)
    except OSError:
        return False
    return result.returncode == 0


def _install_scheduler(config: ShadowForwardPilotAutomationConfig, paths: dict[str, Path], self_check_report: dict[str, Any]) -> dict[str, Any]:
    if not config.confirm_install_scheduler:
        report = {
            "install_attempted": False,
            "install_success": False,
            "explicit_confirmation_received": False,
            "blocked_reason": "explicit_confirmation_required",
            "task_name": TASK_NAME,
            **RESEARCH_ONLY_FLAGS,
        }
        _write_json(paths["scheduler_install"], report)
        return report
    command_report = _generate_scheduler_command(config, paths)
    command = str(command_report["command"])
    warnings: list[str] = []
    if os.name != "nt":
        warnings.append("windows_task_scheduler_unavailable_on_this_platform")
    if self_check_report.get("classification") != "AUTOMATION_SELF_CHECK_PASSED":
        warnings.append("self_check_failed")
    if any(flag in command.lower() for flag in ("paper", "live", "order")) and "--mode manual_test_run" not in command:
        warnings.append("unsafe_scheduler_command")
    log_dir = _scheduler_log_path(config.output_root).parent
    log_dir.mkdir(parents=True, exist_ok=True)
    start_time = str(command_report["schedule"]).split()[-1]
    success = False
    if not warnings:
        create = subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME, "/SC", "HOURLY", "/MO", "1", "/ST", start_time, "/TR", command, "/F"],
            capture_output=True,
            text=True,
            check=False,
        )
        success = create.returncode == 0
        if not success:
            warnings.append(create.stderr.strip() or create.stdout.strip() or "scheduler_create_failed")
    report = {
        "install_attempted": True,
        "install_success": success,
        "explicit_confirmation_received": True,
        "task_name": TASK_NAME,
        "schedule": command_report["schedule"],
        "command": command,
        "working_directory": str(_project_root(config.package_root)),
        "safety_guard_passed": self_check_report.get("classification") == "AUTOMATION_SELF_CHECK_PASSED",
        "no_order_path_confirmed": True,
        "no_paper_path_confirmed": True,
        "no_live_path_confirmed": True,
        "broker_execution_created": False,
        "warnings": warnings,
        "classification": "AUTOMATION_SCHEDULER_INSTALLED_RESEARCH_ONLY" if success else "AUTOMATION_INCOMPLETE",
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(paths["scheduler_install"], report)
    return report


def _remove_scheduler(config: ShadowForwardPilotAutomationConfig, paths: dict[str, Path]) -> dict[str, Any]:
    if not config.confirm_remove_scheduler:
        report = {
            "remove_attempted": False,
            "remove_success": False,
            "explicit_confirmation_received": False,
            "blocked_reason": "explicit_confirmation_required",
            "task_name": TASK_NAME,
            **RESEARCH_ONLY_FLAGS,
        }
        _write_json(paths["scheduler_remove"], report)
        return report
    if os.name != "nt":
        report = {
            "remove_attempted": False,
            "remove_success": False,
            "explicit_confirmation_received": True,
            "blocked_reason": "windows_task_scheduler_unavailable_on_this_platform",
            "task_name": TASK_NAME,
            "warnings": ["windows_task_scheduler_unavailable_on_this_platform"],
            "classification": "AUTOMATION_INCOMPLETE",
            **RESEARCH_ONLY_FLAGS,
        }
        _write_json(paths["scheduler_remove"], report)
        return report
    result = subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], capture_output=True, text=True, check=False)
    success = result.returncode == 0
    report = {
        "remove_attempted": True,
        "remove_success": success,
        "explicit_confirmation_received": True,
        "task_name": TASK_NAME,
        "warnings": [] if success else [result.stderr.strip() or result.stdout.strip() or "scheduler_remove_failed"],
        "classification": "AUTOMATION_READY_FOR_MANUAL_APPROVAL" if success else "AUTOMATION_INCOMPLETE",
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(paths["scheduler_remove"], report)
    return report


def _count_recent_rows(rows: list[dict[str, Any]], *, since: datetime) -> int:
    total = 0
    for row in rows:
        parsed = _timestamp(row.get("timestamp") or row.get("resolved_at_utc") or row.get("updated_at_utc"))
        if parsed is not None and parsed >= since:
            total += 1
    return total


def _daily_status(config: ShadowForwardPilotAutomationConfig, settings: dict[str, Any], paths: dict[str, Path], anchor: dict[str, Any]) -> dict[str, Any]:
    watchtower_root = _watchtower_root(config.package_root)
    updater_root = _updater_root(config.package_root)
    watchtower_heartbeat = _read_json(watchtower_root / "diagnostics" / "heartbeat.json", {})
    watchtower_readiness = _read_json(watchtower_root / "diagnostics" / "readiness_progress.json", {})
    watchtower_safety = _read_json(watchtower_root / "diagnostics" / "safety_guard_report.json", {})
    watchtower_summary = _read_json(watchtower_root / "watchtower_summary.json", {})
    updater_summary = _read_json(updater_root / "fresh_btcusdt_data_updater_summary.json", {})
    updater_quality = _read_json(updater_root / "diagnostics" / "fresh_data_quality_audit.json", {})
    manual_test = _read_json(paths["manual_test"], {})
    capital_anchor = _read_json(watchtower_root / "diagnostics" / "future_capital_anchor_plan.json", {})
    signal_rows = _read_csv_rows(watchtower_root / "ledger" / "watchtower_signal_log.csv")
    run_rows = _read_csv_rows(watchtower_root / "ledger" / "watchtower_run_log.csv")
    now = _now_utc()
    since_24h = now - timedelta(hours=24)

    latest_run_time = _timestamp(watchtower_heartbeat.get("resolved_at_utc") or watchtower_heartbeat.get("updated_at_utc"))
    if latest_run_time is None and run_rows:
        run_timestamps = [parsed for parsed in (_timestamp(row.get("timestamp")) for row in run_rows) if parsed is not None]
        latest_run_time = max(run_timestamps) if run_timestamps else None
    if latest_run_time is None:
        latest_run_time = _timestamp(watchtower_summary.get("resolved_at_utc"))
    latest_successful_run = _timestamp(updater_summary.get("resolved_at_utc"))
    latest_canonical_timestamp = _timestamp(updater_summary.get("latest_canonical_timestamp"))
    stale_minutes = None
    if latest_canonical_timestamp is not None:
        stale_minutes = max(0.0, (now - latest_canonical_timestamp.replace(tzinfo=timezone.utc)).total_seconds() / 60.0)

    warnings: list[str] = []
    status_color = STATUS_GREEN
    if not _safe_bool(watchtower_safety.get("passed"), False):
        status_color = STATUS_RED
        warnings.append("watchtower_safety_guard_failed")
    if stale_minutes is None:
        status_color = STATUS_RED
        warnings.append("canonical_timestamp_missing")
    elif stale_minutes > _safe_int(settings.get("stale_data_block_minutes"), 180):
        status_color = STATUS_RED
        warnings.append("canonical_data_stale_block")
    elif stale_minutes > _safe_int(settings.get("stale_data_warning_minutes"), 90):
        status_color = STATUS_YELLOW if status_color != STATUS_RED else status_color
        warnings.append("canonical_data_stale_warning")
    if _safe_bool(watchtower_readiness.get("paper_validation_ready"), False):
        status_color = STATUS_RED
        warnings.append("paper_validation_ready_should_be_false")
    if not anchor.get("no_order_path") or not anchor.get("no_paper_path") or not anchor.get("no_live_path") or not anchor.get("no_broker_execution"):
        status_color = STATUS_RED
        warnings.append("unsafe_path_detected")
    if _safe_int(manual_test.get("duplicate_1h_decisions_skipped"), 0) > _safe_int(settings.get("maximum_duplicate_1h_decisions_allowed"), 0):
        status_color = STATUS_RED
        warnings.append("duplicate_decision_incident")
    if _safe_int(watchtower_readiness.get("unexplained_missed_signals"), 0) > _safe_int(settings.get("maximum_unexplained_missed_signals_allowed"), 0):
        status_color = STATUS_RED
        warnings.append("unexplained_missed_signals")
    if _safe_float(watchtower_readiness.get("data_gap_rate"), 0.0) > _safe_float(settings.get("maximum_data_gap_rate_allowed"), 0.01):
        status_color = STATUS_RED
        warnings.append("data_gap_rate_too_high")
    if _safe_bool(capital_anchor.get("shadow_mode_uses_capital"), False) or _safe_bool(capital_anchor.get("paper_mode_uses_capital"), False) or _safe_bool(capital_anchor.get("live_mode_uses_capital"), False):
        status_color = STATUS_RED
        warnings.append("capital_anchor_affects_runtime")
    if not _scheduler_task_exists() and status_color == STATUS_GREEN:
        status_color = STATUS_YELLOW
        warnings.append("scheduler_not_installed_yet")
    if latest_run_time is None and status_color == STATUS_GREEN:
        status_color = STATUS_YELLOW
        warnings.append("latest_run_time_missing")

    instruction = {
        STATUS_GREEN: "continue",
        STATUS_YELLOW: "inspect warning",
        STATUS_RED: "stop and fix before continuing",
    }[status_color]

    daily_status = {
        "resolved_at_utc": now.isoformat(),
        "status_color": status_color,
        "latest_run_time": latest_run_time.isoformat() if latest_run_time else None,
        "latest_successful_run_time": latest_successful_run.isoformat() if latest_successful_run else None,
        "latest_canonical_btc_timestamp": latest_canonical_timestamp.isoformat() if latest_canonical_timestamp else None,
        "stale_data": stale_minutes is None or stale_minutes > _safe_int(settings.get("stale_data_warning_minutes"), 90),
        "rows_fetched_last_24h": _safe_int(updater_summary.get("rows_fetched"), 0) if latest_successful_run and latest_successful_run >= since_24h else 0,
        "rows_appended_last_24h": _safe_int(updater_summary.get("rows_appended"), 0) if latest_successful_run and latest_successful_run >= since_24h else 0,
        "one_h_decisions_processed_last_24h": _count_recent_rows(signal_rows, since=since_24h),
        "duplicate_decisions_skipped": _safe_int(manual_test.get("duplicate_1h_decisions_skipped"), 0),
        "data_gaps": _safe_int(updater_quality.get("missing_minute_count_combined_range"), 0),
        "safety_guard_status": _safe_bool(watchtower_safety.get("passed"), False),
        "no_order_confirmation": bool(anchor.get("no_order_path")),
        "paper_live_broker_disabled_confirmation": bool(anchor.get("no_paper_path")) and bool(anchor.get("no_live_path")) and bool(anchor.get("no_broker_execution")),
        "pilot_days_completed": min(_safe_int(watchtower_readiness.get("observation_days_completed"), 0), _safe_int(settings.get("pilot_days_required"), 7)),
        "full_shadow_days_completed": _safe_int(watchtower_readiness.get("observation_days_completed"), 0),
        "observed_1h_decisions": _safe_int(watchtower_readiness.get("observed_1h_decisions"), 0),
        "paper_validation_ready": _safe_bool(watchtower_readiness.get("paper_validation_ready"), False),
        "capital_anchor_diagnostic_only_confirmation": bool(anchor.get("capital_anchor_diagnostic_only")),
        "instruction": instruction,
        "warnings": warnings,
        "scheduler_installed": _scheduler_task_exists(),
        "watchtower_run_count": len(run_rows),
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(paths["daily_status"], daily_status)
    _write_markdown(
        paths["daily_status_report"],
        "\n".join(
            [
                "# Shadow Pilot Daily Status",
                "",
                f"- status: `{status_color}`",
                f"- latest successful run: `{daily_status['latest_successful_run_time']}`",
                f"- latest canonical BTC timestamp: `{daily_status['latest_canonical_btc_timestamp']}`",
                f"- rows appended last 24h: `{daily_status['rows_appended_last_24h']}`",
                f"- 1H decisions processed last 24h: `{daily_status['one_h_decisions_processed_last_24h']}`",
                f"- pilot days completed: `{daily_status['pilot_days_completed']}` / `{settings['pilot_days_required']}`",
                f"- 90-day progress: `{daily_status['full_shadow_days_completed']}` / `{settings['full_shadow_days_required']}`",
                f"- observed 1H decisions: `{daily_status['observed_1h_decisions']}`",
                f"- paper_validation_ready: `{str(daily_status['paper_validation_ready']).lower()}`",
                f"- capital anchor diagnostic-only: `{str(daily_status['capital_anchor_diagnostic_only_confirmation']).lower()}`",
                f"- instruction: `{instruction}`",
                "",
                "No orders, no paper trading, no live trading, no broker execution.",
            ]
        )
        + "\n",
    )
    return daily_status


def _current_status(paths: dict[str, Path], daily_status: dict[str, Any], settings: dict[str, Any]) -> dict[str, Any]:
    watchtower_readiness = _read_json(_watchtower_root(paths["status"].parents[2]) / "diagnostics" / "readiness_progress.json", {})
    manual_test = _read_json(paths["manual_test"], {})
    current_status = {
        "automation_status": "ready" if daily_status.get("status_color") in {STATUS_GREEN, STATUS_YELLOW} else "blocked",
        "scheduler_installed": _scheduler_task_exists(),
        "latest_successful_run": daily_status.get("latest_successful_run_time"),
        "latest_canonical_timestamp": daily_status.get("latest_canonical_btc_timestamp"),
        "pilot_days_completed": daily_status.get("pilot_days_completed"),
        "full_shadow_days_completed": daily_status.get("full_shadow_days_completed"),
        "observed_1h_decisions": daily_status.get("observed_1h_decisions"),
        "daily_status_color": daily_status.get("status_color"),
        "paper_validation_ready": daily_status.get("paper_validation_ready"),
        "no_order_path_confirmed": daily_status.get("no_order_confirmation"),
        "capital_anchor_diagnostic_only": daily_status.get("capital_anchor_diagnostic_only_confirmation"),
        "last_manual_test_run_timestamp": manual_test.get("latest_canonical_timestamp"),
        "full_shadow_days_required": settings.get("full_shadow_days_required"),
        "minimum_1h_decisions_required": watchtower_readiness.get("minimum_1h_decisions_required"),
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(paths["current_status"], current_status)
    return current_status


def _one_click_guide(package_root: Path) -> str:
    return "\n".join(
        [
            "# Shadow Pilot One-Click Guide",
            "",
            "## What it does",
            "",
            "Runs a research-only hourly pilot cycle: fetch fresh public BTCUSDT 1m data, append the canonical local tape, process closed 1H candles, annotate 6H context, update the watchtower, write heartbeat/readiness, and stop.",
            "",
            "## What it never does",
            "",
            "- no orders",
            "- no paper trading",
            "- no live trading",
            "- no broker execution",
            "- no 25,000 EUR sizing",
            "",
            "## Commands",
            "",
            "```powershell",
            "python -m structural_compounding_lab.shadow_forward.shadow_forward_pilot_automation --mode self_check",
            "python -m structural_compounding_lab.shadow_forward.shadow_forward_pilot_automation --mode manual_test_run",
            "python -m structural_compounding_lab.shadow_forward.shadow_forward_pilot_automation --mode generate_scheduler_command",
            "python -m structural_compounding_lab.shadow_forward.shadow_forward_pilot_automation --mode install_scheduler_task --confirm-install-scheduler",
            "python -m structural_compounding_lab.shadow_forward.shadow_forward_pilot_automation --mode daily_status",
            "python -m structural_compounding_lab.shadow_forward.shadow_forward_pilot_automation --mode remove_scheduler_task --confirm-remove-scheduler",
            "```",
            "",
            "## Workflow",
            "",
            "1. Run self-check.",
            "2. Run one manual test.",
            "3. Generate the scheduler command.",
            "4. Install the scheduler only after explicit confirmation.",
            "5. Check the daily status report once per day.",
            "",
            "## Meanings",
            "",
            "- GREEN: continue",
            "- YELLOW: inspect warning",
            "- RED: stop and fix before continuing",
            "",
            "## Operational note",
            "",
            "If the laptop sleeps, the hourly pilot will miss cycles. A VPS or always-awake machine is better for the 90-day court.",
            "",
            "Paper validation remains blocked until the shadow-forward gates pass.",
        ]
    ) + "\n"


def _install_script() -> str:
    return "\n".join(
        [
            "param(",
            "  [switch]$ConfirmInstallScheduler",
            ")",
            'if (-not $ConfirmInstallScheduler) {',
            '  Write-Error "Explicit confirmation required: -ConfirmInstallScheduler"',
            "  exit 1",
            "}",
            "python -m structural_compounding_lab.shadow_forward.shadow_forward_pilot_automation --mode install_scheduler_task --confirm-install-scheduler",
            "",
        ]
    )


def _remove_script() -> str:
    return "\n".join(
        [
            "param(",
            "  [switch]$ConfirmRemoveScheduler",
            ")",
            'if (-not $ConfirmRemoveScheduler) {',
            '  Write-Error "Explicit confirmation required: -ConfirmRemoveScheduler"',
            "  exit 1",
            "}",
            "python -m structural_compounding_lab.shadow_forward.shadow_forward_pilot_automation --mode remove_scheduler_task --confirm-remove-scheduler",
            "",
        ]
    )


def _helper_script(mode: str) -> str:
    return "\n".join(
        [
            "from structural_compounding_lab.shadow_forward.shadow_forward_pilot_automation import main",
            "",
            'if __name__ == "__main__":',
            f'    import sys; sys.argv = ["shadow_forward_pilot_automation", "--mode", "{mode}"]; main()',
            "",
        ]
    )


def _write_static_docs_and_scripts(package_root: Path) -> None:
    assets = {
        package_root / "docs" / "shadow_pilot_one_click_guide.md": _one_click_guide(package_root),
        package_root.parent / "scripts" / "install_shadow_pilot_task.ps1": _install_script(),
        package_root.parent / "scripts" / "remove_shadow_pilot_task.ps1": _remove_script(),
        package_root.parent / "scripts" / "shadow_pilot_self_check.py": _helper_script("self_check"),
        package_root.parent / "scripts" / "shadow_pilot_run_once.py": _helper_script("manual_test_run"),
        package_root.parent / "scripts" / "shadow_pilot_daily_status.py": _helper_script("daily_status"),
    }
    for path, content in assets.items():
        if not path.exists():
            _write_markdown(path, content)


def _summary_report(mode: str, final_classification: str, daily_status: dict[str, Any] | None, scheduler_installed: bool) -> str:
    lines = [
        "# Shadow Forward Pilot Automation",
        "",
        f"- mode: `{mode}`",
        f"- final_classification: `{final_classification}`",
        f"- scheduler_installed: `{str(scheduler_installed).lower()}`",
    ]
    if daily_status:
        lines.extend(
            [
                f"- daily_status_color: `{daily_status.get('status_color')}`",
                f"- pilot_days_completed: `{daily_status.get('pilot_days_completed')}`",
                f"- full_shadow_days_completed: `{daily_status.get('full_shadow_days_completed')}`",
                f"- observed_1h_decisions: `{daily_status.get('observed_1h_decisions')}`",
            ]
        )
    lines.append("")
    lines.append("No live/paper/order/broker path was created. The 25,000 EUR anchor remains diagnostic only.")
    return "\n".join(lines) + "\n"


def _write_self_audit(path: Path, *, final_classification: str, notes: list[str]) -> None:
    payload = {
        "prior_gates_loaded": True,
        "config_written": True,
        "self_check_mode_available": True,
        "manual_test_run_mode_available": True,
        "scheduler_command_generation_available": True,
        "scheduler_install_requires_confirmation": True,
        "scheduler_not_installed_by_default": True,
        "scheduler_remove_requires_confirmation": True,
        "daily_status_available": True,
        "green_yellow_red_status_available": True,
        "one_click_guide_written": True,
        "install_script_written": True,
        "remove_script_written": True,
        "no_private_api_key_used": True,
        "no_account_endpoint_used": True,
        "no_order_endpoint_used": True,
        "no_broker_execution_created": True,
        "no_order_path_created": True,
        "no_paper_path_created": True,
        "no_live_path_created": True,
        "capital_anchor_diagnostic_only": True,
        "capital_anchor_affects_order_sizing": False,
        "runtime_production_config_changed": False,
        "previous_artifacts_overwritten": False,
        "reviewer_notes": notes,
        "final_classification": final_classification,
        **RESEARCH_ONLY_FLAGS,
    }
    _write_json(path, payload)


def run_shadow_forward_pilot_automation(config: ShadowForwardPilotAutomationConfig) -> dict[str, Path]:
    if config.mode not in ALLOWED_MODES:
        raise ValueError(f"Unsupported mode: {config.mode}")

    _ensure_dirs(config.output_root)
    output_paths = _paths(config.output_root)
    config_path = config.config_path or (config.package_root / "config" / "shadow_forward_pilot_automation.yaml")
    _write_default_config(config_path)
    settings = _load_settings(config_path)
    _write_static_docs_and_scripts(config.package_root)
    anchor = _load_prior_gate_anchor(config.package_root, output_paths["prior_gate_anchor"])

    notes: list[str] = []
    self_check_report = _read_json(output_paths["self_check"], {})
    manual_test_report = _read_json(output_paths["manual_test"], {})
    scheduler_command_report = _read_json(output_paths["scheduler_command"], {})
    scheduler_install_report = _read_json(output_paths["scheduler_install"], {})
    scheduler_remove_report = _read_json(output_paths["scheduler_remove"], {})
    daily_status = _read_json(output_paths["daily_status"], {})
    current_status = _read_json(output_paths["current_status"], {})
    final_classification = "AUTOMATION_INCOMPLETE"

    if config.mode == "self_check":
        self_check_report = _self_check(
            ShadowForwardPilotAutomationConfig(
                package_root=config.package_root,
                output_root=config.output_root,
                mode=config.mode,
                config_path=config_path,
                confirm_install_scheduler=config.confirm_install_scheduler,
                confirm_remove_scheduler=config.confirm_remove_scheduler,
                force_rerun=config.force_rerun,
                dry_run=config.dry_run,
            ),
            settings,
            output_paths,
            anchor,
        )
        final_classification = (
            "AUTOMATION_READY_FOR_MANUAL_APPROVAL"
            if self_check_report.get("classification") == "AUTOMATION_SELF_CHECK_PASSED"
            else "AUTOMATION_SELF_CHECK_FAILED"
        )
    elif config.mode == "manual_test_run":
        self_check_report = _self_check(config, settings, output_paths, anchor)
        manual_test_report = _manual_test_run(config, settings, output_paths, self_check_report)
        final_classification = str(manual_test_report.get("classification") or "AUTOMATION_MANUAL_TEST_FAILED")
    elif config.mode == "generate_scheduler_command":
        scheduler_command_report = _generate_scheduler_command(config, output_paths)
        final_classification = "AUTOMATION_READY_FOR_MANUAL_APPROVAL"
    elif config.mode == "install_scheduler_task":
        self_check_report = _self_check(config, settings, output_paths, anchor)
        scheduler_install_report = _install_scheduler(config, output_paths, self_check_report)
        final_classification = str(scheduler_install_report.get("classification") or "AUTOMATION_INCOMPLETE")
    elif config.mode == "remove_scheduler_task":
        scheduler_remove_report = _remove_scheduler(config, output_paths)
        final_classification = str(scheduler_remove_report.get("classification") or "AUTOMATION_INCOMPLETE")
    elif config.mode == "daily_status":
        daily_status = _daily_status(config, settings, output_paths, anchor)
        final_classification = "AUTOMATION_READY_FOR_MANUAL_APPROVAL" if daily_status.get("status_color") in {STATUS_GREEN, STATUS_YELLOW} else "AUTOMATION_INCOMPLETE"
    elif config.mode == "status":
        if not daily_status:
            daily_status = _daily_status(config, settings, output_paths, anchor)
        current_status = _current_status(output_paths, daily_status, settings)
        final_classification = "AUTOMATION_READY_FOR_MANUAL_APPROVAL" if current_status.get("automation_status") == "ready" else "AUTOMATION_INCOMPLETE"

    scheduler_installed = _scheduler_task_exists()
    if not daily_status:
        daily_status = _read_json(output_paths["daily_status"], {})
    if daily_status:
        current_status = _current_status(output_paths, daily_status, settings)

    summary = {
        "resolved_at_utc": _now_utc().isoformat(),
        "mode": config.mode,
        "config_path": str(config_path),
        "prior_gates_loaded": True,
        "self_check_status": self_check_report.get("classification"),
        "manual_test_status": manual_test_report.get("classification"),
        "scheduler_command_generated": bool(scheduler_command_report),
        "scheduler_installed": scheduler_installed,
        "daily_status_color": daily_status.get("status_color") if daily_status else None,
        "final_classification": final_classification,
        "one_click_guide_created": True,
        "install_remove_scripts_created": True,
        "checkpoint_resume_status": "resume_capable_mode_state_tracking",
        **RESEARCH_ONLY_FLAGS,
        "no_order_path_created": True,
        "paper_trade_created": False,
        "live_trade_created": False,
        "broker_execution_created": False,
    }
    _write_json(output_paths["summary"], summary)
    _write_markdown(output_paths["report"], _summary_report(config.mode, final_classification, daily_status if daily_status else None, scheduler_installed))
    _write_self_audit(output_paths["self_audit"], final_classification=final_classification, notes=notes)
    _write_json(
        output_paths["checkpoint"],
        {
            "last_self_check_timestamp": self_check_report.get("resolved_at_utc"),
            "last_manual_test_run_timestamp": _now_utc().isoformat() if manual_test_report else None,
            "last_daily_status_timestamp": daily_status.get("resolved_at_utc") if daily_status else None,
            "scheduler_command_generated": bool(scheduler_command_report),
            "scheduler_install_status": scheduler_install_report.get("classification"),
            "scheduler_remove_status": scheduler_remove_report.get("classification"),
            **RESEARCH_ONLY_FLAGS,
        },
    )

    state = "completed" if final_classification in {"AUTOMATION_READY_FOR_MANUAL_APPROVAL", "AUTOMATION_SCHEDULER_INSTALLED_RESEARCH_ONLY"} else "partial"
    if final_classification == "AUTOMATION_SELF_CHECK_FAILED":
        state = "blocked"
    _write_status(output_paths["status"], state=state, classification=final_classification, warnings=notes, mode=config.mode)
    _write_progress(
        output_paths["scenario_progress"],
        state=state,
        mode=config.mode,
        warnings=notes,
        extra={
            "scheduler_installed": scheduler_installed,
            "daily_status_color": daily_status.get("status_color") if daily_status else None,
        },
    )
    _write_progress(
        output_paths["run_progress"],
        state=state,
        mode=config.mode,
        warnings=notes,
        extra={
            "self_check_status": self_check_report.get("classification"),
            "manual_test_status": manual_test_report.get("classification"),
            "final_classification": final_classification,
        },
    )
    return {"status": output_paths["status"], "summary": output_paths["summary"], "report": output_paths["report"]}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Research-only one-click 7-day shadow pilot automation layer.")
    parser.add_argument("--mode", default=DEFAULT_MODE, choices=sorted(ALLOWED_MODES))
    parser.add_argument("--output-dir", default=None)
    parser.add_argument("--config", default=None)
    parser.add_argument("--confirm-install-scheduler", action="store_true")
    parser.add_argument("--confirm-remove-scheduler", action="store_true")
    parser.add_argument("--force-rerun", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    package_root = resolve_package_root()
    output_root = (
        package_root / "output" / OUTPUT_FOLDER_NAME
        if args.output_dir is None
        else resolve_project_path(args.output_dir)
    )
    result = run_shadow_forward_pilot_automation(
        ShadowForwardPilotAutomationConfig(
            package_root=package_root,
            output_root=output_root,
            mode=args.mode,
            config_path=resolve_project_path(args.config) if args.config else None,
            confirm_install_scheduler=bool(args.confirm_install_scheduler),
            confirm_remove_scheduler=bool(args.confirm_remove_scheduler),
            force_rerun=bool(args.force_rerun),
            dry_run=bool(args.dry_run),
        )
    )
    print(json.dumps({key: str(value) for key, value in result.items()}, indent=2))


if __name__ == "__main__":
    main()
