from __future__ import annotations

import argparse
import csv
import json
import os
import smtplib
from html import escape
from dataclasses import asdict, is_dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from structural_compounding_lab.common.email_safety import smtp_allowed_for_output_root
from structural_compounding_lab.common.project_paths import output_root, resolve_project_path
from structural_compounding_lab.execution.binance_live_spot_client import (
    BinanceLiveSpotClient,
    BinanceLiveSpotConfig,
    BinanceLiveSpotExecutionError,
    BinanceLiveSpotSafetyError,
    build_client_order_id,
    decimal_to_plain,
    floor_to_step,
    parse_symbol_rules,
    quantity_for_notional,
    redact_secret,
)
from structural_compounding_lab.execution.demo_order_models import DemoOrderIntent
from structural_compounding_lab.execution.usdt_usdc_execution_guard import (
    ExecutionSignal,
    GuardThresholds,
    PatienceGuardConfig,
    USDT_TO_USDC,
    evaluate_usdt_signal_to_usdc_execution_guard_with_patience,
)


COURT_NAME = "BINANCE_LIVE_STRATEGY_CANARY_BRIDGE_REAL_MONEY_GUARDED"
OUTPUT_FOLDER_NAME = "binance_live_strategy_canary_court_001"
DEFAULT_SOURCE_LEDGER = "multi_symbol_forward_runtime_earned_parallel_slots/ledger/multi_symbol_forward_decision_ledger.csv"
DEFAULT_SYMBOL_ALLOWLIST = "ADAUSDT,LINKUSDT,BNBUSDT,XRPUSDT,AVAXUSDT,DOGEUSDT,ETHUSDT,BTCUSDT,SOLUSDT"
DEFAULT_ALERT_TO = "nneupane1@gmail.com"

DRY_RUN_READY = "BINANCE_LIVE_STRATEGY_CANARY_DRY_RUN_READY_NO_ORDER"
NO_ELIGIBLE = "BINANCE_LIVE_STRATEGY_CANARY_NO_ELIGIBLE_SIGNAL"
ORDER_SUBMITTED = "BINANCE_LIVE_STRATEGY_CANARY_ORDER_SUBMITTED"
POSITION_MONITORING = "BINANCE_LIVE_STRATEGY_CANARY_POSITION_MONITORING_NO_ORDER"
ROUNDTRIP_COMPLETED = "BINANCE_LIVE_STRATEGY_CANARY_ROUNDTRIP_COMPLETED"
BLOCKED_SAFETY = "BINANCE_LIVE_STRATEGY_CANARY_BLOCKED_SAFETY"
BLOCKED_NEEDS_KEYS = "BINANCE_LIVE_STRATEGY_CANARY_BLOCKED_NEEDS_KEYS"
FAILED = "BINANCE_LIVE_STRATEGY_CANARY_FAILED"

REQUIRED_ENABLED_VALUE = "true"
REQUIRED_CONFIRMATION_VALUES = {
    "YES_TINY_REAL_MONEY_STRATEGY_CANARY",
    "YES_MICRO_LIVE_REAL_MONEY_STRATEGY_CANARY",
}
REQUIRED_LOSS_ACK_VALUES = {
    "I_ACCEPT_MAX_25_EUR_LIVE_CANARY_BUDGET",
    "I_ACCEPT_MAX_100_EUR_MICRO_LIVE_BUDGET",
}
MAX_HARD_ACCOUNT_CAPITAL_EUR = Decimal("1000")
MAX_HARD_TEST_BUDGET_EUR = Decimal("100")
MAX_HARD_ORDER_NOTIONAL_EUR = Decimal("100")
MAX_HARD_DAILY_LOSS_EUR = Decimal("25")
MAX_OPEN_POSITIONS = 2

