from __future__ import annotations

from core.autonomous_mode_controller import AutonomousModeConfig, AutonomousModeController
from core.strategy_lifecycle_manager import StrategyLifecycleConfig, StrategyLifecycleManager, StrategyPhase
from ledger.ledger_db import Ledger
from user_data.strategies.polymarket_strategy_factory import MeanReversionStrategy


def _ledger(tmp_path):
    ledger = Ledger(db_path=str(tmp_path / "mode.db"))
    ledger.conn.execute("DELETE FROM capital_allocation")
    ledger.conn.execute("INSERT INTO capital_allocation (total_capital, available_capital, allocated_pct) VALUES (1000, 1000, 10)")
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
    for i in range(wins):
        result = ledger.record_paper_order("MKT", "BUY", 0.50, 10, signal_source="test")
        ledger.close_paper_position(result["position_id"], exit_price=0.70, pnl=2.0, is_win=True)
    for i in range(losses):
        result = ledger.record_paper_order("MKT", "BUY", 0.50, 10, signal_source="test")
        ledger.close_paper_position(result["position_id"], exit_price=0.40, pnl=-1.0, is_win=False)


def test_mode_stays_paper_without_proven_edge(tmp_path):
    ledger = _ledger(tmp_path)
    lifecycle = _lifecycle(tmp_path)

    decision = AutonomousModeController(ledger, lifecycle).decide()

    assert decision.mode == "PAPER"
    assert "Insufficient" in decision.reason


def test_mode_promotes_to_shadow_after_profitable_paper(tmp_path):
    ledger = _ledger(tmp_path)
    lifecycle = _lifecycle(tmp_path)
    lifecycle.states["mean_reversion"].phase = StrategyPhase.SANITY
    _record_closed_paper(ledger, wins=5, losses=1)

    decision = AutonomousModeController(ledger, lifecycle).decide()

    assert decision.mode == "SHADOW"
    assert decision.shadow_ready is True


def test_mode_promotes_to_prod_only_with_real_prerequisites(tmp_path, monkeypatch):
    monkeypatch.delenv("AUTONOMOUS_REAL_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("REAL", raising=False)
    monkeypatch.delenv("MODE", raising=False)

    ledger = _ledger(tmp_path)
    lifecycle = _lifecycle(tmp_path)
    state = lifecycle.states["mean_reversion"]
    state.phase = StrategyPhase.REAL
    state.allocation_usdc = 10.0
    _record_closed_paper(ledger, wins=8, losses=2)

    config = AutonomousModeConfig(min_paper_trades_for_real=10)

    assert AutonomousModeController(ledger, lifecycle, config).decide().mode == "SHADOW"

    monkeypatch.setenv("AUTONOMOUS_REAL_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("REAL", "true")

    decision = AutonomousModeController(ledger, lifecycle, config).decide()

    assert decision.mode == "PROD"
    assert decision.real_ready is True


def test_force_prod_bypasses_profitability_gates_but_keeps_prerequisites(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_FORCE_PROD", "true")
    monkeypatch.setenv("AUTONOMOUS_REAL_EXECUTION_ENABLED", "true")
    monkeypatch.setenv("REAL", "true")

    ledger = _ledger(tmp_path)
    lifecycle = _lifecycle(tmp_path)

    decision = AutonomousModeController(ledger, lifecycle).decide()

    assert decision.mode == "PROD"
    assert decision.reason == "Forced PROD override enabled for non-interactive runtime"


def test_force_prod_still_requires_prod_prerequisites(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTONOMOUS_FORCE_PROD", "true")
    monkeypatch.delenv("AUTONOMOUS_REAL_EXECUTION_ENABLED", raising=False)
    monkeypatch.delenv("REAL", raising=False)
    monkeypatch.delenv("MODE", raising=False)

    ledger = _ledger(tmp_path)
    lifecycle = _lifecycle(tmp_path)

    decision = AutonomousModeController(ledger, lifecycle).decide()

    assert decision.mode == "PAPER"
    assert "Insufficient" in decision.reason


def test_apply_updates_ledger_mode(tmp_path):
    ledger = _ledger(tmp_path)
    lifecycle = _lifecycle(tmp_path)
    lifecycle.states["mean_reversion"].phase = StrategyPhase.SANITY
    _record_closed_paper(ledger, wins=5, losses=1)

    decision = AutonomousModeController(ledger, lifecycle).apply()

    assert decision.mode == "SHADOW"
    assert ledger.get_execution_mode() == "SHADOW"


def test_apply_respects_manual_override(tmp_path):
    ledger = _ledger(tmp_path)
    lifecycle = _lifecycle(tmp_path)

    # Manually set mode to PROD via Ledger (simulating Redis hot-swap)
    ledger.set_execution_mode("PROD", manual=True)

    # Even if logic would suggest PAPER, apply() must honor manual PROD
    decision = AutonomousModeController(ledger, lifecycle).apply()

    assert decision.mode == "PROD"
    assert decision.reason == "Manual override active"
    assert ledger.get_execution_mode() == "PROD"
