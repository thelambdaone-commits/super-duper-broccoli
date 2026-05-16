from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger("PolymarketClient")

GAMMA_BASE = "https://gamma-api.polymarket.com"
CLOB_BASE = "https://clob.polymarket.com"
CACHE_TTL = 300

_TIMEOUT = httpx.Timeout(10.0)


@dataclass
class OrderBookLevel:
    price: float
    size: float


@dataclass
class OrderBook:
    bids: list[OrderBookLevel] = field(default_factory=list)
    asks: list[OrderBookLevel] = field(default_factory=list)


@dataclass
class Market:
    condition_id: str
    slug: str
    question: str
    description: str
    outcomes: list[str]
    outcome_prices: list[float]
    tokens: list[dict[str, Any]]
    active: bool
    closed: bool
    volume: float = 0.0
    liquidity: float = 0.0
    end_date: str = ""
    fee_rate_bps: int = 0
    tick_size: float = 0.01
    tags: list[str] = field(default_factory=list)

    def get_token_id(self, outcome: str) -> str:
        outcome_lower = outcome.lower()
        for token in self.tokens:
            if token.get("outcome", "").lower() == outcome_lower:
                return token["token_id"]
        raise ValueError(f"No token found for outcome {outcome!r}")

    @property
    def yes_token_id(self) -> str:
        return self.get_token_id("yes")

    @property
    def no_token_id(self) -> str:
        return self.get_token_id("no")

    @property
    def yes_price(self) -> float:
        for i, outcome in enumerate(self.outcomes):
            if outcome.lower() == "yes":
                return self.outcome_prices[i]
        return 0.0

    @property
    def no_price(self) -> float:
        for i, outcome in enumerate(self.outcomes):
            if outcome.lower() == "no":
                return self.outcome_prices[i]
        return 0.0

    @property
    def spread(self) -> float:
        return abs(self.yes_price - self.no_price)

    @property
    def is_yes_winning(self) -> bool:
        return self.yes_price >= 0.80

    @property
    def is_no_winning(self) -> bool:
        return self.no_price >= 0.80

    @property
    def is_competitive(self) -> bool:
        return 0.30 <= self.yes_price <= 0.70

    @property
    def winning_outcome(self) -> str | None:
        if self.yes_price >= 0.99:
            return "YES"
        if self.no_price >= 0.99:
            return "NO"
        return None

    @property
    def probability_pct(self) -> float:
        return max(self.yes_price, self.no_price) * 100


class PolymarketClient:
    def __init__(self) -> None:
        self._http = httpx.Client(timeout=_TIMEOUT)
        self._cache: dict[str, tuple[float, Any]] = {}

    def close(self) -> None:
        self._http.close()

    def _cache_get(self, key: str) -> Any | None:
        entry = self._cache.get(key)
        if entry is None:
            return None
        ts, data = entry
        if time.time() - ts > CACHE_TTL:
            del self._cache[key]
            return None
        return data

    def _cache_set(self, key: str, data: Any) -> None:
        self._cache[key] = (time.time(), data)

    def _gamma_get(self, path: str, params: dict | None = None) -> list | dict:
        url = f"{GAMMA_BASE}{path}"
        try:
            resp = self._http.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"Gamma API error: {e.response.status_code} {e.response.text[:200]}")
            return []
        except httpx.RequestError as e:
            logger.error(f"Gamma API request failed: {e}")
            return []

    def _clob_get(self, path: str, params: dict | None = None) -> dict | list:
        url = f"{CLOB_BASE}{path}"
        try:
            resp = self._http.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error(f"CLOB API error: {e.response.status_code} {e.response.text[:200]}")
            return {}
        except httpx.RequestError as e:
            logger.error(f"CLOB API request failed: {e}")
            return {}

    def list_markets(self, limit: int = 20, sort_by: str = "volume") -> list[Market]:
        params = {"limit": limit, "active": "true", "closed": "false"}
        if sort_by == "volume":
            params["order"] = "volume"
            params["ascending"] = "false"
        elif sort_by == "liquidity":
            params["order"] = "liquidity"
            params["ascending"] = "false"

        data = self._gamma_get("/markets", params=params)
        if not isinstance(data, list):
            return []
        return [_parse_market(m) for m in data if _has_condition_id(m)]

    def search_markets(self, query: str, limit: int = 10) -> list[Market]:
        data = self._gamma_get("/markets", params={"_q": query, "limit": limit})
        if not isinstance(data, list):
            return []
        return [_parse_market(m) for m in data if _has_condition_id(m)]

    def get_tags(self) -> list[dict]:
        cache_key = "tags:all"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        data = self._gamma_get("/tags")
        if not isinstance(data, list):
            return []
        self._cache_set(cache_key, data)
        return data

    def get_market(self, slug_or_id: str) -> Market | None:
        cache_key = f"market:{slug_or_id}"
        cached = self._cache_get(cache_key)
        if cached is not None:
            return _parse_market(cached)

        data = self._gamma_get("/markets", params={"slug": slug_or_id})
        if isinstance(data, list) and len(data) > 0:
            self._cache_set(cache_key, data[0])
            return _parse_market(data[0])
        if isinstance(data, dict) and _has_condition_id(data):
            self._cache_set(cache_key, data)
            return _parse_market(data)

        if slug_or_id.startswith("0x"):
            try:
                clob_data = self._clob_get(f"/markets/{slug_or_id}")
                if isinstance(clob_data, dict) and clob_data.get("condition_id"):
                    market = _parse_clob_market(clob_data)
                    if market.slug:
                        gamma_data = self._gamma_get("/markets", params={"slug": market.slug})
                        if isinstance(gamma_data, list) and len(gamma_data) > 0:
                            self._cache_set(cache_key, gamma_data[0])
                            return _parse_market(gamma_data[0])
                    self._cache_set(cache_key, clob_data)
                    return market
            except Exception:
                pass

        logger.warning(f"Market not found: {slug_or_id}")
        return None

    def get_order_book(self, token_id: str) -> OrderBook:
        data = self._clob_get("/book", params={"token_id": token_id})
        return _parse_order_book(data)

    def get_midpoint(self, token_id: str) -> float:
        data = self._clob_get("/midpoint", params={"token_id": token_id})
        return float(data.get("mid", 0.0)) if isinstance(data, dict) else 0.0

    def get_markets_by_tag(
        self, tag_slug: str, limit: int = 20, closed: bool = False
    ) -> list[Market]:
        params = {
            "tag_slug": tag_slug,
            "limit": limit,
            "closed": str(closed).lower(),
            "active": str(not closed).lower(),
        }
        data = self._gamma_get("/markets", params=params)
        if not isinstance(data, list):
            return []
        return [_parse_market(m) for m in data if _has_condition_id(m)]

        self._cache_set(cache_key, data)
        return data

    def deep_scrape_market(self, slug: str) -> Optional[str]:
        """Uses Scrapling to fetch deep market rules and context from the web UI."""
        try:
            from scrapling import Fetcher
            url = f"https://polymarket.com/event/{slug}"
            fetcher = Fetcher()
            resp = fetcher.get(url)
            # Simple heuristic to extract main text/rules
            return resp.text[:2000] # Return first 2k chars of text content
        except Exception as e:
            logger.warning(f"Scrapling failed for {slug}: {e}")
            return None