FORBIDDEN_ENV_NAMES = {
    "BINANCE_API_KEY",
    "BINANCE_API_SECRET",
    "BINANCE_SECRET",
    "LIVE_API_KEY",
    "LIVE_API_SECRET",
    "BINANCE_DEMO_API_KEY",
    "BINANCE_DEMO_API_SECRET",
}


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat()


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
    if isinstance(value, (list, tuple)):
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


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _append_csv(path: Path, row: dict[str, Any], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.exists()
    with path.open("a", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not exists:
            writer.writeheader()
        writer.writerow({key: _jsonable(row.get(key, "")) for key in fieldnames})


def _parse_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y"}


def _parse_decimal(value: str | None, default: str = "0") -> Decimal:
    try:
        return Decimal(str(value if value not in {None, ""} else default))
    except Exception:
        return Decimal(default)


def _parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _paths(root: Path) -> dict[str, Path]:
    return {
        "latest_status": root / "latest_status.json",
        "safety_manifest": root / "safety_manifest.json",
        "activation": root / "state" / "activation_state.json",
        "open_position": root / "state" / "open_position.json",
        "open_positions_dir": root / "state" / "open_positions",
        "candidate_ledger": root / "ledger" / "live_canary_signal_candidates.csv",
        "order_ledger": root / "ledger" / "live_canary_orders.csv",
        "fill_ledger": root / "ledger" / "live_canary_fills.csv",
        "roundtrip_ledger": root / "ledger" / "live_canary_roundtrips.csv",
        "latest_email": root / "alerts" / "latest_live_canary_email.txt",
        "latest_email_html": root / "alerts" / "latest_live_canary_email.html",
        "email_ledger": root / "alerts" / "live_canary_email_ledger.csv",
    }


def _safe_state_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in str(value))
    return safe.strip("_") or "unknown"


def _position_path(root: Path, source_trade_id: str) -> Path:
    return _paths(root)["open_positions_dir"] / f"{_safe_state_name(source_trade_id)}.json"


def _open_positions(root: Path) -> list[tuple[Path, dict[str, Any]]]:
    paths = _paths(root)
    positions: list[tuple[Path, dict[str, Any]]] = []
    directory = paths["open_positions_dir"]
    if directory.exists():
        for path in sorted(directory.glob("*.json")):
            position = _read_json(path, {})
            if position.get("open"):
                positions.append((path, position))
    legacy = _read_json(paths["open_position"], {})
    if legacy.get("open"):
        legacy_trade_id = str(legacy.get("source_trade_id", ""))
        if legacy_trade_id and not any(str(item.get("source_trade_id", "")) == legacy_trade_id for _, item in positions):
            migrated_path = _position_path(root, legacy_trade_id)
            migrated_path.parent.mkdir(parents=True, exist_ok=True)
            if not migrated_path.exists():
                _write_json(migrated_path, legacy)
            positions.append((migrated_path, legacy))
    positions.sort(key=lambda item: _parse_timestamp(str(item[1].get("created_at", ""))) or datetime.min.replace(tzinfo=timezone.utc))
    return positions


def _open_position_symbols(root: Path) -> set[str]:
    return {str(position.get("symbol", "")).upper() for _, position in _open_positions(root) if position.get("symbol")}


def _open_position_exposure_quote(root: Path) -> Decimal:
    exposure = Decimal("0")
    for _, position in _open_positions(root):
        exposure += _parse_decimal(str(position.get("entry_quote_filled") or position.get("entry_quote_spent_delta")), "0")
    return exposure


def _source_timestamp(row: dict[str, str]) -> datetime | None:
    for key in ("timestamp", "decision_slot", "closed_1h_candle_start", "entry_time", "source_timestamp"):
        parsed = _parse_timestamp(row.get(key))
        if parsed is not None:
            return parsed
    return None


def _source_trade_id(row: dict[str, str]) -> str:
    return str(row.get("trade_id") or row.get("decision_key") or row.get("source_trade_id") or "").strip()


def _source_event_type(row: dict[str, str]) -> str:
    return str(row.get("event_type") or row.get("order_event_type") or "").strip().upper()


def _source_direction(row: dict[str, str]) -> str:
    return str(row.get("direction") or row.get("side") or "").strip().lower()


def _source_symbol(row: dict[str, str]) -> str:
    return str(row.get("symbol") or "").strip().upper()


def _row_is_trade_signal(row: dict[str, str]) -> bool:
    event = _source_event_type(row)
    triggered = _parse_bool(row.get("trade_triggered"))
    accepted = _parse_bool(row.get("setup_accepted"))
    has_trade_id = bool(_source_trade_id(row))
    if event == "ENTRY":
        return True
    return has_trade_id and (triggered or accepted)


def _source_entry(row: dict[str, str]) -> str:
    return str(row.get("entry_price") or row.get("entry_reference") or "")


def _source_stop(row: dict[str, str]) -> str:
    return str(row.get("initial_stop") or row.get("stop_reference") or "")


def _source_target(row: dict[str, str]) -> str:
    return str(row.get("exit_price") or row.get("target_reference") or "")


def _source_setup_class(row: dict[str, str]) -> str:
    return str(row.get("setup_class") or row.get("source_setup_class") or "").strip().upper()


def _source_convexity_label(row: dict[str, str]) -> str:
    return str(row.get("convexity_label") or row.get("personality_label") or "").strip().lower()


def _conviction_tier(setup_class: str, convexity_label: str) -> str:
    if str(convexity_label).lower() == "elite_convexity":
        return "elite"
    if str(setup_class).upper() == "A" or str(convexity_label).lower() == "strong_convexity":
        return "a_plus"
    return "normal"


def _activation_timestamp(root: Path, source_rows: list[dict[str, str]], allow_backlog: bool) -> datetime | None:
    if allow_backlog:
        return None
    path = _paths(root)["activation"]
    existing = _parse_timestamp(str(_read_json(path, {}).get("activated_after_source_timestamp", "")))
    if existing is not None:
        return existing
    timestamps = [ts for ts in (_source_timestamp(row) for row in source_rows) if ts is not None]
    watermark = max(timestamps) if timestamps else _now_dt()
    _write_json(
        path,
        {
            "activated_after_source_timestamp": watermark,
            "created_at": _now(),
            "reason": "initial_live_canary_activation_blocks_historical_replay",
            "allow_backlog_replay": False,
        },
    )
    return watermark


def _candidate_fieldnames() -> list[str]:
    return [
        "created_at",
        "source_trade_id",
        "source_timestamp",
        "symbol",
        "execution_symbol",
        "direction",
        "event_type",
        "entry_reference",
        "stop_reference",
        "target_reference",
        "setup_class",
        "convexity_label",
        "conviction_tier",
        "eligible",
        "skip_reason",
        "mode",
        "canary_order_submitted",
    ]


def _order_fieldnames() -> list[str]:
    return [
        "created_at",
        "event_type",
        "source_trade_id",
        "symbol",
        "side",
        "client_order_id",
        "exchange_order_id",
        "exchange_status",
        "quantity",
        "executed_qty",
        "quote_filled",
        "reference_price",
        "max_order_notional_quote",
        "reason",
        "real_money_allowed",
        "production_strategy_order_path_allowed",
    ]


def _fill_fieldnames() -> list[str]:
    return ["created_at", "symbol", "side", "client_order_id", "price", "qty", "commission", "commission_asset", "trade_id"]


def _roundtrip_fieldnames() -> list[str]:
    return [
        "created_at",
        "source_trade_id",
        "symbol",
        "quote_asset",
        "entry_client_order_id",
        "exit_client_order_id",
        "entry_quote_filled",
        "exit_quote_filled",
        "quote_delta",
        "base_delta",
        "quote_balance_before_exit",
        "quote_balance_after_exit",
        "base_balance_after_exit",
        "estimated_total_equity_quote_after_exit",
        "exit_reason",
        "result_label",
        "setup_class",
        "convexity_label",
        "conviction_tier",
        "research_sizing_profile",
        "execution_guard_classification",
        "execution_patience_attempts",
        "execution_patience_delay_seconds",
    ]


def _fmt_decimal(value: Any, suffix: str = "") -> str:
    try:
        dec = Decimal(str(value))
    except Exception:
        text = str(value or "")
        return f"{text}{suffix}" if text else ""
    formatted = f"{dec:,.8f}".rstrip("0").rstrip(".")
    return f"{formatted}{suffix}"


def _fmt_signed_quote(value: Any, asset: str = "USDC") -> str:
    try:
        dec = Decimal(str(value))
    except Exception:
        return f"{value} {asset}".strip()
    sign = "+" if dec > 0 else ""
    return f"{sign}{_fmt_decimal(dec)} {asset}"


def _html_document(*, title: str, hero: str, hero_kind: str, sections: list[tuple[str, list[tuple[str, Any]]]], footer: str) -> str:
    color = "#10b981" if hero_kind == "profit" else "#f59e0b" if hero_kind == "entry" else "#ef4444"
    accent_bg = "rgba(16,185,129,.16)" if hero_kind == "profit" else "rgba(245,158,11,.16)" if hero_kind == "entry" else "rgba(239,68,68,.16)"
    emoji = "🎯" if hero_kind == "profit" else "⚡" if hero_kind == "entry" else "🛡️"
    status_label = "PROFIT EXIT" if hero_kind == "profit" else "LIVE CANARY ENTRY" if hero_kind == "entry" else "LOSS CONTROL"
    first_rows = sections[0][1] if sections else []
    kpi_html = []
    for key, value in first_rows[:4]:
        kpi_html.append(
            "<td class=\"metric\">"
            f"<div class=\"metricLabel\">{escape(str(key))}</div>"
            f"<div class=\"metricValue\">{escape(str(value))}</div>"
            "</td>"
        )
    rows: list[str] = []
    for heading, items in sections:
        rows.append(f"<div class=\"section\"><h2>{escape(heading)}</h2>")
        rows.append("<table class=\"dataTable\">")
        for key, value in items:
            rows.append(
                "<tr>"
                f"<th>{escape(str(key))}</th>"
                f"<td>{escape(str(value))}</td>"
                "</tr>"
            )
        rows.append("</table></div>")
    return f"""<!doctype html>
<html>
  <body style="margin:0;background:#050b16;color:#e5eef9;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif;">
    <div class="stage" style="max-width:860px;margin:0 auto;padding:28px;">
      <div class="shell">
        <div class="topbar">
          <div class="eyebrow">RTS Live Canary · Binance Spot · USDC guarded execution</div>
          <h1>{escape(title)}</h1>
          <div class="subtitle">Tiny real-money canary only. This is not full capital deployment.</div>
        </div>
        <div class="content">
          <div class="hero" style="border-color:{color};background:linear-gradient(135deg,{accent_bg},rgba(15,23,42,.88));">
            <div class="orb" style="background:{color};box-shadow:0 0 34px {color};">{emoji}</div>
            <div>
              <div class="heroLabel" style="color:{color};">{status_label}</div>
              <div class="heroText">{escape(hero)}</div>
            </div>
          </div>
          <table class="metricGrid"><tr>{''.join(kpi_html)}</tr></table>
          {''.join(rows)}
          <div class="footerBox">{escape(footer)}</div>
        </div>
      </div>
    </div>
    <style>
      @keyframes pulseGlow {{ 0% {{ transform:scale(1); opacity:.92; }} 50% {{ transform:scale(1.04); opacity:1; }} 100% {{ transform:scale(1); opacity:.92; }} }}
      .shell {{ border:1px solid rgba(148,163,184,.38); border-radius:26px; background:radial-gradient(circle at 20% 0%,rgba(34,211,238,.22),transparent 34%),radial-gradient(circle at 100% 0%,rgba(168,85,247,.20),transparent 30%),linear-gradient(135deg,#07111f,#0b2532 54%,#111827); box-shadow:0 24px 70px rgba(0,0,0,.48); overflow:hidden; }}
      .topbar {{ padding:28px 32px; border-bottom:1px solid rgba(148,163,184,.24); background:rgba(255,255,255,.035); }}
      .eyebrow {{ letter-spacing:.18em; text-transform:uppercase; color:#93c5fd; font-size:12px; font-weight:900; }}
      h1 {{ font-size:31px; line-height:1.15; margin:10px 0 8px; color:#ffffff; }}
      .subtitle {{ color:#a8b3c7; font-size:14px; font-weight:700; }}
      .content {{ padding:28px 32px 32px; }}
      .hero {{ border:1px solid; border-radius:22px; padding:22px; margin-bottom:18px; display:flex; gap:16px; align-items:center; box-shadow:inset 0 0 42px rgba(255,255,255,.035); }}
      .orb {{ width:54px; height:54px; border-radius:18px; display:inline-flex; align-items:center; justify-content:center; font-size:26px; animation:pulseGlow 2.8s ease-in-out infinite; }}
      .heroLabel {{ font-size:13px; letter-spacing:.14em; text-transform:uppercase; font-weight:950; }}
      .heroText {{ font-size:32px; line-height:1.14; color:#ffffff; font-weight:950; margin-top:6px; }}
      .metricGrid {{ width:100%; border-collapse:separate; border-spacing:10px; margin:0 0 18px; }}
      .metric {{ width:25%; padding:14px; border:1px solid rgba(125,211,252,.24); border-radius:16px; background:linear-gradient(135deg,rgba(14,165,233,.12),rgba(15,23,42,.78)); vertical-align:top; }}
      .metricLabel {{ color:#93a4b8; font-size:11px; letter-spacing:.12em; text-transform:uppercase; font-weight:900; }}
      .metricValue {{ color:#f8fafc; font-size:16px; line-height:1.25; font-weight:950; margin-top:7px; }}
      .section {{ border:1px solid rgba(148,163,184,.20); border-radius:18px; padding:14px; margin:16px 0; background:rgba(2,6,23,.34); }}
      .dataTable {{ width:100%; border-collapse:collapse; background:rgba(15,23,42,.72); border-radius:14px; overflow:hidden; }}
      th,td {{ padding:12px 14px; border-bottom:1px solid rgba(148,163,184,.18); text-align:left; vertical-align:top; }}
      th {{ width:40%; color:#93a4b8; font-size:12px; text-transform:uppercase; letter-spacing:.08em; }}
      td {{ color:#f8fafc; font-size:15px; font-weight:800; }}
      h2 {{ color:#e0f2fe; font-size:18px; margin:0 0 10px; }}
      .footerBox {{ margin-top:20px; color:#cbd5e1; font-size:13px; line-height:1.6; border:1px solid rgba(148,163,184,.18); border-radius:16px; padding:14px; background:rgba(15,23,42,.55); }}
    </style>
  </body>
</html>
"""


def _email(root: Path, *, subject: str, body_lines: list[str], html_body: str | None = None) -> dict[str, Any]:
    paths = _paths(root)
    recipient = os.getenv("RTS_ALERT_EMAIL_TO", DEFAULT_ALERT_TO)
    enabled = _parse_bool(os.getenv("RTS_ALERT_EMAIL_ENABLED"))
    dry_run = _parse_bool(os.getenv("RTS_ALERT_EMAIL_DRY_RUN"))
    host = os.getenv("RTS_ALERT_SMTP_HOST", "").strip()
    sender = os.getenv("RTS_ALERT_EMAIL_FROM", "").strip()
    username = os.getenv("RTS_ALERT_SMTP_USERNAME", "").strip()
    password = os.getenv("RTS_ALERT_SMTP_PASSWORD", "")
    body = "\n".join(body_lines + ["", f"Artifact root: {root}"])
    paths["latest_email"].parent.mkdir(parents=True, exist_ok=True)
    paths["latest_email"].write_text(f"To: {recipient}\nSubject: {subject}\n\n{body}\n", encoding="utf-8")
    if html_body:
        paths["latest_email_html"].write_text(html_body, encoding="utf-8")
    sent = False
    note = "draft_written"
    smtp_allowed, smtp_note = smtp_allowed_for_output_root(root)
    if not smtp_allowed:
        note = smtp_note
    if smtp_allowed and enabled and not dry_run and host and sender:
        msg = EmailMessage()
        msg["From"] = sender
        msg["To"] = recipient
        msg["Subject"] = subject
        msg.set_content(body)
        if html_body:
            msg.add_alternative(html_body, subtype="html")
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
        "email_html_path": str(paths["latest_email_html"]) if html_body else "",
    }
    _append_csv(
        paths["email_ledger"],
        record,
        ["created_at", "subject", "recipient", "email_sent", "email_draft_written", "email_note", "email_path"],
    )
    return record


