from .ssvi import SSVIParams, ssvi_total_variance, surface_grid, sample_params
from .synth import SurfaceDataset, generate_paths, generate_independent_surfaces
from .arbitrage import arbitrage_report
from .metrics import surface_rmse, atm_rmse, smile_slope_rmse
from .adapter import VolSurfaceAdapter

try:
    from .models import ReconstructionMLP, ForecastGRU
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
