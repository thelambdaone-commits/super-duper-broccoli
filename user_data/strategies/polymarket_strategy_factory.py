from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from user_data.strategies.base_strategy import (
    MarketFeatures,
    StrategyParameters,
    StrategySignal,
    coerce_features,
)
from user_data.strategies.btc_15m_fusion import Btc15MinuteFusionStrategy


@dataclass
class PolymarketStrategy:
    strategy_id: str
    name: str
    parameters: StrategyParameters

    def update_parameters(self, updates: Mapping[str, float | int]) -> None:
        for key, value in updates.items():
            if hasattr(self.parameters, key):
                setattr(self.parameters, key, value)

    def _signal(
        self,
        features: MarketFeatures,
        side: str,
        confidence: float,
        edge: float,
        reason: str,
        order_type: str = "LIMIT",
        metadata: dict[str, Any] | None = None,
    ) -> StrategySignal | None:
        if features.price <= 0.0:
            return None
        if abs(edge) < self.parameters.min_edge:
            return None
        if confidence < self.parameters.min_confidence:
            return None
        if features.spread > self.parameters.max_spread:
            return None
        return StrategySignal(
            strategy_id=self.strategy_id,
            market_id=features.market_id,
            ticker=features.ticker,
            side=side,
            price=features.price,
            confidence=max(0.0, min(1.0, confidence)),
            edge=float(edge),
            reason=reason,
            order_type=order_type,
            metadata=metadata or {},
        )


class InterMarketArbitrageStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        params = parameters or StrategyParameters(
            min_edge=0.025,
            min_confidence=0.58,
            extra={"confidence_multiplier": 5.0}
        )
        super().__init__(
            strategy_id="inter_market_arbitrage",
            name="Inter-Market Arbitrage",
            parameters=params,
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        reference = f.external_price if f.external_price is not None else f.correlated_price
        if reference is None or reference <= 0.0:
            return None
        edge = float(reference - f.price)
        side = "BUY" if edge > 0 else "SELL"
        multiplier = float(self.parameters.extra.get("confidence_multiplier", 5.0))
        confidence = min(1.0, 0.50 + abs(edge) * multiplier)
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
        params = parameters or StrategyParameters(
            min_edge=0.035,
            min_confidence=0.60,
            extra={"confidence_multiplier": 4.0, "regime_bonus": 0.08}
        )
        super().__init__(
            strategy_id="macro_trend_ml",
            name="ML-Driven Macro Trend",
            parameters=params,
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

        multiplier = float(self.parameters.extra.get("confidence_multiplier", 4.0))
        bonus_val = float(self.parameters.extra.get("regime_bonus", 0.08))
        regime_bonus = bonus_val if "TREND" in regime or "BULL" in regime else 0.0

        confidence = min(1.0, 0.50 + abs(edge) * multiplier + regime_bonus)
        return self._signal(
            f,
            side=side,
            confidence=confidence,
            edge=edge,
            reason="HybridQuantModel probability and HMM regime pass trend gate",
            metadata={"ml_probability": f.ml_probability, "hmm_regime": f.hmm_regime},
        )


class SemanticMomentumStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        params = parameters or StrategyParameters(
            min_edge=0.03,
            min_confidence=0.62,
            extra={"edge_multiplier": 0.10, "sentiment_bonus_max": 0.20}
        )
        super().__init__(
            strategy_id="semantic_momentum",
            name="LLM/Semantic Momentum",
            parameters=params,
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if f.semantic_confidence <= 0.0 or f.sentiment_score == 0.0:
            return None

        edge_mult = float(self.parameters.extra.get("edge_multiplier", 0.10))
        bonus_max = float(self.parameters.extra.get("sentiment_bonus_max", 0.20))

        edge = float(f.sentiment_score * edge_mult)
        side = "BUY" if edge > 0 else "SELL"
        confidence = min(1.0, f.semantic_confidence + min(bonus_max, abs(f.sentiment_score) * bonus_max))
        return self._signal(
            f,
            side=side,
            confidence=confidence,
            edge=edge,
            reason="Telegram/news semantic momentum is aligned with market direction",
            metadata={"sentiment_score": f.sentiment_score},
        )


class PassiveMarketMakingStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="passive_market_making",
            name="Passive Market Making / Spread Capture",
            parameters=parameters or StrategyParameters(
                min_edge=0.012,
                min_confidence=0.52,
                max_spread=0.12,
                passive_spread_threshold=0.018,
            ),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if f.bid_price <= 0.0 or f.ask_price <= 0.0:
            return None
        if f.spread < self.parameters.passive_spread_threshold:
            return None
        side = "BUY" if f.order_imbalance >= 0.0 else "SELL"
        edge = f.spread / 2.0
        confidence = min(1.0, 0.52 + min(0.20, abs(f.order_imbalance) * 0.20))
        return self._signal(
            f,
            side=side,
            confidence=confidence,
            edge=edge,
            reason="Spread is wide enough for passive maker capture",
            order_type="LIMIT",
            metadata={"order_imbalance": f.order_imbalance, "spread": f.spread},
        )


class MeanReversionStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        params = parameters or StrategyParameters(
            min_edge=0.02,
            min_confidence=0.57,
            max_spread=0.10,
            extra={
                "max_imbalance": 0.80,
                "base_confidence": 0.54,
                "confidence_multiplier": 5.0,
                "imbalance_bonus": 0.20
            }
        )
        super().__init__(
            strategy_id="mean_reversion",
            name="Microstructure Mean Reversion",
            parameters=params,
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        fair_value = f.ml_probability if f.ml_probability is not None else f.metadata.get("rolling_mean_price")
        if fair_value is None:
            fair_value = f.correlated_price
        if fair_value is None:
            return None
        fair_value = float(fair_value)
        edge = fair_value - f.price

        max_imb = float(self.parameters.extra.get("max_imbalance", 0.80))
        if abs(f.order_imbalance) > max_imb:
            return None

        side = "BUY" if edge > 0 else "SELL"

        base_conf = float(self.parameters.extra.get("base_confidence", 0.54))
        conf_mult = float(self.parameters.extra.get("confidence_multiplier", 5.0))
        imb_bonus = float(self.parameters.extra.get("imbalance_bonus", 0.20))

        confidence = min(1.0, base_conf + abs(edge) * conf_mult + max(0.0, imb_bonus - abs(f.order_imbalance)) * imb_bonus)
        return self._signal(
            f,
            side=side,
            confidence=confidence,
            edge=edge,
            reason="Market price deviates from fair value and order imbalance is not extreme",
            metadata={"fair_value": fair_value, "order_imbalance": f.order_imbalance},
        )


class DynamicMarketMakingStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="dynamic_market_making",
            name="Dynamic Market Making",
            parameters=parameters or StrategyParameters(min_edge=0.01, min_confidence=0.54, max_spread=0.15),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        inventory = float(f.metadata.get("inventory_bias", 0.0) or 0.0)
        flow = float(f.metadata.get("order_flow_imbalance", f.order_imbalance) or 0.0)
        if f.bid_price <= 0.0 or f.ask_price <= 0.0 or f.spread <= 0.0:
            return None
        side = "SELL" if inventory > 0.35 else "BUY" if inventory < -0.35 else ("BUY" if flow >= 0 else "SELL")
        edge = max(f.spread / 2.0, abs(flow) * 0.015)
        confidence = min(1.0, 0.54 + abs(flow) * 0.18 + min(0.12, f.spread))
        quote_price = f.bid_price if side == "BUY" else f.ask_price
        return self._signal(
            f.__class__(**{**f.__dict__, "price": quote_price}),
            side,
            confidence,
            edge,
            "Dynamic maker quote adjusted for inventory and order flow",
            metadata={"inventory_bias": inventory, "order_flow_imbalance": flow},
        )


class MomentumBreakoutStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="momentum_breakout",
            name="Momentum / Trend Breakout",
            parameters=parameters or StrategyParameters(min_edge=0.025, min_confidence=0.58, max_spread=0.10),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        momentum = float(f.metadata.get("momentum_1m", f.metadata.get("return_5m", 0.0)) or 0.0)
        volume_z = float(f.metadata.get("volume_zscore", 0.0) or 0.0)
        if abs(momentum) < self.parameters.min_edge or volume_z < 0.5:
            return None
        side = "BUY" if momentum > 0 else "SELL"
        confidence = min(1.0, 0.55 + abs(momentum) * 3.0 + min(0.15, volume_z * 0.03))
        return self._signal(f, side, confidence, momentum, "Momentum breakout with volume confirmation")


class MicroScalpingStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="micro_scalping",
            name="Micro-Spread Scalping",
            parameters=parameters or StrategyParameters(min_edge=0.006, min_confidence=0.53, max_spread=0.04),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        queue_velocity = float(f.metadata.get("queue_velocity", 0.0) or 0.0)
        if f.spread <= 0.0 or abs(queue_velocity) < 0.20:
            return None
        side = "BUY" if queue_velocity > 0 else "SELL"
        edge = min(0.02, f.spread * 0.40)
        confidence = min(1.0, 0.53 + abs(queue_velocity) * 0.15)
        return self._signal(f, side, confidence, edge, "Intraminute queue velocity supports micro-spread scalp")


class SwingCatalystStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="swing_catalyst",
            name="Swing Catalyst Trading",
            parameters=parameters or StrategyParameters(min_edge=0.04, min_confidence=0.62, max_spread=0.12),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        catalyst_score = float(f.metadata.get("catalyst_score", 0.0) or 0.0)
        time_to_event_hours = float(f.metadata.get("time_to_event_hours", 999.0) or 999.0)
        if abs(catalyst_score) < 0.40 or time_to_event_hours < 1.0:
            return None
        edge = catalyst_score * 0.10
        side = "BUY" if edge > 0 else "SELL"
        confidence = min(1.0, 0.58 + abs(catalyst_score) * 0.25)
        return self._signal(f, side, confidence, edge, "Catalyst score supports multi-hour swing positioning")


class DirectionalConvictionStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="directional_conviction",
            name="Buy-and-Hold Directional Conviction",
            parameters=parameters or StrategyParameters(min_edge=0.06, min_confidence=0.68, max_spread=0.10),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        fundamental_prob = f.metadata.get("fundamental_probability")
        if fundamental_prob is None:
            return None
        edge = float(fundamental_prob) - f.price
        side = "BUY" if edge > 0 else "SELL"
        confidence = min(1.0, 0.60 + abs(edge) * 2.0)
        return self._signal(f, side, confidence, edge, "Fundamental probability diverges from market odds")


class ContrarianExcessStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="contrarian_excess",
            name="Contrarian Excess Reversal",
            parameters=parameters or StrategyParameters(min_edge=0.03, min_confidence=0.60, max_spread=0.12),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        crowding = float(f.metadata.get("crowding_score", 0.0) or 0.0)
        sentiment = f.sentiment_score
        if abs(crowding) < 0.70 or abs(sentiment) < 0.30:
            return None
        edge = -sentiment * min(0.12, abs(crowding) * 0.10)
        side = "BUY" if edge > 0 else "SELL"
        confidence = min(1.0, 0.56 + abs(crowding) * 0.18)
        return self._signal(f, side, confidence, edge, "Crowding and sentiment indicate consensus excess")


class IntraMarketArbitrageStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="intra_market_arbitrage",
            name="Intra-Market Outcome Sum Arbitrage",
            parameters=parameters or StrategyParameters(min_edge=0.015, min_confidence=0.60, max_spread=0.15),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        total_prob = f.metadata.get("outcome_total_probability")
        if total_prob is None:
            return None
        deviation = float(total_prob) - 1.0
        if abs(deviation) < self.parameters.min_edge:
            return None
        side = "SELL" if deviation > 0 else "BUY"
        confidence = min(1.0, 0.60 + abs(deviation) * 4.0)
        return self._signal(f, side, confidence, abs(deviation), "Mutually-exclusive outcomes do not sum to one")


class BundleSpreadArbitrageStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="bundle_spread_arbitrage",
            name="Bundle Spread Arbitrage",
            parameters=parameters or StrategyParameters(min_edge=0.018, min_confidence=0.61, max_spread=0.12),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        bundle_edge = float(f.metadata.get("bundle_locked_edge", 0.0) or 0.0)
        legging_risk = float(f.metadata.get("legging_risk", 1.0) or 1.0)
        if bundle_edge < self.parameters.min_edge or legging_risk > 0.35:
            return None
        return self._signal(f, "BUY", min(1.0, 0.62 + bundle_edge * 4.0), bundle_edge, "Positive bundle spread after legging-risk adjustment")


class PublicOracleLagStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="public_oracle_lag",
            name="Public Oracle / Off-Chain Lag",
            parameters=parameters or StrategyParameters(min_edge=0.025, min_confidence=0.65, max_spread=0.10),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        if not bool(f.metadata.get("public_source_confirmed", False)):
            return None
        oracle_prob = f.metadata.get("oracle_implied_probability")
        if oracle_prob is None:
            return None
        edge = float(oracle_prob) - f.price
        side = "BUY" if edge > 0 else "SELL"
        return self._signal(f, side, min(1.0, 0.65 + abs(edge) * 2.0), edge, "Public off-chain/oracle information is not fully reflected")


class NewsDrivenStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="news_driven",
            name="News-Driven Trading",
            parameters=parameters or StrategyParameters(min_edge=0.035, min_confidence=0.64, max_spread=0.12),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        news_score = float(f.metadata.get("news_score", 0.0) or 0.0)
        source_reliability = float(f.metadata.get("source_reliability", 0.0) or 0.0)
        if abs(news_score) < 0.35 or source_reliability < 0.60:
            return None
        edge = news_score * 0.10 * source_reliability
        side = "BUY" if edge > 0 else "SELL"
        return self._signal(f, side, min(1.0, 0.60 + source_reliability * 0.20), edge, "Reliable news catalyst changed event odds")


class CalendarEventStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="calendar_event",
            name="Event Calendar Trading",
            parameters=parameters or StrategyParameters(min_edge=0.025, min_confidence=0.58, max_spread=0.12),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        hours = float(f.metadata.get("hours_to_known_event", 999.0) or 999.0)
        expected_move = float(f.metadata.get("expected_event_move", 0.0) or 0.0)
        if not (0.0 < hours <= 72.0) or abs(expected_move) < self.parameters.min_edge:
            return None
        side = "BUY" if expected_move > 0 else "SELL"
        confidence = min(1.0, 0.56 + min(0.25, abs(expected_move) * 3.0))
        return self._signal(f, side, confidence, expected_move, "Known calendar catalyst has positive expected move")


class PublicOnchainFlowStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="public_onchain_flow",
            name="Public On-Chain Flow Following",
            parameters=parameters or StrategyParameters(min_edge=0.025, min_confidence=0.60, max_spread=0.10),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        whale_flow = float(f.metadata.get("known_wallet_flow_score", 0.0) or 0.0)
        if abs(whale_flow) < 0.40:
            return None
        edge = whale_flow * 0.08
        side = "BUY" if edge > 0 else "SELL"
        return self._signal(f, side, min(1.0, 0.58 + abs(whale_flow) * 0.20), edge, "Public wallet flow indicates informed demand")


class ExpectedValueStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="expected_value",
            name="Expected Value Betting",
            parameters=parameters or StrategyParameters(min_edge=0.025, min_confidence=0.58, max_spread=0.10),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        probability = f.ml_probability if f.ml_probability is not None else f.metadata.get("estimated_probability")
        if probability is None:
            return None
        edge = float(probability) - f.price
        ev = edge - float(f.metadata.get("fee_slippage_cost", f.spread) or 0.0)
        side = "BUY" if ev > 0 else "SELL"
        confidence = min(1.0, 0.55 + abs(ev) * 4.0)
        return self._signal(f, side, confidence, ev, "Positive expected value after fees and slippage", metadata={"estimated_probability": float(probability), "ev": ev})


class BayesianUpdateStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="bayesian_update",
            name="Bayesian Belief Updating",
            parameters=parameters or StrategyParameters(min_edge=0.025, min_confidence=0.59, max_spread=0.10),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        posterior = f.metadata.get("posterior_probability")
        if posterior is None:
            return None
        edge = float(posterior) - f.price
        side = "BUY" if edge > 0 else "SELL"
        confidence = min(1.0, 0.57 + abs(edge) * 3.0)
        return self._signal(f, side, confidence, edge, "Bayesian posterior diverges from market odds", metadata={"posterior_probability": float(posterior)})


class MonteCarloEdgeStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="monte_carlo_edge",
            name="Monte Carlo Scenario Edge",
            parameters=parameters or StrategyParameters(min_edge=0.03, min_confidence=0.60, max_spread=0.10),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        simulated_prob = f.metadata.get("monte_carlo_probability")
        tail_loss = float(f.metadata.get("simulated_tail_loss", 0.0) or 0.0)
        if simulated_prob is None or tail_loss > 0.25:
            return None
        edge = float(simulated_prob) - f.price
        side = "BUY" if edge > 0 else "SELL"
        return self._signal(f, side, min(1.0, 0.58 + abs(edge) * 3.5), edge, "Monte Carlo scenarios show positive risk-adjusted edge")


class PairsTradingStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="pairs_trading",
            name="Pairs Trading Between Correlated Markets",
            parameters=parameters or StrategyParameters(min_edge=0.025, min_confidence=0.60, max_spread=0.12),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        pair_z = float(f.metadata.get("pair_spread_zscore", 0.0) or 0.0)
        hedge_available = bool(f.metadata.get("hedge_market_available", False))
        if abs(pair_z) < 2.0 or not hedge_available:
            return None
        edge = min(0.12, abs(pair_z) * 0.015)
        side = "SELL" if pair_z > 0 else "BUY"
        return self._signal(f, side, min(1.0, 0.60 + min(0.20, abs(pair_z) * 0.04)), edge, "Correlated market pair spread is statistically stretched", metadata={"pair_spread_zscore": pair_z})


class OpportunisticLiquidityTakerStrategy(PolymarketStrategy):
    def __init__(self, parameters: StrategyParameters | None = None) -> None:
        super().__init__(
            strategy_id="opportunistic_liquidity_taker",
            name="Opportunistic Liquidity Taker",
            parameters=parameters or StrategyParameters(min_edge=0.05, min_confidence=0.70, max_spread=0.06),
        )

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        f = coerce_features(features)
        stale_quote_edge = float(f.metadata.get("stale_quote_edge", 0.0) or 0.0)
        available_depth = float(f.metadata.get("available_depth_usdc", 0.0) or 0.0)
        if abs(stale_quote_edge) < self.parameters.min_edge or available_depth <= 0:
            return None
        side = "BUY" if stale_quote_edge > 0 else "SELL"
        return self._signal(f, side, min(1.0, 0.70 + abs(stale_quote_edge)), stale_quote_edge, "Large edge justifies taker execution despite spread", order_type="MARKET")


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
        SwingCatalystStrategy(),
        DirectionalConvictionStrategy(),
        ContrarianExcessStrategy(),
        ExpectedValueStrategy(),
        BayesianUpdateStrategy(),
        MonteCarloEdgeStrategy(),
        PairsTradingStrategy(),
        OpportunisticLiquidityTakerStrategy(),
        Btc15MinuteFusionStrategy(),
    ]
