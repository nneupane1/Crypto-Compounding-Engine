from __future__ import annotations

import argparse
import csv
import json
import math
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path
from structural_compounding_lab.diagnostics.multi_symbol_exact_fill_symbol_cap_calibration_court import (
    BINANCE_BASE_URL,
    STRICT_MAX_SLIPPAGE_BPS,
    WARNING_MAX_SLIPPAGE_BPS,
    _calibrate_symbol,
    _fetch_eur_to_usdt,
    _public_depth,
)


COURT_NAME = "MULTI_SYMBOL_BTC_EXACT_FILL_CAP_CALIBRATION_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_symbol_btc_exact_fill_cap_calibration_court_001"

PASSED = "MULTI_SYMBOL_BTC_EXACT_FILL_CAP_CALIBRATION_PASSED_RESEARCH_ONLY"
WARNING = "MULTI_SYMBOL_BTC_EXACT_FILL_CAP_CALIBRATION_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_SYMBOL_BTC_EXACT_FILL_CAP_CALIBRATION_FAILED_RESEARCH_ONLY"
BLOCKED = "MULTI_SYMBOL_BTC_EXACT_FILL_CAP_CALIBRATION_BLOCKED_RESEARCH_ONLY"

BTC_SYMBOL = "BTCUSDT"
CURRENT_ACTIVE_CAP_EUR = 500_000.0
FUTURE_DEEP_CAPACITY_CEILING_EUR = 2_000_000.0
BTC_CAP_CANDIDATES_EUR: tuple[float, ...] = (
    250_000.0,
    500_000.0,
    1_000_000.0,
    2_000_000.0,
    5_000_000.0,
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
class BTCExactFillCapConfig:
    project_root: Path
    package_root: Path
    eight_symbol_exact_fill_root: Path
    btc_inclusion_root: Path
    output_root: Path
    depth_fetcher: Callable[[str], dict[str, Any]] | None = None
    sleep_seconds: float = 0.05


def default_config() -> BTCExactFillCapConfig:
    pkg = package_root()
    return BTCExactFillCapConfig(
        project_root=project_root(),
        package_root=pkg,
        eight_symbol_exact_fill_root=pkg / "output" / "multi_symbol_exact_fill_symbol_cap_calibration_court_001",
        btc_inclusion_root=pkg / "output" / "multi_asset_earned_parallel_slot_btc_inclusion_court_001",
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


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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


def _strict_observed_cap_eur(rows: list[dict[str, Any]]) -> float:
    caps = [float(row.get("recommended_strict_25bps_cap_eur") or 0.0) for row in rows]
    return max(caps) if caps else 0.0


def _write_report(config: BTCExactFillCapConfig, summary: dict[str, Any]) -> None:
    lines = [
        "# BTCUSDT Exact-Fill Cap Calibration Court 001",
        "",
        f"- Final classification: `{summary['final_classification']}`",
        "- Research-only. Public Binance order-book depth only.",
        "- No account, signed, private, order, broker, paper, live, or real-money endpoint is used.",
        f"- Strict slippage gate: `{STRICT_MAX_SLIPPAGE_BPS}` bps two-sided.",
        f"- Warning slippage gate: `{WARNING_MAX_SLIPPAGE_BPS}` bps two-sided.",
        "",
        "## Result",
        "",
        f"- Observed strict BTC cap: `EUR {float(summary['btc_observed_strict_25bps_cap_eur']):,.0f}`",
        f"- Frozen BTC cap for active nine-symbol artifact: `EUR {float(summary['recommended_btc_cap_eur']):,.0f}`",
        f"- Current active cap covered: `{str(summary['gate']['btc_cap_covers_current_active_cap']).lower()}`",
        f"- Future deep-capacity ceiling covered: `{str(summary['gate']['btc_cap_covers_future_deep_capacity_ceiling']).lower()}`",
        "",
        "## Candidate checks",
        "",
        "| Candidate cap | Worst slippage | Strict pass | Warning pass | Strict recommended cap |",
        "| ---: | ---: | --- | --- | ---: |",
    ]
    for row in summary.get("btc_candidate_cap_checks", []):
        lines.append(
            "| EUR {cap:,.0f} | {slip:.4f} bps | {strict} | {warning} | EUR {rec:,.0f} |".format(
                cap=float(row["target_gear1_cap_eur"]),
                slip=float(row["worst_side_slippage_bps"] or 0.0),
                strict=str(bool(row["strict_25bps_pass"])).lower(),
                warning=str(bool(row["warning_50bps_pass"])).lower(),
                rec=float(row["recommended_strict_25bps_cap_eur"] or 0.0),
            )
        )
    lines.extend(
        [
            "",
            "## Nine-symbol caps",
            "",
            "| Symbol | Cap |",
            "| --- | ---: |",
        ]
    )
    for symbol, cap in sorted(summary.get("nine_symbol_recommended_symbol_caps_eur", {}).items()):
        lines.append(f"| {symbol} | EUR {float(cap):,.0f} |")
    lines.extend(
        [
            "",
            "## Gate",
            "",
            f"- May freeze BTC cap into nine-symbol research artifact: `{str(summary['gate']['may_freeze_btc_cap_into_9_symbol_research_artifact']).lower()}`",
            "- May enable paper/live/order/broker: `false`",
            "- `paper_validation_ready=false`",
        ]
    )
    (config.output_root / "multi_symbol_btc_exact_fill_cap_calibration_report.md").write_text("\n".join(lines), encoding="utf-8")


def _blocked(config: BTCExactFillCapConfig, reasons: list[str], missing: list[str]) -> dict[str, Any]:
    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": BLOCKED,
        "classification_reasons": reasons,
        "missing_artifacts": missing,
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_symbol_btc_exact_fill_cap_calibration_summary.json", summary)
    return summary


def run(config: BTCExactFillCapConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)

    eight_summary_path = config.eight_symbol_exact_fill_root / "multi_symbol_exact_fill_symbol_cap_calibration_summary.json"
    btc_inclusion_path = config.btc_inclusion_root / "multi_asset_earned_parallel_slot_btc_inclusion_summary.json"
    missing = [str(path) for path in (eight_summary_path, btc_inclusion_path) if not path.exists()]
    if missing:
        return _blocked(config, ["missing_required_source_artifacts"], missing)

    eight = _read_json(eight_summary_path)
    btc_inclusion = _read_json(btc_inclusion_path)
    eight_caps = {str(symbol): float(cap) for symbol, cap in (eight.get("recommended_symbol_caps_eur") or {}).items()}
    if len(eight_caps) != 8 or BTC_SYMBOL in eight_caps:
        return _blocked(config, ["eight_symbol_cap_artifact_unexpected_shape"], [])
    if btc_inclusion.get("final_classification") != "MULTI_ASSET_9_SYMBOL_BTC_INCLUSION_FREEZE_CANDIDATE_RESEARCH_ONLY":
        return _blocked(config, ["btc_inclusion_court_not_passed"], [])

    eur = _fetch_eur_to_usdt()
    fetcher = config.depth_fetcher or _public_depth
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for cap in BTC_CAP_CANDIDATES_EUR:
        try:
            depth = fetcher(BTC_SYMBOL)
            row = _calibrate_symbol(BTC_SYMBOL, target_cap_eur=cap, eur_to_usdt=float(eur["eur_to_usdt"]), depth=depth)
            row["cap_candidate_role"] = "btc_exact_fill_cap_scan"
            rows.append(row)
            if config.sleep_seconds > 0:
                time.sleep(config.sleep_seconds)
        except Exception as exc:  # noqa: BLE001
            errors.append({"symbol": BTC_SYMBOL, "cap_eur": cap, "error": f"{type(exc).__name__}: {exc}"})

    observed_strict = _strict_observed_cap_eur(rows)
    recommended_btc_cap = min(FUTURE_DEEP_CAPACITY_CEILING_EUR, observed_strict)
    recommended_btc_cap = math.floor(recommended_btc_cap / 25_000.0) * 25_000.0
    current_cap_covered = recommended_btc_cap >= CURRENT_ACTIVE_CAP_EUR
    future_ceiling_covered = recommended_btc_cap >= FUTURE_DEEP_CAPACITY_CEILING_EUR
    candidate_2m = next((row for row in rows if float(row["target_gear1_cap_eur"]) == FUTURE_DEEP_CAPACITY_CEILING_EUR), {})
    strict_2m_pass = bool(candidate_2m.get("strict_25bps_pass"))

    if errors:
        classification = FAILED
        reasons = ["public_btc_depth_fetch_errors_present"]
    elif strict_2m_pass and future_ceiling_covered:
        classification = PASSED
        reasons = ["btc_depth_supports_future_deep_capacity_ceiling_under_strict_25bps"]
    elif current_cap_covered:
        classification = WARNING
        reasons = ["btc_depth_supports_current_active_cap_but_not_future_deep_capacity_ceiling"]
    else:
        classification = FAILED
        reasons = ["btc_depth_does_not_support_current_active_cap_under_strict_25bps"]

    nine_caps = dict(eight_caps)
    if classification in {PASSED, WARNING} and recommended_btc_cap > 0:
        nine_caps[BTC_SYMBOL] = recommended_btc_cap

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_eight_symbol_exact_fill_summary": str(eight_summary_path),
        "source_btc_inclusion_summary": str(btc_inclusion_path),
        "public_market_data_source": BINANCE_BASE_URL,
        "public_unsigned_order_book_depth_only": True,
        "eur_to_usdt_proxy": eur,
        "strict_max_slippage_bps": STRICT_MAX_SLIPPAGE_BPS,
        "warning_max_slippage_bps": WARNING_MAX_SLIPPAGE_BPS,
        "current_active_cap_eur": CURRENT_ACTIVE_CAP_EUR,
        "future_deep_capacity_ceiling_eur": FUTURE_DEEP_CAPACITY_CEILING_EUR,
        "btc_cap_candidates_eur": list(BTC_CAP_CANDIDATES_EUR),
        "btc_observed_strict_25bps_cap_eur": observed_strict,
        "recommended_btc_cap_eur": recommended_btc_cap,
        "eight_symbol_recommended_symbol_caps_eur": eight_caps,
        "nine_symbol_recommended_symbol_caps_eur": nine_caps,
        "recommended_symbol_caps_eur": nine_caps,
        "btc_candidate_cap_checks": rows,
        "errors": errors,
        "compatibility_artifact": {
            "writes_multi_symbol_reduced_cap_gear_ladder_restatement_summary_json": classification in {PASSED, WARNING},
            "compatibility_reason": "lets active runtime read a 9-symbol recommended_symbol_caps_eur map without mutating the old 8-symbol output folder",
        },
        "gate": {
            "btc_exact_fill_cap_passed": classification == PASSED,
            "btc_cap_covers_current_active_cap": current_cap_covered,
            "btc_cap_covers_future_deep_capacity_ceiling": future_ceiling_covered,
            "may_freeze_btc_cap_into_9_symbol_research_artifact": classification in {PASSED, WARNING},
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "paper_validation_ready": False,
            "next_required_court": "NINE_SYMBOL_FORWARD_EVIDENCE_CONTINUITY_RESEARCH_ONLY",
        },
        **SAFETY_FLAGS,
    }

    _write_json(config.output_root / "multi_symbol_btc_exact_fill_cap_calibration_summary.json", summary)
    _write_csv(config.output_root / "btc_exact_fill_cap_candidate_rows.csv", rows)
    _write_report(config, summary)

    if classification in {PASSED, WARNING}:
        compatibility = {
            "court_name": "NINE_SYMBOL_BTC_CAP_COMPATIBILITY_ARTIFACT_RESEARCH_ONLY",
            "created_at_utc": summary["created_at_utc"],
            "final_classification": "NINE_SYMBOL_BTC_EXACT_FILL_CAP_FREEZE_READY_RESEARCH_ONLY",
            "classification_reasons": reasons,
            "source_btc_exact_fill_summary": str(config.output_root / "multi_symbol_btc_exact_fill_cap_calibration_summary.json"),
            "source_eight_symbol_exact_fill_summary": str(eight_summary_path),
            "active_cap_eur": CURRENT_ACTIVE_CAP_EUR,
            "recommended_symbol_caps_eur": nine_caps,
            "btc_recommended_cap_eur": recommended_btc_cap,
            "gate": {
                "may_treat_9_symbol_caps_as_fill_calibrated_research_caps": classification == PASSED,
                "may_enable_paper_trading": False,
                "may_enable_live_trading": False,
                "may_create_order_or_broker_path": False,
                "paper_validation_ready": False,
            },
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json", compatibility)
        _write_json(config.output_root / "nine_symbol_recommended_symbol_caps_manifest.json", compatibility)

    return _round_payload(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--eight-symbol-exact-fill-root", default="structural_compounding_lab/output/multi_symbol_exact_fill_symbol_cap_calibration_court_001")
    parser.add_argument("--btc-inclusion-root", default="structural_compounding_lab/output/multi_asset_earned_parallel_slot_btc_inclusion_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        BTCExactFillCapConfig(
            project_root=root,
            package_root=package_root(),
            eight_symbol_exact_fill_root=resolve_project_path(args.eight_symbol_exact_fill_root),
            btc_inclusion_root=resolve_project_path(args.btc_inclusion_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
