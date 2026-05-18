import logging
import json
import asyncio
import time
import os
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger("ArbitrageEngine")


@dataclass
class ArbitrageOpportunity:
    timestamp: str
    basket_id: str
    markets: List[str]
    theoretical_spread: float
    expected_profit: float
    legs: List[Dict[str, Any]]
    authorized: bool
    authorization_reason: str


@dataclass
class ArbitrageResult:
    basket_id: str
    status: str
    theoretical_spread: float
    realized_profit: float
    friction_cost: float
    execution_latency_ms: float
    efficiency_loss: float
    legs_executed: int
    legs_total: int
    timestamp: str


from utils.config_loader import TRADING_PARAMS

class LobstarArbitrageEngine:
    """
    Moteur d'Arbitrage Auto-Apprenant pour l'essaim Ruflo.
    Audite les paniers de contrats Polymarket, gère le risque d'exécution partielle 
    et enregistre la télémétrie des opérations dans un fichier JSONL.
    """

    FRICTION_PER_CONTRACT = TRADING_PARAMS["FRICTION_PER_CONTRACT"]
    MIN_LIQUIDITY_THRESHOLD = float(TRADING_PARAMS["LEGGING_LIQUIDITY_MIN"])
    DEFAULT_TRIGGER_THRESHOLD = TRADING_PARAMS["ARBITRAGE_TRIGGER_THRESHOLD"]

    def __init__(
        self,
        execution_mode: str = "PAPER",
        slippage_tolerance: float = 0.002,
        trigger_threshold: float = DEFAULT_TRIGGER_THRESHOLD,
        telemetry_path: str = "user_data/data/raw_stream"
    ):
        import os
        self.execution_mode = execution_mode
        self.slippage_tolerance = slippage_tolerance
        self.trigger_threshold = trigger_threshold
        self.telemetry_path = telemetry_path
        self.MIN_LIQUIDITY_THRESHOLD = float(TRADING_PARAMS["LEGGING_LIQUIDITY_MIN"])

        self._opportunities: List[ArbitrageOpportunity] = []
        self._results: List[ArbitrageResult] = []
        self._legger_failures = 0

    def detecter_anomalie_kolmogorov(self, outcomes: Dict[str, float]) -> Optional[Dict[str, Any]]:
        """
        Détecte les violations des axiomes de Kolmogorov:
        - Somme des outcomes exclusifs != 1.0
        - Incohérences conditionnelles
        """
        total = sum(outcomes.values())

        if abs(total - 1.0) > 0.01:
            spread = abs(total - 1.0)
            logger.warning(f"⚠️ KOLMOGOROV VIOLATION: sum={total:.4f}, spread={spread:.4f}")

            return {
                "detected": True,
                "type": "SUM_VIOLATION",
                "sum": total,
                "spread": spread,
                "theoretical_edge": spread
            }

        return {"detected": False, "type": "NONE", "spread": 0}

    def detecter_arbitrage_cross_market(
        self,
        primary_market: str,
        primary_outcome: float,
        secondary_markets: List[Dict[str, Any]]
    ) -> Optional[ArbitrageOpportunity]:
        """
        Analyse les opportunités d'arbitrage entre marchés interconnectés.
        """
        basket_id = f"ARB_{int(time.time() * 1000)}"

        theoretical_spread = 0.0

        for sec in secondary_markets:
            theoretical_spread += abs(primary_outcome - sec.get("outcome", 0.5))

        if theoretical_spread >= self.trigger_threshold:
            legs = [{"ticker": primary_market, "outcome": primary_outcome, "side": "YES"}]
            for sec in secondary_markets:
                legs.append({"ticker": sec["ticker"], "outcome": sec["outcome"], "side": "NO"})

            return ArbitrageOpportunity(
                timestamp=datetime.now(timezone.utc).isoformat(),
                basket_id=basket_id,
                markets=[primary_market] + [s["ticker"] for s in secondary_markets],
                theoretical_spread=theoretical_spread,
                expected_profit=theoretical_spread * 100,
                legs=legs,
                authorized=False,
                authorization_reason="PENDING_LIQUIDITY_CHECK"
            )

        return None

    def evaluer_legging_risk(self, panier_contrats: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Analyse la profondeur des carnets sur toutes les jambes de l'arbitrage.
        Calcule la probabilité que le bot se retrouve bloqué avec une position ouverte asymétrique.
        """
        scores_liquidite = []
        leg_details = []

        for i, contrat in enumerate(panier_contrats):
            orderbook = contrat.get("orderbook", {})

            bids = orderbook.get("bids", [])
            asks = orderbook.get("asks", [])

            # Handle both list format [[price, size], ...] and dict format
            def get_volume(level):
                if isinstance(level, list) and len(level) >= 2:
                    return float(level[1])
                elif isinstance(level, dict):
                    return float(level.get("size", 0))
                return 0.0

            bid_vol = sum(get_volume(b) for b in bids[:2])
            ask_vol = sum(get_volume(a) for a in asks[:2])
            volume_total = bid_vol + ask_vol

            scores_liquidite.append(volume_total)
            leg_details.append({
                "leg_index": i,
                "ticker": contrat.get("ticker", f"LEG_{i}"),
                "bid_volume": bid_vol,
                "ask_volume": ask_vol,
                "total_volume": volume_total,
                "liquid": volume_total >= self.MIN_LIQUIDITY_THRESHOLD
            })

        min_liquidity = min(scores_liquidite) if scores_liquidite else 0

        if min_liquidity < self.MIN_LIQUIDITY_THRESHOLD:
            logger.warning(f"⚠️ LEGGING RISK: Min liquidity {min_liquidity} < {self.MIN_LIQUIDITY_THRESHOLD}")

            self._legger_failures += 1

            return {
                "authorized": False,
                "reason": f"Legging Risk trop élevé. Liquidité min: {min_liquidity:.1f} < {self.MIN_LIQUIDITY_THRESHOLD}",
                "liquidity_scores": leg_details,
                "min_liquidity": min_liquidity
            }

        return {
            "authorized": True,
            "reason": "Liquidité du panier validée pour exécution simultanée.",
            "liquidity_scores": leg_details,
            "min_liquidity": min_liquidity
        }

    async def archiver_telemtrie_arbitrage(
        self,
        basket_id: str,
        anomalie_initiale: float,
        profit_reel: float,
        latence_ms: float,
        friction_cost: float = 0.0,
        status: str = "SUCCESS",
        legs_executed: int = 0,
        legs_total: int = 0
    ) -> str:
        """
        Sérialise le résultat de l'arbitrage en format JSONL.
        """
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "timestamp_unix": time.time(),
            "basket_id": basket_id,
            "mode": self.execution_mode,
            "theoretical_spread": anomalie_initiale,
            "realized_profit": profit_reel,
            "friction_cost": friction_cost,
            "execution_latency_ms": latence_ms,
            "efficiency_loss": anomalie_initiale - profit_reel,
            "status": status,
            "legs_executed": legs_executed,
            "legs_total": legs_total
        }

        filename = f"{self.telemetry_path}/arbitrage_telemetry.jsonl"
        await asyncio.to_thread(self._write_jsonl, filename, payload)

        logger.info(f"💾 [ARBITRAGE MLOPS] Télémétrie archivée: {basket_id}")

        self._results.append(ArbitrageResult(
            basket_id=basket_id,
            status=status,
            theoretical_spread=anomalie_initiale,
            realized_profit=profit_reel,
            friction_cost=friction_cost,
            execution_latency_ms=latence_ms,
            efficiency_loss=anomalie_initiale - profit_reel,
            legs_executed=legs_executed,
            legs_total=legs_total,
            timestamp=datetime.now(timezone.utc).isoformat()
        ))

        if len(self._results) > 100:
            self._results.pop(0)

        return filename

    @staticmethod
    def _write_jsonl(filename: str, payload: Dict[str, Any]) -> None:
        os.makedirs(os.path.dirname(filename), exist_ok=True)
        with open(filename, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload) + "\n")

    def ajuster_seuil_trigger(self, nouvelle_efficience: float) -> None:
        """
        Ajuste dynamiquement le seuil de déclenchement basé sur l'efficience observée.
        """
        if nouvelle_efficience < 0.5:
            self.trigger_threshold *= 1.2
            logger.warning(f"📈 Threshold augmenté: {self.trigger_threshold:.4f}")
        elif nouvelle_efficience > 0.8:
            self.trigger_threshold *= 0.95
            logger.info(f"📉 Threshold réduit: {self.trigger_threshold:.4f}")

    def get_arbitrage_stats(self) -> Dict[str, Any]:
        if not self._results:
            return {
                "total_opportunities": 0,
                "success_rate": 0,
                "avg_profit": 0,
                "avg_latency_ms": 0
            }

        total = len(self._results)
        successes = sum(1 for r in self._results if r.status == "SUCCESS")
        avg_profit = sum(r.realized_profit for r in self._results) / total
        avg_latency = sum(r.execution_latency_ms for r in self._results) / total
        total_friction = sum(r.friction_cost for r in self._results)

        return {
            "total_opportunities": total,
            "successes": successes,
            "success_rate": successes / total if total > 0 else 0,
            "total_profit": sum(r.realized_profit for r in self._results),
            "avg_profit": avg_profit,
            "total_friction": total_friction,
            "avg_latency_ms": avg_latency,
            "legger_failures": self._legger_failures,
            "current_threshold": self.trigger_threshold
        }

    def format_arbitrage_report(self) -> str:
        stats = self.get_arbitrage_stats()

        lines = [
            "🎰 *ARBITRAGE FEEDBACK LOOP REPORT*",
            "───────────────────────────────",
            "",
            f"📊 *Opportunités:* `{stats['total_opportunities']}`",
            f"✅ *Succès:* `{stats['successes']}` | ❌ *Échecs:* `{stats['total_opportunities'] - stats['successes']}`",
            f"📈 *Taux Succès:* `{stats['success_rate']*100:.1f}%`",
            "",
            f"💰 *Profit Total:* `${stats['total_profit']:.4f}`",
            f"💵 *Friction Totale:* `${stats['total_friction']:.4f}`",
            f"⏱️ *Latence Moyenne:* `{stats['avg_latency_ms']:.1f}ms`",
            "",
            f"⚠️ *Legger Failures:* `{stats['legger_failures']}`",
            f"🎯 *Seuil Actuel:* `{stats['current_threshold']*100:.2f}%`",
        ]

        return "\n".join(lines)

    async def scanner_anomalies(self) -> None:
        """PATH MOYEN: scan for Kolmogorov violations and cross-market arbitrage opportunities."""
        logger.info("🔍 [ARBITRAGE SCAN] Scanning contract matrix for Kolmogorov and cross-market anomalies...")
