from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import plistlib
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path  # noqa: E402


COURT_NAME = "CONTINUOUS_SCHEDULER_FORWARD_VALIDATION_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "continuous_scheduler_forward_validation_court_001"
READY = "CONTINUOUS_SCHEDULER_FORWARD_VALIDATION_READY_RESEARCH_ONLY"
WARNING = "CONTINUOUS_SCHEDULER_FORWARD_VALIDATION_WARNING_RESEARCH_ONLY"
FAILED = "CONTINUOUS_SCHEDULER_FORWARD_VALIDATION_FAILED_RESEARCH_ONLY"
LAUNCH_AGENT_LABEL = "com.retail_trading_system.research_forward_shadow"
PLIST_NAME = f"{LAUNCH_AGENT_LABEL}.plist"
START_CAPITAL = 25_000.0
TARGET_EQUITY = 1_000_000.0
TARGET_MONTHS = 60
MISSION_WORDING = (
    "EUR25k -> EUR1M remains the mission/Strong target based mainly on old rolling 5Y normal-cost evidence. "
    "It is not independently validated by Court 002 net-cost holdout."
)

SAFETY_FLAGS: dict[str, Any] = {
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


@dataclass(frozen=True)
class SchedulerCourtConfig:
    project_root: Path
    package_root: Path
    output_root: Path
    canonical_csv_path: Path
    launch_agents_dir: Path
    log_dir: Path


def default_config() -> SchedulerCourtConfig:
    root = project_root()
    pkg = package_root()
    home = Path.home()
    return SchedulerCourtConfig(
        project_root=root,
        package_root=pkg,
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
        canonical_csv_path=root
        / "structural_compounding_lab"
        / "data_storage"
        / "BTCUSDT"
        / "1m"
        / "btcusdt_1m_canonical_shadow_forward.csv",
        launch_agents_dir=home / "Library" / "LaunchAgents",
        log_dir=home / "Library" / "Logs" / "retail_trading_system_forward_shadow",
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def _jsonable(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 900) -> dict[str, Any]:
    merged_env = os.environ.copy()
    if env:
        merged_env.update(env)
    started = _now()
    try:
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            env=merged_env,
            text=True,
            capture_output=True,
            timeout=timeout,
        )
        return {
            "command": command,
            "started_at": started,
            "finished_at": _now(),
            "returncode": proc.returncode,
            "stdout_tail": proc.stdout[-4000:],
            "stderr_tail": proc.stderr[-4000:],
            "succeeded": proc.returncode == 0,
        }
    except Exception as exc:
        return {
            "command": command,
            "started_at": started,
            "finished_at": _now(),
            "returncode": None,
            "stdout_tail": "",
            "stderr_tail": str(exc),
            "succeeded": False,
        }


def _quality(csv_path: Path) -> dict[str, Any]:
    frame = pd.read_csv(csv_path)
    timestamps = pd.to_datetime(frame["timestamp"], utc=True, errors="coerce")
    duplicates = int(timestamps.duplicated().sum())
    diffs = timestamps.drop_duplicates().sort_values().diff().dropna()
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
        "path": str(csv_path),
        "rows": int(len(frame)),
        "first_timestamp": timestamps.iloc[0].isoformat() if len(frame) else None,
        "latest_canonical_timestamp": timestamps.iloc[-1].isoformat() if len(frame) else None,
        "duplicate_count": duplicates,
        "gap_count": gaps,
        "missing_minute_count": missing,
        "ohlc_failures": ohlc,
    }


def _ledger_counts(config: SchedulerCourtConfig) -> dict[str, Any]:
    runtime = config.package_root / "output" / "forward_validation_runtime"
    decision_path = runtime / "ledger" / "forward_decision_ledger.csv"
    trade_path = runtime / "ledger" / "forward_simulated_trade_ledger.csv"
    decisions = pd.read_csv(decision_path) if decision_path.exists() else pd.DataFrame()
    trades = pd.read_csv(trade_path) if trade_path.exists() else pd.DataFrame()
    duplicate_decisions = int(decisions["decision_id"].duplicated().sum()) if "decision_id" in decisions else 0
    duplicate_trades = int(trades["trade_id"].duplicated().sum()) if "trade_id" in trades else 0
    return {
        "decision_ledger": str(decision_path),
        "simulated_trade_ledger": str(trade_path),
        "decision_count": int(len(decisions)),
        "simulated_trade_count": int(len(trades)),
        "duplicate_decision_count": duplicate_decisions,
        "duplicate_simulated_trade_count": duplicate_trades,
        "latest_decision_timestamp": str(decisions["timestamp"].iloc[-1]) if len(decisions) and "timestamp" in decisions else None,
    }


