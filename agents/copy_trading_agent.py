"""
Copy Trading Agent - Surveille un wallet cible et mirror ses trades
=================================================================
Implémente:
- Polling de l'API Data pour détecter nouveaux trades
- Matching des positions et taille de copie
- Risk management (max position, max notional)
- Mode BUY ONLY (safeguard par défaut)
"""

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional

import httpx

logger = logging.getLogger("CopyTradingAgent")

DATA_API_BASE = "https://data-api.polymarket.com"
SESSION_NOTIONAL_CAP = 1000.0
RECENT_TRADE_WINDOW_SECONDS = 300
SESSION_RESET_SECONDS = 3600


@dataclass
class TargetTrade:
    """Trade détecté depuis le wallet cible."""
    id: str
    wallet: str
    token_id: str
    outcome: str
    side: str  # BUY or SELL
    size: float  # En USD
    price: float
    timestamp: float
    market: str
    condition_id: str


@dataclass
class CopyConfig:
    """Configuration du copy trading."""
    target_wallet: str
    copy_multiplier: float = 0.1  # 10% de la taille originale
    max_copy_notional: float = 100.0  # Max $100 par trade
    min_copy_notional: float = 1.0  # Min $1
    buy_only: bool = True  # Safeguard: BUY uniquement
    slippage_tolerance: float = 0.02  # 2% slippage


