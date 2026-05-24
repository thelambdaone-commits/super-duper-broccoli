import asyncio
import json
import logging
import math
import os
from typing import Any, Dict, Optional

try:
    from py_clob_client_v2 import ApiCreds, ClobClient, OrderArgs, OrderType, PartialCreateOrderOptions
except ModuleNotFoundError:
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
        self.funder = funder
        try:
            # LOBSTAR V2: Prioritize POLYMARKET_SIGNATURE_TYPE from environment
            env_sig_type = os.getenv("POLYMARKET_SIGNATURE_TYPE")
            if env_sig_type is not None:
                try:
                    signature_type = int(env_sig_type)
                    logger.info("Using explicit POLYMARKET_SIGNATURE_TYPE=%d from env", signature_type)
                except ValueError:
                    logger.warning("Invalid POLYMARKET_SIGNATURE_TYPE in env: %s", env_sig_type)

            if signature_type is None:
                # py_clob_client_v2 supports POLY_1271=3 for deposit-wallet flows.
                # Default to 3 whenever a funder/proxy wallet is configured, otherwise use direct EOA=0.
                signature_type = 3 if funder else 0
            self.signature_type = signature_type

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
            
            # LOBSTAR V2: Separate client for Gamma API (market metadata)
            from utils.polymarket_client import PolymarketClient
            self.market_client = PolymarketClient()
            
            logger.info("Polymarket CLOB connector initialized (SigType: %d, Funder: %s)", signature_type, funder)
        except Exception as e:
            raise QuantFatal(f"CLOB connector initialization failed: {e}")

    def _extract_market_context(self, token_id: str) -> dict[str, Any]:
        context: dict[str, Any] = {"market_id": None, "token_id": token_id, "outcome": None}
        if not hasattr(self, "market_client"):
            return context
            
        try:
            market = self.market_client.get_market_by_token(token_id)
            if not market or not isinstance(market, dict):
                return context
            
            context["market_id"] = (
                market.get("condition_id")
                or market.get("market_id")
                or market.get("id")
                or market.get("slug")
            )
            for token in market.get("tokens", []) or []:
                candidate = str(token.get("token_id") or token.get("id") or "")
                if candidate == str(token_id):
                    context["outcome"] = token.get("outcome")
                    break
        except Exception as e:
            logger.debug(f"Failed to extract market context for {token_id}: {e}")
        return context

    def _log_order_context(
        self,
        *,
        stage: str,
        token_id: str,
        side: str,
        price: float,
        size: float,
        response_text: Optional[str] = None,
    ) -> None:
        context = self._extract_market_context(token_id)
        logger.info(
            "Polymarket order context: %s",
            {
                "stage": stage,
                "market": context.get("market_id"),
                "token_id": token_id,
                "outcome": context.get("outcome"),
                "side": side,
                "price": price,
                "size": size,
                "signature_type": getattr(self, "signature_type", None),
                "proxy_wallet": getattr(self, "funder", None),
                "response": response_text,
            },
        )

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

    @staticmethod
    def _extract_order_price(order: Any) -> float:
        if isinstance(order, dict):
            raw = order.get("price")
        else:
            raw = getattr(order, "price", 0.0)
        try:
            return max(0.0, float(raw or 0.0))
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _extract_order_remaining_size(order: Any) -> float:
        candidates = []
        if isinstance(order, dict):
            candidates = [
                order.get("remaining_size"),
                order.get("remainingSize"),
                order.get("size_matched"),
                order.get("size"),
                order.get("original_size"),
            ]
        else:
            candidates = [
                getattr(order, "remaining_size", None),
                getattr(order, "remainingSize", None),
                getattr(order, "size_matched", None),
                getattr(order, "size", None),
                getattr(order, "original_size", None),
            ]
        for raw in candidates:
            if raw is None:
                continue
            try:
                return max(0.0, float(raw))
            except (TypeError, ValueError):
                continue
        return 0.0

    @staticmethod
    def _extract_order_side(order: Any) -> str:
        if isinstance(order, dict):
            raw = order.get("side", "")
        else:
            raw = getattr(order, "side", "")
        return str(raw or "").upper()

    @staticmethod
    def _parse_balance_allowance_response(raw: Any) -> float:
        if raw is None:
            return 0.0
        if isinstance(raw, dict):
            balance = raw.get("balance")
            if balance is None:
                return 0.0
            try:
                return max(0.0, float(balance) / 1_000_000.0)
            except (TypeError, ValueError):
                return 0.0
        return 0.0

    def get_available_collateral_usdc(self) -> Optional[dict[str, float]]:
        try:
            from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams
        except ModuleNotFoundError:
            return None

        try:
            params = BalanceAllowanceParams(asset_type=AssetType.COLLATERAL, signature_type=-1)
            try:
                self.client.update_balance_allowance(params)
            except Exception:
                pass
            raw = self.client.get_balance_allowance(params)
            total_balance = self._parse_balance_allowance_response(raw)

            open_orders = self.client.get_open_orders() or []
            locked_balance = 0.0
            for order in open_orders:
                if self._extract_order_side(order) != "BUY":
                    continue
                locked_balance += self._extract_order_price(order) * self._extract_order_remaining_size(order)

            available_balance = max(0.0, total_balance - locked_balance)
            return {
                "total_balance_usdc": total_balance,
                "locked_balance_usdc": locked_balance,
                "available_balance_usdc": available_balance,
            }
        except Exception as exc:
            logger.debug("Unable to compute available collateral: %s", exc)
            return None

    def _validate_market_is_tradeable(self, token_id: str) -> None:
        try:
            book = self.client.get_order_book(token_id)
        except Exception as exc:
            raise ValueError(f"[Market] Ordre rejeté: token_id invalide ou marché indisponible ({exc})") from exc

        if book is None:
            raise ValueError("[Market] Ordre rejeté: carnet introuvable pour ce token.")

        if isinstance(book, dict):
            active = book.get("active")
            closed = book.get("closed")
            archived = book.get("archived")
        else:
            active = getattr(book, "active", None)
            closed = getattr(book, "closed", None)
            archived = getattr(book, "archived", None)

        if active is False or closed is True or archived is True:
            raise ValueError(
                f"[Market] Ordre rejeté: marché inactif/résolu (active={active}, closed={closed}, archived={archived})."
            )

    def normalize_and_validate(self, ticker: str, price: float, size: float) -> tuple[int, float]:
        market_context = self._extract_market_context(ticker)
        self._validate_market_is_tradeable(ticker)
        market_filters = self._get_market_filters(ticker)
        min_notional = float(market_filters.get("min_notional", self.POLYMARKET_MIN_NOTIONAL) or self.POLYMARKET_MIN_NOTIONAL)
        min_order_size = float(market_filters.get("min_order_size", 1.0) or 1.0)
        tick_size = market_filters.get("tick_size")

        # 1. Price Normalization (Round to tick size)
        normalized_price = price
        if tick_size:
            try:
                ts = float(tick_size)
                # LOBSTAR V2: Precise rounding to avoid floating point issues
                decimal_places = abs(math.floor(math.log10(ts))) if ts < 1 else 0
                normalized_price = round(round(price / ts) * ts, decimal_places)
                normalized_price = max(0.0001, min(0.9999, normalized_price))
            except (TypeError, ValueError):
                pass

        # 2. Size Normalization (Shares are integers in py-clob-client usually)
        normalized_size = int(math.floor(float(size)))

        # 3. Min Notional Check & Adjustment
        current_notional = float(normalized_size) * normalized_price
        if 0 < current_notional < min_notional:
            # SAFE BUMP: Ensure we hit at least 5.05 USDC to avoid edge-case rejections
            target_notional = max(min_notional + 0.05, current_notional)
            required_size = math.ceil(target_notional / normalized_price)
            
            # Strict safety check: don't boost more than 20% or $2.00
            if required_size <= normalized_size * 1.20 or (required_size - normalized_size) * normalized_price < 2.0:
                logger.info(f"Boosting size for {ticker} from {normalized_size} to {required_size} to meet min_notional {min_notional}")
                normalized_size = int(required_size)
                current_notional = float(normalized_size) * normalized_price
            else:
                raise ValueError(
                    f"[Sizing] Ordre rejeté: notionnel ({current_notional:.2f}) trop loin du minimum ({min_notional:.2f})"
                )

        if normalized_size < min_order_size:
             if min_order_size <= normalized_size * 1.5:
                 normalized_size = int(min_order_size)
                 current_notional = float(normalized_size) * normalized_price
             else:
                raise ValueError(f"[Sizing] Ordre rejeté: taille ({normalized_size}) < min_order_size ({min_order_size})")

        # FINAL PRECISION CHECK
        if normalized_size < min_order_size:
            raise ValueError(f"[Sizing] Ordre rejeté: taille ({normalized_size}) < min_order_size ({min_order_size})")
        if current_notional < min_notional:
            raise ValueError(f"[Sizing] Ordre rejeté: notionnel ({current_notional:.2f}) < min_notional ({min_notional:.2f})")
        logger.info(
            "Polymarket normalized order: %s",
            {
                "market": market_context.get("market_id"),
                "token_id": ticker,
                "outcome": market_context.get("outcome"),
                "price": normalized_price,
                "size": normalized_size,
                "tick_size": tick_size,
                "min_size": min_order_size,
            },
        )

        return normalized_size, normalized_price

    async def create_order(
        self, ticker: str, side: str, price: float, size: float
    ) -> Dict[str, Any]:
        """Taker execution via create_and_post_order."""
        def _create_order_sync() -> Dict[str, Any]:
            order_side = "BUY" if side in ("YES", "BUY", "LONG") else "SELL"
            validated_size, validated_price = self.normalize_and_validate(ticker, price, size)
            self._log_order_context(
                stage="taker_submit",
                token_id=ticker,
                side=order_side,
                price=validated_price,
                size=validated_size,
            )
            
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
            logger.info("✅ [CLOB SUCCESS] Order ID: %s | Full Response: %s", 
                        confirmation.get('orderID'), json.dumps(confirmation) if isinstance(confirmation, dict) else confirmation)
            return confirmation
        except ValueError as e:
            logger.warning(f"Validation locale échouée: {e}")
            return {"status": "LOCAL_REJECT_MIN_NOTIONAL", "error": str(e)}
        except Exception as e:
            logger.exception("❌ [CLOB REJECTED] Order attempt failed:")
            # Attempt to extract detailed response if available from httpx-based exceptions
            error_details = str(e)
            if hasattr(e, "response") and hasattr(e.response, "text"):
                error_details = f"{e} | Response: {e.response.text}"
                logger.error(f"DETAILED API ERROR: {e.response.text}")
            self._log_order_context(
                stage="taker_reject",
                token_id=ticker,
                side=side,
                price=price,
                size=size,
                response_text=error_details,
            )
            return {"status": "REJECTED", "error": error_details}

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
            validated_size, validated_price = self.normalize_and_validate(ticker, price, size)
            self._log_order_context(
                stage="maker_submit",
                token_id=ticker,
                side=order_side,
                price=validated_price,
                size=validated_size,
            )
            
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

            # LOBSTAR SDK FIX: create_and_post_order does NOT support post_only.
            # We must create the order then post it with the flag.
            order = self.client.create_order(order_args, options=options)
            return self.client.post_order(order, post_only=True)

        try:
            confirmation = await asyncio.to_thread(_post_order_sync)
            logger.info("✅ [CLOB MAKER SUCCESS] Order ID: %s | Full Response: %s", 
                        confirmation.get('orderID'), json.dumps(confirmation) if isinstance(confirmation, dict) else confirmation)
            return confirmation
        except ValueError as e:
            logger.warning(f"Validation locale maker échouée: {e}")
            return {"status": "LOCAL_REJECT_MIN_NOTIONAL", "error": str(e)}
        except Exception as e:
            err_str = str(e).lower()
            if "post only" in err_str or "would match" in err_str:
                logger.warning(f"Post-only order rejected for {ticker}: would match immediately.")
                self._log_order_context(
                    stage="maker_post_only_reject",
                    token_id=ticker,
                    side=side,
                    price=price,
                    size=size,
                    response_text=str(e),
                )
                return {"status": "POST_ONLY_REJECTED", "error": str(e)}
            
            logger.error("❌ [CLOB MAKER FAILED] Order rejected: %s", e)
            error_details = str(e)
            if hasattr(e, "response") and hasattr(e.response, "text"):
                error_details = f"{e} | Response: {e.response.text}"
                logger.error(f"DETAILED MAKER API ERROR: {e.response.text}")
            self._log_order_context(
                stage="maker_reject",
                token_id=ticker,
                side=side,
                price=price,
                size=size,
                response_text=error_details,
            )
            return {"status": "REJECTED", "error": error_details}


    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        try:
            status = await asyncio.to_thread(self.client.get_order, order_id)
            if status is None:
                return {"status": "NOT_FOUND", "order_id": order_id}
            return status
        except Exception as e:
            logger.error(f"Failed to fetch order status for {order_id}: {e}")
            return {"status": "ERROR", "error": str(e)}

    async def get_open_orders(self) -> list[dict[str, Any]]:
        """Fetches all open orders from the CLOB."""
        try:
            orders = await asyncio.to_thread(self.client.get_open_orders)
            return orders or []
        except Exception as e:
            logger.error(f"Failed to fetch open orders: {e}")
            return []

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        try:
            result = await asyncio.to_thread(self.client.cancel, order_id)
            logger.info(f"Order cancelled: {order_id}")
            return {"status": "CANCELLED", "order_id": order_id, "result": result}
        except Exception as e:
            logger.error(f"Cancel failed for {order_id}: {e}")
            return {"status": "CANCEL_FAILED", "error": str(e)}

    async def get_midpoint(self, token_id: str) -> float:
        """Return the current midpoint price for a token via the CLOB client."""
        try:
            midpoint = await asyncio.wait_for(
                asyncio.to_thread(self.client.get_midpoint, token_id),
                timeout=5.0,
            )
            return float(midpoint)
        except TimeoutError:
            logger.error(f"Timed out while fetching midpoint for {token_id}")
            return 0.0
        except Exception as e:
            logger.error(f"Failed to fetch midpoint for {token_id}: {e}")
            return 0.0

    async def stream_ticks_to_duckdb(self) -> None:
        """
        Placeholder for tick streaming.
        In this version, tick streaming is handled by CLOBListener.
        """
        pass
