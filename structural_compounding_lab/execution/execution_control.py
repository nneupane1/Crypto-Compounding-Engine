from __future__ import annotations

import argparse
import json
import math
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from structural_compounding_lab.common.project_paths import package_root, project_root, resolve_project_path


OUTPUT_FOLDER_NAME = "execution_readiness"
COURT_NAME = "EXECUTION_CONTROL_SCAFFOLD_RESEARCH_ONLY"
ACTIVE_MULTI_SYMBOL_RUNTIME_FOLDER = "multi_symbol_forward_runtime_earned_parallel_slots"

ExecutionMode = Literal["research", "paper", "live"]

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
class ExecutionControlConfig:
    project_root: Path
    package_root: Path
    output_root: Path
    multi_symbol_runtime_root: Path
    multi_symbol_evidence_root: Path
    scheduler_installation_root: Path
    reduced_cap_root: Path


@dataclass(frozen=True)
class OrderIntent:
    symbol: str
    side: Literal["buy", "sell"]
    quantity: float
    order_type: Literal["market", "limit"]
    mode: ExecutionMode
    reason: str


@dataclass(frozen=True)
class ExecutionDecision:
    accepted: bool
    mode: ExecutionMode
    reason: str
    order_sent: bool = False
    paper_trade_created: bool = False
    live_trade_created: bool = False
    broker_endpoint_used: bool = False
    account_endpoint_used: bool = False
    signed_request_used: bool = False


