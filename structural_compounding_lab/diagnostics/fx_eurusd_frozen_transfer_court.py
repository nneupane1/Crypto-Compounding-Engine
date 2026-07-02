from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from structural_compounding_lab.common.project_paths import package_root, project_root


COURT_NAME = "FX_EURUSD_FROZEN_TRANSFER_COURT_RESEARCH_ONLY"
OUTPUT_FOLDER_NAME = "fx_eurusd_frozen_transfer_court_001"
QUALITY_OUTPUT_FOLDER_NAME = "fx_dukascopy_data_quality_court_001"

PASSED = "FX_EURUSD_FROZEN_TRANSFER_VALIDATED_RESEARCH_ONLY"
FAILED = "FX_EURUSD_FROZEN_TRANSFER_BLOCKED_BY_HOLDOUT_DATA_QUALITY_RESEARCH_ONLY"

SAFETY_FLAGS: dict[str, bool] = {
    "paper_validation_ready": False,
    "paper_allowed": False,
    "live_allowed": False,
    "real_money_allowed": False,
    "behavior_change_allowed": False,
    "broker_path_created": False,
    "order_path_created": False,
    "account_path_created": False,
    "private_endpoint_used": False,
    "signed_endpoint_used": False,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def _write_markdown(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# EURUSD Frozen Transfer Court 001",
        "",
        f"- Court: `{payload['court_name']}`",
        f"- Classification: `{payload['final_classification']}`",
        f"- Created at: `{payload['created_at']}`",
        f"- Source data: `{payload['source_data_path']}`",
        f"- Quality summary: `{payload['quality_summary_path']}`",
        f"- Gap manifest: `{payload['gap_manifest_path']}`",
        "",
        "## Data-quality gate",
        "",
        f"- Rows: `{payload['rows']}`",
        f"- Sealed holdout: `{payload['sealed_holdout_start']}` through `{payload['sealed_holdout_end']}`",
        f"- Holdout rows: `{payload['sealed_holdout_rows']}`",
        f"- Holdout duplicate count: `{payload['sealed_holdout_duplicate_count']}`",
        f"- Holdout OHLC failures: `{payload['sealed_holdout_ohlc_sanity_failures']}`",
        f"- Holdout unexpected in-session missing minutes: `{payload['sealed_holdout_unexpected_in_session_missing_minutes']}`",
        f"- Holdout session clean: `{payload['sealed_holdout_session_clean']}`",
        f"- Ready for frozen strategy transfer: `{payload['ready_for_frozen_strategy_transfer_court']}`",
        "",
        "## Decision",
        "",
        payload["decision"],
        "",
        "## Execution, tax, and safety",
        "",
        "- No strategy logic changed.",
        "- No synthetic candles inserted.",
        "- No forward-fill or back-fill price bars inserted.",
        "- No paper, live, broker, account, order, private, or signed endpoint path used.",
        "- No fee, tax, or PnL conclusion is valid until the sealed holdout is clean and the frozen transfer court can actually run.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_report() -> dict[str, Any]:
    root = project_root()
    pkg = package_root()
    output_root = pkg / "output" / OUTPUT_FOLDER_NAME
    quality_root = pkg / "output" / QUALITY_OUTPUT_FOLDER_NAME
    quality_summary_path = quality_root / "fx_data_quality_court_summary.json"
    gap_manifest_path = quality_root / "symbols" / "EURUSD" / "fx_gap_manifest.json"
    symbol_quality_path = quality_root / "symbols" / "EURUSD" / "quality_summary.json"
    source_data_path = root / "data_storage" / "FX" / "EURUSD" / "1m" / "EURUSD_1m_2003-05-04_to_2026-06-29.csv"

    court_summary = _read_json(quality_summary_path)
    gap_manifest = _read_json(gap_manifest_path)
    symbol_quality = _read_json(symbol_quality_path)
    symbol_rows = next(
        (row for row in court_summary.get("symbols", []) if row.get("symbol") == "EURUSD"),
        {},
    )
    quality = {**symbol_quality, **symbol_rows}

    holdout_gap_count = int(gap_manifest.get("holdout_gap_count", quality.get("sealed_holdout_gap_count", 0)) or 0)
    holdout_unexpected_missing = int(
        gap_manifest.get(
            "holdout_unexpected_in_session_missing_minutes",
            quality.get("sealed_holdout_unexpected_in_session_missing_minutes", 0),
        )
        or 0
    )
    holdout_duplicates = int(quality.get("sealed_holdout_duplicate_count", 0) or 0)
    holdout_ohlc = int(quality.get("sealed_holdout_ohlc_sanity_failures", 0) or 0)
    ready = bool(quality.get("ready_for_frozen_strategy_transfer_court")) and holdout_unexpected_missing == 0

    final_classification = PASSED if ready else FAILED
    decision = (
        "The EURUSD frozen transfer court may proceed."
        if ready
        else (
            "The EURUSD frozen transfer court is stopped before backtest/PnL calculation because the sealed virgin "
            "holdout is not session-clean. Running the frozen engine over this holdout would make the validation "
            "look precise while relying on missing in-session market data."
        )
    )

    payload: dict[str, Any] = {
        "court_name": COURT_NAME,
        "created_at": _now(),
        "final_classification": final_classification,
        "decision": decision,
        "project_root": str(root),
        "source_data_path": str(source_data_path),
        "quality_summary_path": str(quality_summary_path),
        "gap_manifest_path": str(gap_manifest_path),
        "rows": int(quality.get("rows", 0) or 0),
        "total_gaps": int(quality.get("total_gaps", gap_manifest.get("total_gaps", 0)) or 0),
        "total_missing_minutes": int(quality.get("total_missing_minutes", gap_manifest.get("total_missing_minutes", 0)) or 0),
        "unexpected_in_session_missing_minutes": int(
            quality.get("unexpected_in_session_missing_minutes", gap_manifest.get("unexpected_in_session_missing_minutes", 0)) or 0
        ),
        "sealed_holdout_start": quality.get("sealed_holdout_start"),
        "sealed_holdout_end": quality.get("sealed_holdout_end"),
        "sealed_holdout_rows": int(quality.get("sealed_holdout_rows", 0) or 0),
        "sealed_holdout_gap_count": holdout_gap_count,
        "sealed_holdout_duplicate_count": holdout_duplicates,
        "sealed_holdout_ohlc_sanity_failures": holdout_ohlc,
        "sealed_holdout_unexpected_in_session_missing_minutes": holdout_unexpected_missing,
        "sealed_holdout_session_clean": bool(quality.get("sealed_holdout_session_clean")) and holdout_unexpected_missing == 0,
        "ready_for_frozen_strategy_transfer_court": ready,
        "backtest_executed": ready,
        "shadow_forward_validation_executed": ready,
        "pnl_result_valid": ready,
        "fee_model_applied": "not_applicable_until_holdout_data_quality_passes",
        "tax_reserve_calculated": False,
        "tax_reserve_reason": "No validated FX PnL exists because the sealed holdout data-quality gate failed.",
        "synthetic_candles_inserted": False,
        "forward_fill_inserted": False,
        "back_fill_inserted": False,
        "holdout_must_be_gap_free": True,
        "strategy_logic_changed": False,
        "promising_assessment": (
            "not_assessable_until_real_public_data_repairs_the_sealed_holdout"
            if not ready
            else "assess_after_validated_transfer_replay"
        ),
        **SAFETY_FLAGS,
    }

    _write_json(output_root / "fx_eurusd_frozen_transfer_court_summary.json", payload)
    _write_markdown(output_root / "FX_EURUSD_FROZEN_TRANSFER_COURT_REPORT.md", payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description=COURT_NAME)
    parser.add_argument("--mode", choices=("run", "self_check"), default="run")
    args = parser.parse_args()
    payload = build_report()
    print(json.dumps(payload, indent=2, sort_keys=True))
    if args.mode == "self_check" and payload["final_classification"] not in {PASSED, FAILED}:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
