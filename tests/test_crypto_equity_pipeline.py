import os
import tempfile
import time

import numpy as np
import pytest

from core.training_pipeline import TrainingPipeline


class MockContinuousStore:
    def __init__(self) -> None:
        self._data: dict[str, list[dict]] = {}
        self._call_count = 0

    def add_history(self, ticker: str, fname: str, values: list[float]) -> None:
        key = f"{ticker}_{fname}"
        self._data[key] = [
            {"value": v, "timestamp": time.time() + i * 300}
            for i, v in enumerate(values)
        ]

    def get_feature_history(self, ticker: str, fname: str, limit: int = 1000):
        self._call_count += 1
        key = f"{ticker}_{fname}"
        return self._data.get(key, [])[-limit:]


@pytest.fixture
def continuous_store() -> MockContinuousStore:
    s = MockContinuousStore()
    n = 500
    t0 = time.time()
    close = 100.0 + 5.0 * np.sin(np.linspace(0, 6 * np.pi, n))
    close += np.random.RandomState(42).normal(0, 0.5, n)
    s.add_history("BTCUSDT", "close", close.tolist())

    for fname in ["rsi_14", "macd", "log_return_1", "log_return_3", "spread_bps", "order_imbalance"]:
        vals = np.random.RandomState(42).randn(n).cumsum() * 0.01
        s.add_history("BTCUSDT", fname, vals.tolist())

    close2 = 200.0 + 10.0 * np.cos(np.linspace(0, 4 * np.pi, n))
    close2 += np.random.RandomState(7).normal(0, 1.0, n)
    s.add_history("SPY", "close", close2.tolist())
    for fname in ["rsi_14", "macd", "log_return_1", "log_return_3", "spread_bps", "order_imbalance"]:
        vals = np.random.RandomState(7).randn(n).cumsum() * 0.01
        s.add_history("SPY", fname, vals.tolist())

    return s


@pytest.fixture
def continuous_pipeline(continuous_store: MockContinuousStore) -> TrainingPipeline:
    return TrainingPipeline(
        store=continuous_store,
        model_dir=tempfile.mkdtemp(),
        retrain_interval_hours=1,
        min_train_samples=50,
        validation_split=0.2,
    )


CONTINUOUS_FEATURES = [
    "close", "rsi_14", "macd", "log_return_1",
    "log_return_3", "spread_bps", "order_imbalance",
]


class TestContinuousTrainingSet:
    def test_build_continuous_set_returns_valid_data(
        self, continuous_pipeline: TrainingPipeline
    ) -> None:
        data = continuous_pipeline._build_continuous_training_set(
            "BTCUSDT", CONTINUOUS_FEATURES, target_feature="close", horizon=3,
        )
        assert data is not None
        X, y, ts = data
        assert len(X) == len(y) == len(ts)
        assert X.shape[1] == len(CONTINUOUS_FEATURES) - 1
        assert set(np.unique(y)).issubset({0, 1})
        assert len(X) >= continuous_pipeline.min_samples

    def test_build_continuous_horizon_affects_target(
        self, continuous_pipeline: TrainingPipeline
    ) -> None:
        data3 = continuous_pipeline._build_continuous_training_set(
            "BTCUSDT", CONTINUOUS_FEATURES, target_feature="close", horizon=3,
        )
        data1 = continuous_pipeline._build_continuous_training_set(
            "BTCUSDT", CONTINUOUS_FEATURES, target_feature="close", horizon=1,
        )
        assert data3 is not None and data1 is not None
        assert len(data3[1]) <= len(data1[1])

    def test_insufficient_data_returns_none(
        self, continuous_pipeline: TrainingPipeline
    ) -> None:
        store = MockContinuousStore()
        store.add_history("SOL", "close", [100.0 + i for i in range(20)])
        store.add_history("SOL", "rsi_14", [50.0] * 20)
        p = TrainingPipeline(store=store, min_train_samples=100)
        data = p._build_continuous_training_set(
            "SOL", ["close", "rsi_14"], target_feature="close", horizon=3,
        )
        assert data is None

    def test_no_features_returns_none(
        self, continuous_pipeline: TrainingPipeline
    ) -> None:
        data = continuous_pipeline._build_continuous_training_set(
            "UNKNOWN", ["close"], target_feature="close", horizon=3,
        )
        assert data is None


class TestContinuousTraining:
    def test_train_continuous_success(
        self, continuous_pipeline: TrainingPipeline
    ) -> None:
        continuous_pipeline.register_continuous_features(
            "BTCUSDT", feature_names=CONTINUOUS_FEATURES,
        )
        result = continuous_pipeline.train_continuous(
            "BTCUSDT", hyperparams={"n_estimators": 10, "max_depth": 3},
        )
        assert result is not None
        assert result["ticker"] == "BTCUSDT"
        assert result["market_type"] == "continuous"
        assert result["horizon"] == 3
        assert result["train_accuracy"] > 0
        assert result["val_accuracy"] > 0
        assert "meta_weights" in result
        assert set(result["meta_weights"].keys()) == {"xgb", "lgbm", "rf"}

    def test_train_continuous_custom_horizon(
        self, continuous_pipeline: TrainingPipeline
    ) -> None:
        continuous_pipeline.register_continuous_features(
            "BTCUSDT", feature_names=CONTINUOUS_FEATURES, horizon=5,
        )
        result = continuous_pipeline.train_continuous(
            "BTCUSDT", hyperparams={"n_estimators": 10, "max_depth": 3}, horizon=5,
        )
        assert result is not None
        assert result["horizon"] == 5

    def test_train_continuous_predict(
        self, continuous_pipeline: TrainingPipeline
    ) -> None:
        continuous_pipeline.register_continuous_features(
            "BTCUSDT", feature_names=CONTINUOUS_FEATURES,
        )
        continuous_pipeline.train_continuous(
            "BTCUSDT", hyperparams={"n_estimators": 10, "max_depth": 3},
        )
        X = np.random.randn(1, len(CONTINUOUS_FEATURES) - 1).astype(np.float32)
        pred = continuous_pipeline.predict_continuous("BTCUSDT", X)
        assert pred is not None
        assert "prob_up" in pred
        assert "prob_down" in pred
        assert "signal" in pred
        assert pred["signal"] in ("BUY", "SELL")

    def test_train_continuous_no_features_returns_none(
        self, continuous_pipeline: TrainingPipeline
    ) -> None:
        result = continuous_pipeline.train_continuous("UNKNOWN")
        assert result is None


