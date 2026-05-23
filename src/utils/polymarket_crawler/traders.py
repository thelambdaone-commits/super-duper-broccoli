"""Trader and market scraper using official Polymarket APIs."""

import time
from dataclasses import dataclass, field
from typing import Any

import requests

from utils.polymarket_crawler.categorize import categorize

GAMMA_API_BASE = "https://gamma-api.polymarket.com"
DATA_API_BASE = "https://data-api.polymarket.com"

MAX_RETRIES = 3
RETRY_DELAY = 1.0
REQUEST_TIMEOUT = 15


@dataclass
class LeaderboardTrader:
    rank: int
    proxy_wallet: str
    user_name: str
    x_username: str
    verified_badge: bool
    volume: float
    pnl: float
    profile_image: str
    category: str = "OVERALL"


@dataclass
class MarketInfo:
    slug: str
    question: str
    condition_id: str
    liquidity: float
    volume: float
    end_date: str
    description: str
    image: str
    outcomes: list[dict]
    closed: bool
    category: str = "general"


@dataclass
class ClosedPosition:
    market_slug: str
    title: str
    side: str
    size: float
    avg_price: float
    realized_pnl: float
    outcome: str


@dataclass
class TradeRecord:
    market_slug: str
    side: str
    price: float
    size: float
    timestamp: str
    maker: str
    outcome: str


@dataclass
class EnrichedTrader:
    wallet: str
    name: str
    rank: int
    total_pnl: float
    total_volume: float
    category: str
    positions: list[ClosedPosition] = field(default_factory=list)
    trades: list[TradeRecord] = field(default_factory=list)
    top_markets: list[str] = field(default_factory=list)


class TraderScraper:
    def __init__(self):
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; PolymarketBot/1.0)",
            "Accept": "application/json",
        })

    def _request(self, method: str, url: str, **kwargs) -> Any:
        for attempt in range(MAX_RETRIES):
            try:
                resp = self._session.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except requests.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                print(f"[traders] request failed: {url} - {e}")
                return None

    def fetch_leaderboard(self, category: str = "OVERALL", time_period: str = "ALL", order_by: str = "PNL", limit: int = 50) -> list[LeaderboardTrader]:
        data = self._request(
            "GET",
            f"{DATA_API_BASE}/v1/leaderboard",
            params={"limit": limit, "timePeriod": time_period, "orderBy": order_by, "category": category},
        )
        if not data:
            return []
        traders = []
        for item in data:
            traders.append(LeaderboardTrader(
                rank=int(item.get("rank", 0)),
                proxy_wallet=str(item.get("proxyWallet", "")).lower(),
                user_name=str(item.get("userName", "")),
                x_username=str(item.get("xUsername", "")),
                verified_badge=bool(item.get("verifiedBadge", False)),
                volume=float(item.get("volume", 0) or 0),
                pnl=float(item.get("pnl", 0) or 0),
                profile_image=str(item.get("profileImage", "")),
                category=category,
            ))
        return traders

    def fetch_markets(self, closed: bool = False, limit: int = 50, tag: str = "") -> list[MarketInfo]:
        params: dict[str, Any] = {"closed": str(closed).lower(), "limit": limit}
        if tag:
            params["tag"] = tag
        data = self._request("GET", f"{GAMMA_API_BASE}/markets", params=params)
        if not data:
            return []
        markets = []
        for item in data:
            category = categorize(item.get("slug", ""), item.get("question", ""))
            markets.append(MarketInfo(
                slug=str(item.get("slug", "")),
                question=str(item.get("question", "")),
                condition_id=str(item.get("conditionId", "")),
                liquidity=float(item.get("liquidity", 0) or 0),
                volume=float(item.get("volume", 0) or 0),
                end_date=str(item.get("endDate", "")),
                description=str(item.get("description", "")),
                image=str(item.get("image", "")),
                outcomes=item.get("outcomes", []),
                closed=bool(item.get("closed", closed)),
                category=category,
            ))
        return markets

    def fetch_closed_positions(self, proxy_wallet: str, limit: int = 100) -> list[ClosedPosition]:
        data = self._request("GET", f"{DATA_API_BASE}/closed-positions", params={"user": proxy_wallet, "limit": limit})
        if not data:
            return []
        return [
            ClosedPosition(
                market_slug=str(item.get("slug", "")),
                title=str(item.get("title", "")),
                side=str(item.get("side", "")),
                size=float(item.get("size", 0) or 0),
                avg_price=float(item.get("avgPrice", 0) or 0),
                realized_pnl=float(item.get("realizedPnl", 0) or 0),
                outcome=str(item.get("outcome", "")),
            )
            for item in data
        ]

    def fetch_trades(self, proxy_wallet: str, limit: int = 100) -> list[TradeRecord]:
        data = self._request("GET", f"{DATA_API_BASE}/trades", params={"user": proxy_wallet, "limit": limit})
        if not data:
            return []
        return [
            TradeRecord(
                market_slug=str(item.get("market", "")),
                side=str(item.get("side", "")),
                price=float(item.get("price", 0) or 0),
                size=float(item.get("size", 0) or 0),
                timestamp=str(item.get("timestamp", "")),
                maker=str(item.get("maker", "")).lower(),
                outcome=str(item.get("outcome", "")),
            )
            for item in data
        ]

    def enrich_trader(self, trader: LeaderboardTrader, max_positions: int = 50, max_trades: int = 100) -> EnrichedTrader:
        positions = self.fetch_closed_positions(trader.proxy_wallet, max_positions)
        trades = self.fetch_trades(trader.proxy_wallet, max_trades)
        top_markets = list(dict.fromkeys(p.market_slug for p in positions if p.market_slug))[:10]
        return EnrichedTrader(
            wallet=trader.proxy_wallet,
            name=trader.user_name or trader.proxy_wallet[:8],
            rank=trader.rank,
            total_pnl=trader.pnl,
            total_volume=trader.volume,
            category=trader.category,
            positions=positions,
            trades=trades,
            top_markets=top_markets,
        )


