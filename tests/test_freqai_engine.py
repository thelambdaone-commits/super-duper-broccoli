from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.freqai_engine import FreqAIEngine


class FakeClient:
    def __init__(self) -> None:
        self.funder = "0xproxy"
        self.post_order_calls: list[tuple[object, object, bool]] = []

    def get_order_book(self, token_id: str):
        return SimpleNamespace(min_order_size="1", tick_size="0.01")

    def get_market(self, token_id: str):
        return {
            "condition_id": "market-1",
            "tokens": [{"token_id": token_id, "outcome": "YES"}],
        }

    def get_market_by_token(self, token_id: str):
        return {
            "condition_id": "market-by-token-1",
            "tokens": [{"token_id": token_id, "outcome": "YES"}],
        }

    def create_and_post_order(self, order_args, options=None):
        return {"status": "FILLED", "orderID": "ord-1"}

    def create_order(self, order_args, options=None):
        return {"signed": True, "args": order_args, "options": options}

    def post_order(self, order, orderType=None, post_only=False):
        self.post_order_calls.append((order, orderType, post_only))
        return {"status": "LIVE", "orderID": "maker-1"}

    def get_midpoint(self, token_id: str):
        return 0.42


def _build_engine() -> FreqAIEngine:
    engine = object.__new__(FreqAIEngine)
    engine.client = FakeClient()
    engine.market_client = FakeClient()  # Both use FakeClient for mocking
    engine.POLYMARKET_MIN_NOTIONAL = 5.0
    engine.funder = "0xproxy"
    engine.signature_type = 2
    return engine


@pytest.fixture(autouse=True)
def run_to_thread_inline(monkeypatch):
    async def fake_to_thread(fn, *args, **kwargs):
        return fn(*args, **kwargs)

    monkeypatch.setattr("core.freqai_engine.asyncio.to_thread", fake_to_thread)


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
    assert "minimum" in result["error"] or "trop loin du minimum" in result["error"]


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
    assert "minimum" in result["error"] or "trop loin du minimum" in result["error"]


@pytest.mark.asyncio
async def test_post_order_uses_sdk_post_only_flag() -> None:
    engine = _build_engine()

    result = await engine.post_order(
        ticker="0xabc",
        side="BUY",
        price=0.5,
        size=11.0,
    )

    assert result["orderID"] == "maker-1"
    assert engine.client.post_order_calls
    _, _, post_only = engine.client.post_order_calls[0]
    assert post_only is True


@pytest.mark.asyncio
async def test_create_order_runs_blocking_client_call_in_thread(monkeypatch) -> None:
    engine = _build_engine()
    calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        calls.append(fn)
        return fn(*args, **kwargs)

    monkeypatch.setattr("core.freqai_engine.asyncio.to_thread", fake_to_thread)

    result = await engine.create_order("0xabc", "BUY", 0.5, 11.0)

    assert result["orderID"] == "ord-1"
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_get_order_status_runs_blocking_client_call_in_thread(monkeypatch) -> None:
    engine = _build_engine()
    engine.client.get_order = lambda order_id: {"id": order_id, "status": "LIVE"}
    calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        calls.append((fn, args))
        return fn(*args, **kwargs)

    monkeypatch.setattr("core.freqai_engine.asyncio.to_thread", fake_to_thread)

    result = await engine.get_order_status("ord-1")

    assert result == {"id": "ord-1", "status": "LIVE"}
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_get_midpoint_runs_blocking_client_call_in_thread(monkeypatch) -> None:
    engine = _build_engine()
    calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        calls.append((fn, args))
        return fn(*args, **kwargs)

    monkeypatch.setattr("core.freqai_engine.asyncio.to_thread", fake_to_thread)

    result = await engine.get_midpoint("0xabc")

    assert result == 0.42
    assert len(calls) == 1


def test_extract_market_context_prefers_market_by_token() -> None:
    engine = _build_engine()

    context = engine._extract_market_context("0xabc")

    assert context["market_id"] == "market-by-token-1"
    assert context["outcome"] == "YES"
