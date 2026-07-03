from __future__ import annotations

import argparse
import csv
import json
import os
import smtplib
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from structural_compounding_lab.common.email_safety import smtp_allowed_for_output_root
from structural_compounding_lab.common.project_paths import output_root, resolve_project_path
from structural_compounding_lab.execution.binance_live_spot_client import (
    REQUIRED_CONFIRMATION,
    BinanceLiveSpotClient,
    BinanceLiveSpotConfig,
    BinanceLiveSpotExecutionError,
    BinanceLiveSpotSafetyError,
    build_client_order_id,
    decimal_to_plain,
    parse_symbol_rules,
    quantity_for_notional,
    redact_secret,
)
from structural_compounding_lab.execution.demo_order_models import DemoOrderIntent


COURT_NAME = "BINANCE_LIVE_TINY_SPOT_SMOKE_COURT_REAL_MONEY_GUARDED"
OUTPUT_FOLDER_NAME = "binance_live_tiny_spot_smoke_court_001"

BLOCKED_NEEDS_KEYS = "BINANCE_LIVE_TINY_SMOKE_BLOCKED_NEEDS_KEYS"
BLOCKED_SAFETY = "BINANCE_LIVE_TINY_SMOKE_BLOCKED_SAFETY"
PREFLIGHT_READY = "BINANCE_LIVE_TINY_SMOKE_PREFLIGHT_READY_NO_ORDER"
ROUNDTRIP_COMPLETED = "BINANCE_LIVE_TINY_SMOKE_ORDER_ROUNDTRIP_COMPLETED"
FAILED = "BINANCE_LIVE_TINY_SMOKE_FAILED"

DEFAULT_ALERT_TO = "nneupane1@gmail.com"
DEFAULT_SYMBOL = "BTCUSDT"
MAX_ALLOWED_ACCOUNT_CAPITAL_EUR = Decimal("1000")
MAX_ALLOWED_TEST_BUDGET_EUR = Decimal("50")
MAX_ALLOWED_ORDER_NOTIONAL_EUR = Decimal("10")
MAX_ALLOWED_DAILY_LOSS_EUR = Decimal("20")
REQUIRED_ENABLED_VALUE = "true"
REQUIRED_LOSS_ACK = "I_ACCEPT_MAX_50_EUR_TEST_BUDGET"
FORBIDDEN_ENV_NAMES = {
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_SECRET",
    "LIVE_API_KEY",
    "LIVE_API_SECRET",
    "BINANCE_DEMO_API_KEY",
    "BINANCE_DEMO_API_SECRET",
}


@dataclass(frozen=True)
class LiveSmokeLimits:
    symbol: str
    max_account_capital_eur: Decimal
    max_test_budget_eur: Decimal
    max_order_notional_eur: Decimal
    max_daily_loss_eur: Decimal
    max_open_positions: int
    run_confirmation_present: bool


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return decimal_to_plain(value)
    if isinstance(value, Path):
        return str(value)
    if is_dataclass(value) and not isinstance(value, type):
        return _jsonable(asdict(value))
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


def _read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)
    return payload if isinstance(payload, dict) else dict(default)


