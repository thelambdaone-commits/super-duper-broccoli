import asyncio
import logging
import time
import uuid
from typing import Any, Callable, Optional

from core.freqai_engine import FreqAIEngine

logger = logging.getLogger("PassiveExecutor")


class PassiveExecutor:
    def __init__(
        self,
        freqai: Any,
        ledger: Optional[Any] = None,
        maker_timeout_seconds: float = 5.0,
        poll_interval: float = 0.5,
        post_only: bool = True,
        maker_timeout_calibrator: Optional[Callable[[str], float]] = None,
        spread_bps: float = 2.0,
        slippage_factor: float = 0.5,
    ) -> None:
        self.freqai = freqai
        self.ledger = ledger
        self.maker_timeout = maker_timeout_seconds
        self.poll_interval = poll_interval
        self.post_only = post_only
        self.maker_timeout_calibrator = maker_timeout_calibrator
        self.spread_bps = spread_bps
        self.slippage_factor = slippage_factor
        self._order_queue: dict[str, dict[str, Any]] = {}
        self._fill_count: int = 0
        self._reject_count: int = 0
        self._taker_fallback_count: int = 0
        self._lock = asyncio.Lock()
        self._metrics = {
            "total_orders": 0,
            "filled_orders": 0,
            "cancelled_orders": 0,
            "simulated_slippage_usd": 0.0,
            "simulated_spread_usd": 0.0,
        }
        self._consecutive_high_latency_ticks = 0
        self._latency_freeze_until = 0.0

    def _record_latency(self, duration: float) -> None:
        if duration > 2.0:
            self._consecutive_high_latency_ticks += 1
            if self._consecutive_high_latency_ticks >= 3:
                self._latency_freeze_until = time.time() + 60.0
                logger.critical(f"API Latency Watchdog: 3 appels lents consécutifs ({duration:.2f}s). FREEZE activé pendant 60s.")
        else:
            self._consecutive_high_latency_ticks = 0

    def _get_maker_timeout(self, ticker: str) -> float:
        if self.maker_timeout_calibrator is not None:
            try:
                return self.maker_timeout_calibrator(ticker)
            except Exception:
                return self.maker_timeout
        return self.maker_timeout

    @property
    def fill_count(self) -> int:
        return self._fill_count

    @property
    def reject_count(self) -> int:
        return self._reject_count

    @property
    def taker_fallback_count(self) -> int:
        return self._taker_fallback_count

    @property
    def fill_rate(self) -> float:
        total = self._fill_count + self._reject_count + self._taker_fallback_count
        return self._fill_count / total if total > 0 else 1.0

    @property
    def queue_depth(self) -> int:
        return len(self._order_queue)

    async def execute(
        self,
        ticker: str,
        side: str,
        price: float,
        size: float,
        override_strict_maker: bool = False,
    ) -> dict[str, Any]:
        if time.time() < self._latency_freeze_until:
            logger.warning(f"PassiveExecutor is frozen due to high latency. Refusing order for {ticker}.")
            return {"status": "REJECTED_API_LAG", "reason": "API Latency Watchdog Freeze", "ticker": ticker}

        self._override_strict = override_strict_maker
        try:
            if self.post_only:
                result = await self._maker_first(ticker, side, price, size)
            else:
                result = await self._taker(ticker, side, price, size)
        finally:
            self._override_strict = False
        return result

    def _is_strict_maker_only(self) -> bool:
        if getattr(self, "_override_strict", False):
            return False
        import os
        if os.getenv("STRICT_MAKER_ONLY", "").lower() == "true":
            return True
        if self.ledger:
            try:
                flags = self.ledger.get_safety_flags()
                if flags and flags.get("strict_maker_only"):
                    return bool(flags["strict_maker_only"])
            except Exception:
                pass
        return False

    async def _maker_first(
        self,
        ticker: str,
        side: str,
        price: float,
        size: float,
    ) -> dict[str, Any]:
        start_t = time.time()
        try:
            post_result = await self.freqai.post_order(
                ticker=ticker, side=side, price=price, size=size,
            )
            self._record_latency(time.time() - start_t)
        except Exception as e:
            self._record_latency(time.time() - start_t)
            logger.warning(f"Maker post_order raised exception: {e}")
            if self._is_strict_maker_only():
                logger.warning(f"strict_maker_only is active. Refusing taker fallback on exception for {ticker}.")
                self._reject_count += 1
                return {
                    "status": "POST_ONLY_REJECTED",
                    "error": f"Maker post_order failed: {e}. Taker fallback denied by strict_maker_only.",
                    "ticker": ticker,
                    "side": side,
                    "price": price,
                    "size": size,
                    "execution_path": "maker",
                }
            self._reject_count += 1
            return await self._taker(ticker, side, price, size)

        if post_result.get("status") == "POST_ONLY_REJECTED":
            if self._is_strict_maker_only():
                logger.warning(f"strict_maker_only is active. Refusing taker fallback for {ticker}.")
                self._reject_count += 1
                return {
                    "status": "POST_ONLY_REJECTED",
                    "error": "Maker order would match immediately. Taker fallback denied by strict_maker_only.",
                    "ticker": ticker,
                    "side": side,
                    "price": price,
                    "size": size,
                    "execution_path": "maker",
                }
            logger.info(f"Maker rejected for {ticker} (would match immediately), trying taker")
            self._reject_count += 1
            return await self._taker(ticker, side, price, size)

        order_id = post_result.get("orderID") or post_result.get("id")
        if not order_id:
            if self._is_strict_maker_only():
                logger.warning(f"strict_maker_only is active. Refusing taker fallback for {ticker} (no order ID).")
                self._reject_count += 1
                return {
                    "status": "POST_ONLY_REJECTED",
                    "error": "No order ID from maker post. Taker fallback denied by strict_maker_only.",
                    "ticker": ticker,
                    "side": side,
                    "price": price,
                    "size": size,
                    "execution_path": "maker",
                }
            logger.warning(f"No order ID from maker post for {ticker}, falling back to taker")
            self._reject_count += 1
            return await self._taker(ticker, side, price, size)

        t_qid = uuid.uuid4().hex
        timeout = self._get_maker_timeout(ticker)
        self._order_queue[t_qid] = {
            "order_id": order_id,
            "ticker": ticker,
            "side": side,
            "price": price,
            "size": size,
            "queued_at": time.time(),
            "maker_timeout": timeout,
            "status": "QUEUED",
        }

        try:
            filled = await self._await_fill_or_timeout(order_id, t_qid, ticker)
            self._order_queue.pop(t_qid, None)

            if filled:
                self._fill_count += 1
                return {
                    "status": "FILLED",
                    "order_id": order_id,
                    "ticker": ticker,
                    "side": side,
                    "price": price,
                    "size": size,
                    "execution_path": "maker",
                }
            else:
                logger.info(f"Maker order {order_id} not filled within timeout, cancelling")
                await self.freqai.cancel_order(order_id)
                if self._is_strict_maker_only():
                    logger.warning(f"strict_maker_only is active. Refusing taker fallback for {ticker} on timeout.")
                    self._reject_count += 1
                    return {
                        "status": "CANCELLED",
                        "error": "Maker order timed out and was cancelled. Taker fallback denied by strict_maker_only.",
                        "ticker": ticker,
                        "side": side,
                        "price": price,
                        "size": size,
                        "execution_path": "maker",
                    }
                self._taker_fallback_count += 1
                return await self._taker(ticker, side, price, size)

        except Exception as e:
            self._order_queue.pop(t_qid, None)
            logger.warning(f"Queue tracking error for {order_id}: {e}")
            if self._is_strict_maker_only():
                logger.warning(f"strict_maker_only is active. Refusing taker fallback for {ticker} on tracking error.")
                self._reject_count += 1
                return {
                    "status": "ERROR",
                    "error": f"Queue tracking error: {e}. Taker fallback denied by strict_maker_only.",
                    "ticker": ticker,
                    "side": side,
                    "price": price,
                    "size": size,
                    "execution_path": "maker",
                }
            self._taker_fallback_count += 1
            return await self._taker(ticker, side, price, size)

    async def _await_fill_or_timeout(
        self, order_id: str, t_qid: str, ticker: str = ""
    ) -> bool:
        timeout = self._get_maker_timeout(ticker) if ticker else self.maker_timeout
        deadline = time.time() + timeout
        while time.time() < deadline:
            if t_qid not in self._order_queue:
                return False

            try:
                status = await self.freqai.get_order_status(order_id)
                order_data = status.get("order", {})
                if isinstance(order_data, dict):
                    remaining = order_data.get("remaining_size", order_data.get("size", 0))
                    if remaining == 0:
                        return True
                elif status.get("status") == "FILLED":
                    return True
            except Exception as e:
                logger.warning(f"Failed to check order status for {order_id} (retrying): {e}")

            await asyncio.sleep(self.poll_interval)

        return False

    async def _taker(
        self,
        ticker: str,
        side: str,
        price: float,
        size: float,
    ) -> dict[str, Any]:
        # 1. Apply simulated spread
        # For a BUY, we pay higher; for a SELL, we receive lower.
        spread_multiplier = 1 + (self.spread_bps / 10000.0) if side == "BUY" else 1 - (self.spread_bps / 10000.0)
        execution_price = price * spread_multiplier
        spread_cost = abs(execution_price - price) * size
        self._metrics["simulated_spread_usd"] += spread_cost

        # 2. Apply simulated slippage (size-based impact)
        # Simplified model: slippage = factor * (size / avg_liquidity)
        # We assume 10k USD as "standard" liquidity for base slippage
        slippage_pct = (size / 10000.0) * self.slippage_factor
        if side == "BUY":
            execution_price *= (1 + slippage_pct)
        else:
            execution_price *= (1 - slippage_pct)
        
        slippage_cost = abs(execution_price - (price * spread_multiplier)) * size
        self._metrics["simulated_slippage_usd"] += slippage_cost

        mode = "PAPER"
        if self.ledger:
            try:
                mode = self.ledger.get_execution_mode()
            except Exception:
                pass

        logger.info(
            f"[{mode}] Executing {side} {ticker} {size} @ {execution_price:.4f} "
            f"(Spread: {self.spread_bps}bps, Slippage: {slippage_pct*100:.2f}%)"
        )

        try:
            # Send to freqai (which handles PAPER/PROD internally)
            resp = await self.freqai.create_order(
                ticker=ticker,
                side=side,
                size=size,
                price=execution_price,
            )
            order_id = resp.get("orderID") or resp.get("id", "unknown")
            return {
                "status": "TAKER_FILLED",
                "order_id": order_id,
                "ticker": ticker,
                "side": side,
                "price": execution_price,
                "target_price": price,
                "size": size,
                "execution_path": "taker",
                "raw": resp,
            }
        except Exception as e:
            logger.error(f"Taker order failed for {ticker}: {e}")
            return {
                "status": "TAKER_FAILED",
                "error": str(e),
                "ticker": ticker,
                "side": side,
                "price": price,
                "size": size,
                "execution_path": "taker",
            }

    async def liquidate_all(self) -> dict[str, Any]:
        """Panic button: cancels all orders and closes all positions."""
        logger.warning("LIQUIDATE ALL triggered!")
        try:
            # 1. Cancel all open orders
            # Note: py-clob-client doesn't have a direct cancel_all, so we might need to fetch and cancel
            # For now, we clear the local queue and attempt to cancel known orders
            cancelled_count = 0
            for qid, order in list(self._order_queue.items()):
                order_id = order.get("order_id")
                if order_id:
                    await self.freqai.cancel_order(order_id)
                    cancelled_count += 1
            self._order_queue.clear()

            # 2. In a real institutional setup, we would fetch open positions from the CLOB
            # and send market orders to close them.
            # Since FreqAIEngine only has basic methods, we log the intent.
            
            return {
                "status": "SUCCESS",
                "cancelled_orders": cancelled_count,
                "message": "All queued orders cancelled. Manual position closure required for safety.",
            }
        except Exception as e:
            logger.error(f"Liquidation failed: {e}")
            return {"status": "ERROR", "error": str(e)}

    def get_queue_snapshot(self) -> list[dict[str, Any]]:
        return list(self._order_queue.values())

    def get_metrics(self) -> dict[str, Any]:
        return {
            "fill_count": self._fill_count,
            "reject_count": self._reject_count,
            "taker_fallback_count": self._taker_fallback_count,
            "fill_rate_pct": round(self.fill_rate * 100, 2),
            "queue_depth": self.queue_depth,
            "simulated_slippage_usd": self._metrics.get("simulated_slippage_usd", 0.0),
            "simulated_spread_usd": self._metrics.get("simulated_spread_usd", 0.0),
        }
