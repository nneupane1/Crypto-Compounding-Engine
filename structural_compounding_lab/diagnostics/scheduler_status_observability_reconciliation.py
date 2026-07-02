from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path  # noqa: E402
from structural_compounding_lab.shadow_forward.forward_validation_runtime import (  # noqa: E402
    LAUNCH_AGENT_LABEL,
    PLIST_NAME,
    SAFETY_FLAGS,
    STATUS_GREEN,
    ForwardValidationRuntimeConfig,
    _paths,
    _read_json,
    detect_user_launchagent_scheduler_status,
    run_once,
)


COURT_NAME = "SCHEDULER_STATUS_OBSERVABILITY_RECONCILIATION_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "scheduler_status_observability_reconciliation_court_001"
PASSED = "SCHEDULER_STATUS_OBSERVABILITY_RECONCILIATION_PASSED_RESEARCH_ONLY"
WARNING = "SCHEDULER_STATUS_OBSERVABILITY_RECONCILIATION_WARNING_RESEARCH_ONLY"
FAILED = "SCHEDULER_STATUS_OBSERVABILITY_RECONCILIATION_FAILED_RESEARCH_ONLY"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(payload, indent=2, sort_keys=True, default=str), encoding="utf-8")
    temp.replace(path)


def _git_changed_files(root: Path) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "diff", "--name-only"],
            cwd=str(root),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def _strategy_files_changed(changed_files: list[str]) -> bool:
    strategy_markers = (
        "structural_compounding_lab/strategy",
        "structural_compounding_lab/backtest/engine",
        "structural_compounding_lab/backtest/strategy",
        "structural_compounding_lab/frozen",
    )
    return any(path.startswith(strategy_markers) for path in changed_files)


def _report(summary: dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Scheduler Status Observability Reconciliation Court",
            "",
            f"- Classification: `{summary['final_classification']}`",
            f"- Court: `{summary['court_name']}`",
            f"- Created: `{summary['created_at_utc']}`",
            "",
            "## Runtime status reconciliation",
            "",
            f"- Previous runtime status: `{summary['previous_runtime_status_color']}`",
            f"- Previous scheduler_installed: `{summary['previous_runtime_scheduler_installed']}`",
            f"- New runtime status: `{summary['new_runtime_status_color']}`",
            f"- New scheduler_installed: `{summary['new_runtime_scheduler_installed']}`",
            f"- New scheduler_loaded: `{summary['new_runtime_scheduler_loaded']}`",
            f"- Mismatch resolved: `{summary['mismatch_resolved']}`",
            "",
            "## LaunchAgent evidence",
            "",
            f"- Label: `{summary['launchagent_label']}`",
            f"- Path: `{summary['launchagent_path']}`",
            f"- Method: `{summary['launchctl_method_used']}`",
            f"- Return code: `{summary['launchctl_returncode']}`",
            f"- Current state: `{summary['launchctl_current_state']}`",
            f"- Last exit code: `{summary['launchctl_last_exit_code']}`",
            f"- Idle between scheduled runs treated as healthy: `{summary['scheduler_idle_between_runs_is_healthy']}`",
            "",
            "## Safety",
            "",
            f"- Scheduler reinstalled: `{summary['scheduler_reinstalled']}`",
            f"- Strategy files changed: `{summary['strategy_files_changed']}`",
            f"- Paper validation ready: `{summary['paper_validation_ready']}`",
            f"- Paper/live/order/broker path appeared: `{summary['paper_live_order_broker_path_appeared']}`",
            "",
            "This court is observability-only. It does not change entries, exits, thresholds, filters, sizing, 6H context, target logic, paper trading, live trading, orders, brokers, accounts, private endpoints, or signed requests.",
            "",
        ]
    )


