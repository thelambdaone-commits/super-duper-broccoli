from __future__ import annotations

from typing import Any

from core.container import ServiceContainer
from core.services.circuit_breaker import CircuitBreakerService
from core.training_pipeline import TrainingPipeline
from utils.model_validator import ModelValidator
from utils.snapshot_manager import get_snapshot_manager
from utils.market_scanner import MarketScanner
from ai.agents.self_improvement_agent import SelfImprovementAgent


def build_runtime_services(container: ServiceContainer, execution_mode: str) -> dict[str, Any]:
    ledger = container.ledger
    freqai = container.freqai
    hmm = container.hmm
    risk = container.risk
    store = container.store
    notifier = container.notifier
    passive_executor = container.executor
    secrets = container.secrets

    circuit_breaker = CircuitBreakerService({"name": "CLOB_Execution"})
    training_pipeline = TrainingPipeline(
        store=store,
        retrain_interval_hours=24,
        min_train_samples=50,
        validation_split=0.2,
    )
    market_scanner = MarketScanner()
    snapshot_mgr = get_snapshot_manager()
    model_validator = ModelValidator(snapshot_manager=snapshot_mgr)
    self_improver = SelfImprovementAgent()
    return {
        "ledger": ledger,
        "freqai": freqai,
        "hmm": hmm,
        "risk": risk,
        "store": store,
        "notifier": notifier,
        "passive_executor": passive_executor,
        "secrets": secrets,
        "circuit_breaker": circuit_breaker,
        "market_scanner": market_scanner,
        "training_pipeline": training_pipeline,
        "snapshot_mgr": snapshot_mgr,
        "model_validator": model_validator,
        "self_improver": self_improver,
    }
