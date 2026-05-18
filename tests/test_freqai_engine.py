from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.freqai_engine import FreqAIEngine


class FakeClient:
    def get_order_book(self, token_id: str):
        return SimpleNamespace(min_order_size="1", tick_size="0.01")


def _build_engine() -> FreqAIEngine:
    engine = object.__new__(FreqAIEngine)
    engine.client = FakeClient()
    engine.POLYMARKET_MIN_NOTIONAL = 5.0
    return engine


@pytest.mark.asyncio
async def test_clob_execute_rejects_below_min_notional() -> None:
    engine = _build_engine()

    result = await engine.clob_execute(
        ticker="0xabc",
        side="BUY",
        price=1.0,
        size=1.0,
    )

    assert result["status"] == "LOCAL_REJECT_MIN_NOTIONAL"
    assert "minimum Polymarket" in result["error"]


@pytest.mark.asyncio
async def test_post_order_rejects_below_min_notional() -> None:
    engine = _build_engine()

    result = await engine.post_order(
        ticker="0xabc",
        side="BUY",
        price=1.0,
        size=1.0,
    )

    assert result["status"] == "LOCAL_REJECT_MIN_NOTIONAL"
    assert "minimum Polymarket" in result["error"]