def run_court(*, canonical_csv: Path | None = None, output_dir: Path | None = None) -> dict[str, Any]:
    root = project_root()
    pkg = package_root()
    court_root = pkg / "output" / OUTPUT_FOLDER_NAME
    runtime_output = output_dir or pkg / "output" / "forward_validation_runtime"
    canonical = canonical_csv or root / "structural_compounding_lab" / "data_storage" / "BTCUSDT" / "1m" / "btcusdt_1m_canonical_shadow_forward.csv"
    plist_path = Path.home() / "Library" / "LaunchAgents" / PLIST_NAME
    previous_status = _read_json(_paths(runtime_output)["status"], {})
    launchagent_status = detect_user_launchagent_scheduler_status(
        label=LAUNCH_AGENT_LABEL,
        plist_path=plist_path,
    )
    config = ForwardValidationRuntimeConfig(
        project_root=root,
        package_root=pkg,
        canonical_csv_path=canonical,
        output_root=runtime_output,
        scheduler_detection_enabled=True,
        scheduler_plist_path=plist_path,
    )
    new_status = run_once(config)
    changed_files = _git_changed_files(root)
    strategy_changed = _strategy_files_changed(changed_files)
    paper_live_order_broker_path_appeared = bool(
        new_status.get("paper_allowed")
        or new_status.get("live_allowed")
        or new_status.get("real_money_allowed")
        or new_status.get("behavior_change_allowed")
        or new_status.get("order_path_exists")
        or new_status.get("broker_path_exists")
    )
    mismatch_resolved = bool(
        previous_status.get("scheduler_installed") is False
        and new_status.get("scheduler_installed") is True
        and new_status.get("scheduler_loaded") is True
    )
    hard_safety_ok = bool(
        new_status.get("research_only") is True
        and new_status.get("real_money_allowed") is False
        and new_status.get("paper_allowed") is False
        and new_status.get("live_allowed") is False
        and new_status.get("behavior_change_allowed") is False
        and new_status.get("order_path_exists") is False
        and new_status.get("broker_path_exists") is False
        and new_status.get("paper_validation_ready") is False
        and new_status.get("eur_25000_anchor_active") is False
    )
    if not hard_safety_ok or strategy_changed or not new_status.get("scheduler_installed") or not new_status.get("scheduler_loaded"):
        classification = FAILED
    elif new_status.get("status") == STATUS_GREEN and mismatch_resolved:
        classification = PASSED
    else:
        classification = WARNING
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "previous_runtime_scheduler_installed": previous_status.get("scheduler_installed"),
        "new_runtime_scheduler_installed": new_status.get("scheduler_installed"),
        "new_runtime_scheduler_loaded": new_status.get("scheduler_loaded"),
        "launchctl_method_used": new_status.get("launchctl_status_method"),
        "launchagent_path": new_status.get("scheduler_plist_path"),
        "launchagent_label": new_status.get("scheduler_label"),
        "launchctl_returncode": new_status.get("launchctl_returncode"),
        "launchctl_current_state": new_status.get("launchctl_current_state"),
        "launchctl_last_exit_code": new_status.get("launchctl_last_exit_code"),
        "scheduler_idle_between_runs_is_healthy": new_status.get("scheduler_idle_between_runs_is_healthy"),
        "previous_runtime_status_color": previous_status.get("status"),
        "new_runtime_status_color": new_status.get("status"),
        "new_runtime_final_reason": new_status.get("final_reason"),
        "mismatch_resolved": mismatch_resolved,
        "scheduler_reinstalled": False,
        "strategy_files_changed": strategy_changed,
        "changed_files": changed_files,
        "paper_live_order_broker_path_appeared": paper_live_order_broker_path_appeared,
        "paper_validation_ready": new_status.get("paper_validation_ready"),
        "hard_safety_ok": hard_safety_ok,
        "launchagent_status_before_runtime_run": launchagent_status,
        "runtime_status_path": str(_paths(runtime_output)["status"]),
        **SAFETY_FLAGS,
        "no_order_path_created": not bool(new_status.get("order_path_exists")),
        "no_broker_path_created": not bool(new_status.get("broker_path_exists")),
    }
    _write_json(court_root / "scheduler_status_observability_summary.json", summary)
    (court_root / "scheduler_status_observability_report.md").write_text(_report(summary), encoding="utf-8")
    return summary


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Scheduler status observability reconciliation court.")
    parser.add_argument(
        "--canonical-csv",
        default="structural_compounding_lab/data_storage/BTCUSDT/1m/btcusdt_1m_canonical_shadow_forward.csv",
    )
    parser.add_argument(
        "--output-dir",
        default="structural_compounding_lab/output/forward_validation_runtime",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    print(
        json.dumps(
            run_court(
                canonical_csv=resolve_project_path(args.canonical_csv),
                output_dir=resolve_project_path(args.output_dir),
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