def _append_csv(path: Path, row: dict[str, Any], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({key: _jsonable(row.get(key, "")) for key in fieldnames})


def _paths(root: Path) -> dict[str, Path]:
    return {
        "latest_status": root / "latest_status.json",
        "safety_manifest": root / "safety_manifest.json",
        "balances": root / "balances_before_after.json",
        "orders": root / "ledger" / "live_tiny_smoke_orders.csv",
        "fills": root / "ledger" / "live_tiny_smoke_fills.csv",
        "state": root / "state" / "live_tiny_smoke_state.json",
        "latest_email": root / "alerts" / "latest_live_tiny_smoke_email.txt",
        "email_ledger": root / "alerts" / "live_tiny_smoke_email_ledger.csv",
    }


def _decimal_env(name: str, default: str) -> Decimal:
    raw = os.getenv(name, default).strip() or default
    try:
        return Decimal(raw)
    except Exception as exc:
        raise BinanceLiveSpotSafetyError(f"{name} must be a decimal value") from exc


def _limits(symbol: str) -> LiveSmokeLimits:
    return LiveSmokeLimits(
        symbol=symbol.upper(),
        max_account_capital_eur=_decimal_env("RTS_LIVE_SMOKE_MAX_ACCOUNT_CAPITAL_EUR", "1000"),
        max_test_budget_eur=_decimal_env("RTS_LIVE_SMOKE_MAX_TEST_BUDGET_EUR", "50"),
        max_order_notional_eur=_decimal_env("RTS_LIVE_SMOKE_MAX_ORDER_NOTIONAL_EUR", "10"),
        max_daily_loss_eur=_decimal_env("RTS_LIVE_SMOKE_MAX_DAILY_LOSS_EUR", "15"),
        max_open_positions=int(os.getenv("RTS_LIVE_SMOKE_MAX_OPEN_POSITIONS", "1") or "1"),
        run_confirmation_present=(
            os.getenv("RTS_LIVE_SMOKE_ENABLED", "").strip().lower() == REQUIRED_ENABLED_VALUE
            and os.getenv("RTS_LIVE_SMOKE_CONFIRM", "").strip() == REQUIRED_CONFIRMATION
            and os.getenv("RTS_LIVE_SMOKE_I_UNDERSTAND_MAX_LOSS", "").strip() == REQUIRED_LOSS_ACK
        ),
    )


def _safety_manifest(*, mode: str, root: Path, limits: LiveSmokeLimits, credentials_present: bool) -> dict[str, Any]:
    generic_present = [key for key in sorted(FORBIDDEN_ENV_NAMES) if os.getenv(key)]
    caps_ok = (
        limits.max_account_capital_eur <= MAX_ALLOWED_ACCOUNT_CAPITAL_EUR
        and limits.max_test_budget_eur <= MAX_ALLOWED_TEST_BUDGET_EUR
        and limits.max_order_notional_eur <= MAX_ALLOWED_ORDER_NOTIONAL_EUR
        and limits.max_daily_loss_eur <= MAX_ALLOWED_DAILY_LOSS_EUR
        and limits.max_open_positions == 1
    )
    return {
        "court_name": COURT_NAME,
        "created_at": _now(),
        "mode": mode,
        "artifact_root": str(root),
        "symbol": limits.symbol,
        "credentials_present": credentials_present,
        "dedicated_live_smoke_keys_required": True,
        "generic_or_demo_keys_present": generic_present,
        "generic_or_demo_keys_rejected": True,
        "spot_mainnet_only": True,
        "margin_allowed": False,
        "futures_allowed": False,
        "short_selling_allowed": False,
        "withdrawal_allowed": False,
        "deposit_allowed": False,
        "account_transfer_allowed": False,
        "full_live_trading_allowed": False,
        "strategy_scheduler_live_allowed": False,
        "paper_validation_ready": False,
        "tiny_live_smoke_only": True,
        "max_account_capital_eur": limits.max_account_capital_eur,
        "max_test_budget_eur": limits.max_test_budget_eur,
        "max_order_notional_eur": limits.max_order_notional_eur,
        "max_daily_loss_eur": limits.max_daily_loss_eur,
        "max_open_positions": limits.max_open_positions,
        "caps_ok": caps_ok,
        "run_confirmation_present": limits.run_confirmation_present,
        "orders_allowed_in_this_mode": mode == "run_once" and caps_ok and limits.run_confirmation_present,
        "real_money_allowed": mode == "run_once" and caps_ok and limits.run_confirmation_present,
        "tiny_live_smoke_order_path_allowed": mode == "run_once" and caps_ok and limits.run_confirmation_present,
        "production_strategy_order_path_allowed": False,
    }


def _validate_caps(manifest: dict[str, Any]) -> None:
    if manifest["generic_or_demo_keys_present"]:
        raise BinanceLiveSpotSafetyError(
            "Refusing live smoke because generic/demo key variables are present: "
            + ",".join(manifest["generic_or_demo_keys_present"])
        )
    if not manifest["caps_ok"]:
        raise BinanceLiveSpotSafetyError("Live smoke caps exceed the hard-coded maximums")
    if manifest["max_open_positions"] != 1:
        raise BinanceLiveSpotSafetyError("Live smoke max_open_positions must be exactly 1")


def _safe_account_summary(account: dict[str, Any], assets: set[str]) -> dict[str, Any]:
    balances = []
    for row in account.get("balances", []):
        asset = str(row.get("asset", ""))
        if asset not in assets:
            continue
        balances.append(
            {
                "asset": asset,
                "free": str(row.get("free", "0")),
                "locked": str(row.get("locked", "0")),
            }
        )
    return {
        "account_type": account.get("accountType", ""),
        "can_trade": account.get("canTrade", ""),
        "can_withdraw": account.get("canWithdraw", ""),
        "can_deposit": account.get("canDeposit", ""),
        "balances": balances,
    }


def _asset_balance(account: dict[str, Any], asset: str) -> Decimal:
    for row in account.get("balances", []):
        if str(row.get("asset", "")).upper() == asset.upper():
            return Decimal(str(row.get("free", "0"))) + Decimal(str(row.get("locked", "0")))
    return Decimal("0")


def _order_fieldnames() -> list[str]:
    return [
        "created_at",
        "court_name",
        "mode",
        "symbol",
        "side",
        "client_order_id",
        "exchange_order_id",
        "status",
        "quantity",
        "executed_qty",
        "quote_filled",
        "reference_price",
        "max_order_notional_eur",
        "max_test_budget_eur",
        "reason",
        "tiny_live_smoke_only",
        "full_live_trading_allowed",
        "strategy_scheduler_live_allowed",
        "real_money_allowed",
        "production_strategy_order_path_allowed",
    ]


def _fill_fieldnames() -> list[str]:
    return [
        "created_at",
        "symbol",
        "side",
        "client_order_id",
        "price",
        "qty",
        "commission",
        "commission_asset",
        "trade_id",
    ]


def _safe_email(root: Path, *, subject_suffix: str, body_lines: list[str]) -> dict[str, Any]:
    paths = _paths(root)
    recipient = os.getenv("RTS_ALERT_EMAIL_TO", DEFAULT_ALERT_TO)
    enabled = os.getenv("RTS_ALERT_EMAIL_ENABLED", "").strip().lower() in {"1", "true", "yes"}
    dry_run = os.getenv("RTS_ALERT_EMAIL_DRY_RUN", "").strip().lower() in {"1", "true", "yes"}
    host = os.getenv("RTS_ALERT_SMTP_HOST", "").strip()
    sender = os.getenv("RTS_ALERT_EMAIL_FROM", "").strip()
    username = os.getenv("RTS_ALERT_SMTP_USERNAME", "").strip()
    password = os.getenv("RTS_ALERT_SMTP_PASSWORD", "")
    subject = f"RTS TINY LIVE SPOT SMOKE: {subject_suffix}"
    body = "\n".join(body_lines + ["", f"Artifact root: {root}"])
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
        "created_at": _now(),
        "subject": subject,
        "recipient": recipient,
        "email_sent": sent,
        "email_draft_written": True,
        "email_note": note,
        "email_path": str(paths["latest_email"]),
    }
    _append_csv(
        paths["email_ledger"],
        record,
        ["created_at", "subject", "recipient", "email_sent", "email_draft_written", "email_note", "email_path"],
    )
    return record


