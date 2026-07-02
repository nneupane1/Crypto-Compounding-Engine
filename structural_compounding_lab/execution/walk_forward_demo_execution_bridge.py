from __future__ import annotations

import argparse
import csv
import json
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from structural_compounding_lab.common.email_safety import smtp_allowed_for_output_root
from structural_compounding_lab.common.project_paths import package_root
from structural_compounding_lab.execution.binance_demo_client import (
    BinanceDemoClient,
    BinanceDemoConfig,
    BinanceDemoExecutionError,
    BinanceDemoSafetyError,
    build_client_order_id,
    compute_minimum_quantity,
    floor_to_step,
    parse_symbol_rules,
    redact_secret,
    validate_base_url,
)
from structural_compounding_lab.execution.demo_order_models import DemoOrderIntent, SAFETY_FLAGS


COURT_NAME = "WALK_FORWARD_BINANCE_DEMO_EXECUTION_BRIDGE_PAPER_ONLY"
OUTPUT_FOLDER_NAME = "walk_forward_demo_execution_bridge"

READY = "WALK_FORWARD_DEMO_EXECUTION_BRIDGE_READY_PAPER_ONLY"
DRY_RUN_READY = "WALK_FORWARD_DEMO_EXECUTION_BRIDGE_DRY_RUN_READY_PAPER_ONLY"
NO_ELIGIBLE = "WALK_FORWARD_DEMO_EXECUTION_BRIDGE_NO_ELIGIBLE_SIGNAL_PAPER_ONLY"
FAILED_SAFETY = "WALK_FORWARD_DEMO_EXECUTION_BRIDGE_FAILED_SAFETY"
FAILED_EXECUTION = "WALK_FORWARD_DEMO_EXECUTION_BRIDGE_FAILED_EXECUTION"
BLOCKED = "WALK_FORWARD_DEMO_EXECUTION_BRIDGE_BLOCKED"

DEFAULT_SOURCE_LEDGER = "multi_symbol_forward_runtime_earned_parallel_slots/ledger/multi_symbol_forward_decision_ledger.csv"
DEFAULT_SYMBOL_ALLOWLIST = "ADAUSDT,LINKUSDT,BNBUSDT,XRPUSDT,AVAXUSDT,DOGEUSDT,ETHUSDT,BTCUSDT,SOLUSDT"
DEFAULT_ALERT_TO = "nneupane1@gmail.com"
DEMO_ENV_PREFIXES = ("BINANCE_DEMO_", "RTS_ALERT_")
DEMO_ENV_KEYS = {"TRADING_SYSTEM_CONFIG"}


@dataclass(frozen=True)
class BridgeConfig:
    mode: str
    source_ledger: Path
    output_root: Path
    symbol_allowlist: tuple[str, ...]
    max_orders_per_run: int
    lookback_hours: int
    process_order: str
    enabled: bool
    allow_backlog_replay: bool
    max_exits_per_run: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    return value


def _load_demo_env_from_dotenv() -> None:
    env_path = package_root().parent / ".env"
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


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_jsonable(payload), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _jsonable(row.get(key, "")) for key in fieldnames})
    temp.replace(path)


def _parse_bool(value: str | None) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "y"}


def _parse_timestamp(value: str) -> datetime | None:
    if not value:
        return None
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _default_output_root() -> Path:
    return package_root() / "output" / OUTPUT_FOLDER_NAME


def _default_source_ledger() -> Path:
    return package_root() / "output" / DEFAULT_SOURCE_LEDGER


def config_from_env(mode: str, *, source_ledger: Path | None = None, output_root: Path | None = None) -> BridgeConfig:
    _load_demo_env_from_dotenv()
    allowlist = tuple(
        item.strip().upper()
        for item in os.getenv("WALK_FORWARD_DEMO_SYMBOL_ALLOWLIST", DEFAULT_SYMBOL_ALLOWLIST).split(",")
        if item.strip()
    )
    return BridgeConfig(
        mode=mode,
        source_ledger=source_ledger or _default_source_ledger(),
        output_root=output_root or _default_output_root(),
        symbol_allowlist=allowlist or ("BTCUSDT",),
        max_orders_per_run=max(0, int(os.getenv("WALK_FORWARD_DEMO_MAX_ORDERS_PER_RUN", "1") or "1")),
        lookback_hours=max(0, int(os.getenv("WALK_FORWARD_DEMO_LOOKBACK_HOURS", "168") or "168")),
        process_order=os.getenv("WALK_FORWARD_DEMO_PROCESS_ORDER", "latest").strip().lower() or "latest",
        enabled=_parse_bool(os.getenv("WALK_FORWARD_DEMO_EXECUTION_ENABLED")),
        allow_backlog_replay=_parse_bool(os.getenv("WALK_FORWARD_DEMO_ALLOW_BACKLOG_REPLAY")),
        max_exits_per_run=max(0, int(os.getenv("WALK_FORWARD_DEMO_MAX_EXITS_PER_RUN", "10") or "10")),
    )


def _ledger_path(output_root: Path) -> Path:
    return output_root / "walk_forward_demo_execution_ledger.csv"


def _activation_state_path(output_root: Path) -> Path:
    return output_root / "walk_forward_demo_activation_state.json"


def _processed_trade_ids(output_root: Path) -> set[str]:
    rows = _read_csv(_ledger_path(output_root))
    return {row.get("source_trade_id", "") for row in rows if row.get("source_trade_id")}


