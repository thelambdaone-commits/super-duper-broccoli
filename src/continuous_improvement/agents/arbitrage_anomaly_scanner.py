import asyncio
import logging
import httpx
from typing import Dict, List, Any

from utils.market_watchlist import get_polymarket_watchlist

logger = logging.getLogger("ArbitrageAnomalyScanner")


class ArbitrageAnomalyScannerAgent:
    """
    Agent de scan des anomalies d'arbitrage.
    Détecte les violations de Kolmogorov et les opportunités cross-marchés.
    """

    def __init__(self, arbitrage_engine=None):
        self.engine = arbitrage_engine
        self._running = False
        self._check_interval = 5
        self._tickers = get_polymarket_watchlist(limit=50, categories=["crypto", "politics", "technology", "macro"])
        self._client = httpx.AsyncClient(timeout=5.0)

    async def start(self, tickers: List[str] = None, interval: float = 5.0):
        if tickers:
            self._tickers = tickers
        self._check_interval = interval
        self._running = True

        logger.info(f"🚀 Arbitrage Anomaly Scanner started for {self._tickers}")
        asyncio.create_task(self._scan_loop())

    async def stop(self):
        self._running = False
        await self._client.aclose()
        logger.info("🛑 Arbitrage Scanner stopped")

    async def _scan_loop(self):
        while self._running:
            for ticker in self._tickers:
                try:
                    await self._check_arbitrage_opportunity(ticker)
                except Exception as e:
                    logger.error(f"Scan error for {ticker}: {e}")

            await asyncio.sleep(self._check_interval)

    async def _check_arbitrage_opportunity(self, ticker: str):
        try:
            url = f"https://clob.polymarket.com/markets/{ticker}"
            resp = await self._client.get(url)

            if resp.status_code != 200:
                return

            data = resp.json()
            outcome = data.get("outcome", 0.5)

            kolmogorov_result = self.engine.detecter_anomalie_kolmogorov(
                {"YES": outcome, "NO": 1 - outcome}
            )

            if kolmogorov_result.get("detected"):
                logger.warning(f"⚠️ ANOMALY DETECTED: {ticker} - {kolmogorov_result}")

                if kolmogorov_result.get("theoretical_edge", 0) >= self.engine.trigger_threshold:
                    await self._trigger_basket_execution(ticker, kolmogorov_result)

        except Exception as e:
            logger.debug(f"Failed to scan {ticker}: {e}")

    async def _trigger_basket_execution(self, ticker: str, anomaly: Dict):
        logger.info(f"🎯 Triggering basket execution for {ticker}")

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "tickers": self._tickers,
            "interval": self._check_interval
        }
