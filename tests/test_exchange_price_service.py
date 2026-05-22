import asyncio

import pytest

from utils.exchange_price_service import ExchangePriceService


class _FakeExchange:
    def __init__(self):
        self.closed = False

    async def fetch_ticker(self, ticker):
        await asyncio.sleep(10)
        return {"last": 1.0}

    async def close(self):
        self.closed = True


@pytest.mark.asyncio
async def test_exchange_price_service_closes_exchanges_on_cancel() -> None:
    service = object.__new__(ExchangePriceService)
    service.tickers = ["BTC/USDT"]
    service.binance = _FakeExchange()
    service.coinbase = _FakeExchange()
    service.latest_prices = {"BINANCE": {}, "COINBASE": {}}
    service._running = False
    service._closed = False

    task = asyncio.create_task(service.start())
    await asyncio.sleep(0)
    task.cancel()

    result = await asyncio.gather(task, return_exceptions=True)

    assert isinstance(result[0], asyncio.CancelledError)
    assert service.binance.closed is True
    assert service.coinbase.closed is True
