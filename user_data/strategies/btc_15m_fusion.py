from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping

from user_data.strategies.base_strategy import (
    MarketFeatures,
    StrategyParameters,
    StrategySignal,
    coerce_features,
)


@dataclass
class Btc15MinuteFusionStrategy:
    strategy_id: str = "btc_15m_fusion"
    name: str = "BTC 15m Fusion"
    parameters: StrategyParameters = field(
        default_factory=lambda: StrategyParameters(
            min_edge=0.025,
            min_confidence=0.60,
            max_spread=0.06,
            passive_spread_threshold=0.02,
        )
    )

    def update_parameters(self, updates: Mapping[str, float | int]) -> None:
        for key, value in updates.items():
            if hasattr(self.parameters, key):
                setattr(self.parameters, key, value)

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if f.ticker.upper() != "BTC":
            return None

        # Allow bypass of timeframe check if forced via metadata
        if not self._is_15m_close(f.metadata) and not f.metadata.get("force_real_execution"):
            return None

        if f.price <= 0.0 or f.spread > self.parameters.max_spread:
            return None

        fused_edge, confidence, reason, metadata = self._score_features(f)
        if abs(fused_edge) < self.parameters.min_edge or confidence < self.parameters.min_confidence:
            return None

        side = "BUY" if fused_edge > 0 else "SELL"
        return StrategySignal(
            strategy_id=self.strategy_id,
            market_id=f.market_id,
            ticker=f.ticker,
            side=side,
            price=f.price,
            confidence=min(1.0, max(0.0, confidence)),
            edge=fused_edge,
            reason=reason,
            metadata=metadata,
        )

    def _is_15m_close(self, metadata: Mapping[str, Any]) -> bool:
        if bool(metadata.get("is_candle_close", False)):
            return True
        interval = str(metadata.get("candle_interval", metadata.get("timeframe", ""))).lower()
        if interval in {"15m", "15min", "15_min", "m15"}:
            return True
        return bool(metadata.get("bar_closed_15m", False))

    def _score_features(self, features: MarketFeatures) -> tuple[float, float, str, dict[str, Any]]:
        microstructure_score = self._microstructure_score(features)
        calibrated_score = self._calibrated_score(features)
        momentum_score = self._momentum_score(features)

        fused_edge = (
            microstructure_score * 0.35
            + calibrated_score * 0.45
            + momentum_score * 0.20
        )
        confidence = 0.50 + min(0.35, abs(fused_edge) * 3.0)
        reason = "15m BTC fusion combines microstructure, calibrated edge, and short-term momentum"
        metadata = {
            "microstructure_score": round(microstructure_score, 6),
            "calibrated_score": round(calibrated_score, 6),
            "momentum_score": round(momentum_score, 6),
            "source_weights": {
                "microstructure": 0.35,
                "calibrated": 0.45,
                "momentum": 0.20,
            },
            "timeframe": "15m",
        }
        return fused_edge, confidence, reason, metadata

    def _microstructure_score(self, features: MarketFeatures) -> float:
        imbalance = float(features.order_imbalance)
        if imbalance != 0.0:
            return max(-0.10, min(0.10, imbalance * 0.12))

        bid = float(features.bid_price)
        ask = float(features.ask_price)
        if bid > 0.0 and ask > bid:
            spread = ask - bid
            mid = (bid + ask) / 2.0
            if mid > 0.0:
                return max(-0.10, min(0.10, (spread / mid) * -0.5))
        return 0.0

    def _calibrated_score(self, features: MarketFeatures) -> float:
        if features.ml_probability is not None:
            return float(features.ml_probability) - float(features.price)
        if features.external_price is not None:
            return float(features.external_price) - float(features.price)
        if features.correlated_price is not None:
            return float(features.correlated_price) - float(features.price)
        return 0.0

    def _momentum_score(self, features: MarketFeatures) -> float:
        metadata = features.metadata
        spike = metadata.get("spike_score")

        # Si le score n'est pas déjà présent, on essaie de le calculer à la volée
        # si des données OHLCV sont fournies dans les métadonnées.
        if spike is None and "ohlcv" in metadata:
            try:
                from utils.chart_pattern_detector import ChartPatternDetector
                detector = ChartPatternDetector()
                spike = detector.detect_spike(metadata["ohlcv"])
            except Exception:
                spike = 0.0

        spike = float(spike or metadata.get("momentum_1m", 0.0) or 0.0)
        return max(-0.10, min(0.10, spike * 0.10))
