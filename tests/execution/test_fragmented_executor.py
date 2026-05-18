from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from execution.fragmented_executor import FragmentedOrderConfig, FragmentedOrderExecutor


class MockImmediateExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, float, float]] = []

    async def execute(self, ticker: str, side: str, price: float, size: float) -> dict:
        self.calls.append((ticker, side, price, size))
        return {
            "status": "FILLED",
            "ticker": ticker,
            "side": side,
            "price": price,
            "size": size,
        }


class FakeFeatureStore:
    def __init__(self, history: dict[str, list[float]]) -> None:
        self.history = history

    def get_feature_history(self, ticker: str, feature_name: str, since_ts: float = 0.0, limit: int = 20):
        values = self.history.get(f"{ticker}:{feature_name}", [])
        return [{"timestamp": i, "value": value} for i, value in enumerate(values[-limit:])]


@pytest.mark.asyncio
async def test_fragmented_executor_uses_twap_for_passive_only_signal(monkeypatch) -> None:
    executor = MockImmediateExecutor()
    twap = FragmentedOrderExecutor(
        FragmentedOrderConfig(twap_default_slices=3, twap_interval_seconds=0.0),
        immediate_executor=executor,
    )
    sleep_mock = AsyncMock()
    monkeypatch.setattr("execution.fragmented_executor.asyncio.sleep", sleep_mock)

    signal = {
        "asset": "SOL",
        "side": "BUY",
        "price": 0.51,
        "size_usd": 90.0,
        "execution_preference": "PASSIVE_ONLY",
        "microstructure_liquidity": {"bid_depth_3": 40.0, "ask_depth_3": 140.0},
    }

    result = await twap.execute(signal, context=object())

    assert result["strategy"] == "TWAP"
    assert result["slices_attempted"] == 3
    assert result["slices_filled"] == 3
    assert result["total_filled_usd"] == pytest.approx(90.0)
    assert len(executor.calls) == 3
    assert executor.calls[0][3] == pytest.approx(30.0 / 0.51)
    assert sleep_mock.await_count == 2


@pytest.mark.asyncio
async def test_fragmented_executor_falls_back_to_immediate_when_not_passive() -> None:
    executor = MockImmediateExecutor()
    twap = FragmentedOrderExecutor(FragmentedOrderConfig(twap_default_slices=4), immediate_executor=executor)

    signal = {
        "asset": "ETH",
        "side": "SELL",
        "price": 0.42,
        "size_usd": 25.0,
    }

    result = await twap.execute(signal, context=object())

    assert result["status"] == "FILLED"
    assert result["ticker"] == "ETH"
    assert len(executor.calls) == 1
    assert executor.calls[0][3] == pytest.approx(25.0)


@pytest.mark.asyncio
async def test_fragmented_executor_caps_slice_by_participation_rate(monkeypatch) -> None:
    executor = MockImmediateExecutor()
    store = FakeFeatureStore({"SOL:volume": [100.0, 100.0, 100.0]})
    twap = FragmentedOrderExecutor(
        {
            "twap_default_slices": 2,
            "twap_interval_seconds": 0.0,
            "max_participation_rate": 0.10,
            "max_first_level_participation_rate": 0.10,
        },
        immediate_executor=executor,
        feature_store=store,
    )
    sleep_mock = AsyncMock()
    monkeypatch.setattr("execution.fragmented_executor.asyncio.sleep", sleep_mock)

    signal = {
        "asset": "SOL",
        "side": "BUY",
        "price": 0.51,
        "size_usd": 50.0,
        "execution_preference": "PASSIVE_ONLY",
        "microstructure_liquidity": {"bid_depth_3": 500.0, "ask_depth_3": 500.0},
    }

    result = await twap.execute(signal, context=object())

    assert result["strategy"] == "TWAP"
    assert len(executor.calls) == 2
    assert executor.calls[0][3] == pytest.approx(10.0 / 0.51)
    assert executor.calls[1][3] == pytest.approx(10.0 / 0.51)
    assert result["total_filled_usd"] == pytest.approx(20.0)
    assert result["avg_market_volume_observed"] == pytest.approx(100.0)
    assert result["realized_participation_rate"] == pytest.approx(20.0 / 200.0)
    assert result["volume_capped_events"] == 2
    assert result["planned_vs_actual_slices"] == "2/2"
    assert sleep_mock.await_count == 1