class TestContinuousRollingTrain:
    def test_rolling_train_continuous_multiple(
        self, continuous_pipeline: TrainingPipeline
    ) -> None:
        continuous_pipeline.register_continuous_features("BTCUSDT", feature_names=CONTINUOUS_FEATURES)
        continuous_pipeline.register_continuous_features("SPY", feature_names=CONTINUOUS_FEATURES)
        results = continuous_pipeline.rolling_train_continuous(
            ["BTCUSDT", "SPY"],
            hyperparams={"n_estimators": 10, "max_depth": 3},
        )
        assert "BTCUSDT" in results
        assert "SPY" in results
        assert results["BTCUSDT"]["train_accuracy"] > 0
        assert results["SPY"]["train_accuracy"] > 0


class TestContinuousWalkForward:
    def test_walk_forward_continuous_returns_metrics(
        self, continuous_pipeline: TrainingPipeline
    ) -> None:
        continuous_pipeline.register_continuous_features("BTCUSDT", feature_names=CONTINUOUS_FEATURES)
        result = continuous_pipeline.backtest_walk_forward_continuous(
            "BTCUSDT", n_splits=3,
            hyperparams={"n_estimators": 10, "max_depth": 3},
        )
        assert result is not None
        assert result["ticker"] == "BTCUSDT"
        assert result["market_type"] == "continuous"
        assert len(result["fold_metrics"]) == 3
        assert result["mean_val_accuracy"] > 0


class TestDataIngestion:
    def test_yfinance_fetch_and_store(self):
        try:
            import yfinance as yf
        except ImportError:
            pytest.skip("yfinance not installed")

        from utils.data_ingestion import YFinanceIngestion

        class MiniStore:
            def __init__(self):
                self._data = []
                self._conn = type("Conn", (), {
                    "executemany": lambda self, q, rows: None,
                    "commit": lambda self: None,
                })()

            def record_feature(self, ticker, fname, value, ts=None):
                pass

        store = MiniStore()
        ing = YFinanceIngestion(store=store)
        n = ing.fetch_and_store("SPY", interval="1d", period="5d")
        assert n > 0

    def test_binance_historical(self):
        from utils.data_ingestion import BinanceWSListener

        class MiniStore:
            def __init__(self):
                self._data = []
                self._conn = type("Conn", (), {
                    "executemany": lambda self, q, rows: None,
                    "commit": lambda self: None,
                })()

            def record_web_event(self, *a, **kw):
                pass

            def record_microstructure(self, *a, **kw):
                pass

            def record_feature(self, *a, **kw):
                pass

        store = MiniStore()
        listener = BinanceWSListener(store=store, tickers=["BTCUSDT"])
        n = listener.fetch_historical_klines("BTCUSDT", interval="1d", limit=5)
        if n == 0:
            pytest.skip("Binance is unreachable in this environment")
        assert n > 0


class TestContinuousConfig:
    def test_settings_json_exists(self):
        import json
        path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "config", "settings.json"
        )
        assert os.path.exists(path)
        with open(path) as f:
            cfg = json.load(f)
        assert "trading_mode" in cfg
        assert "active_providers" in cfg
        assert "continuous_markets" in cfg

    def test_constants_have_continuous_tickers(self):
        from config.constants import (
            CONTINUOUS_MARKET_TICKERS_BINANCE,
            CONTINUOUS_MARKET_TICKERS_YFINANCE,
            CONTINUOUS_FEATURE_NAMES,
        )
        assert "BTCUSDT" in CONTINUOUS_MARKET_TICKERS_BINANCE
        assert "ETHUSDT" in CONTINUOUS_MARKET_TICKERS_BINANCE
        assert "SPY" in CONTINUOUS_MARKET_TICKERS_YFINANCE
        assert "QQQ" in CONTINUOUS_MARKET_TICKERS_YFINANCE
        assert len(CONTINUOUS_FEATURE_NAMES) > 0


class TestTrainAllAlignment:
    def test_generate_synthetic_data_uses_five_minute_spacing(self):
        from scripts.train_all import CONTINUOUS_SEQUENCE_SECONDS, generate_synthetic_data

        class MiniStore:
            def __init__(self):
                self.rows = []
                self._conn = type("Conn", (), {
                    "executemany": lambda self, q, rows: self._capture(rows),
                    "commit": lambda self: None,
                    "_capture": self._capture,
                })()

            def _capture(self, rows):
                self.rows.extend(rows)

            def get_stats(self):
                return {"features_computed": 0}

        store = MiniStore()
        generate_synthetic_data(store)
        assert CONTINUOUS_SEQUENCE_SECONDS == 300
        timestamps = sorted({row[0] for row in store.rows if row[1] == "BTC"})
        assert len(timestamps) > 1
        assert timestamps[1] - timestamps[0] == 300
