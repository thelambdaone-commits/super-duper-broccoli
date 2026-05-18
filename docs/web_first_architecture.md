# Web-First Ingestion Architecture

This repository now uses a web-first data path for Polymarket market discovery,
order-book snapshots, and terminal/webhook-friendly output formatting.

## Core Modules

```text
scrapers/
  web_scraper.py       # Gamma API polling for market-level events
  clob_listener.py     # CLOB WebSocket parsing for order-book snapshots

utils/
  feature_store.py     # DuckDB-backed persistence for web events and features
  output_formatter.py  # Markdown-compatible telemetry formatting
  credential_manager.py# Ephemeral CLOB sessions and encrypted wallet utilities
  vault_handler.py     # Secret loading into process memory
```

## Runtime Behavior

### `WebScraper`

[`scrapers/web_scraper.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scrapers/web_scraper.py)
polls the Polymarket Gamma API and detects:

- first-seen markets
- volume changes above `min_volume_delta`
- transitions to closed/resolved markets
- active/inactive state changes

Detected events can be persisted to `FeatureStore.record_web_event()` and also
forwarded to an async callback.

### `CLOBListener`

[`scrapers/clob_listener.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/scrapers/clob_listener.py)
parses raw websocket payloads into normalized snapshots with:

- best bid / best ask
- mid price
- spread in bps
- depth over the first 3 levels
- order imbalance

Snapshots are written to:

- `FeatureStore.record_feature()` for derived metrics
- `FeatureStore.record_web_event()` for raw event retention

### `OutputFormatter`

[`utils/output_formatter.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/output_formatter.py)
produces plain text output suitable for terminals and webhook sinks. The current
code intentionally avoids Telegram-specific escaping and keeps a backward
compatible alias:

```python
from utils.output_formatter import OutputFormatter, TelegramOutputFormatter

assert TelegramOutputFormatter is OutputFormatter
```

## Import Map

```python
from scrapers.web_scraper import WebScraper, WebScraperConfig
from scrapers.clob_listener import CLOBListener, CLOBListenerConfig
from utils.output_formatter import OutputFormatter, TelegramOutputFormatter
from utils.feature_store import FeatureStore
```

## Configuration

Environment variables used by the current implementation:

```text
POLYMARKET_GAMMA_API_URL=https://gamma-api.polymarket.com
POLYMARKET_CLOB_WS_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market
DATA_PATH=user_data/data
```

Default polling settings:

- `WebScraperConfig.poll_interval_seconds = 2.0`
- `WebScraperConfig.market_limit = 100`
- `WebScraperConfig.timeout_seconds = 5.0`
- `WebScraperConfig.min_volume_delta = 1.0`
- `CLOBListenerConfig.reconnect_delay_seconds = 1.0`
- `CLOBListenerConfig.heartbeat_seconds = 15.0`

## Secret And Wallet Policy

- `CredentialManager.derive_ephemeral_clob_session()` returns a RAM-only CLOB session.
- `CredentialManager.destroy_secret_map()` clears mutable secret dictionaries after use.
- `CredentialManager.get_or_generate_creds()` and `save_private_key()` still persist
  encrypted material when explicitly invoked.
- The web-first ingest path should prefer ephemeral session derivation at process start.

## Feature Store Notes

[`utils/feature_store.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/utils/feature_store.py)
persists web data to DuckDB tables including:

- `web_events_raw`
- `features_computed`
- `market_microstructure`

The tests covering this architecture currently live in
[`tests/test_web_scraping_architecture.py`](/home/ogj9f33gvvzc/quant-agentic-trading-core-v2/tests/test_web_scraping_architecture.py).

## Example

```python
from scrapers.web_scraper import WebScraper
from scrapers.clob_listener import CLOBListener
from utils.feature_store import FeatureStore

store = FeatureStore()
scraper = WebScraper(store=store)
listener = CLOBListener(store=store)
```
