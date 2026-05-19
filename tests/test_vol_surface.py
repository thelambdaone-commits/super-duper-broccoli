import numpy as np
import pytest

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

from models.volatility_surface.ssvi import SSVIParams, sample_params, surface_grid, implied_vol
from models.volatility_surface.synth import generate_independent_surfaces, generate_paths
from models.volatility_surface.arbitrage import arbitrage_report
from models.volatility_surface.metrics import surface_rmse
from models.volatility_surface.adapter import VolSurfaceAdapter


class TestSSVIParametrization:
    def test_ssvi_params_clip(self):
        p = SSVIParams(theta_atm=-1.0, rho=-2.0, eta=20.0, gamma=1.0)
        clipped = p.clip()
        assert clipped.theta_atm >= 0.01
        assert clipped.rho >= -0.999
        assert clipped.eta <= 10.0
        assert clipped.gamma <= 0.5

    def test_sample_params(self):
        p = sample_params()
        assert p.theta_atm > 0
        assert -1 < p.rho < 1
        assert p.gamma > 0

    def test_implied_vol_positive(self):
        p = sample_params()
        vol = implied_vol(0.0, 0.5, p)
        assert vol > 0

    def test_surface_grid_shape(self):
        p = sample_params()
        strikes = np.linspace(-0.5, 0.5, 20)
        expiries = np.linspace(0.05, 1.0, 5)
        surf = surface_grid(p, strikes, expiries)
        assert surf.shape == (5, 20)
        assert np.all(surf > 0)


class TestSyntheticData:
    def test_independent_surfaces(self):
        data = generate_independent_surfaces(n_surfaces=10, n_strikes=10, n_expiries=5)
        assert data.surfaces.shape == (10, 5, 10)
        assert data.params.shape == (10, 4)

    def test_generate_paths(self):
        data = generate_paths(n_paths=2, n_steps=10, n_strikes=10, n_expiries=5, seed=42)
        assert data.surfaces.shape == (20, 5, 10)
        assert data.path_id is not None
        assert len(np.unique(data.path_id)) == 2


class TestArbitrageDetection:
    def test_arbitrage_report_on_synthetic(self):
        data = generate_independent_surfaces(n_surfaces=5, n_strikes=15, n_expiries=5)
        strikes = np.linspace(-0.5, 0.5, 15)
        expiries = np.linspace(0.05, 1.0, 5)
        report = arbitrage_report(data.surfaces[0], strikes, expiries)
        assert "calendar_spread_violations" in report
        assert "butterfly_violations" in report
        assert "arbitrage_free" in report


class TestMetrics:
    def test_surface_rmse_identical(self):
        surf = np.random.randn(5, 20).astype(np.float32)
        rmse = surface_rmse(surf, surf)
        assert rmse == 0.0

    def test_surface_rmse_different(self):
        a = np.zeros((5, 20), dtype=np.float32)
        b = np.ones((5, 20), dtype=np.float32)
        rmse = surface_rmse(a, b)
        assert rmse > 0


class TestAdapter:
    def test_adapter_generate_synthetic(self):
        adapter = VolSurfaceAdapter(n_strikes=10, n_expiries=5)
        surfaces = adapter.generate_synthetic_surfaces(n_surfaces=5, seed=42)
        assert len(surfaces) == 5
        assert "params" in surfaces[0]

    def test_adapter_status(self):
        adapter = VolSurfaceAdapter()
        status = adapter.get_status()
        assert status["n_strikes"] == 20
        assert status["n_expiries"] == 5


@pytest.mark.skipif(not TORCH_AVAILABLE, reason="torch not installed")
class TestTorchModels:
    def test_reconstruction_mlp_forward(self):
        from models.volatility_surface.models import ReconstructionMLP
        model = ReconstructionMLP()
        x = torch.randn(10, 4)
        out = model(x)
        assert out.shape == (10,)

    def test_forecast_gru_forward(self):
        from models.volatility_surface.models import ForecastGRU
        model = ForecastGRU()
        x = torch.randn(4, 20, 4)
        out = model(x)
        assert out.shape == (4, 4)