def _is_true(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes"}


def _source_max_timestamp(rows: list[dict[str, str]]) -> datetime | None:
    timestamps = [_source_timestamp(row) for row in rows]
    valid = [item for item in timestamps if item is not None]
    return max(valid) if valid else None


def _source_timestamp(row: dict[str, str]) -> datetime | None:
    for key in ("timestamp", "decision_slot", "closed_1h_candle_start", "entry_time", "source_timestamp"):
        parsed = _parse_timestamp(row.get(key, ""))
        if parsed is not None:
            return parsed
    return None


def _source_trade_id(row: dict[str, str]) -> str:
    return str(row.get("decision_key") or row.get("trade_id") or row.get("source_trade_id") or "").strip()


def _source_decision_id(row: dict[str, str]) -> str:
    return str(row.get("decision_id") or row.get("decision_key") or row.get("trade_id") or "").strip()


def _source_symbol(row: dict[str, str]) -> str:
    return str(row.get("symbol") or row.get("decision_id", "").split("-")[0] or "BTCUSDT").upper()


def _source_direction(row: dict[str, str]) -> str:
    return str(row.get("direction") or row.get("side") or "").strip().lower()


def _source_event_type(row: dict[str, str]) -> str:
    return str(row.get("event_type") or row.get("order_event_type") or "").strip().upper()


def _source_entry_reference(row: dict[str, str]) -> str:
    return str(row.get("entry_reference") or row.get("entry_price") or "")


def _source_stop_reference(row: dict[str, str]) -> str:
    return str(row.get("stop_reference") or row.get("initial_stop") or "")


def _source_target_reference(row: dict[str, str]) -> str:
    return str(row.get("target_reference") or row.get("exit_price") or "")


def _read_activation_timestamp(output_root: Path) -> datetime | None:
    path = _activation_state_path(output_root)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return _parse_timestamp(str(payload.get("activated_after_source_timestamp", "")))


def _write_activation_timestamp(output_root: Path, timestamp: datetime | None, *, reason: str) -> None:
    if timestamp is None:
        return
    _write_json(
        _activation_state_path(output_root),
        {
            "activated_after_source_timestamp": timestamp.astimezone(timezone.utc).isoformat(),
            "updated_at": _now(),
            "reason": reason,
            "backlog_replay_default": False,
            "only_newer_source_rows_may_execute_by_default": True,
        },
    )


def _candidate_rows(config: BridgeConfig, *, activation_timestamp: datetime | None = None) -> tuple[list[dict[str, str]], list[dict[str, Any]]]:
    rows = _read_csv(config.source_ledger)
    processed = _processed_trade_ids(config.output_root)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=config.lookback_hours) if config.lookback_hours else None
    candidates: list[dict[str, str]] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        trade_id = _source_trade_id(row)
        symbol = _source_symbol(row)
        direction = _source_direction(row)
        event_type = _source_event_type(row)
        timestamp = _source_timestamp(row)
        reason = ""
        if not trade_id:
            reason = "missing_trade_id"
        elif trade_id in processed:
            reason = "already_processed"
        elif event_type and event_type != "ENTRY":
            reason = "source_event_not_entry"
        elif symbol not in config.symbol_allowlist:
            reason = "symbol_not_allowlisted"
        elif not _is_true(row.get("research_only", "true")):
            reason = "source_row_not_research_only"
        elif not _is_true(row.get("no_order_sent", "true")):
            reason = "source_claims_order_already_sent"
        elif str(row.get("broker_path_exists", "false")).lower() == "true":
            reason = "source_claims_broker_path_exists"
        elif timestamp is None:
            reason = "invalid_timestamp"
        elif activation_timestamp is not None and timestamp <= activation_timestamp:
            reason = "before_or_at_demo_bridge_activation_checkpoint"
        elif cutoff and timestamp < cutoff:
            reason = "outside_lookback"
        elif direction != "long":
            reason = "spot_testnet_bridge_skips_non_long_signal"
        if reason:
            if reason not in {"already_processed", "outside_lookback"}:
                skipped.append(
                    {
                        "source_trade_id": trade_id,
                        "source_decision_id": _source_decision_id(row),
                        "symbol": symbol,
                        "timestamp": timestamp.isoformat() if timestamp else "",
                        "direction": direction,
                        "entry_reference": _source_entry_reference(row),
                        "stop_reference": _source_stop_reference(row),
                        "target_reference": _source_target_reference(row),
                        "amount_bought_eur": row.get("amount_bought_eur", ""),
                        "position_notional_eur": row.get("position_notional_eur", ""),
                        "risk_eur": row.get("risk_eur", ""),
                        "total_equity_after_event_eur": row.get("total_equity_after_event_eur", ""),
                        "active_equity_reference_eur": row.get("active_equity_reference_eur", ""),
                        "state": event_type or row.get("state", ""),
                        "research_only": row.get("research_only", ""),
                        "no_order_sent": row.get("no_order_sent", ""),
                        "broker_path_exists": row.get("broker_path_exists", ""),
                        "skip_reason": reason,
                    }
                )
            continue
        candidates.append(
            {
                **row,
                "trade_id": trade_id,
                "decision_id": _source_decision_id(row),
                "timestamp": timestamp.isoformat() if timestamp else "",
                "symbol": symbol,
                "direction": direction,
                "state": event_type or row.get("state", ""),
                "entry_reference": _source_entry_reference(row),
                "stop_reference": _source_stop_reference(row),
                "target_reference": _source_target_reference(row),
                "amount_bought_eur": row.get("amount_bought_eur", ""),
                "position_notional_eur": row.get("position_notional_eur", ""),
                "risk_eur": row.get("risk_eur", ""),
                "active_equity_reference_eur": row.get("active_equity_reference_eur", ""),
                "total_equity_after_event_eur": row.get("total_equity_after_event_eur", ""),
                "active_equity_after_event_eur": row.get("active_equity_after_event_eur", ""),
                "spot_compatible_long_only": row.get("spot_compatible_long_only", "true"),
                "short_selling_allowed": row.get("short_selling_allowed", "false"),
            }
        )
    candidates.sort(key=lambda item: _parse_timestamp(item.get("timestamp", "")) or datetime.min.replace(tzinfo=timezone.utc))
    if config.process_order == "latest":
        candidates.reverse()
    return candidates, skipped


