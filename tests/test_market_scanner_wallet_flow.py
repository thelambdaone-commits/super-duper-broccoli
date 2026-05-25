from __future__ import annotations

from dataclasses import dataclass

from utils.market_scanner import MarketScanner, MarketSignal, ScanResult
from utils.wallet_flow_service import WalletMarketFlow


@dataclass
class _StubWalletFlowService:
    def refresh_scores(self, force: bool = False):
        return {
            "btc-above-100k": WalletMarketFlow(
                market_slug="btc-above-100k",
                score=0.75,
                trade_count=4,
                wallet_count=2,
                last_updated=0.0,
            )
        }


def test_strategy_features_include_known_wallet_flow_score() -> None:
    scanner = MarketScanner(wallet_flow_service=_StubWalletFlowService())
    scanner._last_scan = ScanResult(
        timestamp="2026-01-01T00:00:00Z",
        winning_bets=[
            MarketSignal(
                ticker="btc-above-100k",
                side="BUY",
                price=0.62,
                confidence=0.8,
                reason="wallet flow",
                market_question="Will BTC go above 100k?",
                market_slug="btc-above-100k",
                current_prob=62.0,
                volume=100000.0,
                sentiment="BULLISH",
                direction="📈 UP",
            )
        ],
        total_markets_scanned=1,
    )
    scanner._refresh_wallet_flow_scores()

    rows = scanner.get_strategy_features()

    assert rows
    assert rows[0]["metadata"]["known_wallet_flow_score"] == 0.75


def test_strategy_features_normalize_buy_signal_to_yes_probability() -> None:
    scanner = MarketScanner()
    scanner._last_scan = ScanResult(
        timestamp="2026-01-01T00:00:00Z",
        winning_bets=[
            MarketSignal(
                ticker="btc-above-100k",
                side="BUY",
                price=0.62,
                confidence=0.8,
                reason="momentum",
                market_question="Will BTC go above 100k?",
                market_slug="btc-above-100k",
                current_prob=62.0,
                volume=100000.0,
                sentiment="BULLISH",
                direction="📈 UP",
            )
        ],
        total_markets_scanned=1,
    )

    [row] = scanner.get_strategy_features()

    assert row["price"] == 0.62
    assert row["ml_probability"] > row["price"]
    assert row["metadata"]["estimated_probability"] == row["ml_probability"]
    assert row["metadata"]["quoted_outcome_price"] == 0.62


def test_strategy_features_normalize_sell_signal_to_yes_probability() -> None:
    scanner = MarketScanner()
    scanner._last_scan = ScanResult(
        timestamp="2026-01-01T00:00:00Z",
        winning_bets=[
            MarketSignal(
                ticker="btc-below-100k",
                side="SELL",
                price=0.38,
                confidence=0.8,
                reason="mean reversion",
                market_question="Will BTC go above 100k?",
                market_slug="btc-below-100k",
                current_prob=62.0,
                volume=100000.0,
                sentiment="BEARISH",
                direction="📉 DOWN",
            )
        ],
        total_markets_scanned=1,
    )

    [row] = scanner.get_strategy_features()

    assert row["price"] == 0.62
    assert row["ml_probability"] < row["price"]
    assert row["metadata"]["estimated_probability"] == row["ml_probability"]
    assert row["metadata"]["quoted_outcome_price"] == 0.38