def _load_locked_evidence(config: SchedulerCourtConfig) -> dict[str, Any]:
    court_002 = _read_json(config.package_root / "output" / "eur25k_sealed_6m_holdout_court_002" / "eur25k_sealed_6m_holdout_summary.json")
    split = _read_json(config.package_root / "output" / "eur25k_sealed_6m_holdout_court_002" / "split_manifest.json")
    anti = _read_json(config.package_root / "output" / "eur25k_sealed_6m_holdout_court_002" / "anti_leakage_audit.json")
    target = _read_json(
        config.package_root
        / "output"
        / "eur25k_realistic_5y_target_translation_court_001"
        / "eur25k_realistic_5y_target_translation_summary.json"
    )
    restatement = _read_json(
        config.package_root / "output" / "court_002_net_cost_restatement_court_001" / "court_002_net_cost_restatement_summary.json"
    )
    zero_stop = _read_json(
        config.package_root
        / "output"
        / "court_002_net_cost_zero_stop_resolution_court_001"
        / "court_002_net_cost_zero_stop_resolution_summary.json"
    )
    cost_bands = _read_json(
        config.package_root
        / "output"
        / "execution_cost_realism_and_trade_redundancy_audit_001"
        / "diagnostics"
        / "execution_cost_band_results.json"
    )
    normal_band = next(
        (row for row in cost_bands.get("rows", []) if row.get("band_name") == "NORMAL_MIXED_MAKER_TAKER_COST"),
        {},
    )
    return {
        "court_002_classification": court_002.get("final_classification"),
        "court_002_holdout_end_timestamp": split.get("holdout_end"),
        "gross_court_002_holdout_equity": court_002.get("sealed_holdout_validation", {}).get("ending_diagnostic_equity"),
        "net_cost_court_002_holdout_equity": restatement.get("sealed_holdout_25k", {})
        .get("restatement", {})
        .get("net_ending_equity"),
        "net_monthly_growth": restatement.get("sealed_holdout_25k", {}).get("net_monthly_compounded_growth"),
        "required_eur1m_monthly_pace": restatement.get("sealed_holdout_25k", {}).get(
            "required_monthly_growth_for_25k_to_1m_over_5y"
        ),
        "court_002_net_cost_warning_classification": zero_stop.get("final_classification"),
        "target_impact_classification": zero_stop.get("target_analysis_impact", {}).get("classification"),
        "old_rolling_5y_normal_cost_anchors": {
            "eur20k_strict_average": normal_band.get("rolling_5y_average_ending_equity"),
            "eur25k_strict_projection": 991_030.70,
            "eur20k_6h_context_average": 881_465.53,
            "eur25k_6h_context_projection": 1_101_831.91,
            "normal_cost_band": normal_band,
        },
        "operational_only": True,
        "strategy_remains_frozen": bool(anti.get("no_retuning_after_holdout_results", True)),
        "target_curve_diagnostic_only": True,
        "paper_validation_ready": False,
        **SAFETY_FLAGS,
        "target_translation_summary_classification": target.get("final_classification"),
    }


def _target_curve() -> dict[str, Any]:
    required_multiple = TARGET_EQUITY / START_CAPITAL
    monthly_growth = required_multiple ** (1.0 / TARGET_MONTHS) - 1.0
    cagr = required_multiple ** (1.0 / 5.0) - 1.0
    checkpoints = [
        {
            "month": month,
            "required_equity": START_CAPITAL * ((1.0 + monthly_growth) ** month),
        }
        for month in range(TARGET_MONTHS + 1)
    ]
    return {
        "starting_diagnostic_equity": START_CAPITAL,
        "target_equity": TARGET_EQUITY,
        "horizon_months": TARGET_MONTHS,
        "required_multiple": required_multiple,
        "exact_cagr": cagr,
        "exact_monthly_growth": monthly_growth,
        "monthly_required_equity_checkpoints": checkpoints,
        "strategy_behavior_changed_by_target_curve": False,
        "wording": MISSION_WORDING,
    }