def _safe_alert(output_root: Path, summary: dict[str, Any], message: str) -> dict[str, Any]:
    alert_path = output_root / "alerts" / "latest_walk_forward_demo_execution_alert.txt"
    recipient = os.getenv("RTS_ALERT_EMAIL_TO", DEFAULT_ALERT_TO)
    enabled = _parse_bool(os.getenv("RTS_ALERT_EMAIL_ENABLED"))
    dry_run = _parse_bool(os.getenv("RTS_ALERT_EMAIL_DRY_RUN"))
    host = os.getenv("RTS_ALERT_SMTP_HOST", "").strip()
    sender = os.getenv("RTS_ALERT_EMAIL_FROM", "").strip()
    username = os.getenv("RTS_ALERT_SMTP_USERNAME", "").strip()
    password = os.getenv("RTS_ALERT_SMTP_PASSWORD", "")
    subject = f"RTS walk-forward demo bridge: {summary['final_classification']}"
    body = (
        f"{message}\n\n"
        f"Classification: {summary['final_classification']}\n"
        f"Mode: {summary['mode']}\n"
        f"Orders submitted: {summary['orders_submitted']}\n"
        f"Signals skipped: {summary['signals_skipped']}\n"
        f"Source ledger: {summary['source_ledger']}\n"
    )
    alert_path.parent.mkdir(parents=True, exist_ok=True)
    alert_path.write_text(f"To: {recipient}\nSubject: {subject}\n\n{body}", encoding="utf-8")
    sent = False
    note = "draft_written"
    smtp_allowed, smtp_gate_note = smtp_allowed_for_output_root(output_root)
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
        except Exception as exc:  # noqa: BLE001 - alert failure must not expose secret
            note = "smtp_failed_draft_written:" + redact_secret(str(exc), password)
    return {
        "alert_recipient": recipient,
        "alert_sent": sent,
        "alert_draft_written": True,
        "alert_path": str(alert_path),
        "alert_note": note,
    }


def _no_run_level_email_policy() -> dict[str, Any]:
    return {
        "alert_recipient": os.getenv("RTS_ALERT_EMAIL_TO", DEFAULT_ALERT_TO),
        "alert_sent": False,
        "alert_draft_written": False,
        "alert_path": "",
        "alert_note": "run_level_email_suppressed_trade_events_only",
        "trade_event_email_policy": "send_email_only_when_demo_order_entry_or_exit_event_is_recorded",
    }


