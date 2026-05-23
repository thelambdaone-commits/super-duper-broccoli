from __future__ import annotations

import pytest

from core.autonomous_trading_loop import AutonomousTradingConfig, AutonomousTradingLoop
from core.strategy_lifecycle_manager import StrategyLifecycleConfig, StrategyLifecycleManager, StrategyPhase
from ledger.ledger_db import Ledger
from user_data.strategies.base_strategy import StrategySignal
from user_data.strategies.polymarket_strategy_factory import MeanReversionStrategy


class _StubRiskEngine:
    def __init__(self, size: float, capital_at_risk: float) -> None:
        self.size = size
        self.capital_at_risk = capital_at_risk

    def compute_position_size(self, **_: object) -> dict[str, float | str]:
        return {
            "size": self.size,
            "capital_at_risk": self.capital_at_risk,
            "reason": "stubbed",
        }


class _StubExecutor:
    async def execute(self, ticker: str, side: str, price: float, size: float) -> dict[str, float | str]:
        return {
            "status": "FILLED",
            "filled_size": size,
            "price": price,
            "order_id": f"oid-{ticker}-{side}",
        }


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


@pytest.mark.asyncio
async def test_bootstrap_paper_history_generates_closed_trades(ledger, lifecycle):
    loop = AutonomousTradingLoop(
        ledger=ledger,
        lifecycle=lifecycle,
        config=AutonomousTradingConfig(default_paper_capital_usdc=20.0),
    )

    actions = await loop.bootstrap_paper_history(
        [
            {
                "market_id": "m1",
                "ticker": "MKT1",
                "price": 0.40,
                "ml_probability": 0.62,
                "spread": 0.01,
                "bid_volume": 100,
                "ask_volume": 100,
                "order_imbalance": 0.05,
            }
        ],
        target_trades=3,
    )

    closed = [a for a in actions if a.action == "close" and a.status == "CLOSED"]
    assert closed
    assert len(ledger.get_paper_positions("CLOSED")) >= 1


@pytest.mark.asyncio
async def test_autonomous_loop_rejects_trade_when_fees_destroy_expected_profit(ledger, lifecycle):
    loop = AutonomousTradingLoop(
        ledger=ledger,
        lifecycle=lifecycle,
        config=AutonomousTradingConfig(default_paper_capital_usdc=20.0),
    )

    action = await loop.open_position(
        StrategySignal(
            strategy_id="fee_guard",
            market_id="m1",
            ticker="MKT1",
            side="BUY",
            price=0.90,
            confidence=0.55,
            edge=0.01,
            reason="tiny edge should die after fees",
            metadata={"spread": 0.03},
        )
    )

    assert action.status == "REJECTED"
    assert "net expected profit" in action.reason
    assert ledger.get_paper_positions("OPEN") == []


@pytest.mark.asyncio
async def test_live_autonomous_loop_uses_risk_engine_capital_and_respects_minimum_notional(ledger, lifecycle):
    ledger.set_execution_mode("PROD")
    ledger.conn.execute(
        "INSERT INTO capital_allocation (total_capital, available_capital, allocated_pct) VALUES (16.739693, 16.739693, 90)"
    )
    ledger.conn.commit()
    loop = AutonomousTradingLoop(
        ledger=ledger,
        lifecycle=lifecycle,
        risk_engine=_StubRiskEngine(size=12.0, capital_at_risk=6.0),
        executor=_StubExecutor(),
        config=AutonomousTradingConfig(allow_real_execution=True),
    )

    action = await loop.open_position(
        StrategySignal(
            strategy_id="live_cap",
            market_id="m1",
            ticker="MKT1",
            side="BUY",
            price=0.50,
            confidence=0.90,
            edge=0.50,
            reason="live bounded sizing",
            suggested_capital=2.0,
            metadata={"spread": 0.0},
        )
    )

    assert action.status == "OPENED"
    positions = ledger.get_open_positions()
    assert len(positions) == 1
    assert positions[0]["notional_usd"] == pytest.approx(5.0)


@pytest.mark.asyncio
async def test_live_autonomous_loop_rejects_sub_minimum_notional_before_executor(ledger, lifecycle):
    ledger.set_execution_mode("PROD")
    ledger.conn.execute(
        "INSERT INTO capital_allocation (total_capital, available_capital, allocated_pct) VALUES (4.0, 4.0, 90)"
    )
    ledger.conn.commit()
    loop = AutonomousTradingLoop(
        ledger=ledger,
        lifecycle=lifecycle,
        risk_engine=_StubRiskEngine(size=2.0, capital_at_risk=1.0),
        executor=_StubExecutor(),
        config=AutonomousTradingConfig(allow_real_execution=True),
    )

    action = await loop.open_position(
        StrategySignal(
            strategy_id="live_reject",
            market_id="m1",
            ticker="MKT1",
            side="BUY",
            price=0.50,
            confidence=0.90,
            edge=0.50,
            reason="must be rejected under min notional",
            metadata={"spread": 0.0},
        )
    )

    assert action.status == "REJECTED"
    assert "Polymarket minimum" in action.reason
    assert ledger.get_open_positions() == []
