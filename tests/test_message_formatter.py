from utils.message_formatter import InstitutionalMessageFormatter


def test_trade_execution_html_escapes_content_and_failed_status() -> None:
    text = InstitutionalMessageFormatter.format_trade_execution_html(
        {
            "status": "failed",
            "ticker": "BTC <spot>",
            "side": "BUY",
            "probability": 0.72,
            "kelly_pct": 4.25,
            "reason_1": "Momentum < invalid",
            "trade_id": "abc<123>",
        }
    )

    assert "<b>TRADE FAILED</b>" in text
    assert "BTC &lt;spot&gt;" in text
    assert "Momentum &lt; invalid" in text
    assert "#abc&lt;123&gt;" in text
    assert "TRADE EXECUTED" not in text