def _limits() -> dict[str, Any]:
    max_account = _parse_decimal(os.getenv("RTS_LIVE_CANARY_MAX_ACCOUNT_CAPITAL_EUR"), "100")
    max_budget = _parse_decimal(os.getenv("RTS_LIVE_CANARY_MAX_TEST_BUDGET_EUR"), "50")
    max_order = _parse_decimal(os.getenv("RTS_LIVE_CANARY_MAX_ORDER_NOTIONAL_EUR"), "10")
    max_daily_loss = _parse_decimal(os.getenv("RTS_LIVE_CANARY_MAX_DAILY_LOSS_EUR"), "10")
    max_open = int(os.getenv("RTS_LIVE_CANARY_MAX_OPEN_POSITIONS", "1") or "1")
    return {
        "max_account_capital_eur": max_account,
        "max_test_budget_eur": max_budget,
        "max_order_notional_eur": max_order,
        "max_daily_loss_eur": max_daily_loss,
        "max_open_positions": max_open,
        "caps_ok": (
            Decimal("0") < max_account <= MAX_HARD_ACCOUNT_CAPITAL_EUR
            and Decimal("0") < max_budget <= MAX_HARD_TEST_BUDGET_EUR
            and Decimal("0") < max_order <= MAX_HARD_ORDER_NOTIONAL_EUR
            and Decimal("0") < max_daily_loss <= MAX_HARD_DAILY_LOSS_EUR
            and 1 <= max_open <= MAX_OPEN_POSITIONS
        ),
    }


