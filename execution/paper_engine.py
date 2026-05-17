import asyncio
import logging
import math
import random
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("PaperEngine")


class PaperExecutionResult:
    def __init__(
        self,
        status: str,
        order_id: str = "",
        fill_price: float = 0.0,
        size_contracts: float = 0.0,
        friction_cost: float = 0.0,
        slippage: float = 0.0,
        slippage_pct: float = 0.0,
        execution_time_ms: float = 0.0,
        reason: str = "",
        partial_fill: bool = False,
        filled_volume_usdc: float = 0.0,
        requested_volume_usdc: float = 0.0,
        spread_slippage_cost: float = 0.0,
        total_execution_cost: float = 0.0,
        fill_probability: float = 0.0,
    ):
        self.status = status
        self.order_id = order_id
        self.fill_price = fill_price
        self.size_contracts = size_contracts
        self.friction_cost = friction_cost
        self.slippage = slippage
        self.slippage_pct = slippage_pct
        self.execution_time_ms = execution_time_ms
        self.reason = reason
        self.partial_fill = partial_fill
        self.filled_volume_usdc = filled_volume_usdc
        self.requested_volume_usdc = requested_volume_usdc
        self.spread_slippage_cost = spread_slippage_cost
        self.total_execution_cost = total_execution_cost
        self.fill_probability = fill_probability


