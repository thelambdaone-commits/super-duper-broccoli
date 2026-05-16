import os
import tempfile

import numpy as np
import pytest

from user_data.freqaimodels.HybridQuantModel import (
    HybridQuantModel,
    TFTEmbeddingHook,
    train_model_from_store,
)


@pytest.fixture
def model() -> HybridQuantModel:
    return HybridQuantModel(n_estimators=10, max_depth=3)


@pytest.fixture
def binary_data() -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.RandomState(42)
    X = rng.randn(200, 10).astype(np.float32)
    y = (X[:, 0] + X[:, 1] > 0).astype(np.int32)
    return X, y


@pytest.fixture
def mock_store() -> None:
    class MockStore:
        def __init__(self) -> None:
            self._data: dict[str, list[dict]] = {}

        def get_feature_history(self, ticker: str, fname: str, limit: int = 1000):
            return self._data.get(f"{ticker}_{fname}", [])

    return MockStore()


class TestTFTEmbeddingHook:
    def test_init(self) -> None:
        hook = TFTEmbeddingHook(d_model=64)
        assert hook.d_model == 64
        assert hook._model is None

    def test_load_nonexistent_checkpoint(self) -> None:
        hook = TFTEmbeddingHook()
        result = hook.load_tft("/nonexistent/path.pt")
        assert result is False

    def test_extract_without_model_passthrough(self) -> None:
        hook = TFTEmbeddingHook()
        X = np.random.randn(10, 5).astype(np.float32)
        result = hook.extract_embeddings(X)
        np.testing.assert_array_equal(result, X)


class TestHybridQuantModelInit:
    def test_default_params(self) -> None:
        m = HybridQuantModel()
        assert m.n_estimators == 100
        assert m.max_depth == 5
        assert m.learning_rate == 0.05
        assert m._models == {}
        assert m._meta is None

    def test_custom_params(self) -> None:
        m = HybridQuantModel(n_estimators=50, max_depth=3, learning_rate=0.1)
        assert m.n_estimators == 50
        assert m.max_depth == 3
        assert m.learning_rate == 0.1


class TestHybridQuantModelFit:
    def test_fit_creates_base_learners(
        self, model: HybridQuantModel, binary_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        X, y = binary_data
        model.fit(X, y)
        assert "xgb" in model._models
        assert "lgbm" in model._models
        assert "rf" in model._models
        assert model._meta is not None

    def test_fit_stores_classes(
        self, model: HybridQuantModel, binary_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        X, y = binary_data
        model.fit(X, y)
        assert model._classes is not None
        assert set(model._classes) == {0, 1}

    def test_fit_returns_self(
        self, model: HybridQuantModel, binary_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        X, y = binary_data
        result = model.fit(X, y)
        assert result is model


class TestHybridQuantModelPredict:
    def test_predict_before_fit_raises(self) -> None:
        m = HybridQuantModel()
        X = np.random.randn(5, 5).astype(np.float32)
        with pytest.raises(RuntimeError, match="not fitted"):
            m.predict(X)

    def test_predict_returns_binary(
        self, model: HybridQuantModel, binary_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        X, y = binary_data
        model.fit(X[:100], y[:100])
        preds = model.predict(X[100:110])
        assert preds.dtype == np.int32
        assert set(preds).issubset({0, 1})

    def test_predict_proba_shape(
        self, model: HybridQuantModel, binary_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        X, y = binary_data
        model.fit(X[:100], y[:100])
        proba = model.predict_proba(X[100:105])
        assert proba.shape == (5, 2)

    def test_predict_direction(
        self, model: HybridQuantModel, binary_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        X, y = binary_data
        model.fit(X[:100], y[:100])
        direction = model.predict_direction(X[100:105], threshold=0.5)
        assert set(direction).issubset({-1, 1})

    def test_reasonable_accuracy(
        self, model: HybridQuantModel, binary_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        X, y = binary_data
        model.fit(X, y)
        acc = model.score(X, y)
        assert acc > 0.6


class TestHybridQuantModelPersistence:
    def test_save_and_load(
        self, model: HybridQuantModel, binary_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        X, y = binary_data
        model.fit(X, y)
        with tempfile.NamedTemporaryFile(suffix=".pkl", delete=False) as f:
            path = f.name
        try:
            model.save(path)
            loaded = HybridQuantModel().load(path)
            preds_orig = model.predict(X[:5])
            preds_loaded = loaded.predict(X[:5])
            np.testing.assert_array_equal(preds_orig, preds_loaded)
            assert loaded.n_estimators == model.n_estimators
        finally:
            if os.path.exists(path):
                os.remove(path)

    def test_load_nonexistent_raises(self) -> None:
        m = HybridQuantModel()
        with pytest.raises(FileNotFoundError):
            m.load("/nonexistent/model.pkl")


class TestFeatureImportance:
    def test_feature_importance_returns_dict(
        self, model: HybridQuantModel, binary_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        X, y = binary_data
        model._feature_names = [f"f_{i}" for i in range(X.shape[1])]
        model.fit(X, y)
        imp = model.feature_importance()
        assert isinstance(imp, dict)
        assert len(imp) > 0

    def test_feature_importance_before_fit_empty(self) -> None:
        m = HybridQuantModel()
        assert m.feature_importance() == {}

    def test_meta_weights(
        self, model: HybridQuantModel, binary_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        X, y = binary_data
        model.fit(X, y)
        weights = model.get_meta_weights()
        assert set(weights.keys()) == {"xgb", "lgbm", "rf"}
        assert all(isinstance(v, float) for v in weights.values())


class TestSummary:
    def test_summary_contains_keys(
        self, model: HybridQuantModel, binary_data: tuple[np.ndarray, np.ndarray]
    ) -> None:
        X, y = binary_data
        model.fit(X, y)
        s = model.summary()
        assert s["model_type"] == "HybridQuantModel"
        assert s["base_learners"] == ["xgb", "lgbm", "rf"]
        assert "meta_weights" in s
        assert "n_estimators" in s


class TestTrainFromStore:
    def test_insufficient_features_returns_none(self, mock_store) -> None:
        result = train_model_from_store(
            store=mock_store, ticker="SOL",
            feature_names=["oi"], min_samples=10,
        )
        assert result is None

    def test_insufficient_samples_returns_none(self, mock_store) -> None:
        mock_store._data["SOL_oi"] = [{"value": 0.5}] * 5
        mock_store._data["SOL_tam"] = [{"value": 1.0}] * 5
        result = train_model_from_store(
            store=mock_store, ticker="SOL",
            feature_names=["oi", "tam"], min_samples=100,
        )
        assert result is None


class TestEdgeCases:
    def test_single_class_target(self) -> None:
        m = HybridQuantModel(n_estimators=10, max_depth=3)
        X = np.random.randn(50, 3).astype(np.float32)
        y = np.ones(50, dtype=np.int32)
        with pytest.raises((ValueError, AssertionError)):
            m.fit(X, y)

    def test_constant_features(self) -> None:
        m = HybridQuantModel(n_estimators=10, max_depth=3)
        X = np.ones((100, 5), dtype=np.float32)
        y = np.where(np.arange(100) > 50, 1, 0).astype(np.int32)
        m.fit(X, y)
        acc = m.score(X, y)
        assert isinstance(acc, float)

    def test_high_dimensional_input(self) -> None:
        m = HybridQuantModel(n_estimators=10, max_depth=3)
        X = np.random.randn(100, 500).astype(np.float32)
        y = (X[:, 0] > 0).astype(np.int32)
        m.fit(X, y)
        acc = m.score(X, y)
        assert acc > 0.5
