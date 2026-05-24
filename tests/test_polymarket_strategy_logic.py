from __future__ import annotations

from strategies.polymarket_strategy_factory import (
    CalendarEventStrategy,
    ContrarianExcessStrategy,
    DirectionalConvictionStrategy,
    NewsDrivenStrategy,
    OpportunisticLiquidityTakerStrategy,
    PairsTradingStrategy,
)


def test_news_driven_strategy_requires_real_catalyst_or_strong_news() -> None:
    strategy = NewsDrivenStrategy()

    assert strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "MKT1",
            "price": 0.4,
            "spread": 0.01,
            "sentiment_score": 0.1,
            "metadata": {"news_score": 0.2, "source_reliability": 0.2},
        }
    ) is None

    signal = strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "MKT1",
            "price": 0.4,
            "spread": 0.01,
            "sentiment_score": 0.8,
            "metadata": {"news_score": 0.9, "source_reliability": 0.8, "catalyst_summary": "policy shock"},
        }
    )
    assert signal is not None
    assert signal.side == "BUY"


def test_calendar_event_strategy_ignores_distant_events() -> None:
    strategy = CalendarEventStrategy()

    assert strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "MKT1",
            "price": 0.55,
            "spread": 0.01,
            "metadata": {"hours_to_known_event": 72, "expected_event_move": 0.05},
        }
    ) is None

    signal = strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "MKT1",
            "price": 0.55,
            "spread": 0.01,
            "metadata": {"hours_to_known_event": 6, "expected_event_move": 0.05},
        }
    )
    assert signal is not None
    assert signal.side == "BUY"


def test_pairs_trading_requires_hedge_and_large_deviation() -> None:
    strategy = PairsTradingStrategy()

    assert strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "PAIR",
            "price": 0.4,
            "spread": 0.01,
            "metadata": {"pair_spread_zscore": -3.0, "hedge_market_available": False},
        }
    ) is None

    signal = strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "PAIR",
            "price": 0.4,
            "spread": 0.01,
            "metadata": {"pair_spread_zscore": -3.0, "hedge_market_available": True},
        }
    )
    assert signal is not None
    assert signal.side == "BUY"


def test_directional_conviction_requires_alignment_and_non_erratic_regime() -> None:
    strategy = DirectionalConvictionStrategy()

    assert strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "DIR",
            "price": 0.4,
            "spread": 0.01,
            "ml_probability": 0.6,
            "semantic_confidence": 0.9,
            "sentiment_score": -0.8,
            "hmm_regime": "TREND",
        }
    ) is None

    assert strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "DIR",
            "price": 0.4,
            "spread": 0.01,
            "ml_probability": 0.6,
            "semantic_confidence": 0.9,
            "sentiment_score": 0.8,
            "hmm_regime": "ERRATIC_VOLATILITY",
        }
    ) is None

    signal = strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "DIR",
            "price": 0.4,
            "spread": 0.01,
            "ml_probability": 0.75,
            "semantic_confidence": 0.9,
            "sentiment_score": 0.9,
            "hmm_regime": "BULL_TREND",
        }
    )
    assert signal is not None
    assert signal.side == "BUY"


def test_contrarian_excess_fades_extreme_sentiment_only() -> None:
    strategy = ContrarianExcessStrategy()

    assert strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "CTR",
            "price": 0.4,
            "spread": 0.01,
            "sentiment_score": 0.2,
        }
    ) is None

    signal = strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "CTR",
            "price": 0.4,
            "spread": 0.01,
            "sentiment_score": 0.9,
        }
    )
    assert signal is not None
    assert signal.side == "SELL"


def test_opportunistic_liquidity_taker_requires_depth_and_edge() -> None:
    strategy = OpportunisticLiquidityTakerStrategy()

    assert strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "TAKER",
            "price": 0.4,
            "spread": 0.01,
            "ml_probability": 0.5,
            "metadata": {"stale_quote_edge": 0.08, "available_depth_usdc": 0},
        }
    ) is None

    signal = strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "TAKER",
            "price": 0.4,
            "spread": 0.01,
            "ml_probability": 0.55,
            "metadata": {"stale_quote_edge": 0.08, "available_depth_usdc": 250},
        }
    )
    assert signal is not None
    assert signal.order_type == "MARKET"
