from __future__ import annotations

import argparse
import csv
import json
import math
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path


COURT_NAME = "MULTI_SYMBOL_EXACT_FILL_AND_SYMBOL_CAP_CALIBRATION_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_symbol_exact_fill_symbol_cap_calibration_court_001"

PASSED = "MULTI_SYMBOL_EXACT_FILL_SYMBOL_CAP_CALIBRATION_PASSED_RESEARCH_ONLY"
WARNING = "MULTI_SYMBOL_EXACT_FILL_SYMBOL_CAP_CALIBRATION_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_SYMBOL_EXACT_FILL_SYMBOL_CAP_CALIBRATION_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_SYMBOL_EXACT_FILL_SYMBOL_CAP_CALIBRATION_BLOCKED_RESEARCH_ONLY"

BINANCE_BASE_URL = "https://api.binance.com"
EUR_TO_USDT_FALLBACK = 1.10
STRICT_MAX_SLIPPAGE_BPS = 25.0
WARNING_MAX_SLIPPAGE_BPS = 50.0
DEPTH_LIMIT = 5000

SYMBOLS: tuple[str, ...] = (
    "ADAUSDT",
    "LINKUSDT",
    "BNBUSDT",
    "XRPUSDT",
    "AVAXUSDT",
    "DOGEUSDT",
    "ETHUSDT",
    "SOLUSDT",
)

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
}


@dataclass(frozen=True)
class ExactFillConfig:
    project_root: Path
    package_root: Path
    earned_gear_root: Path
    public_fetch_root: Path
    output_root: Path
    depth_fetcher: Callable[[str], dict[str, Any]] | None = None


def default_config() -> ExactFillConfig:
    pkg = package_root()
    return ExactFillConfig(
        project_root=project_root(),
        package_root=pkg,
        earned_gear_root=pkg / "output" / "earned_capital_gear_ladder_court_001",
        public_fetch_root=pkg / "output" / "multi_symbol_public_fetch_runtime_prototype_court_001",
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round_payload(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
    if isinstance(value, dict):
        return {key: _round_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_round_payload(item) for item in value]
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_round_payload(payload), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return "" if math.isnan(value) or math.isinf(value) else round(value, 10)
    if value is None:
        return ""
    return value


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: _csv_value(row.get(key)) for key in keys})


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _http_json(url: str, *, timeout: float = 10.0) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"User-Agent": "Crypto-Compounding-Engine-Research-Court/1.0"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _fetch_eur_to_usdt() -> dict[str, Any]:
    try:
        payload = _http_json("https://api.frankfurter.app/latest?from=EUR&to=USD", timeout=8.0)
        rate = float((payload.get("rates") or {}).get("USD") or 0.0)
        if rate > 0:
            return {"eur_to_usdt": rate, "source": "frankfurter_public_eur_usd_proxy", "fallback_used": False}
    except Exception as exc:  # noqa: BLE001
        return {"eur_to_usdt": EUR_TO_USDT_FALLBACK, "source": "fallback_static_proxy", "fallback_used": True, "warning": f"{type(exc).__name__}: {exc}"}
    return {"eur_to_usdt": EUR_TO_USDT_FALLBACK, "source": "fallback_static_proxy", "fallback_used": True}


def _public_depth(symbol: str) -> dict[str, Any]:
    url = f"{BINANCE_BASE_URL}/api/v3/depth?{urllib.parse.urlencode({'symbol': symbol, 'limit': DEPTH_LIMIT})}"
    return _http_json(url, timeout=12.0)


def _levels(payload: dict[str, Any], side: str) -> list[tuple[float, float]]:
    return [(float(price), float(qty)) for price, qty in payload.get(side, [])]


def _mid_price(bids: list[tuple[float, float]], asks: list[tuple[float, float]]) -> float:
    if not bids or not asks:
        return 0.0
    return (bids[0][0] + asks[0][0]) / 2.0


