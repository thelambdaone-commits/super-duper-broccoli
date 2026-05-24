from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Mapping

from .base_strategy import (
    MarketFeatures,
    PolymarketStrategy,
    StrategyParameters,
    StrategySignal,
    coerce_features,
)

logger = logging.getLogger("PolymarketStrategyFactory")


class InterMarketArbitrageStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="inter_market_arbitrage",
            name="Inter-Market Arbitrage",
            parameters=parameters or StrategyParameters(min_edge=0.025, min_confidence=0.58),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        reference = f.external_price if f.external_price is not None else f.correlated_price
        if reference is None or reference <= 0.0:
            return None
        edge = float(reference - f.price)
        side = "BUY" if edge > 0 else "SELL"
        confidence = min(1.0, 0.50 + abs(edge) * 5.0)
        return self._signal(
            f,
            side=side,
            confidence=confidence,
            edge=edge,
            reason="Polymarket price diverges from external/correlated reference",
            metadata={"reference_price": reference},
        )


class MacroTrendMLStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="macro_trend_ml",
            name="ML-Driven Macro Trend",
            parameters=parameters or StrategyParameters(min_edge=0.035, min_confidence=0.60),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if f.ml_probability is None:
            return None
        regime = f.hmm_regime.upper()
        if "ERRATIC" in regime or "RISK_OFF" in regime:
            return None
        edge = float(f.ml_probability - f.price)
        side = "BUY" if edge > 0 else "SELL"
        regime_bonus = 0.08 if "TREND" in regime or "BULL" in regime else 0.0
        return self._signal(
            f,
            side=side,
            confidence=float(f.ml_probability) + regime_bonus,
            edge=edge,
            reason="HybridQuantModel probability and HMM regime pass trend gate",
        )


class SemanticMomentumStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="semantic_momentum",
            name="Semantic Sentiment Momentum",
            parameters=parameters or StrategyParameters(min_edge=0.02, min_confidence=0.65),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if f.semantic_confidence < self.parameters.min_confidence:
            return None
        # Score typically ranges -1 to 1; map to probability-like space for edge calc
        # if score > 0.3, it's a BUY signal with edge
        sentiment_edge = f.sentiment_score * 0.1
        if abs(sentiment_edge) < self.parameters.min_edge:
            return None
        side = "BUY" if sentiment_edge > 0 else "SELL"
        return self._signal(
            f,
            side=side,
            confidence=f.semantic_confidence,
            edge=sentiment_edge,
            reason=f"LLM semantic analyzer detected strong {side} sentiment",
        )


class NewsDrivenStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="news_driven_catalyst",
            name="News Catalyst Filter",
            parameters=parameters or StrategyParameters(min_edge=0.05, min_confidence=0.70),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        # Placeholder for news catalyst logic (e.g. check metadata for 'catalyst' tag)
        if not f.metadata.get("catalyst_detected"):
            return None
        edge = 0.15 # Aggressive edge for news
        side = f.metadata.get("catalyst_direction", "BUY")
        return self._signal(
            f,
            side=side,
            confidence=0.85,
            edge=edge,
            reason=f"Systemic catalyst detected: {f.metadata.get('catalyst_summary')}",
        )


class CalendarEventStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="calendar_event_drift",
            name="Scheduled Event Drift",
            parameters=parameters or StrategyParameters(min_edge=0.04, min_confidence=0.60),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        # Check if resolution is close (e.g. within 4 hours)
        # time-to-res stored in metadata
        ttr_hours = f.metadata.get("hours_to_resolution")
        if ttr_hours is None or ttr_hours > 4:
            return None
        # Probability tends to drift towards 1.0 or 0.0 near resolution
        if f.price > 0.85:
            return self._signal(f, "BUY", 0.90, 0.05, "Resolution drift: High probability outcome converging")
        if f.price < 0.15:
            return self._signal(f, "SELL", 0.90, 0.05, "Resolution drift: Low probability outcome decaying")
        return None


class PublicOnchainFlowStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="onchain_whale_flow",
            name="Public On-chain Flow",
            parameters=parameters or StrategyParameters(min_edge=0.03, min_confidence=0.55),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        flow_score = f.known_wallet_flow_score
        if abs(flow_score) < 0.5:
            return None
        edge = flow_score * 0.05
        side = "BUY" if flow_score > 0 else "SELL"
        return self._signal(
            f,
            side=side,
            confidence=min(1.0, 0.5 + abs(flow_score) / 4.0),
            edge=edge,
            reason="Significant capital flow from tracked wallets detected on-chain",
        )


class PassiveMarketMakingStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="passive_market_making",
            name="Passive Liquidity Provision",
            parameters=parameters or StrategyParameters(min_edge=0.01, min_confidence=0.50, max_spread=0.02),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        # Only quote if spread is healthy
        if f.spread > self.parameters.max_spread:
            return None
        # Bias based on ML probability if available, else neutral
        prob = f.ml_probability if f.ml_probability is not None else 0.5
        side = "BUY" if prob >= 0.5 else "SELL"
        return self._signal(
            f,
            side=side,
            confidence=0.51,
            edge=0.015,
            reason="Market making: placing passive quote near midpoint",
        )


class DynamicMarketMakingStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="dynamic_market_making",
            name="Dynamic Liquidity Provision",
            parameters=parameters or StrategyParameters(min_edge=0.01, min_confidence=0.50, max_spread=0.03),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if f.spread > self.parameters.max_spread:
            return None
        # Skew quotes based on order imbalance
        skew = f.order_imbalance * 0.02
        prob = (f.ml_probability if f.ml_probability is not None else 0.5) + skew
        side = "BUY" if prob >= 0.5 else "SELL"
        return self._signal(
            f,
            side=side,
            confidence=0.52,
            edge=0.02,
            reason=f"Market making: skewed quote (imbalance={f.order_imbalance:.2f})",
        )


class MeanReversionStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="mean_reversion",
            name="Microstructure Mean Reversion",
            parameters=parameters or StrategyParameters(min_edge=0.02, min_confidence=0.55),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        # Check for extreme price deviations from SMA (mock logic)
        # Normally use indicators from feature_store
        return None


class MomentumBreakoutStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="momentum_breakout",
            name="Orderbook Momentum Breakout",
            parameters=parameters or StrategyParameters(min_edge=0.03, min_confidence=0.60),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if abs(f.order_imbalance) < 0.7:
            return None
        side = "BUY" if f.order_imbalance > 0 else "SELL"
        return self._signal(
            f,
            side=side,
            confidence=0.65,
            edge=0.04,
            reason="Momentum: high orderbook imbalance suggests imminent breakout",
        )


class MicroScalpingStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="micro_scalping",
            name="Midpoint Scalping",
            parameters=parameters or StrategyParameters(min_edge=0.005, min_confidence=0.51),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        # High frequency scalping logic
        return None


class ExpectedValueStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="expected_value",
            name="Pure EV Maximization",
            parameters=parameters or StrategyParameters(min_edge=0.03, min_confidence=0.50),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if f.ml_probability is None:
            return None
        ev = float(f.ml_probability - f.price)
        if abs(ev) < self.parameters.min_edge:
            return None
        side = "BUY" if ev > 0 else "SELL"
        return self._signal(
            f,
            side=side,
            confidence=0.5,
            edge=abs(ev),
            reason=f"Positive expected value detected (ev={ev:+.4f})",
        )


class BundleSpreadArbitrageStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="bundle_spread_arb",
            name="Cross-Outcome Spread Arbitrage",
            parameters=parameters or StrategyParameters(min_edge=0.015, min_confidence=0.80),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        # Check if sum of YES and NO prices significantly deviates from 1.0
        # This requires both token prices in features metadata
        return None


class IntraMarketArbitrageStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="intra_market_arb",
            name="Intra-Market Inefficiency",
            parameters=parameters or StrategyParameters(min_edge=0.01, min_confidence=0.75),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        # High frequency intra-market arb
        return None


class PublicOracleLagStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="oracle_lag_latency",
            name="Oracle Lag Latency",
            parameters=parameters or StrategyParameters(min_edge=0.05, min_confidence=0.85),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        # Detect delay between real world event and Polymarket oracle update
        return None


class PairsTradingStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="pairs_mean_reversion",
            name="Correlated Pairs Trading",
            parameters=parameters or StrategyParameters(min_edge=0.02, min_confidence=0.58),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        # Trading two correlated markets (e.g. BTC Up vs ETH Up)
        return None


class SwingCatalystStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="swing_catalyst",
            name="Multi-Day Swing Catalyst",
            parameters=parameters or StrategyParameters(min_edge=0.08, min_confidence=0.75),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        # Longer term swing trading based on major news
        return None


class ContrarianExcessStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="contrarian_excess",
            name="Contrarian Mean Reversion",
            parameters=parameters or StrategyParameters(min_edge=0.05, min_confidence=0.60),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        # Bet against extreme crowd sentiment (overbought/oversold)
        return None


class BayesianUpdateStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="bayesian_inference",
            name="Bayesian Belief Update",
            parameters=parameters or StrategyParameters(min_edge=0.025, min_confidence=0.65),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        # Iterative update of winning probability based on stream of features
        return None


class DirectionalConvictionStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="directional_trend",
            name="High-Conviction Trend",
            parameters=parameters or StrategyParameters(min_edge=0.10, min_confidence=0.85),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        # Only trade when everything aligns (ML + HMM + Sentiment)
        return None


class MonteCarloEdgeStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="monte_carlo_edge",
            name="Simulated Path Edge",
            parameters=parameters or StrategyParameters(min_edge=0.04, min_confidence=0.55),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        # Use SABR/SSVI simulations to find edge in tail events
        return None


class OpportunisticLiquidityTakerStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="liquidity_taker_edge",
            name="Opportunistic Spread Taker",
            parameters=parameters or StrategyParameters(min_edge=0.06, min_confidence=0.80),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        # If edge is HUGE, take the spread instead of waiting as maker
        if f.ml_probability is None:
            return None
        
        raw_edge = float(f.ml_probability - f.price)
        stale_quote_edge = raw_edge - f.spread
        
        if abs(stale_quote_edge) < self.parameters.min_edge:
            return None
        
        side = "BUY" if stale_quote_edge > 0 else "SELL"
        return self._signal(f, side, min(1.0, 0.70 + abs(stale_quote_edge)), stale_quote_edge, "Large edge justifies taker execution despite spread", order_type="MARKET")


def build_default_polymarket_strategies() -> list[PolymarketStrategy]:
    from .deep_rl_allocation_strategy import DeepRLAllocationStrategy
    return [
        DeepRLAllocationStrategy(),
        InterMarketArbitrageStrategy(),
        IntraMarketArbitrageStrategy(),
        BundleSpreadArbitrageStrategy(),
        PublicOracleLagStrategy(),
        MacroTrendMLStrategy(),
        SemanticMomentumStrategy(),
        NewsDrivenStrategy(),
        CalendarEventStrategy(),
        PublicOnchainFlowStrategy(),
        PassiveMarketMakingStrategy(),
        DynamicMarketMakingStrategy(),
        MeanReversionStrategy(),
        MomentumBreakoutStrategy(),
        MicroScalpingStrategy(),
        ExpectedValueStrategy(),
        PairsTradingStrategy(),
        SwingCatalystStrategy(),
        ContrarianExcessStrategy(),
        BayesianUpdateStrategy(),
        DirectionalConvictionStrategy(),
        MonteCarloEdgeStrategy(),
        OpportunisticLiquidityTakerStrategy(),
    ]
