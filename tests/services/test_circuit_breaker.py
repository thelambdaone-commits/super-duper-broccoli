from __future__ import annotations


import pytest

from core.services.circuit_breaker import CircuitBreakerConfig, CircuitBreakerService, CircuitState


class DummyStorage:
    def __init__(self) -> None:
        self.saved_states: list[dict] = []

    def save_circuit_breaker_state(self, payload: dict) -> None:
        self.saved_states.append(dict(payload))


def test_closed_state_allows_signals() -> None:
    service = CircuitBreakerService(CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=10))

    assert service.state == CircuitState.CLOSED
    assert service.check_signal({"ticker": "SOL"}) is True
    assert service.is_allowed() is True


def test_opens_after_failure_threshold() -> None:
    storage = DummyStorage()
    service = CircuitBreakerService(
        CircuitBreakerConfig(failure_threshold=2, recovery_timeout_seconds=10, name="test"),
        storage_backend=storage,
    )

    service.record_failure("boom-1")
    assert service.state == CircuitState.CLOSED
    assert service.check_signal({"ticker": "SOL"}) is True

    service.record_failure("boom-2")
    assert service.state == CircuitState.OPEN
    assert service.check_signal({"ticker": "SOL"}) is False
    assert storage.saved_states[-1]["state"] == "OPEN"


def test_half_open_recovers_after_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    service = CircuitBreakerService(CircuitBreakerConfig(failure_threshold=1, recovery_timeout_seconds=5))
    service.record_failure("boom")
    assert service.state == CircuitState.OPEN

    monkeypatch.setattr("core.services.circuit_breaker.time.time", lambda: 100.0)
    service.last_failure_time = 90.0

    assert service.is_allowed() is True
    assert service.state == CircuitState.HALF_OPEN

    service.record_success()
    assert service.state == CircuitState.CLOSED
    assert service.failure_count == 0


def test_record_success_in_half_open_closes_circuit(monkeypatch: pytest.MonkeyPatch) -> None:
    service = CircuitBreakerService(CircuitBreakerConfig(failure_threshold=1, recovery_timeout_seconds=1))
    service.state = CircuitState.HALF_OPEN
    service.failure_count = 1
    service.record_success()

    assert service.state == CircuitState.CLOSED
    assert service.failure_count == 0
    assert service.check_signal({"ticker": "BTC"}) is True