def _write_status(root: Path, payload: dict[str, Any]) -> dict[str, Any]:
    _write_json(_paths(root)["latest_status"], payload)
    return payload


def _blocked_status(root: Path, *, mode: str, classification: str, reason: str, limits: LiveSmokeLimits | None = None) -> dict[str, Any]:
    limits = limits or _limits(DEFAULT_SYMBOL)
    credentials_present = bool(os.getenv("BINANCE_LIVE_SMOKE_API_KEY") and os.getenv("BINANCE_LIVE_SMOKE_API_SECRET"))
    manifest = _safety_manifest(mode=mode, root=root, limits=limits, credentials_present=credentials_present)
    _write_json(_paths(root)["safety_manifest"], manifest)
    status = {
        **manifest,
        "final_classification": classification,
        "reason": reason,
        "orders_submitted": 0,
        "real_money_allowed": False,
        "tiny_live_smoke_order_path_allowed": False,
    }
    return _write_status(root, status)


def preflight(root: Path, *, symbol: str) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    limits = _limits(symbol)
    credentials_present = bool(os.getenv("BINANCE_LIVE_SMOKE_API_KEY") and os.getenv("BINANCE_LIVE_SMOKE_API_SECRET"))
    manifest = _safety_manifest(mode="preflight", root=root, limits=limits, credentials_present=credentials_present)
    _write_json(_paths(root)["safety_manifest"], manifest)
    try:
        _validate_caps(manifest)
    except BinanceLiveSpotSafetyError as exc:
        return _blocked_status(root, mode="preflight", classification=BLOCKED_SAFETY, reason=str(exc), limits=limits)
    if not credentials_present:
        return _blocked_status(
            root,
            mode="preflight",
            classification=BLOCKED_NEEDS_KEYS,
            reason="missing_BINANCE_LIVE_SMOKE_API_KEY_or_BINANCE_LIVE_SMOKE_API_SECRET",
            limits=limits,
        )
    config = BinanceLiveSpotConfig.from_env(require_credentials=True, require_confirmation=False)
    client = BinanceLiveSpotClient(config)
    exchange_info = client.exchange_info(limits.symbol)
    rules = parse_symbol_rules(exchange_info, limits.symbol)
    price = client.ticker_price(limits.symbol)
    open_orders = client.open_orders(limits.symbol)
    account = client.account()
    assets = {rules.base_asset, rules.quote_asset, "EUR", "USDT"}
    account_summary = _safe_account_summary(account, assets)
    min_qty_for_min_notional = quantity_for_notional(rules.min_notional, price, rules)
    notional_for_min_order = min_qty_for_min_notional * price
    min_order_fits_cap = notional_for_min_order <= limits.max_order_notional_eur
    _write_json(
        _paths(root)["balances"],
        {
            "created_at": _now(),
            "stage": "preflight",
            "account": account_summary,
            "open_orders_count": len(open_orders),
            "symbol_rules": rules,
            "ticker_price": price,
            "minimum_market_order_quantity": min_qty_for_min_notional,
            "estimated_minimum_order_notional": notional_for_min_order,
            "minimum_order_fits_cap": min_order_fits_cap,
        },
    )
    classification = PREFLIGHT_READY if min_order_fits_cap and not open_orders else BLOCKED_SAFETY
    reason = "ready_no_order_submitted"
    if open_orders:
        reason = "open_orders_exist_refusing_smoke"
    elif not min_order_fits_cap:
        reason = "binance_minimum_order_exceeds_max_order_cap"
    status = {
        **manifest,
        "final_classification": classification,
        "reason": reason,
        "base_url": config.base_url,
        "symbol_rules": _jsonable(rules),
        "ticker_price": price,
        "minimum_market_order_quantity": min_qty_for_min_notional,
        "estimated_minimum_order_notional": notional_for_min_order,
        "minimum_order_fits_cap": min_order_fits_cap,
        "open_orders_count": len(open_orders),
        "account_summary": account_summary,
        "orders_submitted": 0,
        "real_money_allowed": False,
        "tiny_live_smoke_order_path_allowed": False,
    }
    return _write_status(root, status)


