import logging
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from engine.backtest.costs import CostModel
from engine.backtest.metrics import (
    sharpe_ratio, sortino_ratio, max_drawdown, calmar_ratio,
    information_coefficient, hit_rate,
)

logger = logging.getLogger("Backtester")


class Backtester:
    def __init__(
        self,
        initial_capital: float = 10000.0,
        cost_model: Optional[CostModel] = None,
        rebalance_freq: str = "1D",
    ):
        self.initial_capital = initial_capital
        self.cost_model = cost_model or CostModel()
        self.rebalance_freq = rebalance_freq

    def run(
        self,
        prices: pd.DataFrame,
        signals: pd.DataFrame,
        signal_col: str = "signal",
        price_col: str = "close",
    ) -> dict:
        data = prices[[price_col]].copy()
        if signal_col in signals.columns:
            data["signal"] = signals[signal_col]
        else:
            data["signal"] = 0.0
        data = data.dropna()

        if len(data) < 2:
            return {"error": "Insufficient data", "total_return": 0.0}

        data["position"] = data["signal"].shift(1).fillna(0)
        data["prev_close"] = data[price_col].shift(1)
        data["trade"] = data["position"].diff().abs().fillna(0)

        data["cost"] = data["trade"] * data[price_col] * (
            self.cost_model.spread_bps + self.cost_model.slippage_bps
        ) / 10000.0
        data["returns"] = data["position"] * data[price_col].pct_change().fillna(0)
        data["net_returns"] = data["returns"] - data["cost"] / data[price_col].shift(1).fillna(data[price_col])

        equity = self.initial_capital * np.cumprod(1 + data["net_returns"].to_numpy())
        rets = data["net_returns"].to_numpy()
        total_return = (equity[-1] / self.initial_capital - 1) * 100

        return {
            "total_return_pct": round(total_return, 2),
            "sharpe": round(sharpe_ratio(rets), 3),
            "sortino": round(sortino_ratio(rets), 3),
            "max_drawdown_pct": round(max_drawdown(equity) * 100, 2),
            "calmar": round(calmar_ratio(rets), 3),
            "hit_rate": round(hit_rate(np.sign(rets), np.sign(rets + 1e-8)), 3),
            "n_trades": int(data["trade"].sum()),
            "final_equity": round(float(equity[-1]), 2),
            "initial_capital": self.initial_capital,
        }
