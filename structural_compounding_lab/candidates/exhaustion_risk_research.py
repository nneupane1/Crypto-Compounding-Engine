from .base_candidate import StructuralResearchCandidate

candidate = StructuralResearchCandidate(
    candidate_id="exhaustion_risk_research",
    hypothesis="Exhaustion-risk tags should identify structurally valid but lower-trust entries that may deserve more conservative de-risking in future research.",
    allowed_scope=["warning_labels", "post_trade_analysis"],
    forbidden_scope=["hard_rejection", "runtime_exit_change"],
    required_inputs=["macd_features", "bollinger_features", "volume_context", "trade_log"],
    expected_outputs=["personality_performance_report.json", "rejected_signal_story_report.md"],
    validation_ladder=["plan_spec", "unit_tests", "diagnostic_fast_window"],
    acceptance_criteria=["exhaustion_tag_explains_weaker_distribution"],
    no_go_rules=["warning_label_produces_false_precision"],
    safety_flags={"research_only": True, "authoritative": False},
)
