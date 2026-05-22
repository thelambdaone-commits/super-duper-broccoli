from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from core.swarm_supervisor import RufloSwarmSupervisor


@pytest.mark.asyncio
async def test_start_and_stop_monitoring_flip_running_state() -> None:
    supervisor = RufloSwarmSupervisor(mode="PAPER")
    supervisor._monitoring_loop = AsyncMock()
    supervisor._redis = None

    await supervisor.start_monitoring()

    assert supervisor._running is True
    assert supervisor._monitoring_task is not None

    await supervisor.stop_monitoring()

    assert supervisor._running is False


@pytest.mark.asyncio
async def test_safe_retrain_isolated_from_failures() -> None:
    supervisor = RufloSwarmSupervisor(mode="PAPER")
    supervisor._last_retrain_time = 0.0

    class _BrokenRetrain:
        async def trigger_retraining(self):
            raise RuntimeError("boom")

    supervisor.register_agent("retrain", _BrokenRetrain())

    await supervisor._safe_trigger_retrain()

    assert supervisor._last_retrain_time > 0.0