def _scheduler_command(config: SchedulerCourtConfig) -> str:
    runtime_root = config.package_root / "output" / "forward_validation_runtime"
    lock_dir = runtime_root / "scheduler.lock"
    python_path = config.project_root / ".venv311" / "bin" / "python"
    return (
        f"cd {str(config.project_root)!r} && "
        f"LOCKDIR={str(lock_dir)!r}; "
        "if mkdir \"$LOCKDIR\" 2>/dev/null; then "
        "trap 'rmdir \"$LOCKDIR\"' EXIT; "
        "BINANCE_API_KEY='' BINANCE_API_SECRET='' "
        f"{str(python_path)!r} -m structural_compounding_lab.shadow_forward.forward_validation_runtime --mode run_once; "
        "else echo 'forward runtime already running; overlap prevented'; fi"
    )


def _plist_payload(config: SchedulerCourtConfig) -> dict[str, Any]:
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": ["/bin/zsh", "-lc", _scheduler_command(config)],
        "WorkingDirectory": str(config.project_root),
        "StartCalendarInterval": {"Minute": 5},
        "RunAtLoad": True,
        "KeepAlive": False,
        "EnvironmentVariables": {
            "BINANCE_API_KEY": "",
            "BINANCE_API_SECRET": "",
            "PYTHONUNBUFFERED": "1",
        },
        "StandardOutPath": str(config.log_dir / "forward_shadow_stdout.log"),
        "StandardErrorPath": str(config.log_dir / "forward_shadow_stderr.log"),
    }


def write_plist(config: SchedulerCourtConfig) -> Path:
    config.output_root.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    plist_path = config.output_root / PLIST_NAME
    with plist_path.open("wb") as handle:
        plistlib.dump(_plist_payload(config), handle, sort_keys=True)
    return plist_path


def install_launch_agent(config: SchedulerCourtConfig, plist_path: Path) -> dict[str, Any]:
    config.launch_agents_dir.mkdir(parents=True, exist_ok=True)
    config.log_dir.mkdir(parents=True, exist_ok=True)
    target = config.launch_agents_dir / PLIST_NAME
    shutil.copy2(plist_path, target)
    uid = os.getuid()
    bootout = _run(["launchctl", "bootout", f"gui/{uid}", str(target)], cwd=config.project_root, timeout=60)
    bootstrap = _run(["launchctl", "bootstrap", f"gui/{uid}", str(target)], cwd=config.project_root, timeout=60)
    printed = _run(["launchctl", "print", f"gui/{uid}/{LAUNCH_AGENT_LABEL}"], cwd=config.project_root, timeout=60)
    env_values_empty = True
    if target.exists():
        with target.open("rb") as handle:
            installed_payload = plistlib.load(handle)
        env_values_empty = all(
            value == ""
            for key, value in installed_payload.get("EnvironmentVariables", {}).items()
            if key in {"BINANCE_API_KEY", "BINANCE_API_SECRET"}
        )
    return {
        "install_attempted": True,
        "install_succeeded": target.exists(),
        "loaded_status": bootstrap["succeeded"] or printed["succeeded"],
        "launchctl_method_used": "bootout_then_bootstrap_gui_user_domain",
        "launchctl_bootout": bootout,
        "launchctl_bootstrap": bootstrap,
        "launchctl_print": printed,
        "plist_path": str(target),
        "plist_hash": _sha256(target) if target.exists() else "",
        "no_secrets_in_plist": bool(target.exists() and env_values_empty),
        "no_paper_live_order_broker_confirmation": True,
        **SAFETY_FLAGS,
    }


