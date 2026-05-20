# Tensor Hybrid Architecture Implementation

## Summary

Implemented a CPU-first optional tensor scoring boundary for Polymarket ML while keeping final risk and sizing deterministic.

## Changes

- Added `UnifiedScoringOutput` as the strict scalar contract for ML scoring output.
- Added `HybridQuantModelAdapter` with optional `torch` loading, CPU-only inference, tensor-path validation, and deterministic NumPy fallback.
- Kept `PortfolioRiskEngine` scalar and deterministic.
- Added scalar risk handling for degraded ML signals:
  - reject `ood_alert=True`
  - reject fallback signals when `predictive_edge` is below the stricter fallback threshold
  - penalize confidence for accepted fallback signals

## Validation

Added `tests/test_tensor_hybrid_architecture.py` covering:

- empty feature vectors
- NaN and Inf feature vectors
- wrong feature dimensions
- valid CPU tensor inference when `torch` is available
- fallback edge gating in the risk engine
- sizing parity between tensor and fallback scoring contracts
- single-trade adapter latency budget

## Runtime Boundary

`torch` remains optional. The bot can start without it and will use the deterministic fallback path.

The sizing engine does not import or consume `torch.Tensor` objects. It only consumes scalar fields derived from `UnifiedScoringOutput`.
