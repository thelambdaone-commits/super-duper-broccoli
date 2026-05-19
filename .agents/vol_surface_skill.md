# Volatility Surface SSVI Skill

## Purpose
Model, reconstruct and forecast implied volatility surfaces using SSVI parameterization and neural networks (MLP + GRU). Generate synthetic surfaces for training, detect arbitrage violations, and feed vol surface features into the trading pipeline.

## Triggers
- `/vol status` — Check module status
- `/vol synthetic --n 100` — Generate synthetic surfaces
- `/vol arbitrage --surface ...` — Check arbitrage violations

## Execution Steps
1. Load `VolSurfaceAdapter` from `models/volatility_surface.adapter`
2. Use `generate_synthetic_surfaces()` for training data
3. Use `ReconstructionMLP` for surface reconstruction from sparse quotes
4. Use `ForecastGRU` for next-day parameter prediction
5. Use `arbitrage_report()` to validate no-arbitrage conditions
6. Store SSVI parameters and metrics in FeatureStore

## Behavioral Boundaries
- SSVI requires at minimum 3 expiries and 5 strikes for meaningful surface
- Arbitrage-free guarantee requires rho in (-1, 1), gamma in (0, 0.5]
- Do NOT use synthetic surfaces for real risk calculations without empirical validation
