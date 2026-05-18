import os
import tempfile
import time

import numpy as np
import pytest
import joblib

from core.training_pipeline import TrainingPipeline


class MockFeatureStore:
    def __init__(self) -> None:
        self._data: dict[str, list[dict]] = {}
        self._tickers: set[str] = set()
        self._call_count = 0

    def add_history(self, ticker: str, fname: str, values: list[float]) -> None:
        key = f"{ticker}_{fname}"
        self._data[key] = [{"value": v, "timestamp": time.time() + i} for i, v in enumerate(values)]

    def get_feature_history(self, ticker: str, fname: str, limit: int = 1000):
        self._call_count += 1
        key = f"{ticker}_{fname}"
        return self._data.get(key, [])[-limit:]


@pytest.fixture
def store() -> MockFeatureStore:
    s = MockFeatureStore()
    s.add_history("SOL", "oi_5min", [0.1 + 0.01 * i for i in range(500)])
    s.add_history("SOL", "tam_state", [1 if i % 2 == 0 else -1 for i in range(500)])
    s.add_history("SOL", "spread_bps", [5.0 + 0.1 * i for i in range(500)])
    s.add_history("SOL", "mid_price", [0.5 + 0.1 * np.sin(0.05 * i) + 0.02 * (i % 7) for i in range(500)])
    s.add_history("BTC", "oi_5min", [0.2 + 0.01 * i for i in range(300)])
    s.add_history("BTC", "returns", [0.002 * (i % 2) for i in range(300)])
    return s


@pytest.fixture
def pipeline(store: MockFeatureStore) -> TrainingPipeline:
    return TrainingPipeline(
        store=store,
        model_dir=tempfile.mkdtemp(),
        retrain_interval_hours=1,
        min_train_samples=50,
        validation_split=0.2,
    )


class TestPipelineInit:
    def test_default_dir_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            p = TrainingPipeline(store=MockFeatureStore(), model_dir=tmpdir)
            assert os.path.exists(tmpdir)

    def test_register_features(self, pipeline: TrainingPipeline) -> None:
        pipeline.register_features("SOL", ["oi_5min", "returns"])
        assert "SOL" in pipeline._feature_registry
        names, target = pipeline._feature_registry["SOL"]
        assert names == ["oi_5min", "returns"]
        assert target == ""


