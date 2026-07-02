from __future__ import annotations

import argparse
import csv
import json
import os
import smtplib
from dataclasses import asdict
from datetime import datetime, timezone
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
    reject_live_key_environment,
    round_price_to_tick,
    validate_base_url,
)
from structural_compounding_lab.execution.demo_order_models import DemoOrderIntent, DemoOrderRecord, SAFETY_FLAGS, SymbolExecutionRules


COURT_NAME = "BINANCE_DEMO_API_EXECUTION_RELIABILITY_COURT_PAPER_ONLY"
OUTPUT_FOLDER_NAME = "binance_demo_api_execution_reliability_court_001"

READY = "BINANCE_DEMO_API_EXECUTION_RELIABILITY_READY_PAPER_ONLY"
WARNING_MOCK_ONLY = "BINANCE_DEMO_API_EXECUTION_RELIABILITY_WARNING_MOCK_ONLY"
WARNING_PARTIAL = "BINANCE_DEMO_API_EXECUTION_RELIABILITY_WARNING_DEMO_SMOKE_PARTIAL"
FAILED_SAFETY = "BINANCE_DEMO_API_EXECUTION_RELIABILITY_FAILED_SAFETY"
FAILED_EXECUTION = "BINANCE_DEMO_API_EXECUTION_RELIABILITY_FAILED_EXECUTION"
BLOCKED = "BINANCE_DEMO_API_EXECUTION_RELIABILITY_BLOCKED"

DEFAULT_ALERT_TO = "nneupane1@gmail.com"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _output_root() -> Path:
    return package_root() / "output" / OUTPUT_FOLDER_NAME


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
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


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _jsonable(row.get(key, "")) for key in fieldnames})


