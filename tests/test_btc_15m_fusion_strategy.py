from __future__ import annotations

from core.strategy_lifecycle_manager import StrategyLifecycleManager, StrategyPhase
from strategies.btc_15m_fusion import Btc15MinuteFusionStrategy


def test_btc_15m_fusion_ignores_non_btc_markets() -> None:
    strategy = Btc15MinuteFusionStrategy()

    signal = strategy.generate_signal(
        {
            "market_id": "m1",
            "ticker": "ETH",
            "price": 0.51,
            "spread": 0.02,
            "metadata": {"is_candle_close": True},
        }
    )

    assert signal is None


def test_btc_15m_fusion_emits_signal_on_15m_close() -> None:
    strategy = Btc15MinuteFusionStrategy()

    signal = strategy.generate_signal(
        {
            "market_id": "btc-m1",
            "ticker": "BTC",
            "price": 0.51,
            "bid_price": 0.50,
            "ask_price": 0.51,
            "spread": 0.01,
            "ml_probability": 0.58,
            "order_imbalance": 0.20,
            "metadata": {
                "is_candle_close": True,
                "spike_score": 0.6,
                "candle_interval": "15m",
            },
        }
    )

    assert signal is not None
    assert signal.strategy_id == "btc_15m_fusion"
    assert signal.ticker == "BTC"
    assert signal.side == "BUY"
    assert signal.confidence >= 0.60
    assert signal.metadata["timeframe"] == "15m"


def test_btc_15m_fusion_eligible_real_signal_flows_through_lifecycle() -> None:
    strategy = Btc15MinuteFusionStrategy()
    manager = StrategyLifecycleManager(strategies=[strategy])
    manager.states[strategy.strategy_id].phase = StrategyPhase.REAL

    signals = manager.eligible_real_signals(
        {
            "market_id": "btc-m1",
            "ticker": "BTC",
            "price": 0.51,
            "bid_price": 0.50,
            "ask_price": 0.51,
            "spread": 0.01,
            "ml_probability": 0.58,
            "order_imbalance": 0.20,
            "metadata": {
                "is_candle_close": True,
                "spike_score": 0.6,
                "candle_interval": "15m",
            },
        }
    )

    assert len(signals) == 1
    assert signals[0].strategy_id == "btc_15m_fusion"
    assert signals[0].ticker == "BTC"
