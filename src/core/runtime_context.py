from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RuntimeContext:
    notifier: Any
    secrets: dict[str, str]
    access_control: Any
    chat_id: int | None
    ledger: Any
    freqai: Any
    hmm: Any
    risk: Any
    store: Any
    passive_executor: Any
    lobstar: Any
    circuit_breaker: Any
    market_scanner: Any
    cognitive_brain: Any
    copy_trading_agent: Any
    training_pipeline: Any
    snapshot_mgr: Any
    model_validator: Any
    self_improver: Any
