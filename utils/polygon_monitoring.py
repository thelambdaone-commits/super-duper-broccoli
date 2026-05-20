import asyncio
import json
import logging
import websockets
from typing import Any, Callable, Optional

logger = logging.getLogger("PolygonMonitoring")

class PolygonMonitor:
    """
    Hybrid Polygon blockchain monitor with WebSocket subscription and HTTP polling fallback.
    Uses public RPC nodes to avoid paid API dependencies.
    """
    def __init__(
        self,
        ws_url: str = "wss://polygon-rpc.com/ws",
        http_url: str = "https://polygon-rpc.com",
        callback: Optional[Callable[[dict], Any]] = None,
        poll_interval: int = 10
    ):
        self.ws_url = ws_url
        self.http_url = http_url
        self.callback = callback
        self.poll_interval = poll_interval
        self._last_block: Optional[int] = None
        self._running = False
        self._ws_task: Optional[asyncio.Task] = None
        self._poll_task: Optional[asyncio.Task] = None

    async def start(self):
        self._running = True
        logger.info(f"Starting Polygon Monitor (WS: {self.ws_url}, HTTP: {self.http_url})")
        self._ws_task = asyncio.create_task(self._ws_listen_loop())
        # The polling task acts as a safety fallback or primary if WS fails
        self._poll_task = asyncio.create_task(self._poll_loop())

    async def stop(self):
        self._running = False
        if self._ws_task:
            self._ws_task.cancel()
        if self._poll_task:
            self._poll_task.cancel()
        logger.info("Polygon Monitor stopped.")

    async def _ws_listen_loop(self):
        subscribe_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "eth_subscribe",
            "params": ["newHeads"] # Changed to newHeads for general block tracking
        }

        while self._running:
            try:
                async with websockets.connect(self.ws_url) as ws:
                    await ws.send(json.dumps(subscribe_msg))
                    logger.info("WebSocket subscribed to newHeads")
                    while self._running:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        if "params" in data and "result" in data["params"]:
                            header = data["params"]["result"]
                            block_num = int(header["number"], 16)
                            await self._handle_new_block(block_num)
            except Exception as e:
                logger.warning(f"WebSocket error: {e}. Retrying in 5s...")
                await asyncio.sleep(5)

    async def _poll_loop(self):
        while self._running:
            try:
                block = await self._rpc_async("eth_blockNumber", [])
                block_num = int(block, 16)
                await self._handle_new_block(block_num)
            except Exception as e:
                logger.debug(f"HTTP Poll error: {e}")
            await asyncio.sleep(self.poll_interval)

    async def _handle_new_block(self, block_num: int):
        if self._last_block is None:
            self._last_block = block_num
            return

        if block_num > self._last_block:
            for b in range(self._last_block + 1, block_num + 1):
                logger.debug(f"Processing block {b}")
                if self.callback:
                    # In a real scenario, we might fetch logs here
                    # For this implementation, we just notify of a new block
                    await self.callback({"type": "block", "number": b})
            self._last_block = block_num

    async def _rpc_async(self, method: str, params: list) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        # Using loop.run_in_executor for requests if needed, but here we use httpx style or just requests in thread
        import httpx
        async with httpx.AsyncClient() as client:
            r = await client.post(self.http_url, json=payload, timeout=10.0)
            r.raise_for_status()
            return r.json()["result"]

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    async def dummy_callback(event):
        print(f"EVENT: {event}")

    monitor = PolygonMonitor(callback=dummy_callback)
    try:
        asyncio.run(monitor.start())
        asyncio.get_event_loop().run_forever()
    except KeyboardInterrupt:
        pass
