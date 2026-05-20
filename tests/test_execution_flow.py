import pandas as pd
from models.predictive_engine import PolymarketPredictiveEngine


def test_predictive_engine_min_edge_rejection() -> None:
    """Verifies that signals with edges < 7% are rejected, and >= 7% are approved."""
    # Initialize engine with 7% edge threshold
    engine = PolymarketPredictiveEngine(min_edge_threshold=0.07, allow_mock_predictions=True)

    # 1. Edge < 7% (probability 55%, price 0.50 -> edge 5%)
    engine._get_mock_prediction = lambda: 0.55
    res = engine.predict_winning_bet(
        df_market_ticks=pd.DataFrame(),
        clob_price_yes=0.50,
        timestamp_resolution=9999999999.0
    )
    assert not res["pari_approuve"]
    assert res["conclusion"] == "REJECT_NO_EDGE"

    # 2. Edge >= 7% (probability 65%, price 0.50 -> edge 15%)
    engine._get_mock_prediction = lambda: 0.65
    res = engine.predict_winning_bet(
        df_market_ticks=pd.DataFrame(),
        clob_price_yes=0.50,
        timestamp_resolution=9999999999.0
    )
    assert res["pari_approuve"]
    assert res["conclusion"] == "EXECUTE_TRADE"


def test_predictive_engine_kelly_sizing() -> None:
    """Validates that edge-based Kelly Sizing matches correct mathematical payout fractions."""
    engine = PolymarketPredictiveEngine(min_edge_threshold=0.07)

    # Probability = 60%, Price = 0.50
    # payout = (1.0 - 0.5) / 0.5 = 1.0
    # q = 0.40
    # kelly = (0.6 * 1.0 - 0.4) / 1.0 = 0.20
    size = engine.calculate_kelly_size(probability_win=0.60, clob_price=0.50)
    assert abs(size - 0.20) < 1e-4

    # Probability = 52%, Price = 0.50
    # payout = 1.0
    # q = 0.48
    # kelly = (0.52 * 1.0 - 0.48) / 1.0 = 0.04
    size = engine.calculate_kelly_size(probability_win=0.52, clob_price=0.50)
    assert abs(size - 0.04) < 1e-4