class CopyTradingAgent:
    """
    Agent de copy trading - monitore un wallet et mirror ses trades.
    Connecté au PortfolioRiskEngine pour respecter le Drawdown Circuit Breaker global.
    """

    def __init__(
        self,
        config: CopyConfig,
        on_copy_callback: Optional[Callable[[TargetTrade, float], Any]] = None,
        risk_engine: Optional[Any] = None,
    ):
        self.config = config
        self.on_copy = on_copy_callback
        self.risk_engine = risk_engine
        self._client = httpx.AsyncClient(timeout=30.0)
        self._last_trade_timestamp = 0.0
        self._running = False
        self._copied_trades: set[str] = set()
        self._session_notional = 0.0
        self._session_start = 0.0

    @property
    def is_running(self) -> bool:
        return self._running

    async def close(self) -> None:
        await self._client.aclose()

    def reset_session(self) -> None:
        """Reset le compteur de session."""
        self._session_notional = 0.0
        self._session_start = time.time()

    def update_config(self, config: CopyConfig) -> None:
        self.config = config
        self._copied_trades.clear()
        self._last_trade_timestamp = 0.0

    def calculate_copy_size(self, original_size: float) -> float:
        """Calcule la taille de la copie basée sur le multiplier."""
        raw_size = original_size * self.config.copy_multiplier
        return min(max(raw_size, self.config.min_copy_notional), self.config.max_copy_notional)

    def check_risk_limits(self, copy_notional: float) -> tuple[bool, str]:
        """Vérifie les limites de risque."""
        if self._session_notional + copy_notional > SESSION_NOTIONAL_CAP:
            return False, "Session notional cap exceeded"

        if copy_notional > self.config.max_copy_notional:
            return False, "Max copy notional exceeded"

        return True, "OK"

    async def fetch_target_trades(self, limit: int = 50) -> list[TargetTrade]:
        """Récupère les derniers trades du wallet cible via Data API."""
        try:
            params = {
                "user": self.config.target_wallet.lower(),
                "type": "trade",
                "limit": limit,
                "sortBy": "timestamp",
                "sortDirection": "desc",
            }

            response = await self._client.get(
                f"{DATA_API_BASE}/activity",
                params=params,
                headers={"Accept": "application/json"},
            )

            if response.status_code != 200:
                logger.warning(f"Data API returned {response.status_code}: {response.text}")
                return []

            data = response.json()
            if not data:
                return []

            trades = [
                TargetTrade(
                    id=item.get("id", ""),
                    wallet=item.get("user", ""),
                    token_id=item.get("token_id", ""),
                    outcome=item.get("outcome", ""),
                    side=item.get("side", "").upper(),
                    size=float(item.get("notional", 0)),
                    price=float(item.get("price", 0)),
                    timestamp=float(item.get("timestamp", 0)),
                    market=item.get("market", ""),
                    condition_id=item.get("condition_id", ""),
                )
                for item in data
            ]

            return trades

        except Exception as e:
            logger.error(f"Failed to fetch target trades: {e}")
            return []

    async def scan_for_new_trades(self) -> list[TargetTrade]:
        """Scanne pour nouveaux trades depuis le dernier check."""
        trades = await self.fetch_target_trades(limit=20)
        now = time.time()

        new_trades = []
        for trade in trades:
            if trade.id in self._copied_trades:
                continue
            if trade.timestamp <= self._last_trade_timestamp:
                continue
            if now - trade.timestamp > RECENT_TRADE_WINDOW_SECONDS:
                continue

            new_trades.append(trade)

        if trades:
            self._last_trade_timestamp = trades[0].timestamp

        return new_trades

    async def process_trade(self, trade: TargetTrade) -> Optional[dict[str, Any]]:
        """Traite un trade détecté et decide si on copie."""
        if self.config.buy_only and trade.side == "SELL":
            logger.info(f"⚠️ Skipping SELL trade (BUY-only mode): {trade.id}")
            return None

        # ─── Drawdown Circuit Breaker Check ───────────────────────────────────
        if self.risk_engine is not None and hasattr(self.risk_engine, "ledger"):
            try:
                ledger = self.risk_engine.ledger
                if hasattr(ledger, "get_global_drawdown"):
                    global_dd = ledger.get_global_drawdown()
                    if global_dd <= -0.10:
                        logger.critical(
                            f"🛑 [COPY TRADING] Drawdown Circuit Breaker ENGAGED "
                            f"({global_dd*100:.1f}%). Blocking copy trade {trade.id}."
                        )
                        return None
            except Exception as e:
                logger.warning(f"CopyTradingAgent: drawdown check failed (non-blocking): {e}")
        # ─────────────────────────────────────────────────────────────────────

        copy_notional = self.calculate_copy_size(trade.size)
        allowed, reason = self.check_risk_limits(copy_notional)
        if not allowed:
            logger.warning(f"⚠️ Risk check blocked trade: {reason}")
            return None

        self._copied_trades.add(trade.id)
        self._session_notional += copy_notional

        copy_signal = {
            "source": "copy_trading",
            "original_trade_id": trade.id,
            "target_wallet": self.config.target_wallet,
            "token_id": trade.token_id,
            "outcome": trade.outcome,
            "side": trade.side,
            "original_size": trade.size,
            "copy_size": copy_notional,
            "price": trade.price,
            "market": trade.market,
            "timestamp": trade.timestamp,
        }

        logger.info(
            f"📋 COPY SIGNAL: {trade.side} {copy_notional:.2f} USD @ {trade.price:.2f} "
            f"({trade.outcome})"
        )

        return copy_signal

    async def process_onchain_signal(self, signal: dict[str, Any]) -> Optional[dict[str, Any]]:
        """
        Traite un signal provenant du WebSocket on-chain (PolymarketMonitor).
        """
        if signal.get("source") != "polymarket_onchain":
            return None

        # Convert signal to TargetTrade format
        trade = TargetTrade(
            id=signal.get("tx_hash", "onchain-" + str(time.time())),
            wallet=signal.get("maker", ""),
            token_id=signal.get("token_id", ""),
            outcome="UNKNOWN", # On-chain match doesn't always specify YES/NO easily
            side=signal.get("side", "BUY"),
            size=float(signal.get("maker_amount", 0)) / 1e6, # Assuming USDC 6 decimals
            price=0.0, # Price is not always in the simple on-chain event without decoding more
            timestamp=time.time(),
            market="",
            condition_id="",
        )

        # If we have a target wallet, verify it
        if self.config.target_wallet and trade.wallet.lower() != self.config.target_wallet.lower():
            return None

        return await self.process_trade(trade)

    async def start_monitoring(
        self,
        poll_interval: float = 10.0,
        on_new_trade: Optional[Callable[[dict[str, Any]], Any]] = None,
    ) -> None:
        """Démarre le monitoring continu du wallet cible."""
        if self._running:
            logger.info("Copy trading monitor already running")
            return

        self._running = True
        self.reset_session()

        logger.info(f"🎯 Starting copy trading monitor for {self.config.target_wallet[:10]}...")
        logger.info(f"   Multiplier: {self.config.copy_multiplier*100}%")
        logger.info(f"   Max copy: ${self.config.max_copy_notional}")
        logger.info(f"   Buy only: {self.config.buy_only}")

        while self._running:
            try:
                new_trades = await self.scan_for_new_trades()

                for trade in new_trades:
                    copy_signal = await self.process_trade(trade)

                    if copy_signal and on_new_trade:
                        result = on_new_trade(copy_signal)
                        if inspect.isawaitable(result):
                            await result

                if time.time() - self._session_start > SESSION_RESET_SECONDS:
                    self.reset_session()
                    logger.info("🔄 Session reset (hourly)")

                await asyncio.sleep(poll_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Copy trading error: {e}")
                await asyncio.sleep(5)
        self._running = False

    def stop_monitoring(self) -> None:
        """Arrête le monitoring."""
        self._running = False
        logger.info("🛑 Copy trading monitor stopped")

    def get_stats(self) -> dict[str, Any]:
        """Retourne les statistiques du copy trading."""
        return {
            "target_wallet": self.config.target_wallet,
            "trades_copied": len(self._copied_trades),
            "session_notional": self._session_notional,
            "buy_only_mode": self.config.buy_only,
            "multiplier": self.config.copy_multiplier,
        }


async def test_copy_trading():
    """Test du module copy trading."""
    config = CopyConfig(
        target_wallet="0x1234567890abcdef1234567890abcdef12345678",  # Example wallet
        copy_multiplier=0.1,
        max_copy_notional=50.0,
        min_copy_notional=1.0,
        buy_only=True,
    )

    agent = CopyTradingAgent(config)

    print("🧪 Testing Copy Trading Agent...")

    # Test fetch
    trades = await agent.fetch_target_trades(limit=5)
    print(f"Found {len(trades)} recent trades")

    # Test with real wallet
    config2 = CopyConfig(
        target_wallet="0xB986E807Ccbefe514F41c628F0893b8ac8253A78",
        copy_multiplier=0.1,
    )

    agent2 = CopyTradingAgent(config2)
    trades2 = await agent2.fetch_target_trades(limit=3)
    print(f"Found {len(trades2)} trades for own wallet (should be 0)")

    await agent.close()
    await agent2.close()

    return agent.get_stats()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    stats = asyncio.run(test_copy_trading())
    print(f"\n✅ Stats: {stats}")
