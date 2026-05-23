from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

import httpx

from utils.feature_store import FeatureStore

logger = logging.getLogger("WebScraper")

POLYMARKET_GAMMA_API_URL = os.getenv(
    "POLYMARKET_GAMMA_API_URL", "https://gamma-api.polymarket.com"
)

EventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass(frozen=True)
class WebScraperConfig:
    gamma_base_url: str = POLYMARKET_GAMMA_API_URL
    poll_interval_seconds: float = 2.0
    market_limit: int = 100
    timeout_seconds: float = 5.0
    min_volume_delta: float = 1.0


class WebScraper:
    """
    Low-latency Polymarket web/API polling layer.

    Polls Gamma market metadata for new market slugs, volume changes and
    resolution state changes, then persists raw events to FeatureStore.
    """

    def __init__(
        self,
        store: Optional[FeatureStore] = None,
        config: Optional[WebScraperConfig] = None,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.store = store
        self.config = config or WebScraperConfig()
        self._client = client or httpx.AsyncClient(
            timeout=httpx.Timeout(self.config.timeout_seconds)
        )
        self._owns_client = client is None
        self._running = False
        self._seen: dict[str, dict[str, Any]] = {}

    async def close(self) -> None:
        self._running = False
        if self._owns_client:
            await self._client.aclose()

    async def fetch_active_markets(self) -> list[dict[str, Any]]:
        response = await self._client.get(
            f"{self.config.gamma_base_url.rstrip('/')}/markets",
            params={
                "active": "true",
                "closed": "false",
                "limit": self.config.market_limit,
                "order": "volume",
                "ascending": "false",
            },
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            data = data.get("data", [])
        return [item for item in data if isinstance(item, dict)]

    def detect_events(self, markets: list[dict[str, Any]]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        now = time.time()
        for market in markets:
            slug = str(market.get("slug") or market.get("market_slug") or "")
            condition_id = str(market.get("conditionId") or market.get("condition_id") or "")
            key = slug or condition_id
            if not key:
                continue

            prev = self._seen.get(key)
            volume = _to_float(market.get("volume"))
            closed = bool(market.get("closed", False))
            active = bool(market.get("active", True))

            if prev is None:
                events.append(self._event("market_seen", market, now))
            else:
                prev_volume = _to_float(prev.get("volume"))
                if abs(volume - prev_volume) >= self.config.min_volume_delta:
                    event = self._event("volume_change", market, now)
                    event["volume_delta"] = volume - prev_volume
                    events.append(event)
                if closed and not bool(prev.get("closed", False)):
                    events.append(self._event("resolution_seen", market, now))
                if active != bool(prev.get("active", True)):
                    events.append(self._event("active_state_change", market, now))

            self._seen[key] = dict(market)
        return events

    def persist_event(self, event: dict[str, Any]) -> int:
        if not self.store:
            return 0
        payload = dict(event.get("market") or {})
        payload["_event"] = {
            "type": event["event_type"],
            "timestamp": event["timestamp"],
            "volume_delta": event.get("volume_delta", 0.0),
        }
        return self.store.record_web_event(
            source="polymarket_gamma",
            event_type=event["event_type"],
            payload=payload,
            market_slug=str(event.get("market_slug", "")),
            condition_id=str(event.get("condition_id", "")),
            timestamp=float(event["timestamp"]),
        )

    async def poll_once(self, callback: Optional[EventCallback] = None) -> list[dict[str, Any]]:
        markets = await self.fetch_active_markets()
        events = self.detect_events(markets)
        for event in events:
            self.persist_event(event)
            if callback:
                maybe = callback(event)
                if asyncio.iscoroutine(maybe):
                    await maybe
        return events

    async def run(self, callback: Optional[EventCallback] = None) -> None:
        self._running = True
        logger.info("Starting Polymarket web scraper")
        while self._running:
            try:
                await self.poll_once(callback=callback)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Web scraper poll failed: %s", exc)
            await asyncio.sleep(self.config.poll_interval_seconds)

    def stop(self) -> None:
        self._running = False

    @staticmethod
    def _event(event_type: str, market: dict[str, Any], timestamp: float) -> dict[str, Any]:
        return {
            "event_type": event_type,
            "timestamp": timestamp,
            "market_slug": market.get("slug") or market.get("market_slug") or "",
            "condition_id": market.get("conditionId") or market.get("condition_id") or "",
            "market": dict(market),
        }


def _to_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
