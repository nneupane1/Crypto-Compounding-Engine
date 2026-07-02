from __future__ import annotations

import argparse
import json
import math
import plistlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path


COURT_NAME = "MULTI_SYMBOL_SCHEDULER_INSTALLATION_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_symbol_scheduler_installation_court_001"
ACTIVE_MULTI_SYMBOL_RUNTIME_FOLDER = "multi_symbol_forward_runtime_earned_parallel_slots"

READY = "MULTI_SYMBOL_SCHEDULER_INSTALLATION_READY_FOR_MANUAL_APPROVAL_RESEARCH_ONLY"
WARNING = "MULTI_SYMBOL_SCHEDULER_INSTALLATION_WARNING_RESEARCH_ONLY"
BLOCKED = "MULTI_SYMBOL_SCHEDULER_INSTALLATION_BLOCKED_RESEARCH_ONLY"

LAUNCH_AGENT_LABEL = "com.retail_trading_system.multi_symbol_earned_parallel_slots_research_forward_shadow"
PLIST_NAME = f"{LAUNCH_AGENT_LABEL}.plist"
START_INTERVAL_SECONDS = 300

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "paper_validation_ready": False,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "private_endpoint_used": False,
    "signed_endpoint_used": False,
    "account_endpoint_used": False,
    "order_endpoint_used": False,
    "broker_path_created": False,
    "order_path_created": False,
    "strategy_logic_changed": False,
    "thresholds_tuned": False,
    "entries_changed": False,
    "exits_changed": False,
    "sizing_changed": False,
    "data_storage_modified": False,
    "btc_scheduler_replaced": False,
    "multi_symbol_scheduler_installed_by_this_court": False,
}


@dataclass(frozen=True)
class MultiSymbolSchedulerInstallationConfig:
    project_root: Path
    package_root: Path
    runtime_root: Path
    evidence_root: Path
    reduced_cap_root: Path
    output_root: Path
    launch_agents_dir: Path
    log_dir: Path


