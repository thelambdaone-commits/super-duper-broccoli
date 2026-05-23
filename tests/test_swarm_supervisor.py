from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core import swarm_supervisor as swarm_module
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


def test_paper_ticks_persist_and_reload(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "swarm_state.json"
    monkeypatch.setattr(swarm_module, "SWARM_STATE_PATH", state_path)

    supervisor = RufloSwarmSupervisor(mode="PAPER")
    supervisor._paper_ticks = 12
    supervisor._persist_state()

    reloaded = RufloSwarmSupervisor(mode="PAPER")

    assert reloaded.paper_ticks == 12


@pytest.mark.asyncio
async def test_record_market_tick_counts_only_meaningful_changes(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "swarm_state.json"
    monkeypatch.setattr(swarm_module, "SWARM_STATE_PATH", state_path)
    supervisor = RufloSwarmSupervisor(mode="PAPER")

    first = await supervisor.record_market_tick({"token_id": "t1", "best_bid": 0.45, "best_ask": 0.47, "mid_price": 0.46})
    second = await supervisor.record_market_tick({"token_id": "t1", "best_bid": 0.45, "best_ask": 0.47, "mid_price": 0.46})
    third = await supervisor.record_market_tick({"token_id": "t1", "best_bid": 0.46, "best_ask": 0.48, "mid_price": 0.47})

    assert first is True
    assert second is False
    assert third is True
    assert supervisor.paper_ticks == 2


def test_warm_start_from_csv_replay(tmp_path: Path, monkeypatch) -> None:
    state_path = tmp_path / "swarm_state.json"
    replay_path = tmp_path / "replay.csv"
    replay_path.write_text(
        "token_id,best_bid,best_ask,mid_price\n"
        "t1,0.45,0.47,0.46\n"
        "t1,0.45,0.47,0.46\n"
        "t1,0.46,0.48,0.47\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(swarm_module, "SWARM_STATE_PATH", state_path)

    supervisor = RufloSwarmSupervisor(mode="PAPER")
    added = supervisor.warm_start_from_replay(replay_path)

    assert added == 2
    assert supervisor.paper_ticks == 2
