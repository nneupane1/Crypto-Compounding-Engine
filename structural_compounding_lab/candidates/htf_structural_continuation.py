from .base_candidate import StructuralResearchCandidate

candidate = StructuralResearchCandidate(
    candidate_id="htf_structural_continuation",
    hypothesis="Higher-timeframe structural continuation trades can be classified more intelligently by separating clean continuation from exhaustion and broken structure.",
    allowed_scope=["research_classification", "reporting", "holdout_comparison"],
    forbidden_scope=["runtime_routing", "threshold_changes", "live_orders"],
    required_inputs=["1h_setups", "12h_context", "levels", "liquidity_events"],
    expected_outputs=["winner_story_report.md", "pullback_type_performance_report.json"],
    validation_ladder=["plan_spec", "unit_tests", "diagnostic_fast_window", "recent_holdout"],
    acceptance_criteria=["structural_runner_cluster_has_positive_expectancy"],
    no_go_rules=["classification_only_adds_noise"],
    safety_flags={"research_only": True, "authoritative": False},
)
