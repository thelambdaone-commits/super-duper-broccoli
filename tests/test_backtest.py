import pytest
import pandas as pd
import numpy as np

from engine.backtest.backtester import Backtester
from engine.backtest.metrics import sharpe_ratio, sortino_ratio, max_drawdown, calmar_ratio, information_coefficient, hit_rate
from engine.backtest.costs import CostModel


class TestCostModel:
    def test_cost_calculation(self):
        cm = CostModel(spread_bps=1.0, commission_bps=0.5, slippage_bps=0.5)
        cost = cm.total_cost(10000.0)
        assert cost > 0
        assert cost < 100.0  # should be ~2 bps = $2

    def test_min_cost(self):
        cm = CostModel(min_cost=1.0)
        cost = cm.total_cost(10.0)
        assert cost == 1.0


class TestMetrics:
    def test_sharpe_constant_returns(self):
        rets = np.ones(100) * 0.001
        sr = sharpe_ratio(rets, risk_free=0.0, periods=252)
        assert sr == 0.0  # zero variance -> zero sharpe

    def test_sharpe_zero_risk_free(self):
        rets = np.random.randn(100) * 0.01
        sr = sharpe_ratio(rets, risk_free=0.0)
        assert isinstance(sr, float)

    def test_sortino(self):
        rets = np.random.randn(100) * 0.01
        sr = sortino_ratio(rets)
        assert isinstance(sr, float)

    def test_max_drawdown(self):
        equity = np.array([100, 110, 105, 115, 95, 120])
        dd = max_drawdown(equity)
        assert dd < 0
        assert dd > -1

    def test_calmar(self):
        rets = np.random.randn(100) * 0.01
        cr = calmar_ratio(rets)
        assert isinstance(cr, float)

    def test_information_coefficient(self):
        pred = np.array([0.1, 0.2, 0.3, 0.4, 0.5])
        actual = np.array([0.15, 0.25, 0.28, 0.42, 0.48])
        ic = information_coefficient(pred, actual)
        assert -1 <= ic <= 1

    def test_hit_rate(self):
        pred = np.array([1, -1, 1, -1])
        actual = np.array([1, -1, -1, 1])
        hr = hit_rate(pred, actual)
        assert 0 <= hr <= 1
        assert hr == 0.5


class TestBacktester:
    def test_backtest_simple(self):
        date_range = pd.date_range("2024-01-01", periods=100, freq="D")
        prices = pd.DataFrame({"close": 100 + np.cumsum(np.random.randn(100) * 0.5)}, index=date_range)
        signals = pd.DataFrame({"signal": np.random.choice([-1, 0, 1], 100)}, index=date_range)
        bt = Backtester(initial_capital=10000.0)
        result = bt.run(prices, signals)
        assert "total_return_pct" in result
        assert "sharpe" in result
        assert "max_drawdown_pct" in result
        assert "final_equity" in result

    def test_backtest_constant_signal(self):
        date_range = pd.date_range("2024-01-01", periods=50, freq="D")
        prices = pd.DataFrame({"close": 100 + np.arange(50) * 0.5}, index=date_range)
        signals = pd.DataFrame({"signal": np.ones(50)}, index=date_range)
        bt = Backtester(initial_capital=10000.0)
        result = bt.run(prices, signals)
        assert result["total_return_pct"] > 0

    def test_backtest_no_data(self):
        prices = pd.DataFrame({"close": []})
        signals = pd.DataFrame({"signal": []})
        bt = Backtester()
        result = bt.run(prices, signals)
        assert "error" in result
