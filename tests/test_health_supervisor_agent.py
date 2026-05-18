from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.health_supervisor_agent import HealthSupervisorAgent, HealthSupervisorConfig
from utils.feature_store import FeatureStore


@dataclass
class FakeLedger:
    total_capital: float = 100.0
    available_capital: float = 100.0

    def get_capital_summary(self) -> dict:
        return {
            "total_capital": self.total_capital,
            "available_capital": self.available_capital,
        }


@dataclass
class FakeWalletManager:
    balances: dict

    async def recuperer_soldes_on_chain(self, wallet_address: str, proxy_address: str = "") -> dict:
        return dict(self.balances)


@dataclass
class FakeArchiver:
    result: dict
    calls: int = 0

    def run_maintenance_cycle(self) -> dict:
        self.calls += 1
        return dict(self.result)


@dataclass
class FakeBroadcaster:
    diffuser_message_au_canal: AsyncMock


def _make_agent(tmp_path: Path, broadcaster: FakeBroadcaster, wallet_balances: dict, ledger_balance: float = 100.0) -> tuple[HealthSupervisorAgent, FeatureStore, FakeArchiver]:
    store = FeatureStore(db_path=str(tmp_path / "feature_store.duckdb"))
    ledger = FakeLedger(total_capital=ledger_balance, available_capital=ledger_balance)
    wallet_manager = FakeWalletManager(wallet_balances)
    archiver = FakeArchiver(
        result={
            "status": "OK",
            "disk_usage": {"feature_store": 1, "archive": 2, "logs": 3},
            "microstructure": {"status": "OK"},
            "logs": {"status": "OK"},
            "cleanup": {"status": "OK"},
        }
    )
    agent = HealthSupervisorAgent(
        feature_store=store,
        ledger=ledger,
        wallet_manager=wallet_manager,
        data_archiver=archiver,
        broadcaster=broadcaster,
        secrets={"POLYMARKET_WALLET_ADDRESS": "0x1111111111111111111111111111111111111111"},
        config=HealthSupervisorConfig(
            staleness_threshold_seconds=30.0,
            memory_warning_mb=512.0,
            memory_critical_mb=1024.0,
            wallet_reconciliation_interval_seconds=3600.0,
            maintenance_interval_seconds=86400.0,
            check_interval_seconds=1.0,
            wallet_drift_tolerance_usd=1.0,
            disk_usage_warning_bytes=10,
            disk_usage_critical_bytes=20,
        ),
    )
    return agent, store, archiver


@pytest.mark.asyncio
async def test_health_supervisor_detects_stale_stream_and_alerts(tmp_path: Path) -> None:
    broadcaster = FakeBroadcaster(diffuser_message_au_canal=AsyncMock(return_value=True))
    agent, store, _ = _make_agent(tmp_path, broadcaster, wallet_balances={"usdc_balance": 100.0})
    stale_ts = time.time() - 120.0
    store.record_web_event("clob", "tick", {"foo": "bar"}, timestamp=stale_ts)

    result = await agent.check_stream_staleness(time.time())

    assert result["status"] == "CRITICAL"
    broadcaster.diffuser_message_au_canal.assert_awaited()


@pytest.mark.asyncio
async def test_health_supervisor_memory_warning(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    broadcaster = FakeBroadcaster(diffuser_message_au_canal=AsyncMock(return_value=True))
    agent, _, _ = _make_agent(tmp_path, broadcaster, wallet_balances={"usdc_balance": 100.0})

    monkeypatch.setattr("core.health_supervisor_agent._read_process_rss_mb", lambda: 2 * 1024.0)

    result = await agent.check_memory_usage()

    assert result["status"] == "CRITICAL"


@pytest.mark.asyncio
async def test_health_supervisor_wallet_reconciliation_reports_drift(tmp_path: Path) -> None:
    broadcaster = FakeBroadcaster(diffuser_message_au_canal=AsyncMock(return_value=True))
    agent, _, _ = _make_agent(tmp_path, broadcaster, wallet_balances={"usdc_balance": 40.0})

    result = await agent.reconcile_wallet_balances()

    assert result["status"] == "WARNING"
    assert result["drift_usd"] == pytest.approx(60.0)
    broadcaster.diffuser_message_au_canal.assert_awaited()


@pytest.mark.asyncio
async def test_health_supervisor_maintenance_cycle_runs_archiver(tmp_path: Path) -> None:
    broadcaster = FakeBroadcaster(diffuser_message_au_canal=AsyncMock(return_value=True))
    agent, _, archiver = _make_agent(tmp_path, broadcaster, wallet_balances={"usdc_balance": 100.0})

    result = await agent.run_maintenance_cycle()

    assert archiver.calls == 1
    assert result["check"] == "maintenance"
    assert result["status"] in {"OK", "WARNING", "CRITICAL"}
