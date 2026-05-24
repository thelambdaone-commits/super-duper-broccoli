from __future__ import annotations

from strategies.polymarket_strategy_factory import build_default_polymarket_strategies


def test_default_catalog_covers_required_polymarket_strategy_families() -> None:
    strategies = build_default_polymarket_strategies()
    ids = {strategy.strategy_id for strategy in strategies}

    expected = {
        "passive_market_making",
        "dynamic_market_making",
        "momentum_breakout",
        "mean_reversion",
        "micro_scalping",
        "swing_catalyst",
        "directional_conviction",
        "contrarian_excess",
        "inter_market_arbitrage",
        "intra_market_arbitrage",
        "bundle_spread_arbitrage",
        "public_oracle_lag",
        "semantic_momentum",
        "news_driven",
        "calendar_event",
        "public_onchain_flow",
        "expected_value",
        "bayesian_update",
        "monte_carlo_edge",
        "pairs_trading",
        "opportunistic_liquidity_taker",
    }

    assert expected.issubset(ids)
    assert "sandwich_like" not in ids


def test_representative_strategies_emit_standard_execution_signals() -> None:
    strategies = {strategy.strategy_id: strategy for strategy in build_default_polymarket_strategies()}
    feature = {
        "market_id": "m1",
        "ticker": "MKT1",
        "price": 0.40,
        "bid_price": 0.39,
        "ask_price": 0.41,
        "spread": 0.02,
        "order_imbalance": 0.10,
        "ml_probability": 0.48,
        "sentiment_score": 0.7,
        "semantic_confidence": 0.8,
        "external_price": 0.47,
        "metadata": {
            "rolling_mean_price": 0.48,
            "momentum_1m": 0.04,
            "volume_zscore": 1.5,
            "news_score": 0.7,
            "source_reliability": 0.8,
            "posterior_probability": 0.49,
            "monte_carlo_probability": 0.50,
            "outcome_total_probability": 1.05,
            "known_wallet_flow_score": 0.6,
            "hours_to_known_event": 12,
            "expected_event_move": 0.04,
            "pair_spread_zscore": -2.5,
            "hedge_market_available": True,
            "stale_quote_edge": 0.06,
            "available_depth_usdc": 100,
        },
    }

    for strategy_id in ("expected_value", "bayesian_update", "monte_carlo_edge", "momentum_breakout"):
        signal = strategies[strategy_id].generate_signal(feature)
        assert signal is not None, strategy_id
        payload = signal.to_execution_signal()
        assert payload["strategy_id"] == strategy_id
        assert payload["ticker"] == "MKT1"
        assert payload["predictive_edge"] != 0
