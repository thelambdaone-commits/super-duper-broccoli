import asyncio
import logging
import os
import time
import feedparser
from typing import List, Dict, Optional, Any

logger = logging.getLogger("RSSAggregator")

class RSSAggregator:
    """
    Simple RSS news aggregator to replace paid search APIs.
    Fetches market intelligence from configured news feeds.
    """
    def __init__(self, feeds: Optional[List[str]] = None, poll_interval: int = 300):
        self.feeds = feeds or os.getenv("NEWS_FEEDS", "").split(",")
        self.feeds = [f.strip() for f in self.feeds if f.strip()]
        self.poll_interval = poll_interval
        self._seen = set()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._latest_news: List[Dict[str, Any]] = []

    async def start(self):
        self._running = True
        logger.info(f"RSS Aggregator started with {len(self.feeds)} feeds.")
        self._task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
        logger.info("RSS Aggregator stopped.")

    async def _poll_loop(self):
        while self._running:
            try:
                await self.fetch_once()
            except Exception as e:
                logger.error(f"RSS Poll error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def fetch_once(self) -> List[Dict[str, Any]]:
        new_items = []
        for url in self.feeds:
            try:
                # Use to_thread for blocking feedparser call
                d = await asyncio.to_thread(feedparser.parse, url)
                for e in d.entries:
                    uid = e.get("id") or e.get("link") or (e.get("title", "") + "|" + e.get("published", ""))
                    if uid in self._seen:
                        continue
                    self._seen.add(uid)
                    item = {
                        "title": e.get("title"),
                        "link": e.get("link"),
                        "summary": e.get("summary"),
                        "published": e.get("published"),
                        "source_url": url
                    }
                    new_items.append(item)
                    logger.debug(f"New article: {item['title']}")
            except Exception as e:
                logger.warning(f"Failed to fetch RSS from {url}: {e}")
        
        if new_items:
            self._latest_news = (new_items + self._latest_news)[:100] # Keep last 100
        return new_items

    def get_latest_news(self, limit: int = 10) -> List[Dict[str, Any]]:
        return self._latest_news[:limit]

    def search_news(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        query = query.lower()
        results = [
            n for n in self._latest_news 
            if query in (n.get("title") or "").lower() or query in (n.get("summary") or "").lower()
        ]
        return results[:limit]

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    feeds = ["https://cointelegraph.com/rss", "https://www.coindesk.com/arc/outboundfeeds/rss/"]
    agg = RSSAggregator(feeds=feeds)
    async def test():
        await agg.fetch_once()
        print(f"Total news: {len(agg.get_latest_news())}")
        for n in agg.get_latest_news(5):
            print(f"- {n['title']}")
    
    asyncio.run(test())
