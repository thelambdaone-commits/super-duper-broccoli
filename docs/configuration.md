# Configuration

The repo has a small set of hard-coded constants and a broader secret-loading
layer for runtime configuration.

## Constants

[`config/constants.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/config/constants.py)
defines the main runtime constants:

- regime labels
- regime sizing multipliers
- execution modes
- fusion modes
- maker timeout and websocket reconnect defaults

## Secret Loading

[`utils/vault_handler.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/vault_handler.py)
loads secrets from either:

- HashiCorp Vault
- environment variables
- encrypted local files, depending on `SECRET_SOURCE` and local state

Required secrets:

- `CLOB_PRIVATE_KEY`
- `CLOB_API_KEY`
- `CLOB_API_SECRET`
- `CLOB_API_PASSPHRASE`

Common optional secrets include:

- `TELEGRAM_BOT_TOKEN`
- `GROQ_API_KEY`
- `OPENROUTER_API_KEY`
- RPC URLs such as `POLYGON_RPC_URL` and `ETH_RPC_URL`
- Polymarket endpoints such as `POLYMARKET_GAMMA_API_URL`

## Practical Defaults

- `POLYMARKET_GAMMA_API_URL` defaults to `https://gamma-api.polymarket.com`
- `POLYMARKET_CLOB_HTTP_URL` defaults to `https://clob.polymarket.com`
- `POLYMARKET_CLOB_WS_URL` defaults to `wss://ws-subscriptions-clob.polymarket.com/ws/market`
- `EXECUTION_MODES` is fixed to `REPLAY`, `PAPER`, `SHADOW`, `PROD`

## Operational Notes

- If Vault is disabled or unavailable, the code can fall back to environment-driven loading.
- Wallet credential derivation is based on the private key and should be treated as sensitive.
- Configuration is intentionally mixed: some values are constants, others are runtime secrets.

