from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Optional
from pydantic import BaseModel, Field, ValidationError

from utils.feature_store import FeatureStore

logger = logging.getLogger("CLOBListener")

POLYMARKET_CLOB_WS_URL = os.getenv(
    "POLYMARKET_CLOB_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/market"
)

SnapshotCallback = Callable[[dict[str, Any]], Awaitable[None] | None]

class Level(BaseModel):
    price: float
    size: float

class ClobSnapshot(BaseModel):
    asset_id: str = Field(alias="asset_id", default="")
    market: str = Field(alias="market", default="")
    bids: list[Level] = Field(default_factory=list)
    asks: list[Level] = Field(default_factory=list)
    timestamp: str | int | float = Field(alias="timestamp", default_factory=time.time)

@dataclass(frozen=True)
class CLOBListenerConfig:
    ws_url: str = POLYMARKET_CLOB_WS_URL
    reconnect_delay_seconds: float = 1.0
    heartbeat_seconds: float = 15.0


class CLOBListener:
    """
    WebSocket listener for Polymarket CLOB market-channel payloads.

    The listener keeps parsing pure and testable: `parse_message()` accepts raw
    websocket text/bytes and returns normalized microstructure snapshots.
    """

    def __init__(
        self,
        token_ids: Optional[list[str]] = None,
        store: Optional[FeatureStore] = None,
        config: Optional[CLOBListenerConfig] = None,
    ) -> None:
        self.token_ids = list(token_ids) if token_ids else []
        self.store = store
        self.config = config or CLOBListenerConfig()
        self._running = False
        self._subscription_queue: asyncio.Queue[list[str]] = asyncio.Queue()

    def subscribe(self, token_ids: list[str]) -> None:
        """Schedule a new subscription update."""
        if not token_ids:
            return
        # Add to local list to ensure persistence across reconnects
        for tid in token_ids:
            if tid not in self.token_ids:
                self.token_ids.append(tid)

        self._subscription_queue.put_nowait(token_ids)
        logger.info("Dynamic subscription scheduled for %s token IDs", len(token_ids))

    @staticmethod
    def subscription_message(token_ids: list[str]) -> str:
        return json.dumps(
            {
                "type": "market",
                "assets_ids": token_ids,
            }
        )

    def parse_message(self, message: str | bytes) -> list[dict[str, Any]]:
        if isinstance(message, bytes):
            message = message.decode("utf-8")
        message = message.strip()
        if not message:
            return []
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            logger.debug("Ignoring non-JSON CLOB websocket frame: %r", message[:120])
            return []
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
        
        # 0. Resolve ticker for institutional analytics
        ticker = snapshot.get("token_id", "UNKNOWN")
        market_slug = str(snapshot.get("market", "")).lower()
        if "bitcoin" in market_slug or "btc-" in market_slug:
            ticker = "BTC"
        elif "ethereum" in market_slug or "eth-" in market_slug:
            ticker = "ETH"
        elif "solana" in market_slug or "sol-" in market_slug:
            ticker = "SOL"

        # 1. Record individual features for standard lookups
        self.store.record_feature(
            snapshot["token_id"],
            "mid_price",
            snapshot["mid_price"],
            timestamp=snapshot["timestamp"],
        )
        self.store.record_feature(
            snapshot["token_id"],
            "spread_bps",
            snapshot["spread_bps"],
            timestamp=snapshot["timestamp"],
        )
        self.store.record_feature(
            snapshot["token_id"],
            "order_imbalance",
            snapshot["order_imbalance"],
            timestamp=snapshot["timestamp"],
        )

        # 2. Record full microstructure for institutional analytics (Gaps: microfish fix)
        self.store.record_microstructure(
            ticker=ticker,
            bid_volume=snapshot["bid_depth_3"],
            ask_volume=snapshot["ask_depth_3"],
            spread=snapshot["spread_bps"],
            mid_price=snapshot["mid_price"],
            order_imbalance=snapshot["order_imbalance"],
            raw_json=snapshot
        )

        # 3. Record raw web event for backtesting/audits
        self.store.record_web_event(
            source="polymarket_clob_ws",
            event_type="orderbook_snapshot",
            payload=snapshot,
            condition_id=str(snapshot.get("market", "")),
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
        import websockets

        self._running = True
        while self._running:
            try:
                async with websockets.connect(
                    self.config.ws_url,
                    ping_interval=self.config.heartbeat_seconds,
                ) as websocket:
                    # Initial subscription
                    if self.token_ids:
                        await websocket.send(self.subscription_message(self.token_ids))

                    # Task to handle dynamic subscriptions
                    async def subscription_worker():
                        while True:
                            new_ids = await self._subscription_queue.get()
                            try:
                                await websocket.send(self.subscription_message(new_ids))
                                logger.info("✅ Sent dynamic subscription for: %s", new_ids)
                            finally:
                                self._subscription_queue.task_done()

                    worker_task = asyncio.create_task(subscription_worker())

                    try:
                        async for message in websocket:
                            try:
                                await self.handle_message(message, callback=callback)
                            except json.JSONDecodeError as exc:
                                logger.debug("Skipping malformed CLOB frame: %s", exc)
                            except Exception as e:
                                logger.warning("CLOB websocket stream error: %s", e)
                                raise
                    finally:
                        worker_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError):
                            await worker_task

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("CLOB websocket disconnected: %s", exc)
                await asyncio.sleep(self.config.reconnect_delay_seconds)

    def stop(self) -> None:
        self._running = False

    @staticmethod
    def _normalize_snapshot(item: dict[str, Any]) -> Optional[dict[str, Any]]:
        # 1. Strictly validate using Pydantic
        try:
            snapshot = ClobSnapshot.model_validate(item)
        except ValidationError as e:
            # Fallback to manual for semi-malformed but usable items
            # or log and skip for total failure
            logger.debug(f"Pydantic validation failed, attempting legacy normalization: {e}")
            token_id = str(item.get("asset_id") or item.get("token_id") or item.get("asset") or "")
            if not token_id:
                return None
            bids_raw = item.get("bids") or item.get("buys") or []
            asks_raw = item.get("asks") or item.get("sells") or []
            ts_raw = item.get("timestamp") or item.get("ts")

            # Map back to a clean dict that mimics the validated output
            snapshot = ClobSnapshot(
                asset_id=token_id,
                bids=[Level(price=float(l.get("price", 0)), size=float(l.get("size", 0))) for l in (bids_raw if isinstance(bids_raw, list) else [])],
                asks=[Level(price=float(l.get("price", 0)), size=float(l.get("size", 0))) for l in (asks_raw if isinstance(asks_raw, list) else [])],
                timestamp=ts_raw if ts_raw else time.time()
            )

        token_id = snapshot.asset_id
        bids = [{"price": l.price, "size": l.size} for l in snapshot.bids]
        asks = [{"price": l.price, "size": l.size} for l in snapshot.asks]

        if not bids and not asks:
            return None

        best_bid = bids[0]["price"] if bids else 0.0
        best_ask = asks[0]["price"] if asks else 0.0
        mid = (best_bid + best_ask) / 2.0 if best_bid > 0 and best_ask > 0 else 0.0
        spread_bps = ((best_ask - best_bid) / mid * 10_000.0) if mid > 0 else 0.0
        bid_depth = sum(level["size"] for level in bids[:3])
        ask_depth = sum(level["size"] for level in asks[:3])
        total_depth = bid_depth + ask_depth
        imbalance = bid_depth / total_depth if total_depth > 0 else 0.5
        timestamp = _timestamp(snapshot.timestamp)

        return {
            "token_id": token_id,
            "market": item.get("market") or item.get("condition_id") or "",
            "timestamp": timestamp,
            "best_bid": best_bid,
            "best_ask": best_ask,
            "mid_price": mid,
            "spread_bps": spread_bps,
            "bid_depth_3": bid_depth,
            "ask_depth_3": ask_depth,
            "order_imbalance": imbalance,
            "raw_event_type": item.get("event_type") or item.get("type") or "",
        }


def _levels(raw_levels: Any) -> list[dict[str, float]]:
    levels = []
    for level in raw_levels:
        try:
            price = float(level.get("price", 0.0))
            size = float(level.get("size", 0.0))
        except (AttributeError, TypeError, ValueError):
            continue
        if price > 0 and size > 0:
            levels.append({"price": price, "size": size})
    return levels


def _timestamp(value: Any) -> float:
    try:
        ts = float(value)
    except (TypeError, ValueError):
        return time.time()
    return ts / 1000.0 if ts > 10_000_000_000 else ts