def _simulate_market_fill(levels: list[tuple[float, float]], notional_usdt: float) -> dict[str, Any]:
    remaining = notional_usdt
    filled_notional = 0.0
    filled_qty = 0.0
    levels_used = 0
    for price, qty in levels:
        if remaining <= 0:
            break
        level_notional = price * qty
        take_notional = min(remaining, level_notional)
        take_qty = take_notional / price if price else 0.0
        filled_notional += take_notional
        filled_qty += take_qty
        remaining -= take_notional
        levels_used += 1
    vwap = filled_notional / filled_qty if filled_qty else 0.0
    return {
        "requested_notional_usdt": notional_usdt,
        "filled_notional_usdt": filled_notional,
        "unfilled_notional_usdt": max(0.0, remaining),
        "filled_ratio": filled_notional / notional_usdt if notional_usdt else 0.0,
        "vwap": vwap,
        "levels_used": levels_used,
        "fully_filled": remaining <= 1e-8,
    }


def _slippage_bps(fill: dict[str, Any], *, mid: float, side: str) -> float:
    if not fill.get("fully_filled") or not mid or not fill.get("vwap"):
        return float("inf")
    vwap = float(fill["vwap"])
    if side == "buy":
        return max(0.0, (vwap - mid) / mid * 10_000.0)
    return max(0.0, (mid - vwap) / mid * 10_000.0)


def _depth_within_bps(levels: list[tuple[float, float]], *, mid: float, side: str, bps: float) -> float:
    if not mid:
        return 0.0
    if side == "buy":
        limit = mid * (1.0 + bps / 10_000.0)
        return sum(price * qty for price, qty in levels if price <= limit)
    limit = mid * (1.0 - bps / 10_000.0)
    return sum(price * qty for price, qty in levels if price >= limit)


def _floor_cap(value: float, step: float = 25_000.0) -> float:
    return max(0.0, math.floor(value / step) * step)


def _gear1_caps(earned: dict[str, Any]) -> dict[str, float]:
    for gear in earned.get("gear_definitions", []):
        if int(gear.get("gear", -1)) == 1:
            return {str(symbol): float(cap) for symbol, cap in gear.get("symbol_caps_eur", {}).items()}
    return {}


def _calibrate_symbol(symbol: str, *, target_cap_eur: float, eur_to_usdt: float, depth: dict[str, Any]) -> dict[str, Any]:
    bids = _levels(depth, "bids")
    asks = _levels(depth, "asks")
    mid = _mid_price(bids, asks)
    target_notional_usdt = target_cap_eur * eur_to_usdt
    buy_fill = _simulate_market_fill(asks, target_notional_usdt)
    sell_fill = _simulate_market_fill(bids, target_notional_usdt)
    buy_slip = _slippage_bps(buy_fill, mid=mid, side="buy")
    sell_slip = _slippage_bps(sell_fill, mid=mid, side="sell")
    strict_depth_usdt = min(
        _depth_within_bps(asks, mid=mid, side="buy", bps=STRICT_MAX_SLIPPAGE_BPS),
        _depth_within_bps(bids, mid=mid, side="sell", bps=STRICT_MAX_SLIPPAGE_BPS),
    )
    warning_depth_usdt = min(
        _depth_within_bps(asks, mid=mid, side="buy", bps=WARNING_MAX_SLIPPAGE_BPS),
        _depth_within_bps(bids, mid=mid, side="sell", bps=WARNING_MAX_SLIPPAGE_BPS),
    )
    recommended_strict_cap_eur = min(target_cap_eur, _floor_cap(strict_depth_usdt / eur_to_usdt))
    recommended_warning_cap_eur = min(target_cap_eur, _floor_cap(warning_depth_usdt / eur_to_usdt))
    strict_pass = bool(buy_fill["fully_filled"] and sell_fill["fully_filled"] and buy_slip <= STRICT_MAX_SLIPPAGE_BPS and sell_slip <= STRICT_MAX_SLIPPAGE_BPS)
    warning_pass = bool(buy_fill["fully_filled"] and sell_fill["fully_filled"] and buy_slip <= WARNING_MAX_SLIPPAGE_BPS and sell_slip <= WARNING_MAX_SLIPPAGE_BPS)
    return {
        "symbol": symbol,
        "target_gear1_cap_eur": target_cap_eur,
        "target_gear1_notional_usdt": target_notional_usdt,
        "best_bid": bids[0][0] if bids else None,
        "best_ask": asks[0][0] if asks else None,
        "mid": mid,
        "spread_bps": ((asks[0][0] - bids[0][0]) / mid * 10_000.0) if mid and bids and asks else None,
        "buy_fully_filled": buy_fill["fully_filled"],
        "sell_fully_filled": sell_fill["fully_filled"],
        "buy_slippage_bps": buy_slip,
        "sell_slippage_bps": sell_slip,
        "worst_side_slippage_bps": max(buy_slip, sell_slip),
        "strict_25bps_pass": strict_pass,
        "warning_50bps_pass": warning_pass,
        "strict_25bps_two_sided_depth_usdt": strict_depth_usdt,
        "warning_50bps_two_sided_depth_usdt": warning_depth_usdt,
        "recommended_strict_25bps_cap_eur": recommended_strict_cap_eur,
        "recommended_warning_50bps_cap_eur": recommended_warning_cap_eur,
        "recommended_current_cap_eur": recommended_strict_cap_eur if recommended_strict_cap_eur > 0 else recommended_warning_cap_eur,
        "depth_levels_bid": len(bids),
        "depth_levels_ask": len(asks),
        "order_book_last_update_id": depth.get("lastUpdateId"),
    }


