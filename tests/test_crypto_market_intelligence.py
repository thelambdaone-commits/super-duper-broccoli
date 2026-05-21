from utils.crypto_market_intelligence import (
    CryptoMarketIntelligence,
    format_intelligence_report,
    report_to_json,
)
from utils.market_scanner import MarketScanner
from utils.polymarket_client import Market


def make_market(
    slug: str,
    question: str,
    yes: float,
    no: float,
    volume: float = 50_000,
    liquidity: float = 10_000,
    description: str = "",
) -> Market:
    return Market(
        condition_id=f"cond-{slug}",
        slug=slug,
        question=question,
        description=description,
        outcomes=["Yes", "No"],
        outcome_prices=[yes, no],
        tokens=[
            {"outcome": "Yes", "token_id": f"{slug}-yes"},
            {"outcome": "No", "token_id": f"{slug}-no"},
        ],
        active=True,
        closed=False,
        volume=volume,
        liquidity=liquidity,
    )


def test_analyze_filters_crypto_markets() -> None:
    platform = CryptoMarketIntelligence()
    report = platform.analyze([
        make_market("bitcoin-ath", "Will Bitcoin hit a new all time high?", 0.55, 0.45),
        make_market("election", "Will candidate A win?", 0.52, 0.48),
    ])

    assert report.market_count == 2
    assert report.crypto_market_count == 1
    assert report.opportunities
    assert report.opportunities[0].asset == "BTC"


def test_thin_liquidity_is_risk_flag() -> None:
    platform = CryptoMarketIntelligence(min_liquidity=5_000)
    report = platform.analyze([
        make_market(
            "solana-thin",
            "Will Solana close above 200?",
            0.58,
            0.42,
            volume=30_000,
            liquidity=100,
        )
    ])

    assert report.risk_flags
    assert report.risk_flags[0].signal_type == "thin_liquidity"
    assert report.risk_flags[0].direction == "AVOID"


def test_short_crypto_tickers_do_not_match_word_fragments() -> None:
    platform = CryptoMarketIntelligence()
    report = platform.analyze([
        make_market(
            "esports-teams-slay-dragon",
            "Will both teams slay the dragon in game one?",
            0.95,
            0.05,
        ),
        make_market(
            "solana-close-above-200",
            "Will SOL close above 200?",
            0.55,
            0.45,
        ),
    ])

    assert report.crypto_market_count == 1
    assert report.opportunities[0].asset == "SOL"


def test_extreme_probability_is_crowded_flag() -> None:
    platform = CryptoMarketIntelligence()
    report = platform.analyze([
        make_market("eth-extreme", "Will Ethereum ETF volume exceed target?", 0.95, 0.05)
    ])

    assert report.risk_flags
    assert report.risk_flags[0].signal_type == "crowded_probability"


def test_report_format_and_json_are_stable() -> None:
    platform = CryptoMarketIntelligence()
    report = platform.analyze([
        make_market("btc-balanced", "Will BTC trade above 100k this month?", 0.51, 0.49)
    ])

    text = format_intelligence_report(report)
    payload = report_to_json(report)

    assert "Lobstar Crypto Intelligence" in text
    assert "conf." in text
    assert "Commandes" in text
    assert "*" not in text
    assert "`" not in text
    assert '"crypto_market_count": 1' in payload


def test_market_scanner_crypto_filter_rejects_non_crypto_winners() -> None:
    scanner = MarketScanner()

    assert not scanner._is_crypto_market(
        make_market(
            "california-governor-election",
            "Will Eleni Kounalakis win the California Governor Election?",
            0.01,
            0.99,
        )
    )
    assert not scanner._is_crypto_market(
        make_market(
            "f1-drivers-champion",
            "Will Arvid Lindblad be the 2026 F1 Drivers' Champion?",
            0.01,
            0.99,
        )
    )
    assert scanner._is_crypto_market(
        make_market(
            "bitcoin-above-80k",
            "Will Bitcoin trade above 80k?",
            0.55,
            0.45,
        )
    )
