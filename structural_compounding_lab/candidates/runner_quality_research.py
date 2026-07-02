from .base_candidate import StructuralResearchCandidate

candidate = StructuralResearchCandidate(
    candidate_id="runner_quality_research",
    hypothesis="Not all structural winners deserve runner treatment; a compounding-readiness layer can distinguish tactical exits from true runner candidates.",
    allowed_scope=["readiness_scoring", "reporting", "backtest_only"],
    forbidden_scope=["exit_logic_change", "pyramiding_behavior_change"],
    required_inputs=["trade_log", "setup_log", "context_features"],
    expected_outputs=["pullback_compounding_readiness_report.json", "winner_story_report.md"],
    validation_ladder=["plan_spec", "unit_tests", "diagnostic_fast_window", "recent_holdout"],
    acceptance_criteria=["runner_tags_are_selective_and_explanatory"],
    no_go_rules=["runner_tags_track_pnl_after_the_fact_only"],
    safety_flags={"research_only": True, "authoritative": False},
)
