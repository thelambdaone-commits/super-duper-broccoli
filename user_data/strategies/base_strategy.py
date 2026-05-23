from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class MarketFeatures:
    market_id: str
    ticker: str
    price: float
    timestamp: float = field(default_factory=time.time)
    bid_price: float = 0.0
    ask_price: float = 0.0
    bid_volume: float = 0.0
    ask_volume: float = 0.0
    spread: float = 0.0
    order_imbalance: float = 0.0
    ml_probability: float | None = None
    hmm_regime: str = "UNKNOWN"
    sentiment_score: float = 0.0
    semantic_confidence: float = 0.0
    external_price: float | None = None
    correlated_price: float | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "MarketFeatures":
        ticker = str(payload.get("ticker") or payload.get("asset") or payload.get("market_id") or "UNKNOWN")
        market_id = str(payload.get("market_id") or payload.get("condition_id") or ticker)
        bid = _to_float(payload.get("bid_price") or payload.get("best_bid"), 0.0)
        ask = _to_float(payload.get("ask_price") or payload.get("best_ask"), 0.0)
        price = _to_float(payload.get("price") or payload.get("mid_price"), 0.0)
        if price <= 0.0 and bid > 0.0 and ask > 0.0:
            price = (bid + ask) / 2.0
        spread = _to_float(payload.get("spread"), 0.0)
        if spread <= 0.0 and bid > 0.0 and ask > 0.0:
            spread = max(0.0, ask - bid)
        return cls(
            market_id=market_id,
            ticker=ticker,
            price=price,
            timestamp=_to_float(payload.get("timestamp"), time.time()),
            bid_price=bid,
            ask_price=ask,
            bid_volume=_to_float(payload.get("bid_volume"), 0.0),
            ask_volume=_to_float(payload.get("ask_volume"), 0.0),
            spread=spread,
            order_imbalance=_to_float(payload.get("order_imbalance"), 0.0),
            ml_probability=_optional_float(payload.get("ml_probability") or payload.get("predictive_probability")),
            hmm_regime=str(payload.get("hmm_regime") or payload.get("regime_label") or "UNKNOWN"),
            sentiment_score=_to_float(payload.get("sentiment_score"), 0.0),
            semantic_confidence=_to_float(payload.get("semantic_confidence") or payload.get("confidence"), 0.0),
            external_price=_optional_float(payload.get("external_price")),
            correlated_price=_optional_float(payload.get("correlated_price")),
            metadata=dict(payload.get("metadata") or {}),
        )


@dataclass(frozen=True)
class StrategySignal:
    strategy_id: str
    market_id: str
    ticker: str
    side: str
    price: float
    confidence: float
    edge: float
    reason: str
    timestamp: float = field(default_factory=time.time)
    order_type: str = "LIMIT"
    suggested_capital: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_execution_signal(self) -> dict[str, Any]:
        return {
            "source": f"autonomous_strategy:{self.strategy_id}",
            "strategy_id": self.strategy_id,
            "asset": self.ticker,
            "ticker": self.ticker,
            "market_id": self.market_id,
            "action": self.side,
            "side": self.side,
            "price": self.price,
            "confidence": self.confidence,
            "predictive_edge": self.edge,
            "size": self.suggested_capital,
            "order_type": self.order_type,
            "reason": self.reason,
            "timestamp": self.timestamp,
            **self.metadata,
        }


@dataclass
class StrategyParameters:
    min_edge: float = 0.01
    min_confidence: float = 0.50
    max_spread: float = 0.15
    extra: dict[str, Any] = field(default_factory=dict)
    passive_spread_threshold: float = 0.015
    batch_size: int = 32


class BaseStrategy(Protocol):
    strategy_id: str
    name: str
    parameters: StrategyParameters

    def generate_signal(self, features: MarketFeatures | Mapping[str, Any]) -> StrategySignal | None:
        ...

    def update_parameters(self, updates: Mapping[str, float | int]) -> None:
        ...


def coerce_features(features: MarketFeatures | Mapping[str, Any]) -> MarketFeatures:
    if isinstance(features, MarketFeatures):
        return features
    return MarketFeatures.from_mapping(features)


def _to_float(value: Any, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if parsed != parsed:
        return default
    return parsed


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    parsed = _to_float(value, 0.0)
    return parsed
