from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from utils.crypto_market_intelligence import CryptoMarketIntelligence
from utils.polymarket_client import Market, PolymarketClient


ASSET_ALIASES = {
    "BTC": ("btc", "bitcoin"),
    "ETH": ("eth", "ethereum", "ether"),
    "SOL": ("sol", "solana"),
    "XRP": ("xrp", "ripple"),
    "HYPE": ("hype", "hyperliquid"),
    "DOGE": ("doge", "dogecoin"),
    "BNB": ("bnb", "binance coin"),
    "ADA": ("ada", "cardano"),
    "AVAX": ("avax", "avalanche"),
    "LINK": ("link", "chainlink"),
    "SUI": ("sui", "sui network"),
    "PEPE": ("pepe", "pepecoin"),
    "WIF": ("wif", "dogwifhat"),
    "TON": ("ton", "toncoin", "the open network"),
    "NEAR": ("near", "near protocol"),
}

HORIZON_ALIASES = {
    "5": ("5m", "5 min", "5 minute", "5-minute", "5 minutes"),
    "15": ("15m", "15 min", "15 minute", "15-minute", "15 minutes"),
    "1h": ("1h", "1 hour", "1-hour", "60 min", "60-minute"),
    "4h": ("4h", "4 hour", "4-hour", "240 min"),
    "1d": ("1d", "1 day", "1-day", "daily", "tomorrow"),
}


@dataclass(frozen=True)
class HorizonSentiment:
    asset: str
    horizon: str
    sentiment: str
    probability: float
    market_slug: str
    question: str
    yes_price: float
    no_price: float
    volume: float
    rationale: str
    time_remaining: str = ""


