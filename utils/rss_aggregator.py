import asyncio
import logging
import os
import xml.etree.ElementTree as ET
from typing import List, Dict, Optional, Any
from urllib import request
from urllib.error import URLError

logger = logging.getLogger("RSSAggregator")


def _parse_rss_bytes(data: bytes, source_url: str) -> List[Dict[str, Any]]:
    """Parse RSS 2.0 or Atom feed bytes into a list of news dicts."""
    items = []
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        logger.warning(f"Failed to parse XML from {source_url}: {e}")
        return items

    # RSS 2.0: <rss><channel><item>...
    # Atom: <feed><entry>...
    ns = {"atom": "http://www.w3.org/2005/Atom"}

    # Try RSS 2.0
    channel = root.find("channel")
    if channel is not None:
        for item in channel.findall("item"):
            title_el = item.find("title")
            link_el = item.find("link")
            desc_el = item.find("description")
            pub_el = item.find("pubDate")
            guid_el = item.find("guid")
            uid = guid_el.text if guid_el is not None and guid_el.text else None
            if not uid:
                uid = link_el.text if link_el is not None and link_el.text else ""
            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            items.append({
                "title": title,
                "link": link_el.text.strip() if link_el is not None and link_el.text else "",
                "summary": desc_el.text.strip() if desc_el is not None and desc_el.text else "",
                "published": pub_el.text.strip() if pub_el is not None and pub_el.text else "",
                "source_url": source_url,
            })
    else:
        # Try Atom
        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            link_el = entry.find("atom:link", ns)
            summary_el = entry.find("atom:summary", ns)
            published_el = entry.find("atom:published", ns)
            id_el = entry.find("atom:id", ns)
            uid = id_el.text if id_el is not None and id_el.text else ""
            title = title_el.text.strip() if title_el is not None and title_el.text else ""
            link = link_el.get("href", "") if link_el is not None else ""
            summary = summary_el.text.strip() if summary_el is not None and summary_el.text else ""
            published = published_el.text.strip() if published_el is not None and published_el.text else ""
            items.append({
                "title": title,
                "link": link,
                "summary": summary,
                "published": published,
                "source_url": source_url,
            })

    return items


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
                data = await asyncio.to_thread(self._fetch_url, url)
                if not data:
                    continue
                entries = _parse_rss_bytes(data, url)
                for item in entries:
                    uid = item.get("link") or item.get("title", "")
                    if not uid or uid in self._seen:
                        continue
                    self._seen.add(uid)
                    new_items.append(item)
                    logger.debug(f"New article: {item['title']}")
            except Exception as e:
                logger.warning(f"Failed to fetch RSS from {url}: {e}")

        if new_items:
            self._latest_news = (new_items + self._latest_news)[:100]
        return new_items

    @staticmethod
    def _fetch_url(url: str) -> Optional[bytes]:
        try:
            with request.urlopen(url, timeout=15) as resp:
                return resp.read()
        except URLError as e:
            logger.warning(f"URL error fetching {url}: {e}")
            return None

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
