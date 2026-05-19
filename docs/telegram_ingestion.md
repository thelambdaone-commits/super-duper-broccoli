# 🤖 Lobstar Telegram Subsystem Guide

This document outlines the architecture, directory structure, dynamic command registry, and instructions for adding new commands to the institutional Telegram Bot.

## 📂 Subsystem Directory Layout

The Telegram subsystem is strictly organized for high modularity to prevent files from growing too large:

```text
telegram_scraper/
├── __init__.py
├── telegram_listener.py       # Core Telegram bot bootstrap, authorization & start/stop cycle.
├── command_router.py          # Centralized registry & dispatcher routing commands dynamically.
└── handlers/                  # Modular functional command handlers
    ├── __init__.py
    ├── markets_handler.py     # Crypto horizon & active markets displays (/btc, /btc5, etc.)
    ├── polymarket_handler.py  # Polymarket bets, CLOB orders & statistics (/polymarket, /clob)
    ├── signals_handler.py     # Signal generations & paper test executions (/signals, /paper)
    ├── system_handlers.py     # Devops, MCP, audits & system health (/mcp, /dev, /audit)
    ├── transfer_handler.py    # Funds transfers & proxy wallet allocations (/transfer)
    └── wallet_handler.py      # Wallet creation, balances & PK imports (/wallet, /gen, /import)
```

---

## ⚡ Centralized Command Registry (`COMMAND_REGISTRY`)

Commands are declared dynamically in the centralized `COMMAND_REGISTRY` mapping located inside [command_router.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/telegram_scraper/command_router.py).

Each entry defines:
- **`func`**: The exact handler method name (implemented in `CommandRouter`).
- **`category`**: The permission and categorization layer (`ADMIN`, `TRADING`, `MARKETS`, `WALLET`, `DEVOPS`).
- **`description`**: A human-friendly explanation.
- **`usage`**: The command syntax signature.
- **`example`**: An operational example.
- **`notes`**: Important tips or advice.

Example registry entry:
```python
    "wallet": {
        "func": "_cmd_wallet",
        "category": "WALLET",
        "description": "Gérer les portefeuilles, soldes et transferts.",
        "usage": "/wallet",
        "example": "/wallet",
        "notes": "Affiche le cockpit des portefeuilles et balances configurés."
    }
```

This registry is also used by the **Dynamic Manual System** (`/man <command>`) to auto-generate fully detailed premium help pages for any command!

---

## 🧪 How to Add a New Command

Adding a new command is fully modular and takes only 3 simple steps:

### 1. Declare the Command in the Registry
Open [command_router.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/telegram_scraper/command_router.py) and add your command details to `COMMAND_REGISTRY`:
```python
    "mycmd": {
        "func": "_cmd_mycmd",
        "category": "DEVOPS",
        "description": "Short description of what it does.",
        "usage": "/mycmd <arg>",
        "example": "/mycmd test",
        "notes": "Administrative notes here."
    }
```

### 2. Implement the Command Route Method
In `CommandRouter` (inside [command_router.py](file:///home/ogj9f33gvvzc/quant-agentic-trading-core-v2/telegram_scraper/command_router.py)), implement the routing method matching the `func` name:
```python
    async def _cmd_mycmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not await self.listener._check_admin_auth(update): return

        # Call the modular handler code
        from telegram_scraper.handlers.system_handlers import handle_mycmd
        await handle_mycmd(update, context, self.listener)
```

### 3. Implement the Handler Logic
Create the corresponding handler function inside the appropriate module in `telegram_scraper/handlers/` (e.g. `system_handlers.py`):
```python
async def handle_mycmd(update, context, listener):
    # Your beautiful premium logic here!
    await listener.reply_to("🚀 Executed successfully!", update)
```

---

## 🔒 Authorization & Access Levels

Access control is strictly checked before executing any commands:
1. **Public/User**: Public commands allowed for everyone.
2. **Authorized (`_check_auth`)**: Restricts access based on `TELEGRAM_PRIVATE_CHAT_IDS`.
3. **Admin (`_check_admin_auth`)**: Requires admin credentials to perform sensitive operations (e.g. trading, PK import).
