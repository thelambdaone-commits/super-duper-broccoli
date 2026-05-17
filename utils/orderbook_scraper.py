"""
Polymarket Orderbook Scraper
=============================
Scrape les données microstructure (orderbook) via l'API publique CLOB.
Récupère les 3 premiers niveaux du carnet d'ordres pour les marchés actifs.
"""

import asyncio
import logging
import time
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime, timezone

import httpx

logger = logging.getLogger("OrderbookScraper")

CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"


@dataclass
class OrderBookLevel:
    """Niveau du carnet d'ordres."""
    price: float
    size: float
    total: float = 0.0


@dataclass
class MicrostructureSnapshot:
    """Snapshot de la microstructure d'un marché."""
    token_id: str
    question: str
    timestamp: float
    bids: List[OrderBookLevel] = field(default_factory=list)
    asks: List[OrderBookLevel] = field(default_factory=list)
    spread_bps: float = 0.0
    mid_price: float = 0.0
    micro_price: float = 0.0
    depth_bid_3: float = 0.0
    depth_ask_3: float = 0.0
    imbalance: float = 0.5


class PolymarketOrderbookScraper:
    """
    Scraper pour les données microstructure Polymarket.
    Utilise l'API publique CLOB sans authentification.
    """

    def __init__(self, update_interval: float = 5.0):
        self.update_interval = update_interval
        self._client = httpx.AsyncClient(timeout=10.0)
        self._markets_cache: List[Dict] = []
        self._last_market_fetch = 0.0
        self._running = False

    async def close(self):
        await self._client.aclose()

    async def get_markets(self, limit: int = 50) -> List[Dict]:
        """Récupère les marchés actifs depuis l'API CLOB (plus complet)."""
        now = time.time()
        if now - self._last_market_fetch < 60 and self._markets_cache:
            return self._markets_cache

        try:
            resp = await self._client.get(
                f"{CLOB_BASE}/markets",
                params={
                    "limit": limit,
                }
            )
            if resp.status_code == 200:
                data = resp.json()
                markets = data.get("data", []) if isinstance(data, dict) else data
                self._markets_cache = [m for m in markets if m.get("active") and m.get("tokens")]
                self._last_market_fetch = now
                logger.info(f"Fetched {len(self._markets_cache)} active markets")
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")

        return self._markets_cache

    async def get_orderbook(self, token_id: str) -> Optional[Dict]:
        """Récupère l'orderbook pour un token_id donné."""
        try:
            resp = await self._client.get(
                f"{CLOB_BASE}/book",
                params={"token_id": token_id}
            )
            if resp.status_code == 200:
                return resp.json()
        except Exception as e:
            logger.warning(f"Failed to get orderbook for {token_id}: {e}")
        return None

    async def get_order_book_snapshot(self, token_id: str, question: str) -> Optional[MicrostructureSnapshot]:
        """Récupère un snapshot complet de l'orderbook."""
        book_data = await self.get_orderbook(token_id)
        if not book_data:
            return None

        bids = []
        asks = []

        for level in book_data.get("bids", [])[:3]:
            bids.append(OrderBookLevel(
                price=float(level.get("price", 0)),
                size=float(level.get("size", 0))
            ))

        for level in book_data.get("asks", [])[:3]:
            asks.append(OrderBookLevel(
                price=float(level.get("price", 0)),
                size=float(level.get("size", 0))
            ))

        if not bids or not asks:
            return None

        bid_price = bids[0].price
        ask_price = asks[0].price
        mid_price = (bid_price + ask_price) / 2
        spread_bps = ((ask_price - bid_price) / mid_price * 10000) if mid_price > 0 else 0

        depth_bid = sum(b.size for b in bids[:3])
        depth_ask = sum(a.size for a in asks[:3])
        imbalance = depth_bid / (depth_bid + depth_ask) if (depth_bid + depth_ask) > 0 else 0.5

        micro_price = (bid_price * depth_ask + ask_price * depth_bid) / (depth_bid + depth_ask) if (depth_bid + depth_ask) > 0 else mid_price

        return MicrostructureSnapshot(
            token_id=token_id,
            question=question,
            timestamp=time.time(),
            bids=bids,
            asks=asks,
            spread_bps=spread_bps,
            mid_price=mid_price,
            micro_price=micro_price,
            depth_bid_3=depth_bid,
            depth_ask_3=depth_ask,
            imbalance=imbalance,
        )

    async def scan_markets(self, max_markets: int = 20) -> List[MicrostructureSnapshot]:
        """Scanne les marchés et retourne les snapshots microstructure."""
        snapshots = []
        markets = await self.get_markets(limit=max_markets)

        for market in markets:
            try:
                tokens = market.get("tokens", [])
                if not tokens:
                    continue

                for token in tokens:
                    token_id = token.get("token_id")
                    if not token_id:
                        continue

                    outcome = token.get("outcome", "").lower()
                    if outcome not in ["yes", "no"]:
                        continue

                    snapshot = await self.get_order_book_snapshot(
                        token_id,
                        market.get("question", "Unknown")
                    )

                    if snapshot:
                        snapshots.append(snapshot)
                        logger.debug(f"✓ {market.get('question', 'Unknown')[:40]}... | {outcome}: {snapshot.mid_price:.2f} | Spread: {snapshot.spread_bps:.1f}bps")

            except Exception as e:
                logger.warning(f"Error processing market: {e}")

        return snapshots

    async def start_scraping(self, callback=None, interval: float = 30.0):
        """Démarre le scraping continu."""
        self._running = True
        logger.info("📡 Starting orderbook scraper...")

        while self._running:
            try:
                snapshots = await self.scan_markets()
                logger.info(f"📊 Scraped {len(snapshots)} orderbooks")

                if callback and snapshots:
                    await callback(snapshots)

                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scraper error: {e}")
                await asyncio.sleep(5)

    def stop_scraping(self):
        """Arrête le scraping."""
        self._running = False


async def test_scraper():
    """Test du scraper."""
    scraper = PolymarketOrderbookScraper()
    
    print("🧪 Testing Polymarket Orderbook Scraper...")
    
    snapshots = await scraper.scan_markets(max_markets=10)
    
    print(f"\n✅ Found {len(snapshots)} orderbooks:\n")
    
    for s in snapshots[:5]:
        print(f"📊 {s.question[:50]}...")
        print(f"   Mid: {s.mid_price:.2f} | Spread: {s.spread_bps:.1f}bps")
        print(f"   Depth: Bids={s.depth_bid_3:.0f} | Asks={s.depth_ask_3:.0f}")
        print(f"   Imbalance: {s.imbalance:.2%}")
        print()
    
    await scraper.close()
    return snapshots


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(test_scraper())