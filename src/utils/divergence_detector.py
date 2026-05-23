import logging
import time
from typing import Dict, Optional, Any

logger = logging.getLogger("DivergenceDetector")

class DivergenceDetector:
    """
    Spike & Divergence Detector (Inspired by Aulekator's Signal Intelligence).
    Monitors price differences between major exchanges (Binance vs Coinbase)
    to identify leading signals for prediction markets.
    """

    def __init__(self, threshold_bps: float = 15.0):
        self.threshold_bps = threshold_bps
        self._prices: Dict[str, Dict[str, float]] = {
            "BINANCE": {},
            "COINBASE": {}
        }
        self._timestamps: Dict[str, Dict[str, float]] = {
            "BINANCE": {},
            "COINBASE": {}
        }

    def update_price(self, exchange: str, ticker: str, price: float):
        exchange = exchange.upper()
        self._prices[exchange][ticker] = price
        self._timestamps[exchange][ticker] = time.time()

    def get_divergence(self, ticker: str) -> Optional[float]:
        """
        Calculates divergence in Basis Points (BPS).
        Returns positive if Binance > Coinbase, negative otherwise.
        """
        b_price = self._prices["BINANCE"].get(ticker)
        c_price = self._prices["COINBASE"].get(ticker)

        if not b_price or not c_price:
            return None

        # Ensure data is fresh (last 10 seconds)
        now = time.time()
        if (now - self._timestamps["BINANCE"][ticker] > 10 or
            now - self._timestamps["COINBASE"][ticker] > 10):
            return None

        mid = (b_price + c_price) / 2.0
        diff = b_price - c_price
        bps = (diff / mid) * 10000.0

        return bps

    def detect_alpha(self, ticker: str) -> Optional[Dict[str, Any]]:
        """
        Detects if a significant divergence exists that could signal a move on Polymarket.
        """
        bps = self.get_divergence(ticker)
        if bps is None:
            return None

        if abs(bps) >= self.threshold_bps:
            direction = "UP" if bps > 0 else "DOWN"
            logger.info(f"🚀 [ALPHA] Divergence detected for {ticker}: {bps:.1f} bps ({direction})")
            return {
                "ticker": ticker,
                "divergence_bps": bps,
                "direction": direction,
                "confidence": min(1.0, abs(bps) / 100.0), # Normalized confidence
                "timestamp": time.time()
            }
        return None
