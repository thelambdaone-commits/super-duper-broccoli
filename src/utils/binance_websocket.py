from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional

from utils.feature_store import FeatureStore

logger = logging.getLogger("BinanceWebSocket")

BINANCE_WS_URL = os.getenv(
    "BINANCE_WS_URL",
    "wss://stream.binance.com:9443/stream",
)

SnapshotCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


@dataclass(frozen=True)
class BinanceWebSocketConfig:
    ws_url: str = BINANCE_WS_URL
    reconnect_delay_seconds: float = 1.0
    heartbeat_seconds: float = 15.0


class BinanceWebSocketListener:
    """
    Minimal Binance WebSocket listener for live crypto features.

    The listener is source-agnostic at the persistence layer: it normalizes the
    incoming stream into a compact snapshot and writes it into FeatureStore.
    """

    def __init__(
        self,
        symbols: Optional[list[str]] = None,
        store: Optional[FeatureStore] = None,
        config: Optional[BinanceWebSocketConfig] = None,
    ) -> None:
        self.symbols = [symbol.upper() for symbol in (symbols or [])]
        self.store = store
        self.config = config or BinanceWebSocketConfig()
        self._running = False

    def subscription_url(self) -> str:
        streams = "/".join(f"{symbol.lower()}@bookTicker" for symbol in self.symbols)
        if not streams:
            return self.config.ws_url
        return f"{self.config.ws_url}?streams={streams}"

    def parse_message(self, message: str | bytes) -> list[dict[str, Any]]:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        payload = json.loads(message)
        items = payload if isinstance(payload, list) else [payload]
        snapshots = []
        for item in items:
            if not isinstance(item, dict):
                continue
            snapshot = self._normalize_snapshot(item)
            if snapshot:
                snapshots.append(snapshot)
        return snapshots

    def persist_snapshot(self, snapshot: dict[str, Any]) -> None:
        if not self.store:
            return
        self.store.record_microstructure(
            ticker=snapshot["ticker"],
            bid_volume=snapshot["bid_volume"],
            ask_volume=snapshot["ask_volume"],
            spread=snapshot["spread"],
            mid_price=snapshot["mid_price"],
            order_imbalance=snapshot["order_imbalance"],
            depth_imbalance=snapshot["depth_imbalance"],
            queue_velocity=0.0,
            liquidity_score=snapshot["liquidity_score"],
            raw_json=snapshot,
        )
        self.store.record_feature(
            snapshot["ticker"],
            "mid_price",
            snapshot["mid_price"],
            timestamp=snapshot["timestamp"],
        )
        self.store.record_feature(
            snapshot["ticker"],
            "spread_bps",
            snapshot["spread_bps"],
            timestamp=snapshot["timestamp"],
        )
        self.store.record_feature(
            snapshot["ticker"],
            "order_imbalance",
            snapshot["order_imbalance"],
            timestamp=snapshot["timestamp"],
        )
        self.store.record_web_event(
            source="binance_ws",
            event_type="book_ticker",
            payload=snapshot,
            market_slug=snapshot["ticker"],
            timestamp=snapshot["timestamp"],
        )
        if getattr(self.store, "_conn", None) is not None:
            self.store._conn.commit()

    async def handle_message(
        self,
        message: str | bytes,
        callback: Optional[SnapshotCallback] = None,
    ) -> list[dict[str, Any]]:
        snapshots = self.parse_message(message)
        for snapshot in snapshots:
            self.persist_snapshot(snapshot)
            if callback:
                maybe = callback(snapshot)
                if asyncio.iscoroutine(maybe):
                    await maybe
        return snapshots

    async def run(self, callback: Optional[SnapshotCallback] = None) -> None:
        import asyncio as _asyncio
        import websockets

        self._running = True
        url = self.subscription_url()
        while self._running:
            try:
                async with websockets.connect(
                    url,
                    ping_interval=self.config.heartbeat_seconds,
                ) as websocket:
                    async for message in websocket:
                        await self.handle_message(message, callback=callback)
            except _asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Binance websocket disconnected: %s", exc)
                await _asyncio.sleep(self.config.reconnect_delay_seconds)

    def stop(self) -> None:
        self._running = False

    @staticmethod
    def _normalize_snapshot(item: dict[str, Any]) -> Optional[dict[str, Any]]:
        data = item.get("data", item)
        symbol = str(
            data.get("s")
            or data.get("symbol")
            or data.get("ticker")
            or ""
        ).upper()
        if not symbol:
            return None

        try:
            best_bid = float(data.get("b", data.get("bidPrice", 0.0)) or 0.0)
            best_ask = float(data.get("a", data.get("askPrice", 0.0)) or 0.0)
            bid_qty = float(data.get("B", data.get("bidQty", 0.0)) or 0.0)
            ask_qty = float(data.get("A", data.get("askQty", 0.0)) or 0.0)
        except (TypeError, ValueError):
            return None

        mid = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0
        spread = max(best_ask - best_bid, 0.0)
        spread_bps = ((spread / mid) * 10_000.0) if mid > 0 else 0.0
        total_qty = bid_qty + ask_qty
        order_imbalance = bid_qty / total_qty if total_qty > 0 else 0.5
        liquidity_score = min((bid_qty + ask_qty) / 1_000.0, 1.0)
        timestamp = _timestamp(data.get("E") or data.get("timestamp"))

        return {
            "ticker": symbol,
            "timestamp": timestamp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid,
            "spread": spread,
            "spread_bps": spread_bps,
            "bid_volume": bid_qty,
            "ask_volume": ask_qty,
            "order_imbalance": order_imbalance,
            "depth_imbalance": order_imbalance,
            "liquidity_score": liquidity_score,
            "raw_event_type": item.get("stream") or data.get("e") or "bookTicker",
        }


def _timestamp(value: Any) -> float:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return time.time()
    return ts / 1000.0 if ts > 10_000_000_000 else ts