def _safe_order_event_alert(output_root: Path, record: dict[str, Any]) -> dict[str, Any]:
    event_type = str(record.get("order_event_type") or "ORDER_EVENT").upper()
    source_trade_id = str(record.get("source_trade_id") or "unknown_source")
    client_order_id = str(record.get("client_order_id") or "unknown_client_order")
    safe_name = "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in f"{event_type}_{source_trade_id}_{client_order_id}")[:180]
    event_dir = output_root / "alerts" / "order_events"
    event_path = event_dir / f"{safe_name}.txt"
    latest_path = event_dir / "latest_order_event_email.txt"

    recipient = os.getenv("RTS_ALERT_EMAIL_TO", DEFAULT_ALERT_TO)
    enabled = _parse_bool(os.getenv("RTS_ALERT_EMAIL_ENABLED"))
    dry_run = _parse_bool(os.getenv("RTS_ALERT_EMAIL_DRY_RUN"))
    host = os.getenv("RTS_ALERT_SMTP_HOST", "").strip()
    sender = os.getenv("RTS_ALERT_EMAIL_FROM", "").strip()
    username = os.getenv("RTS_ALERT_SMTP_USERNAME", "").strip()
    password = os.getenv("RTS_ALERT_SMTP_PASSWORD", "")
    subject = _order_event_subject(event_type, record)
    body_lines = [
            _order_event_heading(event_type),
            "",
            "Source signal:",
            f"- source_trade_id: {record.get('source_trade_id', '')}",
            f"- source_decision_id: {record.get('source_decision_id', '')}",
            f"- source_timestamp: {record.get('source_timestamp', '')}",
            f"- source_direction: {record.get('direction', '')}",
            f"- source_state: {record.get('source_state', '')}",
            f"- source_entry_reference: {record.get('source_entry_reference', '')}",
            f"- source_stop_reference: {record.get('source_stop_reference', '')}",
            f"- source_target_reference: {record.get('source_target_reference', '')}",
            f"- source_amount_bought_eur: {record.get('source_amount_bought_eur', '')}",
            f"- source_position_notional_eur: {record.get('source_position_notional_eur', '')}",
            f"- source_risk_eur: {record.get('source_risk_eur', '')}",
            f"- source_total_equity_after_event_eur: {record.get('source_total_equity_after_event_eur', '')}",
            f"- source_active_equity_reference_eur: {record.get('source_active_equity_reference_eur', '')}",
            f"- source_research_only: {record.get('source_research_only', '')}",
            f"- source_no_order_sent: {record.get('source_no_order_sent', '')}",
            f"- source_broker_path_exists: {record.get('source_broker_path_exists', '')}",
            "",
            "Reason / context:",
            f"- bridge_reason: {record.get('bridge_reason', '')}",
            f"- position_effect: {record.get('position_effect', '')}",
            f"- execution_scope: {record.get('execution_scope', '')}",
            f"- exit_handling_note: {record.get('exit_handling_note', '')}",
    ]
    if event_type == "EXIT":
        body_lines.extend(
            [
                "",
                "Entry:",
                f"- entry_time: {record.get('entry_created_at', '')}",
                f"- entry_price_reference: {record.get('source_entry_reference', '')}",
                f"- entry_stop_reference: {record.get('source_stop_reference', '')}",
                f"- entry_target_reference: {record.get('source_target_reference', '')}",
                f"- entry_quantity: {record.get('entry_executed_qty', '')}",
                f"- entry_quote_filled: {record.get('entry_quote_filled', '')}",
                f"- entry_exchange_order_id: {record.get('entry_exchange_order_id', '')}",
                "",
                "Exit:",
                f"- exit_reason: {record.get('exit_reason', '')}",
                f"- exit_trigger_price: {record.get('exit_trigger_price', '')}",
                f"- exit_reference: {record.get('exit_reference', '')}",
                "",
                "PnL:",
                f"- gross_pnl_quote: {record.get('gross_pnl_quote', '')}",
                f"- estimated_fees_quote: {record.get('estimated_fees_quote', '')}",
                f"- net_pnl_quote: {record.get('net_pnl_quote', '')}",
                f"- net_r_multiple: {record.get('net_r_multiple', '')}",
                f"- result: {record.get('result_label', '')}",
                f"- holding_seconds: {record.get('holding_seconds', '')}",
            ]
        )
    if event_type == "SHORT_SIGNAL":
        body_lines.extend(
            [
                "",
                "Short signal handling:",
                "- signal_direction: short",
                "- execution_status: not_executed_on_spot_testnet",
                "- reason: Binance Spot Testnet adapter currently supports long spot BUY/SELL lifecycle only.",
                "- system_signal_preserved: true",
                "- this_is_not_a_strategy_rejection: true",
                "- no_fake_short_fill_created: true",
            ]
        )
    body_lines.extend(
        [
            "",
            "Demo order:",
            f"- event_type: {event_type}",
            f"- symbol: {record.get('symbol', '')}",
            f"- side: {record.get('demo_side', '')}",
            f"- order_type: {record.get('order_type', '')}",
            f"- quantity: {record.get('quantity', '')}",
            f"- client_order_id: {record.get('client_order_id', '')}",
            f"- exchange_order_id: {record.get('exchange_order_id', '')}",
            f"- exchange_status: {record.get('exchange_status', '')}",
            f"- executed_qty: {record.get('executed_qty', '')}",
            f"- quote_filled: {record.get('quote_filled', '')}",
            f"- created_at: {record.get('created_at', '')}",
            "",
            "Safety:",
            "- environment: Binance Spot Testnet demo only",
            "- real_money_allowed: false",
            "- live_allowed: false",
            "- production_order_path_allowed: false",
            "- paper_validation_ready: false",
            "- sizing: tiny exchange-minimum demo sizing, not EUR 25k strategy sizing",
            "- signal source: active frozen multi-symbol long-only scheduler ledger",
            "",
            f"Artifact root: {output_root}",
        ]
    )
    body = "\n".join(body_lines)
    event_dir.mkdir(parents=True, exist_ok=True)
    event_text = f"To: {recipient}\nSubject: {subject}\n\n{body}\n"
    event_path.write_text(event_text, encoding="utf-8")
    latest_path.write_text(event_text, encoding="utf-8")
    sent = False
    note = "draft_written"
    smtp_allowed, smtp_gate_note = smtp_allowed_for_output_root(output_root)
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
        "event_type": event_type,
        "source_trade_id": source_trade_id,
        "client_order_id": client_order_id,
        "email_recipient": recipient,
        "email_sent": sent,
        "email_draft_written": True,
        "email_path": str(event_path),
        "latest_email_path": str(latest_path),
        "email_note": note,
    }


def _order_event_subject(event_type: str, record: dict[str, Any]) -> str:
    prefix = os.getenv("RTS_DEMO_EMAIL_SUBJECT_PREFIX", "RTS 6-MONTH BINANCE SPOT TESTNET DEMO")
    symbol = record.get("symbol", "")
    side = record.get("demo_side", "")
    status = record.get("exchange_status", "")
    if event_type == "EXIT":
        net_pnl = _decimal(record.get("net_pnl_quote"))
        pnl_suffix = f" {net_pnl:+f} USDT" if net_pnl else ""
        if net_pnl > 0:
            return f"{prefix} EXIT - CONGRATULATIONS PROFIT: {symbol} {side} {status}{pnl_suffix}"
        if net_pnl < 0:
            return f"{prefix} EXIT - LOSS CONTROL: {symbol} {side} {status}{pnl_suffix}"
        return f"{prefix} EXIT - FLAT: {symbol} {side} {status}"
    if event_type == "SHORT_SIGNAL":
        return f"{prefix} SHORT SIGNAL: {symbol} SHORT NOT EXECUTED ON SPOT TESTNET"
    return f"{prefix} {event_type}: {symbol} {side} {status}"


def _order_event_heading(event_type: str) -> str:
    if event_type == "SHORT_SIGNAL":
        return "Demo walk-forward short signal observed."
    return f"Demo walk-forward {event_type.lower()} order event."


def _existing_records(output_root: Path) -> list[dict[str, Any]]:
    return [dict(row) for row in _read_csv(_ledger_path(output_root))]


