from __future__ import annotations

import time
import asyncio
from dataclasses import dataclass

import pytest

from core.lobstar_cognitive_brain import LobstarCognitiveBrain
from core.signal_executor import _apply_cognitive_confidence


class FakeStore:
    def get_microstructure_range(self, start_ts, end_ts, ticker):
        return [
            {"order_imbalance": 0.20},
            {"order_imbalance": 0.40},
        ]

    def get_feature_history(self, ticker, feature_name, since_ts=0.0, limit=1000):
        return []


@dataclass
class Level:
    price: float
    size: float


@dataclass
class Book:
    bids: list[Level]
    asks: list[Level]


class FakeClient:
    def get_order_book(self, token_id):
        return Book(
            bids=[Level(price=0.51, size=70.0)],
            asks=[Level(price=0.52, size=30.0)],
        )


class FakeScanner:
    client = FakeClient()

    def resolve_ticker_to_token_id(self, ticker, side="YES"):
        return "0xabc"


class FakePipeline:
    def latest_features_as_vector(self, ticker):
        return [[1.0, 2.0]]

    def predict(self, ticker, features):
        return {"prob_up": 0.80}


def test_cognitive_brain_combines_past_present_future() -> None:
    brain = LobstarCognitiveBrain(
        store=FakeStore(),
        scanner=FakeScanner(),
        training_pipeline=FakePipeline(),
        time_decay_half_life_seconds=3600,
    )

    decision = asyncio.run(
        brain.synthetiser_decision_decision(
            {"asset": "SOL", "action": "BUY", "timestamp": time.time()}
        )
    )

    assert decision.ticker == "SOL"
    assert decision.past_order_imbalance_avg == pytest.approx(0.30)
    assert decision.present_orderbook_imbalance == pytest.approx(0.40)
    assert decision.future_time_decay_probability == pytest.approx(0.80)
    assert decision.fused_score == pytest.approx(0.45)
    assert decision.action == "EXECUTE"


def test_cognitive_brain_enriches_signal() -> None:
    brain = LobstarCognitiveBrain(
        store=FakeStore(),
        scanner=FakeScanner(),
        training_pipeline=FakePipeline(),
    )
    signal = {"asset": "SOL", "action": "BUY", "timestamp": time.time()}
    decision = asyncio.run(brain.synthetiser_decision_decision(signal))
    enriched = brain.enrich_signal(signal, decision)

    assert enriched["cognitive_decision"]["ticker"] == "SOL"
    assert enriched["cognitive_confidence"] == decision.confidence
    assert enriched["calibrated_prob_time_decay"] == decision.future_time_decay_probability
    assert enriched["cognitive_fused_score"] == decision.fused_score
    assert enriched["cognitive_action"] == decision.action


def test_cognitive_brain_public_alias_matches_legacy_method() -> None:
    brain = LobstarCognitiveBrain(
        store=FakeStore(),
        scanner=FakeScanner(),
        training_pipeline=FakePipeline(),
    )
    signal = {"asset": "SOL", "action": "BUY", "timestamp": time.time()}

    legacy = asyncio.run(brain.synthetiser_decision_decision(signal))
    public = asyncio.run(brain.synthetiser_decision_cognitive(signal))

    assert public.ticker == legacy.ticker
    assert public.side == legacy.side
    assert public.future_time_decay_probability == pytest.approx(
        legacy.future_time_decay_probability,
        abs=0.001,
    )


def test_cognitive_confidence_fade_reduces_executor_confidence() -> None:
    confidence = _apply_cognitive_confidence(
        {"cognitive_confidence": 0.90, "cognitive_action": "FADE"},
        0.80,
    )

    assert confidence == pytest.approx(0.40)


def test_cognitive_brain_nominal_backward_compatibility() -> None:
    brain = LobstarCognitiveBrain(
        store=FakeStore(),
        scanner=FakeScanner(),
        training_pipeline=FakePipeline(),
    )
    decision = asyncio.run(
        brain.synthetiser_decision_decision(
            {"asset": "SOL", "action": "BUY", "timestamp": time.time()}
        )
    )
    assert decision.arbitrage_edge == 0.0
    assert decision.legging_risk_score == 0.0
    assert decision.kolmogorov_spread == 0.0


def test_cognitive_brain_kolmogorov_fusion() -> None:
    from core.arbitrage_feedback_loop import LobstarArbitrageEngine
    engine = LobstarArbitrageEngine(trigger_threshold=0.015)
    brain = LobstarCognitiveBrain(
        store=FakeStore(),
        scanner=FakeScanner(),
        training_pipeline=FakePipeline(),
        arbitrage_engine=engine,
    )

    signal = {
        "asset": "SOL",
        "action": "BUY",
        "timestamp": time.time(),
        "outcomes": {"YES": 0.55, "NO": 0.55},
    }
    decision = asyncio.run(brain.synthetiser_decision_decision(signal))

    assert decision.kolmogorov_spread == pytest.approx(0.10)
    assert decision.arbitrage_edge == pytest.approx(0.10)
    assert decision.fused_score > 0.45


def test_cognitive_brain_cross_market_arbitrage_fusion() -> None:
    from core.arbitrage_feedback_loop import LobstarArbitrageEngine
    engine = LobstarArbitrageEngine(trigger_threshold=0.015)
    brain = LobstarCognitiveBrain(
        store=FakeStore(),
        scanner=FakeScanner(),
        training_pipeline=FakePipeline(),
        arbitrage_engine=engine,
    )

    signal = {
        "asset": "SOL",
        "action": "BUY",
        "timestamp": time.time(),
        "primary_outcome": 0.60,
        "secondary_markets": [
            {"ticker": "SOL_M1", "outcome": 0.50},
            {"ticker": "SOL_M2", "outcome": 0.45},
        ]
    }
    decision = asyncio.run(brain.synthetiser_decision_decision(signal))

    assert decision.arbitrage_edge == pytest.approx(0.25)
    assert decision.fused_score > 0.45


def test_cognitive_brain_legging_risk_degradation() -> None:
    from core.arbitrage_feedback_loop import LobstarArbitrageEngine
    engine = LobstarArbitrageEngine(trigger_threshold=0.015)
    brain = LobstarCognitiveBrain(
        store=FakeStore(),
        scanner=FakeScanner(),
        training_pipeline=FakePipeline(),
        arbitrage_engine=engine,
    )

    signal = {
        "asset": "SOL",
        "action": "BUY",
        "timestamp": time.time(),
        "outcomes": {"YES": 0.55, "NO": 0.55},
        "panier_contrats": [
            {
                "ticker": "SOL",
                "orderbook": {
                    "bids": [{"price": 0.50, "size": 5.0}],
                    "asks": [{"price": 0.51, "size": 5.0}],
                }
            }
        ]
    }
    decision = asyncio.run(brain.synthetiser_decision_decision(signal))

    assert decision.legging_risk_score == pytest.approx(1.0)
    assert decision.fused_score < 0.20
    assert decision.action == "FADE"
