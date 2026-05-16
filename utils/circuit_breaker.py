import logging
import time
from enum import Enum
from typing import Optional

logger = logging.getLogger("CircuitBreaker")

class CircuitState(Enum):
    CLOSED = "CLOSED"  # Normal operation
    OPEN = "OPEN"      # Blocked
    HALF_OPEN = "HALF_OPEN" # Testing recovery

class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout_seconds: int = 300,
        name: str = "Global",
    ) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout_seconds
        self.failure_count = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time: Optional[float] = None

    def record_failure(self, error: str = "") -> None:
        self.failure_count += 1
        self.last_failure_time = time.time()
        logger.warning(f"CircuitBreaker[{self.name}]: Failure recorded ({self.failure_count}/{self.failure_threshold}). Error: {error}")
        
        if self.failure_count >= self.failure_threshold:
            self._open_circuit()

    def record_success(self) -> None:
        if self.state == CircuitState.HALF_OPEN:
            logger.info(f"CircuitBreaker[{self.name}]: Success in HALF_OPEN, closing circuit.")
            self._close_circuit()
        self.failure_count = 0

    def is_allowed(self) -> bool:
        if self.state == CircuitState.CLOSED:
            return True
            
        if self.state == CircuitState.OPEN:
            elapsed = time.time() - (self.last_failure_time or 0)
            if elapsed >= self.recovery_timeout:
                logger.info(f"CircuitBreaker[{self.name}]: Recovery timeout elapsed, switching to HALF_OPEN.")
                self.state = CircuitState.HALF_OPEN
                return True
            return False
            
        return True # HALF_OPEN allows one trial

    def _open_circuit(self) -> None:
        if self.state != CircuitState.OPEN:
            self.state = CircuitState.OPEN
            logger.critical(f"CircuitBreaker[{self.name}]: CIRCUIT OPENED! Execution blocked for {self.recovery_timeout}s.")

    def _close_circuit(self) -> None:
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        logger.info(f"CircuitBreaker[{self.name}]: Circuit closed. Resuming normal operations.")

    @property
    def status_report(self) -> str:
        return f"State: {self.state.value} | Failures: {self.failure_count}/{self.failure_threshold}"
