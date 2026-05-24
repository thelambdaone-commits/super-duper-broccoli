from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("CircuitBreakerService")


class CircuitState(Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


@dataclass
class CircuitBreakerConfig:
    failure_threshold: int = 5
    recovery_timeout_seconds: int = 300
    name: str = "Global"


class CircuitBreakerService:
    """
    Stateful circuit breaker with explicit half-open recovery semantics.

    The service keeps the execution policy local and exposes a small interface
    that can later be backed by Redis or another storage backend without
    changing orchestrator code.
    """

    def __init__(self, config: dict | CircuitBreakerConfig | None = None, storage_backend: Any = None):
        if config is None:
            config = CircuitBreakerConfig()
        elif isinstance(config, dict):
            config = CircuitBreakerConfig(
                failure_threshold=int(config.get("failure_threshold", 5)),
                recovery_timeout_seconds=int(config.get("recovery_timeout_seconds", 300)),
                name=str(config.get("name", "Global")),
            )
        self.config = config
        self.storage_backend = storage_backend
        self._is_tripped = False
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time: Optional[float] = None

    def check_signal(self, signal: Any) -> bool:
        """Return True when the signal is allowed to proceed."""
        del signal
        return self.is_allowed()

    def record_failure(self, error: Any = "") -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        self._persist_state()
        logger.warning(
            "CircuitBreaker[%s]: Failure recorded (%s/%s). Error: %s",
            self.config.name,
            self.failure_count,
            self.config.failure_threshold,
            error,
        )

        if self.failure_count >= self.config.failure_threshold:
            self._open_circuit()

    def record_success(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            logger.info("CircuitBreaker[%s]: Success in HALF_OPEN, closing circuit.", self.config.name)
            self._close_circuit()
        self.failure_count = 0
        self._is_tripped = False
        self._persist_state()

    def is_allowed(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True

        if self.state == CircuitState.OPEN:
            elapsed = time.time() - (self.last_failure_time or 0)
            if elapsed >= self.config.recovery_timeout_seconds:
                logger.info(
                    "CircuitBreaker[%s]: Recovery timeout elapsed, switching to HALF_OPEN.",
                    self.config.name,
                )
                self.state = CircuitState.HALF_OPEN
                self._is_tripped = False
                self._persist_state()
                return True
            return False

        return True

    def _open_circuit(self) -> None:
        if self.state != CircuitState.OPEN:
            self.state = CircuitState.OPEN
            self._is_tripped = True
            self._persist_state()
            logger.critical(
                "CircuitBreaker[%s]: CIRCUIT OPENED! Execution blocked for %ss.",
                self.config.name,
                self.config.recovery_timeout_seconds,
            )

    def _close_circuit(self) -> None:
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self._is_tripped = False
        self._persist_state()
        logger.info("CircuitBreaker[%s]: Circuit closed. Resuming normal operations.", self.config.name)

    def _persist_state(self) -> None:
        if self.storage_backend is None:
            return
        try:
            self.storage_backend.save_circuit_breaker_state(
                {
                    "state": self.state.value,
                    "failure_count": self.failure_count,
                    "last_failure_time": self.last_failure_time,
                    "is_tripped": self._is_tripped,
                    "name": self.config.name,
                }
            )
        except Exception as exc:
            logger.debug("CircuitBreaker[%s]: persistence skipped: %s", self.config.name, exc)

    @property
    def status_report(self) -> str:
        return f"State: {self.state.value} | Failures: {self.failure_count}/{self.config.failure_threshold}"