def discover_top_traders(
    categories: list[str] | None = None,
    time_period: str = "ALL",
    order_by: str = "PNL",
    limit: int = 20,
    enrich: bool = True,
) -> dict[str, list[EnrichedTrader]]:
    if categories is None:
        categories = ["OVERALL", "SPORTS", "CRYPTO", "POLITICS"]
    scraper = TraderScraper()
    result: dict[str, list[EnrichedTrader]] = {}
    for cat in categories:
        print(f"[traders] fetching {cat} leaderboard...")
        traders = scraper.fetch_leaderboard(category=cat, time_period=time_period, order_by=order_by, limit=limit)
        enriched = []
        for t in traders:
            if enrich:
                et = scraper.enrich_trader(t)
                enriched.append(et)
                time.sleep(0.3)
            else:
                enriched.append(EnrichedTrader(
                    wallet=t.proxy_wallet,
                    name=t.user_name or t.proxy_wallet[:8],
                    rank=t.rank,
                    total_pnl=t.pnl,
                    total_volume=t.volume,
                    category=cat,
                ))
        result[cat] = enriched
        print(f"[traders] {cat}: {len(enriched)} traders")
    return result


def discover_active_markets(limit: int = 50, tag: str = "") -> list[MarketInfo]:
    return TraderScraper().fetch_markets(closed=False, limit=limit, tag=tag)


def run_discovery(
    categories: list[str] | None = None,
    market_limit: int = 20,
    trader_limit: int = 10,
    time_period: str = "ALL",
) -> str:
    from utils.polymarket_crawler.trader_formatters import fmt_discovery_report
    print("[traders] running full discovery...")
    markets = discover_active_markets(limit=market_limit)
    print(f"[traders] {len(markets)} active markets")
    results = discover_top_traders(categories=categories, time_period=time_period, limit=trader_limit)
    return fmt_discovery_report(results, markets)