def _record_order(root: Path, *, side: str, symbol: str, client_order_id: str, response: dict[str, Any], price: Decimal, limits: LiveSmokeLimits) -> None:
    row = {
        "created_at": _now(),
        "court_name": COURT_NAME,
        "mode": "run_once",
        "symbol": symbol,
        "side": side,
        "client_order_id": client_order_id,
        "exchange_order_id": str(response.get("orderId", "")),
        "status": str(response.get("status", "")),
        "quantity": str(response.get("origQty", "")),
        "executed_qty": str(response.get("executedQty", "0")),
        "quote_filled": str(response.get("cummulativeQuoteQty", "0")),
        "reference_price": price,
        "max_order_notional_eur": limits.max_order_notional_eur,
        "max_test_budget_eur": limits.max_test_budget_eur,
        "reason": "tiny_live_spot_smoke_order_lifecycle_test",
        "tiny_live_smoke_only": True,
        "full_live_trading_allowed": False,
        "strategy_scheduler_live_allowed": False,
        "real_money_allowed": True,
        "production_strategy_order_path_allowed": False,
    }
    _append_csv(_paths(root)["orders"], row, _order_fieldnames())
    for fill in response.get("fills", []) or []:
        _append_csv(
            _paths(root)["fills"],
            {
                "created_at": _now(),
                "symbol": symbol,
                "side": side,
                "client_order_id": client_order_id,
                "price": fill.get("price", ""),
                "qty": fill.get("qty", ""),
                "commission": fill.get("commission", ""),
                "commission_asset": fill.get("commissionAsset", ""),
                "trade_id": fill.get("tradeId", ""),
            },
            _fill_fieldnames(),
        )