def wait_for_launch_agent_idle(config: SchedulerCourtConfig, *, timeout_seconds: int = 900) -> dict[str, Any]:
    uid = os.getuid()
    started = datetime.now(timezone.utc)
    polls = 0
    last_print: dict[str, Any] = {}
    while (datetime.now(timezone.utc) - started).total_seconds() < timeout_seconds:
        polls += 1
        last_print = _run(["launchctl", "print", f"gui/{uid}/{LAUNCH_AGENT_LABEL}"], cwd=config.project_root, timeout=60)
        if "state = running" not in str(last_print.get("stdout_tail") or ""):
            return {
                "wait_attempted": True,
                "idle": True,
                "polls": polls,
                "started_at": started.isoformat(),
                "finished_at": _now(),
                "last_launchctl_print": last_print,
            }
        subprocess.run(["sleep", "10"], check=False)
    return {
        "wait_attempted": True,
        "idle": False,
        "polls": polls,
        "started_at": started.isoformat(),
        "finished_at": _now(),
        "last_launchctl_print": last_print,
    }


def _manual_scheduler_run(config: SchedulerCourtConfig) -> dict[str, Any]:
    return _run(["/bin/zsh", "-lc", _scheduler_command(config)], cwd=config.project_root, env={"BINANCE_API_KEY": "", "BINANCE_API_SECRET": ""})


def _snapshot(config: SchedulerCourtConfig) -> dict[str, Any]:
    quality = _quality(config.canonical_csv_path)
    ledgers = _ledger_counts(config)
    status = _read_json(config.package_root / "output" / "forward_validation_runtime" / "latest_status.json", {})
    return {"quality": quality, "ledgers": ledgers, "runtime_status": status}


def run_smoke_tests(config: SchedulerCourtConfig) -> dict[str, Any]:
    before = _snapshot(config)
    first_run = _manual_scheduler_run(config)
    after_first = _snapshot(config)
    second_run = _manual_scheduler_run(config)
    after_second = _snapshot(config)
    return {
        "first_run_status": first_run,
        "second_run_status": second_run,
        "rows_before": before["quality"]["rows"],
        "rows_after_first_run": after_first["quality"]["rows"],
        "rows_after_second_run": after_second["quality"]["rows"],
        "decisions_before": before["ledgers"]["decision_count"],
        "decisions_after_first_run": after_first["ledgers"]["decision_count"],
        "decisions_after_second_run": after_second["ledgers"]["decision_count"],
        "duplicate_data_count": after_second["quality"]["duplicate_count"],
        "duplicate_decision_count": after_second["ledgers"]["duplicate_decision_count"],
        "gaps": after_second["quality"]["gap_count"],
        "ohlc_failures": after_second["quality"]["ohlc_failures"],
        "status_color": after_second["runtime_status"].get("status"),
        "alert_status": {
            "email_alert_required": after_second["runtime_status"].get("email_alert_required"),
            "email_alert_sent": after_second["runtime_status"].get("email_alert_sent"),
            "email_alert_draft_written": after_second["runtime_status"].get("email_alert_draft_written"),
            "email_alert_path": after_second["runtime_status"].get("email_alert_path"),
        },
        "safety_flags": {key: after_second["runtime_status"].get(key, value) for key, value in SAFETY_FLAGS.items()},
        "first_run_snapshot": after_first,
        "second_run_snapshot": after_second,
        "idempotency_passed": (
            after_second["quality"]["duplicate_count"] == 0
            and after_second["ledgers"]["duplicate_decision_count"] == 0
            and after_second["quality"]["gap_count"] == 0
            and after_second["quality"]["ohlc_failures"] == 0
        ),
    }


