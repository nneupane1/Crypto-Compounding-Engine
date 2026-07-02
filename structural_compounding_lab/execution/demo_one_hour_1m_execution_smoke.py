from __future__ import annotations

import argparse
import csv
import json
import os
import smtplib
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from structural_compounding_lab.common.email_safety import smtp_allowed_for_output_root
from structural_compounding_lab.common.project_paths import output_root, resolve_project_path
from structural_compounding_lab.execution.binance_demo_client import (
    BinanceDemoClient,
    BinanceDemoConfig,
    BinanceDemoExecutionError,
    BinanceDemoSafetyError,
    build_client_order_id,
    compute_minimum_quantity,
    parse_symbol_rules,
    redact_secret,
)
from structural_compounding_lab.execution.demo_order_models import DemoOrderIntent, SAFETY_FLAGS


COURT_NAME = "BINANCE_DEMO_ONE_HOUR_1M_EXECUTION_SMOKE_COURT_PAPER_ONLY"
OUTPUT_FOLDER_NAME = "binance_demo_one_hour_1m_execution_smoke_court_001"
RUNNING = "BINANCE_DEMO_ONE_HOUR_1M_EXECUTION_SMOKE_RUNNING_PAPER_ONLY"
COMPLETED = "BINANCE_DEMO_ONE_HOUR_1M_EXECUTION_SMOKE_COMPLETED_PAPER_ONLY"
BLOCKED = "BINANCE_DEMO_ONE_HOUR_1M_EXECUTION_SMOKE_BLOCKED"
FAILED = "BINANCE_DEMO_ONE_HOUR_1M_EXECUTION_SMOKE_FAILED"

DEFAULT_SYMBOL = "BTCUSDT"
DEFAULT_ALERT_TO = "nneupane1@gmail.com"
DEMO_ENV_PREFIXES = ("BINANCE_DEMO_", "RTS_ALERT_")
DEMO_ENV_KEYS = {"TRADING_SYSTEM_CONFIG"}
FORBIDDEN_LIVE_ENV_NAMES = {
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_SECRET",
    "LIVE_API_KEY",
    "LIVE_API_SECRET",
}


@dataclass(frozen=True)
class SmokeConfig:
    output_root: Path
    symbol: str
    duration_seconds: int
    interval_seconds: int
    aggressive: bool
    max_round_trips: int
    client: BinanceDemoClient | Any


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_text() -> str:
    return _now().isoformat()


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


def _reject_live_env() -> None:
    present = [key for key in sorted(FORBIDDEN_LIVE_ENV_NAMES) if os.getenv(key)]
    if present:
        raise BinanceDemoSafetyError(
            "Refusing 1m demo execution smoke because live-looking environment variables are present: "
            + ",".join(present)
        )


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
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


