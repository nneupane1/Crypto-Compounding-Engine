from .base_candidate import StructuralResearchCandidate

candidate = StructuralResearchCandidate(
    candidate_id="compression_breakout_research",
    hypothesis="Compression states identified through Bollinger width and structural acceptance may deserve different patience and runner handling.",
    allowed_scope=["research_classification", "reporting"],
    forbidden_scope=["live_behavior_change", "paper_behavior_change"],
    required_inputs=["bollinger_features", "levels", "trade_outcomes"],
    expected_outputs=["indicator_confluence_report.json", "pullback_compounding_readiness_report.json"],
    validation_ladder=["plan_spec", "unit_tests", "diagnostic_fast_window"],
    acceptance_criteria=["compression_breakouts_show_distinct_distribution"],
    no_go_rules=["classification_is_not_stable"],
    safety_flags={"research_only": True, "authoritative": False},
)
