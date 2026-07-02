from __future__ import annotations

import argparse
import csv
import json
import os
import smtplib
import time
from datetime import datetime, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from structural_compounding_lab.common.email_safety import smtp_allowed_for_output_root
from structural_compounding_lab.common.project_paths import output_root
from structural_compounding_lab.execution.binance_demo_client import redact_secret
from structural_compounding_lab.execution.walk_forward_demo_execution_bridge import run as run_bridge


COURT_NAME = "BINANCE_DEMO_WALK_FORWARD_RUNTIME_COURT_PAPER_ONLY"
OUTPUT_FOLDER_NAME = "binance_demo_walk_forward_six_month_court_001"
COMPLETED = "BINANCE_DEMO_WALK_FORWARD_SIX_MONTH_RUNTIME_COMPLETED_PAPER_ONLY"
FAILED = "BINANCE_DEMO_WALK_FORWARD_SIX_MONTH_RUNTIME_FAILED"
DEFAULT_ALERT_TO = "nneupane1@gmail.com"
DEMO_ENV_PREFIXES = ("BINANCE_DEMO_", "RTS_ALERT_")
DEMO_ENV_KEYS = {"TRADING_SYSTEM_CONFIG"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_demo_env_from_dotenv() -> None:
    env_path = output_root().parents[1] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        if key not in DEMO_ENV_KEYS and not any(key.startswith(prefix) for prefix in DEMO_ENV_PREFIXES):
            continue
        os.environ.setdefault(key, value.strip().strip('"').strip("'"))


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
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


def _append_csv(path: Path, row: dict[str, Any], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({key: _jsonable(row.get(key, "")) for key in fieldnames})


def _artifact_root() -> Path:
    return output_root() / OUTPUT_FOLDER_NAME


def _rotate_existing(path: Path) -> None:
    if not path.exists():
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(f"previous_{path.stem}_{stamp}{path.suffix}")
    path.replace(target)


def _safe_email(root: Path, summary: dict[str, Any]) -> dict[str, Any]:
    alert_path = root / "alerts" / "latest_six_month_demo_completion_email.txt"
    recipient = os.getenv("RTS_ALERT_EMAIL_TO", DEFAULT_ALERT_TO)
    enabled = os.getenv("RTS_ALERT_EMAIL_ENABLED", "").strip().lower() in {"1", "true", "yes"}
    dry_run = os.getenv("RTS_ALERT_EMAIL_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}
    host = os.getenv("RTS_ALERT_SMTP_HOST", "").strip()
    sender = os.getenv("RTS_ALERT_EMAIL_FROM", "").strip()
    username = os.getenv("RTS_ALERT_SMTP_USERNAME", "").strip()
    password = os.getenv("RTS_ALERT_SMTP_PASSWORD", "")
    subject_prefix = os.getenv("RTS_DEMO_EMAIL_SUBJECT_PREFIX", "RTS 6-MONTH BINANCE SPOT TESTNET DEMO")
    subject = f"{subject_prefix}: SUPERVISOR {summary['final_classification']}"
    body = "\n".join(
        [
            "Binance Spot Testnet walk-forward demo supervision completed.",
            "",
            f"Classification: {summary['final_classification']}",
            f"Started: {summary['started_at']}",
            f"Completed: {summary['completed_at']}",
            f"Planned duration seconds: {summary['duration_seconds']}",
            f"Interval seconds: {summary['interval_seconds']}",
            f"Iterations: {summary['iterations_completed']}",
            f"Bridge orders submitted: {summary['bridge_orders_submitted_total']}",
            f"Bridge eligible signals seen: {summary['bridge_eligible_signals_seen_total']}",
            f"Bridge skipped signals: {summary['bridge_signals_skipped_total']}",
            f"Order event emails sent: {summary['order_event_emails_sent_total']}",
            f"Order event email drafts written: {summary['order_event_email_drafts_total']}",
            f"Artifact root: {summary['artifact_root']}",
            "",
            "Safety:",
            f"- paper_validation_ready: {summary['paper_validation_ready']}",
            f"- live_allowed: {summary['live_allowed']}",
            f"- real_money_allowed: {summary['real_money_allowed']}",
            f"- production_order_path_allowed: {summary['production_order_path_allowed']}",
            f"- strategy_changed: {summary['strategy_changed']}",
            f"- btc_scheduler_changed: {summary['btc_scheduler_changed']}",
        ]
    )
    alert_path.parent.mkdir(parents=True, exist_ok=True)
    alert_path.write_text(f"To: {recipient}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
    sent = False
    note = "draft_written"
    smtp_allowed, smtp_gate_note = smtp_allowed_for_output_root(root)
    if not smtp_allowed:
        note = smtp_gate_note
    if smtp_allowed and enabled and not dry_run and host and sender:
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.set_content(body)
        try:
            with smtplib.SMTP(host, int(os.getenv("RTS_ALERT_SMTP_PORT", "587") or "587"), timeout=20) as smtp:
                smtp.starttls()
                if username or password:
                    smtp.login(username, password)
                smtp.send_message(msg)
            sent = True
            note = "smtp_sent"
        except Exception as exc:  # noqa: BLE001
            note = "smtp_failed_draft_written:" + redact_secret(str(exc), password)
    return {
        "completion_email_recipient": recipient,
        "completion_email_sent": sent,
        "completion_email_draft_written": True,
        "completion_email_path": str(alert_path),
        "completion_email_note": note,
    }


def run_supervisor(
    *,
    duration_seconds: int,
    interval_seconds: int,
    root: Path | None = None,
    source_ledger: Path | None = None,
) -> dict[str, Any]:
    _load_demo_env_from_dotenv()
    artifact_root = root or _artifact_root()
    artifact_root.mkdir(parents=True, exist_ok=True)
    bridge_root = artifact_root / "execution_bridge"
    bridge_root.mkdir(parents=True, exist_ok=True)
    summaries_root = artifact_root / "bridge_iteration_summaries"
    heartbeat_path = artifact_root / "heartbeat.csv"
    _rotate_existing(artifact_root / "final_summary.json")
    _rotate_existing(heartbeat_path)
    pid_path = artifact_root / "run.pid"
    pid_path.write_text(str(os.getpid()), encoding="utf-8")

    started_at = _now()
    deadline = time.monotonic() + max(0, duration_seconds)
    iterations = 0
    orders_total = 0
    eligible_total = 0
    skipped_total = 0
    order_event_emails_sent_total = 0
    order_event_email_drafts_total = 0
    failures: list[str] = []
    latest_bridge_summary: dict[str, Any] = {}

    base_status: dict[str, Any] = {
        "court_name": COURT_NAME,
        "artifact_root": str(artifact_root),
        "bridge_artifact_root": str(bridge_root),
        "source_ledger": str(source_ledger) if source_ledger else "default_active_multi_symbol_forward_decision_ledger",
        "started_at": started_at,
        "duration_seconds": duration_seconds,
        "interval_seconds": interval_seconds,
        "status": "RUNNING",
        "source_strategy_ledger": "active_multi_symbol_frozen_forward_decision_ledger",
        "spot_compatible_long_only": True,
        "short_selling_allowed": False,
        "paper_validation_ready": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "production_order_path_allowed": False,
        "production_broker_path_allowed": False,
        "strategy_changed": False,
        "btc_scheduler_changed": False,
        "same_artifact_shape_for_future_real_account": True,
        "future_real_account_adapter_required": True,
        "current_adapter": "binance_spot_testnet_demo_only",
    }
    _write_json(artifact_root / "latest_status.json", base_status)

    try:
        while True:
            iterations += 1
            try:
                latest_bridge_summary = run_bridge("execute_once", source_ledger=source_ledger, output_root=bridge_root)
                orders_total += int(latest_bridge_summary.get("orders_submitted", 0) or 0)
                eligible_total += int(latest_bridge_summary.get("eligible_signals_seen", 0) or 0)
                skipped_total += int(latest_bridge_summary.get("signals_skipped", 0) or 0)
                order_event_emails_sent_total += int(latest_bridge_summary.get("order_event_emails_sent", 0) or 0)
                order_event_email_drafts_total += int(latest_bridge_summary.get("order_event_email_drafts_written", 0) or 0)
                _write_json(summaries_root / f"bridge_iteration_{iterations:04d}.json", latest_bridge_summary)
                state = "OK"
                error = ""
            except Exception as exc:  # noqa: BLE001
                state = "ERROR"
                error = str(exc)
                failures.append(error)
            heartbeat = {
                "timestamp": _now(),
                "iteration": iterations,
                "state": state,
                "bridge_classification": latest_bridge_summary.get("final_classification", ""),
                "orders_submitted_this_iteration": latest_bridge_summary.get("orders_submitted", 0),
                "orders_submitted_total": orders_total,
                "eligible_signals_seen_this_iteration": latest_bridge_summary.get("eligible_signals_seen", 0),
                "signals_skipped_this_iteration": latest_bridge_summary.get("signals_skipped", 0),
                "error": error,
            }
            _append_csv(
                heartbeat_path,
                heartbeat,
                [
                    "timestamp",
                    "iteration",
                    "state",
                    "bridge_classification",
                    "orders_submitted_this_iteration",
                    "orders_submitted_total",
                    "eligible_signals_seen_this_iteration",
                    "signals_skipped_this_iteration",
                    "error",
                ],
            )
            _write_json(
                artifact_root / "latest_status.json",
                {
                    **base_status,
                    "last_heartbeat": heartbeat,
                    "iterations_completed": iterations,
                    "bridge_orders_submitted_total": orders_total,
                    "bridge_eligible_signals_seen_total": eligible_total,
                    "bridge_signals_skipped_total": skipped_total,
                    "order_event_emails_sent_total": order_event_emails_sent_total,
                    "order_event_email_drafts_total": order_event_email_drafts_total,
                    "failure_count": len(failures),
                },
            )
            if time.monotonic() >= deadline:
                break
            time.sleep(max(1, interval_seconds))
    finally:
        completed_at = _now()

    summary = {
        **base_status,
        "status": "COMPLETED" if not failures else "COMPLETED_WITH_FAILURES",
        "final_classification": COMPLETED if not failures else FAILED,
        "completed_at": completed_at,
        "iterations_completed": iterations,
        "bridge_orders_submitted_total": orders_total,
        "bridge_eligible_signals_seen_total": eligible_total,
        "bridge_signals_skipped_total": skipped_total,
        "order_event_emails_sent_total": order_event_emails_sent_total,
        "order_event_email_drafts_total": order_event_email_drafts_total,
        "failure_count": len(failures),
        "failures": failures[-10:],
        "latest_bridge_summary": latest_bridge_summary,
    }
    summary.update(_safe_email(artifact_root, summary))
    _write_json(artifact_root / "final_summary.json", summary)
    _write_json(artifact_root / "latest_status.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--duration-seconds", type=int, default=21600)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--output-dir", default="")
    parser.add_argument("--source-ledger", default="")
    args = parser.parse_args()
    print(
        json.dumps(
            _jsonable(
                run_supervisor(
                    duration_seconds=args.duration_seconds,
                    interval_seconds=args.interval_seconds,
                    root=Path(args.output_dir) if args.output_dir else None,
                    source_ledger=Path(args.source_ledger) if args.source_ledger else None,
                )
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
