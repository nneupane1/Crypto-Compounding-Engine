from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from structural_compounding_lab.execution.live_strategy_canary_bridge import (
    DEFAULT_SOURCE_LEDGER,
    _parse_timestamp,
    _source_event_type,
    _source_symbol,
    _source_timestamp,
    _source_trade_id,
)


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8", errors="replace") as handle:
        return list(csv.DictReader(handle))


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value if value not in {None, ""} else "0"))
    except Exception:
        return Decimal("0")


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


def audit(source_ledger: Path, *, max_signal_age_seconds: int = 7200, now: datetime | None = None) -> dict[str, Any]:
    rows = _read_csv(source_ledger)
    now = now or datetime.now(timezone.utc)
    exits_by_trade_id = {
        trade_id: row
        for row in rows
        if (trade_id := _source_trade_id(row)) and _source_event_type(row) == "EXIT"
    }
    entries = [row for row in rows if _source_trade_id(row) and _source_event_type(row) == "ENTRY"]

    executable: list[dict[str, Any]] = []
    blocked_closed: list[dict[str, Any]] = []
    blocked_stale: list[dict[str, Any]] = []

    per_symbol: dict[str, dict[str, Any]] = {}
    for row in entries:
        trade_id = _source_trade_id(row)
        symbol = _source_symbol(row)
        ts = _source_timestamp(row)
        age = None if ts is None else max(0.0, (now - ts.astimezone(timezone.utc)).total_seconds())
        pnl = _dec(row.get("net_pnl_eur") or row.get("pnl_eur"))
        record = {
            "trade_id": trade_id,
            "symbol": symbol,
            "timestamp": ts.isoformat() if ts else "",
            "age_seconds": age,
            "shadow_pnl_eur": pnl,
        }
        bucket = per_symbol.setdefault(
            symbol,
            {
                "entry_count": 0,
                "executable_count": 0,
                "blocked_already_closed_count": 0,
                "blocked_stale_count": 0,
                "executable_shadow_pnl_eur": Decimal("0"),
                "blocked_already_closed_shadow_pnl_eur": Decimal("0"),
                "blocked_stale_shadow_pnl_eur": Decimal("0"),
            },
        )
        bucket["entry_count"] += 1
        if trade_id in exits_by_trade_id:
            blocked_closed.append(record)
            bucket["blocked_already_closed_count"] += 1
            bucket["blocked_already_closed_shadow_pnl_eur"] += pnl
        elif age is not None and max_signal_age_seconds > 0 and age > max_signal_age_seconds:
            blocked_stale.append(record)
            bucket["blocked_stale_count"] += 1
            bucket["blocked_stale_shadow_pnl_eur"] += pnl
        else:
            executable.append(record)
            bucket["executable_count"] += 1
            bucket["executable_shadow_pnl_eur"] += pnl

    summary = {
        "created_at": now.isoformat(),
        "source_ledger": str(source_ledger),
        "max_signal_age_seconds": max_signal_age_seconds,
        "source_rows": len(rows),
        "entry_rows": len(entries),
        "exit_rows": len(exits_by_trade_id),
        "executable_entry_count": len(executable),
        "blocked_already_closed_count": len(blocked_closed),
        "blocked_stale_count": len(blocked_stale),
        "executable_shadow_pnl_eur": sum((row["shadow_pnl_eur"] for row in executable), Decimal("0")),
        "blocked_already_closed_shadow_pnl_eur": sum((row["shadow_pnl_eur"] for row in blocked_closed), Decimal("0")),
        "blocked_stale_shadow_pnl_eur": sum((row["shadow_pnl_eur"] for row in blocked_stale), Decimal("0")),
        "per_symbol": per_symbol,
        "blocked_examples": {
            "already_closed": blocked_closed[-10:],
            "stale": blocked_stale[-10:],
        },
        "interpretation": (
            "Blocked PnL is shadow PnL from signals that should not be chased by real-money canary. "
            "It is not deleted research edge; it is protected capital when the execution follower sees a signal too late."
        ),
    }
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-ledger", type=Path, default=Path("structural_compounding_lab/output") / DEFAULT_SOURCE_LEDGER)
    parser.add_argument("--output", type=Path, default=Path("structural_compounding_lab/output/binance_live_strategy_canary_court_001/live_executable_freshness_audit.json"))
    parser.add_argument("--max-signal-age-seconds", type=int, default=7200)
    args = parser.parse_args()
    result = audit(args.source_ledger, max_signal_age_seconds=args.max_signal_age_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(_jsonable(result), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
