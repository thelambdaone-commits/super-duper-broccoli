from __future__ import annotations

from types import SimpleNamespace

import pytest

from bootstrap import scheduler as scheduler_module


@pytest.mark.asyncio
async def test_setup_quantum_runner_keeps_swarm_init_task_reference(monkeypatch) -> None:
    started = {}

    async def _fake_initialize_swarm_supervisor(mode: str = "PAPER"):
        started["mode"] = mode
        return SimpleNamespace(mode=mode)

    monkeypatch.setattr(
        "core.swarm_supervisor.initialize_swarm_supervisor",
        _fake_initialize_swarm_supervisor,
    )

    runner = SimpleNamespace(register_job=lambda *args, **kwargs: None)
    ledger = SimpleNamespace(get_execution_mode=lambda: "PAPER")
    freqai = SimpleNamespace(stream_ticks_to_duckdb=lambda: None)
    cognitive_brain = SimpleNamespace(arbitrage_engine=None)
    mlops_engine = SimpleNamespace(analyser_sante_brain=lambda: None, should_prune=lambda **kwargs: False)
    autonomic_healer = SimpleNamespace(log_path="logs/healer.log", analyser_nouveaux_logs=lambda: [], deployer_correctif_autonome=lambda err: None)
    broadcaster = SimpleNamespace(notifier=None)

    scheduler_module._setup_quantum_runner(
        runner=runner,
        freqai=freqai,
        cognitive_brain=cognitive_brain,
        mlops_engine=mlops_engine,
        autonomic_healer=autonomic_healer,
        broadcaster=broadcaster,
        ledger=ledger,
    )

    assert hasattr(runner, "_swarm_init_task")
    await runner._swarm_init_task
    assert started["mode"] == "PAPER"
