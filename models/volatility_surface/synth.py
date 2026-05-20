import random
from dataclasses import dataclass
from typing import Optional

import numpy as np

from models.volatility_surface.ssvi import SSVIParams, sample_params, surface_grid


@dataclass
class SurfaceDataset:
    surfaces: np.ndarray
    params: np.ndarray
    path_id: Optional[np.ndarray] = None
    strikes: Optional[np.ndarray] = None
    expiries: Optional[np.ndarray] = None


def generate_independent_surfaces(
    n_surfaces: int = 1000,
    n_strikes: int = 20,
    n_expiries: int = 5,
    strike_range: tuple[float, float] = (-0.5, 0.5),
    expiry_range: tuple[float, float] = (0.05, 1.0),
) -> SurfaceDataset:
    strikes = np.linspace(*strike_range, n_strikes)
    expiries = np.linspace(*expiry_range, n_expiries)
    surfaces = np.zeros((n_surfaces, n_expiries, n_strikes), dtype=np.float32)
    param_list = []
    for i in range(n_surfaces):
        p = sample_params()
        surfaces[i] = surface_grid(p, strikes, expiries)
        param_list.append(p.to_array())
    return SurfaceDataset(
        surfaces=surfaces,
        params=np.array(param_list, dtype=np.float32),
        strikes=strikes,
        expiries=expiries,
    )


def generate_paths(
    n_paths: int = 100,
    n_steps: int = 252,
    n_strikes: int = 20,
    n_expiries: int = 5,
    strike_range: tuple[float, float] = (-0.5, 0.5),
    expiry_range: tuple[float, float] = (0.05, 1.0),
    ar1: float = 0.95,
    innov_std: float = 0.02,
    seed: Optional[int] = None,
) -> SurfaceDataset:
    if seed is not None:
        random.seed(seed)
        np.random.seed(seed)
    strikes = np.linspace(*strike_range, n_strikes)
    expiries = np.linspace(*expiry_range, n_expiries)
    surfaces = np.zeros((n_paths * n_steps, n_expiries, n_strikes), dtype=np.float32)
    all_params = np.zeros((n_paths * n_steps, 4), dtype=np.float32)
    path_ids = np.zeros(n_paths * n_steps, dtype=np.int32)
    for path in range(n_paths):
        p = sample_params()
        params_array = p.to_array()
        for step in range(n_steps):
            params_array = ar1 * params_array + (1 - ar1) * params_array + np.random.randn(4) * innov_std
            current = SSVIParams(
                theta_atm=float(params_array[0]),
                rho=float(params_array[1]),
                eta=float(params_array[2]),
                gamma=float(params_array[3]),
            ).clip()
            idx = path * n_steps + step
            surfaces[idx] = surface_grid(current, strikes, expiries)
            all_params[idx] = current.to_array()
            path_ids[idx] = path
    return SurfaceDataset(
        surfaces=surfaces,
        params=all_params,
        path_id=path_ids,
        strikes=strikes,
        expiries=expiries,
    )
