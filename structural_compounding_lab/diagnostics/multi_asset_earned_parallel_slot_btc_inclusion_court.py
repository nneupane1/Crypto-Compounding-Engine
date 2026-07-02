from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path  # noqa: E402
from structural_compounding_lab.diagnostics.multi_asset_earned_parallel_slot_court import (  # noqa: E402
    ACTIVE_CAP,
    EARNED_SLOT_VARIANTS,
    SAFETY_FLAGS,
    START_CAPITAL,
    TAX_RESERVE_RATE,
    EarnedParallelSlotConfig,
    _load_rows,
    _replay,
    _scenario_public,
    _symbol_caps,
    _write_csv,
    _write_json,
)
from structural_compounding_lab.diagnostics.multi_asset_execution_feasibility_scanner_replay_court import _load_assets  # noqa: E402
from structural_compounding_lab.diagnostics.multi_asset_portfolio_selection_court import (  # noqa: E402
    TRANSFER_ASSETS,
    _load_trade_rows,
    _read_json,
)


COURT_NAME = "MULTI_ASSET_EARNED_PARALLEL_SLOT_BTC_INCLUSION_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "multi_asset_earned_parallel_slot_btc_inclusion_court_001"

PASSED = "MULTI_ASSET_9_SYMBOL_BTC_INCLUSION_FREEZE_CANDIDATE_RESEARCH_ONLY"
WARNING = "MULTI_ASSET_9_SYMBOL_BTC_INCLUSION_WARNING_RESEARCH_ONLY"
FAILED = "MULTI_ASSET_9_SYMBOL_BTC_INCLUSION_NOT_BETTER_THAN_8_SYMBOL_RESEARCH_ONLY"
BLOCKED = "MULTI_ASSET_9_SYMBOL_BTC_INCLUSION_BLOCKED_RESEARCH_ONLY"

BTC_SYMBOL = "BTCUSDT"


@dataclass(frozen=True)
class BTCInclusionConfig:
    project_root: Path
    package_root: Path
    transfer_root: Path
    portfolio_root: Path
    reduced_cap_root: Path
    btc_reference_root: Path
    existing_earned_slot_root: Path
    output_root: Path


