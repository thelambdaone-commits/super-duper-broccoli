from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from utils.crypto_market_intelligence import CryptoMarketIntelligence, DEFAULT_CRYPTO_KEYWORDS
from utils.polymarket_client import Market, PolymarketClient

logger = logging.getLogger("MarketScanner")

SCAN_INTERVAL_SECONDS = 300
TOP_MARKETS_LIMIT = 100
MIN_VOLUME_USD = 1_000
CRYPTO_TAGS = {"cryptocurrency", "btc", "bitcoin", "eth", "ethereum", "sol", "solana", "crypto", "cryptocurrencies", "altcoin", "altcoins"}
BULLISH_KEYWORDS = {"bullish", "moon", "pump", "buy", "long", "accumulate", "bull", "bull trap", "bull run", "bull market", "bullish reversal", "bullish momentum", "bullish trend", "bullish pattern", "bullish breakout", "bullish divergence", "bull flag", "bullish engulfing", "bullish hammer", "bullish pennant", "bullish wedge", "bullish channel", "bullish triangle", "bullish flag", "bullish pattern", "bullish setup", "bullish signal", "bullish alert", "bullish call", "bullish recommendation", "bullish advice", "bullish prediction", "bullish forecast", "bullish outlook", "bullish sentiment", "bullish bias", "bullish stance", "bullish position", "bullish exposure", "bullish allocation", "bullish investment", "bullish trade", "bullish position", "bullish holding", "bullish long", "bullish buy", "bullish accumulation", "bullish entry", "bullish exit", "bullish stop", "bullish limit", "bullish take profit", "bullish stop loss", "bullish risk", "bullish reward", "bullish ratio", "bullish risk reward", "bullish risk/reward", "bullish rr", "bullish payoff", "bullish expectancy", "bullish edge", "bullish advantage", "bullish opportunity", "bullish setup", "bullish signal", "bullish alert", "bullish call", "bullish recommendation", "bullish advice", "bullish prediction", "bullish forecast", "bullish outlook", "bullish sentiment", "bullish bias", "bullish stance", "bullish position", "bullish exposure", "bullish allocation", "bullish investment", "bullish trade", "bullish position", "bullish holding", "bullish long", "bullish buy", "bullish accumulation", "bullish entry", "bullish exit", "bullish stop", "bullish limit", "bullish take profit", "bullish stop loss", "bullish risk", "bullish reward", "bullish ratio", "bullish risk reward", "bullish risk/reward", "bullish rr", "bullish payoff", "bullish expectancy", "bullish edge", "bullish advantage", "bullish opportunity"}
BEARISH_KEYWORDS = {"bearish", "dump", "sell", "short", "bear", "bear trap", "bear market", "bearish reversal", "bearish momentum", "bearish trend", "bearish pattern", "bearish breakout", "bearish divergence", "bearish flag", "bearish engulfing", "bearish hammer", "bearish pennant", "bearish wedge", "bearish channel", "bearish triangle", "bearish flag", "bearish pattern", "bearish setup", "bearish signal", "bearish alert", "bearish call", "bearish recommendation", "bearish advice", "bearish prediction", "bearish forecast", "bearish outlook", "bearish sentiment", "bearish bias", "bearish stance", "bearish position", "bearish exposure", "bearish allocation", "bearish investment", "bearish trade", "bearish position", "bearish holding", "bearish short", "bearish sell", "bearish accumulation", "bearish entry", "bearish exit", "bearish stop", "bearish limit", "bearish take profit", "bearish stop loss", "bearish risk", "bearish reward", "bearish ratio", "bearish risk reward", "bearish risk/reward", "bearish rr", "bearish payoff", "bearish expectancy", "bearish edge", "bearish advantage", "bearish opportunity", "bearish setup", "bearish signal", "bearish alert", "bearish call", "bearish recommendation", "bearish advice", "bearish prediction", "bearish forecast", "bearish outlook", "bearish sentiment", "bearish bias", "bearish stance", "bearish position", "bearish exposure", "bearish allocation", "bearish investment", "bearish trade", "bearish position", "bearish holding", "bearish short", "bearish sell", "bearish accumulation", "bearish entry", "bearish exit", "bearish stop", "bearish limit", "bearish take profit", "bearish stop loss", "bearish risk", "bearish reward", "bearish ratio", "bearish risk reward", "bearish risk/reward", "bearish rr", "bearish payoff", "bearish expectancy", "bearish edge", "bearish advantage", "bearish opportunity"}

