from __future__ import annotations

import json
import os
import signal
import sys
import time
from pathlib import Path
from typing import Any

from structural_compounding_lab.common.project_paths import project_root
from structural_compounding_lab.shadow_forward.multi_symbol_forward_runtime import (
    MultiSymbolForwardRuntimeConfig,
    OUTPUT_FOLDER_NAME,
    package_root,
    resolve_project_path,
    run_once,
)


STOP = False


def _handle_stop(signum: int, frame: Any) -> None:
    global STOP
    STOP = True


def _copy_seed_file(seed_root: Path, relative: str, target_root: Path) -> None:
    source = seed_root / relative
    target = target_root / relative
    if not source.exists() or target.exists():
        return
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(source.read_bytes())


def ensure_runtime_seed() -> None:
    root = project_root()
    seed_root = root / "structural_compounding_lab" / "runtime_seed"
    if not seed_root.exists():
        return
    for source in seed_root.rglob("*"):
        if not source.is_file():
            continue
        relative = source.relative_to(seed_root)
        target = root / "structural_compounding_lab" / relative
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.read_bytes())


def _config() -> MultiSymbolForwardRuntimeConfig:
    root = project_root()
    return MultiSymbolForwardRuntimeConfig(
        project_root=root,
        package_root=package_root(),
        data_root=resolve_project_path(os.getenv("RTS_DATA_ROOT", "data_storage")),
        reduced_cap_root=resolve_project_path(
            os.getenv(
                "RTS_REDUCED_CAP_ROOT",
                "structural_compounding_lab/output/multi_symbol_btc_exact_fill_cap_calibration_court_001",
            )
        ),
        output_root=resolve_project_path(
            os.getenv("RTS_RUNTIME_OUTPUT_ROOT", f"structural_compounding_lab/output/{OUTPUT_FOLDER_NAME}")
        ),
        seed_tail_rows=int(os.getenv("RTS_SEED_TAIL_ROWS", "43200")),
        max_catchup_minutes=int(os.getenv("RTS_MAX_CATCHUP_MINUTES", "10080")),
        throttle_seconds=float(os.getenv("RTS_SYMBOL_THROTTLE_SECONDS", "0.05")),
    )


def main() -> None:
    signal.signal(signal.SIGTERM, _handle_stop)
    signal.signal(signal.SIGINT, _handle_stop)
    interval = max(30, int(os.getenv("RTS_SCHEDULER_INTERVAL_SECONDS", "300")))
    run_at_start = os.getenv("RTS_RUN_AT_START", "true").lower() in {"1", "true", "yes"}
    ensure_runtime_seed()
    first = True
    while not STOP:
        if first and not run_at_start:
            first = False
        else:
            first = False
            summary = run_once(_config())
            print(json.dumps({"scheduler_iteration": time.time(), "summary": summary}, default=str), flush=True)
        deadline = time.time() + interval
        while not STOP and time.time() < deadline:
            time.sleep(min(5, deadline - time.time()))
    print("scheduler_loop_stopped", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()
