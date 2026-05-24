# 🤖 Mets Telegram Scraper Guide

## 📂 Directory Layout

```text
scrappers/
├── __init__.py
└── mets_telegram_scraper.py
```

## 🔧 Configuration

Variables d'environnement dans `.env` :

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token du bot Telegram (@BotFather) |
| `METS_CHANNEL_IDS` | IDs des channels à scraper (virgule séparés) |
| `METS_KEYWORDS` | Mots-clés pour filtrer les messages |

## 🧪 Entités extraites automatiquement

- **game_mention** : `Mets vs Dodgers`, `NYM @ Yankees`
- **score** : `Mets 5-3`
- **odds** : `Mets +150`, `NYM -120`

## 🚀 Usage

```python
from scrappers.mets_telegram_scraper import MetsTelegramScraper

scraper = MetsTelegramScraper()
await scraper.run(callback=my_callback)
```
