from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from unittest.mock import AsyncMock

import numpy as np
import pytest

import scrapers.telegram_broadcaster as broadcaster_mod
from scrapers.telegram_broadcaster import (
    BroadcastMemory,
    BroadcastSignal,
    TelegramBroadcaster,
    TokenBucketRateLimiter,
)
from user_data.strategies.probability_calibrator import ProbabilityCalibrator


class DummyLimiter:
    async def acquire(self) -> None:
        return None


@dataclass
class FakeMarket:
    slug: str
    question: str
    active: bool = True
    closed: bool = False
    volume: float = 50_000.0
    liquidity: float = 25_000.0
    yes_price: float = 0.65


class FakePipeline:
    def __init__(self, prob_up: float) -> None:
        self.prob_up = prob_up

    def latest_features_as_vector(self, ticker: str):
        return np.array([[1.0, 2.0]], dtype=np.float32)

    def predict(self, ticker: str, features: np.ndarray):
        return {
            "ticker": ticker,
            "prob_up": self.prob_up,
            "prob_down": 1.0 - self.prob_up,
            "direction": 1 if self.prob_up >= 0.5 else -1,
            "signal": "BUY" if self.prob_up >= 0.5 else "SELL",
        }


class FakeClient:
    def __init__(self, market: FakeMarket | None) -> None:
        self.market = market

    def get_market(self, slug_or_id: str):
        return None

    def search_markets(self, query: str, limit: int = 10):
        return [self.market] if self.market is not None else []


def _make_broadcaster(prob_up: float, market_yes: float, edge_threshold: float = 0.07):
    market = FakeMarket(
        slug="sol-above-200",
        question="Will SOL trade above $200 by year-end?",
        yes_price=market_yes,
    )
    notifier = SimpleNamespace(enabled=True, send_async=AsyncMock(return_value=True))
    return (
        TelegramBroadcaster(
            notifier=notifier,
            training_pipeline=FakePipeline(prob_up),
            market_client=FakeClient(market),
            tickers=["SOL"],
            edge_threshold=edge_threshold,
            rate_limiter=DummyLimiter(),
            enabled=True,
        ),
        notifier,
    )


def test_calibrator_roundtrip(tmp_path) -> None:
    rng = np.random.RandomState(7)
    raw = rng.beta(2, 5, size=100)
    y_true = (rng.uniform(size=100) < raw).astype(np.int32)
    probas = np.zeros((100, 2))
    probas[:, 1] = raw
    probas[:, 0] = 1.0 - raw

    calibrator = ProbabilityCalibrator(fusion_mode="ensemble")
    calibrator.calibrate(probas, y_true, ticker="SOL", model_version="v1")
    path = calibrator.save(str(tmp_path / "calibrator.pkl"))

    loaded = ProbabilityCalibrator().load(path)
    restored = loaded.predict_proba(probas[:5])

    assert loaded.is_fitted
    assert loaded.calibration_log["fusion_mode"] == "ensemble"
    assert restored.shape == (5, 2)


@pytest.mark.asyncio
async def test_rate_limiter_enforces_wait(monkeypatch) -> None:
    calls = {"count": 0}

    def fake_monotonic() -> float:
        calls["count"] += 1
        if calls["count"] <= 2:
            return 0.0
        return 20.0

    monkeypatch.setattr(broadcaster_mod.time, "monotonic", fake_monotonic)
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(broadcaster_mod.asyncio, "sleep", fake_sleep)

    limiter = TokenBucketRateLimiter(capacity=1, refill_period_seconds=20.0)
    limiter.tokens = 0.0
    limiter._updated_at = 0.0

    await limiter.acquire()

    assert sleep_calls == [20.0]


@pytest.mark.asyncio
async def test_broadcast_triggers_only_on_edge() -> None:
    broadcaster, notifier = _make_broadcaster(prob_up=0.75, market_yes=0.65)
    signals = await broadcaster.scan_and_broadcast(["SOL"])

    assert len(signals) == 1
    assert isinstance(signals[0], BroadcastSignal)
    assert notifier.send_async.await_count == 1
    payload = notifier.send_async.await_args.args[0]
    assert "CALIBRATED EDGE ALERT" in payload
    assert "ticker: SOL" in payload
    assert "p_real:" in payload
    assert "p_market:" in payload
    assert "action: BUY" in payload


@pytest.mark.asyncio
async def test_broadcast_skips_when_edge_below_threshold() -> None:
    broadcaster, notifier = _make_broadcaster(prob_up=0.68, market_yes=0.65)
    signals = await broadcaster.scan_and_broadcast(["SOL"])

    assert signals == []
    notifier.send_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_broadcast_memory_skips_redundant_signal() -> None:
    notifier = SimpleNamespace(enabled=True, send_async=AsyncMock(return_value=True))
    broadcaster = TelegramBroadcaster(
        notifier=notifier,
        training_pipeline=FakePipeline(0.75),
        market_client=FakeClient(None),
        rate_limiter=DummyLimiter(),
        memory=BroadcastMemory(ttl_seconds=3600, probability_bucket=0.01),
    )
    signal = BroadcastSignal(
        ticker="SOL",
        market_slug="sol-above-200",
        market_question="Will SOL trade above $200 by year-end?",
        calibrated_probability=0.75,
        market_probability=0.65,
        edge=0.10,
        action="BUY",
    )

    assert await broadcaster.broadcast_opportunity(signal) is True
    assert await broadcaster.broadcast_opportunity(signal) is False
    assert notifier.send_async.await_count == 1
    assert broadcaster.memory.last_for_ticker("SOL") == signal


@pytest.mark.asyncio
async def test_broadcast_memory_allows_materially_different_signal() -> None:
    notifier = SimpleNamespace(enabled=True, send_async=AsyncMock(return_value=True))
    broadcaster = TelegramBroadcaster(
        notifier=notifier,
        training_pipeline=FakePipeline(0.75),
        market_client=FakeClient(None),
        rate_limiter=DummyLimiter(),
        memory=BroadcastMemory(ttl_seconds=3600, probability_bucket=0.01),
    )
    first = BroadcastSignal(
        ticker="SOL",
        market_slug="sol-above-200",
        market_question="Will SOL trade above $200 by year-end?",
        calibrated_probability=0.75,
        market_probability=0.65,
        edge=0.10,
        action="BUY",
    )
    second = BroadcastSignal(
        ticker="SOL",
        market_slug="sol-above-200",
        market_question="Will SOL trade above $200 by year-end?",
        calibrated_probability=0.80,
        market_probability=0.65,
        edge=0.15,
        action="BUY",
    )

    assert await broadcaster.broadcast_opportunity(first) is True
    assert await broadcaster.broadcast_opportunity(second) is True
    assert notifier.send_async.await_count == 2
