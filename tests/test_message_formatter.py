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


def test_format_unified_feed_report() -> None:
    from utils.message_formatter import format_unified_feed_report
    from utils.crypto_market_intelligence import IntelligenceReport, IntelligenceSignal
    from datetime import datetime, timezone

    # 1. Mock general markets
    class MockMarket:
        def __init__(self, question, yes_price):
            self.question = question
            self.yes_price = yes_price
            self.probability_pct = yes_price * 100.0

    markets_general = [
        MockMarket("Will Aberdeen FC win on 2026-05-17?", 0.33),
        MockMarket("Will SD Huesca win on 2026-05-18?", 0.76)
    ]

    # 2. Mock intelligence report
    signals = [
        IntelligenceSignal(
            market_slug="will-ethereum-dip-to-1500-by-december-31-2026",
            question="Will Ethereum dip to 1500 by December 31, 2026?",
            asset="ETH",
            signal_type="liquidity_focus",
            direction="MONITOR",
            score=1.0,
            confidence=1.0,
            yes_price=0.44,
            no_price=0.56,
            volume=500000.0,
            liquidity=50000.0,
            rationale=["probabilite equilibree avec activite exploitable"]
        )
    ]

    report = IntelligenceReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        source="test",
        market_count=100,
        crypto_market_count=6,
        opportunities=signals,
        risk_flags=signals,
        watchlist=["BTC", "ETH", "SOL"],
        summary={
            "total_crypto_volume": 1286218.0,
            "total_crypto_liquidity": 116555.0,
            "avg_signal_confidence": 0.91,
            "opportunity_count": 1,
            "risk_flag_count": 1,
        }
    )

    text = format_unified_feed_report(markets_general, report)

    assert "LIVE MARKET FEED" in text
    assert "Will Aberdeen FC win on 2026-05-17?" in text
    assert "<code>███░░░░░░░</code> <code>33%</code>" in text
    assert "Lobstar Crypto Intelligence" in text
    assert "NEUTRE" in text or "BULLISH" in text or "BEARISH" in text
    assert "will-ethereum-dip-to-1500-by-december-31-2026" in text
