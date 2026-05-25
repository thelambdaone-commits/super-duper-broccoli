"""Compatibility re-exports for legacy ``core.services`` imports."""

from services.circuit_breaker import CircuitBreakerConfig, CircuitBreakerService
from services.predictive_gate import PredictiveGateConfig, PredictiveGateService
from services.signal_router import SignalRouter
from services.trade_notification_service import TradeNotificationService

__all__ = [
    "CircuitBreakerConfig",
    "CircuitBreakerService",
    "PredictiveGateConfig",
    "PredictiveGateService",
    "SignalRouter",
    "TradeNotificationService",
]
