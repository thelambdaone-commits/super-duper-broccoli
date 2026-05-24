from __future__ import annotations

from utils.crypto_horizon_sentiment import (
    CryptoHorizonSentiment,
    format_horizon_sentiment,
    normalize_horizon,
)
from utils.market_scanner import MarketScanner, MarketSignal
from utils.polymarket_client import Market


def make_market(slug: str, question: str, yes: float, no: float, volume: float = 10_000) -> Market:
    return Market(
        condition_id=f"cond-{slug}",
        slug=slug,
        question=question,
        description="",
        outcomes=["Yes", "No"],
        outcome_prices=[yes, no],
        tokens=[
            {"outcome": "Yes", "token_id": f"{slug}-yes"},
            {"outcome": "No", "token_id": f"{slug}-no"},
        ],
        active=True,
        closed=False,
        volume=volume,
        liquidity=5_000,
    )


class FakeClient:
    def __init__(self, markets):
        self.markets = markets

    def list_markets(self, limit=150, sort_by="volume"):
        return self.markets[:limit]

    def get_order_book(self, token_id):
        return {"active": True, "closed": False, "archived": False, "token_id": token_id}


def test_normalize_horizon() -> None:
    assert normalize_horizon("5m") == "5"
    assert normalize_horizon("15") == "15"
    assert normalize_horizon("1") == "1h"


def test_horizon_sentiment_bullish_exact_market() -> None:
    analyzer = CryptoHorizonSentiment(
        client=FakeClient([
            make_market("bitcoin-updown-15m-1", "Bitcoin up or down 15 minutes?", 0.72, 0.28),
        ])
    )

    sentiment = analyzer.analyze("BTC", "15")

    assert sentiment is not None
    assert sentiment.sentiment == "BULLISH"
    assert sentiment.probability == 0.72
    assert sentiment.horizon == "15"


def test_horizon_sentiment_bearish_for_dip_market() -> None:
    analyzer = CryptoHorizonSentiment(
        client=FakeClient([
            make_market("solana-dip-5m", "Will Solana dip in the next 5 minutes?", 0.78, 0.22),
        ])
    )

    sentiment = analyzer.analyze("SOL", "5")

    assert sentiment is not None
    assert sentiment.sentiment == "BEARISH"
    assert sentiment.probability == 0.78


def test_format_horizon_sentiment_plain_text() -> None:
    analyzer = CryptoHorizonSentiment(
        client=FakeClient([
            make_market("xrp-updown-1h", "XRP up or down 1 hour?", 0.51, 0.49),
        ])
    )
    text = format_horizon_sentiment(analyzer.analyze("XRP", "1h"), "XRP", "1h")

    assert "LOBSTAR CRYPTO SENTIMENT — XRP (1h)" in text
    assert "*" not in text
    assert "`" not in text


def test_end_date_naive_tz() -> None:
    from datetime import datetime, timezone, timedelta
    naive_future_date = (datetime.now(timezone.utc) + timedelta(minutes=10)).strftime("%Y-%m-%dT%H:%M:%S")
    market = make_market("btc-updown-5m", "BTC up or down 5m?", 0.65, 0.35)
    market.end_date = naive_future_date

    analyzer = CryptoHorizonSentiment(client=FakeClient([market]))
    assert analyzer._matches_horizon(market, "15") is True


def test_midpoint_fallback_for_zero_prices() -> None:
    class MockClient:
        def __init__(self):
            pass
        def list_markets(self, limit=150, sort_by="volume"):
            m = make_market("btc-updown-5m", "BTC up or down 5m?", 0.0, 0.0)
            m.tokens = [{"outcome": "Yes", "token_id": "yes-token-id"}]
            return [m]
        def get_midpoint(self, token_id):
            if token_id == "yes-token-id":
                return 0.75
            return 0.0

    analyzer = CryptoHorizonSentiment(client=MockClient())
    sentiment = analyzer.analyze("BTC", "5")

    assert sentiment is not None
    assert sentiment.sentiment == "BULLISH"
    assert sentiment.yes_price == 0.75
    assert sentiment.no_price == 0.25
    assert sentiment.probability == 0.75


def test_composite_proxy_fallback_when_no_candidates() -> None:
    class MockClient:
        def list_markets(self, limit=150, sort_by="volume"):
            m1 = make_market("btc-updown-5m", "BTC up or down 5m?", 0.70, 0.30)
            m1.volume = 1000
            m2 = make_market("eth-updown-5m", "ETH up or down 5m?", 0.60, 0.40)
            m2.volume = 2000
            return [m1, m2]

    analyzer = CryptoHorizonSentiment(client=MockClient())
    sentiment = analyzer.analyze("XRP", "5")

    assert sentiment is not None
    assert sentiment.asset == "XRP"
    assert sentiment.market_slug == "composite-proxy-btc-eth-sol"
    assert sentiment.sentiment == "BULLISH"
    assert sentiment.yes_price == 0.65
    assert sentiment.no_price == 0.35
    assert sentiment.probability == 0.65
    assert sentiment.volume == 3000.0
    assert "Correlation composite hedge" in sentiment.rationale


