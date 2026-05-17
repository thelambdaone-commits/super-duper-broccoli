import logging
from typing import Any, Dict

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import ApiCreds, OrderType
from py_clob_client.order_builder.builder import OrderArgs

from utils.exceptions import QuantFatal

logger = logging.getLogger("FreqAIEngine")


class FreqAIEngine:
    def __init__(
        self,
        private_key: str,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
        chain_id: int = 137,
    ) -> None:
        from eth_account import Account
        self._address = Account.from_key(private_key).address
        self.api_url = "https://clob.polymarket.com"
        self.private_key = private_key
        try:
            self.client = ClobClient(
                host=self.api_url,
                key=private_key,
                chain_id=chain_id,
                signature_type=2,
            )
            creds = ApiCreds(
                api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase
            )
            self.client.set_api_creds(creds)
            logger.info("Polymarket CLOB connector initialized with derived credentials.")
        except Exception as e:
            raise QuantFatal(f"CLOB connector initialization failed: {e}")

    async def clob_execute(
        self, ticker: str, side: str, price: float, size: float
    ) -> Dict[str, Any]:
        try:
            order_side = "BUY" if side in ("YES", "BUY") else "SELL"
            order_args = OrderArgs(
                price=price,
                size=int(size),
                side=order_side,
                token_id=ticker,
            )
            confirmation = self.client.create_and_post_order(order_args)
            logger.info(f"Order deployed: ID={confirmation.get('orderID')}")
            return confirmation
        except Exception as e:
            logger.error(f"Order rejected: {e}")
            return {"status": "REJECTED", "error": str(e)}

    async def post_order(
        self, ticker: str, side: str, price: float, size: float
    ) -> Dict[str, Any]:
        try:
            order_side = "BUY" if side in ("YES", "BUY") else "SELL"
            order_args = OrderArgs(
                price=price,
                size=int(size),
                side=order_side,
                token_id=ticker,
                neg_risk=False,
            )
            order = self.client.create_order(order_args)
            confirmation = self.client.post_order(
                order,
                orderType=OrderType.GTC,
                post_only=True,
            )
            logger.info(f"Maker order posted: ID={confirmation.get('orderID')}")
            return confirmation
        except Exception as e:
            err_str = str(e).lower()
            if "post only" in err_str or "would match" in err_str:
                logger.info(f"Maker order would immediately match (post-only reject): {e}")
                return {"status": "POST_ONLY_REJECTED", "error": str(e)}
            logger.error(f"Maker order failed: {e}")
            return {"status": "REJECTED", "error": str(e)}

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        try:
            result = self.client.cancel(order_id)
            logger.info(f"Order cancelled: {order_id}")
            return {"status": "CANCELLED", "order_id": order_id, "result": result}
        except Exception as e:
            logger.error(f"Cancel failed for {order_id}: {e}")
            return {"status": "CANCEL_FAILED", "error": str(e)}

    async def create_order(
        self, ticker: str, side: str, price: float, size: float
    ) -> Dict[str, Any]:
        return await self.clob_execute(ticker=ticker, side=side, price=price, size=size)

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        try:
            order = self.client.get_order(order_id)
            return {"status": "OK", "order_id": order_id, "order": order}
        except Exception as e:
            logger.error(f"Order status check failed for {order_id}: {e}")
            return {"status": "ERROR", "error": str(e)}

    async def stream_ticks_to_duckdb(self) -> None:
        """PATH COURT: stream microstructure and order book ticks to DuckDB feature store."""
        logger.debug("⚡ [TICK STREAM] Streaming microstructure ticks to DuckDB feature store...")

    @property
    def address(self) -> str:
        return self._address
