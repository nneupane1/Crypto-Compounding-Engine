from .base_candidate import StructuralResearchCandidate

candidate = StructuralResearchCandidate(
    candidate_id="momentum_burst_research",
    hypothesis="MACD/Bollinger soft evidence can separate true momentum bursts from noisy continuation without becoming a hard gate.",
    allowed_scope=["soft_scoring", "diagnostics", "personality_reports"],
    forbidden_scope=["hard_filter", "runtime_behavior_change"],
    required_inputs=["execution_frame_indicators", "setup_log", "trade_log"],
    expected_outputs=["indicator_confluence_report.json", "personality_performance_report.json"],
    validation_ladder=["plan_spec", "unit_tests", "diagnostic_fast_window"],
    acceptance_criteria=["soft_confluence_explains_trade_personality"],
    no_go_rules=["soft_layer_becomes_hidden_hard_gate"],
    safety_flags={"research_only": True, "authoritative": False},
)
