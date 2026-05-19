import asyncio
import base64
import hmac
import json
import logging
import os
import time
from typing import Any, Awaitable, Callable, Optional

import websockets
from py_clob_client_v2 import ApiCreds

logger = logging.getLogger("UserCLOBListener")

USER_CLOB_WS_URL = os.getenv(
    "USER_CLOB_WS_URL", "wss://ws-subscriptions-clob.polymarket.com/ws/"
)

UserEventCallback = Callable[[dict[str, Any]], Awaitable[None] | None]


class UserCLOBListener:
    """
    WebSocket listener for Polymarket CLOB user-specific events (fills, cancels, etc.).
    """

    def __init__(
        self,
        api_creds: ApiCreds,
        ws_url: str = USER_CLOB_WS_URL,
        on_event: Optional[UserEventCallback] = None,
    ) -> None:
        self.api_creds = api_creds
        self.ws_url = ws_url
        self.on_event = on_event
        self._running = False

    def _generate_auth_payload(self) -> dict[str, Any]:
        """
        Generates the authentication payload required for the 'user' channel.
        """
        timestamp = str(int(time.time()))
        # Signature format for WebSocket: timestamp + "GET" + "/ws" + ""
        message = f"{timestamp}GET/ws"
        
        # API Secret is base64 encoded in Polymarket
        secret = base64.b64decode(self.api_creds.api_secret)
        signature = hmac.new(
            secret, message.encode("utf-8"), digestmod="sha256"
        ).digest()
        signature_b64 = base64.b64encode(signature).decode("utf-8")

        return {
            "type": "subscribe",
            "channel": "user",
            "auth": {
                "apiKey": self.api_creds.api_key,
                "passphrase": self.api_creds.api_passphrase,
                "timestamp": timestamp,
                "signature": signature_b64,
            },
        }

    async def run(self) -> None:
        self._running = True
        reconnect_delay = 1.0
        
        while self._running:
            try:
                async with websockets.connect(self.ws_url) as websocket:
                    logger.info("Connected to User CLOB WebSocket")
                    
                    # Send auth subscription
                    auth_payload = self._generate_auth_payload()
                    await websocket.send(json.dumps(auth_payload))
                    
                    async for message in websocket:
                        data = json.loads(message)
                        
                        # Handle pong for heartbeats if needed (usually websockets handles ping/pong)
                        if data.get("type") == "error":
                            logger.error(f"User CLOB WS Error: {data.get('message')}")
                            continue

                        await self.handle_event(data)
                        
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(f"User CLOB WebSocket disconnected: {exc}. Reconnecting in {reconnect_delay}s...")
                await asyncio.sleep(reconnect_delay)
                reconnect_delay = min(reconnect_delay * 2, 60.0)

    async def handle_event(self, event: dict[str, Any]) -> None:
        """
        Processes incoming user events.
        """
        event_type = event.get("event_type")
        if not event_type:
            return

        logger.debug(f"User event received: {event_type}")
        
        if event_type == "order":
            order_id = event.get("order_id")
            status = event.get("status")
            filled = event.get("filled_size")
            logger.info(f"Order Update: {order_id} | Status: {status} | Filled: {filled}")
        
        elif event_type == "trade":
            logger.info(f"Trade Execution (Fill): {event.get('size')} @ {event.get('price')} on {event.get('asset_id')}")

        if self.on_event:
            maybe = self.on_event(event)
            if asyncio.iscoroutine(maybe):
                await maybe

    def stop(self) -> None:
        self._running = False
