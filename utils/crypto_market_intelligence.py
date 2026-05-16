from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Iterable

from utils.polymarket_client import Market


DEFAULT_CRYPTO_KEYWORDS = {
    "BTC": ("btc", "bitcoin"),
    "ETH": ("eth", "ethereum", "ether"),
    "SOL": ("sol", "solana"),
    "XRP": ("xrp", "ripple"),
    "DOGE": ("doge", "dogecoin"),
    "CRYPTO": ("crypto", "cryptocurrency", "blockchain", "coinbase", "binance", "etf"),
}


@dataclass
class IntelligenceSignal:
    market_slug: str
    question: str
    asset: str
    signal_type: str
    direction: str
    score: float
    confidence: float
    yes_price: float
    no_price: float
    volume: float
    liquidity: float
    rationale: list[str] = field(default_factory=list)


@dataclass
class IntelligenceReport:
    generated_at: str
    source: str
    market_count: int
    crypto_market_count: int
    opportunities: list[IntelligenceSignal] = field(default_factory=list)
    risk_flags: list[IntelligenceSignal] = field(default_factory=list)
    watchlist: list[str] = field(default_factory=list)
    summary: dict[str, float | int | str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "generated_at": self.generated_at,
            "source": self.source,
            "market_count": self.market_count,
            "crypto_market_count": self.crypto_market_count,
            "opportunities": [asdict(signal) for signal in self.opportunities],
            "risk_flags": [asdict(signal) for signal in self.risk_flags],
            "watchlist": self.watchlist,
            "summary": self.summary,
        }


