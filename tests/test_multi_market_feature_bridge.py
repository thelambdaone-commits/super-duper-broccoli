import os
import tempfile

import pytest

from core.services.predictive_gate import PredictiveGateConfig, PredictiveGateService
from schemas.prediction import PolymarketPredictiveEngine
from utils.exceptions import QuantFatal
from utils.feature_store import FeatureStore


def test_multi_market_feature_frame_asof_aligns_binance_and_polymarket() -> None:
    path = os.path.join(tempfile.gettempdir(), "test_multi_market_feature_bridge.duckdb")
    if os.path.exists(path):
        os.remove(path)
    store = FeatureStore(path)
    try:
        for i in range(10):
            ts = 1_700_000_000.0 + i * 60.0
            store.record_feature("BTC", "mid_price", 0.50 + i * 0.01, timestamp=ts)
            store.record_feature("BTC", "spread_bps", 10.0 + i, timestamp=ts)
            store.record_feature("BTC", "order_imbalance", 0.4 + i * 0.01, timestamp=ts)

            store.record_web_event(
                source="binance_ws",
                event_type="book_ticker",
                payload={
                    "ticker": "BTCUSDT",
                    "mid_price": 100.0 + i,
                    "spread_bps": 8.0 + i,
                    "order_imbalance": 0.5 + (i * 0.01),
                },
                market_slug="BTCUSDT",
                timestamp=ts,
            )

        rows = store.get_multi_market_feature_frame(
            target_ticker="BTC",
            base_feature_names=["mid_price", "spread_bps", "order_imbalance"],
            binance_symbol="BTCUSDT",
            since_ts=1_700_000_000.0,
            limit=100,
            window_seconds=300,
        )

        assert rows
        row = rows[-1]
        assert row["mid_price"] == pytest.approx(0.59)
        assert row["binance_return_1m"] >= 0.0
        assert row["binance_order_imbalance"] > 0.5
        assert "polymarket_spread_premium" in row
    finally:
        store.close()
        if os.path.exists(path):
            os.remove(path)


def test_binance_window_features_accept_raw_book_ticker_fields() -> None:
    rows = [
        (
            1_700_000_000.0,
            {"s": "BTCUSDT", "b": "100.00", "a": "100.10", "B": "10.0", "A": "30.0"},
        ),
        (
            1_700_000_060.0,
            {"s": "BTCUSDT", "b": "101.00", "a": "101.10", "B": "30.0", "A": "10.0"},
        ),
    ]

    features = FeatureStore._compute_binance_window_features(rows, 1_700_000_060.0, window_seconds=300)

    assert features["binance_return_1m"] > 0.0
    assert features["binance_spread_bps"] > 0.0
    assert features["binance_order_imbalance"] == pytest.approx(0.5)


class _FakeFeatureStore:
    def __init__(self, events: list[dict]) -> None:
        self._events = events

    def get_web_events(self, event_type: str = "book_ticker", limit: int = 200) -> list[dict]:
        return self._events


def test_live_prediction_rejects_future_binance_snapshot() -> None:
    engine = PolymarketPredictiveEngine(feature_store=_FakeFeatureStore([]))
    engine._hybrid_model = None

    now = __import__("time").time()
    future_ts = now + 10.0
    engine.feature_store = _FakeFeatureStore(
        [
            {
                "timestamp": future_ts,
                "source": "binance_ws",
                "market_slug": "BTCUSDT",
                "raw": {
                    "mid_price": 101.0,
                    "spread_bps": 8.0,
                    "order_imbalance": 0.55,
                },
            }
        ]
    )

    with pytest.raises(QuantFatal):
        engine._latest_binance_snapshot("BTC", max_staleness_seconds=3.0)


def test_predictive_gate_uses_live_binance_injection_when_available() -> None:
    class _ModelRegistry:
        def __init__(self) -> None:
            self.calls = 0

        def predict_winning_bet(self, *args, **kwargs):
            raise AssertionError("predict_winning_bet should not be used in this test")

        def get_live_prediction(
            self,
            ticker: str,
            polymarket_frame: dict,
            clob_price_yes: float,
            timestamp_resolution: float,
        ):
            self.calls += 1
            assert ticker == "BTC"
            return {
                "pari_approuve": True,
                "probability_win": 0.71,
                "absolute_edge": 0.11,
                "clob_price": clob_price_yes,
                "latency_ms": 1.0,
                "inference_count": 1,
                "conclusion": "EXECUTE_TRADE",
            }

    now = __import__("time").time()
    feature_store = _FakeFeatureStore(
        [
            {
                "timestamp": now - 1.0,
                "source": "binance_ws",
                "market_slug": "BTCUSDT",
                "raw": {
                    "mid_price": 101.0,
                    "spread_bps": 8.0,
                    "order_imbalance": 0.55,
                    "queue_velocity": 0.2,
                },
            }
        ]
    )
    gate = PredictiveGateService(
        PredictiveGateConfig(allow_simulated_gate=False),
        model_registry=_ModelRegistry(),
        feature_store=feature_store,
    )

    ok, reason = gate.validate_signal(
        {
            "ticker": "BTC",
            "side": "BUY",
            "price": 0.49,
            "market_features": {"mid_price": 0.5, "spread_bps": 10.0, "order_imbalance": 0.2},
            "timestamp_resolution": now + 3600.0,
        }
    )

    assert ok is True
    assert reason == "ACCEPT_PREDICTIVE_EDGE"


def test_predictive_engine_reads_staleness_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MAX_BINANCE_STALENESS_SECONDS", "1.5")
    assert PolymarketPredictiveEngine._max_binance_staleness_seconds() == pytest.approx(1.5)
