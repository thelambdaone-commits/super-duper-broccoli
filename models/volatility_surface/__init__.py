from models.volatility_surface.ssvi import SSVIParams, ssvi_total_variance, surface_grid, sample_params
from models.volatility_surface.synth import SurfaceDataset, generate_paths, generate_independent_surfaces
from models.volatility_surface.arbitrage import arbitrage_report
from models.volatility_surface.metrics import surface_rmse, atm_rmse, smile_slope_rmse
from models.volatility_surface.adapter import VolSurfaceAdapter

try:
    from models.volatility_surface.models import ReconstructionMLP, ForecastGRU
except ImportError:
    class ReconstructionMLP:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("torch required for ReconstructionMLP")
    class ForecastGRU:  # type: ignore
        def __init__(self, *args, **kwargs):
            raise ImportError("torch required for ForecastGRU")

__all__ = [
    "SSVIParams", "ssvi_total_variance", "surface_grid", "sample_params",
    "SurfaceDataset", "generate_paths", "generate_independent_surfaces",
    "ReconstructionMLP", "ForecastGRU",
    "arbitrage_report",
    "surface_rmse", "atm_rmse", "smile_slope_rmse",
    "VolSurfaceAdapter",
]
