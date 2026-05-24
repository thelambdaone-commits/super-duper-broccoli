from typing import Optional

import numpy as np

from schemas.risk.bsm_pricing import bsm_call
from schemas.risk.sabr_sim import SABRSimulator


class HedgingEnv:
    def __init__(
        self,
        S0: float = 100.0,
        K: float = 100.0,
        T: float = 20.0 / 252,
        r: float = 0.0,
        sigma: float = 0.2,
        spread: float = 0.01,
        num_contracts: int = 1,
        trade_freq: int = 1,
        cost_model: str = "spread",
    ):
        self.S0 = S0
        self.K = K
        self.T = T
        self.r = r
        self.sigma = sigma
        self.spread = spread
        self.num_contracts = num_contracts
        self.trade_freq = trade_freq
        self.cost_model = cost_model
        self.sabr = SABRSimulator(S0=S0, alpha=sigma, r=r, dt=1.0 / 252)
        self._reset_state()

    def _reset_state(self):
        self.t = 0
        self.position = 0.0
        self.cash = 0.0
        self.option_price = bsm_call(self.S0, self.K, self.T, self.r, self.sigma)
        self.asset_paths = None

    def reset(self, seed: Optional[int] = None) -> np.ndarray:
        self._reset_state()
        result = self.sabr.simulate(int(self.T * 252) + 1, n_paths=1, seed=seed)
        self.asset_paths = result["S"][0]
        self.t = 0
        self.position = 0.0
        self.cash = 0.0
        return self._get_state()

    def _get_state(self) -> np.ndarray:
        remaining = max(1e-8, self.T - self.t * self.sabr.dt)
        return np.array([
            float(self.asset_paths[self.t]),
            float(self.position),
            float(remaining),
        ], dtype=np.float32)

    def step(self, action: float) -> tuple[np.ndarray, float, bool, dict]:
        price = self.asset_paths[self.t]
        prev_position = self.position
        target_position = action * self.num_contracts * 100
        delta_pos = target_position - prev_position

        if self.cost_model == "spread":
            tx_cost = self.spread * price * abs(delta_pos)
        elif self.cost_model == "bps":
            tx_cost = 0.0005 * price * abs(delta_pos)
        else:
            tx_cost = 0.0

        self.cash -= delta_pos * price + tx_cost
        self.position = target_position
        self.t += 1

        done = self.t >= len(self.asset_paths) - 1
        if done:
            final_price = self.asset_paths[-1]
            option_payoff = max(0.0, final_price - self.K) * self.num_contracts
            self.cash += self.position * final_price - option_payoff
            reward = self.cash
        else:
            reward = -(delta_pos * price + tx_cost)

        return self._get_state() if not done else np.zeros(3, dtype=np.float32), reward, done, {}

    def render(self):
        print(f"t={self.t}, S={self.asset_paths[self.t]:.2f}, pos={self.position:.2f}, cash={self.cash:.4f}")
