import logging
import os
from typing import Any, Optional

import numpy as np

from schemas.volatility.ssvi import sample_params, surface_grid
from schemas.volatility.arbitrage import arbitrage_report
from schemas.volatility.metrics import surface_rmse

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

logger = logging.getLogger("VolSurfaceAdapter")


class VolSurfaceAdapter:
    def __init__(
        self,
        n_strikes: int = 20,
        n_expiries: int = 5,
        model_dir: str = "user_data/models/volatility_surface/weights",
        device: Optional[str] = None,
    ):
        self.n_strikes = n_strikes
        self.n_expiries = n_expiries
        self.model_dir = model_dir
        self.device = device
        if TORCH_AVAILABLE:
            self.device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        self._reconstruction_model: Optional[Any] = None
        self._forecast_model: Optional[Any] = None
        os.makedirs(model_dir, exist_ok=True)

    def load_or_init_models(self) -> None:
        if not TORCH_AVAILABLE:
            logger.warning("torch not available; models cannot be loaded")
            return
        from schemas.volatility.models import ReconstructionMLP, ForecastGRU
        rec_path = os.path.join(self.model_dir, "reconstruction_mlp.pt")
        fore_path = os.path.join(self.model_dir, "forecast_gru.pt")
        self._reconstruction_model = ReconstructionMLP()
        self._forecast_model = ForecastGRU()
        if os.path.exists(rec_path):
            self._reconstruction_model.load_state_dict(
                torch.load(rec_path, map_location=self.device, weights_only=True)
            )
            logger.info("Loaded reconstruction model from %s", rec_path)
        if os.path.exists(fore_path):
            self._forecast_model.load_state_dict(
                torch.load(fore_path, map_location=self.device, weights_only=True)
            )
            logger.info("Loaded forecast model from %s", fore_path)

    def generate_synthetic_surfaces(
        self, n_surfaces: int = 100, seed: Optional[int] = None
    ) -> list[dict]:
        if seed is not None:
            np.random.seed(seed)
        strikes = np.linspace(-0.5, 0.5, self.n_strikes)
        expiries = np.linspace(0.05, 1.0, self.n_expiries)
        results = []
        for _ in range(n_surfaces):
            p = sample_params()
            surf = surface_grid(p, strikes, expiries)
            results.append({
                "params": {
                    "theta_atm": p.theta_atm,
                    "rho": p.rho,
                    "eta": p.eta,
                    "gamma": p.gamma,
                },
                "surface_shape": list(surf.shape),
                "surface_mean": float(surf.mean()),
                "surface_std": float(surf.std()),
            })
        return results

    def check_arbitrage(self, surface: np.ndarray) -> dict:
        strikes = np.linspace(-0.5, 0.5, self.n_strikes)
        expiries = np.linspace(0.05, 1.0, self.n_expiries)
        return arbitrage_report(surface, strikes, expiries)

    def compute_metrics(self, predicted: np.ndarray, target: np.ndarray) -> dict:
        return {
            "rmse": round(surface_rmse(predicted, target), 6),
        }

    def get_status(self) -> dict:
        return {
            "device": self.device,
            "n_strikes": self.n_strikes,
            "n_expiries": self.n_expiries,
            "reconstruction_model_loaded": self._reconstruction_model is not None,
            "forecast_model_loaded": self._forecast_model is not None,
            "model_dir": self.model_dir,
        }
