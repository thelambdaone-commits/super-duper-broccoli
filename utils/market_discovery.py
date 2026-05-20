import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from utils.polymarket_client import PolymarketClient, Market

logger = logging.getLogger("MarketDiscovery")


@dataclass
class MarketScoring:
    market: Market
    score: float = 0.0
    liquidity_score: float = 0.0
    volume_score: float = 0.0
    edge_score: float = 0.0
    competition_score: float = 0.0
    sentiment_score: float = 0.0

    def to_dict(self) -> dict:
        return {
            "condition_id": self.market.condition_id,
            "slug": self.market.slug,
            "question": self.market.question[:80],
            "yes_price": self.market.yes_price,
            "no_price": self.market.no_price,
            "volume": self.market.volume,
            "liquidity": self.market.liquidity,
            "total_score": round(self.score, 2),
            "liquidity_score": round(self.liquidity_score, 2),
            "volume_score": round(self.volume_score, 2),
            "edge_score": round(self.edge_score, 0),
            "competition_score": round(self.competition_score, 2),
            "sentiment_score": round(self.sentiment_score, 2),
        }


class MarketDiscovery:
    MIN_VOLUME = 1000
    MIN_LIQUIDITY = 500
    IDEAL_PRICE_RANGE = (0.25, 0.75)
    MAX_DAYS_TO_RESOLUTION = 3.0

    def __init__(self, client: Optional[PolymarketClient] = None):
        self.client = client or PolymarketClient()

    @staticmethod
    def _days_to_resolution(market: Market) -> float | None:
        if not market.end_date:
            return None
        try:
            end_dt = datetime.fromisoformat(market.end_date.replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            return (end_dt - datetime.now(timezone.utc)).total_seconds() / 86400.0
        except Exception as e:
            logger.warning(f"Failed to parse end_date for {market.slug}: {e}")
            return None

    def _is_short_horizon(self, market: Market, max_days: float | None = None) -> bool:
        max_days = self.MAX_DAYS_TO_RESOLUTION if max_days is None else max_days
        days = self._days_to_resolution(market)
        return days is not None and 0.0 <= days <= max_days

    def _score_liquidity(self, market: Market) -> float:
        if market.liquidity < self.MIN_LIQUIDITY:
            return 0.0
        if market.liquidity >= 100000:
            return 100.0
        return min(100.0, (market.liquidity / 100000) * 100)

    def _score_volume(self, market: Market) -> float:
        if market.volume < self.MIN_VOLUME:
            return 0.0
        if market.volume >= 1000000:
            return 100.0
        return min(100.0, (market.volume / 1000000) * 100)

    def _score_edge_potential(self, market: Market) -> float:
        yes_price = market.yes_price
        no_price = market.no_price

        total = yes_price + no_price
        if total == 0:
            return 0.0

        spread = abs(1.0 - total)

        if spread > 0.10:
            return 80.0

        if yes_price == 0 or no_price == 0:
            return 20.0

        ideal_yes, ideal_no = 0.5, 0.5
        deviation = abs(yes_price - ideal_yes) + abs(no_price - ideal_no)

        if deviation < 0.1:
            return 60.0
        elif deviation < 0.3:
            return 100.0
        elif deviation < 0.5:
            return 70.0
        else:
            return 30.0

    def _score_competition(self, market: Market) -> float:
        yes_price = market.yes_price
        no_price = market.no_price

        if yes_price == 0 or no_price == 0:
            return 0.0

        min_price = min(yes_price, no_price)
        if min_price >= 0.90:
            return 20.0
        elif min_price >= 0.75:
            return 40.0
        elif min_price >= 0.50:
            return 100.0
        elif min_price >= 0.25:
            return 80.0
        else:
            return 50.0

    def _score_sentiment(self, market: Market) -> float:
        tags = [t.lower() for t in market.tags]

        positive_tags = ["crypto", "bitcoin", "ethereum", "solana", "bullish", "up"]
        negative_tags = ["dump", "crash", "bearish", "down", "risk"]

        positive_count = sum(1 for t in tags if any(pt in t for pt in positive_tags))
        negative_count = sum(1 for t in tags if any(nt in t for nt in negative_tags))

        if positive_count > negative_count:
            return 70.0
        elif negative_count > positive_count:
            return 40.0

        return 50.0

    def score_market(self, market: Market) -> MarketScoring:
        liquidity_score = self._score_liquidity(market)
        volume_score = self._score_volume(market)
        edge_score = self._score_edge_potential(market)
        competition_score = self._score_competition(market)
        sentiment_score = self._score_sentiment(market)

        weights = {
            "liquidity": 0.30,
            "volume": 0.25,
            "edge": 0.25,
            "competition": 0.15,
            "sentiment": 0.05,
        }

        total_score = (
            liquidity_score * weights["liquidity"] +
            volume_score * weights["volume"] +
            edge_score * weights["edge"] +
            competition_score * weights["competition"] +
            sentiment_score * weights["sentiment"]
        )

        return MarketScoring(
            market=market,
            score=total_score,
            liquidity_score=liquidity_score,
            volume_score=volume_score,
            edge_score=edge_score,
            competition_score=competition_score,
            sentiment_score=sentiment_score,
        )

    def discover_markets(
        self,
        limit: int = 20,
        min_score: float = 50.0,
        category: Optional[str] = None,
        max_days_to_resolution: float | None = None,
    ) -> list[MarketScoring]:
        search_limit = max(limit * 10, 100)
        if category:
            markets = self.client.get_markets_by_tag(category, limit=search_limit)
        else:
            markets = self.client.list_markets(limit=search_limit, sort_by="volume")

        scored_markets = []
        for market in markets:
            if not market.active or market.closed:
                continue
            if not self._is_short_horizon(market, max_days_to_resolution):
                continue

            scoring = self.score_market(market)
            scored_markets.append(scoring)

        scored_markets.sort(key=lambda x: x.score, reverse=True)
        strong_matches = [sm for sm in scored_markets if sm.score >= min_score]
        if len(strong_matches) >= limit:
            return strong_matches[:limit]

        seen = {sm.market.condition_id for sm in strong_matches}
        fallback_matches = [sm for sm in scored_markets if sm.market.condition_id not in seen]
        combined = strong_matches + fallback_matches
        return combined[:limit]

    def find_betting_opportunities(
        self,
        min_edge_percent: float = 5.0,
        min_volume: float = 500,
        limit: int = 10,
        max_days_to_resolution: float | None = None,
    ) -> list[dict]:

        markets = self.client.list_markets(limit=200, sort_by="volume")
        candidates = []

        for market in markets:
            if not market.active or market.closed:
                continue
            if market.volume < min_volume:
                continue
            if not self._is_short_horizon(market, max_days_to_resolution):
                continue

            yes_price = market.yes_price
            no_price = market.no_price

            total = yes_price + no_price
            if total == 0:
                continue

            pricing_edge = abs(yes_price - no_price) * 100
            mispricing = abs(1.0 - total) * 100
            side_bias = "YES" if yes_price < no_price else "NO"
            signal_strength = max(pricing_edge, mispricing)

            entry = {
                "condition_id": market.condition_id,
                "slug": market.slug,
                "question": market.question,
                "yes_price": yes_price,
                "no_price": no_price,
                "spread_percent": round(pricing_edge, 2),
                "mispricing_percent": round(mispricing, 2),
                "signal_strength": round(signal_strength, 2),
                "volume": market.volume,
                "liquidity": market.liquidity,
                "recommended_side": side_bias,
                "edge": round(abs(yes_price - no_price), 4),
                "end_date": market.end_date,
                "days_to_resolution": round(self._days_to_resolution(market) or 0.0, 2),
            }
            candidates.append(entry)

        candidates.sort(
            key=lambda x: (
                x["signal_strength"] >= min_edge_percent,
                x["signal_strength"],
                x["volume"],
            ),
            reverse=True,
        )

        selected = candidates[:limit]
        if not selected:
            return []

        strong = [item for item in selected if item["signal_strength"] >= min_edge_percent]
        weak = [item for item in selected if item["signal_strength"] < min_edge_percent]
        return strong + weak

    def get_top_crypto_markets(self, limit: int = 10) -> list[MarketScoring]:
        return self.discover_markets(
            limit=limit,
            min_score=40.0,
            category="crypto",
        )

    def get_top_political_markets(self, limit: int = 10) -> list[MarketScoring]:
        return self.discover_markets(
            limit=limit,
            min_score=40.0,
            category="politics",
        )

    def get_contrarian_opportunities(self, limit: int = 10) -> list[dict]:

        markets = self.client.list_markets(limit=100, sort_by="volume")
        contrarian = []

        for market in markets:
            if not market.active or market.closed:
                continue
            if market.volume < 5000:
                continue
            if not self._is_short_horizon(market):
                continue

            yes_price = market.yes_price

            if yes_price >= 0.80:
                contrarian.append({
                    "condition_id": market.condition_id,
                    "slug": market.slug,
                    "question": market.question,
                    "current_odds": f"YES at {yes_price:.1%}",
                    "contrarian_bet": "NO",
                    "reason": "Market too bullish, potential overvaluation",
                    "volume": market.volume,
                    "end_date": market.end_date,
                    "days_to_resolution": round(self._days_to_resolution(market) or 0.0, 2),
                })
            elif yes_price <= 0.20:
                contrarian.append({
                    "condition_id": market.condition_id,
                    "slug": market.slug,
                    "question": market.question,
                    "current_odds": f"YES at {yes_price:.1%}",
                    "contrarian_bet": "YES",
                    "reason": "Market too bearish, potential undervaluation",
                    "volume": market.volume,
                    "end_date": market.end_date,
                    "days_to_resolution": round(self._days_to_resolution(market) or 0.0, 2),
                })

        contrarian.sort(key=lambda x: x["volume"], reverse=True)
        return contrarian[:limit]

    def get_market_details(self, slug_or_id: str) -> Optional[dict]:
        market = self.client.get_market(slug_or_id)
        if not market:
            return None

        scoring = self.score_market(market)
        return scoring.to_dict()


def format_market_discovery(scored_markets: list[MarketScoring]) -> str:
    if not scored_markets:
        return "❌ No markets found matching criteria."

    lines = [
        "📊 *MARKET DISCOVERY REPORT* 📊",
        "────────────────────────",
    ]

    for i, sm in enumerate(scored_markets[:10], 1):
        m = sm.market

        emoji = "🟢" if m.yes_price >= 0.50 else "🔴"

        lines.append(
            f"{i}. {emoji} `{m.question[:50]}...`\n"
            f"   💰 Vol: `${m.volume:,.0f}` | Liq: `${m.liquidity:,.0f}`\n"
            f"   📈 Yes: `{m.yes_price:.1%}` | No: `{m.no_price:.1%}`\n"
            f"   ⭐ Score: `{sm.score:.0f}/100`"
        )

    lines.append("────────────────────────")
    lines.append(f"Showing top {len(scored_markets[:10])} markets by scoring")

    return "\n".join(lines)


def format_betting_opportunities(opportunities: list[dict]) -> str:
    if not opportunities:
        return "❌ No betting opportunities found."

    lines = [
        "🎯 *BETTING OPPORTUNITIES* 🎯",
        "────────────────────────",
    ]

    for i, opp in enumerate(opportunities[:10], 1):
        mispricing = opp.get("mispricing_percent", opp.get("spread_percent", 0.0))
        lines.append(
            f"{i}. *{opp['question'][:50]}...*\n"
            f"   Side: `{opp['recommended_side']}` @ "
            f"{opp.get('yes_price', 0):.1%} / {opp.get('no_price', 0):.1%}\n"
            f"   Edge: `{opp['spread_percent']:.1f}%` | Mispricing: `{mispricing:.1f}%` | Vol: `${opp['volume']:,.0f}`"
        )

    lines.append("────────────────────────")
    lines.append(f"Found {len(opportunities)} opportunities")

    return "\n".join(lines)