def _decimal(value: Any, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value not in {None, ""} else default))
    except Exception:
        return Decimal(default)


def _plain_decimal(value: Decimal, places: int = 8) -> str:
    quant = Decimal("1").scaleb(-places)
    text = format(value.quantize(quant), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _existing_exit_trade_ids(records: list[dict[str, Any]]) -> set[str]:
    return {
        str(row.get("source_trade_id", ""))
        for row in records
        if _is_true(str(row.get("submitted", ""))) and str(row.get("order_event_type", "")).upper() == "EXIT"
    }


def _open_entry_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    exited = _existing_exit_trade_ids(records)
    entries = [
        row
        for row in records
        if _is_true(str(row.get("submitted", "")))
        and str(row.get("order_event_type", "")).upper() == "ENTRY"
        and str(row.get("source_trade_id", "")) not in exited
        and str(row.get("exchange_status", "")).upper() in {"FILLED", "PARTIALLY_FILLED"}
    ]
    return sorted(entries, key=lambda row: str(row.get("created_at", "")))


def _short_signal_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "created_at": _now(),
        "source_trade_id": item.get("source_trade_id", ""),
        "source_decision_id": item.get("source_decision_id", ""),
        "source_timestamp": item.get("timestamp", ""),
        "symbol": item.get("symbol", ""),
        "direction": item.get("direction", ""),
        "source_state": item.get("state", ""),
        "source_entry_reference": item.get("entry_reference", ""),
        "source_stop_reference": item.get("stop_reference", ""),
        "source_target_reference": item.get("target_reference", ""),
        "source_research_only": item.get("research_only", ""),
        "source_no_order_sent": item.get("no_order_sent", ""),
        "source_broker_path_exists": item.get("broker_path_exists", ""),
        "bridge_reason": "short_signal_observed_spot_testnet_execution_not_available",
        "execution_scope": "binance_spot_testnet_demo_signal_email_only",
        "exit_handling_note": "no_short_position_opened_no_exit_order_possible_on_spot_testnet",
        "order_event_type": "SHORT_SIGNAL",
        "position_effect": "DEMO_SHORT_SIGNAL_ONLY_NO_POSITION",
        "demo_side": "SHORT_SIGNAL_ONLY",
        "order_type": "NONE",
        "quantity": "",
        "client_order_id": "",
        "exchange_order_id": "",
        "exchange_status": "NOT_EXECUTED_ON_SPOT_TESTNET",
        "executed_qty": "",
        "quote_filled": "",
        "submitted": False,
        "skipped": True,
        "skip_reason": item.get("skip_reason", ""),
        "error": "",
    }


def _exit_reason_for_price(entry: dict[str, Any], price: Decimal) -> tuple[str, Decimal] | None:
    target = _decimal(entry.get("source_target_reference"))
    stop = _decimal(entry.get("source_stop_reference"))
    if target > 0 and price >= target:
        return "target_reached", target
    if stop > 0 and price <= stop:
        return "stop_reached", stop
    return None