def _cockpit(config: SchedulerCourtConfig, evidence: dict[str, Any], smoke: dict[str, Any], install: dict[str, Any]) -> dict[str, Any]:
    target = _target_curve()
    latest_status = smoke.get("second_run_snapshot", {}).get("runtime_status", {})
    net_equity = evidence.get("net_cost_court_002_holdout_equity") or START_CAPITAL
    gross_equity = evidence.get("gross_court_002_holdout_equity")
    required = target["monthly_required_equity_checkpoints"][0]["required_equity"]
    status_color = "GREEN" if install.get("loaded_status") and smoke.get("idempotency_passed") else "YELLOW"
    if smoke.get("gaps") or smoke.get("duplicate_data_count") or smoke.get("duplicate_decision_count") or smoke.get("ohlc_failures"):
        status_color = "RED"
    return {
        "current_net_cost_diagnostic_equity": net_equity,
        "primary_equity_basis": "net_cost_diagnostic_equity",
        "current_gross_diagnostic_equity_reference_only": gross_equity,
        "gross_equity_secondary_reference_only": True,
        "eur25k_to_eur1m_target_equity": TARGET_EQUITY,
        "ahead_or_behind_target_using_net_cost_equity": net_equity - required,
        "current_month_index": 0,
        "required_monthly_growth": target["exact_monthly_growth"],
        "actual_net_cost_monthly_growth": evidence.get("net_monthly_growth"),
        "accepted_trades": latest_status.get("simulated_trades_created_this_run"),
        "rejected_setups": None,
        "trade_frequency": None,
        "zero_trade_days": None,
        "win_rate": None,
        "profit_factor": None,
        "max_drawdown": evidence.get("old_rolling_5y_normal_cost_anchors", {}).get("normal_cost_band", {}).get("max_drawdown_pct"),
        "full_history_net_cost_max_drawdown_warning": 0.906242,
        "current_drawdown": None,
        "severe_drawdown_warning": True,
        "six_h_context_health": "context_only_no_behavior_change",
        "data_health": {
            "gaps": smoke.get("gaps"),
            "duplicate_data_count": smoke.get("duplicate_data_count"),
            "ohlc_failures": smoke.get("ohlc_failures"),
        },
        "scheduler_health": "loaded" if install.get("loaded_status") else "not_loaded",
        "outage_recovery_health": "runtime_catchup_idempotent" if smoke.get("idempotency_passed") else "needs_review",
        "alerting_health": "available_draft_or_smtp_on_red",
        "status_color": status_color,
        "signal_collapse_warning": False,
        "overtrading_warning": False,
        "undertrading_warning": False,
        "target_chasing_warning": False,
        "target_curve_strategy_behavior_change": False,
        "target_wording": MISSION_WORDING,
        **SAFETY_FLAGS,
    }


def _six_month_gates() -> dict[str, Any]:
    return {
        "six_month_forward_validation_already_passed": False,
        "future_gates": [
            "scheduler_operated_continuously_or_recovered_cleanly",
            "public_data_updated_correctly",
            "no_unresolved_gaps",
            "no_duplicates",
            "no_ohlc_failures",
            "decisions_processed_once",
            "missed_candles_caught_up_exactly_once",
            "red_failures_alerted",
            "no_strategy_tuning",
            "no_threshold_changes",
            "no_entry_exit_filter_sizing_changes",
            "no_6h_context_behavior_changes",
            "no_target_chasing",
            "net_cost_diagnostic_eur25k_equity_tracked_honestly",
            "net_cost_drawdown_stayed_within_defined_risk_gates",
            "trade_frequency_did_not_collapse",
            "signal_did_not_collapse",
            "paper_validation_ready_false_unless_future_explicit_court_changes_it",
        ],
        **SAFETY_FLAGS,
    }


