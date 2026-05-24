# Utilities Reference

This page groups smaller support modules that are used across the runtime but
do not warrant separate subsystem pages.

## Signal Utilities

- [`utils/signal_parser.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/signal_parser.py)
  parses deterministic signal strings like `BUY BTC @ 0.50` and a looser
  semantic fallback.
- [`utils/signal_generator.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/signal_generator.py)
  builds indicator-driven `TradingSignal` objects and caches them by asset and
  timeframe.

## Market Utilities

- [`utils/market_scanner.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/market_scanner.py)
  scans Polymarket markets for trending, competitive, and arbitrage-like setups.
- [`utils/market_discovery.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/market_discovery.py)
  and [`utils/market_data_reader.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/market_data_reader.py)
  provide supporting market lookup and data access helpers.

## Wallet Utilities

- [`utils/wallet_manager.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/wallet_manager.py)
  reads Polygon balances and produces wallet snapshots.
- [`utils/credential_manager.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/credential_manager.py)
  handles encrypted wallet and CLOB credential storage.
- [`utils/derive_clob_creds.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/derive_clob_creds.py)
  derives CLOB API credentials from a private key.

## UX And Help

- [`utils/help_manager.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/help_manager.py)
  renders Telegram help pages and inline navigation.
- [`utils/message_formatter.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/message_formatter.py)
  formats institutional-style alerts and trade confirmations.
- [`utils/notifier.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/notifier.py)
  provides outbound notification helpers.

## Shared Infrastructure

- [`utils/access_control.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/access_control.py)
- [`utils/config_loader.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/config_loader.py)
- [`utils/logging_setup.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/logging_setup.py)
- [`utils/project_context.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/project_context.py)
- [`utils/prompt_memory.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/prompt_memory.py)
- [`utils/rpc_provider.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/rpc_provider.py)
- [`utils/security_utils.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/security_utils.py)

## Notes

These helpers are intentionally not split into individual pages:

- they are small and composable
- they mostly support the larger runtime surfaces already documented
- they change more often than the major subsystem contracts