def test_market_with_up_down_outcomes() -> None:
    # A market with outcomes other than Yes/No, e.g. Up/Down
    m = Market(
        condition_id="cond-updown",
        slug="btc-updown-15m-12345",
        question="Bitcoin Up or Down?",
        description="",
        outcomes=["Up", "Down"],
        outcome_prices=[0.55, 0.45],
        tokens=[
            {"outcome": "Up", "token_id": "token-up"},
            {"outcome": "Down", "token_id": "token-down"},
        ],
        active=True,
        closed=False,
        volume=10_000,
        liquidity=5_000,
    )

    # Verify generalized outcome_prices mappings on Market property methods
    assert m.yes_price == 0.55
    assert m.no_price == 0.45
    assert m.yes_token_id == "token-up"
    assert m.no_token_id == "token-down"

    # Also verify that the analyzer is able to analyze it properly
    analyzer = CryptoHorizonSentiment(client=FakeClient([m]))
    sentiment = analyzer.analyze("BTC", "15")
    assert sentiment is not None
    assert sentiment.sentiment == "NEUTRAL"  # 0.55 is < 0.62, so NEUTRAL
    assert sentiment.yes_price == 0.55
    assert sentiment.no_price == 0.45


def test_market_scanner_prefers_high_quality_non_proxy_signals() -> None:
    scanner = MarketScanner(client=FakeClient([]))
    scanner._last_scan = type(
        "Scan",
        (),
        {
            "winning_bets": [
                MarketSignal(
                    ticker="eth-above-4000",
                    token_id="eth-above-4000-yes",
                    side="BUY",
                    price=0.61,
                    confidence=0.92,
                    reason="Imminent resolution: YES at 78%",
                    market_question="Will ETH be above 4000?",
                    market_slug="eth-above-4000",
                    current_prob=78.0,
                    volume=250_000,
                    sentiment="BULLISH",
                    direction="📈 UP",
                )
            ],
            "trending_markets": [],
            "competitive_markets": [
                MarketSignal(
                    ticker="composite",
                    token_id="composite-yes",
                    side="BUY",
                    price=0.52,
                    confidence=0.75,
                    reason="Competitive market: spread 1.2%",
                    market_question="Correlation Composite Proxy Sentiment (BTC/ETH/SOL)",
                    market_slug="composite-proxy-btc-eth-sol",
                    current_prob=52.0,
                    volume=500_000,
                    sentiment="NEUTRAL",
                    direction="📈 UP",
                )
            ],
            "arbitrage_opportunities": [],
        },
    )()

    best = scanner.best_tradeable_signals(limit=1)
    assert best
    assert best[0].market_slug == "eth-above-4000"


def test_market_scanner_scan_markets_populates_token_ids() -> None:
    market = make_market("btc-above-100k", "Will BTC be above 100k?", 0.55, 0.45, volume=50_000)
    scanner = MarketScanner(client=FakeClient([market]))

    result = scanner.scan_markets()

    signals = result.trending_markets + result.competitive_markets + result.winning_bets + result.arbitrage_opportunities
    assert signals
    assert all(sig.token_id for sig in signals)


def test_best_tradeable_signals_skips_inactive_orderbooks() -> None:
    class _BookClient(FakeClient):
        def get_order_book(self, token_id):
            if token_id == "dead-token":
                return {"active": False, "closed": True, "archived": False}
            return {"active": True, "closed": False, "archived": False}

    scanner = MarketScanner(client=_BookClient([]))
    scanner._last_scan = type(
        "Scan",
        (),
        {
            "winning_bets": [
                MarketSignal(
                    ticker="dead-market",
                    token_id="dead-token",
                    side="BUY",
                    price=0.75,
                    confidence=0.99,
                    reason="Imminent resolution",
                    market_question="Dead market?",
                    market_slug="dead-market",
                    current_prob=75.0,
                    volume=300_000,
                    sentiment="BULLISH",
                    direction="📈 UP",
                ),
                MarketSignal(
                    ticker="live-market",
                    token_id="live-token",
                    side="BUY",
                    price=0.71,
                    confidence=0.90,
                    reason="Imminent resolution",
                    market_question="Live market?",
                    market_slug="live-market",
                    current_prob=71.0,
                    volume=250_000,
                    sentiment="BULLISH",
                    direction="📈 UP",
                ),
            ],
            "trending_markets": [],
            "competitive_markets": [],
            "arbitrage_opportunities": [],
        },
    )()

    best = scanner.best_tradeable_signals(limit=2)

    assert [sig.market_slug for sig in best] == ["live-market"]
