from __future__ import annotations

import asyncio
import contextlib

import pytest

from core.quantum_runner import LobstarQuantumRunner


class StubGovernor:
    def __init__(self, *, multiplier: float = 1.0, skip_heavy: bool = False) -> None:
        self.multiplier = multiplier
        self.skip_heavy = skip_heavy

    def sample_if_due(self, *, force: bool = False):
        return None

    def interval_multiplier(self, profile: str) -> float:
        return self.multiplier if profile == "heavy" else 1.0

    def should_skip_job(self, profile: str) -> bool:
        return self.skip_heavy and profile == "heavy"


@pytest.mark.asyncio
async def test_quantum_runner_skips_heavy_jobs_in_critical_mode() -> None:
    runner = LobstarQuantumRunner()
    runner.resource_governor = StubGovernor(skip_heavy=True)

    calls: list[str] = []

    async def _heavy() -> None:
        calls.append("heavy")

    runner.register_job("heavy_job", _heavy, interval_sec=0.01, resource_profile="heavy")
    runner._is_running = True

    task = asyncio.create_task(runner.start())
    await asyncio.sleep(0.05)
    runner.stop()
    await asyncio.sleep(0.02)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task

    assert calls == []


@pytest.mark.asyncio
async def test_quantum_runner_stretches_heavy_job_interval() -> None:
    runner = LobstarQuantumRunner()
    runner.resource_governor = StubGovernor(multiplier=5.0, skip_heavy=False)

    async def _noop() -> None:
        return None

    runner.register_job("heavy_job", _noop, interval_sec=2.0, resource_profile="heavy")
    job = runner.jobs[0]
    job.last_run = 0.0

    original_sleep = asyncio.sleep

    async def _fast_sleep(_delay: float) -> None:
        runner.stop()
        await original_sleep(0)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr("core.quantum_runner.asyncio.sleep", _fast_sleep)
    monkeypatch.setattr("core.quantum_runner.time.monotonic", lambda: 3.0)
    try:
        await runner.start()
    finally:
        monkeypatch.undo()

    assert job.interval == 10.0


def test_quantum_runner_reports_job_stats() -> None:
    runner = LobstarQuantumRunner()

    async def _noop() -> None:
        return None

    runner.register_job("profiled_job", _noop, interval_sec=2.0, resource_profile="heavy")
    job = runner.jobs[0]
    job.stats.run_count = 3
    job.stats.success_count = 2
    job.stats.error_count = 1
    job.stats.skip_count = 4
    job.stats.total_duration_ms = 30.0
    job.stats.last_duration_ms = 12.5
    job.stats.max_duration_ms = 17.5

    stats = runner.get_job_stats()

    assert stats["profiled_job"]["resource_profile"] == "heavy"
    assert stats["profiled_job"]["run_count"] == 3
    assert stats["profiled_job"]["success_count"] == 2
    assert stats["profiled_job"]["error_count"] == 1
    assert stats["profiled_job"]["skip_count"] == 4
    assert stats["profiled_job"]["avg_duration_ms"] == 15.0