def run_once(root: Path, *, symbol: str) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    limits = _limits(symbol)
    credentials_present = bool(os.getenv("BINANCE_LIVE_SMOKE_API_KEY") and os.getenv("BINANCE_LIVE_SMOKE_API_SECRET"))
    manifest = _safety_manifest(mode="run_once", root=root, limits=limits, credentials_present=credentials_present)
    _write_json(_paths(root)["safety_manifest"], manifest)
    try:
        _validate_caps(manifest)
        if not credentials_present:
            raise BinanceLiveSpotSafetyError("missing_BINANCE_LIVE_SMOKE_API_KEY_or_BINANCE_LIVE_SMOKE_API_SECRET")
        if not limits.run_confirmation_present:
            raise BinanceLiveSpotSafetyError(
                "missing explicit live-smoke confirmations: RTS_LIVE_SMOKE_ENABLED, RTS_LIVE_SMOKE_CONFIRM, "
                "RTS_LIVE_SMOKE_I_UNDERSTAND_MAX_LOSS"
            )
    except BinanceLiveSpotSafetyError as exc:
        classification = BLOCKED_NEEDS_KEYS if "missing_BINANCE_LIVE_SMOKE" in str(exc) else BLOCKED_SAFETY
        return _blocked_status(root, mode="run_once", classification=classification, reason=str(exc), limits=limits)

    config = BinanceLiveSpotConfig.from_env(require_credentials=True, require_confirmation=True)
    client = BinanceLiveSpotClient(config)
    exchange_info = client.exchange_info(limits.symbol)
    rules = parse_symbol_rules(exchange_info, limits.symbol)
    if rules.quote_asset.upper() != "USDT":
        raise BinanceLiveSpotSafetyError("Tiny live smoke currently supports USDT-quoted spot pairs only")
    price = client.ticker_price(limits.symbol)
    quantity = quantity_for_notional(limits.max_order_notional_eur, price, rules)
    estimated_notional = quantity * price
    if estimated_notional > limits.max_order_notional_eur:
        return _blocked_status(
            root,
            mode="run_once",
            classification=BLOCKED_SAFETY,
            reason="computed_order_notional_exceeds_max_order_cap",
            limits=limits,
        )
    if estimated_notional > limits.max_test_budget_eur:
        return _blocked_status(
            root,
            mode="run_once",
            classification=BLOCKED_SAFETY,
            reason="computed_order_notional_exceeds_test_budget",
            limits=limits,
        )
    open_orders = client.open_orders(limits.symbol)
    if open_orders:
        return _blocked_status(root, mode="run_once", classification=BLOCKED_SAFETY, reason="open_orders_exist_refusing_smoke", limits=limits)

    before_account = client.account()
    quote_before = _asset_balance(before_account, rules.quote_asset)
    base_before = _asset_balance(before_account, rules.base_asset)
    if quote_before < estimated_notional:
        return _blocked_status(
            root,
            mode="run_once",
            classification=BLOCKED_SAFETY,
            reason=f"insufficient_{rules.quote_asset}_balance_for_tiny_order",
            limits=limits,
        )

    signal_seed = f"{COURT_NAME}|{limits.symbol}|{_now()}|{estimated_notional}"
    buy_client_order_id = build_client_order_id("rtslivebuy", signal_seed)
    buy_intent = DemoOrderIntent(
        signal_id=signal_seed,
        symbol=limits.symbol,
        side="BUY",
        order_type="MARKET",
        quantity=quantity,
        reason="tiny_live_spot_smoke_buy",
    )
    buy_response = client.create_order(buy_intent, buy_client_order_id)
    _record_order(root, side="BUY", symbol=limits.symbol, client_order_id=buy_client_order_id, response=buy_response, price=price, limits=limits)
    executed_qty = Decimal(str(buy_response.get("executedQty", "0") or "0"))
    if executed_qty <= 0:
        raise BinanceLiveSpotExecutionError("buy_order_returned_zero_executed_quantity")

    sell_seed = f"{signal_seed}|SELL|{buy_client_order_id}"
    sell_client_order_id = build_client_order_id("rtslivesell", sell_seed)
    sell_intent = DemoOrderIntent(
        signal_id=sell_seed,
        symbol=limits.symbol,
        side="SELL",
        order_type="MARKET",
        quantity=executed_qty,
        reason="tiny_live_spot_smoke_immediate_exit",
    )
    sell_response = client.create_order(sell_intent, sell_client_order_id)
    _record_order(root, side="SELL", symbol=limits.symbol, client_order_id=sell_client_order_id, response=sell_response, price=client.ticker_price(limits.symbol), limits=limits)

    after_account = client.account()
    quote_after = _asset_balance(after_account, rules.quote_asset)
    base_after = _asset_balance(after_account, rules.base_asset)
    quote_delta = quote_after - quote_before
    base_delta = base_after - base_before
    _write_json(
        _paths(root)["balances"],
        {
            "created_at": _now(),
            "stage": "run_once_after_roundtrip",
            "before_account": _safe_account_summary(before_account, {rules.base_asset, rules.quote_asset, "EUR", "USDT"}),
            "after_account": _safe_account_summary(after_account, {rules.base_asset, rules.quote_asset, "EUR", "USDT"}),
            "quote_delta": quote_delta,
            "base_delta": base_delta,
            "estimated_order_notional": estimated_notional,
        },
    )
    state = {
        "created_at": _now(),
        "symbol": limits.symbol,
        "buy_client_order_id": buy_client_order_id,
        "sell_client_order_id": sell_client_order_id,
        "buy_exchange_order_id": str(buy_response.get("orderId", "")),
        "sell_exchange_order_id": str(sell_response.get("orderId", "")),
        "buy_status": str(buy_response.get("status", "")),
        "sell_status": str(sell_response.get("status", "")),
        "executed_base_quantity": executed_qty,
        "buy_quote_filled": str(buy_response.get("cummulativeQuoteQty", "0")),
        "sell_quote_filled": str(sell_response.get("cummulativeQuoteQty", "0")),
        "quote_delta_after_roundtrip": quote_delta,
        "base_delta_after_roundtrip": base_delta,
    }
    _write_json(_paths(root)["state"], state)
    email = _safe_email(
        root,
        subject_suffix=f"ROUNDTRIP COMPLETED {limits.symbol} quote_delta {decimal_to_plain(quote_delta)} {rules.quote_asset}",
        body_lines=[
            "Tiny real-money Binance Spot smoke completed.",
            "This was NOT the production strategy scheduler.",
            "",
            f"Symbol: {limits.symbol}",
            f"Max order cap: {decimal_to_plain(limits.max_order_notional_eur)} EUR/USDT equivalent",
            f"Max test budget: {decimal_to_plain(limits.max_test_budget_eur)} EUR",
            f"BUY order id: {buy_response.get('orderId', '')}",
            f"SELL order id: {sell_response.get('orderId', '')}",
            f"Executed base quantity: {decimal_to_plain(executed_qty)} {rules.base_asset}",
            f"Quote balance delta after roundtrip: {decimal_to_plain(quote_delta)} {rules.quote_asset}",
            "",
            "Safety:",
            "- Spot only",
            "- no margin",
            "- no futures",
            "- no short selling",
            "- no withdrawal code",
            "- full strategy live trading remains disabled",
        ],
    )
    status = {
        **manifest,
        "final_classification": ROUNDTRIP_COMPLETED,
        "reason": "tiny_live_spot_buy_sell_roundtrip_completed",
        "base_url": config.base_url,
        "symbol_rules": _jsonable(rules),
        "reference_price": price,
        "quantity": executed_qty,
        "estimated_order_notional": estimated_notional,
        "quote_delta_after_roundtrip": quote_delta,
        "base_delta_after_roundtrip": base_delta,
        "orders_submitted": 2,
        "buy_status": str(buy_response.get("status", "")),
        "sell_status": str(sell_response.get("status", "")),
        "email": email,
    }
    return _write_status(root, status)