class CryptoHorizonSentiment:
    def __init__(self, client: PolymarketClient | None = None) -> None:
        self.client = client or PolymarketClient()
        self._classifier = CryptoMarketIntelligence()

    def analyze(self, asset: str, horizon: str, limit: int = 150) -> HorizonSentiment | None:
        asset = asset.upper().strip()
        horizon = normalize_horizon(horizon)
        if asset not in ASSET_ALIASES or horizon not in HORIZON_ALIASES:
            return None

        import logging
        logger = logging.getLogger("CryptoHorizonSentiment")

        markets = self.client.list_markets(limit=limit, sort_by="volume")
        direct = self._analyze_direct(asset, horizon, markets)
        if direct:
            return direct

        # Fallback: Try to build a composite proxy sentiment from high-cap assets
        logger.info("Direct market for %s not found. Constructing Correlation Composite Proxy Sentiment...", asset)
        proxies = []
        for proxy_asset in ("BTC", "ETH", "SOL"):
            if proxy_asset != asset:
                p_sent = self._analyze_direct(proxy_asset, horizon, markets)
                if p_sent:
                    proxies.append(p_sent)

        if not proxies:
            return None

        bullish_probs = [p.yes_price for p in proxies]
        total_volume = sum(p.volume for p in proxies)
        avg_bullish = sum(bullish_probs) / len(bullish_probs)

        if avg_bullish >= 0.62:
            sentiment = "BULLISH"
            probability = avg_bullish
        elif avg_bullish <= 0.38:
            sentiment = "BEARISH"
            probability = 1.0 - avg_bullish
        else:
            sentiment = "NEUTRAL"
            probability = max(avg_bullish, 1.0 - avg_bullish)

        return HorizonSentiment(
            asset=asset,
            horizon=horizon,
            sentiment=sentiment,
            probability=round(probability, 4),
            market_slug="composite-proxy-btc-eth-sol",
            question="Correlation Composite Proxy Sentiment (BTC/ETH/SOL)",
            yes_price=round(avg_bullish, 4),
            no_price=round(1.0 - avg_bullish, 4),
            volume=total_volume,
            rationale="Correlation composite hedge (BTC/ETH/SOL)",
        )

    def _analyze_direct(self, asset: str, horizon: str, markets: list[Market]) -> HorizonSentiment | None:
        candidates = [
            market for market in markets
            if self._classifier._classify_asset(market) == asset
        ]
        if not candidates:
            return None

        exact = [market for market in candidates if self._matches_horizon(market, horizon)]
        pool = exact or candidates
        best = sorted(
            pool,
            key=lambda market: (
                self._score_market_fit(market, asset, horizon, exact_match=market in exact),
                market.volume,
                market.liquidity,
            ),
            reverse=True,
        )[0]
        return self._build_sentiment(best, asset, horizon, exact_match=best in exact)

    def _build_sentiment(
        self,
        market: Market,
        asset: str,
        horizon: str,
        exact_match: bool,
    ) -> HorizonSentiment:
        yes = 0.0
        no = 0.0
        try:
            yes = float(market.yes_price)
            no = float(market.no_price)
        except (ValueError, TypeError):
            pass

        if yes == 0.0 and no == 0.0:
            try:
                yes_token = market.yes_token_id
                if yes_token:
                    mid = self.client.get_midpoint(yes_token)
                    if mid > 0.0:
                        yes = mid
                        no = 1.0 - mid
            except Exception:
                pass

        yes = max(0.0, min(1.0, yes))
        no = max(0.0, min(1.0, no))
        bullish_probability = yes
        bearish_probability = no

        question = market.question.lower()
        if any(term in question for term in ("dip", "below", "under")):
            bullish_probability = no
            bearish_probability = yes

        if bullish_probability >= 0.62:
            sentiment = "BULLISH"
            probability = bullish_probability
        elif bearish_probability >= 0.62:
            sentiment = "BEARISH"
            probability = bearish_probability
        else:
            sentiment = "NEUTRAL"
            probability = max(bullish_probability, bearish_probability)

        if exact_match:
            rationale = "marche horizon exact"
        else:
            rationale = "fallback meilleur marche crypto liquide"

        time_rem = "N/A"
        if market.end_date:
            try:
                end = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
                if end.tzinfo is None:
                    end = end.replace(tzinfo=timezone.utc)
                diff = end - datetime.now(timezone.utc)
                total_sec = diff.total_seconds()
                if total_sec <= 0:
                    time_rem = "Closed"
                else:
                    days = int(total_sec // 86400)
                    hours = int((total_sec % 86400) // 3600)
                    mins = int((total_sec % 3600) // 60)
                    if days > 0:
                        time_rem = f"{days}d {hours}h"
                    elif hours > 0:
                        time_rem = f"{hours}h {mins}m"
                    else:
                        time_rem = f"{mins}m"
            except Exception:
                pass

        return HorizonSentiment(
            asset=asset,
            horizon=horizon,
            sentiment=sentiment,
            probability=round(probability, 4),
            market_slug=market.slug,
            question=market.question,
            yes_price=yes,
            no_price=no,
            volume=float(market.volume),
            rationale=rationale,
            time_remaining=time_rem,
        )

    def _matches_horizon(self, market: Market, horizon: str) -> bool:
        text = f"{market.slug} {market.question} {market.description}".lower()
        if any(alias in text for alias in HORIZON_ALIASES[horizon]):
            return True
        if horizon == "15" and "updown-15m" in text:
            return True
        if horizon == "5" and "updown-5m" in text:
            return True
        return self._end_date_matches(market, horizon)

    def _end_date_matches(self, market: Market, horizon: str) -> bool:
        if not market.end_date:
            return False
        try:
            end = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
        except ValueError:
            return False
        if end.tzinfo is None:
            end = end.replace(tzinfo=timezone.utc)
        minutes = (end - datetime.now(timezone.utc)).total_seconds() / 60.0
        windows = {
            "5": (0, 8),
            "15": (8, 22),
            "1h": (22, 90),
            "4h": (90, 300),
            "1d": (300, 1800),
        }
        low, high = windows[horizon]
        return low <= minutes <= high

    def _score_market_fit(self, market: Market, asset: str, horizon: str, exact_match: bool) -> float:
        score = 10.0 if exact_match else 0.0
        text = f"{market.slug} {market.question}".lower()
        score += sum(2.0 for alias in ASSET_ALIASES[asset] if self._contains_keyword(text, alias))
        if "updown" in text or "up-or-down" in text or "above" in text or "below" in text:
            score += 2.0
        if market.active and not market.closed:
            score += 1.0
        return score

    @staticmethod
    def _contains_keyword(text: str, keyword: str) -> bool:
        escaped = re.escape(keyword.lower())
        return re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text) is not None


def normalize_horizon(raw: str) -> str:
    value = raw.lower().strip()
    if value in {"5", "5m", "m5"}:
        return "5"
    if value in {"15", "15m", "m15"}:
        return "15"
    if value in {"1", "1h", "h1", "60", "60m"}:
        return "1h"
    if value in {"4", "4h", "h4"}:
        return "4h"
    if value in {"1d", "d1", "24", "24h"}:
        return "1d"
    return value


def format_horizon_sentiment(sentiment: HorizonSentiment | None, asset: str, horizon: str) -> str:
    horizon = normalize_horizon(horizon)
    if sentiment is None:
        return (
            f"🔍 {asset.upper()} ({horizon}): aucun marché crypto fiable trouvé.\n"
            "Essaie /markets crypto ou attends le prochain scan Polymarket."
        )

    header_emoji = {"BULLISH": "📈", "BEARISH": "📉", "NEUTRAL": "⚖️"}.get(sentiment.sentiment, "💎")
    direction_arrow = {"BULLISH": "UP 🟢", "BEARISH": "DOWN 🔴", "NEUTRAL": "FLAT 🟡"}.get(sentiment.sentiment, sentiment.sentiment)

    is_proxy = (sentiment.market_slug == "composite-proxy-btc-eth-sol")
    proxy_suffix = " [PROXY HEDGE 🌐]" if is_proxy else ""

    pct = sentiment.probability * 100.0
    bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))

    lines = [
        f"{header_emoji} LOBSTAR CRYPTO SENTIMENT — {sentiment.asset} ({sentiment.horizon})\n",
        f"  • Sentiment: {sentiment.sentiment} ({direction_arrow}){proxy_suffix}",
        f"    {bar} {pct:.1f}% | YES ${sentiment.yes_price:.3f} vs NO ${sentiment.no_price:.3f}\n",
        f"  • Market Details:",
        f"    Volume: ${sentiment.volume:,.0f}",
    ]
    if sentiment.time_remaining and sentiment.time_remaining != "N/A":
        lines.append(f"    Time Left: {sentiment.time_remaining}")
    lines.extend([
        f"    Base: {sentiment.rationale}",
        f"    Slug: {sentiment.market_slug}\n",
        "  ⚠️ Avis consultatif. Pas d'exécution sans parser, risque, ledger et mode valide."
    ])
    return "\n".join(lines)
