import math

import numpy as np


class SABRSimulator:
    def __init__(
        self,
        S0: float = 100.0,
        alpha: float = 0.3,
        beta: float = 1.0,
        rho: float = -0.4,
        nu: float = 0.6,
        r: float = 0.0,
        dt: float = 1.0 / 252,
    ):
        self.S0 = S0
        self.alpha = alpha
        self.beta = beta
        self.rho = rho
        self.nu = nu
        self.r = r
        self.dt = dt

    def simulate(self, n_steps: int, n_paths: int = 1, seed: int | None = None) -> dict:
        if seed is not None:
            np.random.seed(seed)
        z1 = np.random.randn(n_paths, n_steps)
        z2 = np.random.randn(n_paths, n_steps)
        z2 = self.rho * z1 + math.sqrt(1 - self.rho ** 2) * z2

        S = np.zeros((n_paths, n_steps + 1), dtype=np.float64)
        alpha = np.full((n_paths,), self.alpha, dtype=np.float64)
        S[:, 0] = self.S0

        sqrt_dt = math.sqrt(self.dt)
        for t in range(n_steps):
            S[:, t + 1] = S[:, t] + self.r * S[:, t] * self.dt + alpha * (S[:, t] ** self.beta) * sqrt_dt * z1[:, t]
            S[:, t + 1] = np.maximum(S[:, t + 1], 1e-8)
            alpha = alpha + self.nu * alpha * sqrt_dt * z2[:, t]
            alpha = np.maximum(alpha, 1e-8)

        return {
            "S": S,
            "alpha": alpha,
            "dt": self.dt,
            "n_steps": n_steps,
            "n_paths": n_paths,
        }

    def sabr_implied_vol(self, F: float, K: float, T: float) -> float:
        if abs(F - K) < 1e-8:
            num1 = self.alpha
            denom1 = F ** (1 - self.beta)
            zeta = self.nu / self.alpha * F ** (1 - self.beta) * math.log(F / K)
            if abs(zeta) < 1e-8:
                return num1 / denom1
            chi = math.log(
                (math.sqrt(1 - 2 * self.rho * zeta + zeta ** 2) + zeta - self.rho) / (1 - self.rho)
            )
            return num1 / denom1 * (zeta / chi)
        logFK = math.log(F / K)
        F_mid = (F + K) / 2
        sigma_0 = self.alpha / (F_mid ** (1 - self.beta))
        z = self.nu / self.alpha * F_mid ** (1 - self.beta) * logFK
        x_z = math.log(
            (math.sqrt(1 - 2 * self.rho * z + z ** 2) + z - self.rho) / (1 - self.rho)
        ) if abs(z) > 1e-8 else 1.0
        return sigma_0 * (z / x_z) if abs(x_z) > 1e-8 else sigma_0
