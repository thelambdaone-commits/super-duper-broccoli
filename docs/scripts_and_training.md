# Scripts and Training

This repository includes a few operational scripts that drive training,
feedback, and diagnostics.

## Training

[`scripts/train_all.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scripts/train_all.py)
is the main model-training entry point.

What it does:

- generates or loads feature data
- trains across a ticker set
- performs walk-forward validation
- records results to JSONL/JSON tracking files
- selects the top-performing configurations

Useful defaults:

- tickers: `SOL`, `BTC`, `ETH`, `LINK`, `ARB`, `OP`
- features: `oi_5min`, `tam_state`, `spread_bps`, `mid_price`
- target: `mid_price`

## Reinforcement Feedback

[`scripts/rl_feedback_loop.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scripts/rl_feedback_loop.py)
reads closed paper positions from the ledger and updates simple bias weights.

Behavior:

- increases bias after wins
- decreases bias after losses
- stores a running `ml_weights.json`
- archives deviation reports for failed trades

## Other Operational Scripts

Additional script entry points in the repo include:

- `scripts/backtest_simulation.py`
- `scripts/simulate_trades.py`
- `scripts/crypto_market_intelligence.py`
- `scripts/sync_optional_vault_keys.py`
- `scripts/discover_free_ai_providers.py`
- `scripts/dump_project.py`
- `scripts/project_memory.py`
- `scripts/llm_council.py`

## Notes

- Training scripts usually depend on `FeatureStore`.
- The feedback loop depends on the ledger and closed paper positions.
- These scripts are maintenance and research tools, not the main production order path.

