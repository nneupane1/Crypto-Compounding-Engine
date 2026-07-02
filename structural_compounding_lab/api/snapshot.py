from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from structural_compounding_lab.common.paths import artifact_paths
from structural_compounding_lab.config import StructuralLabConfig


def load_structural_summary(config: StructuralLabConfig | None = None) -> dict[str, Any]:
    paths = artifact_paths(config)
    summary_path = paths["summary"]
    if not summary_path.exists():
        return {"has_run": False, "empty_state": "No structural backtest run found yet."}
    return json.loads(summary_path.read_text(encoding="utf-8"))


def load_artifact_bundle(config: StructuralLabConfig | None = None) -> dict[str, Any]:
    cfg = config or StructuralLabConfig.load()
    paths = artifact_paths(cfg)
    return {
      "config_path": str(cfg.config_path),
      "output_root": str(cfg.output_root),
      "artifacts": {key: {"path": str(path), "exists": path.exists()} for key, path in paths.items()},
      "summary": load_structural_summary(cfg),
    }
