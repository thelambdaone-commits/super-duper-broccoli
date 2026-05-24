# API and MCP Surface

This repository exposes two thin surfaces over the same runtime state:

- a FastAPI HTTP API in `api/api_server.py`
- an MCP server in `mcp_agents/mcp_server.py`

Both are wired to the same underlying ledger, HMM regime filter, risk engine,
feature store, executor, and arbitrage scanner.

## HTTP API

[`api/api_server.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/api/api_server.py)
bootstraps the runtime through `ServiceContainer` and exposes versioned routes
under `/v1`.

Notable endpoints:

- `GET /health`
- `GET /v1/ledger`
- `GET /v1/regime`
- `POST /v1/circuit-breaker`
- `POST /v1/execution-mode`
- `GET /v1/execution-mode`
- `GET /v1/executor/metrics`
- `GET /v1/arbitrage`
- `POST /v1/arbitrage/scan-mispricing`
- `POST /v1/sentiment`
- `POST /v1/sentiment/batch`
- `GET /v1/feature-store`
- `GET /v1/features/{ticker}/{feature_name}`
- `GET /v1/pnl/summary`
- `GET /v1/pnl/history`
- `GET /v1/pnl/positions`
- `GET /v1/market-intelligence/crypto`

## MCP Server

[`mcp_agents/mcp_server.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/mcp_agents/mcp_server.py)
registers tools over `FastMCP` after `initialize(...)` is called with the live
runtime components.

Core tool groups:

- ledger and capital state
- HMM market regime and circuit breaker control
- execution mode and executor metrics
- arbitrage and feature-store access
- AI specialist lookup and project prompt memory
- a small set of dynamic agent-skills wrappers

## Shared Runtime Contract

The two surfaces are intentionally stateful and expect initialized objects:

- `Ledger`
- `HMMRegimeFilter`
- `PortfolioRiskEngine`
- `FeatureStore`
- `PassiveExecutor`
- `ArbitrageScanner`

If they are not initialized, the handlers return `503` at the API layer or a
structured error object at the MCP helper layer.

## Operational Notes

- `POST /v1/circuit-breaker` can freeze outbound trading.
- `POST /v1/execution-mode` accepts `REPLAY`, `PAPER`, `SHADOW`, `PROD`.
- The API lifespan handler also initializes MCP so both surfaces stay aligned.
- `GET /v1/market-intelligence/crypto` depends on both `PolymarketClient` and
  `CryptoMarketIntelligence`.

