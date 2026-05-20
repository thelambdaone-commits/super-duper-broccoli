from __future__ import annotations

import pytest

from core.autonomous_trading_loop import AutonomousTradingConfig, AutonomousTradingLoop
from core.strategy_lifecycle_manager import StrategyLifecycleConfig, StrategyLifecycleManager, StrategyPhase
from ledger.ledger_db import Ledger
from user_data.strategies.polymarket_strategy_factory import MeanReversionStrategy


@pytest.fixture
def ledger(tmp_path):
    return Ledger(db_path=str(tmp_path / "autonomous.db"))


@pytest.fixture
def lifecycle(tmp_path):
    manager = StrategyLifecycleManager(
        strategies=[MeanReversionStrategy()],
        config=StrategyLifecycleConfig(
            dashboard_path=str(tmp_path / "dashboard.md"),
            state_path=str(tmp_path / "state.json"),
            min_paper_trades=1,
        ),
    )
    manager.states["mean_reversion"].phase = StrategyPhase.PAPER
    return manager


@pytest.mark.asyncio
async def test_autonomous_loop_opens_paper_position_with_sltp(ledger, lifecycle):
    loop = AutonomousTradingLoop(
        ledger=ledger,
        lifecycle=lifecycle,
        config=AutonomousTradingConfig(default_paper_capital_usdc=20.0),
    )

    actions = await loop.run_once([
        {
            "market_id": "m1",
            "ticker": "MKT1",
            "price": 0.40,
            "ml_probability": 0.48,
            "spread": 0.01,
            "bid_volume": 100,
            "ask_volume": 100,
            "order_imbalance": 0.05,
        }
    ])

    assert any(a.action == "open" and a.status == "OPENED" for a in actions)
    positions = ledger.get_paper_positions("OPEN")
    assert len(positions) == 1
    assert positions[0]["take_profit_pct"] > 0
    assert positions[0]["stop_loss_pct"] > 0


@pytest.mark.asyncio
async def test_autonomous_loop_closes_take_profit_and_records_pnl(ledger, lifecycle):
    loop = AutonomousTradingLoop(
        ledger=ledger,
        lifecycle=lifecycle,
        config=AutonomousTradingConfig(default_paper_capital_usdc=20.0, default_take_profit_pct=0.10),
    )
    await loop.run_once([
        {
            "market_id": "m1",
            "ticker": "MKT1",
            "price": 0.40,
            "ml_probability": 0.48,
            "spread": 0.01,
            "bid_volume": 100,
            "ask_volume": 100,
            "order_imbalance": 0.05,
        }
    ])

    actions = await loop.run_once([
        {
            "market_id": "m1",
            "ticker": "MKT1",
            "price": 0.46,
            "ml_probability": 0.48,
            "spread": 0.01,
            "bid_volume": 100,
            "ask_volume": 100,
            "order_imbalance": 0.05,
        }
    ])

    closes = [a for a in actions if a.action == "close"]
    assert closes
    assert closes[0].status == "CLOSED"
    assert closes[0].pnl > 0
    assert ledger.get_paper_positions("OPEN") == []
    assert len(ledger.get_paper_positions("CLOSED")) == 1


@pytest.mark.asyncio
async def test_real_position_exit_is_blocked_without_explicit_flag(ledger, lifecycle):
    loop = AutonomousTradingLoop(
        ledger=ledger,
        lifecycle=lifecycle,
        config=AutonomousTradingConfig(allow_real_execution=False),
    )
    ledger.conn.execute(
        "INSERT INTO capital_allocation (total_capital, available_capital, allocated_pct) VALUES (1000, 1000, 10)"
    )
    ledger.conn.commit()
    ledger.record_order("real-1", "MKT1", "BUY", 0.40, 10.0, notional_usd=4.0)
    ledger.set_position_sltp("real-1", stop_loss_pct=0.05, take_profit_pct=0.10)

    actions = await loop.manage_open_positions({"MKT1": 0.46})

    assert actions[0].status == "BLOCKED"
    assert ledger.get_open_positions()[0]["status"] == "OPEN"


@pytest.mark.asyncio
async def test_autonomous_loop_uses_selector_top_k(ledger, tmp_path):
    from user_data.strategies.polymarket_strategy_factory import MacroTrendMLStrategy

    manager = StrategyLifecycleManager(
        strategies=[MeanReversionStrategy(), MacroTrendMLStrategy()],
        config=StrategyLifecycleConfig(
            dashboard_path=str(tmp_path / "dashboard_topk.md"),
            state_path=str(tmp_path / "state_topk.json"),
        ),
    )
    for state in manager.states.values():
        state.phase = StrategyPhase.PAPER

    loop = AutonomousTradingLoop(
        ledger=ledger,
        lifecycle=manager,
        config=AutonomousTradingConfig(default_paper_capital_usdc=20.0, top_k_opportunities=1),
    )

    actions = await loop.run_once([
        {
            "market_id": "m1",
            "ticker": "MKT1",
            "price": 0.40,
            "ml_probability": 0.50,
            "spread": 0.01,
            "bid_volume": 100,
            "ask_volume": 100,
            "order_imbalance": 0.05,
        }
    ])

    opened = [a for a in actions if a.status == "OPENED"]
    assert len(opened) == 1
    assert "selection_score" in opened[0].metadata