def _submit_demo_exit(client: Any, entry: dict[str, Any]) -> dict[str, Any] | None:
    symbol = str(entry.get("symbol", "")).upper()
    if not symbol:
        return None
    price = client.ticker_price(symbol)
    exit_signal = _exit_reason_for_price(entry, price)
    if exit_signal is None:
        return None
    exit_reason, exit_reference = exit_signal
    exchange_info = client.exchange_info(symbol)
    rules = parse_symbol_rules(exchange_info, symbol)
    quantity = floor_to_step(_decimal(entry.get("executed_qty")), rules.step_size)
    if quantity <= 0:
        return None
    signal_id = f"{entry.get('source_trade_id', '')}:exit:{exit_reason}"
    intent = DemoOrderIntent(
        signal_id=signal_id,
        symbol=symbol,
        side="SELL",
        order_type="MARKET",
        quantity=quantity,
        reason=f"walk_forward_demo_bridge_long_exit_{exit_reason}",
    )
    client_order_id = build_client_order_id("wfdemox", signal_id)
    response = client.create_order(intent, client_order_id)
    exchange_client_id = str(response.get("clientOrderId") or client_order_id)
    exchange_order_id = response.get("orderId") or ""
    status = client.get_order(symbol, exchange_client_id, exchange_order_id)
    exit_qty = _decimal(status.get("executedQty"), str(quantity))
    entry_qty = _decimal(entry.get("executed_qty"))
    entry_quote = _decimal(entry.get("quote_filled"))
    exit_quote = _decimal(status.get("cummulativeQuoteQty"))
    comparable_qty = min(entry_qty, exit_qty) if entry_qty > 0 and exit_qty > 0 else exit_qty
    entry_avg = entry_quote / entry_qty if entry_qty > 0 else _decimal(entry.get("source_entry_reference"))
    exit_avg = exit_quote / exit_qty if exit_qty > 0 else price
    gross_pnl = (exit_avg - entry_avg) * comparable_qty
    fee_rate = _decimal(os.getenv("WALK_FORWARD_DEMO_ESTIMATED_FEE_RATE", "0.001"))
    estimated_fees = (entry_avg * comparable_qty + exit_avg * comparable_qty) * fee_rate
    net_pnl = gross_pnl - estimated_fees
    reference_risk_per_unit = abs(_decimal(entry.get("source_entry_reference")) - _decimal(entry.get("source_stop_reference")))
    risk_quote = reference_risk_per_unit * comparable_qty
    net_r = net_pnl / risk_quote if risk_quote > 0 else Decimal("0")
    entry_time = _parse_timestamp(str(entry.get("created_at", "")))
    exit_time = _parse_timestamp(_now())
    holding_seconds = int((exit_time - entry_time).total_seconds()) if entry_time and exit_time else ""
    return {
        "created_at": exit_time.isoformat() if exit_time else _now(),
        "source_trade_id": entry.get("source_trade_id", ""),
        "source_decision_id": entry.get("source_decision_id", ""),
        "source_timestamp": entry.get("source_timestamp", ""),
        "symbol": symbol,
        "direction": entry.get("direction", ""),
        "source_state": entry.get("source_state", ""),
        "source_entry_reference": entry.get("source_entry_reference", ""),
        "source_stop_reference": entry.get("source_stop_reference", ""),
        "source_target_reference": entry.get("source_target_reference", ""),
        "source_amount_bought_eur": entry.get("source_amount_bought_eur", ""),
        "source_position_notional_eur": entry.get("source_position_notional_eur", ""),
        "source_risk_eur": entry.get("source_risk_eur", ""),
        "source_total_equity_after_event_eur": entry.get("source_total_equity_after_event_eur", ""),
        "source_active_equity_reference_eur": entry.get("source_active_equity_reference_eur", ""),
        "source_research_only": entry.get("source_research_only", ""),
        "source_no_order_sent": entry.get("source_no_order_sent", ""),
        "source_broker_path_exists": entry.get("source_broker_path_exists", ""),
        "bridge_reason": f"walk_forward_demo_bridge_long_exit_{exit_reason}",
        "execution_scope": "binance_spot_testnet_demo_only",
        "exit_handling_note": "spot_testnet_demo_exit_close_submitted_from_original_research_stop_target_reference",
        "order_event_type": "EXIT",
        "position_effect": "DEMO_SPOT_LONG_EXIT_CLOSE",
        "demo_side": "SELL",
        "order_type": "MARKET",
        "quantity": str(quantity),
        "client_order_id": client_order_id,
        "exchange_order_id": str(status.get("orderId", exchange_order_id)),
        "exchange_status": str(status.get("status", "")),
        "executed_qty": str(status.get("executedQty", "")),
        "quote_filled": str(status.get("cummulativeQuoteQty", "")),
        "submitted": True,
        "skipped": False,
        "skip_reason": "",
        "error": "",
        "entry_created_at": entry.get("created_at", ""),
        "entry_executed_qty": entry.get("executed_qty", ""),
        "entry_quote_filled": entry.get("quote_filled", ""),
        "entry_exchange_order_id": entry.get("exchange_order_id", ""),
        "exit_reason": exit_reason,
        "exit_trigger_price": _plain_decimal(price),
        "exit_reference": _plain_decimal(exit_reference),
        "gross_pnl_quote": _plain_decimal(gross_pnl),
        "estimated_fees_quote": _plain_decimal(estimated_fees),
        "net_pnl_quote": _plain_decimal(net_pnl),
        "net_r_multiple": _plain_decimal(net_r, 6),
        "result_label": "WIN" if net_pnl > 0 else "LOSS" if net_pnl < 0 else "FLAT",
        "holding_seconds": holding_seconds,
    }


def _submit_demo_entry(client: Any, row: dict[str, str]) -> dict[str, Any]:
    symbol = row["symbol"].upper()
    exchange_info = client.exchange_info(symbol)
    rules = parse_symbol_rules(exchange_info, symbol)
    reference_price = client.ticker_price(symbol)
    quantity = compute_minimum_quantity(reference_price, rules)
    quantity = floor_to_step(quantity * Decimal("1.25"), rules.step_size)
    intent = DemoOrderIntent(
        signal_id=row["trade_id"],
        symbol=symbol,
        side="BUY",
        order_type="MARKET",
        quantity=quantity,
        reason="walk_forward_demo_bridge_long_entry",
    )
    client_order_id = build_client_order_id("wfdemo", row["trade_id"])
    response = client.create_order(intent, client_order_id)
    exchange_client_id = str(response.get("clientOrderId") or client_order_id)
    exchange_order_id = response.get("orderId") or ""
    status = client.get_order(symbol, exchange_client_id, exchange_order_id)
    return {
        "created_at": _now(),
        "source_trade_id": row["trade_id"],
        "source_decision_id": row.get("decision_id", ""),
        "source_timestamp": row.get("timestamp", ""),
        "symbol": symbol,
        "direction": row.get("direction", ""),
        "source_state": row.get("state", ""),
        "source_entry_reference": row.get("entry_reference", ""),
        "source_stop_reference": row.get("stop_reference", ""),
        "source_target_reference": row.get("target_reference", ""),
        "source_amount_bought_eur": row.get("amount_bought_eur", ""),
        "source_position_notional_eur": row.get("position_notional_eur", ""),
        "source_risk_eur": row.get("risk_eur", ""),
        "source_total_equity_after_event_eur": row.get("total_equity_after_event_eur", ""),
        "source_active_equity_reference_eur": row.get("active_equity_reference_eur", ""),
        "source_research_only": row.get("research_only", ""),
        "source_no_order_sent": row.get("no_order_sent", ""),
        "source_broker_path_exists": row.get("broker_path_exists", ""),
        "bridge_reason": "walk_forward_demo_bridge_long_entry_from_research_signal",
        "execution_scope": "binance_spot_testnet_demo_only",
        "exit_handling_note": "spot_testnet_demo_exit_email_requires_future_exit_event; no production exit/order path is enabled",
        "order_event_type": "ENTRY",
        "position_effect": "DEMO_SPOT_LONG_ENTRY",
        "demo_side": "BUY",
        "order_type": "MARKET",
        "quantity": str(quantity),
        "client_order_id": client_order_id,
        "exchange_order_id": str(status.get("orderId", exchange_order_id)),
        "exchange_status": str(status.get("status", "")),
        "executed_qty": str(status.get("executedQty", "")),
        "quote_filled": str(status.get("cummulativeQuoteQty", "")),
        "submitted": True,
        "skipped": False,
        "skip_reason": "",
        "error": "",
    }


