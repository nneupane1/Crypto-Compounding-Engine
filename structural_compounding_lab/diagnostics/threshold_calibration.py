from __future__ import annotations

from pathlib import Path

from structural_compounding_lab.diagnostics.detector_tightening import (
    ThresholdCalibrationConfig,
    write_threshold_calibration,
)


def main() -> None:
    root = Path(__file__).resolve().parents[2]
    config = ThresholdCalibrationConfig(
        review_root=root / "structural_compounding_lab" / "output" / "evidence_review_001",
        refinement_root=root / "structural_compounding_lab" / "output" / "evidence_refinement_001",
        stage2_root=root / "structural_compounding_lab" / "output" / "detector_tightening_001",
        output_root=root / "structural_compounding_lab" / "output" / "detector_tightening_002",
    )
    write_threshold_calibration(config)
    print(f"Threshold calibration artifacts written to: {config.output_root}")


if __name__ == "__main__":
    main()