def _has_condition_id(data: dict) -> bool:
    return bool(data.get("conditionId") or data.get("condition_id"))


def _parse_clob_market(data: dict) -> Market:
    tokens_raw = data.get("tokens", [])
    if isinstance(tokens_raw, str):
        tokens_raw = json.loads(tokens_raw)
    tokens = [{"token_id": t.get("token_id", ""), "outcome": t.get("outcome", "")} for t in tokens_raw]

    def _to_bool(val: Any) -> bool:
        if isinstance(val, str):
            return val.lower() == "true"
        return bool(val)

    return Market(
        condition_id=data.get("condition_id", ""),
        slug=data.get("market_slug", ""),
        question=data.get("question", ""),
        description=data.get("description", ""),
        outcomes=[t.get("outcome", "") for t in tokens] or ["Yes", "No"],
        outcome_prices=[0.0, 0.0],
        tokens=tokens,
        active=_to_bool(data.get("active", True)),
        closed=_to_bool(data.get("closed", False)),
        end_date=data.get("end_date_iso", ""),
        tick_size=float(data.get("minimum_tick_size", 0.01) or 0.01),
    )


def _parse_market(data: dict) -> Market:
    outcomes_raw = data.get("outcomes", [])
    if isinstance(outcomes_raw, str):
        outcomes_raw = json.loads(outcomes_raw)
    outcomes = outcomes_raw if outcomes_raw else ["Yes", "No"]

    outcome_prices_raw = data.get("outcomePrices", data.get("outcome_prices", []))
    if isinstance(outcome_prices_raw, str):
        outcome_prices_raw = json.loads(outcome_prices_raw)
    outcome_prices = [float(p) for p in outcome_prices_raw] if outcome_prices_raw else [0.0, 0.0]

    tokens = []
    clob_token_ids_raw = data.get("clobTokenIds")
    tokens_raw = data.get("tokens")
    if clob_token_ids_raw:
        if isinstance(clob_token_ids_raw, str):
            clob_token_ids_raw = json.loads(clob_token_ids_raw)
        for i, token_id in enumerate(clob_token_ids_raw):
            outcome_name = outcomes[i] if i < len(outcomes) else f"Outcome{i}"
            tokens.append({"token_id": str(token_id), "outcome": outcome_name})
    elif tokens_raw:
        if isinstance(tokens_raw, str):
            tokens_raw = json.loads(tokens_raw)
        for t in tokens_raw:
            tokens.append({"token_id": t.get("token_id", ""), "outcome": t.get("outcome", "")})

    condition_id = data.get("conditionId", data.get("condition_id", ""))
    tick_size_raw = data.get("orderPriceMinTickSize", data.get("minimum_tick_size", 0.01))
    tick_size = float(tick_size_raw) if tick_size_raw else 0.01

    return Market(
        condition_id=condition_id,
        slug=data.get("slug", ""),
        question=data.get("question", ""),
        description=data.get("description", ""),
        outcomes=outcomes,
        outcome_prices=outcome_prices,
        tokens=tokens,
        active=bool(data.get("active", False)),
        closed=bool(data.get("closed", False)),
        volume=float(data.get("volume", 0) or 0),
        liquidity=float(data.get("liquidity", 0) or 0),
        end_date=data.get("endDateIso", data.get("end_date_iso", data.get("end_date", ""))),
        fee_rate_bps=int(data.get("fee_rate_bps", 0) or 0),
        tick_size=tick_size,
        tags=[t.get("label", t.get("slug", "")) for t in data.get("tags", []) if isinstance(t, dict)],
    )


def _parse_order_book(data: dict) -> OrderBook:
    bids = [OrderBookLevel(price=float(e.get("price", 0)), size=float(e.get("size", 0))) for e in data.get("bids", [])]
    asks = [OrderBookLevel(price=float(e.get("price", 0)), size=float(e.get("size", 0))) for e in data.get("asks", [])]
    return OrderBook(bids=bids, asks=asks)
