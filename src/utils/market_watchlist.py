from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

from utils.crypto_market_intelligence import DEFAULT_CRYPTO_KEYWORDS
from utils.polymarket_client import PolymarketClient

DEFAULT_WATCHLIST = [
    "BTC",
    "ETH",
    "SOL",
    "TRUMP",
    "META",
    "XRP",
    "DOGE",
    "HYPE",
    "BNB",
]

WATCHLIST_CONFIG_PATH = Path("config/polymarket_watchlist.json")


def load_static_watchlist() -> list[str]:
    if not WATCHLIST_CONFIG_PATH.exists():
        return DEFAULT_WATCHLIST.copy()

    try:
        payload = json.loads(WATCHLIST_CONFIG_PATH.read_text())
    except Exception:
        return DEFAULT_WATCHLIST.copy()

    tickers = payload.get("tickers", DEFAULT_WATCHLIST)
    return _normalize_unique(tickers) or DEFAULT_WATCHLIST.copy()


def load_category_watchlists() -> dict[str, list[str]]:
    if not WATCHLIST_CONFIG_PATH.exists():
        return {}

    try:
        payload = json.loads(WATCHLIST_CONFIG_PATH.read_text())
    except Exception:
        return {}

    categories = payload.get("categories", {})
    if not isinstance(categories, dict):
        return {}

    normalized: dict[str, list[str]] = {}
    for category, tickers in categories.items():
        normalized[str(category).strip().lower()] = _normalize_unique(tickers)
    return normalized


def discover_active_watchlist(limit: int = 100, categories: Iterable[str] | None = None) -> list[str]:
    client = PolymarketClient()
    try:
        markets = client.list_markets(limit=limit, sort_by="volume")
    finally:
        client.close()

    requested_categories = {
        str(category).strip().lower()
        for category in (categories or DEFAULT_CRYPTO_KEYWORDS.keys())
        if str(category).strip()
    }

    discovered: list[str] = []
    for market in markets:
        text = f"{market.slug} {market.question} {market.description}".lower()
        for asset, keywords in DEFAULT_CRYPTO_KEYWORDS.items():
            if asset.lower() in requested_categories and any(_contains_keyword(text, keyword) for keyword in keywords):
                discovered.append(asset)
        if len(discovered) >= limit:
            break

    return _normalize_unique(discovered)


def get_polymarket_watchlist(
    limit: int = 100,
    categories: Iterable[str] | None = None,
    auto_discover_only: bool | None = None,
) -> list[str]:
    categories = list(categories or [])
    config = _load_config()
    if auto_discover_only is None:
        auto_discover_only = str(os.getenv("POLYMARKET_WATCHLIST_AUTO_ONLY", "")).lower() in {"1", "true", "yes", "on"}

    if not categories:
        categories = config.get("categories_order") or list(DEFAULT_CRYPTO_KEYWORDS.keys())

    active_watchlist = discover_active_watchlist(limit=limit, categories=categories)
    if auto_discover_only:
        return active_watchlist

    config_watchlist = load_static_watchlist()
    category_watchlist = []
    categories_map = load_category_watchlists()
    for category in categories:
        category_watchlist.extend(categories_map.get(str(category).lower(), []))

    merged = active_watchlist + category_watchlist + config_watchlist
    return _normalize_unique(merged)


def _load_config() -> dict:
    if not WATCHLIST_CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(WATCHLIST_CONFIG_PATH.read_text())
    except Exception:
        return {}


def _normalize_unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        item = str(value).upper().strip()
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _contains_keyword(text: str, keyword: str) -> bool:
    token = keyword.lower()
    return token in text
