# Telegram Ingestion

The Telegram path is still part of the runtime, even as the repository moves
toward more web-first market data ingestion.

## Listener

[`telegram_scraper/telegram_listener.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/telegram_scraper/telegram_listener.py)
handles:

- channel messages
- private chat messages
- command routing
- signal parsing
- message splitting and retry behavior

## Key Behaviors

- Commands such as `/help`, `/status`, `/mode`, and related operational commands are handled in the listener.
- Private chat handling can be restricted by `TELEGRAM_PRIVATE_CHAT_IDS`.
- `TELEGRAM_PRIVATE_ENABLED=0` disables private-message processing entirely.
- Telegram messages are parsed through deterministic and semantic paths before reaching execution components.

## Shared Helpers

Useful support modules:

- [`telegram_scraper/command_router.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/telegram_scraper/command_router.py)
- [`utils/signal_parser.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/signal_parser.py)
- [`utils/telegram_helpers.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/telegram_helpers.py)

## Output Formatting

Telegram-specific output is now less central than before. For system telemetry,
prefer the plain-text formatter in:

- [`utils/output_formatter.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/output_formatter.py)

## Operational Notes

- The listener keeps an internal queue for inbound messages.
- It can be attached to the ledger, risk engine, HMM filter, feature store,
  executor, scanner, and copy-trading agent.
- Authorization checks happen before sensitive commands or signals are accepted.

