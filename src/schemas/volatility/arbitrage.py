import numpy as np


def _gatheral_g(k: np.ndarray, w: np.ndarray, eps: float = 1e-6) -> np.ndarray:
    dw = np.gradient(w, k)
    d2w = np.gradient(dw, k)
    g = (1 - k * dw / (2 * w)) ** 2 - (dw ** 2 / 4) * (1 / w + 0.25) + 0.5 * d2w
    return g


def calendar_spread_violations(
    surfaces: np.ndarray,
    axis: int = 0,
) -> tuple[float, float, float]:
    dw_dt = np.diff(surfaces, axis=axis)
    violations = dw_dt < -1e-8
    total = violations.size
    n_viol = int(violations.sum())
    mean_viol = float(-dw_dt[violations].mean()) if n_viol > 0 else 0.0
    return n_viol, mean_viol, n_viol / total if total > 0 else 0.0


def butterfly_violations(surfaces: np.ndarray, dt: float = 1.0) -> tuple[int, float, float]:
    total_viol = 0
    sum_viol = 0.0
    total_points = 0
    for i in range(surfaces.shape[0]):
        w = surfaces[i] * surfaces[i] * dt
        g = _gatheral_g(np.arange(len(w), dtype=float), w)
        mask = g < -1e-8
        n = int(mask.sum())
        total_viol += n
        sum_viol += float((-g[mask]).sum())
        total_points += len(g)
    return total_viol, sum_viol / total_viol if total_viol > 0 else 0.0, total_viol / total_points if total_points > 0 else 0.0


def arbitrage_report(
    surfaces: np.ndarray,
    strikes: np.ndarray,
    expiries: np.ndarray,
) -> dict:
    n_cal, mean_cal, frac_cal = calendar_spread_violations(surfaces)
    n_but, mean_but, frac_but = butterfly_violations(surfaces)
    n_total = n_cal + n_but
    n_points = surfaces.size
    return {
        "calendar_spread_violations": n_cal,
        "mean_calendar_violation": round(mean_cal, 8),
        "calendar_violation_fraction": round(frac_cal, 6),
        "butterfly_violations": n_but,
        "mean_butterfly_violation": round(mean_but, 8),
        "butterfly_violation_fraction": round(frac_but, 6),
        "total_violations": n_total,
        "violation_rate": round(n_total / n_points, 6) if n_points > 0 else 0.0,
        "arbitrage_free": n_total == 0,
    }