class TestTraining:
    def test_training_set_uses_asof_features_without_future_leakage(self) -> None:
        class AsOfStore:
            def __init__(self) -> None:
                self.data = {
                    "SOL_mid_price": [
                        {"timestamp": float(i), "value": 100.0 + i}
                        for i in range(30)
                    ],
                    "SOL_leaky_feature": [
                        {"timestamp": float(i) + 0.5, "value": float(i)}
                        for i in range(30)
                    ],
                }

            def get_feature_history(self, ticker: str, fname: str, limit: int = 1000):
                return self.data[f"{ticker}_{fname}"][-limit:]

        pipeline = TrainingPipeline(
            store=AsOfStore(),
            model_dir=tempfile.mkdtemp(),
            min_train_samples=1,
        )
        data = pipeline._build_training_set(
            "SOL", ["leaky_feature", "mid_price"], target_feature="mid_price"
        )
        assert data is not None
        X, _, ts = data
        assert ts[0] == pytest.approx(1.0)
        assert X[0, 0] == pytest.approx(0.0)
        assert X[1, 0] == pytest.approx(1.0)

    def test_train_success(self, pipeline: TrainingPipeline) -> None:
        pipeline.register_features("SOL", ["oi_5min", "tam_state", "spread_bps", "mid_price"], target_feature="mid_price")
        result = pipeline.train("SOL", hyperparams={"n_estimators": 10, "max_depth": 3})
        assert result is not None
        assert result["ticker"] == "SOL"
        assert result["train_accuracy"] > 0
        assert result["val_accuracy"] > 0
        assert "model_path" in result
        assert os.path.exists(result["model_path"])

    def test_train_returns_meta_weights(self, pipeline: TrainingPipeline) -> None:
        pipeline.register_features("SOL", ["oi_5min", "tam_state", "spread_bps", "mid_price"], target_feature="mid_price")
        result = pipeline.train("SOL", hyperparams={"n_estimators": 10, "max_depth": 3})
        assert result is not None
        assert "meta_weights" in result
        assert set(result["meta_weights"].keys()) == {"xgb", "lgbm", "rf"}

    def test_train_no_features_returns_none(self, pipeline: TrainingPipeline) -> None:
        result = pipeline.train("UNKNOWN", hyperparams={"n_estimators": 10})
        assert result is None

    def test_train_insufficient_data_returns_none(
        self, pipeline: TrainingPipeline
    ) -> None:
        store = MockFeatureStore()
        store.add_history("SOL", "oi", [0.5] * 10)
        store.add_history("SOL", "dummy", [0.5] * 10)
        p = TrainingPipeline(store=store, min_train_samples=100)
        p.register_features("SOL", ["oi", "dummy"], target_feature="dummy")
        result = p.train("SOL")
        assert result is None

    def test_predict_after_train(self, pipeline: TrainingPipeline) -> None:
        pipeline.register_features("SOL", ["oi_5min", "tam_state", "spread_bps", "mid_price"], target_feature="mid_price")
        pipeline.train("SOL", hyperparams={"n_estimators": 10, "max_depth": 3})
        X = np.random.randn(1, 3).astype(np.float32)
        pred = pipeline.predict("SOL", X)
        assert pred is not None
        assert "prob_up" in pred
        assert "prob_down" in pred
        assert "signal" in pred
        assert "dissimilarity_index" in pred
        assert "ood_alert" in pred
        assert pred["signal"] in ("BUY", "SELL")

    def test_train_exports_calibrated_model(self, pipeline: TrainingPipeline) -> None:
        pipeline.register_features("SOL", ["oi_5min", "tam_state", "spread_bps", "mid_price"], target_feature="mid_price")
        result = pipeline.train("SOL", hyperparams={"n_estimators": 10, "max_depth": 3})
        assert result is not None
        assert result["calibrated_model_path"]
        assert os.path.exists(result["calibrated_model_path"])
        calibrated = joblib.load(result["calibrated_model_path"])
        X = np.random.randn(2, 3).astype(np.float32)
        proba = calibrated.predict_proba(X)
        assert proba.shape == (2, 2)

    def test_prune_model_artifacts_keeps_latest_two(self, pipeline: TrainingPipeline) -> None:
        pipeline.register_features("SOL", ["oi_5min", "tam_state", "spread_bps", "mid_price"], target_feature="mid_price")
        result = pipeline.train("SOL", hyperparams={"n_estimators": 10, "max_depth": 3})
        assert result is not None
        extra = os.path.join(pipeline.model_dir, "SOL_legacy.pkl")
        with open(extra, "wb") as fh:
            fh.write(b"old")
        stats = pipeline.prune_model_artifacts("SOL", keep_latest=2)
        assert stats["removed"] >= 1
        assert os.path.exists(result["model_path"])
        assert os.path.exists(result["calibrated_model_path"])

    def test_audit_model_calibration_reports_ece(self) -> None:
        y_true = np.array([0, 0, 1, 1, 0, 1, 1, 0], dtype=np.int32)
        y_prob = np.array([0.1, 0.2, 0.8, 0.9, 0.3, 0.7, 0.6, 0.4], dtype=np.float32)
        audit = TrainingPipeline.audit_model_calibration(y_true, y_prob, n_bins=4)
        assert "ece" in audit
        assert audit["ece"] >= 0.0
        assert len(audit["true_frequencies"]) == len(audit["pred_probabilities"])

    def test_predict_without_train_returns_none(
        self, pipeline: TrainingPipeline
    ) -> None:
        X = np.random.randn(1, 3).astype(np.float32)
        pred = pipeline.predict("NONEXISTENT", X)
        assert pred is None


