from __future__ import annotations

import json
from pathlib import Path

from structural_compounding_lab.backtest.engine import StructuralBacktestEngine
from structural_compounding_lab.config import StructuralLabConfig


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    config = StructuralLabConfig.load(root / "structural_compounding_lab" / "config" / "structural_compounding_smoke.yaml")
    engine = StructuralBacktestEngine(config=config)
    summary = engine.run(
        symbol="BTCUSDT",
        source_csv=root / "structural_compounding_lab" / "tests" / "fixtures" / "btcusdt_structural_fixture_1m.csv",
        output_dir="output/smoke_run",
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