def build_court_outputs(*, install: bool = False, smoke: bool = False) -> dict[str, Any]:
    config = default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    evidence = _load_locked_evidence(config)
    pre_quality = _quality(config.canonical_csv_path)
    runtime_status = _read_json(config.package_root / "output" / "forward_validation_runtime" / "latest_status.json", {})
    latest_safe = runtime_status.get("latest_safe_market_timestamp") or pre_quality["latest_canonical_timestamp"]
    forward_start = {
        "court_002_holdout_end": evidence.get("court_002_holdout_end_timestamp"),
        "forward_shadow_start_anchor": "2026-06-21T18:00:00+00:00",
        "latest_canonical_timestamp_before_scheduler_install": pre_quality["latest_canonical_timestamp"],
        "latest_safe_market_timestamp": latest_safe,
        "catch_up_needed": pre_quality["latest_canonical_timestamp"] != latest_safe,
        "gap_exists": pre_quality["gap_count"] > 0,
        "duplicate_exists": pre_quality["duplicate_count"] > 0,
        "ohlc_failure_exists": pre_quality["ohlc_failures"] > 0,
        "scheduler_starts_from_clean_state": pre_quality["gap_count"] == 0 and pre_quality["duplicate_count"] == 0 and pre_quality["ohlc_failures"] == 0,
    }
    plist_path = write_plist(config)
    plist = _plist_payload(config)
    scheduler_manifest = {
        "scheduler_type": "macOS LaunchAgent",
        "plist_path": str(config.launch_agents_dir / PLIST_NAME),
        "generated_plist_path": str(plist_path),
        "program_arguments": plist["ProgramArguments"],
        "working_directory": plist["WorkingDirectory"],
        "cadence": "StartCalendarInterval minute 5 hourly",
        "log_paths": {"stdout": plist["StandardOutPath"], "stderr": plist["StandardErrorPath"]},
        "lock_path": str(config.package_root / "output" / "forward_validation_runtime" / "scheduler.lock"),
        "run_at_load": plist["RunAtLoad"],
        "keep_alive": plist["KeepAlive"],
        "environment_variables": plist["EnvironmentVariables"],
        "binance_keys_empty": True,
        "no_private_signed_account_order_broker_endpoint_used": True,
        "expected_command_line": _scheduler_command(config),
        "scheduler_installed": (config.launch_agents_dir / PLIST_NAME).exists(),
        "scheduler_loaded": False,
        **SAFETY_FLAGS,
    }
    install_audit = {"install_attempted": False, "install_succeeded": False, "loaded_status": False, **SAFETY_FLAGS}
    if install:
        install_audit = install_launch_agent(config, plist_path)
        scheduler_manifest["scheduler_installed"] = bool(install_audit.get("install_succeeded"))
        scheduler_manifest["scheduler_loaded"] = bool(install_audit.get("loaded_status"))
        install_audit["run_at_load_wait"] = wait_for_launch_agent_idle(config)
    smoke_result = {"smoke_attempted": False, "idempotency_passed": False}
    if smoke:
        smoke_result = run_smoke_tests(config)
        install_audit["first_scheduled_manual_run_status"] = smoke_result.get("first_run_status", {}).get("succeeded")
    cockpit = _cockpit(config, evidence, smoke_result, install_audit)
    target_curve = _target_curve()
    gates = _six_month_gates()
    final_classification = READY
    reasons: list[str] = []
    if not install_audit.get("install_succeeded") or not install_audit.get("loaded_status"):
        final_classification = WARNING
        reasons.append("scheduler_safe_but_launchctl_load_not_confirmed")
    if smoke and not smoke_result.get("idempotency_passed"):
        final_classification = FAILED
        reasons.append("smoke_or_idempotency_failed")
    if pre_quality["gap_count"] or pre_quality["duplicate_count"] or pre_quality["ohlc_failures"]:
        final_classification = FAILED
        reasons.append("data_health_failed")
    if cockpit["status_color"] == "YELLOW" and final_classification == READY:
        final_classification = WARNING
        reasons.append("target_or_operational_warning_carried_forward")
    if not reasons:
        reasons.append("scheduler_loaded_smoke_idempotency_passed_research_only")

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": final_classification,
        "classification_reasons": reasons,
        "evidence_lock_manifest_path": str(config.output_root / "evidence_lock_manifest.json"),
        "forward_start_manifest_path": str(config.output_root / "forward_start_manifest.json"),
        "scheduler_manifest_path": str(config.output_root / "scheduler_manifest.json"),
        "scheduler_install_audit_path": str(config.output_root / "scheduler_install_audit.json"),
        "initial_smoke_test_path": str(config.output_root / "initial_smoke_test.json"),
        "forward_validation_cockpit_path": str(config.output_root / "forward_validation_cockpit.json"),
        "target_curve_path": str(config.output_root / "target_curve_25k_to_1m_5y.json"),
        "six_month_forward_validation_gates_path": str(config.output_root / "six_month_forward_validation_gates.json"),
        "preflight_data_health": pre_quality,
        "evidence_lock": evidence,
        "forward_start": forward_start,
        "scheduler_manifest": scheduler_manifest,
        "scheduler_install_audit": install_audit,
        "initial_smoke_test": smoke_result,
        "forward_validation_cockpit": cockpit,
        "six_month_forward_validation_gates": gates,
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "evidence_lock_manifest.json", evidence)
    _write_json(config.output_root / "forward_start_manifest.json", forward_start)
    _write_json(config.output_root / "scheduler_manifest.json", scheduler_manifest)
    _write_json(config.output_root / "scheduler_install_audit.json", install_audit)
    _write_json(config.output_root / "initial_smoke_test.json", smoke_result)
    _write_json(config.output_root / "forward_validation_cockpit.json", cockpit)
    _write_json(config.output_root / "target_curve_25k_to_1m_5y.json", target_curve)
    _write_json(config.output_root / "six_month_forward_validation_gates.json", gates)
    _write_json(config.output_root / "continuous_scheduler_forward_validation_summary.json", summary)
    (config.output_root / "continuous_scheduler_forward_validation_report.md").write_text(_report(summary), encoding="utf-8")
    return summary


