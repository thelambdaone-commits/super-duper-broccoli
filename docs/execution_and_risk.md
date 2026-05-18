# Execution and Risk

This repo uses a staged execution model with explicit risk gates.

## Risk Engine

[`core/portfolio_risk_engine.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/portfolio_risk_engine.py)
computes size recommendations from:

- Kelly sizing
- regime multiplier
- volatility targeting
- concentration caps
- correlated drawdown caps
- trailing drawdown protection

Important behavior:

- `ERRATIC_VOLATILITY` is blocked outright.
- `compute_position_size()` returns a structured result with a `reason`.
- The engine uses the ledger for capital and exposure context.
- `book_exposure()` and `rehydrate_from_ledger()` keep internal exposure state aligned with open positions.

## Execution Modes

The runtime recognizes four execution modes:

- `REPLAY`
- `PAPER`
- `SHADOW`
- `PROD`

These modes are surfaced through the ledger, the API, and the MCP server.

## Execution Path

The main execution path is organized around:

- signal ingestion
- risk validation
- ledger authorization and reservation
- maker-first execution where possible
- fallback handling through the executor layer

Relevant modules:

- [`execution/passive_executor.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/execution/passive_executor.py)
- [`core/signal_executor.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/core/signal_executor.py)
- [`ledger/ledger_db.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/ledger/ledger_db.py)

## Safety Constraints

- Production trading is gated by the `PROD` mode and ledger authorization.
- The circuit breaker can freeze outbound orders.
- Position sizing should never bypass the risk engine.
- The current architecture expects maker-first behavior, not blind market execution.

