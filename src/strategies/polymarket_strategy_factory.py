from __future__ import annotations

import logging
from typing import Any, Mapping

from .base_strategy import (
    MarketFeatures,
    PolymarketStrategy,
    StrategyParameters,
    StrategySignal,
    coerce_features,
)

logger = logging.getLogger("PolymarketStrategyFactory")


def _meta_float(features: MarketFeatures, key: str, default: float = 0.0) -> float:
    value = features.metadata.get(key, default)
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _meta_bool(features: MarketFeatures, key: str, default: bool = False) -> bool:
    value = features.metadata.get(key, default)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


class DeepRLAllocationStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="deep_rl_allocation",
            name="Deep RL Portfolio Allocation",
            parameters=parameters or StrategyParameters(min_confidence=0.65, min_edge=0.015, max_spread=0.04),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        probability = f.ml_probability if f.ml_probability is not None else _meta_float(f, "posterior_probability", 0.5)
        edge = float(probability - f.price)
        side = "BUY" if edge > 0 else "SELL"
        return self._signal(f, side, abs(probability), abs(edge), f"RL allocation proxy (p={probability:.2f})")


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
        sentiment_edge = f.sentiment_score * 0.1
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
            strategy_id="news_driven",
            name="News Catalyst Filter",
            parameters=parameters or StrategyParameters(min_edge=0.05, min_confidence=0.70),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        news_score = max(_meta_float(f, "news_score"), _meta_float(f, "source_reliability"))
        if news_score < self.parameters.min_confidence and not _meta_bool(f, "catalyst_detected"):
            return None
        edge = max(self.parameters.min_edge, abs(f.sentiment_score) * 0.1, _meta_float(f, "expected_event_move"))
        side = "BUY" if f.sentiment_score >= 0 else "SELL"
        summary = f.metadata.get("catalyst_summary") or "News catalyst detected"
        return self._signal(f, side, max(news_score, 0.85), edge, str(summary))


class CalendarEventStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="calendar_event",
            name="Scheduled Event Drift",
            parameters=parameters or StrategyParameters(min_edge=0.04, min_confidence=0.60),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        hours_to_resolution = _meta_float(f, "hours_to_resolution", _meta_float(f, "hours_to_known_event", 999.0))
        if hours_to_resolution > 24:
            return None
        expected_move = max(self.parameters.min_edge, _meta_float(f, "expected_event_move", 0.0))
        if f.price >= 0.5:
            return self._signal(f, "BUY", 0.75, expected_move, "Event-driven drift favors the current leader")
        return self._signal(f, "SELL", 0.75, expected_move, "Event-driven drift penalizes the lagging outcome")


class PublicOnchainFlowStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="public_onchain_flow",
            name="Public On-chain Flow",
            parameters=parameters or StrategyParameters(min_edge=0.03, min_confidence=0.55),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        flow_score = _meta_float(f, "known_wallet_flow_score", 0.0)
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
        if f.spread > self.parameters.max_spread:
            return None
        probability = f.ml_probability if f.ml_probability is not None else 0.5
        side = "BUY" if probability >= 0.5 else "SELL"
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
        skew = f.order_imbalance * 0.02
        probability = (f.ml_probability if f.ml_probability is not None else 0.5) + skew
        side = "BUY" if probability >= 0.5 else "SELL"
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
        rolling_mean = _meta_float(f, "rolling_mean_price", f.price)
        edge = rolling_mean - f.price
        if abs(edge) < self.parameters.min_edge:
            return None
        side = "BUY" if edge > 0 else "SELL"
        confidence = min(1.0, 0.55 + abs(edge))
        return self._signal(f, side, confidence, edge, "Price deviates from rolling mean and may revert")


class MomentumBreakoutStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="momentum_breakout",
            name="Orderbook Momentum Breakout",
            parameters=parameters or StrategyParameters(min_edge=0.03, min_confidence=0.60),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        momentum = max(abs(f.order_imbalance), abs(_meta_float(f, "momentum_1m", 0.0) * 10.0))
        if momentum < 0.3:
            return None
        side = "BUY" if (f.order_imbalance or _meta_float(f, "momentum_1m", 0.0)) > 0 else "SELL"
        edge = max(self.parameters.min_edge, abs(_meta_float(f, "momentum_1m", 0.0)), 0.04)
        return self._signal(
            f,
            side=side,
            confidence=0.65,
            edge=edge,
            reason="Momentum: orderbook imbalance or short-term drift suggests breakout",
        )


class MicroScalpingStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="micro_scalping",
            name="Midpoint Scalping",
            parameters=parameters or StrategyParameters(min_edge=0.005, min_confidence=0.51),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if f.bid_price <= 0 or f.ask_price <= 0 or f.spread <= 0:
            return None
        edge = min(f.spread / 2.0, 0.02)
        side = "BUY" if f.order_imbalance >= 0 else "SELL"
        return self._signal(f, side, 0.52, edge, "Tight spread allows midpoint scalping")


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
            strategy_id="bundle_spread_arbitrage",
            name="Cross-Outcome Spread Arbitrage",
            parameters=parameters or StrategyParameters(min_edge=0.015, min_confidence=0.80),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        total_probability = _meta_float(f, "outcome_total_probability", 1.0)
        deviation = 1.0 - total_probability
        if abs(deviation) < self.parameters.min_edge:
            return None
        side = "BUY" if deviation > 0 else "SELL"
        return self._signal(
            f,
            side=side,
            confidence=0.82,
            edge=abs(deviation),
            reason="Bundle outcome probabilities deviate from 1.0",
        )


class IntraMarketArbitrageStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="intra_market_arbitrage",
            name="Intra-Market Inefficiency",
            parameters=parameters or StrategyParameters(min_edge=0.01, min_confidence=0.75),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        edge = _meta_float(f, "stale_quote_edge", 0.0)
        if abs(edge) < self.parameters.min_edge:
            return None
        side = "BUY" if edge > 0 else "SELL"
        return self._signal(f, side, 0.78, abs(edge), "Stale quote detected inside the same market")


class PublicOracleLagStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="public_oracle_lag",
            name="Oracle Lag Latency",
            parameters=parameters or StrategyParameters(min_edge=0.05, min_confidence=0.85),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        oracle_probability = _meta_float(f, "posterior_probability", 0.0)
        if oracle_probability <= 0.0:
            return None
        edge = oracle_probability - f.price
        side = "BUY" if edge > 0 else "SELL"
        return self._signal(f, side, 0.85, abs(edge), "Public oracle lags the observed market state")


class PairsTradingStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="pairs_trading",
            name="Correlated Pairs Trading",
            parameters=parameters or StrategyParameters(min_edge=0.02, min_confidence=0.58),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        pair_spread_zscore = _meta_float(f, "pair_spread_zscore", 0.0)
        if abs(pair_spread_zscore) < 2.0 or not _meta_bool(f, "hedge_market_available"):
            return None
        side = "BUY" if pair_spread_zscore < 0 else "SELL"
        edge = min(0.10, abs(pair_spread_zscore) / 50.0)
        return self._signal(f, side, 0.62, edge, "Correlated pair spread is statistically stretched")


class SwingCatalystStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="swing_catalyst",
            name="Multi-Day Swing Catalyst",
            parameters=parameters or StrategyParameters(min_edge=0.08, min_confidence=0.75),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        expected_move = _meta_float(f, "expected_event_move", 0.0)
        if expected_move < self.parameters.min_edge:
            return None
        side = "BUY" if (f.ml_probability or 0.5) >= f.price else "SELL"
        return self._signal(f, side, 0.8, expected_move, "Multi-session catalyst justifies a swing setup")


class ContrarianExcessStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="contrarian_excess",
            name="Contrarian Mean Reversion",
            parameters=parameters or StrategyParameters(min_edge=0.05, min_confidence=0.60),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if abs(f.sentiment_score) < 0.6:
            return None
        side = "SELL" if f.sentiment_score > 0 else "BUY"
        edge = abs(f.sentiment_score) * 0.08
        return self._signal(f, side, 0.64, edge, "Crowd sentiment appears stretched; fade the excess")


class BayesianUpdateStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="bayesian_update",
            name="Bayesian Belief Update",
            parameters=parameters or StrategyParameters(min_edge=0.025, min_confidence=0.65),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        posterior = _meta_float(f, "posterior_probability", 0.0)
        if posterior <= 0.0:
            return None
        edge = posterior - f.price
        side = "BUY" if edge > 0 else "SELL"
        return self._signal(f, side, 0.68, abs(edge), "Bayesian posterior diverges from traded probability")


class DirectionalConvictionStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="directional_conviction",
            name="High-Conviction Trend",
            parameters=parameters or StrategyParameters(min_edge=0.10, min_confidence=0.85),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if f.ml_probability is None or f.semantic_confidence < 0.75:
            return None
        edge = float(f.ml_probability - f.price)
        if abs(edge) < self.parameters.min_edge:
            return None
        sentiment_aligns = (f.sentiment_score >= 0 and edge > 0) or (f.sentiment_score <= 0 and edge < 0)
        if not sentiment_aligns:
            return None
        regime = f.hmm_regime.upper()
        if "ERRATIC" in regime:
            return None
        side = "BUY" if edge > 0 else "SELL"
        confidence = min(1.0, 0.85 + abs(f.sentiment_score) * 0.05)
        return self._signal(f, side, confidence, abs(edge), "ML, sentiment and regime align on one direction")


class MonteCarloEdgeStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="monte_carlo_edge",
            name="Simulated Path Edge",
            parameters=parameters or StrategyParameters(min_edge=0.04, min_confidence=0.55),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        mc_probability = _meta_float(f, "monte_carlo_probability", 0.0)
        if mc_probability <= 0.0:
            return None
        edge = mc_probability - f.price
        side = "BUY" if edge > 0 else "SELL"
        return self._signal(f, side, 0.6, abs(edge), "Monte Carlo path simulation disagrees with current price")


class OpportunisticLiquidityTakerStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="opportunistic_liquidity_taker",
            name="Opportunistic Spread Taker",
            parameters=parameters or StrategyParameters(min_edge=0.06, min_confidence=0.80),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if f.ml_probability is None:
            return None
        raw_edge = float(f.ml_probability - f.price)
        stale_quote_edge = _meta_float(f, "stale_quote_edge", raw_edge - f.spread)
        if abs(stale_quote_edge) < self.parameters.min_edge:
            return None
        available_depth = _meta_float(f, "available_depth_usdc", 0.0)
        if available_depth <= 0.0:
            return None
        side = "BUY" if stale_quote_edge > 0 else "SELL"
        confidence = min(1.0, 0.80 + abs(stale_quote_edge) * 0.5)
        return self._signal(
            f,
            side,
            confidence,
            abs(stale_quote_edge),
            "Large edge justifies taker execution despite spread",
            order_type="MARKET",
        )


def build_default_polymarket_strategies() -> list[PolymarketStrategy]:
    return [
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
