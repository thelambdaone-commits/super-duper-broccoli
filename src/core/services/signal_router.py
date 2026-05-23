from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

logger = logging.getLogger("SignalRouterService")


@dataclass
class SignalRouterContext:
    ledger: Any
    freqai: Any
    risk: Any = None
    hmm: Any = None
    store: Any = None
    executor: Any = None
    scanner: Any = None
    tenant_wallet: Optional[str] = None
    lobstar_agent: Any = None


class SignalRouter:
    """
    Routes validated signals to the appropriate execution path.
    """

    def __init__(
        self,
        passive_executor: Any = None,
        active_executor: Any = None,
        arbitrage_executor: Any = None,
        **kwargs: Any,
    ) -> None:
        self.passive_executor = passive_executor
        self.active_executor = active_executor
        self.arbitrage_executor = arbitrage_executor
        self.extra = kwargs

    def _require_executor(self, executor: Any, label: str) -> Any:
        if executor is None:
            raise ValueError(f"Configuration Error: {label} is required but missing in SignalRouter")
        return executor

    async def _dispatch(self, executor: Any, signal: dict, context: SignalRouterContext) -> dict:
        if hasattr(executor, "execute_signal"):
            return await executor.execute_signal(signal, context)

        if hasattr(executor, "execute"):
            return await executor.execute(signal, context)

        if callable(executor):
            return await executor(signal, context)

        return {"status": "FAILED", "reason": "Unsupported executor interface"}

    async def route(self, signal: dict, context: SignalRouterContext) -> dict:
        source = signal.get("source", "")

        if source == "arbitrage" or signal.get("arb_type") is not None:
            logger.info("⚡ Routing arbitrage signal")
            executor = self._require_executor(self.arbitrage_executor, "arbitrage_executor")
            return await self._dispatch(executor, signal, context)

        if source == "lobstar_llm":
            if not context.lobstar_agent:
                logger.warning("Lobstar signal received but agent is disabled.")
                return {"status": "FAILED", "reason": "Lobstar agent disabled"}
            executor = self._require_executor(self.active_executor, "active_executor")
            return await self._dispatch(executor, signal, context)

        if source == "polymarket_onchain":
            logger.info("⚡ Routing on-chain signal")
            return {"status": "SKIPPED", "reason": "On-chain signals handled separately"}

        logger.info("⚡ Routing regex signal")
        executor = self._require_executor(self.passive_executor, "passive_executor")
        return await self._dispatch(executor, signal, context)
