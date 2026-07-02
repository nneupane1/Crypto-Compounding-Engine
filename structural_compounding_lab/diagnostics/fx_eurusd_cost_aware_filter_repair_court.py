from __future__ import annotations

import argparse
import csv
import json
import math
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path  # noqa: E402


COURT_NAME = "FX_EURUSD_COST_AWARE_FILTER_REPAIR_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "fx_eurusd_cost_aware_filter_repair_court_001"

PASSED = "FX_EURUSD_COST_AWARE_FILTER_REPAIR_PASSED_RESEARCH_ONLY"
WARNING = "FX_EURUSD_COST_AWARE_FILTER_REPAIR_WARNING_RESEARCH_ONLY"
FAILED = "FX_EURUSD_COST_AWARE_FILTER_REPAIR_FAILED_RESEARCH_ONLY"
BLOCKED = "FX_EURUSD_COST_AWARE_FILTER_REPAIR_BLOCKED_RESEARCH_ONLY"

START_CAPITAL_EUR = 25_000.0
ACTIVE_CAP_EUR = 250_000.0
RISK_PER_TRADE = 0.01
CONSERVATIVE_TAX_RATE = 0.47475
CAPITAL_INCOME_STYLE_TAX_RATE = 0.26375
EXTRA_COMMISSION_BPS = 1.0

SPREAD_R_GATES: tuple[float, ...] = (0.05, 0.10, 0.15, 0.20)
MIN_STOP_PIPS: tuple[float, ...] = (3.0, 5.0, 8.0, 10.0)
STRESS_EXTRA_COMMISSION_BPS: tuple[float, ...] = (0.0, 0.5, 1.0, 3.0, 5.0)

SOURCE_FX_CSV = "data_storage/FX/EURUSD/1m/EURUSD_1m_2003-05-04_to_2026-06-29.csv"
REPLAY_ROOT = "structural_compounding_lab/output/fx_eurusd_pre_holdout_research_replay_001"

SAFETY_FLAGS: dict[str, Any] = {
    "research_only": True,
    "tax_advice": False,
    "requires_steuerberater_review": True,
    "paper_validation_ready": False,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "paper_trade_created": False,
    "live_trade_created": False,
    "order_path_created": False,
    "broker_path_created": False,
    "private_endpoint_used": False,
    "signed_endpoint_used": False,
    "strategy_logic_changed": False,
    "thresholds_tuned_in_runtime": False,
}


@dataclass(frozen=True)
class RepairCourtConfig:
    project_root: Path
    package_root: Path
    replay_root: Path
    source_fx_csv: Path
    output_root: Path


def default_config() -> RepairCourtConfig:
    root = project_root()
    pkg = package_root()
    return RepairCourtConfig(
        project_root=root,
        package_root=pkg,
        replay_root=resolve_project_path(REPLAY_ROOT),
        source_fx_csv=root / SOURCE_FX_CSV,
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
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(_round_payload(payload), indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    keys = sorted({key for row in rows for key in row})
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=keys)
        writer.writeheader()
        writer.writerows([{key: _csv_value(row.get(key)) for key in keys} for row in rows])


def _csv_value(value: Any) -> Any:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, float):
        return "" if math.isnan(value) or math.isinf(value) else round(value, 10)
    if value is None:
        return ""
    return value


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _timestamp_key(value: str) -> str:
    return str(value).replace("T", " ")[:16]


