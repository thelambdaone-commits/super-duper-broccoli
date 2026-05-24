# Ledger and Wallets

This repo splits capital accounting from wallet storage.

## Ledger

[`ledger/ledger_db.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/ledger/ledger_db.py)
persists the runtime state in SQLite.

Key responsibilities:

- capital allocation
- open positions
- transactions
- paper positions
- execution mode
- performance metrics

Important behaviors:

- `validate_and_reserve()` checks available capital before orders are persisted.
- `record_order()` writes live orders and deducts capital atomically.
- `record_paper_order()` stores simulated trades for REPLAY/PAPER flows.
- `set_execution_mode()` only accepts the configured execution modes.

## Wallets

The wallet and credential path is handled by:

- [`utils/credential_manager.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/credential_manager.py)
- [`utils/vault_handler.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/vault_handler.py)

Behavior to know:

- credentials can be derived from a private key
- ephemeral CLOB sessions can be created in RAM only
- user wallets may be stored encrypted on disk when explicitly requested
- the active wallet and configured wallets are managed through encrypted files under `DATA_PATH`

## Safety Notes

- The ledger is the source of truth for authorization and reservation.
- Do not bypass ledger checks in execution code.
- Wallet data should remain encrypted unless the flow explicitly requests an ephemeral in-memory session.

