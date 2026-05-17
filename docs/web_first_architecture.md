# Web-First Ingestion Architecture

Canonical runtime modules:

```text
scrapers/
  web_scraper.py       # Polymarket Gamma/API event polling
  clob_listener.py     # Polymarket CLOB WebSocket order-book stream

utils/
  output_formatter.py  # Terminal/webhook-safe Markdown text blocks
  vault_handler.py     # Vault/env secret injection into process memory
  credential_manager.py# Ephemeral CLOB sessions and encrypted wallet utilities
```

Import mapping:

```python
from scrapers.web_scraper import WebScraper, WebScraperConfig
from scrapers.clob_listener import CLOBListener, CLOBListenerConfig
from utils.output_formatter import OutputFormatter
```

Legacy compatibility aliases still available during transition:

```python
from utils.output_formatter import TelegramOutputFormatter  # alias of OutputFormatter
```

Configuration:

```text
POLYMARKET_GAMMA_API_URL=https://gamma-api.polymarket.com
POLYMARKET_CLOB_HTTP_URL=https://clob.polymarket.com
POLYMARKET_CLOB_WS_URL=wss://ws-subscriptions-clob.polymarket.com/ws/market
```

Secret policy:

- Trading runtime requires CLOB credentials, not Telegram credentials.
- `VaultHandler.fetch_quantum_secrets()` injects CLOB keys and Polymarket endpoints into RAM.
- `CredentialManager.derive_ephemeral_clob_session()` derives a CLOB session without writing encrypted files.
- `CredentialManager.destroy_secret_map()` clears mutable secret dictionaries after use.
