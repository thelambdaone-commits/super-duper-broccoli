import json
import os
import tempfile

import pytest

from core.ml_bridge import TrainingPipelinePredictiveAdapter
from core.services.predictive_gate import PredictiveGateConfig, PredictiveGateService
from core.training_pipeline import TrainingPipeline
from scrapers.clob_listener import CLOBListener
from utils.feature_store import FeatureStore


@pytest.fixture
def feature_store() -> FeatureStore:
    path = os.path.join(tempfile.gettempdir(), "test_ml_integration_live_features.duckdb")
    if os.path.exists(path):
        os.remove(path)
    store = FeatureStore(path)
    yield store
    store.close()
    if os.path.exists(path):
        os.remove(path)


def _seed_live_like_series(store: FeatureStore, ticker: str = "BTCUSDT") -> None:
    listener = CLOBListener(store=store)
    for i in range(80):
        mid = 100.0 + (0.8 if i % 2 == 0 else -0.8) + (0.1 * (i % 3))
        spread = 0.05 + (0.01 if i % 2 == 0 else 0.0)
        payload = json.dumps(
            {
                "asset_id": ticker,
                "market": "crypto-live",
                "timestamp": 1_700_000_000_000 + i * 1_000,
                "bids": [{"price": f"{mid - spread:.2f}", "size": f"{10 + i:.2f}"}],
                "asks": [{"price": f"{mid + spread:.2f}", "size": f"{12 + i:.2f}"}],
            }
        )
        # Synchronous helper call is sufficient here because handle_message just
        # persists the parsed snapshot.
        import asyncio
        asyncio.run(listener.handle_message(payload))


def test_live_features_can_train_and_feed_predictive_gate(feature_store: FeatureStore) -> None:
    _seed_live_like_series(feature_store)

    pipeline = TrainingPipeline(
        store=feature_store,
        model_dir=tempfile.mkdtemp(),
        min_train_samples=20,
        validation_split=0.2,
    )
    pipeline.register_features("BTCUSDT", ["mid_price", "spread_bps", "order_imbalance"], target_feature="mid_price")
    result = pipeline.train("BTCUSDT", hyperparams={"n_estimators": 10, "max_depth": 3})

    assert result is not None
    assert result["train_samples"] > 0

    latest = pipeline.latest_features_as_vector("BTCUSDT")
    assert latest is not None

    adapter = TrainingPipelinePredictiveAdapter(pipeline=pipeline, ticker="BTCUSDT")
    gate = PredictiveGateService(
        config=PredictiveGateConfig(allow_simulated_gate=True),
        model_registry=adapter,
        feature_store=feature_store,
    )

    signal = {
        "ticker": "BTCUSDT",
        "token_id": "BTCUSDT",
        "side": "BUY",
        "price": 0.5,
    }
    accepted, reason = gate.validate_signal(signal)

    assert reason in {"ACCEPT_PREDICTIVE_EDGE", "REJECT_NO_EDGE:+0.0000", "REJECT_NO_EDGE:-0.0000", "REJECT_SIMULATED_EDGE"}
    assert "market_features" in signal or "microstructure_liquidity" in signal
    assert "predictive_probability" in signal or not accepted