def _confirmations_present() -> bool:
    return (
        os.getenv("RTS_LIVE_CANARY_ENABLED", "").strip().lower() == REQUIRED_ENABLED_VALUE
        and os.getenv("RTS_LIVE_CANARY_CONFIRM", "").strip() in REQUIRED_CONFIRMATION_VALUES
        and os.getenv("RTS_LIVE_CANARY_I_UNDERSTAND_MAX_LOSS", "").strip() in REQUIRED_LOSS_ACK_VALUES
    )


def _forbidden_env_present() -> list[str]:
    return [name for name in sorted(FORBIDDEN_ENV_NAMES) if os.getenv(name)]


def _safety_manifest(mode: str, root: Path, source_ledger: Path) -> dict[str, Any]:
    limits = _limits()
    credentials_present = bool(os.getenv("BINANCE_LIVE_SMOKE_API_KEY") and os.getenv("BINANCE_LIVE_SMOKE_API_SECRET"))
    confirmations = _confirmations_present()
    forbidden = _forbidden_env_present()
    orders_allowed = mode == "execute_once" and limits["caps_ok"] and credentials_present and confirmations and not forbidden
    return {
        "court_name": COURT_NAME,
        "created_at": _now(),
        "mode": mode,
        "source_ledger": source_ledger,
        "output_root": root,
        "credentials_present": credentials_present,
        "dedicated_live_smoke_keys_required": True,
        "generic_or_demo_keys_present": forbidden,
        "generic_or_demo_keys_rejected": True,
        "run_confirmation_present": confirmations,
        **limits,
        "orders_allowed_in_this_mode": orders_allowed,
        "micro_live_canary_only": True,
        "live_canary_order_path_allowed": orders_allowed,
        "production_strategy_order_path_allowed": False,
        "full_live_trading_allowed": False,
        "strategy_scheduler_live_allowed": False,
        "paper_validation_ready": False,
        "real_money_allowed": orders_allowed,
        "spot_mainnet_only": True,
        "short_selling_allowed": False,
        "margin_allowed": False,
        "futures_allowed": False,
        "withdrawal_allowed": False,
        "deposit_allowed": False,
        "account_transfer_allowed": False,
    }


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest["generic_or_demo_keys_present"]:
        raise BinanceLiveSpotSafetyError("forbidden generic/demo key variables present")
    if not manifest["caps_ok"]:
        raise BinanceLiveSpotSafetyError("live canary caps exceed hard-coded safety limits")
    if not (1 <= int(manifest["max_open_positions"]) <= MAX_OPEN_POSITIONS):
        raise BinanceLiveSpotSafetyError("live canary max_open_positions must be 1 or 2")


def _asset_balance(account: dict[str, Any], asset: str) -> Decimal:
    for row in account.get("balances", []):
        if str(row.get("asset", "")).upper() == asset.upper():
            return Decimal(str(row.get("free", "0"))) + Decimal(str(row.get("locked", "0")))
    return Decimal("0")


def _daily_closed_loss(root: Path) -> Decimal:
    rows = _read_csv(_paths(root)["roundtrip_ledger"])
    today = _now_dt().date()
    loss = Decimal("0")
    for row in rows:
        ts = _parse_timestamp(row.get("created_at"))
        if ts is None or ts.date() != today:
            continue
        delta = _parse_decimal(row.get("quote_delta"), "0")
        if delta < 0:
            loss += abs(delta)
    return loss


