from __future__ import annotations

from decimal import Decimal

from structural_compounding_lab.execution.live_strategy_canary_bridge import _entry_email, _exit_email


def _disable_smtp(monkeypatch) -> None:
    monkeypatch.setenv("RTS_ALERT_EMAIL_TO", "test@example.com")
    monkeypatch.setenv("RTS_ALERT_EMAIL_ENABLED", "false")
    monkeypatch.delenv("RTS_ALERT_SMTP_HOST", raising=False)
    monkeypatch.delenv("RTS_ALERT_EMAIL_FROM", raising=False)


def test_entry_email_writes_clear_plain_and_html_artifacts(tmp_path, monkeypatch) -> None:
    _disable_smtp(monkeypatch)
    record = _entry_email(
        tmp_path,
        {
            "source_symbol": "ADAUSDT",
            "symbol": "ADAUSDC",
            "quote_asset": "USDC",
            "base_asset": "ADA",
            "source_trade_id": "ADAUSDT-1",
            "source_timestamp": "2026-07-05T00:00:00+00:00",
            "entry_exchange_order_id": "123",
            "entry_executed_qty": "10",
            "entry_quote_filled": "6.00000000",
            "estimated_total_equity_quote_after_entry": Decimal("111.1234"),
            "entry_reference": "0.50",
            "stop_reference": "0.49",
            "target_reference": "0.55",
            "setup_class": "A",
            "convexity_label": "elite_convexity",
            "conviction_tier": "elite",
            "research_sizing_profile": "a_plus_2p50_elite_3p00_total_5p00; live canary remains capped",
            "max_order_notional_quote": Decimal("6"),
        },
    )

    text = (tmp_path / "alerts" / "latest_live_canary_email.txt").read_text()
    html = (tmp_path / "alerts" / "latest_live_canary_email.html").read_text()
    assert "BUY FILLED: 6 USDC" in text
    assert "Estimated total canary equity after entry: 111.1234 USDC" in text
    assert "Conviction tier: elite" in text
    assert "Research sizing profile: a_plus_2p50_elite_3p00_total_5p00; live canary remains capped" in text
    assert "Live canary sizing: tiny fixed cap" in text
    assert "Exit email is sent only after a later SELL fill" in text
    assert "BUY filled: 6 USDC" in html
    assert "Estimated total canary equity after entry" in html
    assert "A+/Elite research sizing label" in html
    assert record["email_sent"] is False


def test_exit_email_profit_has_congratulations_pnl_and_total_equity(tmp_path, monkeypatch) -> None:
    _disable_smtp(monkeypatch)
    record = _exit_email(
        tmp_path,
        {
            "symbol": "ADAUSDC",
            "quote_asset": "USDC",
            "source_trade_id": "ADAUSDT-1",
            "entry_client_order_id": "entry-1",
            "exit_client_order_id": "exit-1",
            "entry_quote_filled": "6",
            "exit_quote_filled": "6.45",
            "quote_delta": Decimal("0.438"),
            "base_delta": "0",
            "estimated_total_equity_quote_after_exit": Decimal("111.438"),
            "exit_reason": "target_reference_reached",
            "result_label": "PROFIT",
            "setup_class": "A",
            "convexity_label": "elite_convexity",
            "conviction_tier": "elite",
            "research_sizing_profile": "a_plus_2p50_elite_3p00_total_5p00; live canary remains capped",
        },
    )

    text = (tmp_path / "alerts" / "latest_live_canary_email.txt").read_text()
    html = (tmp_path / "alerts" / "latest_live_canary_email.html").read_text()
    assert "CONGRATULATIONS — PROFIT +0.438 USDC" in text
    assert "Total canary equity after exit: 111.438 USDC" in text
    assert "Subject: RTS LIVE CANARY EXIT CONGRATULATIONS PROFIT [ELITE]" in text
    assert "Conviction tier: elite" in text
    assert "CONGRATULATIONS" in html
    assert "+0.438 USDC" in html
    assert "111.438 USDC" in html
    assert "A+/Elite research sizing label" in html
    assert record["email_sent"] is False


def test_exit_email_loss_uses_loss_control_not_profit(tmp_path, monkeypatch) -> None:
    _disable_smtp(monkeypatch)
    _exit_email(
        tmp_path,
        {
            "symbol": "BTCUSDC",
            "quote_asset": "USDC",
            "source_trade_id": "BTCUSDT-1",
            "entry_client_order_id": "entry-1",
            "exit_client_order_id": "exit-1",
            "entry_quote_filled": "6",
            "exit_quote_filled": "5.90",
            "quote_delta": Decimal("-0.112"),
            "base_delta": "0",
            "estimated_total_equity_quote_after_exit": Decimal("110.888"),
            "exit_reason": "stop_reference_reached",
            "result_label": "LOSS",
        },
    )

    text = (tmp_path / "alerts" / "latest_live_canary_email.txt").read_text()
    assert "OOPS — LOSS -0.112 USDC" in text
    assert "CONGRATULATIONS — PROFIT" not in text
