from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

import pandas as pd

from structural_compounding_lab.capital import (
    ProfitVaultState,
    build_convexity_profile,
    compute_position_size,
    should_add_to_winner,
)
from structural_compounding_lab.common.paths import artifact_paths, write_json
from structural_compounding_lab.config import StructuralLabConfig
from structural_compounding_lab.compounding import assess_compounding_readiness
from structural_compounding_lab.context import build_htf_context, detect_danger_state
from structural_compounding_lab.data import StructuralDataAdapter
from structural_compounding_lab.entry import build_trade_plan, detect_setup_candidate, score_setup_candidate
from structural_compounding_lab.exit import start_cooldown, should_lock_profit, update_cooldown, evaluate_exit
from structural_compounding_lab.features import (
    build_atr_context,
    build_ema_context,
    build_htf_structure_context,
    build_support_resistance_context,
    build_volume_context,
    build_vwap_context,
    classify_momentum_personality,
    detect_micro_pullback,
    extract_bollinger_features,
    extract_macd_features,
)
from structural_compounding_lab.indicators import (
    compute_atr,
    compute_bollinger_bands,
    compute_ema_stack,
    compute_macd,
    compute_session_vwap,
)
from structural_compounding_lab.market_structure import detect_liquidity_events, detect_structural_levels
from structural_compounding_lab.reports import write_structural_report
from structural_compounding_lab.research_pipeline import write_research_artifacts
from structural_compounding_lab.setup_stories import build_entry_story
from structural_compounding_lab.backtest.metrics import summarize_trades
from structural_compounding_lab.backtest.checkpoint import StructuralCheckpointStore
from structural_compounding_lab.backtest.portfolio import StructuralPortfolioState


