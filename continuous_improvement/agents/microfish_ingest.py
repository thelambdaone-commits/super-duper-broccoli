import asyncio
import logging
import time
import json
from typing import Dict, List, Optional, Any
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("MicrofishAgent")


class MicrofishIngestAgent:
    """
    Agent de surveillance continue du carnet d'ordres Polymarket.
    Calcule l'Order Imbalance (OI) et archive les données microstructurelles.
    """

    def __init__(self, storage_path: str = "data/microfish_stream.jsonl"):
        self.storage_path = storage_path
        self.client = httpx.AsyncClient(timeout=5.0)
        self._running = False
        self._history: List[Dict] = []
        self._spread_history: List[float] = []

    async def start(self, tickers: List[str], interval: float = 1.0):
        self._running = True
        logger.info(f"Microfish agent started for {tickers}")

        while self._running:
            for ticker in tickers:
                try:
                    await self._capture_orderbook(ticker)
                except Exception as e:
                    logger.error(f"Error capturing {ticker}: {e}")

            await asyncio.sleep(interval)

    async def stop(self):
        self._running = False
        await self.client.aclose()
        logger.info("Microfish agent stopped")

    async def _capture_orderbook(self, ticker: str) -> Optional[Dict]:
        # Resolve ticker to active Polymarket token_id
        token_id = ticker
        if not ticker.startswith("0x") and not ticker.isdigit():
            try:
                from utils.market_scanner import MarketScanner
                scanner = MarketScanner()
                resolved = scanner.resolve_ticker_to_token_id(ticker)
                if resolved:
                    token_id = resolved
                else:
                    fallbacks = {
                        "BTC": "21742635293231363653130060240013007380969601353527263520038819166723064027732",
                        "ETH": "21742635293231363653130060240013007380969601353527263520038819166723064027733",
                        "SOL": "21742635293231363653130060240013007380969601353527263520038819166723064027734"
                    }
                    token_id = fallbacks.get(ticker.upper(), ticker)
            except Exception as ex:
                logger.warning(f"Failed resolving {ticker}: {ex}")

        url = f"https://clob.polymarket.com/book?token_id={token_id}"

        try:
            resp = await self.client.get(url)
            if resp.status_code != 200:
                return None

            data = resp.json()
            bids = data.get("bids", [])
            asks = data.get("asks", [])

            if not bids or not asks:
                return None

            bid_price = float(bids[0]["price"])
            ask_price = float(asks[0]["price"])
            spread = ask_price - bid_price
            mid = (bid_price + ask_price) / 2

            bid_vol = sum(float(b.get("size", 0)) for b in bids[:3])
            ask_vol = sum(float(a.get("size", 0)) for a in asks[:3])

            total = bid_vol + ask_vol
            oi = (bid_vol - ask_vol) / total if total > 0 else 0.0

            self._spread_history.append(spread)
            if len(self._spread_history) > 100:
                self._spread_history.pop(0)

            avg_spread = sum(self._spread_history) / len(self._spread_history) if self._spread_history else 0
            spread_divergence = spread / avg_spread if avg_spread > 0 else 1.0

            record = {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "ticker": ticker,
                "bid_price": bid_price,
                "ask_price": ask_price,
                "mid_price": mid,
                "spread": spread,
                "spread_divergence": spread_divergence,
                "bid_volume": bid_vol,
                "ask_volume": ask_vol,
                "order_imbalance": oi,
                "top_bid_size": float(bids[0].get("size", 0)),
                "top_ask_size": float(asks[0].get("size", 0)),
            }

            self._history.append(record)
            if len(self._history) > 1000:
                self._history.pop(0)

            await self._append_to_jsonl(record)

            if spread_divergence > 2.0:
                await self._trigger_learning("SPREAD_DIVERGENCE", record)

            return record

        except Exception as e:
            logger.error(f"Failed to fetch orderbook for {ticker}: {e}")
            return None

    async def _append_to_jsonl(self, record: Dict):
        try:
            with open(self.storage_path, "a") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as e:
            logger.error(f"Failed to write JSONL: {e}")

    async def _trigger_learning(self, trigger: str, data: Dict):
        logger.warning(f"LEARNING TRIGGER: {trigger} - {data['ticker']} spread divergence: {data['spread_divergence']:.2f}x")

    def get_current_oi(self, ticker: str) -> Optional[float]:
        for record in reversed(self._history):
            if record["ticker"] == ticker:
                return record["order_imbalance"]
        return None

    def get_spread_stats(self) -> Dict[str, float]:
        if not self._spread_history:
            return {"avg": 0, "max": 0, "min": 0, "current": 0}

        return {
            "avg": sum(self._spread_history) / len(self._spread_history),
            "max": max(self._spread_history),
            "min": min(self._spread_history),
            "current": self._spread_history[-1] if self._spread_history else 0
        }

    def get_latest_snapshot(self, ticker: str) -> Optional[Dict]:
        for record in reversed(self._history):
            if record["ticker"] == ticker:
                return record
        return None