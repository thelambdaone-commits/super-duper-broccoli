import numpy as np
from scipy import stats


def sharpe_ratio(returns: np.ndarray, risk_free: float = 0.0, periods: int = 252) -> float:
    excess = returns - risk_free / periods
    if excess.std() < 1e-8:
        return 0.0
    return float(np.sqrt(periods) * excess.mean() / excess.std())


def sortino_ratio(returns: np.ndarray, risk_free: float = 0.0, periods: int = 252) -> float:
    excess = returns - risk_free / periods
    downside = excess[excess < 0]
    if len(downside) < 1 or downside.std() < 1e-8:
        return 0.0
    return float(np.sqrt(periods) * excess.mean() / downside.std())


def max_drawdown(equity: np.ndarray) -> float:
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return float(np.min(dd))


def calmar_ratio(returns: np.ndarray, periods: int = 252) -> float:
    ann_return = float(np.mean(returns) * periods)
    eq = np.cumprod(1 + returns)
    mdd = max_drawdown(eq)
    if abs(mdd) < 1e-8:
        return 0.0
    return ann_return / abs(mdd)


def information_coefficient(pred: np.ndarray, actual: np.ndarray) -> float:
    if len(pred) < 2:
        return 0.0
    rho, _ = stats.spearmanr(pred, actual)
    return float(rho) if not np.isnan(rho) else 0.0


def hit_rate(pred_direction: np.ndarray, actual_direction: np.ndarray) -> float:
    correct = (pred_direction == actual_direction).sum()
    return float(correct) / len(pred_direction) if len(pred_direction) > 0 else 0.0
