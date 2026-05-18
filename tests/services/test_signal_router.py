from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.services.signal_router import SignalRouter, SignalRouterContext


class MockLedger:
    def get_execution_mode(self):
        return "PAPER"

    def record_paper_order(self, **kwargs):
        return {"position_id": "paper-1", **kwargs}

    def record_order(self, **kwargs):
        return None

    def validate_and_reserve(self, **kwargs):
        return {"authorized": True, "size": kwargs.get("requested_size", 10.0), "reason": "ok"}


class MockExecutor:
    def __init__(self, status: str = "SUCCESS") -> None:
        self.status = status
        self.calls: list[tuple[dict, SignalRouterContext]] = []

    async def execute(self, signal: dict, context: SignalRouterContext) -> dict:
        self.calls.append((dict(signal), context))
        return {"status": self.status, "ticker": signal.get("asset", "UNK")}


@pytest.mark.asyncio
async def test_routes_regex_signals() -> None:
    executor = MockExecutor()
    router = SignalRouter(passive_executor=executor)
    ctx = SignalRouterContext(
        ledger=MockLedger(),
        freqai=AsyncMock(),
        risk=None,
        hmm=None,
        store=None,
        executor=None,
        scanner=None,
    )

    signal = {"asset": "SOL", "action": "BUY", "price": 0.5}
    result = await router.route(signal, ctx)

    assert result["status"] == "SUCCESS"
    assert executor.calls


@pytest.mark.asyncio
async def test_routes_lobstar_without_agent_returns_failure() -> None:
    router = SignalRouter(active_executor=MockExecutor())
    ctx = SignalRouterContext(ledger=MockLedger(), freqai=AsyncMock(), lobstar_agent=None)

    result = await router.route({"source": "lobstar_llm", "raw": "text"}, ctx)

    assert result["status"] == "FAILED"
    assert "disabled" in result["reason"].lower()


@pytest.mark.asyncio
async def test_routes_regex_without_passive_executor_fails_fast() -> None:
    router = SignalRouter(passive_executor=None)
    ctx = SignalRouterContext(ledger=MockLedger(), freqai=AsyncMock())

    with pytest.raises(ValueError, match="passive_executor is required"):
        await router.route({"asset": "SOL", "action": "BUY", "price": 0.5}, ctx)
