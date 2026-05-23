import asyncio
import logging
import math
from typing import Any, Dict, Optional

from py_clob_client import ApiCreds, ClobClient, OrderArgs, OrderType, PartialCreateOrderOptions

from utils.exceptions import QuantFatal
from utils.secret_validation import validate_private_key_or_raise

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
        self.private_key = validate_private_key_or_raise(private_key, source="FreqAIEngine initialization")
        self._address = Account.from_key(self.private_key).address
        self.api_url = "https://clob.polymarket.com"
        try:
            if signature_type is None:
                signature_type = 3 if funder else 0

            self.client = ClobClient(
                host=self.api_url,
                key=self.private_key,
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

    def normalize_and_validate(self, ticker: str, price: float, size: float) -> tuple[int, float]:
        market_filters = self._get_market_filters(ticker)
        min_notional = float(market_filters.get("min_notional", self.POLYMARKET_MIN_NOTIONAL) or self.POLYMARKET_MIN_NOTIONAL)
        min_order_size = float(market_filters.get("min_order_size", 1.0) or 1.0)
        tick_size = market_filters.get("tick_size")

        # 1. Price Normalization (Round to tick size)
        normalized_price = price
        if tick_size:
            try:
                ts = float(tick_size)
                normalized_price = round(price / ts) * ts
                normalized_price = max(0.0001, min(0.9999, normalized_price))
            except (TypeError, ValueError):
                pass

        # 2. Size Normalization (Shares are integers in py-clob-client usually)
        normalized_size = int(math.floor(float(size)))

        # 3. Min Notional Check & Adjustment
        current_notional = float(normalized_size) * normalized_price
        if 0 < current_notional < min_notional:
            required_size = math.ceil(min_notional / normalized_price)
            if required_size <= normalized_size * 1.15: # 15% boost max
                logger.info(f"Boosting size for {ticker} from {normalized_size} to {required_size} to meet min_notional {min_notional}")
                normalized_size = int(required_size)
                current_notional = float(normalized_size) * normalized_price

        if normalized_size < min_order_size:
             if min_order_size <= normalized_size * 1.5:
                 normalized_size = int(min_order_size)
             else:
                raise ValueError(f"[Sizing] Ordre rejeté: taille ({normalized_size}) < min_order_size ({min_order_size})")

        if current_notional < min_notional:
            raise ValueError(
                f"[Sizing] Ordre rejeté: notionnel ({current_notional:.2f}) < minimum Polymarket ({min_notional:.2f})"
            )

        return normalized_size, normalized_price

    async def create_order(
        self, ticker: str, side: str, price: float, size: float
    ) -> Dict[str, Any]:
        """Taker execution via create_and_post_order."""
        def _create_order_sync() -> Dict[str, Any]:
            order_side = "BUY" if side in ("YES", "BUY", "LONG") else "SELL"
            validated_size, validated_price = self._normalize_and_validate(ticker, price, size)
            order_args = OrderArgs(
                price=validated_price,
                size=validated_size,
                side=order_side,
                token_id=ticker,
            )

            market_filters = self._get_market_filters(ticker)
            tick_size = market_filters.get("tick_size")
            options = None
            if tick_size:
                if isinstance(tick_size, (int, float)):
                    tick_size = str(tick_size)
                if tick_size in ('0.1', '0.01', '0.001', '0.0001'):
                    options = PartialCreateOrderOptions(tick_size=tick_size)

            return self.client.create_and_post_order(order_args, options=options)

        try:
            confirmation = await asyncio.to_thread(_create_order_sync)
            logger.info(f"Taker order deployed: ID={confirmation.get('orderID')}")
            return confirmation
        except ValueError as e:
            logger.warning(f"Validation locale échouée: {e}")
            return {"status": "LOCAL_REJECT_MIN_NOTIONAL", "error": str(e)}
        except Exception as e:
            logger.error(f"Order rejected: {e}")
            return {"status": "REJECTED", "error": str(e)}

    async def clob_execute(
        self, ticker: str, side: str, price: float, size: float
    ) -> Dict[str, Any]:
        """Backward-compatible alias for taker execution."""
        return await self.create_order(ticker=ticker, side=side, price=price, size=size)

    async def post_order(
        self, ticker: str, side: str, price: float, size: float
    ) -> Dict[str, Any]:
        """Maker execution with post-only options."""
        def _post_order_sync() -> Dict[str, Any]:
            order_side = "BUY" if side in ("YES", "BUY", "LONG") else "SELL"
            validated_size, validated_price = self._normalize_and_validate(ticker, price, size)
            order_args = OrderArgs(
                price=validated_price,
                size=validated_size,
                side=order_side,
                token_id=ticker,
            )

            market_filters = self._get_market_filters(ticker)
            tick_size = market_filters.get("tick_size")
            options = PartialCreateOrderOptions(neg_risk=False)
            if tick_size:
                if isinstance(tick_size, (int, float)):
                    tick_size = str(tick_size)
                if tick_size in ('0.1', '0.01', '0.001', '0.0001'):
                    options = PartialCreateOrderOptions(neg_risk=False, tick_size=tick_size)

            return self.client.create_and_post_order(order_args, options=options)

        try:
            confirmation = await asyncio.to_thread(_post_order_sync)
            return confirmation
        except ValueError as e:
            logger.warning(f"Validation locale maker échouée: {e}")
            return {"status": "LOCAL_REJECT_MIN_NOTIONAL", "error": str(e)}
        except Exception as e:
            err_str = str(e).lower()
            if "post only" in err_str or "would match" in err_str:
                return {"status": "POST_ONLY_REJECTED", "error": str(e)}
            logger.error(f"Maker order failed: {e}")
            return {"status": "REJECTED", "error": str(e)}

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        try:
            return await asyncio.to_thread(self.client.get_order, order_id)
        except Exception as e:
            logger.error(f"Failed to fetch order status for {order_id}: {e}")
            return {"status": "ERROR", "error": str(e)}

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        try:
            result = await asyncio.to_thread(self.client.cancel, order_id)
            logger.info(f"Order cancelled: {order_id}")
            return {"status": "CANCELLED", "order_id": order_id, "result": result}
        except Exception as e:
            logger.error(f"Cancel failed for {order_id}: {e}")
            return {"status": "CANCEL_FAILED", "error": str(e)}

    async def stream_ticks_to_duckdb(self) -> None:
        """
        Placeholder for tick streaming.
        In this version, tick streaming is handled by CLOBListener.
        """
        pass