class StructuralBacktestEngine:
    def __init__(self, config: StructuralLabConfig | None = None) -> None:
        self.config = config or StructuralLabConfig.load()
        self.adapter = StructuralDataAdapter(self.config)

    def _build_research_story(
        self,
        *,
        symbol: str,
        bundle: dict[str, pd.DataFrame],
        history: pd.DataFrame,
        row: pd.Series,
        candidate: dict[str, Any],
        scored: dict[str, Any],
        htf_context: dict[str, Any],
        levels: list[dict[str, Any]],
        cooldown_active: bool,
        fast_clear_eligible: bool,
        risk_multiplier: float,
        convexity_label: str | None,
    ) -> dict[str, Any]:
        side = str(scored.get("side", candidate.get("side", "long"))).lower()
        row_map = row.to_dict()
        ema_context = build_ema_context(row_map, side=side)
        atr_context = build_atr_context(row_map, stop_price=float(scored.get("stop_price", candidate.get("stop_price", 0.0)) or 0.0))
        volume_context = build_volume_context(history, row_map)
        vwap_context = build_vwap_context(row_map, side=side)
        support_resistance = build_support_resistance_context(candidate=scored, levels=levels)
        htf_structure = build_htf_structure_context(htf_context, side=side)
        lower_frame = bundle.get("5m") if self.config.require("execution_timeframe") == "1h" else bundle.get("1m")
        macd_features = extract_macd_features(history, row_map)
        bollinger_features = extract_bollinger_features(history, row_map)
        candidate_with_volume = {**scored, **volume_context, "symbol": symbol, "execution_timeframe": self.config.require("execution_timeframe")}
        pullback_features = detect_micro_pullback(
            lower_timeframe_frame=lower_frame,
            current_time=history.index[-1],
            candidate=candidate_with_volume,
            macd_features=macd_features,
            bollinger_features=bollinger_features,
        )
        personality = classify_momentum_personality(
            candidate=candidate_with_volume,
            ema_context=ema_context,
            volume_context=volume_context,
            vwap_context=vwap_context,
            macd_features=macd_features,
            bollinger_features=bollinger_features,
            pullback_features=pullback_features,
            htf_context=htf_structure,
        )
        compounding = assess_compounding_readiness(
            personality_label=str(personality.get("personality_label")),
            htf_aligned=bool(htf_structure.get("htf_aligned")),
            risk_reward=float(scored.get("risk_reward", 0.0) or 0.0),
            pullback_quality_score=float(pullback_features.get("pullback_quality_score", 0.0) or 0.0),
            exhaustion_warning=bool(personality.get("warning_conditions")),
            volume_distribution_warning=bool(volume_context.get("distribution_warning")),
            cooldown_active=cooldown_active,
            fast_clear_eligible=fast_clear_eligible,
            risk_multiplier=risk_multiplier,
            convexity_label=convexity_label,
            pullback_type=str(pullback_features.get("pullback_type", "NO_PULLBACK_SIGNAL")),
        )
        story = build_entry_story(
            candidate=candidate_with_volume,
            ema_context=ema_context,
            atr_context=atr_context,
            volume_context=volume_context,
            vwap_context=vwap_context,
            support_resistance=support_resistance,
            htf_context=htf_structure,
            macd_features=macd_features,
            bollinger_features=bollinger_features,
            pullback_features=pullback_features,
            personality=personality,
            compounding=compounding,
            story_id=f"{symbol}-{scored.get('timestamp')}-{side}",
        )
        return story

    def _checkpoint_metadata(
        self,
        *,
        symbol: str,
        source_csv: str | None,
        output_dir: str | None,
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "source_csv": source_csv,
            "execution_timeframe": self.config.require("execution_timeframe"),
            "analysis_start_date": str(self.config.get("data", "analysis_start_date") or self.config.get("data", "history_start_date")),
            "analysis_end_date": str(self.config.get("data", "analysis_end_date") or self.config.get("data", "history_end_date")),
            "output_dir": output_dir or str(self.config.output_root),
        }

    def _checkpoint_compatible(self, payload: dict[str, Any] | None, metadata: dict[str, Any]) -> bool:
        if not payload:
            return False
        saved = payload.get("metadata", {})
        return all(saved.get(key) == value for key, value in metadata.items())

    def _write_phase_status(
        self,
        *,
        paths: dict[str, Path],
        state: str,
        current_index: int,
        total_bars: int,
        last_timestamp: Any,
        resumed_from_checkpoint: bool,
    ) -> None:
        progress_pct = (float(current_index) / float(total_bars)) if total_bars else 0.0
        status_payload = {
            "state": state,
            "updated_at_utc": pd.Timestamp.now("UTC").isoformat(),
            "current_index": int(current_index),
            "total_bars": int(total_bars),
            "progress_pct": progress_pct,
            "last_timestamp": str(last_timestamp) if last_timestamp is not None else None,
            "resumed_from_checkpoint": bool(resumed_from_checkpoint),
        }
        write_json(paths["status"], status_payload)
        write_json(
            paths["scenario_progress"],
            {
                "run_state": state,
                "current_index": int(current_index),
                "total_bars": int(total_bars),
                "progress_pct": progress_pct,
                "last_timestamp": str(last_timestamp) if last_timestamp is not None else None,
                "resumed_from_checkpoint": bool(resumed_from_checkpoint),
            },
        )

    def _save_checkpoint(
        self,
        *,
        store: StructuralCheckpointStore,
        metadata: dict[str, Any],
        next_index: int,
        total_bars: int,
        last_timestamp: Any,
        portfolio: StructuralPortfolioState,
        seen_levels: set[tuple[str, str, float]],
        seen_liquidity: set[tuple[str, str, float]],
    ) -> None:
        store.save(
            {
                "updated_at": pd.Timestamp.now("UTC").isoformat(),
                "metadata": metadata,
                "next_index": int(next_index),
                "total_bars": int(total_bars),
                "next_candle_time": str(last_timestamp) if last_timestamp is not None else None,
                "portfolio_state": portfolio.to_dict(),
                "seen_levels": [list(item) for item in sorted(seen_levels)],
                "seen_liquidity": [list(item) for item in sorted(seen_liquidity)],
            }
        )

    def run(
        self,
        *,
        symbol: str | None = None,
        source_csv: str | None = None,
        output_dir: str | None = None,
        max_bars: int | None = None,
    ) -> dict[str, Any]:
        symbol = (symbol or self.config.get("symbol") or "BTCUSDT").upper()
        output_paths = artifact_paths(self.config, output_dir=output_dir)
        resolved_source_csv = None
        if source_csv is not None:
            resolved_source_csv = str(Path(source_csv).expanduser().resolve())
        checkpoint_store = StructuralCheckpointStore(output_paths["checkpoint"])
        checkpoint_metadata = self._checkpoint_metadata(
            symbol=symbol,
            source_csv=resolved_source_csv,
            output_dir=str(output_paths["summary"].parent),
        )
        bundle = self.adapter.build_timeframe_bundle(
            symbol,
            source_csv=source_csv,
            timeframes=["1m", "5m", "15m", self.config.require("execution_timeframe"), *self.config.require("confirmation_timeframes"), "4h"],
        )
        execution_timeframe = self.config.require("execution_timeframe")
        execution = bundle[execution_timeframe].copy()
        ema_cfg = self.config.require("ema")
        execution = compute_ema_stack(execution, fast=int(ema_cfg["fast"]), mid=int(ema_cfg["mid"]), slow=int(ema_cfg["slow"]))
        execution["atr"] = compute_atr(execution, period=int(self.config.require("atr", "period")))
        execution["vwap"] = compute_session_vwap(execution)
        execution = compute_macd(execution)
        execution = compute_bollinger_bands(execution)
        execution["ema_fast_slope"] = execution[f"ema_{int(ema_cfg['fast'])}"].diff()
        execution["ema_mid_slope"] = execution[f"ema_{int(ema_cfg['mid'])}"].diff()
        execution = execution.dropna().copy()

        structure_window_bars = int(self.config.require("engine", "structure_window_bars"))
        liquidity_window_bars = int(self.config.require("engine", "liquidity_window_bars"))
        setup_window_bars = int(self.config.require("engine", "setup_window_bars"))
        recent_liquidity_bars = int(self.config.require("setup", "recent_liquidity_bars"))
        max_level_distance_atr = float(self.config.require("setup", "max_level_distance_atr"))
        min_level_strength = float(self.config.require("setup", "min_level_strength"))
        target_buffer_atr = float(self.config.require("setup", "target_buffer_atr"))
        fallback_without_liquidity = bool(self.config.require("setup", "fallback_without_liquidity"))

        resume_enabled = bool(self.config.require("engine", "resume_enabled"))
        checkpoint_every_bars = max(0, int(self.config.require("engine", "checkpoint_every_bars")))
        write_partial_artifacts = bool(self.config.require("engine", "write_partial_artifacts"))

        portfolio = StructuralPortfolioState(
            profit_vault=ProfitVaultState(
                base_capital=float(self.config.require("base_capital")),
                active_trading_capital=float(self.config.require("base_capital")),
            )
        )
        seen_levels: set[tuple[str, str, float]] = set()
        seen_liquidity: set[tuple[str, str, float]] = set()
        start_index = 0
        resumed_from_checkpoint = False
        checkpoint_payload = checkpoint_store.load() if resume_enabled and checkpoint_store.exists() else None
        if self._checkpoint_compatible(checkpoint_payload, checkpoint_metadata):
            next_index = int(checkpoint_payload.get("next_index", 0))
            if 0 < next_index < len(execution):
                portfolio = StructuralPortfolioState.from_dict(checkpoint_payload.get("portfolio_state"))
                seen_levels = {
                    (str(item[0]), str(item[1]), float(item[2]))
                    for item in checkpoint_payload.get("seen_levels", [])
                    if len(item) == 3
                }
                seen_liquidity = {
                    (str(item[0]), str(item[1]), float(item[2]))
                    for item in checkpoint_payload.get("seen_liquidity", [])
                    if len(item) == 3
                }
                start_index = next_index
                resumed_from_checkpoint = True
        max_hold_bars = int(self.config.require("risk", "max_hold_bars"))
        add_on_trigger_r = float(self.config.require("pyramiding", "add_on_trigger_r"))
        max_add_ons = int(self.config.require("pyramiding", "max_add_ons"))
        add_on_fraction = float(self.config.require("pyramiding", "size_fraction"))
        cooldown_bars = int(self.config.require("cooldown", "bars"))
        cooldown_minimum_bars = int(self.config.require("cooldown", "minimum_bars"))
        cooldown_fast_resume_score = float(self.config.require("cooldown", "fast_resume_score"))
        cooldown_requires_danger_clear = bool(self.config.require("cooldown", "requires_danger_clear"))
        min_rr = float(self.config.require("risk", "minimum_rr"))
        profit_lock_floor_r = float(self.config.require("profit_vault", "lock_after_r"))
        convexity_cfg = self.config.require("convexity")
        decision_start_value = self.config.get("engine", "decision_start_date")
        decision_start_timestamp = (
            pd.Timestamp(decision_start_value).tz_convert("UTC")
            if decision_start_value and pd.Timestamp(decision_start_value).tzinfo is not None
            else (pd.Timestamp(decision_start_value).tz_localize("UTC") if decision_start_value else None)
        )

        processed_since_resume = 0
        self._write_phase_status(
            paths=output_paths,
            state="running",
            current_index=start_index,
            total_bars=len(execution),
            last_timestamp=(execution.index[start_index - 1] if start_index > 0 else None),
            resumed_from_checkpoint=resumed_from_checkpoint,
        )

        for position in range(start_index, len(execution)):
            timestamp = execution.index[position]
            current_timestamp = pd.Timestamp(timestamp)
            if decision_start_timestamp is None:
                decision_allowed = True
            elif current_timestamp.tzinfo is None and decision_start_timestamp.tzinfo is not None:
                decision_allowed = current_timestamp.tz_localize("UTC") >= decision_start_timestamp
            elif current_timestamp.tzinfo is not None and decision_start_timestamp.tzinfo is None:
                decision_allowed = current_timestamp >= decision_start_timestamp.tz_localize(current_timestamp.tzinfo)
            else:
                decision_allowed = current_timestamp >= decision_start_timestamp
            row = execution.iloc[position]
            htf_context = build_htf_context(bundle, pd.Timestamp(timestamp))
            history = execution.iloc[: position + 1]
            structure_history = history.tail(structure_window_bars)
            liquidity_history = history.tail(liquidity_window_bars)
            setup_history = history.tail(setup_window_bars)
            levels = [level.to_dict() for level in detect_structural_levels(
                structure_history,
                cutoff_timestamp=timestamp,
                timeframe_source=execution_timeframe,
                pivot_left=int(self.config.require("sr", "pivot_left")),
                pivot_right=int(self.config.require("sr", "pivot_right")),
                tolerance_pct=float(self.config.require("sr", "touch_tolerance_pct")),
                rolling_range_bars=int(self.config.require("sr", "rolling_range_bars")),
            )]
            for level in levels:
                key = (level["type"], level["last_touched"], level["price"])
                if key not in seen_levels:
                    portfolio.level_rows.append({"symbol": symbol, **level, "timestamp": level["last_touched"]})
                    seen_levels.add(key)
            liquidity = [event.to_dict() for event in detect_liquidity_events(
                liquidity_history,
                cutoff_timestamp=timestamp,
                timeframe_source=execution_timeframe,
                equal_level_tolerance_pct=float(self.config.require("liquidity", "equal_level_tolerance_pct")),
                sweep_lookback_bars=int(self.config.require("liquidity", "sweep_lookback_bars")),
                reclaim_tolerance_pct=float(self.config.require("liquidity", "reclaim_tolerance_pct")),
            )]
            for event in liquidity:
                key = (event["type"], event["timestamp"], event["price"])
                if key not in seen_liquidity:
                    portfolio.liquidity_rows.append({"symbol": symbol, **event})
                    seen_liquidity.add(key)

            candidate = None
            scored = None
            convexity_profile = None
            if portfolio.open_trade is None and decision_allowed:
                candidate = detect_setup_candidate(
                    setup_history,
                    levels=levels,
                    liquidity_events=liquidity,
                    htf_context=htf_context,
                    minimum_rr=min_rr,
                    recent_liquidity_bars=recent_liquidity_bars,
                    max_level_distance_atr=max_level_distance_atr,
                    min_level_strength=min_level_strength,
                    target_buffer_atr=target_buffer_atr,
                    fallback_without_liquidity=fallback_without_liquidity,
                )
                if candidate is not None:
                    scored = score_setup_candidate(candidate)
                    scored["symbol"] = symbol
                    convexity_profile = build_convexity_profile(
                        scored,
                        min_risk_multiplier=float(convexity_cfg["min_risk_multiplier"]),
                        max_risk_multiplier=float(convexity_cfg["max_risk_multiplier"]),
                        strong_score_threshold=float(convexity_cfg["strong_score_threshold"]),
                        elite_score_threshold=float(convexity_cfg["elite_score_threshold"]),
                    )
                    scored["convexity_profile"] = convexity_profile

            prior_cooldown_active = portfolio.cooldown.active
            if portfolio.cooldown.active:
                portfolio.cooldown = update_cooldown(
                    portfolio.cooldown,
                    danger_cleared=htf_context.get("bias") != "bearish",
                    candidate_ready=bool(scored and scored.get("accepted")),
                    candidate_score=float(scored.get("total_score", 0.0)) if scored else 0.0,
                    aligned_setup=bool(convexity_profile and convexity_profile.get("cooldown_fast_clear_eligible")),
                )
                portfolio.profit_vault.cooldown_active = portfolio.cooldown.active
                if prior_cooldown_active and not portfolio.cooldown.active:
                    portfolio.profit_vault.cooldown_active = False
                    portfolio.cooldown_rows.append(
                        {
                            "symbol": symbol,
                            "timestamp": pd.Timestamp(timestamp).isoformat(),
                            "reason": portfolio.cooldown.release_reason or "cooldown_completed",
                            "cooldown_bars": 0,
                            "event_type": "cooldown_release",
                        }
                    )

            if portfolio.open_trade is not None:
                open_trade = portfolio.open_trade
                pnl_if_marked = (
                    (float(row["close"]) - float(open_trade["entry_price"])) * float(open_trade["quantity"])
                    if open_trade["side"] == "long"
                    else (float(open_trade["entry_price"]) - float(row["close"])) * float(open_trade["quantity"])
                )
                portfolio.profit_vault.mark_floating_profit(pnl_if_marked)
                danger_state = detect_danger_state(
                    row,
                    side=open_trade["side"],
                    htf_context=htf_context,
                    atr_shock_multiple=float(self.config.require("atr", "shock_multiple")),
                    open_trade=open_trade,
                )
                exit_decision = evaluate_exit(
                    open_trade,
                    row,
                    holding_bars=int(open_trade["holding_bars"]),
                    danger_state=danger_state,
                )
                pnl_r = float(exit_decision.get("pnl_r", 0.0))
                current_price = float(row["close"])
                next_stop_price = float(exit_decision.get("new_stop", open_trade["active_stop_price"]))
                stop_improved_by_r = (
                    abs(next_stop_price - float(open_trade["entry_price"])) / max(float(open_trade["risk_per_unit"]), 1e-8)
                )
                if self.config.require("pyramiding", "enabled") and should_add_to_winner(
                    side=open_trade["side"],
                    entry_price=float(open_trade["entry_price"]),
                    current_price=current_price,
                    active_stop_price=next_stop_price,
                    add_on_count=int(open_trade["add_on_count"]),
                    max_add_ons=min(max_add_ons, int(open_trade.get("convexity_add_on_budget", max_add_ons))),
                    pnl_r=pnl_r,
                    trigger_r=max(add_on_trigger_r, float(open_trade.get("trail_activation_r", add_on_trigger_r))),
                    score=float(open_trade.get("entry_score", 0.0)),
                    min_score=float(open_trade.get("add_on_min_score", 0.0)),
                    stop_improved_by_r=stop_improved_by_r,
                    min_stop_upgrade_r=float(open_trade.get("add_on_min_stop_upgrade_r", 0.0)),
                    convexity_budget_remaining=int(open_trade.get("convexity_add_on_budget", max_add_ons)) - int(open_trade["add_on_count"]),
                ):
                    add_quantity = float(open_trade["quantity"]) * add_on_fraction
                    open_trade["quantity"] += add_quantity
                    open_trade["add_on_count"] += 1
                    portfolio.pyramiding_rows.append(
                        {
                            "symbol": symbol,
                            "timestamp": pd.Timestamp(timestamp).isoformat(),
                            "add_type": "proof_retest_add",
                            "side": open_trade["side"],
                            "quantity": add_quantity,
                            "price": current_price,
                            "risk_multiplier": float(open_trade.get("risk_multiplier", 1.0)),
                            "convexity_label": open_trade.get("convexity_label"),
                            "stop_upgrade_r": stop_improved_by_r,
                            "cycle_id": portfolio.profit_vault.current_compounding_cycle_id,
                        }
                    )
                if exit_decision.get("new_stop") is not None:
                    open_trade["active_stop_price"] = float(exit_decision["new_stop"])
                open_trade["holding_bars"] += 1
                if exit_decision["exit"]:
                    realized_pnl = float(exit_decision["pnl_r"]) * float(open_trade["risk_per_unit"]) * float(open_trade["quantity"])
                    portfolio.profit_vault.apply_realized_pnl(realized_pnl)
                    portfolio.profit_vault.mark_floating_profit(0.0)
                    ending_equity = portfolio.profit_vault.total_equity
                    trade_row = {
                        "trade_id": f"{symbol}-{len(portfolio.trade_rows)+1}",
                        "symbol": symbol,
                        "side": open_trade["side"],
                        "entry_time": open_trade["entry_time"],
                        "exit_time": pd.Timestamp(timestamp).isoformat(),
                        "entry_price": open_trade["entry_price"],
                        "exit_price": float(exit_decision["exit_price"]),
                        "initial_stop": open_trade["stop_price"],
                        "trail_stop": open_trade["active_stop_price"],
                        "pnl": realized_pnl,
                        "r_multiple": float(exit_decision["pnl_r"]),
                        "entry_reason": open_trade["entry_reason"],
                        "exit_reason": exit_decision["reason"],
                        "add_on_count": open_trade["add_on_count"],
                        "holding_bars": open_trade["holding_bars"],
                        "setup_class": open_trade["setup_class"],
                        "strategy_type": "structural_compounding",
                        "moonshot_state": "moonshot" if float(exit_decision["pnl_r"]) >= 4.0 else "normal",
                        "entry_score": float(open_trade.get("entry_score", 0.0)),
                        "risk_multiplier": float(open_trade.get("risk_multiplier", 1.0)),
                        "convexity_label": open_trade.get("convexity_label"),
                        "cooldown_fast_clear_eligible": bool(open_trade.get("cooldown_fast_clear_eligible", False)),
                        "personality_label": open_trade.get("personality_label"),
                        "personality_confidence": float(open_trade.get("personality_confidence", 0.0) or 0.0),
                        "pullback_type": open_trade.get("pullback_type"),
                        "pullback_quality_score": float(open_trade.get("pullback_quality_score", 0.0) or 0.0),
                        "pullback_entry_price": float(open_trade.get("pullback_entry_price", 0.0) or 0.0),
                        "pullback_stop_price": float(open_trade.get("pullback_stop_price", 0.0) or 0.0),
                        "pullback_r_improvement": float(open_trade.get("pullback_r_improvement", 0.0) or 0.0),
                        "compounding_readiness_score": float(open_trade.get("compounding_readiness_score", 0.0) or 0.0),
                        "runner_label": open_trade.get("runner_label"),
                        "add_on_research_candidate": bool(open_trade.get("add_on_research_candidate", False)),
                        "patience_score": float(open_trade.get("patience_score", 0.0) or 0.0),
                        "de_risk_score": float(open_trade.get("de_risk_score", 0.0) or 0.0),
                        "equity_after": ending_equity,
                        "cycle_id": portfolio.profit_vault.current_compounding_cycle_id,
                    }
                    portfolio.trade_rows.append(trade_row)
                    if should_lock_profit(
                        current_equity=portfolio.profit_vault.active_trading_capital,
                        base_capital=portfolio.profit_vault.base_capital,
                        danger_state=danger_state,
                        minimum_lock_profit=float(self.config.require("profit_vault", "minimum_lock_profit")),
                    ) and float(exit_decision["pnl_r"]) >= min(float(open_trade.get("profit_lock_floor_r", profit_lock_floor_r)), profit_lock_floor_r):
                        lock_event = portfolio.profit_vault.lock_profit_and_reset(reason=exit_decision["reason"])
                        lock_event["timestamp"] = pd.Timestamp(timestamp).isoformat()
                        lock_event["symbol"] = symbol
                        lock_event["event_type"] = "profit_lock"
                        lock_event["convexity_label"] = open_trade.get("convexity_label")
                        lock_event["r_multiple"] = float(exit_decision["pnl_r"])
                        portfolio.pyramiding_rows.append(lock_event)
                        portfolio.cooldown = start_cooldown(
                            bars=cooldown_bars,
                            reason=exit_decision["reason"],
                            minimum_bars=cooldown_minimum_bars,
                            fast_resume_score=cooldown_fast_resume_score,
                            requires_danger_clear=cooldown_requires_danger_clear,
                        )
                        portfolio.profit_vault.cooldown_active = True
                        portfolio.cooldown_rows.append(
                            {
                                "symbol": symbol,
                                "timestamp": pd.Timestamp(timestamp).isoformat(),
                                "reason": exit_decision["reason"],
                                "cooldown_bars": cooldown_bars,
                                "minimum_bars": cooldown_minimum_bars,
                                "event_type": "cooldown_start",
                            }
                        )
                    portfolio.open_trade = None

            if portfolio.open_trade is None:
                if scored is not None:
                    research_story = self._build_research_story(
                        symbol=symbol,
                        bundle=bundle,
                        history=history,
                        row=row,
                        candidate=candidate or scored,
                        scored=scored,
                        htf_context=htf_context,
                        levels=levels,
                        cooldown_active=portfolio.cooldown.active,
                        fast_clear_eligible=bool((convexity_profile or {}).get("cooldown_fast_clear_eligible", False)),
                        risk_multiplier=float((convexity_profile or {}).get("risk_multiplier", 1.0)),
                        convexity_label=(convexity_profile or {}).get("label"),
                    )
                    pullback_features = research_story.get("pullback", {})
                    personality = research_story.get("personality", {})
                    compounding = research_story.get("compounding", {})
                    macd_features = research_story.get("macd", {})
                    bollinger_features = research_story.get("bollinger", {})
                    setup_decision = scored["decision"]
                    opened_trade = False
                    portfolio.setup_rows.append(
                        {
                            "symbol": symbol,
                            "timestamp": scored["timestamp"],
                            "side": scored["side"],
                            "setup_type": "structural_compounding",
                            "setup_class": scored["classification"],
                            "classification": scored["classification"],
                            "structure_score": scored["structure_score"],
                            "liquidity_score": scored["liquidity_score"],
                            "ema_score": scored["ema_score"],
                            "htf_confirmation_score": scored["htf_confirmation_score"],
                            "volatility_score": scored["volatility_score"],
                            "risk_reward_score": scored["risk_reward_score"],
                            "score": scored["total_score"],
                            "total_score": scored["total_score"],
                            "accepted": scored["accepted"],
                            "decision": "pending_open",
                            "entry_reason": scored["entry_reason"],
                            "explanation": scored["entry_reason"],
                            "pattern": scored["pattern"],
                            "htf_aligned": bool(scored.get("htf_aligned", False)),
                            "target_price": float(scored.get("target_price", 0.0)),
                            "level_distance_atr": float(scored.get("level_distance_atr", 0.0)),
                            "liquidity_event_type": scored.get("liquidity_event_type"),
                            "liquidity_event_age_bars": scored.get("liquidity_event_age_bars"),
                            "risk_multiplier": float((convexity_profile or {}).get("risk_multiplier", 1.0)),
                            "convexity_label": (convexity_profile or {}).get("label"),
                            "cooldown_fast_clear_eligible": bool((convexity_profile or {}).get("cooldown_fast_clear_eligible", False)),
                            "execution_timeframe": execution_timeframe,
                            "story_id": research_story.get("story_id"),
                            "personality_label": personality.get("personality_label"),
                            "personality_confidence": float(personality.get("personality_confidence", 0.0) or 0.0),
                            "personality_explanation": personality.get("explanation_text"),
                            "macd_state": macd_features.get("macd_state"),
                            "macd_confirmation_flag": bool(macd_features.get("macd_confirmation_flag", False)),
                            "macd_warning_flag": bool(macd_features.get("macd_warning_flag", False)),
                            "bollinger_state": bollinger_features.get("bb_state"),
                            "bb_compression": bool(bollinger_features.get("bb_compression", False)),
                            "bb_expansion": bool(bollinger_features.get("bb_expansion", False)),
                            "bb_warning_flag": bool(bollinger_features.get("bb_warning_flag", False)),
                            "pullback_type": pullback_features.get("pullback_type"),
                            "micro_pullback_detected": bool(pullback_features.get("micro_pullback_detected", False)),
                            "pullback_entry_time": pullback_features.get("entry_candidate_time"),
                            "pullback_entry_price": float(pullback_features.get("entry_candidate_price", 0.0) or 0.0),
                            "pullback_stop_price": float(pullback_features.get("stop_price", 0.0) or 0.0),
                            "pullback_quality_score": float(pullback_features.get("pullback_quality_score", 0.0) or 0.0),
                            "pullback_depth_atr": float(pullback_features.get("pullback_depth_atr", 0.0) or 0.0),
                            "pullback_estimated_r": float(pullback_features.get("estimated_R_to_existing_target", 0.0) or 0.0),
                            "pullback_r_improvement": float(pullback_features.get("r_improvement_vs_original", 0.0) or 0.0),
                            "pullback_explanation": pullback_features.get("explanation"),
                            "compounding_readiness_score": float(compounding.get("compounding_readiness_score", 0.0) or 0.0),
                            "runner_label": compounding.get("runner_label"),
                            "runner_eligible_candidate": bool(compounding.get("runner_eligible_candidate", False)),
                            "add_on_research_candidate": bool(compounding.get("add_on_research_candidate", False)),
                            "patience_score": float(compounding.get("patience_score", 0.0) or 0.0),
                            "de_risk_score": float(compounding.get("de_risk_score", 0.0) or 0.0),
                        }
                    )
                    if scored["accepted"] and not portfolio.cooldown.active:
                        plan = build_trade_plan(scored, max_hold_bars=max_hold_bars)
                        risk_multiplier = float((convexity_profile or {}).get("risk_multiplier", 1.0))
                        quantity = compute_position_size(
                            active_capital=portfolio.profit_vault.active_trading_capital,
                            risk_per_trade_pct=float(self.config.require("risk", "risk_per_trade_pct")),
                            entry_price=plan["entry_price"],
                            stop_price=plan["stop_price"],
                            risk_multiplier=risk_multiplier,
                        )
                        portfolio.open_trade = {
                            "symbol": symbol,
                            "side": scored["side"],
                            "entry_time": scored["timestamp"],
                            "entry_price": plan["entry_price"],
                            "quantity": quantity,
                            "stop_price": plan["stop_price"],
                            "active_stop_price": plan["stop_price"],
                            "initial_target": plan["initial_target"],
                            "risk_per_unit": plan["risk_per_unit"],
                            "max_hold_bars": plan["max_hold_bars"],
                            "holding_bars": 0,
                            "setup_class": scored["classification"],
                            "entry_reason": scored["entry_reason"],
                            "add_on_count": 0,
                            "entry_score": float(scored["total_score"]),
                            "risk_multiplier": risk_multiplier,
                            "convexity_label": (convexity_profile or {}).get("label"),
                            "convexity_add_on_budget": int((convexity_profile or {}).get("add_on_budget", max_add_ons)),
                            "add_on_min_score": float((convexity_profile or {}).get("add_on_min_score", 0.0)),
                            "add_on_min_stop_upgrade_r": float((convexity_profile or {}).get("add_on_min_stop_upgrade_r", 0.0)),
                            "trail_activation_r": float((convexity_profile or {}).get("trail_activation_r", add_on_trigger_r)),
                            "profit_lock_floor_r": float((convexity_profile or {}).get("profit_lock_floor_r", profit_lock_floor_r)),
                            "cooldown_fast_clear_eligible": bool((convexity_profile or {}).get("cooldown_fast_clear_eligible", False)),
                            "personality_label": personality.get("personality_label"),
                            "personality_confidence": float(personality.get("personality_confidence", 0.0) or 0.0),
                            "pullback_type": pullback_features.get("pullback_type"),
                            "pullback_quality_score": float(pullback_features.get("pullback_quality_score", 0.0) or 0.0),
                            "pullback_entry_price": float(pullback_features.get("entry_candidate_price", plan["entry_price"]) or plan["entry_price"]),
                            "pullback_stop_price": float(pullback_features.get("stop_price", plan["stop_price"]) or plan["stop_price"]),
                            "pullback_r_improvement": float(pullback_features.get("r_improvement_vs_original", 0.0) or 0.0),
                            "compounding_readiness_score": float(compounding.get("compounding_readiness_score", 0.0) or 0.0),
                            "runner_label": compounding.get("runner_label"),
                            "add_on_research_candidate": bool(compounding.get("add_on_research_candidate", False)),
                            "patience_score": float(compounding.get("patience_score", 0.0) or 0.0),
                            "de_risk_score": float(compounding.get("de_risk_score", 0.0) or 0.0),
                        }
                        opened_trade = True
                        setup_decision = "opened"
                    elif scored["accepted"] and portfolio.cooldown.active:
                        setup_decision = "cooldown_blocked"

                    portfolio.setup_rows[-1]["decision"] = setup_decision
                    portfolio.setup_rows[-1]["opened"] = opened_trade

            current_equity = portfolio.profit_vault.total_equity
            portfolio.equity_curve.append(
                {
                    "timestamp": pd.Timestamp(timestamp).isoformat(),
                    "equity": current_equity,
                    "active_capital": portfolio.profit_vault.active_trading_capital,
                    "locked_profit": portfolio.profit_vault.locked_profit,
                }
            )

            processed_since_resume += 1
            if (
                checkpoint_every_bars > 0
                and processed_since_resume % checkpoint_every_bars == 0
            ):
                if write_partial_artifacts:
                    self._write_outputs(
                        symbol=symbol,
                        execution=execution.iloc[: position + 1],
                        portfolio=portfolio,
                        output_dir=output_dir,
                        source_csv=resolved_source_csv,
                        structure_window_bars=structure_window_bars,
                        liquidity_window_bars=liquidity_window_bars,
                        setup_window_bars=setup_window_bars,
                        recent_liquidity_bars=recent_liquidity_bars,
                        run_state="running",
                        resumed_from_checkpoint=resumed_from_checkpoint,
                        current_index=position + 1,
                        total_bars=len(execution),
                    )
                self._save_checkpoint(
                    store=checkpoint_store,
                    metadata=checkpoint_metadata,
                    next_index=position + 1,
                    total_bars=len(execution),
                    last_timestamp=pd.Timestamp(timestamp).isoformat(),
                    portfolio=portfolio,
                    seen_levels=seen_levels,
                    seen_liquidity=seen_liquidity,
                )
                self._write_phase_status(
                    paths=output_paths,
                    state="running",
                    current_index=position + 1,
                    total_bars=len(execution),
                    last_timestamp=pd.Timestamp(timestamp).isoformat(),
                    resumed_from_checkpoint=resumed_from_checkpoint,
                )

            if max_bars is not None and processed_since_resume >= int(max_bars):
                if write_partial_artifacts:
                    summary = self._write_outputs(
                        symbol=symbol,
                        execution=execution.iloc[: position + 1],
                        portfolio=portfolio,
                        output_dir=output_dir,
                        source_csv=resolved_source_csv,
                        structure_window_bars=structure_window_bars,
                        liquidity_window_bars=liquidity_window_bars,
                        setup_window_bars=setup_window_bars,
                        recent_liquidity_bars=recent_liquidity_bars,
                        run_state="interrupted",
                        resumed_from_checkpoint=resumed_from_checkpoint,
                        current_index=position + 1,
                        total_bars=len(execution),
                    )
                else:
                    summary = {}
                self._save_checkpoint(
                    store=checkpoint_store,
                    metadata=checkpoint_metadata,
                    next_index=position + 1,
                    total_bars=len(execution),
                    last_timestamp=pd.Timestamp(timestamp).isoformat(),
                    portfolio=portfolio,
                    seen_levels=seen_levels,
                    seen_liquidity=seen_liquidity,
                )
                self._write_phase_status(
                    paths=output_paths,
                    state="interrupted",
                    current_index=position + 1,
                    total_bars=len(execution),
                    last_timestamp=pd.Timestamp(timestamp).isoformat(),
                    resumed_from_checkpoint=resumed_from_checkpoint,
                )
                return summary

        summary = self._write_outputs(
            symbol=symbol,
            execution=execution,
            portfolio=portfolio,
            output_dir=output_dir,
            source_csv=resolved_source_csv,
            structure_window_bars=structure_window_bars,
            liquidity_window_bars=liquidity_window_bars,
            setup_window_bars=setup_window_bars,
            recent_liquidity_bars=recent_liquidity_bars,
            run_state="completed",
            resumed_from_checkpoint=resumed_from_checkpoint,
            current_index=len(execution),
            total_bars=len(execution),
        )
        self._save_checkpoint(
            store=checkpoint_store,
            metadata=checkpoint_metadata,
            next_index=len(execution),
            total_bars=len(execution),
            last_timestamp=(pd.Timestamp(execution.index[-1]).isoformat() if not execution.empty else None),
            portfolio=portfolio,
            seen_levels=seen_levels,
            seen_liquidity=seen_liquidity,
        )
        self._write_phase_status(
            paths=output_paths,
            state="completed",
            current_index=len(execution),
            total_bars=len(execution),
            last_timestamp=(pd.Timestamp(execution.index[-1]).isoformat() if not execution.empty else None),
            resumed_from_checkpoint=resumed_from_checkpoint,
        )
        return summary

    def _write_outputs(
        self,
        *,
        symbol: str,
        execution: pd.DataFrame,
        portfolio: StructuralPortfolioState,
        output_dir: str | None,
        source_csv: str | Path | None,
        structure_window_bars: int,
        liquidity_window_bars: int,
        setup_window_bars: int,
        recent_liquidity_bars: int,
        run_state: str,
        resumed_from_checkpoint: bool,
        current_index: int,
        total_bars: int,
    ) -> dict[str, Any]:
        paths = artifact_paths(self.config, output_dir=output_dir)

        equity_df = pd.DataFrame(portfolio.equity_curve)
        trades_df = pd.DataFrame(portfolio.trade_rows)
        setups_df = pd.DataFrame(portfolio.setup_rows)
        levels_df = pd.DataFrame(portfolio.level_rows)
        liquidity_df = pd.DataFrame(portfolio.liquidity_rows)
        cooldown_df = pd.DataFrame(portfolio.cooldown_rows)
        pyramiding_df = pd.DataFrame(portfolio.pyramiding_rows)

        equity_df.to_csv(paths["equity"], index=False)
        trades_df.to_csv(paths["trades"], index=False)
        setups_df.to_csv(paths["setup_log"], index=False)
        levels_df.to_csv(paths["level_log"], index=False)
        liquidity_df.to_csv(paths["liquidity_events"], index=False)
        cooldown_df.to_csv(paths["cooldown_log"], index=False)
        pyramiding_df.to_csv(paths["pyramiding_log"], index=False)
        write_json(paths["profit_vault"], portfolio.profit_vault.to_dict())

        ending_equity = portfolio.profit_vault.total_equity
        metrics = summarize_trades(
            portfolio.trade_rows,
            base_capital=portfolio.profit_vault.base_capital,
            ending_equity=ending_equity,
        )
        summary = {
            "lab_name": self.config.get("lab_name"),
            "symbol": symbol,
            "execution_timeframe": self.config.require("execution_timeframe"),
            "source_csv": str(source_csv) if source_csv is not None else None,
            "run_state": run_state,
            "resumed_from_checkpoint": bool(resumed_from_checkpoint),
            "progress": {
                "current_index": int(current_index),
                "total_bars": int(total_bars),
                "progress_pct": (float(current_index) / float(total_bars)) if total_bars else 0.0,
            },
            "current_equity": ending_equity,
            "ending_equity": ending_equity,
            "active_trading_capital": portfolio.profit_vault.active_trading_capital,
            "locked_profit": portfolio.profit_vault.locked_profit,
            "floating_profit": portfolio.profit_vault.floating_profit,
            "cooldown_active": portfolio.cooldown.active,
            "current_compounding_cycle": portfolio.profit_vault.current_compounding_cycle_id,
            "trade_count": len(portfolio.trade_rows),
            "setup_count": len(portfolio.setup_rows),
            "level_count": len(portfolio.level_rows),
            "liquidity_event_count": len(portfolio.liquidity_rows),
            "add_on_event_count": sum(1 for row in portfolio.pyramiding_rows if str(row.get("event_type") or row.get("add_type")) != "profit_lock"),
            "profit_lock_count": sum(1 for row in portfolio.pyramiding_rows if str(row.get("event_type")) == "profit_lock"),
            "cooldown_event_count": len(portfolio.cooldown_rows),
            "replay_checkpoint_timestamp": str(pd.Timestamp(execution.index[-1]).isoformat()) if not execution.empty else None,
            "run_context": {
                "loaded_history_start": str(pd.Timestamp(execution.index[0]).isoformat()) if not execution.empty else None,
                "loaded_history_end": str(pd.Timestamp(execution.index[-1]).isoformat()) if not execution.empty else None,
                "analysis_start_date": str(self.config.get("data", "analysis_start_date") or self.config.get("data", "history_start_date")),
                "analysis_end_date": str(self.config.get("data", "analysis_end_date") or self.config.get("data", "history_end_date")),
                "structure_window_bars": structure_window_bars,
                "liquidity_window_bars": liquidity_window_bars,
                "setup_window_bars": setup_window_bars,
                "recent_liquidity_bars": recent_liquidity_bars,
            },
            "metrics": metrics,
            "artifacts": {key: str(path) for key, path in paths.items()},
        }
        stories = [
            {
                "story_id": row.get("story_id") or f"{row.get('symbol', symbol)}-{row.get('timestamp')}",
                "symbol": row.get("symbol", symbol),
                "timestamp": row.get("timestamp"),
                "setup": {
                    "pattern": row.get("pattern"),
                    "side": row.get("side"),
                    "entry_price": row.get("pullback_entry_price") or row.get("target_price"),
                },
                "personality": {
                    "personality_label": row.get("personality_label"),
                    "personality_confidence": row.get("personality_confidence"),
                },
                "pullback": {
                    "pullback_type": row.get("pullback_type"),
                    "pullback_quality_score": row.get("pullback_quality_score"),
                },
                "compounding": {
                    "compounding_readiness_score": row.get("compounding_readiness_score"),
                    "runner_label": row.get("runner_label"),
                },
            }
            for row in portfolio.setup_rows
        ]
        diagnostics = write_research_artifacts(
            paths=paths,
            summary=summary,
            trades=portfolio.trade_rows,
            setup_rows=portfolio.setup_rows,
            stories=stories,
        )
        summary["research_diagnostics"] = diagnostics
        write_json(paths["summary"], summary)
        write_json(
            paths["status"],
            {
                "state": run_state,
                "updated_at_utc": pd.Timestamp.now("UTC").isoformat(),
                "current_index": int(current_index),
                "total_bars": int(total_bars),
                "progress_pct": (float(current_index) / float(total_bars)) if total_bars else 0.0,
                "replay_checkpoint_timestamp": summary.get("replay_checkpoint_timestamp"),
                "resumed_from_checkpoint": bool(resumed_from_checkpoint),
            },
        )
        write_json(
            paths["scenario_progress"],
            {
                "run_state": run_state,
                "current_index": int(current_index),
                "total_bars": int(total_bars),
                "progress_pct": (float(current_index) / float(total_bars)) if total_bars else 0.0,
                "replay_checkpoint_timestamp": summary.get("replay_checkpoint_timestamp"),
                "resumed_from_checkpoint": bool(resumed_from_checkpoint),
            },
        )
        write_structural_report(paths["report"], summary=summary, settings=self.config.data)
        return summary