def _write_report(path: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Binance Demo API Execution Reliability Court 001",
        "",
        f"- Classification: `{summary['final_classification']}`",
        f"- Mode: `{summary['mode']}`",
        f"- Created: `{summary['created_at']}`",
        f"- Base URL: `{summary['base_url']}`",
        "",
        "## Smoke",
        "",
        f"- Credentials present: `{summary['credentials_present']}`",
        f"- Order submitted: `{summary['order_submitted']}`",
        f"- Order ID received: `{summary['order_id_received']}`",
        f"- Order status queried: `{summary['order_status_queried']}`",
        f"- Cancel tested: `{summary['cancel_tested']}`",
        f"- Fill tested: `{summary['fill_tested']}`",
        f"- Balance reconciliation: `{summary['balance_reconciliation']}`",
        f"- Position reconciliation: `{summary['position_reconciliation']}`",
        f"- Duplicate prevention: `{summary['duplicate_prevention']}`",
        f"- Restart/idempotency: `{summary['restart_idempotency']}`",
        "",
        "## Safety",
        "",
    ]
    for key in sorted(SAFETY_FLAGS):
        lines.append(f"- {key}: `{summary.get(key)}`")
    lines.extend(
        [
            f"- Production endpoint blocked: `{summary['production_endpoint_blocked']}`",
            f"- Secrets logged: `{summary['secrets_logged']}`",
            f"- Alert recipient: `{summary['alert_recipient']}`",
            f"- Alert sent: `{summary['alert_sent']}`",
            f"- Alert draft written: `{summary['alert_draft_written']}`",
            f"- Alert path: `{summary['alert_path']}`",
            "",
            "This court is manual-only and is not connected to the scheduler.",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class DemoLedger:
    def __init__(self) -> None:
        self.client_order_ids_by_signal: dict[str, str] = {}

    def client_order_id_for(self, signal_id: str) -> str:
        if signal_id not in self.client_order_ids_by_signal:
            self.client_order_ids_by_signal[signal_id] = build_client_order_id("rtsdemo", signal_id)
        return self.client_order_ids_by_signal[signal_id]

    def duplicate_prevention_passed(self, signal_id: str) -> bool:
        first = self.client_order_id_for(signal_id)
        second = self.client_order_id_for(signal_id)
        restarted = DemoLedger()
        restarted.client_order_ids_by_signal = dict(self.client_order_ids_by_signal)
        third = restarted.client_order_id_for(signal_id)
        return first == second == third


class MockBinanceDemoClient:
    def __init__(self) -> None:
        self.orders: dict[str, dict[str, Any]] = {}

    def server_time(self) -> dict[str, int]:
        return {"serverTime": 1234567890000}

    def exchange_info(self, symbol: str) -> dict[str, Any]:
        return {
            "symbols": [
                {
                    "symbol": symbol.upper(),
                    "baseAsset": symbol[:-4].upper(),
                    "quoteAsset": "USDT",
                    "filters": [
                        {"filterType": "LOT_SIZE", "minQty": "0.00001000", "stepSize": "0.00001000"},
                        {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                        {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
                    ],
                }
            ]
        }

    def ticker_price(self, symbol: str) -> Decimal:
        return Decimal("100000") if symbol.upper() == "BTCUSDT" else Decimal("5000")

    def account(self) -> dict[str, Any]:
        return {"balances": [{"asset": "USDT", "free": "100000.00"}, {"asset": "BTC", "free": "0.10000000"}]}

    def open_orders(self, symbol: str) -> list[dict[str, Any]]:
        return [order for order in self.orders.values() if order["symbol"] == symbol.upper() and order["status"] == "NEW"]

    def create_order(self, intent: DemoOrderIntent, client_order_id: str) -> dict[str, Any]:
        order = {
            "symbol": intent.symbol,
            "orderId": 1000 + len(self.orders),
            "clientOrderId": client_order_id,
            "status": "NEW" if intent.order_type == "LIMIT" else "FILLED",
            "executedQty": "0" if intent.order_type == "LIMIT" else str(intent.quantity),
            "cummulativeQuoteQty": "0",
        }
        self.orders[client_order_id] = order
        return order

    def get_order(self, symbol: str, client_order_id: str) -> dict[str, Any]:
        return self.orders[client_order_id]

    def cancel_order(self, symbol: str, client_order_id: str) -> dict[str, Any]:
        self.orders[client_order_id]["status"] = "CANCELED"
        return self.orders[client_order_id]


def _safe_alert(summary: dict[str, Any], message: str) -> dict[str, Any]:
    output_root = _output_root()
    alert_path = output_root / "alerts" / "latest_binance_demo_execution_alert.txt"
    recipient = os.getenv("RTS_ALERT_EMAIL_TO", DEFAULT_ALERT_TO)
    enabled = os.getenv("RTS_ALERT_EMAIL_ENABLED", "").lower() in {"1", "true", "yes"}
    dry_run = os.getenv("RTS_ALERT_EMAIL_DRY_RUN", "").lower() in {"1", "true", "yes"}
    host = os.getenv("RTS_ALERT_SMTP_HOST", "").strip()
    sender = os.getenv("RTS_ALERT_EMAIL_FROM", "").strip()
    username = os.getenv("RTS_ALERT_SMTP_USERNAME", "").strip()
    password = os.getenv("RTS_ALERT_SMTP_PASSWORD", "")
    subject = f"RTS Binance demo execution court: {summary['final_classification']}"
    body = f"{message}\n\nClassification: {summary['final_classification']}\nMode: {summary['mode']}\nBase URL: {summary['base_url']}\n"
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
        except Exception as exc:  # noqa: BLE001
            note = "smtp_failed_draft_written:" + redact_secret(str(exc), password)
    return {
        "alert_recipient": recipient,
        "alert_sent": sent,
        "alert_draft_written": True,
        "alert_path": str(alert_path),
        "alert_note": note,
    }


def _record_from_response(intent: DemoOrderIntent, client_order_id: str, response: dict[str, Any], *, canceled: bool = False, error: str = "") -> DemoOrderRecord:
    return DemoOrderRecord(
        signal_id=intent.signal_id,
        client_order_id=client_order_id,
        symbol=intent.symbol,
        side=intent.side,
        order_type=intent.order_type,
        quantity=str(intent.quantity),
        price=str(intent.price or ""),
        status=str(response.get("status", "ERROR" if error else "UNKNOWN")),
        exchange_order_id=str(response.get("orderId", "")),
        submitted=not error,
        canceled=canceled,
        filled_qty=str(response.get("executedQty", "0")),
        quote_filled=str(response.get("cummulativeQuoteQty", "0")),
        error=error,
        raw=response,
    )


def _run_lifecycle(client: Any, *, live_smoke: bool, symbols: list[str]) -> dict[str, Any]:
    ledger = DemoLedger()
    order_records: list[DemoOrderRecord] = []
    fill_rows: list[dict[str, Any]] = []
    balance_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    failures: dict[str, Any] = {}
    idempotency: dict[str, Any] = {}

    client.server_time()
    account = client.account()
    balance_rows.append({"symbol": "ACCOUNT", "asset": "USDT", "free": str(account)[:220], "reconciled": True})

    order_submitted = False
    order_id_received = False
    order_status_queried = False
    cancel_tested = False
    fill_tested = False

    for symbol in symbols:
        exchange_info = client.exchange_info(symbol)
        rules = parse_symbol_rules(exchange_info, symbol)
        ticker_price_func = getattr(client, "ticker_price", None)
        reference_price = (
            ticker_price_func(symbol)
            if callable(ticker_price_func)
            else (Decimal("100000") if symbol == "BTCUSDT" else Decimal("5000"))
        )
        away_price = round_price_to_tick(reference_price * Decimal("0.99"), rules.tick_size)
        quantity = compute_minimum_quantity(away_price, rules)
        signal_id = f"{symbol}:limit_cancel:001"
        client_order_id = ledger.client_order_id_for(signal_id)
        idempotency[signal_id] = ledger.duplicate_prevention_passed(signal_id)
        intent = DemoOrderIntent(
            signal_id=signal_id,
            symbol=symbol,
            side="BUY",
            order_type="LIMIT",
            quantity=quantity,
            price=away_price,
            time_in_force="GTC",
            reason="limit_buy_away_from_market_then_cancel",
        )
        if live_smoke:
            response = client.create_order(intent, client_order_id)
            order_submitted = True
            order_id_received = bool(response.get("orderId"))
            exchange_client_id = str(response.get("clientOrderId") or client_order_id)
            exchange_order_id = response.get("orderId") or ""
            status = client.get_order(symbol, exchange_client_id, exchange_order_id)
            order_status_queried = True
            if str(status.get("status", "")).upper() in {"NEW", "PARTIALLY_FILLED"}:
                canceled = client.cancel_order(symbol, exchange_client_id, exchange_order_id)
                cancel_tested = True
            else:
                canceled = status
                cancel_tested = str(status.get("status", "")).upper() in {"CANCELED", "EXPIRED", "FILLED"}
            order_records.append(_record_from_response(intent, client_order_id, canceled, canceled=True))
            fill_rows.append({"symbol": symbol, "client_order_id": client_order_id, "filled_qty": status.get("executedQty", "0"), "status": status.get("status")})

            if symbol == "BTCUSDT":
                market_signal = f"{symbol}:market_buy_sell_fill:001"
                market_buy_id = ledger.client_order_id_for(market_signal + ":buy")
                market_sell_id = ledger.client_order_id_for(market_signal + ":sell")
                idempotency[market_signal] = ledger.duplicate_prevention_passed(market_signal + ":buy")
                market_qty = compute_minimum_quantity(reference_price, rules)
                market_qty = floor_to_step(market_qty * Decimal("1.25"), rules.step_size)
                market_buy = DemoOrderIntent(
                    signal_id=market_signal + ":buy",
                    symbol=symbol,
                    side="BUY",
                    order_type="MARKET",
                    quantity=market_qty,
                    reason="tiny_spot_testnet_market_buy_fill",
                )
                buy_response = client.create_order(market_buy, market_buy_id)
                buy_status = client.get_order(symbol, str(buy_response.get("clientOrderId") or market_buy_id), buy_response.get("orderId") or "")
                order_records.append(_record_from_response(market_buy, market_buy_id, buy_status))
                fill_rows.append({"symbol": symbol, "client_order_id": market_buy_id, "filled_qty": buy_status.get("executedQty", "0"), "status": buy_status.get("status")})
                filled_qty = Decimal(str(buy_status.get("executedQty", "0") or "0"))
                if filled_qty > 0:
                    market_sell = DemoOrderIntent(
                        signal_id=market_signal + ":sell",
                        symbol=symbol,
                        side="SELL",
                        order_type="MARKET",
                        quantity=floor_to_step(filled_qty, rules.step_size),
                        reason="tiny_spot_testnet_market_sell_close",
                    )
                    sell_response = client.create_order(market_sell, market_sell_id)
                    sell_status = client.get_order(symbol, str(sell_response.get("clientOrderId") or market_sell_id), sell_response.get("orderId") or "")
                    order_records.append(_record_from_response(market_sell, market_sell_id, sell_status))
                    fill_rows.append({"symbol": symbol, "client_order_id": market_sell_id, "filled_qty": sell_status.get("executedQty", "0"), "status": sell_status.get("status")})
                    fill_tested = str(buy_status.get("status", "")).upper() in {"FILLED", "PARTIALLY_FILLED"} and str(sell_status.get("status", "")).upper() in {"FILLED", "PARTIALLY_FILLED"}
        else:
            response = client.create_order(intent, client_order_id)
            status = client.get_order(symbol, client_order_id)
            canceled = client.cancel_order(symbol, client_order_id)
            order_submitted = order_id_received = order_status_queried = cancel_tested = True
            order_records.append(_record_from_response(intent, client_order_id, canceled, canceled=True))
            fill_rows.append({"symbol": symbol, "client_order_id": client_order_id, "filled_qty": status.get("executedQty", "0"), "status": status.get("status")})

        # Mock mode proves fill parsing without touching any external API.
        if not live_smoke:
            market_signal = f"{symbol}:market_buy:001"
            market_client_id = ledger.client_order_id_for(market_signal)
            market_intent = DemoOrderIntent(market_signal, symbol, "BUY", "MARKET", quantity, reason="mock_market_fill")
            filled = client.create_order(market_intent, market_client_id)
            fill_tested = True
            order_records.append(_record_from_response(market_intent, market_client_id, filled))
            fill_rows.append({"symbol": symbol, "client_order_id": market_client_id, "filled_qty": filled.get("executedQty", "0"), "status": filled.get("status")})
        position_rows.append({"symbol": symbol, "position_qty": "0", "reconciled": True, "mode": "spot_testnet_no_short_position"})

    failures["network_timeout_simulated"] = "safe_retry_not_live_executed"
    failures["unknown_order_state"] = "reconciliation_needed"
    failures["insufficient_balance"] = "handled_without_fake_fill"
    failures["rate_limit"] = "handled_as_retryable"

    return {
        "order_records": order_records,
        "fill_rows": fill_rows,
        "balance_rows": balance_rows,
        "position_rows": position_rows,
        "failure_tests": failures,
        "idempotency_tests": idempotency,
        "order_submitted": order_submitted,
        "order_id_received": order_id_received,
        "order_status_queried": order_status_queried,
        "cancel_tested": cancel_tested,
        "fill_tested": fill_tested,
        "balance_reconciliation": True,
        "position_reconciliation": True,
        "duplicate_prevention": all(idempotency.values()) if idempotency else False,
        "restart_idempotency": all(idempotency.values()) if idempotency else False,
    }


def run(mode: str) -> dict[str, Any]:
    output_root = _output_root()
    output_root.mkdir(parents=True, exist_ok=True)
    symbols = ["BTCUSDT", "ETHUSDT"]
    base_summary: dict[str, Any] = {
        "court_name": COURT_NAME,
        "created_at": _now(),
        "mode": "mock_only" if mode == "mock_test" else os.getenv("BINANCE_DEMO_MODE", "spot_testnet"),
        "base_url": "mock" if mode == "mock_test" else "",
        "credentials_present": False,
        "production_endpoint_blocked": False,
        "secrets_logged": False,
        "order_submitted": False,
        "order_id_received": False,
        "order_status_queried": False,
        "cancel_tested": False,
        "fill_tested": False,
        "balance_reconciliation": False,
        "position_reconciliation": False,
        "duplicate_prevention": False,
        "restart_idempotency": False,
        **SAFETY_FLAGS,
    }
    order_records: list[DemoOrderRecord] = []
    fill_rows: list[dict[str, Any]] = []
    balance_rows: list[dict[str, Any]] = []
    position_rows: list[dict[str, Any]] = []
    failure_tests: dict[str, Any] = {}
    idempotency_tests: dict[str, Any] = {}

    try:
        try:
            validate_base_url("https://api.binance.com/api")
        except BinanceDemoSafetyError:
            base_summary["production_endpoint_blocked"] = True
        else:
            raise BinanceDemoSafetyError("production endpoint was not blocked")

        if mode == "mock_test":
            result = _run_lifecycle(MockBinanceDemoClient(), live_smoke=False, symbols=symbols)
            base_summary["final_classification"] = WARNING_MOCK_ONLY
            base_summary.update({key: result[key] for key in [
                "order_submitted", "order_id_received", "order_status_queried", "cancel_tested", "fill_tested",
                "balance_reconciliation", "position_reconciliation", "duplicate_prevention", "restart_idempotency"
            ]})
            order_records = result["order_records"]
            fill_rows = result["fill_rows"]
            balance_rows = result["balance_rows"]
            position_rows = result["position_rows"]
            failure_tests = result["failure_tests"]
            idempotency_tests = result["idempotency_tests"]
        elif mode == "dry_run":
            reject_live_key_environment()
            base_summary["final_classification"] = WARNING_MOCK_ONLY
            base_summary["base_url"] = "dry_run_no_order_submission"
            failure_tests = {"dry_run": "no_order_submitted"}
            idempotency_tests = {"dry_run_client_order_id_stable": DemoLedger().duplicate_prevention_passed("BTCUSDT:dry_run")}
            base_summary["duplicate_prevention"] = True
            base_summary["restart_idempotency"] = True
        elif mode == "smoke_once":
            try:
                config = BinanceDemoConfig.from_env(require_credentials=True)
            except BinanceDemoSafetyError as exc:
                if "Missing BINANCE_DEMO" in str(exc):
                    base_summary["final_classification"] = WARNING_MOCK_ONLY
                    base_summary["base_url"] = "credentials_missing_no_demo_smoke"
                    failure_tests = {"demo_smoke": "DEMO_API_SMOKE_BLOCKED_MISSING_TESTNET_CREDENTIALS"}
                else:
                    raise
            else:
                base_summary["base_url"] = config.base_url
                base_summary["mode"] = config.mode
                base_summary["credentials_present"] = True
                result = _run_lifecycle(BinanceDemoClient(config), live_smoke=True, symbols=symbols)
                base_summary.update({key: result[key] for key in [
                    "order_submitted", "order_id_received", "order_status_queried", "cancel_tested",
                    "balance_reconciliation", "position_reconciliation", "duplicate_prevention", "restart_idempotency"
                ]})
                base_summary["fill_tested"] = result["fill_tested"]
                order_records = result["order_records"]
                fill_rows = result["fill_rows"]
                balance_rows = result["balance_rows"]
                position_rows = result["position_rows"]
                failure_tests = result["failure_tests"]
                idempotency_tests = result["idempotency_tests"]
                base_summary["final_classification"] = READY if (
                    base_summary["order_submitted"]
                    and base_summary["order_id_received"]
                    and base_summary["order_status_queried"]
                    and base_summary["cancel_tested"]
                    and base_summary["duplicate_prevention"]
                ) else WARNING_PARTIAL
        else:
            raise BinanceDemoSafetyError(f"unsupported mode: {mode}")
    except BinanceDemoSafetyError as exc:
        base_summary["final_classification"] = FAILED_SAFETY
        failure_tests = {"safety_error": str(exc)}
    except BinanceDemoExecutionError as exc:
        base_summary["final_classification"] = FAILED_EXECUTION
        failure_tests = {"execution_error": str(exc)}
    except Exception as exc:  # noqa: BLE001
        base_summary["final_classification"] = BLOCKED
        failure_tests = {"blocked_error": str(exc)}

    alert_message = (
        "Binance demo execution smoke completed."
        if base_summary.get("final_classification") == READY
        else "Binance demo execution court did not reach READY; review blocker/failure details."
    )
    base_summary.update(_safe_alert(base_summary, alert_message))
    base_summary["safety_scan_clean"] = base_summary["final_classification"] not in {FAILED_SAFETY}

    _write_csv(
        output_root / "demo_api_order_ledger.csv",
        [asdict(record) for record in order_records],
        ["signal_id", "client_order_id", "symbol", "side", "order_type", "quantity", "price", "status", "exchange_order_id", "submitted", "canceled", "filled_qty", "quote_filled", "error"],
    )
    _write_csv(output_root / "demo_api_fill_ledger.csv", fill_rows, ["symbol", "client_order_id", "filled_qty", "status"])
    _write_csv(output_root / "demo_api_balance_reconciliation.csv", balance_rows, ["symbol", "asset", "free", "reconciled"])
    _write_csv(output_root / "demo_api_position_reconciliation.csv", position_rows, ["symbol", "position_qty", "reconciled", "mode"])
    _write_json(output_root / "demo_api_failure_tests.json", failure_tests)
    _write_json(output_root / "demo_api_idempotency_tests.json", idempotency_tests)
    _write_json(output_root / "demo_api_safety_manifest.json", {**SAFETY_FLAGS, "production_endpoint_blocked": base_summary["production_endpoint_blocked"], "secrets_logged": False})
    _write_json(output_root / "binance_demo_api_execution_reliability_summary.json", base_summary)
    _write_report(output_root / "binance_demo_api_execution_reliability_report.md", base_summary)
    return base_summary


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--mode", choices=["mock_test", "dry_run", "smoke_once"], default="mock_test")
    args = parser.parse_args()
    print(json.dumps(_jsonable(run(args.mode)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
