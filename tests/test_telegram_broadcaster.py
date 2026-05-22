from __future__ import annotations

import asyncio
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
from utils.notifier import TelegramNotifier


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


def test_calibrator_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(ProbabilityCalibrator, "ALLOWED_DIR", str(tmp_path))
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


def test_escape_markdown_v2_escapes_reserved_chars() -> None:
    from utils.telegram.formatter import TelegramMessageFormatter

    escaped = TelegramMessageFormatter.escape_markdown_v2("BTC_USDT (spot)! 100%")
    assert "BTC\\_USDT" in escaped
    assert "\\(spot\\)" in escaped
    assert "\\!" in escaped


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


@pytest.mark.asyncio
async def test_risk_alert_escapes_message_text() -> None:
    notifier = SimpleNamespace(enabled=True, send_async=AsyncMock(return_value=True))
    broadcaster = TelegramBroadcaster(
        notifier=notifier,
        training_pipeline=FakePipeline(0.75),
        market_client=FakeClient(None),
        rate_limiter=DummyLimiter(),
    )

    await broadcaster.diffuser_alerte_risque_au_canal({
        "title": "Queue full (BTC_USDT)",
        "message": "Signal loss > 10% !",
        "severity": "critical",
    })

    payload = notifier.send_async.await_args.args[0]
    assert "BTC" in payload
    assert "Signal loss" in payload
    assert "&gt;" in payload
    assert "!" in payload


@pytest.mark.asyncio
async def test_notifier_keeps_background_task_and_logs_failure(monkeypatch, caplog) -> None:
    notifier = TelegramNotifier(bot_token="token", chat_id="chat")

    async def failing_send_async(message: str, parse_mode: str = "Markdown") -> bool:
        raise RuntimeError("telegram boom")

    monkeypatch.setattr(notifier, "send_async", failing_send_async)

    with caplog.at_level("ERROR", logger="Notifier"):
        assert notifier.send("hello") is True
        assert len(notifier._background_tasks) == 1
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    assert len(notifier._background_tasks) == 0
    assert any("telegram boom" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_broadcast_memory_rehydrates_from_feature_store() -> None:
    from utils.security_utils import encrypt_data
    import json
    import time

    class FakeFeatureStore:
        def __init__(self, signals: list[dict]) -> None:
            self.signals = signals

        def replay_signals(self, since_timestamp: float, limit: int) -> list[dict]:
            return [s for s in self.signals if s["timestamp"] > since_timestamp][:limit]

    encrypted_dec = encrypt_data(json.dumps({"market_slug": "sol-above-200"}))
    now_ts = time.time()

    fake_signals = [
        {
            "signal_id": 1,
            "timestamp": now_ts - 100.0,
            "source": "lobstar_llm",
            "ticker": "SOL",
            "side": "BUY",
            "price": 0.65,
            "size": 100.0,
            "confidence": 0.75,
            "raw_text": "Buy SOL",
            "regime_label": "LOW_VOLATILITY",
            "decision_json": encrypted_dec,
        }
    ]

    fs = FakeFeatureStore(fake_signals)
    memory = BroadcastMemory(ttl_seconds=3600, probability_bucket=0.01, feature_store=fs)

    test_signal = BroadcastSignal(
        ticker="SOL",
        market_slug="sol-above-200",
        market_question="",
        calibrated_probability=0.75,
        market_probability=0.65,
        edge=0.10,
        action="BUY",
    )

    # Signal was sent and recorded within the 24h/1h TTL window, so memory should recognize it as duplicate
    assert memory.was_sent(test_signal) is True
    assert memory.last_for_ticker("SOL") is not None
    assert memory.last_for_ticker("SOL").market_slug == "sol-above-200"


@pytest.mark.asyncio
async def test_broadcaster_persistent_memory_save_and_rehydrate() -> None:
    from unittest.mock import MagicMock, AsyncMock
    from scrapers.telegram_broadcaster import TelegramBroadcaster, BroadcastSignal

    mock_store = MagicMock()
    mock_notifier = MagicMock()
    mock_notifier.enabled = True
    mock_notifier.send_async = AsyncMock(return_value=True)

    broadcaster = TelegramBroadcaster(
        notifier=mock_notifier,
        training_pipeline=MagicMock(),
        tickers=["SOL"],
        feature_store=mock_store,
    )

    test_signal = BroadcastSignal(
        ticker="SOL",
        market_slug="sol-above-200",
        market_question="Will SOL exceed $200?",
        calibrated_probability=0.85,
        market_probability=0.70,
        edge=0.15,
        action="BUY",
    )

    # Broadcast the opportunity
    ok = await broadcaster.broadcast_opportunity(test_signal)
    assert ok is True

    # Verify it recorded the signal into the FeatureStore
    assert mock_store.record_signal.called
    call_kwargs = mock_store.record_signal.call_args[1]
    assert call_kwargs["source"] == "telegram_broadcaster"
    assert call_kwargs["ticker"] == "SOL"
    assert call_kwargs["side"] == "BUY"
    assert call_kwargs["price"] == 0.70
    assert call_kwargs["confidence"] == 0.85
    assert call_kwargs["decision_json"] == {"market_slug": "sol-above-200"}
