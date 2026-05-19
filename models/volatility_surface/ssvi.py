import math
import random
from dataclasses import dataclass
from typing import Optional

import numpy as np


@dataclass
class SSVIParams:
    theta_atm: float
    rho: float
    eta: float
    gamma: float

    def clip(self) -> "SSVIParams":
        return SSVIParams(
            theta_atm=max(0.01, min(10.0, self.theta_atm)),
            rho=max(-0.999, min(0.999, self.rho)),
            eta=max(0.1, min(10.0, self.eta)),
            gamma=max(0.01, min(0.5, self.gamma)),
        )

    def to_array(self) -> np.ndarray:
        return np.array([self.theta_atm, self.rho, self.eta, self.gamma], dtype=np.float32)


def phi_power(theta: float, eta: float, gamma: float) -> float:
    return eta / (theta ** gamma * (1 + theta) ** (1 - gamma))


def ssvi_total_variance(k: float, t: float, params: SSVIParams) -> float:
    theta = params.theta_atm
    rho = params.rho
    eta = params.eta
    gamma = params.gamma
    phi_t = phi_power(theta, eta, gamma)
    term = phi_t * k + rho
    w = 0.5 * theta * (1 + rho * phi_t * k + math.sqrt(term * term + 1 - rho * rho))
    return max(w, 1e-8)


def implied_vol(k: float, t: float, params: SSVIParams) -> float:
    w = ssvi_total_variance(k, t, params)
    return math.sqrt(w / t) if t > 1e-8 else math.sqrt(w)


def surface_grid(
    params: SSVIParams,
    strikes: np.ndarray,
    expiries: np.ndarray,
) -> np.ndarray:
    surface = np.zeros((len(expiries), len(strikes)), dtype=np.float32)
    for i, t in enumerate(expiries):
        for j, k in enumerate(strikes):
            surface[i, j] = implied_vol(k, t, params)
    return surface


def sample_params(
    theta_range: tuple[float, float] = (0.05, 2.0),
    rho_range: tuple[float, float] = (-0.8, -0.2),
    eta_range: tuple[float, float] = (0.5, 4.0),
    gamma_range: tuple[float, float] = (0.1, 0.45),
) -> SSVIParams:
    return SSVIParams(
        theta_atm=random.uniform(*theta_range),
        rho=random.uniform(*rho_range),
        eta=random.uniform(*eta_range),
        gamma=random.uniform(*gamma_range),
    )