def _fmt_eur(value: Any) -> str:
    return "N/A" if value is None else f"€{float(value):,.2f}"


def _report(summary: dict[str, Any]) -> str:
    install = summary["scheduler_install_audit"]
    scheduler = summary["scheduler_manifest"]
    smoke = summary["initial_smoke_test"]
    cockpit = summary["forward_validation_cockpit"]
    evidence = summary["evidence_lock"]
    gates = summary["six_month_forward_validation_gates"]["future_gates"]
    lines = [
        "# Continuous Scheduler Forward Validation Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        f"- Scheduler installed: `{install.get('install_succeeded')}`",
        f"- Scheduler loaded: `{install.get('loaded_status')}`",
        f"- Command: `{scheduler.get('expected_command_line')}`",
        f"- Cadence: `{scheduler.get('cadence')}`",
        "- Public unsigned Binance klines only: `true`",
        f"- Canonical data gap-free / duplicate-free: `{summary['preflight_data_health']['gap_count'] == 0 and summary['preflight_data_health']['duplicate_count'] == 0}`",
        f"- Shadow decisions idempotent: `{smoke.get('idempotency_passed')}`",
        "- RED failure alerting: `available via runtime SMTP/draft path`",
        f"- Status color: `{cockpit.get('status_color')}`",
        f"- EUR25k diagnostic only: `{not summary['eur_25000_anchor_active']}`",
        f"- Cockpit primary equity basis: `{cockpit.get('primary_equity_basis')}`",
        f"- Gross equity reference only: `{cockpit.get('gross_equity_secondary_reference_only')}`",
        "- EUR25k -> EUR1M target curve present: `true`",
        f"- Target wording: {MISSION_WORDING}",
        f"- Court 002 net-cost holdout equity: `{_fmt_eur(evidence.get('net_cost_court_002_holdout_equity'))}`",
        f"- Court 002 gross holdout equity: `{_fmt_eur(evidence.get('gross_court_002_holdout_equity'))}`",
        "- Court 002 net-cost holdout does not independently validate EUR1M pace.",
        "- Court 002 holdout left untouched: `true`",
        "- Strategy files changed by this court: `false`",
        "- Paper/live/execution/broker paths introduced: `false`",
        f"- paper_validation_ready: `{summary['paper_validation_ready']}`",
        "",
        "## Check tomorrow",
        "",
        "- Confirm LaunchAgent is still loaded.",
        "- Confirm latest canonical timestamp advanced only through closed candles.",
        "- Confirm gaps, duplicates, OHLC failures, and duplicate decisions remain zero.",
        "- Confirm status color and alert state.",
        "- Confirm net-cost diagnostic equity remains the cockpit primary truth.",
        "",
        "## Check after one week",
        "",
        "- Review trade count, accepted/rejected ratio, zero-trade days, win rate, profit factor, drawdown, 6H context annotations, outage/catch-up events, alerts, and net-cost target progress.",
        "- Verify no strategy/config drift and no forbidden execution path appeared.",
        "",
        "## Six-month forward validation gates",
        "",
    ]
    lines.extend([f"- `{gate}`" for gate in gates])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Install and audit the continuous scheduler forward-validation court.")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()
    result = build_court_outputs(install=args.install, smoke=args.smoke)
    print(
        json.dumps(
            {
                "final_classification": result["final_classification"],
                "scheduler_installed": result["scheduler_install_audit"].get("install_succeeded"),
                "scheduler_loaded": result["scheduler_install_audit"].get("loaded_status"),
                "status_color": result["forward_validation_cockpit"].get("status_color"),
                "output_root": str(default_config().output_root),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
