from __future__ import annotations

import time


from core.services.predictive_gate import PredictiveGateConfig, PredictiveGateService


class FakePredictiveEngine:
    def __init__(self, approved: bool = True, edge: float = 0.10, probability: float = 0.66) -> None:
        self.approved = approved
        self.edge = edge
        self.probability = probability
        self.calls = []

    def predict_winning_bet(self, df_market_ticks, clob_price_yes, timestamp_resolution):
        self.calls.append(
            {
                "shape": df_market_ticks.shape,
                "price": clob_price_yes,
                "timestamp_resolution": timestamp_resolution,
            }
        )
        return {
            "pari_approuve": self.approved,
            "probability_win": self.probability,
            "absolute_edge": self.edge,
        }


class FakeFeatureStore:
    def __init__(self, events: list[dict]) -> None:
        self._events = list(events)

    def get_web_events(self, event_type: str = "orderbook_snapshot", limit: int = 100, since_ts: float = 0.0):
        return list(self._events)[-limit:]


def test_rejects_without_features_when_simulation_disabled() -> None:
    service = PredictiveGateService(PredictiveGateConfig(allow_simulated_gate=False))

    allowed, reason = service.validate_signal({"price": 0.5})

    assert allowed is False
    assert reason == "REJECT_NO_MARKET_FEATURES"


def test_accepts_with_real_features_and_positive_edge() -> None:
    engine = FakePredictiveEngine(approved=True, edge=0.12, probability=0.74)
    service = PredictiveGateService(PredictiveGateConfig(min_edge_threshold=0.07), model_registry=engine)

    signal = {
        "price": 0.5,
        "timestamp_resolution": time.time() + 3600,
        "market_features": {"price": [0.5], "volume": [100.0], "bid_depth": [50.0], "ask_depth": [50.0]},
    }
    allowed, reason = service.validate_signal(signal)

    assert allowed is True
    assert reason == "ACCEPT_PREDICTIVE_EDGE"
    assert signal["predictive_probability"] == 0.74
    assert signal["predictive_edge"] == 0.12
    assert engine.calls[0]["shape"] == (1, 4)


def test_rejects_when_predicted_edge_below_threshold() -> None:
    engine = FakePredictiveEngine(approved=False, edge=0.03, probability=0.56)
    service = PredictiveGateService(PredictiveGateConfig(min_edge_threshold=0.07), model_registry=engine)

    signal = {
        "price": 0.5,
        "timestamp_resolution": time.time() + 3600,
        "market_features": {"price": [0.5], "volume": [100.0], "bid_depth": [50.0], "ask_depth": [50.0]},
    }
    allowed, reason = service.validate_signal(signal)

    assert allowed is False
    assert reason.startswith("REJECT_NO_EDGE:")


def test_simulated_gate_can_accept_on_configured_threshold() -> None:
    service = PredictiveGateService(
        PredictiveGateConfig(allow_simulated_gate=True, min_edge_threshold=0.07, simulated_probability=0.62),
        model_registry=None,
    )

    signal = {"simulated_edge": 0.10}
    allowed, reason = service.validate_signal(signal)

    assert allowed is True
    assert reason == "ACCEPT_SIMULATED_EDGE"
    assert signal["predictive_probability"] == 0.62
    assert signal["predictive_edge"] == 0.10


def test_rejects_buy_signals_on_negative_orderbook_imbalance() -> None:
    engine = FakePredictiveEngine(approved=True, edge=0.11, probability=0.72)
    store = FakeFeatureStore(
        [
            {
                "timestamp": time.time(),
                "raw": {
                    "token_id": "tok-1",
                    "spread_bps": 120.0,
                    "order_imbalance": -0.55,
                    "bid_depth_3": 20.0,
                    "ask_depth_3": 80.0,
                    "mid_price": 0.51,
                },
            }
        ]
    )
    service = PredictiveGateService(
        PredictiveGateConfig(min_edge_threshold=0.07),
        model_registry=engine,
        feature_store=store,
    )

    signal = {
        "token_id": "tok-1",
        "side": "BUY",
        "price": 0.5,
        "timestamp_resolution": time.time() + 3600,
    }
    allowed, reason = service.validate_signal(signal)

    assert allowed is False
    assert reason.startswith("REJECT_ORDERBOOK_IMBALANCE_BUY:")
    assert signal["microstructure_liquidity"]["spread_bps"] == 120.0


def test_marks_wide_spread_signals_passive_only() -> None:
    engine = FakePredictiveEngine(approved=True, edge=0.11, probability=0.72)
    store = FakeFeatureStore(
        [
            {
                "timestamp": time.time(),
                "raw": {
                    "token_id": "tok-2",
                    "spread_bps": 620.0,
                    "order_imbalance": 0.12,
                    "bid_depth_3": 60.0,
                    "ask_depth_3": 55.0,
                    "mid_price": 0.49,
                },
            }
        ]
    )
    service = PredictiveGateService(
        {
            "min_edge_threshold": 0.07,
            "max_spread_bps": 350.0,
            "allow_passive_only_on_wide_spread": True,
        },
        model_registry=engine,
        feature_store=store,
    )

    signal = {
        "token_id": "tok-2",
        "side": "BUY",
        "price": 0.5,
        "timestamp_resolution": time.time() + 3600,
    }
    allowed, reason = service.validate_signal(signal)

    assert allowed is True
    assert reason == "ACCEPT_PREDICTIVE_EDGE"
    assert signal["execution_preference"] == "PASSIVE_ONLY"
    assert signal["microstructure_liquidity"]["spread_bps"] == 620.0
