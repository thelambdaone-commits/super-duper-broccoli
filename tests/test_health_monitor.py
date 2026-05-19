from __future__ import annotations

import asyncio
import json
from unittest.mock import MagicMock
import pytest
import core.health_monitor as health_monitor
from core.health_monitor import LobstarHealthMonitor


class FakeTask:
    def __init__(self, done: bool = False):
        self._done = done

    def done(self) -> bool:
        return self._done


class FakeOrchestrator:
    def __init__(self, queue_done: bool = False):
        self._queue_worker_task = FakeTask(done=queue_done)


class FakeRunner:
    def __init__(self, running: bool = True):
        self._is_running = running


def test_health_monitor_endpoints_when_components_are_up() -> None:
    orchestrator = FakeOrchestrator(queue_done=False)
    runner = FakeRunner(running=True)
    health_monitor._orchestrator = orchestrator
    health_monitor._runner = runner

    response = health_monitor.get_liveness()
    assert response["status"] == "UP"
    assert response["components"]["orchestrator"] == "UP"
    assert response["components"]["quantum_runner"] == "UP"


def test_health_monitor_endpoints_when_orchestrator_is_down() -> None:
    orchestrator = FakeOrchestrator(queue_done=True) # Work task completed/failed
    runner = FakeRunner(running=True)
    health_monitor._orchestrator = orchestrator
    health_monitor._runner = runner

    response = health_monitor.get_liveness()
    assert response.status_code == 503
    data = json.loads(response.body)
    assert data["status"] == "DOWN"
    assert data["components"]["orchestrator"] == "DOWN"
    assert data["components"]["quantum_runner"] == "UP"


def test_health_monitor_endpoints_when_runner_is_down() -> None:
    orchestrator = FakeOrchestrator(queue_done=False)
    runner = FakeRunner(running=False) # Not running
    health_monitor._orchestrator = orchestrator
    health_monitor._runner = runner

    response = health_monitor.get_liveness()
    assert response.status_code == 503
    data = json.loads(response.body)
    assert data["status"] == "DOWN"
    assert data["components"]["orchestrator"] == "UP"
    assert data["components"]["quantum_runner"] == "DOWN"


def test_health_monitor_endpoints_when_missing_references() -> None:
    health_monitor._orchestrator = None
    health_monitor._runner = None

    response = health_monitor.get_liveness()
    assert response.status_code == 503
    data = json.loads(response.body)
    assert data["status"] == "DOWN"
    assert data["components"]["orchestrator"] == "DOWN"
    assert data["components"]["quantum_runner"] == "DOWN"
