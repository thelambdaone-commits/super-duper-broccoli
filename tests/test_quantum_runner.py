import asyncio
import pytest
from core.quantum_runner import LobstarQuantumRunner
from core.arbitrage_feedback_loop import LobstarArbitrageEngine
from core.mlops_feedback_loop import LobstarMLOpsEngine
from polymarket.execution.freqai_engine import FreqAIEngine


@pytest.mark.asyncio
async def test_quantum_job_registration():
    """Verify jobs register properly in the scheduler."""
    runner = LobstarQuantumRunner()

    async def dummy_callback():
        pass

    runner.enregistrer_job("Test_Job_1", dummy_callback, interval_sec=1.5)

    assert len(runner.jobs) == 1
    job = runner.jobs[0]
    assert job.name == "Test_Job_1"
    assert job.interval == 1.5
    assert job.callback == dummy_callback
    assert job.last_run == 0.0


@pytest.mark.asyncio
async def test_quantum_runner_tick_execution():
    """Verify that the quantum runner executes scheduled jobs periodically and updates last_run."""
    runner = LobstarQuantumRunner()
    runner.montre_interne_tick_rate = 0.005  # Faster tick rate for unit tests (5ms)

    execution_count = 0

    async def increment_callback():
        nonlocal execution_count
        execution_count += 1

    # Register a job with 10ms interval
    runner.enregistrer_job("Quick_Job", increment_callback, interval_sec=0.01)

    # Start the runner as a background task
    runner_task = asyncio.create_task(runner.start())

    # Wait for a short duration to let it tick a few times
    await asyncio.sleep(0.05)

    # Stop the runner
    runner.stop()
    await runner_task

    # Ensure it ticked and executed the callback multiple times
    assert execution_count > 0
    assert runner.jobs[0].last_run > 0.0


@pytest.mark.asyncio
async def test_quantum_runner_error_isolation():
    """Verify that a failing job does not interrupt or crash other concurrent jobs."""
    runner = LobstarQuantumRunner()
    runner.montre_interne_tick_rate = 0.005  # 5ms tick resolution

    healthy_executions = 0
    failing_executions = 0

    async def healthy_callback():
        nonlocal healthy_executions
        healthy_executions += 1

    async def crashing_callback():
        nonlocal failing_executions
        failing_executions += 1
        raise ValueError("Simulated network/API timeout failure in job callback")

    runner.enregistrer_job("Healthy_Job", healthy_callback, interval_sec=0.01)
    runner.enregistrer_job("Crashing_Job", crashing_callback, interval_sec=0.01)

    runner_task = asyncio.create_task(runner.start())

    # Let both run for a short duration
    await asyncio.sleep(0.05)

    runner.stop()
    await runner_task

    # Verify both jobs were triggered, and the crash of one didn't block the other or crash the loop
    assert healthy_executions > 0
    assert failing_executions > 0
    assert not runner._is_running


@pytest.mark.asyncio
async def test_engine_callbacks_callable():
    """Verify that the multiscale paths on the real engines exist and are callable as async methods."""
    # 1. FreqAIEngine stream_ticks_to_duckdb
    # Dummy credentials to construct FreqAIEngine safely
    freqai = FreqAIEngine(
        private_key="0x68fa799c110cea4880de05e62368b945b37589780627e1b40f0b0e2634a6b2ac",
        api_key="019e3418-a35a-72e6-b9c0-7bbd76a6567c",
        api_secret="PS_GZ1ZHBW1Fe2j_UeIYWikrKKyoZCzen2Hc22WtbK8=",
        api_passphrase="45033dc49ad13ccb4376090974f27bd6c391b6b70622844c3bb1b42a6dbd920",
    )
    assert hasattr(freqai, "stream_ticks_to_duckdb")
    await freqai.stream_ticks_to_duckdb()

    # 2. LobstarArbitrageEngine scanner_anomalies
    arb = LobstarArbitrageEngine()
    assert hasattr(arb, "scanner_anomalies")
    await arb.scanner_anomalies()

    # 3. LobstarMLOpsEngine analyser_sante_brain
    mlops = LobstarMLOpsEngine()
    assert hasattr(mlops, "analyser_sante_brain")
    await mlops.analyser_sante_brain()
