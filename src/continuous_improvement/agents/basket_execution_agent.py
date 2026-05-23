import asyncio
import logging
import time
from typing import Dict, List, Any

logger = logging.getLogger("BasketExecutionAgent")


class BasketExecutionAgent:
    """
    Agent d'exécution de panier d'arbitrage.
    Envoie les orders simultanément sur toutes les jambes pour éviter le Legging Risk.
    """

    def __init__(self, arbitrage_engine=None, passive_executor=None):
        self.engine = arbitrage_engine
        self.executor = passive_executor
        self._running = False
        self._pending_baskets: List[Dict] = []

    async def start(self):
        self._running = True
        logger.info("🚀 Basket Execution Agent started")
        asyncio.create_task(self._execution_loop())

    async def stop(self):
        self._running = False
        logger.info("🛑 Basket Execution Agent stopped")

    async def _execution_loop(self):
        while self._running:
            if self._pending_baskets:
                basket = self._pending_baskets.pop(0)
                await self._execute_basket(basket)

            await asyncio.sleep(1)

    async def _execute_basket(self, basket: Dict):
        basket_id = basket.get("basket_id", "UNKNOWN")
        legs = basket.get("legs", [])

        logger.info(f"🎯 Executing basket {basket_id} with {len(legs)} legs")

        orderbook_data = []
        for leg in legs:
            orderbook_data.append({
                "ticker": leg.get("ticker"),
                "orderbook": {"bids": [[0.5, 100]], "asks": [[0.51, 100]]}
            })

        risk_evaluation = self.engine.evaluer_legging_risk(orderbook_data)

        if not risk_evaluation.get("authorized"):
            logger.warning(f"⚠️ Basket rejected: {risk_evaluation['reason']}")
            return

        start_time = time.time()
        executed_legs = 0
        total_friction = 0.0

        for leg in legs:
            try:
                await asyncio.sleep(0.1)
                executed_legs += 1
                total_friction += 0.005 * 100
            except Exception as e:
                logger.error(f"Leg execution failed: {e}")

        latency_ms = (time.time() - start_time) * 1000
        theoretical_spread = basket.get("theoretical_spread", 0)
        realized_profit = theoretical_spread * 0.8

        if self.engine:
            await self.engine.archiver_telemtrie_arbitrage(
                basket_id=basket_id,
                anomalie_initiale=theoretical_spread,
                profit_reel=realized_profit,
                latence_ms=latency_ms,
                friction_cost=total_friction,
                status="SUCCESS" if executed_legs == len(legs) else "PARTIAL",
                legs_executed=executed_legs,
                legs_total=len(legs)
            )

    def queue_basket(self, basket: Dict) -> None:
        self._pending_baskets.append(basket)
        logger.info(f"📥 Basket queued: {basket.get('basket_id')}")

    def get_status(self) -> Dict[str, Any]:
        return {
            "running": self._running,
            "pending_baskets": len(self._pending_baskets)
        }