from __future__ import annotations

from pathlib import Path

from core.strategy_selector import StrategyBandit, StrategySelectionConfig, StrategySelector
from user_data.strategies.base_strategy import MarketFeatures, StrategySignal


def _signal(strategy_id: str, edge: float, confidence: float = 0.7, price: float = 0.4) -> StrategySignal:
    return StrategySignal(
        strategy_id=strategy_id,
        market_id="m1",
        ticker="MKT1",
        side="BUY",
        price=price,
        confidence=confidence,
        edge=edge,
        reason="test",
        metadata={
            "estimated_probability": price + edge,
            "time_to_settlement_hours": 24,
            "sigma_relative": 0.10,
        },
    )


def test_selector_ranks_positive_ev_above_weaker_signal(tmp_path: Path) -> None:
    selector = StrategySelector(
        StrategySelectionConfig(
            bandit_state_path=str(tmp_path / "bandit.json"),
            exploration_rate=0.0,
            min_score=-1.0,
            risk_lambda=0.1,
            cost_mu=0.1,
        )
    )
    features = {"m1": MarketFeatures(market_id="m1", ticker="MKT1", price=0.4, spread=0.01, bid_volume=100, ask_volume=100)}

    ranked = selector.rank([_signal("weak", 0.03), _signal("strong", 0.12)], features)

    assert ranked[0].signal.strategy_id == "strong"
    assert ranked[0].ev > ranked[1].ev


def test_selector_applies_top_k(tmp_path: Path) -> None:
    selector = StrategySelector(
        StrategySelectionConfig(
            bandit_state_path=str(tmp_path / "bandit.json"),
            exploration_rate=0.0,
            top_k=2,
            max_new_positions_per_cycle=2,
            max_concurrent_markets=5,
            min_score=-1.0,
            risk_lambda=0.1,
            cost_mu=0.1,
        )
    )
    signals = [
        StrategySignal("a", "m1", "MKT1", "BUY", 0.4, 0.7, 0.03, "test", metadata={"estimated_probability": 0.43, "sigma_relative": 0.1}),
        StrategySignal("b", "m2", "MKT2", "BUY", 0.4, 0.7, 0.08, "test", metadata={"estimated_probability": 0.48, "sigma_relative": 0.1}),
        StrategySignal("c", "m3", "MKT3", "BUY", 0.4, 0.7, 0.12, "test", metadata={"estimated_probability": 0.52, "sigma_relative": 0.1}),
    ]
    features = {
        "m1": MarketFeatures("m1", "MKT1", 0.4, bid_volume=100, ask_volume=100),
        "m2": MarketFeatures("m2", "MKT2", 0.4, bid_volume=100, ask_volume=100),
        "m3": MarketFeatures("m3", "MKT3", 0.4, bid_volume=100, ask_volume=100),
    }
    selected = selector.select(signals, features_by_market=features)

    assert len(selected) == 2
    assert {s.signal.strategy_id for s in selected} == {"b", "c"}


def test_bandit_feedback_persists_and_changes_mean(tmp_path: Path) -> None:
    path = str(tmp_path / "bandit.json")
    bandit = StrategyBandit(path)
    before = bandit._arm("mean_reversion").mean

    bandit.update("mean_reversion", pnl=2.0, slippage=0.1, filled=True)
    after = bandit._arm("mean_reversion").mean
    reloaded = StrategyBandit(path)

    assert after > before
    assert reloaded._arm("mean_reversion").pulls == 1


def test_selector_rejects_low_quality_signals(tmp_path: Path) -> None:
    selector = StrategySelector(
        StrategySelectionConfig(
            bandit_state_path=str(tmp_path / "bandit.json"),
            exploration_rate=0.0,
            ev_min=0.01,
            sigma_relative_max=0.2,
            min_liquidity_usdc=25.0,
            max_cost=0.03,
        )
    )
    liquid = {"m1": MarketFeatures("m1", "MKT1", 0.4, spread=0.01, bid_volume=100, ask_volume=100)}
    illiquid = {"m1": MarketFeatures("m1", "MKT1", 0.4, spread=0.01, bid_volume=1, ask_volume=1)}

    uncertain = _signal("uncertain", 0.08, confidence=0.5)
    uncertain = StrategySignal(
        uncertain.strategy_id,
        uncertain.market_id,
        uncertain.ticker,
        uncertain.side,
        uncertain.price,
        uncertain.confidence,
        uncertain.edge,
        uncertain.reason,
        metadata={**uncertain.metadata, "sigma_relative": 0.50},
    )

    assert selector.select([_signal("good", 0.08)], liquid)
    assert selector.select([_signal("low_ev", 0.001)], liquid) == []
    assert selector.select([uncertain], liquid) == []
    assert selector.select([_signal("illiquid", 0.08)], illiquid) == []
    assert selector.select([StrategySignal("costly", "m1", "MKT1", "BUY", 0.4, 0.8, 0.08, "test", metadata={"estimated_probability": 0.48, "sigma_relative": 0.1, "fee_slippage_cost": 0.05})], liquid) == []


def test_selector_caps_suggested_capital(tmp_path: Path) -> None:
    selector = StrategySelector(
        StrategySelectionConfig(
            bandit_state_path=str(tmp_path / "bandit.json"),
            exploration_rate=0.0,
            ev_min=0.001,
            min_liquidity_usdc=10.0,
            absolute_trade_capital_usdc=25.0,
            max_capital_per_market_pct=0.05,
            risk_lambda=0.1,
            cost_mu=0.1,
        )
    )
    features = {"m1": MarketFeatures("m1", "MKT1", 0.4, spread=0.01, bid_volume=1000, ask_volume=1000)}

    selected = selector.select([_signal("edge", 0.15, confidence=0.9)], features, total_capital=1000.0)

    assert selected
    assert 0.0 < selected[0].suggested_capital <= 25.0