def default_config() -> MultiSymbolSchedulerInstallationConfig:
    root = project_root()
    pkg = package_root()
    return MultiSymbolSchedulerInstallationConfig(
        project_root=root,
        package_root=pkg,
        runtime_root=pkg / "output" / ACTIVE_MULTI_SYMBOL_RUNTIME_FOLDER,
        evidence_root=pkg / "output" / "multi_symbol_six_month_forward_evidence_court_001",
        reduced_cap_root=pkg / "output" / "multi_symbol_reduced_cap_gear_ladder_restatement_court_001",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
        launch_agents_dir=Path.home() / "Library" / "LaunchAgents",
        log_dir=Path.home() / "Library" / "Logs" / "retail_trading_system_multi_symbol_earned_parallel_slots",
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


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


def _command(config: MultiSymbolSchedulerInstallationConfig) -> str:
    python_path = config.project_root / ".venv311" / "bin" / "python"
    return (
        f"cd {config.project_root} && "
        "BINANCE_API_KEY='' BINANCE_API_SECRET='' "
        f"{python_path} -m structural_compounding_lab.shadow_forward.multi_symbol_forward_runtime "
        f"--mode run_once --output-dir structural_compounding_lab/output/{ACTIVE_MULTI_SYMBOL_RUNTIME_FOLDER}"
    )


def _plist_payload(config: MultiSymbolSchedulerInstallationConfig) -> dict[str, Any]:
    config.log_dir.mkdir(parents=True, exist_ok=True)
    return {
        "Label": LAUNCH_AGENT_LABEL,
        "ProgramArguments": ["/bin/zsh", "-lc", _command(config)],
        "WorkingDirectory": str(config.project_root),
        "EnvironmentVariables": {
            "BINANCE_API_KEY": "",
            "BINANCE_API_SECRET": "",
            "PYTHONUNBUFFERED": "1",
        },
        "StartInterval": START_INTERVAL_SECONDS,
        "RunAtLoad": False,
        "KeepAlive": False,
        "StandardOutPath": str(config.log_dir / "earned_parallel_slots.out.log"),
        "StandardErrorPath": str(config.log_dir / "earned_parallel_slots.err.log"),
    }


def _write_plist(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        plistlib.dump(payload, handle, sort_keys=True)


def _plist_safety(plist_path: Path) -> dict[str, Any]:
    text = plist_path.read_text(encoding="utf-8", errors="ignore")
    forbidden = ["PRIVATE_KEY", "PASSWORD", "TOKEN", "BINANCE_SECRET>", "API_KEY>not-empty"]
    return {
        "plist_path": str(plist_path),
        "contains_private_key_literal": "PRIVATE_KEY" in text,
        "contains_password_literal": "PASSWORD" in text,
        "contains_token_literal": "TOKEN" in text,
        "contains_broker_or_order_command": any(value in text.lower() for value in ["broker", "order endpoint", "account endpoint", "signed request"]),
        "forbidden_terms_checked": forbidden,
        "safe": not any(value in text for value in ["PRIVATE_KEY", "PASSWORD", "TOKEN"]),
    }


def _installed_plist_path(config: MultiSymbolSchedulerInstallationConfig) -> Path:
    return config.launch_agents_dir / PLIST_NAME


def _write_report(config: MultiSymbolSchedulerInstallationConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# Multi-Symbol Scheduler Installation Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        "- Research-only scheduler plan. This court writes a plist draft only.",
        "- It does not install, load, unload, or replace any LaunchAgent.",
        "",
        "## Scheduler draft",
        "",
        f"- Label: `{LAUNCH_AGENT_LABEL}`",
        f"- Cadence: every `{START_INTERVAL_SECONDS}` seconds",
        f"- Draft plist: `{summary['scheduler_manifest']['draft_plist_path']}`",
        f"- Proposed installed plist path: `{summary['scheduler_manifest']['proposed_installed_plist_path']}`",
        "",
        "## Gate",
        "",
        f"- May install after explicit approval: `{str(summary['gate']['may_install_after_explicit_user_approval']).lower()}`",
        f"- Installed by this court: `{str(summary['gate']['scheduler_installed_by_this_court']).lower()}`",
        f"- BTC scheduler replacement allowed: `{str(summary['gate']['may_replace_btc_scheduler']).lower()}`",
        f"- Paper validation ready: `{str(summary['gate']['paper_validation_ready']).lower()}`",
    ]
    (config.output_root / "multi_symbol_scheduler_installation_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: MultiSymbolSchedulerInstallationConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)

    runtime_status_path = config.runtime_root / "latest_status.json"
    runtime_summary_path = config.runtime_root / "multi_symbol_forward_runtime_summary.json"
    evidence_summary_path = config.evidence_root / "multi_symbol_six_month_forward_evidence_summary.json"
    reduced_cap_summary_path = config.reduced_cap_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json"

    runtime_status = _read_json(runtime_status_path)
    runtime_summary = _read_json(runtime_summary_path)
    evidence = _read_json(evidence_summary_path)
    reduced_cap = _read_json(reduced_cap_summary_path)

    missing = [
        str(path)
        for path, payload in [
            (runtime_status_path, runtime_status),
            (runtime_summary_path, runtime_summary),
            (evidence_summary_path, evidence),
            (reduced_cap_summary_path, reduced_cap),
        ]
        if not payload
    ]

    plist_path = config.output_root / PLIST_NAME
    plist_payload = _plist_payload(config)
    _write_plist(plist_path, plist_payload)

    runtime_duplicate_keys = int(runtime_status.get("decision_ledger_duplicate_keys") or runtime_summary.get("decision_ledger_duplicate_keys") or 0)
    expected_symbols = int(runtime_status.get("symbols_expected") or runtime_summary.get("symbols_expected") or 9)
    runtime_clean = (
        runtime_status.get("status_color") in {"GREEN", "YELLOW"}
        and int(runtime_status.get("symbols_clean") or 0) == expected_symbols
        and runtime_duplicate_keys == 0
        and runtime_status.get("paper_validation_ready") is False
    )
    evidence_ready = (
        evidence.get("final_classification") == "MULTI_SYMBOL_SIX_MONTH_FORWARD_EVIDENCE_READY_RESEARCH_ONLY"
        and evidence.get("paper_validation_ready") is False
        and int(evidence.get("aggregate", {}).get("decision_ledger_duplicate_keys") or 0) == 0
    )
    reduced_cap_ready = (
        reduced_cap.get("final_classification") == "MULTI_SYMBOL_REDUCED_CAP_GEAR_LADDER_RESTATEMENT_PASSED_RESEARCH_ONLY"
        and reduced_cap.get("paper_validation_ready") is False
        and bool(reduced_cap.get("gate", {}).get("may_treat_500k_gear1_as_fill_calibrated_research_cap")) is True
    )
    installed_path = _installed_plist_path(config)
    installed_already = installed_path.exists()
    plist_safety = _plist_safety(plist_path)
    prerequisites_ready = not missing and runtime_clean and evidence_ready and reduced_cap_ready and plist_safety["safe"]

    if missing:
        classification = BLOCKED
        reasons = ["missing_runtime_evidence_or_reduced_cap_artifact"]
    elif prerequisites_ready:
        classification = READY
        reasons = ["multi_symbol_scheduler_draft_ready_for_manual_approval_not_installed"]
    else:
        classification = WARNING
        reasons = []
        if not runtime_clean:
            reasons.append("runtime_status_not_clean")
        if not evidence_ready:
            reasons.append("six_month_evidence_gate_not_ready")
        if not reduced_cap_ready:
            reasons.append("reduced_cap_gate_not_ready")
        if not plist_safety["safe"]:
            reasons.append("plist_safety_scan_failed")

    manifest = {
        "label": LAUNCH_AGENT_LABEL,
        "draft_plist_path": str(plist_path),
        "proposed_installed_plist_path": str(installed_path),
        "expected_command_line": _command(config),
        "working_directory": str(config.project_root),
        "start_interval_seconds": START_INTERVAL_SECONDS,
        "run_at_load": False,
        "keep_alive": False,
        "environment_variables": plist_payload["EnvironmentVariables"],
        "stdout_log": plist_payload["StandardOutPath"],
        "stderr_log": plist_payload["StandardErrorPath"],
        "manual_install_commands_if_approved": [
            f"cp {plist_path} {installed_path}",
            f"launchctl load {installed_path}",
            f"launchctl print gui/$(id -u)/{LAUNCH_AGENT_LABEL}",
        ],
        "manual_uninstall_commands": [
            f"launchctl unload {installed_path}",
            f"rm {installed_path}",
        ],
        "scheduler_installed_by_this_court": False,
        "installed_plist_already_exists": installed_already,
        "btc_scheduler_replaced": False,
    }

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_runtime_status": str(runtime_status_path),
        "source_runtime_summary": str(runtime_summary_path),
        "source_evidence_summary": str(evidence_summary_path),
        "source_reduced_cap_summary": str(reduced_cap_summary_path),
        "missing_artifacts": missing,
        "runtime_preflight": {
            "status_color": runtime_status.get("status_color"),
            "symbols_clean": runtime_status.get("symbols_clean"),
            "decision_ledger_duplicate_keys": runtime_duplicate_keys,
            "latest_safe_1m_timestamp": runtime_status.get("latest_safe_1m_timestamp"),
            "runtime_clean": runtime_clean,
        },
        "evidence_preflight": {
            "final_classification": evidence.get("final_classification"),
            "minimum_complete_1h_slots": evidence.get("aggregate", {}).get("minimum_complete_1h_slots"),
            "remaining_1h_slots_before_six_month_gate": evidence.get("aggregate", {}).get("remaining_1h_slots_before_six_month_gate"),
            "evidence_ready": evidence_ready,
        },
        "reduced_cap_preflight": {
            "final_classification": reduced_cap.get("final_classification"),
            "recommended_symbol_caps_eur": reduced_cap.get("recommended_symbol_caps_eur", {}),
            "reduced_cap_ready": reduced_cap_ready,
        },
        "plist_safety": plist_safety,
        "scheduler_manifest": manifest,
        "gate": {
            "may_install_after_explicit_user_approval": classification == READY,
            "scheduler_installed_by_this_court": False,
            "may_replace_btc_scheduler": False,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "paper_validation_ready": False,
            "next_required_action": "request_user_approval_before_copying_or_loading_launchagent",
        },
        **SAFETY_FLAGS,
    }

    _write_json(config.output_root / "multi_symbol_scheduler_installation_summary.json", summary)
    _write_json(config.output_root / "scheduler_manifest.json", manifest)
    _write_report(config, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Prepare a research-only multi-symbol scheduler installation court.")
    parser.add_argument("--runtime-root", default=f"structural_compounding_lab/output/{ACTIVE_MULTI_SYMBOL_RUNTIME_FOLDER}")
    parser.add_argument("--evidence-root", default="structural_compounding_lab/output/multi_symbol_six_month_forward_evidence_court_001")
    parser.add_argument("--reduced-cap-root", default="structural_compounding_lab/output/multi_symbol_reduced_cap_gear_ladder_restatement_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        MultiSymbolSchedulerInstallationConfig(
            project_root=root,
            package_root=package_root(),
            runtime_root=resolve_project_path(args.runtime_root),
            evidence_root=resolve_project_path(args.evidence_root),
            reduced_cap_root=resolve_project_path(args.reduced_cap_root),
            output_root=resolve_project_path(args.output_dir),
            launch_agents_dir=Path.home() / "Library" / "LaunchAgents",
            log_dir=Path.home() / "Library" / "Logs" / "retail_trading_system_multi_symbol_earned_parallel_slots",
        )
    )
    print(json.dumps(_jsonable(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