SCAN_INTERVAL_SECONDS = 300
TOP_MARKETS_LIMIT = 30
MIN_VOLUME_USD = 10_000


@dataclass
class MarketSignal:
    ticker: str
    side: str  # BUY or SELL
    price: float
    confidence: float
    reason: str
    market_question: str
    market_slug: str
    current_prob: float
    volume: float
    sentiment: str  # BULLISH or BEARISH
    direction: str  # 📈 UP or 📉 DOWN
    fee_rate_bps: int = 0


@dataclass
class ScanResult:
    timestamp: str
    winning_bets: list[MarketSignal] = field(default_factory=list)
    trending_markets: list[MarketSignal] = field(default_factory=list)
    competitive_markets: list[MarketSignal] = field(default_factory=list)
    arbitrage_opportunities: list[MarketSignal] = field(default_factory=list)
    total_markets_scanned: int = 0
    aggregate_sentiment: dict = field(default_factory=lambda: {"sentiment": "NEUTRAL", "bullish_pct": 50})


class MarketScanner:
    def __init__(self, client: Optional[PolymarketClient] = None) -> None:
        self.client = client or PolymarketClient()
        self._last_scan: Optional[ScanResult] = None
        self._known_markets: dict[str, float] = {}
        self._sentiment_cache: dict[str, str] = {}

    def close(self) -> None:
        self.client.close()

    def _extract_sentiment(self, question: str, description: str) -> str:
        text = (question + " " + (description or "")).lower()
        bullish = any(kw in text for kw in BULLISH_KEYWORDS)
        bearish = any(kw in text for kw in BEARISH_KEYWORDS)
        if bullish and not bearish:
            return "BULLISH"
        if bearish and not bullish:
            return "BEARISH"
        return "NEUTRAL"

    def _get_sentiment(self, market: Market) -> str:
        cache_key = market.slug
        if cache_key in self._sentiment_cache:
            return self._sentiment_cache[cache_key]
        sentiment = self._extract_sentiment(market.question, market.description)
        self._sentiment_cache[cache_key] = sentiment
        return sentiment

    def _is_crypto_market(self, market: Market) -> bool:
        text = (market.slug + " " + market.question + " " + (market.description or "")).lower()
        crypto_keywords = {
            keyword
            for keywords in DEFAULT_CRYPTO_KEYWORDS.values()
            for keyword in keywords
        } | {
            "xmr", "monero", "pepe", "shib", "nft", "defi", "dex", "usdc",
            "usdt", "polygon", "matic", "staking", "airdrop", "satoshi",
        }

        if any(CryptoMarketIntelligence._contains_keyword(text, keyword) for keyword in crypto_keywords):
            return True

        market_tags = [t.lower() for t in market.tags]
        if any(t in CRYPTO_TAGS or t in {"defi", "nft", "web3"} for t in market_tags):
            return True

        return False

    def scan_markets(self) -> ScanResult:
        result = ScanResult(
            timestamp=datetime.now(timezone.utc).isoformat()
        )

        try:
            markets = self.client.list_markets(limit=TOP_MARKETS_LIMIT, sort_by="volume")
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            return result

        result.total_markets_scanned = len(markets)

        for market in markets:
            if market.volume < MIN_VOLUME_USD:
                continue
            if not self._is_crypto_market(market):
                continue

            slug = market.slug
            prev_prob = self._known_markets.get(slug)

            # Check for winning bets (imminent resolution)
            winning = market.winning_outcome
            if winning:
                confidence = min(0.85 + market.probability_pct / 1000, 0.99)
                price = market.yes_price if winning == "YES" else market.no_price
                sentiment = self._get_sentiment(market)
                direction = "📈 UP" if winning == "YES" else "📉 DOWN"
                result.winning_bets.append(MarketSignal(
                    ticker=slug,
                    side="BUY" if winning == "YES" else "SELL",
                    price=round(price, 4),
                    confidence=round(confidence, 4),
                    reason=f"Imminent resolution: {winning} at {market.probability_pct:.0f}%",
                    market_question=market.question,
                    market_slug=slug,
                    current_prob=round(market.probability_pct, 1),
                    volume=market.volume,
                    sentiment=sentiment,
                    direction=direction,
                    fee_rate_bps=getattr(market, "fee_rate_bps", 0),
                ))

            # Check for trending markets (sharp moves)
            if prev_prob is not None:
                prob_change = abs(market.probability_pct - prev_prob)
                if prob_change >= 15 and market.volume >= 50000:
                    direction = "📈 UP" if market.yes_price > prev_prob / 100 else "📉 DOWN"
                    sentiment = self._get_sentiment(market)
                    result.trending_markets.append(MarketSignal(
                        ticker=slug,
                        side="BUY" if direction == "📈 UP" else "SELL",
                        price=round(market.yes_price, 4),
                        confidence=round(0.5 + prob_change / 100, 4),
                        reason=f"Sharp move: {prob_change:.0f}% change in probability",
                        market_question=market.question,
                        market_slug=slug,
                        current_prob=round(market.probability_pct, 1),
                        volume=market.volume,
                        sentiment=sentiment,
                        direction=direction,
                        fee_rate_bps=getattr(market, "fee_rate_bps", 0),
                    ))

            # Check for competitive markets (tight spreads)
            if market.is_competitive and market.volume >= 25000:
                spread_pct = market.spread * 100
                sentiment = self._get_sentiment(market)
                direction = "📈 UP" if market.yes_price <= 0.5 else "📉 DOWN"
                result.competitive_markets.append(MarketSignal(
                    ticker=slug,
                    side="BUY" if direction == "📈 UP" else "SELL",
                    price=round(market.yes_price, 4),
                    confidence=round(0.5 + (50 - spread_pct) / 100, 4),
                    reason=f"Competitive market: spread {spread_pct:.1f}%, vol ${market.volume:,.0f}",
                    market_question=market.question,
                    market_slug=slug,
                    current_prob=round(market.probability_pct, 1),
                    volume=market.volume,
                    sentiment=sentiment,
                    direction=direction,
                    fee_rate_bps=getattr(market, "fee_rate_bps", 0),
                ))

            # Check for arbitrage opportunities (surebets)
            if market.outcomes and len(market.outcomes) == 2:
                yes_price = market.yes_price
                no_price = market.no_price
                if yes_price > 0 and no_price > 0:
                    # Check for arbitrage: sum of inverse prices < 1
                    arb = (1 / yes_price) + (1 / no_price)
                    if arb < 1.0:
                        result.arbitrage_opportunities.append(MarketSignal(
                            ticker=slug,
                            side="BUY" if yes_price < no_price else "SELL",
                            price=round(min(yes_price, no_price), 4),
                            confidence=0.99,
                            reason=f"Arbitrage opportunity: {arb:.4f} < 1.0",
                            market_question=market.question,
                            market_slug=slug,
                            current_prob=round(market.probability_pct, 1),
                            volume=market.volume,
                            sentiment="ARBITRAGE",
                            direction="📈 UP" if yes_price < no_price else "📉 DOWN",
                            fee_rate_bps=getattr(market, "fee_rate_bps", 0),
                        ))

            self._known_markets[slug] = market.probability_pct

        self._last_scan = result
        result.aggregate_sentiment = self.get_aggregate_sentiment()
        return result

    def record_features(self, store: FeatureStore):
        """Records current market state into the FeatureStore for training."""
        if not self._last_scan or not self._last_scan.total_markets_scanned:
            return

        # We focus on top crypto markets for training features
        markets = self.client.list_markets(limit=20, sort_by="volume")
        for market in markets:
            if not self._is_crypto_market(market):
                continue
                
            slug = market.slug
            # Record base price/probability
            store.record_feature(slug, "mid_price", market.yes_price)
            store.record_feature(slug, "volume", market.volume)
            
            # Record order book features if available
            outcome_prices = getattr(market, "outcome_prices", None)
            if outcome_prices:
                # Approximate spread from YES/NO prices if book is not fetched
                spread = abs(market.yes_price - (1 - market.no_price))
                store.record_feature(slug, "spread_bps", spread * 10000)
                
            # Open Interest (if available from Gamma/CLOB)
            # Using liquidity as a proxy for depth/OI if specific OI is not in Market object
            store.record_feature(slug, "oi_5min", market.liquidity)
            
            # Sentiment
            sentiment_val = 1.0 if self._get_sentiment(market) == "BULLISH" else (-1.0 if self._get_sentiment(market) == "BEARISH" else 0.0)
            store.record_feature(slug, "tam_state", sentiment_val)
            
        logger.info(f"Recorded features for {len(markets)} markets in FeatureStore.")

    def get_aggregate_sentiment(self) -> dict[str, Any]:
        """Calculate aggregate sentiment across all scanned crypto markets."""
        from typing import Any
        if not self._last_scan or not self._last_scan.total_markets_scanned:
            return {"sentiment": "NEUTRAL", "bullish_pct": 50, "total": 0}
        
        all_signals = (
            self._last_scan.winning_bets + 
            self._last_scan.trending_markets + 
            self._last_scan.competitive_markets
        )
        
        if not all_signals:
            return {"sentiment": "NEUTRAL", "bullish_pct": 50, "total": 0}
            
        bullish_count = sum(1 for s in all_signals if s.sentiment == "BULLISH")
        total = len(all_signals)
        bullish_pct = (bullish_count / total) * 100
        
        sentiment = "NEUTRAL"
        if bullish_pct > 60: sentiment = "BULLISH"
        elif bullish_pct < 40: sentiment = "BEARISH"
        
        return {
            "sentiment": sentiment,
            "bullish_pct": round(bullish_pct, 1),
            "total": total
        }

    @property
    def top_winning_bets(self) -> list[MarketSignal]:
        if not self._last_scan:
            return []
        return sorted(self._last_scan.winning_bets, key=lambda s: -s.confidence)[:5]

    @property
    def top_trending(self) -> list[MarketSignal]:
        if not self._last_scan:
            return []
        return sorted(self._last_scan.trending_markets, key=lambda s: -abs(s.current_prob - 50))[:5]

    @property
    def top_competitive(self) -> list[MarketSignal]:
        if not self._last_scan:
            return []
        return sorted(self._last_scan.competitive_markets, key=lambda s: -s.volume)[:5]

    @property
    def top_arbitrage(self) -> list[MarketSignal]:
        if not self._last_scan:
            return []
        return sorted(self._last_scan.arbitrage_opportunities, key=lambda s: -s.confidence)[:3]

    def resolve_ticker_to_token_id(self, ticker: str, side: str = "YES") -> Optional[str]:
        """Resolves a slug or ticker (like BTC) to a Polymarket token ID."""
        # 1. Try direct slug match
        market = self.client.get_market(ticker)
        if market:
            try:
                # Map BUY/SELL to YES/NO
                outcome = "YES" if side.upper() in ("BUY", "YES", "LONG") else "NO"
                return market.get_token_id(outcome)
            except ValueError:
                pass
        
        # 2. Try search if it looks like a generic asset (BTC, ETH, SOL)
        if ticker.upper() in ["BTC", "ETH", "SOL", "BITCOIN", "ETHEREUM", "SOLANA"]:
            markets = self.client.search_markets(ticker, limit=5)
            # Find the most liquid/active one
            valid_markets = [m for m in markets if m.active and not m.closed]
            if valid_markets:
                best_market = sorted(valid_markets, key=lambda m: -m.volume)[0]
                try:
                    outcome = "YES" if side.upper() in ("BUY", "YES", "LONG") else "NO"
                    return best_market.get_token_id(outcome)
                except ValueError:
                    pass
                    
        return None




def _fmt_signal(s: MarketSignal) -> str:
    fees_str = f" | Fees: {s.fee_rate_bps} bps" if getattr(s, "fee_rate_bps", 0) > 0 else ""
    return (
        f"\U0001f3c6 *{s.reason}*"
        f"\n\U0001f4c8 {s.market_question[:80]}"
        f"\n\U0001f4b0 Vol: ${s.volume:,.0f} | Prob: {s.current_prob:.0f}%{fees_str}"
        f"\n\U0001f4c8 Signal: `{s.side} @ {s.price}` (conf: {s.confidence:.0%})"
        f"\n\U0001f4a1 Sentiment: {s.sentiment} | Direction: {s.direction}"
    )
