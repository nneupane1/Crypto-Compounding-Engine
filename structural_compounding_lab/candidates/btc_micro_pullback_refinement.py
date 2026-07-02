from .base_candidate import StructuralResearchCandidate

candidate = StructuralResearchCandidate(
    candidate_id="btc_micro_pullback_refinement",
    hypothesis="BTC structural continuation trades may gain materially better R and add-on base quality when entry waits for a valid lower-timeframe micro pullback instead of chasing the first impulse.",
    allowed_scope=["research_reports", "backtest_comparison", "btc_only"],
    forbidden_scope=["live_runtime", "paper_runtime", "real_orders", "hard_entry_gate"],
    required_inputs=["1m_candles", "5m_candles", "1h_structural_context", "12h_context"],
    expected_outputs=["original_vs_pullback_entry.csv", "pullback_quality_report.json"],
    validation_ladder=["plan_spec", "unit_tests", "smoke_window", "diagnostic_fast_window", "recent_holdout"],
    acceptance_criteria=["average_R_improves", "missed_winner_rate_remains_bounded", "drawdown_does_not_worsen_materially"],
    no_go_rules=["trade_frequency_collapses", "holdout_degrades", "pullback_logic_requires_future_leakage"],
    safety_flags={"research_only": True, "authoritative": False},
)
