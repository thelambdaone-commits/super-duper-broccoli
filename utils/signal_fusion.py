from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger("SignalFusionEngine")

@dataclass
class FusionComponent:
    id: str
    weight: float
    last_signal_time: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0

class SignalFusionEngine:
    """
    Lobstar Signal Fusion Engine (Inspired by Aulekator's 7-Phase Architecture).
    Aggregates signals from multiple agentic sources and computes a weighted consensus.
    """

    def __init__(self, threshold: float = 0.65):
        self.threshold = threshold
        self.components: Dict[str, FusionComponent] = {
            "btc_15m_fusion": FusionComponent("btc_15m_fusion", weight=0.40),
            "arbitrage_scanner": FusionComponent("arbitrage_scanner", weight=0.25),
            "social_sentiment": FusionComponent("social_sentiment", weight=0.15),
            "llm_council": FusionComponent("llm_council", weight=0.15),
            "divergence_alpha": FusionComponent("divergence_alpha", weight=0.05),
        }
        self.active_signals: List[Dict[str, Any]] = []
        from utils.divergence_detector import DivergenceDetector
        self.divergence_detector = DivergenceDetector()

    def add_signal(self, component_id: str, signal: Dict[str, Any]):
        """Injects a signal from a specific component."""
        if component_id not in self.components:
            logger.warning(f"Unknown component ID: {component_id}")
            return

        signal["component_id"] = component_id
        signal["received_at"] = time.time()
        self.active_signals.append(signal)
        self.components[component_id].last_signal_time = time.time()

        # Keep only recent signals (last 5 minutes)
        self.active_signals = [s for s in self.active_signals if time.time() - s["received_at"] < 300]

    def compute_consensus(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Computes the weighted consensus for a specific ticker.
        consensus_score = sum(weight * confidence * direction)
        """
        relevant_signals = [s for s in self.active_signals if s.get("ticker") == ticker]
        if not relevant_signals:
            return None

        consensus_score = 0.0
        total_weight_present = 0.0
        details = {}

        for sig in relevant_signals:
            comp_id = sig["component_id"]
            weight = self.components[comp_id].weight
            confidence = sig.get("confidence", 0.5)

            # side: BUY/YES -> +1, SELL/NO -> -1
            direction = 1 if sig.get("side") in ["BUY", "YES", "LONG"] else -1

            consensus_score += (weight * confidence * direction)
            total_weight_present += weight
            details[comp_id] = {
                "direction": direction,
                "confidence": confidence,
                "weighted_contribution": weight * confidence * direction
            }

        # Normalize score
        final_score = consensus_score / total_weight_present if total_weight_present > 0 else 0.0

        logger.info(f"Consensus for {ticker}: {final_score:.2f} (Threshold: {self.threshold})")

        if abs(final_score) >= self.threshold:
            side = "BUY" if final_score > 0 else "SELL"
            return {
                "ticker": ticker,
                "side": side,
                "score": final_score,
                "confidence": abs(final_score),
                "reason": f"Weighted consensus achieved from: {list(details.keys())}",
                "metadata": {
                    "fusion_details": details,
                    "total_weight": total_weight_present
                }
            }

        return None

    def update_weights_from_pnl(self, performance_data: Dict[str, Dict[str, float]]):
        """
        Phase 7: Feedback Loop.
        Adjusts component weights based on actual PnL reported by the Ledger.
        """
        for comp_id, perf in performance_data.items():
            if comp_id in self.components:
                pnl = perf.get("total_pnl", 0.0)
                # Adaptive adjustment: +5% weight for profit, -5% for loss
                if pnl > 0:
                    self.components[comp_id].weight *= 1.05
                elif pnl < 0:
                    self.components[comp_id].weight *= 0.95

                # Ensure weights stay in reasonable bounds (0.05 - 0.70)
                self.components[comp_id].weight = max(0.05, min(0.70, self.components[comp_id].weight))

        # Re-normalize weights to sum to 1.0
        total = sum(c.weight for c in self.components.values())
        for c in self.components.values():
            c.weight /= total

        logger.info("Weights optimized based on performance feedback.")