def default_config() -> BTCInclusionConfig:
    pkg = package_root()
    return BTCInclusionConfig(
        project_root=project_root(),
        package_root=pkg,
        transfer_root=pkg / "output" / "multi_asset_frozen_transfer_court_001",
        portfolio_root=pkg / "output" / "multi_asset_portfolio_selection_court_001",
        reduced_cap_root=pkg / "output" / "multi_symbol_reduced_cap_gear_ladder_restatement_court_001",
        btc_reference_root=pkg / "output" / "cost_aware_frozen_candidate_rebuild_court_001",
        existing_earned_slot_root=pkg / "output" / "multi_asset_earned_parallel_slot_court_001",
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


def _pct_delta(candidate: float, control: float) -> float:
    return ((candidate - control) / control * 100.0) if control else 0.0


def _load_btc_rows(config: BTCInclusionConfig) -> dict[str, list[dict[str, Any]]]:
    return {
        "research_rows": _load_trade_rows(
            config.btc_reference_root / "candidate_full_history_results.csv",
            symbol_override=BTC_SYMBOL,
            period="research",
        ),
        "holdout_rows": _load_trade_rows(
            config.btc_reference_root / "candidate_holdout_results.csv",
            symbol_override=BTC_SYMBOL,
            period="holdout",
        ),
    }


def _standalone_research_equity_by_symbol(assets: dict[str, dict[str, Any]], btc_rows: dict[str, list[dict[str, Any]]]) -> dict[str, float]:
    standings: dict[str, float] = {}
    for symbol in TRANSFER_ASSETS:
        summary = assets.get(symbol, {}).get("summary", {})
        standings[symbol] = float(
            summary.get("research_pre_holdout", {})
            .get("cost_aware_candidate", {})
            .get("ending_equity", 0.0)
        )
    equity = START_CAPITAL
    for row in sorted(btc_rows["research_rows"], key=lambda item: (item["entry_timestamp"], item["exit_timestamp"], item["symbol"])):
        equity += equity * 0.01 * float(row["net_r"])
    standings[BTC_SYMBOL] = equity
    return standings


def _rank_with_btc(control_priority: list[str], assets: dict[str, dict[str, Any]], btc_rows: dict[str, list[dict[str, Any]]]) -> list[str]:
    standings = _standalone_research_equity_by_symbol(assets, btc_rows)
    known = set(control_priority) | {BTC_SYMBOL}
    return sorted(known, key=lambda symbol: (-standings.get(symbol, 0.0), control_priority.index(symbol) if symbol in control_priority else 999))


def _run_policy(
    *,
    policy_id: str,
    priority_symbols: list[str],
    period_rows: dict[str, list[dict[str, Any]]],
    symbol_caps: dict[str, float],
) -> dict[str, dict[str, dict[str, Any]]]:
    output: dict[str, dict[str, dict[str, Any]]] = {}
    for variant_name, variant_ladder in EARNED_SLOT_VARIANTS:
        output[variant_name] = {}
        for period, rows in period_rows.items():
            output[variant_name][period] = _replay(
                rows,
                scenario_id=f"{policy_id}:{variant_name}",
                period=period,
                priority_symbols=priority_symbols,
                symbol_caps=symbol_caps,
                ladder=variant_ladder,
                active_cap=ACTIVE_CAP,
                tax_rate=TAX_RESERVE_RATE,
            )
    return output


def _best_variant(results: dict[str, dict[str, dict[str, Any]]]) -> str:
    return max(
        results,
        key=lambda name: (
            float(results[name]["holdout"]["ending_total_equity_after_tax"]),
            float(results[name]["research"]["ending_total_equity_after_tax"]),
            -float(results[name]["holdout"]["max_drawdown_total_after_tax"]),
        ),
    )


def run(config: BTCInclusionConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)

    required = [
        config.transfer_root / "multi_asset_frozen_transfer_summary.json",
        config.portfolio_root / "multi_asset_portfolio_selection_summary.json",
        config.reduced_cap_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json",
        config.btc_reference_root / "candidate_full_history_results.csv",
        config.btc_reference_root / "candidate_holdout_results.csv",
        config.existing_earned_slot_root / "multi_asset_earned_parallel_slot_summary.json",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_required_source_artifacts"],
            "missing_artifacts": missing,
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_asset_earned_parallel_slot_btc_inclusion_summary.json", summary)
        return _round_payload(summary)

    existing_summary = _read_json(config.existing_earned_slot_root / "multi_asset_earned_parallel_slot_summary.json")
    control_priority = list(existing_summary.get("fixed_priority_symbols") or [])
    if set(control_priority) != set(TRANSFER_ASSETS):
        control_priority = list(TRANSFER_ASSETS)

    earned_config = EarnedParallelSlotConfig(
        project_root=config.project_root,
        package_root=config.package_root,
        transfer_root=config.transfer_root,
        portfolio_root=config.portfolio_root,
        scanner_root=config.package_root / "output" / "multi_asset_execution_feasibility_scanner_replay_court_001",
        reduced_cap_root=config.reduced_cap_root,
        output_root=config.output_root,
    )
    assets = _load_assets(type("ScannerConfig", (), {"transfer_root": config.transfer_root})())
    missing_assets = [symbol for symbol in TRANSFER_ASSETS if symbol not in assets]
    btc_rows = _load_btc_rows(config)
    if missing_assets or not btc_rows["research_rows"] or not btc_rows["holdout_rows"]:
        summary = {
            "court_name": COURT_NAME,
            "created_at_utc": _now(),
            "final_classification": BLOCKED,
            "classification_reasons": ["missing_candidate_rows"],
            "missing_assets": missing_assets,
            "btc_research_rows": len(btc_rows["research_rows"]),
            "btc_holdout_rows": len(btc_rows["holdout_rows"]),
            **SAFETY_FLAGS,
        }
        _write_json(config.output_root / "multi_asset_earned_parallel_slot_btc_inclusion_summary.json", summary)
        return _round_payload(summary)

    symbol_caps = _symbol_caps(earned_config)
    control_rows = {
        "research": _load_rows(assets, "research_rows", control_priority),
        "holdout": _load_rows(assets, "holdout_rows", control_priority),
    }

    btc_assets_view = {
        **assets,
        BTC_SYMBOL: {
            "research_rows": btc_rows["research_rows"],
            "holdout_rows": btc_rows["holdout_rows"],
        },
    }
    btc_append_priority = [*control_priority, BTC_SYMBOL]
    btc_ranked_priority = _rank_with_btc(control_priority, assets, btc_rows)
    policy_priorities = {
        "control_8_symbol": control_priority,
        "btc_appended_last_9_symbol": btc_append_priority,
        "btc_research_ranked_9_symbol": btc_ranked_priority,
    }
    policy_rows = {
        "control_8_symbol": control_rows,
        "btc_appended_last_9_symbol": {
            "research": _load_rows(btc_assets_view, "research_rows", btc_append_priority),
            "holdout": _load_rows(btc_assets_view, "holdout_rows", btc_append_priority),
        },
        "btc_research_ranked_9_symbol": {
            "research": _load_rows(btc_assets_view, "research_rows", btc_ranked_priority),
            "holdout": _load_rows(btc_assets_view, "holdout_rows", btc_ranked_priority),
        },
    }

    policy_results: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    all_trade_rows: list[dict[str, Any]] = []
    all_rejected_rows: list[dict[str, Any]] = []
    all_yearly_rows: list[dict[str, Any]] = []
    for policy_id, rows in policy_rows.items():
        results = _run_policy(
            policy_id=policy_id,
            priority_symbols=policy_priorities[policy_id],
            period_rows=rows,
            symbol_caps=symbol_caps,
        )
        policy_results[policy_id] = results
        for variants in results.values():
            for result in variants.values():
                all_trade_rows.extend(result["trade_rows"])
                all_rejected_rows.extend(result["rejected_rows"])
                all_yearly_rows.extend(result["yearly_rows"])

    control_variant = _best_variant(policy_results["control_8_symbol"])
    control = policy_results["control_8_symbol"][control_variant]
    comparisons: dict[str, Any] = {}
    best_btc_policy = ""
    best_btc_variant = ""
    for policy_id in ("btc_appended_last_9_symbol", "btc_research_ranked_9_symbol"):
        variant = _best_variant(policy_results[policy_id])
        candidate = policy_results[policy_id][variant]
        holdout_delta = _pct_delta(
            float(candidate["holdout"]["ending_total_equity_after_tax"]),
            float(control["holdout"]["ending_total_equity_after_tax"]),
        )
        research_delta = _pct_delta(
            float(candidate["research"]["ending_total_equity_after_tax"]),
            float(control["research"]["ending_total_equity_after_tax"]),
        )
        holdout_dd_gate = float(candidate["holdout"]["max_drawdown_total_after_tax"]) <= max(
            0.50, float(control["holdout"]["max_drawdown_total_after_tax"]) * 1.25
        )
        holdout_pf_gate = float(candidate["holdout"]["profit_factor"]) >= 3.0
        comparisons[policy_id] = {
            "best_variant": variant,
            "priority_symbols": policy_priorities[policy_id],
            "research_delta_vs_control_pct": research_delta,
            "holdout_delta_vs_control_pct": holdout_delta,
            "holdout_drawdown_gate_passed": holdout_dd_gate,
            "holdout_profit_factor_gate_passed": holdout_pf_gate,
            "freeze_candidate_gate_passed": holdout_delta > 0.0 and research_delta >= 0.0 and holdout_dd_gate and holdout_pf_gate,
            "research": _scenario_public(candidate["research"]),
            "holdout": _scenario_public(candidate["holdout"]),
        }
        if not best_btc_policy or (
            float(candidate["holdout"]["ending_total_equity_after_tax"]),
            float(candidate["research"]["ending_total_equity_after_tax"]),
        ) > (
            float(policy_results[best_btc_policy][best_btc_variant]["holdout"]["ending_total_equity_after_tax"]),
            float(policy_results[best_btc_policy][best_btc_variant]["research"]["ending_total_equity_after_tax"]),
        ):
            best_btc_policy = policy_id
            best_btc_variant = variant

    best_candidate = comparisons[best_btc_policy]
    reasons: list[str] = []
    if bool(best_candidate["freeze_candidate_gate_passed"]):
        classification = PASSED
        reasons.append(f"btc_9_symbol_policy_improved_control:{best_btc_policy}:{best_btc_variant}")
    elif float(best_candidate["holdout"]["ending_total_equity_after_tax"]) > START_CAPITAL:
        classification = WARNING
        reasons.append("btc_9_symbol_policy_survived_but_did_not_beat_8_symbol_freeze_gate")
    else:
        classification = FAILED
        reasons.append("btc_9_symbol_policy_failed_to_survive_holdout")

    summary = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "final_classification": classification,
        "classification_reasons": reasons,
        "source_existing_8_symbol_root": str(config.existing_earned_slot_root),
        "source_btc_reference_root": str(config.btc_reference_root),
        "source_transfer_root": str(config.transfer_root),
        "control_8_symbol": {
            "best_variant": control_variant,
            "priority_symbols": control_priority,
            "research": _scenario_public(control["research"]),
            "holdout": _scenario_public(control["holdout"]),
        },
        "btc_candidate_rows": {
            "research_rows": len(btc_rows["research_rows"]),
            "holdout_rows": len(btc_rows["holdout_rows"]),
            "source_is_cost_aware_candidate_ledger": True,
        },
        "btc_symbol_cap": {
            "present_in_existing_symbol_caps": BTC_SYMBOL in symbol_caps,
            "used_existing_replay_default_when_missing": BTC_SYMBOL not in symbol_caps,
            "cap_value_eur": symbol_caps.get(BTC_SYMBOL),
        },
        "comparisons": comparisons,
        "best_btc_policy": best_btc_policy,
        "best_btc_variant": best_btc_variant,
        "freeze_gate": {
            "may_freeze_9_symbol_candidate": classification == PASSED,
            "requires_separate_user_approval_before_freeze": True,
            "current_8_symbol_freeze_mutated": False,
            "scheduler_changed": False,
            "may_enable_paper_trading": False,
            "may_enable_live_trading": False,
            "may_create_order_or_broker_path": False,
            "paper_validation_ready": False,
        },
        "method": {
            "starting_capital_eur": START_CAPITAL,
            "active_cap_eur": ACTIVE_CAP,
            "tax_reserve_rate": TAX_RESERVE_RATE,
            "cost_model_source": "pre-existing net_r/net_cost_r cost-aware candidate ledgers",
            "strategy_logic_changed": False,
            "entries_changed": False,
            "exits_changed": False,
            "thresholds_tuned": False,
            "scheduler_changed": False,
            "btc_added_as_candidate_stream_only": True,
        },
        **SAFETY_FLAGS,
    }
    _write_json(config.output_root / "multi_asset_earned_parallel_slot_btc_inclusion_summary.json", summary)
    _write_csv(config.output_root / "multi_asset_earned_parallel_slot_btc_inclusion_trade_ledger.csv", all_trade_rows)
    _write_csv(config.output_root / "multi_asset_earned_parallel_slot_btc_inclusion_rejected_rows.csv", all_rejected_rows)
    _write_csv(config.output_root / "multi_asset_earned_parallel_slot_btc_inclusion_yearly_tax_rows.csv", all_yearly_rows)
    return _round_payload(summary)


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--transfer-root", default="structural_compounding_lab/output/multi_asset_frozen_transfer_court_001")
    parser.add_argument("--portfolio-root", default="structural_compounding_lab/output/multi_asset_portfolio_selection_court_001")
    parser.add_argument("--reduced-cap-root", default="structural_compounding_lab/output/multi_symbol_reduced_cap_gear_ladder_restatement_court_001")
    parser.add_argument("--btc-reference-root", default="structural_compounding_lab/output/cost_aware_frozen_candidate_rebuild_court_001")
    parser.add_argument("--existing-earned-slot-root", default="structural_compounding_lab/output/multi_asset_earned_parallel_slot_court_001")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    summary = run(
        BTCInclusionConfig(
            project_root=root,
            package_root=package_root(),
            transfer_root=resolve_project_path(args.transfer_root),
            portfolio_root=resolve_project_path(args.portfolio_root),
            reduced_cap_root=resolve_project_path(args.reduced_cap_root),
            btc_reference_root=resolve_project_path(args.btc_reference_root),
            existing_earned_slot_root=resolve_project_path(args.existing_earned_slot_root),
            output_root=resolve_project_path(args.output_dir),
        )
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