class CryptoMarketIntelligence:
    """
    Python adaptation of a market-intelligence platform for crypto prediction markets.

    It is advisory only: it ranks and explains crypto-related market situations, but
    does not execute trades. Execution remains behind parser, risk, ledger, and mode
    checks.
    """

    def __init__(
        self,
        watchlist: Iterable[str] = ("BTC", "ETH", "SOL"),
        min_volume: float = 10_000.0,
        min_liquidity: float = 1_000.0,
    ) -> None:
        self.watchlist = [item.upper() for item in watchlist]
        self.min_volume = min_volume
        self.min_liquidity = min_liquidity

    def analyze(self, markets: list[Market], source: str = "polymarket_gamma") -> IntelligenceReport:
        crypto_markets = [market for market in markets if self._classify_asset(market) != "OTHER"]
        signals = [self._score_market(market) for market in crypto_markets]
        signals = [signal for signal in signals if signal is not None]
        signals.sort(key=lambda signal: signal.score, reverse=True)

        opportunities = [
            signal for signal in signals
            if signal.signal_type in {"momentum", "mispricing", "liquidity_focus"}
        ][:10]
        risk_flags = [
            signal for signal in signals
            if signal.signal_type in {"thin_liquidity", "crowded_probability"}
        ][:10]

        avg_confidence = (
            sum(signal.confidence for signal in signals) / len(signals)
            if signals else 0.0
        )
        total_volume = sum(market.volume for market in crypto_markets)
        total_liquidity = sum(market.liquidity for market in crypto_markets)

        return IntelligenceReport(
            generated_at=datetime.now(timezone.utc).isoformat(),
            source=source,
            market_count=len(markets),
            crypto_market_count=len(crypto_markets),
            opportunities=opportunities,
            risk_flags=risk_flags,
            watchlist=self.watchlist,
            summary={
                "total_crypto_volume": round(total_volume, 2),
                "total_crypto_liquidity": round(total_liquidity, 2),
                "avg_signal_confidence": round(avg_confidence, 4),
                "opportunity_count": len(opportunities),
                "risk_flag_count": len(risk_flags),
            },
        )

    def _score_market(self, market: Market) -> IntelligenceSignal | None:
        asset = self._classify_asset(market)
        if asset == "OTHER":
            return None

        rationale: list[str] = []
        liquidity_score = self._bounded_log_score(market.liquidity, self.min_liquidity)
        volume_score = self._bounded_log_score(market.volume, self.min_volume)
        probability = market.yes_price
        conviction = abs(probability - 0.5) * 2
        spread = abs(market.yes_price - market.no_price)

        if market.volume >= self.min_volume:
            rationale.append(f"volume ${market.volume:,.0f} above crypto intelligence threshold")
        if market.liquidity >= self.min_liquidity:
            rationale.append(f"liquidity ${market.liquidity:,.0f} supports monitoring")
        if asset in self.watchlist:
            rationale.append(f"{asset} is in configured watchlist")

        if market.liquidity < self.min_liquidity:
            signal_type = "thin_liquidity"
            direction = "AVOID"
            score = 0.35 + volume_score * 0.25
            rationale.append("thin liquidity can distort quoted probabilities")
        elif conviction >= 0.8:
            signal_type = "crowded_probability"
            direction = "WATCH_REVERSAL"
            score = 0.45 + conviction * 0.35 + volume_score * 0.2
            rationale.append("probability is crowded near an extreme")
        elif 0.35 <= probability <= 0.65 and market.volume >= self.min_volume:
            signal_type = "liquidity_focus"
            direction = "MONITOR"
            score = 0.45 + liquidity_score * 0.3 + volume_score * 0.25
            rationale.append("balanced probability with tradable activity")
        elif spread > 0.15:
            signal_type = "mispricing"
            direction = "REVIEW_BOOK"
            score = 0.50 + min(spread, 0.5) * 0.5
            rationale.append(f"wide YES/NO spread {spread:.2f} suggests book review")
        else:
            signal_type = "momentum"
            direction = "BULLISH" if probability > 0.5 else "BEARISH"
            score = 0.4 + conviction * 0.3 + volume_score * 0.2 + liquidity_score * 0.1
            rationale.append("probability tilt plus market activity creates directional watch signal")

        confidence = min(max(score, 0.0), 0.99)
        return IntelligenceSignal(
            market_slug=market.slug,
            question=market.question,
            asset=asset,
            signal_type=signal_type,
            direction=direction,
            score=round(score, 4),
            confidence=round(confidence, 4),
            yes_price=round(market.yes_price, 4),
            no_price=round(market.no_price, 4),
            volume=round(market.volume, 2),
            liquidity=round(market.liquidity, 2),
            rationale=rationale[:5],
        )

    def _classify_asset(self, market: Market) -> str:
        text = " ".join([market.slug, market.question, market.description]).lower()
        for asset, keywords in DEFAULT_CRYPTO_KEYWORDS.items():
            if any(self._contains_keyword(text, keyword) for keyword in keywords):
                return asset
        return "OTHER"

    @staticmethod
    def _bounded_log_score(value: float, baseline: float) -> float:
        if value <= 0 or baseline <= 0:
            return 0.0
        return min(math.log1p(value) / math.log1p(baseline * 20), 1.0)

    @staticmethod
    def _contains_keyword(text: str, keyword: str) -> bool:
        escaped = re.escape(keyword.lower())
        return re.search(rf"(?<![a-z0-9]){escaped}(?![a-z0-9])", text) is not None


def format_intelligence_report(report: IntelligenceReport) -> str:
    data = report.to_dict()
    lines = [
        "*Crypto Market Intelligence*",
        f"Markets scanned: {data['market_count']} ({data['crypto_market_count']} crypto)",
        f"Volume: ${data['summary']['total_crypto_volume']:,.0f}",
        f"Liquidity: ${data['summary']['total_crypto_liquidity']:,.0f}",
        "",
    ]

    if report.opportunities:
        lines.append("*Opportunities / Watchlist*")
        for signal in report.opportunities[:5]:
            lines.append(
                f"- {signal.asset} {signal.direction} `{signal.market_slug}` "
                f"score={signal.score:.2f} yes={signal.yes_price:.2f}"
            )
    else:
        lines.append("*Opportunities / Watchlist*: none")

    if report.risk_flags:
        lines.extend(["", "*Risk Flags*"])
        for signal in report.risk_flags[:5]:
            lines.append(
                f"- {signal.asset} {signal.signal_type} `{signal.market_slug}` "
                f"confidence={signal.confidence:.2f}"
            )

    lines.extend([
        "",
        "Advisory only. Execution still requires parser, risk, ledger, and mode validation.",
    ])
    return "\n".join(lines)


def report_to_json(report: IntelligenceReport) -> str:
    return json.dumps(report.to_dict(), indent=2, ensure_ascii=True)