def _write_report(config: ExactFillConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# Multi-Symbol Exact Fill and Symbol Cap Calibration Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        "- Research-only. Public order-book depth only. No execution endpoint or order path.",
        f"- Strict slippage gate: `{STRICT_MAX_SLIPPAGE_BPS}` bps per side.",
        f"- Warning slippage gate: `{WARNING_MAX_SLIPPAGE_BPS}` bps per side.",
        "",
        "| Symbol | Gear 1 cap | Worst slippage | Strict pass | Warning pass | Recommended strict cap |",
        "| --- | ---: | ---: | --- | --- | ---: |",
    ]
    for row in summary["symbol_calibrations"]:
        lines.append(
            "| {symbol} | EUR {cap:,.0f} | {slip:.2f} bps | {strict} | {warn} | EUR {rec:,.0f} |".format(
                symbol=row["symbol"],
                cap=float(row["target_gear1_cap_eur"]),
                slip=float(row["worst_side_slippage_bps"] or 0.0),
                strict=str(bool(row["strict_25bps_pass"])).lower(),
                warn=str(bool(row["warning_50bps_pass"])).lower(),
                rec=float(row["recommended_strict_25bps_cap_eur"] or 0.0),
            )
        )
    lines.extend(
        [
            "",
            "## Gate",
            "",
            f"- Exact fill passed for current Gear 1 caps: `{str(summary['gate']['exact_fill_passed_for_current_gear1_caps']).lower()}`",
            f"- May keep Gear 1 at original caps: `{str(summary['gate']['may_keep_gear1_caps_without_reduction']).lower()}`",
            f"- May enable paper/live/order/broker: `false`",
        ]
    )
    (config.output_root / "multi_symbol_exact_fill_symbol_cap_calibration_report.md").write_text("\n".join(lines), encoding="utf-8")


