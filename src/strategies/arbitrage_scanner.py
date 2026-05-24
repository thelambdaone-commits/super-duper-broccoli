import logging
import statistics
import time
from collections import defaultdict, deque
from typing import Any, Optional

logger = logging.getLogger("ArbitrageScanner")

MIN_PROFIT_THRESHOLD = 0.02
MISPRICING_ZSCORE_THRESHOLD = 2.0
PRICE_HISTORY_WINDOW = 50


IPVDefaultConfig = {
    "ma_short_window": 10,
    "ma_long_window": 30,
    "zscore_threshold": MISPRICING_ZSCORE_THRESHOLD,
    "min_history_samples": 10,
    "max_trend_residual_pct": 0.05,
}


class ArbitrageScanner:
    def __init__(
        self,
        min_profit_threshold: float = MIN_PROFIT_THRESHOLD,
        ipv_config: Optional[dict] = None,
    ) -> None:
        self.min_profit = min_profit_threshold
        self._opportunities: list[dict[str, Any]] = []
        self._price_history: dict[str, deque[tuple[float, float]]] = defaultdict(
            lambda: deque(maxlen=PRICE_HISTORY_WINDOW)
        )
        self._ipv_config = {**IPVDefaultConfig, **(ipv_config or {})}

    def record_price(self, market_id: str, price: float) -> None:
        self._price_history[market_id].append((time.time(), price))

    def _sma(self, market_id: str, window: int) -> Optional[float]:
        history = self._price_history.get(market_id)
        if not history or len(history) < window:
            return None
        recent = [p for _, p in history][-window:]
        return sum(recent) / len(recent)

    def _zscore(self, market_id: str, current_price: float) -> Optional[float]:
        history = self._price_history.get(market_id)
        if not history or len(history) < self._ipv_config["min_history_samples"]:
            return None
        prices = [p for _, p in history]
        mean = statistics.mean(prices)
        if len(prices) < 2:
            return None
        stdev = statistics.stdev(prices)
        if stdev == 0:
            return None
        return (current_price - mean) / stdev

    def _linear_trend_residual(
        self, market_id: str, current_price: float
    ) -> Optional[float]:
        history = self._price_history.get(market_id)
        if not history or len(history) < self._ipv_config["min_history_samples"]:
            return None
        points = list(history)
        n = len(points)
        xs = list(range(n))
        ys = [p for _, p in points]
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        den = sum((x - mean_x) ** 2 for x in xs)
        if den == 0:
            return None
        slope = num / den
        intercept = mean_y - slope * mean_x
        predicted = slope * n + intercept
        if predicted == 0:
            return None
        return (current_price - predicted) / abs(predicted)

    def scan_mispricing(
        self,
        market_prices: dict[str, float],
    ) -> list[dict[str, Any]]:
        opportunities: list[dict[str, Any]] = []
        for market_id, current_price in market_prices.items():
            self.record_price(market_id, current_price)
            zs = self._zscore(market_id, current_price)
            if zs is None:
                continue
            if abs(zs) < self._ipv_config["zscore_threshold"]:
                continue
            short_ma = self._sma(market_id, self._ipv_config["ma_short_window"])
            long_ma = self._sma(market_id, self._ipv_config["ma_long_window"])
            trend_residual = self._linear_trend_residual(market_id, current_price)
            deviation_pct = round(float(abs(zs)), 4)
            confidence = min(1.0, deviation_pct / 5.0)
            action = "SELL" if zs > 0 else "BUY"
            opp: dict[str, Any] = {
                "type": "mispricing_ipv",
                "market_id": market_id,
                "current_price": current_price,
                "zscore": round(float(zs), 4),
                "short_ma": round(short_ma, 6) if short_ma is not None else None,
                "long_ma": round(long_ma, 6) if long_ma is not None else None,
                "trend_residual_pct": round(float(trend_residual), 6) if trend_residual is not None else None,
                "deviation_pct": deviation_pct,
                "action": action,
                "confidence": confidence,
            }
            opportunities.append(opp)
            logger.info(
                f"Mispricing detected in {market_id}: "
                f"price={current_price:.4f} zscore={zs:.2f} action={action} "
                f"confidence={confidence:.2f}"
            )
        self._opportunities.extend(opportunities)
        return opportunities

    def scan_sum_inefficiency(
        self,
        market_outcomes: dict[str, dict[str, float]],
    ) -> list[dict[str, Any]]:
        opportunities: list[dict[str, Any]] = []
        for market_id, outcomes in market_outcomes.items():
            total_prob = sum(outcomes.values())
            deviation = total_prob - 1.0
            if abs(deviation) > self.min_profit:
                overpriced = max(outcomes, key=outcomes.get)
                underpriced = min(outcomes, key=outcomes.get)
                action = "SELL" if deviation > 0 else "BUY"
                opportunities.append({
                    "type": "sum_inefficiency",
                    "market_id": market_id,
                    "total_probability": round(total_prob, 4),
                    "deviation": round(deviation, 4),
                    "overpriced_outcome": overpriced,
                    "overpriced_prob": outcomes[overpriced],
                    "underpriced_outcome": underpriced,
                    "underpriced_prob": outcomes[underpriced],
                    "action": action,
                    "confidence": min(1.0, abs(deviation) * 5),
                })
                logger.info(
                    f"Sum inefficiency detected in {market_id}: "
                    f"total_prob={total_prob:.4f}, "
                    f"action={action}, "
                    f"overpriced={overpriced} ({outcomes[overpriced]:.4f}), "
                    f"underpriced={underpriced} ({outcomes[underpriced]:.4f})"
                )
        self._opportunities.extend(opportunities)
        return opportunities

    def scan_conditional_overpricing(
        self,
        parent_market_id: str,
        parent_prob: float,
        child_outcomes: dict[str, float],
    ) -> list[dict[str, Any]]:
        opportunities: list[dict[str, Any]] = []
        for outcome, child_prob in child_outcomes.items():
            if child_prob > parent_prob + self.min_profit:
                opportunities.append({
                    "type": "conditional_overpricing",
                    "parent_market_id": parent_market_id,
                    "parent_probability": parent_prob,
                    "child_outcome": outcome,
                    "child_probability": child_prob,
                    "excess": round(child_prob - parent_prob, 4),
                    "action": "SELL",
                    "confidence": min(1.0, (child_prob - parent_prob) * 3),
                })
                logger.info(
                    f"Conditional overpricing: child={outcome} "
                    f"({child_prob:.4f}) > parent={parent_market_id} "
                    f"({parent_prob:.4f})"
                )
        self._opportunities.extend(opportunities)
        return opportunities

    def to_signals(self, opportunities: list[dict[str, Any]]) -> list[dict[str, Any]]:
        signals: list[dict[str, Any]] = []
        for opp in opportunities:
            base_price = opp.get("current_price")
            if base_price is None:
                if opp.get("type") == "sum_inefficiency":
                    base_price = opp.get("underpriced_prob" if opp.get("action") == "BUY" else "overpriced_prob", 0.5)
                else:
                    base_price = opp.get("child_probability", 0.5)
            signals.append({
                "source": "arbitrage",
                "asset": opp.get("market_id", "UNKNOWN"),
                "action": opp.get("action", "SELL"),
                "price": base_price,
                "size": 0.0,
                "confidence": opp.get("confidence", 0.5),
                "arb_type": opp.get("type", "unknown"),
                "overpriced_outcome": opp.get("overpriced_outcome", ""),
                "underpriced_outcome": opp.get("underpriced_outcome", ""),
                "zscore": opp.get("zscore"),
                "timestamp": time.time(),
            })
        return signals

    def clear_opportunities(self) -> int:
        count = len(self._opportunities)
        self._opportunities.clear()
        return count

    def clear_price_history(self, market_id: Optional[str] = None) -> None:
        if market_id:
            self._price_history.pop(market_id, None)
        else:
            self._price_history.clear()

    @property
    def opportunity_count(self) -> int:
        return len(self._opportunities)

    def get_active_opportunities(self) -> list[dict[str, Any]]:
        return list(self._opportunities)
