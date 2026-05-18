import os
import tempfile

import numpy as np

from core.mlops_feedback_loop import LobstarMLOpsEngine
from user_data.freqaimodels.HybridQuantModel import HybridQuantModel
from utils.feature_store import FeatureStore


def test_feature_store_prune_and_vacuum_removes_old_raw_events() -> None:
    path = os.path.join(tempfile.gettempdir(), "test_storage_maintenance.duckdb")
    if os.path.exists(path):
        os.remove(path)
    store = FeatureStore(path)
    try:
        store.record_web_event(
            source="binance_ws",
            event_type="book_ticker",
            payload={"ticker": "BTCUSDT"},
            market_slug="BTCUSDT",
            timestamp=1_000.0,
        )
        store.record_web_event(
            source="binance_ws",
            event_type="book_ticker",
            payload={"ticker": "BTCUSDT"},
            market_slug="BTCUSDT",
            timestamp=10_000.0,
        )

        removed = store.prune_before(5_000.0, tables=["web_events_raw"])
        assert removed["web_events_raw"] == 1
        remaining = store.get_web_events()
        assert len(remaining) == 1
        assert remaining[0]["timestamp"] == 10_000.0
    finally:
        store.close()
        if os.path.exists(path):
            os.remove(path)


def test_hybrid_model_saves_with_joblib_compression(tmp_path) -> None:
    X = np.array(
        [[0.0, 0.1], [0.2, 0.3], [0.4, 0.5], [0.6, 0.7], [0.8, 0.9], [1.0, 1.1]],
        dtype=np.float32,
    )
    y = np.array([0, 1, 0, 1, 0, 1], dtype=np.int32)
    model = HybridQuantModel(n_estimators=5, max_depth=2)
    model._feature_names = ["f1", "f2"]
    model.fit(X, y)

    path = tmp_path / "model.pkl"
    saved = model.save(str(path))
    assert os.path.exists(saved)
    loaded = HybridQuantModel().load(saved)
    pred = loaded.predict_proba(X[:1])
    assert pred.shape == (1, 2)


def test_mlops_prune_hook_tracks_last_prune(tmp_path) -> None:
    path = tmp_path / "feature_store.duckdb"
    store = FeatureStore(str(path))
    try:
        engine = LobstarMLOpsEngine()
        assert engine.should_prune(interval_hours=24) is True
        engine.prune_feature_store(store, raw_retention_days=7, vacuum=False)
        assert engine.should_prune(interval_hours=24) is False
    finally:
        store.close()