FIELDNAMES = [
    "created_at",
    "source_trade_id",
    "source_decision_id",
    "source_timestamp",
    "symbol",
    "direction",
    "source_state",
    "source_entry_reference",
    "source_stop_reference",
    "source_target_reference",
    "source_amount_bought_eur",
    "source_position_notional_eur",
    "source_risk_eur",
    "source_total_equity_after_event_eur",
    "source_active_equity_reference_eur",
    "source_research_only",
    "source_no_order_sent",
    "source_broker_path_exists",
    "bridge_reason",
    "execution_scope",
    "exit_handling_note",
    "order_event_type",
    "position_effect",
    "demo_side",
    "order_type",
    "quantity",
    "client_order_id",
    "exchange_order_id",
    "exchange_status",
    "executed_qty",
    "quote_filled",
    "submitted",
    "skipped",
    "skip_reason",
    "error",
    "entry_created_at",
    "entry_executed_qty",
    "entry_quote_filled",
    "entry_exchange_order_id",
    "exit_reason",
    "exit_trigger_price",
    "exit_reference",
    "gross_pnl_quote",
    "estimated_fees_quote",
    "net_pnl_quote",
    "net_r_multiple",
    "result_label",
    "holding_seconds",
]


def run(
    mode: str,
    *,
    source_ledger: Path | None = None,
    output_root: Path | None = None,
    client: Any | None = None,
) -> dict[str, Any]:
    config = config_from_env(mode, source_ledger=source_ledger, output_root=output_root)
    config.output_root.mkdir(parents=True, exist_ok=True)
    records = _existing_records(config.output_root)
    skipped_records: list[dict[str, Any]] = []
    summary: dict[str, Any] = {
        "court_name": COURT_NAME,
        "created_at": _now(),
        "mode": mode,
        "source_ledger": str(config.source_ledger),
        "output_root": str(config.output_root),
        "symbol_allowlist": list(config.symbol_allowlist),
        "max_orders_per_run": config.max_orders_per_run,
        "max_exits_per_run": config.max_exits_per_run,
        "lookback_hours": config.lookback_hours,
        "process_order": config.process_order,
        "walk_forward_demo_execution_enabled": config.enabled,
        "walk_forward_demo_allow_backlog_replay": config.allow_backlog_replay,
        "source_strategy_ledger": "active_multi_symbol_frozen_forward_decision_ledger",
        "spot_compatible_long_only": True,
        "short_selling_allowed": False,
        "activation_checkpoint": "",
        "base_url": "",
        "credentials_present": False,
        "source_rows_seen": 0,
        "eligible_signals_seen": 0,
        "orders_submitted": 0,
        "entry_orders_submitted": 0,
        "exit_orders_submitted": 0,
        "open_entries_seen": 0,
        "open_entries_triggered_for_exit": 0,
        "short_signal_emails_sent": 0,
        "short_signal_email_drafts_written": 0,
        "order_event_emails_sent": 0,
        "order_event_email_drafts_written": 0,
        "order_event_email_records": [],
        "signals_skipped": 0,
        "latest_source_trade_id": "",
        "strategy_changed": False,
        "scheduler_changed": False,
        "candidate_deployed_to_scheduler": False,
        **SAFETY_FLAGS,
    }
    summary["paper_validation_ready"] = False
    summary["live_allowed"] = False
    summary["real_money_allowed"] = False
    summary["production_order_path_allowed"] = False
    summary["production_broker_path_allowed"] = False

    try:
        validate_base_url("https://api.binance.com/api")
        raise BinanceDemoSafetyError("production endpoint was not blocked")
    except BinanceDemoSafetyError:
        summary["production_endpoint_blocked"] = True

    try:
        source_rows = _read_csv(config.source_ledger)
        summary["source_rows_seen"] = len(source_rows)
        source_max_timestamp = _source_max_timestamp(source_rows)
        activation_timestamp = None
        if not config.allow_backlog_replay:
            activation_timestamp = _read_activation_timestamp(config.output_root)
            if activation_timestamp is None:
                activation_timestamp = source_max_timestamp
                _write_activation_timestamp(
                    config.output_root,
                    activation_timestamp,
                    reason="initial_activation_checkpoint_blocks_historical_replay",
                )
        summary["activation_checkpoint"] = activation_timestamp.isoformat() if activation_timestamp else ""
        candidates, skipped = _candidate_rows(config, activation_timestamp=activation_timestamp)
        skipped_records.extend(skipped)
        summary["eligible_signals_seen"] = len(candidates)

        if mode == "dry_run":
            summary["final_classification"] = DRY_RUN_READY if candidates else NO_ELIGIBLE
        elif mode == "execute_once":
            if not config.enabled:
                raise BinanceDemoSafetyError("WALK_FORWARD_DEMO_EXECUTION_ENABLED must be true for execute_once")
            if config.max_orders_per_run <= 0:
                raise BinanceDemoSafetyError("WALK_FORWARD_DEMO_MAX_ORDERS_PER_RUN must be positive")
            if client is None:
                demo_config = BinanceDemoConfig.from_env(require_credentials=True)
                summary["base_url"] = demo_config.base_url
                summary["credentials_present"] = True
                client = BinanceDemoClient(demo_config)
            else:
                summary["base_url"] = "mock_client"
                summary["credentials_present"] = True
            try:
                client.account()
            except AttributeError:
                pass
            open_entries = _open_entry_records(records)
            summary["open_entries_seen"] = len(open_entries)
            for entry in open_entries[: config.max_exits_per_run]:
                try:
                    exit_record = _submit_demo_exit(client, entry)
                except BinanceDemoExecutionError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise BinanceDemoExecutionError(str(exc)) from exc
                if exit_record is None:
                    continue
                records.append(exit_record)
                event_email = _safe_order_event_alert(config.output_root, exit_record)
                summary["order_event_email_records"].append(event_email)
                if event_email.get("email_sent"):
                    summary["order_event_emails_sent"] += 1
                if event_email.get("email_draft_written"):
                    summary["order_event_email_drafts_written"] += 1
                summary["orders_submitted"] += 1
                summary["exit_orders_submitted"] += 1
                summary["open_entries_triggered_for_exit"] += 1
                summary["latest_source_trade_id"] = str(exit_record.get("source_trade_id", ""))
            for row in candidates[: config.max_orders_per_run]:
                try:
                    record = _submit_demo_entry(client, row)
                except BinanceDemoExecutionError:
                    raise
                except Exception as exc:  # noqa: BLE001
                    raise BinanceDemoExecutionError(str(exc)) from exc
                records.append(record)
                event_email = _safe_order_event_alert(config.output_root, record)
                summary["order_event_email_records"].append(event_email)
                if event_email.get("email_sent"):
                    summary["order_event_emails_sent"] += 1
                if event_email.get("email_draft_written"):
                    summary["order_event_email_drafts_written"] += 1
                summary["orders_submitted"] += 1
                summary["entry_orders_submitted"] += 1
                summary["latest_source_trade_id"] = row["trade_id"]
            summary["final_classification"] = READY if summary["orders_submitted"] else NO_ELIGIBLE
            if summary["orders_submitted"] and source_max_timestamp is not None and not config.allow_backlog_replay:
                _write_activation_timestamp(
                    config.output_root,
                    source_max_timestamp,
                    reason="post_execution_watermark_advanced_to_latest_seen_source_timestamp",
                )
        else:
            raise BinanceDemoSafetyError(f"unsupported mode: {mode}")
    except BinanceDemoSafetyError as exc:
        summary["final_classification"] = FAILED_SAFETY
        summary["safety_error"] = str(exc)
    except BinanceDemoExecutionError as exc:
        summary["final_classification"] = FAILED_EXECUTION
        summary["execution_error"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        summary["final_classification"] = BLOCKED
        summary["blocked_error"] = str(exc)

    skip_rows = [
        {
            "created_at": _now(),
            "source_trade_id": item.get("source_trade_id", ""),
            "source_decision_id": item.get("source_decision_id", ""),
            "source_timestamp": item.get("timestamp", ""),
            "symbol": item.get("symbol", ""),
            "direction": item.get("direction", ""),
            "source_state": item.get("state", ""),
            "source_entry_reference": item.get("entry_reference", ""),
            "source_stop_reference": item.get("stop_reference", ""),
            "source_target_reference": item.get("target_reference", ""),
            "source_amount_bought_eur": item.get("amount_bought_eur", ""),
            "source_position_notional_eur": item.get("position_notional_eur", ""),
            "source_risk_eur": item.get("risk_eur", ""),
            "source_total_equity_after_event_eur": item.get("total_equity_after_event_eur", ""),
            "source_active_equity_reference_eur": item.get("active_equity_reference_eur", ""),
            "source_research_only": item.get("research_only", ""),
            "source_no_order_sent": item.get("no_order_sent", ""),
            "source_broker_path_exists": item.get("broker_path_exists", ""),
            "bridge_reason": "",
            "execution_scope": "binance_spot_testnet_demo_only",
            "exit_handling_note": "",
            "order_event_type": "",
            "position_effect": "",
            "demo_side": "",
            "order_type": "",
            "quantity": "",
            "client_order_id": "",
            "exchange_order_id": "",
            "exchange_status": "",
            "executed_qty": "",
            "quote_filled": "",
            "submitted": False,
            "skipped": True,
            "skip_reason": item.get("skip_reason", ""),
            "error": "",
        }
        for item in skipped_records
    ]
    summary["signals_skipped"] = len(skip_rows)
    all_records = records + skip_rows
    _write_csv(_ledger_path(config.output_root), all_records, FIELDNAMES)
    _write_json(
        config.output_root / "walk_forward_demo_execution_safety_manifest.json",
        {
            **SAFETY_FLAGS,
            "paper_validation_ready": False,
            "live_allowed": False,
            "real_money_allowed": False,
            "production_endpoint_blocked": summary.get("production_endpoint_blocked", False),
            "testnet_order_path_allowed": True,
            "strategy_changed": False,
            "scheduler_changed": False,
            "source_runtime_mutated": False,
            "spot_testnet_shorts_skipped": True,
            "spot_compatible_long_only": True,
            "short_selling_allowed": False,
            "source_strategy_ledger": "active_multi_symbol_frozen_forward_decision_ledger",
        },
    )
    summary.update(_no_run_level_email_policy())
    _write_json(config.output_root / "walk_forward_demo_execution_summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--mode", choices=["dry_run", "execute_once"], default="dry_run")
    parser.add_argument("--source-ledger", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(_jsonable(run(args.mode, source_ledger=args.source_ledger)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
