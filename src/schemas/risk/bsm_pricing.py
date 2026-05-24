import math

from scipy.stats import norm


def bsm_call(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 1e-8 or sigma <= 1e-8:
        return max(0.0, S - K)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return S * norm.cdf(d1) - K * math.exp(-r * T) * norm.cdf(d2)


def bsm_delta(S: float, K: float, T: float, r: float, sigma: float) -> float:
    if T <= 1e-8 or sigma <= 1e-8:
        return 1.0 if S > K else 0.0
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return float(norm.cdf(d1))


def bartlett_delta(
    S: float, K: float, T: float, r: float,
    sigma: float, alpha: float, rho: float,
    nu: float, beta: float = 1.0,
) -> float:
    bs_delta = bsm_delta(S, K, T, r, sigma)
    if nu <= 1e-8:
        return bs_delta
    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        vega = S * math.sqrt(T) * norm.pdf(d1)
        if alpha <= 1e-8:
            return bs_delta
        dsigma_dS = (alpha * sigma / S) * rho
        return bs_delta + vega * dsigma_dS
    except (ValueError, ZeroDivisionError):
        return bs_delta
