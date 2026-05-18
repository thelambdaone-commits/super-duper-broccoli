import logging
import math
from typing import Any, Dict, Optional

from py_clob_client_v2 import ApiCreds, ClobClient, OrderArgs, OrderType, Side, PartialCreateOrderOptions

from utils.exceptions import QuantFatal
logger = logging.getLogger("FreqAIEngine")


class FreqAIEngine:
    POLYMARKET_MIN_NOTIONAL = 5.0

    def __init__(
        self,
        private_key: str,
        api_key: str,
        api_secret: str,
        api_passphrase: str,
        chain_id: int = 137,
        funder: Optional[str] = None,
        signature_type: Optional[int] = None,
    ) -> None:
        from eth_account import Account
        self._address = Account.from_key(private_key).address
        self.api_url = "https://clob.polymarket.com"
        self.private_key = private_key
        try:
            if signature_type is None:
                signature_type = 3 if funder else 0
            
            self.client = ClobClient(
                host=self.api_url,
                key=private_key,
                chain_id=chain_id,
                signature_type=signature_type,
                funder=funder,
            )
            creds = ApiCreds(
                api_key=api_key, api_secret=api_secret, api_passphrase=api_passphrase
            )
            self.client.set_api_creds(creds)
            logger.info("Polymarket CLOB connector initialized with derived credentials.")
        except Exception as e:
            raise QuantFatal(f"CLOB connector initialization failed: {e}")

    def _get_market_filters(self, token_id: str) -> dict[str, Any]:
        """
        Extracts market metadata from the live CLOB when available.
        Falls back to a conservative local policy when the exchange metadata is unavailable.
        """
        filters: dict[str, Any] = {
            "min_notional": self.POLYMARKET_MIN_NOTIONAL,
            "min_order_size": 1.0,
            "tick_size": None,
        }
        try:
            book = self.client.get_order_book(token_id)
            if isinstance(book, dict):
                filters["min_order_size"] = float(book.get("min_order_size", filters["min_order_size"]) or filters["min_order_size"])
                filters["tick_size"] = book.get("tick_size") or filters["tick_size"]
            else:
                filters["min_order_size"] = float(getattr(book, "min_order_size", filters["min_order_size"]) or filters["min_order_size"])
                filters["tick_size"] = getattr(book, "tick_size", None) or filters["tick_size"]
        except Exception as exc:
            logger.debug("Unable to resolve market filters for %s: %s", token_id, exc)
        return filters

    def _normalize_and_validate(self, ticker: str, price: float, size: float) -> int:
        normalized_size = int(math.floor(float(size)))
        if normalized_size <= 0:
            raise ValueError(
                f"[Sizing] Ordre rejeté localement pour {ticker} : taille normalisée nulle "
                f"(brute={size}, entier={normalized_size})"
            )

        market_filters = self._get_market_filters(ticker)
        real_notional = float(normalized_size) * float(price)
        min_notional = float(market_filters.get("min_notional", self.POLYMARKET_MIN_NOTIONAL) or self.POLYMARKET_MIN_NOTIONAL)
        min_order_size = float(market_filters.get("min_order_size", 1.0) or 1.0)

        if normalized_size < min_order_size:
            raise ValueError(
                f"[Sizing] Ordre rejeté localement pour {ticker} : taille ({normalized_size}) "
                f"inférieure au minimum marché ({min_order_size})"
            )

        if real_notional < min_notional:
            raise ValueError(
                f"[Sizing] Ordre rejeté localement pour {ticker} : notionnel calculé "
                f"({real_notional:.2f}) inférieur au minimum Polymarket ({min_notional:.2f}). "
                f"Taille brute={size}, taille entière={normalized_size}"
            )

        return normalized_size

    async def clob_execute(
        self, ticker: str, side: str, price: float, size: float
    ) -> Dict[str, Any]:
        try:
            order_side = Side.BUY if side in ("YES", "BUY") else Side.SELL
            validated_size = self._normalize_and_validate(ticker, price, size)
            order_args = OrderArgs(
                price=price,
                size=validated_size,
                side=order_side,
                token_id=ticker,
            )
            
            # Resolve tick size options if possible
            options = None
            market_filters = self._get_market_filters(ticker)
            tick_size = market_filters.get("tick_size")
            if tick_size:
                if isinstance(tick_size, (int, float)):
                    tick_size = str(tick_size)
                if tick_size in ('0.1', '0.01', '0.001', '0.0001'):
                    options = PartialCreateOrderOptions(tick_size=tick_size)
            
            confirmation = self.client.create_and_post_order(order_args, options=options)
            logger.info(f"Order deployed: ID={confirmation.get('orderID')}")
            return confirmation
        except ValueError as e:
            logger.warning(f"Validation locale échouée: {e}")
            return {"status": "LOCAL_REJECT_MIN_NOTIONAL", "error": str(e)}
        except Exception as e:
            logger.error(f"Order rejected: {e}")
            return {"status": "REJECTED", "error": str(e)}

    async def post_order(
        self, ticker: str, side: str, price: float, size: float
    ) -> Dict[str, Any]:
        try:
            order_side = Side.BUY if side in ("YES", "BUY") else Side.SELL
            validated_size = self._normalize_and_validate(ticker, price, size)
            order_args = OrderArgs(
                price=price,
                size=validated_size,
                side=order_side,
                token_id=ticker,
            )
            
            # Use negative risk options and tick size in V2 Options
            options = PartialCreateOrderOptions(neg_risk=False)
            market_filters = self._get_market_filters(ticker)
            tick_size = market_filters.get("tick_size")
            if tick_size:
                if isinstance(tick_size, (int, float)):
                    tick_size = str(tick_size)
                if tick_size in ('0.1', '0.01', '0.001', '0.0001'):
                    options = PartialCreateOrderOptions(tick_size=tick_size, neg_risk=False)
                    
            order = self.client.create_order(order_args, options=options)
            confirmation = self.client.post_order(
                order,
                order_type=OrderType.GTC,
                post_only=True,
            )
            logger.info(f"Maker order posted: ID={confirmation.get('orderID')}")
            return confirmation
        except ValueError as e:
            logger.warning(f"Validation locale maker échouée: {e}")
            return {"status": "LOCAL_REJECT_MIN_NOTIONAL", "error": str(e)}
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
        """Reserved hook for live crypto tick streaming.

        The actual live feed is intentionally started by the orchestration layer
        so unit tests can safely call this method without opening network
        connections. The supported live connectors are:

        - Polymarket CLOB snapshots via `scrapers.clob_listener.CLOBListener`
        - Binance `bookTicker` streams via `utils.binance_websocket.BinanceWebSocketListener`
        """
        logger.debug("⚡ [TICK STREAM] live tick stream hook invoked")

    @property
    def address(self) -> str:
        return self._address
