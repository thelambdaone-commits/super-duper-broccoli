from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, AsyncMock
import pytest
from agents.health_monitor_agent import HealthMonitorAgent, HealthMonitorConfig


class FakeFeatureStore:
    def __init__(self):
        self.pruned_ts = None
        self.vacuum_calls = 0

    def prune_before(self, cutoff_ts: float) -> int:
        self.pruned_ts = cutoff_ts
        return 42

    def vacuum(self) -> None:
        self.vacuum_calls += 1


class FakeLedger:
    def __init__(self, summary: dict):
        self.summary = summary

    def get_capital_summary(self) -> dict:
        return self.summary


class FakeBroadcaster:
    def __init__(self):
        self.diffuser_alerte_risque_au_canal = AsyncMock(return_value=True)


def test_health_monitor_agent_init() -> None:
    agent = HealthMonitorAgent()
    assert isinstance(agent.config, HealthMonitorConfig)
    assert agent.config.max_memory_rss_mb == 2048.0
    assert agent.config.enable_ledger_reconciliation is True
    assert agent.healer is not None


def test_health_monitor_agent_dict_config() -> None:
    config_dict = {
        "heartbeat_interval_seconds": 15.0,
        "max_memory_rss_mb": 512.0,
        "enable_ledger_reconciliation": False,
    }
    agent = HealthMonitorAgent(config=config_dict)
    assert agent.config.heartbeat_interval_seconds == 15.0
    assert agent.config.max_memory_rss_mb == 512.0
    assert agent.config.enable_ledger_reconciliation is False


@pytest.mark.asyncio
async def test_health_monitor_emit_heartbeat() -> None:
    agent = HealthMonitorAgent()
    hb = await agent.emit_heartbeat()
    assert hb["status"] == "ok"
    assert "timestamp" in hb
    assert hb["pid"] > 0


@pytest.mark.asyncio
async def test_health_monitor_maintain_feature_store() -> None:
    store = FakeFeatureStore()
    agent = HealthMonitorAgent(feature_store=store)

    res = await agent.maintain_feature_store()
    assert res["status"] == "ok"
    assert res["removed"] == 42
    assert store.pruned_ts is not None
    assert store.vacuum_calls == 1


@pytest.mark.asyncio
async def test_health_monitor_reconcile_ledger() -> None:
    ledger = FakeLedger({"available_capital": 1000.0})
    agent = HealthMonitorAgent(ledger=ledger)

    res = await agent.reconcile_ledger()
    assert res["status"] == "ok"
    assert res["capital_summary"]["available_capital"] == 1000.0


@pytest.mark.asyncio
async def test_health_monitor_check_memory_under_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = HealthMonitorAgent(config=HealthMonitorConfig(max_memory_rss_mb=100.0))

    # Mock psutil memory rss to be 50MB (well under 100MB limit)
    class FakeMemoryInfo:
        rss = 50.0 * 1024.0 * 1024.0

    class FakeProcess:
        def __init__(self, pid):
            pass
        def memory_info(self):
            return FakeMemoryInfo()

    import psutil
    monkeypatch.setattr(psutil, "Process", FakeProcess)

    res = await agent.check_memory()
    assert res["status"] == "ok"
    assert res["rss_mb"] == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_health_monitor_check_memory_over_limit_triggers_gc(monkeypatch: pytest.MonkeyPatch) -> None:
    agent = HealthMonitorAgent(config=HealthMonitorConfig(max_memory_rss_mb=100.0))

    # Mock psutil memory rss to be 150MB (over 100MB limit)
    class FakeMemoryInfo:
        rss = 150.0 * 1024.0 * 1024.0

    class FakeProcess:
        def __init__(self, pid):
            pass
        def memory_info(self):
            return FakeMemoryInfo()

    import psutil
    monkeypatch.setattr(psutil, "Process", FakeProcess)

    # Mock healer repair call
    agent.healer._repair_memory_leak = MagicMock(return_value={"statut": "REPAIRED"})

    res = await agent.check_memory()
    assert res["status"] == "warn"
    assert res["rss_mb"] == pytest.approx(150.0)
    agent.healer._repair_memory_leak.assert_called_once()


@pytest.mark.asyncio
async def test_health_monitor_run_once() -> None:
    store = FakeFeatureStore()
    ledger = FakeLedger({"available_capital": 100.0})
    agent = HealthMonitorAgent(feature_store=store, ledger=ledger)

    res = await agent.run_once()
    assert "heartbeat" in res
    assert "memory" in res
    assert "ledger" in res
    assert "feature_store" in res
    assert res["feature_store"]["status"] == "ok"


@pytest.mark.asyncio
async def test_health_monitor_run_forever_graceful_cancel() -> None:
    agent = HealthMonitorAgent()

    # We execute run_forever but cancel it right away
    task = asyncio.create_task(agent.run_forever(poll_interval=0.01))
    await asyncio.sleep(0.02)
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    assert task.done()
