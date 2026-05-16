import logging
from dataclasses import dataclass
from typing import Optional, List

from utils.polymarket_client import PolymarketClient, Market

logger = logging.getLogger("MarketDataReader")


@dataclass
class MarketSnapshot:
    """Snapshot of a market at a point in time."""
    market_id: str
    slug: str
    question: str
    yes_price: float
    no_price: float
    spread: float
    volume: float
    liquidity: float
    is_active: bool
    is_closed: bool
    outcomes: list[str]
    end_date: str
    fee_rate_bps: int


@dataclass
class MarketOpportunity:
    """Trading opportunity identified in a market."""
    market_id: str
    slug: str
    opportunity_type: str  # "arbitrage", "mispricing", "high_spread"
    confidence: float  # 0.0-1.0
    spread: float
    description: str
    recommended_action: Optional[str] = None


class MarketDataReader:
    """Reads and analyzes Polymarket data."""

    def __init__(self, polymarket_client: Optional[PolymarketClient] = None):
        self.client = polymarket_client or PolymarketClient()
        self._market_cache: dict[str, MarketSnapshot] = {}

    def get_market_snapshot(self, market_id_or_slug: str) -> Optional[MarketSnapshot]:
        """Get current snapshot of a market."""
        try:
            market = self.client.get_market(market_id_or_slug)
            if not market:
                return None

            snapshot = MarketSnapshot(
                market_id=market.condition_id,
                slug=market.slug,
                question=market.question,
                yes_price=market.yes_price,
                no_price=market.no_price,
                spread=market.spread,
                volume=market.volume,
                liquidity=market.liquidity,
                is_active=market.active,
                is_closed=market.closed,
                outcomes=market.outcomes,
                end_date=market.end_date,
                fee_rate_bps=market.fee_rate_bps,
            )

            self._market_cache[market_id_or_slug] = snapshot
            return snapshot
        except Exception as e:
            logger.error(f"Failed to get market snapshot: {e}")
            return None

    def list_top_markets(self, limit: int = 10, sort_by: str = "volume") -> list[MarketSnapshot]:
        """Get top markets by volume or liquidity."""
        try:
            markets = self.client.list_markets(limit=limit, sort_by=sort_by)
            snapshots = []
            for market in markets:
                snapshot = MarketSnapshot(
                    market_id=market.condition_id,
                    slug=market.slug,
                    question=market.question,
                    yes_price=market.yes_price,
                    no_price=market.no_price,
                    spread=market.spread,
                    volume=market.volume,
                    liquidity=market.liquidity,
                    is_active=market.active,
                    is_closed=market.closed,
                    outcomes=market.outcomes,
                    end_date=market.end_date,
                    fee_rate_bps=market.fee_rate_bps,
                )
                snapshots.append(snapshot)
            return snapshots
        except Exception as e:
            logger.error(f"Failed to list markets: {e}")
            return []

    def search_markets(self, query: str, limit: int = 10) -> list[MarketSnapshot]:
        """Search for markets by query."""
        try:
            markets = self.client.search_markets(query, limit=limit)
            snapshots = []
            for market in markets:
                snapshot = MarketSnapshot(
                    market_id=market.condition_id,
                    slug=market.slug,
                    question=market.question,
                    yes_price=market.yes_price,
                    no_price=market.no_price,
                    spread=market.spread,
                    volume=market.volume,
                    liquidity=market.liquidity,
                    is_active=market.active,
                    is_closed=market.closed,
                    outcomes=market.outcomes,
                    end_date=market.end_date,
                    fee_rate_bps=market.fee_rate_bps,
                )
                snapshots.append(snapshot)
            return snapshots
        except Exception as e:
            logger.error(f"Failed to search markets: {e}")
            return []

    def get_markets_by_tag(self, tag: str, limit: int = 10) -> list[MarketSnapshot]:
        """Get markets by category tag."""
        try:
            markets = self.client.get_markets_by_tag(tag, limit=limit)
            snapshots = []
            for market in markets:
                snapshot = MarketSnapshot(
                    market_id=market.condition_id,
                    slug=market.slug,
                    question=market.question,
                    yes_price=market.yes_price,
                    no_price=market.no_price,
                    spread=market.spread,
                    volume=market.volume,
                    liquidity=market.liquidity,
                    is_active=market.active,
                    is_closed=market.closed,
                    outcomes=market.outcomes,
                    end_date=market.end_date,
                    fee_rate_bps=market.fee_rate_bps,
                )
                snapshots.append(snapshot)
            return snapshots
        except Exception as e:
            logger.error(f"Failed to get markets by tag: {e}")
            return []

    def identify_opportunities(self, markets: list[MarketSnapshot]) -> list[MarketOpportunity]:
        """Identify trading opportunities in markets."""
        opportunities = []

        for market in markets:
            # High spread opportunity
            if market.spread > 0.15:  # >15% spread
                opp = MarketOpportunity(
                    market_id=market.market_id,
                    slug=market.slug,
                    opportunity_type="high_spread",
                    confidence=0.6 + (market.spread - 0.15) * 2,  # Confidence increases with spread
                    spread=market.spread,
                    description=f"Wide spread: {market.spread:.2%}",
                    recommended_action=f"Consider arb: Buy ${market.no_price:.2f} YES, "
                                     f"Sell {market.yes_price:.2f} NO",
                )
                opportunities.append(opp)

            # Mispricing detection (extreme probabilities)
            if market.yes_price > 0.95 or market.no_price > 0.95:
                confident_outcome = "YES" if market.yes_price > 0.95 else "NO"
                opposite_price = market.no_price if market.yes_price > 0.95 else market.yes_price
                opp = MarketOpportunity(
                    market_id=market.market_id,
                    slug=market.slug,
                    opportunity_type="potential_resolution",
                    confidence=0.8,
                    spread=market.spread,
                    description=f"{confident_outcome} looks likely ({market.yes_price:.1%})",
                    recommended_action=f"Consider betting on {confident_outcome}",
                )
                opportunities.append(opp)

        return opportunities

    def format_market_snapshot(self, snapshot: MarketSnapshot) -> str:
        """Format market snapshot for display."""
        lines = [
            f"📈 **{snapshot.question[:100]}...**\n" if len(snapshot.question) > 100 else f"📈 **{snapshot.question}**\n",
            f"• YES: `${snapshot.yes_price:.2f}` | NO: `${snapshot.no_price:.2f}`",
            f"• Spread: `{snapshot.spread:.2%}`",
            f"• Volume: `${snapshot.volume:,.0f}`",
            f"• Liquidity: `${snapshot.liquidity:,.0f}`",
            f"• Fees: `{snapshot.fee_rate_bps} bps`",
        ]
        
        if snapshot.is_closed:
            lines.append("• Status: `CLOSED`")
        elif not snapshot.is_active:
            lines.append("• Status: `INACTIVE`")
        else:
            lines.append("• Status: `ACTIVE`")
        
        if snapshot.end_date:
            lines.append(f"• Ends: `{snapshot.end_date}`")
        
        return "\n".join(lines)

    def format_opportunity(self, opp: MarketOpportunity) -> str:
        """Format opportunity for display."""
        lines = [
            f"💡 **{opp.opportunity_type.upper()}**",
            f"• Market: `{opp.slug[:50]}...`" if len(opp.slug) > 50 else f"• Market: `{opp.slug}`",
            f"• Confidence: `{opp.confidence:.0%}`",
            f"• Spread: `{opp.spread:.2%}`",
            f"• Description: {opp.description}",
        ]
        
        if opp.recommended_action:
            lines.append(f"• Action: {opp.recommended_action}")
        
        return "\n".join(lines)

    def format_markets_list(self, markets: list[MarketSnapshot], limit: int = 5) -> str:
        """Format list of markets for display."""
        lines = [f"📊 **Top {min(len(markets), limit)} Markets**\n"]
        
        for i, market in enumerate(markets[:limit], 1):
            lines.append(f"{i}. [{market.slug[:40]}...](https://polymarket.com/event/{market.slug})")
            lines.append(f"   YES: `{market.yes_price:.2f}` | NO: `{market.no_price:.2f}` | Vol: `${market.volume:,.0f}`")
        
        return "\n".join(lines)

    def get_market_health_status(self, snapshot: MarketSnapshot) -> dict:
        """Analyze market health."""
        health = {
            "is_active": snapshot.is_active and not snapshot.is_closed,
            "has_volume": snapshot.volume > 0,
            "has_liquidity": snapshot.liquidity > 1000,  # >$1000
            "spread_reasonable": snapshot.spread < 0.20,  # <20%
            "fees_standard": snapshot.fee_rate_bps == 200,  # 2%
        }
        
        health["overall_health"] = sum(health.values()) / len(health)
        
        return health
