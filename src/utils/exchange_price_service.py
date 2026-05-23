import logging
import asyncio
import ccxt.async_support as ccxt
from typing import Dict, List, Optional

logger = logging.getLogger("ExchangePriceService")

class ExchangePriceService:
    """
    Asynchronous service to fetch live prices from multiple exchanges.
    Feeds the DivergenceDetector in the Orchestrator.
    """

    def __init__(self, tickers: List[str] = ["BTC/USDT", "ETH/USDT", "SOL/USDT"]):
        self.tickers = tickers
        self.binance = ccxt.binance({"enableRateLimit": True})
        self.coinbase = ccxt.coinbaseadvanced({"enableRateLimit": True})
        self.latest_prices: Dict[str, Dict[str, float]] = {
            "BINANCE": {},
            "COINBASE": {}
        }
        self._running = False
        self._closed = False

    async def start(self):
        self._running = True
        logger.info(f"🚀 Starting ExchangePriceService for {self.tickers}")
        try:
            while self._running:
                try:
                    # Fetch Binance
                    for ticker in self.tickers:
                        ticker_data = await self.binance.fetch_ticker(ticker)
                        if ticker_data and "last" in ticker_data:
                            # Normalize ticker name for Polymarket (e.g. BTC/USDT -> BTC)
                            polymarket_ticker = ticker.split("/")[0]
                            self.latest_prices["BINANCE"][polymarket_ticker] = ticker_data["last"]

                    # Fetch Coinbase
                    for ticker in self.tickers:
                        # Coinbase tickers might use different symbols, e.g. BTC-USD
                        cb_ticker = ticker.replace("/", "-").replace("USDT", "USD")
                        ticker_data = await self.coinbase.fetch_ticker(cb_ticker)
                        if ticker_data and "last" in ticker_data:
                            polymarket_ticker = ticker.split("/")[0]
                            self.latest_prices["COINBASE"][polymarket_ticker] = ticker_data["last"]

                    await asyncio.sleep(2) # Poll every 2 seconds
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.debug(f"Price fetch error: {e}")
                    await asyncio.sleep(5)
        finally:
            await self._close_exchanges()

    async def stop(self):
        self._running = False
        await self._close_exchanges()
        logger.info("🛑 ExchangePriceService stopped")

    async def _close_exchanges(self):
        if self._closed:
            return
        self._closed = True
        await asyncio.gather(
            self.binance.close(),
            self.coinbase.close(),
            return_exceptions=True,
        )

    def get_prices(self) -> Dict[str, Dict[str, float]]:
        return self.latest_prices
