import asyncio
import contextlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Callable, Optional

import websockets
from eth_abi.codec import ABICodec
from eth_abi.registry import registry
from web3 import Web3
from web3.middleware import ExtraDataToPOAMiddleware

logger = logging.getLogger("PolymarketMonitor")

MATCH_ORDERS_SIGNATURE = os.getenv("MATCH_ORDERS_SIGNATURE", "0xd2539b37")
WS_SUB_METHOD = os.getenv("WS_SUBSCRIPTION_METHOD", "alchemy_pendingTransactions")
WS_FALLBACK_METHOD = "eth_newPendingTransactions"
DEFAULT_RECONNECT_DELAY = 5
DEFAULT_MAX_RECONNECT_DELAY = 60


class PolymarketMonitor:
    def __init__(
        self,
        on_signal: Callable[[dict], None],
        target_wallet: Optional[str] = None,
        ws_url: Optional[str] = None,
        rpc_url: Optional[str] = None,
        match_signature: str = MATCH_ORDERS_SIGNATURE,
    ) -> None:
        self.on_signal = on_signal
        self.target_wallet = Web3.to_checksum_address(target_wallet) if target_wallet else None
        self.ws_url = ws_url or os.getenv("WS_URL", "")
        self.rpc_url = rpc_url or os.getenv("POLYGON_RPC_URL") or os.getenv("RPC_URL", "")
        self.match_signature = match_signature
        self._running = False
        self._health_task: Optional[asyncio.Task] = None
        self._message_count = 0
        self._start_time: Optional[datetime] = None

        if self.rpc_url:
            self.web3 = Web3(Web3.WebsocketProvider(self.rpc_url) if self.rpc_url.startswith("ws") else Web3.HTTPProvider(self.rpc_url))
            self.web3.middleware_onion.inject(ExtraDataToPOAMiddleware, layer=0)
        else:
            self.web3 = None

        if not self.match_signature.startswith("0x"):
            self.match_signature = "0x" + self.match_signature

    def decode_match_orders(self, input_data: str) -> Optional[dict]:
        try:
            func_sig = input_data[:10]
            if func_sig.lower() != self.match_signature.lower():
                return None
            data_bytes = bytes.fromhex(input_data[10:])
            codec = ABICodec(registry)
            param_types = [
                "tuple(address,uint256,uint256,uint256,uint8,uint8,uint64,uint64,bytes)",
                "tuple(address,uint256,uint256,uint256,uint8,uint8,uint64,uint64,bytes)",
                "uint256",
            ]
            decoded = codec.decode(param_types, data_bytes)
            taker_order = decoded[0]
            maker_order = decoded[1]
            return {
                "maker": taker_order[0],
                "taker": maker_order[0],
                "makerAmount": taker_order[1],
                "takerAmount": maker_order[1],
                "tokenId": taker_order[2],
                "side": taker_order[4],
                "feeRateBps": maker_order[5] if len(maker_order) > 5 else 0,
            }
        except Exception as e:
            logger.debug(f"decode_match_orders failed: {e}")
            return None

    def is_target_trade(self, decoded: dict) -> bool:
        if not decoded:
            return False
        if self.target_wallet is None:
            return True
        return (
            decoded.get("maker", "").lower() == self.target_wallet.lower()
            or decoded.get("taker", "").lower() == self.target_wallet.lower()
        )

    async def _health_checker(self) -> None:
        while self._running:
            await asyncio.sleep(30)
            uptime = datetime.now(timezone.utc) - self._start_time if self._start_time else 0
            logger.info(
                f"HEALTH: uptime={uptime}, messages={self._message_count}, "
                f"target={'all' if self.target_wallet is None else self.target_wallet}"
            )

    async def _process_message(self, message: str) -> None:
        try:
            data = json.loads(message)
            if "params" not in data or "result" not in data.get("params", {}):
                return
            tx_data = data["params"]["result"]
            tx_hash = tx_data.get("hash", "")
            input_data = tx_data.get("input", "")
            if not input_data or not input_data.startswith(self.match_signature):
                return
            decoded = self.decode_match_orders(input_data)
            if not self.is_target_trade(decoded):
                return
            signal = {
                "source": "polymarket_onchain",
                "type": "copy_trade",
                "tx_hash": tx_hash,
                "token_id": str(decoded["tokenId"]),
                "side": "BUY" if decoded["side"] == 0 else "SELL",
                "maker_amount": str(decoded["makerAmount"]),
                "maker": decoded["maker"],
                "taker": decoded["taker"],
                "timestamp": datetime.now(timezone.UTC).isoformat(),
            }
            logger.info(f"ONCHAIN SIGNAL: {signal['side']} {signal['token_id']} from {signal['maker'][:10]}...")
            self._message_count += 1
            self.on_signal(signal)
        except json.JSONDecodeError:
            pass
        except Exception as e:
            logger.error(f"Error processing on-chain message: {e}")

    async def start(self) -> None:
        if not self.ws_url:
            logger.warning("PolymarketMonitor: WS_URL not set — monitor disabled")
            return
        self._running = True
        self._start_time = datetime.now(timezone.utc)
        self._health_task = asyncio.create_task(self._health_checker())
        reconnect_delay = DEFAULT_RECONNECT_DELAY
        subscribe_methods = [WS_SUB_METHOD, WS_FALLBACK_METHOD]
        subscribe_msg_template = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": None,
        }
        logger.info(f"PolymarketMonitor: starting — target={self.target_wallet or 'ALL'}")
        while self._running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    logger.info("PolymarketMonitor: WebSocket connected")
                    subscribed = False
                    for method in subscribe_methods:
                        msg = dict(subscribe_msg_template, params=[method])
                        await ws.send(json.dumps(msg))
                        ack = await ws.recv()
                        ack_data = json.loads(ack)
                        if "result" in ack_data:
                            logger.info(f"PolymarketMonitor: subscribed via {method}")
                            subscribed = True
                            break
                        logger.warning(f"PolymarketMonitor: {method} rejected, trying fallback")
                    if not subscribed:
                        logger.error("PolymarketMonitor: all subscription methods failed")
                        await asyncio.sleep(reconnect_delay)
                        reconnect_delay = min(reconnect_delay * 2, DEFAULT_MAX_RECONNECT_DELAY)
                        continue
                    reconnect_delay = DEFAULT_RECONNECT_DELAY
                    while self._running:
                        message = await ws.recv()
                        await self._process_message(message)
            except websockets.exceptions.ConnectionClosed:
                logger.warning(f"PolymarketMonitor: connection lost, reconnecting in {reconnect_delay}s")
            except Exception as e:
                logger.error(f"PolymarketMonitor: error: {e}")
            if not self._running:
                break
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, DEFAULT_MAX_RECONNECT_DELAY)

    async def stop(self) -> None:
        self._running = False
        if self._health_task:
            self._health_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._health_task