def default_config() -> ExecutionControlConfig:
    root = project_root()
    pkg = package_root()
    return ExecutionControlConfig(
        project_root=root,
        package_root=pkg,
        output_root=pkg / "output" / OUTPUT_FOLDER_NAME,
        multi_symbol_runtime_root=pkg / "output" / ACTIVE_MULTI_SYMBOL_RUNTIME_FOLDER,
        multi_symbol_evidence_root=pkg / "output" / "multi_symbol_six_month_forward_evidence_court_001",
        scheduler_installation_root=pkg / "output" / "multi_symbol_scheduler_installation_court_001",
        reduced_cap_root=pkg / "output" / "multi_symbol_reduced_cap_gear_ladder_restatement_court_001",
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return round(value, 6)
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


def _read_json(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return {} if default is None else default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {} if default is None else default


def _env_flag(name: str) -> bool:
    return str(os.getenv(name, "")).strip().lower() in {"1", "true", "yes", "y"}


def _real_money_ack() -> bool:
    return os.getenv("RTS_REAL_MONEY_ACK", "") == "I_UNDERSTAND_REAL_MONEY_RISK"


def build_readiness(config: ExecutionControlConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    runtime_status_path = config.multi_symbol_runtime_root / "latest_status.json"
    evidence_summary_path = config.multi_symbol_evidence_root / "multi_symbol_six_month_forward_evidence_summary.json"
    scheduler_summary_path = config.scheduler_installation_root / "multi_symbol_scheduler_installation_summary.json"
    reduced_cap_summary_path = config.reduced_cap_root / "multi_symbol_reduced_cap_gear_ladder_restatement_summary.json"
    runtime = _read_json(runtime_status_path)
    evidence = _read_json(evidence_summary_path)
    scheduler = _read_json(scheduler_summary_path)
    reduced_cap = _read_json(reduced_cap_summary_path)

    expected_symbols = int(runtime.get("symbols_expected") or runtime.get("active_symbol_count") or 9)
    runtime_green = runtime.get("status_color") in {"GREEN", "YELLOW"} and int(runtime.get("symbols_clean") or 0) == expected_symbols
    no_duplicate_decisions = int(runtime.get("decision_ledger_duplicate_keys") or 0) == 0
    six_month_complete = evidence.get("final_classification") == "MULTI_SYMBOL_SIX_MONTH_FORWARD_EVIDENCE_PASSED_RESEARCH_ONLY"
    six_month_ready = evidence.get("final_classification") == "MULTI_SYMBOL_SIX_MONTH_FORWARD_EVIDENCE_READY_RESEARCH_ONLY"
    scheduler_loaded_research = scheduler.get("final_classification") == "MULTI_SYMBOL_SCHEDULER_INSTALLATION_READY_FOR_MANUAL_APPROVAL_RESEARCH_ONLY"
    reduced_cap_passed = reduced_cap.get("final_classification") == "MULTI_SYMBOL_REDUCED_CAP_GEAR_LADDER_RESTATEMENT_PASSED_RESEARCH_ONLY"

    env_paper_requested = _env_flag("RTS_ENABLE_PAPER_TRADING")
    env_live_requested = _env_flag("RTS_ENABLE_LIVE_TRADING")
    env_real_money_ack = _real_money_ack()
    paper_readiness_court_passed = False

    paper_blockers: list[str] = []
    if not runtime_green:
        paper_blockers.append("multi_symbol_runtime_not_green_or_yellow")
    if not no_duplicate_decisions:
        paper_blockers.append("decision_ledger_has_duplicate_keys")
    if not reduced_cap_passed:
        paper_blockers.append("reduced_cap_restatement_not_passed")
    if not six_month_complete:
        paper_blockers.append("six_month_forward_evidence_not_complete")
    if not paper_readiness_court_passed:
        paper_blockers.append("paper_readiness_court_not_passed")
    if not env_paper_requested:
        paper_blockers.append("RTS_ENABLE_PAPER_TRADING_not_true")

    live_blockers = list(paper_blockers)
    if not env_live_requested:
        live_blockers.append("RTS_ENABLE_LIVE_TRADING_not_true")
    if not env_real_money_ack:
        live_blockers.append("RTS_REAL_MONEY_ACK_missing")
    live_blockers.append("no_broker_adapter_implemented")
    live_blockers.append("no_order_sender_implemented")

    paper_ready = not paper_blockers
    live_ready = False

    payload = {
        "court_name": COURT_NAME,
        "created_at_utc": _now(),
        "mode": "execution_scaffold_only",
        "paper_scaffold_exists": True,
        "live_scaffold_exists": True,
        "paper_ready": paper_ready,
        "live_ready": live_ready,
        "paper_blockers": paper_blockers,
        "live_blockers": live_blockers,
        "source_artifacts": {
            "runtime_status": str(runtime_status_path),
            "six_month_evidence": str(evidence_summary_path),
            "scheduler_installation": str(scheduler_summary_path),
            "reduced_cap_restatement": str(reduced_cap_summary_path),
        },
        "preflight": {
            "runtime_status_color": runtime.get("status_color"),
            "symbols_clean": runtime.get("symbols_clean"),
            "symbols_expected": expected_symbols,
            "decision_ledger_duplicate_keys": runtime.get("decision_ledger_duplicate_keys"),
            "six_month_evidence_classification": evidence.get("final_classification"),
            "six_month_ready_not_complete": six_month_ready,
            "six_month_complete": six_month_complete,
            "scheduler_installation_classification": scheduler.get("final_classification"),
            "scheduler_loaded_research": scheduler_loaded_research,
            "reduced_cap_classification": reduced_cap.get("final_classification"),
            "reduced_cap_passed": reduced_cap_passed,
            "env_RTS_ENABLE_PAPER_TRADING": env_paper_requested,
            "env_RTS_ENABLE_LIVE_TRADING": env_live_requested,
            "env_RTS_REAL_MONEY_ACK": env_real_money_ack,
            "paper_readiness_court_passed": paper_readiness_court_passed,
        },
        "capability_matrix": {
            "research_shadow_forward": "enabled",
            "multi_symbol_scheduler_research": "enabled",
            "paper_trading": "blocked_by_gate",
            "live_trading": "blocked_by_gate",
            "broker_adapter": "not_implemented",
            "order_sender": "not_implemented",
            "signed_exchange_requests": "forbidden",
        },
        "gate": {
            "may_create_paper_trades": paper_ready,
            "may_create_live_trades": False,
            "may_send_orders": False,
            "may_use_broker": False,
            "may_use_private_or_signed_endpoint": False,
            "paper_validation_ready": paper_ready,
            "next_required_court": "SIX_MONTH_MULTI_SYMBOL_FORWARD_EVIDENCE_PASSED_THEN_PAPER_READINESS_COURT",
        },
        **SAFETY_FLAGS,
    }
    if paper_ready:
        payload["research_only"] = False
        payload["paper_allowed"] = True
        payload["paper_validation_ready"] = True
    return payload


def evaluate_order_intent(intent: OrderIntent, readiness: dict[str, Any] | None = None) -> ExecutionDecision:
    readiness = readiness or build_readiness()
    if intent.mode == "research":
        return ExecutionDecision(
            accepted=False,
            mode="research",
            reason="research_mode_records_observation_only_no_execution",
        )
    if intent.mode == "paper":
        if readiness.get("paper_ready") is True:
            return ExecutionDecision(
                accepted=True,
                mode="paper",
                reason="paper_gate_ready_but_no_paper_ledger_writer_enabled_in_this_scaffold",
                order_sent=False,
                paper_trade_created=False,
            )
        return ExecutionDecision(
            accepted=False,
            mode="paper",
            reason="paper_gate_blocked:" + ",".join(readiness.get("paper_blockers", [])),
        )
    return ExecutionDecision(
        accepted=False,
        mode="live",
        reason="live_gate_blocked:" + ",".join(readiness.get("live_blockers", [])),
    )


def write_readiness(config: ExecutionControlConfig | None = None) -> dict[str, Any]:
    config = config or default_config()
    config.output_root.mkdir(parents=True, exist_ok=True)
    payload = build_readiness(config)
    _write_json(config.output_root / "latest_execution_readiness.json", payload)
    _write_json(config.output_root / "execution_capability_matrix.json", payload["capability_matrix"])
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Execution-control readiness scaffold.")
    parser.add_argument("--mode", choices=["status", "evaluate-intent"], default="status")
    parser.add_argument("--output-dir", default=f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
    args = parser.parse_args()
    root = project_root()
    config = ExecutionControlConfig(
        project_root=root,
        package_root=package_root(),
        output_root=resolve_project_path(args.output_dir),
        multi_symbol_runtime_root=resolve_project_path(f"structural_compounding_lab/output/{ACTIVE_MULTI_SYMBOL_RUNTIME_FOLDER}"),
        multi_symbol_evidence_root=resolve_project_path("structural_compounding_lab/output/multi_symbol_six_month_forward_evidence_court_001"),
        scheduler_installation_root=resolve_project_path("structural_compounding_lab/output/multi_symbol_scheduler_installation_court_001"),
        reduced_cap_root=resolve_project_path("structural_compounding_lab/output/multi_symbol_reduced_cap_gear_ladder_restatement_court_001"),
    )
    payload = write_readiness(config)
    if args.mode == "evaluate-intent":
        decision = evaluate_order_intent(
            OrderIntent(symbol="BTCUSDT", side="buy", quantity=0.0, order_type="market", mode="live", reason="scaffold_smoke"),
            payload,
        )
        payload = {**payload, "sample_live_intent_decision": asdict(decision)}
    print(json.dumps(_jsonable(payload), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