class PolymarketPaperEngine:
    """
    Simulateur d'Exécution Haute Fidélité (Paper Trading) pour Polymarket.
    Reproduit le comportement réel du carnet d'ordres (CLOB), la friction mathématique
    et les probabilités de remplissage des ordres passifs.
    """

    FRICTION_PER_CONTRACT = 0.005
    LATENCY_MIN_MS = 15
    LATENCY_MAX_MS = 85
    EPSILON = 1e-9

    def __init__(
        self,
        ledger: Optional[Any] = None,
        friction_per_contract: float = FRICTION_PER_CONTRACT,
        latency_min_ms: int = LATENCY_MIN_MS,
        latency_max_ms: int = LATENCY_MAX_MS,
    ) -> None:
        self.ledger = ledger
        self.friction = friction_per_contract
        self.latency_min = latency_min_ms
        self.latency_max = latency_max_ms
        self._executions: List[Dict[str, Any]] = []

    @staticmethod
    def _is_buy(side: str) -> bool:
        return side.upper() in {"BUY", "YES", "LONG"}

    @staticmethod
    def _mid_price(bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> float:
        return (bids[0][0] + asks[0][0]) / 2.0 if bids and asks else 0.0

    @staticmethod
    def _valid_level(price: float, volume: float) -> bool:
        return math.isfinite(price) and math.isfinite(volume) and price > 0 and volume > 0

    async def _simulate_latency(self) -> float:
        """Simule le délai de transit réseau aller-retour (RTT) avec l'API."""
        delay_ms = random.randint(self.latency_min, self.latency_max)
        await asyncio.sleep(delay_ms / 1000.0)
        return delay_ms

    def _parse_orderbook(self, orderbook_data: Dict[str, Any]) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
        """Parse orderbook data into structured format."""
        bids = []
        asks = []

        if "bids" in orderbook_data:
            for level in orderbook_data["bids"][:10]:
                if isinstance(level, list) and len(level) >= 2:
                    price, volume = float(level[0]), float(level[1])
                elif isinstance(level, dict):
                    price, volume = float(level.get("price", 0)), float(level.get("size", 0))
                else:
                    continue
                if self._valid_level(price, volume):
                    bids.append((price, volume))

        if "asks" in orderbook_data:
            for level in orderbook_data["asks"][:10]:
                if isinstance(level, list) and len(level) >= 2:
                    price, volume = float(level[0]), float(level[1])
                elif isinstance(level, dict):
                    price, volume = float(level.get("price", 0)), float(level.get("size", 0))
                else:
                    continue
                if self._valid_level(price, volume):
                    asks.append((price, volume))

        return sorted(bids, key=lambda level: level[0], reverse=True), sorted(asks, key=lambda level: level[0])

    def _calculate_order_imbalance(self, bids: List[Tuple[float, float]], asks: List[Tuple[float, float]]) -> float:
        """Calculate Order Imbalance (OI) from top 3 levels."""
        bid_vol = sum(v for _, v in bids[:3])
        ask_vol = sum(v for _, v in asks[:3])

        total = bid_vol + ask_vol
        if total == 0:
            return 0.0

        return (bid_vol - ask_vol) / total

    def _calculate_limit_fill_probability(
        self,
        side: str,
        target_price: float,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
    ) -> float:
        """Estimate maker fill probability using OI plus quote distance from touch."""
        oi = self._calculate_order_imbalance(bids, asks)
        best_bid, best_ask = bids[0][0], asks[0][0]
        spread = max(best_ask - best_bid, self.EPSILON)

        if self._is_buy(side):
            directional_oi = -oi
            distance_from_touch = max(0.0, best_bid - target_price) / spread
        else:
            directional_oi = oi
            distance_from_touch = max(0.0, target_price - best_ask) / spread

        oi_component = 0.32 * directional_oi
        queue_component = -0.18 * min(distance_from_touch, 3.0)
        probability = 0.45 + oi_component + queue_component
        return max(0.02, min(0.95, probability))

    def _reject_lookahead_orderbook(self, orderbook: Dict[str, Any]) -> Optional[PaperExecutionResult]:
        signal_ts = orderbook.get("signal_timestamp")
        book_ts = orderbook.get("timestamp") or orderbook.get("ts")
        if signal_ts is None or book_ts is None:
            return None
        try:
            if float(book_ts) - float(signal_ts) > self.EPSILON:
                return PaperExecutionResult(
                    status="REJECTED",
                    reason="Look-ahead orderbook rejected: book timestamp is newer than signal timestamp",
                )
        except (TypeError, ValueError):
            return PaperExecutionResult(status="REJECTED", reason="Invalid orderbook timestamp metadata")
        return None

    async def execute_order(
        self,
        ticker: str,
        side: str,
        order_type: str,
        target_price: float,
        allocated_capital: float,
        orderbook: Optional[Dict[str, Any]] = None,
    ) -> PaperExecutionResult:
        """
        Exécute virtuellement un ordre au marché ou limite en simulant la microstructure
        et la liquidité disponible dans le carnet d'ordres réel.
        """
        timestamp_start = time.time()
        latency_ms = await self._simulate_latency()

        if not orderbook:
            return PaperExecutionResult(
                status="REJECTED",
                reason="No orderbook data provided",
            )
        lookahead_rejection = self._reject_lookahead_orderbook(orderbook)
        if lookahead_rejection:
            return lookahead_rejection

        bids, asks = self._parse_orderbook(orderbook)

        if not bids or not asks:
            return PaperExecutionResult(
                status="REJECTED",
                reason="Empty orderbook",
            )

        book_side = asks if self._is_buy(side) else bids

        if not book_side:
            return PaperExecutionResult(
                status="REJECTED",
                reason="Empty book side",
            )

        best_market_price = book_side[0][0]
        requested_contracts = allocated_capital / target_price if target_price > 0 else 0

        if order_type.upper() == "MARKET":
            return await self._execute_market_order(
                ticker=ticker,
                side=side,
                book_side=book_side,
                bids=bids,
                asks=asks,
                best_market_price=best_market_price,
                allocated_capital=allocated_capital,
                requested_contracts=requested_contracts,
                timestamp_start=timestamp_start,
                latency_ms=latency_ms,
            )
        elif order_type.upper() == "LIMIT":
            return await self._execute_limit_order(
                ticker=ticker,
                side=side,
                book_side=book_side,
                bids=bids,
                asks=asks,
                target_price=target_price,
                allocated_capital=allocated_capital,
                requested_contracts=requested_contracts,
                timestamp_start=timestamp_start,
                latency_ms=latency_ms,
            )
        else:
            return PaperExecutionResult(
                status="REJECTED",
                reason=f"Unsupported order type: {order_type}",
            )

    async def _execute_market_order(
        self,
        ticker: str,
        side: str,
        book_side: List[Tuple[float, float]],
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        best_market_price: float,
        allocated_capital: float,
        requested_contracts: float,
        timestamp_start: float,
        latency_ms: float,
    ) -> PaperExecutionResult:
        """Execute a market order simulating liquidity sweep."""
        capital_remaining = allocated_capital
        total_contracts = 0.0
        total_friction = 0.0
        total_value = 0.0

        for price, volume in book_side:
            if capital_remaining <= 0:
                break

            capital_available = price * volume

            if capital_remaining >= capital_available:
                contracts_filled = volume
                capital_remaining -= capital_available
            else:
                contracts_filled = capital_remaining / price
                capital_remaining = 0

            total_contracts += contracts_filled
            total_friction += contracts_filled * self.friction
            total_value += contracts_filled * price

        if total_contracts == 0:
            return PaperExecutionResult(
                status="REJECTED",
                reason="Insufficient liquidity to fill order",
            )

        avg_fill_price = total_value / total_contracts if total_contracts > 0 else 0
        mid_price = self._mid_price(bids, asks)
        if self._is_buy(side):
            slippage = max(0.0, avg_fill_price - mid_price)
        else:
            slippage = max(0.0, mid_price - avg_fill_price)
        slippage_pct = (slippage / mid_price) * 100 if mid_price > 0 else 0

        execution_time_ms = (time.time() - timestamp_start) * 1000

        filled_volume = total_contracts * avg_fill_price
        partial = filled_volume < allocated_capital
        spread_slippage_cost = slippage * total_contracts
        total_execution_cost = spread_slippage_cost + total_friction

        result = PaperExecutionResult(
            status="SUCCESS",
            order_id=f"PAPER_MKT_{int(timestamp_start * 1000)}",
            fill_price=avg_fill_price,
            size_contracts=total_contracts,
            friction_cost=total_friction,
            slippage=slippage,
            slippage_pct=slippage_pct,
            execution_time_ms=execution_time_ms,
            partial_fill=partial,
            filled_volume_usdc=filled_volume,
            requested_volume_usdc=allocated_capital,
            spread_slippage_cost=spread_slippage_cost,
            total_execution_cost=total_execution_cost,
        )

        self._log_execution(ticker, side, "MARKET", result)
        return result

    async def _execute_limit_order(
        self,
        ticker: str,
        side: str,
        book_side: List[Tuple[float, float]],
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        target_price: float,
        allocated_capital: float,
        requested_contracts: float,
        timestamp_start: float,
        latency_ms: float,
    ) -> PaperExecutionResult:
        """Execute a limit (maker/post-only) order with fill probability."""
        best_market_price = book_side[0][0]

        if self._is_buy(side):
            if target_price >= best_market_price:
                return PaperExecutionResult(
                    status="REJECTED",
                    reason="Post-Only violation: Order would execute as Taker",
                )
        else:
            if target_price <= best_market_price:
                return PaperExecutionResult(
                    status="REJECTED",
                    reason="Post-Only violation: Order would execute as Taker",
                )

        fill_probability = self._calculate_limit_fill_probability(side, target_price, bids, asks)

        if random.random() <= fill_probability:
            size_contracts = allocated_capital / target_price
            friction_cost = size_contracts * self.friction

            execution_time_ms = (time.time() - timestamp_start) * 1000

            result = PaperExecutionResult(
                status="SUCCESS",
                order_id=f"PAPER_LMT_{int(timestamp_start * 1000)}",
                fill_price=target_price,
                size_contracts=size_contracts,
                friction_cost=friction_cost,
                slippage=0.0,
                slippage_pct=0.0,
                execution_time_ms=execution_time_ms,
                filled_volume_usdc=allocated_capital,
                requested_volume_usdc=allocated_capital,
                spread_slippage_cost=0.0,
                total_execution_cost=friction_cost,
                fill_probability=fill_probability,
            )

            self._log_execution(ticker, side, "LIMIT", result)
            return result
        else:
            return PaperExecutionResult(
                status="TIMEOUT_EXPIRED",
                reason=f"Passive fill failed (prob: {fill_probability:.2%})",
                fill_probability=fill_probability,
            )

    def _log_execution(self, ticker: str, side: str, order_type: str, result: PaperExecutionResult) -> None:
        """Log execution details."""
        exec_record = {
            "ticker": ticker,
            "side": side,
            "order_type": order_type,
            "status": result.status,
            "order_id": result.order_id,
            "fill_price": result.fill_price,
            "size_contracts": result.size_contracts,
            "friction_cost": result.friction_cost,
            "slippage": result.slippage,
            "slippage_pct": result.slippage_pct,
            "partial_fill": result.partial_fill,
            "spread_slippage_cost": result.spread_slippage_cost,
            "total_execution_cost": result.total_execution_cost,
            "fill_probability": result.fill_probability,
            "timestamp": time.time(),
        }
        self._executions.append(exec_record)

        logger.info(
            f"PAPER EXEC: {ticker} {side} {order_type} -> {result.status} | "
            f"Fill: ${result.fill_price:.4f} | Size: {result.size_contracts:.2f} | "
            f"Slippage: {result.slippage_pct:.2f}%"
        )

    async def execute_and_record(
        self,
        ticker: str,
        side: str,
        order_type: str,
        target_price: float,
        allocated_capital: float,
        orderbook: Optional[Dict[str, Any]] = None,
        confidence: float = 0.5,
        regime_label: str = "UNKNOWN",
        signal_source: str = "unknown",
    ) -> PaperExecutionResult:
        """Execute order and record to ledger if available."""
        result = await self.execute_order(
            ticker=ticker,
            side=side,
            order_type=order_type,
            target_price=target_price,
            allocated_capital=allocated_capital,
            orderbook=orderbook,
        )

        if result.status == "SUCCESS" and self.ledger:
            try:
                from core.performance_attribution import PerformanceAttribution
                perf_attr = PerformanceAttribution(ledger=self.ledger)

                trade_id = perf_attr.enregistrer_trade(
                    ticker=ticker,
                    condition_id=f"cond_{ticker}",
                    side=side,
                    entry_price=result.fill_price,
                    size=result.size_contracts,
                    mid_price_at_signal=target_price,
                    fill_price=result.fill_price,
                    confidence=confidence,
                    signal_source=signal_source,
                    regime_label=regime_label,
                    resolution_timestamp=time.time() + (7 * 24 * 3600),
                )

                result.order_id = trade_id if trade_id else result.order_id

            except Exception as e:
                logger.error(f"Failed to record to ledger: {e}")

        return result

    def get_execution_history(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent execution history."""
        return self._executions[-limit:]

    def get_statistics(self) -> Dict[str, Any]:
        """Get execution statistics."""
        if not self._executions:
            return {
                "total_executions": 0,
                "success_rate": 0.0,
                "avg_slippage_pct": 0.0,
                "avg_friction": 0.0,
            }

        total = len(self._executions)
        successful = sum(1 for e in self._executions if e["status"] == "SUCCESS")
        slippage_values = [e["slippage_pct"] for e in self._executions if e["slippage_pct"] != 0]
        friction_values = [e["friction_cost"] for e in self._executions]

        return {
            "total_executions": total,
            "successful": successful,
            "success_rate": successful / total if total > 0 else 0,
            "avg_slippage_pct": sum(slippage_values) / len(slippage_values) if slippage_values else 0,
            "max_slippage_pct": max(slippage_values) if slippage_values else 0,
            "total_friction": sum(friction_values),
            "avg_friction": sum(friction_values) / len(friction_values) if friction_values else 0,
        }

    def clear_history(self) -> None:
        """Clear execution history."""
        self._executions.clear()
        logger.info("Paper engine execution history cleared")