def _load_trade_rows(path: Path, *, period: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            entry = float(row.get("entry_price") or 0.0)
            stop = float(row.get("initial_stop") or row.get("trail_stop") or 0.0)
            risk_per_unit = abs(entry - stop)
            rows.append(
                {
                    "period": period,
                    "trade_id": row.get("trade_id", ""),
                    "symbol": row.get("symbol", "EURUSD"),
                    "side": row.get("side", ""),
                    "entry_time": row.get("entry_time", ""),
                    "exit_time": row.get("exit_time", ""),
                    "entry_key": _timestamp_key(row.get("entry_time", "")),
                    "exit_key": _timestamp_key(row.get("exit_time", "")),
                    "exit_year": int(str(row.get("exit_time", "0000"))[:4]),
                    "entry_price": entry,
                    "exit_price": float(row.get("exit_price") or 0.0),
                    "initial_stop": stop,
                    "risk_per_unit": risk_per_unit,
                    "stop_distance_pips": risk_per_unit * 10_000.0,
                    "gross_r": float(row.get("r_multiple") or 0.0),
                    "entry_reason": row.get("entry_reason", ""),
                    "exit_reason": row.get("exit_reason", ""),
                    "setup_class": row.get("setup_class", ""),
                    "entry_score": float(row.get("entry_score") or 0.0),
                    "personality_label": row.get("personality_label", ""),
                    "pullback_type": row.get("pullback_type", ""),
                    "runner_label": row.get("runner_label", ""),
                }
            )
    return sorted(rows, key=lambda item: (str(item["exit_time"]), str(item["trade_id"])))


def _required_spread_keys(groups: list[list[dict[str, Any]]]) -> set[str]:
    keys: set[str] = set()
    for rows in groups:
        for row in rows:
            if row["entry_key"]:
                keys.add(row["entry_key"])
            if row["exit_key"]:
                keys.add(row["exit_key"])
    return keys


def _load_spread_lookup(source_fx_csv: Path, required_keys: set[str], cache_path: Path) -> dict[str, Any]:
    if cache_path.exists():
        cached = _read_json(cache_path)
        if set(cached.get("spread_by_key", {})).issuperset(required_keys):
            return cached

    started = time.time()
    spread_by_key: dict[str, float] = {}
    sampled: list[float] = []
    with source_fx_csv.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            key = _timestamp_key(row.get("timestamp", ""))
            try:
                spread = float(row.get("spread_close_bps") or "")
            except Exception:
                continue
            if len(sampled) < 750_000:
                sampled.append(spread)
            if key in required_keys:
                spread_by_key[key] = spread
            if len(spread_by_key) >= len(required_keys):
                break
    fallback = _median(sampled)
    payload = {
        "created_at": _now(),
        "source_fx_csv": str(source_fx_csv),
        "required_timestamp_keys": len(required_keys),
        "matched_timestamp_keys": len(spread_by_key),
        "fallback_spread_bps": fallback,
        "scan_seconds": time.time() - started,
        "spread_by_key": spread_by_key,
        **SAFETY_FLAGS,
    }
    _write_json(cache_path, payload)
    return payload


def _median(values: list[float]) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2.0


def _attach_spread_cost(rows: list[dict[str, Any]], spread_payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    lookup = {str(key): float(value) for key, value in (spread_payload.get("spread_by_key") or {}).items()}
    fallback = float(spread_payload.get("fallback_spread_bps") or 0.0)
    out: list[dict[str, Any]] = []
    missing = 0
    roundtrip_spreads: list[float] = []
    for row in rows:
        entry_spread = lookup.get(str(row["entry_key"]))
        exit_spread = lookup.get(str(row["exit_key"]))
        if entry_spread is None:
            entry_spread = fallback
            missing += 1
        if exit_spread is None:
            exit_spread = fallback
            missing += 1
        spread_roundtrip_bps = max(0.0, 0.5 * entry_spread + 0.5 * exit_spread)
        spread_r = (
            (float(row["entry_price"]) * (spread_roundtrip_bps / 10_000.0)) / max(float(row["risk_per_unit"]), 1e-12)
            if float(row["risk_per_unit"]) > 0
            else float("inf")
        )
        out.append(
            {
                **row,
                "entry_spread_bps": entry_spread,
                "exit_spread_bps": exit_spread,
                "spread_roundtrip_bps": spread_roundtrip_bps,
                "spread_cost_r": spread_r,
            }
        )
        roundtrip_spreads.append(spread_roundtrip_bps)
    stats = {
        "rows": len(rows),
        "missing_spread_fills": missing,
        "avg_roundtrip_spread_bps": sum(roundtrip_spreads) / len(roundtrip_spreads) if roundtrip_spreads else 0.0,
        "median_roundtrip_spread_bps": _median(roundtrip_spreads),
        "p95_roundtrip_spread_bps": _quantile(roundtrip_spreads, 0.95),
    }
    return out, stats


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    index = int(round((len(values) - 1) * q))
    return values[max(0, min(index, len(values) - 1))]


def _max_drawdown(curve: list[float]) -> float:
    peak = curve[0] if curve else 0.0
    worst = 0.0
    for value in curve:
        peak = max(peak, value)
        if peak > 0:
            worst = max(worst, (peak - value) / peak)
    return worst


def _profit_factor(values: list[float]) -> float:
    wins = sum(value for value in values if value > 0.0)
    losses = abs(sum(value for value in values if value < 0.0))
    return wins / losses if losses else (1.0 if wins > 0 else 0.0)


def _filter_rows(rows: list[dict[str, Any]], *, spread_r_gate: float, min_stop_pips: float) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    rejected_spread = 0
    rejected_stop = 0
    rejected_zero = 0
    for row in rows:
        if float(row["risk_per_unit"]) <= 0:
            rejected_zero += 1
            continue
        if float(row["stop_distance_pips"]) < min_stop_pips:
            rejected_stop += 1
            continue
        if float(row["spread_cost_r"]) > spread_r_gate:
            rejected_spread += 1
            continue
        kept.append(row)
    return kept, {
        "source_trades": len(rows),
        "kept_trades": len(kept),
        "rejected_zero_or_invalid_stop": rejected_zero,
        "rejected_min_stop_pips": rejected_stop,
        "rejected_spread_cost_r_gate": rejected_spread,
        "kept_ratio": len(kept) / len(rows) if rows else 0.0,
    }


def _replay_cap_cost_tax(
    rows: list[dict[str, Any]],
    *,
    active_cap: float,
    extra_commission_bps: float,
    tax_rate: float,
) -> dict[str, Any]:
    active = START_CAPITAL_EUR
    vault = 0.0
    ledger: list[dict[str, Any]] = []
    net_r_values: list[float] = []
    active_curve = [active]
    stopped = False
    stopped_at = ""
    for index, row in enumerate(rows, start=1):
        risk_base = max(0.0, min(active, active_cap))
        if risk_base <= 0.0:
            stopped = True
            stopped_at = str(row["exit_time"])
            break
        total_cost_bps = float(row["spread_roundtrip_bps"]) + extra_commission_bps
        extra_commission_r = (
            (float(row["entry_price"]) * (extra_commission_bps / 10_000.0)) / max(float(row["risk_per_unit"]), 1e-12)
            if float(row["risk_per_unit"]) > 0
            else 0.0
        )
        total_cost_r = float(row["spread_cost_r"]) + extra_commission_r
        net_r = float(row["gross_r"]) - total_cost_r
        risk_eur = risk_base * RISK_PER_TRADE
        pnl = risk_eur * net_r
        active_before = active
        vault_before = vault
        if active + pnl < 0.0:
            pnl = -active
            active = 0.0
            stopped = True
            stopped_at = str(row["exit_time"])
        else:
            active += pnl
        if active > active_cap:
            vault += active - active_cap
            active = active_cap
        net_r_values.append(net_r)
        active_curve.append(active)
        ledger.append(
            {
                "trade_number": index,
                "trade_id": row["trade_id"],
                "period": row["period"],
                "side": row["side"],
                "entry_time": row["entry_time"],
                "exit_time": row["exit_time"],
                "stop_distance_pips": row["stop_distance_pips"],
                "gross_r": row["gross_r"],
                "spread_cost_r": row["spread_cost_r"],
                "spread_roundtrip_bps": row["spread_roundtrip_bps"],
                "extra_commission_bps": extra_commission_bps,
                "extra_commission_r": extra_commission_r,
                "total_cost_bps": total_cost_bps,
                "total_cost_r": total_cost_r,
                "net_r_after_cost": net_r,
                "risk_eur": risk_eur,
                "net_pnl_before_tax": pnl,
                "active_before_trade": active_before,
                "vault_before_trade": vault_before,
                "active_after_trade_before_year_tax": active,
                "vault_after_trade_before_year_tax": vault,
                "total_after_trade_before_year_tax": active + vault,
                "entry_reason": row.get("entry_reason", ""),
                "exit_reason": row.get("exit_reason", ""),
                "setup_class": row.get("setup_class", ""),
                "personality_label": row.get("personality_label", ""),
            }
        )
        if stopped:
            break

    active = START_CAPITAL_EUR
    vault = 0.0
    tax_total = 0.0
    post_tax_curve = [active + vault]
    yearly_rows: list[dict[str, Any]] = []
    for year in sorted({int(str(row["exit_time"])[:4]) for row in ledger}):
        bucket = [row for row in ledger if int(str(row["exit_time"])[:4]) == year]
        year_pnl = 0.0
        for item in bucket:
            pnl = float(item["net_pnl_before_tax"])
            if active + pnl < 0.0:
                pnl = -active
                active = 0.0
            else:
                active += pnl
            if active > active_cap:
                vault += active - active_cap
                active = active_cap
            year_pnl += pnl
            post_tax_curve.append(active + vault)
        tax = max(year_pnl, 0.0) * tax_rate
        from_vault = min(vault, tax)
        vault -= from_vault
        remainder = tax - from_vault
        from_active = 0.0
        if remainder > 0:
            from_active = min(active, remainder)
            active = max(0.0, active - remainder)
        tax_total += tax
        yearly_rows.append(
            {
                "year": year,
                "trades": len(bucket),
                "realized_net_pnl_before_tax": year_pnl,
                "tax_reserved_or_withdrawn": tax,
                "tax_paid_from_vault": from_vault,
                "tax_paid_from_active": from_active,
                "ending_active_capital_after_tax": active,
                "ending_profit_vault_after_tax": vault,
                "ending_total_equity_after_tax": active + vault,
            }
        )
        post_tax_curve.append(active + vault)

    return {
        "starting_equity": START_CAPITAL_EUR,
        "active_cap_eur": active_cap,
        "extra_commission_bps": extra_commission_bps,
        "tax_rate": tax_rate,
        "ending_total_equity_after_tax": active + vault,
        "ending_active_capital_after_tax": active,
        "ending_profit_vault_after_tax": vault,
        "net_gain_after_tax": active + vault - START_CAPITAL_EUR,
        "return_multiple_after_tax": (active + vault) / START_CAPITAL_EUR,
        "total_tax_reserved_or_withdrawn": tax_total,
        "trades_available_after_filter": len(rows),
        "trades_processed": len(ledger),
        "account_ruined_or_stopped": stopped,
        "ruined_or_stopped_at": stopped_at,
        "sum_net_r_after_cost": sum(net_r_values),
        "profit_factor_after_cost": _profit_factor(net_r_values),
        "win_rate_after_cost": sum(1 for value in net_r_values if value > 0.0) / len(net_r_values) if net_r_values else 0.0,
        "max_drawdown_total_after_tax": _max_drawdown(post_tax_curve),
        "max_drawdown_active_pre_tax": _max_drawdown(active_curve),
        "yearly_rows": yearly_rows,
        "trade_rows": ledger,
    }


def _scenario_summary(replay: dict[str, Any], filter_summary: dict[str, Any], *, spread_r_gate: float, min_stop_pips: float) -> dict[str, Any]:
    return {
        "spread_r_gate": spread_r_gate,
        "min_stop_pips": min_stop_pips,
        **filter_summary,
        **{key: value for key, value in replay.items() if key not in {"yearly_rows", "trade_rows"}},
    }


def _score_candidate(row: dict[str, Any]) -> tuple[float, float, float, float]:
    return (
        0.0 if row.get("account_ruined_or_stopped") else 1.0,
        float(row.get("ending_total_equity_after_tax") or 0.0),
        -float(row.get("max_drawdown_total_after_tax") or 0.0),
        float(row.get("trades_processed") or 0.0),
    )


def _validation_summary_for_candidate(
    validation_groups: list[dict[str, Any]],
    *,
    spread_r_gate: float,
    min_stop_pips: float,
    extra_commission_bps: float,
    tax_rate: float,
) -> list[dict[str, Any]]:
    summaries: list[dict[str, Any]] = []
    for group in validation_groups:
        filtered, filter_summary = _filter_rows(group["rows"], spread_r_gate=spread_r_gate, min_stop_pips=min_stop_pips)
        replay = _replay_cap_cost_tax(
            filtered,
            active_cap=ACTIVE_CAP_EUR,
            extra_commission_bps=extra_commission_bps,
            tax_rate=tax_rate,
        )
        summaries.append(
            {
                "window_id": group["window_id"],
                "source_quality_status": "clean_window_replayed",
                **_scenario_summary(replay, filter_summary, spread_r_gate=spread_r_gate, min_stop_pips=min_stop_pips),
            }
        )
    return summaries


def run(config: RepairCourtConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)

    research_path = config.replay_root / "raw_engine" / "trades.csv"
    if not research_path.exists() or not config.source_fx_csv.exists():
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "blocked_reason": "missing_research_trades_or_fx_source_csv",
            "research_trades": str(research_path),
            "source_fx_csv": str(config.source_fx_csv),
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "fx_eurusd_cost_aware_filter_repair_summary.json", summary)
        return summary

    raw_summary = _read_json(config.replay_root / "raw_engine" / "summary.json")
    research_rows = _load_trade_rows(research_path, period="research_pre_holdout")
    validation_groups: list[dict[str, Any]] = []
    blocked_validation_windows: list[dict[str, Any]] = []
    for window_dir in sorted((config.replay_root / "validation_windows").glob("virgin_6m_*")):
        trades_path = window_dir / "raw_engine" / "trades.csv"
        source_manifest = _read_json(window_dir / "validation_source_manifest.json")
        if trades_path.exists():
            validation_groups.append({"window_id": window_dir.name, "rows": _load_trade_rows(trades_path, period=window_dir.name)})
        else:
            blocked_validation_windows.append(
                {
                    "window_id": window_dir.name,
                    "source_quality_status": "blocked_or_not_run",
                    "quality": source_manifest.get("quality", {}),
                    "validation_executed": False,
                }
            )

    required_keys = _required_spread_keys([research_rows, *[item["rows"] for item in validation_groups]])
    spread_payload = _load_spread_lookup(config.source_fx_csv, required_keys, config.output_root / "fx_spread_lookup_cache.json")
    research_rows, research_spread_stats = _attach_spread_cost(research_rows, spread_payload)
    for group in validation_groups:
        group["rows"], group["spread_stats"] = _attach_spread_cost(group["rows"], spread_payload)

    scenario_rows: list[dict[str, Any]] = []
    scenario_ledgers: dict[str, dict[str, Any]] = {}
    for spread_gate in SPREAD_R_GATES:
        for min_stop_pips in MIN_STOP_PIPS:
            filtered, filter_summary = _filter_rows(research_rows, spread_r_gate=spread_gate, min_stop_pips=min_stop_pips)
            replay = _replay_cap_cost_tax(
                filtered,
                active_cap=ACTIVE_CAP_EUR,
                extra_commission_bps=EXTRA_COMMISSION_BPS,
                tax_rate=CONSERVATIVE_TAX_RATE,
            )
            scenario = _scenario_summary(replay, filter_summary, spread_r_gate=spread_gate, min_stop_pips=min_stop_pips)
            scenario["scenario_id"] = f"spreadR_{spread_gate:.2f}_minStop_{min_stop_pips:.0f}pips"
            scenario_rows.append(scenario)
            scenario_ledgers[scenario["scenario_id"]] = replay

    viable = [
        row
        for row in scenario_rows
        if not row.get("account_ruined_or_stopped")
        and float(row.get("ending_total_equity_after_tax") or 0.0) > START_CAPITAL_EUR
        and int(row.get("trades_processed") or 0) >= 100
    ]
    best = max(viable or scenario_rows, key=_score_candidate) if scenario_rows else {}
    best_id = str(best.get("scenario_id", ""))
    best_replay = scenario_ledgers.get(best_id, {})

    validation_results = _validation_summary_for_candidate(
        validation_groups,
        spread_r_gate=float(best.get("spread_r_gate") or 0.0),
        min_stop_pips=float(best.get("min_stop_pips") or 0.0),
        extra_commission_bps=EXTRA_COMMISSION_BPS,
        tax_rate=CONSERVATIVE_TAX_RATE,
    ) if best else []
    validation_profitable = [
        item
        for item in validation_results
        if not item.get("account_ruined_or_stopped")
        and float(item.get("ending_total_equity_after_tax") or 0.0) > START_CAPITAL_EUR
    ]

    stress_rows: list[dict[str, Any]] = []
    if best:
        best_filtered, best_filter_summary = _filter_rows(
            research_rows,
            spread_r_gate=float(best["spread_r_gate"]),
            min_stop_pips=float(best["min_stop_pips"]),
        )
        for extra in STRESS_EXTRA_COMMISSION_BPS:
            for tax_name, tax_rate in {
                "project_conservative_47_475pct": CONSERVATIVE_TAX_RATE,
                "capital_income_style_26_375pct": CAPITAL_INCOME_STYLE_TAX_RATE,
            }.items():
                stress = _replay_cap_cost_tax(
                    best_filtered,
                    active_cap=ACTIVE_CAP_EUR,
                    extra_commission_bps=extra,
                    tax_rate=tax_rate,
                )
                stress_rows.append(
                    {
                        "tax_scenario": tax_name,
                        **_scenario_summary(
                            stress,
                            best_filter_summary,
                            spread_r_gate=float(best["spread_r_gate"]),
                            min_stop_pips=float(best["min_stop_pips"]),
                        ),
                    }
                )

    if not viable:
        classification = FAILED
        reasons = ["no_research_filter_candidate_survived_cost_tax_profit_gate"]
    elif len(validation_profitable) == len(validation_groups) and not blocked_validation_windows:
        classification = PASSED
        reasons = ["research_candidate_and_all_virgin_windows_profitable_after_fx_cost_filters"]
    else:
        classification = WARNING
        reasons = ["research_candidate_survived_but_validation_is_mixed_or_one_window_blocked"]
        if blocked_validation_windows:
            reasons.append("one_or_more_virgin_windows_blocked_by_data_quality")
        if len(validation_profitable) < len(validation_groups):
            reasons.append("one_or_more_clean_virgin_windows_not_profitable_after_cost_filters")

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_research_summary": str(config.replay_root / "raw_engine" / "summary.json"),
        "source_research_trades": str(research_path),
        "source_fx_csv": str(config.source_fx_csv),
        "raw_research_ending_equity": raw_summary.get("ending_equity"),
        "raw_research_trade_count": raw_summary.get("trade_count"),
        "method": {
            "active_cap_eur": ACTIVE_CAP_EUR,
            "risk_per_trade": RISK_PER_TRADE,
            "extra_commission_bps": EXTRA_COMMISSION_BPS,
            "tax_rate": CONSERVATIVE_TAX_RATE,
            "spread_cost_model": "Dukascopy bid/ask mid source; half spread at entry plus half spread at exit converted to R",
            "filter_grid": {
                "spread_r_gates": list(SPREAD_R_GATES),
                "min_stop_pips": list(MIN_STOP_PIPS),
            },
            "runtime_strategy_changed": False,
            "diagnostic_filter_only": True,
        },
        "research_spread_stats": research_spread_stats,
        "best_research_candidate": best,
        "best_candidate_validation_results": validation_results,
        "blocked_validation_windows": blocked_validation_windows,
        "stress_rows_for_best_candidate": stress_rows,
        "gate": {
            "may_freeze_eurusd_now": classification == PASSED,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "next_step": "If warning/failed, inspect rejected trade distribution and consider FX-native setup redesign rather than loosening cost filters.",
        },
        **SAFETY_FLAGS,
    }

    _write_json(config.output_root / "fx_eurusd_cost_aware_filter_repair_summary.json", summary)
    _write_csv(config.output_root / "research_filter_grid_results.csv", scenario_rows)
    _write_csv(config.output_root / "best_candidate_stress_rows.csv", stress_rows)
    _write_csv(config.output_root / "best_candidate_validation_results.csv", validation_results + blocked_validation_windows)
    if best_replay:
        _write_csv(config.output_root / "best_candidate_yearly_tax_rows.csv", best_replay.get("yearly_rows", []))
        _write_csv(config.output_root / "best_candidate_trade_ledger.csv", best_replay.get("trade_rows", []))
    return _round_payload(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    parser.add_argument("--replay-root", default=REPLAY_ROOT)
    parser.add_argument("--source-fx-csv", default=SOURCE_FX_CSV)
    args = parser.parse_args()
    root = project_root()
    summary = run(
        RepairCourtConfig(
            project_root=root,
            package_root=package_root(),
            replay_root=resolve_project_path(args.replay_root),
            source_fx_csv=resolve_project_path(args.source_fx_csv),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