def status(root: Path) -> dict[str, Any]:
    path = _paths(root)["latest_status"]
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return _blocked_status(root, mode="status", classification=BLOCKED_NEEDS_KEYS, reason="latest_status_missing")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Guarded tiny Binance Spot mainnet smoke test.")
    parser.add_argument("--mode", choices=["preflight", "run_once", "status"], default="preflight")
    parser.add_argument("--symbol", default=os.getenv("RTS_LIVE_SMOKE_SYMBOL", DEFAULT_SYMBOL))
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = resolve_project_path(args.output_dir)
    try:
        if args.mode == "preflight":
            result = preflight(root, symbol=args.symbol)
        elif args.mode == "run_once":
            result = run_once(root, symbol=args.symbol)
        else:
            result = status(root)
    except (BinanceLiveSpotSafetyError, BinanceLiveSpotExecutionError, Exception) as exc:  # noqa: BLE001
        limits = _limits(args.symbol)
        safe_error = redact_secret(
            str(exc),
            os.getenv("BINANCE_LIVE_SMOKE_API_KEY", ""),
            os.getenv("BINANCE_LIVE_SMOKE_API_SECRET", ""),
        )
        manifest = _safety_manifest(
            mode=args.mode,
            root=root,
            limits=limits,
            credentials_present=bool(os.getenv("BINANCE_LIVE_SMOKE_API_KEY") and os.getenv("BINANCE_LIVE_SMOKE_API_SECRET")),
        )
        result = {
            **manifest,
            "final_classification": FAILED,
            "reason": safe_error,
            "orders_submitted": 0,
            "real_money_allowed": False,
            "tiny_live_smoke_order_path_allowed": False,
        }
        _write_json(_paths(root)["safety_manifest"], manifest)
        _write_status(root, result)
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
