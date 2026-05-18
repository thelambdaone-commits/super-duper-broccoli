# Core Orchestration

The `core/` package contains the main orchestration and learning control plane.

## Orchestrator

[`core/orchestrator.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/orchestrator.py)
coordinates:

- signal ingestion queueing
- circuit-breaker enforcement
- snapshot capture
- predictive gating
- cognitive-brain execution
- execution confirmation and cleanup

Operational notes:

- signals are queued asynchronously
- queue saturation triggers warnings
- execution results are confirmed back to the listener or sender
- the orchestrator can broadcast signals and risk alerts

## Training Pipeline

[`core/training_pipeline.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/training_pipeline.py)
builds and validates ML models from `FeatureStore` data.

Key behaviors:

- point-in-time feature alignment
- chronological train/validation splitting
- walk-forward validation
- hybrid model training
- optional calibration persistence

The pipeline is tied to `user_data/freqaimodels/HybridQuantModel.py` and
`user_data/strategies/probability_calibrator.py`.

## Related Core Modules

- [`core/signal_executor.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/signal_executor.py)
- [`core/portfolio_risk_engine.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/portfolio_risk_engine.py)
- [`core/freqai_engine.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/freqai_engine.py)
- [`core/strategy_manager.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/strategy_manager.py)

## Predictive Models

[`models/predictive_engine.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/models/predictive_engine.py)
contains the `PolymarketPredictiveEngine`.

What it does:

- predicts win probability from market ticks
- applies optional calibration
- applies time decay toward resolution
- computes whether the edge clears a minimum threshold
- calculates Kelly sizing from the calibrated output

Important behaviors:

- if no model is loaded and mock predictions are disabled, it rejects the trade
- if mock predictions are enabled, it can generate simulated outputs for testing
- inference statistics are tracked in-memory

## Loading

The engine can load:

- a `HybridQuantModel`
- a `ProbabilityCalibrator`

by scanning the `user_data/models/` directory or by explicit paths.

## Market Monitoring

[`monitors/polymarket_monitor.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/monitors/polymarket_monitor.py)
listens to websocket transaction streams and tries to decode matching orders.

Key behaviors:

- subscribes to a websocket endpoint from `WS_URL`
- falls back across subscription methods
- filters by target wallet when configured
- decodes the matching-order calldata signature
- emits copy-trade style signals through a callback

Relevant environment variables:

- `WS_URL`
- `POLYGON_RPC_URL`
- `RPC_URL`
- `MATCH_ORDERS_SIGNATURE`

The monitor is best-effort and can disable itself on authorization failures.
