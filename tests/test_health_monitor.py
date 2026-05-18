from __future__ import annotations

import asyncio
from unittest.mock import MagicMock
import httpx
import pytest
from core.health_monitor import LobstarHealthMonitor, app


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


@pytest.mark.asyncio
async def test_health_monitor_endpoints_when_components_are_up() -> None:
    orchestrator = FakeOrchestrator(queue_done=False)
    runner = FakeRunner(running=True)

    monitor = LobstarHealthMonitor(orchestrator, runner, port=8089)
    monitor.start()

    try:
        # Simulate a direct client request using FastAPI's TestClient style or mock http
        from fastapi.testclient import TestClient
        client = TestClient(app)
        
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "UP"
        assert data["components"]["orchestrator"] == "UP"
        assert data["components"]["quantum_runner"] == "UP"

        response_live = client.get("/liveness")
        assert response_live.status_code == 200
        assert response_live.json()["status"] == "UP"

    finally:
        await monitor.stop()


@pytest.mark.asyncio
async def test_health_monitor_endpoints_when_orchestrator_is_down() -> None:
    orchestrator = FakeOrchestrator(queue_done=True) # Work task completed/failed
    runner = FakeRunner(running=True)

    monitor = LobstarHealthMonitor(orchestrator, runner, port=8090)
    monitor.start()

    try:
        from fastapi.testclient import TestClient
        client = TestClient(app)
        
        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "DOWN"
        assert data["components"]["orchestrator"] == "DOWN"
        assert data["components"]["quantum_runner"] == "UP"

    finally:
        await monitor.stop()


@pytest.mark.asyncio
async def test_health_monitor_endpoints_when_runner_is_down() -> None:
    orchestrator = FakeOrchestrator(queue_done=False)
    runner = FakeRunner(running=False) # Not running

    monitor = LobstarHealthMonitor(orchestrator, runner, port=8091)
    monitor.start()

    try:
        from fastapi.testclient import TestClient
        client = TestClient(app)
        
        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "DOWN"
        assert data["components"]["orchestrator"] == "UP"
        assert data["components"]["quantum_runner"] == "DOWN"

    finally:
        await monitor.stop()


@pytest.mark.asyncio
async def test_health_monitor_endpoints_when_missing_references() -> None:
    monitor = LobstarHealthMonitor(None, None, port=8092)
    monitor.start()

    try:
        from fastapi.testclient import TestClient
        client = TestClient(app)
        
        response = client.get("/health")
        assert response.status_code == 503
        data = response.json()
        assert data["status"] == "DOWN"
        assert data["components"]["orchestrator"] == "DOWN"
        assert data["components"]["quantum_runner"] == "DOWN"

    finally:
        await monitor.stop()
