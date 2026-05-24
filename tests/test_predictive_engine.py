import time

import numpy as np
import pandas as pd

from schemas.prediction import PolymarketPredictiveEngine


class StaticModel:
    def __init__(self, probability: float) -> None:
        self.probability = probability

    def predict_proba(self, X):
        return np.array([[1.0 - self.probability, self.probability]])


class IdentityPipeline:
    def transform(self, df):
        return df.values


def test_predictive_engine_rejects_when_no_model_and_mock_disabled() -> None:
    engine = PolymarketPredictiveEngine(allow_mock_predictions=False)
    result = engine.predire_pari_gagnant(
        pd.DataFrame([[1.0, 2.0]]),
        clob_price_yes=0.5,
        timestamp_resolution=time.time() + 3600,
    )
    assert result["pari_approuve"] is False
    assert result["conclusion"] == "REJECT_NO_MODEL"
    assert result["probability_win"] == 0.5


def test_predictive_engine_stacks_ensemble_probabilities() -> None:
    engine = PolymarketPredictiveEngine(
        models_ensemble={
            "xgb": StaticModel(0.70),
            "lgbm": StaticModel(0.80),
            "rf": StaticModel(0.60),
        },
        feature_pipeline=IdentityPipeline(),
        min_edge_threshold=0.01,
        allow_mock_predictions=False,
    )
    result = engine.predire_pari_gagnant(
        pd.DataFrame([[1.0, 2.0]]),
        clob_price_yes=0.55,
        timestamp_resolution=time.time() + 3600,
    )
    assert result["conclusion"] == "EXECUTE_TRADE"
    assert result["probability_win"] > 0.55
    assert result["absolute_edge"] > 0.01


def test_time_decay_accepts_epoch_resolution_timestamp() -> None:
    engine = PolymarketPredictiveEngine()
    decayed = engine._calculer_time_decay(0.80, time.time() + 3600)
    assert 0.50 < decayed <= 0.80


def test_kelly_size_rejects_invalid_prices() -> None:
    engine = PolymarketPredictiveEngine()
    assert engine.calculate_kelly_size(0.9, 0.0) == 0.0
    assert engine.calculate_kelly_size(0.9, 1.0) == 0.0
