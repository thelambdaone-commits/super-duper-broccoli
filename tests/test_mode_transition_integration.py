from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.autonomous_mode_controller import AutonomousModeConfig, AutonomousModeController
from core.autonomous_trading_loop import AutonomousTradingConfig, AutonomousTradingLoop
from core.swarm import supervisor as swarm_impl
from core.strategy_lifecycle_manager import StrategyLifecycleConfig, StrategyLifecycleManager, StrategyPhase
from core.swarm_supervisor import get_swarm_supervisor
from database.ledger_db import Ledger
from strategies.base_strategy import StrategySignal
from strategies.polymarket_strategy_factory import MeanReversionStrategy


def _ledger(tmp_path):
    ledger = Ledger(db_path=str(tmp_path / "integration_mode.db"))
    ledger.conn.execute("DELETE FROM capital_allocation")
    ledger.conn.execute(
        "INSERT INTO capital_allocation (total_capital, available_capital, allocated_pct) VALUES (1000, 1000, 10)"
    )
    ledger.conn.commit()
    return ledger


def _lifecycle(tmp_path):
    return StrategyLifecycleManager(
        strategies=[MeanReversionStrategy()],
        config=StrategyLifecycleConfig(
            dashboard_path=str(tmp_path / "dashboard.md"),
            state_path=str(tmp_path / "state.json"),
        ),
    )


def _record_closed_paper(ledger: Ledger, wins: int, losses: int) -> None:
    for _ in range(wins):
        result = ledger.record_paper_order("MKT", "BUY", 0.50, 10, signal_source="integration")
        ledger.close_paper_position(result["position_id"], exit_price=0.70, pnl=2.0, is_win=True)
    for _ in range(losses):
        result = ledger.record_paper_order("MKT", "BUY", 0.50, 10, signal_source="integration")
        ledger.close_paper_position(result["position_id"], exit_price=0.40, pnl=-1.0, is_win=False)


def _signal() -> StrategySignal:
    return StrategySignal(
        strategy_id="mean_reversion",
        market_id="btc-updown-5m-demo",
        ticker="BTC-UP",
        side="BUY",
        price=0.45,
        confidence=0.72,
        edge=0.08,
        reason="integration test signal",
    )


@pytest.mark.asyncio
async def test_ledger_mode_transition_controls_execution_path(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_REAL_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("REAL", "true")

    ledger = _ledger(tmp_path)
    lifecycle = _lifecycle(tmp_path)
    monkeypatch.setattr(swarm_impl, "_supervisor_instance", None)
    controller = AutonomousModeController(
        ledger,
        lifecycle,
        AutonomousModeConfig(min_paper_trades_for_shadow=3, min_paper_trades_for_real=8),
    )
    swarm = get_swarm_supervisor()
    swarm.sync_execution_mode("PAPER")

    # First promotion: profitable paper history promotes to SHADOW only.
    lifecycle.states["mean_reversion"].phase = StrategyPhase.SANITY
    _record_closed_paper(ledger, wins=5, losses=1)
    decision = controller.apply()
    assert decision.mode == "SHADOW"
    assert ledger.get_execution_mode() == "SHADOW"
    assert swarm.mode == "SHADOW"

    loop = AutonomousTradingLoop(
        ledger=ledger,
        lifecycle=lifecycle,
        config=AutonomousTradingConfig(allow_real_execution=False),
    )
    paper_action = await loop.open_position(_signal())
    assert paper_action.status == "OPENED"
    assert paper_action.position_id.startswith("paper-")

    # Second promotion: REAL lifecycle + stronger paper performance promotes to PROD.
    lifecycle.states["mean_reversion"].phase = StrategyPhase.REAL
    lifecycle.states["mean_reversion"].allocation_usdc = 10.0
    _record_closed_paper(ledger, wins=4, losses=0)

    class _Executor:
        async def execute(self, ticker: str, side: str, price: float, size: float):
            return {
                "status": "TAKER_FILLED",
                "order_id": "live-order-1",
                "price": price,
                "filled_size": size,
            }

    real_loop = AutonomousTradingLoop(
        ledger=ledger,
        lifecycle=lifecycle,
        config=AutonomousTradingConfig(allow_real_execution=True),
        executor=_Executor(),
    )

    decision = controller.apply()
    assert decision.mode == "PROD"
    assert ledger.get_execution_mode() == "PROD"
    assert swarm.mode == "PROD"

    real_action = await real_loop.open_position(_signal())
    assert real_action.status == "OPENED"
    assert not real_action.position_id.startswith("paper-")
    assert ledger.get_open_positions()

    # Demotion: drawdown guard forces back to PAPER and execution path follows.
    original_drawdown = controller._global_drawdown
    controller._global_drawdown = lambda: -0.10
    try:
        decision = controller.apply()
    finally:
        controller._global_drawdown = original_drawdown
    assert decision.mode == "PAPER"
    assert ledger.get_execution_mode() == "PAPER"
    assert swarm.mode == "PAPER"

    paper_again = await real_loop.open_position(_signal())
    assert paper_again.status == "OPENED"
    assert paper_again.position_id.startswith("paper-")
