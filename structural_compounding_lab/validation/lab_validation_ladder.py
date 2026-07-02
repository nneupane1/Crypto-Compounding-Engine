from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from structural_compounding_lab.validation.acceptance_criteria import default_acceptance_criteria
from structural_compounding_lab.validation.no_go_rules import default_no_go_rules


def build_validation_ladder_payload() -> dict[str, Any]:
    return {
        "name": "structural_compounding_lab_validation_ladder_v2",
        "research_only": True,
        "auto_run_expensive_stages": False,
        "stages": [
            {"stage": "plan_spec", "symbol_scope": ["BTCUSDT"], "auto_run": False},
            {"stage": "unit_tests", "symbol_scope": ["BTCUSDT"], "auto_run": False},
            {"stage": "smoke_window", "symbol_scope": ["BTCUSDT"], "start": "2026-05-31", "end": "2026-06-13", "auto_run": False},
            {"stage": "diagnostic_fast_window", "symbol_scope": ["BTCUSDT"], "start": "2025-12-14", "end": "2026-06-13", "auto_run": False},
            {"stage": "stress_bull_window", "symbol_scope": ["BTCUSDT"], "start": "2020-10-01", "end": "2021-05-31", "auto_run": False},
            {"stage": "stress_bear_window", "symbol_scope": ["BTCUSDT"], "start": "2022-04-01", "end": "2022-07-31", "auto_run": False},
            {"stage": "stress_chop_window", "symbol_scope": ["BTCUSDT"], "start": "2024-10-01", "end": "2025-03-31", "auto_run": False},
            {"stage": "recent_holdout", "symbol_scope": ["BTCUSDT"], "start": "2025-06-14", "end": "2026-06-13", "auto_run": False},
            {"stage": "execution_cost_sensitivity", "symbol_scope": ["BTCUSDT"], "auto_run": False},
            {"stage": "full_history_confirmation", "symbol_scope": ["BTCUSDT"], "start": "2018-01-01", "end": "2026-06-13", "auto_run": False},
            {"stage": "monte_carlo", "symbol_scope": ["BTCUSDT"], "auto_run": False},
            {"stage": "paper_candidate_later", "symbol_scope": ["BTCUSDT"], "auto_run": False},
            {"stage": "manual_promotion_review", "symbol_scope": ["BTCUSDT"], "auto_run": False},
        ],
        "acceptance_criteria": default_acceptance_criteria(),
        "no_go_rules": default_no_go_rules(),
    }


def render_validation_ladder_markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Structural Compounding Lab Master Plan",
        "",
        "This validation ladder is research-only and does not auto-run expensive stages.",
        "",
        "## Stages",
        "",
    ]
    for stage in payload.get("stages", []):
        lines.append(
            f"- `{stage.get('stage')}` | symbols={stage.get('symbol_scope')} | auto_run={stage.get('auto_run', False)}"
        )
    lines.extend(
        [
            "",
            "## Acceptance Criteria",
            "",
            *[f"- {item}" for item in payload.get("acceptance_criteria", [])],
            "",
            "## No-Go Rules",
            "",
            *[f"- {item}" for item in payload.get("no_go_rules", [])],
            "",
        ]
    )
    return "\n".join(lines)


def write_master_lab_plan(*, json_path: Path, markdown_path: Path) -> dict[str, Any]:
    payload = build_validation_ladder_payload()
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    markdown_path.write_text(render_validation_ladder_markdown(payload), encoding="utf-8")
    return payload