def _append_csv(path: Path, row: dict[str, Any], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({key: _jsonable(row.get(key, "")) for key in fieldnames})


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else dict(default)
    except Exception:
        return dict(default)


def _paths(root: Path) -> dict[str, Path]:
    return {
        "state": root / "state" / "one_hour_1m_execution_smoke_state.json",
        "heartbeat": root / "heartbeat.csv",
        "orders": root / "ledger" / "one_hour_1m_execution_smoke_orders.csv",
        "latest_status": root / "latest_status.json",
        "final_summary": root / "final_summary.json",
        "latest_email": root / "alerts" / "order_events" / "latest_one_hour_1m_smoke_order_email.txt",
        "email_ledger": root / "alerts" / "order_events" / "one_hour_1m_smoke_order_email_ledger.csv",
        "pid": root / "run.pid",
    }


def _default_state() -> dict[str, Any]:
    return {
        "open_position": False,
        "symbol": DEFAULT_SYMBOL,
        "entry_order_id": "",
        "entry_client_order_id": "",
        "entry_time": "",
        "entry_price": "",
        "base_quantity": "0",
        "round_trips_completed": 0,
        "orders_submitted": 0,
        "last_closed_kline_open_time": "",
        "created_at": _now_text(),
    }


def _closed_1m_klines(client: BinanceDemoClient | Any, symbol: str) -> list[dict[str, Any]]:
    payload = client.request(
        "GET",
        "/v3/klines",
        params={"symbol": symbol.upper(), "interval": "1m", "limit": 4},
        signed=False,
    )
    now_ms = int(time.time() * 1000)
    rows: list[dict[str, Any]] = []
    for item in payload:
        if len(item) < 7:
            continue
        close_time_ms = int(item[6])
        if close_time_ms >= now_ms:
            continue
        rows.append(
            {
                "open_time_ms": int(item[0]),
                "open_time": datetime.fromtimestamp(int(item[0]) / 1000, tz=timezone.utc).isoformat(),
                "open": Decimal(str(item[1])),
                "high": Decimal(str(item[2])),
                "low": Decimal(str(item[3])),
                "close": Decimal(str(item[4])),
                "volume": Decimal(str(item[5])),
                "close_time": datetime.fromtimestamp(close_time_ms / 1000, tz=timezone.utc).isoformat(),
            }
        )
    return rows


def _signal_from_klines(rows: list[dict[str, Any]], *, open_position: bool, aggressive: bool) -> tuple[str, str]:
    if len(rows) < 2:
        return "hold", "not_enough_closed_1m_candles"
    previous = rows[-2]
    latest = rows[-1]
    prev_close = Decimal(str(previous["close"]))
    close = Decimal(str(latest["close"]))
    open_ = Decimal(str(latest["open"]))
    high = Decimal(str(latest["high"]))
    low = Decimal(str(latest["low"]))
    candle_range = max(high - low, Decimal("0"))
    lower_wick = min(open_, close) - low
    upper_wick = high - max(open_, close)
    dipped = close < prev_close or (candle_range > 0 and lower_wick / candle_range >= Decimal("0.45"))
    popped = close > prev_close or (candle_range > 0 and upper_wick / candle_range >= Decimal("0.45"))
    if not open_position:
        if aggressive:
            return "buy", "aggressive_execution_smoke_buy_after_closed_1m_candle"
        if dipped:
            return "buy", "closed_1m_dip_or_lower_wick_detected"
        return "hold", "no_closed_1m_dip_signal"
    if aggressive:
        return "sell", "aggressive_execution_smoke_sell_next_cycle"
    if popped:
        return "sell", "closed_1m_pop_or_upper_wick_detected"
    return "hold", "open_demo_position_waiting_for_closed_1m_exit_signal"


def _order_fieldnames() -> list[str]:
    return [
        "created_at",
        "court_name",
        "symbol",
        "side",
        "signal_id",
        "client_order_id",
        "exchange_order_id",
        "status",
        "quantity",
        "executed_qty",
        "quote_filled",
        "reference_price",
        "reason",
        "closed_1m_open_time",
        "submitted",
        "error",
        "paper_validation_ready",
        "live_allowed",
        "real_money_allowed",
        "production_order_path_allowed",
        "testnet_order_path_allowed",
    ]


def _heartbeat_fieldnames() -> list[str]:
    return [
        "created_at",
        "iteration",
        "symbol",
        "final_classification",
        "signal",
        "reason",
        "open_position",
        "orders_submitted_total",
        "round_trips_completed",
        "latest_closed_1m_open_time",
        "latest_closed_1m_close",
        "paper_validation_ready",
        "live_allowed",
        "real_money_allowed",
    ]


def _safe_email(root: Path, event: dict[str, Any]) -> dict[str, Any]:
    paths = _paths(root)
    recipient = os.getenv("RTS_ALERT_EMAIL_TO", DEFAULT_ALERT_TO)
    enabled = os.getenv("RTS_ALERT_EMAIL_ENABLED", "").strip().lower() in {"1", "true", "yes"}
    dry_run = os.getenv("RTS_ALERT_EMAIL_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}
    host = os.getenv("RTS_ALERT_SMTP_HOST", "").strip()
    sender = os.getenv("RTS_ALERT_EMAIL_FROM", "").strip()
    username = os.getenv("RTS_ALERT_SMTP_USERNAME", "").strip()
    password = os.getenv("RTS_ALERT_SMTP_PASSWORD", "")
    side = str(event.get("side", "ORDER")).upper()
    subject = (
        f"RTS 1H DEMO 1M EXECUTION SMOKE {side}: "
        f"{event.get('symbol')} {event.get('status')} {event.get('client_order_id')}"
    )
    body = "\n".join(
        [
            "This is a Binance Spot Testnet execution-readiness smoke event.",
            "It is NOT the frozen research strategy and it is NOT live-money trading.",
            "",
            f"Court: {COURT_NAME}",
            f"Created: {event.get('created_at')}",
            f"Symbol: {event.get('symbol')}",
            f"Side: {event.get('side')}",
            f"Status: {event.get('status')}",
            f"Quantity: {event.get('quantity')}",
            f"Executed quantity: {event.get('executed_qty')}",
            f"Quote filled: {event.get('quote_filled')}",
            f"Reference price: {event.get('reference_price')}",
            f"Signal id: {event.get('signal_id')}",
            f"Client order id: {event.get('client_order_id')}",
            f"Exchange order id: {event.get('exchange_order_id')}",
            f"Reason: {event.get('reason')}",
            f"Closed 1m candle: {event.get('closed_1m_open_time')}",
            "",
            "Safety:",
            "- Binance Spot Testnet only",
            "- minimum-size demo order",
            "- paper_validation_ready=false",
            "- live_allowed=false",
            "- real_money_allowed=false",
            "- production_order_path_allowed=false",
            f"Artifact root: {root}",
        ]
    )
    paths["latest_email"].parent.mkdir(parents=True, exist_ok=True)
    paths["latest_email"].write_text(f"To: {recipient}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
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
    record = {
        "created_at": _now_text(),
        "symbol": event.get("symbol", ""),
        "side": event.get("side", ""),
        "client_order_id": event.get("client_order_id", ""),
        "exchange_order_id": event.get("exchange_order_id", ""),
        "email_sent": sent,
        "email_draft_written": True,
        "email_note": note,
        "email_path": str(paths["latest_email"]),
        "recipient": recipient,
    }
    _append_csv(
        paths["email_ledger"],
        record,
        [
            "created_at",
            "symbol",
            "side",
            "client_order_id",
            "exchange_order_id",
            "email_sent",
            "email_draft_written",
            "email_note",
            "email_path",
            "recipient",
        ],
    )
    return record


def _submit_market_order(
    config: SmokeConfig,
    *,
    state: dict[str, Any],
    side: str,
    reason: str,
    closed_1m_open_time: str,
    reference_price: Decimal,
) -> dict[str, Any]:
    symbol = config.symbol.upper()
    rules = parse_symbol_rules(config.client.exchange_info(symbol), symbol)
    if side == "BUY":
        quantity = compute_minimum_quantity(reference_price, rules)
    else:
        quantity = Decimal(str(state.get("base_quantity") or "0"))
        if quantity <= 0:
            raise BinanceDemoExecutionError("cannot_sell_without_recorded_demo_base_quantity")
    signal_id = f"{COURT_NAME}|{symbol}|{side}|{closed_1m_open_time}|{state.get('orders_submitted', 0)}"
    client_order_id = build_client_order_id("rts1m", signal_id)
    intent = DemoOrderIntent(
        signal_id=signal_id,
        symbol=symbol,
        side=side,  # type: ignore[arg-type]
        order_type="MARKET",
        quantity=quantity,
        reason=reason,
    )
    raw = config.client.create_order(intent, client_order_id)
    status = str(raw.get("status", ""))
    executed_qty = str(raw.get("executedQty", "0"))
    quote_filled = str(raw.get("cummulativeQuoteQty", raw.get("cumQuote", "0")))
    event = {
        "created_at": _now_text(),
        "court_name": COURT_NAME,
        "symbol": symbol,
        "side": side,
        "signal_id": signal_id,
        "client_order_id": client_order_id,
        "exchange_order_id": str(raw.get("orderId", "")),
        "status": status,
        "quantity": str(quantity),
        "executed_qty": executed_qty,
        "quote_filled": quote_filled,
        "reference_price": str(reference_price),
        "reason": reason,
        "closed_1m_open_time": closed_1m_open_time,
        "submitted": True,
        "error": "",
        "paper_validation_ready": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "production_order_path_allowed": False,
        "testnet_order_path_allowed": True,
    }
    _append_csv(_paths(config.output_root)["orders"], event, _order_fieldnames())
    _safe_email(config.output_root, event)
    state["orders_submitted"] = int(state.get("orders_submitted", 0)) + 1
    if side == "BUY":
        state["open_position"] = True
        state["entry_order_id"] = event["exchange_order_id"]
        state["entry_client_order_id"] = client_order_id
        state["entry_time"] = event["created_at"]
        state["entry_price"] = str(reference_price)
        state["base_quantity"] = executed_qty if Decimal(str(executed_qty or "0")) > 0 else str(quantity)
    else:
        state["open_position"] = False
        state["entry_order_id"] = ""
        state["entry_client_order_id"] = ""
        state["entry_time"] = ""
        state["entry_price"] = ""
        state["base_quantity"] = "0"
        state["round_trips_completed"] = int(state.get("round_trips_completed", 0)) + 1
    return event


def run_once(config: SmokeConfig, *, iteration: int) -> dict[str, Any]:
    paths = _paths(config.output_root)
    config.output_root.mkdir(parents=True, exist_ok=True)
    state = _read_json(paths["state"], _default_state())
    state["symbol"] = config.symbol.upper()
    rows = _closed_1m_klines(config.client, config.symbol)
    latest = rows[-1] if rows else {}
    latest_open_time = str(latest.get("open_time", ""))
    latest_close = Decimal(str(latest.get("close", "0") or "0"))
    signal, reason = _signal_from_klines(rows, open_position=bool(state.get("open_position")), aggressive=config.aggressive)
    order_event: dict[str, Any] | None = None
    error = ""
    if int(state.get("round_trips_completed", 0)) >= config.max_round_trips:
        signal = "hold"
        reason = "max_round_trips_reached"
    try:
        if signal in {"buy", "sell"}:
            order_event = _submit_market_order(
                config,
                state=state,
                side="BUY" if signal == "buy" else "SELL",
                reason=reason,
                closed_1m_open_time=latest_open_time,
                reference_price=latest_close if latest_close > 0 else config.client.ticker_price(config.symbol),
            )
    except Exception as exc:  # noqa: BLE001
        error = redact_secret(str(exc), os.getenv("BINANCE_DEMO_API_KEY", ""), os.getenv("BINANCE_DEMO_API_SECRET", ""))
    state["last_closed_kline_open_time"] = latest_open_time
    _write_json(paths["state"], state)
    heartbeat = {
        "created_at": _now_text(),
        "iteration": iteration,
        "symbol": config.symbol.upper(),
        "final_classification": RUNNING,
        "signal": signal,
        "reason": reason,
        "open_position": bool(state.get("open_position")),
        "orders_submitted_total": int(state.get("orders_submitted", 0)),
        "round_trips_completed": int(state.get("round_trips_completed", 0)),
        "latest_closed_1m_open_time": latest_open_time,
        "latest_closed_1m_close": str(latest_close),
        "paper_validation_ready": False,
        "live_allowed": False,
        "real_money_allowed": False,
    }
    _append_csv(paths["heartbeat"], heartbeat, _heartbeat_fieldnames())
    status = {
        **SAFETY_FLAGS,
        "court_name": COURT_NAME,
        "final_classification": RUNNING if not error else FAILED,
        "created_at": _now_text(),
        "artifact_root": str(config.output_root),
        "mode": "spot_testnet",
        "symbol": config.symbol.upper(),
        "duration_seconds": config.duration_seconds,
        "interval_seconds": config.interval_seconds,
        "aggressive_execution_smoke": config.aggressive,
        "max_round_trips": config.max_round_trips,
        "iteration": iteration,
        "signal": signal,
        "reason": reason,
        "latest_closed_1m_open_time": latest_open_time,
        "latest_closed_1m_close": str(latest_close),
        "open_position": bool(state.get("open_position")),
        "orders_submitted_total": int(state.get("orders_submitted", 0)),
        "round_trips_completed": int(state.get("round_trips_completed", 0)),
        "last_order_event": order_event or {},
        "error": error,
        "strategy_changed": False,
        "frozen_scheduler_changed": False,
        "candidate_deployed_to_scheduler": False,
        "paper_validation_ready": False,
        "live_allowed": False,
        "real_money_allowed": False,
        "production_order_path_allowed": False,
        "production_broker_path_allowed": False,
        "testnet_order_path_allowed": True,
    }
    _write_json(paths["latest_status"], status)
    return status


def run_supervisor(config: SmokeConfig) -> dict[str, Any]:
    paths = _paths(config.output_root)
    config.output_root.mkdir(parents=True, exist_ok=True)
    paths["pid"].write_text(str(os.getpid()), encoding="utf-8")
    started = time.monotonic()
    deadline = started + max(0, config.duration_seconds)
    iteration = 0
    last_status: dict[str, Any] = {}
    while True:
        iteration += 1
        last_status = run_once(config, iteration=iteration)
        if last_status.get("final_classification") == FAILED:
            break
        if time.monotonic() >= deadline:
            break
        sleep_for = min(max(1, config.interval_seconds), max(0, deadline - time.monotonic()))
        if sleep_for <= 0:
            break
        time.sleep(sleep_for)
    final = {
        **last_status,
        "final_classification": COMPLETED if last_status.get("final_classification") != FAILED else FAILED,
        "completed_at": _now_text(),
        "iterations_completed": iteration,
    }
    _write_json(paths["final_summary"], final)
    _write_json(paths["latest_status"], final)
    return final


def status(root: Path) -> dict[str, Any]:
    paths = _paths(root)
    if paths["latest_status"].exists():
        return json.loads(paths["latest_status"].read_text(encoding="utf-8"))
    return {
        **SAFETY_FLAGS,
        "court_name": COURT_NAME,
        "final_classification": BLOCKED,
        "artifact_root": str(root),
        "reason": "latest_status_missing",
        "paper_validation_ready": False,
        "live_allowed": False,
        "real_money_allowed": False,
    }


def build_config(args: argparse.Namespace) -> SmokeConfig:
    _load_demo_env_from_dotenv()
    _reject_live_env()
    os.environ.setdefault("BINANCE_DEMO_MODE", "spot_testnet")
    os.environ.setdefault("BINANCE_DEMO_API_TEST_CONFIRM", "YES_TESTNET_ONLY")
    demo_config = BinanceDemoConfig.from_env(require_credentials=True)
    if demo_config.mode != "spot_testnet":
        raise BinanceDemoSafetyError("1m execution smoke supports spot_testnet only")
    root = resolve_project_path(args.output_dir) if args.output_dir else output_root() / OUTPUT_FOLDER_NAME
    return SmokeConfig(
        output_root=root,
        symbol=args.symbol.upper(),
        duration_seconds=int(args.duration_seconds),
        interval_seconds=int(args.interval_seconds),
        aggressive=bool(args.aggressive),
        max_round_trips=int(args.max_round_trips),
        client=BinanceDemoClient(demo_config),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["run_once", "run_supervisor", "status"], default="status")
    parser.add_argument("--symbol", default=DEFAULT_SYMBOL)
    parser.add_argument("--duration-seconds", type=int, default=3600)
    parser.add_argument("--interval-seconds", type=int, default=60)
    parser.add_argument("--max-round-trips", type=int, default=20)
    parser.add_argument("--aggressive", action="store_true", help="Force buy/sell churn for execution-readiness testing.")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = resolve_project_path(args.output_dir)
    if args.mode == "status":
        print(json.dumps(_jsonable(status(root)), indent=2, sort_keys=True))
        return
    try:
        config = build_config(args)
        result = run_once(config, iteration=1) if args.mode == "run_once" else run_supervisor(config)
    except (BinanceDemoSafetyError, BinanceDemoExecutionError, Exception) as exc:  # noqa: BLE001
        result = {
            **SAFETY_FLAGS,
            "court_name": COURT_NAME,
            "final_classification": FAILED,
            "created_at": _now_text(),
            "artifact_root": str(root),
            "error": redact_secret(str(exc), os.getenv("BINANCE_DEMO_API_KEY", ""), os.getenv("BINANCE_DEMO_API_SECRET", "")),
            "paper_validation_ready": False,
            "live_allowed": False,
            "real_money_allowed": False,
            "production_order_path_allowed": False,
        }
        _write_json(_paths(root)["latest_status"], result)
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
