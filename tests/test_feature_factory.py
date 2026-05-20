import pandas as pd
import numpy as np

from utils.feature_factory import FeatureFactory
from user_data.strategies.feature_pipeline import compute_advanced_features


class TestFeatureFactory:
    def test_feature_factory_basic(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        ohlcv = pd.DataFrame({
            "Open": 100 + np.random.randn(100).cumsum() * 0.5,
            "High": 102 + np.random.randn(100).cumsum() * 0.5,
            "Low": 98 + np.random.randn(100).cumsum() * 0.5,
            "Close": 100 + np.random.randn(100).cumsum() * 0.5,
            "Volume": np.random.randint(1000, 10000, 100),
        }, index=dates)
        factory = FeatureFactory(ohlcv)
        features = factory.get_feature_names()
        assert len(features) > 30
        assert "ret_1d" in features
        assert "rsi_14" in features
        assert "realized_vol_21d" in features
        assert "macd" in features
        assert "volume_zscore_21" in features

    def test_feature_matrix_shape(self):
        dates = pd.date_range("2024-01-01", periods=50, freq="D")
        ohlcv = pd.DataFrame({
            "close": 100 + np.random.randn(50).cumsum(),
            "high": 102 + np.random.randn(50).cumsum(),
            "low": 98 + np.random.randn(50).cumsum(),
            "open": 100 + np.random.randn(50).cumsum(),
            "volume": np.random.randint(1000, 10000, 50),
        }, index=dates)
        factory = FeatureFactory(ohlcv)
        mat = factory.get_feature_matrix()
        assert mat.shape[0] == 50
        assert mat.shape[1] > 30

    def test_feature_dataframe(self):
        dates = pd.date_range("2024-01-01", periods=30, freq="D")
        ohlcv = pd.DataFrame({
            "Open": 100 + np.arange(30, dtype=float),
            "High": 102 + np.arange(30, dtype=float),
            "Low": 98 + np.arange(30, dtype=float),
            "Close": 100 + np.arange(30, dtype=float),
            "Volume": np.random.randint(1000, 10000, 30),
        }, index=dates)
        factory = FeatureFactory(ohlcv)
        df = factory.get_feature_dataframe()
        assert not df.empty


class TestAdvancedFeaturePipeline:
    def test_compute_advanced_features(self):
        dates = pd.date_range("2024-01-01", periods=100, freq="D")
        ohlcv = pd.DataFrame({
            "Close": 100 + np.random.randn(100).cumsum(),
            "High": 102 + np.random.randn(100).cumsum(),
            "Low": 98 + np.random.randn(100).cumsum(),
            "Volume": np.random.randint(1000, 10000, 100),
        }, index=dates)
        feats = compute_advanced_features(ohlcv)
        assert not feats.empty
        assert any("mom_ret" in c for c in feats.columns)
        assert any("vol_realized" in c for c in feats.columns)
        assert any("bb_pct_b" in c for c in feats.columns)
