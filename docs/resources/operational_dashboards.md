# Operational Dashboards

This page covers the user-facing and operational utilities that sit beside the
core trading runtime.

## Streamlit Dashboard

[`api/dashboard.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/api/dashboard.py)
renders the main operator view.

It displays:

- capital summary
- execution mode
- open positions
- feature-store row counts
- PnL summaries and closed positions
- sentiment analysis
- arbitrage scan controls
- execution mode controls

The dashboard is backed by the same `Ledger`, `FeatureStore`, `HMMRegimeFilter`,
`PortfolioRiskEngine`, `ArbitrageScanner`, and `SentimentAnalyzer` objects used
elsewhere in the runtime.

## Paper Execution

[`execution/paper_engine.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/execution/paper_engine.py)
simulates high-fidelity paper fills.

It models:

- latency
- market vs limit execution
- order-book parsing
- order imbalance
- maker fill probability
- look-ahead rejection

This is the simulation layer used for paper-style validation, not live order
routing.

## Event Pipeline

[`scrapers/data_pipeline.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scrapers/data_pipeline.py)
contains event archiving and a predictive opinion engine.

Important behavior:

- archives events to JSONL
- strips non-serializable update objects
- can produce a tool-aware OpenRouter-based opinion
- falls back to a mock analysis when credentials are unavailable

## Telegram Broadcasting

[`scrapers/telegram_broadcaster.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scrapers/telegram_broadcaster.py)
handles alert broadcast and deduplication.

It includes:

- token-bucket rate limiting
- per-signal deduplication memory
- cooldown management
- market resolution and opportunity formatting

## Health Probe

[`core/health_monitor.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/health_monitor.py)
exposes a minimal liveness endpoint for orchestrator and runner status.

It is intended for operational checks, not trade logic.

