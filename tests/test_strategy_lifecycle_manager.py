from __future__ import annotations

from pathlib import Path

from core.strategy_lifecycle_manager import (
    StrategyLifecycleConfig,
    StrategyLifecycleManager,
    StrategyPhase,
)
from scripts.reinforcement_optimization_loop import optimize_once
from user_data.strategies.polymarket_strategy_factory import InterMarketArbitrageStrategy


def _config(tmp_path: Path) -> StrategyLifecycleConfig:
    return StrategyLifecycleConfig(
        min_sharpe=2.0,
        min_profit=0.0,
        max_drawdown=0.20,
        min_backtest_trades=3,
        min_paper_trades=5,
        max_paper_slippage=0.04,
        initial_real_allocation=7.5,
        dashboard_path=str(tmp_path / "STRATEGY_AUTONOMOUS_DASHBOARD.md"),
        state_path=str(tmp_path / "strategy_state.json"),
    )


def _profitable_rows() -> list[dict]:
    rows = []
    price = 0.40
    for i in range(8):
        rows.append(
            {
                "market_id": "m-election",
                "ticker": "ELECTION",
                "price": price,
                "external_price": price + 0.08,
                "spread": 0.001,
                "timestamp": 1_700_000_000 + i,
            }
        )
        price += 0.02
    return rows


def test_gated_pipeline_promotes_only_after_all_gates(tmp_path: Path) -> None:
    strategy = InterMarketArbitrageStrategy()
    manager = StrategyLifecycleManager(strategies=[strategy], config=_config(tmp_path))

    result = manager.run_backtests({"inter_market_arbitrage": _profitable_rows()})

    metrics = result["inter_market_arbitrage"]
    assert metrics.trade_count >= 3
    assert metrics.sharpe >= 2.0
    assert manager.states["inter_market_arbitrage"].phase == StrategyPhase.PAPER

    for _ in range(5):
        manager.record_paper_result("inter_market_arbitrage", pnl=0.02, slippage=0.01)
    assert manager.states["inter_market_arbitrage"].phase == StrategyPhase.SANITY

    report = manager.run_sanity_checks(
        "inter_market_arbitrage",
        {"heartbeat_ok": True, "tensor_fallback_ok": True, "strict_json_ok": True, "risk_veto_ok": True},
    )
    state = manager.states["inter_market_arbitrage"]
    assert report.passed is True
    assert state.phase == StrategyPhase.REAL
    assert state.allocation_usdc == 7.5

    dashboard = (tmp_path / "STRATEGY_AUTONOMOUS_DASHBOARD.md").read_text(encoding="utf-8")
    assert "Inter-Market Arbitrage" in dashboard
    assert "REAL" in dashboard


def test_circuit_breaker_demotes_real_strategy_after_consecutive_losses(tmp_path: Path) -> None:
    strategy = InterMarketArbitrageStrategy()
    manager = StrategyLifecycleManager(strategies=[strategy], config=_config(tmp_path))
    state = manager.states["inter_market_arbitrage"]
    state.phase = StrategyPhase.REAL
    state.allocation_usdc = 7.5

    for _ in range(3):
        manager.record_paper_result("inter_market_arbitrage", pnl=-0.03, slippage=0.01)

    assert state.phase == StrategyPhase.PAPER
    assert state.allocation_usdc == 0.0
    assert "Circuit breaker" in state.disabled_reason


def test_optimization_loop_tightens_underperforming_strategy(tmp_path: Path) -> None:
    strategy = InterMarketArbitrageStrategy()
    manager = StrategyLifecycleManager(strategies=[strategy], config=_config(tmp_path))
    state = manager.states["inter_market_arbitrage"]
    state.phase = StrategyPhase.PAPER

    for _ in range(3):
        manager.record_paper_result("inter_market_arbitrage", pnl=-0.02, slippage=0.05)

    old_edge = strategy.parameters.min_edge
    old_confidence = strategy.parameters.min_confidence
    mutations = optimize_once(manager)

    assert mutations
    assert strategy.parameters.min_edge > old_edge
    assert strategy.parameters.min_confidence > old_confidence
    assert state.mutations