class TestRollingTrain:
    def test_rolling_train_multiple_tickers(
        self, pipeline: TrainingPipeline
    ) -> None:
        pipeline.register_features("SOL", ["oi_5min", "tam_state", "mid_price"], target_feature="mid_price")
        pipeline.register_features("BTC", ["oi_5min", "returns"])
        results = pipeline.rolling_train(
            ["SOL", "BTC"],
            hyperparams={"n_estimators": 10, "max_depth": 3},
        )
        assert "SOL" in results
        assert "BTC" in results
        assert results["SOL"]["train_accuracy"] > 0
        assert results["BTC"]["train_accuracy"] > 0


class TestBacktestWalkForward:
    def test_walk_forward_returns_metrics(
        self, pipeline: TrainingPipeline
    ) -> None:
        pipeline.register_features("SOL", ["oi_5min", "tam_state", "spread_bps", "mid_price"], target_feature="mid_price")
        result = pipeline.backtest_walk_forward(
            "SOL", n_splits=3,
            hyperparams={"n_estimators": 10, "max_depth": 3},
        )
        assert result is not None
        assert result["ticker"] == "SOL"
        assert len(result["fold_metrics"]) == 3
        assert result["mean_val_accuracy"] > 0
        assert result["std_val_accuracy"] >= 0

    def test_walk_forward_no_features_returns_none(
        self, pipeline: TrainingPipeline
    ) -> None:
        result = pipeline.backtest_walk_forward("UNKNOWN")
        assert result is None


class TestAutoRetrain:
    def test_should_retrain_when_no_model(
        self, pipeline: TrainingPipeline
    ) -> None:
        assert pipeline.should_retrain("SOL") is True

    def test_should_not_retrain_after_fresh_train(
        self, pipeline: TrainingPipeline
    ) -> None:
        pipeline.register_features("SOL", ["oi_5min", "tam_state", "spread_bps", "mid_price"], target_feature="mid_price")
        pipeline.train("SOL", hyperparams={"n_estimators": 10, "max_depth": 3})
        assert pipeline.should_retrain("SOL") is False

    def test_auto_retrain_trains_missing(
        self, pipeline: TrainingPipeline, store: MockFeatureStore
    ) -> None:
        pipeline.register_features("SOL", ["oi_5min", "tam_state", "spread_bps", "mid_price"], target_feature="mid_price")
        pipeline.register_features("BTC", ["oi_5min", "returns"])
        pipeline.train("SOL", hyperparams={"n_estimators": 10, "max_depth": 3})
        pipeline.train("BTC", hyperparams={"n_estimators": 10, "max_depth": 3})
        results = pipeline.auto_retrain_if_needed(
            ["SOL", "BTC"],
            hyperparams={"n_estimators": 10, "max_depth": 3},
        )
        assert results["SOL"]["status"] == "SKIPPED"
        assert results["BTC"]["status"] == "SKIPPED"


class TestLatestFeatures:
    def test_latest_features_vector(
        self, pipeline: TrainingPipeline
    ) -> None:
        pipeline.register_features("SOL", ["oi_5min", "tam_state", "spread_bps", "mid_price"], target_feature="mid_price")
        vec = pipeline.latest_features_as_vector("SOL")
        assert vec is not None
        assert vec.shape[1] == 3

    def test_no_features_returns_none(
        self, pipeline: TrainingPipeline
    ) -> None:
        vec = pipeline.latest_features_as_vector("UNKNOWN")
        assert vec is None


class TestListModels:
    def test_list_trained_models_empty(self, pipeline: TrainingPipeline) -> None:
        models = pipeline.list_trained_models()
        assert models == []

    def test_list_trained_models_after_train(
        self, pipeline: TrainingPipeline
    ) -> None:
        pipeline.register_features("SOL", ["oi_5min", "tam_state", "spread_bps", "mid_price"], target_feature="mid_price")
        pipeline.train("SOL", hyperparams={"n_estimators": 10, "max_depth": 3})
        models = pipeline.list_trained_models()
        assert len(models) == 1
        assert models[0]["ticker"] == "SOL"
        assert models[0]["size_kb"] > 0