def _candidate_rows(root: Path, source_ledger: Path, *, allow_backlog: bool, lookback_hours: int, symbol_allowlist: set[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    rows = _read_csv(source_ledger)
    activation = _activation_timestamp(root, rows, allow_backlog)
    cutoff = _now_dt() - timedelta(hours=lookback_hours) if lookback_hours > 0 else None
    existing_order_rows = _read_csv(_paths(root)["order_ledger"])
    processed = {row.get("source_trade_id", "") for row in existing_order_rows if row.get("source_trade_id")}
    candidates: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    for row in rows:
        ts = _source_timestamp(row)
        trade_id = _source_trade_id(row)
        symbol = _source_symbol(row)
        direction = _source_direction(row)
        event_type = _source_event_type(row)
        setup_class = _source_setup_class(row)
        convexity_label = _source_convexity_label(row)
        reason = ""
        if not _row_is_trade_signal(row):
            reason = "not_a_trade_entry_signal"
        elif not trade_id:
            reason = "missing_trade_id"
        elif trade_id in processed:
            reason = "already_processed"
        elif ts is None:
            reason = "invalid_timestamp"
        elif activation is not None and ts <= activation:
            reason = "before_or_at_live_canary_activation_checkpoint"
        elif cutoff is not None and ts < cutoff:
            reason = "outside_lookback"
        elif symbol not in symbol_allowlist:
            reason = "symbol_not_allowlisted"
        elif event_type and event_type != "ENTRY":
            reason = "source_event_not_entry"
        elif direction not in {"long", "buy", ""}:
            reason = "spot_live_canary_rejects_short_or_non_long"
        elif str(row.get("order_created", row.get("live_trade_created", "false"))).lower() == "true":
            reason = "source_claims_order_created"
        candidate = {
            "created_at": _now(),
            "source_trade_id": trade_id,
            "source_timestamp": ts.isoformat() if ts else "",
            "symbol": symbol,
            "execution_symbol": USDT_TO_USDC.get(symbol, ""),
            "direction": direction or "long",
            "event_type": event_type or "ENTRY",
            "entry_reference": _source_entry(row),
            "stop_reference": _source_stop(row),
            "target_reference": _source_target(row),
            "setup_class": setup_class,
            "convexity_label": convexity_label,
            "conviction_tier": _conviction_tier(setup_class, convexity_label),
            "eligible": not bool(reason),
            "skip_reason": reason,
            "mode": "",
            "canary_order_submitted": False,
            "raw": row,
        }
        if reason:
            if reason not in {"not_a_trade_entry_signal", "already_processed", "outside_lookback"}:
                skipped.append(candidate)
            continue
        candidates.append(candidate)
    candidates.sort(key=lambda item: _parse_timestamp(str(item["source_timestamp"])) or datetime.min.replace(tzinfo=timezone.utc))
    return candidates, skipped, len(rows)


def _record_order(root: Path, *, event_type: str, source_trade_id: str, side: str, symbol: str, client_order_id: str, response: dict[str, Any], price: Decimal, max_order: Decimal, reason: str, real_money_allowed: bool) -> None:
    _append_csv(
        _paths(root)["order_ledger"],
        {
            "created_at": _now(),
            "event_type": event_type,
            "source_trade_id": source_trade_id,
            "symbol": symbol,
            "side": side,
            "client_order_id": client_order_id,
            "exchange_order_id": str(response.get("orderId", "")),
            "exchange_status": str(response.get("status", "")),
            "quantity": str(response.get("origQty", "")),
            "executed_qty": str(response.get("executedQty", "0")),
            "quote_filled": str(response.get("cummulativeQuoteQty", "0")),
            "reference_price": price,
            "max_order_notional_quote": max_order,
            "reason": reason,
            "real_money_allowed": real_money_allowed,
            "production_strategy_order_path_allowed": False,
        },
        _order_fieldnames(),
    )
    for fill in response.get("fills", []) or []:
        _append_csv(
            _paths(root)["fill_ledger"],
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


def _entry_email(root: Path, position: dict[str, Any]) -> dict[str, Any]:
    source_symbol = str(position["source_symbol"])
    execution_symbol = str(position["symbol"])
    quote_asset = str(position["quote_asset"])
    base_asset = str(position["base_asset"])
    quote_filled = _fmt_decimal(position["entry_quote_filled"], f" {quote_asset}")
    total_equity = position.get("estimated_total_equity_quote_after_entry", position.get("quote_balance_after_entry", ""))
    patience_attempts = position.get("execution_patience_attempts", "")
    patience_delay = position.get("execution_patience_delay_seconds", "")
    conviction_tier = str(position.get("conviction_tier") or "normal")
    research_sizing_profile = str(position.get("research_sizing_profile") or "A+/Elite research sizing candidate; live canary remains micro-capped")
    subject = (
        f"RTS LIVE CANARY ENTRY [{conviction_tier.upper()}]: {source_symbol} -> "
        f"{execution_symbol} BUY {quote_filled} | Equity {_fmt_decimal(total_equity, f' {quote_asset}')}"
    )
    html = _html_document(
        title=f"Entry opened: {execution_symbol}",
        hero=f"BUY filled: {quote_filled}",
        hero_kind="entry",
        sections=[
            (
                "Execution",
                [
                    ("Source signal", source_symbol),
                    ("Execution pair", execution_symbol),
                    ("Side", "BUY / spot long only"),
                    ("Source trade id", position["source_trade_id"]),
                    ("Entry order id", position["entry_exchange_order_id"]),
                    ("Executed quantity", f"{_fmt_decimal(position['entry_executed_qty'])} {base_asset}"),
                    ("Quote filled", quote_filled),
                    ("Estimated total canary equity after entry", _fmt_decimal(total_equity, f" {quote_asset}")),
                ],
            ),
            (
                "A+/Elite research sizing label",
                [
                    ("Conviction tier", conviction_tier),
                    ("Setup class", position.get("setup_class", "")),
                    ("Convexity label", position.get("convexity_label", "")),
                    ("Research sizing profile", research_sizing_profile),
                    ("Live canary sizing", "micro-live two-slot cap; research sizing is not full-live enabled"),
                ],
            ),
            (
                "USDC execution patience guard",
                [
                    ("Guard", "5-minute symbol-aware USDT-signal → USDC-execution patience guard"),
                    ("Decision", position.get("execution_guard_classification", "")),
                    ("Attempts", patience_attempts),
                    ("Wait before safe execution", f"{patience_delay}s" if patience_delay != "" else ""),
                    ("Initial block reasons", ", ".join(position.get("execution_guard_initial_reasons", []))),
                    ("Final reasons", ", ".join(position.get("execution_guard_reasons", []))),
                ],
            ),
            (
                "Frozen signal references",
                [
                    ("Source timestamp", position.get("source_timestamp", "")),
                    ("Source entry reference", position.get("entry_reference", "")),
                    ("Stop reference", position.get("stop_reference", "")),
                    ("Target reference", position.get("target_reference", "")),
                ],
            ),
            (
                "Safety",
                [
                    ("Max canary order", _fmt_decimal(position.get("max_order_notional_quote", ""), f" {quote_asset}")),
                    ("Position rule", f"up to {position.get('max_open_positions', 1)} open canary positions; total exposure capped by test budget"),
                    ("Execution product", "Binance Spot only"),
                    ("Disabled", "short-selling, margin, futures, withdrawals, full-capital live deployment"),
                ],
            ),
        ],
        footer="Entry email is sent immediately after the BUY fill. Exit email is sent only later, when a future scheduler run detects the frozen target/stop exit condition and the SELL fill completes.",
    )
    return _email(
        root,
        subject=subject,
        body_lines=[
            "RTS LIVE CANARY ENTRY",
            "=====================",
            "",
            f"BUY FILLED: {quote_filled}",
            f"Estimated total canary equity after entry: {_fmt_decimal(total_equity, f' {quote_asset}')}",
            "",
            "Execution",
            "---------",
            f"Source signal symbol: {source_symbol}",
            f"Execution symbol: {execution_symbol}",
            f"Source trade id: {position['source_trade_id']}",
            f"Source timestamp: {position.get('source_timestamp', '')}",
            f"Entry order id: {position['entry_exchange_order_id']}",
            f"Executed quantity: {_fmt_decimal(position['entry_executed_qty'])} {base_asset}",
            f"Quote filled: {quote_filled}",
            "",
            "A+/Elite research sizing label",
            "--------------------------------",
            f"Conviction tier: {conviction_tier}",
            f"Setup class: {position.get('setup_class', '')}",
            f"Convexity label: {position.get('convexity_label', '')}",
            f"Research sizing profile: {research_sizing_profile}",
            "Live canary sizing: micro-live two-slot cap; research sizing is not full-live enabled",
            "",
            "USDC execution patience guard",
            "-----------------------------",
            "Guard: 5-minute symbol-aware USDT-signal -> USDC-execution patience guard",
            f"Decision: {position.get('execution_guard_classification', '')}",
            f"Attempts: {patience_attempts}",
            f"Wait before safe execution: {patience_delay}s",
            f"Initial block reasons: {', '.join(position.get('execution_guard_initial_reasons', []))}",
            f"Final reasons: {', '.join(position.get('execution_guard_reasons', []))}",
            "",
            "Frozen signal references",
            "------------------------",
            f"Entry reference: {position.get('entry_reference', '')}",
            f"Stop reference: {position.get('stop_reference', '')}",
            f"Target reference: {position.get('target_reference', '')}",
            "",
            "Safety",
            "------",
            "This is micro real-money canary execution only.",
            "Entry email is immediate after BUY fill.",
            "Exit email is sent only after a later SELL fill.",
            "Spot only, long only, no margin, no futures, no withdrawals, no full-capital live deployment.",
        ],
        html_body=html,
    )


def _exit_email(root: Path, roundtrip: dict[str, Any]) -> dict[str, Any]:
    quote_delta = _parse_decimal(str(roundtrip.get("quote_delta")), "0")
    symbol = str(roundtrip["symbol"])
    quote_asset = str(roundtrip.get("quote_asset") or symbol[-4:] or "USDC")
    if quote_delta > 0:
        label = "CONGRATULATIONS PROFIT"
        hero = f"CONGRATULATIONS — PROFIT {_fmt_signed_quote(quote_delta, quote_asset)}"
        hero_kind = "profit"
    elif quote_delta < 0:
        label = "OOPS LOSS CONTROL"
        hero = f"OOPS — LOSS {_fmt_signed_quote(quote_delta, quote_asset)}"
        hero_kind = "loss"
    else:
        label = "FLAT EXIT"
        hero = f"FLAT EXIT {_fmt_signed_quote(quote_delta, quote_asset)}"
        hero_kind = "entry"
    total_equity = roundtrip.get("estimated_total_equity_quote_after_exit", roundtrip.get("quote_balance_after_exit", ""))
    conviction_tier = str(roundtrip.get("conviction_tier") or "normal")
    research_sizing_profile = str(roundtrip.get("research_sizing_profile") or "A+/Elite research sizing candidate; live canary remains micro-capped")
    subject = f"RTS LIVE CANARY EXIT {label} [{conviction_tier.upper()}]: {symbol} PnL { _fmt_signed_quote(quote_delta, quote_asset) } | Equity {_fmt_decimal(total_equity, f' {quote_asset}')}"
    html = _html_document(
        title=f"Exit closed: {symbol}",
        hero=f"{hero} | Total equity {_fmt_decimal(total_equity, f' {quote_asset}')}",
        hero_kind=hero_kind,
        sections=[
            (
                "PnL",
                [
                    ("Net canary PnL / quote delta", _fmt_signed_quote(quote_delta, quote_asset)),
                    ("Total canary equity after exit", _fmt_decimal(total_equity, f" {quote_asset}")),
                    ("Result", str(roundtrip.get("result_label", ""))),
                    ("Exit reason", str(roundtrip.get("exit_reason", ""))),
                ],
            ),
            (
                "Execution",
                [
                    ("Symbol", symbol),
                    ("Source trade id", roundtrip["source_trade_id"]),
                    ("Entry order id", roundtrip["entry_client_order_id"]),
                    ("Exit order id", roundtrip["exit_client_order_id"]),
                    ("Entry quote filled", _fmt_decimal(roundtrip["entry_quote_filled"], f" {quote_asset}")),
                    ("Exit quote filled", _fmt_decimal(roundtrip["exit_quote_filled"], f" {quote_asset}")),
                    ("Base delta after close", _fmt_decimal(roundtrip.get("base_delta", ""))),
                ],
            ),
            (
                "A+/Elite research sizing label",
                [
                    ("Conviction tier", conviction_tier),
                    ("Setup class", str(roundtrip.get("setup_class", ""))),
                    ("Convexity label", str(roundtrip.get("convexity_label", ""))),
                    ("Research sizing profile", research_sizing_profile),
                    ("Live canary sizing", "micro-live two-slot cap; research sizing is not full-live enabled"),
                ],
            ),
            (
                "USDC execution patience guard",
                [
                    ("Entry guard", str(roundtrip.get("execution_guard_classification", ""))),
                    ("Entry guard attempts", str(roundtrip.get("execution_patience_attempts", ""))),
                    ("Entry guard wait", f"{roundtrip.get('execution_patience_delay_seconds', '')}s"),
                    ("Route", "USDT frozen signal mapped to USDC Spot execution"),
                ],
            ),
            (
                "Safety",
                [
                    ("Execution product", "Binance Spot only"),
                    ("Disabled", "short-selling, margin, futures, withdrawals, full-capital live deployment"),
                ],
            ),
        ],
        footer="Exit email is sent only after the SELL fill is completed and the roundtrip ledger is written.",
    )
    return _email(
        root,
        subject=subject,
        body_lines=[
            f"RTS LIVE CANARY EXIT — {label}",
            "===================================",
            "",
            hero,
            f"Total canary equity after exit: {_fmt_decimal(total_equity, f' {quote_asset}')}",
            "",
            "PnL",
            "---",
            f"Net canary PnL / quote delta: {_fmt_signed_quote(quote_delta, quote_asset)}",
            f"Result: {roundtrip.get('result_label', '')}",
            f"Exit reason: {roundtrip['exit_reason']}",
            "",
            "Execution",
            "---------",
            f"Symbol: {symbol}",
            f"Source trade id: {roundtrip['source_trade_id']}",
            f"Entry order id: {roundtrip['entry_client_order_id']}",
            f"Exit order id: {roundtrip['exit_client_order_id']}",
            f"Entry quote filled: {_fmt_decimal(roundtrip['entry_quote_filled'], f' {quote_asset}')}",
            f"Exit quote filled: {_fmt_decimal(roundtrip['exit_quote_filled'], f' {quote_asset}')}",
            f"Base delta after close: {_fmt_decimal(roundtrip.get('base_delta', ''))}",
            "",
            "A+/Elite research sizing label",
            "--------------------------------",
            f"Conviction tier: {conviction_tier}",
            f"Setup class: {roundtrip.get('setup_class', '')}",
            f"Convexity label: {roundtrip.get('convexity_label', '')}",
            f"Research sizing profile: {research_sizing_profile}",
            "Live canary sizing: micro-live two-slot cap; research sizing is not full-live enabled",
            "",
            "USDC execution patience guard",
            "-----------------------------",
            f"Entry guard: {roundtrip.get('execution_guard_classification', '')}",
            f"Entry guard attempts: {roundtrip.get('execution_patience_attempts', '')}",
            f"Entry guard wait: {roundtrip.get('execution_patience_delay_seconds', '')}s",
            "Route: USDT frozen signal mapped to USDC Spot execution",
            "",
            "Safety",
            "------",
            "This is micro real-money canary execution only.",
            "Spot only, long only, no margin, no futures, no withdrawals, no full-capital live deployment.",
        ],
        html_body=html,
    )


def _maybe_exit_open_positions(root: Path, client: BinanceLiveSpotClient, manifest: dict[str, Any]) -> dict[str, Any] | None:
    monitored: list[dict[str, Any]] = []
    for position_path, position in _open_positions(root):
        symbol = str(position["symbol"]).upper()
        exchange_info = client.exchange_info(symbol)
        rules = parse_symbol_rules(exchange_info, symbol)
        price = client.ticker_price(symbol)
        target = _parse_decimal(str(position.get("target_reference", "")), "0")
        stop = _parse_decimal(str(position.get("stop_reference", "")), "0")
        exit_reason = ""
        if target > 0 and price >= target:
            exit_reason = "target_reference_reached"
        elif stop > 0 and price <= stop:
            exit_reason = "stop_reference_reached"
        if not exit_reason:
            monitored.append(
                {
                    "source_trade_id": position.get("source_trade_id", ""),
                    "symbol": symbol,
                    "current_price": price,
                    "target_reference": target,
                    "stop_reference": stop,
                }
            )
            continue
        before = client.account()
        base_before = _asset_balance(before, rules.base_asset)
        quote_before = _asset_balance(before, rules.quote_asset)
        base_at_entry = _parse_decimal(str(position.get("base_balance_before_entry", "0")), "0")
        sell_qty = floor_to_step(max(Decimal("0"), base_before - base_at_entry), rules.step_size)
        if sell_qty * price < rules.min_notional:
            raise BinanceLiveSpotSafetyError("open canary position is below Binance minimum sell notional")
        seed = f"{COURT_NAME}|EXIT|{position['source_trade_id']}|{_now()}"
        client_order_id = build_client_order_id("rtscanx", seed)
        intent = DemoOrderIntent(
            signal_id=seed,
            symbol=symbol,
            side="SELL",
            order_type="MARKET",
            quantity=sell_qty,
            reason=f"live_strategy_canary_exit_{exit_reason}",
        )
        response = client.create_order(intent, client_order_id)
        _record_order(
            root,
            event_type="EXIT",
            source_trade_id=str(position["source_trade_id"]),
            side="SELL",
            symbol=symbol,
            client_order_id=client_order_id,
            response=response,
            price=price,
            max_order=_parse_decimal(str(manifest["max_order_notional_eur"]), "10"),
            reason=f"live_strategy_canary_exit_{exit_reason}",
            real_money_allowed=True,
        )
        after = client.account()
        quote_after = _asset_balance(after, rules.quote_asset)
        base_after = _asset_balance(after, rules.base_asset)
        quote_delta = quote_after - quote_before - _parse_decimal(str(position.get("entry_quote_spent_delta", "0")), "0")
        roundtrip = {
            "created_at": _now(),
            "source_trade_id": position["source_trade_id"],
            "symbol": symbol,
            "quote_asset": rules.quote_asset,
            "entry_client_order_id": position["entry_client_order_id"],
            "exit_client_order_id": client_order_id,
            "entry_quote_filled": position["entry_quote_filled"],
            "exit_quote_filled": str(response.get("cummulativeQuoteQty", "0")),
            "quote_delta": quote_delta,
            "base_delta": base_after - _parse_decimal(str(position.get("base_balance_before_entry", "0")), "0"),
            "quote_balance_before_exit": quote_before,
            "quote_balance_after_exit": quote_after,
            "base_balance_after_exit": base_after,
            "estimated_total_equity_quote_after_exit": quote_after + (base_after * price),
            "exit_reason": exit_reason,
            "result_label": "PROFIT" if quote_delta > 0 else "LOSS" if quote_delta < 0 else "FLAT",
            "setup_class": position.get("setup_class", ""),
            "convexity_label": position.get("convexity_label", ""),
            "conviction_tier": position.get("conviction_tier", "normal"),
            "research_sizing_profile": position.get("research_sizing_profile", ""),
            "execution_guard_classification": position.get("execution_guard_classification", ""),
            "execution_patience_attempts": position.get("execution_patience_attempts", ""),
            "execution_patience_delay_seconds": position.get("execution_patience_delay_seconds", ""),
        }
        _append_csv(_paths(root)["roundtrip_ledger"], roundtrip, _roundtrip_fieldnames())
        position["open"] = False
        position["closed_at"] = _now()
        position["exit_client_order_id"] = client_order_id
        position["exit_exchange_order_id"] = str(response.get("orderId", ""))
        position["exit_reason"] = exit_reason
        _write_json(position_path, position)
        _write_json(_paths(root)["open_position"], position)
        email = _exit_email(root, roundtrip)
        return {
            **manifest,
            "final_classification": ROUNDTRIP_COMPLETED,
            "reason": "open_canary_position_exit_submitted",
            "orders_submitted": 1,
            "exit_order_status": str(response.get("status", "")),
            "roundtrip": roundtrip,
            "open_positions_monitored": monitored,
            "email": email,
        }
    return None


def _submit_entry(root: Path, client: BinanceLiveSpotClient, manifest: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    source_symbol = str(candidate["symbol"]).upper()
    max_open = int(manifest["max_open_positions"])
    open_positions = _open_positions(root)
    if len(open_positions) >= max_open:
        raise BinanceLiveSpotSafetyError("live_canary_open_position_slots_full")
    if USDT_TO_USDC.get(source_symbol, "") in _open_position_symbols(root):
        raise BinanceLiveSpotSafetyError("live_canary_already_has_open_position_for_execution_symbol")
    max_budget = _parse_decimal(str(manifest["max_test_budget_eur"]), "50")
    max_order_config = _parse_decimal(str(manifest["max_order_notional_eur"]), "10")
    remaining_budget = max_budget - _open_position_exposure_quote(root)
    max_order = min(max_order_config, remaining_budget)
    if max_order <= Decimal("0"):
        raise BinanceLiveSpotSafetyError("live_canary_test_budget_fully_allocated")
    guard_decision = evaluate_usdt_signal_to_usdc_execution_guard_with_patience(
        ExecutionSignal(
            source_symbol=source_symbol,
            side="BUY",
            order_notional_eur=max_order,
            source_signal_time=str(candidate.get("source_timestamp", "")),
            signal_id=str(candidate.get("source_trade_id", "")),
        ),
        thresholds=GuardThresholds(max_order_notional_eur=max_order_config),
        patience_config=PatienceGuardConfig(patience_seconds=300, recheck_interval_seconds=15),
    )
    if not guard_decision.accepted:
        raise BinanceLiveSpotSafetyError("usdt_usdc_execution_guard_blocked:" + ",".join(guard_decision.reasons))
    symbol = guard_decision.execution_symbol
    exchange_info = client.exchange_info(symbol)
    rules = parse_symbol_rules(exchange_info, symbol)
    price = client.ticker_price(symbol)
    quantity = quantity_for_notional(max_order, price, rules)
    estimated_notional = quantity * price
    if estimated_notional > max_order:
        raise BinanceLiveSpotSafetyError("computed canary order notional exceeds cap")
    if estimated_notional > max_budget:
        raise BinanceLiveSpotSafetyError("computed canary order exceeds test budget")
    if _daily_closed_loss(root) >= _parse_decimal(str(manifest["max_daily_loss_eur"]), "10"):
        raise BinanceLiveSpotSafetyError("daily canary loss cap reached")
    if client.open_orders(symbol):
        raise BinanceLiveSpotSafetyError("open Binance orders exist for symbol; refusing canary entry")
    before = client.account()
    quote_before = _asset_balance(before, rules.quote_asset)
    base_before = _asset_balance(before, rules.base_asset)
    estimated_account_value_quote = quote_before + (base_before * price)
    max_account = _parse_decimal(str(manifest["max_account_capital_eur"]), "100")
    if estimated_account_value_quote > max_account:
        raise BinanceLiveSpotSafetyError(
            f"estimated_{rules.quote_asset}_account_value_exceeds_live_canary_cap:"
            f"{decimal_to_plain(estimated_account_value_quote)}>{decimal_to_plain(max_account)}"
        )
    if quote_before < estimated_notional:
        raise BinanceLiveSpotSafetyError(f"insufficient_{rules.quote_asset}_balance_for_live_canary")
    seed = f"{COURT_NAME}|ENTRY|{candidate['source_trade_id']}|{_now()}"
    client_order_id = build_client_order_id("rtscane", seed)
    intent = DemoOrderIntent(
        signal_id=seed,
        symbol=symbol,
        side="BUY",
        order_type="MARKET",
        quantity=quantity,
        reason="live_strategy_canary_entry_from_frozen_signal",
    )
    response = client.create_order(intent, client_order_id)
    _record_order(
        root,
        event_type="ENTRY",
        source_trade_id=str(candidate["source_trade_id"]),
        side="BUY",
        symbol=symbol,
        client_order_id=client_order_id,
        response=response,
        price=price,
        max_order=max_order,
        reason="live_strategy_canary_entry_from_frozen_signal",
        real_money_allowed=True,
    )
    after = client.account()
    patience_metrics = dict(guard_decision.metrics.get("execution_patience_guard", {}))
    position = {
        "open": True,
        "created_at": _now(),
        "source_trade_id": candidate["source_trade_id"],
        "source_timestamp": candidate["source_timestamp"],
        "source_symbol": source_symbol,
        "symbol": symbol,
        "base_asset": rules.base_asset,
        "quote_asset": rules.quote_asset,
        "entry_client_order_id": client_order_id,
        "entry_exchange_order_id": str(response.get("orderId", "")),
        "entry_status": str(response.get("status", "")),
        "entry_executed_qty": str(response.get("executedQty", "0")),
        "entry_quote_filled": str(response.get("cummulativeQuoteQty", "0")),
        "entry_execution_reference_price": price,
        "entry_reference": candidate.get("entry_reference", ""),
        "stop_reference": candidate.get("stop_reference", ""),
        "target_reference": candidate.get("target_reference", ""),
        "setup_class": candidate.get("setup_class", ""),
        "convexity_label": candidate.get("convexity_label", ""),
        "conviction_tier": candidate.get("conviction_tier", "normal"),
        "research_sizing_profile": "a_plus_2p50_elite_3p00_total_5p00; live canary remains capped by RTS_LIVE_CANARY_MAX_ORDER_NOTIONAL_EUR and RTS_LIVE_CANARY_MAX_TEST_BUDGET_EUR",
        "base_balance_before_entry": base_before,
        "base_balance_after_entry": _asset_balance(after, rules.base_asset),
        "quote_balance_before_entry": quote_before,
        "quote_balance_after_entry": _asset_balance(after, rules.quote_asset),
        "entry_quote_spent_delta": quote_before - _asset_balance(after, rules.quote_asset),
        "estimated_total_equity_quote_after_entry": _asset_balance(after, rules.quote_asset) + (_asset_balance(after, rules.base_asset) * price),
        "max_order_notional_quote": max_order,
        "max_open_positions": max_open,
        "open_positions_after_entry": len(open_positions) + 1,
        "remaining_budget_before_entry": remaining_budget,
        "execution_guard_classification": guard_decision.classification,
        "execution_guard_reasons": guard_decision.reasons,
        "execution_guard_initial_reasons": patience_metrics.get("initial_reasons", []),
        "execution_patience_guard_enabled": True,
        "execution_patience_seconds": patience_metrics.get("patience_seconds", 300),
        "execution_patience_attempts": patience_metrics.get("attempts", ""),
        "execution_patience_delay_seconds": patience_metrics.get("delay_seconds", ""),
        "execution_patience_accepted_after_wait": patience_metrics.get("accepted_after_wait", False),
        "execution_patience_decision_rule": patience_metrics.get("decision_rule", ""),
    }
    _write_json(_position_path(root, str(candidate["source_trade_id"])), position)
    _write_json(_paths(root)["open_position"], position)
    email = _entry_email(root, position)
    return {
        **manifest,
        "final_classification": ORDER_SUBMITTED,
        "reason": "live_canary_entry_submitted_from_frozen_signal",
        "orders_submitted": 1,
        "entry_order_status": str(response.get("status", "")),
        "open_position": position,
        "email": email,
    }


def run(mode: str, *, source_ledger: Path | None = None, output_dir: Path | None = None) -> dict[str, Any]:
    root = resolve_project_path(output_dir or (output_root() / OUTPUT_FOLDER_NAME))
    source = resolve_project_path(source_ledger or (output_root() / DEFAULT_SOURCE_LEDGER))
    root.mkdir(parents=True, exist_ok=True)
    manifest = _safety_manifest(mode, root, source)
    _write_json(_paths(root)["safety_manifest"], manifest)
    status: dict[str, Any]
    try:
        _validate_manifest(manifest)
        allowlist = {item.strip().upper() for item in os.getenv("RTS_LIVE_CANARY_SYMBOL_ALLOWLIST", DEFAULT_SYMBOL_ALLOWLIST).split(",") if item.strip()}
        lookback_hours = int(os.getenv("RTS_LIVE_CANARY_LOOKBACK_HOURS", "168") or "168")
        allow_backlog = _parse_bool(os.getenv("RTS_LIVE_CANARY_ALLOW_BACKLOG_REPLAY"))
        candidates, skipped, source_rows = _candidate_rows(root, source, allow_backlog=allow_backlog, lookback_hours=lookback_hours, symbol_allowlist=allowlist)
        for row in candidates[:50]:
            row = {key: value for key, value in row.items() if key != "raw"}
            row["mode"] = mode
            _append_csv(_paths(root)["candidate_ledger"], row, _candidate_fieldnames())
        if mode in {"status", "dry_run"}:
            status = {
                **manifest,
                "final_classification": DRY_RUN_READY if candidates else NO_ELIGIBLE,
                "reason": "dry_run_no_order_submitted" if candidates else "no_fresh_eligible_live_canary_signal",
                "source_rows_seen": source_rows,
                "eligible_signals_seen": len(candidates),
                "skipped_signal_rows": len(skipped),
                "latest_candidate": {key: value for key, value in (candidates[-1] if candidates else {}).items() if key != "raw"},
                "orders_submitted": 0,
                "real_money_allowed": False,
                "live_canary_order_path_allowed": False,
                "open_position": _read_json(_paths(root)["open_position"], {}),
                "open_positions": [position for _, position in _open_positions(root)],
            }
        elif mode == "execute_once":
            if not manifest["credentials_present"]:
                raise BinanceLiveSpotSafetyError("missing_BINANCE_LIVE_SMOKE_API_KEY_or_BINANCE_LIVE_SMOKE_API_SECRET")
            if not manifest["run_confirmation_present"]:
                raise BinanceLiveSpotSafetyError("missing explicit live-canary confirmations")
            config = BinanceLiveSpotConfig.from_env(require_credentials=True, require_confirmation=False)
            client = BinanceLiveSpotClient(config)
            exit_status = _maybe_exit_open_positions(root, client, manifest)
            if exit_status is not None:
                status = exit_status
            elif not candidates:
                status = {
                    **manifest,
                    "final_classification": NO_ELIGIBLE,
                    "reason": "no_fresh_eligible_live_canary_signal",
                    "source_rows_seen": source_rows,
                    "eligible_signals_seen": 0,
                    "orders_submitted": 0,
                    "real_money_allowed": False,
                    "live_canary_order_path_allowed": False,
                    "open_positions": [position for _, position in _open_positions(root)],
                }
            elif len(_open_positions(root)) >= int(manifest["max_open_positions"]):
                status = {
                    **manifest,
                    "final_classification": POSITION_MONITORING,
                    "reason": "open_position_slots_full_no_exit_condition",
                    "source_rows_seen": source_rows,
                    "eligible_signals_seen": len(candidates),
                    "orders_submitted": 0,
                    "real_money_allowed": False,
                    "live_canary_order_path_allowed": False,
                    "open_positions": [position for _, position in _open_positions(root)],
                }
            else:
                status = _submit_entry(root, client, manifest, candidates[-1])
                status["source_rows_seen"] = source_rows
                status["eligible_signals_seen"] = len(candidates)
        else:
            raise BinanceLiveSpotSafetyError(f"unsupported mode: {mode}")
    except (BinanceLiveSpotSafetyError, BinanceLiveSpotExecutionError, Exception) as exc:  # noqa: BLE001
        safe_error = redact_secret(
            str(exc),
            os.getenv("BINANCE_LIVE_SMOKE_API_KEY", ""),
            os.getenv("BINANCE_LIVE_SMOKE_API_SECRET", ""),
        )
        classification = BLOCKED_NEEDS_KEYS if "BINANCE_LIVE_SMOKE" in safe_error else BLOCKED_SAFETY
        if not isinstance(exc, BinanceLiveSpotSafetyError):
            classification = FAILED
        status = {
            **manifest,
            "final_classification": classification,
            "reason": safe_error,
            "orders_submitted": 0,
            "real_money_allowed": False,
            "live_canary_order_path_allowed": False,
        }
    _write_json(_paths(root)["latest_status"], status)
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--mode", choices=["status", "dry_run", "execute_once"], default="dry_run")
    parser.add_argument("--source-ledger", type=Path, default=None)
    parser.add_argument("--output-dir", type=Path, default=None)
    args = parser.parse_args()
    print(json.dumps(_jsonable(run(args.mode, source_ledger=args.source_ledger, output_dir=args.output_dir)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