def run(config: ExactFillConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    earned = _read_json(config.earned_gear_root / "earned_capital_gear_ladder_summary.json")
    public_fetch = _read_json(config.public_fetch_root / "multi_symbol_public_fetch_runtime_prototype_summary.json")
    if not earned or not public_fetch:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_earned_gear_or_public_fetch_artifact"],
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_symbol_exact_fill_symbol_cap_calibration_summary.json", summary)
        return summary
    caps = _gear1_caps(earned)
    if set(caps) != set(SYMBOLS):
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_gear1_symbol_caps"],
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_symbol_exact_fill_symbol_cap_calibration_summary.json", summary)
        return summary
    eur = _fetch_eur_to_usdt()
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    fetcher = config.depth_fetcher or _public_depth
    for symbol in SYMBOLS:
        try:
            depth = fetcher(symbol)
            rows.append(_calibrate_symbol(symbol, target_cap_eur=caps[symbol], eur_to_usdt=float(eur["eur_to_usdt"]), depth=depth))
            time.sleep(0.05)
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": symbol, "error": f"{type(exc).__name__}: {exc}"})
    all_strict = len(rows) == len(SYMBOLS) and all(bool(row["strict_25bps_pass"]) for row in rows)
    all_warning = len(rows) == len(SYMBOLS) and all(bool(row["warning_50bps_pass"]) for row in rows)
    any_recommendation_positive = any(float(row.get("recommended_current_cap_eur") or 0.0) > 0 for row in rows)
    if all_strict and not errors:
        classification = PASSED
        reasons = ["current_gear1_symbol_caps_pass_exact_fill_strict_25bps"]
    elif all_warning and not errors:
        classification = WARNING
        reasons = ["current_gear1_symbol_caps_pass_50bps_but_not_strict_25bps"]
    elif any_recommendation_positive and not errors:
        classification = WARNING
        reasons = ["current_gear1_caps_need_symbol_cap_reduction_before_exact_fill_gate"]
    else:
        classification = FAILED
        reasons = ["exact_fill_depth_insufficient_or_fetch_errors"]
        if errors:
            reasons.append("public_depth_fetch_errors_present")
    recommended_caps = {row["symbol"]: row["recommended_current_cap_eur"] for row in rows}
    strict_caps = {row["symbol"]: row["recommended_strict_25bps_cap_eur"] for row in rows}
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_earned_gear_summary": str(config.earned_gear_root / "earned_capital_gear_ladder_summary.json"),
        "source_public_fetch_summary": str(config.public_fetch_root / "multi_symbol_public_fetch_runtime_prototype_summary.json"),
        "public_market_data_source": BINANCE_BASE_URL,
        "public_unsigned_order_book_depth_only": True,
        "eur_to_usdt_proxy": eur,
        "strict_max_slippage_bps": STRICT_MAX_SLIPPAGE_BPS,
        "warning_max_slippage_bps": WARNING_MAX_SLIPPAGE_BPS,
        "gear1_target_symbol_caps_eur": caps,
        "recommended_symbol_caps_eur": recommended_caps,
        "recommended_strict_25bps_symbol_caps_eur": strict_caps,
        "symbol_calibrations": rows,
        "errors": errors,
        "gate": {
            "exact_fill_passed_for_current_gear1_caps": all_strict,
            "may_keep_gear1_caps_without_reduction": all_strict,
            "may_use_recommended_reduced_caps_for_next_research_court": classification in {PASSED, WARNING},
            "may_unlock_1m_now": False,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "paper_validation_ready": False,
            "next_required_court": "MULTI_SYMBOL_REDUCED_CAP_GEAR_LADDER_RESTATEMENT_COURT_RESEARCH_ONLY" if not all_strict else "SIX_MONTH_MULTI_SYMBOL_FORWARD_EVIDENCE_COURT_RESEARCH_ONLY",
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_symbol_exact_fill_symbol_cap_calibration_summary.json", summary)
    _write_csv(config.output_root / "symbol_exact_fill_calibration_rows.csv", rows)
    _write_report(config, summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run exact fill and symbol-cap calibration court from public Binance order-book depth.")
    parser.add_argument("--earned-gear-root", default="structural_compounding_lab/output/earned_capital_gear_ladder_court_001")
    parser.add_argument("--public-fetch-root", default="structural_compounding_lab/output/multi_symbol_public_fetch_runtime_prototype_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        ExactFillConfig(
            project_root=root,
            package_root=package_root(),
            earned_gear_root=resolve_project_path(args.earned_gear_root),
            public_fetch_root=resolve_project_path(args.public_fetch_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(_round_payload(summary), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
